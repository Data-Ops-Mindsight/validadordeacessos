"""
Aba 10 - Construção de Relatórios (Controle + planilhas externas).

Monta relatórios a partir do histórico do Controle, com a opção de cruzar o resultado com
uma planilha externa (relatório híbrido). Nada é gravado no Controle.

Ideia central: a "foto" de um funcionário em uma data. Todo dado do Controle que tem
histórico (registro de funcionário, área, área pai, cargo, gestor, salário) é lido no valor
que VALIA naquela data (start <= data <= end; end vazio = em aberto). Cada modelo de
relatório é só uma forma de usar essa foto:

  - Headcount por data: para cada data informada, entra quem tem um registro de funcionário
    válido na data (admissão <= data e desligamento vazio ou >= data; quem foi desligado
    no próprio dia conta). Cada pessoa conta uma vez por data.
  - Movimentação: no período informado, cada mudança de área, cargo ou gestor (troca do
    valor entre um registro e o anterior da mesma pessoa) e cada lançamento de salário
    (todos os tipos de reajuste) vira uma linha: funcionário, tipo, data, de, para.

O usuário escolhe as colunas (o modelo já sugere as padrão), por qual dimensão o resumo é
agrupado e, se quiser, sobe uma planilha externa que é ligada aos funcionários pelo CPF
ou, se não achar, pelo e-mail.

Para criar um modelo novo: acrescente uma entrada em MODELOS e uma função montar_<modelo>.
Funcionários da Mindsight são ignorados.
"""

import re
from datetime import date

import pandas as pd
import streamlit as st

from functions import *

MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VAZIOS = {'nan', 'none', '', '-', 'nat', 'null'}
SEM_VALOR = '(sem informação na data)'


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
    """Texto limpo (sem espaços sobrando); '' para vazio."""
    return " ".join(_codigo(valor).split())


def _data(valor):
    """Data no formato AAAA-MM-DD ('' para vazio)."""
    d = pd.to_datetime(_codigo(valor), errors='coerce')
    return '' if pd.isna(d) else d.strftime('%Y-%m-%d')


def _data_br(valor):
    """AAAA-MM-DD -> DD/MM/AAAA ('' para vazio)."""
    return f"{valor[8:10]}/{valor[5:7]}/{valor[:4]}" if valor else ''


def _cpf(valor):
    """Só os dígitos do CPF, com zeros à esquerda (11 dígitos); '' se não parecer um CPF."""
    digitos = re.sub(r'\D', '', _codigo(valor))
    if not digitos or len(digitos) > 11:
        return ''
    return digitos.zfill(11)


def _email(valor):
    texto = _texto(valor).lower()
    return texto if '@' in texto else ''


def _col(df, nome):
    """Coluna do DataFrame, ou uma coluna vazia se ela não existir."""
    return df[nome] if nome in df.columns else pd.Series([''] * len(df), index=df.index)


def _primeira_col(df, opcoes):
    return next((c for c in opcoes if c in df.columns), None)


def ler_datas(texto):
    """'30/06/2024, 30/06/2025' -> ['2024-06-30', '2025-06-30'] (ordenadas, sem repetir) e a lista de inválidas."""
    validas, invalidas = set(), []
    for parte in re.split(r"[,;\s]+", texto or ''):
        if not parte:
            continue
        d = pd.to_datetime(parte, dayfirst=True, errors='coerce')
        if pd.isna(d):
            invalidas.append(parte)
        else:
            validas.add(d.strftime('%Y-%m-%d'))
    return sorted(validas), invalidas


# =============================================================================
# CATÁLOGO DE COLUNAS
# =============================================================================
# Cada coluna diz de qual base do Controle ela vem. A coluna sempre mostra o valor que
# valia na data de referência (data do headcount ou data da movimentação).
COLUNAS = {
    'Nome':                   'funcionarios',
    'CPF':                    'funcionarios',
    'E-mail':                 'funcionarios',
    'Username':               'funcionarios',
    'Empresa':                'registros',
    'Filial':                 'registros',
    'Tipo de contrato':       'registros',
    'Data de admissão':       'registros',
    'Data de desligamento':   'registros',
    'Área':                   'areas_func',
    'Código da área':         'areas_func',
    'Área pai':               'areas_pai',
    'Cargo':                  'cargos',
    'Gestor':                 'gestores',
    'Código do gestor':       'gestores',
    'Salário':                'salarios',
    'Data do último reajuste': 'salarios',
    'Tipo do último reajuste': 'salarios',
}
AGRUPAMENTOS = ['Área', 'Área pai', 'Cargo', 'Gestor', 'Empresa', 'Filial', 'Tipo de contrato']

