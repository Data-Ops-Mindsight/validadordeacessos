import pandas as pd
import numpy as np
import requests
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pandas import json_normalize

# Importações Mindsight
from mindsight_api_requests.wrappers.auth import *
from mindsight_api_requests.wrappers.hub import *
from mindsight_api_requests.wrappers.controle import *

def gerar_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Planilha1')
    return output.getvalue()

def ler_csv_seguro(uploaded_file):
    uploaded_file.seek(0)
    try:
        df = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
    except Exception:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, sep=';', encoding='latin1')
    df.columns = [str(c).strip() for c in df.columns]
    return df

def fetch_data_with_pagination(url, headers, page_size=1000):
    results = []
    current_url = url
    while current_url:
        response = requests.get(current_url, headers=headers)
        if response.status_code != 200:
            break
        data = response.json()
        results.extend(data.get('results', []))
        current_url = data.get('next')
    return results

def func_api_get_base_parallel(sistema, client, token, endpoint, ids=None, group_param=None, page_size=1000, extra_param=None):
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
            try:
                results = future.result()
                all_results.extend(results)
            except Exception:
                pass 
    return pd.DataFrame(json_normalize(all_results))

def ler_usuarios_full(cliente, token_full):
    return func_api_get_base_parallel('full', cliente, token_full, 'users')

# =============================================================================
# FORMATAÇÃO DE ACESSOS (COM CHECK DE REMOÇÃO)
# =============================================================================
def formatar_acessos_duplo(row, opcao_full, lista_controle, tem_token_full, validacao, opcao_ats, lista_ats, lista_hub, rem_ctrl, rem_ats, rem_hub):
    valor_atual = row.get('access_to_systems', row.get('access_to_systems_auth', ''))
    sou_gestor = row['sou_gestor']
    is_active_full = row['is_active_full']
    is_active_auth = row['is_active'] 
    username = str(row['username']).strip()

    if pd.isna(valor_atual) or str(valor_atual).lower() == 'nan' or str(valor_atual) == '':
        lista_atual = []
    else:
        limpo = str(valor_atual).replace("'", "").replace('"', "").replace(" ", "").lower()
        lista_atual = [s.strip() for s in limpo.split(',') if s.strip()]

    lista_csv1 = lista_atual.copy()
    lista_csv2 = None
    motivos = []

    # 1. Validação de inativos
    precisa_ativar = is_active_auth not in [1, '1', True, 'True', 1.0]
    if precisa_ativar: 
        motivos.append('ativar usuário inativo')

    # 2. Validação de Metas e Performance
    precisa_metas = validacao in ['Validação padrão (metas, perfomance)', 'Validar somente metas']
    precisa_performance = validacao in ['Validação padrão (metas, perfomance)', 'Validar somente performance']

    if precisa_metas and 'metas' not in lista_csv1:
        lista_csv1.append('metas')
        motivos.append('faltava metas')
    
    if precisa_performance and 'performance' not in lista_csv1:
        lista_csv1.append('performance')
        motivos.append('faltava performance')

    # 3. Validação do Controle (organograma)
    if username in lista_controle:
        if 'organograma' not in lista_csv1:
            lista_csv1.append('organograma')
            motivos.append('adicionar organograma')
    else:
        if 'organograma' in lista_csv1 and rem_ctrl:
            lista_csv1.remove('organograma')
            motivos.append('remover organograma')

    # 4. Validação do ATS
    deve_ter_ats = False
    if opcao_ats == 'Todos os usuários': 
        deve_ter_ats = True
    elif opcao_ats == 'Gestores' and sou_gestor: 
        deve_ter_ats = True
        
    if username in lista_ats: 
        deve_ter_ats = True

    if deve_ter_ats:
        if 'ats' not in lista_csv1:
            lista_csv1.append('ats')
            motivos.append('adicionar ats')
    else:
        if 'ats' in lista_csv1 and rem_ats:
            lista_csv1.remove('ats')
            motivos.append('remover ats')

    # 5. Validação do People Hub (Full)
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
                if 'full' in lista_csv1:
                    lista_csv1.remove('full')
                    motivos.append('remover full para trick de reativação')
                else:
                    motivos.append('faltava full (enviado direto para o trick)')
                lista_csv2 = lista_csv1.copy()
                lista_csv2.append('full')
            else:
                if 'full' not in lista_csv1:
                    lista_csv1.append('full')
                    motivos.append('faltava full')
        else:
            if 'full' in lista_csv1 and rem_hub:
                lista_csv1.remove('full')
                motivos.append('remover full')

    str_atual = ",".join(lista_atual)
    str_csv1 = ",".join(lista_csv1)
    str_csv2 = ",".join(lista_csv2) if lista_csv2 is not None else str_csv1
    motivo_final = "; ".join(motivos)

    teve_mudanca_csv1 = (str_atual != str_csv1) or precisa_ativar
    teve_mudanca_csv2 = str_csv1 != str_csv2

    return pd.Series([str_csv1, str_csv2, teve_mudanca_csv1, teve_mudanca_csv2, motivo_final])

def montar_df_upload(df_base, coluna_acessos, incluir_motivo=False):
    df_upload = pd.DataFrame()
    df_upload['vazio'] = np.nan
    df_upload['id'] = df_base['id']
    df_upload['username'] = df_base['username']
    df_upload['email'] = df_base['email']
    df_upload['first_name'] = df_base['first_name']
    df_upload['last_name'] = df_base['last_name']
    df_upload['login_AD'] = 0
    df_upload['ad_only'] = 0
    df_upload['password'] = ''
    df_upload['is_staff'] = 0
    df_upload['groups'] = '1,2'
    df_upload['is_active'] = 1 
    df_upload['access_to_systems'] = df_base[coluna_acessos]
    df_upload['is_superuser'] = df_base['is_superuser'].map({True: 1, 'True': 1, False: 0, 'False': 0}).fillna(0).astype(int)
    
    if incluir_motivo:
        df_upload['motivo_ajuste'] = df_base['motivo']
    return df_upload