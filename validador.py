import streamlit as st
import pandas as pd
import numpy as np
import time
import subprocess
import sys

# ==========================================
# INSTALAÇÃO DINÂMICA DA BIBLIOTECA PRIVADA
# ==========================================
try:
    import mindsight_api_requests
except ImportError:
    # Tenta instalar apenas se a biblioteca ainda não estiver no ambiente
    if "GITHUB_TOKEN" in st.secrets:
        token = st.secrets["GITHUB_TOKEN"]
        # Use a conta correta identificada no seu erro (Data-Ops-Mindsight)
        repo_url = f"git+https://{token}@github.com/Data-Ops-Mindsight/mindsight_api_requests.git"
        
        with st.spinner("A instalar dependências privadas..."):
            subprocess.check_call([sys.executable, "-m", "pip", "install", repo_url])
    else:
        st.error("🚨 GITHUB_TOKEN não encontrado nos Secrets do Streamlit!")
        st.stop()

# Importando todas as lógicas do nosso arquivo de funções após garantir a instalação
from validador_functions import *

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA STREAMLIT
# =============================================================================
st.set_page_config(
    page_title="Gestão de Acessos | Mindsight", 
    page_icon="mindsight-logo.png", 
    layout="wide"
)

# ==========================================
# INJEÇÃO DE CSS (TEMA MINDSIGHT)
# ==========================================
st.markdown("""
    <style>
    .stApp { background-color: #09030f; color: #ffffff; }
    header[data-testid="stHeader"] { background-color: transparent !important; }
    [data-testid="stSidebar"] { background-color: #120520 !important; }
    div.stButton > button:first-child {
        background: linear-gradient(90deg, #6200ea 0%, #b500ff 100%);
        color: white; border: none; border-radius: 6px; font-weight: bold;
    }
    div.stButton > button:first-child:hover {
        background: linear-gradient(90deg, #b500ff 0%, #6200ea 100%);
    }
    .stTabs [data-baseweb="tab-list"] { gap: 20px; }
    .stTabs [data-baseweb="tab"] { color: #b0b0b0; }
    .stTabs [aria-selected="true"] { color: #b500ff !important; border-bottom-color: #b500ff !important; }
    </style>
""", unsafe_allow_html=True)

st.sidebar.image("preview_mind.png", use_container_width=True)
st.title("Gestão de Acessos Mindsight")

# =============================================================================
# INICIALIZAÇÃO BLINDADA (SESSION STATE)
# =============================================================================
chaves_memoria = {
    'cookies_sessao': None,
    't1_processed': False, 't1_df1': pd.DataFrame(), 't1_df2': pd.DataFrame(), 't1_len': 0, 't1_tenant': "",
    't2_processed': False, 't2_df': pd.DataFrame(), 't2_tenant': "", 't2_msg': "", 't2_empty': False,
    't3_processed': False, 't3_df_fix': pd.DataFrame(), 't3_df_not_found': pd.DataFrame(), 
    't3_df_desligados': pd.DataFrame(), 't3_len_total': 0, 't3_qtd_mindsight': 0, 't3_tenant': "",
    't4_processed': False, 't4_tenant': "", 't4_val1_ok': pd.DataFrame(), 't4_val1_faltantes': pd.DataFrame(), 
    't4_val2': pd.DataFrame(), 't4_val3': pd.DataFrame(), 't4_val4': pd.DataFrame(),
    't5_tenant': "", 't5_df_ctrl': pd.DataFrame(), 't5_df_hub': pd.DataFrame(), 't5_df_metas_users': pd.DataFrame(), 't5_final': pd.DataFrame()
}

for chave, valor in chaves_memoria.items():
    if chave not in st.session_state:
        st.session_state[chave] = valor

# =============================================================================
# BARRA LATERAL: AUTENTICAÇÃO SCRAPING
# =============================================================================
st.sidebar.header("🔐 Autenticação Mindsight")
st.sidebar.markdown("Necessário para Metas e Performance (Abas 4 e 5).")
tenant_login = st.sidebar.text_input("Tenant para Login:", key="tenant_login")

if st.sidebar.button("Realizar Login Edge"):
    if tenant_login:
        with st.spinner("Abrindo Edge... Faça o login na janela. O navegador fechará sozinho quando concluir."):
            driver = webdriver.Edge()
            driver.get(f"https://auth.mindsight.com.br/{tenant_login}/")
            while "login" in driver.current_url or "mfa" in driver.current_url or "otp" in driver.current_url:
                time.sleep(1)
            cookies_selenium = driver.get_cookies()
            st.session_state['cookies_sessao'] = {cookie['name']: cookie['value'] for cookie in cookies_selenium}
            driver.quit()
        st.sidebar.success("✅ Conectado com sucesso! Sessão salva.")
    else:
        st.sidebar.error("Preencha o tenant para logar.")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "✅ Validação (Ativos)", 
    "❌ Inativar (Desligados)", 
    "🎯 Participantes (Rodada)", 
    "🔍 Validação de usuários entre módulos",
    "👥 Validação de funcionários entre módulos"
])

