import streamlit as st
import pandas as pd
import os
import base64
import subprocess
import sys


# 1. Configuração da página (DEVE ser a primeira linha)
st.set_page_config(page_title="Canivete Suíço | Mindsight", layout="wide", initial_sidebar_state="expanded")

# 1. Configuração da página
st.set_page_config(page_title="Canivete Suíço | Mindsight", layout="wide", initial_sidebar_state="expanded")

# =============================================================================
# INSTALADOR DINÂMICO DO PACOTE PRIVADO
# =============================================================================
try:
    import mindsight_api_requests
except ImportError:
    with st.spinner("Instalando dependências privadas..."):
        # Puxa o token em segurança diretamente do painel Secrets
        token = st.secrets["GITHUB_TOKEN"]
        # Monta a URL de instalação com o token real
        repo_url = f"git+https://{token}@github.com/Data-Ops-Mindsight/mindsight-api-requests.git"
        # Executa a instalação via pip no servidor
        subprocess.check_call([sys.executable, "-m", "pip", "install", repo_url])
        st.rerun() # Reinicia a página após instalar

# 2. Importações Locais (Devem ficar ABAIXO do instalador dinâmico)
from style import apply_style
from abas.aba1_validacao import render_aba1

# Aplica o estilo Mindsight
apply_style()

# 2. Importações Locais
from style import apply_style
from abas.aba1_validacao import render_aba1

# Aplica o estilo Mindsight
apply_style()

# 3. Inicialização da Memória (Session State global)
chaves_memoria = {
    't1_processed': False, 't1_df1': pd.DataFrame(), 't1_df2': pd.DataFrame(), 't1_len': 0, 't1_tenant': ""
}

for chave, valor in chaves_memoria.items():
    if chave not in st.session_state:
        st.session_state[chave] = valor

# =============================================================================
# BARRA LATERAL COM A LOGO 
# =============================================================================
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

# Quando as próximas abas forem criadas, basta adicionar:
# with tab2:
#     render_aba2()
