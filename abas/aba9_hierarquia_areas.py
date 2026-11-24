"""
Aba 9 - Criação de Hierarquia de Áreas (Controle).

Monta uma nova hierarquia de áreas a partir dos dados que já estão no Controle e gera
os arquivos de importação. A ferramenta NÃO grava nada no Controle: você confere e sobe.

Fluxo da aba:
  1. O usuário escolhe a base da hierarquia (por enquanto só "dados do sistema"),
     quantos níveis ela terá e o que é cada nível: EMPRESA, FILIAL, ÁREA PAI ou ÁREA
     (cada opção só pode ser usada em um nível).
  2. Escolhe como os funcionários serão atualizados:
       - Todas as áreas: os vínculos de área atuais E antigos passam a apontar para a
         nova área (o registro é atualizado pelo id, sem fechar nada);
       - Só a área atual: o vínculo atual é fechado hoje e um novo vínculo é aberto
         hoje na nova área.
  3. A ferramenta busca no Controle: registros de funcionário (empresa e filial),
     empresas, filiais, áreas, registros de área, áreas pai e áreas dos funcionários.
  4. Para cada vínculo de área de funcionário, monta o caminho da hierarquia
     (ex.: CAVALEIRO > CAVALEIRO # ESCRITÓRIO > GRUPO MARSARO > AUDITORIA).
     Cada trecho do caminho vira uma área nova:
       - Nome: o valor do nível, quando ele aparece em um só caminho da hierarquia;
         quando aparece em caminhos diferentes, o caminho completo separado por " - "
         (ex.: "CAVALEIRO - CAVALEIRO # ESCRITÓRIO - GRUPO MARSARO - AUDITORIA").
       - Código: "H" + nível + "-" + 8 caracteres gerados a partir do caminho
         (ex.: H4-3F9A2C1B). O mesmo caminho gera sempre o mesmo código.
     Um nível vazio (ex.: área sem área pai) é pulado nesse caminho.
  5. Arquivos gerados: áreas (instâncias), registros de área, áreas pai e áreas dos
     funcionários, além de uma planilha de conferência.
  Funcionários da Mindsight são ignorados.
"""

import hashlib
from datetime import date

import pandas as pd
import streamlit as st

from functions import *

MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VAZIOS = {'nan', 'none', '', '-', 'nat', 'null'}

EMPRESA, FILIAL, AREA_PAI, AREA = 'EMPRESA', 'FILIAL', 'ÁREA PAI', 'ÁREA'
DIMENSOES = [EMPRESA, FILIAL, AREA_PAI, AREA]
INICIO_PADRAO = '1900-01-01'
SEPARADOR_NOME = ' - '

MODO_TODAS = 'todas'
MODO_ATUAL = 'atual'


