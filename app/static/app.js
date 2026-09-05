const initialToken = new URLSearchParams(location.search).get('token') || sessionStorage.getItem('dpnApiToken') || '';
if (initialToken) { sessionStorage.setItem('dpnApiToken', initialToken); if (location.search.includes('token=')) history.replaceState({}, '', location.pathname); }

const VOICE_PACE_VERSION = 3;
const storedPaceVersion = Number(localStorage.getItem('dpnVoicePaceVersion') || 0);
if (storedPaceVersion < VOICE_PACE_VERSION) {
  const sentinelLegacy = Number(localStorage.getItem('dpnVoiceSpeed:sentinel'));
  if (!Number.isFinite(sentinelLegacy) || sentinelLegacy <= 0.84) localStorage.removeItem('dpnVoiceSpeed:sentinel');
  localStorage.setItem('dpnVoicePaceVersion', String(VOICE_PACE_VERSION));
}

const state = {
  conversationId: null,
  conversations: [],
  models: [],
  profiles: [],
  projects: [],
  settings: null,
  sending: false,
  pendingAttachments: [],
  editingMessageId: null,
  editingNode: null,
  skills: [],
  selectedSkills: [],
  apiToken: initialToken,
  voiceProfiles: [],
  voice: {
    selected: localStorage.getItem('dpnVoiceProfile') || 'sentinel',
    autoSpeak: localStorage.getItem('dpnAutoSpeak') === 'true',
    handsFree: localStorage.getItem('dpnHandsFree') === 'true',
    reviewBeforeSend: localStorage.getItem('dpnVoiceReview') !== 'false',
    sttModel: localStorage.getItem('dpnSttModel') || 'base',
    toneOverrides: {
      sentinel: localStorage.getItem('dpnVoiceTone:sentinel') || 'clear',
      aurora: localStorage.getItem('dpnVoiceTone:aurora') || 'gentle',
      system: localStorage.getItem('dpnVoiceTone:system') || 'natural',
    },
    speedOverrides: {
      sentinel: localStorage.getItem('dpnVoiceSpeed:sentinel') ? Number(localStorage.getItem('dpnVoiceSpeed:sentinel')) : null,
      aurora: localStorage.getItem('dpnVoiceSpeed:aurora') ? Number(localStorage.getItem('dpnVoiceSpeed:aurora')) : null,
      system: localStorage.getItem('dpnVoiceSpeed:system') ? Number(localStorage.getItem('dpnVoiceSpeed:system')) : null,
    },
    mediaRecorder: null,
    mediaStream: null,
    audioContext: null,
    analyser: null,
    chunks: [],
    recording: false,
    speechDetected: false,
    silenceStarted: 0,
    recordingStarted: 0,
    monitorFrame: 0,
    currentAudio: null,
    currentObjectUrl: null,
    voiceAvailable: false,
  },
};

const $ = (id) => document.getElementById(id);
const els = {
  sidebar: $('sidebar'), menuBtn: $('menuBtn'), newChatBtn: $('newChatBtn'), refreshChatsBtn: $('refreshChatsBtn'),
  conversationList: $('conversationList'), activeTitle: $('activeTitle'), modelSelect: $('modelSelect'), profileSelect: $('profileSelect'), modeSelect: $('modeSelect'),
  projectSelect: $('projectSelect'), indexBtn: $('indexBtn'), chat: $('chat'), welcome: $('welcome'), messages: $('messages'),
  promptInput: $('promptInput'), sendBtn: $('sendBtn'), fileInput: $('fileInput'), filesBtn: $('filesBtn'), memoryBtn: $('memoryBtn'), editBanner: $('editBanner'), cancelEditBtn: $('cancelEditBtn'),
  projectsBtn: $('projectsBtn'), missionsBtn: $('missionsBtn'), jobsBtn: $('jobsBtn'), graphBtn: $('graphBtn'), sandboxBtn: $('sandboxBtn'), capabilityForgeBtn: $('capabilityForgeBtn'), mcpBtn: $('mcpBtn'), approvalsBtn: $('approvalsBtn'), automationsBtn: $('automationsBtn'), runsBtn: $('runsBtn'), snapshotsBtn: $('snapshotsBtn'),
  diagnosticsBtn: $('diagnosticsBtn'), settingsBtn: $('settingsBtn'), skillsBtn: $('skillsBtn'), connectorsBtn: $('connectorsBtn'), voiceBtn: $('voiceBtn'), statusDot: $('statusDot'), statusText: $('statusText'),
  statusDetail: $('statusDetail'), permissionText: $('permissionText'), modalBackdrop: $('modalBackdrop'), modalTitle: $('modalTitle'),
  modalEyebrow: $('modalEyebrow'), modalBody: $('modalBody'), closeModalBtn: $('closeModalBtn'), pendingFiles: $('pendingFiles'),
  micBtn: $('micBtn'), voiceState: $('voiceState'), voiceTranscript: $('voiceTranscript'), voiceLevel: $('voiceLevel'), voiceSelect: $('voiceSelect'),
  autoSpeakToggle: $('autoSpeakToggle'), handsFreeToggle: $('handsFreeToggle'), voiceReviewToggle: $('voiceReviewToggle'), stopVoiceBtn: $('stopVoiceBtn'), voiceSettingsBtn: $('voiceSettingsBtn'),
  messageTemplate: $('messageTemplate'),
};

async function api(path, options = {}) {
  options.headers = {...(options.headers || {})};
  if (state.apiToken) options.headers['X-DPN-Token'] = state.apiToken;
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    let detail = data?.detail || data?.error || data || `HTTP ${response.status}`;
    if (response.status >= 500 && (!detail || detail === 'Internal Server Error')) {
      detail = 'DPN AI hit a server error. Check runtime_logs\\errors.log and runtime_logs\\server.log in the installation folder.';
    }
    const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    error.status = response.status;
    error.errorId = data?.error_id || null;
    throw error;
  }
  return data;
}

async function streamChat(payload, onEvent) {
  const headers = {'Content-Type':'application/json'};
  if (state.apiToken) headers['X-DPN-Token'] = state.apiToken;
  const response = await fetch('/api/chat/stream', {method:'POST', headers, body:JSON.stringify(payload)});
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  if (!response.body) throw new Error('This browser did not provide a streaming response body.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const {value, done} = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      let event;
      try { event = JSON.parse(line); } catch { continue; }
      await onEvent(event);
    }
    if (done) break;
  }
  if (buffer.trim()) {
    try { await onEvent(JSON.parse(buffer)); } catch { /* ignore partial trailing event */ }
  }
}

async function apiBlob(path, options = {}) {
  options.headers = {...(options.headers || {})};
  if (state.apiToken) options.headers['X-DPN-Token'] = state.apiToken;
  const response = await fetch(path, options);
  if (!response.ok) {
    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('application/json') ? await response.json() : await response.text();
    let detail = data?.detail || data?.error || data || `HTTP ${response.status}`;
    if (response.status >= 500 && (!detail || detail === 'Internal Server Error')) {
      detail = 'DPN AI hit a server error. Check runtime_logs\\errors.log and runtime_logs\\server.log in the installation folder.';
    }
    const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    error.status = response.status;
    error.errorId = data?.error_id || null;
    throw error;
  }
  return response.blob();
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}

function inlineMarkdown(text) {
  let html = escapeHtml(text);
  const links = [];
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => {
    const token = `@@LINK_${links.length}@@`;
    links.push(`<a href="${url}" target="_blank" rel="noreferrer">${label}</a>`);
    return token;
  });
  html = html.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noreferrer">$1</a>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  links.forEach((link, index) => { html = html.replace(`@@LINK_${index}@@`, link); });
  return html;
}

function renderMarkdown(text = '') {
  const blocks = [];
  let protectedText = String(text).replace(/```([\w-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const token = `@@CODEBLOCK_${blocks.length}@@`;
    blocks.push(`<pre><code data-language="${escapeHtml(lang)}">${escapeHtml(code.trim())}</code></pre>`);
    return token;
  });
  const lines = protectedText.split('\n');
  const out = [];
  let listType = null;
  const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) { closeList(); continue; }
    if (/^@@CODEBLOCK_\d+@@$/.test(line.trim())) { closeList(); out.push(line.trim()); continue; }
    let match;
    if ((match = line.match(/^###\s+(.+)/))) { closeList(); out.push(`<h3>${inlineMarkdown(match[1])}</h3>`); continue; }
    if ((match = line.match(/^##\s+(.+)/))) { closeList(); out.push(`<h2>${inlineMarkdown(match[1])}</h2>`); continue; }
    if ((match = line.match(/^#\s+(.+)/))) { closeList(); out.push(`<h2>${inlineMarkdown(match[1])}</h2>`); continue; }
    if ((match = line.match(/^>\s?(.+)/))) { closeList(); out.push(`<blockquote>${inlineMarkdown(match[1])}</blockquote>`); continue; }
    if ((match = line.match(/^[-*]\s+(.+)/))) {
      if (listType !== 'ul') { closeList(); listType = 'ul'; out.push('<ul>'); }
      out.push(`<li>${inlineMarkdown(match[1])}</li>`); continue;
    }
    if ((match = line.match(/^\d+[.)]\s+(.+)/))) {
      if (listType !== 'ol') { closeList(); listType = 'ol'; out.push('<ol>'); }
      out.push(`<li>${inlineMarkdown(match[1])}</li>`); continue;
    }
    closeList(); out.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  let html = out.join('');
  blocks.forEach((block, index) => { html = html.replace(`@@CODEBLOCK_${index}@@`, block); });
  return html || '<p></p>';
}

function formatBytes(bytes = 0) {
  if (!Number.isFinite(Number(bytes))) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Number(bytes); let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function formatDate(value) {
  if (!value) return 'Never';
  try { return new Date(value).toLocaleString(); } catch { return value; }
}

function toast(message, error = false) {
  let stack = document.querySelector('.toast-stack');
  if (!stack) { stack = document.createElement('div'); stack.className = 'toast-stack'; document.body.appendChild(stack); }
  const item = document.createElement('div'); item.className = `toast${error ? ' error' : ''}`; item.textContent = message;
  stack.appendChild(item); setTimeout(() => item.remove(), 4600);
}

function setWelcome(show) { els.welcome.style.display = show ? '' : 'none'; }


function setVoiceUi(mode, detail = '', level = 0) {
  if (!els.voiceState) return;
  const labels = {ready:'VOICE READY', listening:'LISTENING', processing:'TRANSCRIBING', thinking:'AI WORKING', speaking:'SPEAKING', unavailable:'VOICE OFF', error:'VOICE ERROR'};
  els.voiceState.textContent = labels[mode] || String(mode).toUpperCase();
  if (els.voiceTranscript) els.voiceTranscript.textContent = detail || (mode === 'ready' ? 'Click the microphone or press Ctrl+Space' : '');
  if (els.voiceLevel) els.voiceLevel.style.width = `${Math.max(0, Math.min(100, level * 100))}%`;
  if (els.micBtn) {
    els.micBtn.classList.toggle('recording', mode === 'listening');
    els.micBtn.classList.toggle('processing', ['processing','thinking'].includes(mode));
    els.micBtn.disabled = mode === 'unavailable';
  }
}

function voiceProfile(voiceId = state.voice.selected) {
  return state.voiceProfiles.find(item => item.id === voiceId) || state.voiceProfiles[0] || {id:voiceId,name:voiceId,installed:false,default_speed:0.82};
}

function selectedVoiceProfile() { return voiceProfile(state.voice.selected); }

function voiceSpeedFor(voiceId = state.voice.selected) {
  const override = Number(state.voice.speedOverrides?.[voiceId]);
  if (Number.isFinite(override) && override >= 0.57 && override <= 1.42) return override;
  const natural = Number(voiceProfile(voiceId).default_speed);
  return Number.isFinite(natural) ? natural : 0.82;
}

function setVoiceSpeed(voiceId, speed) {
  const value = Math.max(0.57, Math.min(1.42, Number(speed)));
  state.voice.speedOverrides[voiceId] = value;
  localStorage.setItem(`dpnVoiceSpeed:${voiceId}`, String(value));
  return value;
}

function resetVoiceSpeed(voiceId) {
  state.voice.speedOverrides[voiceId] = null;
  localStorage.removeItem(`dpnVoiceSpeed:${voiceId}`);
  return voiceSpeedFor(voiceId);
}

function voiceToneFor(voiceId = state.voice.selected) {
  return state.voice.toneOverrides?.[voiceId] || voiceProfile(voiceId).default_tone || 'natural';
}

function setVoiceTone(voiceId, tone) {
  const profile = voiceProfile(voiceId);
  const allowed = profile.tone_options || ['natural'];
  const value = allowed.includes(tone) ? tone : (profile.default_tone || allowed[0] || 'natural');
  state.voice.toneOverrides[voiceId] = value;
  localStorage.setItem(`dpnVoiceTone:${voiceId}`, value);
  return value;
}

async function loadVoiceProfiles() {
  try {
    const data = await api('/api/voice/profiles');
    state.voiceProfiles = data.profiles || [];
    const ids = state.voiceProfiles.map(item => item.id);
    if (!ids.includes(state.voice.selected)) state.voice.selected = data.default_voice || ids[0] || 'sentinel';
    els.voiceSelect.innerHTML = state.voiceProfiles.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}${item.installed ? '' : ' â€¢ install'}</option>`).join('');
    els.voiceSelect.value = state.voice.selected;
    els.autoSpeakToggle.checked = state.voice.autoSpeak;
    els.handsFreeToggle.checked = state.voice.handsFree;
    if (els.voiceReviewToggle) els.voiceReviewToggle.checked = state.voice.reviewBeforeSend;
    const status = await api('/api/voice/status');
    state.voice.voiceAvailable = Boolean(status.stt || status.tts);
    setVoiceUi(state.settings?.allow_voice ? 'ready' : 'unavailable', state.settings?.allow_voice ? `${selectedVoiceProfile().name} â€¢ local speech` : 'Enable voice capabilities in Settings');
  } catch (error) {
    state.voice.voiceAvailable = false;
    setVoiceUi('error', error.message);
  }
}

