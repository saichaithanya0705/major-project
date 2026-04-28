import {
  EXECUTION_PHASES,
  buildLifecycleSnapshot,
  getShortcutLabels,
  inferLifecycleSnapshot,
} from './status_lifecycle.js';

const commandInput = document.getElementById('command-input');
const commandSend = document.getElementById('command-send');
const commandVoice = document.getElementById('command-voice');
const chatMessages = document.getElementById('chat-messages');
const chatStatus = document.getElementById('chat-status');
const chatStatusPhase = document.getElementById('chat-status-phase');
const chatStatusText = document.getElementById('chat-status-text');
const chatStatusDetail = document.getElementById('chat-status-detail');
const chatShortcutsMenu = document.getElementById('chat-shortcuts-menu');
const chatShortcutsToggle = document.getElementById('chat-shortcuts-toggle');
const chatShortcutsPopover = document.getElementById('chat-shortcuts-popover');
const chatHide = document.getElementById('chat-hide');
const chatStop = document.getElementById('chat-stop');
const chatHistoryToggle = document.getElementById('chat-history-toggle');
const chatNew = document.getElementById('chat-new');
const chatBody = document.getElementById('chat-body');
const chatMain = document.getElementById('chat-main');
const historyPanel = document.getElementById('history-panel');
const historyPanelClose = document.getElementById('history-panel-close');
const historyRetentionNote = document.getElementById('history-retention-note');
const historyList = document.getElementById('history-list');
const historyEmpty = document.getElementById('history-empty');
const historyFilterActive = document.getElementById('history-filter-active');
const historyFilterArchived = document.getElementById('history-filter-archived');
const chatComposerHint = document.getElementById('chat-composer-hint');
const chatSessionMarker = document.getElementById('chat-session-marker');
const chatEmptyState = document.getElementById('chat-empty-state');
const chatEmptyTitle = document.getElementById('chat-empty-title');
const chatEmptyBody = document.getElementById('chat-empty-body');
const chatGuidanceOpenShortcut = document.getElementById('chat-guidance-open-shortcut');
const chatGuidanceStopShortcut = document.getElementById('chat-guidance-stop-shortcut');
const chatGuidanceHideShortcut = document.getElementById('chat-guidance-hide-shortcut');
const terminalPanel = document.getElementById('terminal-panel');
const terminalPanelMeta = document.getElementById('terminal-panel-meta');
const terminalPanelOutput = document.getElementById('terminal-panel-output');
const terminalPanelStop = document.getElementById('terminal-panel-stop');

const platform = window.api?.getPlatform ? window.api.getPlatform() : 'win32';
const shortcuts = getShortcutLabels(platform);

const MAX_INPUT_HEIGHT = 140;
const DUPLICATE_WINDOW_MS = 1200;
const MAX_PERSISTED_MESSAGES = 300;
const SESSION_SAVE_DEBOUNCE_MS = 250;
const MAX_ASSISTANT_CACHE = 120;
const ASSISTANT_THINKING_TEXT = 'Waiting for model response…';
const CHAT_HIDDEN_AGENT_SOURCES = new Set(['jarvis']);
const MAX_TERMINAL_TRANSCRIPT_CHARS = 16000;
const MAX_TERMINAL_CHAT_CHARS = 2200;
const DEFAULT_INPUT_PLACEHOLDER = 'Describe the next task for JARVIS…';
const ARCHIVED_INPUT_PLACEHOLDER = 'Archived chats are read-only. Start a new chat to continue.';
const VOICE_MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];

let socket;
let reconnectDelay = 500;
let reconnectTimer = null;
let lastSubmittedText = '';
let lastSubmittedAt = 0;
let pendingAssistantEl = null;
let lastAssistantText = '';
let saveTimer = null;
let isHydratingSession = false;
let activeTerminalSessionId = '';
let activeTerminalRunning = false;
let terminalChatBuffer = [];
let terminalChatReady = false;
let isHistoryOpen = false;
let historyFilter = 'active';
let retentionDays = 30;
let purgeDays = 30;
let currentSession = null;
let activeSessions = [];
let archivedSessions = [];
let currentLifecycle = buildLifecycleSnapshot(EXECUTION_PHASES.IDLE);
let sessionResumeMarkerVisible = false;
let lastStopAnnouncementAt = 0;
let lastStopAnnouncementText = '';
let voiceRecorder = null;
let voiceStream = null;
let voiceChunks = [];
let isVoiceRecording = false;
let isVoiceTranscribing = false;
let voiceDiscardOnStop = false;
let pendingVoiceRequestId = '';

const assistantMessageCache = [];
const chatHistory = [];