# =============================================================================
# FUNÇÕES DE APOIO
# =============================================================================
def _codigo(valor):
    """Texto de um código/id vindo da API (ex.: 40.0 -> '40'; vazio -> '')."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ''
    texto = str(valor).strip()
    if texto.endswith('.0') and texto[:-2].isdigit():
        texto = texto[:-2]
    return '' if texto.lower() in VAZIOS else texto


def _texto(valor):
    """Nome limpo (sem espaços sobrando); '' para vazio."""
    return " ".join(_codigo(valor).split())


def _chave(valor):
    """Nome padronizado para comparação (minúsculo, sem espaços sobrando)."""
    return _texto(valor).lower()


def _data(valor):
    """Data no formato AAAA-MM-DD ('' para vazio)."""
    d = pd.to_datetime(_codigo(valor), errors='coerce')
    return '' if pd.isna(d) else d.strftime('%Y-%m-%d')


def _codigo_no(caminho):
    """Código curto (< 50 caracteres) e estável para um caminho da hierarquia."""
    base = '|'.join(_chave(v) for v in caminho)
    resumo = hashlib.sha1(base.encode('utf-8')).hexdigest()[:8].upper()
    return f"H{len(caminho)}-{resumo}"


def _registro_na_data(registros, data_ref):
    """
    Registro de funcionário que valia na data informada (start <= data <= end).
    Sem data ou sem registro na data: o registro aberto mais recente; senão, o mais recente.
    `registros` já vem ordenado do mais recente para o mais antigo.
    """
    if registros.empty:
        return None
    if data_ref:
        no_periodo = registros[(registros['_start'] <= data_ref) &
                               ((registros['_end'] == '') | (registros['_end'] >= data_ref))]
        if not no_periodo.empty:
            return no_periodo.iloc[0]
    abertos = registros[registros['_end'] == '']
    return (abertos if not abertos.empty else registros).iloc[0]


# =============================================================================
# LEITURA DO CONTROLE
# =============================================================================
def _buscar_dados(tenant, token, bar):
    """Busca no Controle tudo o que a aba usa."""
    consultas = [
        ('registros', "os registros de funcionário do Controle", get_controle_employee_records_api,
         ['employee_code', 'start', 'end']),
        ('empresas', "as empresas do Controle", get_controle_corporations_api, ['id', 'name']),
        ('filiais', "as filiais do Controle", get_controle_branch_corporations_api, ['id', 'name']),
        ('areas', "as áreas do Controle", get_controle_areas_api, ['id', 'code', 'name']),
        ('areas_pai', "as áreas pai do Controle", get_controle_parent_areas_api, None),
        ('areas_func', "as áreas dos funcionários do Controle", get_controle_employee_areas_api,
         ['id', 'employee_code', 'area_code', 'start', 'end']),
    ]
    dados = {}
    for i, (chave, descricao, funcao, obrigatorias) in enumerate(consultas):
        bar.progress(5 + i * 13, text=f"Obtendo {descricao.split(' ', 1)[1]}...")
        df = chamar_api(descricao, funcao, tenant, token)
        if obrigatorias:
            validar_retorno_api(df, descricao, obrigatorias)
        dados[chave] = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    return dados


# =============================================================================
# MONTAGEM DA HIERARQUIA
# =============================================================================
def montar_hierarquia(dados, niveis, modo, hoje):
    """
    Monta a nova hierarquia e os arquivos de importação.

    dados:  dicionário com os DataFrames do Controle (ver _buscar_dados).
    niveis: lista com a dimensão de cada nível, do 1º ao último (ex.: [EMPRESA, FILIAL, ÁREA PAI, ÁREA]).
    modo:   MODO_TODAS ou MODO_ATUAL.
    hoje:   data atual no formato AAAA-MM-DD.
    """
    # --- Empresas e filiais (nome pelo id) ---
    emp = dados['empresas']
    fil = dados['filiais']
    nome_empresa = dict(zip(emp['id'].map(_codigo), emp['name'].map(_texto)))
    nome_filial = dict(zip(fil['id'].map(_codigo), fil['name'].map(_texto)))

    # --- Registros de funcionário (empresa e filial de cada funcionário ao longo do tempo) ---
    reg = dados['registros'].copy()
    reg['employee_code'] = reg['employee_code'].map(_codigo)
    reg['_start'] = reg['start'].map(_data)
    reg['_end'] = reg['end'].map(_data)

    def _col(df, nome):
        return df[nome] if nome in df.columns else pd.Series([''] * len(df), index=df.index)

    id_emp = _col(reg, 'id_corporation').map(_codigo)
    id_emp = id_emp.where(id_emp != '', _col(reg, 'corporation').map(_codigo))
    reg['_empresa'] = id_emp.map(nome_empresa).fillna('')
    reg['_empresa'] = reg['_empresa'].where(reg['_empresa'] != '', _col(reg, 'name').map(_texto))
    id_fil = _col(reg, 'id_branch_corporation').map(_codigo)
    id_fil = id_fil.where(id_fil != '', _col(reg, 'branch_corporation').map(_codigo))
    reg['_filial'] = id_fil.map(nome_filial).fillna('')
    reg['_filial'] = reg['_filial'].where(reg['_filial'] != '', _col(reg, 'name_branch_corporation').map(_texto))
    reg = reg.sort_values(['employee_code', '_start'], ascending=[True, False])
    registros_por_func = {cod: g for cod, g in reg.groupby('employee_code')}

    nome_col = 'name_employee' if 'name_employee' in reg.columns else None
    nome_func = dict(zip(reg['employee_code'], reg[nome_col].map(_texto))) if nome_col else {}

    # Funcionários da Mindsight
    mindsight = reg['employee_code'].str.contains('mindsight', case=False, na=False)
    for col in ['user.username', 'email', 'user.email']:
        if col in reg.columns:
            mindsight |= reg[col].astype(str).str.contains('mindsight', case=False, na=False)
    codigos_mindsight = set(reg.loc[mindsight, 'employee_code'])

    # --- Áreas: nome pelo código e área pai atual de cada área ---
    areas = dados['areas']
    nome_area = dict(zip(areas['code'].map(_codigo), areas['name'].map(_texto)))
    codigos_existentes = {_chave(c) for c in areas['code']}
    nomes_existentes = {_chave(n): _codigo(c) for n, c in zip(areas['name'], areas['code'])}

    pais = dados['areas_pai'].copy()
    pai_da_area = {}
    if not pais.empty and {'area_code', 'parent_code'}.issubset(pais.columns):
        pais['area_code'] = pais['area_code'].map(_codigo)
        pais['parent_code'] = pais['parent_code'].map(_codigo)
        pais['_start'] = pais['start'].map(_data) if 'start' in pais.columns else ''
        pais['_end'] = pais['end'].map(_data) if 'end' in pais.columns else ''
        # Vale a relação em aberto mais recente; sem relação em aberto, a mais recente
        pais = pais.sort_values(['area_code', '_start'], ascending=[True, False])
        for cod, g in pais.groupby('area_code'):
            abertas = g[g['_end'] == '']
            pai_da_area[cod] = (abertas if not abertas.empty else g).iloc[0]['parent_code']

    # --- Vínculos de área dos funcionários que serão atualizados ---
    vinc = dados['areas_func'].copy()
    vinc['id'] = vinc['id'].map(_codigo)
    vinc['employee_code'] = vinc['employee_code'].map(_codigo)
    vinc['area_code'] = vinc['area_code'].map(_codigo)
    vinc['_start'] = vinc['start'].map(_data)
    vinc['_end'] = vinc['end'].map(_data)
    vinc = vinc[~vinc['employee_code'].isin(codigos_mindsight)]
    if modo == MODO_ATUAL:
        vinc = vinc[vinc['_end'] == '']
    vinc = vinc.sort_values(['employee_code', '_start'])

    # --- Caminho de cada vínculo ---
    linhas = []
    avisos = []
    for _, v in vinc.iterrows():
        cod_func = v['employee_code']
        data_ref = v['_start'] if modo == MODO_TODAS else hoje
        r = _registro_na_data(registros_por_func.get(cod_func, pd.DataFrame()), data_ref)
        area_nome = nome_area.get(v['area_code'], '') or _texto(v.get('name', ''))
        cod_pai = pai_da_area.get(v['area_code'], '')
        valores = {
            EMPRESA: r['_empresa'] if r is not None else '',
            FILIAL: r['_filial'] if r is not None else '',
            AREA_PAI: nome_area.get(cod_pai, cod_pai),
            AREA: area_nome,
        }
        caminho = tuple(valores[n] for n in niveis if valores[n])
        tipos = [n for n in niveis if valores[n]]
        faltando = [n for n in niveis if not valores[n]]
        if r is None:
            avisos.append((cod_func, nome_func.get(cod_func, ''), v['area_code'],
                           'Funcionário sem registro de funcionário: empresa e filial ficaram vazias'))
        elif faltando:
            avisos.append((cod_func, nome_func.get(cod_func, ''), v['area_code'],
                           f"Sem {', '.join(faltando)}: esse nível foi pulado no caminho"))
        if not caminho:
            avisos.append((cod_func, nome_func.get(cod_func, ''), v['area_code'],
                           'Nenhum nível preenchido: o vínculo não foi atualizado'))
            continue
        linhas.append({
            'id_vinculo': v['id'], 'employee_code': cod_func, 'area_code_antigo': v['area_code'],
            'area_antiga': area_nome, 'start': v['_start'], 'end': v['_end'],
            'Empresa': valores[EMPRESA], 'Filial': valores[FILIAL], 'Área pai': valores[AREA_PAI],
            'caminho': caminho, 'tipos': tipos,
        })

    # --- Nós da hierarquia (cada trecho de caminho) ---
    nos = {}
    tipo_no = {}
    for linha in linhas:
        c = linha['caminho']
        for k in range(1, len(c) + 1):
            nos.setdefault(c[:k], None)
            tipo_no.setdefault(c[:k], linha['tipos'][k - 1])

    # Um valor que aparece em mais de um caminho ganha o caminho completo no nome
    caminhos_por_valor = {}
    for caminho in nos:
        caminhos_por_valor.setdefault(_chave(caminho[-1]), set()).add(caminho)
    for caminho in nos:
        repetido = len(caminhos_por_valor[_chave(caminho[-1])]) > 1
        nome = SEPARADOR_NOME.join(caminho) if repetido else caminho[-1]
        nos[caminho] = {'code': _codigo_no(caminho), 'name': nome, 'nivel': len(caminho)}

    # Códigos repetidos (praticamente impossível) ou já usados no Controle
    codigos = [n['code'] for n in nos.values()]
    for caminho, n in nos.items():
        if codigos.count(n['code']) > 1 or _chave(n['code']) in codigos_existentes:
            avisos.append(('', '', n['code'], f"Código {n['code']} repetido ou já existe no Controle "
                                              f"(área {n['name']}). Ajuste antes de importar."))

    ordenados = sorted(nos.items(), key=lambda kv: (kv[1]['nivel'], [_chave(x) for x in kv[0]]))

    # --- Arquivos de importação ---
    df_areas = pd.DataFrame([{'id': '', 'code': n['code'], 'name': n['name']} for _, n in ordenados],
                            columns=['id', 'code', 'name'])
    df_registros = pd.DataFrame([{'id': '', 'area_code': n['code'], 'start': INICIO_PADRAO, 'end': ''}
                                 for _, n in ordenados], columns=['id', 'area_code', 'start', 'end'])
    df_pais = pd.DataFrame([{'id': '', 'area_code': n['code'], 'parent_code': nos[c[:-1]]['code'],
                             'start': INICIO_PADRAO, 'end': ''}
                            for c, n in ordenados if len(c) > 1],
                           columns=['id', 'area_code', 'parent_code', 'start', 'end'])

    func_rows = []
    for linha in linhas:
        novo = nos[linha['caminho']]['code']
        if modo == MODO_TODAS:
            func_rows.append({'employee_code': linha['employee_code'], 'area_code': novo,
                              'start': linha['start'], 'end': linha['end'], 'id': linha['id_vinculo'],
                              'Ação': 'Atualizar vínculo'})
        else:
            if linha['start'] and linha['start'] >= hoje:
                avisos.append((linha['employee_code'], nome_func.get(linha['employee_code'], ''),
                               linha['area_code_antigo'],
                               f"O vínculo atual começa em {linha['start']}, igual ou depois de hoje: "
                               f"não dá para fechar em {hoje}. Ajuste esse vínculo manualmente."))
                continue
            func_rows.append({'employee_code': linha['employee_code'], 'area_code': linha['area_code_antigo'],
                              'start': linha['start'], 'end': hoje, 'id': linha['id_vinculo'],
                              'Ação': 'Fechar vínculo atual'})
            func_rows.append({'employee_code': linha['employee_code'], 'area_code': novo,
                              'start': hoje, 'end': '', 'id': '', 'Ação': 'Abrir vínculo na nova área'})
    df_func_conf = pd.DataFrame(func_rows, columns=['employee_code', 'area_code', 'start', 'end', 'id', 'Ação'])
    df_func = df_func_conf.drop(columns=['Ação'])

    # Conferência: de -> para por vínculo
    df_mapa = pd.DataFrame([{
        'Colaborador': nome_func.get(l['employee_code'], ''),
        'employee_code': l['employee_code'],
        'id do vínculo': l['id_vinculo'],
        'Início do vínculo': l['start'],
        'Fim do vínculo': l['end'],
        'Empresa': l['Empresa'],
        'Filial': l['Filial'],
        'Área pai': l['Área pai'],
        'Área antiga': l['area_antiga'],
        'Código antigo': l['area_code_antigo'],
        'Nova área': nos[l['caminho']]['name'],
        'Novo código': nos[l['caminho']]['code'],
        'Caminho': ' > '.join(l['caminho']),
    } for l in linhas])

    # Árvore: uma linha por área nova, com o pai
    qtd_por_caminho = {}
    for l in linhas:
        qtd_por_caminho[l['caminho']] = qtd_por_caminho.get(l['caminho'], 0) + 1
    df_arvore = pd.DataFrame([{
        'Nível': n['nivel'],
        'Tipo': tipo_no[c],
        'Nome': n['name'],
        'Código': n['code'],
        'Área pai (nome)': nos[c[:-1]]['name'] if len(c) > 1 else '',
        'Área pai (código)': nos[c[:-1]]['code'] if len(c) > 1 else '',
        'Caminho': ' > '.join(c),
        'Vínculos de funcionário': qtd_por_caminho.get(c, 0),
        'Nome já existe no Controle (código)': nomes_existentes.get(_chave(n['name']), ''),
    } for c, n in ordenados])

    df_avisos = pd.DataFrame(avisos, columns=['employee_code', 'Colaborador', 'Área (código)', 'Aviso']).drop_duplicates()

    resumo = pd.DataFrame([
        ('Hierarquia', ' > '.join(niveis)),
        ('Atualização dos funcionários', 'Todas as áreas (atuais e antigas)' if modo == MODO_TODAS
         else f'Só a área atual (fecha e abre em {hoje})'),
        ('Vínculos de área analisados', len(vinc)),
        ('Funcionários envolvidos', vinc['employee_code'].nunique()),
        ('Áreas novas', len(df_areas)),
        ('Relações de área pai', len(df_pais)),
        ('Áreas novas com nome igual a uma área que já existe', int((df_arvore['Nome já existe no Controle (código)'] != '').sum()) if not df_arvore.empty else 0),
        ('Linhas no arquivo de áreas dos funcionários', len(df_func)),
        ('Avisos', len(df_avisos)),
    ], columns=['Item', 'Valor'])
    resumo['Valor'] = resumo['Valor'].astype(str)

    return {
        'resumo': resumo,
        'areas': df_areas,
        'registros': df_registros,
        'pais': df_pais,
        'funcionarios': df_func,
        'funcionarios_conf': df_func_conf,
        'arvore': df_arvore,
        'mapa': df_mapa,
        'avisos': df_avisos,
    }


# =============================================================================
# TELA
# =============================================================================
def _marcar_unico(marcado, outro):
    """Ao marcar um dos checks de atualização, desmarca o outro."""
    if st.session_state.get(marcado):
        st.session_state[outro] = False


def render_aba9():
    for chave, valor in {'t9_processed': False, 't9_tenant': "", 't9_resultado': {}}.items():
        st.session_state.setdefault(chave, valor)

    st.header("Criação de Hierarquia de Áreas")

    st.info(
        "💡 **O que esta página faz?**\n"
        "Monta uma nova hierarquia de áreas no Controle combinando **Empresa**, **Filial**, **Área pai** e "
        "**Área** na ordem que você escolher, e gera os arquivos de importação: áreas novas, registros de "
        "área, áreas pai e áreas dos funcionários. Nada é gravado no Controle.\n\n"
        "🏷️ **Nomes:** uma área mantém o nome curto quando aparece em um só caminho da hierarquia. "
        "Quando aparece em caminhos diferentes (ex.: a mesma AUDITORIA em duas filiais), recebe o caminho "
        "completo, como `CAVALEIRO - CAVALEIRO # ESCRITÓRIO - GRUPO MARSARO - AUDITORIA`. "
        "O código é curto e gerado a partir do caminho (ex.: `H4-3F9A2C1B`).\n\n"
        "🚫 Funcionários da Mindsight são desconsiderados."
    )

    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2 = st.columns(2)
    tenant_t9 = c1.text_input("Tenant do Cliente", key="tenant_t9", placeholder="Ex: empresa123")
    token_controle_t9 = c2.text_input("Token do Controle", key="token_controle_t9")

    st.markdown("### 🧱 Como será a hierarquia")
    base = st.radio("A hierarquia será montada com base em:",
                    ["Dados que já estão no sistema", "Planilha"], key="base_t9", horizontal=True)
    if base == "Planilha":
        st.warning("🚧 A montagem a partir de planilha ainda não está disponível. Use os dados do sistema.")
        return

    qtd = st.number_input("Quantos níveis a hierarquia terá?", min_value=1, max_value=len(DIMENSOES),
                          value=len(DIMENSOES), step=1, key="qtd_niveis_t9")
    niveis = []
    colunas = st.columns(int(qtd))
    for i in range(int(qtd)):
        opcoes = [d for d in DIMENSOES if d not in niveis]
        chave = f"nivel_{i}_t9"
        if st.session_state.get(chave) not in opcoes:
            st.session_state[chave] = opcoes[0]
        niveis.append(colunas[i].selectbox(f"{i + 1}º nível", opcoes, key=chave))
    st.caption("Cada opção só pode ser usada em um nível. Os funcionários ficam no último nível do caminho deles.")

    st.markdown("### 👥 Atualização das áreas dos funcionários")
    st.checkbox("Atualizar **todas** as áreas dos funcionários (atuais e antigas) para a nova hierarquia, "
                "sem fechar o registro atual", key="todas_t9",
                on_change=_marcar_unico, args=("todas_t9", "atual_t9"))
    st.checkbox("Atualizar **apenas a área atual** do funcionário: fecha o registro atual hoje e abre um novo "
                "na nova área", key="atual_t9",
                on_change=_marcar_unico, args=("atual_t9", "todas_t9"))

    if st.button("Gerar Hierarquia", key="btn_t9"):
        modo = MODO_TODAS if st.session_state.get("todas_t9") else (
            MODO_ATUAL if st.session_state.get("atual_t9") else None)
        if not tenant_t9 or not token_controle_t9:
            st.error("Preencha o Tenant e o Token do Controle.")
        elif modo is None:
            st.error("Marque uma das opções de atualização das áreas dos funcionários.")
        else:
            bar = st.progress(0, text="Iniciando...")
            try:
                dados = _buscar_dados(tenant_t9.strip(), token_controle_t9.strip(), bar)
                bar.progress(90, text="Montando a hierarquia...")
                st.session_state.t9_resultado = montar_hierarquia(dados, niveis, modo, date.today().strftime('%Y-%m-%d'))
                st.session_state.t9_tenant = tenant_t9.strip()
                st.session_state.t9_processed = True
                bar.progress(100, text="Concluído!")
            except Exception as e:
                st.session_state.t9_processed = False
                bar.empty()
                st.error(f"Erro ao montar a hierarquia: {e}")

    if not st.session_state.t9_processed:
        return

    res = st.session_state.t9_resultado
    tenant = st.session_state.t9_tenant
    st.write("### Resumo")
    st.dataframe(res['resumo'], width='stretch', hide_index=True)

    if not res['avisos'].empty:
        st.write(f"### ⚠️ Avisos ({len(res['avisos'])})")
        st.caption("Confira antes de importar: vínculos sem empresa, filial ou área pai, nomes que já existem no Controle etc.")
        st.dataframe(res['avisos'], width='stretch', hide_index=True)

    st.write(f"### 🌳 Nova hierarquia ({len(res['arvore'])} áreas)")
    st.caption("A última coluna mostra quando já existe no Controle uma área com o mesmo nome (normal quando a área "
               "mantém o nome curto). Ela continua existindo: só os vínculos dos funcionários mudam.")
    st.dataframe(res['arvore'], width='stretch', hide_index=True)

    st.write(f"### 🔁 De → para dos vínculos ({len(res['mapa'])})")
    st.dataframe(res['mapa'], width='stretch', hide_index=True)

    st.markdown("### 📥 Arquivos de importação (suba nesta ordem)")
    arquivos = [
        ('areas', "1. Áreas (instâncias)", "areas"),
        ('registros', "2. Registros de área", "registros_area"),
        ('pais', "3. Áreas pai", "areas_pai"),
        ('funcionarios', "4. Áreas dos funcionários", "areas_funcionarios"),
    ]
    cols = st.columns(len(arquivos))
    for col, (chave, titulo, nome) in zip(cols, arquivos):
        df = res[chave]
        col.metric(titulo, len(df))
        col.download_button("📥 Baixar (Excel)", data=gerar_excel(df), file_name=f"{tenant}_{nome}.xlsx",
                            mime=MIME_EXCEL, key=f"down_t9_{chave}", disabled=df.empty)
    st.caption("No arquivo 4, as linhas com `id` preenchido atualizam um vínculo que já existe; "
               "as linhas com `id` vazio criam um vínculo novo.")

    st.markdown("---")
    planilhas = {
        'Resumo': res['resumo'],
        '1 Áreas': res['areas'],
        '2 Registros de área': res['registros'],
        '3 Áreas pai': res['pais'],
        '4 Áreas dos funcionários': res['funcionarios_conf'],
        'Nova hierarquia': res['arvore'],
        'De para dos vínculos': res['mapa'],
    }
    if not res['avisos'].empty:
        planilhas['Avisos'] = res['avisos']
    st.download_button("📥 Baixar Relatório Completo (Excel)", data=gerar_excel_multi_abas(planilhas),
                       file_name=f"{tenant}_hierarquia_areas.xlsx", mime=MIME_EXCEL, key="down_t9_completo")