function stopVoicePlayback(updateUi = true) {
  if (state.voice.currentAudio) {
    state.voice.currentAudio.pause();
    state.voice.currentAudio.src = '';
    state.voice.currentAudio = null;
  }
  if (state.voice.currentObjectUrl) {
    URL.revokeObjectURL(state.voice.currentObjectUrl);
    state.voice.currentObjectUrl = null;
  }
  if (updateUi && !state.voice.recording) setVoiceUi(state.settings?.allow_voice ? 'ready' : 'unavailable');
}

async function speakText(text, voiceId = state.voice.selected) {
  if (!state.settings?.allow_voice) throw new Error('Voice capabilities are disabled in Settings.');
  stopVoicePlayback(false);
  const profile = voiceProfile(voiceId);
  const speed = voiceSpeedFor(voiceId);
  setVoiceUi('processing', `Preparing ${profile.name} at ${speed.toFixed(2)}Ã— narration paceâ€¦`);
  const result = await api('/api/voice/synthesize', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text, voice_id:voiceId, speed, filename:`dpn-voice-${Date.now()}.wav`, tone:voiceToneFor(voiceId)}),
  });
  const blob = await apiBlob(result.download_url);
  const objectUrl = URL.createObjectURL(blob);
  const audio = new Audio(objectUrl);
  state.voice.currentAudio = audio;
  state.voice.currentObjectUrl = objectUrl;
  setVoiceUi('speaking', `${result.voice?.name || voiceId} is speaking`);
  audio.onended = () => {
    stopVoicePlayback(false);
    setVoiceUi('ready', 'Voice reply complete');
    if (state.voice.handsFree) setTimeout(() => startVoiceRecording(true).catch(error => { setVoiceUi('error', error.message); toast(error.message,true); }), 450);
  };
  audio.onerror = () => { stopVoicePlayback(); toast('The generated voice audio could not be played.', true); };
  await audio.play();
  return result;
}

function cleanupRecorder() {
  if (state.voice.monitorFrame) cancelAnimationFrame(state.voice.monitorFrame);
  state.voice.monitorFrame = 0;
  if (state.voice.audioContext) state.voice.audioContext.close().catch(() => {});
  state.voice.audioContext = null;
  state.voice.analyser = null;
  if (state.voice.mediaStream) state.voice.mediaStream.getTracks().forEach(track => track.stop());
  state.voice.mediaStream = null;
  state.voice.mediaRecorder = null;
  state.voice.recording = false;
  els.voiceLevel.style.width = '0%';
}

async function processVoiceRecording(blob) {
  if (!blob || blob.size < 200) { setVoiceUi('ready', 'No usable audio was captured'); if (state.voice.handsFree) setTimeout(() => startVoiceRecording(true), 800); return; }
  setVoiceUi('processing', 'Local faster-whisper is transcribingâ€¦');
  const form = new FormData();
  const extension = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('wav') ? 'wav' : 'webm';
  form.append('file', blob, `microphone-${Date.now()}.${extension}`);
  form.append('model_size', state.voice.sttModel);
  try {
    const transcript = await api('/api/voice/transcribe', {method:'POST', body:form});
    const text = String(transcript.text || '').trim();
    if (!text) throw new Error('No speech was detected.');
    els.promptInput.value = text; autoresize();
    if (state.voice.reviewBeforeSend && !state.voice.handsFree) {
      setVoiceUi('ready', 'Transcript placed in the chat box. Edit it, then press Send.');
      els.promptInput.focus();
      toast('Voice transcript is ready to edit before sending.');
    } else {
      setVoiceUi('thinking', text);
      await sendMessage(text, {fromVoice:true});
    }
  } catch (error) {
    setVoiceUi('error', error.message);
    toast(error.message, true);
    if (state.voice.handsFree) setTimeout(() => startVoiceRecording(true).catch(() => {}), 1200);
  }
}

function monitorVoiceActivity() {
  const analyser = state.voice.analyser;
  if (!analyser || !state.voice.recording) return;
  const data = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(data);
  let sum = 0;
  for (const value of data) { const normalized = (value - 128) / 128; sum += normalized * normalized; }
  const rms = Math.sqrt(sum / data.length);
  const level = Math.min(1, rms * 8);
  els.voiceLevel.style.width = `${Math.max(2, level * 100)}%`;
  const now = performance.now();
  if (rms > 0.032) {
    state.voice.speechDetected = true;
    state.voice.silenceStarted = 0;
    els.voiceTranscript.textContent = 'Speech detectedâ€¦';
  } else if (state.voice.speechDetected && rms < 0.018) {
    if (!state.voice.silenceStarted) state.voice.silenceStarted = now;
    if (state.voice.handsFree && now - state.voice.silenceStarted > 1050) stopVoiceRecording();
  }
  if (now - state.voice.recordingStarted > 90000 || (!state.voice.speechDetected && now - state.voice.recordingStarted > 15000 && state.voice.handsFree)) stopVoiceRecording();
  if (state.voice.recording) state.voice.monitorFrame = requestAnimationFrame(monitorVoiceActivity);
}

async function startVoiceRecording(handsFree = false) {
  if (state.voice.recording || state.sending) return;
  if (!state.settings?.allow_voice) throw new Error('Enable offline voice tools in DPN AI Settings first.');
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('This browser does not support microphone recording.');
  stopVoicePlayback(false);
  const stream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true, noiseSuppression:true, autoGainControl:true}, video:false});
  const candidates = ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus'];
  const mimeType = candidates.find(type => MediaRecorder.isTypeSupported(type)) || '';
  const recorder = mimeType ? new MediaRecorder(stream,{mimeType}) : new MediaRecorder(stream);
  state.voice.mediaStream = stream;
  state.voice.mediaRecorder = recorder;
  state.voice.chunks = [];
  state.voice.recording = true;
  state.voice.speechDetected = false;
  state.voice.silenceStarted = 0;
  state.voice.recordingStarted = performance.now();
  recorder.ondataavailable = event => { if (event.data?.size) state.voice.chunks.push(event.data); };
  recorder.onstop = () => {
    const blob = new Blob(state.voice.chunks, {type:recorder.mimeType || 'audio/webm'});
    cleanupRecorder();
    processVoiceRecording(blob);
  };
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (AudioContextClass) {
    state.voice.audioContext = new AudioContextClass();
    const source = state.voice.audioContext.createMediaStreamSource(stream);
    state.voice.analyser = state.voice.audioContext.createAnalyser();
    state.voice.analyser.fftSize = 1024;
    source.connect(state.voice.analyser);
  }
  recorder.start(250);
  setVoiceUi('listening', handsFree ? 'Speak naturally. DPN AI stops after silence.' : 'Listening. Click the microphone again when finished.');
  monitorVoiceActivity();
}

function stopVoiceRecording() {
  const recorder = state.voice.mediaRecorder;
  if (!recorder || !state.voice.recording) return;
  state.voice.recording = false;
  if (recorder.state !== 'inactive') recorder.stop();
}

async function toggleVoiceRecording() {
  if (state.voice.recording) { stopVoiceRecording(); return; }
  await startVoiceRecording(false);
}

async function installVoiceProfile(voiceId) {
  toast(`Installing the improved ${voiceId} model. This local download may be over 100 MB.`);
  const result = await api(`/api/voice/profiles/${encodeURIComponent(voiceId)}/install`, {method:'POST'});
  await loadVoiceProfiles();
  toast(`${result.voice?.name || voiceId} is installed locally.`);
  return result;
}

async function showVoiceCenter() {
  const [profileData, status] = await Promise.all([api('/api/voice/profiles'), api('/api/voice/status')]);
  const profiles = profileData.profiles || [];
  openModal('Voice Command Center', 'LOCAL CONVERSATIONAL AUDIO', `
    <div class="metric-grid"><div><strong>${status.stt ? 'READY' : 'OFF'}</strong><span>Speech recognition</span></div><div><strong>${status.piper ? 'READY' : 'OFF'}</strong><span>Neural TTS engine</span></div><div><strong>${status.installed_profiles?.length || 0}</strong><span>Installed voices</span></div><div><strong>${escapeHtml(state.voice.sttModel)}</strong><span>STT model</span></div></div>
    <p class="help-text">The v5.0.7 clarity engine uses a higher-quality Sentinel model when installed, natural sentence pacing, low-noise gain control and selectable delivery tones. Aurora remains softer and gentler. Neither voice imitates a real person.</p>
    <div class="voice-profile-grid">${profiles.map(profile => `<article class="voice-profile-card ${profile.id === state.voice.selected ? 'selected' : ''}"><header><div><span class="status-badge ${profile.installed ? 'completed' : 'failed'}">${profile.installed ? 'INSTALLED' : 'NOT INSTALLED'}</span><h4>${escapeHtml(profile.name)}</h4></div><strong>${escapeHtml(profile.gender)}</strong></header><p>${escapeHtml(profile.style)}</p><small>${escapeHtml(profile.description)}</small><div class="voice-tone"><b>Delivery tone</b><span>${escapeHtml(profile.tone || profile.style)}</span></div><label class="voice-pace"><span>Reading pace <output data-voice-speed-output="${profile.id}">${voiceSpeedFor(profile.id).toFixed(2)}Ã—</output></span><input type="range" min="0.65" max="1.12" step="0.01" value="${voiceSpeedFor(profile.id)}" data-voice-speed="${profile.id}"><small>Natural preset: ${Number(profile.default_speed || 0.90).toFixed(2)}Ã—</small></label><label class="voice-tone-select"><span>Delivery tone</span><select data-voice-tone="${profile.id}">${(profile.tone_options || ['natural']).map(tone => `<option value="${tone}" ${voiceToneFor(profile.id) === tone ? 'selected' : ''}>${tone.charAt(0).toUpperCase()+tone.slice(1)}</option>`).join('')}</select><small>${profile.using_fallback_model ? `Legacy model active: ${profile.active_model}. Install the HD voice for the cleanest result.` : `Active model: ${profile.active_model || 'system voice'}`}</small></label><div class="modal-actions"><button class="secondary" data-voice-select="${profile.id}">Use Voice</button><button class="secondary" data-voice-reset="${profile.id}">Natural Pace</button>${profile.installed ? `<button class="secondary" data-voice-sample="${profile.id}">Play Sample</button>` : ''}${profile.update_available ? `<button class="primary compact" data-voice-install="${profile.id}">Upgrade to HD</button>` : (!profile.installed ? `<button class="primary compact" data-voice-install="${profile.id}">Install Locally</button>` : '')}</div></article>`).join('')}</div>
    <div class="form-grid voice-advanced"><div class="field"><label>Speech recognition model</label><select id="voiceSttModel"><option value="tiny">Tiny â€” fastest</option><option value="base">Base â€” recommended</option><option value="small">Small â€” more accurate</option><option value="medium">Medium â€” high accuracy</option><option value="large-v3-turbo">Large v3 Turbo â€” strongest</option></select><small>The model downloads locally the first time it is used.</small></div></div>
    <div class="modal-actions"><button class="secondary" id="clearVoiceCacheBtn">Release Voice Models From Memory</button></div>`, true);
  $('voiceSttModel').value = state.voice.sttModel;
  $('voiceSttModel').onchange = event => { state.voice.sttModel = event.target.value; localStorage.setItem('dpnSttModel',state.voice.sttModel); };
  document.querySelectorAll('[data-voice-select]').forEach(button => button.onclick = () => { state.voice.selected=button.dataset.voiceSelect; localStorage.setItem('dpnVoiceProfile',state.voice.selected); els.voiceSelect.value=state.voice.selected; closeModal(); setVoiceUi('ready',`${selectedVoiceProfile().name} selected at ${voiceSpeedFor().toFixed(2)}Ã—`); });
  document.querySelectorAll('[data-voice-speed]').forEach(input => input.oninput = () => { const voiceId=input.dataset.voiceSpeed; const value=setVoiceSpeed(voiceId,input.value); const output=document.querySelector(`[data-voice-speed-output="${voiceId}"]`); if (output) output.textContent=`${value.toFixed(2)}Ã—`; });
  document.querySelectorAll('[data-voice-tone]').forEach(select => select.onchange = () => { const voiceId=select.dataset.voiceTone; const value=setVoiceTone(voiceId,select.value); toast(`${voiceProfile(voiceId).name} tone set to ${value}.`); });
  document.querySelectorAll('[data-voice-reset]').forEach(button => button.onclick = () => { const voiceId=button.dataset.voiceReset; const value=resetVoiceSpeed(voiceId); const input=document.querySelector(`[data-voice-speed="${voiceId}"]`); const output=document.querySelector(`[data-voice-speed-output="${voiceId}"]`); if (input) input.value=String(value); if (output) output.textContent=`${value.toFixed(2)}Ã—`; toast(`${voiceProfile(voiceId).name} restored to its natural narration pace.`); });
  document.querySelectorAll('[data-voice-install]').forEach(button => button.onclick = async () => { try { await installVoiceProfile(button.dataset.voiceInstall); await showVoiceCenter(); } catch(error) { toast(error.message,true); } });
  document.querySelectorAll('[data-voice-sample]').forEach(button => button.onclick = () => { const voiceId=button.dataset.voiceSample; const sample=voiceId === 'aurora' ? 'Take a comfortable breath. I can read this slowly, gently, and clearly, with space between each thought.' : 'DPN AI voice systems are online. I will deliver each operation clearly, calmly, and at a measured pace.'; speakText(sample,voiceId).catch(error=>toast(error.message,true)); });
  $('clearVoiceCacheBtn').onclick = async () => { const result=await api('/api/voice/cache/clear',{method:'POST'}); toast(`Released ${result.piper_models_released + result.whisper_models_released} cached voice model(s).`); };
}

