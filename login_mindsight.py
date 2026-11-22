"""
Login na Mindsight feito pelo próprio app (sem navegador / Selenium).

Por que existe: as telas de admin do Performance e do Metas (Django Admin) só
abrem para quem está logado. Quando o app roda no Streamlit Cloud, quem acessa
essas páginas é o servidor, então ele mesmo precisa fazer o login.

Como funciona (mesmo fluxo da tela de login):
  1. Etapa 1: o usuário informa tenant, email e senha. O app abre a página de
     login do auth.mindsight.com.br, preenche o formulário e envia.
  2. Etapa 2: a Mindsight envia um token para o email. O usuário digita o token
     no app, que envia o segundo formulário.
  3. Com o login concluído, os cookies da sessão ficam guardados APENAS na
     memória da sessão do Streamlit (st.session_state['cookies_sessao']).
     Nada é salvo em disco e a senha não é guardada.

O formulário é lido da própria página (campos ocultos, CSRF, nomes dos campos),
então o login continua funcionando mesmo se os nomes dos campos mudarem.
"""

from urllib.parse import urljoin

import requests
import streamlit as st
from bs4 import BeautifulSoup

URL_LOGIN = "https://auth.mindsight.com.br/{tenant}/"
TIMEOUT = 30
# Trechos de URL que indicam que ainda estamos em alguma etapa do login
TRECHOS_LOGIN = ('login', 'mfa', 'otp', 'token', 'verif', '2fa')
# Nomes de campo que indicam o campo do token enviado por email
NOMES_TOKEN = ('token', 'otp', 'code', 'codigo', 'mfa', 'verification')


class ErroLogin(Exception):
    """Erro no login, já com mensagem pronta para mostrar ao usuário."""
    pass


# =============================================================================
# FUNÇÕES AUXILIARES DE LEITURA DE FORMULÁRIO
# =============================================================================
def _inputs_visiveis(form):
    """Campos que o usuário digitaria (exclui ocultos, botões, checkboxes)."""
    visiveis = []
    for inp in form.find_all('input'):
        tipo = (inp.get('type') or 'text').lower()
        if inp.get('name') and tipo in ('text', 'email', 'number', 'tel', 'password'):
            visiveis.append(inp)
    return visiveis


def _dados_do_form(form):
    """Lê todos os campos do formulário com seus valores atuais (inclui o CSRF oculto)."""
    dados = {}
    for campo in form.find_all(['input', 'select', 'textarea']):
        nome = campo.get('name')
        if not nome:
            continue
        tipo = (campo.get('type') or 'text').lower()
        if tipo in ('submit', 'button', 'image', 'reset'):
            continue
        if tipo in ('checkbox', 'radio') and not campo.has_attr('checked'):
            continue
        dados[nome] = campo.get('value', '')
    return dados


def _form_de_senha(html):
    """Encontra o formulário que tem campo de senha (etapa 1)."""
    soup = BeautifulSoup(html, 'html.parser')
    for form in soup.find_all('form'):
        if form.find('input', attrs={'type': 'password'}):
            return form
    return None


def _form_de_token(html, url):
    """
    Encontra o formulário do token (etapa 2): sem campo de senha e com um campo
    visível cujo nome parece de token, ou qualquer campo visível se a URL ainda
    for de login/verificação.
    """
    soup = BeautifulSoup(html, 'html.parser')
    url_de_login = any(t in url.lower() for t in TRECHOS_LOGIN)
    for form in soup.find_all('form'):
        if form.find('input', attrs={'type': 'password'}):
            continue
        visiveis = _inputs_visiveis(form)
        if not visiveis:
            continue
        por_nome = [i for i in visiveis if any(n in i.get('name', '').lower() for n in NOMES_TOKEN)]
        if por_nome:
            return form, por_nome[0].get('name')
        if url_de_login:
            return form, visiveis[0].get('name')
    return None, None


def _mensagem_de_erro(html):
    """Tenta extrair a mensagem de erro mostrada pela própria tela de login."""
    soup = BeautifulSoup(html, 'html.parser')
    for seletor in ['.errorlist', '.alert-danger', '.alert', '.error', '.invalid-feedback']:
        elem = soup.select_one(seletor)
        if elem and elem.get_text(strip=True):
            return elem.get_text(" ", strip=True)
    return ""


def _enviar_form(sessao, form, dados, url_pagina):
    """Envia o formulário para o 'action' dele (ou para a própria página)."""
    destino = urljoin(url_pagina, form.get('action') or url_pagina)
    # O Django exige o Referer em requisições HTTPS com CSRF
    return sessao.post(destino, data=dados, headers={'Referer': url_pagina}, timeout=TIMEOUT)


def _login_concluido(resposta):
    """Considera logado quando já não há formulário de senha nem de token."""
    if _form_de_senha(resposta.text) is not None:
        return False
    form_token, _ = _form_de_token(resposta.text, resposta.url)
    return form_token is None