# =============================================================================
# ABA 1: VALIDAÇÃO (ATIVOS)
# =============================================================================
with tab1:
    st.header("Validação de Acessos - Colaboradores Ativos")
    col1, col2 = st.columns(2)
    with col1:
        tenant_t1 = st.text_input("Tenant do Cliente", key="tenant_t1")
        token_controle_t1 = st.text_input("Token do Controle", key="token_controle_t1")
        token_full_t1 = st.text_input("Token do Full (Opcional)", key="token_full_t1")
    with col2:
        acesso_full_t1 = st.radio("Acesso ao People Hub:", options=['Todos os usuários', 'Gestores', 'Nenhum usuário'], index=2, key="acesso_full_t1")
        validacao_t1 = st.radio("Tipo de Validação:", options=['Validação padrão (metas, perfomance)', 'Validar somente metas', 'Validar somente performance'], key="validacao_t1")
        acesso_controle_t1 = st.text_area("Usuários com acesso ao Controle (separados por vírgula):", key="acesso_controle_t1")

    arquivo_auth_t1 = st.file_uploader("Upload Auth (.csv)", type=['csv'], key="arquivo_auth_t1")

    if st.button("Processar Validação", key="btn_t1"):
        if not tenant_t1 or not token_controle_t1 or not arquivo_auth_t1:
            st.error("Preencha todos os campos obrigatórios.")
        else:
            bar = st.progress(0, text="A iniciar processamento...")
            try:
                df_usuarios_auth = ler_csv_seguro(arquivo_auth_t1)
                if 'username' not in df_usuarios_auth.columns:
                    st.error("Erro: A planilha não possui a coluna 'username'.")
                    st.stop()
                
                bar.progress(10, text="Obtendo Funcionários do Controle...")
                funcionarios_controle = get_controle_employees_api(tenant_t1, token_controle_t1)
                user_col_t1 = 'user.username' if 'user.username' in funcionarios_controle.columns else 'username'
                if user_col_t1 not in funcionarios_controle.columns: funcionarios_controle[user_col_t1] = ''

                bar.progress(30, text="Obtendo Registos do Controle...")
                reg_funcionarios_controle = get_controle_employee_records_api(tenant_t1, token_controle_t1)
                
                gestores_funcionario_controle = get_controle_employee_managers_api(tenant_t1, token_controle_t1) if acesso_full_t1 == 'Gestores' else pd.DataFrame()
                df_usuarios_full = ler_usuarios_full(tenant_t1, token_full_t1) if token_full_t1 else pd.DataFrame()

                bar.progress(60, text="Cruzando dados e validando acessos...")
                reg_funcionarios_controle['start'] = pd.to_datetime(reg_funcionarios_controle['start'], errors='coerce')
                reg_funcionarios_controle['end'] = pd.to_datetime(reg_funcionarios_controle['end'], errors='coerce')
                reg_funcionarios_controle = reg_funcionarios_controle.sort_values(by=['employee_code', 'end', 'start'], ascending=[True, True, True], na_position='last')
                df_mais_recente_ativos = reg_funcionarios_controle.drop_duplicates(subset='employee_code', keep='last').copy()
                df_mais_recente_ativos = df_mais_recente_ativos.loc[df_mais_recente_ativos['end'].isna()].copy()
                
                df_gestores_ativos = pd.DataFrame()
                if not gestores_funcionario_controle.empty:
                    gestores_funcionario_controle['start'] = pd.to_datetime(gestores_funcionario_controle['start'], errors='coerce')
                    gestores_funcionario_controle['end'] = pd.to_datetime(gestores_funcionario_controle['end'], errors='coerce')
                    gestores_funcionario_controle = gestores_funcionario_controle.sort_values(by=['employee_code', 'end', 'start'], ascending=[True, True, True], na_position='last')
                    df_gestores_ativos = gestores_funcionario_controle.drop_duplicates(subset='employee_code', keep='last').copy()
                    df_gestores_ativos = df_gestores_ativos.loc[df_gestores_ativos['end'].isna()].copy()

                df_validacao = df_mais_recente_ativos[['employee_code']].copy()
                df_usuarios_auth_limpo = df_usuarios_auth.loc[~df_usuarios_auth['username'].astype(str).str.contains('mindsight', na=False, case=False)].copy()
                
                mapa_usr = funcionarios_controle.set_index('employee_code')[user_col_t1].to_dict()
                df_validacao['user.username'] = df_validacao['employee_code'].map(mapa_usr).fillna('').astype(str).str.strip()
                df_usuarios_auth_limpo['username'] = df_usuarios_auth_limpo['username'].astype(str).str.strip()

                df_validacao = df_validacao.merge(df_usuarios_auth_limpo[['username', 'access_to_systems', 'is_active']], left_on='user.username', right_on='username', how='left')
                
                if token_full_t1 and not df_usuarios_full.empty:
                    df_usuarios_full_limpo = df_usuarios_full[['username', 'is_active']].copy()
                    df_usuarios_full_limpo['username'] = df_usuarios_full_limpo['username'].astype(str).str.strip()
                    df_validacao = df_validacao.merge(df_usuarios_full_limpo, left_on='user.username', right_on='username', how='left', suffixes=('', '_full_drop'))
                    df_validacao['is_active_full'] = df_validacao['is_active'].fillna(False)
                else:
                    df_validacao['is_active_full'] = True

                df_validacao['sou_gestor'] = df_validacao['employee_code'].isin(df_gestores_ativos['manager_code'].dropna().unique()) if not df_gestores_ativos.empty else False

                bar.progress(90, text="A gerar ficheiros de correção...")
                df_add_acessos = df_usuarios_auth_limpo.merge(df_validacao[['username', 'sou_gestor', 'is_active_full']], on='username', how='inner').copy()
                
                lista_acessos = [u.strip() for u in acesso_controle_t1.split(',')] if acesso_controle_t1.strip() else []
                df_add_acessos[['acessos_csv1', 'acessos_csv2', 'vai_pro_csv1', 'vai_pro_csv2', 'motivo']] = df_add_acessos.apply(lambda row: formatar_acessos_duplo(row, acesso_full_t1, lista_acessos, bool(token_full_t1), validacao_t1), axis=1)

                st.session_state.t1_df1 = df_add_acessos[df_add_acessos['vai_pro_csv1'] == True].copy()
                st.session_state.t1_df2 = df_add_acessos[df_add_acessos['vai_pro_csv2'] == True].copy()
                st.session_state.t1_len = len(df_mais_recente_ativos)
                st.session_state.t1_tenant = tenant_t1
                st.session_state.t1_processed = True
                
                bar.progress(100, text="Concluído!")
                time.sleep(1)
                bar.empty()
            except Exception as e:
                st.error(f"Ocorreu um erro: {e}")

    if st.session_state.t1_processed:
        st.success(f"✅ Validação concluída! Funcionários Ativos identificados: {st.session_state.t1_len}")
        if not st.session_state.t1_df1.empty:
            df_final_1 = montar_df_upload(st.session_state.t1_df1, 'acessos_csv1', incluir_motivo=True)
            st.write("### PASSO 1: Ajustes de Acessos / Ativação")
            
            motivos = df_final_1['motivo_ajuste'].value_counts().reset_index()
            motivos.columns = ['Motivo', 'Quantidade']
            st.markdown(motivos.to_html(index=False), unsafe_allow_html=True)
            st.download_button("📥 Baixar Planilha PASSO 1 (CSV)", data=df_final_1.to_csv(index=False, sep=',', encoding='utf-8-sig'), file_name=f"{st.session_state.t1_tenant}_ajustes_acessos.csv", mime="text/csv", key="down1")
        else:
            st.info("Nenhum ajuste necessário para o PASSO 1.")
            
        if not st.session_state.t1_df2.empty:
            df_final_2 = montar_df_upload(st.session_state.t1_df2, 'acessos_csv2', False)
            st.write("### PASSO 2: Reativação do Full")
            st.download_button("📥 Baixar Planilha PASSO 2 (CSV)", data=df_final_2.to_csv(index=False, sep=',', encoding='utf-8-sig'), file_name=f"{st.session_state.t1_tenant}_reativacao_full.csv", mime="text/csv", key="down2")
        else:
            st.info("Nenhum ajuste necessário para o PASSO 2.")

