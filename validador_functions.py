import pandas as pd
import numpy as np
import requests
import time
import io
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from concurrent.futures import ThreadPoolExecutor, as_completed
from pandas import json_normalize

# =============================================================================
# IMPORTAÇÕES DO PACOTE MINDSIGHT
# =============================================================================
try:
    from mindsight_api_requests.wrappers.auth import *
    from mindsight_api_requests.wrappers.hub import *
    from mindsight_api_requests.wrappers.controle import *
except ImportError as e:
    print(f"Aviso: Não foi possível importar mindsight_api_requests: {e}")

# =============================================================================
# FUNÇÕES AUXILIARES E API 
# =============================================================================
def gerar_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Planilha1')
    return output.getvalue()

def gerar_excel_multi_abas(dict_dfs):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for nome_aba, df in dict_dfs.items():
            df.to_excel(writer, index=False, sheet_name=nome_aba)
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

    urls = [f"{base_url}&{group_param}={id_}" for id_ in ids] if ids and group_param else [base_url]

    all_results = []
    with ThreadPoolExecutor() as executor:
        future_to_url = {executor.submit(fetch_data, url): url for url in urls}
        for future in as_completed(future_to_url):
            try:
                all_results.extend(future.result())
            except Exception:
                pass 

    return pd.DataFrame(json_normalize(all_results))

def ler_usuarios_full(cliente, token_full):
    return func_api_get_base_parallel('full', cliente, token_full, 'users')

def ler_usuarios_controle(cliente, token_controle):
    return func_api_get_base_parallel('controle', cliente, token_controle, 'users')

def ler_usuarios_performance(cliente, token_performance, rodada):
    return func_api_get_base_parallel('performance', cliente, token_performance, 'participants', extra_param = f'&evaluation_rounds={rodada}')

def ler_perfomance_evaluation_rounds(cliente, token_performance):
    return func_api_get_base_parallel('performance', cliente, token_performance, 'evaluation_rounds')

def extrair_django_admin(url_base, cookies):
    sessao = requests.Session()
    requests.utils.add_dict_to_cookiejar(sessao.cookies, cookies)
    pagina = 0
    usuarios = []
    ultima_primeira_linha = None
    
    while True:
        resposta = sessao.get(f"{url_base}?p={pagina}")
        if "login" in resposta.url: return pd.DataFrame()
            
        soup = BeautifulSoup(resposta.text, 'html.parser')
        tabela = soup.select_one("#result_list tbody")
        
        if not tabela: break
        linhas = tabela.find_all("tr")
        if not linhas: break
        
        primeira_linha_atual = str(linhas[0])
        if primeira_linha_atual == ultima_primeira_linha: break
        ultima_primeira_linha = primeira_linha_atual
        
        for linha in linhas:
            username_elem = linha.select_one(".field-username") or linha.select_one("th a")
            email_elem = linha.select_one(".field-email")
            first_name_elem = linha.select_one(".field-first_name")
            last_name_elem = linha.select_one(".field-last_name")
            is_active_img = linha.select_one(".field-is_active img")
            uuid_elem = linha.select_one(".field-uuid")
            
            usuarios.append({
                'username': username_elem.text.strip() if username_elem else "",
                'first_name': first_name_elem.text.strip() if first_name_elem else "",
                'last_name': last_name_elem.text.strip() if last_name_elem else "",
                'email': email_elem.text.strip() if email_elem else "",
                'is_active': 1 if is_active_img and is_active_img.get('alt') == 'True' else 0,
                'uuid': uuid_elem.text.strip() if uuid_elem else ""
            })
        pagina += 1
        
    df = pd.DataFrame(usuarios)
    return df.drop_duplicates() if not df.empty else df