function normalizeAgentSource(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function shouldDisplayReplyInChat(payload) {
  return !CHAT_HIDDEN_AGENT_SOURCES.has(normalizeAgentSource(payload?.source));
}

function normalizeTerminalText(value, maxChars = MAX_TERMINAL_TRANSCRIPT_CHARS) {
  const text = typeof value === 'string' ? value.replace(/\r\n/g, '\n').trim() : '';
  if (!text) return '';
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 18).trimEnd()}\n...[truncated]...`;
}

function truncateTerminalChatText(value) {
  return normalizeTerminalText(value, MAX_TERMINAL_CHAT_CHARS);
}

function pushTerminalChatLine(text) {
  const value = truncateTerminalChatText(text);
  if (!value) return;
  terminalChatBuffer.push(value);
}

function flushTerminalChatBuffer() {
  if (!terminalChatReady || terminalChatBuffer.length === 0) {
    return;
  }
  appendMessage('terminal', terminalChatBuffer.join('\n\n'), { pending: false, persist: true });
  terminalChatBuffer = [];
  terminalChatReady = false;
}

function truncateText(value, maxChars) {
  const text = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
  if (!text) return '';
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
}

function deriveSessionTitle(messages) {
  if (!Array.isArray(messages) || messages.length === 0) {
    return 'New chat';
  }
  const firstUserMessage = messages.find((item) => item.role === 'user' && item.text);
  if (firstUserMessage) {
    return truncateText(firstUserMessage.text, 58) || 'New chat';
  }
  const fallback = messages.find((item) => item.text);
  return truncateText(fallback?.text || '', 58) || 'New chat';
}

function deriveSessionPreview(messages) {
  if (!Array.isArray(messages) || messages.length === 0) {
    return 'No messages yet';
  }
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const preview = truncateText(message?.text || '', 96);
    if (preview) {
      return preview;
    }
  }
  return 'No messages yet';
}

function sortSessionSummaries(items, useArchivedDate = false) {
  items.sort((left, right) => {
    const leftDate = Date.parse(useArchivedDate ? (left?.archivedAt || left?.updatedAt || 0) : (left?.updatedAt || 0));
    const rightDate = Date.parse(useArchivedDate ? (right?.archivedAt || right?.updatedAt || 0) : (right?.updatedAt || 0));
    return rightDate - leftDate;
  });
}

function cloneChatHistory() {
  return chatHistory.map((message) => ({ ...message }));
}

function buildSessionSummary(session) {
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  return {
    sessionId: typeof session?.sessionId === 'string' ? session.sessionId : '',
    title: truncateText(session?.title || deriveSessionTitle(messages), 58) || 'New chat',
    preview: deriveSessionPreview(messages),
    startedAt: typeof session?.startedAt === 'string' ? session.startedAt : new Date().toISOString(),
    updatedAt: typeof session?.updatedAt === 'string' ? session.updatedAt : new Date().toISOString(),
    archivedAt: typeof session?.archivedAt === 'string' && session.archivedAt.trim() ? session.archivedAt : null,
    messageCount: messages.length,
  };
}

function normalizeSessionSummary(summary) {
  if (!summary || typeof summary !== 'object') return null;
  return {
    sessionId: typeof summary.sessionId === 'string' ? summary.sessionId : '',
    title: truncateText(summary.title || '', 58) || 'New chat',
    preview: truncateText(summary.preview || '', 96) || 'No messages yet',
    startedAt: typeof summary.startedAt === 'string' ? summary.startedAt : new Date().toISOString(),
    updatedAt: typeof summary.updatedAt === 'string' ? summary.updatedAt : new Date().toISOString(),
    archivedAt: typeof summary.archivedAt === 'string' && summary.archivedAt.trim() ? summary.archivedAt : null,
    messageCount: Number.isFinite(summary.messageCount) ? Number(summary.messageCount) : 0,
  };
}

function normalizePersistedMessage(role, text, ts = Date.now()) {
  const normalizedRole = typeof role === 'string' ? role.trim().toLowerCase() : '';
  const normalizedText = typeof text === 'string' ? text.trim() : '';
  const normalizedTs = Number.isFinite(ts) ? Number(ts) : Date.now();
  if (!normalizedRole || !normalizedText) return null;
  if (!['user', 'assistant', 'system', 'terminal'].includes(normalizedRole)) return null;
  return { role: normalizedRole, text: normalizedText, ts: normalizedTs };
}

function normalizeSession(session) {
  if (!session || typeof session !== 'object') return null;
  const messages = Array.isArray(session.messages)
    ? session.messages
      .map((item) => normalizePersistedMessage(item.role, item.text, item.ts))
      .filter(Boolean)
    : [];

  return {
    sessionId: typeof session.sessionId === 'string' ? session.sessionId : '',
    title: truncateText(session.title || '', 58) || deriveSessionTitle(messages),
    startedAt: typeof session.startedAt === 'string' ? session.startedAt : new Date().toISOString(),
    updatedAt: typeof session.updatedAt === 'string' ? session.updatedAt : new Date().toISOString(),
    archivedAt: typeof session.archivedAt === 'string' && session.archivedAt.trim() ? session.archivedAt : null,
    messages,
  };
}

function upsertSessionSummary(summary) {
  if (!summary || !summary.sessionId) return;
  const targetCollection = summary.archivedAt ? archivedSessions : activeSessions;
  const otherCollection = summary.archivedAt ? activeSessions : archivedSessions;
  const existingIndex = targetCollection.findIndex((item) => item.sessionId === summary.sessionId);
  const otherIndex = otherCollection.findIndex((item) => item.sessionId === summary.sessionId);

  if (otherIndex >= 0) {
    otherCollection.splice(otherIndex, 1);
  }

  if (existingIndex >= 0) {
    targetCollection.splice(existingIndex, 1, summary);
  } else {
    targetCollection.push(summary);
  }

  sortSessionSummaries(activeSessions, false);
  sortSessionSummaries(archivedSessions, true);
}

function removeSessionSummary(sessionId) {
  if (!sessionId) return;
  const activeIndex = activeSessions.findIndex((item) => item.sessionId === sessionId);
  if (activeIndex >= 0) {
    activeSessions.splice(activeIndex, 1);
  }
  const archivedIndex = archivedSessions.findIndex((item) => item.sessionId === sessionId);
  if (archivedIndex >= 0) {
    archivedSessions.splice(archivedIndex, 1);
  }
}

function hasActiveWork() {
  return Boolean(pendingAssistantEl) || activeTerminalRunning;
}

function isCurrentSessionArchived() {
  return Boolean(currentSession?.archivedAt);
}

function updateActionAvailability() {
  const blocked = hasActiveWork();
  if (chatNew) {
    chatNew.disabled = blocked;
  }
}

function getReadyDetail() {
  if (isCurrentSessionArchived()) {
    return 'Archived chats are read-only until you start a new chat.';
  }
  return 'Type the next task below or reopen a prior session from History.';
}

function renderLifecycle(snapshot) {
  currentLifecycle = snapshot;
  if (chatStatus) {
    chatStatus.dataset.phase = snapshot.phase;
  }
  if (chatStatusPhase) {
    chatStatusPhase.textContent = snapshot.label;
  }
  if (chatStatusText) {
    chatStatusText.textContent = snapshot.text;
  }
  if (chatStatusDetail) {
    chatStatusDetail.textContent = snapshot.detail || '';
  }
}

function setLifecyclePhase(phase, overrides = {}) {
  const snapshot = buildLifecycleSnapshot(phase, {
    ...overrides,
    detail: overrides.detail ?? (phase === EXECUTION_PHASES.IDLE ? getReadyDetail() : undefined),
  });
  renderLifecycle(snapshot);
}

function setLifecycleFromRawText(text, options = {}) {
  const snapshot = inferLifecycleSnapshot(text, {
    source: options.source,
    phaseHint: options.phaseHint,
    detail: options.detail,
    theme: options.theme,
  });

  if (snapshot.phase === EXECUTION_PHASES.IDLE && !options.detail) {
    snapshot.detail = getReadyDetail();
  }

  renderLifecycle(snapshot);
  return snapshot;
}

function setReadyLifecycle() {
  if (isCurrentSessionArchived()) {
    setLifecyclePhase(EXECUTION_PHASES.IDLE, {
      text: 'Viewing archived chat',
      detail: 'Archived chats are read-only until you start a new chat.',
    });
    return;
  }

  setLifecyclePhase(EXECUTION_PHASES.IDLE, {
    text: 'Ready for command',
    detail: getReadyDetail(),
  });
}

function updateShortcutUi() {
  if (chatGuidanceOpenShortcut) {
    chatGuidanceOpenShortcut.textContent = shortcuts.open;
  }
  if (chatGuidanceStopShortcut) {
    chatGuidanceStopShortcut.textContent = shortcuts.stop;
  }
  if (chatGuidanceHideShortcut) {
    chatGuidanceHideShortcut.textContent = shortcuts.hide;
  }

  if (chatShortcutsToggle) {
    chatShortcutsToggle.title = 'Show shortcuts';
  }
  if (chatHistoryToggle) {
    chatHistoryToggle.title = 'Open chat history';
  }
  if (chatNew) {
    chatNew.title = 'Start a new chat';
  }
  if (chatStop) {
    chatStop.title = `Stop running actions (${shortcuts.stop})`;
  }
  if (chatHide) {
    chatHide.title = `Hide window (${shortcuts.hide})`;
  }
  if (commandVoice) {
    commandVoice.title = 'Record voice command';
  }
  if (commandSend) {
    commandSend.title = 'Send command (Enter)';
  }
  if (terminalPanelStop) {
    terminalPanelStop.title = `Stop terminal session (${shortcuts.stop})`;
  }
}

function isShortcutsPopoverOpen() {
  return Boolean(chatShortcutsPopover && !chatShortcutsPopover.hidden);
}

function openShortcutsPopover() {
  if (!chatShortcutsPopover) return;
  chatShortcutsPopover.hidden = false;
  if (chatShortcutsToggle) {
    chatShortcutsToggle.setAttribute('aria-expanded', 'true');
  }
}

function closeShortcutsPopover(options = {}) {
  if (!chatShortcutsPopover) return;
  const { restoreFocus = false } = options;
  chatShortcutsPopover.hidden = true;
  if (chatShortcutsToggle) {
    chatShortcutsToggle.setAttribute('aria-expanded', 'false');
    if (restoreFocus) {
      chatShortcutsToggle.focus();
    }
  }
}

function toggleShortcutsPopover() {
  if (isShortcutsPopoverOpen()) {
    closeShortcutsPopover();
    return;
  }
  openShortcutsPopover();
}

function handleEscapeKey(options = {}) {
  const { restoreShortcutFocus = false } = options;
  if (isShortcutsPopoverOpen()) {
    closeShortcutsPopover({ restoreFocus: restoreShortcutFocus });
    return true;
  }
  if (isHistoryOpen) {
    closeHistoryPanel();
    return true;
  }
  hideInputWindow();
  return true;
}

function isTerminalStopRequest(text) {
  const value = typeof text === 'string' ? text.trim().toLowerCase() : '';
  if (!value) return false;
  return [
    'close terminal',
    'close the terminal',
    'stop terminal',
    'stop the terminal',
    'kill terminal',
    'stop cli agent',
  ].some((phrase) => value.includes(phrase));
}

function setTerminalMeta(text) {
  if (!terminalPanelMeta) return;
  terminalPanelMeta.textContent = typeof text === 'string' && text.trim() ? text.trim() : 'Waiting for CLI activity...';
}

function showTerminalPanel() {
  if (terminalPanel) {
    terminalPanel.hidden = false;
  }
}

function scrollTerminalToBottom() {
  if (!terminalPanelOutput) return;
  terminalPanelOutput.scrollTop = terminalPanelOutput.scrollHeight;
}

function clearTerminalTranscript() {
  if (terminalPanelOutput) {
    terminalPanelOutput.textContent = '';
  }
}

function appendTerminalTranscript(text) {
  if (!terminalPanelOutput || (terminalPanel && terminalPanel.hidden)) return;
  const value = normalizeTerminalText(text);
  if (!value) return;
  const existing = terminalPanelOutput.textContent || '';
  const next = existing ? `${existing}\n\n${value}` : value;
  terminalPanelOutput.textContent = next.length > MAX_TERMINAL_TRANSCRIPT_CHARS
    ? next.slice(next.length - MAX_TERMINAL_TRANSCRIPT_CHARS)
    : next;
  scrollTerminalToBottom();
}

function resetTerminalSession(options = {}) {
  const { hide = false } = options;
  activeTerminalSessionId = '';
  activeTerminalRunning = false;
  terminalChatBuffer = [];
  terminalChatReady = false;
  clearTerminalTranscript();
  setTerminalMeta('Waiting for CLI activity...');
  if (hide && terminalPanel) {
    terminalPanel.hidden = true;
  }
  updateActionAvailability();
}

function ensureTerminalSession(sessionId) {
  const nextId = typeof sessionId === 'string' ? sessionId.trim() : '';
  if (nextId && activeTerminalSessionId && activeTerminalSessionId !== nextId) {
    clearTerminalTranscript();
    terminalChatBuffer = [];
    terminalChatReady = false;
  }
  if (nextId) {
    activeTerminalSessionId = nextId;
  }
  showTerminalPanel();
}

function updatePendingAssistantStatus(text) {
  const value = typeof text === 'string' ? text.trim() : '';
  if (!pendingAssistantEl || !pendingAssistantEl.isConnected || !value) return;
  setMessageElementText(pendingAssistantEl, value, {
    role: 'assistant',
    pending: true,
  });
}

function getTerminalLifecycleSnapshot(kind, status, shellCommand, text) {
  if (kind === 'session_started') {
    return buildLifecycleSnapshot(EXECUTION_PHASES.RUNNING, {
      text: 'Running terminal action…',
      detail: text || 'CLI session started.',
    });
  }

  if (kind === 'command_started') {
    return buildLifecycleSnapshot(EXECUTION_PHASES.RUNNING, {
      text: 'Running terminal action…',
      detail: shellCommand ? `Running ${shellCommand}` : 'Running CLI command.',
    });
  }

  if (kind === 'command_output' && status === 'error') {
    return buildLifecycleSnapshot(EXECUTION_PHASES.STOPPED, {
      text: 'Terminal command failed',
      detail: 'Review the CLI transcript for the failure output.',
    });
  }

  if (kind === 'session_finished') {
    return buildLifecycleSnapshot(EXECUTION_PHASES.COMPLETED, {
      text: 'Completed',
      detail: text || 'CLI session finished.',
    });
  }

  if (kind === 'session_error') {
    return buildLifecycleSnapshot(EXECUTION_PHASES.STOPPED, {
      text: 'Terminal session failed',
      detail: text || 'CLI session failed.',
    });
  }

  if (kind === 'session_stopped') {
    return buildLifecycleSnapshot(EXECUTION_PHASES.STOPPED, {
      text: 'Stopped',
      detail: text || 'CLI session stopped.',
    });
  }

  return null;
}

function handleTerminalSessionEvent(payload) {
  const kind = typeof payload?.kind === 'string' ? payload.kind.trim().toLowerCase() : '';
  const shellCommand = typeof payload?.shellCommand === 'string' ? payload.shellCommand.trim() : '';
  const text = normalizeTerminalText(payload?.text || '');
  const status = typeof payload?.status === 'string' ? payload.status.trim().toLowerCase() : '';

  ensureTerminalSession(payload?.sessionId);

  if (kind === 'session_started') {
    activeTerminalRunning = true;
    setTerminalMeta(text || 'CLI session started.');
    appendTerminalTranscript(text || 'CLI session started.');
    terminalChatBuffer = [];
    terminalChatReady = false;
    updateActionAvailability();
  } else if (kind === 'command_started') {
    activeTerminalRunning = true;
    setTerminalMeta(shellCommand ? `Running: ${shellCommand}` : 'Running shell command...');
    appendTerminalTranscript(shellCommand ? `$ ${shellCommand}` : '$ [shell command]');
    pushTerminalChatLine(shellCommand ? `$ ${shellCommand}` : '$ [shell command]');
    updateActionAvailability();
  } else if (kind === 'command_output') {
    const transcript = text || '(command completed with no output)';
    if (status === 'error') {
      setTerminalMeta('Command failed.');
      appendTerminalTranscript(`[error]\n${transcript}`);
      pushTerminalChatLine(`[error]\n${transcript}`);
      activeTerminalRunning = false;
      terminalChatReady = true;
      updateActionAvailability();
    } else {
      setTerminalMeta('Command completed.');
      appendTerminalTranscript(transcript);
      pushTerminalChatLine(transcript);
    }
  } else if (kind === 'session_finished') {
    activeTerminalRunning = false;
    setTerminalMeta(text || 'CLI session finished.');
    if (text) {
      appendTerminalTranscript(`[done] ${text}`);
    }
    terminalChatReady = true;
    updateActionAvailability();
  } else if (kind === 'session_error') {
    activeTerminalRunning = false;
    setTerminalMeta(text || 'CLI session failed.');
    appendTerminalTranscript(`[session error]\n${text || 'CLI session failed.'}`);
    pushTerminalChatLine(`[session error]\n${text || 'CLI session failed.'}`);
    terminalChatReady = true;
    updateActionAvailability();
  } else if (kind === 'session_stopped') {
    activeTerminalRunning = false;
    setTerminalMeta(text || 'Terminal session stopped.');
    appendTerminalTranscript(`[stopped] ${text || 'Terminal session stopped.'}`);
    pushTerminalChatLine(`[stopped] ${text || 'Terminal session stopped.'}`);
    terminalChatReady = true;
    updateActionAvailability();
  }

  const lifecycle = getTerminalLifecycleSnapshot(kind, status, shellCommand, text);
  if (lifecycle) {
    renderLifecycle(lifecycle);
    if (activeTerminalRunning) {
      updatePendingAssistantStatus(lifecycle.text);
    }
  }
}

function resizeInput() {
  if (!commandInput) return;
  commandInput.style.height = 'auto';
  const targetHeight = Math.min(MAX_INPUT_HEIGHT, commandInput.scrollHeight);
  commandInput.style.height = `${targetHeight}px`;
}

function focusCommandInput() {
  if (!commandInput || commandInput.disabled) return;
  commandInput.focus();
  const end = commandInput.value.length;
  commandInput.setSelectionRange(end, end);
}

function scrollMessagesToBottom() {
  if (!chatMessages) return;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function formatMessageTime(ts) {
  const date = new Date(Number.isFinite(ts) ? Number(ts) : Date.now());
  return new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

function getMessageRoleLabel(role) {
  if (role === 'user') return 'You';
  if (role === 'assistant') return 'Assistant';
  if (role === 'system') return 'System';
  if (role === 'terminal') return 'CLI';
  return 'Message';
}

function setMessageElementText(el, text, options = {}) {
  if (!el) return;
  const role = options.role || el.dataset.role || 'assistant';
  const value = typeof text === 'string' ? text.trim() : '';
  const content = el.querySelector('.chat-msg-content');
  const roleEl = el.querySelector('.chat-msg-role');
  const timeEl = el.querySelector('.chat-msg-time');
  const pending = Boolean(options.pending);
  const timestamp = Number.isFinite(options.ts) ? Number(options.ts) : Number(el.dataset.ts || Date.now());

  if (content) {
    content.textContent = value;
  }
  if (roleEl) {
    roleEl.textContent = getMessageRoleLabel(role);
  }
  if (timeEl) {
    timeEl.textContent = pending ? 'Live' : formatMessageTime(timestamp);
    timeEl.dateTime = new Date(timestamp).toISOString();
  }

  el.dataset.role = role;
  el.dataset.ts = String(timestamp);
  el.classList.toggle('pending', pending);
}

function createMessageElement(role, text, options = {}) {
  if (!chatMessages) return null;
  const value = typeof text === 'string' ? text.trim() : '';
  if (!value) return null;

  const pending = Boolean(options.pending);
  const ts = Number.isFinite(options.ts) ? Number(options.ts) : Date.now();

  const el = document.createElement('article');
  el.className = `chat-msg ${role}${pending ? ' pending' : ''}`;

  const meta = document.createElement('div');
  meta.className = 'chat-msg-meta';

  const roleEl = document.createElement('span');
  roleEl.className = 'chat-msg-role';

  const timeEl = document.createElement('time');
  timeEl.className = 'chat-msg-time';

  meta.appendChild(roleEl);
  meta.appendChild(timeEl);

  const content = document.createElement('div');
  content.className = 'chat-msg-content';

  el.appendChild(meta);
  el.appendChild(content);
  chatMessages.appendChild(el);
  setMessageElementText(el, value, { role, pending, ts });
  scrollMessagesToBottom();
  return el;
}

function renderConversationDecorators() {
  if (chatEmptyState) {
    const showEmpty = chatHistory.length === 0 && !pendingAssistantEl;
    chatEmptyState.hidden = !showEmpty;
    if (showEmpty) {
      if (chatEmptyTitle) {
        chatEmptyTitle.textContent = isCurrentSessionArchived() ? 'Archived chat' : 'Ready for command';
      }
      if (chatEmptyBody) {
        chatEmptyBody.textContent = isCurrentSessionArchived()
          ? 'Archived chats are read-only. Start a new chat to continue.'
          : 'Type the next task below or reopen a prior session from History.';
      }
    }
  }

  if (chatSessionMarker) {
    const showMarker = sessionResumeMarkerVisible && chatHistory.length > 0;
    chatSessionMarker.hidden = !showMarker;
    if (showMarker) {
      chatSessionMarker.textContent = `Resumed session · Updated ${formatSessionDate(currentSession?.updatedAt)}`;
    } else {
      chatSessionMarker.textContent = '';
    }
  }
}

function syncCurrentSessionMetadataFromHistory(lastTs = Date.now()) {
  if (!currentSession) return;

  currentSession.messages = cloneChatHistory();
  currentSession.title = deriveSessionTitle(currentSession.messages);
  if (!currentSession.archivedAt && chatHistory.length > 0 && Number.isFinite(lastTs)) {
    currentSession.updatedAt = new Date(lastTs).toISOString();
  }

  upsertSessionSummary(buildSessionSummary(currentSession));
  if (isHistoryOpen) {
    renderHistoryList();
  }
  renderConversationDecorators();
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
  if (!currentSession?.sessionId || currentSession.archivedAt) return;
  try {
    const result = await window.api.saveChatSession(currentSession.sessionId, chatHistory);
    if (result?.readOnly) {
      return;
    }
    if (typeof result?.updatedAt === 'string') {
      currentSession.updatedAt = result.updatedAt;
      upsertSessionSummary(buildSessionSummary(currentSession));
      if (isHistoryOpen) {
        renderHistoryList();
      }
    }
  } catch {
    // Best-effort persistence.
  }
}

function queuePersistChatHistory() {
  if (isHydratingSession) return;
  if (!window.api?.saveChatSession) return;
  if (!currentSession?.sessionId || currentSession.archivedAt) return;
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    saveTimer = null;
    void persistChatHistoryNow();
  }, SESSION_SAVE_DEBOUNCE_MS);
}

async function flushPendingSessionSave() {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  await persistChatHistoryNow();
}

function appendMessage(role, text, options = {}) {
  const { pending = false, persist = true, ts = Date.now() } = options;
  const el = createMessageElement(role, text, { pending, ts });
  if (!el) return null;

  if (persist && !pending) {
    const message = rememberMessage(role, text, ts);
    if (message) {
      syncCurrentSessionMetadataFromHistory(message.ts);
      queuePersistChatHistory();
    }
  } else {
    renderConversationDecorators();
  }

  return el;
}

function appendSystemNotice(text, options = {}) {
  const now = Date.now();
  const value = typeof text === 'string' ? text.trim() : '';
  if (!value) return null;
  const signature = value.toLowerCase().startsWith('stop') ? 'stop-flow' : value;
  if (signature === lastStopAnnouncementText && (now - lastStopAnnouncementAt) < 900) {
    return null;
  }
  lastStopAnnouncementText = signature;
  lastStopAnnouncementAt = now;
  return appendMessage('system', value, { pending: false, persist: true, ts: options.ts || now });
}

function finalizePendingAssistant(text) {
  const value = typeof text === 'string' ? text.trim() : '';
  if (!value || value === ASSISTANT_THINKING_TEXT) return;
  if (value === lastAssistantText) return;

  const ts = Date.now();

  if (pendingAssistantEl && pendingAssistantEl.isConnected) {
    setMessageElementText(pendingAssistantEl, value, {
      role: 'assistant',
      pending: false,
      ts,
    });
    const message = rememberMessage('assistant', value, ts);
    if (message) {
      syncCurrentSessionMetadataFromHistory(message.ts);
      queuePersistChatHistory();
    }
  } else {
    appendMessage('assistant', value, { pending: false, persist: true, ts });
  }

  pendingAssistantEl = null;
  lastAssistantText = value;
  assistantMessageCache.push(value);
  if (assistantMessageCache.length > MAX_ASSISTANT_CACHE) {
    assistantMessageCache.shift();
  }
  flushTerminalChatBuffer();
  updateActionAvailability();
  renderConversationDecorators();
}

function clearPendingAssistant() {
  if (pendingAssistantEl && pendingAssistantEl.isConnected) {
    pendingAssistantEl.remove();
  }
  pendingAssistantEl = null;
  if (terminalChatReady) {
    flushTerminalChatBuffer();
  }
  updateActionAvailability();
  renderConversationDecorators();
}

function clearRenderedMessages() {
  if (!chatMessages) return;
  chatMessages.querySelectorAll('.chat-msg').forEach((node) => node.remove());
  renderConversationDecorators();
}

function restoreMessages(messages) {
  clearRenderedMessages();
  chatHistory.length = 0;
  let restoredLastAssistant = '';

  for (const item of messages) {
    const restored = normalizePersistedMessage(item?.role, item?.text, item?.ts);
    if (!restored) continue;
    chatHistory.push(restored);
    createMessageElement(restored.role, restored.text, { pending: false, ts: restored.ts });
    if (restored.role === 'assistant') {
      restoredLastAssistant = restored.text;
    }
  }

  lastAssistantText = restoredLastAssistant;
  renderConversationDecorators();
}

function formatSessionDate(value) {
  const timestamp = Date.parse(value || '');
  if (!Number.isFinite(timestamp)) {
    return 'Unknown date';
  }

  const now = Date.now();
  const diffMs = now - timestamp;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diffMs < minute) return 'Just now';
  if (diffMs < hour) return `${Math.max(1, Math.floor(diffMs / minute))}m ago`;
  if (diffMs < day) return `${Math.max(1, Math.floor(diffMs / hour))}h ago`;
  if (diffMs < 7 * day) return `${Math.max(1, Math.floor(diffMs / day))}d ago`;

  const formatter = new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: new Date(timestamp).getFullYear() === new Date(now).getFullYear() ? undefined : 'numeric',
  });

  return formatter.format(new Date(timestamp));
}

function updateHistoryRetentionCopy() {
  if (!historyRetentionNote) return;
  historyRetentionNote.textContent = `Chats inactive for ${retentionDays} days move to archive. Archived chats are deleted after another ${purgeDays} days.`;
}

function updateComposerState() {
  const archived = isCurrentSessionArchived();

  if (commandInput) {
    commandInput.disabled = archived;
    commandInput.placeholder = archived ? ARCHIVED_INPUT_PLACEHOLDER : DEFAULT_INPUT_PLACEHOLDER;
  }

  if (commandSend) {
    commandSend.disabled = archived;
  }

  updateVoiceButtonState();

  if (chatComposerHint) {
    if (archived) {
      chatComposerHint.hidden = false;
      chatComposerHint.textContent = `Viewing an archived chat. Start a new chat to continue. Archived chats are removed ${purgeDays} days after archiving.`;
    } else {
      chatComposerHint.hidden = true;
      chatComposerHint.textContent = '';
    }
  }

  resizeInput();
}

function renderHistoryList() {
  if (!historyList || !historyEmpty) return;

  historyList.textContent = '';
  const items = historyFilter === 'archived' ? archivedSessions : activeSessions;
  historyEmpty.hidden = items.length > 0;
  historyEmpty.textContent = historyFilter === 'archived'
    ? 'No archived chats yet.'
    : 'Start a new chat to create your first session.';

  const blocked = hasActiveWork();

  for (const summary of items) {
    const item = document.createElement('article');
    item.className = `history-item${summary.sessionId === currentSession?.sessionId ? ' current' : ''}`;
    item.setAttribute('role', 'listitem');

    const mainButton = document.createElement('button');
    mainButton.type = 'button';
    mainButton.className = 'history-item-main';
    mainButton.disabled = blocked && summary.sessionId !== currentSession?.sessionId;

    const titleRow = document.createElement('div');
    titleRow.className = 'history-item-title-row';

    const title = document.createElement('span');
    title.className = 'history-item-title';
    title.textContent = summary.title || 'New chat';

    titleRow.appendChild(title);

    if (summary.sessionId === currentSession?.sessionId) {
      const badge = document.createElement('span');
      badge.className = 'history-item-badge';
      badge.textContent = 'Current';
      titleRow.appendChild(badge);
    }

    const preview = document.createElement('div');
    preview.className = 'history-item-preview';
    preview.textContent = summary.preview || 'No messages yet';

    const meta = document.createElement('div');
    meta.className = 'history-item-meta';
    meta.textContent = summary.archivedAt
      ? `Archived ${formatSessionDate(summary.archivedAt)}`
      : `Updated ${formatSessionDate(summary.updatedAt)}`;

    mainButton.appendChild(titleRow);
    mainButton.appendChild(preview);
    mainButton.appendChild(meta);
    mainButton.addEventListener('click', () => {
      if (summary.sessionId === currentSession?.sessionId) {
        closeHistoryPanel();
        return;
      }
      void switchToSession(summary.sessionId);
    });
    item.appendChild(mainButton);

    if (!summary.archivedAt) {
      const archiveButton = document.createElement('button');
      archiveButton.type = 'button';
      archiveButton.className = 'history-item-action';
      archiveButton.textContent = 'Archive';
      archiveButton.disabled = blocked;
      archiveButton.addEventListener('click', (event) => {
        event.stopPropagation();
        void archiveSession(summary.sessionId);
      });
      item.appendChild(archiveButton);
    }

    historyList.appendChild(item);
  }

  if (historyFilterActive) {
    historyFilterActive.setAttribute('aria-selected', historyFilter === 'active' ? 'true' : 'false');
  }
  if (historyFilterArchived) {
    historyFilterArchived.setAttribute('aria-selected', historyFilter === 'archived' ? 'true' : 'false');
  }
}

function openHistoryPanel() {
  closeShortcutsPopover();
  isHistoryOpen = true;
  if (chatBody) {
    chatBody.dataset.view = 'history';
  }
  if (historyPanel) {
    historyPanel.hidden = false;
  }
  if (chatMain) {
    chatMain.hidden = true;
  }
  if (chatHistoryToggle) {
    chatHistoryToggle.setAttribute('aria-pressed', 'true');
  }
  renderHistoryList();
}

function closeHistoryPanel() {
  isHistoryOpen = false;
  if (chatBody) {
    chatBody.dataset.view = 'chat';
  }
  if (historyPanel) {
    historyPanel.hidden = true;
  }
  if (chatMain) {
    chatMain.hidden = false;
  }
  if (chatHistoryToggle) {
    chatHistoryToggle.setAttribute('aria-pressed', 'false');
  }
}

function toggleHistoryPanel() {
  if (isHistoryOpen) {
    closeHistoryPanel();
  } else {
    openHistoryPanel();
  }
}

function applySessionState(state, options = {}) {
  const { keepHistoryOpen = isHistoryOpen, focusInput = false } = options;
  retentionDays = Number.isFinite(Number(state?.retentionDays)) ? Number(state.retentionDays) : retentionDays;
  purgeDays = Number.isFinite(Number(state?.purgeDays)) ? Number(state.purgeDays) : purgeDays;
  activeSessions = Array.isArray(state?.activeSessions)
    ? state.activeSessions.map(normalizeSessionSummary).filter(Boolean)
    : [];
  archivedSessions = Array.isArray(state?.archivedSessions)
    ? state.archivedSessions.map(normalizeSessionSummary).filter(Boolean)
    : [];
  currentSession = normalizeSession(state?.currentSession);

  updateHistoryRetentionCopy();

  if (!currentSession) {
    clearRenderedMessages();
    chatHistory.length = 0;
    sessionResumeMarkerVisible = false;
  } else {
    sessionResumeMarkerVisible = currentSession.messages.length > 0;
    restoreMessages(currentSession.messages);
    upsertSessionSummary(buildSessionSummary(currentSession));
  }

  clearPendingAssistant();
  resetTerminalSession({ hide: true });
  updateComposerState();
  updateActionAvailability();
  renderHistoryList();
  renderConversationDecorators();

  if (keepHistoryOpen) {
    openHistoryPanel();
  } else {
    closeHistoryPanel();
  }

  setReadyLifecycle();

  if (focusInput) {
    requestAnimationFrame(() => {
      focusCommandInput();
    });
  }
}

async function refreshChatSessionState(sessionId = null, options = {}) {
  if (!window.api?.getChatSessionState) return;
  isHydratingSession = true;
  try {
    const state = await window.api.getChatSessionState(sessionId);
    applySessionState(state, options);
  } catch {
    // Keep running even if load fails.
  } finally {
    isHydratingSession = false;
  }
}

async function switchToSession(sessionId) {
  if (!sessionId) return;
  if (hasActiveWork()) {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Switch blocked',
      detail: 'Stop current work before switching chats.',
    });
    return;
  }
  await flushPendingSessionSave();
  setLifecyclePhase(EXECUTION_PHASES.PREPARING, {
    text: 'Restoring session…',
    detail: 'Loading the selected chat history.',
  });
  await refreshChatSessionState(sessionId, { keepHistoryOpen: false, focusInput: true });
  setReadyLifecycle();
}

async function createNewChat() {
  if (!window.api?.createChatSession) return;
  if (hasActiveWork()) {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'New chat blocked',
      detail: 'Stop current work before starting a new chat.',
    });
    return;
  }
  await flushPendingSessionSave();
  setLifecyclePhase(EXECUTION_PHASES.PREPARING, {
    text: 'Creating new chat…',
    detail: 'Starting a fresh session.',
  });
  try {
    const state = await window.api.createChatSession();
    applySessionState(state, { keepHistoryOpen: false, focusInput: true });
    sessionResumeMarkerVisible = false;
    renderConversationDecorators();
    setReadyLifecycle();
  } catch {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Unable to create a new chat',
      detail: 'The session could not be created right now.',
    });
  }
}

async function archiveSession(sessionId) {
  if (!window.api?.archiveChatSession || !sessionId) return;
  if (hasActiveWork()) {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Archive blocked',
      detail: 'Stop current work before archiving a chat.',
    });
    return;
  }

  if (sessionId === currentSession?.sessionId) {
    await flushPendingSessionSave();
  }

  setLifecyclePhase(EXECUTION_PHASES.PREPARING, {
    text: 'Archiving chat…',
    detail: 'Moving the current session into archive.',
  });
  try {
    const state = await window.api.archiveChatSession(sessionId);
    removeSessionSummary(sessionId);
    applySessionState(state, { keepHistoryOpen: true, focusInput: !isCurrentSessionArchived() });
    setLifecyclePhase(EXECUTION_PHASES.COMPLETED, {
      text: 'Chat archived',
      detail: 'The session is now read-only in archive.',
    });
  } catch {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Unable to archive chat',
      detail: 'The session could not be archived right now.',
    });
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
  } catch {
    return fallback;
  }
}

function sendMessage(payload) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify(payload));
  return true;
}

function isSocketConnected() {
  return Boolean(socket && socket.readyState === WebSocket.OPEN);
}

function stopVoiceStream() {
  if (!voiceStream) return;
  for (const track of voiceStream.getTracks()) {
    try {
      track.stop();
    } catch {
      // Best-effort track cleanup.
    }
  }
  voiceStream = null;
}

function resetVoiceState() {
  stopVoiceStream();
  voiceRecorder = null;
  voiceChunks = [];
  voiceDiscardOnStop = false;
  pendingVoiceRequestId = '';
  isVoiceRecording = false;
  isVoiceTranscribing = false;
  updateVoiceButtonState();
}

function getVoiceButtonMeta() {
  if (isVoiceRecording) {
    return {
      state: 'recording',
      label: 'Stop listening',
      title: 'Stop listening',
      disabled: false,
      pressed: 'true',
    };
  }

  if (isVoiceTranscribing) {
    return {
      state: 'transcribing',
      label: 'Transcribing voice command',
      title: 'Transcribing voice command',
      disabled: true,
      pressed: 'false',
    };
  }

  const unavailable = isCurrentSessionArchived() || !isSocketConnected();
  return {
    state: 'idle',
    label: 'Record voice command',
    title: isCurrentSessionArchived()
      ? 'Archived chats are read-only'
      : isSocketConnected()
        ? 'Record voice command'
        : 'Voice command is unavailable while reconnecting',
    disabled: unavailable,
    pressed: 'false',
  };
}

function updateVoiceButtonState() {
  if (!commandVoice) return;
  const meta = getVoiceButtonMeta();
  commandVoice.dataset.state = meta.state;
  commandVoice.disabled = meta.disabled;
  commandVoice.title = meta.title;
  commandVoice.setAttribute('aria-label', meta.label);
  commandVoice.setAttribute('aria-pressed', meta.pressed);
}

function pickVoiceMimeType() {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return '';
  }
  for (const candidate of VOICE_MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(candidate)) {
      return candidate;
    }
  }
  return '';
}

function extensionForMimeType(mimeType) {
  const value = typeof mimeType === 'string' ? mimeType.toLowerCase() : '';
  if (value.includes('mp4') || value.includes('mpeg-4')) return 'mp4';
  if (value.includes('ogg')) return 'ogg';
  if (value.includes('wav')) return 'wav';
  if (value.includes('mpeg') || value.includes('mp3')) return 'mp3';
  return 'webm';
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Unable to read the recorded audio.'));
    reader.onloadend = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      const commaIndex = result.indexOf(',');
      if (commaIndex < 0) {
        reject(new Error('Unable to encode the recorded audio.'));
        return;
      }
      resolve(result.slice(commaIndex + 1));
    };
    reader.readAsDataURL(blob);
  });
}

function mergeTranscriptIntoDraft(transcript) {
  const existing = typeof commandInput?.value === 'string' ? commandInput.value.trim() : '';
  if (!existing) {
    return transcript;
  }
  const separator = /[\s\n]$/.test(commandInput.value) ? '' : ' ';
  return `${commandInput.value}${separator}${transcript}`;
}

async function requestVoiceTranscription(blob, mimeType) {
  const normalizedMimeType = mimeType || blob.type || 'audio/webm';
  const requestId = `voice_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
  const filename = `voice-command.${extensionForMimeType(normalizedMimeType)}`;
  const audioBase64 = await blobToBase64(blob);

  pendingVoiceRequestId = requestId;
  const queued = sendMessage({
    event: 'transcribe_audio',
    requestId,
    filename,
    mimeType: normalizedMimeType,
    audioBase64,
  });

  if (!queued) {
    pendingVoiceRequestId = '';
    isVoiceTranscribing = false;
    updateVoiceButtonState();
    appendSystemNotice('Unable to send the voice recording while reconnecting.');
    setLifecyclePhase(EXECUTION_PHASES.RECONNECTING, {
      text: 'Reconnect in progress…',
      detail: 'The live session is unavailable. Try the microphone again once the connection returns.',
    });
  }
}

