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
from abas.aba2_inativacao import render_aba2
from abas.aba3_participantes import render_aba3
from abas.aba4_usuarios_modulos import render_aba4

# Aplica o estilo Mindsight
apply_style()

# Inicialização da Memória (Session State global)
# Guarda os resultados da Aba 1 entre as interações (cada clique reexecuta o script inteiro).
#   t1_processed: se já houve um processamento bem-sucedido
#   t1_df1 / t1_df2: usuários do Passo 1 e do Passo 2
#   t1_len: total de funcionários ativos encontrados no Controle
#   t1_tenant: tenant usado no processamento (vai no nome dos arquivos)
#   t1_mod_verificados: módulos (Performance/Metas) cujos CSVs foram enviados para os tricks
# E os resultados da Aba 2:
#   t2_processed / t2_df / t2_tenant: processamento, base de inativação e tenant
#   t2_msg / t2_empty: mensagem de resultado e se não havia ninguém para inativar
# E os resultados da Aba 3:
#   t3_df_fix / t3_df_not_found / t3_df_desligados: correção do Auth, não encontrados e desligados
#   t3_len_total / t3_qtd_mindsight / t3_tenant / t3_nome_rodada: totais e dados da rodada
# E os resultados da Aba 4:
#   t4_val1_ok / t4_val1_faltantes / t4_val1_fora_auth / t4_val2 / t4_val3 / t4_val_email / t4_val4: resultado de cada validação
#   t4_tem_uuid / t4_bases_vazias / t4_tenant: informações para a tela de resultados
chaves_memoria = {
    't1_processed': False, 't1_df1': pd.DataFrame(), 't1_df2': pd.DataFrame(), 't1_len': 0, 't1_tenant': "", 't1_mod_verificados': [],
    't2_processed': False, 't2_df': pd.DataFrame(), 't2_tenant': "", 't2_msg': "", 't2_empty': False,
    't3_processed': False, 't3_df_fix': pd.DataFrame(), 't3_df_not_found': pd.DataFrame(),
    't3_df_desligados': pd.DataFrame(), 't3_len_total': 0, 't3_qtd_mindsight': 0, 't3_tenant': "", 't3_nome_rodada': "",
    't4_processed': False, 't4_tenant': "", 't4_val1_ok': pd.DataFrame(), 't4_val1_faltantes': pd.DataFrame(), 't4_val1_fora_auth': pd.DataFrame(),
    't4_val2': pd.DataFrame(), 't4_val3': pd.DataFrame(), 't4_val_email': pd.DataFrame(), 't4_val4': pd.DataFrame(), 't4_tem_uuid': False, 't4_bases_vazias': []
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
st.sidebar.header("Módulos Disponíveis")
st.sidebar.markdown("✅ Validação de Acessos (Ativos)")
st.sidebar.markdown("❌ Inativar Acessos (Desligados)")
st.sidebar.markdown("🎯 Participantes da Rodada")
st.sidebar.markdown("🔍 Usuários x Módulos")

# =============================================================================
# CORPO PRINCIPAL
# =============================================================================
st.title("Canivete Suíço de Acessos")

# Criação das abas visuais
# Observação: por enquanto apenas as Abas 1 a 4 estão implementadas; as demais ainda estão vazias.
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

with tab2:
    render_aba2()

with tab3:
    render_aba3()

with tab4:
    render_aba4()