def extrair_django_admin_users_com_id(url_base, cookies):
    sessao = requests.Session()
    requests.utils.add_dict_to_cookiejar(sessao.cookies, cookies)
    pagina = 0
    usuarios = []
    ultima_primeira = None
    
    while True:
        r = sessao.get(f"{url_base}?p={pagina}")
        if "login" in r.url: return pd.DataFrame()
        soup = BeautifulSoup(r.text, 'html.parser')
        tabela = soup.select_one("#result_list tbody")
        
        if not tabela: break
        linhas = tabela.find_all("tr")
        if not linhas: break
        if str(linhas[0]) == ultima_primeira: break
        ultima_primeira = str(linhas[0])
        
        for linha in linhas:
            username_elem = linha.select_one(".field-username") or linha.select_one("th a")
            email_elem = linha.select_one(".field-email")
            
            user_id = ''
            if username_elem and username_elem.name == 'a':
                href = username_elem.get('href', '')
                if len(href.split('/')) >= 3: user_id = href.split('/')[-3]
            elif linha.select_one("th a"):
                href = linha.select_one("th a").get('href', '')
                if len(href.split('/')) >= 3: user_id = href.split('/')[-3]
                
            usuarios.append({
                'id_user': str(user_id),
                'username': username_elem.text.strip() if username_elem else "",
                'email': email_elem.text.strip() if email_elem else ""
            })
        pagina += 1
        
    df = pd.DataFrame(usuarios)
    if not df.empty: df = df.drop_duplicates()
    return df

def scrapePerformanceParticipant(link, wait, driver):
    driver.get(link)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    try: uuid = driver.find_element(By.XPATH, '//*[@id="id_uuid"]').get_attribute("value")
    except: uuid = ""
    try: name = driver.find_element(By.XPATH, '//*[@id="id_name"]').get_attribute("value")
    except: name = ""
    try: key = driver.find_element(By.XPATH, '//*[@id="id_key"]').get_attribute("value")
    except: key = ""
    try: id_user = driver.find_element(By.XPATH, '//*[@id="id_user"]').get_attribute("value")
    except: id_user = ""

    return {
        "link": link, "UUID_Perf": uuid, "name": name, 
        "employee_code": key, "user_id": id_user,
    }

def extrair_performance_selenium_original(tenant, cookies, progress_bar=None):
    options = webdriver.EdgeOptions()
    driver = webdriver.Edge(options=options)
    driver.get(f"https://performance.mindsight.com.br/{tenant}/staff/")
    time.sleep(1)
    
    for name, value in cookies.items():
        driver.add_cookie({'name': name, 'value': value})
        
    base_url = f"https://performance.mindsight.com.br/{tenant}/staff/participants/participant/"
    wait = WebDriverWait(driver, 10)
    
    extracted_data = []
    page = 0
    
    try:
        while True:
            if progress_bar: progress_bar.text(f"Scraping Performance: Analisando tabela da página {page}...")
            driver.get(f"{base_url}?p={page}")
            while "login" in driver.current_url or "mfa" in driver.current_url or "otp" in driver.current_url:
                time.sleep(1)
            try:
                wait.until(EC.presence_of_element_located((By.ID, "result_list")))
                rows = driver.find_elements(By.CSS_SELECTOR, "#result_list tbody tr")
                if not rows: break 
                
                links = []
                for row in rows:
                    try:
                        header_cell = row.find_element(By.TAG_NAME, "th")
                        links.append(header_cell.find_element(By.TAG_NAME, "a").get_attribute("href"))
                    except: pass
                    
                for i, link in enumerate(links):
                    while "login" in driver.current_url: time.sleep(1)
                    extracted_data.append(scrapePerformanceParticipant(link, wait, driver))
                    if progress_bar:
                        progress_bar.progress(min(int(((i+1)/len(links))*100), 100), text=f"Página {page} - Extraindo participante {i+1}/{len(links)}...")
                page += 1
            except: break
    except Exception as e:
        print(f"Error occurred: {e}")
            
    driver.quit()
    colunas_seguras = ['employee_code', 'UUID_Perf', 'user_id', 'name']
    if not extracted_data: return pd.DataFrame(columns=colunas_seguras)
    return pd.DataFrame(extracted_data)