# =============================================================================
# ABA 2: INATIVAR (DESLIGADOS)
# =============================================================================
with tab2:
    st.header("Inativar Acessos - Colaboradores Desligados")
    col1, col2 = st.columns(2)
    with col1:
        tenant_t2 = st.text_input("Tenant do Cliente", key="tenant_t2")
        token_controle_t2 = st.text_input("Token do Controle", key="token_controle_t2")
    arquivo_auth_t2 = st.file_uploader("Upload Auth (.csv)", type=['csv'], key="arquivo_auth_t2")

    if st.button("Processar Inativações", key="btn_t2"):
        if not tenant_t2 or not token_controle_t2 or not arquivo_auth_t2:
            st.error("Preencha todos os campos.")
        else:
            bar = st.progress(0, text="Lendo dados...")
            try:
                df_auth = ler_csv_seguro(arquivo_auth_t2)
                if 'username' not in df_auth.columns: st.stop()
                    
                df_auth = df_auth.loc[~df_auth['username'].astype(str).str.contains('mindsight', na=False, case=False)]
                
                bar.progress(30, text="Obtendo Funcionários do Controle...")
                func_ctrl = get_controle_employees_api(tenant_t2, token_controle_t2)
                user_col = 'user.username' if 'user.username' in func_ctrl.columns else 'username'
                if user_col not in func_ctrl.columns: func_ctrl[user_col] = ''
                
                bar.progress(60, text="Verificando registos...")
                reg_ctrl = get_controle_employee_records_api(tenant_t2, token_controle_t2)
                
                func_ctrl = func_ctrl[~(func_ctrl['employee_code'].astype(str).str.contains('@mindsight', case=False, na=False) | func_ctrl[user_col].astype(str).str.contains('@mindsight', case=False, na=False))].copy()

                reg_ctrl['employee_code'] = reg_ctrl['employee_code'].astype(str).str.strip()
                status_por_func = reg_ctrl.groupby('employee_code')['end'].apply(lambda x: x.isna().sum() == 0)
                codigos_encerrados = status_por_func[status_por_func == True].index.tolist()

                codigos_sem_registro = list(set(func_ctrl['employee_code'].astype(str).str.strip().unique()) - set(reg_ctrl['employee_code'].unique()))
                codigos_desligados = list(set(codigos_encerrados + codigos_sem_registro))

                usernames_desl = func_ctrl[func_ctrl['employee_code'].astype(str).str.strip().isin(codigos_desligados)][user_col].dropna().astype(str).str.strip().unique()

                bar.progress(90, text="A gerar relatório...")
                df_desl_ativos = df_auth[(df_auth['username'].astype(str).str.strip().isin(usernames_desl)) & (df_auth['is_active'].isin([1, True, '1', 'True', 1.0]))].copy()

                st.session_state.t2_tenant = tenant_t2
                if df_desl_ativos.empty:
                    st.session_state.t2_empty = True
                    st.session_state.t2_msg = f"🎉 Validação concluída! Todos os desligados já estão inativados!"
                else:
                    st.session_state.t2_empty = False
                    st.session_state.t2_msg = f"Foram encontrados **{len(df_desl_ativos)}** usuários de colaboradores desligados ainda ATIVOS."
                    df_f = pd.DataFrame()
                    for col in ['id', 'first_name', 'last_name', 'email']: df_f[col] = df_desl_ativos[col]
                    df_f['username'] = df_desl_ativos['username'].astype(str).str.strip()
                    df_f['login_AD'] = 0
                    df_f['access_to_systems'] = ''
                    df_f['groups'] = ''
                    df_f['is_superuser'] = 0
                    df_f['is_staff'] = 0
                    df_f['is_active'] = 0
                    st.session_state.t2_df = df_f[['login_AD', 'access_to_systems', 'id', 'is_superuser', 'groups', 'first_name', 'last_name', 'is_staff', 'is_active', 'username', 'email']]

                st.session_state.t2_processed = True
                bar.progress(100, text="Concluído!")
                time.sleep(1)
                bar.empty()
                
            except Exception as e:
                st.error(f"Erro: {e}")

    if st.session_state.t2_processed:
        if st.session_state.t2_empty:
            st.success(st.session_state.t2_msg)
        else:
            st.warning(st.session_state.t2_msg)
            st.download_button("📥 Baixar Inativação (CSV)", data=st.session_state.t2_df.to_csv(index=False, sep=',', encoding='utf-8-sig'), file_name=f"{st.session_state.t2_tenant}_inativar_acessos.csv", mime="text/csv", key="down3")

