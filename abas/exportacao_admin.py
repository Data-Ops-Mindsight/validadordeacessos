"""
Exportação dos usuários do Performance e do Metas pelo favorito do navegador.

Compartilhado pelas abas que usam o favorito (Abas 1, 4 e 5):
  - codigo_favorito(): código do favorito "Exportar dados do Django" (bookmarklet);
  - ler_csv_modulo(): lê e confere o CSV gerado pelo favorito;
  - render_criar_favorito(): código do favorito e como criá-lo em cada navegador;
  - render_instrucoes_exportacao(): passo a passo exibido na tela (usuários).

Por que assim: no Performance o admin do Django não permite exportar os
usuários, no Metas a exportação não traz o UUID e a API também não traz essas
informações. O favorito roda no navegador já logado, lê todas as páginas da
tabela de usuários do admin e baixa um CSV.
"""

import os

import streamlit as st

from functions import ler_csv_seguro

# Favorito (bookmarklet) que exporta os usuários das telas de admin em CSV
ARQUIVO_FAVORITO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'ferramentas', 'bookmarklet_exportar_usuarios.txt')


def codigo_favorito():
    """Lê o código do favorito para exibir na tela (vazio se o arquivo não existir)."""
    try:
        with open(ARQUIVO_FAVORITO, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ""


def ler_csv_modulo(arquivo, nome_modulo, prefixo_esperado, exigir_ativo=False):
    """
    Lê o CSV exportado pelo favorito para um módulo (Performance ou Metas).
    Confere se é o arquivo certo (pelo nome) e se tem a coluna username.
    """
    nome_arquivo = (arquivo.name or "").lower()
    outros = {'performance_', 'metas_'} - {prefixo_esperado}
    if any(nome_arquivo.startswith(o) for o in outros):
        raise ValueError(f"o arquivo enviado em '{nome_modulo}' parece ser de outro módulo ({arquivo.name}).")
    if '_participantes' in nome_arquivo or '_persons' in nome_arquivo:
        raise ValueError(f"o arquivo enviado em '{nome_modulo}' é de participants/persons ({arquivo.name}). "
                         "Aqui vai o CSV gerado na tela de usuários (accounts/user/).")
    df = ler_csv_seguro(arquivo)
    if 'username' not in df.columns:
        raise ValueError(f"o CSV do {nome_modulo} não possui a coluna 'username'. "
                         "Gere o arquivo pelo favorito 'Exportar dados do Django'.")
    if exigir_ativo and ('is_active' not in df.columns or df['is_active'].isna().all()
                         or df['is_active'].astype(str).str.strip().isin(['', 'nan']).all()):
        raise ValueError(f"o CSV do {nome_modulo} não informa se os usuários estão ativos (coluna 'is_active'). "
                         "Gere o arquivo novamente com a versão atual do favorito 'Exportar dados do Django'.")
    return df


def render_criar_favorito(titulo="#### Passo 1 - Criar o favorito (só na primeira vez)"):
    """Mostra o código do favorito e como criá-lo em cada navegador (usado nas Abas 1, 4 e 5)."""
    # --- Passo 1: criar o favorito ---
    st.markdown(
        titulo + "\n"
        "Copie o código abaixo (ícone de copiar no canto direito da caixa). Ele começa com `javascript:` "
        "e é ele que vai no lugar do endereço do favorito."
    )
    codigo = codigo_favorito()
    if codigo:
        st.code(codigo, language=None)
    else:
        st.warning("Arquivo do favorito não encontrado (ferramentas/bookmarklet_exportar_usuarios.txt).")

    st.markdown("Depois siga os passos do seu navegador:")
    aba_edge, aba_chrome, aba_firefox = st.tabs(["Microsoft Edge", "Google Chrome", "Mozilla Firefox"])
    with aba_edge:
        st.markdown(
            "1. Deixe a barra de favoritos visível com **Ctrl + Shift + B**;\n"
            "2. Em qualquer página aberta, clique com o botão direito na barra de favoritos e escolha "
            "**Adicionar esta página aos favoritos**. Clique em **Concluído**;\n"
            "3. Clique com o botão direito no favorito que acabou de aparecer na barra e escolha **Editar**;\n"
            "4. Em **Nome**, escreva `Exportar dados do Django`;\n"
            "5. Em **URL**, apague o endereço que estiver lá e cole o código copiado;\n"
            "6. Clique em **Salvar**."
        )
    with aba_chrome:
        st.markdown(
            "1. Deixe a barra de favoritos visível com **Ctrl + Shift + B**;\n"
            "2. Clique com o botão direito na barra de favoritos e escolha **Adicionar página...**;\n"
            "3. Em **Nome**, escreva `Exportar dados do Django`;\n"
            "4. Em **URL**, apague o endereço que estiver lá e cole o código copiado;\n"
            "5. Clique em **Salvar**."
        )
    with aba_firefox:
        st.markdown(
            "1. Deixe a barra de favoritos visível com **Ctrl + Shift + B**;\n"
            "2. Clique com o botão direito na barra de favoritos e escolha **Adicionar favorito...**;\n"
            "3. Em **Nome**, escreva `Exportar dados do Django`;\n"
            "4. Em **URL**, cole o código copiado;\n"
            "5. Clique em **Salvar**."
        )
    st.caption("Ao final, o favorito **Exportar dados do Django** aparece na barra de favoritos. Não é preciso criar de novo "
               "nas próximas vezes. Se o código do favorito mudar, edite o favorito e cole o código novo no campo **URL**.")


def render_instrucoes_exportacao(texto_envio):
    """
    Mostra o expansor com o passo a passo para gerar os CSVs.
    texto_envio: texto do Passo 4 (o que fazer com os arquivos nesta aba).
    """
    with st.expander("❓ Como gerar os CSVs do Performance e do Metas"):
        # --- Por que a exportação é feita assim ---
        st.markdown(
            "#### Por que é preciso exportar assim?\n"
            "- No **Performance**, o admin do Django **não tem a opção de exportar** os usuários;\n"
            "- No **Metas**, a exportação do Django **não traz o UUID** dos usuários;\n"
            "- Pela **API**, essas informações também não vêm.\n\n"
            "Por isso usamos um **favorito do navegador** chamado **Exportar dados do Django**. Ao clicar nele, com a tela "
            "de usuários do admin aberta, ele percorre **todas as páginas** da tabela e baixa um arquivo CSV com "
            "usuário, email, nome, sobrenome, se está ativo no módulo e UUID. Ele usa o login que você já tem aberto no navegador e "
            "**apenas lê** a tabela: nada é alterado no sistema."
        )

        render_criar_favorito()

        # --- Passo 2 e 3: exportar ---
        st.markdown(
            "#### Passo 2 - Exportar os usuários do Performance\n"
            "1. Entre no Performance normalmente (com o seu login de sempre);\n"
            "2. Abra a tela de usuários do admin: `https://performance.mindsight.com.br/<tenant>/staff/accounts/user/` "
            "(troque `<tenant>` pelo tenant do cliente);\n"
            "3. Clique no favorito **Exportar dados do Django**. Um aviso roxo aparece no canto superior direito mostrando "
            "o andamento;\n"
            "4. Ao terminar, o arquivo `performance_<tenant>_usuarios.csv` é baixado.\n\n"
            "#### Passo 3 - Exportar os usuários do Metas\n"
            "1. Abra a tela de usuários do admin do Metas: `https://acompanhamento.mindsight.com.br/<tenant>/admin/accounts/user/`;\n"
            "2. Clique no favorito **Exportar dados do Django**;\n"
            "3. Ao terminar, o arquivo `metas_<tenant>_usuarios.csv` é baixado.\n\n"
            "#### Passo 4 - Enviar os arquivos\n" + texto_envio
        )
        st.caption("💡 Se o favorito mostrar “Abra a tela de usuários do admin”, confira se você está na tela "
                   "`accounts/user/` (lista de usuários) e logado no módulo.")