# Bases que cada coluna precisa (além dela mesma)
DEPENDENCIAS = {
    'areas_pai': ['areas_func', 'areas'],
    'areas_func': ['areas'],
    'gestores': ['funcionarios'],
    'registros': ['empresas', 'filiais'],
}

TIPOS_MOV = ['Área', 'Cargo', 'Gestor', 'Salário']
ROTULO_MOV = {'Área': 'Mudanças de área', 'Cargo': 'Mudanças de cargo', 'Gestor': 'Mudanças de gestor',
              'Salário': 'Lançamentos de salário'}
BASE_DO_TIPO = {'Área': 'areas_func', 'Cargo': 'cargos', 'Gestor': 'gestores', 'Salário': 'salarios'}

MODELOS = {
    'Headcount por data': {
        'descricao': "Quantidade de pessoas no quadro em cada data informada: total, resumo pela dimensão "
                     "escolhida e lista nominal.",
        'colunas': ['Nome', 'Área', 'Cargo', 'Gestor', 'Empresa', 'Data de admissão', 'Data de desligamento'],
        'agrupar': 'Área',
    },
    'Movimentação': {
        'descricao': "Mudanças de área, cargo, gestor e salário no período: uma linha por mudança, com o valor "
                     "anterior (De) e o novo (Para). Entram todos os lançamentos de salário, de qualquer tipo de "
                     "reajuste.",
        'colunas': ['Nome', 'Área', 'Cargo', 'Gestor'],
        'agrupar': 'Área',
    },
}


# =============================================================================
# LEITURA DO CONTROLE
# =============================================================================
CONSULTAS = {
    # chave: (descrição, função, colunas obrigatórias)
    'funcionarios': ("os funcionários do Controle", 'get_controle_employees_api', ['employee_code']),
    'registros': ("os registros de funcionário do Controle", 'get_controle_employee_records_api',
                  ['employee_code', 'start', 'end']),
    'empresas': ("as empresas do Controle", 'get_controle_corporations_api', None),
    'filiais': ("as filiais do Controle", 'get_controle_branch_corporations_api', None),
    'areas': ("as áreas do Controle", 'get_controle_areas_api', None),
    'areas_pai': ("as áreas pai do Controle", 'get_controle_parent_areas_api', None),
    'areas_func': ("as áreas dos funcionários do Controle", 'get_controle_employee_areas_api',
                   ['employee_code', 'area_code', 'start', 'end']),
    'cargos': ("os cargos dos funcionários do Controle", 'get_controle_employee_positions_api',
               ['employee_code', 'start', 'end']),
    'gestores': ("os gestores dos funcionários do Controle", 'get_controle_employee_managers_api',
                 ['employee_code', 'manager_code', 'start', 'end']),
    'salarios': ("os salários do Controle", 'get_controle_salaries_api', ['employee_code', 'date', 'salary']),
}


def bases_necessarias(colunas, agrupar, tipos_mov):
    """Quais consultas ao Controle o relatório precisa (sempre funcionários e registros)."""
    precisa = {'funcionarios', 'registros'}
    for c in list(colunas) + [agrupar]:
        if c in COLUNAS:
            precisa.add(COLUNAS[c])
    for t in tipos_mov:
        precisa.add(BASE_DO_TIPO[t])
    mudou = True
    while mudou:
        mudou = False
        for b in list(precisa):
            for dep in DEPENDENCIAS.get(b, []):
                if dep not in precisa:
                    precisa.add(dep)
                    mudou = True
    return [k for k in CONSULTAS if k in precisa]


def buscar_dados(tenant, token, bases, bar):
    dados = {}
    for i, chave in enumerate(bases):
        descricao, nome_funcao, obrigatorias = CONSULTAS[chave]
        bar.progress(5 + int(70 * i / len(bases)), text=f"Obtendo {descricao.split(' ', 1)[1]}...")
        df = chamar_api(descricao, globals()[nome_funcao], tenant, token)
        if obrigatorias:
            validar_retorno_api(df, descricao, obrigatorias)
        dados[chave] = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    return dados


