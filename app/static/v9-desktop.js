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

  function ensureShell() {
    if ($('v9CommandPalette')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <div id="v9CommandPalette" class="v9-command-palette hidden" role="dialog" aria-modal="true" aria-label="Command palette">
        <div class="v9-command-panel">
          <div class="v9-command-head"><strong>DPN AI Command Palette</strong><kbd>Esc</kbd></div>
          <input id="v9CommandInput" type="search" autocomplete="off" placeholder="Search commands…" aria-label="Search commands" />
          <div id="v9CommandResults" class="v9-command-results" role="listbox"></div>
        </div>
      </div>
      <aside id="v9ActivityRail" class="v9-activity-rail" aria-label="Live activity">
        <header><div><span>LIVE ACTIVITY</span><strong id="v9ActivityState">Ready</strong></div><button id="v9ActivityToggle" aria-label="Toggle activity rail">×</button></header>
        <div class="v9-activity-grid">
          <button data-target="missionsBtn"><span>MISSIONS</span><strong id="v9MissionCount">0</strong></button>
          <button data-target="approvalsBtn"><span>APPROVALS</span><strong id="v9ApprovalCount">0</strong></button>
          <button data-target="automationsBtn"><span>AUTOMATIONS</span><strong id="v9AutomationCount">0</strong></button>
          <button data-target="connectorsBtn"><span>CONNECTORS</span><strong id="v9ConnectorCount">0</strong></button>
        </div>
        <div class="v9-focus-actions">
          <button id="v9TaskCenterBtn"><span>TASK CENTER</span><small>Queue, runs, pause/resume/cancel controls</small></button>
          <button id="v9ApprovalCenterBtn"><span>APPROVAL CENTER</span><small>Human decisions before sensitive actions</small></button>
          <button id="v9AgentActivityBtn"><span>AGENT ACTIVITY</span><small>Operational summaries and evidence only</small></button>
        </div>
      </aside>
      <section id="v9FocusDrawer" class="v9-focus-drawer hidden" aria-label="Desktop focus center" aria-live="polite">
        <header><div><span id="v9FocusEyebrow">DPN AI</span><strong id="v9FocusTitle">Focus Center</strong></div><button id="v9FocusClose" aria-label="Close focus center">×</button></header>
        <div id="v9FocusBody" class="v9-focus-body"></div>
      </section>
      <button id="v9PaletteButton" class="v9-palette-button" title="Command palette (Ctrl+K)" aria-label="Open command palette">⌘</button>
      <div id="v9LiveRegion" class="v9-sr-only" aria-live="polite"></div>
    `);

    $('v9PaletteButton')?.addEventListener('click', openPalette);
    $('v9ActivityToggle')?.addEventListener('click', () => $('v9ActivityRail')?.classList.toggle('collapsed'));
    $('v9ActivityRail')?.querySelectorAll('[data-target]').forEach((button) => {
      button.addEventListener('click', () => invoke(button.dataset.target));
    });
    $('v9TaskCenterBtn')?.addEventListener('click', () => openFocus('tasks'));
    $('v9ApprovalCenterBtn')?.addEventListener('click', () => openFocus('approvals'));
    $('v9AgentActivityBtn')?.addEventListener('click', () => openFocus('agents'));
    $('v9FocusClose')?.addEventListener('click', closeFocus);
    $('v9CommandPalette')?.addEventListener('click', (event) => {
      if (event.target === $('v9CommandPalette')) closePalette();
    });
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
      <button class="v9-command-item ${index === selected ? 'selected' : ''}" role="option" aria-selected="${index === selected}" data-target="${id}" data-index="${index}">
        <span>${label}</span><kbd>${shortcut}</kbd>
      </button>`).join('') || '<div class="v9-command-empty">No matching commands</div>';
    host.querySelectorAll('[data-target]').forEach((button) => {
      button.addEventListener('mouseenter', () => { selected = Number(button.dataset.index); renderCommands(); });
      button.addEventListener('click', () => { invoke(button.dataset.target); closePalette(); });
    });
  }

  function openPalette() {
    ensureShell();
    selected = 0;
    $('v9CommandPalette')?.classList.remove('hidden');
    renderCommands();
    window.setTimeout(() => $('v9CommandInput')?.focus(), 0);
  }

  function closePalette() {
    $('v9CommandPalette')?.classList.add('hidden');
    if ($('v9CommandInput')) $('v9CommandInput').value = '';
  }

  function onPaletteKey(event) {
    const results = filteredCommands();
    if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, Math.max(0, results.length - 1)); renderCommands(); }
    if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); renderCommands(); }
    if (event.key === 'Enter' && results[selected]) { event.preventDefault(); invoke(results[selected][1]); closePalette(); }
    if (event.key === 'Escape') { event.preventDefault(); closePalette(); }
  }

  function focusTemplate(kind) {
    if (kind === 'tasks') {
      return {
        eyebrow: 'TASK CENTER',
        title: 'Execution Control',
        body: `
          <p>Use the existing autonomous job queue and run history as the source of truth. Controls below route to those live surfaces rather than simulating task state.</p>
          <div class="v9-focus-grid">
            <button data-route="jobsBtn"><strong>Open Job Queue</strong><small>Queued, running, paused, cancelled, and failed work</small></button>
            <button data-route="runsBtn"><strong>Open Run History</strong><small>Evidence, audit state, and terminal outcomes</small></button>
            <button data-route="automationsBtn"><strong>Open Automations</strong><small>Recurring and conditional workflows</small></button>
          </div>
          <div class="v9-control-note"><b>Pause / Resume / Cancel:</b> available through the existing task/run surfaces when the underlying runtime exposes those actions. This overlay never fabricates successful cancellation.</div>`,
      };
    }
    if (kind === 'approvals') {
      return {
        eyebrow: 'APPROVAL CENTER',
        title: 'Human Control Boundary',
        body: `
          <p>Review sensitive and destructive operations before execution. Approval state remains owned by the existing Approval Inbox.</p>
          <div class="v9-focus-grid">
            <button data-route="approvalsBtn"><strong>Open Approval Inbox</strong><small>Pending human decisions and evidence</small></button>
            <button data-route="runsBtn"><strong>Review Audit Trail</strong><small>See what was approved, denied, or blocked</small></button>
            <button data-route="settingsBtn"><strong>Permission Settings</strong><small>Inspect session and persistent permission policy</small></button>
          </div>
          <div class="v9-control-note"><b>Safety:</b> this center does not auto-approve requests or weaken existing permission gates.</div>`,
      };
    }
    return {
      eyebrow: 'AGENT ACTIVITY',
      title: 'Operational Activity Summary',
      body: `
        <p>DPN AI can show agent status, selected tools, outputs, evidence, errors, retries, and completion state without exposing private internal reasoning.</p>
        <div class="v9-focus-grid">
          <button data-route="missionsBtn"><strong>Mission Activity</strong><small>Planner/executor/reviewer progress and evidence</small></button>
          <button data-route="runsBtn"><strong>Run Evidence</strong><small>Tool activity, timestamps, outcomes, and failures</small></button>
          <button data-route="diagnosticsBtn"><strong>Diagnostics</strong><small>Runtime health and recovery evidence</small></button>
        </div>
        <div class="v9-control-note"><b>Privacy boundary:</b> activity views expose concise operational summaries, not hidden chain-of-thought or private reasoning traces.</div>`,
    };
  }

  function openFocus(kind) {
    ensureShell();
    const template = focusTemplate(kind);
    if ($('v9FocusEyebrow')) $('v9FocusEyebrow').textContent = template.eyebrow;
    if ($('v9FocusTitle')) $('v9FocusTitle').textContent = template.title;
    if ($('v9FocusBody')) {
      $('v9FocusBody').innerHTML = template.body;
      $('v9FocusBody').querySelectorAll('[data-route]').forEach((button) => {
        button.addEventListener('click', () => invoke(button.dataset.route));
      });
    }
    $('v9FocusDrawer')?.classList.remove('hidden');
  }

  function closeFocus() {
    $('v9FocusDrawer')?.classList.add('hidden');
  }

  function bindKeyboard() {
    document.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openPalette(); return; }
      if (event.key === 'Escape') {
        if (!$('v9CommandPalette')?.classList.contains('hidden')) closePalette();
        if (!$('v9FocusDrawer')?.classList.contains('hidden')) closeFocus();
      }
      if (!(event.ctrlKey || event.metaKey) || event.target?.matches('input, textarea, select')) return;
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

  function mirrorDesktopSummary() {
    const sourceMap = [
      ['desktopMissionCard', 'v9MissionCount'],
      ['desktopApprovalCard', 'v9ApprovalCount'],
      ['desktopAutomationCard', 'v9AutomationCount'],
      ['desktopConnectorCard', 'v9ConnectorCount'],
    ];
    for (const [sourceId, destId] of sourceMap) {
      const source = $(sourceId)?.querySelector('strong')?.textContent || '0';
      const numeric = source.match(/\d+/)?.[0] || source;
      if ($(destId)) $(destId).textContent = numeric;
    }
    const core = $('desktopCoreCard');
    const state = core?.dataset.state || 'unknown';
    if ($('v9ActivityState')) $('v9ActivityState').textContent = state === 'healthy' ? 'Online' : state;
  }

  function observeSummary() {
    const dashboard = document.querySelector('.desktop-status-grid');
    if (!dashboard) return;
    new MutationObserver(() => {
      mirrorDesktopSummary();
      const live = $('v9LiveRegion');
      const approvals = $('desktopApprovalCard')?.querySelector('strong')?.textContent;
      if (live && approvals) live.textContent = `Approval status updated: ${approvals}`;
    }).observe(dashboard, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['data-state'] });
    mirrorDesktopSummary();
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.body.classList.add('desktop-v9');
    ensureShell();
    bindKeyboard();
    observeSummary();
  });
})();
