const commandInput = document.getElementById('command-input');
const commandSend = document.getElementById('command-send');
const chatMessages = document.getElementById('chat-messages');
const chatStatus = document.getElementById('chat-status');
const chatHide = document.getElementById('chat-hide');
const chatStop = document.getElementById('chat-stop');
const MAX_INPUT_HEIGHT = 140;
const DUPLICATE_WINDOW_MS = 1200;
const MAX_PERSISTED_MESSAGES = 300;
const SESSION_SAVE_DEBOUNCE_MS = 250;
const MAX_ASSISTANT_CACHE = 120;
const ASSISTANT_THINKING_TEXT = 'Assistant is thinking...';

let socket;
let reconnectDelay = 500;
let reconnectTimer = null;
let lastSubmittedText = '';
let lastSubmittedAt = 0;
let pendingAssistantEl = null;
let lastAssistantText = '';
let lastStatusText = '';
let saveTimer = null;
let isHydratingSession = false;
const assistantMessageCache = [];
const chatHistory = [];

function resizeInput() {
  if (!commandInput) return;
  commandInput.style.height = 'auto';
  const targetHeight = Math.min(MAX_INPUT_HEIGHT, commandInput.scrollHeight);
  commandInput.style.height = `${targetHeight}px`;
}

function focusCommandInput() {
  if (!commandInput) return;
  commandInput.focus();
  const end = commandInput.value.length;
  commandInput.setSelectionRange(end, end);
}

function setStatus(text) {
  if (!chatStatus) return;
  const value = typeof text === 'string' ? text.trim() : '';
  if (!value || value === lastStatusText) return;
  lastStatusText = value;
  chatStatus.textContent = value;
}

function scrollMessagesToBottom() {
  if (!chatMessages) return;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function normalizePersistedMessage(role, text, ts = Date.now()) {
  const normalizedRole = typeof role === 'string' ? role.trim().toLowerCase() : '';
  const normalizedText = typeof text === 'string' ? text.trim() : '';
  const normalizedTs = Number.isFinite(ts) ? Number(ts) : Date.now();
  if (!normalizedRole || !normalizedText) return null;
  if (!['user', 'assistant', 'system'].includes(normalizedRole)) return null;
  return { role: normalizedRole, text: normalizedText, ts: normalizedTs };
}

function rememberMessage(role, text, ts = Date.now()) {
  const entry = normalizePersistedMessage(role, text, ts);
  if (!entry) return null;
  chatHistory.push(entry);
  if (chatHistory.length > MAX_PERSISTED_MESSAGES) {
    chatHistory.splice(0, chatHistory.length - MAX_PERSISTED_MESSAGES);
  }
  return entry;
}

async function persistChatHistoryNow() {
  if (!window.api?.saveChatSession) return;
  try {
    await window.api.saveChatSession(chatHistory);
  } catch (error) {
    // Best-effort persistence.
  }
}

function queuePersistChatHistory() {
  if (isHydratingSession) return;
  if (!window.api?.saveChatSession) return;
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    saveTimer = null;
    void persistChatHistoryNow();
  }, SESSION_SAVE_DEBOUNCE_MS);
}

function appendMessage(role, text, options = {}) {
  if (!chatMessages) return null;
  const { pending = false, persist = true, ts = Date.now() } = options;
  const value = typeof text === 'string' ? text.trim() : '';
  if (!value) return null;

  const el = document.createElement('div');
  el.className = `chat-msg ${role}${pending ? ' pending' : ''}`;
  el.textContent = value;
  chatMessages.appendChild(el);
  scrollMessagesToBottom();

  if (persist && !pending) {
    const message = rememberMessage(role, value, ts);
    if (message) {
      queuePersistChatHistory();
    }
  }

  return el;
}

function finalizePendingAssistant(text) {
  const value = typeof text === 'string' ? text.trim() : '';
  if (!value || value === ASSISTANT_THINKING_TEXT) return;
  if (value === lastAssistantText) return;

  if (pendingAssistantEl && pendingAssistantEl.isConnected) {
    pendingAssistantEl.classList.remove('pending');
    pendingAssistantEl.textContent = value;
    const message = rememberMessage('assistant', value);
    if (message) {
      queuePersistChatHistory();
    }
  } else {
    appendMessage('assistant', value, { pending: false, persist: true });
  }
  pendingAssistantEl = null;
  lastAssistantText = value;
  assistantMessageCache.push(value);
  if (assistantMessageCache.length > MAX_ASSISTANT_CACHE) {
    assistantMessageCache.shift();
  }
}

function clearPendingAssistant() {
  if (pendingAssistantEl && pendingAssistantEl.isConnected) {
    pendingAssistantEl.remove();
  }
  pendingAssistantEl = null;
}

function clearRenderedMessages() {
  if (!chatMessages) return;
  while (chatMessages.firstChild) {
    chatMessages.removeChild(chatMessages.firstChild);
  }
}

