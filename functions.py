"""
Funções de apoio do Validador de Acessos.

Aqui ficam:
- leitura dos arquivos enviados pelo usuário (CSV do Auth);
- chamadas às APIs da Mindsight (com mensagens de erro claras);
- a regra que decide quais acessos (access_to_systems) cada usuário deve ter;
- a montagem do CSV final no formato aceito pelo upload do Auth.
"""

import re
import pandas as pd
import numpy as np
import requests
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pandas import json_normalize

# Importações Mindsight (pacote privado clonado pelo app.py na inicialização)
from mindsight_api_requests.wrappers.auth import *
from mindsight_api_requests.wrappers.hub import *
from mindsight_api_requests.wrappers.controle import *


# =============================================================================
# TRATAMENTO DE ERROS DE API
# =============================================================================
class ErroAPI(Exception):
    """Erro de comunicação com alguma API, já com uma mensagem pronta para mostrar ao usuário."""
    pass


def descrever_status_http(status_code):
    """Traduz os códigos HTTP mais comuns em uma explicação curta em português."""
    explicacoes = {
        400: "requisição inválida",
        401: "token inválido ou expirado",
        403: "o token não tem permissão para este recurso",
        404: "endereço não encontrado (confira se o tenant está correto)",
        429: "muitas requisições seguidas; aguarde um pouco e tente de novo",
        500: "erro interno no servidor da Mindsight",
        502: "servidor da Mindsight indisponível no momento",
        503: "servidor da Mindsight indisponível no momento",
        504: "o servidor da Mindsight demorou demais para responder",
    }
    return explicacoes.get(status_code, "resposta inesperada do servidor")


def chamar_api(descricao, funcao, *args, **kwargs):
    """
    Executa uma função que consulta uma API e, se algo der errado, levanta um
    ErroAPI com uma mensagem clara dizendo QUAL consulta falhou e o que conferir.

    descricao: texto curto que identifica a consulta (ex.: "funcionários do Controle").
    funcao:    a função que faz a chamada (ex.: get_controle_employees_api).
    """
    try:
        return funcao(*args, **kwargs)
    except ErroAPI:
        # Já veio com mensagem pronta (ex.: da paginação abaixo); só repassa.
        raise
    except requests.exceptions.ConnectionError:
        raise ErroAPI(
            f"Não foi possível conectar à API ao buscar {descricao}. "
            "Verifique sua conexão com a internet e se o tenant está correto."
        )
    except requests.exceptions.Timeout:
        raise ErroAPI(f"A API demorou demais para responder ao buscar {descricao}. Tente novamente.")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        raise ErroAPI(
            f"A API respondeu com erro {status} ao buscar {descricao}: "
            f"{descrever_status_http(status)}."
        )
    except Exception as e:
        raise ErroAPI(
            f"Falha ao buscar {descricao}. Confira o tenant e o token informados. "
            f"Detalhe técnico: {type(e).__name__}: {e}"
        )


def validar_retorno_api(df, descricao, colunas_obrigatorias):
    """
    Confere se a API devolveu dados utilizáveis. Uma resposta vazia ou sem as
    colunas esperadas normalmente indica tenant/token errado ou falha silenciosa.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        raise ErroAPI(
            f"A API não retornou nenhum dado ao buscar {descricao}. "
            "Confira se o tenant e o token estão corretos e se o cliente possui dados nesse módulo."
        )
    faltando = [c for c in colunas_obrigatorias if c not in df.columns]
    if faltando:
        raise ErroAPI(
            f"A resposta da API para {descricao} veio incompleta "
            f"(faltam as colunas: {', '.join(faltando)}). Confira o tenant e o token."
        )
    return df


# =============================================================================
# UTILITÁRIOS DE ENTRADA E SAÍDA
# =============================================================================
def separar_usuarios(texto):
    """
    Converte o conteúdo de um campo de texto em uma lista de usernames.
    Aceita usuários separados por vírgula, ponto e vírgula ou quebra de linha
    (ou qualquer mistura disso), ignorando espaços e linhas vazias.

    Ex.: "joao.silva, maria.santos\\npedro.costa" -> ['joao.silva', 'maria.santos', 'pedro.costa']
    """
    if not texto or not str(texto).strip():
        return []
    partes = re.split(r"[,;\r\n]+", str(texto))
    return [p.strip() for p in partes if p.strip()]


def gerar_excel(df):
    """Gera um arquivo Excel (.xlsx) em memória a partir de um DataFrame."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Planilha1')
    return output.getvalue()


