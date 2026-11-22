"""
Aba 6 - Criador de Regras de Acessos (BPs) no People Hub.

Contexto: o acesso admin do Hub mostra todos os funcionários da empresa. Quando o
cliente não quer isso, cada BP (Business Partner) recebe regras de acesso que liberam
só alguns funcionários, por Empresa ou por Área.

Fluxo da aba:
  1. Carrega do People Hub (API): funcionários ativos, empresas, cargos, hierarquia
     de áreas e regras de acesso já cadastradas;
  2. Para cada BP: escolhe a pessoa, o modo (Empresa ou Área), o que ela visualiza
     e as exclusões (áreas, empresas, cargos, senioridades);
  3. Calcula quem cada BP deve visualizar e gera:
       - CSV de upload só com as regras NOVAS;
       - relatório das regras novas;
       - relatório das regras que já existem, dizendo se cada uma ainda bate.

Regras geradas por funcionário visível:
  - sempre 'individual';
  - 'tree' só para gestores cujos liderados (todos os níveis abaixo) também podem
    ser vistos pela BP. O tree libera a equipe inteira do gestor, então não pode
    ser usado se alguém da equipe estiver fora da regra da BP.
O owner da regra é o usuário (user) da própria BP, e a BP não entra na própria regra.
"""

import json
import time

import pandas as pd
import streamlit as st

# Como o arquivo é executado a partir do app.py (na raiz), importamos diretamente
from functions import *

MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MODO_EMPRESA, MODO_AREA = 'Por Empresa', 'Por Área'