async function finalizeVoiceRecording(recordedMimeType) {
  const chunks = voiceChunks.slice();
  voiceChunks = [];
  voiceRecorder = null;
  stopVoiceStream();

  if (voiceDiscardOnStop) {
    voiceDiscardOnStop = false;
    isVoiceRecording = false;
    isVoiceTranscribing = false;
    updateVoiceButtonState();
    return;
  }

  const blob = new Blob(chunks, { type: recordedMimeType || 'audio/webm' });
  if (!blob.size) {
    isVoiceTranscribing = false;
    updateVoiceButtonState();
    appendSystemNotice('No audio was captured from the microphone.');
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Voice command unavailable',
      detail: 'The recording was empty. Try again and speak after the mic turns red.',
    });
    return;
  }

  try {
    await requestVoiceTranscription(blob, recordedMimeType);
  } catch (error) {
    pendingVoiceRequestId = '';
    isVoiceTranscribing = false;
    updateVoiceButtonState();
    appendSystemNotice('Unable to prepare the voice recording.');
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Voice command unavailable',
      detail: error instanceof Error ? error.message : 'Unable to prepare the voice recording.',
    });
  }
}

function stopVoiceRecording(options = {}) {
  if (!voiceRecorder || voiceRecorder.state === 'inactive') {
    return;
  }
  isVoiceRecording = false;
  isVoiceTranscribing = !options.discard;
  voiceDiscardOnStop = Boolean(options.discard);
  updateVoiceButtonState();

  try {
    voiceRecorder.stop();
  } catch (error) {
    resetVoiceState();
    appendSystemNotice('Unable to stop the voice recording cleanly.');
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Voice command unavailable',
      detail: error instanceof Error ? error.message : 'Unable to stop the voice recording cleanly.',
    });
  }
}

