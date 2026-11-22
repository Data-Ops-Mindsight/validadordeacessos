"""
Aba 4 - Validação de USUÁRIOS entre os módulos.

Cruza os usuários do Auth (CSV enviado) com os usuários de cada módulo:
  - Controle e People Hub (Full): lidos pela API, com token;
  - Performance e Metas: CSVs exportados das telas de admin pelo favorito
    "Exportar dados do Django" (ferramentas/bookmarklet_exportar_usuarios.txt).

Validações geradas (cada uma com um Excel para baixar):
  1. Presença: em quais módulos cada usuário do Auth existe (pelo username);
  2. Possíveis duplicados: mesmo nome completo com mais de um username ou email;
  3. Divergência de username: mesmo email com username diferente entre Auth e módulo;
  4. Divergência de email: mesmo username com email diferente entre Auth e módulo;
  5. UUIDs: compara o UUID do Auth com o de cada módulo (pelo username).
"""

import streamlit as st
import pandas as pd
import numpy as np
import time

# Como o arquivo é executado a partir do app.py (na raiz), importamos diretamente
from functions import *
from abas.exportacao_admin import ler_csv_modulo, render_instrucoes_exportacao

MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MODULOS = ['Controle', 'Full', 'Performance', 'Metas']
VAZIOS = ['nan', 'none', '', '-']

def _limpar_base(df):
    """Remove usuários da Mindsight e padroniza username/email (minúsculo, sem espaços)."""
    if df is None or df.empty or 'username' not in df.columns:
        return pd.DataFrame() if df is None else df
    df = df.loc[~df['username'].astype(str).str.contains('mindsight', case=False, na=False)].copy()
    for c in ['username', 'email']:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip().str.lower()
    return df


def _valido(valor):
    return str(valor).strip().lower() not in VAZIOS