# =============================================================================
# PREPARAÇÃO: cada base vira um histórico padronizado (_cod, _start, _end, valores)
# =============================================================================
def _historico(df, valores, col_cod='employee_code', col_start='start', col_end='end'):
    """DataFrame com _cod, _start, _end (AAAA-MM-DD; '' = em aberto) e as colunas de valor pedidas."""
    if df is None or df.empty or col_cod not in df.columns:
        return pd.DataFrame(columns=['_cod', '_start', '_end'] + list(valores))
    h = pd.DataFrame({'_cod': df[col_cod].map(_codigo),
                      '_start': _col(df, col_start).map(_data),
                      '_end': _col(df, col_end).map(_data) if col_end else ''})
    for nome, serie in valores.items():
        h[nome] = serie.values
    return h[h['_cod'] != ''].reset_index(drop=True)


def preparar(dados):
    """Padroniza as bases do Controle. Devolve (funcionários, históricos, códigos da Mindsight)."""
    func = dados['funcionarios'].copy()
    nomes = func['name'] if 'name' in func.columns else (
        _col(func, 'first_name').fillna('').astype(str) + ' ' + _col(func, 'last_name').fillna('').astype(str))
    col_user = _primeira_col(func, ['user.username', 'username'])
    base = pd.DataFrame({
        '_cod': func['employee_code'].map(_codigo),
        'Nome': nomes.map(_texto),
        'Username': func[col_user].map(_texto) if col_user else '',
    })
    # CPFs e e-mails do funcionário (todas as colunas candidatas; o username também vale se for CPF/e-mail)
    cols_cpf = [c for c in func.columns if 'cpf' in c.lower() or c.lower() in ('document', 'documento')]
    cols_email = [c for c in func.columns if 'mail' in c.lower()]
    cpfs = [func[c].map(_cpf) for c in cols_cpf] + ([func[col_user].map(_cpf)] if col_user else [])
    emails = [func[c].map(_email) for c in cols_email] + ([func[col_user].map(_email)] if col_user else [])
    base['_cpfs'] = [sorted({v for v in vals if v}) for vals in zip(*cpfs)] if cpfs else [[]] * len(base)
    base['_emails'] = [sorted({v for v in vals if v}) for vals in zip(*emails)] if emails else [[]] * len(base)
    base['CPF'] = base['_cpfs'].map(lambda l: l[0] if l else '')
    base['E-mail'] = [next((e for e in l if '@' in e), '') for l in base['_emails']]
    base = base[base['_cod'] != ''].drop_duplicates('_cod')

    eh_mindsight = (base['_cod'].str.contains('mindsight', case=False) |
                    base['Username'].str.contains('mindsight', case=False) |
                    base['E-mail'].str.contains('mindsight', case=False))
    mindsight = set(base.loc[eh_mindsight, '_cod'])
    reg_raw = dados['registros']
    for col in ['user.username', 'email', 'user.email']:
        if col in reg_raw.columns:
            mindsight |= set(reg_raw.loc[reg_raw[col].astype(str).str.contains('mindsight', case=False, na=False),
                                         'employee_code'].map(_codigo))
    base = base[~base['_cod'].isin(mindsight)]
    nome_por_cod = dict(zip(base['_cod'], base['Nome']))

    hist = {}
    # --- Registros de funcionário: empresa, filial, tipo de contrato, admissão e desligamento ---
    emp, fil = dados.get('empresas', pd.DataFrame()), dados.get('filiais', pd.DataFrame())
    nome_emp = dict(zip(emp['id'].map(_codigo), emp['name'].map(_texto))) if {'id', 'name'} <= set(emp.columns) else {}
    nome_fil = dict(zip(fil['id'].map(_codigo), fil['name'].map(_texto))) if {'id', 'name'} <= set(fil.columns) else {}
    r = reg_raw
    id_emp = _col(r, 'id_corporation').map(_codigo)
    id_emp = id_emp.where(id_emp != '', _col(r, 'corporation').map(_codigo))
    empresa = id_emp.map(nome_emp).fillna('')
    empresa = empresa.where(empresa != '', _col(r, 'name').map(_texto))
    id_fil = _col(r, 'id_branch_corporation').map(_codigo)
    id_fil = id_fil.where(id_fil != '', _col(r, 'branch_corporation').map(_codigo))
    filial = id_fil.map(nome_fil).fillna('')
    filial = filial.where(filial != '', _col(r, 'name_branch_corporation').map(_texto))
    hist['registros'] = _historico(r, {
        'Empresa': empresa, 'Filial': filial, 'Tipo de contrato': _col(r, 'contract_type').map(_texto),
        'Data de admissão': _col(r, 'start').map(_data).map(_data_br),
        'Data de desligamento': _col(r, 'end').map(_data).map(_data_br),
    })

    # --- Áreas ---
    areas = dados.get('areas', pd.DataFrame())
    nome_area = dict(zip(areas['code'].map(_codigo), areas['name'].map(_texto))) \
        if {'code', 'name'} <= set(areas.columns) else {}
    if 'areas_func' in dados:
        a = dados['areas_func']
        cod_area = a['area_code'].map(_codigo)
        nome = cod_area.map(nome_area).fillna('')
        nome = nome.where(nome != '', _col(a, 'name').map(_texto))
        hist['areas_func'] = _historico(a, {'Área': nome, 'Código da área': cod_area})
    if 'areas_pai' in dados and {'area_code', 'parent_code'} <= set(dados['areas_pai'].columns):
        p = dados['areas_pai']
        cod_pai = p['parent_code'].map(_codigo)
        hist['areas_pai'] = _historico(p, {'Área pai': cod_pai.map(nome_area).fillna(cod_pai)}, col_cod='area_code')

    # --- Cargos ---
    if 'cargos' in dados:
        c = dados['cargos']
        col_nome = _primeira_col(c, ['name', 'position_name', 'position.name', 'position'])
        hist['cargos'] = _historico(c, {'Cargo': c[col_nome].map(_texto) if col_nome else _col(c, 'x')})

    # --- Gestores (nome pelo código do gestor) ---
    if 'gestores' in dados:
        g = dados['gestores']
        cod_gestor = g['manager_code'].map(_codigo)
        hist['gestores'] = _historico(g, {'Gestor': cod_gestor.map(nome_por_cod).fillna(cod_gestor),
                                          'Código do gestor': cod_gestor})

    # --- Salários: cada lançamento vale da sua data até o próximo ---
    if 'salarios' in dados:
        s = dados['salarios']
        hist['salarios'] = _historico(s, {
            'Salário': pd.to_numeric(s['salary'], errors='coerce'),
            'Data do último reajuste': s['date'].map(_data).map(_data_br),
            'Tipo do último reajuste': _col(s, 'raise_type').map(_texto),
        }, col_start='date', col_end=None)

    for k, h in hist.items():
        if k != 'areas_pai':
            hist[k] = h[~h['_cod'].isin(mindsight)].reset_index(drop=True)
    return base, hist


