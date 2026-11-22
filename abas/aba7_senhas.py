"""
Aba 7 - Criação de Senhas.

Fluxo da aba:
  1. O usuário informa o tenant do cliente, o texto do padrão de senha e faz upload
     da base exportada do Auth (.csv).
  2. Ao clicar em "Gerar Senhas", a ferramenta:
       - remove os usuários da Mindsight e os usuários inativos (is_active = 0);
       - opcionalmente ignora quem já logou no sistema (coluna last_login preenchida);
       - separa os usuários cujo username não é um CPF (11 dígitos, ignorando pontos e traço),
         que NÃO recebem senha;
       - cria a senha: 5 primeiros dígitos do CPF + texto do padrão.
  3. Gera dois Excel:
       - "Base de senhas - <tenant>.xlsx": Colaborador, Usuário (Login) e Senha (enviada ao cliente);
       - "Base senha - <tenant>.xlsx": id_auth, username, email e password (usada no script
         que atualiza as senhas).
"""

import streamlit as st
import pandas as pd

from functions import *

# Valores que o Auth usa para indicar "usuário ativo" (base lida como texto)
VALORES_ATIVO_TXT = ['1', 'true', '1.0']
MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _so_digitos(valor):
    """Remove pontos, traços e espaços do username."""
    return str(valor).replace('.', '').replace('-', '').replace(' ', '')


