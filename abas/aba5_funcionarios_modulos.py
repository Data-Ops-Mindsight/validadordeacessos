"""
Aba 5 - Validação de FUNCIONÁRIOS entre os módulos.

O Controle é a referência: cada funcionário do Controle (ativo ou desligado) é
procurado nos outros módulos pelo employee_code e comparado com o que está no Controle.

De onde vem cada informação:
  - Controle (API): funcionário (username e UUID), status (registros), gestor,
    cargo e área atuais;
  - People Hub: CSV exportado do admin (liga o person ao employee_code e traz o UUID)
    + API (cargo, área, gestor e usernames);
  - Performance: CSV de participants gerado pelo favorito "Exportar usuários";
  - Metas: CSV de persons gerado pelo favorito "Exportar usuários".

Verificações (uma linha por funcionário do Controle):
  - existe no módulo;
  - username e UUID iguais aos do Controle (Hub, Metas e Performance);
  - gestor atual igual ao do Controle (Hub e Metas);
  - cargo e área atuais iguais aos do Controle (Hub).
"""

import time

import numpy as np
import pandas as pd
import streamlit as st

# Como o arquivo é executado a partir do app.py (na raiz), importamos diretamente
from functions import *
from abas.exportacao_admin import render_criar_favorito

MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VAZIOS = {'nan', 'none', '', '-', 'nat', 'null'}

# Textos usados nas colunas de comparação
OK, DIVERGENTE, NAO_EXISTE = 'OK', 'Divergente', 'Não existe no módulo'
SEM_USUARIO, SEM_UUID = 'Sem usuário no módulo', 'Sem UUID no módulo'


# =============================================================================
# FUNÇÕES DE APOIO
# =============================================================================
def _norm(valor):
    """Padroniza um valor para comparação: texto minúsculo, sem espaços sobrando ('' para vazio)."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ''
    texto = " ".join(str(valor).split()).lower()
    if texto.endswith('.0') and texto[:-2].isdigit():   # ids que vieram como número (ex.: 40.0)
        texto = texto[:-2]
    return '' if texto in VAZIOS else texto


def _limpar_codigo(valor):
    """Texto para exibir um código vindo da API (ex.: 40.0 -> '40'; vazio -> '')."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ''
    texto = str(valor).strip()
    return texto[:-2] if texto.endswith('.0') and texto[:-2].isdigit() else texto


def _registro_atual(df, coluna_valor):
    """
    Para cada employee_code, pega o registro atual (aberto e mais recente; se não houver
    registro aberto, o mais recente) e devolve um dicionário código -> valor da coluna.
    """
    if df is None or df.empty or 'employee_code' not in df.columns or coluna_valor not in df.columns:
        return {}
    d = df.copy()
    d['start'] = pd.to_datetime(d['start'], errors='coerce') if 'start' in d.columns else pd.NaT
    d['end'] = pd.to_datetime(d['end'], errors='coerce') if 'end' in d.columns else pd.NaT
    d['_cod'] = d['employee_code'].apply(_norm)
    # Registro "em aberto" (end vazio) ou o mais recente fica por último
    d = d.sort_values(by=['_cod', 'end', 'start'], ascending=True, na_position='last')
    d = d.drop_duplicates(subset='_cod', keep='last')
    return d.set_index('_cod')[coluna_valor].to_dict()


def _status_controle(df_registros):
    """Ativo = registro mais recente sem data de demissão. Sem registro aberto (ou sem registro) = Desligado."""
    if df_registros is None or df_registros.empty:
        return {}
    d = df_registros.copy()
    d['end'] = pd.to_datetime(d['end'], errors='coerce')
    atual = _registro_atual(d.assign(_aberto=d['end'].isna()), '_aberto')
    return {cod: ('Ativo' if aberto else 'Desligado') for cod, aberto in atual.items()}


def _coluna_texto(df, nome):
    """Devolve a coluna 'nome' (ou 'nome.name', se a API tiver expandido o objeto) como texto."""
    for c in [f'{nome}.name', nome]:
        if c in df.columns:
            return df[c]
    return pd.Series([''] * len(df), index=df.index)