def gerar_excel_multi_abas(dict_dfs):
    """Gera um Excel (.xlsx) com várias planilhas: {'nome da planilha': DataFrame}."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for nome_aba, df in dict_dfs.items():
            df.to_excel(writer, index=False, sheet_name=nome_aba[:31])  # Excel limita a 31 caracteres
    return output.getvalue()


def ler_csv_seguro(uploaded_file):
    """
    Lê o CSV enviado pelo usuário tentando primeiro detectar o separador
    automaticamente (UTF-8). Se falhar, tenta o padrão Excel brasileiro
    (separador ';' e codificação latin1). Também remove espaços dos nomes das colunas.
    """
    uploaded_file.seek(0)
    try:
        df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
    except Exception:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, sep=';', encoding='latin1')
    df.columns = [str(c).strip() for c in df.columns]
    return df


# =============================================================================
# CONSULTAS DIRETAS À API (People Hub / Full)
# =============================================================================
def fetch_data_with_pagination(url, headers, page_size=1000):
    """
    Busca todas as páginas de um endpoint paginado (padrão Django REST:
    campos 'results' e 'next'). Se qualquer página falhar, levanta ErroAPI
    em vez de seguir com dados incompletos.
    """
    results = []
    current_url = url
    while current_url:
        response = requests.get(current_url, headers=headers)
        if response.status_code != 200:
            raise ErroAPI(
                f"A API respondeu com erro {response.status_code} "
                f"({descrever_status_http(response.status_code)}) ao acessar {current_url.split('?')[0]}."
            )
        try:
            data = response.json()
        except ValueError:
            raise ErroAPI(
                f"A API devolveu uma resposta que não é JSON ao acessar {current_url.split('?')[0]}. "
                "Confira se o tenant está correto."
            )
        results.extend(data.get('results', []))
        current_url = data.get('next')
    return results


def func_api_get_base_parallel(sistema, client, token, endpoint, ids=None, group_param=None, page_size=1000, extra_param=None):
    """
    Busca um endpoint da API Mindsight e devolve um DataFrame.

    sistema:  subdomínio do sistema (ex.: 'full').
    client:   tenant do cliente.
    endpoint: recurso da API (ex.: 'users').
    ids + group_param: se informados, faz uma consulta por id em paralelo.
    """
    headers = {'Authorization': f'Token {token}'}
    base_url = f'https://{sistema}.mindsight.com.br/{client}/api/v1/{endpoint}/?page_size={page_size}'
    if extra_param:
        base_url += extra_param

    def fetch_data(url):
        return fetch_data_with_pagination(url, headers, page_size)

    if ids and group_param:
        urls = [f"{base_url}&{group_param}={id_}" for id_ in ids]
    else:
        urls = [base_url]

    all_results = []
    with ThreadPoolExecutor() as executor:
        future_to_url = {executor.submit(fetch_data, url): url for url in urls}
        for future in as_completed(future_to_url):
            # Se alguma consulta falhar, o erro é repassado (antes era ignorado
            # silenciosamente, o que gerava bases incompletas sem aviso).
            all_results.extend(future.result())
    return pd.DataFrame(json_normalize(all_results))


def ler_usuarios_full(cliente, token_full):
    """Lista todos os usuários do People Hub (Full) do cliente."""
    return func_api_get_base_parallel('full', cliente, token_full, 'users')


def ler_usuarios_controle(cliente, token_controle):
    """Lista todos os usuários do Controle (endpoint 'users', diferente de 'employees')."""
    return func_api_get_base_parallel('controle', cliente, token_controle, 'users')


def ler_usuarios_performance(cliente, token_performance, rodada):
    """Lista os participantes de uma rodada (evaluation round) do Performance."""
    return func_api_get_base_parallel('performance', cliente, token_performance, 'participants',
                                      extra_param=f'&evaluation_rounds={rodada}')


def ler_perfomance_evaluation_rounds(cliente, token_performance):
    """Lista as rodadas de avaliação do Performance (usado para mostrar o nome da rodada)."""
    return func_api_get_base_parallel('performance', cliente, token_performance, 'evaluation_rounds')


# =============================================================================
# REGRA DE ACESSOS (COM CHECK DE REMOÇÃO)
# =============================================================================
# Opções do campo "Acesso ao ATS" (usadas na tela e na regra abaixo)
ATS_NENHUM = 'Nenhum usuário'
ATS_GESTORES = 'Gestores'
ATS_ESPECIFICOS = 'Usuários específicos'


# Situação do usuário dentro de um módulo (Metas/Performance), vinda do CSV do favorito
STATUS_ATIVO = 'ativo'
STATUS_INATIVO = 'inativo'
STATUS_INEXISTENTE = 'inexistente'
NOMES_MODULOS = {'metas': 'Metas', 'performance': 'Performance', 'full': 'People Hub'}


def nome_para_trick(nome):
    """
    Devolve o first_name alterado usado no trick do nome: tudo minúsculo
    (ou tudo maiúsculo, se o nome já estiver minúsculo). Se o nome não tiver
    letras, acrescenta um ponto no final.
    """
    nome = '' if pd.isna(nome) else str(nome)
    if nome.lower() != nome:
        return nome.lower()
    if nome.upper() != nome:
        return nome.upper()
    return nome + '.'


def formatar_acessos_duplo(row, opcao_full, lista_controle, tem_token_full, validacao, opcao_ats, lista_ats, lista_hub, rem_ctrl, rem_ats, rem_hub):
    """
    Recebe uma linha (um usuário) e calcula como ele deve subir no Passo 1 e no Passo 2.

    Retorna 8 valores:
      - acessos do CSV 1 (Passo 1);
      - acessos do CSV 2 (Passo 2);
      - se o usuário entra no CSV 1;
      - se o usuário entra no CSV 2;
      - os motivos do Passo 1 (texto para conferência);
      - o first_name do CSV 1;
      - o first_name do CSV 2;
      - os motivos do Passo 2.

    Tricks (usam o Passo 1 e o Passo 2):
      - Trick de reativação: o usuário deve ter o módulo (full, metas ou performance),
        mas está INATIVO nele. O módulo sai no Passo 1 e volta no Passo 2.
      - Trick do nome: o usuário deve ter o módulo (metas ou performance), mas ele
        NÃO EXISTE no módulo. O first_name sobe alterado (minúsculo) no Passo 1 e
        volta ao original no Passo 2, gerando a tarefa de alteração que cria o usuário.
    A situação no Metas/Performance vem das colunas 'status_metas'/'status_performance'
    (ativo, inativo ou inexistente). Sem o CSV do módulo, esses tricks não são aplicados.

    Parâmetros de regra:
      opcao_full / opcao_ats: opção escolhida nos campos de acesso ao People Hub / ATS.
      lista_controle / lista_ats / lista_hub: usernames autorizados em cada módulo.
      rem_ctrl / rem_ats / rem_hub: se True, remove o acesso de quem NÃO está autorizado.
      tem_token_full: só mexe no 'full' quando o token do Full foi informado.
    """
    valor_atual = row.get('access_to_systems', row.get('access_to_systems_auth', ''))
    sou_gestor = row['sou_gestor']
    is_active_full = row['is_active_full']
    is_active_auth = row['is_active']
    username = str(row['username']).strip()
    nome_original = row.get('first_name', '')
    nome_original = '' if pd.isna(nome_original) else str(nome_original)

    # Converte o texto atual (ex.: "'metas', 'performance'") em lista limpa e minúscula
    if pd.isna(valor_atual) or str(valor_atual).lower() == 'nan' or str(valor_atual) == '':
        lista_atual = []
    else:
        limpo = str(valor_atual).replace("'", "").replace('"', "").replace(" ", "").lower()
        lista_atual = [s.strip() for s in limpo.split(',') if s.strip()]

    lista_csv1 = lista_atual.copy()
    readicionar = []        # módulos que saem no Passo 1 e voltam no Passo 2 (trick de reativação)
    trick_nome = []         # módulos em que o usuário não existe (trick do nome)
    motivos = []
    motivos2 = []

    # 1. Usuário inativo no Auth precisa ser reativado
    precisa_ativar = is_active_auth not in [1, '1', True, 'True', 1.0]
    if precisa_ativar:
        motivos.append('ativar usuário inativo')

    # 2. Módulos de desempenho (metas e/ou performance), conforme a opção escolhida
    precisa_metas = validacao in ['Validação padrão (metas, perfomance)', 'Validar somente metas']
    precisa_performance = validacao in ['Validação padrão (metas, perfomance)', 'Validar somente performance']

    for modulo, precisa in [('metas', precisa_metas), ('performance', precisa_performance)]:
        if not precisa:
            continue
        status = row.get(f'status_{modulo}')
        nome_mod = NOMES_MODULOS[modulo]
        if status == STATUS_INATIVO:
            # Trick de reativação: sobe SEM o módulo no Passo 1 e COM ele no Passo 2
            if modulo in lista_csv1:
                lista_csv1.remove(modulo)
                motivos.append(f'remover {modulo} para trick de reativação (inativo no {nome_mod})')
            else:
                motivos.append(f'faltava {modulo} e está inativo no {nome_mod} (enviado direto para o trick)')
            readicionar.append(modulo)
        else:
            if modulo not in lista_csv1:
                lista_csv1.append(modulo)
                motivos.append(f'faltava {modulo}')
            if status == STATUS_INEXISTENTE:
                # Trick do nome: o usuário não existe no módulo
                trick_nome.append(modulo)

    # 3. Controle (organograma): só quem está na lista restrita recebe
    if username in lista_controle:
        if 'organograma' not in lista_csv1:
            lista_csv1.append('organograma')
            motivos.append('adicionar organograma')
    else:
        if 'organograma' in lista_csv1 and rem_ctrl:
            lista_csv1.remove('organograma')
            motivos.append('remover organograma')

    # 4. ATS: depende da opção escolhida no campo "Acesso ao ATS"
    #    - Nenhum usuário:        ninguém recebe (só remove se o checkbox estiver marcado)
    #    - Gestores:              recebem apenas os gestores ativos
    #    - Usuários específicos:  recebem apenas os usernames digitados na lista
    deve_ter_ats = False
    if opcao_ats == ATS_GESTORES and sou_gestor:
        deve_ter_ats = True
    elif opcao_ats == ATS_ESPECIFICOS and username in lista_ats:
        deve_ter_ats = True

    if deve_ter_ats:
        if 'ats' not in lista_csv1:
            lista_csv1.append('ats')
            motivos.append('adicionar ats')
    else:
        if 'ats' in lista_csv1 and rem_ats:
            lista_csv1.remove('ats')
            motivos.append('remover ats')

    # 5. People Hub (Full): só é avaliado quando o token do Full foi informado
    if tem_token_full:
        alvo_da_regra_full = False

        if opcao_full == 'Todos os usuários':
            alvo_da_regra_full = True
        elif opcao_full == 'Gestores' and sou_gestor:
            alvo_da_regra_full = True

        if username in lista_hub:
            alvo_da_regra_full = True

        if alvo_da_regra_full:
            if not is_active_full:
                # Trick de reativação: no Passo 1 o usuário sobe SEM 'full' e,
                # no Passo 2, sobe COM 'full', forçando a sincronização com o Hub.
                if 'full' in lista_csv1:
                    lista_csv1.remove('full')
                    motivos.append('remover full para trick de reativação')
                else:
                    motivos.append('faltava full (enviado direto para o trick)')
                readicionar.append('full')
            else:
                if 'full' not in lista_csv1:
                    lista_csv1.append('full')
                    motivos.append('faltava full')
        else:
            if 'full' in lista_csv1 and rem_hub:
                lista_csv1.remove('full')
                motivos.append('remover full')

    # 6. Trick do nome: Passo 1 com o first_name alterado, Passo 2 com o original
    nome_csv1 = nome_csv2 = nome_original
    if trick_nome:
        nome_csv1 = nome_para_trick(nome_original)
        modulos_txt = ' e '.join(NOMES_MODULOS[m] for m in trick_nome)
        motivos.append(f'trocar o nome para criar o usuário no {modulos_txt} (não existe lá)')
        motivos2.append(f'voltar o nome original (trick de criação no {modulos_txt})')

    # Passo 2: devolve os módulos retirados no Passo 1
    lista_csv2 = lista_csv1.copy()
    for modulo in readicionar:
        if modulo not in lista_csv2:
            lista_csv2.append(modulo)
            motivos2.append(f'devolver {modulo} (trick de reativação no {NOMES_MODULOS[modulo]})')

    # Monta os textos finais e verifica se houve mudança em relação ao atual
    str_atual = ",".join(lista_atual)
    str_csv1 = ",".join(lista_csv1)
    str_csv2 = ",".join(lista_csv2)
    motivo_final = "; ".join(motivos)
    motivo_passo2 = "; ".join(motivos2)

    teve_mudanca_csv2 = (str_csv1 != str_csv2) or (nome_csv1 != nome_csv2)
    # Quem vai para o Passo 2 sempre passa antes pelo Passo 1
    teve_mudanca_csv1 = (str_atual != str_csv1) or precisa_ativar or teve_mudanca_csv2

    return pd.Series([str_csv1, str_csv2, teve_mudanca_csv1, teve_mudanca_csv2, motivo_final,
                      nome_csv1, nome_csv2, motivo_passo2])


def formatar_acesso_performance(row):
    """
    Regra da Aba 3 (participantes da rodada): todo participante precisa estar
    ativo no Auth e ter o módulo 'performance'.

    Retorna 3 valores: acessos novos, se precisa de ajuste e o motivo.
    Participantes que não existem na base do Auth ('_merge' == 'left_only')
    não entram no arquivo de correção; vão para a lista de "não encontrados".
    """
    if row['_merge'] == 'left_only':
        return pd.Series(['', False, 'Usuário não encontrado na base do Auth enviada'])

    motivos = []
    is_active = row['is_active']
    access = row['access_to_systems']

    # 1. Usuário inativo no Auth precisa ser reativado
    precisa_ativar = is_active not in [1, '1', True, 'True', 1.0]
    if precisa_ativar:
        motivos.append('ativar usuário inativo')

    # Converte o texto atual de acessos em lista limpa e minúscula
    if pd.isna(access) or str(access).strip() == '':
        lista_atual = []
    else:
        limpo = str(access).replace("'", "").replace('"', "").replace(" ", "").lower()
        lista_atual = [s.strip() for s in limpo.split(',') if s.strip()]

    # 2. Garante o módulo performance (mantém os demais acessos como estão)
    lista_nova = lista_atual.copy()
    if 'performance' not in lista_nova:
        lista_nova.append('performance')
        motivos.append('faltava performance')

    precisa_ajuste = precisa_ativar or ('faltava performance' in motivos)
    return pd.Series([",".join(lista_nova), precisa_ajuste, "; ".join(motivos)])


def montar_df_upload(df_base, coluna_acessos, incluir_motivo=False, coluna_nome='first_name', coluna_motivo='motivo'):
    """
    Monta o DataFrame no layout exato do arquivo de upload de usuários do Auth.

    coluna_acessos: coluna de df_base com os acessos a enviar ('acessos_csv1' ou 'acessos_csv2').
    incluir_motivo: adiciona a coluna 'motivo_ajuste' (útil para conferência).
    coluna_nome: coluna de df_base com o first_name a enviar (muda no trick do nome).
    coluna_motivo: coluna de df_base usada no 'motivo_ajuste'.
    """
    df_upload = pd.DataFrame()
    df_upload['vazio'] = np.nan            # primeira coluna vazia exigida pelo layout
    df_upload['id'] = df_base['id']
    df_upload['username'] = df_base['username']
    df_upload['email'] = df_base['email']
    df_upload['first_name'] = df_base[coluna_nome]
    df_upload['last_name'] = df_base['last_name']
    df_upload['login_AD'] = 0
    df_upload['ad_only'] = 0
    df_upload['password'] = ''
    df_upload['is_staff'] = 0
    df_upload['groups'] = '1,2'
    df_upload['is_active'] = 1             # todos os usuários do arquivo ficam ativos
    df_upload['access_to_systems'] = df_base[coluna_acessos]
    df_upload['is_superuser'] = df_base['is_superuser'].map({True: 1, 'True': 1, False: 0, 'False': 0}).fillna(0).astype(int)

    if incluir_motivo:
        df_upload['motivo_ajuste'] = df_base[coluna_motivo]
    return df_upload
