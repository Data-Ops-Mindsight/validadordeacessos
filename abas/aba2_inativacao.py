"""
Aba 2 - Inativar acessos de colaboradores DESLIGADOS.

Fluxo da aba:
  1. O usuário informa tenant e token do Controle e faz upload da base do Auth (.csv).
  2. Ao clicar em "Processar Inativações", a ferramenta:
       - busca no Controle os funcionários e os seus registros (vínculos);
       - considera desligado quem tem TODOS os registros encerrados (com data de fim)
         ou quem não tem nenhum registro;
       - procura na base do Auth os usuários desses desligados que ainda estão ATIVOS.
  3. Gera o CSV de upload que inativa esses usuários no Auth
     (is_active = 0, sem acessos e sem grupos).
"""

import streamlit as st
import pandas as pd
import time

# Como o arquivo é executado a partir do app.py (na raiz), importamos diretamente
from functions import *

# Valores que o Auth usa para indicar "usuário ativo"
VALORES_ATIVO = [1, True, '1', 'True', 1.0]


def render_aba2():
    st.header("Inativar Acessos - Colaboradores Desligados")

    # -------------------------------------------------------------------------
    # SEÇÃO 1: CREDENCIAIS
    # -------------------------------------------------------------------------
    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2, _ = st.columns(3)
    tenant_t2 = c1.text_input("Tenant do Cliente", key="tenant_t2", placeholder="Ex: empresa123")
    token_controle_t2 = c2.text_input("Token do Controle", key="token_controle_t2")

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # SEÇÃO 2: BASE DO AUTH E PROCESSAMENTO
    # -------------------------------------------------------------------------
    st.markdown("### 📁 Base de Usuários (Auth)")
    arquivo_auth_t2 = st.file_uploader("Faça o upload da base exportada do Auth (.csv)", type=['csv'], key="arquivo_auth_t2")

    if st.button("Processar Inativações", key="btn_t2"):
        if not tenant_t2 or not token_controle_t2 or not arquivo_auth_t2:
            st.error("Preencha o Tenant, o Token do Controle e faça o upload da base.")
        else:
            bar = st.progress(0, text="Lendo os dados...")
            try:
                # --- Leitura da base do Auth enviada pelo usuário ---
                df_auth = ler_csv_seguro(arquivo_auth_t2)
                colunas_faltando = [c for c in ['id', 'username', 'email', 'first_name', 'last_name', 'is_active'] if c not in df_auth.columns]
                if colunas_faltando:
                    raise ValueError(f"a base do Auth não possui as colunas: {', '.join(colunas_faltando)}.")

                # Remove usuários internos da Mindsight da base do Auth
                df_auth = df_auth.loc[~df_auth['username'].astype(str).str.contains('mindsight', na=False, case=False)].copy()
                df_auth['username'] = df_auth['username'].astype(str).str.strip()

                # --- Consultas às APIs do Controle (cada uma com mensagem de erro clara) ---
                bar.progress(30, text="Obtendo Funcionários do Controle...")
                func_ctrl = chamar_api("os funcionários do Controle",
                                       get_controle_employees_api, tenant_t2, token_controle_t2)
                validar_retorno_api(func_ctrl, "os funcionários do Controle", ['employee_code'])
                user_col = 'user.username' if 'user.username' in func_ctrl.columns else 'username'
                if user_col not in func_ctrl.columns:
                    func_ctrl[user_col] = ''

                bar.progress(60, text="Verificando registros (vínculos)...")
                reg_ctrl = chamar_api("os registros (vínculos) dos funcionários do Controle",
                                      get_controle_employee_records_api, tenant_t2, token_controle_t2)
                validar_retorno_api(reg_ctrl, "os registros (vínculos) dos funcionários do Controle",
                                    ['employee_code', 'end'])

                # Remove funcionários internos da Mindsight do Controle
                func_ctrl = func_ctrl[~(func_ctrl['employee_code'].astype(str).str.contains('@mindsight', case=False, na=False)
                                        | func_ctrl[user_col].astype(str).str.contains('@mindsight', case=False, na=False))].copy()

                # Padroniza códigos e usernames como texto sem espaços, para as comparações baterem
                func_ctrl['employee_code'] = func_ctrl['employee_code'].astype(str).str.strip()
                func_ctrl[user_col] = func_ctrl[user_col].fillna('').astype(str).str.strip()
                reg_ctrl['employee_code'] = reg_ctrl['employee_code'].astype(str).str.strip()

                # Converte a data de fim; textos vazios ou inválidos viram "sem data" (registro em aberto)
                reg_ctrl['end'] = pd.to_datetime(reg_ctrl['end'], errors='coerce')

                # --- Quem está desligado? ---
                # a) Todos os registros do funcionário têm data de fim (nenhum vínculo em aberto)
                status_por_func = reg_ctrl.groupby('employee_code')['end'].apply(lambda x: x.isna().sum() == 0)
                codigos_encerrados = status_por_func[status_por_func].index.tolist()
                # b) Funcionário cadastrado sem nenhum registro
                codigos_sem_registro = list(set(func_ctrl['employee_code'].unique()) - set(reg_ctrl['employee_code'].unique()))
                codigos_desligados = set(codigos_encerrados + codigos_sem_registro)

                usernames_desl = set(func_ctrl.loc[func_ctrl['employee_code'].isin(codigos_desligados), user_col])
                # Proteção para recontratados: se o mesmo username também pertence a um
                # funcionário ATIVO (outro employee_code), ele não deve ser inativado.
                usernames_ativos = set(func_ctrl.loc[~func_ctrl['employee_code'].isin(codigos_desligados), user_col])
                usernames_desl = usernames_desl - usernames_ativos - {''}

                # --- Usuários do Auth que são de desligados e ainda estão ativos ---
                bar.progress(90, text="Gerando relatório...")
                df_desl_ativos = df_auth[df_auth['username'].isin(usernames_desl)
                                         & df_auth['is_active'].isin(VALORES_ATIVO)].copy()

                st.session_state.t2_tenant = tenant_t2
                if df_desl_ativos.empty:
                    st.session_state.t2_empty = True
                    st.session_state.t2_df = pd.DataFrame()
                    st.session_state.t2_msg = "🎉 Validação concluída! Todos os desligados já estão inativados!"
                else:
                    st.session_state.t2_empty = False
                    st.session_state.t2_msg = f"Foram encontrados **{len(df_desl_ativos)}** usuários de colaboradores desligados ainda ATIVOS."

                    # Monta o arquivo no layout de upload do Auth, já inativando o usuário
                    df_f = pd.DataFrame()
                    for col in ['id', 'first_name', 'last_name', 'email']:
                        df_f[col] = df_desl_ativos[col]
                    df_f['username'] = df_desl_ativos['username']
                    df_f['login_AD'] = 0
                    df_f['access_to_systems'] = ''   # remove todos os acessos
                    df_f['groups'] = ''              # remove todos os grupos
                    df_f['is_superuser'] = 0
                    df_f['is_staff'] = 0
                    df_f['is_active'] = 0            # inativa o usuário
                    st.session_state.t2_df = df_f[['login_AD', 'access_to_systems', 'id', 'is_superuser', 'groups',
                                                   'first_name', 'last_name', 'is_staff', 'is_active', 'username', 'email']]

                st.session_state.t2_processed = True
                bar.progress(100, text="Concluído!")
                time.sleep(1)
                bar.empty()

            except ErroAPI as e:
                # Falha em alguma API: mostra a mensagem clara e descarta resultados antigos
                bar.empty()
                st.session_state.t2_processed = False
                st.error(f"❌ Falha na comunicação com a API. {e}")
            except Exception as e:
                bar.empty()
                st.session_state.t2_processed = False
                st.error(f"Ocorreu um erro: {e}")

    # -------------------------------------------------------------------------
    # RESULTADO E DOWNLOAD
    # -------------------------------------------------------------------------
    if st.session_state.t2_processed:
        if st.session_state.t2_empty:
            st.success(st.session_state.t2_msg)
        else:
            st.warning(st.session_state.t2_msg)
            with st.expander("👁️ Ver lista de usuários que serão inativados"):
                st.dataframe(st.session_state.t2_df[['username', 'email', 'first_name', 'last_name']], use_container_width=True)
            st.download_button("📥 Baixar Inativação (CSV)",
                               data=st.session_state.t2_df.to_csv(index=False, sep=',', encoding='utf-8-sig'),
                               file_name=f"{st.session_state.t2_tenant}_inativar_acessos.csv",
                               mime="text/csv", key="down3")