function cancelVoiceCapture() {
  if (voiceRecorder && voiceRecorder.state !== 'inactive') {
    stopVoiceRecording({ discard: true });
    return;
  }
  resetVoiceState();
}

async function startVoiceRecording() {
  if (isCurrentSessionArchived()) {
    return;
  }
  if (!isSocketConnected()) {
    appendSystemNotice('Voice command is unavailable while reconnecting.');
    setLifecyclePhase(EXECUTION_PHASES.RECONNECTING, {
      text: 'Reconnect in progress…',
      detail: 'Wait for the live session to reconnect before starting the microphone.',
    });
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    appendSystemNotice('This environment does not support microphone capture.');
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Voice command unavailable',
      detail: 'Microphone access is not available in this runtime.',
    });
    return;
  }

  const mimeType = pickVoiceMimeType();
  try {
    voiceStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    voiceChunks = [];
    voiceDiscardOnStop = false;
    voiceRecorder = mimeType
      ? new MediaRecorder(voiceStream, { mimeType })
      : new MediaRecorder(voiceStream);
    const recordedMimeType = voiceRecorder.mimeType || mimeType || 'audio/webm';

    voiceRecorder.addEventListener('dataavailable', (event) => {
      if (event.data && event.data.size > 0) {
        voiceChunks.push(event.data);
      }
    });
    voiceRecorder.addEventListener('stop', () => {
      void finalizeVoiceRecording(recordedMimeType);
    });

    isVoiceRecording = true;
    isVoiceTranscribing = false;
    updateVoiceButtonState();

    voiceRecorder.start(1000);
  } catch (error) {
    resetVoiceState();
    const detail = error instanceof Error ? error.message : 'Microphone access was denied.';
    appendSystemNotice('Microphone access was not available.');
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Voice command unavailable',
      detail,
    });
  }
}