def render_aba7():
    st.header("Criação de Senhas")

    st.warning(
        "⚠️ **Antes de exportar os usuários do Auth, rode as abas Validação (Ativos) e "
        "Inativar (Desligados)** e suba os arquivos gerados no Auth. Assim os usuários de "
        "funcionários ativos que estavam inativos no Auth são ativados, e os de funcionários "
        "desligados são inativados. Só depois exporte a base do Auth para esta aba. Isso evita "
        "criar senha para usuário de funcionário desligado e deixar sem senha um funcionário "
        "ativo cujo usuário estava inativo no Auth."
    )

    st.info(
        "💡 **Como a senha é criada?** 5 primeiros dígitos do username (CPF) + o texto do padrão "
        "informado abaixo. Ex.: username `12345678900` com o padrão `Mind@2026` gera a senha "
        "`12345Mind@2026`.\n\n"
        "✅ **Quem recebe senha:** usuários ativos no Auth cujo username é um CPF (11 dígitos, "
        "ignorando pontos e traço), tenham ou não email cadastrado.\n\n"
        "🚫 **Quem não recebe senha:** usuários da Mindsight, usuários inativos (`is_active` = 0) "
        "e usuários cujo username não é um CPF (ex.: um email). Esses últimos são listados para "
        "você conferir."
    )

    # -------------------------------------------------------------------------
    # SEÇÃO 1: DADOS DO CLIENTE E PADRÃO DA SENHA
    # -------------------------------------------------------------------------
    st.markdown("### 🔑 Dados do Cliente")
    c1, c2, _ = st.columns(3)
    tenant_t7 = c1.text_input("Tenant do Cliente", key="tenant_t7", placeholder="Ex: empresa123")
    padrao_t7 = c2.text_input("Texto do padrão de senha", key="padrao_senha_t7",
                              placeholder="Digite o texto da senha. Ex: Mind@2026",
                              help="A senha será: 5 primeiros dígitos do CPF + este texto.")

    ignorar_logados = st.checkbox("Ignorar usuários que já logaram no sistema (coluna last_login preenchida)",
                                  value=True, key="ignorar_logados_t7")
    if not ignorar_logados:
        st.warning("⚠️ Com esta opção desmarcada, será criada senha para **todos os usuários ativos**, "
                   "inclusive os que já logaram e talvez já tenham definido a própria senha.")

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # SEÇÃO 2: BASE DO AUTH E PROCESSAMENTO
    # -------------------------------------------------------------------------
    st.markdown("### 📁 Base de Usuários (Auth)")
    arquivo_auth_t7 = st.file_uploader("Faça o upload da base exportada do Auth (.csv)", type=['csv'], key="arquivo_auth_t7")

    if st.button("Gerar Senhas", key="btn_t7"):
        if not tenant_t7 or not padrao_t7.strip() or not arquivo_auth_t7:
            st.error("Preencha o Tenant, o texto do padrão de senha e faça o upload da base.")
        else:
            try:
                df = ler_csv_seguro(arquivo_auth_t7, como_texto=True)
                obrigatorias = ['id', 'username', 'email', 'first_name', 'last_name', 'is_active']
                if ignorar_logados:
                    obrigatorias.append('last_login')
                faltando = [c for c in obrigatorias if c not in df.columns]
                if faltando:
                    raise ValueError(f"a base do Auth não possui as colunas: {', '.join(faltando)}.")

                df['username'] = df['username'].astype(str).str.strip()
                total = len(df)

                # Remove usuários da Mindsight
                eh_mindsight = df['username'].str.contains('mindsight', case=False, na=False) \
                    | df['email'].astype(str).str.contains('@mindsight', case=False, na=False)
                qtd_mindsight = int(eh_mindsight.sum())
                df = df.loc[~eh_mindsight]

                # Remove inativos
                ativo = df['is_active'].astype(str).str.strip().str.lower().isin(VALORES_ATIVO_TXT)
                qtd_inativos = int((~ativo).sum())
                df = df.loc[ativo]

                # Ignora quem já logou
                qtd_logados = 0
                if ignorar_logados:
                    logou = df['last_login'].astype(str).str.strip().replace({'nan': '', 'None': '', 'NaT': ''}) != ''
                    qtd_logados = int(logou.sum())
                    df = df.loc[~logou]

                # Separa quem não tem username no padrão CPF
                digitos = df['username'].map(_so_digitos)
                eh_cpf = digitos.str.fullmatch(r'\d{11}')
                df_fora = df.loc[~eh_cpf].copy()
                df = df.loc[eh_cpf].copy()
                df['cpf'] = digitos[eh_cpf]

                # Cria as senhas
                df['password'] = df['cpf'].str[:5] + padrao_t7.strip()
                df['id_auth'] = df['id']
                df['Colaborador'] = (df['first_name'].fillna('') + ' ' + df['last_name'].fillna('')).str.strip()

                df_cliente = df[['Colaborador', 'username', 'password']].rename(
                    columns={'username': 'Usuário (Login)', 'password': 'Senha'}).sort_values('Colaborador')
                df_script = df[['id_auth', 'username', 'email', 'password']]

                df_fora['Colaborador'] = (df_fora['first_name'].fillna('') + ' ' + df_fora['last_name'].fillna('')).str.strip()
                df_fora = df_fora[['id', 'Colaborador', 'username', 'email']].rename(
                    columns={'id': 'id_auth', 'username': 'Usuário (Login)', 'email': 'Email'}).sort_values('Colaborador')

                st.session_state.t7_tenant = tenant_t7.strip()
                st.session_state.t7_cliente = df_cliente
                st.session_state.t7_script = df_script
                st.session_state.t7_fora = df_fora
                st.session_state.t7_resumo = pd.DataFrame([
                    ('Usuários na base do Auth', total),
                    ('Usuários da Mindsight (ignorados)', qtd_mindsight),
                    ('Usuários inativos (ignorados)', qtd_inativos),
                    ('Usuários que já logaram (ignorados)', qtd_logados if ignorar_logados else 'opção desmarcada'),
                    ('Username fora do padrão CPF (sem senha)', len(df_fora)),
                    ('Senhas criadas', len(df_cliente)),
                ], columns=['Item', 'Quantidade'])
                st.session_state.t7_processed = True
            except Exception as e:
                st.session_state.t7_processed = False
                st.error(f"Erro ao gerar as senhas: {e}")

    # -------------------------------------------------------------------------
    # RESULTADOS E DOWNLOADS
    # -------------------------------------------------------------------------
    if st.session_state.t7_processed:
        tenant = st.session_state.t7_tenant
        st.write("### Resumo")
        st.dataframe(st.session_state.t7_resumo.astype(str), width='stretch', hide_index=True)

        df_fora = st.session_state.t7_fora
        if not df_fora.empty:
            st.error(f"⚠️ **{len(df_fora)}** usuários ativos têm username fora do padrão CPF e **não receberam senha**. "
                     "Confira esses casos com o cliente.")
            st.dataframe(df_fora, width='stretch', hide_index=True)
            st.download_button("📥 Baixar Usuários sem Senha (Excel)", data=gerar_excel(df_fora),
                               file_name=f"{tenant}_usuarios_fora_padrao_cpf.xlsx", mime=MIME_EXCEL, key="down_t7_fora")

        df_cliente = st.session_state.t7_cliente
        if df_cliente.empty:
            st.warning("Nenhuma senha foi criada.")
            return

        st.success(f"✅ {len(df_cliente)} senhas criadas.")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Base de senhas** (enviar ao cliente)")
            st.dataframe(df_cliente.head(), width='stretch', hide_index=True)
            st.download_button("📥 Baixar Base de senhas (Excel)", data=gerar_excel(df_cliente),
                               file_name=f"Base de senhas - {tenant}.xlsx", mime=MIME_EXCEL, key="down_t7_cliente")
        with c2:
            st.write("**Base senha** (usar no script que atualiza as senhas)")
            st.dataframe(st.session_state.t7_script.head(), width='stretch', hide_index=True)
            st.download_button("📥 Baixar Base senha (Excel)", data=gerar_excel(st.session_state.t7_script),
                               file_name=f"Base senha - {tenant}.xlsx", mime=MIME_EXCEL, key="down_t7_script")
