"""
Canivete Suíço Mindsight - ponto de entrada do app Streamlit.

Responsabilidades deste arquivo:
  - configurar a página;
  - baixar o pacote privado 'mindsight-api-requests' (usado pelas funções de API);
  - inicializar a memória da sessão (session_state);
  - montar a barra lateral com a logo e o menu de ferramentas (agrupado por assunto).

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
st.set_page_config(page_title="Canivete Suíço Mindsight", layout="wide", initial_sidebar_state="expanded")

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
from abas.aba5_funcionarios_modulos import render_aba5
from abas.aba6_regras_bps import render_aba6
from abas.aba7_senhas import render_aba7
from abas.aba8_salarios import render_aba8

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
# E os resultados da Aba 5:
#   t5_processed / t5_tenant: processamento e tenant
#   t5_final / t5_resumo / t5_planilhas / t5_mod_verificados: relatório completo, resumo, planilhas do Excel e módulos verificados
# E os da Aba 6:
#   t6_dados / t6_tenant: dados carregados do People Hub e tenant
#   t6_processed / t6_csv / t6_novas / t6_existentes / t6_resumo: regras calculadas e relatórios
#   t7_processed / t7_tenant / t7_cliente / t7_script / t7_fora / t7_resumo: senhas geradas e relatórios
#   t8_processed / t8_tenant / t8_resultado: validação de salários (resumo e tabelas)
chaves_memoria = {
    't1_processed': False, 't1_df1': pd.DataFrame(), 't1_df2': pd.DataFrame(), 't1_len': 0, 't1_tenant': "", 't1_mod_verificados': [],
    't2_processed': False, 't2_df': pd.DataFrame(), 't2_tenant': "", 't2_msg': "", 't2_empty': False,
    't3_processed': False, 't3_df_fix': pd.DataFrame(), 't3_df_not_found': pd.DataFrame(),
    't3_df_desligados': pd.DataFrame(), 't3_len_total': 0, 't3_qtd_mindsight': 0, 't3_tenant': "", 't3_nome_rodada': "",
    't4_processed': False, 't4_tenant': "", 't4_val1_ok': pd.DataFrame(), 't4_val1_faltantes': pd.DataFrame(), 't4_val1_fora_auth': pd.DataFrame(),
    't4_val2': pd.DataFrame(), 't4_val3': pd.DataFrame(), 't4_val_email': pd.DataFrame(), 't4_val4': pd.DataFrame(), 't4_tem_uuid': False, 't4_bases_vazias': [],
    't5_processed': False, 't5_tenant': "", 't5_final': pd.DataFrame(), 't5_resumo': pd.DataFrame(), 't5_planilhas': {},
    't5_mod_verificados': [],
    't6_dados': None, 't6_tenant': "", 't6_processed': False, 't6_csv': pd.DataFrame(), 't6_novas': pd.DataFrame(),
    't6_existentes': pd.DataFrame(), 't6_resumo': pd.DataFrame(),
    't7_processed': False, 't7_tenant': "", 't7_cliente': pd.DataFrame(), 't7_script': pd.DataFrame(),
    't7_fora': pd.DataFrame(), 't7_resumo': pd.DataFrame(),
    't8_processed': False, 't8_tenant': "", 't8_resultado': {}
}

for chave, valor in chaves_memoria.items():
    if chave not in st.session_state:
        st.session_state[chave] = valor

# =============================================================================
# LOGO (canto superior da barra lateral)
# =============================================================================
# Usa a logo em SVG; se não existir, o PNG; se nada existir, mostra o nome em texto.
logo = next((f for f in ["mindsight_logo.svg", "mindsight_logo.png"] if os.path.exists(f)), None)
if logo:
    try:
        st.logo(logo, size="large")
        # O st.logo limita a altura da imagem; este CSS deixa a logo ocupar a largura da barra lateral
        st.markdown("""
            <style>
            [data-testid="stSidebarHeader"] { height: auto !important; align-items: flex-start; padding-top: 1.5rem; padding-bottom: 0.5rem; }
            [data-testid="stSidebarHeader"] > div:has(> [data-testid="stSidebarLogo"]),
            [data-testid="stSidebarHeader"] > a:has([data-testid="stSidebarLogo"]) { flex: 1; }
            img[data-testid="stSidebarLogo"] { height: auto !important; max-height: none !important; max-width: none !important; width: 90% !important; }
            </style>
        """, unsafe_allow_html=True)
    except Exception:
        st.sidebar.markdown("### **mindsight**")
else:
    st.sidebar.markdown("### **mindsight**")


# =============================================================================
# MENU DE NAVEGAÇÃO (barra lateral, agrupado por assunto)
# =============================================================================
# Cada ferramenta é uma página com endereço próprio (ex.: .../regras-bps) e só a
# página aberta é executada. Para criar uma ferramenta nova, basta acrescentar um
# st.Page no grupo certo.
paginas = {
    "Acessos no Auth": [
        st.Page(render_aba1, title="Validação (Ativos)", icon="✅", url_path="validacao-ativos", default=True),
        st.Page(render_aba2, title="Inativar (Desligados)", icon="❌", url_path="inativar-desligados"),
        st.Page(render_aba3, title="Participantes (Rodada)", icon="🎯", url_path="participantes-rodada"),
        st.Page(render_aba7, title="Criação de Senhas", icon="🔐", url_path="criacao-senhas"),
    ],
    "Conferência entre módulos": [
        st.Page(render_aba4, title="Usuários x Módulos", icon="🔍", url_path="usuarios-modulos"),
        st.Page(render_aba5, title="Funcionários x Módulos", icon="👥", url_path="funcionarios-modulos"),
    ],
    "People Hub / Organograma": [
        st.Page(render_aba6, title="Regras de Acessos (BPs)", icon="🛠️", url_path="regras-bps"),
        st.Page(render_aba8, title="Validação de Salários", icon="💰", url_path="validacao-salarios"),
    ],
}
pagina = st.navigation(paginas, position="sidebar")

# =============================================================================
# CORPO PRINCIPAL
# =============================================================================
st.title("Canivete Suíço Mindsight")
pagina.run()