function cancelMessageEdit(clearInput = false) {
  state.editingMessageId = null;
  state.editingNode = null;
  if (els.editBanner) els.editBanner.classList.add('hidden');
  if (clearInput) { els.promptInput.value = ''; autoresize(); }
}

function startMessageEdit(messageId, content, node) {
  if (!messageId) return;
  state.editingMessageId = Number(messageId);
  state.editingNode = node;
  els.promptInput.value = content;
  autoresize();
  if (els.editBanner) els.editBanner.classList.remove('hidden');
  els.promptInput.focus();
  els.promptInput.setSelectionRange(els.promptInput.value.length, els.promptInput.value.length);
  toast('Edit the message, then press Send to regenerate from that point.');
}

function adaptiveVerification(message, profile, mode) {
  if (mode === 'mission') return false;
  const text = String(message || '').toLowerCase();
  const artifact = /(word document|docx|pdf|spreadsheet|excel|xlsx|powerpoint|pptx|presentation|slide deck)/.test(text);
  return artifact || ['software','fivem','security','data','science'].includes(profile) || /(verify|test|audit|fix|production|release|deploy|accurate|current research)/.test(text);
}

function ensureMessagePart(node, className) {
  if (!node) return null;
  let part = node.querySelector(`.${className}`);
  if (!part) {
    part = document.createElement('div');
    part.className = className;
    const main = node.querySelector('.message-main') || node;
    main.appendChild(part);
  }
  return part;
}

function attachUserMessageActions(node, messageId, content) {
  if (!node || !messageId) return;
  const actions = ensureMessagePart(node, 'message-actions');
  if (!actions) return;
  actions.innerHTML = '';
  const editButton = document.createElement('button');
  editButton.innerHTML = 'âœŽ Edit & resend';
  editButton.title = 'Edit this message and regenerate the conversation from here';
  editButton.onclick = () => startMessageEdit(messageId, content, node);
  const copyButton = document.createElement('button');
  copyButton.innerHTML = 'â–£ Copy';
  copyButton.onclick = async () => { await navigator.clipboard.writeText(content); toast('Message copied.'); };
  actions.append(editButton, copyButton);
}

function addMessage(role, content, metadata = {}) {
  setWelcome(false);
  const templateNode = els.messageTemplate?.content?.firstElementChild;
  const node = templateNode ? templateNode.cloneNode(true) : document.createElement('article');
  if (!templateNode) node.innerHTML = '<div class="avatar"></div><div class="message-main"></div>';
  node.classList.add('message');
  node.classList.add(role);
  const label = ensureMessagePart(node, 'message-label');
  if (label) label.textContent = role === 'user' ? 'YOU' : 'DPN AI';
  const badges = ensureMessagePart(node, 'run-badges');
  if (metadata.profile) badges.innerHTML += `<span>${escapeHtml(metadata.profile)}</span>`;
  if (metadata.model) badges.innerHTML += `<span>${escapeHtml(metadata.model)}</span>`;
  if (metadata.run_id) badges.innerHTML += `<span title="Operation run">RUN ${escapeHtml(metadata.run_id.slice(0, 8))}</span>`;
  if (metadata.project_id) {
    const project = state.projects.find(item => item.id === metadata.project_id);
    badges.innerHTML += `<span>${escapeHtml(project?.name || 'Project')}</span>`;
  }
  if (!badges.children.length) badges.remove();
  const contentNode = ensureMessagePart(node, 'message-content');
  if (contentNode) contentNode.innerHTML = renderMarkdown(content);
  const actions = ensureMessagePart(node, 'message-actions');
  if (actions && role === 'assistant' && content) {
    const readButton = document.createElement('button');
    readButton.innerHTML = 'â—‰ Read aloud';
    readButton.title = 'Read this response using the selected local voice';
    readButton.onclick = () => speakText(content).catch(error => toast(error.message, true));
    const copyButton = document.createElement('button');
    copyButton.innerHTML = 'â–£ Copy';
    copyButton.onclick = async () => { await navigator.clipboard.writeText(content); toast('Response copied.'); };
    actions.append(readButton, copyButton);
  } else if (role === 'user' && metadata.message_id) {
    attachUserMessageActions(node, metadata.message_id, content);
  } else if (actions) {
    actions.remove();
  }
  const attachments = ensureMessagePart(node, 'attachments');
  const shownFiles = [...(metadata.attachments || []), ...(metadata.generated_files || [])];
  for (const path of [...new Set(shownFiles)]) {
    const a = document.createElement('a');
    a.className = 'file-chip'; a.href = `/api/files/download/${encodeURI(path)}`; a.textContent = `â–£ ${path}`; a.setAttribute('download', '');
    if (attachments) attachments.appendChild(a);
  }
  if (attachments && !attachments.children.length) attachments.remove();
  const trace = ensureMessagePart(node, 'trace');
  for (const entry of metadata.traces || []) {
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.innerHTML = `<span class="${entry.ok ? 'ok' : 'bad'}">${entry.ok ? 'âœ“' : 'âœ•'}</span> ${escapeHtml(entry.name)} <small>${entry.elapsed_ms || 0} ms</small>`;
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify({arguments: entry.arguments, result: entry.result}, null, 2);
    details.append(summary, pre); if (trace) trace.appendChild(details);
  }
  if (trace && !trace.children.length) trace.remove();
  els.messages.appendChild(node);
  els.chat.scrollTop = els.chat.scrollHeight;
  return node;
}

function addTyping() {
  const node = addMessage('assistant', '');
  node.classList.add('pending');
  const contentNode = ensureMessagePart(node, 'message-content');
  if (contentNode) contentNode.innerHTML = '<span class="typing"><i></i><i></i><i></i></span><small class="operation-pulse">DPN AI is executing the operationâ€¦</small>';
  return node;
}

function renderPendingAttachments() {
  els.pendingFiles.innerHTML = '';
  for (const path of state.pendingAttachments) {
    const chip = document.createElement('span');
    chip.className = 'pending-chip';
    chip.innerHTML = `<span>${escapeHtml(path)}</span><button title="Remove attachment">âœ•</button>`;
    chip.querySelector('button').onclick = () => {
      state.pendingAttachments = state.pendingAttachments.filter(item => item !== path);
      renderPendingAttachments();
    };
    els.pendingFiles.appendChild(chip);
  }
  els.pendingFiles.style.display = state.pendingAttachments.length ? 'flex' : 'none';
}

function autoresize() {
  els.promptInput.style.height = 'auto';
  els.promptInput.style.height = `${Math.min(els.promptInput.scrollHeight, 180)}px`;
}

function openModal(title, eyebrow, bodyHtml, wide = false) {
  if (!els.modalBackdrop || !els.modalBody) return toast('The control center could not open. Refresh the interface cache with Ctrl+F5.', true);
  if (els.modalTitle) els.modalTitle.textContent = title;
  if (els.modalEyebrow) els.modalEyebrow.textContent = eyebrow;
  els.modalBody.innerHTML = bodyHtml;
  const modal = $('modal');
  if (modal) modal.classList.toggle('modal-wide', wide);
  els.modalBackdrop.classList.remove('hidden');
  els.modalBody.scrollTop = 0;
  els.modalBody.scrollLeft = 0;
  requestAnimationFrame(() => els.modalBody.focus({preventScroll:true}));
}
function closeModal() { if (els.modalBackdrop) els.modalBackdrop.classList.add('hidden'); }

async function loadHealth() {
  try {
    const data = await api('/api/health');
    const gateway = data.model_gateway || data.ollama || {};
    const ok = Boolean(gateway.ok);
    const provider = String(gateway.default_provider || data.settings?.default_provider || 'ollama').toUpperCase();
    els.statusDot.className = `status-dot ${ok ? 'ok' : 'bad'}`;
    els.statusText.textContent = ok ? `DPN Core v${data.version}` : 'Model Gateway Offline';
    const activeModel = data.intelligence?.active_model && data.intelligence.active_model !== 'warming' ? data.intelligence.active_model : 'warming strongest model';
    els.statusDetail.textContent = ok ? `${provider} â€¢ MAX intelligence â€¢ ${activeModel} â€¢ ${data.plugins.loaded_tools} tools` : 'Start Ollama or configure a compatible model server';
    state.settings = data.settings; updatePermissions();
  } catch (error) {
    els.statusDot.className = 'status-dot bad'; els.statusText.textContent = 'Core Error'; els.statusDetail.textContent = error.message;
  }
}

function updatePermissions() {
  if (!state.settings) return;
  els.permissionText.textContent = `Web ${state.settings.allow_web ? 'ON' : 'OFF'} â€¢ Voice ${state.settings.allow_voice ? 'ON' : 'OFF'} â€¢ MCP ${state.settings.allow_mcp ? 'ON' : 'OFF'} â€¢ Forge ${state.settings.allow_self_improvement ? 'ON' : 'OFF'} â€¢ Commands ${state.settings.allow_commands ? 'ON' : 'OFF'} â€¢ ${String(state.settings.approval_mode || 'standard').toUpperCase()}`;
  if (els.micBtn) els.micBtn.disabled = !state.settings.allow_voice;
}

async function loadModels() {
  try {
    const data = await api('/api/models'); state.models = data.models || [];
    const selected = state.settings?.model || els.modelSelect.value;
    const names = [...new Set(state.models.map(item => item.name || item.model).filter(Boolean))];
    if (selected && !names.includes(selected) && selected !== '__maximum__') names.unshift(selected);
    const autoOption = '<option value="__maximum__">AUTO â€” Strongest Installed Model</option>';
    els.modelSelect.innerHTML = autoOption + (names.length ? names.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('') : '');
    els.modelSelect.value = state.settings?.intelligence_mode === 'manual' && selected ? selected : '__maximum__';
  } catch (error) {
    els.modelSelect.innerHTML = `<option value="">Model gateway offline</option>`;
  }
}

async function loadProfiles() {
  const data = await api('/api/profiles'); state.profiles = data.profiles || [];
  els.profileSelect.innerHTML = state.profiles.map(profile => `<option value="${escapeHtml(profile.key)}">${escapeHtml(profile.name)}</option>`).join('');
}

async function loadSkills() {
  const data = await api('/api/skills');
  state.skills = data.skills || [];
  state.selectedSkills = state.selectedSkills.filter(id => state.skills.some(skill => skill.id === id));
}

async function loadProjects() {
  const data = await api('/api/projects'); state.projects = data.projects || [];
  const selected = els.projectSelect.value;
  els.projectSelect.innerHTML = '<option value="">No project</option>' + state.projects.map(project => `<option value="${project.id}">${escapeHtml(project.name)}</option>`).join('');
  if (state.projects.some(item => item.id === selected)) els.projectSelect.value = selected;
}