def _exigir_colunas(df, colunas, descricao):
    faltando = [c for c in colunas if c not in df.columns]
    if faltando:
        raise ValueError(f"o {descricao} não possui as colunas: {', '.join(faltando)}.")


def _ler_hub(arquivo, tenant, token_full):
    """
    People Hub: o CSV exportado do admin liga o person ao employee_code (registration_code)
    e traz o UUID; a API traz cargo, área, gestor (manager_id) e os usernames.
    """
    exp = ler_csv_seguro(arquivo, como_texto=True)
    _exigir_colunas(exp, ['id', 'registration_code', 'uuid', 'user'], "CSV exportado do People Hub")
    exp['_id'] = exp['id'].apply(_norm)
    mapa_id_codigo = dict(zip(exp['_id'], exp['registration_code'].apply(_norm)))

    pessoas = chamar_api("os funcionários do People Hub", ler_funcionarios_hub, tenant, token_full)
    validar_retorno_api(pessoas, "os funcionários do People Hub", ['id'])
    pessoas['_id'] = pessoas['id'].apply(_norm)
    pessoas['_cargo'] = _coluna_texto(pessoas, 'position')
    pessoas['_area'] = _coluna_texto(pessoas, 'area')
    pessoas['_gestor_id'] = pessoas['manager_id'].apply(_norm) if 'manager_id' in pessoas.columns else ''
    pessoas = pessoas.drop_duplicates('_id').set_index('_id')

    usuarios = chamar_api("os usuários do People Hub", ler_usuarios_full, tenant, token_full)
    mapa_usuarios = {}
    if not usuarios.empty and {'id', 'username'}.issubset(usuarios.columns):
        mapa_usuarios = dict(zip(usuarios['id'].apply(_norm), usuarios['username']))

    hub = pd.DataFrame({
        '_cod': exp['registration_code'].apply(_norm),
        'Codigo': exp['registration_code'],
        'Username': exp['user'].apply(_norm).map(mapa_usuarios).fillna(''),
        'UUID': exp['uuid'],
        'Gestor': exp['_id'].map(pessoas['_gestor_id']).fillna('').map(lambda g: mapa_id_codigo.get(g, g)),
        'Cargo': exp['_id'].map(pessoas['_cargo']).fillna(''),
        'Area': exp['_id'].map(pessoas['_area']).fillna(''),
    })
    return hub


def _ler_performance(arquivo):
    """Performance: CSV de participants gerado pelo favorito (key = employee_code)."""
    if (arquivo.name or '').lower().startswith('metas_'):
        raise ValueError(f"o arquivo enviado no Performance parece ser do Metas ({arquivo.name}).")
    df = ler_csv_seguro(arquivo, como_texto=True)
    _exigir_colunas(df, ['key', 'username', 'uuid'],
                    "CSV de participants do Performance (gere-o com o favorito na tela de participants)")
    return pd.DataFrame({'_cod': df['key'].apply(_norm), 'Codigo': df['key'],
                         'Username': df['username'], 'UUID': df['uuid']})


def _ler_metas(arquivo):
    """Metas: CSV de persons gerado pelo favorito (key = employee_code; o gestor é outro person)."""
    if (arquivo.name or '').lower().startswith('performance_'):
        raise ValueError(f"o arquivo enviado no Metas parece ser do Performance ({arquivo.name}).")
    df = ler_csv_seguro(arquivo, como_texto=True)
    _exigir_colunas(df, ['id', 'key', 'username', 'uuid', 'parent_id'],
                    "CSV de persons do Metas (gere-o com o favorito na tela de persons)")
    # O Parent é o id de outro person: a key desse person é o código do gestor
    mapa_id_key = dict(zip(df['id'].apply(_norm), df['key'].apply(_norm)))
    return pd.DataFrame({
        '_cod': df['key'].apply(_norm), 'Codigo': df['key'],
        'Username': df['username'], 'UUID': df['uuid'],
        'Gestor': df['parent_id'].apply(_norm).map(lambda g: mapa_id_key.get(g, g) if g else ''),
        'Ativo_no_Modulo': df['is_active'].map(lambda v: 'Sim' if _norm(v) in {'1', 'true'} else 'Não')
        if 'is_active' in df.columns else '',
    })


