import streamlit as st

def apply_style():
    st.markdown("""
        <style>
        /* Fundo branco e texto escuro global */
        html, body, [data-testid="stAppViewContainer"], .stApp, .main { 
            background-color: #ffffff !important; 
            color: #1e1e1e !important; 
            font-family: 'Inter', sans-serif;
        }
        
        /* Força a cor escura nos textos */
        p, h1, h2, h3, h4, h5, h6, span, label, div.stMarkdown, .st-emotion-cache-10trblm { 
            color: #1e1e1e !important; 
        }
        
        /* Sidebar (Barra Lateral) branca com sombra leve */
        [data-testid="stSidebar"] { 
            background-color: #ffffff !important; 
            border-right: 1px solid #e0e0e0;
        }
        
        header[data-testid="stHeader"] { background-color: transparent !important; }
        
        /* Dropdowns (Selectbox e Multiselect) com estilo clean */
        [data-baseweb="popover"], [data-baseweb="menu"], [data-baseweb="select"] {
            background-color: #ffffff !important;
            border-radius: 8px !important;
        }
        [role="listbox"], [role="listbox"] li {
            background-color: #ffffff !important;
            color: #1e1e1e !important;
        }
        [role="option"]:hover {
            background-color: #f4e8ff !important;
            color: #8c00ff !important;
        }
        .stMultiSelect div[data-baseweb="select"] > div {
            background-color: #ffffff !important;
            color: #1e1e1e !important;
            border: 1px solid #cccccc !important;
            border-radius: 8px !important;
        }
        
        /* Estilização dos Botões principais (Roxo Mindsight) */
        div.stButton > button:first-child {
            background: linear-gradient(90deg, #8c00ff 0%, #b500ff 100%);
            color: white !important; 
            border: none; 
            border-radius: 8px; 
            font-weight: 600;
            padding: 0.5rem 1rem;
            box-shadow: 0 4px 6px rgba(140, 0, 255, 0.2);
        }
        div.stButton > button:first-child *, div.stButton > button:first-child p {
            color: white !important; 
        }
        div.stButton > button:first-child:hover {
            background: linear-gradient(90deg, #b500ff 0%, #8c00ff 100%);
            box-shadow: 0 6px 12px rgba(140, 0, 255, 0.3);
        }
        
        /* Estilização das Abas (Tabs) Mindsight Style */
        .stTabs [data-baseweb="tab-list"] { 
            gap: 24px; 
            border-bottom: 2px solid #f0f0f0;
        }
        .stTabs [data-baseweb="tab"] { 
            color: #777777 !important; 
            font-weight: 500;
            background-color: transparent !important;
            padding-bottom: 10px;
        }
        .stTabs [aria-selected="true"] { 
            color: #8c00ff !important; 
            border-bottom-color: #8c00ff !important; 
            font-weight: 700;
        }
        .stTabs [aria-selected="true"] p {
            color: #8c00ff !important;
            font-weight: 700;
        }
        
        /* Estilo dos containers e métricas (Cards) */
        div[data-testid="stMetricValue"] { color: #8c00ff !important; }
        
        /* Personalização do expander */
        .streamlit-expanderHeader {
            background-color: #f9f9f9;
            border-radius: 8px;
        }
        </style>
    """, unsafe_allow_html=True)