async function toggleVoiceRecording() {
  if (isVoiceTranscribing) {
    return;
  }
  if (isVoiceRecording) {
    stopVoiceRecording();
    return;
  }
  await startVoiceRecording();
}

function handleVoiceTranscriptionResult(payload) {
  if (payload?.requestId && payload.requestId !== pendingVoiceRequestId) {
    return;
  }
  pendingVoiceRequestId = '';
  isVoiceTranscribing = false;
  updateVoiceButtonState();

  const transcript = typeof payload?.text === 'string' ? payload.text.trim() : '';
  if (!transcript) {
    appendSystemNotice('No speech was detected in the microphone input.');
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Voice command unavailable',
      detail: 'No speech was detected in the recording. Try again and speak a little closer to the mic.',
    });
    return;
  }

  if (commandInput) {
    commandInput.value = mergeTranscriptIntoDraft(transcript);
    commandInput.dispatchEvent(new Event('input', { bubbles: true }));
    commandInput.selectionStart = commandInput.value.length;
    commandInput.selectionEnd = commandInput.value.length;
  }
  resizeInput();
  focusCommandInput();
}

function handleVoiceTranscriptionError(payload) {
  if (payload?.requestId && payload.requestId !== pendingVoiceRequestId) {
    return;
  }
  pendingVoiceRequestId = '';
  isVoiceTranscribing = false;
  updateVoiceButtonState();
  const detail = typeof payload?.error === 'string' && payload.error.trim()
    ? payload.error.trim()
    : 'Voice transcription could not be completed.';
  appendSystemNotice('Voice transcription failed.');
  setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
    text: 'Voice command unavailable',
    detail,
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void connectSocket();
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 1.5, 5000);
}