async function loadConversations() {
  const data = await api('/api/conversations'); state.conversations = data.conversations || [];
  els.conversationList.innerHTML = '';
  for (const conversation of state.conversations) {
    const row = document.createElement('div'); row.className = `conversation${conversation.id === state.conversationId ? ' active' : ''}`;
    row.innerHTML = `<button class="conversation-open"><span class="name">${escapeHtml(conversation.title)}</span></button><button class="export" title="Export">â‡©</button><button class="delete" title="Delete">âœ•</button>`;
    row.querySelector('.conversation-open').onclick = () => openConversation(conversation.id, conversation.title);
    row.querySelector('.conversation-open').ondblclick = async () => {
      const title = prompt('Rename operation', conversation.title);
      if (!title?.trim()) return;
      await api(`/api/conversations/${conversation.id}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:title.trim()})});
      await loadConversations();
    };
    row.querySelector('.export').onclick = async (event) => {
      event.stopPropagation(); const result = await api(`/api/conversations/${conversation.id}/export?format=markdown`, {method:'POST'});
      toast(`Exported to ${result.path}`);
    };
    row.querySelector('.delete').onclick = async (event) => {
      event.stopPropagation(); if (!confirm(`Delete â€œ${conversation.title}â€?`)) return;
      await api(`/api/conversations/${conversation.id}`, {method:'DELETE'});
      if (state.conversationId === conversation.id) newConversation();
      await loadConversations();
    };
    els.conversationList.appendChild(row);
  }
}

async function openConversation(id, title) {
  const data = await api(`/api/conversations/${id}`);
  state.conversationId = id; els.activeTitle.textContent = title; els.messages.innerHTML = ''; setWelcome(!(data.messages || []).length);
  for (const message of data.messages || []) addMessage(message.role, message.content, {...(message.metadata || {}), message_id:message.id});
  await loadConversations(); els.sidebar.classList.remove('open');
}

function newConversation() {
  state.conversationId = null; cancelMessageEdit(true); els.activeTitle.textContent = 'New operation'; els.messages.innerHTML = ''; setWelcome(true); els.promptInput.focus();
  [...els.conversationList.children].forEach(node => node.classList.remove('active'));
}

async function sendMessage(forcedPrompt = null, options = {}) {
  const message = (forcedPrompt ?? els.promptInput.value).trim();
  if (!message || state.sending) return null;
  state.sending = true; els.sendBtn.disabled = true;
  if (options.fromVoice) setVoiceUi('thinking', message);
  const attachments = [...state.pendingAttachments];
  const editMessageId = state.editingMessageId;
  if (editMessageId && state.editingNode) {
    let node = state.editingNode;
    while (node) { const next = node.nextElementSibling; node.remove(); node = next; }
  }
  cancelMessageEdit(false);
  const userNode = addMessage('user', message, {attachments, profile: els.profileSelect.value, project_id: els.projectSelect.value || null});
  els.promptInput.value = ''; autoresize();
  const pending = addTyping();
  let responseData = null;
  try {
    const requestPayload = {conversation_id: state.conversationId, message, model: els.modelSelect.value || '__maximum__', attachments, profile: els.profileSelect.value, project_id: els.projectSelect.value || null, execution_mode: editMessageId ? 'direct' : els.modeSelect.value, skill_ids: state.selectedSkills, verify: adaptiveVerification(message, els.profileSelect.value, els.modeSelect.value), edit_message_id:editMessageId};
    let streamedText = '';
    let data = null;
    await streamChat(requestPayload, async event => {
      if (event.type === 'token') {
        streamedText += String(event.text || '');
        pending.classList.remove('pending');
        const streamNode = ensureMessagePart(pending, 'message-content');
        if (streamNode) streamNode.innerHTML = renderMarkdown(streamedText);
        els.chat.scrollTop = els.chat.scrollHeight;
      } else if (event.type === 'status') {
        if (!streamedText) { const streamNode = ensureMessagePart(pending, 'message-content'); if (streamNode) streamNode.innerHTML = `<span class="typing"><i></i><i></i><i></i></span><small class="operation-pulse">${escapeHtml(event.message || 'DPN AI is workingâ€¦')}</small>`; }
      } else if (event.type === 'error') {
        throw new Error(event.message || 'DPN AI streaming operation failed.');
      } else if (event.type === 'final') {
        data = event.data;
      }
    });
    if (!data) throw new Error('DPN AI finished the stream without a final result.');
    responseData = data;
    pending.remove(); state.conversationId = data.conversation_id; state.pendingAttachments = []; renderPendingAttachments();
    if (data.user_message_id) attachUserMessageActions(userNode, data.user_message_id, message);
    const missionFiles = (data.evidence || []).flatMap(item => item.generated_files || []);
    const missionTrace = (data.evidence || []).map(item => ({name:item.step || 'mission step', ok:!item.error, elapsed_ms:0, arguments:{profile:item.profile}, result:item}));
    addMessage('assistant', data.message, {traces:data.traces || missionTrace, generated_files:data.generated_files || missionFiles, model:data.model, profile:data.profile || 'mission', run_id:data.run_id, mission_id:data.mission_id, verification:data.verification || data.review, project_id:els.projectSelect.value || null});
    await Promise.all([loadConversations(), loadProjects()]);
    const conversation = state.conversations.find(item => item.id === state.conversationId);
    els.activeTitle.textContent = conversation?.title || 'DPN Operation';
    if ((state.voice.autoSpeak || state.voice.handsFree || options.readReply) && state.settings?.allow_voice) {
      try { await speakText(data.message); } catch (voiceError) { setVoiceUi('error', voiceError.message); toast(voiceError.message, true); }
    } else if (state.voice.handsFree && state.settings?.allow_voice) {
      setTimeout(() => startVoiceRecording(true).catch(error => toast(error.message,true)), 500);
    } else if (options.fromVoice) {
      setVoiceUi('ready', 'Response complete');
    }
  } catch (error) {
    pending.remove();
    const recovery = error.status >= 500
      ? '\n\nOpen `runtime_logs\\errors.log` for the exact traceback, then restart DPN AI after correcting the reported model or configuration issue.'
      : '';
    addMessage('assistant', `**Operation failed:** ${error.message}${recovery}`);
    toast(error.message, true);
    loadHealth().catch(() => {});
    if (options.fromVoice) setVoiceUi('error', error.message);
  } finally {
    state.sending = false; els.sendBtn.disabled = false; els.promptInput.focus();
  }
  return responseData;
}

async function uploadFiles(fileList) {
  if (!fileList?.length) return;
  const form = new FormData(); [...fileList].forEach(file => form.append('files', file));
  try {
    toast(`Uploading ${fileList.length} file(s)â€¦`);
    const result = await api('/api/files/upload', {method:'POST', body:form});
    state.pendingAttachments = [...new Set([...state.pendingAttachments, ...result.uploaded])]; renderPendingAttachments();
    toast(`Uploaded and indexed ${result.uploaded.length} file(s).`);
  } catch (error) { toast(error.message, true); }
  els.fileInput.value = '';
}

async function showFiles() {
  const data = await api('/api/files?path=.&recursive=true');
  const entries = data.entries || [];
  openModal('Workspace Files', 'RESTRICTED LOCAL WORKSPACE', `
    <div class="toolbar"><span>${entries.length} entries</span><button class="secondary" id="reindexFiles">Reindex All</button></div>
    <div class="file-table">${entries.slice(0,1000).map(item => `<div class="file-row"><span class="file-type">${item.type === 'directory' ? 'DIR' : 'FILE'}</span><span class="file-path">${escapeHtml(item.path)}</span><span>${item.type === 'file' ? formatBytes(item.size_bytes) : ''}</span>${item.type === 'file' ? `<a href="/api/files/download/${encodeURI(item.path)}" download>Download</a>` : '<span></span>'}</div>`).join('') || '<div class="empty-state">Workspace is empty.</div>'}</div>`, true);
  $('reindexFiles').onclick = async () => { const result = await api('/api/knowledge/index?force=true', {method:'POST'}); toast(`Indexed ${result.indexed}, skipped ${result.skipped}.`); };
}

async function showMemory() {
  const data = await api('/api/memories');
  openModal('Local Memory', 'PRIVATE DURABLE CONTEXT', `
    <div class="form-inline"><input id="memoryKey" placeholder="Memory key"><input id="memoryValue" placeholder="Preference, fact, or decision"><button class="primary compact" id="addMemoryBtn">Save</button></div>
    <div id="memoryList">${(data.memories || []).map(item => `<div class="list-card"><header><strong>${escapeHtml(item.key)}</strong><button data-memory="${encodeURIComponent(item.key)}">Delete</button></header><p>${escapeHtml(item.value)}</p><small>${formatDate(item.updated_at)}</small></div>`).join('') || '<div class="empty-state">No durable memories saved.</div>'}</div>`);
  $('addMemoryBtn').onclick = async () => {
    const key = $('memoryKey').value.trim(), value = $('memoryValue').value.trim(); if (!key || !value) return toast('Enter a key and value.', true);
    await api('/api/memories', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({key,value})}); toast('Memory saved.'); await showMemory();
  };
  document.querySelectorAll('[data-memory]').forEach(button => button.onclick = async () => { await api(`/api/memories/${button.dataset.memory}`, {method:'DELETE'}); await showMemory(); });
}

function taskCard(task, projectId) {
  return `<div class="task-card priority-${task.priority}">
    <header><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(task.priority)}</span></header>
    ${task.details ? `<p>${escapeHtml(task.details)}</p>` : ''}
    <div class="task-controls"><select data-task-status="${task.id}">${['backlog','ready','running','blocked','done','failed'].map(status => `<option value="${status}" ${status === task.status ? 'selected' : ''}>${status}</option>`).join('')}</select><button data-task-delete="${task.id}">Delete</button></div>
  </div>`;
}

async function showProjects() {
  await loadProjects();
  openModal('Projects & Task Board', 'PERSISTENT OPERATIONS CONTROL', `
    <div class="form-grid project-create">
      <div class="form-inline"><input id="projectName" placeholder="Project name"><input id="projectRoot" value="." placeholder="Workspace root"><button class="primary compact" id="createProjectBtn">Create Project</button></div>
      <textarea id="projectDescription" placeholder="Mission, scope, constraints, and desired outcome"></textarea>
    </div>
    <div class="project-grid">${state.projects.map(project => `<button class="project-card" data-project-open="${project.id}"><span class="project-status ${project.status}">${project.status}</span><h4>${escapeHtml(project.name)}</h4><p>${escapeHtml(project.description || 'No description')}</p><div class="project-metrics"><span>${project.task_counts.total} tasks</span><span>${project.task_counts.done} done</span><span>${project.task_counts.blocked} blocked</span></div><small>${escapeHtml(project.root_path)}</small></button>`).join('') || '<div class="empty-state">Create your first persistent project.</div>'}</div>`, true);
  $('createProjectBtn').onclick = async () => {
    const name = $('projectName').value.trim(); if (!name) return toast('Enter a project name.', true);
    const result = await api('/api/projects', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name, description:$('projectDescription').value.trim(), root_path:$('projectRoot').value.trim() || '.'})});
    toast(`Created ${result.project.name}.`); await loadProjects(); await showProject(result.project.id);
  };
  document.querySelectorAll('[data-project-open]').forEach(button => button.onclick = () => showProject(button.dataset.projectOpen));
}

async function showProject(projectId) {
  const data = await api(`/api/projects/${projectId}`); const project = data.project; const tasks = data.tasks || [];
  const statuses = ['backlog','ready','running','blocked','done','failed'];
  openModal(project.name, 'PROJECT COMMAND BOARD', `
    <div class="project-header"><div><span class="project-status ${project.status}">${project.status}</span><p>${escapeHtml(project.description || 'No description')}</p><small>Workspace: ${escapeHtml(project.root_path)}</small></div><div class="header-actions"><button class="secondary" id="useProjectBtn">Use in Chat</button><button class="secondary" id="snapshotProjectBtn">Snapshot</button><select id="projectStatus">${['active','paused','completed','archived'].map(status => `<option ${status === project.status ? 'selected' : ''}>${status}</option>`).join('')}</select></div></div>
    <div class="form-inline task-create"><input id="taskTitle" placeholder="New task"><select id="taskPriority"><option>normal</option><option>high</option><option>critical</option><option>low</option></select><button class="primary compact" id="createTaskBtn">Add Task</button></div>
    <textarea id="taskDetails" placeholder="Task details, acceptance criteria, or constraints"></textarea>
    <div class="kanban">${statuses.map(status => `<section class="kanban-column"><header>${status.toUpperCase()} <span>${tasks.filter(task => task.status === status).length}</span></header><div>${tasks.filter(task => task.status === status).map(task => taskCard(task, projectId)).join('') || '<p class="column-empty">No tasks</p>'}</div></section>`).join('')}</div>`, true);
  $('useProjectBtn').onclick = () => { els.projectSelect.value = projectId; closeModal(); toast(`${project.name} is now active.`); };
  $('snapshotProjectBtn').onclick = async () => { const result = await api('/api/snapshots', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:`${project.name} backup`, path:project.root_path})}); toast(`Snapshot created: ${formatBytes(result.size_bytes)}`); };
  $('projectStatus').onchange = async () => { await api(`/api/projects/${projectId}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:$('projectStatus').value})}); await loadProjects(); };
  $('createTaskBtn').onclick = async () => {
    const title = $('taskTitle').value.trim(); if (!title) return toast('Enter a task title.', true);
    await api(`/api/projects/${projectId}/tasks`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title,details:$('taskDetails').value.trim(),priority:$('taskPriority').value,dependencies:[]})}); await showProject(projectId);
  };
  document.querySelectorAll('[data-task-status]').forEach(select => select.onchange = async () => { await api(`/api/tasks/${select.dataset.taskStatus}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:select.value})}); toast('Task updated.'); });
  document.querySelectorAll('[data-task-delete]').forEach(button => button.onclick = async () => { if (!confirm('Delete this task?')) return; await api(`/api/tasks/${button.dataset.taskDelete}`, {method:'DELETE'}); await showProject(projectId); });
}

async function showAutomations() {
  const data = await api('/api/automations'); const automations = data.automations || [];
  const projectOptions = '<option value="">No project</option>' + state.projects.map(project => `<option value="${project.id}">${escapeHtml(project.name)}</option>`).join('');
  const profileOptions = state.profiles.map(profile => `<option value="${profile.key}">${escapeHtml(profile.name)}</option>`).join('');
  openModal('Local Automations', 'PERSISTENT SCHEDULED OPERATIONS', `
    <div class="automation-form form-grid">
      <div class="form-inline"><input id="automationName" placeholder="Automation name"><select id="automationType"><option value="interval">Every N minutes</option><option value="daily">Daily at HH:MM</option></select><input id="automationValue" value="60" placeholder="60 or 08:00"></div>
      <textarea id="automationPrompt" placeholder="The complete operation DPN AI should execute"></textarea>
      <div class="form-inline"><select id="automationProfile">${profileOptions}</select><select id="automationProject">${projectOptions}</select><button class="primary compact" id="createAutomationBtn">Create Automation</button></div>
    </div>
    <div>${automations.map(item => `<div class="list-card automation-card"><header><div><strong>${escapeHtml(item.name)}</strong><span class="status-badge ${item.last_status || ''}">${item.enabled ? 'ENABLED' : 'DISABLED'}</span></div><div><button data-auto-run="${item.id}">Run Now</button><button data-auto-toggle="${item.id}" data-enabled="${item.enabled}">${item.enabled ? 'Disable' : 'Enable'}</button><button data-auto-delete="${item.id}">Delete</button></div></header><p>${escapeHtml(item.prompt)}</p><div class="data-line"><span>${escapeHtml(item.schedule_type)}: ${escapeHtml(item.schedule_value)}</span><span>Next: ${formatDate(item.next_run_at)}</span><span>Last: ${escapeHtml(item.last_status || 'never')}</span></div>${item.last_result ? `<details><summary>Last result</summary><pre>${escapeHtml(item.last_result)}</pre></details>` : ''}</div>`).join('') || '<div class="empty-state">No local automations configured.</div>'}</div>`, true);
  $('createAutomationBtn').onclick = async () => {
    const payload = {name:$('automationName').value.trim(), prompt:$('automationPrompt').value.trim(), schedule_type:$('automationType').value, schedule_value:$('automationValue').value.trim(), profile:$('automationProfile').value, project_id:$('automationProject').value || null, enabled:true};
    if (!payload.name || !payload.prompt) return toast('Enter a name and complete prompt.', true);
    await api('/api/automations', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}); toast('Automation created.'); await showAutomations();
  };
  document.querySelectorAll('[data-auto-run]').forEach(button => button.onclick = async () => { toast('Running automationâ€¦'); const result = await api(`/api/automations/${button.dataset.autoRun}/run`, {method:'POST'}); toast(`Automation completed in conversation ${result.conversation_id.slice(0,8)}.`); await showAutomations(); });
  document.querySelectorAll('[data-auto-toggle]').forEach(button => button.onclick = async () => { await api(`/api/automations/${button.dataset.autoToggle}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({enabled:button.dataset.enabled !== 'true'})}); await showAutomations(); });
  document.querySelectorAll('[data-auto-delete]').forEach(button => button.onclick = async () => { if (!confirm('Delete this automation?')) return; await api(`/api/automations/${button.dataset.autoDelete}`, {method:'DELETE'}); await showAutomations(); });
}

