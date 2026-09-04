(() => {
  'use strict';

  const STATUS_ENDPOINTS = {
    core: '/api/health',
    summary: '/api/v1/desktop/summary',
    events: '/api/v1/desktop/events',
  };
  let streamAbort = null;
  let reconnectTimer = null;

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

  const authHeaders = () => {
    const token = sessionStorage.getItem('dpnApiToken') || '';
    return token ? { 'X-DPN-Token': token } : {};
  };

  function renderSummary(summary) {
    const missions = summary?.missions || {};
    const approvals = summary?.approvals || {};
    const model = summary?.model || {};
    const automations = summary?.automations || {};
    const connectors = summary?.connectors || {};

    setState(
      'desktopCoreCard',
      'healthy',
      'Online',
      `Desktop API ${summary?.api_version || 'v1'} • unified local runtime`,
    );
    setState(
      'desktopMissionCard',
      Number(missions.failed || 0) > 0 ? 'warning' : 'healthy',
      `${Number(missions.running || 0)} running`,
      `${Number(missions.queued || 0)} queued • ${Number(missions.total || 0)} total`,
    );
    setState(
      'desktopApprovalCard',
      Number(approvals.pending || 0) > 0 ? 'warning' : 'healthy',
      `${Number(approvals.pending || 0)} pending`,
      'Human-control approval boundary',
    );
    setState(
      'desktopModelCard',
      model?.warm_status?.ok ? 'healthy' : 'unknown',
      String(model.active || 'warming'),
      model?.warm_status?.ok ? 'Active intelligence model ready' : 'Model runtime warming or unavailable',
    );
    setState(
      'desktopAutomationCard',
      'healthy',
      `${Number(automations.enabled || 0)} enabled`,
      `${Number(automations.total || 0)} configured automations`,
    );
    setState(
      'desktopConnectorCard',
      'healthy',
      `${Number(connectors.enabled || 0)} enabled`,
      `${Number(connectors.total || 0)} configured connectors`,
    );
  }

  async function probeDesktopSummary() {
    setState('desktopCoreCard', 'unknown', 'Checking…', 'Versioned local desktop API probe');
    try {
      const response = await fetch(STATUS_ENDPOINTS.summary, {
        cache: 'no-store',
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderSummary(await response.json());
      return true;
    } catch (_) {
      setState('desktopCoreCard', 'blocked', 'Unavailable', 'Desktop API is not responding');
      return false;
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connectEventStream();
    }, 3000);
  }

  async function connectEventStream() {
    if (streamAbort) streamAbort.abort();
    streamAbort = new AbortController();
    try {
      const response = await fetch(STATUS_ENDPOINTS.events, {
        cache: 'no-store',
        headers: { ...authHeaders(), Accept: 'text/event-stream' },
        signal: streamAbort.signal,
      });
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split('\n\n');
        buffer = frames.pop() || '';
        for (const frame of frames) {
          const dataLine = frame.split('\n').find((line) => line.startsWith('data: '));
          if (!dataLine) continue;
          try {
            renderSummary(JSON.parse(dataLine.slice(6)));
          } catch (_) {}
        }
      }
      scheduleReconnect();
    } catch (error) {
      if (error?.name !== 'AbortError') scheduleReconnect();
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

  document.addEventListener('DOMContentLoaded', async () => {
    document.body.classList.add('desktop-v8');
    bindQuickActions();
    bindWorkspaceTabs();
    const online = await probeDesktopSummary();
    if (online) connectEventStream();
    window.setInterval(probeDesktopSummary, 30000);
  });

  window.addEventListener('beforeunload', () => {
    if (streamAbort) streamAbort.abort();
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
  });
})();