function handleStopUi(detailText, options = {}) {
  const shouldAddMessage = options.addSystemMessage !== false;

  activeTerminalRunning = false;
  if (activeTerminalSessionId) {
    showTerminalPanel();
    setTerminalMeta(options.pending ? 'Stopping terminal…' : 'Stopped');
    appendTerminalTranscript(options.pending
      ? '[stop requested] Stop signal sent from chat controls.'
      : '[stopped] Stop signal received.');
  }

  clearPendingAssistant();

  if (shouldAddMessage) {
    appendSystemNotice(options.pending ? 'Stopping active work.' : 'Stopped all running actions.');
  }

  setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
    text: options.pending ? 'Stopping active work…' : 'Stopped',
    detail: detailText,
  });

  updateActionAvailability();
  renderConversationDecorators();
}

async function connectSocket() {
  const target = await getSocketTarget();
  const wsUrl = `ws://${target.host}:${target.port}`;
  socket = new WebSocket(wsUrl);

  socket.addEventListener('open', () => {
    reconnectDelay = 500;
    updateVoiceButtonState();
    setReadyLifecycle();
  });

  socket.addEventListener('close', () => {
    if (isVoiceRecording) {
      cancelVoiceCapture();
    } else if (isVoiceTranscribing) {
      pendingVoiceRequestId = '';
      isVoiceTranscribing = false;
    }
    updateVoiceButtonState();
    setLifecyclePhase(EXECUTION_PHASES.RECONNECTING, {
      text: 'Reconnect in progress…',
      detail: 'Trying to restore the live session.',
    });
    scheduleReconnect();
  });

  socket.addEventListener('error', () => {
    // Keep reconnect behavior on close.
  });

  socket.addEventListener('message', (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }

    if (payload.event === 'voice_transcription_result') {
      handleVoiceTranscriptionResult(payload);
      return;
    }

    if (payload.event === 'voice_transcription_error') {
      handleVoiceTranscriptionError(payload);
      return;
    }

    if (payload.command === 'draw_text' && payload.id === 'direct_response') {
      if (!shouldDisplayReplyInChat(payload)) {
        clearPendingAssistant();
        return;
      }
      finalizePendingAssistant(payload.text || '');
      return;
    }

    if (payload.command === 'show_status_bubble' || payload.command === 'update_status_bubble') {
      const snapshot = setLifecycleFromRawText(payload.text || '', {
        source: payload.source,
        theme: payload.theme,
        phaseHint: EXECUTION_PHASES.RUNNING,
      });
      if (shouldDisplayReplyInChat(payload)) {
        updatePendingAssistantStatus(snapshot.text);
      }
      return;
    }

    if (payload.command === 'complete_status_bubble') {
      const responseText = payload.responseText || payload.text || '';
      if (shouldDisplayReplyInChat(payload)) {
        finalizePendingAssistant(responseText);
      } else {
        clearPendingAssistant();
      }

      setLifecyclePhase(EXECUTION_PHASES.COMPLETED, {
        text: 'Completed',
        detail: responseText ? 'Latest response is ready.' : 'The latest action finished successfully.',
      });
      return;
    }

    if (payload.command === 'hide_status_bubble') {
      setReadyLifecycle();
      return;
    }

    if (payload.command === 'terminal_session_event') {
      handleTerminalSessionEvent(payload);
    }
  });
}

