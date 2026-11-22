/*
 * Exportar usuários do Django Admin (Performance e Metas) - código-fonte do favorito.
 *
 * Como usar:
 *   1. Crie um favorito no navegador e cole no campo URL o conteúdo de
 *      ferramentas/bookmarklet_exportar_usuarios.txt (versão em uma linha deste arquivo).
 *   2. Abra a tela de usuários do admin, já logado:
 *        Performance: https://performance.mindsight.com.br/<tenant>/staff/accounts/user/
 *        Metas:       https://acompanhamento.mindsight.com.br/<tenant>/admin/accounts/user/
 *   3. Clique no favorito. Ele lê todas as páginas da tabela e baixa um CSV.
 *
 * O código roda no próprio navegador, com o login que já está aberto.
 * Ele só LÊ a tabela de usuários; não altera nada no sistema.
 */
(async () => {
  // Só funciona na tela de listagem de usuários do Django Admin
  if (!document.querySelector('#result_list')) {
    alert('Abra a tela de usuários do admin (accounts/user/) antes de clicar no favorito.');
    return;
  }

  // Aviso de progresso no canto da tela
  const aviso = document.createElement('div');
  aviso.style.cssText = 'position:fixed;top:16px;right:16px;z-index:99999;background:#8c00ff;color:#fff;' +
    'padding:12px 16px;border-radius:8px;font:14px sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.3)';
  document.body.appendChild(aviso);
  const mostrar = (txt) => { aviso.textContent = txt; };

  const texto = (linha, seletor) => {
    const el = linha.querySelector(seletor);
    return el ? el.textContent.trim() : '';
  };
  const usuarios = new Map();
  const base = location.origin + location.pathname;

  // Lê uma página da listagem e devolve quantos usuários novos ela trouxe (null = página inválida)
  async function lerPagina(p) {
    const resp = await fetch(base + '?p=' + p, { credentials: 'same-origin' });
    if (!resp.ok || resp.url.includes('login') || resp.url.includes('e=1')) return null;
    const doc = new DOMParser().parseFromString(await resp.text(), 'text/html');
    const linhas = doc.querySelectorAll('#result_list tbody tr');
    if (!linhas.length) return null;
    let novos = 0;
    linhas.forEach((linha) => {
      const username = texto(linha, '.field-username') || texto(linha, 'th a');
      if (!username || usuarios.has(username)) return;
      const ativo = linha.querySelector('.field-is_active img');
      const staff = linha.querySelector('.field-is_staff img');
      usuarios.set(username, {
        username: username,
        email: texto(linha, '.field-email'),
        first_name: texto(linha, '.field-first_name'),
        last_name: texto(linha, '.field-last_name'),
        is_active: ativo ? (ativo.getAttribute('alt') === 'True' ? 1 : 0) : '',
        is_staff: staff ? (staff.getAttribute('alt') === 'True' ? 1 : 0) : '',
        uuid: texto(linha, '.field-uuid'),
      });
      novos++;
    });
    return novos;
  }

  try {
    // A paginação do Django Admin começa em 0 ou em 1, dependendo da versão.
    // Lê a partir de 0 e para quando uma página não traz nenhum usuário novo.
    let p = 0, tentouExtra = false;
    while (true) {
      mostrar('Exportando usuários... página ' + (p + 1) + ' (' + usuarios.size + ' até agora)');
      const novos = await lerPagina(p);
      if (novos === null) {
        if (p === 0) { p = 1; continue; }        // paginação começa em 1
        break;                                   // passou da última página
      }
      if (novos === 0) {
        if (p === 1 && !tentouExtra) { tentouExtra = true; p++; continue; }
        break;
      }
      p++;
    }

    if (!usuarios.size) {
      mostrar('Nenhum usuário encontrado. Confira se você está logado e na tela de usuários.');
      setTimeout(() => aviso.remove(), 6000);
      return;
    }

    // Monta o CSV (separador vírgula, com BOM para abrir certo no Excel)
    const colunas = ['username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff', 'uuid'];
    const esc = (v) => '"' + String(v).replace(/"/g, '""') + '"';
    const csv = '﻿' + [colunas.join(',')]
      .concat([...usuarios.values()].map((u) => colunas.map((c) => esc(u[c])).join(',')))
      .join('\r\n');

    // Nome do arquivo: <sistema>_<tenant>_usuarios.csv
    const sistema = location.hostname.startsWith('performance') ? 'performance'
      : location.hostname.startsWith('acompanhamento') ? 'metas' : location.hostname.split('.')[0];
    const tenant = location.pathname.split('/').filter(Boolean)[0] || 'tenant';
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    link.download = sistema + '_' + tenant + '_usuarios.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();

    mostrar('✅ ' + usuarios.size + ' usuários exportados (' + link.download + ').');
    setTimeout(() => aviso.remove(), 6000);
  } catch (e) {
    mostrar('Erro ao exportar: ' + e.message);
    setTimeout(() => aviso.remove(), 8000);
  }
})();
