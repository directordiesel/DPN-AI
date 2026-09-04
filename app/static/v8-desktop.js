(() => {
  'use strict';

  const STATUS_ENDPOINTS = {
    core: '/api/health',
  };

  const setState = (id, state, title, detail) => {
    const card = document.getElementById(id);
    if (!card) return;
    card.dataset.state = state;
    const strong = card.querySelector('strong');
    const small = card.querySelector('small');
    if (strong) strong.textContent = title;
    if (small) small.textContent = detail;
  };

  const invokeExisting = (id) => {
    const target = document.getElementById(id);
    if (target) target.click();
  };

  async function probeCore() {
    setState('desktopCoreCard', 'unknown', 'Checking…', 'Local runtime health probe');
    try {
      const response = await fetch(STATUS_ENDPOINTS.core, { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setState('desktopCoreCard', 'healthy', 'Online', 'Local DPN AI runtime responding');
    } catch (error) {
      setState('desktopCoreCard', 'blocked', 'Unavailable', 'Local runtime health endpoint not responding');
    }
  }

  function bindQuickActions() {
    const map = {
      desktopNewMissionBtn: 'missionsBtn',
      desktopApprovalsBtn: 'approvalsBtn',
      desktopProjectsBtn: 'projectsBtn',
      desktopDiagnosticsBtn: 'diagnosticsBtn',
    };
    for (const [source, target] of Object.entries(map)) {
      document.getElementById(source)?.addEventListener('click', () => invokeExisting(target));
    }
  }

  function bindWorkspaceTabs() {
    const map = {
      chat: 'newChatBtn',
      missions: 'missionsBtn',
      projects: 'projectsBtn',
      creator: 'capabilityForgeBtn',
      research: 'mcpBtn',
      automation: 'automationsBtn',
      diagnostics: 'diagnosticsBtn',
    };
    document.querySelectorAll('.desktop-workspace-tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.desktop-workspace-tab').forEach((item) => item.classList.remove('active'));
        tab.classList.add('active');
        const target = map[tab.dataset.workspace];
        if (target) invokeExisting(target);
        try {
          localStorage.setItem('dpn-ai-v8-workspace', tab.dataset.workspace || 'chat');
        } catch (_) {}
      });
    });

    try {
      const saved = localStorage.getItem('dpn-ai-v8-workspace');
      if (saved) {
        const tab = document.querySelector(`.desktop-workspace-tab[data-workspace="${saved}"]`);
        if (tab) {
          document.querySelectorAll('.desktop-workspace-tab').forEach((item) => item.classList.remove('active'));
          tab.classList.add('active');
        }
      }
    } catch (_) {}
  }

  function markUnavailableSurfaces() {
    setState('desktopMissionCard', 'unknown', 'No live feed', 'Waiting for mission summary API');
    setState('desktopApprovalCard', 'unknown', 'No live feed', 'Waiting for approval summary API');
    setState('desktopModelCard', 'unknown', 'No live feed', 'Waiting for model runtime summary API');
    setState('desktopAutomationCard', 'unknown', 'No live feed', 'Waiting for scheduler summary API');
    setState('desktopConnectorCard', 'unknown', 'No live feed', 'Waiting for connector health summary API');
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.body.classList.add('desktop-v8');
    bindQuickActions();
    bindWorkspaceTabs();
    markUnavailableSurfaces();
    probeCore();
    window.setInterval(probeCore, 30000);
  });
})();