# =============================================================================
# FUNÇÕES DE APOIO
# =============================================================================
def _id(valor):
    """Padroniza um id: aceita número, texto ou link da API (ex.: .../users/45/ -> '45')."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ''
    texto = str(valor).strip().rstrip('/')
    if '/' in texto:
        texto = texto.split('/')[-1]
    if texto.endswith('.0') and texto[:-2].isdigit():
        texto = texto[:-2]
    return '' if texto.lower() in ('', 'nan', 'none') else texto


def _texto(valor):
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ''
    return " ".join(str(valor).split())


def _atual_por_pessoa(df, colunas):
    """
    Para cada person, pega o registro atual (sem data de fim e mais recente; se não houver
    registro aberto, o mais recente) e devolve um DataFrame indexado pelo id do person.
    """
    if df is None or df.empty or 'person' not in df.columns:
        return pd.DataFrame(columns=colunas)
    d = df.copy()
    d['_person'] = d['person'].apply(_id)
    d['_inicio'] = pd.to_datetime(d['start_date'], errors='coerce') if 'start_date' in d.columns else pd.NaT
    d['_fim'] = pd.to_datetime(d['end_date'], errors='coerce') if 'end_date' in d.columns else pd.NaT
    d['_aberto'] = d['_fim'].isna()
    d = d.sort_values(['_person', '_aberto', '_inicio'], na_position='first')
    d = d.drop_duplicates('_person', keep='last').set_index('_person')
    for c in colunas:
        if c not in d.columns:
            d[c] = ''
    return d[colunas]


def _person_da_regra(params):
    """Extrai o person_id do params da regra (texto JSON ou dicionário)."""
    if isinstance(params, dict):
        return _id(params.get('person_id'))
    try:
        return _id(json.loads(params).get('person_id'))
    except Exception:
        return ''


def carregar_dados_hub(tenant, token):
    """Busca tudo o que a aba precisa no People Hub e já deixa cruzado por funcionário."""
    func = chamar_api("os funcionários ativos do People Hub", get_hub_active_employees_api, tenant, token)
    validar_retorno_api(func, "os funcionários ativos do People Hub", ['id', 'name', 'user'])
    empresas = chamar_api("as empresas do People Hub", get_hub_companies_api, tenant, token)
    cargos = chamar_api("os cargos do People Hub", get_hub_positions_api, tenant, token)
    hierarquia = chamar_api("a hierarquia de áreas do People Hub", get_hub_area_hierarchy_api, tenant, token)
    regras = chamar_api("as regras de acesso do People Hub", get_hub_access_rules_api, tenant, token)
    niveis = chamar_api("os níveis de senioridade do People Hub", get_hub_seniority_levels_api, tenant, token)

    # Níveis de senioridade cadastrados: id -> nome (coluna level), na ordem do cadastro
    mapa_niveis, lista_niveis = {}, []
    if niveis is not None and not niveis.empty and {'id', 'level'}.issubset(niveis.columns):
        n = niveis.copy()
        n['_id'] = n['id'].apply(_id)
        n = n.sort_values('id', key=lambda c: pd.to_numeric(c, errors='coerce'))
        mapa_niveis = dict(zip(n['_id'], n['level'].apply(_texto)))
        lista_niveis = [l for l in n['level'].apply(_texto) if l]

    # --- Base de funcionários ativos: uma linha por person ---
    base = pd.DataFrame({
        'person_id': func['id'].apply(_id),
        'Nome': func['name'].apply(_texto),
        'user_id': func['user'].apply(_id),
        'Email': func['email'] if 'email' in func.columns else '',
        'gestor_id': func['manager_id'].apply(_id) if 'manager_id' in func.columns else '',
        'Área': func['area'].apply(_texto) if 'area' in func.columns else '',
    }).drop_duplicates('person_id')
    emp_atual = _atual_por_pessoa(empresas, ['name'])
    cargo_atual = _atual_por_pessoa(cargos, ['name', 'level', 'seniority_level'])
    base['Empresa'] = base['person_id'].map(emp_atual['name']).apply(_texto)
    base['Cargo'] = base['person_id'].map(cargo_atual['name']).apply(_texto)
    # Senioridade do cargo atual: pelo nível de senioridade ligado ao cargo (seniority_level);
    # se não houver, usa o texto 'level' do próprio cargo
    sen_id = base['person_id'].map(cargo_atual['seniority_level']).apply(_id)
    sen_txt = base['person_id'].map(cargo_atual['level']).apply(_texto)
    base['Senioridade'] = [mapa_niveis.get(i) or t for i, t in zip(sen_id, sen_txt)]

    # --- Hierarquia de áreas vigente (sem data de fim): pai -> filhas, pelo nome ---
    filhas, pai = {}, {}
    if hierarquia is not None and not hierarquia.empty and {'name', 'name_parent'}.issubset(hierarquia.columns):
        h = hierarquia.copy()
        if 'end_date' in h.columns:
            h = h[pd.to_datetime(h['end_date'], errors='coerce').isna()]
        for filha, mae in zip(h['name'].apply(_texto), h['name_parent'].apply(_texto)):
            if filha and mae:
                filhas.setdefault(mae, set()).add(filha)
                pai[filha] = mae
    base['Área pai'] = base['Área'].map(pai).fillna('')

    # --- Regras já cadastradas: user da BP + person do funcionário ---
    if regras is None or regras.empty:
        regras = pd.DataFrame(columns=['id', 'user', 'owner', 'type', 'params'])
    regras = regras.copy()
    if 'params.person_id' in regras.columns:
        regras['_person'] = regras['params.person_id'].apply(_id)
    else:
        regras['_person'] = regras['params'].apply(_person_da_regra) if 'params' in regras.columns else ''
    regras['_user'] = regras['user'].apply(_id)
    # Tipo da regra (individual ou tree). A coluna só vem quando o cliente já tem alguma regra.
    regras['_type'] = regras['type'].apply(_texto).str.lower() if 'type' in regras.columns else ''

    # Listas para as opções da tela
    areas = set(base['Área']) | set(filhas) | set(pai)
    opcoes = {
        'empresas': sorted({e for e in base['Empresa'] if e} |
                           {_texto(n) for n in empresas.get('name', pd.Series(dtype=str)) if _texto(n)}),
        'areas': sorted(a for a in areas if a),
        'cargos': sorted(c for c in base['Cargo'].unique() if c),
        'senioridades': list(dict.fromkeys(lista_niveis)) or sorted(s for s in base['Senioridade'].unique() if s),
    }
    return {'base': base, 'filhas': filhas, 'regras': regras, 'opcoes': opcoes}


def _com_areas_abaixo(areas, filhas):
    """Devolve as áreas informadas mais todas as áreas abaixo delas (todos os níveis)."""
    resultado, fila = set(areas), list(areas)
    while fila:
        for f in filhas.get(fila.pop(), set()):
            if f not in resultado:
                resultado.add(f)
                fila.append(f)
    return resultado


def _avaliar_bp(cfg, base, filhas):
    """
    Para uma BP, devolve uma Series person_id -> motivo. Motivo vazio = a BP pode ver.
    """
    if cfg['modo'] == MODO_EMPRESA:
        dentro = base['Empresa'].isin(cfg['incluir'])
        motivo_fora = 'Fora das empresas da BP'
    else:
        areas = _com_areas_abaixo(cfg['incluir'], filhas) if cfg['abaixo'] else set(cfg['incluir'])
        dentro = base['Área'].isin(areas)
        motivo_fora = 'Fora das áreas da BP'

    motivo = pd.Series('', index=base.index)
    motivo[~dentro] = motivo_fora
    excl_areas = _com_areas_abaixo(cfg['excl_areas'], filhas) if cfg['excl_areas_abaixo'] else set(cfg['excl_areas'])
    for coluna, valores, texto in [('Área', excl_areas, 'Área excluída'),
                                   ('Empresa', set(cfg['excl_empresas']), 'Empresa excluída'),
                                   ('Cargo', set(cfg['excl_cargos']), 'Cargo excluído'),
                                   ('Senioridade', set(cfg['excl_senioridades']), 'Senioridade excluída')]:
        if valores:
            motivo[(motivo == '') & base[coluna].isin(valores)] = texto
    motivo[base['person_id'] == cfg['person_id']] = 'É a própria BP'
    return pd.Series(motivo.values, index=base['person_id'].values)


def _liderados(base):
    """Mapa gestor -> todos os liderados abaixo dele (todos os níveis), só entre os ativos."""
    diretos = {}
    for p, g in zip(base['person_id'], base['gestor_id']):
        if g and g != p:
            diretos.setdefault(g, []).append(p)
    todos = {}
    for gestor in diretos:
        vistos, fila = set(), list(diretos[gestor])
        while fila:
            atual = fila.pop()
            if atual not in vistos and atual != gestor:
                vistos.add(atual)
                fila.extend(diretos.get(atual, []))
        todos[gestor] = vistos
    return todos


# =============================================================================
# TELA
# =============================================================================
def render_aba6():
    st.header("Criador de Regras de Acessos (BPs)")

    st.info(
        "💡 **O que esta aba faz?** No People Hub, o acesso **admin** mostra todos os funcionários da empresa. "
        "Quando o cliente não quer isso, cada **BP** recebe **regras de acesso** que liberam só alguns "
        "funcionários, **por Empresa** ou **por Área**. Esta aba calcula essas regras em massa.\n\n"
        "⚙️ **Como funciona para cada BP:**\n"
        "- **Por Empresa:** a BP vê os funcionários das empresas escolhidas. Dá para excluir áreas, cargos e "
        "senioridades;\n"
        "- **Por Área:** a BP vê os funcionários das áreas escolhidas e, se marcado, de **todas as áreas abaixo** "
        "delas. Dá para excluir empresas, cargos e senioridades.\n\n"
        "📄 **Regras geradas para cada funcionário que a BP pode ver:**\n"
        "- **individual:** sempre. Libera aquele funcionário;\n"
        "- **tree:** só para **gestores** cuja equipe inteira (todos os níveis abaixo) também pode ser vista "
        "pela BP. O tree libera a equipe do gestor, então, se alguém da equipe estiver fora da regra "
        "(ex.: um cargo excluído), o gestor recebe só o individual.\n\n"
        "O **owner** da regra é o usuário (user) da própria BP, e a BP não entra na própria regra (ela já se vê). "
        "Só são considerados os funcionários **ativos** no People Hub."
    )

    # -------------------------------------------------------------------------
    # SEÇÃO 1: CREDENCIAIS E CARGA DOS DADOS
    # -------------------------------------------------------------------------
    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2 = st.columns(2)
    tenant_t6 = c1.text_input("Tenant do Cliente", key="tenant_t6", placeholder="Ex: empresa123")
    token_t6 = c2.text_input("Token do Full (People Hub)", key="token_full_t6")

    if st.button("Carregar dados do People Hub", key="btn_t6_carregar"):
        if not tenant_t6 or not token_t6:
            st.error("Preencha o Tenant e o Token do Full.")
        else:
            try:
                with st.spinner("Buscando funcionários, empresas, cargos, áreas e regras existentes..."):
                    st.session_state.t6_dados = carregar_dados_hub(tenant_t6, token_t6)
                st.session_state.t6_tenant = tenant_t6
                st.session_state.t6_processed = False
            except ErroAPI as e:
                st.session_state.t6_dados = None
                st.error(f"❌ Falha na comunicação com a API. {e}")
            except Exception as e:
                st.session_state.t6_dados = None
                st.error(f"Ocorreu um erro: {e}")

    dados = st.session_state.get('t6_dados')
    if not dados:
        st.caption("Carregue os dados do cliente para configurar as BPs.")
        return

    base, opcoes = dados['base'], dados['opcoes']
    st.success(f"Dados de **{st.session_state.t6_tenant}** carregados: {len(base)} funcionários ativos, "
               f"{len(opcoes['empresas'])} empresas, {len(opcoes['areas'])} áreas e "
               f"{len(dados['regras'])} regras de acesso já cadastradas.")

    # -------------------------------------------------------------------------
    # SEÇÃO 2: CONFIGURAÇÃO DAS BPs
    # -------------------------------------------------------------------------
    st.markdown("### 👥 Configuração das BPs")
    # Opções de BP: "Nome (email)" -> person_id
    rotulos = {f"{n} ({e})" if _texto(e) else n: p
               for n, e, p in sorted(zip(base['Nome'], base['Email'], base['person_id']))}
    qtd = st.number_input("Quantas BPs terão regras de acesso?", min_value=1, max_value=30, value=1, step=1, key="qtd_bps_t6")

    configs, erros = [], []
    for i in range(int(qtd)):
        with st.container(border=True):
            st.markdown(f"#### {i + 1}ª BP")
            bp = st.selectbox("Funcionário (BP)", options=list(rotulos), index=None, key=f"t6_bp_{i}",
                              placeholder="Digite para buscar pelo nome...")
            modo = st.radio("A BP vai visualizar os funcionários:", [MODO_EMPRESA, MODO_AREA],
                            horizontal=True, key=f"t6_modo_{i}")
            cfg = {'modo': modo, 'abaixo': False, 'excl_areas': [], 'excl_areas_abaixo': False,
                   'excl_empresas': [], 'excl_cargos': [], 'excl_senioridades': []}

            if modo == MODO_EMPRESA:
                cfg['incluir'] = st.multiselect("Empresas que a BP visualiza", opcoes['empresas'], key=f"t6_emp_{i}")
                st.markdown("**Exclusões** (funcionários dessas empresas que a BP **não** pode ver):")
                e1, e2, e3 = st.columns(3)
                if e1.checkbox("Excluir áreas", key=f"t6_xa_{i}"):
                    cfg['excl_areas'] = e1.multiselect("Áreas excluídas", opcoes['areas'], key=f"t6_xal_{i}")
                    cfg['excl_areas_abaixo'] = e1.checkbox("Excluir também as áreas abaixo", value=True, key=f"t6_xab_{i}")
                ex_cargo, ex_sen = e2, e3
            else:
                cfg['incluir'] = st.multiselect("Áreas que a BP visualiza", opcoes['areas'], key=f"t6_area_{i}")
                cfg['abaixo'] = st.checkbox("Incluir as áreas abaixo das áreas escolhidas (todos os níveis)",
                                            value=True, key=f"t6_abaixo_{i}")
                st.markdown("**Exclusões** (funcionários dessas áreas que a BP **não** pode ver):")
                e1, e2, e3 = st.columns(3)
                if e1.checkbox("Excluir empresas", key=f"t6_xe_{i}"):
                    cfg['excl_empresas'] = e1.multiselect("Empresas excluídas", opcoes['empresas'], key=f"t6_xel_{i}")
                ex_cargo, ex_sen = e2, e3
            if ex_cargo.checkbox("Excluir cargos", key=f"t6_xc_{i}"):
                cfg['excl_cargos'] = ex_cargo.multiselect("Cargos excluídos", opcoes['cargos'], key=f"t6_xcl_{i}")
            if ex_sen.checkbox("Excluir senioridades", key=f"t6_xs_{i}"):
                cfg['excl_senioridades'] = ex_sen.multiselect("Senioridades excluídas", opcoes['senioridades'], key=f"t6_xsl_{i}")

            if not bp:
                erros.append(f"Escolha o funcionário da {i + 1}ª BP.")
            elif not cfg['incluir']:
                erros.append(f"Escolha ao menos uma {'empresa' if modo == MODO_EMPRESA else 'área'} para a {i + 1}ª BP.")
            else:
                linha_bp = base[base['person_id'] == rotulos[bp]].iloc[0]
                if not linha_bp['user_id']:
                    erros.append(f"A BP {linha_bp['Nome']} não tem usuário no People Hub, então não pode receber regras.")
                cfg.update({'person_id': linha_bp['person_id'], 'user_id': linha_bp['user_id'], 'nome': linha_bp['Nome']})
                configs.append(cfg)

    # -------------------------------------------------------------------------
    # SEÇÃO 3: PROCESSAMENTO
    # -------------------------------------------------------------------------
    if st.button("Gerar Regras de Acesso", key="btn_t6_gerar"):
        if erros:
            for e in erros:
                st.error(e)
        else:
            liderados = _liderados(base)
            regras = dados['regras']
            info = base.set_index('person_id')
            cols_info = ['Nome', 'Empresa', 'Área', 'Área pai', 'Cargo', 'Senioridade']
            novas, existentes, resumo = [], [], []

            for cfg in configs:
                motivos = _avaliar_bp(cfg, base, dados['filhas'])
                visiveis = set(motivos[motivos == ''].index)
                existentes_bp = regras[regras['_user'] == cfg['user_id']]
                # Regras já cadastradas para a BP: (person, tipo)
                ja_tem = set(zip(existentes_bp['_person'], existentes_bp['_type']))

                def pode_tree(p):
                    """tree só para gestor cuja equipe inteira pode ser vista (a própria BP pode estar na equipe)."""
                    equipe = liderados.get(p, set())
                    return bool(equipe) and all(m in visiveis or m == cfg['person_id'] for m in equipe)

                # Regras que a BP deveria ter e ainda não tem
                qtd_tree = qtd_completos = 0
                for p in visiveis:
                    tipos = ['individual'] + (['tree'] if pode_tree(p) else [])
                    qtd_tree += 'tree' in tipos
                    faltando = [t for t in tipos if (p, t) not in ja_tem]
                    if not faltando:
                        qtd_completos += 1
                        continue
                    novas.append({'BP': cfg['nome'], 'Funcionário': info.at[p, 'Nome'],
                                  **{c: info.at[p, c] for c in cols_info[1:]},
                                  'Regras novas': " + ".join(faltando),
                                  'user': cfg['user_id'], 'owner': cfg['user_id'], 'person_id': p,
                                  '_tipos': faltando})

                # Regras que já existem para a BP (uma linha por regra): ainda batem com a configuração?
                qtd_nao_batem = 0
                for p, tipo in sorted(ja_tem):
                    if p in info.index:
                        dados_func = {c: info.at[p, c] for c in cols_info}
                        motivo = motivos.get(p, '')
                        if not motivo and tipo == 'tree' and not pode_tree(p):
                            motivo = ('Tree não deveria existir: há pessoas na equipe do gestor que a BP não pode ver'
                                      if liderados.get(p) else 'Tree em quem não é mais gestor')
                    else:
                        dados_func = {'Nome': f'(person {p})'}
                        motivo = 'Funcionário não está ativo no People Hub'
                    qtd_nao_batem += bool(motivo)
                    existentes.append({'BP': cfg['nome'], 'Funcionário': dados_func.pop('Nome'), **dados_func,
                                       'Tipo': tipo or '-', 'Ainda bate?': 'Sim' if not motivo else 'Não',
                                       'Motivo': motivo or '-'})

                resumo.append({'BP': cfg['nome'], 'Modo': cfg['modo'],
                               'Funcionários que visualiza': len(visiveis),
                               'Gestores com tree': qtd_tree,
                               'Já tinham todas as regras': qtd_completos,
                               'Com regras novas': len(visiveis) - qtd_completos,
                               'Regras existentes que não batem': qtd_nao_batem})

            df_novas = pd.DataFrame(novas)
            # CSV de upload: uma linha por regra (individual e, quando couber, tree)
            linhas_csv = []
            for r in novas:
                for tipo in r['_tipos']:
                    linhas_csv.append({'user': r['user'], 'id': '', 'owner': r['owner'], 'type': tipo,
                                       'params': json.dumps({'person_id': int(r['person_id'])
                                                             if str(r['person_id']).isdigit() else r['person_id']}),
                                       'name_bp': r['BP'], 'name_func': r['Funcionário']})
            st.session_state.t6_csv = pd.DataFrame(linhas_csv, columns=['user', 'id', 'owner', 'type', 'params', 'name_bp', 'name_func'])
            st.session_state.t6_novas = df_novas.drop(columns=['user', 'owner', 'person_id', '_tipos']) if not df_novas.empty else df_novas
            st.session_state.t6_existentes = pd.DataFrame(existentes).fillna('-')
            st.session_state.t6_resumo = pd.DataFrame(resumo)
            st.session_state.t6_processed = True

    # -------------------------------------------------------------------------
    # RESULTADOS E DOWNLOADS
    # -------------------------------------------------------------------------
    if st.session_state.get('t6_processed'):
        tenant = st.session_state.t6_tenant
        st.write("---")
        st.subheader("Resumo por BP")
        st.markdown(st.session_state.t6_resumo.to_html(index=False), unsafe_allow_html=True)
        st.write("<br>", unsafe_allow_html=True)

        df_csv, df_novas, df_exist = st.session_state.t6_csv, st.session_state.t6_novas, st.session_state.t6_existentes

        # Regras novas
        st.subheader("Regras novas")
        if df_csv.empty:
            st.info("Nenhuma regra nova: todos os funcionários que as BPs devem ver já têm regra cadastrada.")
        else:
            st.markdown(f"**{len(df_novas)}** funcionários com regras faltando, que geram **{len(df_csv)}** regras "
                        "novas (individual e, para os gestores liberados, tree). Quem já tem a regra não entra de novo.")
            with st.expander("👁️ Ver regras novas"):
                st.dataframe(df_novas, use_container_width=True, hide_index=True)
            d1, d2 = st.columns(2)
            d1.download_button("📥 Baixar CSV de Upload das Regras", key="down_t6_csv",
                               data=df_csv.to_csv(index=False, sep=',', encoding='utf-8-sig'),
                               file_name=f"{tenant}_hub_regras_de_acessos.csv", mime="text/csv")
            d2.download_button("📥 Baixar Relatório das Regras Novas (Excel)", key="down_t6_novas",
                               data=gerar_excel_multi_abas({'Resumo por BP': st.session_state.t6_resumo,
                                                            'Regras Novas': df_novas}),
                               file_name=f"{tenant}_regras_novas_bps.xlsx", mime=MIME_EXCEL)

        # Regras existentes
        st.subheader("Regras que já existem")
        if df_exist.empty:
            st.info("As BPs configuradas ainda não têm nenhuma regra cadastrada.")
        else:
            nao_batem = int((df_exist['Ainda bate?'] == 'Não').sum())
            st.markdown(f"**{len(df_exist)}** regras já cadastradas para as BPs, das quais **{nao_batem}** "
                        "não batem mais com a configuração (coluna *Motivo*).")
            with st.expander("👁️ Ver regras existentes"):
                st.dataframe(df_exist, use_container_width=True, hide_index=True)
            st.download_button("📥 Baixar Relatório das Regras Existentes (Excel)", key="down_t6_exist",
                               data=gerar_excel_multi_abas({'Regras Existentes': df_exist}),
                               file_name=f"{tenant}_regras_existentes_bps.xlsx", mime=MIME_EXCEL)