def formatar_acessos_duplo(row, opcao, lista_controle, tem_token_full, validacao):
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

    precisa_ativar = is_active_auth not in [1, '1', True, 'True', 1.0]
    if precisa_ativar: motivos.append('ativar usuario inativo')

    precisa_metas = validacao in ['Validação padrão (metas, perfomance)', 'Validar somente metas']
    precisa_performance = validacao in ['Validação padrão (metas, perfomance)', 'Validar somente performance']

    if precisa_metas and 'metas' not in lista_csv1:
        lista_csv1.append('metas')
        motivos.append('faltava metas')
    
    if precisa_performance and 'performance' not in lista_csv1:
        lista_csv1.append('performance')
        motivos.append('faltava performance')

    if lista_controle: 
        if username in lista_controle:
            if 'organograma' not in lista_csv1:
                lista_csv1.append('organograma')
                motivos.append('adicionar organograma')
        else:
            if 'organograma' in lista_csv1:
                lista_csv1.remove('organograma')
                motivos.append('remover organograma')

    if tem_token_full:
        alvo_da_regra_full = (opcao == 'Todos os usuários') or (opcao == 'Gestores' and sou_gestor)
        if alvo_da_regra_full:
            if not is_active_full:
                if 'full' in lista_csv1:
                    lista_csv1.remove('full')
                    motivos.append('remover full para trick de reativacao')
                else:
                    motivos.append('faltava full (enviado direto para o trick)')
                lista_csv2 = lista_csv1.copy()
                lista_csv2.append('full')
            else:
                if 'full' not in lista_csv1:
                    lista_csv1.append('full')
                    motivos.append('faltava full')

    str_atual = ",".join(lista_atual)
    str_csv1 = ",".join(lista_csv1)
    str_csv2 = ",".join(lista_csv2) if lista_csv2 is not None else str_csv1
    motivo_final = "; ".join(motivos)

    return pd.Series([str_csv1, str_csv2, (str_atual != str_csv1) or precisa_ativar, str_csv1 != str_csv2, motivo_final])

def formatar_acesso_performance(row):
    if row['_merge'] == 'left_only':
        return pd.Series(['', False, 'Usuário não encontrado na base do Auth baixada'])
        
    motivos = []
    precisa_ativar = row['is_active'] not in [1, '1', True, 'True', 1.0]
    if precisa_ativar: motivos.append('ativar usuario inativo')
        
    access = row['access_to_systems']
    lista_nova = [s.strip() for s in str(access).replace("'", "").replace('"', "").replace(" ", "").lower().split(',') if s.strip()] if pd.notna(access) and str(access).strip() != '' else []
    
    if 'performance' not in lista_nova:
        lista_nova.append('performance')
        motivos.append('faltava performance')
        
    return pd.Series([",".join(lista_nova), precisa_ativar or ('faltava performance' in motivos), "; ".join(motivos)])

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
    
    if incluir_motivo: df_upload['motivo_ajuste'] = df_base['motivo']
    return df_upload
    
def get_controle_users_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos usuários do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos usuários do sistema Controle.
    """
    standard_columns = ['id','username','email','first_name','last_name','is_superuser','is_staff','is_active','last_login','uuid','date_joined','name']
    df_users_api = get_dataframe_from_api('controle', tenant, 'users', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_users_api.empty:
        df_users_api = pd.DataFrame(columns=standard_columns)
    else:        
        df_users_api['name'] = df_users_api['first_name'] + ' ' + df_users_api['last_name']
    return df_users_api

def get_controle_employees_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos funcionários do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos funcionários do sistema Controle.
    """
    standard_columns = ['id', 'name', 'first_name', 'last_name', 'email', 'user.username', 'username', 'employee_code', 'gender', 'cpf', 'birth_date', 'company_referal', 'work_type', 'work_city', 'uuid']
    df_employees_api = get_dataframe_from_api('controle', tenant, 'employees/?expand=user,uuid', token, page_size, max_workers, parallel, end_url_with_slash=False, ignore_page_size_limits=ignore_page_size_limits)
    if df_employees_api.empty:
        df_employees_api = pd.DataFrame(columns=standard_columns)
    else:        
        df_employees_api['name'] = df_employees_api['first_name'] + ' ' + df_employees_api['last_name']
        df_employees_api['employee_code'] = df_employees_api['employee_code'].astype(str)
        df_employees_api = df_employees_api.loc[:,~df_employees_api.columns.str.startswith('_')]
    return df_employees_api