def _comparar(valor_controle, valor_modulo, existe, texto_vazio=None):
    """OK / Divergente / Não existe no módulo (e, opcionalmente, um texto quando o módulo está vazio)."""
    if not existe:
        return NAO_EXISTE
    a, b = _norm(valor_controle), _norm(valor_modulo)
    if texto_vazio and not b:
        return texto_vazio
    return OK if a == b else DIVERGENTE


# =============================================================================
# TELA
# =============================================================================
def render_aba5():
    st.header("Validação de Funcionários entre Módulos")

    # Explicação do que a aba faz
    st.info(
        "💡 **O que esta aba faz?** O **Controle é a referência**: cada funcionário do Controle, **ativo ou "
        "desligado** (coluna *Status*), é procurado no **People Hub**, no **Metas** e no **Performance** pelo "
        "**código do funcionário** (`employee_code`) e comparado com o que está no Controle.\n\n"
        "🚫 **Funcionários da Mindsight são desconsiderados.**\n\n"
        "✅ **O que é verificado:**\n"
        "- **Existe no módulo:** o funcionário do Controle foi encontrado no Hub, no Metas e no Performance;\n"
        "- **Username e UUID:** iguais aos do funcionário no Controle (Hub, Metas e Performance);\n"
        "- **Gestor atual:** o mesmo gestor do Controle (Hub e Metas);\n"
        "- **Cargo e área atuais:** os mesmos do Controle (Hub).\n\n"
        "Cada módulo é opcional: se o arquivo de um módulo não for enviado, ele não é verificado. "
        "O resultado sai em um Excel com um resumo, a base completa e uma planilha para cada tipo de problema."
    )

    # -------------------------------------------------------------------------
    # SEÇÃO 1: CREDENCIAIS
    # -------------------------------------------------------------------------
    st.markdown("### 🔑 Credenciais de Acesso")
    c1, c2, c3 = st.columns(3)
    tenant_t5 = c1.text_input("Tenant do Cliente", key="tenant_t5", placeholder="Ex: empresa123")
    token_controle_t5 = c2.text_input("Token do Controle", key="token_controle_t5")
    token_full_t5 = c3.text_input("Token do Full (People Hub)", key="token_full_t5",
                                  help="Necessário para verificar o People Hub.")

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # SEÇÃO 2: ARQUIVOS DOS MÓDULOS
    # -------------------------------------------------------------------------
    st.markdown("### 📁 Arquivos dos Módulos")
    with st.expander("❓ Como gerar os arquivos do People Hub, do Performance e do Metas"):
        st.markdown(
            "#### Por que são precisos esses arquivos?\n"
            "- **People Hub:** a API não traz o código do funcionário. Ele só vem na **exportação** do admin;\n"
            "- **Performance:** a tabela de participants só mostra nome e key, e a API não traz o UUID. "
            "O UUID e o usuário só aparecem ao abrir cada participant;\n"
            "- **Metas:** a exportação de persons traz o usuário e o gestor só como números (ids), e a "
            "tabela não mostra o UUID.\n\n"
            "No Performance e no Metas usamos o favorito **Exportar usuários**: na tela de listagem, ele abre "
            "por trás a página de **cada** registro (várias ao mesmo tempo), lê os campos e baixa um CSV. Ele "
            "usa o login que já está aberto no navegador e **apenas lê**: nada é alterado."
        )
        render_criar_favorito("#### Passo 1 - Criar o favorito (só na primeira vez)")
        st.markdown(
            "#### Passo 2 - Exportar os funcionários do People Hub\n"
            "1. Abra `https://hub.mindsight.com.br/<tenant>/staff/people/person/` (troque `<tenant>` pelo tenant do cliente);\n"
            "2. Marque a caixa no topo da tabela e clique em **Selecionar todos** (para pegar todas as páginas);\n"
            "3. Em **Ação**, escolha **Exportar funcionários selecionados**, formato **csv**, e clique em **Ir**;\n"
            "4. ⚠️ **Não abra e salve o arquivo no Excel** antes de enviar: o Excel transforma códigos como "
            "`76706119288` em `7.67E+10` e o código se perde.\n\n"
            "#### Passo 3 - Exportar os participants do Performance\n"
            "1. Abra `https://performance.mindsight.com.br/<tenant>/staff/participants/participant/`;\n"
            "2. Clique no favorito **Exportar usuários**. O aviso roxo mostra o andamento (ele abre cada participant);\n"
            "3. Ao terminar, o arquivo `performance_<tenant>_participantes.csv` é baixado.\n\n"
            "#### Passo 4 - Exportar os persons do Metas\n"
            "1. Abra `https://acompanhamento.mindsight.com.br/<tenant>/admin/person/person/`;\n"
            "2. Clique no favorito **Exportar usuários**;\n"
            "3. Ao terminar, o arquivo `metas_<tenant>_persons.csv` é baixado.\n\n"
            "#### Passo 5 - Enviar os arquivos\n"
            "Envie os arquivos nos campos abaixo, preencha o tenant e os tokens e clique em "
            "**Processar Validação de Funcionários**."
        )
        st.caption("💡 Se o favorito mostrar “Abra a tela de listagem do admin”, confira se você está na tela de "
                   "listagem (participants ou persons) e logado no módulo.")

    c4, c5, c6 = st.columns(3)
    arquivo_hub_t5 = c4.file_uploader("Funcionários do People Hub (.csv)", type=['csv'], key="arquivo_hub_t5",
                                      help="Exportação nativa da tela de funcionários do admin do Hub.")
    arquivo_perf_t5 = c5.file_uploader("Participants do Performance (.csv)", type=['csv'], key="arquivo_perf_t5",
                                       help="Arquivo performance_<tenant>_participantes.csv gerado pelo favorito.")
    arquivo_metas_t5 = c6.file_uploader("Persons do Metas (.csv)", type=['csv'], key="arquivo_metas_t5",
                                        help="Arquivo metas_<tenant>_persons.csv gerado pelo favorito.")

    if st.button("Processar Validação de Funcionários", key="btn_t5"):
        if not tenant_t5 or not token_controle_t5:
            st.error("Preencha o Tenant e o Token do Controle.")
        elif not (arquivo_hub_t5 or arquivo_perf_t5 or arquivo_metas_t5):
            st.error("Envie o arquivo de pelo menos um módulo (People Hub, Performance ou Metas).")
        elif arquivo_hub_t5 and not token_full_t5:
            st.error("Para verificar o People Hub, informe também o Token do Full.")
        else:
            bar = st.progress(0, text="Iniciando...")
            try:
                # --- Arquivos dos módulos (lidos primeiro para avisar logo se algum estiver errado) ---
                bar.progress(5, text="Lendo os arquivos dos módulos...")
                modulos = {}
                if arquivo_perf_t5:
                    modulos['Performance'] = _ler_performance(arquivo_perf_t5)
                if arquivo_metas_t5:
                    modulos['Metas'] = _ler_metas(arquivo_metas_t5)

                # --- Controle (API) ---
                bar.progress(15, text="1/6 - Obtendo funcionários do Controle...")
                func = chamar_api("os funcionários do Controle", get_controle_employees_api, tenant_t5, token_controle_t5)
                validar_retorno_api(func, "os funcionários do Controle", ['employee_code'])

                bar.progress(30, text="2/6 - Obtendo registros (vínculos) do Controle...")
                registros = chamar_api("os registros (vínculos) dos funcionários do Controle",
                                       get_controle_employee_records_api, tenant_t5, token_controle_t5)
                validar_retorno_api(registros, "os registros (vínculos) dos funcionários do Controle",
                                    ['employee_code', 'start', 'end'])

                bar.progress(40, text="3/6 - Obtendo gestores do Controle...")
                gestores = chamar_api("os gestores do Controle", get_controle_employee_managers_api,
                                      tenant_t5, token_controle_t5)

                bar.progress(50, text="4/6 - Obtendo cargos do Controle...")
                cargos = chamar_api("os cargos do Controle", get_controle_employee_positions_api,
                                    tenant_t5, token_controle_t5)

                bar.progress(60, text="5/6 - Obtendo áreas do Controle...")
                areas = chamar_api("as áreas do Controle", get_controle_employee_areas_api,
                                   tenant_t5, token_controle_t5)

                # --- People Hub (CSV exportado + API) ---
                if arquivo_hub_t5:
                    bar.progress(70, text="6/6 - Obtendo funcionários do People Hub...")
                    modulos['Hub'] = _ler_hub(arquivo_hub_t5, tenant_t5, token_full_t5)

                # --- Base do Controle: uma linha por funcionário ---
                bar.progress(85, text="Cruzando os dados...")
                col_user = 'user.username' if 'user.username' in func.columns else 'username'
                col_uuid = 'uuid' if 'uuid' in func.columns else None
                if 'name' in func.columns:
                    nomes = func['name']
                else:
                    nomes = (func.get('first_name', pd.Series('', index=func.index)).fillna('').astype(str) + " " +
                             func.get('last_name', pd.Series('', index=func.index)).fillna('').astype(str)).str.strip()
                base = pd.DataFrame({
                    'employee_code': func['employee_code'].astype(str).str.strip(),
                    'Nome': nomes,
                    'Username_Controle': func[col_user] if col_user in func.columns else '',
                    'UUID_Controle': func[col_uuid] if col_uuid else '',
                })
                for c in ['Nome', 'Username_Controle', 'UUID_Controle']:
                    base[c] = base[c].fillna('')
                base['_cod'] = base['employee_code'].apply(_norm)
                base = base[base['_cod'] != ''].drop_duplicates('_cod')

                # Remove funcionários internos da Mindsight
                eh_mindsight = (base['Username_Controle'].astype(str).str.contains('mindsight', case=False, na=False) |
                                base['employee_code'].str.contains('mindsight', case=False, na=False))
                base = base[~eh_mindsight].copy()

                base['Status'] = base['_cod'].map(_status_controle(registros)).fillna('Desligado')
                base['Gestor_Controle'] = base['_cod'].map(_registro_atual(gestores, 'manager_code')).apply(_limpar_codigo)
                base['Cargo_Controle'] = base['_cod'].map(_registro_atual(cargos, 'name')).fillna('')
                base['Area_Controle'] = base['_cod'].map(_registro_atual(areas, 'name')).fillna('')

                # --- Cruzamento com cada módulo ---
                duplicados = []
                for nome_mod, df_mod in modulos.items():
                    df_mod = df_mod[df_mod['_cod'] != '']
                    # Mesmo código mais de uma vez no módulo: vai para a planilha de duplicados
                    contagem = df_mod['_cod'].value_counts()
                    for cod, qtd in contagem[contagem > 1].items():
                        duplicados.append({'Modulo': nome_mod, 'Codigo': cod, 'Quantidade': int(qtd)})
                    df_mod = df_mod.drop_duplicates('_cod').set_index('_cod')

                    existe = base['_cod'].isin(df_mod.index)
                    base[f'Existe_{nome_mod}'] = np.where(existe, 'Sim', 'Não')
                    if 'Ativo_no_Modulo' in df_mod.columns:
                        base[f'Ativo_no_{nome_mod}'] = base['_cod'].map(df_mod['Ativo_no_Modulo']).fillna('-')
                    for campo, texto_vazio in [('Username', SEM_USUARIO), ('UUID', SEM_UUID)]:
                        base[f'{campo}_{nome_mod}'] = base['_cod'].map(df_mod[campo]).fillna('')
                        base[f'Match_{campo}_{nome_mod}'] = [
                            _comparar(c, m, e, texto_vazio)
                            for c, m, e in zip(base[f'{campo}_Controle'], base[f'{campo}_{nome_mod}'], existe)]
                    campos_extra = [('Gestor', 'Gestor')] if nome_mod == 'Metas' else \
                        [('Gestor', 'Gestor'), ('Cargo', 'Cargo'), ('Area', 'Area')] if nome_mod == 'Hub' else []
                    for campo, col in campos_extra:
                        base[f'{campo}_{nome_mod}'] = base['_cod'].map(df_mod[col]).fillna('')
                        base[f'Match_{campo}_{nome_mod}'] = [
                            _comparar(c, m, e)
                            for c, m, e in zip(base[f'{campo}_Controle'], base[f'{campo}_{nome_mod}'], existe)]

                base = base.drop(columns=['_cod']).sort_values(['Status', 'Nome']).reset_index(drop=True)

                # --- Resumo e planilhas por tipo de problema ---
                col_match = [c for c in base.columns if c.startswith('Match_')]
                resumo = []
                for c in col_match:
                    _, campo, nome_mod = c.split('_', 2)
                    valores = base[c]
                    resumo.append({
                        'Verificação': f"{campo} - {nome_mod}",
                        'OK': int((valores == OK).sum()),
                        'Divergente': int((valores == DIVERGENTE).sum()),
                        'Vazio no módulo': int(valores.isin([SEM_USUARIO, SEM_UUID]).sum()),
                        'Não existe no módulo': int((valores == NAO_EXISTE).sum()),
                    })
                df_resumo = pd.DataFrame(resumo)

                def com_problema(prefixos):
                    cols = [c for c in col_match if any(c.startswith(p) for p in prefixos)]
                    if not cols:
                        return pd.DataFrame()
                    return base[base[cols].isin([DIVERGENTE, SEM_USUARIO, SEM_UUID]).any(axis=1)]

                cols_existe = [c for c in base.columns if c.startswith('Existe_')]
                planilhas = {
                    'Resumo': df_resumo,
                    'Completo': base,
                    'Não Existem nos Módulos': base[(base[cols_existe] == 'Não').any(axis=1)] if cols_existe else pd.DataFrame(),
                    'Username Divergente': com_problema(['Match_Username_']),
                    'UUID Divergente': com_problema(['Match_UUID_']),
                    'Gestor Divergente': com_problema(['Match_Gestor_']),
                    'Cargo e Área Divergentes': com_problema(['Match_Cargo_', 'Match_Area_']),
                    'Duplicados nos Módulos': pd.DataFrame(duplicados, columns=['Modulo', 'Codigo', 'Quantidade']),
                }

                # Guarda os resultados na memória da sessão
                st.session_state.t5_final = base
                st.session_state.t5_resumo = df_resumo
                st.session_state.t5_planilhas = planilhas
                st.session_state.t5_mod_verificados = list(modulos.keys())
                st.session_state.t5_tenant = tenant_t5
                st.session_state.t5_processed = True

                bar.progress(100, text="Concluído!")
                time.sleep(1)
                bar.empty()

            except ErroAPI as e:
                bar.empty()
                st.session_state.t5_processed = False
                st.error(f"❌ Falha na comunicação com a API. {e}")
            except Exception as e:
                bar.empty()
                st.session_state.t5_processed = False
                st.error(f"Ocorreu um erro: {e}")

    # -------------------------------------------------------------------------
    # RESULTADOS E DOWNLOADS
    # -------------------------------------------------------------------------
    if st.session_state.t5_processed:
        tenant = st.session_state.t5_tenant
        base = st.session_state.t5_final
        planilhas = st.session_state.t5_planilhas
        qtd_ativos = int((base['Status'] == 'Ativo').sum())
        st.success(f"✅ Análise concluída para **{tenant}**: {len(base)} funcionários do Controle "
                   f"({qtd_ativos} ativos e {len(base) - qtd_ativos} desligados).")
        st.caption(f"Módulos verificados: {', '.join(st.session_state.t5_mod_verificados)}.")

        st.write("---")
        st.subheader("Resumo das verificações")
        st.markdown(st.session_state.t5_resumo.to_html(index=False), unsafe_allow_html=True)
        st.write("<br>", unsafe_allow_html=True)

        # Uma prévia para cada tipo de problema
        for nome in ['Não Existem nos Módulos', 'Username Divergente', 'UUID Divergente', 'Gestor Divergente',
                     'Cargo e Área Divergentes', 'Duplicados nos Módulos']:
            df = planilhas.get(nome, pd.DataFrame())
            if not df.empty:
                with st.expander(f"👁️ {nome} ({len(df)})"):
                    st.dataframe(df, use_container_width=True)

        st.download_button("📥 Baixar Análise Completa (Excel)",
                           data=gerar_excel_multi_abas({k: v for k, v in planilhas.items() if not v.empty}),
                           file_name=f"{tenant}_funcionarios_x_modulos.xlsx", mime=MIME_EXCEL, key="down_t5")
