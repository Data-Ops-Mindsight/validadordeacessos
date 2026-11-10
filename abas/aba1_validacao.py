import streamlit as st
import pandas as pd
import time
import zipfile
import io

# Como o ficheiro será executado a partir do app.py (na raiz), importamos diretamente
from functions import *

def render_aba1():
    st.header("Validação de Acessos - Colaboradores Ativos")
    
    # --- SEÇÃO 1: CREDENCIAIS ---
    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2, c3 = st.columns(3)
    tenant_t1 = c1.text_input("Tenant do Cliente", key="tenant_t1", placeholder="Ex: empresa123")
    token_controle_t1 = c2.text_input("Token do Controle", key="token_controle_t1")
    token_full_t1 = c3.text_input("Token do Full (Opcional)", key="token_full_t1")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- SEÇÃO 2: REGRAS GERAIS DE ACESSO ---
    st.markdown("### ⚙️ Regras Gerais de Acesso")
    c4, c5, c6 = st.columns(3)
    acesso_full_t1 = c4.radio("Acesso ao People Hub (Full):", options=['Todos os usuários', 'Gestores', 'Nenhum usuário'], index=2, key="acesso_full_t1")
    acesso_ats_t1 = c5.radio("Acesso ao ATS:", options=['Todos os usuários', 'Gestores', 'Nenhum usuário'], index=2, key="acesso_ats_t1")
    validacao_t1 = c6.radio("Módulos de Desempenho:", options=['Validação padrão (metas, perfomance)', 'Validar somente metas', 'Validar somente performance'], key="validacao_t1")

    st.markdown("<br>", unsafe_allow_html=True)

    # --- SEÇÃO 3: ACESSOS RESTRITOS ---
    st.markdown("### 🎯 Acessos Restritos (Listas Específicas)")
    st.info("💡 **Dica:** Utilize estes campos se um módulo for de uso restrito. Por exemplo: se apenas dois *sponsors* utilizam o Controle (Organograma), digite os seus *usernames* abaixo e assinale a opção **'Remover o acesso de quem NÃO está autorizado'**. Desta forma, a ferramenta remove o acesso a todos os outros funcionários.")
    
    c7, c8, c9 = st.columns(3)
    
    with c7:
        acesso_controle_t1 = st.text_area("Lista Restrita: Controle", help="Coloque aqui os usuários que DEVEM ter acesso. Separados por vírgula.", key="acesso_controle_t1", placeholder="Ex: joao.silva, maria.santos")
        rem_ctrl_t1 = st.checkbox("Remover o acesso de quem NÃO está autorizado", key="rem_ctrl_t1")

    with c8:
        acesso_especifico_ats_t1 = st.text_area("Lista Restrita: ATS", help="Coloque aqui os usuários que DEVEM ter acesso. Separados por vírgula.", key="acesso_especifico_ats_t1", placeholder="Ex: pedro.costa, ana.lima")
        rem_ats_t1 = st.checkbox("Remover o acesso de quem NÃO está autorizado ", key="rem_ats_t1")
        
    with c9:
        acesso_especifico_hub_t1 = st.text_area("Lista Restrita: People Hub", help="Coloque aqui os usuários que DEVEM ter acesso. Separados por vírgula.", key="acesso_especifico_hub_t1", placeholder="Ex: carlos.souza, julia.melo")
        rem_hub_t1 = st.checkbox("Remover o acesso de quem NÃO está autorizado  ", key="rem_hub_t1")

    st.markdown("<br>", unsafe_allow_html=True)

    # --- SEÇÃO 4: BASE AUTH E PROCESSAMENTO ---
    st.markdown("### 📁 Base de Usuários (Auth)")
    arquivo_auth_t1 = st.file_uploader("Faça o upload da base exportada do Auth (.csv)", type=['csv'], key="arquivo_auth_t1")
    
    chunk_size = st.number_input("Dividir arquivos finais de quantos em quantos usuários? (Deixe 0 para não dividir)", min_value=0, value=0, step=100)

    if st.button("Processar Validação", key="btn_t1"):
        if not tenant_t1 or not token_controle_t1 or not arquivo_auth_t1:
            st.error("Preencha o Tenant, o Token do Controle e faça o upload da base.")
        else:
            bar = st.progress(0, text="Iniciando o processamento...")
            try:
                df_usuarios_auth = ler_csv_seguro(arquivo_auth_t1)
                if 'username' not in df_usuarios_auth.columns:
                    st.error("Erro: A base não possui a coluna 'username'.")
                    st.stop()
                
                bar.progress(10, text="Obtendo Funcionários do Controle...")
                funcionarios_controle = get_controle_employees_api(tenant_t1, token_controle_t1)
                user_col_t1 = 'user.username' if 'user.username' in funcionarios_controle.columns else 'username'
                if user_col_t1 not in funcionarios_controle.columns: funcionarios_controle[user_col_t1] = ''

                bar.progress(30, text="Obtendo registros do Controle...")
                reg_funcionarios_controle = get_controle_employee_records_api(tenant_t1, token_controle_t1)
                
                gestores_funcionario_controle = pd.DataFrame()
                if acesso_full_t1 == 'Gestores' or acesso_ats_t1 == 'Gestores':
                    gestores_funcionario_controle = get_controle_employee_managers_api(tenant_t1, token_controle_t1)

                df_usuarios_full = pd.DataFrame()
                if token_full_t1:
                    df_usuarios_full = ler_usuarios_full(tenant_t1, token_full_t1)

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

                # Merge principal com os dados do Auth
                df_validacao = df_validacao.merge(df_usuarios_auth_limpo[['username', 'access_to_systems', 'is_active']], left_on='user.username', right_on='username', how='left')
                
                # Merge com os dados do Hub (Corrigido para evitar duplicação da coluna username)
                if token_full_t1 and not df_usuarios_full.empty:
                    if 'username' in df_usuarios_full.columns:
                        df_usuarios_full_limpo = df_usuarios_full[['username', 'is_active']].copy()
                        df_usuarios_full_limpo['username'] = df_usuarios_full_limpo['username'].astype(str).str.strip()
                        df_usuarios_full_limpo.rename(columns={'is_active': 'is_active_hub'}, inplace=True)
                        
                        # O parâmetro suffixes=('', '_hub_drop') evita que o 'username' original vire 'username_x'
                        df_validacao = df_validacao.merge(df_usuarios_full_limpo, left_on='user.username', right_on='username', how='left', suffixes=('', '_hub_drop'))
                        df_validacao['is_active_full'] = df_validacao['is_active_hub'].fillna(False)
                    else:
                        df_validacao['is_active_full'] = True
                else:
                    df_validacao['is_active_full'] = True

                if not df_gestores_ativos.empty:
                    df_validacao['sou_gestor'] = df_validacao['employee_code'].isin(df_gestores_ativos['manager_code'].dropna().unique())
                else:
                    df_validacao['sou_gestor'] = False

                bar.progress(90, text="Gerando base de correção...")
                df_add_acessos = df_usuarios_auth_limpo.merge(df_validacao[['username', 'sou_gestor', 'is_active_full']], on='username', how='inner').copy()
                
                lista_acessos_controle = [u.strip() for u in acesso_controle_t1.split(',')] if acesso_controle_t1.strip() else []
                lista_acessos_ats = [u.strip() for u in acesso_especifico_ats_t1.split(',')] if acesso_especifico_ats_t1.strip() else []
                lista_acessos_hub = [u.strip() for u in acesso_especifico_hub_t1.split(',')] if acesso_especifico_hub_t1.strip() else []
                
                df_add_acessos[['acessos_csv1', 'acessos_csv2', 'vai_pro_csv1', 'vai_pro_csv2', 'motivo']] = df_add_acessos.apply(
                    lambda row: formatar_acessos_duplo(row, acesso_full_t1, lista_acessos_controle, bool(token_full_t1), validacao_t1, acesso_ats_t1, lista_acessos_ats, lista_acessos_hub, rem_ctrl_t1, rem_ats_t1, rem_hub_t1), axis=1
                )

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
            st.info("💡 **O que é este passo?** Esta base contém os usuários que precisam ter seus acessos atualizados (ex: adicionar Metas, Performance, ATS, Organograma) ou que estão inativos no Auth e precisam ser reativados. **Suba este arquivo primeiro.**")
            
            motivos = df_final_1['motivo_ajuste'].value_counts().reset_index()
            motivos.columns = ['Motivo', 'Quantidade']
            st.markdown(motivos.to_html(index=False), unsafe_allow_html=True)
            
            st.write("<br>", unsafe_allow_html=True)
            with st.expander("👁️ Ver lista de usuários impactados e seus ajustes"):
                st.dataframe(df_final_1[['username', 'email', 'first_name', 'last_name', 'motivo_ajuste']], use_container_width=True)
            
            if chunk_size > 0 and len(df_final_1) > chunk_size:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    for i in range(0, len(df_final_1), int(chunk_size)):
                        chunk = df_final_1.iloc[i:i + int(chunk_size)]
                        csv_bytes = chunk.to_csv(index=False, sep=',', encoding='utf-8-sig')
                        zip_file.writestr(f"{st.session_state.t1_tenant}_ajustes_parte_{i//int(chunk_size) + 1}.csv", csv_bytes)
                st.download_button("📦 Baixar Arquivos Fatiados (ZIP)", data=zip_buffer.getvalue(), file_name=f"{st.session_state.t1_tenant}_ajustes_acessos.zip", mime="application/zip", key="down1_zip")
            else:
                st.download_button("📥 Baixar Base PASSO 1 (CSV)", data=df_final_1.to_csv(index=False, sep=',', encoding='utf-8-sig'), file_name=f"{st.session_state.t1_tenant}_ajustes_acessos.csv", mime="text/csv", key="down1")
        else:
            st.info("Nenhum ajuste necessário para o PASSO 1.")
            
        if not st.session_state.t1_df2.empty:
            df_final_2 = montar_df_upload(st.session_state.t1_df2, 'acessos_csv2', False)
            st.write("### PASSO 2: Reativação do Full")
            st.info("💡 **O que é este passo?** Esta base serve exclusivamente para o *Trick* do People Hub. Ela pega os usuários que estavam inativos no Hub e re-adiciona o acesso 'full' (que foi removido no Passo 1) para forçar a sincronização. **Suba este arquivo APENAS DEPOIS de concluir o Passo 1.**")
            
            if chunk_size > 0 and len(df_final_2) > chunk_size:
                zip_buffer2 = io.BytesIO()
                with zipfile.ZipFile(zip_buffer2, "w", zipfile.ZIP_DEFLATED) as zip_file2:
                    for i in range(0, len(df_final_2), int(chunk_size)):
                        chunk2 = df_final_2.iloc[i:i + int(chunk_size)]
                        csv_bytes2 = chunk2.to_csv(index=False, sep=',', encoding='utf-8-sig')
                        zip_file2.writestr(f"{st.session_state.t1_tenant}_reativacao_parte_{i//int(chunk_size) + 1}.csv", csv_bytes2)
                st.download_button("📦 Baixar Arquivos Fatiados (ZIP)", data=zip_buffer2.getvalue(), file_name=f"{st.session_state.t1_tenant}_reativacao_full.zip", mime="application/zip", key="down2_zip")
            else:
                st.download_button("📥 Baixar Base PASSO 2 (CSV)", data=df_final_2.to_csv(index=False, sep=',', encoding='utf-8-sig'), file_name=f"{st.session_state.t1_tenant}_reativacao_full.csv", mime="text/csv", key="down2")
        else:
            st.info("Nenhum ajuste necessário para o PASSO 2.")