async function showRuns() {
  const [runData, auditData] = await Promise.all([api('/api/runs?limit=100'), api('/api/audit?limit=150')]);
  openModal('Runs & Audit Trail', 'ACCOUNTABLE LOCAL OPERATIONS', `
    <div class="metric-grid"><div><strong>${runData.runs.length}</strong><span>Recent runs</span></div><div><strong>${runData.runs.filter(run => run.status === 'completed').length}</strong><span>Completed</span></div><div><strong>${runData.runs.filter(run => run.status === 'failed').length}</strong><span>Failed</span></div><div><strong>${auditData.events.length}</strong><span>Audit events</span></div></div>
    <h4 class="section-title">Operation Runs</h4>
    <div>${runData.runs.map(run => `<div class="list-card run-card"><header><strong>${escapeHtml(run.objective)}</strong><span class="status-badge ${run.status}">${run.status}</span></header><div class="data-line"><span>${escapeHtml(run.profile)}</span><span>${escapeHtml(run.model)}</span><span>${formatDate(run.created_at)}</span><span>${run.traces.length} tool actions</span></div>${run.error_text ? `<p class="error-text">${escapeHtml(run.error_text)}</p>` : ''}</div>`).join('') || '<div class="empty-state">No operation runs yet.</div>'}
    <h4 class="section-title">Audit Events</h4>
    <div class="audit-list">${auditData.events.map(event => `<div class="audit-row"><span>${formatDate(event.created_at)}</span><strong>${escapeHtml(event.event_type)}</strong><p>${escapeHtml(event.summary)}</p></div>`).join('')}</div>`, true);
}

async function showSnapshots() {
  const data = await api('/api/snapshots'); const snapshots = data.snapshots || [];
  openModal('Workspace Snapshots', 'VERIFIED LOCAL RECOVERY POINTS', `
    <div class="form-inline"><input id="snapshotName" value="manual backup" placeholder="Snapshot name"><input id="snapshotPath" value="." placeholder="Workspace path"><button class="primary compact" id="createSnapshotBtn">Create Snapshot</button></div>
    <p class="help-text">Snapshots are ZIP archives with a SHA-256 manifest. Restore skips existing files unless overwrite is explicitly selected.</p>
    <div>${snapshots.map(item => `<div class="list-card snapshot-card"><header><div><strong>${escapeHtml(item.name)}</strong><span>${formatBytes(item.size_bytes)}</span></div><div><a href="/api/snapshots/${item.id}/download">Download</a><button data-snapshot-restore="${item.id}">Restore Missing</button><button data-snapshot-overwrite="${item.id}">Overwrite Restore</button></div></header><p>${escapeHtml(item.source_path)} â€¢ ${item.manifest?.file_count || 0} files</p><small>${formatDate(item.created_at)} â€¢ Archive ${item.archive_exists ? 'available' : 'missing'}</small></div>`).join('') || '<div class="empty-state">No snapshots yet.</div>'}</div>`, true);
  $('createSnapshotBtn').onclick = async () => { toast('Creating verified snapshotâ€¦'); const result = await api('/api/snapshots', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:$('snapshotName').value.trim(), path:$('snapshotPath').value.trim() || '.'})}); toast(`Snapshot created with ${result.manifest.file_count} files.`); await showSnapshots(); };
  document.querySelectorAll('[data-snapshot-restore]').forEach(button => button.onclick = async () => { if (!confirm('Restore files that are currently missing?')) return; const result = await api(`/api/snapshots/${button.dataset.snapshotRestore}/restore?overwrite=false`, {method:'POST'}); toast(`Restored ${result.restored}; skipped ${result.skipped}.`); });
  document.querySelectorAll('[data-snapshot-overwrite]').forEach(button => button.onclick = async () => { if (!confirm('Overwrite current workspace files from this snapshot? This can replace newer work.')) return; const result = await api(`/api/snapshots/${button.dataset.snapshotOverwrite}/restore?overwrite=true`, {method:'POST'}); toast(`Restored ${result.restored} files.`); });
}

async function showDiagnostics() {
  const data = await api('/api/diagnostics');
  const counts = data.database?.counts || {};
  openModal('System Diagnostics', 'LOCAL CORE HEALTH', `
    <div class="metric-grid"><div><strong>${data.ollama?.ok ? 'ONLINE' : 'OFFLINE'}</strong><span>Ollama</span></div><div><strong>${data.models?.length || 0}</strong><span>Models</span></div><div><strong>${data.plugins?.tool_count || 0}</strong><span>Tools</span></div><div><strong>${formatBytes(data.disk?.free_bytes || 0)}</strong><span>Disk free</span></div></div>
    <div class="diagnostic-grid">
      <section><h4>System</h4><p>${escapeHtml(data.system.platform)}</p><p>Python ${escapeHtml(data.system.python)} â€¢ ${escapeHtml(data.system.architecture)}</p><p>${data.cpu.logical_cores || '?'} logical CPU cores${data.cpu.percent !== undefined ? ` â€¢ ${data.cpu.percent}% active` : ''}</p><p>${data.memory.total_bytes ? `${formatBytes(data.memory.available_bytes)} available of ${formatBytes(data.memory.total_bytes)}` : escapeHtml(data.memory.status || '')}</p></section>
      <section><h4>Workspace</h4><p>${data.workspace.files} files â€¢ ${data.workspace.directories} directories</p><p>${formatBytes(data.workspace.bytes)} total indexed workspace storage</p><p>${escapeHtml(data.workspace.root)}</p></section>
      <section><h4>Database</h4>${Object.entries(counts).map(([key,value]) => `<p>${escapeHtml(key)}: <strong>${value}</strong></p>`).join('')}</section>
      <section><h4>Installed Models</h4>${(data.models || []).map(model => `<p>${escapeHtml(model.name || model.model)} â€¢ ${formatBytes(model.size || 0)}</p>`).join('') || '<p>No models detected.</p>'}</section>
    </div>
    ${data.plugins?.errors?.length ? `<h4>Plugin Errors</h4><pre>${escapeHtml(JSON.stringify(data.plugins.errors,null,2))}</pre>` : ''}`, true);
}


async function showMissions() {
  const data = await api('/api/missions?limit=200');
  openModal('Universal Missions', 'MULTI-AGENT ORCHESTRATION', `
    <div class="metric-grid"><div><strong>${data.missions.length}</strong><span>Total missions</span></div><div><strong>${data.missions.filter(x=>x.status==='completed').length}</strong><span>Completed</span></div><div><strong>${data.missions.filter(x=>x.status==='running').length}</strong><span>Running</span></div><div><strong>${data.missions.filter(x=>x.status==='failed').length}</strong><span>Failed</span></div></div>
    <div>${data.missions.map(m => `<div class="list-card"><header><strong>${escapeHtml(m.objective.slice(0,160))}</strong><span class="badge">${escapeHtml(m.status)}</span></header><p>Planner: ${escapeHtml(m.planner_model || 'default')} â€¢ Worker: ${escapeHtml(m.worker_model || 'default')} â€¢ Reviewer: ${escapeHtml(m.reviewer_model || 'default')}</p><small>${formatDate(m.created_at)} â€¢ ${escapeHtml(m.id)}</small><div class="modal-actions"><button class="secondary" data-mission-open="${m.id}">View Mission</button></div></div>`).join('') || '<div class="empty-state">No missions yet. Select Mission mode and send a complex request.</div>'}</div>`, true);
  document.querySelectorAll('[data-mission-open]').forEach(button => button.onclick = async () => {
    const result = await api(`/api/missions/${button.dataset.missionOpen}`); const m=result.mission;
    openModal('Mission Detail','CONTRACT â€¢ CHECKPOINTS â€¢ WORKERS â€¢ REVIEW QUORUM', `<div class="list-card"><h4>${escapeHtml(m.objective)}</h4><p>Status: <strong>${escapeHtml(m.status)}</strong></p><details open><summary>Goal contract</summary><pre>${escapeHtml(JSON.stringify(m.goal_contract?.contract||m.result?.contract||{},null,2))}</pre></details></div>${(m.steps||[]).map(step=>`<div class="list-card"><header><strong>${step.ordinal+1}. ${escapeHtml(step.title)}</strong><span class="badge">${escapeHtml(step.status)}</span></header><p>${escapeHtml(step.instructions)}</p><small>Attempts: ${step.attempts||0} â€¢ Dependencies: ${(step.dependencies||[]).length}</small><pre>${escapeHtml(JSON.stringify(step.result||{},null,2))}</pre></div>`).join('')}<h4>Mission Checkpoints</h4><pre>${escapeHtml(JSON.stringify(m.checkpoints||[],null,2))}</pre><h4>Independent Evaluations</h4><pre>${escapeHtml(JSON.stringify(m.evaluations||[],null,2))}</pre><h4>Consensus Review</h4><pre>${escapeHtml(JSON.stringify(m.result?.review||{},null,2))}</pre>`, true);
  });
}