function restoreMessages(messages) {
  clearRenderedMessages();
  chatHistory.length = 0;
  let restoredLastAssistant = '';

  for (const item of messages) {
    if (!item || typeof item !== 'object') continue;
    const restored = rememberMessage(item.role, item.text, item.ts);
    if (!restored) continue;
    appendMessage(restored.role, restored.text, { pending: false, persist: false, ts: restored.ts });
    if (restored.role === 'assistant') {
      restoredLastAssistant = restored.text;
    }
  }

  lastAssistantText = restoredLastAssistant;
}

async function hydrateSessionHistory() {
  if (!window.api?.loadChatSession) return;
  isHydratingSession = true;
  try {
    const data = await window.api.loadChatSession();
    const messages = Array.isArray(data?.messages) ? data.messages : [];
    restoreMessages(messages);
  } catch (error) {
    // Keep running even if load fails.
  } finally {
    isHydratingSession = false;
  }
}

async function getSocketTarget() {
  const fallback = { host: '127.0.0.1', port: 8765 };
  try {
    if (!window.api?.getServerConfig) {
      return fallback;
    }
    const config = await window.api.getServerConfig();
    const host = typeof config?.host === 'string' && config.host.trim() ? config.host.trim() : fallback.host;
    const portValue = Number(config?.port);
    const port = Number.isInteger(portValue) && portValue > 0 ? portValue : fallback.port;
    return { host, port };
  } catch (error) {
    return fallback;
  }
}

function sendMessage(payload) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify(payload));
  return true;
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void connectSocket();
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 1.5, 5000);
}

async function connectSocket() {
  const target = await getSocketTarget();
  const wsUrl = `ws://${target.host}:${target.port}`;
  socket = new WebSocket(wsUrl);
  socket.addEventListener('open', () => {
    reconnectDelay = 500;
    setStatus('Connected');
  });
  socket.addEventListener('close', () => {
    setStatus('Reconnecting...');
    scheduleReconnect();
  });
  socket.addEventListener('error', () => {
    // Keep reconnect behavior on close.
  });
  socket.addEventListener('message', (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (error) {
      return;
    }

    if (payload.command === 'draw_text' && payload.id === 'direct_response') {
      finalizePendingAssistant(payload.text || '');
      return;
    }

    if (payload.command === 'show_status_bubble' || payload.command === 'update_status_bubble') {
      if (typeof payload.text === 'string' && payload.text.trim()) {
        setStatus(payload.text);
      }
      return;
    }

    if (payload.command === 'complete_status_bubble') {
      const responseText = payload.responseText || payload.text || '';
      finalizePendingAssistant(responseText);
      setStatus(payload.doneText || 'Done');
      return;
    }

    if (payload.command === 'hide_status_bubble') {
      setStatus('Ready');
    }
  });
}

function hideInputWindow() {
  if (window.api?.hideInputWindow) {
    window.api.hideInputWindow();
  }
}

function submitCommand() {
  const text = (commandInput.value || '').trim();
  if (!text) {
    return;
  }

  const now = Date.now();
  if (text === lastSubmittedText && (now - lastSubmittedAt) < DUPLICATE_WINDOW_MS) {
    return;
  }
  lastSubmittedText = text;
  lastSubmittedAt = now;

  clearPendingAssistant();
  lastAssistantText = '';
  appendMessage('user', text, { pending: false, persist: true });
  pendingAssistantEl = appendMessage('assistant', 'Working on your request...', { pending: true, persist: false });
  setStatus('Planning and executing...');

  sendMessage({ event: 'capture_screenshot' });
  sendMessage({
    event: 'overlay_input',
    text,
    requestId: `overlay_${now}_${Math.random().toString(16).slice(2, 8)}`
  });
  commandInput.value = '';
  resizeInput();
  focusCommandInput();
}

commandInput?.addEventListener('input', resizeInput);
commandInput?.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    submitCommand();
    return;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    hideInputWindow();
  }
});
commandSend?.addEventListener('click', () => submitCommand());
chatHide?.addEventListener('click', () => hideInputWindow());
chatStop?.addEventListener('click', () => {
  if (window.api?.requestStopAll) {
    window.api.requestStopAll();
  }
  clearPendingAssistant();
  appendMessage('system', 'Stopped all running actions.', { pending: false, persist: true });
  setStatus('Stopped');
  focusCommandInput();
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  event.preventDefault();
  hideInputWindow();
});

if (window.api?.onShowInputWindow) {
  window.api.onShowInputWindow(() => {
    requestAnimationFrame(() => {
      focusCommandInput();
    });
  });
}

if (window.api?.onHideInputWindow) {
  window.api.onHideInputWindow(() => {
    setStatus('Ready');
  });
}

if (window.api?.onStopAll) {
  window.api.onStopAll(() => {
    clearPendingAssistant();
    appendMessage('system', 'Stopped all running actions.', { pending: false, persist: true });
    setStatus('Stopped');
  });
}

window.addEventListener('beforeunload', () => {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  void persistChatHistoryNow();
});

async function initializeInputWindow() {
  resizeInput();
  setStatus('Loading chat session...');
  await hydrateSessionHistory();
  setStatus('Connecting...');
  await connectSocket();
}

void initializeInputWindow();