# =============================================================================
# ETAPAS DO LOGIN
# =============================================================================
def iniciar_login(tenant, email, senha):
    """
    Etapa 1: envia email e senha.
    Retorna (sessao, contexto_token). Se contexto_token for None, o login já foi
    concluído (sem token); caso contrário, é preciso chamar confirmar_token().
    """
    sessao = requests.Session()
    sessao.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    try:
        r = sessao.get(URL_LOGIN.format(tenant=tenant.strip()), timeout=TIMEOUT)
    except requests.exceptions.RequestException:
        raise ErroLogin("Não foi possível acessar a página de login da Mindsight. Verifique a conexão e o tenant.")
    if r.status_code == 404:
        raise ErroLogin("Página de login não encontrada. Confira se o tenant está correto.")

    form = _form_de_senha(r.text)
    if form is None:
        raise ErroLogin("Não encontrei o formulário de login na página da Mindsight. Confira o tenant.")

    # Preenche o campo de usuário/email e o de senha, mantendo os campos ocultos (CSRF)
    dados = _dados_do_form(form)
    campo_senha = form.find('input', attrs={'type': 'password'}).get('name')
    candidatos = [i for i in _inputs_visiveis(form) if (i.get('type') or 'text').lower() != 'password']
    preferidos = [i for i in candidatos if (i.get('type') or '').lower() == 'email'
                  or any(n in i.get('name', '').lower() for n in ('email', 'username', 'login', 'user'))]
    campo_usuario = (preferidos or candidatos)[0].get('name') if (preferidos or candidatos) else 'username'
    dados[campo_usuario] = email.strip()
    dados[campo_senha] = senha

    r2 = _enviar_form(sessao, form, dados, r.url)

    # Continua na tela de senha = email ou senha errados
    if _form_de_senha(r2.text) is not None:
        detalhe = _mensagem_de_erro(r2.text)
        raise ErroLogin("Email ou senha incorretos." + (f" ({detalhe})" if detalhe else ""))

    form_token, campo_token = _form_de_token(r2.text, r2.url)
    if form_token is None:
        return sessao, None  # login concluído sem token

    contexto = {'dados': _dados_do_form(form_token), 'campo': campo_token,
                'url': r2.url, 'form_html': str(form_token)}
    return sessao, contexto


def confirmar_token(sessao, contexto, token):
    """Etapa 2: envia o token recebido por email e conclui o login."""
    form = BeautifulSoup(contexto['form_html'], 'html.parser').find('form')
    dados = dict(contexto['dados'])
    dados[contexto['campo']] = token.strip()
    r = _enviar_form(sessao, form, dados, contexto['url'])
    if not _login_concluido(r):
        detalhe = _mensagem_de_erro(r.text)
        raise ErroLogin("Token inválido ou expirado. Solicite um novo login." + (f" ({detalhe})" if detalhe else ""))
    return sessao


# =============================================================================
# BLOCO DE LOGIN NA BARRA LATERAL
# =============================================================================
def _limpar_login():
    for chave in ['cookies_sessao', 'login_sessao', 'login_contexto', 'login_tenant']:
        st.session_state[chave] = None


def render_login_sidebar():
    """Mostra o login na barra lateral (necessário para as abas que leem Performance e Metas)."""
    for chave in ['cookies_sessao', 'login_sessao', 'login_contexto', 'login_tenant']:
        st.session_state.setdefault(chave, None)

    st.sidebar.header("🔐 Login Mindsight")
    st.sidebar.caption("Necessário para as abas que leem o Performance e o Metas.")

    # Já logado: mostra o status e o botão de sair
    if st.session_state['cookies_sessao']:
        st.sidebar.success(f"✅ Logado no tenant **{st.session_state['login_tenant']}**.")
        if st.sidebar.button("Sair", key="btn_logout"):
            _limpar_login()
            st.rerun()
        return

    # Etapa 2: aguardando o token enviado por email
    if st.session_state['login_contexto']:
        st.sidebar.info("📧 Enviamos um token para o seu email. Digite-o abaixo.")
        token = st.sidebar.text_input("Token recebido por email", key="login_token")
        c1, c2 = st.sidebar.columns(2)
        if c1.button("Confirmar", key="btn_token"):
            if not token.strip():
                st.sidebar.error("Digite o token.")
            else:
                try:
                    sessao = confirmar_token(st.session_state['login_sessao'], st.session_state['login_contexto'], token)
                    st.session_state['cookies_sessao'] = sessao.cookies.get_dict()
                    st.session_state['login_sessao'] = None
                    st.session_state['login_contexto'] = None
                    st.rerun()
                except ErroLogin as e:
                    st.sidebar.error(str(e))
                except requests.exceptions.RequestException:
                    st.sidebar.error("Falha de conexão ao enviar o token. Tente novamente.")
        if c2.button("Cancelar", key="btn_cancelar_login"):
            _limpar_login()
            st.rerun()
        return

    # Etapa 1: tenant, email e senha
    with st.sidebar.form("form_login"):
        tenant = st.text_input("Tenant", placeholder="Ex: empresa123")
        email = st.text_input("Email")
        senha = st.text_input("Senha", type="password")
        enviar = st.form_submit_button("Entrar")
    if enviar:
        if not tenant or not email or not senha:
            st.sidebar.error("Preencha tenant, email e senha.")
            return
        try:
            with st.spinner("Entrando..."):
                sessao, contexto = iniciar_login(tenant, email, senha)
            st.session_state['login_tenant'] = tenant.strip()
            if contexto is None:
                st.session_state['cookies_sessao'] = sessao.cookies.get_dict()
            else:
                st.session_state['login_sessao'] = sessao
                st.session_state['login_contexto'] = contexto
            st.rerun()
        except ErroLogin as e:
            st.sidebar.error(str(e))
        except requests.exceptions.RequestException:
            st.sidebar.error("Falha de conexão com a Mindsight. Tente novamente.")