def get_controle_corporations_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações das instâncias de empresa do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações das empresas do sistema Controle.
    """
    standard_columns = ['id', 'name', 'code']
    df_corporations_api = get_dataframe_from_api('controle', tenant, 'corporations', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_corporations_api.empty:
        df_corporations_api = pd.DataFrame(columns=standard_columns)
    return df_corporations_api

def get_controle_branch_corporations_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações das instâncias de filial do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações das filiais do sistema Controle.
    """
    standard_columns = ['id', 'name', 'code', 'corporation']
    df_branch_corporations_api = get_dataframe_from_api('controle', tenant, 'branch_corporations', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_branch_corporations_api.empty:
        df_branch_corporations_api = pd.DataFrame(columns=standard_columns)
    return df_branch_corporations_api

def get_controle_contract_types_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos tipos de contrato do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos tipos de contrato do sistema Controle.
    """
    standard_columns = ['id', 'description', 'key', 'contract']
    df_contract_types_api = get_dataframe_from_api('controle', tenant, 'contract_types', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_contract_types_api.empty:
        df_contract_types_api = pd.DataFrame(columns=standard_columns)
    return df_contract_types_api

def get_controle_employee_records_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém registros de funcionários do sistema Controle via API, incluindo informações relacionadas.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com registros de funcionários do sistema Controle, enriquecido com informações de funcionários, empresas, filiais e tipos de contrato.
    """
    standard_columns = ['employee_code', 'corporation_code', 'branch_corporation_code', 'contract_type', 'start', 'end', 'id', 'registration_code', 'termination_type', 'termination_reason', 'entrance_type', 'uuid', 'email', 'corporation']
    df_employee_records_api = get_dataframe_from_api('controle', tenant, 'employee_records', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_employee_records_api.empty:
        df_employee_records_api = pd.DataFrame(columns=standard_columns)
    else:
        df_employees_api = get_controle_employees_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_corporations_api = get_controle_corporations_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_branch_corporations_api = get_controle_branch_corporations_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_contract_types_api = get_controle_contract_types_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)

        df_employee_records_api['employee'] = df_employee_records_api['employee'].apply(get_ID_from_url)
        df_employee_records_api['corporation'] = df_employee_records_api['corporation'].apply(get_ID_from_url).astype('Int64')
        df_employee_records_api['branch_corporation'] = df_employee_records_api['branch_corporation'].apply(get_ID_from_url).astype('Int64')
        df_employee_records_api['contract_type'] = df_employee_records_api['contract_type'].apply(get_ID_from_url).astype('Int64')
        
        df_employee_records_api.rename(columns={'timespan.lower':'start', 'timespan.upper':'end'}, inplace=True)
        df_employee_records_api.drop(columns=['api_url', 'created', 'modified'], inplace=True)
        df_employee_records_api.sort_values(['employee', 'start'], inplace=True)

        df_employee_records_api = df_employee_records_api.merge(df_contract_types_api, how='left', left_on='contract_type', right_on='id', suffixes=('', '_contract_type'))
        df_employee_records_api = df_employee_records_api.merge(df_corporations_api, how='left', left_on='corporation', right_on='id', suffixes=('', '_corporation'))
        df_employee_records_api = df_employee_records_api.merge(df_branch_corporations_api, how='left', left_on='branch_corporation', right_on='id', suffixes=('', '_branch_corporation'))
        df_employee_records_api = df_employee_records_api.merge(df_employees_api, how='left', left_on='employee', right_on='id', suffixes=('', '_employee'))
        df_employee_records_api['contract_type'] = df_employee_records_api['key']
        df_employee_records_api['branch_corporation_code'] = df_employee_records_api['code_branch_corporation']
        df_employee_records_api['corporation_code'] = df_employee_records_api['code']
        
    return df_employee_records_api

def get_controle_areas_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações das instâncias de área do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações das áreas do sistema Controle.
    """
    standard_columns = ['id', 'name', 'code']
    drop_columns = ['api_url', 'created', 'modified', '_links.record_set', '_links.employee_history', '_links.parents']
    df_area_instances_api = get_dataframe_from_api('controle', tenant, 'areas', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_area_instances_api.empty:
        df_area_instances_api = pd.DataFrame(columns=standard_columns)
    else:
        df_area_instances_api.drop(columns=drop_columns, inplace=True)
        df_area_instances_api['code'] = df_area_instances_api['code'].astype(str)
    return df_area_instances_api

def get_controle_area_records_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém registros de áreas do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com registros de áreas do sistema Controle, enriquecido com informações das áreas.
    """
    standard_columns = ['id','area','start','end','id_area','code','name','area_code']
    df_controle_area_records_api = get_dataframe_from_api('controle', tenant, 'area_records', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_controle_area_records_api.empty:
        df_controle_area_records_api = pd.DataFrame(columns=standard_columns)
    else:
        df_controle_area_records_api['start'] = df_controle_area_records_api['timespan.lower']
        df_controle_area_records_api['end'] = df_controle_area_records_api['timespan.upper']
        df_controle_area_records_api.drop(columns=['api_url', 'created', 'modified','timespan.upper','timespan.lower'], inplace=True)
        df_controle_area_records_api['area'] = df_controle_area_records_api['area'].apply(get_ID_from_url)
        df_controle_inst_area_api = get_controle_areas_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_controle_area_records_api = df_controle_area_records_api.merge(df_controle_inst_area_api, how='left', left_on='area', right_on='id', suffixes=('', '_area'))
        df_controle_area_records_api['area_code'] = df_controle_area_records_api['code'].astype(str)
    return df_controle_area_records_api

def get_controle_parent_areas_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações das hierarquias de área do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações das hierarquias de área do sistema Controle.
    """
    standard_columns = ['area_code', 'parent_code', 'start', 'end', 'id', 'uuid']
    df_parent_areas_api = get_dataframe_from_api('controle', tenant, 'parent_areas', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_parent_areas_api.empty:
        df_parent_areas_api = pd.DataFrame(columns=standard_columns)
    else:
        df_area_instances_api = get_controle_areas_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        dict_area_id_code = dict(zip(df_area_instances_api['id'], df_area_instances_api['code']))
        df_parent_areas_api['id'] = df_parent_areas_api['api_url'].apply(get_ID_from_url)
        df_parent_areas_api.rename(columns={'timespan.lower':'start', 'timespan.upper':'end'}, inplace=True)
        df_parent_areas_api['area'] = df_parent_areas_api['area'].apply(get_ID_from_url)
        df_parent_areas_api['area_code'] = df_parent_areas_api['area'].map(dict_area_id_code)
        df_parent_areas_api['parent'] = df_parent_areas_api['parent'].apply(get_ID_from_url)
        df_parent_areas_api['parent_code'] = df_parent_areas_api['parent'].map(dict_area_id_code)
    return df_parent_areas_api

def get_controle_employee_areas_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações das áreas dos funcionários do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações das áreas dos funcionários do sistema Controle.
    """
    standard_columns = ['employee_code', 'area_code', 'start', 'end', 'id', 'review_access', 'uuid']
    df_employee_areas_api = get_dataframe_from_api('controle', tenant, 'employee_areas', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_employee_areas_api.empty:
        df_employee_areas_api = pd.DataFrame(columns=standard_columns)
    else:
        df_area_instances_api = get_controle_areas_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_employees_api = get_controle_employees_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_employee_areas_api['employee_id'] = df_employee_areas_api['employee'].apply(get_ID_from_url)
        df_employee_areas_api['area'] = df_employee_areas_api['area'].apply(get_ID_from_url)
        df_employee_areas_api.rename(columns={'timespan.lower':'start', 'timespan.upper':'end'}, inplace=True)
        df_employee_areas_api.drop(columns=['api_url', 'created', 'modified'], inplace=True)
        df_employee_areas_api.sort_values(['employee_id', 'start'], inplace=True)
        df_employee_areas_api = df_employee_areas_api.merge(df_area_instances_api, how='left', left_on='area', right_on='id', suffixes=('', '_area'))
        df_employee_areas_api = df_employee_areas_api.merge(df_employees_api, how='left', left_on='employee_id', right_on='id', suffixes=('', '_employee'))
        df_employee_areas_api = df_employee_areas_api.rename(columns={'code':'area_code'})   
    return df_employee_areas_api

def get_controle_employee_managers_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos gestores dos funcionários do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos gestores dos funcionários do sistema Controle.
    """
    standard_columns = ['employee_code', 'manager_code', 'start', 'end', 'id', 'review_access', 'uuid']
    drop_columns = ['api_url', 'created', 'modified']
    df_employee_managers_api = get_dataframe_from_api('controle', tenant, 'employee_managers', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_employee_managers_api.empty:
        df_employee_managers_api = pd.DataFrame(columns=standard_columns)
    else:
        df_employees_api = get_controle_employees_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_employee_managers_api['employee_id'] = df_employee_managers_api['employee'].apply(get_ID_from_url)
        df_employee_managers_api['manager_id'] = df_employee_managers_api['manager'].apply(get_ID_from_url)
        df_employee_managers_api.rename(columns={'timespan.lower':'start', 'timespan.upper':'end'}, inplace=True)
        df_employee_managers_api.drop(columns=drop_columns, inplace=True)
        df_employee_managers_api.sort_values(['employee_id', 'start'], inplace=True)

        df_employee_managers_api = df_employee_managers_api.merge(df_employees_api, how='left', left_on='employee_id', right_on='id', suffixes=('', '_employee'))
        df_employee_managers_api = df_employee_managers_api.merge(df_employees_api, how='left', left_on='manager_id', right_on='id', suffixes=('', '_manager'))
        df_employee_managers_api.drop(columns=['review_access'], inplace=True)
        df_employee_managers_api = df_employee_managers_api.loc[:,~df_employee_managers_api.columns.str.startswith('_links')]
        df_employee_managers_api = df_employee_managers_api.loc[:,~df_employee_managers_api.columns.str.startswith('_actions')]
        df_employee_managers_api = df_employee_managers_api.rename(columns={'employee_code_manager':'manager_code'})
    return df_employee_managers_api

def get_controle_seniority_levels_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos níveis de senioridade do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos níveis de senioridade do sistema Controle.
    """
    standard_columns = ['id', 'key', 'level']
    df_seniority_levels_api = get_dataframe_from_api('controle', tenant, 'seniority_levels', token, page_size, max_workers, parallel=False, ignore_page_size_limits=ignore_page_size_limits)
    if df_seniority_levels_api.empty:
        df_seniority_levels_api = pd.DataFrame(columns=standard_columns)
    return df_seniority_levels_api

def get_controle_positions_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações das instâncias de cargo do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos cargos do sistema Controle.
    """
    standard_columns = ['id', 'name', 'code', 'seniority_level', 'description', 'category']
    drop_columns = ['api_url', 'created', 'modified', '_links.record_set', '_links.employee_history']
    df_positions_api = get_dataframe_from_api('controle', tenant, 'positions', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_positions_api.empty:
        df_positions_api = pd.DataFrame(columns=standard_columns)
    else:
        df_positions_api['code'] = df_positions_api['code'].astype(str)
        df_positions_api.drop(columns=drop_columns, inplace=True)
    return df_positions_api

def get_controle_position_records_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém registros de cargo do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com registros de cargos do sistema Controle, enriquecido com informações dos cargos.
    """
    standard_columns = ['id','position','start','end','id_position','code','name','position_code']
    df_controle_position_records_api = get_dataframe_from_api('controle', tenant, 'position_records', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_controle_position_records_api.empty:
        df_controle_position_records_api = pd.DataFrame(columns=standard_columns)
    else:
        df_controle_position_records_api['start'] = df_controle_position_records_api['timespan.lower']
        df_controle_position_records_api['end'] = df_controle_position_records_api['timespan.upper']
        df_controle_position_records_api.drop(columns=['api_url', 'created', 'modified','timespan.upper','timespan.lower'], inplace=True)
        df_controle_position_records_api['position'] = df_controle_position_records_api['position'].apply(get_ID_from_url)
        df_controle_inst_position_api = get_controle_positions_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_controle_position_records_api = df_controle_position_records_api.merge(df_controle_inst_position_api, how='left', left_on='position', right_on='id', suffixes=('', '_position'))
        df_controle_position_records_api['position_code'] = df_controle_position_records_api['code'].astype(str)
    return df_controle_position_records_api

def get_controle_employee_positions_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos cargos dos funcionários do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos cargos dos funcionários do sistema Controle.
    """
    standard_columns = ['employee_code', 'position_code', 'start', 'end', 'id', 'review_access', 'uuid']
    drop_columns = ['api_url', 'created', 'modified']
    df_employee_positions_api = get_dataframe_from_api('controle', tenant, 'employee_positions', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_employee_positions_api.empty:
        df_employee_positions_api = pd.DataFrame(columns=standard_columns)
    else:
        df_positions_api = get_controle_positions_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_employees_api = get_controle_employees_api(tenant, token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
        df_employee_positions_api['employee_id'] = df_employee_positions_api['employee'].apply(get_ID_from_url)
        df_employee_positions_api['position'] = df_employee_positions_api['position'].apply(get_ID_from_url)
        df_employee_positions_api.rename(columns={'timespan.lower':'start', 'timespan.upper':'end'}, inplace=True)
        df_employee_positions_api.drop(columns=drop_columns, inplace=True)
        df_employee_positions_api.sort_values(['employee', 'start'], inplace=True)
        df_employee_positions_api = df_employee_positions_api.merge(df_positions_api, how='left', left_on='position', right_on='id', suffixes=('', '_position'))
        df_employee_positions_api = df_employee_positions_api.merge(df_employees_api, how='left', left_on='employee_id', right_on='id', suffixes=('', '_employee'))
        df_employee_positions_api = df_employee_positions_api.rename(columns={'code':'position_code'})
    return df_employee_positions_api

def get_controle_raise_types_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos tipos de promoção do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos tipos de promoção do sistema Controle.
    """
    standard_columns = ['id', 'key', 'description', 'raise_type']
    df_raise_types_api = get_dataframe_from_api('controle', tenant, 'raise_types', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_raise_types_api.empty:
        df_raise_types_api = pd.DataFrame(columns=standard_columns)
    return df_raise_types_api

def get_controle_salaries_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos salários do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos salários do sistema Controle.
    """
    standard_columns = ['id', 'employee_code', 'employee', 'date', 'salary_currency', 'salary', 'raise_type']
    df_salaries_api = get_dataframe_from_api('controle', tenant, 'salaries', token, page_size, max_workers, parallel, ignore_page_size_limits=ignore_page_size_limits)
    if df_salaries_api.empty:
        df_salaries_api = pd.DataFrame(columns=standard_columns)
    else:
        df_salaries_api['employee_code'] = df_salaries_api['employee']
    return df_salaries_api


def get_controle_template_tasks_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos salários do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos salários do sistema Controle.
    """
    standard_columns = ['id', 'key', 'name', 'description', 'tags']
    df_template_tasks_api = get_dataframe_from_api('controle', tenant, 'employee_tasks/template-tasks/', token, parallel=False)
    if df_template_tasks_api.empty:
        df_template_tasks_api = pd.DataFrame(columns=standard_columns)
    return df_template_tasks_api

def get_controle_tasks_evaluation_options_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos salários do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos salários do sistema Controle.
    """
    standard_columns = ['id', 'key', 'name', 'description', 'color_tag', 'color_text']
    df_tasks_evaluation_options_api = get_dataframe_from_api('controle', tenant, 'employee_tasks/evaluation-options/', token, parallel=False)
    if df_tasks_evaluation_options_api.empty:
        df_tasks_evaluation_options_api = pd.DataFrame(columns=standard_columns)
    return df_tasks_evaluation_options_api

def get_controle_employee_tasks_api(
    tenant: str,
    token: str,
    page_size: Optional[int] = None,
    max_workers: Optional[int] = None,
    parallel: bool = True,
    ignore_page_size_limits: bool = False
) -> pd.DataFrame:
    """
    Obtém informações dos salários do sistema Controle via API.

    Parâmetros:
    -----------
    tenant : str
        Nome do tenant.
    token : str
        Token de autenticação.
    page_size : int, opcional
        Tamanho da página (padrão: None).
    max_workers : int, opcional
        Número máximo de threads paralelas.
    parallel : bool, opcional
        Se True, faz requisições em paralelo.
    ignore_page_size_limits : bool, opcional
        Se True, ignora limites de tamanho de página.

    Retorna:
    --------
    pd.DataFrame
        DataFrame com informações dos salários do sistema Controle.
    """
    standard_columns = [
        'id', 'template_task', 'template_task.id', 'template_task.key', 'template_task.name', 'template_task.description', 'template_task.tags',
        'priority','priority_display','source_type','source_object_type','source_object_id','ignored_at','ignored_by','created','modified'
    ]
    df_employee_tasks_api = get_dataframe_from_api('controle', tenant, 'employee_tasks/tasks/', token, parallel=False)
    if df_employee_tasks_api.empty:
        df_employee_tasks_api = pd.DataFrame(columns=standard_columns)
    return df_employee_tasks_api