def vigente(pares, hist, colunas, chave='_cod'):
    """
    Para cada par (chave, _data) devolve as colunas do registro do histórico que valia na data:
    _start <= _data e (_end vazio ou _end >= _data). Havendo mais de um, o de início mais recente.
    Sem registro na data, as colunas ficam vazias (NaN).
    """
    if hist is None or hist.empty:
        return pd.DataFrame({c: [pd.NA] * len(pares) for c in colunas}, index=pares.index)
    h = hist[['_cod', '_start', '_end'] + colunas].rename(columns={'_cod': chave})
    m = pares[[chave, '_data']].reset_index().merge(h, on=chave, how='inner')
    m = m[(m['_start'] != '') & (m['_start'] <= m['_data']) & ((m['_end'] == '') | (m['_end'] >= m['_data']))]
    m = m.sort_values('_start', ascending=False).drop_duplicates('index').set_index('index')
    return m[colunas].reindex(pares.index)


def foto(pares, base, hist, colunas):
    """Acrescenta aos pares (_cod, _data) as colunas pedidas, com o valor que valia em cada data."""
    out = pares.copy()
    por_cod = base.set_index('_cod')
    for c in [c for c in colunas if COLUNAS.get(c) == 'funcionarios']:
        out[c] = out['_cod'].map(por_cod[c]).fillna('')
    for b in ['registros', 'areas_func', 'cargos', 'gestores', 'salarios']:
        cols = [c for c in colunas if COLUNAS.get(c) == b]
        if b == 'areas_func' and 'Área pai' in colunas and 'Código da área' not in cols:
            cols.append('Código da área')
        if cols and b in hist:
            vals = vigente(out, hist[b], cols)
            for c in cols:
                out[c] = vals[c]
    if 'Área pai' in colunas and 'areas_pai' in hist:
        pares_area = pd.DataFrame({'_area': out['Código da área'].fillna(''), '_data': out['_data']}, index=out.index)
        out['Área pai'] = vigente(pares_area, hist['areas_pai'], ['Área pai'], chave='_area')['Área pai']
    for c in colunas:
        if c not in out.columns:
            out[c] = ''
        elif c != 'Salário':
            out[c] = out[c].fillna('')
    return out


