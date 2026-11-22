"""
Aba 8 - Validação de Salários (Controle x People Hub).

Fluxo da aba:
  1. O usuário informa tenant, token do Controle e token do Full (People Hub).
  2. Ao clicar em "Validar Salários", a ferramenta busca:
       - Controle: funcionários e salários (o salário já traz o employee_code);
       - People Hub: funcionários e salários (o salário traz o id do person).
     O person do Hub é ligado ao employee_code do Controle pelo UUID do funcionário.
  3. Compara os salários pela chave funcionário (employee_code) + data:
       - Só no Controle / Só no Hub: a data não existe do outro lado;
       - Divergente: a data existe dos dois lados, mas o valor (2 casas) ou o tipo de
         reajuste (raise_type) é diferente.
  4. Procura quedas salariais em cada sistema: salário menor que o imediatamente anterior
     do mesmo funcionário. Salários do mesmo funcionário na mesma data viram "Data duplicada".
  Funcionários da Mindsight são ignorados.
"""

import pandas as pd
import streamlit as st

from functions import *

MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VAZIOS = {'nan', 'none', '', '-', 'nat', 'null'}


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


def _tipo(valor):
    """Tipo de reajuste padronizado para comparação (minúsculo, sem espaços sobrando)."""
    texto = _codigo(valor)
    return " ".join(texto.split()).lower()