# =============================================================================
# ABA 3: PARTICIPANTES (RODADA)
# =============================================================================
with tab3:
    st.header("Validação de participantes (rodada)")
    col1, col2 = st.columns(2)
    with col1:
        tenant_t3 = st.text_input("Tenant do Cliente", key="tenant_t3")
        token_perf_t3 = st.text_input("Token do Performance", key="token_perf_t3")
        token_controle_t3 = st.text_input("Token do Controle", key="token_controle_t3")
    with col2:
        rodada_t3 = st.text_input("ID da Rodada", key="rodada_t3")
        arquivo_auth_t3 = st.file_uploader("Upload Auth (.csv)", type=['csv'], key="arquivo_auth_t3")

    if st.button("Processar Validação Performance", key="btn_t3"):
        if not tenant_t3 or not token_perf_t3 or not token_controle_t3 or not rodada_t3 or not arquivo_auth_t3:
            st.error("Preencha todos os campos.")
        else:
            bar = st.progress(0, text="Obtendo rodadas...")
            try:
                df_rounds = ler_perfomance_evaluation_rounds(tenant_t3, token_perf_t3)
                nome_rodada = str(rodada_t3)
                
                if not df_rounds.empty and 'id' in df_rounds.columns and 'name' in df_rounds.columns:
                    match = df_rounds[df_rounds['id'].astype(str) == str(rodada_t3)]
                    if not match.empty:
                        nome_rodada = match['name'].iloc[0]

                bar.progress(20, text=f"Puxando usuários da rodada '{nome_rodada}'...")
                df_perf = ler_usuarios_performance(tenant_t3, token_perf_t3, rodada_t3)
                
                if df_perf.empty or 'username' not in df_perf.columns: st.stop()
                if 'name' not in df_perf.columns: df_perf['name'] = df_perf['username']

                mascara_m_perf = df_perf['username'].astype(str).str.contains('@mindsight', case=False, na=False)
                qtd_mindsight = mascara_m_perf.sum()
                df_perf = df_perf[~mascara_m_perf].copy()

                bar.progress(40, text="Processando Auth...")
                df_auth = ler_csv_seguro(arquivo_auth_t3)
                df_auth_limpo = df_auth.loc[~df_auth['username'].astype(str).str.contains('mindsight', na=False, case=False)].copy()
                df_auth_limpo['username'] = df_auth_limpo['username'].astype(str).str.strip()

                bar.progress(60, text="Obtendo Funcionários do Controle...")
                func_ctrl = get_controle_employees_api(tenant_t3, token_controle_t3)
                user_col = 'user.username' if 'user.username' in func_ctrl.columns else 'username'
                if user_col not in func_ctrl.columns: func_ctrl[user_col] = ''
                
                reg_ctrl = get_controle_employee_records_api(tenant_t3, token_controle_t3)
                reg_ctrl['start'] = pd.to_datetime(reg_ctrl['start'], errors='coerce')
                reg_ctrl['end'] = pd.to_datetime(reg_ctrl['end'], errors='coerce')
                reg_ctrl = reg_ctrl.sort_values(by=['employee_code', 'end', 'start'], ascending=[True, True, True], na_position='last')
                
                df_status = reg_ctrl.drop_duplicates(subset='employee_code', keep='last').copy()
                df_status['situacao_controle'] = np.where(df_status['end'].isna(), 'Ativo', 'Desligado')
                
                mapa_usr = func_ctrl.set_index('employee_code')[user_col].to_dict()
                df_status['user.username'] = df_status['employee_code'].map(mapa_usr).fillna('').astype(str).str.strip()

                bar.progress(80, text="Analisando resultados...")
                df_perf['username'] = df_perf['username'].astype(str).str.strip()
                
                df_val = df_perf[['username', 'name']].drop_duplicates().merge(df_auth_limpo[['username', 'id', 'email', 'first_name', 'last_name', 'is_active', 'access_to_systems', 'is_superuser']], on='username', how='left', indicator=True)
                df_val = df_val.merge(df_status[['user.username', 'situacao_controle', 'end']], left_on='username', right_on='user.username', how='left')

                st.session_state.t3_df_desligados = df_val[df_val['situacao_controle'] == 'Desligado'].copy()
                
                df_ativos = df_val[df_val['situacao_controle'] != 'Desligado'].copy()
                df_ativos[['acessos_novos', 'precisa_ajuste', 'motivo']] = df_ativos.apply(formatar_acesso_performance, axis=1)

                st.session_state.t3_len_total = len(df_perf)
                st.session_state.t3_qtd_mindsight = qtd_mindsight
                st.session_state.t3_tenant = tenant_t3
                st.session_state.t3_df_fix = df_ativos[df_ativos['precisa_ajuste'] == True].copy()
                st.session_state.t3_df_not_found = df_ativos[df_ativos['_merge'] == 'left_only'].copy()
                st.session_state.t3_processed = True
                
                bar.progress(100, text="Concluído!")
                time.sleep(1)
                bar.empty()
            except Exception as e:
                st.error(f"Erro: {e}")

    if st.session_state.t3_processed:
        st.success(f"✅ Total participantes: {st.session_state.t3_len_total} (Ignorando {st.session_state.t3_qtd_mindsight} @mindsight)")
        
        if not st.session_state.t3_df_not_found.empty:
            st.error(f"⚠️ **{len(st.session_state.t3_df_not_found)}** participantes ATIVOS na rodada NÃO existem no Auth!")
            st.download_button("📥 Baixar Não Encontrados (Excel)", data=gerar_excel(st.session_state.t3_df_not_found[['username', 'motivo']]), file_name=f"{st.session_state.t3_tenant}_nao_encontrados_auth.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="down4")
        
        if not st.session_state.t3_df_fix.empty:
            df_final_3 = montar_df_upload(st.session_state.t3_df_fix, 'acessos_novos', incluir_motivo=True)
            st.write("### Ajustes Necessários (Adicionar Performance / Ativar)")
            st.download_button("📥 Baixar Correção Auth (CSV)", data=df_final_3.to_csv(index=False, sep=',', encoding='utf-8-sig'), file_name=f"{st.session_state.t3_tenant}_correcao_performance.csv", mime="text/csv", key="down5")
        else:
            st.info("Nenhum ajuste necessário no Auth.")
            
        if not st.session_state.t3_df_desligados.empty:
            st.error(f"🚨 Participantes DESLIGADOS no Controle: {len(st.session_state.t3_df_desligados)}")
            df_show = st.session_state.t3_df_desligados[['name', 'username', 'end']].copy()
            df_show.columns = ['Nome do funcionário', 'Usuário', 'Data de Desligamento']
            df_show['Data de Desligamento'] = df_show['Data de Desligamento'].dt.strftime('%d/%m/%Y')
            st.download_button("📥 Baixar Lista de Desligados (Excel)", data=gerar_excel(df_show), file_name=f"{st.session_state.t3_tenant}_participantes_desligados.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="down6")

# =============================================================================
# ABA 4: USUÁRIOS ENTRE MÓDULOS
# =============================================================================
with tab4:
    st.header("Validação de usuários entre módulos")
    col1, col2 = st.columns(2)
    with col1:
        tenant_t4 = st.text_input("Tenant do Cliente", key="tenant_t4")
        token_controle_t4 = st.text_input("Token do Controle", key="token_controle_t4")
    with col2:
        token_full_t4 = st.text_input("Token do Full", key="token_full_t4")
        arquivo_auth_t4 = st.file_uploader("Upload Auth (.csv)", type=['csv'], key="arquivo_auth_t4")

    if st.button("Processar Validações de Módulos", key="btn_t4"):
        if not tenant_t4 or not token_controle_t4 or not token_full_t4 or not arquivo_auth_t4:
            st.error("Preencha todos os campos.")
        elif st.session_state['cookies_sessao'] is None:
            st.error("⚠️ Faça o login na barra lateral primeiro.")
        else:
            bar = st.progress(0, text="Iniciando varredura...")
            try:
                bar.progress(10, text="1/5 - Lendo Auth...")
                df_auth = ler_csv_seguro(arquivo_auth_t4)
                if 'username' not in df_auth.columns: st.stop()
                df_auth = df_auth.loc[~df_auth['username'].astype(str).str.contains('@mindsight', case=False, na=False)].copy()
                
                for c in ['username', 'email']:
                    if c in df_auth.columns: df_auth[c] = df_auth[c].astype(str).str.strip().str.lower()
                
                bar.progress(30, text="2/5 - Obtendo Funcionários do Controle...")
                df_controle = ler_usuarios_controle(tenant_t4, token_controle_t4)
                if not df_controle.empty:
                    df_controle = df_controle.loc[~df_controle['username'].astype(str).str.contains('@mindsight', case=False, na=False)].copy()
                    for c in ['username', 'email']: 
                        if c in df_controle.columns: df_controle[c] = df_controle[c].astype(str).str.strip().str.lower()
                
                bar.progress(50, text="3/5 - Obtendo Funcionários do People Hub...")
                df_full = ler_usuarios_full(tenant_t4, token_full_t4)
                if not df_full.empty:
                    df_full = df_full.loc[~df_full['username'].astype(str).str.contains('@mindsight', case=False, na=False)].copy()
                    for c in ['username', 'email']: 
                        if c in df_full.columns: df_full[c] = df_full[c].astype(str).str.strip().str.lower()

                bar.progress(70, text="4/5 - Obtendo Participantes do Performance...")
                df_perf = extrair_django_admin(f"https://performance.mindsight.com.br/{tenant_t4}/staff/accounts/user/", st.session_state['cookies_sessao'])
                if not df_perf.empty:
                    df_perf = df_perf.loc[~df_perf['username'].astype(str).str.contains('@mindsight', case=False, na=False)].copy()
                    for c in ['username', 'email']: 
                        if c in df_perf.columns: df_perf[c] = df_perf[c].astype(str).str.strip().str.lower()

                bar.progress(85, text="5/5 - Obtendo Persons do Metas...")
                df_metas = extrair_django_admin(f"https://acompanhamento.mindsight.com.br/{tenant_t4}/admin/accounts/user/", st.session_state['cookies_sessao'])
                if not df_metas.empty:
                    df_metas = df_metas.loc[~df_metas['username'].astype(str).str.contains('@mindsight', case=False, na=False)].copy()
                    for c in ['username', 'email']: 
                        if c in df_metas.columns: df_metas[c] = df_metas[c].astype(str).str.strip().str.lower()

                bar.progress(95, text="Cruzando dados...")
                df_val1 = df_auth[['username', 'email', 'first_name', 'last_name']].copy()
                df_val1['Auth'] = 'Sim'
                for n, d in [('Controle', df_controle), ('Full', df_full), ('Performance', df_perf), ('Metas', df_metas)]:
                    df_val1[n] = 'Sim' if not d.empty else 'Base Vazia'
                    if not d.empty: df_val1[n] = np.where(df_val1['username'].isin(d['username']), 'Sim', 'Não')
                
                df_val1['Modulos_Ausentes'] = df_val1.apply(lambda r: ", ".join([m for m in ['Controle', 'Full', 'Performance', 'Metas'] if r[m] == 'Não']) or "Nenhum", axis=1)

                todos = []
                for n, d in {'Auth': df_auth, 'Controle': df_controle, 'Full': df_full, 'Performance': df_perf, 'Metas': df_metas}.items():
                    if not d.empty and 'first_name' in d.columns and 'last_name' in d.columns:
                        t = d[['username', 'email', 'first_name', 'last_name']].copy()
                        t['Modulo'] = n
                        todos.append(t)
                        
                df_val2 = pd.DataFrame()
                if todos:
                    df_t = pd.concat(todos, ignore_index=True)
                    df_t['nome'] = (df_t['first_name'].astype(str).str.strip() + " " + df_t['last_name'].astype(str).str.strip()).str.lower()
                    df_t = df_t[df_t['nome'].str.strip() != ""]
                    
                    agg = df_t.groupby('nome').agg({
                        'username': lambda x: ", ".join(sorted(set(str(i) for i in x if str(i).strip().lower() not in ['nan','none','','-']))), 
                        'email': lambda x: ", ".join(sorted(set(str(i) for i in x if str(i).strip().lower() not in ['nan','none','','-']))), 
                        'Modulo': lambda x: ", ".join(sorted(set(str(i) for i in x)))
                    }).reset_index()
                    
                    df_val2 = agg[(agg['username'].astype(str).str.contains(',')) | (agg['email'].astype(str).str.contains(','))].copy()
                    df_val2.rename(columns={'nome': 'Nome Completo', 'username': 'Usernames Associados', 'email': 'E-mails Associados', 'Modulo': 'Módulos'}, inplace=True)

                div_list = []
                da = df_auth[~df_auth['email'].isin(['nan', 'none', '', '-'])].copy()
                da['n'] = da['first_name'].astype(str) + " " + da['last_name'].astype(str)
                for n, d in {'Controle': df_controle, 'Full': df_full, 'Performance': df_perf, 'Metas': df_metas}.items():
                    if d.empty or 'email' not in d.columns: continue
                    db = d[~d['email'].astype(str).str.lower().isin(['nan', 'none', '', '-'])].copy()
                    db['n2'] = db['first_name'].astype(str) + " " + db['last_name'].astype(str) if 'first_name' in db.columns else 'N/A'
                    m = da.merge(db, on='email', suffixes=('_auth', '_mod'))
                    diff = m[m['username_auth'] != m['username_mod']].copy()
                    if not diff.empty:
                        diff['Modulo_Divergente'] = n
                        diff = diff.rename(columns={'email':'Email', 'username_auth':'Username_Auth', 'username_mod':'Username_Modulo', 'n':'Nome_Auth', 'n2':'Nome_Modulo'})
                        div_list.append(diff[['Email', 'Username_Auth', 'Username_Modulo', 'Nome_Auth', 'Nome_Modulo', 'Modulo_Divergente']])
                        
                df_val3 = pd.concat(div_list, ignore_index=True) if div_list else pd.DataFrame(columns=['Email'])

                df_val4 = pd.DataFrame({'Erro': ['A planilha do Auth não possui UUID.']})
                if 'uuid' in df_auth.columns:
                    df_val4 = df_auth[['username', 'uuid']].copy().rename(columns={'uuid': 'UUID_Auth'})
                    df_val4['UUID_Auth'] = df_val4['UUID_Auth'].astype(str).str.strip().str.lower()
                    for n, d in {'Controle': df_controle, 'Full': df_full}.items():
                        if d.empty or 'uuid' not in d.columns: continue
                        m_u = d.set_index('username')['uuid'].astype(str).str.strip().str.lower().to_dict()
                        df_val4[f"UUID_{n}"] = df_val4['username'].map(m_u)
                        df_val4[f"Match_{n}"] = np.where(df_val4[f"UUID_{n}"].isna(), 'Não Existe', np.where(df_val4['UUID_Auth'] == df_val4[f"UUID_{n}"], 'OK', 'Divergente'))

                st.session_state.t4_tenant = tenant_t4
                st.session_state.t4_val1_ok = df_val1[df_val1['Modulos_Ausentes'] == 'Nenhum'].copy()
                st.session_state.t4_val1_faltantes = df_val1[df_val1['Modulos_Ausentes'] != 'Nenhum'].copy()
                st.session_state.t4_val2 = df_val2
                st.session_state.t4_val3 = df_val3
                st.session_state.t4_val4 = df_val4
                st.session_state.t4_processed = True
                
                bar.progress(100, text="Concluído!")
                time.sleep(1)
                bar.empty()
            except Exception as e:
                st.error(f"Erro: {e}")

    if st.session_state.t4_processed:
        st.success(f"✅ Análise de Módulos (Usuários) para {st.session_state.t4_tenant}!")
        st.write("---")
        st.subheader("1ª Validação: Presença nos Módulos")
        if not st.session_state.t4_val1_ok.empty or not st.session_state.t4_val1_faltantes.empty:
            st.download_button("📥 Baixar Planilha Presença (Excel 2 Abas)", data=gerar_excel_multi_abas({'Presentes em Todos': st.session_state.t4_val1_ok, 'Faltando em Módulos': st.session_state.t4_val1_faltantes}), file_name=f"{st.session_state.t4_tenant}_validacao_presenca.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="down_v1")

        st.write("---")
        st.subheader("2ª Validação: Usuários Possivelmente Duplicados")
        if not st.session_state.t4_val2.empty:
            st.download_button("📥 Baixar Planilha Duplicados (Excel)", data=gerar_excel(st.session_state.t4_val2), file_name=f"{st.session_state.t4_tenant}_validacao_duplicados.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="down_v2")

        st.write("---")
        st.subheader("3ª Validação: Divergências de Username")
        if not st.session_state.t4_val3.empty:
            st.download_button("📥 Baixar Planilha Divergências (Excel)", data=gerar_excel(st.session_state.t4_val3), file_name=f"{st.session_state.t4_tenant}_validacao_divergencias.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="down_v3")

        st.write("---")
        st.subheader("4ª Validação: Conferência de UUIDs")
        if 'Erro' not in st.session_state.t4_val4.columns:
            st.download_button("📥 Baixar Planilha UUIDs (Excel)", data=gerar_excel(st.session_state.t4_val4), file_name=f"{st.session_state.t4_tenant}_validacao_uuids.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="down_v4")

# =============================================================================
# ABA 5: FUNCIONÁRIOS ENTRE MÓDULOS 
# =============================================================================
with tab5:
    st.header("Validação de funcionários entre módulos")
    
    col1, col2 = st.columns(2)
    with col1:
        tenant_t5 = st.text_input("Tenant do Cliente", key="tenant_t5")
        token_controle_t5 = st.text_input("Token Controle", key="tk_ctrl_t5")
    with col2:
        token_full_t5 = st.text_input("Token People Hub (Full)", key="tk_full_t5")

    st.write("---")
    st.subheader("1. Controle e People Hub")
    if st.button("Baixar Dados Controle e Hub", key="btn_t5_1"):
        if not tenant_t5 or not token_controle_t5 or not token_full_t5:
            st.error("Preencha todos os campos superiores.")
        else:
            bar1 = st.progress(10, text="Obtendo Funcionários do Controle...")
            
            df_ctrl = func_api_get_base_parallel('controle', tenant_t5, token_controle_t5, 'employees', extra_param='&expand=~all')
            df_ctrl = df_ctrl[~df_ctrl['employee_code'].astype(str).str.contains('@mindsight', case=False, na=False)].copy()
            usr_col = 'user.username' if 'user.username' in df_ctrl.columns else 'username'
            df_c = df_ctrl[['employee_code', usr_col, 'uuid', 'name']].rename(columns={usr_col: 'Username_Controle', 'uuid': 'UUID_Controle'}).copy()
            st.session_state['t5_df_ctrl'] = df_c
            
            bar1.progress(60, text="Obtendo Funcionários do People Hub...")
            df_hub_people = func_api_get_base_parallel('hub', tenant_t5, token_full_t5, 'people', extra_param='&expand=~all')
            df_hub_users = ler_usuarios_full(tenant_t5, token_full_t5)
            
            def extract_user_id(url):
                try:
                    if pd.isna(url): return None
                    return str(url).strip('/').split('/')[-1]
                except: return None

            if not df_hub_people.empty and not df_hub_users.empty and 'username' in df_hub_users.columns and 'id' in df_hub_users.columns:
                df_hub_people['user_id'] = df_hub_people['user'].apply(extract_user_id)
                df_hub_users['id'] = df_hub_users['id'].astype(str)
                df_hub_merged = df_hub_people.merge(df_hub_users[['id', 'username']], left_on='user_id', right_on='id', how='left')
                df_h = df_hub_merged[['registration_code', 'username', 'uuid']].rename(columns={'registration_code': 'employee_code', 'username': 'Username_Hub', 'uuid': 'UUID_Hub'}).copy()
            else:
                df_h = pd.DataFrame(columns=['employee_code', 'Username_Hub', 'UUID_Hub'])
            st.session_state['t5_df_hub'] = df_h
            
            bar1.progress(100, text="Concluído!")
            time.sleep(1)
            bar1.empty()

    if not st.session_state['t5_df_ctrl'].empty:
        st.success("Dados do Controle salvos na memória!")
        st.markdown(st.session_state['t5_df_ctrl'].head(5).to_html(index=False), unsafe_allow_html=True)
        
    if not st.session_state['t5_df_hub'].empty:
        st.success("Dados do People Hub salvos na memória!")
        st.markdown(st.session_state['t5_df_hub'].head(5).to_html(index=False), unsafe_allow_html=True)
    st.write("---")
    st.subheader("2. Usuários e Planilha do Metas")
    if st.button("Extrair Usuários do Metas", key="btn_t5_2"):
        if not tenant_t5 or st.session_state.get('cookies_sessao') is None:
            st.error("Preencha o Tenant e garanta que fez login na barra lateral.")
        else:
            bar2 = st.progress(50, text="Obtendo lista de utilizadores do Metas...")
            df_m_users = extrair_django_admin_users_com_id(f"https://acompanhamento.mindsight.com.br/{tenant_t5}/admin/accounts/user/", st.session_state['cookies_sessao'])
            st.session_state['t5_df_metas_users'] = df_m_users
            bar2.progress(100, text="Concluído!")
            time.sleep(1)
            bar2.empty()
            
    if not st.session_state['t5_df_metas_users'].empty:
        st.success("Usuários do Metas extraídos e salvos na memória!")
        st.markdown(st.session_state['t5_df_metas_users'].head(5).to_html(index=False), unsafe_allow_html=True)
        
    arquivo_metas_t5 = st.file_uploader("Upload da Planilha exportada de Persons (.csv)", type=['csv'], key="arquivo_metas_t5")

    st.write("---")
    st.subheader("3. Scraping Performance e Cruzamento Final")
    if st.button("Iniciar Scraping Performance e Gerar Relatório", key="btn_t5_3"):
        if st.session_state['t5_df_ctrl'].empty or st.session_state['t5_df_hub'].empty:
            st.error("Execute o Passo 1 primeiro (Baixar Dados Controle e Hub).")
        elif arquivo_metas_t5 is None or st.session_state['t5_df_metas_users'].empty:
            st.error("Execute o Passo 2: Extraia os Usuários do Metas e faça o upload da planilha Persons.")
        elif st.session_state.get('cookies_sessao') is None:
            st.error("Faça o login na barra lateral antes de prosseguir.")
        else:
            bar3 = st.progress(0, text="Formatando dados do Metas...")
            
            df_m_csv = ler_csv_seguro(arquivo_metas_t5)
            mapa_metas_users = st.session_state['t5_df_metas_users'].set_index('id_user')['username'].to_dict()
            
            if 'user' in df_m_csv.columns:
                df_m_csv['Username_Metas'] = df_m_csv['user'].astype(str).map(mapa_metas_users)
            else:
                df_m_csv['Username_Metas'] = ''
                
            key_col = 'key' if 'key' in df_m_csv.columns else ('registration_code' if 'registration_code' in df_m_csv.columns else None)
            uuid_col = 'uuid' if 'uuid' in df_m_csv.columns else None
            
            if key_col and uuid_col:
                df_m = df_m_csv[[key_col, 'Username_Metas', uuid_col]].rename(columns={key_col: 'employee_code', uuid_col: 'UUID_Metas'})
            else:
                df_m = pd.DataFrame(columns=['employee_code', 'Username_Metas', 'UUID_Metas'])
                st.warning("O arquivo Metas não contém as colunas 'key' ou 'uuid' esperadas.")
            
            bar3.progress(20, text="Iniciando Scraping do Performance...")
            df_p_scrap = extrair_performance_selenium_original(tenant_t5, st.session_state['cookies_sessao'], bar3)
            
            df_perf_users_api = func_api_get_base_parallel('performance', tenant_t5, token_controle_t5, 'users')
            mapa_perf_users = {}
            if not df_perf_users_api.empty and 'id' in df_perf_users_api.columns and 'username' in df_perf_users_api.columns:
                mapa_perf_users = df_perf_users_api.set_index('id')['username'].to_dict()
                
            def get_perf_username(row):
                if row.get('user_id') and str(row['user_id']).isdigit(): return mapa_perf_users.get(int(row['user_id']), '')
                return ''
                
            if not df_p_scrap.empty:
                df_p_scrap['Username_Perf'] = df_p_scrap.apply(get_perf_username, axis=1)
                df_p = df_p_scrap[['employee_code', 'Username_Perf', 'UUID_Perf']]
            else:
                df_p = pd.DataFrame(columns=['employee_code', 'Username_Perf', 'UUID_Perf'])
            
            bar3.progress(90, text="Cruzando toda a estrutura...")
            df_c = st.session_state['t5_df_ctrl']
            df_h = st.session_state['t5_df_hub']
            
            for d in [df_c, df_h, df_m, df_p]: 
                if not d.empty and 'employee_code' in d.columns:
                    d['employee_code'] = d['employee_code'].astype(str).str.strip().str.lower()
            
            df_final = df_c.merge(df_h, on='employee_code', how='left').merge(df_m, on='employee_code', how='left').merge(df_p, on='employee_code', how='left')
            
            for mod in ['Hub', 'Metas', 'Perf']:
                if f"Username_{mod}" not in df_final.columns: df_final[f"Username_{mod}"] = "Não Encontrado"
                if f"UUID_{mod}" not in df_final.columns: df_final[f"UUID_{mod}"] = "Não Encontrado"
                
                df_final[f"Username_{mod}"] = df_final[f"Username_{mod}"].replace('', "Não Encontrado").fillna("Não Encontrado")
                df_final[f"UUID_{mod}"] = df_final[f"UUID_{mod}"].replace('', "Não Encontrado").fillna("Não Encontrado")
                
                df_final[f"Match_User_{mod}"] = np.where(df_final[f"Username_{mod}"] == "Não Encontrado", "-", np.where(df_final['Username_Controle'] == df_final[f"Username_{mod}"], "OK", "Divergente"))
                df_final[f"Match_UUID_{mod}"] = np.where(df_final[f"UUID_{mod}"] == "Não Encontrado", "-", np.where(df_final['UUID_Controle'] == df_final[f"UUID_{mod}"], "OK", "Divergente"))

            st.session_state.t5_final = df_final
            st.session_state.t5_tenant = tenant_t5
            
            bar3.progress(100, text="Concluído!")
            time.sleep(1)
            bar3.empty()

    if not st.session_state.t5_final.empty:
        st.success(f"✅ Análise Estrutural Concluída para {st.session_state.t5_tenant}!")
        st.markdown(st.session_state.t5_final.head(20).to_html(index=False), unsafe_allow_html=True)
        st.download_button("📥 Baixar Análise Completa (Excel)", data=gerar_excel(st.session_state.t5_final), file_name=f"{st.session_state.t5_tenant}_funcionarios_cross_check.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="down_t5")
