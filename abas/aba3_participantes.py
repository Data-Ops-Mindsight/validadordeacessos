"""
Aba 3 - Validação dos PARTICIPANTES de uma rodada do Performance.

Fluxo da aba:
  1. O usuário informa tenant, tokens do Performance e do Controle, o ID da
     rodada e faz upload da base do Auth (.csv).
  2. Ao clicar em "Processar Validação da Rodada", a ferramenta:
       - busca os participantes da rodada no Performance;
       - cruza com a base do Auth (acessos e status) e com o Controle (ativo/desligado);
  3. Mostra e gera arquivos com:
       - a correção do Auth (ativar usuário e/ou adicionar 'performance');
       - os participantes que não existem no Auth;
       - os participantes que estão desligados no Controle.
"""

import streamlit as st
import pandas as pd
import numpy as np
import time

# Como o arquivo é executado a partir do app.py (na raiz), importamos diretamente
from functions import *

MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render_aba3():
    st.header("Validação de Participantes (Rodada)")

    # Explicação da regra e do que os arquivos gerados fazem
    st.info(
        "💡 **O que esta aba valida?** Todos os **participantes da rodada** informada no Performance "
        "precisam estar **ativos no Auth** e ter o módulo **performance**.\n\n"
        "🚫 **Funcionários da Mindsight são desconsiderados** nesta validação.\n\n"
        "📄 **O que é gerado:**\n"
        "- **Correção do Auth (CSV):** para os participantes que estão inativos no Auth ou sem o módulo "
        "performance, reativa o usuário (`1` na coluna `is_active`) e adiciona `performance` na coluna "
        "`access_to_systems`, mantendo os demais acessos;\n"
        "- **Não encontrados no Auth (Excel):** participantes da rodada que não existem na base do Auth enviada;\n"
        "- **Desligados no Controle (Excel):** participantes cujo registro de funcionário mais recente no "
        "Controle tem data de demissão. Eles **não** entram na correção, para avaliar se devem sair da rodada."
    )

    # -------------------------------------------------------------------------
    # SEÇÃO 1: CREDENCIAIS E RODADA
    # -------------------------------------------------------------------------
    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2, c3 = st.columns(3)
    tenant_t3 = c1.text_input("Tenant do Cliente", key="tenant_t3", placeholder="Ex: empresa123")
    token_perf_t3 = c2.text_input("Token do Performance", key="token_perf_t3")
    token_controle_t3 = c3.text_input("Token do Controle", key="token_controle_t3")

    c4, _, _ = st.columns(3)
    rodada_t3 = c4.text_input("ID da Rodada", key="rodada_t3", placeholder="Ex: 42",
                              help="ID numérico da rodada (evaluation round) no Performance.")

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # SEÇÃO 2: BASE DO AUTH E PROCESSAMENTO
    # -------------------------------------------------------------------------
    st.markdown("### 📁 Base de Usuários (Auth)")
    arquivo_auth_t3 = st.file_uploader("Faça o upload da base exportada do Auth (.csv)", type=['csv'], key="arquivo_auth_t3")

    if st.button("Processar Validação da Rodada", key="btn_t3"):
        rodada_t3 = str(rodada_t3).strip()
        if not tenant_t3 or not token_perf_t3 or not token_controle_t3 or not rodada_t3 or not arquivo_auth_t3:
            st.error("Preencha o Tenant, os tokens do Performance e do Controle, o ID da Rodada e faça o upload da base.")
        else:
            bar = st.progress(0, text="Obtendo rodadas...")
            try:
                # --- Nome da rodada (só para exibição; se falhar, usa o próprio ID) ---
                nome_rodada = rodada_t3
                try:
                    df_rounds = ler_perfomance_evaluation_rounds(tenant_t3, token_perf_t3)
                    if not df_rounds.empty and {'id', 'name'}.issubset(df_rounds.columns):
                        match = df_rounds[df_rounds['id'].astype(str) == rodada_t3]
                        if not match.empty:
                            nome_rodada = match['name'].iloc[0]
                except Exception:
                    pass

                # --- Participantes da rodada no Performance ---
                bar.progress(20, text=f"Obtendo participantes da rodada '{nome_rodada}'...")
                df_perf = chamar_api(f"os participantes da rodada {rodada_t3} no Performance",
                                     ler_usuarios_performance, tenant_t3, token_perf_t3, rodada_t3)
                if df_perf.empty:
                    raise ErroAPI(f"Nenhum participante foi encontrado na rodada '{nome_rodada}'. "
                                  "Confira se o ID da Rodada, o tenant e o token do Performance estão corretos.")
                validar_retorno_api(df_perf, "os participantes da rodada no Performance", ['username'])
                if 'name' not in df_perf.columns:
                    df_perf['name'] = df_perf['username']

                # Remove participantes internos da Mindsight
                df_perf['username'] = df_perf['username'].astype(str).str.strip()
                mascara_mindsight = df_perf['username'].str.contains('@mindsight', case=False, na=False)
                qtd_mindsight = int(mascara_mindsight.sum())
                df_perf = df_perf[~mascara_mindsight].copy()

                # --- Leitura da base do Auth enviada pelo usuário ---
                bar.progress(40, text="Processando a base do Auth...")
                df_auth = ler_csv_seguro(arquivo_auth_t3)
                colunas_auth = ['username', 'id', 'email', 'first_name', 'last_name', 'is_active', 'access_to_systems', 'is_superuser']
                colunas_faltando = [c for c in colunas_auth if c not in df_auth.columns]
                if colunas_faltando:
                    raise ValueError(f"a base do Auth não possui as colunas: {', '.join(colunas_faltando)}.")
                df_auth_limpo = df_auth.loc[~df_auth['username'].astype(str).str.contains('mindsight', na=False, case=False)].copy()
                df_auth_limpo['username'] = df_auth_limpo['username'].astype(str).str.strip()

                # --- Situação de cada funcionário no Controle ---
                bar.progress(60, text="Obtendo Funcionários do Controle...")
                func_ctrl = chamar_api("os funcionários do Controle",
                                       get_controle_employees_api, tenant_t3, token_controle_t3)
                validar_retorno_api(func_ctrl, "os funcionários do Controle", ['employee_code'])
                user_col = 'user.username' if 'user.username' in func_ctrl.columns else 'username'
                if user_col not in func_ctrl.columns:
                    func_ctrl[user_col] = ''

                reg_ctrl = chamar_api("os registros (vínculos) dos funcionários do Controle",
                                      get_controle_employee_records_api, tenant_t3, token_controle_t3)
                validar_retorno_api(reg_ctrl, "os registros (vínculos) dos funcionários do Controle",
                                    ['employee_code', 'start', 'end'])
                reg_ctrl['start'] = pd.to_datetime(reg_ctrl['start'], errors='coerce')
                reg_ctrl['end'] = pd.to_datetime(reg_ctrl['end'], errors='coerce')
                # Ordena para que o registro "em aberto" (end vazio) ou o mais recente fique por último
                reg_ctrl = reg_ctrl.sort_values(by=['employee_code', 'end', 'start'], ascending=[True, True, True], na_position='last')

                df_status = reg_ctrl.drop_duplicates(subset='employee_code', keep='last').copy()
                df_status['situacao_controle'] = np.where(df_status['end'].isna(), 'Ativo', 'Desligado')

                mapa_usr = func_ctrl.set_index('employee_code')[user_col].to_dict()
                df_status['user.username'] = df_status['employee_code'].map(mapa_usr).fillna('').astype(str).str.strip()
                # Um username pode ter mais de um código (ex.: recontratado). Fica um por username,
                # dando preferência ao vínculo Ativo, para não duplicar participantes.
                df_status = (df_status[df_status['user.username'] != '']
                             .sort_values('situacao_controle')          # 'Ativo' vem antes de 'Desligado'
                             .drop_duplicates(subset='user.username', keep='first'))

                # --- Cruzamento: participantes x Auth x Controle ---
                bar.progress(80, text="Analisando resultados...")
                df_val = df_perf[['username', 'name']].drop_duplicates(subset='username').merge(
                    df_auth_limpo[colunas_auth], on='username', how='left', indicator=True)
                df_val = df_val.merge(df_status[['user.username', 'situacao_controle', 'end']],
                                      left_on='username', right_on='user.username', how='left')

                # Desligados no Controle: só listados, não entram na correção
                st.session_state.t3_df_desligados = df_val[df_val['situacao_controle'] == 'Desligado'].copy()

                # Demais participantes: aplica a regra de performance
                df_ativos = df_val[df_val['situacao_controle'] != 'Desligado'].copy()
                if df_ativos.empty:
                    df_ativos = df_ativos.assign(acessos_novos='', precisa_ajuste=False, motivo='')
                else:
                    df_ativos[['acessos_novos', 'precisa_ajuste', 'motivo']] = df_ativos.apply(formatar_acesso_performance, axis=1)

                # Guarda os resultados na memória da sessão para os downloads
                st.session_state.t3_len_total = len(df_perf)
                st.session_state.t3_qtd_mindsight = qtd_mindsight
                st.session_state.t3_tenant = tenant_t3
                st.session_state.t3_nome_rodada = str(nome_rodada)
                st.session_state.t3_df_fix = df_ativos[df_ativos['precisa_ajuste'] == True].copy()
                st.session_state.t3_df_not_found = df_ativos[df_ativos['_merge'] == 'left_only'].copy()
                st.session_state.t3_processed = True

                bar.progress(100, text="Concluído!")
                time.sleep(1)
                bar.empty()

            except ErroAPI as e:
                # Falha em alguma API: mostra a mensagem clara e descarta resultados antigos
                bar.empty()
                st.session_state.t3_processed = False
                st.error(f"❌ Falha na comunicação com a API. {e}")
            except Exception as e:
                bar.empty()
                st.session_state.t3_processed = False
                st.error(f"Ocorreu um erro: {e}")

    # -------------------------------------------------------------------------
    # RESULTADOS E DOWNLOADS
    # -------------------------------------------------------------------------
    if st.session_state.t3_processed:
        tenant = st.session_state.t3_tenant
        st.success(f"✅ Rodada '{st.session_state.t3_nome_rodada}': {st.session_state.t3_len_total} participantes "
                   f"(ignorando {st.session_state.t3_qtd_mindsight} da Mindsight).")

        # Participantes que não existem no Auth
        if not st.session_state.t3_df_not_found.empty:
            st.error(f"⚠️ **{len(st.session_state.t3_df_not_found)}** participantes da rodada NÃO existem na base do Auth!")
            df_nf = st.session_state.t3_df_not_found[['name', 'username', 'motivo']].copy()
            df_nf.columns = ['Nome do participante', 'Usuário', 'Motivo']
            with st.expander("👁️ Ver participantes não encontrados"):
                st.dataframe(df_nf, use_container_width=True)
            st.download_button("📥 Baixar Não Encontrados (Excel)", data=gerar_excel(df_nf),
                               file_name=f"{tenant}_nao_encontrados_auth.xlsx", mime=MIME_EXCEL, key="down4")

        # Correção do Auth (ativar e/ou adicionar performance)
        if not st.session_state.t3_df_fix.empty:
            df_final_3 = montar_df_upload(st.session_state.t3_df_fix, 'acessos_novos', incluir_motivo=True)
            st.write("### Ajustes Necessários (Adicionar Performance / Ativar)")
            motivos = df_final_3['motivo_ajuste'].value_counts().reset_index()
            motivos.columns = ['Motivo', 'Quantidade']
            st.markdown(motivos.to_html(index=False), unsafe_allow_html=True)
            st.write("<br>", unsafe_allow_html=True)
            with st.expander("👁️ Ver lista de usuários impactados e seus ajustes"):
                st.dataframe(df_final_3[['username', 'email', 'first_name', 'last_name', 'motivo_ajuste']], use_container_width=True)
            st.download_button("📥 Baixar Correção Auth (CSV)",
                               data=df_final_3.to_csv(index=False, sep=',', encoding='utf-8-sig'),
                               file_name=f"{tenant}_correcao_performance.csv", mime="text/csv", key="down5")
        else:
            st.info("Nenhum ajuste necessário no Auth.")

        # Participantes desligados no Controle
        if not st.session_state.t3_df_desligados.empty:
            st.error(f"🚨 Participantes DESLIGADOS no Controle: {len(st.session_state.t3_df_desligados)}")
            df_show = st.session_state.t3_df_desligados[['name', 'username', 'end']].copy()
            df_show.columns = ['Nome do funcionário', 'Usuário', 'Data de Desligamento']
            df_show['Data de Desligamento'] = pd.to_datetime(df_show['Data de Desligamento']).dt.strftime('%d/%m/%Y')
            with st.expander("👁️ Ver participantes desligados"):
                st.dataframe(df_show, use_container_width=True)
            st.download_button("📥 Baixar Lista de Desligados (Excel)", data=gerar_excel(df_show),
                               file_name=f"{tenant}_participantes_desligados.xlsx", mime=MIME_EXCEL, key="down6")