# =============================================================================
# MODELOS
# =============================================================================
def montar_headcount(base, hist, datas, colunas, agrupar):
    """Headcount em cada data: quem tem registro de funcionário válido na data (desligado no dia conta)."""
    cods = sorted(set(hist['registros']['_cod']) & set(base['_cod']))
    pares = pd.DataFrame([(c, d) for d in datas for c in cods], columns=['_cod', '_data'])
    ativo = vigente(pares, hist['registros'], ['Data de admissão'])['Data de admissão'].notna()
    pares = pares[ativo].reset_index(drop=True)

    cols_foto = list(dict.fromkeys(colunas + [agrupar]))
    det = foto(pares, base, hist, cols_foto)
    det[agrupar] = det[agrupar].replace('', SEM_VALOR)
    det.insert(0, 'Data de referência', det['_data'].map(_data_br))
    det.insert(1, 'Código', det['_cod'])

    rotulo = {d: _data_br(d) for d in datas}
    total = pd.DataFrame({'Data de referência': [rotulo[d] for d in datas],
                          'Headcount': [int((det['_data'] == d).sum()) for d in datas]})
    resumo = det.pivot_table(index=agrupar, columns='_data', values='_cod', aggfunc='nunique', fill_value=0)
    resumo = resumo.reindex(columns=datas, fill_value=0).rename(columns=rotulo).reset_index()
    resumo = resumo.sort_values(agrupar).reset_index(drop=True)
    linha_total = {agrupar: 'TOTAL', **{rotulo[d]: int(resumo[rotulo[d]].sum()) for d in datas}}
    resumo = pd.concat([resumo, pd.DataFrame([linha_total])], ignore_index=True)
    resumo.columns.name = None

    det = det.sort_values(['_data', '_cod']).reset_index(drop=True)
    detalhe = det[['Data de referência', 'Código'] + colunas]
    sem_grupo = int((det[agrupar] == SEM_VALOR).sum())
    avisos = []
    if sem_grupo:
        avisos.append(f"{sem_grupo} linha(s) sem '{agrupar}' na data de referência aparecem como \"{SEM_VALOR}\".")
    return {'Total': total, 'Resumo': resumo, 'Detalhe': detalhe, 'avisos': avisos}


def _mudancas(hist, col_valor, tipo, inicio, fim, col_extra=None):
    """Linhas em que o valor muda em relação ao registro anterior da mesma pessoa, dentro do período."""
    h = hist[hist['_start'] != ''].sort_values(['_cod', '_start']).copy()
    h['De'] = h.groupby('_cod')[col_valor].shift(1)
    h['_fim_ant'] = h.groupby('_cod')['_end'].shift(1)
    h = h[(h['_start'] >= inicio) & (h['_start'] <= fim)]
    if tipo != 'Salário':
        # Não é movimentação: o primeiro registro da pessoa (admissão), um valor repetido e o registro
        # que começa depois de um intervalo (ex.: readmissão, com o registro anterior já encerrado antes)
        vespera = (pd.to_datetime(h['_start']) - pd.Timedelta(days=1)).dt.strftime('%Y-%m-%d')
        continuo = (h['_fim_ant'] == '') | (h['_fim_ant'] >= vespera)
        h = h[h['De'].notna() & continuo & (h['De'].astype(str) != h[col_valor].astype(str))]
    out = pd.DataFrame({'_cod': h['_cod'], '_data': h['_start'], 'Tipo': tipo,
                        'De': h['De'], 'Para': h[col_valor]})
    out['Tipo de reajuste'] = h[col_extra] if col_extra else ''
    return out