async function showJobs() {
  const data = await api('/api/jobs?limit=200'); const jobs=data.jobs||[];
  const projectOptions='<option value="">No project</option>'+state.projects.map(p=>`<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
  openModal('Autonomous Job Queue','PERSISTENT â€¢ RESUMABLE â€¢ RESTART-SAFE', `
    <div class="metric-grid"><div><strong>${jobs.length}</strong><span>Total jobs</span></div><div><strong>${jobs.filter(x=>x.status==='queued').length}</strong><span>Queued</span></div><div><strong>${jobs.filter(x=>x.status==='running').length}</strong><span>Running</span></div><div><strong>${jobs.filter(x=>x.status==='completed').length}</strong><span>Completed</span></div></div>
    <div class="list-card"><h4>Queue a new autonomous operation</h4><div class="form-inline"><select id="jobKind"><option value="mission">Verified mission</option><option value="direct">Direct operation</option></select><select id="jobProject">${projectOptions}</select></div><textarea id="jobPrompt" rows="5" placeholder="Describe the complete goal, deliverables, constraints, and success criteria."></textarea><div class="modal-actions"><button class="primary compact" id="queueJobBtn">Queue Operation</button><button class="secondary" id="refreshJobsBtn">Refresh</button></div></div>
    <div>${jobs.map(j=>`<div class="list-card"><header><div><strong>${escapeHtml(j.kind.toUpperCase())}</strong><span class="badge">${escapeHtml(j.status)}</span></div><div>${['queued','running'].includes(j.status)?`<button data-job-cancel="${j.id}">Cancel</button>`:''}${['failed','cancelled','completed'].includes(j.status)?`<button data-job-retry="${j.id}">Retry</button>`:''}</div></header><p>${escapeHtml(String(j.payload?.objective||j.payload?.message||j.payload?.workflow_id||'').slice(0,500))}</p><div class="data-line"><span>${formatDate(j.created_at)}</span><span>${escapeHtml(j.progress?.stage||'queued')}</span></div>${j.error_text?`<pre>${escapeHtml(j.error_text)}</pre>`:''}<details><summary>Result and payload</summary><pre>${escapeHtml(JSON.stringify({progress:j.progress,result:j.result,payload:j.payload},null,2))}</pre></details></div>`).join('')||'<div class="empty-state">No background jobs yet.</div>'}</div>`, true);
  $('queueJobBtn').onclick=async()=>{const kind=$('jobKind').value,prompt=$('jobPrompt').value.trim(),project_id=$('jobProject').value||null;if(!prompt)return toast('Enter a complete goal.',true);const payload=kind==='mission'?{objective:prompt,project_id,profile:'auto'}:{message:prompt,project_id,profile:'auto'};await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,payload})});toast('Autonomous job queued.');await showJobs();};
  $('refreshJobsBtn').onclick=()=>showJobs();
  document.querySelectorAll('[data-job-cancel]').forEach(b=>b.onclick=async()=>{await api(`/api/jobs/${b.dataset.jobCancel}/cancel`,{method:'POST'});await showJobs();});
  document.querySelectorAll('[data-job-retry]').forEach(b=>b.onclick=async()=>{await api(`/api/jobs/${b.dataset.jobRetry}/retry`,{method:'POST'});toast('Job requeued.');await showJobs();});
}

async function showGraph(query='') {
  const [stats,result]=await Promise.all([api('/api/graph/stats'),query?api(`/api/graph/search?q=${encodeURIComponent(query)}&limit=100`):Promise.resolve({nodes:[]})]);
  openModal('Knowledge Graph','PROVENANCE-BACKED LONG-TERM UNDERSTANDING', `
    <div class="metric-grid"><div><strong>${stats.nodes||0}</strong><span>Nodes</span></div><div><strong>${stats.edges||0}</strong><span>Relationships</span></div><div><strong>${(stats.types||[]).length}</strong><span>Entity types</span></div><div><strong>${(result.nodes||[]).length}</strong><span>Search matches</span></div></div>
    <div class="form-inline"><input id="graphQuery" value="${escapeHtml(query)}" placeholder="Search entities, systems, people, decisionsâ€¦"><button class="secondary" id="graphSearchBtn">Search</button></div>
    <div class="list-card"><h4>Remember a provenance-backed fact</h4><div class="form-inline"><input id="factSubject" placeholder="Subject"><input id="factRelation" placeholder="Relation, e.g. uses"><input id="factObject" placeholder="Object"></div><div class="form-inline"><input id="factSource" value="operator" placeholder="Source"><input id="factConfidence" type="number" min="0" max="1" step="0.05" value="0.9"><button class="primary compact" id="saveFactBtn">Save Fact</button></div></div>
    <div>${(result.nodes||[]).map(n=>`<div class="list-card"><header><strong>${escapeHtml(n.label)}</strong><span class="badge">${escapeHtml(n.node_type)}</span></header><p>Confidence ${Number(n.confidence||0).toFixed(2)} â€¢ Source: ${escapeHtml(n.source||'unknown')}</p><small>${escapeHtml(n.id)}</small><div class="modal-actions"><button class="secondary" data-graph-neighborhood="${n.id}">View Relationships</button></div></div>`).join('')||'<div class="empty-state">Search the graph or add a fact. Relevant nodes are automatically recalled into operations.</div>'}</div>`, true);
  $('graphSearchBtn').onclick=()=>showGraph($('graphQuery').value.trim());
  $('saveFactBtn').onclick=async()=>{const payload={subject:$('factSubject').value.trim(),relation:$('factRelation').value.trim(),object_value:$('factObject').value.trim(),source:$('factSource').value.trim()||'operator',confidence:Number($('factConfidence').value),project_id:els.projectSelect.value||null};if(!payload.subject||!payload.relation||!payload.object_value)return toast('Enter a subject, relation, and object.',true);await api('/api/graph/facts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});toast('Fact added to the local graph.');await showGraph(payload.subject);};
  document.querySelectorAll('[data-graph-neighborhood]').forEach(b=>b.onclick=async()=>{const r=await api(`/api/graph/nodes/${b.dataset.graphNeighborhood}/neighborhood?depth=2&limit=200`);openModal('Graph Neighborhood','TRACEABLE RELATIONSHIPS',`<pre>${escapeHtml(JSON.stringify(r.graph,null,2))}</pre>`,true);});
}

async function showSandbox() {
  const status=await api('/api/sandbox/status');
  openModal('Sandbox Lab','BOUNDED CODE EXECUTION', `
    <div class="metric-grid"><div><strong>${status.docker_available?'READY':'OFFLINE'}</strong><span>Docker isolation</span></div><div><strong>${status.host_fallback_enabled?'ENABLED':'DISABLED'}</strong><span>Host fallback</span></div><div><strong>NO NETWORK</strong><span>Default policy</span></div><div><strong>PYTHON</strong><span>Runtime</span></div></div>
    <p class="help-text">Docker mode uses a read-only root, dropped capabilities, PID/CPU/memory limits, and no network by default. Host fallback is not a security boundary.</p>
    <textarea id="sandboxCode" rows="14" spellcheck="false">print("DPN AI v5 sandbox ready")</textarea>
    <div class="form-inline"><input id="sandboxTimeout" type="number" min="1" max="300" value="30"><input id="sandboxMemory" type="number" min="64" max="4096" value="512"><label class="voice-toggle"><input id="sandboxHost" type="checkbox"><span>Host fallback</span></label><button class="primary compact" id="runSandboxBtn">Run Python</button></div><pre id="sandboxOutput">No execution yet.</pre>`, true);
  $('runSandboxBtn').onclick=async()=>{const output=$('sandboxOutput');output.textContent='Executingâ€¦';try{const r=await api('/api/sandbox/python',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('sandboxCode').value,timeout_seconds:Number($('sandboxTimeout').value),memory_mb:Number($('sandboxMemory').value),network:false,use_host_fallback:$('sandboxHost').checked})});output.textContent=JSON.stringify(r,null,2);}catch(error){output.textContent=error.message;}};
}

async function showCapabilityForge() {
  const data=await api('/api/capability-forge');
  openModal('Capability Forge','STAGE â€¢ INSPECT â€¢ VALIDATE â€¢ PROMOTE â€¢ ROLLBACK', `
    <div class="metric-grid"><div><strong>${(data.active||[]).length}</strong><span>Active plugins</span></div><div><strong>${(data.staged||[]).length}</strong><span>Staged</span></div><div><strong>AST + COMPILE</strong><span>Validation</span></div><div><strong>APPROVAL</strong><span>Promotion boundary</span></div></div>
    <div class="list-card"><h4>Stage a local capability</h4><input id="forgeId" placeholder="capability-id"><input id="forgeDescription" placeholder="Purpose and trust assumptions"><textarea id="forgeCode" rows="13" spellcheck="false">def register(registry):\n    registry.register(\n        "my_capability",\n        "Describe exactly what this tool does.",\n        {"type": "object", "properties": {}},\n        lambda: {"ok": True, "message": "Capability ready"},\n    )</textarea><div class="modal-actions"><button class="primary compact" id="stageCapabilityBtn">Stage Only</button></div></div>
    <h4>Staged capabilities</h4>${(data.staged||[]).map(c=>`<div class="list-card"><header><strong>${escapeHtml(c.id)}</strong><span class="badge">${c.validation?.valid?'VALID':c.validation?'REJECTED':'UNVALIDATED'}</span></header><p>${escapeHtml(c.description||'')}</p><small>SHA-256 ${escapeHtml(c.sha256||'')}</small>${c.validation?`<pre>${escapeHtml(JSON.stringify(c.validation,null,2))}</pre>`:''}<div class="modal-actions"><button class="secondary" data-forge-validate="${c.id}">Validate</button><button class="primary compact" data-forge-promote="${c.id}">Promote</button></div></div>`).join('')||'<div class="empty-state">No staged capabilities.</div>'}<h4>Active plugins</h4><div class="capability-strip">${(data.active||[]).map(name=>`<span>${escapeHtml(name)}</span>`).join('')||'<span>No custom plugins active</span>'}</div><h4>Rollback backups</h4>${(data.backups||[]).map(item=>`<div class="list-card"><header><strong>${escapeHtml(item.name)}</strong><button data-forge-rollback="${escapeHtml(item.name.split('-')[0])}" data-backup-name="${escapeHtml(item.name)}">Restore Backup</button></header><small>${formatBytes(item.size_bytes)} â€¢ ${formatDate(new Date(item.modified_at*1000).toISOString())}</small></div>`).join('')||'<div class="empty-state">No plugin rollback backups exist yet.</div>'}`, true);
  $('stageCapabilityBtn').onclick=async()=>{const payload={capability_id:$('forgeId').value.trim(),description:$('forgeDescription').value.trim(),code:$('forgeCode').value,overwrite:false};if(!payload.capability_id)return toast('Enter a capability id.',true);await api('/api/capability-forge/stage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});toast('Capability staged but not activated.');await showCapabilityForge();};
  document.querySelectorAll('[data-forge-validate]').forEach(b=>b.onclick=async()=>{const r=await api(`/api/capability-forge/${b.dataset.forgeValidate}/validate`,{method:'POST'});toast(r.valid?'Capability validation passed.':'Capability validation rejected.',!r.valid);await showCapabilityForge();});
  document.querySelectorAll('[data-forge-promote]').forEach(b=>b.onclick=async()=>{const r=await api(`/api/capability-forge/${b.dataset.forgePromote}/promote`,{method:'POST'});if(r.approval_required)toast('Promotion is waiting in the Approval Inbox.');else toast(r.ok?'Capability promoted; restart DPN AI to load it.':r.error,!r.ok);});
  document.querySelectorAll('[data-forge-rollback]').forEach(b=>b.onclick=async()=>{if(!confirm('Restore this preserved plugin version? A restart will be required.'))return;const r=await api(`/api/capability-forge/${b.dataset.forgeRollback}/rollback?backup_name=${encodeURIComponent(b.dataset.backupName)}`,{method:'POST'});if(r.approval_required)toast('Rollback is waiting in the Approval Inbox.');else toast(r.ok?'Plugin backup restored; restart DPN AI.':r.error,!r.ok);});
}

async function showMCP() {
  const [status,data]=await Promise.all([api('/api/mcp/status'),api('/api/mcp/servers')]); const servers=data.servers||[];
  openModal('MCP Tool Bridge','DENY-BY-DEFAULT STANDARD TOOL INTEGRATION', `
    <div class="metric-grid"><div><strong>${status.available?'READY':'NOT INSTALLED'}</strong><span>Python MCP SDK</span></div><div><strong>${servers.length}</strong><span>Configured servers</span></div><div><strong>ALLOWLIST</strong><span>Tool policy</span></div><div><strong>APPROVAL</strong><span>External calls</span></div></div>
    <p class="help-text">New servers start with no callable tools. Discover tools, select only trusted names, then save the allowlist. Sensitive environment values must reference encrypted secrets.</p>
    <div class="list-card"><h4>Add MCP server</h4><div class="form-inline"><input id="mcpName" placeholder="Server name"><select id="mcpTransport"><option value="stdio">Local stdio</option><option value="http">Streamable HTTP</option></select></div><input id="mcpCommand" placeholder="stdio executable, e.g. python"><input id="mcpArgs" placeholder='stdio arguments JSON, e.g. ["server.py"]'><input id="mcpUrl" placeholder="HTTP URL"><textarea id="mcpEnv" rows="3" placeholder='Environment JSON. Secrets: {"API_TOKEN":"{{secret:MCP_TOKEN}}"}'></textarea><button class="primary compact" id="createMcpBtn">Add Disabled-by-Allowlist Server</button></div>
    ${servers.map(server=>`<div class="list-card"><header><div><strong>${escapeHtml(server.name)}</strong><span class="badge">${server.enabled?'ENABLED':'DISABLED'}</span></div><div><button data-mcp-discover="${server.id}">Discover</button><button data-mcp-save="${server.id}">Save Allowlist</button><button data-mcp-delete="${server.id}">Delete</button></div></header><p>${escapeHtml(server.transport)} â€¢ ${escapeHtml(server.config?.command||server.config?.url||'')}</p><div class="file-table">${(server.tools||[]).map(tool=>`<label class="toggle-row"><div><strong>${escapeHtml(tool.name||'unnamed')}</strong><small>${escapeHtml(tool.description||'')}</small></div><input type="checkbox" data-mcp-tool="${server.id}" value="${escapeHtml(tool.name||'')}" ${(server.allowed_tools||[]).includes(tool.name)?'checked':''}></label>`).join('')||'<small>No tools cached. Use Discover.</small>'}</div></div>`).join('')||'<div class="empty-state">No MCP servers configured.</div>'}`, true);
  $('createMcpBtn').onclick=async()=>{let args=[],env={};try{args=JSON.parse($('mcpArgs').value||'[]');env=JSON.parse($('mcpEnv').value||'{}');}catch(error){return toast('Arguments and environment must be valid JSON.',true);}const payload={name:$('mcpName').value.trim(),transport:$('mcpTransport').value,command:$('mcpCommand').value.trim()||null,args,url:$('mcpUrl').value.trim()||null,env,allowed_tools:[],enabled:true};await api('/api/mcp/servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});toast('MCP server configured with an empty allowlist.');await showMCP();};
  document.querySelectorAll('[data-mcp-discover]').forEach(b=>b.onclick=async()=>{const r=await api(`/api/mcp/servers/${b.dataset.mcpDiscover}/discover`,{method:'POST'});if(r.approval_required)toast('Discovery is waiting in the Approval Inbox.');else toast(r.ok?`Discovered ${r.tool_count} tools.`:r.error,!r.ok);if(r.ok)await showMCP();});
  document.querySelectorAll('[data-mcp-save]').forEach(b=>b.onclick=async()=>{const allowed=[...document.querySelectorAll(`[data-mcp-tool="${b.dataset.mcpSave}"]:checked`)].map(x=>x.value);await api(`/api/mcp/servers/${b.dataset.mcpSave}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({allowed_tools:allowed})});toast(`Saved ${allowed.length} allow-listed tools.`);await showMCP();});
  document.querySelectorAll('[data-mcp-delete]').forEach(b=>b.onclick=async()=>{if(!confirm('Delete this MCP server configuration and call audit records?'))return;await api(`/api/mcp/servers/${b.dataset.mcpDelete}`,{method:'DELETE'});await showMCP();});
}