def render_aba4():
    st.header("Validação de Usuários entre Módulos")

    # Explicação do que a aba faz
    st.info(
        "💡 **O que esta aba faz?** Compara os usuários do **Auth** (base enviada) com os usuários do "
        "**Controle**, **People Hub (Full)**, **Performance** e **Metas**. Todos os usuários do Auth são "
        "considerados, **inclusive os inativos**.\n\n"
        "📥 Os usuários do **Performance** e do **Metas** precisam ser enviados em CSV, gerados com o favorito "
        "**Exportar dados do Django** (veja o passo a passo em *Como gerar os CSVs do Performance e do Metas*).\n\n"
        "🚫 **Usuários da Mindsight são desconsiderados** nesta validação.\n\n"
        "📄 **Validações geradas:**\n"
        "1. **Presença nos módulos:** em quais módulos cada usuário do Auth existe e em quais está faltando, e "
        "quais usuários existem em algum módulo mas **não existem no Auth**;\n"
        "2. **Possíveis duplicados:** nomes completos com mais de um username ou email (pode ser homônimo, "
        "mas também um funcionário cadastrado duas vezes);\n"
        "3. **Divergência de username:** mesmo email com username diferente entre o Auth e o módulo;\n"
        "4. **Divergência de email:** mesmo username com email diferente entre o Auth e o módulo;\n"
        "5. **Conferência de UUIDs:** o UUID do Auth comparado com o de cada módulo (exige a coluna `uuid` na base do Auth)."
    )

    # -------------------------------------------------------------------------
    # SEÇÃO 1: CREDENCIAIS
    # -------------------------------------------------------------------------
    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2, c3 = st.columns(3)
    tenant_t4 = c1.text_input("Tenant do Cliente", key="tenant_t4", placeholder="Ex: empresa123")
    token_controle_t4 = c2.text_input("Token do Controle", key="token_controle_t4")
    token_full_t4 = c3.text_input("Token do Full", key="token_full_t4")

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # SEÇÃO 2: BASES (AUTH, PERFORMANCE E METAS) E PROCESSAMENTO
    # -------------------------------------------------------------------------
    st.markdown("### 📁 Bases de Usuários")

    # Passo a passo para gerar os CSVs do Performance e do Metas (compartilhado com a Aba 1)
    render_instrucoes_exportacao(
        "Envie nos campos abaixo a **base do Auth**, o **CSV do Performance** e o **CSV do Metas**, "
        "preencha o tenant e os tokens e clique em **Processar Validações de Módulos**."
    )

    c4, c5, c6 = st.columns(3)
    arquivo_auth_t4 = c4.file_uploader("Base do Auth (.csv)", type=['csv'], key="arquivo_auth_t4")
    arquivo_perf_t4 = c5.file_uploader("Usuários do Performance (.csv)", type=['csv'], key="arquivo_perf_t4",
                                       help="Arquivo performance_<tenant>_usuarios.csv gerado pelo favorito.")
    arquivo_metas_t4 = c6.file_uploader("Usuários do Metas (.csv)", type=['csv'], key="arquivo_metas_t4",
                                        help="Arquivo metas_<tenant>_usuarios.csv gerado pelo favorito.")

    if st.button("Processar Validações de Módulos", key="btn_t4"):
        if not tenant_t4 or not token_controle_t4 or not token_full_t4:
            st.error("Preencha o Tenant e os tokens do Controle e do Full.")
        elif not arquivo_auth_t4 or not arquivo_perf_t4 or not arquivo_metas_t4:
            st.error("Envie os três arquivos: base do Auth, usuários do Performance e usuários do Metas.")
        else:
            bar = st.progress(0, text="Iniciando...")
            try:
                # --- 1/5: base do Auth ---
                bar.progress(10, text="1/5 - Lendo a base do Auth...")
                df_auth = ler_csv_seguro(arquivo_auth_t4)
                colunas_faltando = [c for c in ['username', 'email', 'first_name', 'last_name'] if c not in df_auth.columns]
                if colunas_faltando:
                    raise ValueError(f"a base do Auth não possui as colunas: {', '.join(colunas_faltando)}.")
                df_auth = _limpar_base(df_auth)

                # --- 2/5: Controle (API) ---
                bar.progress(25, text="2/5 - Obtendo usuários do Controle...")
                df_controle = _limpar_base(chamar_api("os usuários do Controle",
                                                      ler_usuarios_controle, tenant_t4, token_controle_t4))

                # --- 3/5: People Hub (API) ---
                bar.progress(45, text="3/5 - Obtendo usuários do People Hub...")
                df_full = _limpar_base(chamar_api("os usuários do People Hub (Full)",
                                                  ler_usuarios_full, tenant_t4, token_full_t4))

                # --- 4/5: Performance (CSV exportado pelo favorito) ---
                bar.progress(65, text="4/5 - Lendo usuários do Performance...")
                df_perf = _limpar_base(ler_csv_modulo(arquivo_perf_t4, "Performance", "performance_"))

                # --- 5/5: Metas (CSV exportado pelo favorito) ---
                bar.progress(80, text="5/5 - Lendo usuários do Metas...")
                df_metas = _limpar_base(ler_csv_modulo(arquivo_metas_t4, "Metas", "metas_"))

                bases = {'Controle': df_controle, 'Full': df_full, 'Performance': df_perf, 'Metas': df_metas}
                bar.progress(92, text="Cruzando dados...")

                # --- Validação 1: presença de cada usuário do Auth nos módulos ---
                df_val1 = df_auth[['username', 'email', 'first_name', 'last_name']].copy()
                if 'is_active' in df_auth.columns:
                    df_val1['Ativo no Auth'] = np.where(df_auth['is_active'].isin([1, True, '1', 'True', 1.0]), 'Sim', 'Não')
                for nome, base in bases.items():
                    if base.empty or 'username' not in base.columns:
                        df_val1[nome] = 'Base Vazia'
                    else:
                        df_val1[nome] = np.where(df_val1['username'].isin(base['username']), 'Sim', 'Não')
                df_val1['Modulos_Ausentes'] = df_val1.apply(
                    lambda r: ", ".join([m for m in MODULOS if r[m] == 'Não']) or "Nenhum", axis=1)

                # --- Validação 1 (parte 2): usuários que existem em algum módulo, mas não no Auth ---
                usernames_auth = set(df_auth['username'])
                registros_fora = []
                for nome, base in bases.items():
                    if base.empty or 'username' not in base.columns:
                        continue
                    # reindex garante as colunas mesmo se o módulo não tiver alguma delas
                    fora = base.reindex(columns=['username', 'email', 'first_name', 'last_name'])
                    fora = fora.loc[~fora['username'].isin(usernames_auth) & fora['username'].apply(_valido)].copy()
                    fora['Modulo'] = nome
                    registros_fora.append(fora)
                df_fora_auth = pd.DataFrame()
                if registros_fora:
                    df_f = pd.concat(registros_fora, ignore_index=True)
                    # Um registro por username: dados do primeiro módulo em que aparece + lista de módulos
                    df_fora_auth = df_f.groupby('username', as_index=False).agg(
                        email=('email', 'first'),
                        first_name=('first_name', 'first'),
                        last_name=('last_name', 'first'),
                        Modulos_Onde_Existe=('Modulo', lambda x: ", ".join(sorted(set(x)))),
                    )

                # --- Validação 2: possíveis duplicados (mesmo nome, vários usernames/emails) ---
                todos = []
                for nome, base in {'Auth': df_auth, **bases}.items():
                    if not base.empty and {'username', 'email', 'first_name', 'last_name'}.issubset(base.columns):
                        t = base[['username', 'email', 'first_name', 'last_name']].copy()
                        t['Modulo'] = nome
                        todos.append(t)
                df_val2 = pd.DataFrame()
                if todos:
                    df_t = pd.concat(todos, ignore_index=True)
                    df_t['nome'] = (df_t['first_name'].astype(str).str.strip() + " "
                                    + df_t['last_name'].astype(str).str.strip()).str.strip().str.lower()
                    df_t = df_t[df_t['nome'] != ""]
                    agg = df_t.groupby('nome').agg({
                        'username': lambda x: ", ".join(sorted(set(str(i) for i in x if _valido(i)))),
                        'email': lambda x: ", ".join(sorted(set(str(i) for i in x if _valido(i)))),
                        'Modulo': lambda x: ", ".join(sorted(set(str(i) for i in x))),
                    }).reset_index()
                    df_val2 = agg[agg['username'].str.contains(',') | agg['email'].str.contains(',')].copy()
                    df_val2.columns = ['Nome Completo', 'Usernames Associados', 'E-mails Associados', 'Módulos']

                # --- Validação 3: mesmo email com username diferente (Auth x módulo) ---
                div_list = []
                da = df_auth[df_auth['email'].apply(_valido)].copy()
                da['n'] = da['first_name'].astype(str) + " " + da['last_name'].astype(str)
                for nome, base in bases.items():
                    if base.empty or 'email' not in base.columns:
                        continue
                    db = base[base['email'].apply(_valido)].copy()
                    db['n2'] = (db['first_name'].astype(str) + " " + db['last_name'].astype(str)) if 'first_name' in db.columns else 'N/A'
                    m = da[['email', 'username', 'n']].merge(db[['email', 'username', 'n2']], on='email', suffixes=('_auth', '_mod'))
                    diff = m[m['username_auth'] != m['username_mod']].copy()
                    if not diff.empty:
                        diff['Modulo_Divergente'] = nome
                        diff = diff.rename(columns={'email': 'Email', 'username_auth': 'Username_Auth', 'username_mod': 'Username_Modulo',
                                                    'n': 'Nome_Auth', 'n2': 'Nome_Modulo'})
                        div_list.append(diff[['Email', 'Username_Auth', 'Username_Modulo', 'Nome_Auth', 'Nome_Modulo', 'Modulo_Divergente']])
                df_val3 = pd.concat(div_list, ignore_index=True) if div_list else pd.DataFrame()

                # --- Validação 4: mesmo username com email diferente (Auth x módulo) ---
                email_list = []
                da_email = df_auth[['username', 'email']].copy()
                for nome, base in bases.items():
                    if base.empty or 'email' not in base.columns:
                        continue
                    db = base[['username', 'email']].drop_duplicates('username')
                    m = da_email.merge(db, on='username', suffixes=('_auth', '_mod'))
                    # Só compara quando os dois lados têm email preenchido
                    m = m[m['email_auth'].apply(_valido) & m['email_mod'].apply(_valido)]
                    diff = m[m['email_auth'] != m['email_mod']].copy()
                    if not diff.empty:
                        diff['Modulo_Divergente'] = nome
                        diff = diff.rename(columns={'username': 'Username', 'email_auth': 'Email_Auth', 'email_mod': 'Email_Modulo'})
                        email_list.append(diff[['Username', 'Email_Auth', 'Email_Modulo', 'Modulo_Divergente']])
                df_val_email = pd.concat(email_list, ignore_index=True) if email_list else pd.DataFrame()

                # --- Validação 5: UUID do Auth x UUID de cada módulo ---
                df_val4 = pd.DataFrame()
                if 'uuid' in df_auth.columns:
                    df_val4 = df_auth[['username', 'uuid']].copy().rename(columns={'uuid': 'UUID_Auth'})
                    df_val4['UUID_Auth'] = df_val4['UUID_Auth'].astype(str).str.strip().str.lower()
                    for nome, base in bases.items():
                        if base.empty or 'uuid' not in base.columns:
                            continue
                        base_uuid = base[base['uuid'].apply(_valido)]  # ignora UUID vazio
                        mapa = base_uuid.drop_duplicates('username').set_index('username')['uuid'].astype(str).str.strip().str.lower().to_dict()
                        df_val4[f"UUID_{nome}"] = df_val4['username'].map(mapa)
                        df_val4[f"Match_{nome}"] = np.where(df_val4[f"UUID_{nome}"].isna(), 'Não Existe',
                                                            np.where(df_val4['UUID_Auth'] == df_val4[f"UUID_{nome}"], 'OK', 'Divergente'))

                # Guarda os resultados na memória da sessão
                st.session_state.t4_tenant = tenant_t4
                st.session_state.t4_val1_ok = df_val1[df_val1['Modulos_Ausentes'] == 'Nenhum'].copy()
                st.session_state.t4_val1_faltantes = df_val1[df_val1['Modulos_Ausentes'] != 'Nenhum'].copy()
                st.session_state.t4_val1_fora_auth = df_fora_auth
                st.session_state.t4_val2 = df_val2
                st.session_state.t4_val3 = df_val3
                st.session_state.t4_val_email = df_val_email
                st.session_state.t4_val4 = df_val4
                st.session_state.t4_tem_uuid = 'uuid' in df_auth.columns
                st.session_state.t4_bases_vazias = [n for n, b in bases.items() if b.empty]
                st.session_state.t4_processed = True

                bar.progress(100, text="Concluído!")
                time.sleep(1)
                bar.empty()

            except ErroAPI as e:
                bar.empty()
                st.session_state.t4_processed = False
                st.error(f"❌ Falha na comunicação com a Mindsight. {e}")
            except Exception as e:
                bar.empty()
                st.session_state.t4_processed = False
                st.error(f"Ocorreu um erro: {e}")

    # -------------------------------------------------------------------------
    # RESULTADOS E DOWNLOADS
    # -------------------------------------------------------------------------
    if st.session_state.t4_processed:
        tenant = st.session_state.t4_tenant
        st.success(f"✅ Análise de usuários entre módulos concluída para **{tenant}**.")
        if st.session_state.t4_bases_vazias:
            st.warning(f"Os seguintes módulos não retornaram nenhum usuário: {', '.join(st.session_state.t4_bases_vazias)}.")

        # 1ª validação
        st.write("---")
        st.subheader("1ª Validação: Presença nos Módulos")
        ok, falt = st.session_state.t4_val1_ok, st.session_state.t4_val1_faltantes
        st.markdown(f"**{len(ok)}** usuários presentes em todos os módulos e **{len(falt)}** faltando em algum.")
        if not falt.empty:
            with st.expander("👁️ Ver usuários faltando em módulos"):
                st.dataframe(falt, use_container_width=True)

        # Usuários que existem em algum módulo, mas não no Auth
        fora = st.session_state.get('t4_val1_fora_auth', pd.DataFrame())
        if fora.empty:
            st.markdown("Todos os usuários dos módulos existem no Auth.")
        else:
            st.markdown(f"**{len(fora)}** usuários existem em algum módulo, mas **não existem no Auth**.")
            with st.expander("👁️ Ver usuários que não existem no Auth"):
                st.dataframe(fora, use_container_width=True)

        if not ok.empty or not falt.empty or not fora.empty:
            st.download_button("📥 Baixar Presença (Excel, 3 planilhas)",
                               data=gerar_excel_multi_abas({'Presentes em Todos': ok, 'Faltando em Módulos': falt,
                                                            'Não Existem no Auth': fora}),
                               file_name=f"{tenant}_validacao_presenca.xlsx", mime=MIME_EXCEL, key="down_v1")

        # 2ª validação
        st.write("---")
        st.subheader("2ª Validação: Usuários Possivelmente Duplicados")
        if st.session_state.t4_val2.empty:
            st.info("Nenhum possível duplicado encontrado.")
        else:
            st.markdown(f"**{len(st.session_state.t4_val2)}** nomes com mais de um username ou email.")
            with st.expander("👁️ Ver possíveis duplicados"):
                st.dataframe(st.session_state.t4_val2, use_container_width=True)
            st.download_button("📥 Baixar Duplicados (Excel)", data=gerar_excel(st.session_state.t4_val2),
                               file_name=f"{tenant}_validacao_duplicados.xlsx", mime=MIME_EXCEL, key="down_v2")

        # 3ª validação
        st.write("---")
        st.subheader("3ª Validação: Divergências de Username")
        if st.session_state.t4_val3.empty:
            st.info("Nenhuma divergência de username encontrada.")
        else:
            st.markdown(f"**{len(st.session_state.t4_val3)}** divergências encontradas.")
            with st.expander("👁️ Ver divergências"):
                st.dataframe(st.session_state.t4_val3, use_container_width=True)
            st.download_button("📥 Baixar Divergências (Excel)", data=gerar_excel(st.session_state.t4_val3),
                               file_name=f"{tenant}_validacao_divergencias.xlsx", mime=MIME_EXCEL, key="down_v3")

        # 4ª validação
        st.write("---")
        st.subheader("4ª Validação: Divergências de Email")
        df_email = st.session_state.get('t4_val_email', pd.DataFrame())
        if df_email.empty:
            st.info("Nenhuma divergência de email encontrada.")
        else:
            st.markdown(f"**{len(df_email)}** usuários com o mesmo username e email diferente entre o Auth e algum módulo.")
            with st.expander("👁️ Ver divergências de email"):
                st.dataframe(df_email, use_container_width=True)
            st.download_button("📥 Baixar Divergências de Email (Excel)", data=gerar_excel(df_email),
                               file_name=f"{tenant}_validacao_divergencias_email.xlsx", mime=MIME_EXCEL, key="down_v5")

        # 5ª validação
        st.write("---")
        st.subheader("5ª Validação: Conferência de UUIDs")
        if not st.session_state.t4_tem_uuid:
            st.warning("A base do Auth não possui a coluna `uuid`, então esta validação não foi feita.")
        elif not st.session_state.t4_val4.empty:
            colunas_match = [c for c in st.session_state.t4_val4.columns if c.startswith('Match_')]
            qtd_div = int((st.session_state.t4_val4[colunas_match] == 'Divergente').any(axis=1).sum()) if colunas_match else 0
            st.markdown(f"**{qtd_div}** usuários com UUID divergente em algum módulo.")
            with st.expander("👁️ Ver conferência de UUIDs"):
                st.dataframe(st.session_state.t4_val4, use_container_width=True)
            st.download_button("📥 Baixar UUIDs (Excel)", data=gerar_excel(st.session_state.t4_val4),
                               file_name=f"{tenant}_validacao_uuids.xlsx", mime=MIME_EXCEL, key="down_v4")
