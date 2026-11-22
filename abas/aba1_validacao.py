"""
Aba 1 - Validação de Acessos dos colaboradores ATIVOS.

Fluxo da aba:
  1. O usuário informa tenant, tokens e as regras de acesso desejadas.
  2. Faz upload da base de usuários exportada do Auth (.csv) e, opcionalmente,
     dos CSVs de usuários do Performance e do Metas (favorito "Exportar usuários").
  3. Ao clicar em "Processar Validação", a ferramenta:
       - busca no Controle quem está ativo (e, se preciso, quem é gestor);
       - busca no People Hub (Full) quem já está ativo lá (se houver token);
       - cruza tudo com a base do Auth e aplica as regras;
  4. Gera dois arquivos para upload no Auth:
       - PASSO 1: ajustes de acessos e reativação de usuários;
       - PASSO 2: "tricks" que completam o Passo 1:
           * reativação: o módulo (full, metas ou performance) sai no Passo 1 e
             volta no Passo 2, para quem está INATIVO no módulo;
           * nome: o first_name sobe alterado no Passo 1 e volta ao original no
             Passo 2, para quem NÃO EXISTE no Metas/Performance.
"""

import streamlit as st
import pandas as pd
import time
import zipfile
import io

# Como o arquivo é executado a partir do app.py (na raiz), importamos diretamente
from functions import *
from abas.exportacao_admin import ler_csv_modulo, render_instrucoes_exportacao


def mapa_status_modulo(df_modulo):
    """
    A partir do CSV de um módulo (Metas ou Performance), devolve um dicionário
    username (minúsculo) -> 'ativo' ou 'inativo'. Quem não estiver no dicionário
    não existe no módulo.
    """
    df = df_modulo.copy()
    df['_usuario'] = df['username'].astype(str).str.strip().str.lower()
    df['_ativo'] = df['is_active'].astype(str).str.strip().str.lower().isin(['1', '1.0', 'true', 'sim'])
    ativos = df.groupby('_usuario')['_ativo'].any()   # se houver duplicado, vale o ativo
    return {u: (STATUS_ATIVO if a else STATUS_INATIVO) for u, a in ativos.items()}


def gerar_downloads(df_final, tenant, sufixo, sufixo_parte, rotulo_csv, chave, chunk_size):
    """
    Mostra o botão de download do arquivo final. Se 'chunk_size' for maior que
    zero e a base for maior que isso, divide em vários CSVs dentro de um ZIP.
    """
    if chunk_size > 0 and len(df_final) > chunk_size:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for i in range(0, len(df_final), int(chunk_size)):
                chunk = df_final.iloc[i:i + int(chunk_size)]
                csv_bytes = chunk.to_csv(index=False, sep=',', encoding='utf-8-sig')
                zip_file.writestr(f"{tenant}_{sufixo_parte}_parte_{i // int(chunk_size) + 1}.csv", csv_bytes)
        st.download_button("📦 Baixar Arquivos Fatiados (ZIP)", data=zip_buffer.getvalue(),
                           file_name=f"{tenant}_{sufixo}.zip", mime="application/zip", key=f"{chave}_zip")
    else:
        st.download_button(rotulo_csv, data=df_final.to_csv(index=False, sep=',', encoding='utf-8-sig'),
                           file_name=f"{tenant}_{sufixo}.csv", mime="text/csv", key=chave)