function hideInputWindow() {
  if (window.api?.hideInputWindow) {
    window.api.hideInputWindow();
  }
}

function submitCommand() {
  if (isCurrentSessionArchived()) {
    setLifecyclePhase(EXECUTION_PHASES.IDLE, {
      text: 'Viewing archived chat',
      detail: 'Archived chats are read-only until you start a new chat.',
    });
    return;
  }

  const text = (commandInput?.value || '').trim();
  if (!text) {
    return;
  }

  if (activeTerminalRunning && isTerminalStopRequest(text)) {
    appendMessage('user', text, { pending: false, persist: true });
    if (window.api?.requestStopAll) {
      window.api.requestStopAll();
    }
    handleStopUi('Interrupting the terminal session now.', {
      pending: true,
      addSystemMessage: true,
    });
    commandInput.value = '';
    resizeInput();
    focusCommandInput();
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
  appendMessage('user', text, { pending: false, persist: true, ts: now });
  pendingAssistantEl = appendMessage('assistant', 'Capturing screen…', {
    pending: true,
    persist: false,
    ts: now,
  });
  setLifecyclePhase(EXECUTION_PHASES.PREPARING, {
    text: 'Capturing screen…',
    detail: 'Collecting the current workspace before routing your request.',
  });
  updateActionAvailability();

  const screenshotQueued = sendMessage({ event: 'capture_screenshot' });
  const requestQueued = sendMessage({
    event: 'overlay_input',
    text,
    requestId: `overlay_${now}_${Math.random().toString(16).slice(2, 8)}`,
  });

  if (!screenshotQueued || !requestQueued) {
    clearPendingAssistant();
    appendSystemNotice('Unable to send the request while reconnecting.');
    setLifecyclePhase(EXECUTION_PHASES.RECONNECTING, {
      text: 'Reconnect in progress…',
      detail: 'The live session is unavailable. Try again once the connection returns.',
    });
    updateActionAvailability();
    return;
  }

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
    event.stopPropagation();
    handleEscapeKey();
  }
});
commandVoice?.addEventListener('click', () => {
  void toggleVoiceRecording();
});
commandSend?.addEventListener('click', () => submitCommand());
chatHide?.addEventListener('click', () => hideInputWindow());
chatShortcutsToggle?.addEventListener('click', (event) => {
  event.stopPropagation();
  toggleShortcutsPopover();
});
chatHistoryToggle?.addEventListener('click', () => toggleHistoryPanel());
historyPanelClose?.addEventListener('click', () => closeHistoryPanel());
historyFilterActive?.addEventListener('click', () => {
  historyFilter = 'active';
  renderHistoryList();
});
historyFilterArchived?.addEventListener('click', () => {
  historyFilter = 'archived';
  renderHistoryList();
});
chatNew?.addEventListener('click', () => {
  closeShortcutsPopover();
  void createNewChat();
});
chatStop?.addEventListener('click', () => {
  closeShortcutsPopover();
  if (window.api?.requestStopAll) {
    window.api.requestStopAll();
  }
  handleStopUi('Interrupting running actions now.', {
    pending: true,
    addSystemMessage: true,
  });
  focusCommandInput();
});

