/*
 * Favorito "Exportar dados do Django" (Performance, Metas e Hub) - código-fonte.
 *
 * Como usar:
 *   1. Crie um favorito no navegador e cole no campo URL o conteúdo de
 *      ferramentas/bookmarklet_exportar_usuarios.txt (versão em uma linha deste arquivo).
 *   2. Abra, já logado, uma destas telas do admin:
 *        Usuários (Performance): https://performance.mindsight.com.br/<tenant>/staff/accounts/user/
 *        Usuários (Metas):       https://acompanhamento.mindsight.com.br/<tenant>/admin/accounts/user/
 *        Participants:           https://performance.mindsight.com.br/<tenant>/staff/participants/participant/
 *        Persons:                https://acompanhamento.mindsight.com.br/<tenant>/admin/person/person/
 *   3. Clique no favorito. Ele lê todas as páginas da tabela e baixa um CSV.
 *
 * Na tela de usuários, a própria tabela já traz tudo. Nas telas de participants e
 * persons, a tabela não mostra UUID, usuário e gestor, então o favorito abre a página
 * de cada registro (por trás, várias ao mesmo tempo) para ler esses campos.
 *
 * O código roda no próprio navegador, com o login que já está aberto.
 * Ele só LÊ as telas; não altera nada no sistema.
 */