def _preparar_salarios(df, col_codigo, sistema):
    """Padroniza data (AAAA-MM-DD), valor (2 casas) e tipo de reajuste de uma base de salários."""
    df = df.copy()
    df['employee_code'] = df[col_codigo].map(_codigo)
    df['Data'] = pd.to_datetime(df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
    df['Valor'] = pd.to_numeric(df['salary'], errors='coerce').round(2)
    df['Tipo de reajuste'] = df['raise_type'].map(_codigo) if 'raise_type' in df.columns else ''
    df['Sistema'] = sistema
    return df


def _quedas(df):
    """
    Marca, por funcionário, os salários menores que o imediatamente anterior (ordem de data)
    e os salários com data repetida. Devolve só as linhas com algum problema.
    """
    if df.empty:
        return df.assign(**{'Salário anterior': None, 'Data anterior': None, 'Problema': None})
    d = df.sort_values(['employee_code', 'Data', 'Valor']).reset_index(drop=True)
    grupo = d.groupby('employee_code')
    d['Salário anterior'] = grupo['Valor'].shift(1)
    d['Data anterior'] = grupo['Data'].shift(1)
    duplicada = d.duplicated(['employee_code', 'Data'], keep=False)
    queda = (d['Valor'] < d['Salário anterior']) & d['Salário anterior'].notna() & (d['Data'] != d['Data anterior'])
    d['Problema'] = ''
    d.loc[queda, 'Problema'] = 'Queda salarial encontrada'
    d.loc[duplicada, 'Problema'] = 'Data duplicada'
    return d[d['Problema'] != '']


# =============================================================================
# PROCESSAMENTO
# =============================================================================
def _processar(tenant, token_controle, token_full, bar):
    # --- Controle ---
    bar.progress(10, text="Obtendo funcionários do Controle...")
    func_ctrl = chamar_api("os funcionários do Controle", get_controle_employees_api, tenant, token_controle)
    validar_retorno_api(func_ctrl, "os funcionários do Controle", ['employee_code', 'uuid'])
    func_ctrl = func_ctrl.copy()
    func_ctrl['employee_code'] = func_ctrl['employee_code'].map(_codigo)
    user_col = 'user.username' if 'user.username' in func_ctrl.columns else None
    eh_mindsight = func_ctrl['employee_code'].str.contains('mindsight', case=False, na=False)
    if user_col:
        eh_mindsight |= func_ctrl[user_col].astype(str).str.contains('mindsight', case=False, na=False)
    codigos_mindsight = set(func_ctrl.loc[eh_mindsight, 'employee_code'])
    if 'name' in func_ctrl.columns:
        nomes = func_ctrl['name']
    else:
        nomes = (func_ctrl.get('first_name', '').fillna('') + ' ' + func_ctrl.get('last_name', '').fillna('')).str.strip()
    nome_por_codigo = dict(zip(func_ctrl['employee_code'], nomes))

    bar.progress(25, text="Obtendo salários do Controle...")
    sal_ctrl = chamar_api("os salários do Controle", get_controle_salaries_api, tenant, token_controle)
    if sal_ctrl is None or sal_ctrl.empty:
        sal_ctrl = pd.DataFrame(columns=['employee_code', 'date', 'salary', 'raise_type'])
    sal_ctrl = _preparar_salarios(sal_ctrl, 'employee_code', 'Controle')

    # --- People Hub ---
    bar.progress(45, text="Obtendo funcionários do People Hub...")
    func_hub = chamar_api("os funcionários do People Hub", get_hub_employees_api, tenant, token_full)
    validar_retorno_api(func_hub, "os funcionários do People Hub", ['id', 'uuid'])
    bar.progress(65, text="Obtendo salários do People Hub...")
    sal_hub = chamar_api("os salários do People Hub", get_hub_salaries_api, tenant, token_full)
    if sal_hub is None or sal_hub.empty:
        sal_hub = pd.DataFrame(columns=['person', 'date', 'salary', 'raise_type', 'raise_type_key'])

    # Liga o person do Hub ao employee_code do Controle pelo UUID
    ctrl_por_uuid = dict(zip(func_ctrl['uuid'].map(_codigo).str.lower(), func_ctrl['employee_code']))
    func_hub = func_hub.copy()
    func_hub['id_hub'] = func_hub['id'].map(_codigo)
    func_hub['employee_code'] = func_hub['uuid'].map(_codigo).str.lower().map(ctrl_por_uuid)
    codigo_por_person = dict(zip(func_hub['id_hub'], func_hub['employee_code']))

    sal_hub = sal_hub.copy()
    sal_hub['person_id'] = sal_hub['person'].map(_codigo)
    sal_hub['employee_code'] = sal_hub['person_id'].map(codigo_por_person)

    # Funcionários do Hub sem correspondência no Controle
    col_nome_hub = next((c for c in ['name', 'full_name', 'person_name'] if c in func_hub.columns), None)
    sem_par = func_hub[func_hub['employee_code'].isna()].copy()
    sem_par = sem_par[~sem_par[col_nome_hub].astype(str).str.contains('mindsight', case=False, na=False)] if col_nome_hub else sem_par
    # Salários do Hub que não puderam ser ligados a um funcionário do Controle
    qtd_sal_sem_par = int(sal_hub['employee_code'].isna().sum())
    sal_por_person = sal_hub.groupby('person_id').size()
    df_sem_par = pd.DataFrame({
        'id do person (Hub)': sem_par['id_hub'],
        'Nome no Hub': sem_par[col_nome_hub] if col_nome_hub else '',
        'UUID no Hub': sem_par['uuid'],
        'Salários no Hub': sem_par['id_hub'].map(sal_por_person).fillna(0).astype(int),
    })
    sal_hub = sal_hub[sal_hub['employee_code'].notna()].copy()
    sal_hub['raise_type_key'] = sal_hub['raise_type_key'] if 'raise_type_key' in sal_hub.columns else ''
    sal_hub = _preparar_salarios(sal_hub, 'employee_code', 'People Hub')
    sal_hub['_tipo_key'] = sal_hub['raise_type_key'].map(_tipo)

    # Remove Mindsight
    sal_ctrl = sal_ctrl[~sal_ctrl['employee_code'].isin(codigos_mindsight)]
    sal_hub = sal_hub[~sal_hub['employee_code'].isin(codigos_mindsight)]

    bar.progress(85, text="Comparando salários...")
    # --- Comparação por funcionário + data ---
    c = sal_ctrl[['employee_code', 'Data', 'Valor', 'Tipo de reajuste']].rename(
        columns={'Valor': 'Valor no Controle', 'Tipo de reajuste': 'Tipo no Controle'})
    h = sal_hub[['employee_code', 'Data', 'Valor', 'Tipo de reajuste', '_tipo_key']].rename(
        columns={'Valor': 'Valor no Hub', 'Tipo de reajuste': 'Tipo no Hub'})
    comp = c.merge(h, on=['employee_code', 'Data'], how='outer', indicator=True)
    comp.insert(0, 'Colaborador', comp['employee_code'].map(nome_por_codigo).fillna(''))

    so_ctrl = comp[comp['_merge'] == 'left_only']
    so_hub = comp[comp['_merge'] == 'right_only']
    ambos = comp[comp['_merge'] == 'both'].copy()
    tipo_ctrl = ambos['Tipo no Controle'].map(_tipo)
    tipo_ok = (tipo_ctrl == ambos['Tipo no Hub'].map(_tipo)) | (tipo_ctrl == ambos['_tipo_key'])
    valor_ok = (ambos['Valor no Controle'] - ambos['Valor no Hub']).abs() < 0.005
    ambos['Divergência'] = [' e '.join(p for p, ok in (('Valor', v), ('Tipo de reajuste', t)) if not ok)
                            for v, t in zip(valor_ok, tipo_ok)]
    divergentes = ambos[ambos['Divergência'] != '']
    qtd_iguais = int((ambos['Divergência'] == '').sum())

    base_cols = ['Colaborador', 'employee_code', 'Data']
    df_so_ctrl = so_ctrl[base_cols + ['Valor no Controle', 'Tipo no Controle']].sort_values(base_cols)
    df_so_hub = so_hub[base_cols + ['Valor no Hub', 'Tipo no Hub']].sort_values(base_cols)
    df_div = divergentes[base_cols + ['Divergência', 'Valor no Controle', 'Valor no Hub',
                                      'Tipo no Controle', 'Tipo no Hub']].sort_values(base_cols)

    # --- Quedas salariais e datas duplicadas ---
    def _tabela_quedas(df):
        q = _quedas(df[['employee_code', 'Data', 'Valor', 'Tipo de reajuste']])
        q.insert(0, 'Colaborador', q['employee_code'].map(nome_por_codigo).fillna(''))
        return q[['Colaborador', 'employee_code', 'Problema', 'Data anterior', 'Salário anterior',
                  'Data', 'Valor', 'Tipo de reajuste']].rename(columns={'Valor': 'Salário'})
    df_quedas_ctrl = _tabela_quedas(sal_ctrl)
    df_quedas_hub = _tabela_quedas(sal_hub)

    resumo = pd.DataFrame([
        ('Salários no Controle', len(sal_ctrl)),
        ('Salários no People Hub (ligados a um funcionário do Controle)', len(sal_hub)),
        ('Salários iguais nos dois sistemas', qtd_iguais),
        ('Salários só no Controle', len(df_so_ctrl)),
        ('Salários só no People Hub', len(df_so_hub)),
        ('Salários divergentes (valor ou tipo de reajuste)', len(df_div)),
        ('Quedas / datas duplicadas no Controle', len(df_quedas_ctrl)),
        ('Quedas / datas duplicadas no People Hub', len(df_quedas_hub)),
        ('Funcionários do Hub sem correspondência no Controle', len(df_sem_par)),
        ('Salários do Hub sem funcionário no Controle (não comparados)', qtd_sal_sem_par),
    ], columns=['Item', 'Quantidade'])

    return {
        'resumo': resumo,
        'Só no Controle': df_so_ctrl,
        'Só no People Hub': df_so_hub,
        'Divergentes': df_div,
        'Quedas no Controle': df_quedas_ctrl,
        'Quedas no People Hub': df_quedas_hub,
        'Hub sem par no Controle': df_sem_par,
    }


# =============================================================================
# TELA
# =============================================================================
TABELAS = [
    ('Só no Controle', "📕 Salários só no Controle",
     "Salários cadastrados no Controle que não existem no People Hub para o mesmo funcionário e data."),
    ('Só no People Hub', "📘 Salários só no People Hub",
     "Salários cadastrados no People Hub que não existem no Controle para o mesmo funcionário e data."),
    ('Divergentes', "⚠️ Salários divergentes",
     "Mesmo funcionário e data nos dois sistemas, mas com valor ou tipo de reajuste diferente."),
    ('Quedas no Controle', "📉 Quedas salariais no Controle",
     "Salário menor que o imediatamente anterior do mesmo funcionário, ou dois salários na mesma data."),
    ('Quedas no People Hub', "📉 Quedas salariais no People Hub",
     "Salário menor que o imediatamente anterior do mesmo funcionário, ou dois salários na mesma data."),
    ('Hub sem par no Controle', "❓ Funcionários do People Hub sem correspondência no Controle",
     "O UUID desses funcionários não foi encontrado no Controle, então os salários deles não foram comparados."),
]


def render_aba8():
    st.header("Validação de Salários")

    st.info(
        "💡 **O que é validado?**\n"
        "- **Controle x People Hub:** cada salário (funcionário + data) precisa existir nos dois sistemas "
        "com o **mesmo valor** (arredondado em 2 casas) e o **mesmo tipo de reajuste** (`raise_type`). "
        "A moeda não é comparada.\n"
        "- **Quedas salariais:** em cada sistema, um salário menor que o salário imediatamente anterior "
        "do mesmo funcionário. Dois salários na mesma data aparecem como **Data duplicada** "
        "(o Controle não permite, mas pode acontecer no People Hub).\n\n"
        "🔗 O funcionário do People Hub é ligado ao do Controle pelo **UUID**. Todos os funcionários "
        "entram, ativos e desligados. 🚫 Funcionários da Mindsight são desconsiderados."
    )

    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2, c3 = st.columns(3)
    tenant_t8 = c1.text_input("Tenant do Cliente", key="tenant_t8", placeholder="Ex: empresa123")
    token_controle_t8 = c2.text_input("Token do Controle", key="token_controle_t8")
    token_full_t8 = c3.text_input("Token do Full (People Hub)", key="token_full_t8")

    if st.button("Validar Salários", key="btn_t8"):
        if not tenant_t8 or not token_controle_t8 or not token_full_t8:
            st.error("Preencha o Tenant, o Token do Controle e o Token do Full.")
        else:
            bar = st.progress(0, text="Iniciando...")
            try:
                st.session_state.t8_resultado = _processar(tenant_t8.strip(), token_controle_t8.strip(),
                                                           token_full_t8.strip(), bar)
                st.session_state.t8_tenant = tenant_t8.strip()
                st.session_state.t8_processed = True
                bar.progress(100, text="Concluído!")
            except Exception as e:
                st.session_state.t8_processed = False
                bar.empty()
                st.error(f"Erro ao validar os salários: {e}")

    if not st.session_state.t8_processed:
        return

    res = st.session_state.t8_resultado
    tenant = st.session_state.t8_tenant
    st.write("### Resumo")
    st.dataframe(res['resumo'], width='stretch', hide_index=True)

    if all(res[chave].empty for chave, _, _ in TABELAS):
        st.success("✅ Nenhuma divergência encontrada: os salários batem entre Controle e People Hub e não há quedas.")
        return

    for i, (chave, titulo, explicacao) in enumerate(TABELAS):
        df = res[chave]
        if df.empty:
            continue
        st.write(f"### {titulo} ({len(df)})")
        st.caption(explicacao)
        st.dataframe(df, width='stretch', hide_index=True)
        st.download_button(f"📥 Baixar {titulo[2:]} (Excel)", data=gerar_excel(df),
                           file_name=f"{tenant}_salarios_{chave.lower().replace(' ', '_')}.xlsx",
                           mime=MIME_EXCEL, key=f"down_t8_{i}")

    st.markdown("---")
    planilhas = {'Resumo': res['resumo']}
    planilhas.update({chave: res[chave] for chave, _, _ in TABELAS if not res[chave].empty})
    st.download_button("📥 Baixar Relatório Completo (Excel)", data=gerar_excel_multi_abas(planilhas),
                       file_name=f"{tenant}_validacao_salarios.xlsx", mime=MIME_EXCEL, key="down_t8_completo")