def render_aba1():
    st.header("Validação de Acessos - Colaboradores Ativos")

    # Explicação da regra e do que os arquivos gerados fazem
    st.info(
        "💡 **Quem é considerado ativo?** O colaborador cujo **registro de funcionário mais recente "
        "no Controle está aberto** (sem data de demissão). Só entram na validação os usuários do Auth "
        "que pertencem a esses colaboradores ativos; os demais não são alterados (os desligados são "
        "tratados na aba **Inativar (Desligados)**).\n\n"
        "🚫 **Funcionários da Mindsight são desconsiderados** nesta validação.\n\n"
        "✅ **O que é validado em cada usuário:**\n"
        "- **Ativação:** se o usuário estiver inativo no Auth, ele é reativado;\n"
        "- **Metas e Performance:** adiciona os módulos conforme a opção de *Módulos de Desempenho*;\n"
        "- **Organograma (Controle):** adiciona para quem está na lista restrita do Controle;\n"
        "- **ATS:** adiciona para os gestores ou para os usuários específicos, conforme a opção escolhida;\n"
        "- **People Hub (Full):** só é avaliado se o token do Full for informado; adiciona para todos, "
        "para os gestores e/ou para a lista restrita, conforme as opções.\n\n"
        "Nos módulos com a opção **'Remover o acesso de quem NÃO está autorizado'** marcada, o acesso "
        "também é retirado de quem não se encaixa na regra.\n\n"
        "📄 **O que os arquivos gerados fazem?** Trazem apenas os usuários que precisam de algum ajuste:\n"
        "- **Passo 1:** atualiza a coluna `access_to_systems` com os módulos corretos e deixa o usuário "
        "ativo no Auth (`1` na coluna `is_active`). A coluna `motivo_ajuste` mostra o que mudou;\n"
        "- **Passo 2:** só traz quem precisa de um dos *tricks* abaixo. Suba-o **depois** do Passo 1.\n\n"
        "🔁 **Tricks (Passo 1 + Passo 2):** só subir o acesso de novo não resolve quando o usuário já tem o "
        "módulo no Auth mas está inativo ou não existe dentro do módulo. Por isso:\n"
        "- **Inativo no módulo** (People Hub, Metas ou Performance) → **trick de reativação**: o módulo **sai** "
        "do `access_to_systems` no Passo 1 e **volta** no Passo 2, o que força a reativação;\n"
        "- **Não existe no módulo** (Metas ou Performance) → **trick do nome**: o `first_name` sobe "
        "**alterado** (tudo minúsculo) no Passo 1 e volta ao **nome original** no Passo 2. A troca gera a "
        "tarefa de alteração do usuário, que cria o usuário no módulo.\n\n"
        "Para o People Hub a situação vem da API (token do Full). Para o **Metas** e o **Performance**, envie "
        "os CSVs gerados pelo favorito **Exportar usuários** (opcional: sem o CSV, os tricks daquele módulo "
        "não são verificados)."
    )

    # -------------------------------------------------------------------------
    # SEÇÃO 1: CREDENCIAIS
    # -------------------------------------------------------------------------
    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2, c3 = st.columns(3)
    tenant_t1 = c1.text_input("Tenant do Cliente", key="tenant_t1", placeholder="Ex: empresa123")
    token_controle_t1 = c2.text_input("Token do Controle", key="token_controle_t1")
    token_full_t1 = c3.text_input("Token do Full (Opcional)", key="token_full_t1")

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # SEÇÃO 2: REGRAS GERAIS DE ACESSO
    # -------------------------------------------------------------------------
    st.markdown("### ⚙️ Regras Gerais de Acesso")
    c4, c5, c6 = st.columns(3)

    # People Hub (Full): quem deve ter o módulo 'full'
    acesso_full_t1 = c4.radio("Acesso ao People Hub (Full):",
                              options=['Todos os usuários', 'Gestores', 'Nenhum usuário'],
                              index=2, key="acesso_full_t1")

    # ATS: quem deve ter o módulo 'ats'.
    # Em "Usuários específicos" aparece um campo para digitar os usernames.
    with c5:
        acesso_ats_t1 = st.radio("Acesso ao ATS:",
                                 options=[ATS_NENHUM, ATS_GESTORES, ATS_ESPECIFICOS],
                                 index=0, key="acesso_ats_t1")
        acesso_especifico_ats_t1 = ""
        if acesso_ats_t1 == ATS_ESPECIFICOS:
            acesso_especifico_ats_t1 = st.text_area(
                "Usuários com acesso ao ATS",
                help="Usernames que DEVEM ter acesso ao ATS. Separe por vírgula ou coloque um por linha.",
                key="acesso_especifico_ats_t1",
                placeholder="Ex: pedro.costa, ana.lima\nou um por linha",
            )
        rem_ats_t1 = st.checkbox("Remover o ATS de quem NÃO está autorizado", key="rem_ats_t1")

    # Módulos de desempenho que todo colaborador ativo deve ter
    validacao_t1 = c6.radio("Módulos de Desempenho:",
                            options=['Validação padrão (metas, perfomance)', 'Validar somente metas', 'Validar somente performance'],
                            key="validacao_t1")

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # SEÇÃO 3: ACESSOS RESTRITOS (listas de usernames)
    # -------------------------------------------------------------------------
    st.markdown("### 🎯 Acessos Restritos (Listas Específicas)")
    st.info("💡 **Dica:** Utilize estes campos se um módulo for de uso restrito. Por exemplo: se apenas dois *sponsors* utilizam o Controle (Organograma), digite os seus *usernames* abaixo e assinale a opção **'Remover o acesso de quem NÃO está autorizado'**. Desta forma, a ferramenta remove o acesso a todos os outros funcionários. Os usuários podem ser separados por vírgula ou um por linha.")

    c7, c8 = st.columns(2)

    with c7:
        acesso_controle_t1 = st.text_area("Lista Restrita: Controle",
                                          help="Usuários que DEVEM ter acesso. Separe por vírgula ou coloque um por linha.",
                                          key="acesso_controle_t1", placeholder="Ex: joao.silva, maria.santos")
        rem_ctrl_t1 = st.checkbox("Remover o acesso de quem NÃO está autorizado", key="rem_ctrl_t1")

    with c8:
        acesso_especifico_hub_t1 = st.text_area("Lista Restrita: People Hub",
                                                help="Usuários que DEVEM ter acesso. Separe por vírgula ou coloque um por linha.",
                                                key="acesso_especifico_hub_t1", placeholder="Ex: carlos.souza, julia.melo")
        rem_hub_t1 = st.checkbox("Remover o acesso de quem NÃO está autorizado  ", key="rem_hub_t1")

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # SEÇÃO 4: BASE DO AUTH E PROCESSAMENTO
    # -------------------------------------------------------------------------
    st.markdown("### 📁 Bases de Usuários")
    arquivo_auth_t1 = st.file_uploader("Faça o upload da base exportada do Auth (.csv)", type=['csv'], key="arquivo_auth_t1")

    # CSVs opcionais do Performance e do Metas, usados para os tricks desses módulos
    st.markdown("**Opcional:** usuários do Performance e do Metas, para identificar quem está inativo ou "
                "não existe nesses módulos (tricks de reativação e do nome).")
    render_instrucoes_exportacao(
        "Envie nos campos abaixo o **CSV do Performance** e/ou o **CSV do Metas**, junto com a base do Auth, "
        "e clique em **Processar Validação**. Se um dos arquivos não for enviado, os tricks daquele módulo "
        "não são verificados."
    )
    c9, c10 = st.columns(2)
    arquivo_perf_t1 = c9.file_uploader("Usuários do Performance (.csv) - opcional", type=['csv'], key="arquivo_perf_t1",
                                       help="Arquivo performance_<tenant>_usuarios.csv gerado pelo favorito.")
    arquivo_metas_t1 = c10.file_uploader("Usuários do Metas (.csv) - opcional", type=['csv'], key="arquivo_metas_t1",
                                         help="Arquivo metas_<tenant>_usuarios.csv gerado pelo favorito.")

    chunk_size = st.number_input("Dividir arquivos finais de quantos em quantos usuários? (Deixe 0 para não dividir)", min_value=0, value=0, step=100)

    if st.button("Processar Validação", key="btn_t1"):
        # Converte os campos de texto em listas (aceita vírgula e quebra de linha)
        lista_acessos_controle = separar_usuarios(acesso_controle_t1)
        lista_acessos_ats = separar_usuarios(acesso_especifico_ats_t1)
        lista_acessos_hub = separar_usuarios(acesso_especifico_hub_t1)

        # Validações dos campos obrigatórios antes de chamar qualquer API
        if not tenant_t1 or not token_controle_t1 or not arquivo_auth_t1:
            st.error("Preencha o Tenant, o Token do Controle e faça o upload da base.")
        elif acesso_ats_t1 == ATS_ESPECIFICOS and not lista_acessos_ats:
            st.error("Você escolheu 'Usuários específicos' no ATS. Informe ao menos um username no campo do ATS.")
        else:
            bar = st.progress(0, text="Iniciando o processamento...")
            try:
                # --- Leitura da base do Auth enviada pelo usuário ---
                df_usuarios_auth = ler_csv_seguro(arquivo_auth_t1)
                if 'username' not in df_usuarios_auth.columns:
                    st.error("Erro: A base não possui a coluna 'username'.")
                    st.stop()

                # --- CSVs opcionais do Performance e do Metas (situação de cada usuário no módulo) ---
                mapas_status = {}
                if arquivo_perf_t1:
                    mapas_status['performance'] = mapa_status_modulo(
                        ler_csv_modulo(arquivo_perf_t1, "Performance", "performance_", exigir_ativo=True))
                if arquivo_metas_t1:
                    mapas_status['metas'] = mapa_status_modulo(
                        ler_csv_modulo(arquivo_metas_t1, "Metas", "metas_", exigir_ativo=True))

                # --- Consultas às APIs (cada uma com mensagem de erro clara) ---
                bar.progress(10, text="Obtendo Funcionários do Controle...")
                funcionarios_controle = chamar_api("os funcionários do Controle",
                                                   get_controle_employees_api, tenant_t1, token_controle_t1)
                validar_retorno_api(funcionarios_controle, "os funcionários do Controle", ['employee_code'])
                user_col_t1 = 'user.username' if 'user.username' in funcionarios_controle.columns else 'username'
                if user_col_t1 not in funcionarios_controle.columns:
                    funcionarios_controle[user_col_t1] = ''

                bar.progress(30, text="Obtendo registros do Controle...")
                reg_funcionarios_controle = chamar_api("os registros (vínculos) dos funcionários do Controle",
                                                       get_controle_employee_records_api, tenant_t1, token_controle_t1)
                validar_retorno_api(reg_funcionarios_controle, "os registros (vínculos) dos funcionários do Controle",
                                    ['employee_code', 'start', 'end'])

                # Os gestores só são consultados se alguma regra depender deles
                gestores_funcionario_controle = pd.DataFrame()
                if acesso_full_t1 == 'Gestores' or acesso_ats_t1 == ATS_GESTORES:
                    bar.progress(45, text="Obtendo gestores do Controle...")
                    gestores_funcionario_controle = chamar_api("os gestores do Controle",
                                                               get_controle_employee_managers_api, tenant_t1, token_controle_t1)
                    validar_retorno_api(gestores_funcionario_controle, "os gestores do Controle",
                                        ['employee_code', 'manager_code', 'start', 'end'])

                # Usuários do People Hub (somente se o token do Full foi informado)
                df_usuarios_full = pd.DataFrame()
                if token_full_t1:
                    bar.progress(50, text="Obtendo usuários do People Hub...")
                    df_usuarios_full = chamar_api("os usuários do People Hub (Full)",
                                                  ler_usuarios_full, tenant_t1, token_full_t1)
                    validar_retorno_api(df_usuarios_full, "os usuários do People Hub (Full)", ['username', 'is_active'])

                # --- Funcionários ativos: último registro de cada um, sem data de fim ---
                bar.progress(60, text="Cruzando dados e validando acessos...")
                reg_funcionarios_controle['start'] = pd.to_datetime(reg_funcionarios_controle['start'], errors='coerce')
                reg_funcionarios_controle['end'] = pd.to_datetime(reg_funcionarios_controle['end'], errors='coerce')
                # Ordena para que o registro "em aberto" (end vazio) ou o mais recente fique por último
                reg_funcionarios_controle = reg_funcionarios_controle.sort_values(by=['employee_code', 'end', 'start'], ascending=[True, True, True], na_position='last')
                df_mais_recente_ativos = reg_funcionarios_controle.drop_duplicates(subset='employee_code', keep='last').copy()
                df_mais_recente_ativos = df_mais_recente_ativos.loc[df_mais_recente_ativos['end'].isna()].copy()

                # --- Gestores ativos: mesma lógica aplicada à relação funcionário x gestor ---
                df_gestores_ativos = pd.DataFrame()
                if not gestores_funcionario_controle.empty:
                    gestores_funcionario_controle['start'] = pd.to_datetime(gestores_funcionario_controle['start'], errors='coerce')
                    gestores_funcionario_controle['end'] = pd.to_datetime(gestores_funcionario_controle['end'], errors='coerce')
                    gestores_funcionario_controle = gestores_funcionario_controle.sort_values(by=['employee_code', 'end', 'start'], ascending=[True, True, True], na_position='last')
                    df_gestores_ativos = gestores_funcionario_controle.drop_duplicates(subset='employee_code', keep='last').copy()
                    df_gestores_ativos = df_gestores_ativos.loc[df_gestores_ativos['end'].isna()].copy()

                # --- Monta a base de validação (um registro por funcionário ativo) ---
                df_validacao = df_mais_recente_ativos[['employee_code']].copy()
                # Remove usuários internos da Mindsight da base do Auth
                df_usuarios_auth_limpo = df_usuarios_auth.loc[~df_usuarios_auth['username'].astype(str).str.contains('mindsight', na=False, case=False)].copy()

                # Traz o username de cada funcionário a partir do cadastro do Controle
                mapa_usr = funcionarios_controle.set_index('employee_code')[user_col_t1].to_dict()
                df_validacao['user.username'] = df_validacao['employee_code'].map(mapa_usr).fillna('').astype(str).str.strip()
                df_usuarios_auth_limpo['username'] = df_usuarios_auth_limpo['username'].astype(str).str.strip()

                # Merge principal com os dados do Auth (acessos atuais e status)
                df_validacao = df_validacao.merge(df_usuarios_auth_limpo[['username', 'access_to_systems', 'is_active']], left_on='user.username', right_on='username', how='left')

                # Merge com os dados do Hub para saber quem já está ativo no Full
                if token_full_t1 and not df_usuarios_full.empty:
                    df_usuarios_full_limpo = df_usuarios_full[['username', 'is_active']].copy()
                    df_usuarios_full_limpo['username'] = df_usuarios_full_limpo['username'].astype(str).str.strip()
                    df_usuarios_full_limpo.rename(columns={'is_active': 'is_active_hub'}, inplace=True)

                    # O parâmetro suffixes=('', '_hub_drop') evita que o 'username' original vire 'username_x'
                    df_validacao = df_validacao.merge(df_usuarios_full_limpo, left_on='user.username', right_on='username', how='left', suffixes=('', '_hub_drop'))
                    df_validacao['is_active_full'] = df_validacao['is_active_hub'].fillna(False)
                else:
                    df_validacao['is_active_full'] = True

                # Marca quem é gestor de alguém ativo
                if not df_gestores_ativos.empty:
                    df_validacao['sou_gestor'] = df_validacao['employee_code'].isin(df_gestores_ativos['manager_code'].dropna().unique())
                else:
                    df_validacao['sou_gestor'] = False

                # --- Aplica as regras de acesso a cada usuário ---
                bar.progress(90, text="Gerando base de correção...")
                df_add_acessos = df_usuarios_auth_limpo.merge(df_validacao[['username', 'sou_gestor', 'is_active_full']], on='username', how='inner').copy()

                # Situação no Metas/Performance: ativo, inativo ou inexistente (só se o CSV foi enviado)
                for modulo, mapa in mapas_status.items():
                    df_add_acessos[f'status_{modulo}'] = (df_add_acessos['username'].astype(str).str.strip().str.lower()
                                                          .map(mapa).fillna(STATUS_INEXISTENTE))

                df_add_acessos[['acessos_csv1', 'acessos_csv2', 'vai_pro_csv1', 'vai_pro_csv2', 'motivo',
                                'nome_csv1', 'nome_csv2', 'motivo_passo2']] = df_add_acessos.apply(
                    lambda row: formatar_acessos_duplo(row, acesso_full_t1, lista_acessos_controle, bool(token_full_t1), validacao_t1, acesso_ats_t1, lista_acessos_ats, lista_acessos_hub, rem_ctrl_t1, rem_ats_t1, rem_hub_t1), axis=1
                )

                # Guarda os resultados na memória da sessão para os downloads
                st.session_state.t1_df1 = df_add_acessos[df_add_acessos['vai_pro_csv1'] == True].copy()
                st.session_state.t1_df2 = df_add_acessos[df_add_acessos['vai_pro_csv2'] == True].copy()
                st.session_state.t1_len = len(df_mais_recente_ativos)
                st.session_state.t1_tenant = tenant_t1
                st.session_state.t1_mod_verificados = [NOMES_MODULOS[m] for m in ['performance', 'metas'] if m in mapas_status]
                st.session_state.t1_processed = True

                bar.progress(100, text="Concluído!")
                time.sleep(1)
                bar.empty()
            except ErroAPI as e:
                # Falha em alguma API: mostra a mensagem clara e descarta resultados antigos
                bar.empty()
                st.session_state.t1_processed = False
                st.error(f"❌ Falha na comunicação com a API. {e}")
            except Exception as e:
                bar.empty()
                st.session_state.t1_processed = False
                st.error(f"Ocorreu um erro: {e}")

    # -------------------------------------------------------------------------
    # RESULTADOS E DOWNLOADS
    # -------------------------------------------------------------------------
    if st.session_state.t1_processed:
        st.success(f"✅ Validação concluída! Funcionários Ativos identificados: {st.session_state.t1_len}")
        verificados = st.session_state.get('t1_mod_verificados', [])
        if verificados:
            st.caption(f"Tricks verificados no Metas/Performance pelos CSVs enviados: {', '.join(verificados)}.")
        else:
            st.caption("Os CSVs do Performance e do Metas não foram enviados: os tricks desses módulos não foram verificados.")

        # PASSO 1: ajustes de acessos e ativação de usuários
        if not st.session_state.t1_df1.empty:
            df_final_1 = montar_df_upload(st.session_state.t1_df1, 'acessos_csv1', incluir_motivo=True, coluna_nome='nome_csv1')
            st.write("### PASSO 1: Ajustes de Acessos / Ativação")
            st.info("💡 **O que é este passo?** Esta base contém os usuários que precisam ter seus acessos atualizados "
                    "(ex: adicionar Metas, Performance, ATS, Organograma) ou que estão inativos no Auth e precisam ser "
                    "reativados. Também traz a **primeira metade dos tricks**: para quem está inativo em um módulo, o "
                    "módulo **sai** do `access_to_systems`; para quem não existe no Metas/Performance, o `first_name` "
                    "sobe **alterado** (tudo minúsculo). Não se preocupe: o Passo 2 desfaz essas mudanças. "
                    "**Suba este arquivo primeiro.**")

            # Resumo de quantos usuários tiveram cada tipo de ajuste
            motivos = df_final_1['motivo_ajuste'].value_counts().reset_index()
            motivos.columns = ['Motivo', 'Quantidade']
            st.markdown(motivos.to_html(index=False), unsafe_allow_html=True)

            st.write("<br>", unsafe_allow_html=True)
            with st.expander("👁️ Ver lista de usuários impactados e seus ajustes"):
                st.dataframe(df_final_1[['username', 'email', 'first_name', 'last_name', 'motivo_ajuste']], use_container_width=True)

            gerar_downloads(df_final_1, st.session_state.t1_tenant, "ajustes_acessos", "ajustes",
                            "📥 Baixar Base PASSO 1 (CSV)", "down1", chunk_size)
        else:
            st.info("Nenhum ajuste necessário para o PASSO 1.")

        # PASSO 2: trick de reativação do Full
        if not st.session_state.t1_df2.empty:
            df_final_2 = montar_df_upload(st.session_state.t1_df2, 'acessos_csv2', incluir_motivo=True,
                                          coluna_nome='nome_csv2', coluna_motivo='motivo_passo2')
            st.write("### PASSO 2: Tricks de Reativação e Criação nos Módulos")
            st.info("💡 **O que é este passo?** Completa os tricks iniciados no Passo 1:\n"
                    "- **Trick de reativação:** devolve o módulo (`full`, `metas` ou `performance`) que foi retirado no "
                    "Passo 1, para quem está **inativo** nele. A saída e a volta do módulo forçam a reativação;\n"
                    "- **Trick do nome:** volta o `first_name` ao **nome original**, para quem **não existe** no Metas ou "
                    "no Performance. A troca de nome gera a tarefa de alteração que cria o usuário no módulo.\n\n"
                    "A coluna `motivo_ajuste` mostra o que cada linha faz. "
                    "**Suba este arquivo APENAS DEPOIS de concluir o Passo 1.**")

            motivos2 = df_final_2['motivo_ajuste'].str.split('; ').explode().value_counts().reset_index()
            motivos2.columns = ['Motivo', 'Quantidade']
            st.markdown(motivos2.to_html(index=False), unsafe_allow_html=True)
            st.write("<br>", unsafe_allow_html=True)
            with st.expander("👁️ Ver lista de usuários do Passo 2"):
                st.dataframe(df_final_2[['username', 'email', 'first_name', 'last_name', 'motivo_ajuste']], use_container_width=True)

            gerar_downloads(df_final_2, st.session_state.t1_tenant, "passo2_tricks", "tricks",
                            "📥 Baixar Base PASSO 2 (CSV)", "down2", chunk_size)
        else:
            st.info("Nenhum ajuste necessário para o PASSO 2.")
