(() => {
  'use strict';

  const COMMANDS = [
    ['New Operation', 'newChatBtn', 'Ctrl+N'],
    ['Universal Missions', 'missionsBtn', 'Ctrl+Shift+M'],
    ['Task Center', 'jobsBtn', 'Ctrl+Shift+J'],
    ['Approval Center', 'approvalsBtn', 'Ctrl+Shift+A'],
    ['Projects & Task Board', 'projectsBtn', 'Ctrl+Shift+P'],
    ['Local Automations', 'automationsBtn', 'Ctrl+Shift+U'],
    ['Runs & Audit Trail', 'runsBtn', 'Ctrl+Shift+R'],
    ['Workspace Files', 'filesBtn', 'Ctrl+Shift+F'],
    ['Local Memory', 'memoryBtn', 'Ctrl+Shift+L'],
    ['Connectors & Secrets', 'connectorsBtn', 'Ctrl+Shift+C'],
    ['System Diagnostics', 'diagnosticsBtn', 'Ctrl+Shift+D'],
    ['System Settings', 'settingsBtn', 'Ctrl+,'],
    ['Voice Command Center', 'voiceBtn', 'Ctrl+Shift+V'],
  ];

  const $ = (id) => document.getElementById(id);
  const invoke = (id) => $(id)?.click();
  let selected = 0;
  let lastFocus = null;

  function rememberFocus() {
    const active = document.activeElement;
    if (active && active !== document.body) lastFocus = active;
  }

  function restoreFocus() {
    if (lastFocus && document.contains(lastFocus) && typeof lastFocus.focus === 'function') {
      lastFocus.focus();
    }
    lastFocus = null;
  }

  function isEditableTarget(target) {
    return Boolean(target?.matches?.('input, textarea, select, [contenteditable="true"]'));
  }

  function focusableWithin(root) {
    if (!root) return [];
    return [...root.querySelectorAll('button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')]
      .filter((node) => !node.hidden && node.offsetParent !== null);
  }

  function trapFocus(event, root) {
    if (event.key !== 'Tab') return;
    const items = focusableWithin(root);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function ensureShell() {
    if ($('v9CommandPalette')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <div id="v9CommandPalette" class="v9-command-palette hidden" role="dialog" aria-modal="true" aria-label="Command palette" aria-hidden="true">
        <div class="v9-command-panel">
          <div class="v9-command-head"><strong>DPN AI Command Palette</strong><kbd>Esc</kbd></div>
          <input id="v9CommandInput" type="search" autocomplete="off" placeholder="Search commands..." aria-label="Search commands" aria-controls="v9CommandResults" aria-activedescendant="" />
          <div id="v9CommandResults" class="v9-command-results" role="listbox"></div>
        </div>
      </div>
      <button id="v9PaletteButton" class="v9-palette-button" title="Command palette (Ctrl+K)" aria-label="Open command palette" aria-haspopup="dialog" aria-controls="v9CommandPalette">Commands</button>
      <div id="v9LiveRegion" class="v9-sr-only" aria-live="polite"></div>
    `);

    $('v9PaletteButton')?.addEventListener('click', openPalette);
    $('v9CommandPalette')?.addEventListener('click', (event) => {
      if (event.target === $('v9CommandPalette')) closePalette();
    });
    $('v9CommandPalette')?.addEventListener('keydown', (event) => trapFocus(event, $('v9CommandPalette')));
    $('v9CommandInput')?.addEventListener('input', renderCommands);
    $('v9CommandInput')?.addEventListener('keydown', onPaletteKey);
  }

  function filteredCommands() {
    const query = ($('v9CommandInput')?.value || '').trim().toLowerCase();
    return COMMANDS.filter(([label, id]) => !query || `${label} ${id}`.toLowerCase().includes(query));
  }

  function renderCommands() {
    const results = filteredCommands();
    selected = Math.min(selected, Math.max(0, results.length - 1));
    const host = $('v9CommandResults');
    if (!host) return;
    host.innerHTML = results.map(([label, id, shortcut], index) => `
      <button id="v9CommandOption${index}" class="v9-command-item ${index === selected ? 'selected' : ''}" role="option" aria-selected="${index === selected}" data-target="${id}" data-index="${index}">
        <span>${label}</span><kbd>${shortcut}</kbd>
      </button>`).join('') || '<div class="v9-command-empty">No matching commands</div>';
    const input = $('v9CommandInput');
    if (input) input.setAttribute('aria-activedescendant', results.length ? `v9CommandOption${selected}` : '');
    host.querySelectorAll('[data-target]').forEach((button) => {
      button.addEventListener('mouseenter', () => { selected = Number(button.dataset.index); renderCommands(); });
      button.addEventListener('click', () => { invoke(button.dataset.target); closePalette(); });
    });
  }

  function openPalette() {
    ensureShell();
    if (!$('v9CommandPalette')?.classList.contains('hidden')) return;
    rememberFocus();
    selected = 0;
    $('v9CommandPalette')?.classList.remove('hidden');
    $('v9CommandPalette')?.setAttribute('aria-hidden', 'false');
    renderCommands();
    window.setTimeout(() => $('v9CommandInput')?.focus(), 0);
  }

  function closePalette() {
    const palette = $('v9CommandPalette');
    if (!palette || palette.classList.contains('hidden')) return;
    palette.classList.add('hidden');
    palette.setAttribute('aria-hidden', 'true');
    if ($('v9CommandInput')) $('v9CommandInput').value = '';
    restoreFocus();
  }

  function onPaletteKey(event) {
    const results = filteredCommands();
    if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, Math.max(0, results.length - 1)); renderCommands(); }
    if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); renderCommands(); }
    if (event.key === 'Enter' && results[selected]) { event.preventDefault(); invoke(results[selected][1]); closePalette(); }
    if (event.key === 'Escape') { event.preventDefault(); closePalette(); }
  }

  function bindKeyboard() {
    document.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !isEditableTarget(event.target)) { event.preventDefault(); openPalette(); return; }
      if (event.key === 'Escape') {
        if (!$('v9CommandPalette')?.classList.contains('hidden')) { closePalette(); return; }
      }
      if (!(event.ctrlKey || event.metaKey) || isEditableTarget(event.target)) return;
      const shift = event.shiftKey;
      const key = event.key.toLowerCase();
      const target = ({
        'n': !shift ? 'newChatBtn' : null,
        'm': shift ? 'missionsBtn' : null,
        'j': shift ? 'jobsBtn' : null,
        'a': shift ? 'approvalsBtn' : null,
        'p': shift ? 'projectsBtn' : null,
        'u': shift ? 'automationsBtn' : null,
        'r': shift ? 'runsBtn' : null,
        'f': shift ? 'filesBtn' : null,
        'l': shift ? 'memoryBtn' : null,
        'c': shift ? 'connectorsBtn' : null,
        'd': shift ? 'diagnosticsBtn' : null,
        'v': shift ? 'voiceBtn' : null,
        ',': !shift ? 'settingsBtn' : null,
      })[key];
      if (target) { event.preventDefault(); invoke(target); }
    });
  }

  function observeSummary() {
    const dashboard = document.querySelector('.desktop-status-grid');
    if (!dashboard) return;
    new MutationObserver(() => {
      const live = $('v9LiveRegion');
      const approvals = $('desktopApprovalCard')?.querySelector('strong')?.textContent;
      if (live && approvals) live.textContent = `Approval status updated: ${approvals}`;
    }).observe(dashboard, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['data-state'] });
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.body.classList.add('desktop-v9');
    ensureShell();
    bindKeyboard();
    observeSummary();
  });
})();