async function showApprovals() {
  const data = await api('/api/approvals?status=pending');
  openModal('Approval Inbox','HUMAN CONTROL BOUNDARY', `<div class="toolbar"><span>${data.approvals.length} pending decision(s)</span><small>External, destructive, and desktop actions pause here in Standard mode.</small></div>${data.approvals.map(a=>`<div class="list-card"><header><strong>${escapeHtml(a.tool_name)}</strong><span class="badge">${escapeHtml(a.risk)}</span></header><p>${escapeHtml(a.reason)}</p><pre>${escapeHtml(JSON.stringify(a.arguments,null,2))}</pre><div class="modal-actions"><button class="primary compact" data-approve="${a.id}">Approve & Execute</button><button class="danger" data-deny="${a.id}">Deny</button></div></div>`).join('') || '<div class="empty-state">No actions are awaiting approval.</div>'}`, true);
  document.querySelectorAll('[data-approve]').forEach(button=>button.onclick=async()=>{ const r=await api(`/api/approvals/${button.dataset.approve}/decision`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:'approved'})}); toast(r.execution?.ok?'Approved action completed.':'Approved action failed.',!r.execution?.ok); await showApprovals(); });
  document.querySelectorAll('[data-deny]').forEach(button=>button.onclick=async()=>{ await api(`/api/approvals/${button.dataset.deny}/decision`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:'denied'})}); await showApprovals(); });
}

