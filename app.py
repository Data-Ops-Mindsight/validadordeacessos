"""
Canivete Suíço de Acessos (Mindsight) - ponto de entrada do app Streamlit.

Responsabilidades deste arquivo:
  - configurar a página;
  - baixar o pacote privado 'mindsight-api-requests' (usado pelas funções de API);
  - inicializar a memória da sessão (session_state);
  - montar a barra lateral com a logo e as abas da ferramenta.

Para rodar localmente: streamlit run app.py
(é necessário ter GITHUB_TOKEN em .streamlit/secrets.toml)
"""

import streamlit as st
import pandas as pd
import os
import base64
import sys
import subprocess

# Configuração da página (DEVE ser a primeira linha)
st.set_page_config(page_title="Canivete Suíço | Mindsight", layout="wide", initial_sidebar_state="expanded")

# =============================================================================
# INJEÇÃO SEGURA DO PACOTE PRIVADO (Sem expor no GitHub e sem usar pip)
# =============================================================================
PASTA_TMP = "/tmp/mindsight_api"

# Se o pacote ainda não estiver na memória temporária do servidor, faz o download
if not os.path.exists(PASTA_TMP):
    with st.spinner("Autenticando ambiente seguro..."):
        # Puxa o token do painel Secrets do Streamlit Cloud
        token = st.secrets["GITHUB_TOKEN"]
        repo_url = f"https://{token}@github.com/Data-Ops-Mindsight/mindsight-api-requests.git"
        
        # Clona o repositório silenciosamente para a pasta temporária do Linux
        subprocess.run(["git", "clone", "--quiet", repo_url, PASTA_TMP], check=True)

# Ensina o Python a procurar bibliotecas dentro desta pasta temporária
if PASTA_TMP not in sys.path:
    sys.path.insert(0, PASTA_TMP)

# =============================================================================
# IMPORTAÇÕES DO PROJETO (Devem ficar abaixo da injeção)
# =============================================================================
from style import apply_style
from abas.aba1_validacao import render_aba1

# Aplica o estilo Mindsight
apply_style()

# Inicialização da Memória (Session State global)
# Guarda os resultados da Aba 1 entre as interações (cada clique reexecuta o script inteiro).
#   t1_processed: se já houve um processamento bem-sucedido
#   t1_df1 / t1_df2: usuários do Passo 1 e do Passo 2
#   t1_len: total de funcionários ativos encontrados no Controle
#   t1_tenant: tenant usado no processamento (vai no nome dos arquivos)
chaves_memoria = {
    't1_processed': False, 't1_df1': pd.DataFrame(), 't1_df2': pd.DataFrame(), 't1_len': 0, 't1_tenant': ""
}

for chave, valor in chaves_memoria.items():
    if chave not in st.session_state:
        st.session_state[chave] = valor

# =============================================================================
# BARRA LATERAL COM A LOGO 
# =============================================================================
# Tenta usar a logo em SVG; se não existir, usa o PNG; se nada existir, mostra o nome em texto.
logo_svg = "mindsight_logo.svg"
logo_png = "mindsight_logo.png"

if os.path.exists(logo_svg):
    try:
        with open(logo_svg, "r", encoding="utf-8") as f:
            svg_content = f.read()
        st.sidebar.markdown(
            f'<div style="width:100%; text-align:center; padding-bottom: 20px;">{svg_content}</div>', 
            unsafe_allow_html=True
        )
    except Exception:
        st.sidebar.markdown("### **mindsight**")
elif os.path.exists(logo_png):
    try:
        with open(logo_png, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        st.sidebar.markdown(
            f'<img src="data:image/png;base64,{data}" style="width:100%; padding-bottom: 20px;">', 
            unsafe_allow_html=True
        )
    except Exception:
        st.sidebar.markdown("### **mindsight**")
else:
    st.sidebar.markdown("### **mindsight**")

st.sidebar.markdown("---")
st.sidebar.header("Módulo Atual")
st.sidebar.markdown("✅ Validação de Acessos (Ativos)")

# =============================================================================
# CORPO PRINCIPAL
# =============================================================================
st.title("Canivete Suíço de Acessos")

# Criação das abas visuais
# Observação: por enquanto apenas a Aba 1 está implementada; as demais ainda estão vazias.
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "✅ Validação (Ativos)", 
    "❌ Inativar (Desligados)", 
    "🎯 Participantes (Rodada)", 
    "🔍 Usuários x Módulos",
    "👥 Funcionários x Módulos",
    "🛠️ Criador de Regras"
])

# Renderização do conteúdo de cada aba de forma modular
with tab1:
    render_aba1()