def montar_movimentacao(base, hist, inicio, fim, tipos, colunas, agrupar):
    partes = []
    if 'Área' in tipos:
        partes.append(_mudancas(hist['areas_func'], 'Área', 'Área', inicio, fim))
    if 'Cargo' in tipos:
        partes.append(_mudancas(hist['cargos'], 'Cargo', 'Cargo', inicio, fim))
    if 'Gestor' in tipos:
        partes.append(_mudancas(hist['gestores'], 'Gestor', 'Gestor', inicio, fim))
    if 'Salário' in tipos:
        partes.append(_mudancas(hist['salarios'], 'Salário', 'Salário', inicio, fim,
                                col_extra='Tipo do último reajuste'))
    mov = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(
        columns=['_cod', '_data', 'Tipo', 'De', 'Para', 'Tipo de reajuste'])
    mov = mov[mov['_cod'].isin(set(base['_cod']))].reset_index(drop=True)

    cols_foto = list(dict.fromkeys(colunas + [agrupar]))
    det = foto(mov[['_cod', '_data']], base, hist, cols_foto)
    for c in ['Tipo', 'De', 'Para', 'Tipo de reajuste']:
        det[c] = mov[c].fillna('')
    det[agrupar] = det[agrupar].replace('', SEM_VALOR)
    det['Data'] = det['_data'].map(_data_br)
    det['Código'] = det['_cod']
    det = det.sort_values(['_data', '_cod', 'Tipo']).reset_index(drop=True)
    fixas = ['Data', 'Código', 'Tipo', 'De', 'Para'] + (['Tipo de reajuste'] if 'Salário' in tipos else [])
    detalhe = det[fixas + [c for c in colunas if c not in fixas]]

    resumo = det.pivot_table(index=agrupar, columns='Tipo', values='_cod', aggfunc='count', fill_value=0)
    resumo = resumo.reindex(columns=[t for t in TIPOS_MOV if t in tipos], fill_value=0)
    resumo.columns = [ROTULO_MOV[t] for t in resumo.columns]
    resumo['Total'] = resumo.sum(axis=1)
    resumo = resumo.reset_index().sort_values(agrupar).reset_index(drop=True)
    if not resumo.empty:
        linha_total = {agrupar: 'TOTAL', **{c: int(resumo[c].sum()) for c in resumo.columns if c != agrupar}}
        resumo = pd.concat([resumo, pd.DataFrame([linha_total])], ignore_index=True)
    resumo.columns.name = None
    total = pd.DataFrame({'Tipo': [t for t in TIPOS_MOV if t in tipos],
                          'Movimentações': [int((det['Tipo'] == t).sum()) for t in TIPOS_MOV if t in tipos]})
    avisos = [f"O resumo agrupa pela '{agrupar}' que a pessoa tinha na data da movimentação (já com o valor novo)."]
    return {'Total': total, 'Resumo': resumo, 'Detalhe': detalhe, 'avisos': avisos}