(async () => {
  // Só funciona em uma tela de listagem do Django Admin
  if (!document.querySelector('#result_list')) {
    alert('Abra a tela de listagem do admin (usuários, participants ou persons) antes de clicar no favorito.');
    return;
  }
  const caminho = location.pathname;
  const modo = caminho.includes('/participants/participant/') ? 'participantes'
    : caminho.includes('/person/person/') ? 'persons'
    : caminho.includes('/accounts/user/') ? 'usuarios' : '';
  if (!modo) {
    alert('Este favorito funciona nas telas de usuários (accounts/user), participants do Performance e persons do Metas.');
    return;
  }

  // Aviso de progresso no canto da tela
  const aviso = document.createElement('div');
  aviso.style.cssText = 'position:fixed;top:16px;right:16px;z-index:99999;background:#8c00ff;color:#fff;' +
    'padding:12px 16px;border-radius:8px;font:14px sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.3)';
  document.body.appendChild(aviso);
  const mostrar = (txt) => { aviso.textContent = txt; };

  const texto = (el, seletor) => {
    const achado = el.querySelector(seletor);
    return achado ? achado.textContent.trim() : '';
  };
  const base = location.origin + caminho;

  // Baixa uma página do admin. Devolve o documento, ou null se a página for inválida ou a sessão tiver caído.
  async function baixarPagina(url) {
    const resp = await fetch(url, { credentials: 'same-origin' });
    if (!resp.ok || resp.url.includes('login') || resp.url.includes('e=1')) return null;
    return new DOMParser().parseFromString(await resp.text(), 'text/html');
  }

  // Lê uma página da listagem. extrair(linha) devolve um objeto com 'chave' (ou null para ignorar a linha).
  // Devolve a lista da página, ou null se a página for inválida.
  async function lerPagina(filtro, p, extrair) {
    const doc = await baixarPagina(base + '?' + (filtro ? filtro + '&' : '') + 'p=' + p);
    if (doc === null) return null;
    const lista = [];  // página válida sem linhas (ex.: filtro sem resultados) devolve lista vazia
    doc.querySelectorAll('#result_list tbody tr').forEach((linha) => {
      const item = extrair(linha);
      if (item && item.chave) lista.push(item);
    });
    return lista;
  }

  // Lê todas as páginas (com um filtro opcional, ex.: 'is_active__exact=1').
  // A paginação do Django Admin começa em 0 ou em 1, dependendo da versão:
  // lê a partir de 0 e para quando uma página não traz nenhum registro novo.
  // Devolve um Map chave -> registro, ou null se o filtro não existir na tela.
  async function lerTodas(filtro, etapa, extrair) {
    const itens = new Map();
    let p = 0, tentouExtra = false, algumaValida = false;
    while (true) {
      mostrar(etapa + '... página ' + (p + 1) + ' (' + itens.size + ' até agora)');
      const lista = await lerPagina(filtro, p, extrair);
      if (lista === null) {
        if (p === 0) { p = 1; continue; }
        break;
      }
      algumaValida = true;
      let novos = 0;
      lista.forEach((u) => { if (!itens.has(u.chave)) { itens.set(u.chave, u); novos++; } });
      if (novos === 0) {
        if (p === 1 && !tentouExtra) { tentouExtra = true; p++; continue; }
        break;
      }
      p++;
    }
    return algumaValida ? itens : (filtro ? null : itens);
  }

  // Valor de um campo na página de detalhe: campo editável (input), ou campo só de leitura
  // (texto, ou ícone de sim/não, que vira 1/0).
  function valorCampo(doc, campo) {
    const input = doc.querySelector('#id_' + campo);
    if (input) return (input.value || '').trim();
    const ro = doc.querySelector('.field-' + campo + ' .readonly');
    if (!ro) return '';
    const img = ro.querySelector('img');
    if (img) return img.getAttribute('alt') === 'True' ? 1 : 0;
    const t = ro.textContent.trim();
    return t === '-' ? '' : t;
  }

  // Texto mostrado ao lado de um campo de ligação (ex.: User: 71 -> "dado.perez@email.com.br")
  function rotuloLigacao(doc, campo) {
    const linha = doc.querySelector('.field-' + campo);
    if (!linha) return '';
    const forte = linha.querySelector('strong a, strong');
    if (forte && forte.textContent.trim()) return forte.textContent.trim();
    const link = [...linha.querySelectorAll('a')].find((a) => a.textContent.trim() && !(a.id || '').startsWith('lookup_'));
    return link ? link.textContent.trim() : '';
  }

  // Abre a página de detalhe de cada registro (6 ao mesmo tempo) e monta a linha do CSV
  async function lerDetalhes(links, etapa, montar) {
    const resultado = new Array(links.length);
    let proximo = 0, feitos = 0;
    async function trabalhador() {
      while (proximo < links.length) {
        const i = proximo++;
        const doc = await baixarPagina(links[i]);
        if (doc === null) throw new Error('não foi possível abrir ' + links[i] + '. Confira se você continua logado.');
        resultado[i] = montar(doc, links[i]);
        feitos++;
        mostrar(etapa + '... ' + feitos + ' de ' + links.length);
      }
    }
    await Promise.all(Array.from({ length: 6 }, trabalhador));
    return resultado;
  }

  // Linha da listagem -> link da página de detalhe
  const extrairLink = (linha) => {
    const a = linha.querySelector('th a') || linha.querySelector('td a');
    if (!a) return null;
    const href = new URL(a.getAttribute('href'), location.href).href;
    return { chave: href };
  };
  const idDoLink = (link) => { const m = link.match(/\/(\d+)\/change\/?/); return m ? m[1] : ''; };

  try {
    let registros = [], colunas = [], tipo = '';

    if (modo === 'usuarios') {
      // ---- Usuários: a própria tabela já traz tudo ----
      const extrairUsuario = (linha) => {
        const username = texto(linha, '.field-username') || texto(linha, 'th a');
        if (!username) return null;
        const staff = linha.querySelector('.field-is_staff img');
        return {
          chave: username,
          username: username,
          email: texto(linha, '.field-email'),
          first_name: texto(linha, '.field-first_name'),
          last_name: texto(linha, '.field-last_name'),
          is_staff: staff ? (staff.getAttribute('alt') === 'True' ? 1 : 0) : '',
          uuid: texto(linha, '.field-uuid'),
        };
      };
      // 1ª passada: todos os usuários
      const usuarios = await lerTodas('', 'Exportando usuários', extrairUsuario);
      // 2ª passada: só os ativos (filtro "Por ativo = Sim"), para preencher a coluna is_active
      if (usuarios.size) {
        const ativos = await lerTodas('is_active__exact=1', 'Verificando usuários ativos', extrairUsuario);
        usuarios.forEach((u) => { u.is_active = ativos === null ? '' : (ativos.has(u.chave) ? 1 : 0); });
      }
      registros = [...usuarios.values()];
      colunas = ['username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff', 'uuid'];
      tipo = 'usuarios';
    } else {
      // ---- Participants / Persons: abre a página de cada registro ----
      const links = [...(await lerTodas('', 'Listando registros', extrairLink)).keys()];
      if (modo === 'participantes') {
        registros = await lerDetalhes(links, 'Lendo participants', (doc, link) => ({
          id: idDoLink(link),
          name: valorCampo(doc, 'name'),
          key: valorCampo(doc, 'key'),
          user_id: valorCampo(doc, 'user'),
          username: rotuloLigacao(doc, 'user'),
          uuid: valorCampo(doc, 'uuid'),
        }));
        colunas = ['id', 'name', 'key', 'user_id', 'username', 'uuid'];
        tipo = 'participantes';
      } else {
        registros = await lerDetalhes(links, 'Lendo persons', (doc, link) => ({
          id: idDoLink(link),
          key: valorCampo(doc, 'key'),
          cpf: valorCampo(doc, 'cpf'),
          user_id: valorCampo(doc, 'user'),
          username: rotuloLigacao(doc, 'user'),
          parent_id: valorCampo(doc, 'parent'),
          parent_username: rotuloLigacao(doc, 'parent'),
          is_active: valorCampo(doc, 'is_active'),
          uuid: valorCampo(doc, 'uuid'),
        }));
        colunas = ['id', 'key', 'cpf', 'user_id', 'username', 'parent_id', 'parent_username', 'is_active', 'uuid'];
        tipo = 'persons';
      }
    }

    if (!registros.length) {
      mostrar('Nenhum registro encontrado. Confira se você está logado e na tela certa.');
      setTimeout(() => aviso.remove(), 6000);
      return;
    }

    // Monta o CSV (separador vírgula, com BOM para abrir certo no Excel)
    const esc = (v) => '"' + String(v === undefined || v === null ? '' : v).replace(/"/g, '""') + '"';
    const csv = '﻿' + [colunas.join(',')]
      .concat(registros.map((u) => colunas.map((c) => esc(u[c])).join(',')))
      .join('\r\n');

    // Nome do arquivo: <sistema>_<tenant>_<tipo>.csv
    const sistema = location.hostname.startsWith('performance') ? 'performance'
      : location.hostname.startsWith('acompanhamento') ? 'metas' : location.hostname.split('.')[0];
    const tenant = caminho.split('/').filter(Boolean)[0] || 'tenant';
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    link.download = sistema + '_' + tenant + '_' + tipo + '.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();

    mostrar('✅ ' + registros.length + ' registros exportados (' + link.download + ').');
    setTimeout(() => aviso.remove(), 6000);
  } catch (e) {
    mostrar('Erro ao exportar: ' + e.message);
    setTimeout(() => aviso.remove(), 8000);
  }
})();