async function showSkills() {
  await loadSkills(); const workflows=(await api('/api/workflows')).workflows||[];
  openModal('Skills & Workflows','REUSABLE OPERATING INTELLIGENCE', `<h4>Activated skills for chat</h4><div class="file-table">${state.skills.map(skill=>`<label class="toggle-row"><div><strong>${escapeHtml(skill.name||skill.id)}</strong><small>${escapeHtml(skill.description||'')}</small></div><input type="checkbox" data-skill-select="${skill.id}" ${state.selectedSkills.includes(skill.id)?'checked':''}></label>`).join('')||'<div class="empty-state">No skill packs installed.</div>'}</div><h4>Reusable workflows</h4>${workflows.map(w=>`<div class="list-card"><header><strong>${escapeHtml(w.name)}</strong><span>${w.steps.length} steps</span></header><p>${escapeHtml(w.description)}</p><button class="secondary" data-workflow-run="${w.id}">Run Workflow</button></div>`).join('')||'<div class="empty-state">No workflows created. The API and agent tools can create them.</div>'}`, true);
  document.querySelectorAll('[data-skill-select]').forEach(input=>input.onchange=()=>{ state.selectedSkills=[...document.querySelectorAll('[data-skill-select]:checked')].map(x=>x.dataset.skillSelect); });
  document.querySelectorAll('[data-workflow-run]').forEach(button=>button.onclick=async()=>{ const result=await api(`/api/workflows/${button.dataset.workflowRun}/run`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs:{}})}); toast(result.ok?'Workflow completed.':result.error,!result.ok); });
}
async function showConnectors() {
  const connectors=(await api('/api/connectors')).connectors||[]; const secrets=(await api('/api/secrets')).secrets||[];
  openModal('Connectors & Secrets','ENCRYPTED LOCAL INTEGRATION HUB', `<h4>Connectors</h4>${connectors.map(c=>`<div class="list-card"><header><strong>${escapeHtml(c.name)}</strong><span>${escapeHtml(c.kind)}</span></header><p>${escapeHtml(c.config.base_url||'')}</p><small>${(c.config.allowed_methods||[]).join(', ')}</small></div>`).join('')||'<div class="empty-state">No connectors configured.</div>'}<h4>Encrypted secret names</h4><div class="capability-strip">${secrets.map(name=>`<span>${escapeHtml(name)}</span>`).join('')||'<span>No secrets stored</span>'}</div><div class="form-inline"><input id="secretName" placeholder="Secret name"><input id="secretValue" type="password" placeholder="Secret value"><button class="primary compact" id="saveSecretBtn">Encrypt & Save</button></div><small>Use {{secret:NAME}} inside connector headers. Secret values are never shown again.</small>`, true);
  $('saveSecretBtn').onclick=async()=>{const name=$('secretName').value.trim(),value=$('secretValue').value;if(!name||!value)return toast('Enter a name and value.',true);await api('/api/secrets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,value})});toast('Secret encrypted and stored.');await showConnectors();};
}

async function showSettings() {
  const current = await api('/api/settings'); state.settings = current;
  const modelOptions = [...new Set([current.model, ...state.models.map(item => item.name || item.model)])].filter(Boolean).map(name => `<option value="${escapeHtml(name)}" ${name === current.model ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('');
  openModal('System Settings', 'DPN AI CONTROL POLICY', `
    <div class="form-grid">
      <div class="field"><label>Intelligence policy</label><select id="settingIntelligence"><option value="maximum">Maximum â€” automatically use strongest installed model</option><option value="balanced">Balanced â€” strong model with adaptive reasoning</option><option value="manual">Manual â€” use selected model exactly</option></select><small>Maximum is the default. DPN AI still disables long reasoning for greetings and uses adaptive verification to keep responses faster.</small></div>
      <div class="toggle-row"><div><strong>Keep strongest model loaded</strong><small>Warms the selected intelligence model in the background and keeps it resident in Ollama for faster first responses. This uses RAM or VRAM while DPN AI is open.</small></div><input class="toggle" id="settingKeepLoaded" type="checkbox" ${current.keep_model_loaded !== false ? 'checked' : ''}></div>
      <div class="field"><label>Default/fallback model</label><select id="settingModel">${modelOptions}</select><small>Used as a fallback if automatic model discovery is unavailable. Prefix a model with compatible: to force the compatible provider.</small></div>
      <div class="field"><label>Default model provider</label><select id="settingProvider"><option value="ollama">Ollama â€” local private models</option><option value="compatible">OpenAI-compatible endpoint</option></select></div>
      <div class="field"><label>OpenAI-compatible API base URL</label><input id="settingCompatibleUrl" value="${escapeHtml(current.compatible_api_url || '')}" placeholder="Example: http://127.0.0.1:1234"><small>Supports local servers such as LM Studio, vLLM, llama.cpp, and LocalAI. DPN AI appends /v1 endpoints.</small></div>
      <div class="field"><label>Encrypted API key secret name</label><input id="settingCompatibleSecret" value="${escapeHtml(current.compatible_api_secret || 'MODEL_PROVIDER_KEY')}" placeholder="MODEL_PROVIDER_KEY"><small>Store the matching value in Connectors & Secrets. The key itself is never displayed here.</small></div>
      <div class="toggle-row"><div><strong>External model endpoints</strong><small>Allow a compatible endpoint outside the local/private network. Keep disabled for a fully local system.</small></div><input class="toggle" id="settingExternalModels" type="checkbox" ${current.allow_external_models ? 'checked' : ''}></div>
      <div class="field"><label>Planner model override</label><input id="settingPlannerModel" value="${escapeHtml(current.planner_model || '')}" placeholder="Blank uses worker/default"></div>
      <div class="field"><label>Worker model override</label><input id="settingWorkerModel" value="${escapeHtml(current.worker_model || '')}" placeholder="Blank uses default"></div>
      <div class="field"><label>Independent reviewer model</label><input id="settingReviewerModel" value="${escapeHtml(current.reviewer_model || '')}" placeholder="Blank uses worker/default"></div>
      <div class="field"><label>Embedding model</label><input id="settingEmbeddingModel" value="${escapeHtml(current.embedding_model || 'nomic-embed-text')}"></div>
      <div class="field"><label>Profile-specific model routes (JSON)</label><textarea id="settingModelRoutes" rows="4" placeholder='{"software":"model-name","research":"model-name"}'>${escapeHtml(JSON.stringify(current.model_routes || {}, null, 2))}</textarea></div>
      <div class="field"><label>Reasoning level</label><select id="settingThink"><option value="false">Off / fastest</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></div>
      <div class="field"><label>Approval mode</label><select id="settingApproval"><option value="safe">Safe â€” blocks execution and deletion</option><option value="standard">Standard â€” execution allowed, destructive tools blocked</option><option value="autonomous">Autonomous â€” all enabled tools available</option></select><small>File operations always remain confined to the workspace.</small></div>
      <div class="toggle-row"><div><strong>Internet research</strong><small>Public web search and page reading.</small></div><input class="toggle" id="settingWeb" type="checkbox" ${current.allow_web ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>Local image generation</strong><small>Submit the configured workflow to local ComfyUI.</small></div><input class="toggle" id="settingImages" type="checkbox" ${current.allow_images ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>Command execution</strong><small>Restricted development commands inside the workspace.</small></div><input class="toggle" id="settingCommands" type="checkbox" ${current.allow_commands ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>Scheduled automations</strong><small>Run persisted local operations while DPN AI is open.</small></div><input class="toggle" id="settingAutomations" type="checkbox" ${current.allow_automations ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>Browser automation</strong><small>Optional Playwright-controlled browser operations. Side effects require approval.</small></div><input class="toggle" id="settingBrowser" type="checkbox" ${current.allow_browser ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>Desktop automation</strong><small>Optional keyboard and mouse control. High risk and disabled by default.</small></div><input class="toggle" id="settingDesktop" type="checkbox" ${current.allow_desktop ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>Offline voice tools</strong><small>Local speech recognition and text-to-speech adapters.</small></div><input class="toggle" id="settingVoice" type="checkbox" ${current.allow_voice ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>Connector hub</strong><small>Allow-listed external APIs using encrypted local secrets.</small></div><input class="toggle" id="settingConnectors" type="checkbox" ${current.allow_connectors ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>MCP tool bridge</strong><small>Connect approved local or allow-listed MCP servers. External calls still require approval in Standard mode.</small></div><input class="toggle" id="settingMcp" type="checkbox" ${current.allow_mcp ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>Capability Forge</strong><small>Allow staging and validating new local plugins. Promotion is approval-controlled and restart-gated.</small></div><input class="toggle" id="settingSelfImprovement" type="checkbox" ${current.allow_self_improvement ? 'checked' : ''}></div>
      <div class="toggle-row"><div><strong>Host sandbox fallback</strong><small>Use only when Docker is unavailable. This is a subprocess limit, not a security isolation boundary.</small></div><input class="toggle" id="settingHostSandbox" type="checkbox" ${current.allow_host_sandbox ? 'checked' : ''}></div>
      <div class="field"><label>Maximum tool calls per operation</label><input id="settingToolCalls" type="number" min="1" max="1000" value="${current.max_tool_calls || 80}"></div>
      <div class="field"><label>Maximum operation runtime (seconds)</label><input id="settingRunSeconds" type="number" min="30" max="86400" value="${current.max_run_seconds || 1800}"></div>
      <div class="field"><label>Command timeout (seconds)</label><input id="settingTimeout" type="number" min="5" max="900" value="${current.command_timeout_seconds}"></div>
      <div class="field"><label>ComfyUI API workflow</label><div class="form-inline"><input id="comfyWorkflowFile" type="file" accept=".json,application/json"><button class="secondary" id="uploadWorkflowBtn">Upload Workflow</button></div></div>
      <div class="field"><label>Pull another Ollama model</label><div class="form-inline"><input id="pullModelName" placeholder="Example: qwen3.5:27b"><button class="secondary" id="pullModelBtn">Pull Model</button></div></div>
    </div>
    <div class="modal-actions"><button class="primary compact" id="saveSettingsBtn">Save Control Policy</button></div>`);
  $('settingThink').value = String(current.think_level); $('settingApproval').value = current.approval_mode || 'standard'; $('settingProvider').value = current.default_provider || 'ollama'; $('settingIntelligence').value = current.intelligence_mode || 'maximum';
  $('saveSettingsBtn').onclick = async () => {
    const thinkRaw = $('settingThink').value;
    let routes={}; try { routes=JSON.parse($('settingModelRoutes').value||'{}'); } catch(error) { return toast('Model routes must be valid JSON.',true); } const payload = {model:$('settingModel').value, intelligence_mode:$('settingIntelligence').value, keep_model_loaded:$('settingKeepLoaded').checked, default_provider:$('settingProvider').value, compatible_api_url:$('settingCompatibleUrl').value.trim(), compatible_api_secret:$('settingCompatibleSecret').value.trim() || 'MODEL_PROVIDER_KEY', allow_external_models:$('settingExternalModels').checked, planner_model:$('settingPlannerModel').value.trim(), worker_model:$('settingWorkerModel').value.trim(), reviewer_model:$('settingReviewerModel').value.trim(), embedding_model:$('settingEmbeddingModel').value.trim(), model_routes:routes, think_level:thinkRaw === 'false' ? false : thinkRaw, approval_mode:$('settingApproval').value, allow_web:$('settingWeb').checked, allow_images:$('settingImages').checked, allow_commands:$('settingCommands').checked, allow_automations:$('settingAutomations').checked, allow_browser:$('settingBrowser').checked, allow_desktop:$('settingDesktop').checked, allow_voice:$('settingVoice').checked, allow_connectors:$('settingConnectors').checked, allow_mcp:$('settingMcp').checked, allow_self_improvement:$('settingSelfImprovement').checked, allow_host_sandbox:$('settingHostSandbox').checked, max_tool_calls:Number($('settingToolCalls').value), max_run_seconds:Number($('settingRunSeconds').value), command_timeout_seconds:Number($('settingTimeout').value)};
    state.settings = await api('/api/settings', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}); updatePermissions(); await Promise.all([loadModels(),loadVoiceProfiles()]); if (payload.keep_model_loaded) api('/api/models/warm',{method:'POST'}).then(()=>loadHealth()).catch(()=>{}); closeModal(); toast('DPN AI control policy saved.');
  };
  $('uploadWorkflowBtn').onclick = async () => { const file = $('comfyWorkflowFile').files[0]; if (!file) return toast('Choose a workflow JSON file.', true); const form = new FormData(); form.append('file',file); const result = await api('/api/images/workflow',{method:'POST',body:form}); toast(`ComfyUI workflow loaded with ${result.nodes} nodes.`); };
  $('pullModelBtn').onclick = async () => { const model = $('pullModelName').value.trim(); if (!model) return; toast(`Pulling ${model}. This may take a while.`); await api('/api/models/pull',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model})}); await loadModels(); toast(`${model} is installed.`); };
}

if (els.newChatBtn) els.newChatBtn.onclick = newConversation;
if (els.refreshChatsBtn) els.refreshChatsBtn.onclick = () => loadConversations().catch(error => toast(error.message,true));
if (els.menuBtn) els.menuBtn.onclick = () => els.sidebar.classList.toggle('open');
if (els.closeModalBtn) els.closeModalBtn.onclick = closeModal;
if (els.modalBackdrop) els.modalBackdrop.onclick = (event) => { if (event.target === els.modalBackdrop) closeModal(); };
if (els.fileInput) els.fileInput.onchange = () => uploadFiles(els.fileInput.files);
if (els.filesBtn) els.filesBtn.onclick = () => showFiles().catch(error => toast(error.message,true));
if (els.memoryBtn) els.memoryBtn.onclick = () => showMemory().catch(error => toast(error.message,true));
if (els.skillsBtn) els.skillsBtn.onclick = () => showSkills().catch(error => toast(error.message,true));
if (els.connectorsBtn) els.connectorsBtn.onclick = () => showConnectors().catch(error => toast(error.message,true));
if (els.missionsBtn) els.missionsBtn.onclick = () => showMissions().catch(error => toast(error.message,true));
if (els.jobsBtn) els.jobsBtn.onclick = () => showJobs().catch(error => toast(error.message,true));
if (els.graphBtn) els.graphBtn.onclick = () => showGraph().catch(error => toast(error.message,true));
if (els.sandboxBtn) els.sandboxBtn.onclick = () => showSandbox().catch(error => toast(error.message,true));
if (els.capabilityForgeBtn) els.capabilityForgeBtn.onclick = () => showCapabilityForge().catch(error => toast(error.message,true));
if (els.mcpBtn) els.mcpBtn.onclick = () => showMCP().catch(error => toast(error.message,true));
if (els.approvalsBtn) els.approvalsBtn.onclick = () => showApprovals().catch(error => toast(error.message,true));
if (els.projectsBtn) els.projectsBtn.onclick = () => showProjects().catch(error => toast(error.message,true));
if (els.automationsBtn) els.automationsBtn.onclick = () => showAutomations().catch(error => toast(error.message,true));
if (els.runsBtn) els.runsBtn.onclick = () => showRuns().catch(error => toast(error.message,true));
if (els.snapshotsBtn) els.snapshotsBtn.onclick = () => showSnapshots().catch(error => toast(error.message,true));
if (els.diagnosticsBtn) els.diagnosticsBtn.onclick = () => showDiagnostics().catch(error => toast(error.message,true));
if (els.settingsBtn) els.settingsBtn.onclick = () => showSettings().catch(error => toast(error.message,true));
if (els.voiceBtn) els.voiceBtn.onclick = () => showVoiceCenter().catch(error => toast(error.message,true));
if (els.voiceSettingsBtn) els.voiceSettingsBtn.onclick = () => showVoiceCenter().catch(error => toast(error.message,true));
if (els.micBtn) els.micBtn.onclick = () => toggleVoiceRecording().catch(error => { setVoiceUi('error',error.message); toast(error.message,true); });
if (els.stopVoiceBtn) els.stopVoiceBtn.onclick = () => { stopVoiceRecording(); stopVoicePlayback(); };
if (els.voiceSelect) els.voiceSelect.onchange = event => { state.voice.selected=event.target.value; localStorage.setItem('dpnVoiceProfile',state.voice.selected); setVoiceUi('ready',`${selectedVoiceProfile().name} selected`); };
if (els.autoSpeakToggle) els.autoSpeakToggle.onchange = event => { state.voice.autoSpeak=event.target.checked; localStorage.setItem('dpnAutoSpeak',String(state.voice.autoSpeak)); };
if (els.voiceReviewToggle) els.voiceReviewToggle.onchange = event => { state.voice.reviewBeforeSend=event.target.checked; localStorage.setItem('dpnVoiceReview',String(state.voice.reviewBeforeSend)); };
if (els.handsFreeToggle) els.handsFreeToggle.onchange = event => {
  state.voice.handsFree=event.target.checked; localStorage.setItem('dpnHandsFree',String(state.voice.handsFree));
  if (state.voice.handsFree) { state.voice.autoSpeak=true; els.autoSpeakToggle.checked=true; localStorage.setItem('dpnAutoSpeak','true'); startVoiceRecording(true).catch(error=>{ state.voice.handsFree=false; els.handsFreeToggle.checked=false; localStorage.setItem('dpnHandsFree','false'); setVoiceUi('error',error.message); toast(error.message,true); }); }
  else { stopVoiceRecording(); stopVoicePlayback(); }
};
if (els.indexBtn) els.indexBtn.onclick = async () => { try { toast('Reindexing workspaceâ€¦'); const result = await api('/api/knowledge/index?force=true',{method:'POST'}); toast(`Indexed ${result.indexed} files into ${result.chunks} chunks.`); } catch(error) { toast(error.message,true); } };
if (els.sendBtn) els.sendBtn.onclick = () => sendMessage();
if (els.cancelEditBtn) els.cancelEditBtn.onclick = () => cancelMessageEdit(true);
if (els.promptInput) els.promptInput.oninput = autoresize;
if (els.promptInput) els.promptInput.onkeydown = (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } };
document.querySelectorAll('.starter').forEach(button => button.onclick = () => { els.profileSelect.value = button.dataset.profile || 'auto'; sendMessage(button.dataset.prompt); });

let dragDepth = 0;
window.addEventListener('dragenter', event => { event.preventDefault(); dragDepth += 1; document.body.classList.add('dragging'); });
window.addEventListener('dragover', event => event.preventDefault());
window.addEventListener('dragleave', event => { event.preventDefault(); dragDepth -= 1; if (dragDepth <= 0) { dragDepth = 0; document.body.classList.remove('dragging'); } });
window.addEventListener('drop', event => { event.preventDefault(); dragDepth = 0; document.body.classList.remove('dragging'); uploadFiles(event.dataTransfer.files); });
window.addEventListener('keydown', event => {
  if (event.ctrlKey && event.code === 'Space') { event.preventDefault(); toggleVoiceRecording().catch(error=>toast(error.message,true)); return; }
  if (event.key === 'Escape') { closeModal(); stopVoicePlayback(); if (state.voice.recording) stopVoiceRecording(); if (state.editingMessageId) cancelMessageEdit(false); }
});

function syncViewportHeight() {
  const height = window.visualViewport?.height || window.innerHeight;
  document.documentElement.style.setProperty('--dpn-viewport-height', `${Math.max(320, height)}px`);
}
syncViewportHeight();
window.addEventListener('resize', syncViewportHeight, {passive:true});
window.visualViewport?.addEventListener('resize', syncViewportHeight, {passive:true});

function validateInterfaceShell() {
  const required = ['sidebar','chat','messages','promptInput','sendBtn','modalBackdrop','modalBody','messageTemplate'];
  const missing = required.filter(id => !$(id));
  if (!missing.length) return true;
  document.body.innerHTML = `<main class="fatal-ui"><h1>DPN AI interface cache mismatch</h1><p>Missing interface elements: ${escapeHtml(missing.join(', '))}</p><button id="repairUiCacheBtn">Repair cached interface</button></main>`;
  $('repairUiCacheBtn').onclick = async () => {
    const registrations = await navigator.serviceWorker?.getRegistrations?.() || [];
    await Promise.all(registrations.map(item => item.unregister()));
    const keys = await caches.keys();
    await Promise.all(keys.map(key => caches.delete(key)));
    location.reload();
  };
  return false;
}

async function boot() {
  if (!validateInterfaceShell()) return;
  await loadHealth();
  await Promise.all([loadModels(), loadProfiles(), loadSkills(), loadProjects(), loadConversations(), loadVoiceProfiles()]);
  newConversation();
}
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js?v=8.0.0').catch(() => {});
boot().catch(error => toast(error.message, true));