# =============================================================================
# PLANILHA EXTERNA (relatório híbrido)
# =============================================================================
def ler_planilha(arquivo):
    if arquivo.name.lower().endswith('.csv'):
        df = ler_csv_seguro(arquivo, como_texto=True)
    else:
        df = pd.read_excel(arquivo, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df.fillna('')


def cruzar_planilha(detalhe, base, planilha, col_cpf, col_email, colunas_trazer):
    """
    Liga cada funcionário do relatório a uma linha da planilha: primeiro pelo CPF; se não achar,
    pelo e-mail. Devolve (detalhe com as colunas da planilha, linhas da planilha não usadas, avisos).
    """
    p = planilha.reset_index(drop=True).copy()
    p['_cpf'] = p[col_cpf].map(_cpf) if col_cpf else ''
    p['_email'] = p[col_email].map(_email) if col_email else ''
    avisos = []
    if col_cpf and p[col_cpf].astype(str).str.contains(r'[eE]\+', regex=True).any():
        avisos.append("Há CPFs em notação científica (ex.: 7.67E+10) na planilha: ela foi salva no Excel com a "
                      "coluna como número. Esses CPFs não serão encontrados.")
    idx_cpf, idx_email = {}, {}
    for i, (c, e) in enumerate(zip(p['_cpf'], p['_email'])):
        if c:
            idx_cpf.setdefault(c, i)
        if e:
            idx_email.setdefault(e, i)
    for nome, chave in [('CPF', '_cpf'), ('e-mail', '_email')]:
        rep = p.loc[p[chave] != '', chave].duplicated().sum()
        if rep:
            avisos.append(f"{rep} linha(s) da planilha repetem um {nome} já usado; vale a primeira ocorrência.")

    por_cod = base.set_index('_cod')
    ligacao = {}
    for cod in detalhe['Código'].unique():
        if cod not in por_cod.index:
            continue
        linha = next((idx_cpf[c] for c in por_cod.at[cod, '_cpfs'] if c in idx_cpf), None)
        via = 'CPF'
        if linha is None:
            linha = next((idx_email[e] for e in por_cod.at[cod, '_emails'] if e in idx_email), None)
            via = 'E-mail'
        if linha is not None:
            ligacao[cod] = (linha, via)

    out = detalhe.copy()
    linha_de = out['Código'].map(lambda c: ligacao.get(c, (None,))[0])
    out['Ligação com a planilha'] = out['Código'].map(lambda c: ligacao.get(c, (None, 'Não encontrado'))[1])
    for c in colunas_trazer:
        nome = c if c not in out.columns else f"{c} (planilha)"
        out[nome] = linha_de.map(lambda i: p.at[int(i), c] if pd.notna(i) else '')
    usadas = {v[0] for v in ligacao.values()}
    nao_usadas = planilha.reset_index(drop=True).loc[[i for i in range(len(p)) if i not in usadas]]
    return out, nao_usadas, avisos


# =============================================================================
# TELA
# =============================================================================
def _sugestao(colunas, termos):
    return next((c for c in colunas if any(t in c.lower() for t in termos)), None)


def render_aba10():
    for chave, valor in {'t10_processed': False, 't10_tenant': "", 't10_resultado': {}}.items():
        st.session_state.setdefault(chave, valor)

    st.header("Construção de Relatórios")
    st.info(
        "💡 **O que esta página faz?**\n"
        "Monta relatórios a partir do **histórico do Controle**: cada coluna mostra o valor que valia na data de "
        "referência (área, cargo, gestor, salário etc. daquele dia, não o atual). Escolha um modelo, ajuste as "
        "colunas e, se quiser, cruze com uma **planilha externa** (ligação pelo CPF ou, se não achar, pelo e-mail). "
        "Nada é gravado no Controle.\n\n"
        "🚫 Funcionários da Mindsight são desconsiderados."
    )

    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2 = st.columns(2)
    tenant = c1.text_input("Tenant do Cliente", key="tenant_t10", placeholder="Ex: empresa123")
    token = c2.text_input("Token do Controle", key="token_controle_t10")

    st.markdown("### 📋 Modelo de relatório")
    modelo = st.radio("Escolha o relatório:", list(MODELOS), key="modelo_t10", horizontal=True)
    cfg = MODELOS[modelo]
    st.caption(cfg['descricao'])

    datas, tipos, inicio, fim = [], [], '', ''
    if modelo == 'Headcount por data':
        texto = st.text_input("Datas de referência (DD/MM/AAAA, separadas por vírgula)", key="datas_t10",
                              placeholder="30/06/2024, 30/06/2025, 30/06/2026")
        datas, invalidas = ler_datas(texto)
        if invalidas:
            st.warning(f"Datas não reconhecidas: {', '.join(invalidas)}")
        st.caption("Entra no quadro quem foi admitido até a data e não tinha sido desligado antes dela "
                   "(quem foi desligado no próprio dia conta).")
    else:
        c1, c2 = st.columns(2)
        ini = c1.date_input("Início do período", key="inicio_t10", value=date(date.today().year, 1, 1),
                            format="DD/MM/YYYY")
        fi = c2.date_input("Fim do período", key="fim_t10", value=date.today(), format="DD/MM/YYYY")
        inicio, fim = ini.strftime('%Y-%m-%d'), fi.strftime('%Y-%m-%d')
        tipos = st.multiselect("Movimentações", TIPOS_MOV, default=TIPOS_MOV, key="tipos_t10")

    st.markdown("### 🧩 Colunas e resumo")
    colunas = st.multiselect("Colunas do relatório (remova ou acrescente)", list(COLUNAS),
                             default=cfg['colunas'], key=f"colunas_t10_{modelo}")
    st.caption("O código do funcionário sempre aparece. Todas as colunas mostram o valor que valia na data de "
               "referência.")
    agrupar = st.selectbox("Agrupar o resumo por", AGRUPAMENTOS, index=AGRUPAMENTOS.index(cfg['agrupar']),
                           key="agrupar_t10")

    st.markdown("### 📎 Planilha externa (opcional)")
    arquivo = st.file_uploader("Planilha para cruzar com o relatório (Excel ou CSV)", type=['xlsx', 'xls', 'csv'],
                               key="planilha_t10")
    planilha, col_cpf, col_email, colunas_trazer = None, None, None, []
    if arquivo is not None:
        try:
            planilha = ler_planilha(arquivo)
        except Exception as e:
            st.error(f"Não foi possível ler a planilha: {e}")
        if planilha is not None:
            cols = list(planilha.columns)
            nenhuma = '(não usar)'
            c1, c2 = st.columns(2)
            sug_cpf, sug_email = _sugestao(cols, ['cpf']), _sugestao(cols, ['mail'])
            col_cpf = c1.selectbox("Coluna de CPF na planilha", [nenhuma] + cols,
                                   index=(cols.index(sug_cpf) + 1) if sug_cpf else 0, key="col_cpf_t10")
            col_email = c2.selectbox("Coluna de e-mail na planilha", [nenhuma] + cols,
                                     index=(cols.index(sug_email) + 1) if sug_email else 0, key="col_email_t10")
            col_cpf = None if col_cpf == nenhuma else col_cpf
            col_email = None if col_email == nenhuma else col_email
            colunas_trazer = st.multiselect("Colunas da planilha que entram no relatório",
                                            [c for c in cols if c not in (col_cpf, col_email)],
                                            default=[c for c in cols if c not in (col_cpf, col_email)],
                                            key="trazer_t10")
            st.caption(f"{len(planilha)} linha(s) na planilha. A ligação tenta primeiro o CPF e, se não achar, "
                       "o e-mail do funcionário no Controle.")

    if st.button("Gerar Relatório", key="btn_t10"):
        erro = None
        if not tenant or not token:
            erro = "Preencha o Tenant e o Token do Controle."
        elif modelo == 'Headcount por data' and not datas:
            erro = "Informe pelo menos uma data de referência."
        elif modelo == 'Movimentação' and (not tipos or inicio > fim):
            erro = "Escolha ao menos um tipo de movimentação e um período válido."
        elif planilha is not None and not (col_cpf or col_email):
            erro = "Escolha a coluna de CPF ou a de e-mail da planilha."
        if erro:
            st.error(erro)
        else:
            bar = st.progress(0, text="Iniciando...")
            try:
                bases = bases_necessarias(colunas, agrupar, tipos)
                dados = buscar_dados(tenant.strip(), token.strip(), bases, bar)
                bar.progress(80, text="Montando o relatório...")
                base, hist = preparar(dados)
                if modelo == 'Headcount por data':
                    res = montar_headcount(base, hist, datas, colunas, agrupar)
                else:
                    res = montar_movimentacao(base, hist, inicio, fim, tipos, colunas, agrupar)
                res['Planilha não encontrados'] = None
                if planilha is not None:
                    bar.progress(90, text="Cruzando com a planilha...")
                    res['Detalhe'], nao_usadas, avisos_p = cruzar_planilha(
                        res['Detalhe'], base, planilha, col_cpf, col_email, colunas_trazer)
                    res['Planilha não encontrados'] = nao_usadas
                    res['avisos'] += avisos_p
                res['modelo'] = modelo
                st.session_state.t10_resultado = res
                st.session_state.t10_tenant = tenant.strip()
                st.session_state.t10_processed = True
                bar.progress(100, text="Concluído!")
            except Exception as e:
                st.session_state.t10_processed = False
                bar.empty()
                st.error(f"Erro ao montar o relatório: {e}")

    if not st.session_state.t10_processed:
        return

    res = st.session_state.t10_resultado
    tenant_res = st.session_state.t10_tenant
    st.markdown(f"### 📊 {res['modelo']}")
    for aviso in res['avisos']:
        st.warning(aviso)
    c1, c2 = st.columns([1, 2])
    c1.dataframe(res['Total'], width='stretch', hide_index=True)
    c2.dataframe(res['Resumo'], width='stretch', hide_index=True)

    det = res['Detalhe']
    st.write(f"### 🧾 Detalhe ({len(det)} linhas)")
    if 'Ligação com a planilha' in det.columns:
        cont = det.drop_duplicates('Código')['Ligação com a planilha'].value_counts()
        st.caption("Ligação com a planilha (por funcionário): " +
                   ", ".join(f"{k}: {v}" for k, v in cont.items()))
    st.dataframe(det, width='stretch', hide_index=True)

    nao = res.get('Planilha não encontrados')
    if nao is not None and not nao.empty:
        st.write(f"### ❓ Linhas da planilha sem funcionário no relatório ({len(nao)})")
        st.caption("Não bateram por CPF nem por e-mail com nenhum funcionário deste relatório.")
        st.dataframe(nao, width='stretch', hide_index=True)

    planilhas = {'Total': res['Total'], 'Resumo': res['Resumo'], 'Detalhe': det}
    if nao is not None and not nao.empty:
        planilhas['Planilha não encontrados'] = nao
    if res['avisos']:
        planilhas['Avisos'] = pd.DataFrame({'Aviso': res['avisos']})
    nome = 'headcount' if res['modelo'] == 'Headcount por data' else 'movimentacao'
    st.download_button("📥 Baixar Relatório (Excel)", data=gerar_excel_multi_abas(planilhas),
                       file_name=f"{tenant_res}_{nome}.xlsx", mime=MIME_EXCEL, key="down_t10")