terminalPanelStop?.addEventListener('click', () => {
  if (window.api?.requestStopAll) {
    window.api.requestStopAll();
  }
  handleStopUi('Interrupting the terminal session now.', {
    pending: true,
    addSystemMessage: true,
  });
  focusCommandInput();
});

document.addEventListener('pointerdown', (event) => {
  if (!isShortcutsPopoverOpen() || !chatShortcutsMenu) return;
  if (chatShortcutsMenu.contains(event.target)) return;
  closeShortcutsPopover();
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  event.preventDefault();
  handleEscapeKey({ restoreShortcutFocus: true });
});

if (window.api?.onShowInputWindow) {
  window.api.onShowInputWindow(() => {
    if (!hasActiveWork()) {
      void refreshChatSessionState(currentSession?.sessionId || null, { keepHistoryOpen: isHistoryOpen });
    }
    requestAnimationFrame(() => {
      if (!isHistoryOpen) {
        focusCommandInput();
      }
    });
  });
}

if (window.api?.onHideInputWindow) {
  window.api.onHideInputWindow(() => {
    cancelVoiceCapture();
    closeShortcutsPopover();
    setReadyLifecycle();
  });
}

if (window.api?.onStopAll) {
  window.api.onStopAll(() => {
    handleStopUi('All running actions were interrupted.', {
      pending: false,
      addSystemMessage: true,
    });
  });
}

window.addEventListener('beforeunload', () => {
  cancelVoiceCapture();
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  void persistChatHistoryNow();
});

async function initializeInputWindow() {
  updateShortcutUi();
  resizeInput();
  updateHistoryRetentionCopy();
  updateComposerState();
  updateActionAvailability();
  closeHistoryPanel();
  renderConversationDecorators();
  setLifecyclePhase(EXECUTION_PHASES.PREPARING, {
    text: 'Restoring session…',
    detail: 'Loading the latest chat session.',
  });
  await refreshChatSessionState(null, { keepHistoryOpen: false });
  setLifecyclePhase(EXECUTION_PHASES.RECONNECTING, {
    text: 'Reconnect in progress…',
    detail: 'Connecting to the live session.',
  });
  await connectSocket();
}

void initializeInputWindow();
