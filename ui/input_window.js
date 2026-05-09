import {
  EXECUTION_PHASES,
  buildLifecycleSnapshot,
  getShortcutLabels,
  inferLifecycleSnapshot,
} from './status_lifecycle.js';
import {
  createAgentWorkTraceState,
  isAgentTraceSource,
  normalizeAgentTraceSnapshot,
} from './agent_work_trace.mjs';
import {
  buildGeneratingIndicatorView,
  isGeneratingPlaceholderText,
} from './generating_indicator.mjs';
import { getAssistantLifecycleOutcome } from './chat_outcome.mjs';

const commandInput = document.getElementById('command-input');
const commandSend = document.getElementById('command-send');
const commandVoice = document.getElementById('command-voice');
const chatMessages = document.getElementById('chat-messages');
const chatStatus = document.getElementById('chat-status');
const chatStatusPhase = document.getElementById('chat-status-phase');
const chatStatusText = document.getElementById('chat-status-text');
const chatStatusDetail = document.getElementById('chat-status-detail');
const chatSettingsMenu = document.getElementById('chat-settings-menu');
const chatSettingsToggle = document.getElementById('chat-settings-toggle');
const chatSettingsPopover = document.getElementById('chat-settings-popover');
const chatSettingsHelp = document.getElementById('chat-settings-help');
const chatSettingsHistory = document.getElementById('chat-settings-history');
const chatHelpPanel = document.getElementById('chat-help-panel');
const chatNew = document.getElementById('chat-new');
const chatBody = document.getElementById('chat-body');
const chatMain = document.getElementById('chat-main');
const historyPanel = document.getElementById('history-panel');
const historyPanelHeader = document.getElementById('history-panel-header');
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
const terminalPanel = document.getElementById('terminal-panel');
const terminalPanelMeta = document.getElementById('terminal-panel-meta');
const terminalPanelOutput = document.getElementById('terminal-panel-output');
const terminalPanelToggle = document.getElementById('terminal-panel-toggle');
const terminalPanelStop = document.getElementById('terminal-panel-stop');

const platform = window.api?.getPlatform ? window.api.getPlatform() : 'win32';
const shortcuts = getShortcutLabels(platform);

const MAX_INPUT_HEIGHT = 140;
const DUPLICATE_WINDOW_MS = 1200;
const MAX_PERSISTED_MESSAGES = 300;
const SESSION_SAVE_DEBOUNCE_MS = 250;
const MAX_ASSISTANT_CACHE = 120;
const MAX_MESSAGE_ARTIFACTS = 4;
const MAX_IMAGE_DATA_URL_CHARS = 8_000_000;
const ASSISTANT_THINKING_TEXT = 'Waiting for model response…';
const CHAT_REPLY_SOURCES = new Set(['rapid_response']);
const MAX_TERMINAL_TRANSCRIPT_CHARS = 16000;
const MAX_TERMINAL_SUMMARY_SOURCE_CHARS = 2200;
const MAX_TERMINAL_SUMMARY_CHARS = 360;
const DEFAULT_INPUT_PLACEHOLDER = 'Describe the next task for JARVIS…';
const ARCHIVED_INPUT_PLACEHOLDER = 'Archived chats are read-only. Start a new chat to continue.';
const VOICE_MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
const RESTORE_CHAT_SYMBOL = '↩';
const DELETE_CHAT_SYMBOL = '🗑';

let socket;
let reconnectDelay = 500;
let reconnectTimer = null;
let lastSubmittedText = '';
let lastSubmittedAt = 0;
let pendingAssistantEl = null;
let pendingAssistantStartedAt = 0;
let pendingAssistantStatusText = '';
let pendingAssistantTicker = null;
let lastAssistantText = '';
let saveTimer = null;
let isHydratingSession = false;
let activeTerminalSessionId = '';
let activeTerminalRunning = false;
let isTerminalPanelMinimized = true;
let terminalChatBuffer = [];
let terminalChatReady = false;
let terminalChatCommand = '';
let terminalChatStatus = 'idle';
let pendingTerminalSummaryEl = null;
let terminalSummaryPersisted = false;
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
let visionChatHiddenForCapture = false;
let visionArtifactViewerEl = null;
let agentWorkTraceEl = null;
let agentWorkTraceToggleEl = null;
let agentWorkTraceBodyEl = null;
let agentWorkTraceSummaryEl = null;
let agentWorkTraceStatusEl = null;
let agentWorkTraceListEl = null;
let agentWorkTraceId = 0;
let pendingDeleteSession = null;
let deleteConfirmOverlay = null;
let deleteConfirmDialog = null;
let deleteConfirmTitle = null;
let deleteConfirmBody = null;
let deleteConfirmCancelButton = null;
let deleteConfirmDeleteButton = null;
let deleteConfirmReturnFocus = null;
let historyDeleteAllArchived = null;

const assistantMessageCache = [];
const chatHistory = [];
const agentWorkTrace = createAgentWorkTraceState();

function normalizeAgentSource(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function shouldDisplayReplyInChat(payload) {
  const source = normalizeAgentSource(payload?.source);
  if (!source) return true;
  return CHAT_REPLY_SOURCES.has(source);
}

function normalizeTerminalText(value, maxChars = MAX_TERMINAL_TRANSCRIPT_CHARS) {
  const text = typeof value === 'string' ? value.replace(/\r\n/g, '\n').trim() : '';
  if (!text) return '';
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 18).trimEnd()}\n...[truncated]...`;
}

function truncateTerminalChatText(value) {
  return normalizeTerminalText(value, MAX_TERMINAL_SUMMARY_SOURCE_CHARS);
}

function pushTerminalChatLine(text) {
  const value = truncateTerminalChatText(text);
  if (!value) return;
  terminalChatBuffer.push(value);
}

function resetTerminalChatSummary() {
  terminalChatBuffer = [];
  terminalChatReady = false;
  terminalChatCommand = '';
  terminalChatStatus = 'idle';
  pendingTerminalSummaryEl = null;
  terminalSummaryPersisted = false;
}

function getTerminalStatusLabel(status) {
  if (status === 'failed') return 'Failed';
  if (status === 'stopped') return 'Stopped';
  if (status === 'stopping') return 'Stopping';
  if (status === 'running') return 'Running';
  return 'Completed';
}

function getTerminalSummaryPreview() {
  const source = normalizeTerminalText(terminalChatBuffer.join('\n\n'), MAX_TERMINAL_SUMMARY_SOURCE_CHARS);
  if (!source) return '';

  const lines = source
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith('$ ') && !/^cli session started\.?$/i.test(line));

  const packetLine = lines.find((line) => /packets:\s*sent\s*=/i.test(line));
  const timingLine = lines.find((line) => /minimum\s*=.*maximum\s*=.*average\s*=/i.test(line));
  if (packetLine || timingLine) {
    return [packetLine, timingLine].filter(Boolean).join('\n');
  }

  const failureLine = lines.find((line) => /error|failed|denied|not recognized|not found|timed out|could not|cannot/i.test(line));
  if (failureLine) {
    return truncateText(failureLine, MAX_TERMINAL_SUMMARY_CHARS);
  }

  const interestingLines = lines
    .filter((line) => !/^reply from /i.test(line))
    .slice(-2);

  return truncateText(interestingLines.join('\n'), MAX_TERMINAL_SUMMARY_CHARS);
}

function buildTerminalChatSummary(status = terminalChatStatus) {
  const label = getTerminalStatusLabel(status);
  const command = terminalChatCommand ? `$ ${terminalChatCommand}` : 'Shell command';
  const preview = getTerminalSummaryPreview();
  return preview ? `${label}: ${command}\n${preview}` : `${label}: ${command}`;
}

function isTerminalSummaryPending(status) {
  return status === 'running' || status === 'stopping';
}

function updateTerminalChatSummary(status = terminalChatStatus, options = {}) {
  terminalChatStatus = status || terminalChatStatus || 'completed';
  const text = buildTerminalChatSummary(terminalChatStatus);
  if (!text) return;

  const ts = Date.now();
  const pending = isTerminalSummaryPending(terminalChatStatus);

  if (pendingTerminalSummaryEl && pendingTerminalSummaryEl.isConnected) {
    setMessageElementText(pendingTerminalSummaryEl, text, { role: 'terminal', pending, ts });
  } else {
    pendingTerminalSummaryEl = appendMessage('terminal', text, { pending, persist: false, ts });
  }

  if (options.persist && !pending && !terminalSummaryPersisted) {
    const message = rememberMessage('terminal', text, ts);
    if (message) {
      terminalSummaryPersisted = true;
      syncCurrentSessionMetadataFromHistory(message.ts);
      queuePersistChatHistory();
    }
  }

  renderConversationDecorators();
}

function finalizeTerminalChatSummary(status = terminalChatStatus) {
  if (!terminalChatReady && !pendingTerminalSummaryEl) {
    return;
  }
  updateTerminalChatSummary(status || 'completed', { persist: true });
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
  return chatHistory.map((message) => {
    const cloned = { ...message };
    if (message.agentTrace) {
      cloned.agentTrace = normalizeAgentTraceSnapshot(message.agentTrace);
    }
    if (Array.isArray(message.artifacts)) {
      cloned.artifacts = message.artifacts
        .map(normalizeVisionArtifact)
        .filter(Boolean)
        .slice(0, MAX_MESSAGE_ARTIFACTS);
    }
    return cloned;
  });
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

function normalizeVisionArtifact(artifact) {
  if (!artifact || typeof artifact !== 'object') return null;
  const kind = typeof artifact.kind === 'string' ? artifact.kind.trim() : '';
  const imageDataUrl = typeof artifact.imageDataUrl === 'string' ? artifact.imageDataUrl.trim() : '';
  if (kind !== 'vision_screenshot') return null;
  if (!imageDataUrl.startsWith('data:image/png;base64,')) return null;
  if (imageDataUrl.length > MAX_IMAGE_DATA_URL_CHARS) return null;

  const width = Number(artifact.width);
  const height = Number(artifact.height);
  const outlineCount = Number(artifact.outlineCount);
  return {
    kind,
    title: truncateText(artifact.title || '', 80) || 'Analyzed screen',
    imageDataUrl,
    width: Number.isFinite(width) && width > 0 ? Math.round(width) : 0,
    height: Number.isFinite(height) && height > 0 ? Math.round(height) : 0,
    outlineCount: Number.isFinite(outlineCount) && outlineCount > 0 ? Math.round(outlineCount) : 0,
  };
}

function normalizeMessageArtifacts(artifacts) {
  if (!Array.isArray(artifacts)) return [];
  return artifacts
    .map(normalizeVisionArtifact)
    .filter(Boolean)
    .slice(0, MAX_MESSAGE_ARTIFACTS);
}

function normalizePersistedMessage(role, text, ts = Date.now(), extras = {}) {
  const normalizedRole = typeof role === 'string' ? role.trim().toLowerCase() : '';
  const normalizedText = typeof text === 'string' ? text.trim() : '';
  const normalizedTs = Number.isFinite(ts) ? Number(ts) : Date.now();
  if (!normalizedRole || !normalizedText) return null;
  if (!['user', 'assistant', 'system', 'terminal'].includes(normalizedRole)) return null;
  const message = { role: normalizedRole, text: normalizedText, ts: normalizedTs };
  const agentTrace = normalizedRole === 'assistant'
    ? normalizeAgentTraceSnapshot(extras.agentTrace)
    : null;
  if (agentTrace) {
    message.agentTrace = agentTrace;
  }
  const artifacts = normalizedRole === 'assistant'
    ? normalizeMessageArtifacts(extras.artifacts)
    : [];
  if (artifacts.length > 0) {
    message.artifacts = artifacts;
  }
  return message;
}

function normalizeSession(session) {
  if (!session || typeof session !== 'object') return null;
  const messages = Array.isArray(session.messages)
    ? session.messages
      .map((item) => normalizePersistedMessage(item.role, item.text, item.ts, {
        agentTrace: item.agentTrace,
        artifacts: item.artifacts,
      }))
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
  if (terminalPanelStop) {
    terminalPanelStop.disabled = !activeTerminalRunning;
  }
  if (terminalPanel) {
    terminalPanel.dataset.running = activeTerminalRunning ? 'true' : 'false';
  }
  updateComposerActionState();
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

  if (chatSettingsToggle) {
    chatSettingsToggle.title = 'Open settings menu';
  }
  if (chatNew) {
    chatNew.title = 'Start a new chat';
  }
  if (commandVoice) {
    commandVoice.title = 'Record voice command';
  }
  updateComposerActionState();
  if (terminalPanelStop) {
    terminalPanelStop.title = `Stop terminal session (${shortcuts.stop})`;
  }
}

function updateComposerActionState() {
  if (!commandSend) return;
  const hasWork = hasActiveWork();
  commandSend.dataset.mode = hasWork ? 'stop' : 'send';
  commandSend.title = hasWork ? `Stop running actions (${shortcuts.stop})` : 'Send command (Enter)';
  commandSend.setAttribute('aria-label', hasWork ? 'Stop running actions' : 'Send command');
  commandSend.disabled = isCurrentSessionArchived() && !hasWork;
}

function isSettingsPopoverOpen() {
  return Boolean(chatSettingsPopover && !chatSettingsPopover.hidden);
}

function resetSettingsHelpPanel() {
  if (chatHelpPanel) {
    chatHelpPanel.hidden = true;
  }
  if (chatSettingsHelp) {
    chatSettingsHelp.setAttribute('aria-expanded', 'false');
  }
}

function openSettingsPopover() {
  if (!chatSettingsPopover) return;
  chatSettingsPopover.hidden = false;
  resetSettingsHelpPanel();
  if (chatSettingsToggle) {
    chatSettingsToggle.setAttribute('aria-expanded', 'true');
  }
}

function closeSettingsPopover(options = {}) {
  if (!chatSettingsPopover) return;
  const { restoreFocus = false } = options;
  chatSettingsPopover.hidden = true;
  resetSettingsHelpPanel();
  if (chatSettingsToggle) {
    chatSettingsToggle.setAttribute('aria-expanded', 'false');
    if (restoreFocus) {
      chatSettingsToggle.focus();
    }
  }
}

function toggleSettingsPopover() {
  if (isSettingsPopoverOpen()) {
    closeSettingsPopover();
    return;
  }
  openSettingsPopover();
}

function showSettingsHelp() {
  if (!chatHelpPanel) return;
  const isOpen = !chatHelpPanel.hidden;
  chatHelpPanel.hidden = isOpen;
  if (chatSettingsHelp) {
    chatSettingsHelp.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
  }
}

function handleEscapeKey(options = {}) {
  const { restoreSettingsFocus = false, restoreShortcutFocus = false } = options;
  if (isSettingsPopoverOpen()) {
    closeSettingsPopover({ restoreFocus: restoreSettingsFocus || restoreShortcutFocus });
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

function updateTerminalPanelControls() {
  const expanded = !isTerminalPanelMinimized;
  if (terminalPanel) {
    terminalPanel.dataset.state = expanded ? 'expanded' : 'minimized';
    terminalPanel.dataset.running = activeTerminalRunning ? 'true' : 'false';
  }
  if (terminalPanelOutput) {
    terminalPanelOutput.setAttribute('aria-hidden', expanded ? 'false' : 'true');
  }
  if (terminalPanelToggle) {
    terminalPanelToggle.textContent = expanded ? 'Minimize' : 'Expand';
    terminalPanelToggle.title = expanded ? 'Minimize terminal output' : 'Expand terminal output';
    terminalPanelToggle.setAttribute(
      'aria-label',
      expanded ? 'Minimize terminal output' : 'Expand terminal output',
    );
    terminalPanelToggle.setAttribute('aria-expanded', String(expanded));
  }
}

function setTerminalPanelMinimized(minimized) {
  isTerminalPanelMinimized = Boolean(minimized);
  updateTerminalPanelControls();
  if (!isTerminalPanelMinimized) {
    scrollTerminalToBottom();
  }
}

function showTerminalPanel() {
  if (terminalPanel) {
    terminalPanel.hidden = false;
    updateTerminalPanelControls();
  }
}

function hideTerminalPanel() {
  if (terminalPanel) {
    terminalPanel.hidden = true;
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
  isTerminalPanelMinimized = true;
  resetTerminalChatSummary();
  clearTerminalTranscript();
  setTerminalMeta('Waiting for CLI activity...');
  if (hide && terminalPanel) {
    hideTerminalPanel();
  }
  updateTerminalPanelControls();
  updateActionAvailability();
}

function ensureTerminalSession(sessionId) {
  const nextId = typeof sessionId === 'string' ? sessionId.trim() : '';
  const isNewTerminalSession = nextId && activeTerminalSessionId !== nextId;
  if (nextId && activeTerminalSessionId && activeTerminalSessionId !== nextId) {
    clearTerminalTranscript();
    resetTerminalChatSummary();
  }
  if (nextId) {
    activeTerminalSessionId = nextId;
  }
  if (isNewTerminalSession) {
    isTerminalPanelMinimized = true;
  }
  showTerminalPanel();
}

function finishTerminalPanel() {
  setTerminalPanelMinimized(true);
  updateTerminalPanelControls();
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
    resetTerminalChatSummary();
    terminalChatStatus = 'running';
    updateActionAvailability();
  } else if (kind === 'command_started') {
    activeTerminalRunning = true;
    terminalChatCommand = shellCommand;
    setTerminalMeta(shellCommand ? `Running: ${shellCommand}` : 'Running shell command...');
    appendTerminalTranscript(shellCommand ? `$ ${shellCommand}` : '$ [shell command]');
    pushTerminalChatLine(shellCommand ? `$ ${shellCommand}` : '$ [shell command]');
    updateTerminalChatSummary('running');
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
      finalizeTerminalChatSummary('failed');
      finishTerminalPanel();
    } else {
      setTerminalMeta('Command completed.');
      appendTerminalTranscript(transcript);
      pushTerminalChatLine(transcript);
      updateTerminalChatSummary('running');
    }
  } else if (kind === 'session_finished') {
    activeTerminalRunning = false;
    setTerminalMeta(text || 'CLI session finished.');
    if (text) {
      appendTerminalTranscript(`[done] ${text}`);
    }
    terminalChatReady = true;
    updateActionAvailability();
    finalizeTerminalChatSummary('completed');
    finishTerminalPanel();
  } else if (kind === 'session_error') {
    activeTerminalRunning = false;
    setTerminalMeta(text || 'CLI session failed.');
    appendTerminalTranscript(`[session error]\n${text || 'CLI session failed.'}`);
    pushTerminalChatLine(`[session error]\n${text || 'CLI session failed.'}`);
    terminalChatReady = true;
    updateActionAvailability();
    finalizeTerminalChatSummary('failed');
    finishTerminalPanel();
  } else if (kind === 'session_stopped') {
    activeTerminalRunning = false;
    setTerminalMeta(text || 'Terminal session stopped.');
    appendTerminalTranscript(`[stopped] ${text || 'Terminal session stopped.'}`);
    pushTerminalChatLine(`[stopped] ${text || 'Terminal session stopped.'}`);
    terminalChatReady = true;
    updateActionAvailability();
    finalizeTerminalChatSummary('stopped');
    finishTerminalPanel();
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

function stopPendingAssistantTicker() {
  if (pendingAssistantTicker) {
    clearInterval(pendingAssistantTicker);
    pendingAssistantTicker = null;
  }
  pendingAssistantStartedAt = 0;
  pendingAssistantStatusText = '';
}

function renderGeneratingIndicatorContent(content, statusText) {
  if (!content) return;
  if (!pendingAssistantStartedAt) {
    pendingAssistantStartedAt = Date.now();
  }
  pendingAssistantStatusText = typeof statusText === 'string' ? statusText.trim() : '';

  const view = buildGeneratingIndicatorView({
    elapsedMs: Date.now() - pendingAssistantStartedAt,
    statusText: pendingAssistantStatusText,
  });

  const wrapper = document.createElement('span');
  wrapper.className = 'chat-generating-indicator';
  wrapper.setAttribute('aria-label', view.ariaLabel);

  const label = document.createElement('span');
  label.className = 'chat-generating-label';
  label.textContent = view.label;
  wrapper.appendChild(label);

  const dots = document.createElement('span');
  dots.className = 'chat-generating-dots';
  dots.setAttribute('aria-hidden', 'true');
  for (let index = 0; index < view.dotCount; index += 1) {
    const dot = document.createElement('span');
    dot.className = 'chat-generating-dot';
    dot.style.animationDelay = `${index * 140}ms`;
    dots.appendChild(dot);
  }
  wrapper.appendChild(dots);

  content.replaceChildren(wrapper);
  content.classList.add('chat-msg-content--generating');
}

function ensurePendingAssistantTicker() {
  if (pendingAssistantTicker) return;
  pendingAssistantTicker = setInterval(() => {
    if (!pendingAssistantEl || !pendingAssistantEl.isConnected) {
      stopPendingAssistantTicker();
      return;
    }
    setMessageElementText(pendingAssistantEl, pendingAssistantStatusText || ASSISTANT_THINKING_TEXT, {
      role: 'assistant',
      pending: true,
    });
  }, 1500);
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

  if (content && role === 'assistant' && pending) {
    renderGeneratingIndicatorContent(content, value);
    ensurePendingAssistantTicker();
  } else if (content) {
    content.classList.remove('chat-msg-content--generating');
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
  el.classList.toggle('chat-msg-generating', role === 'assistant' && pending);
  if (!(role === 'assistant' && pending) && (el === pendingAssistantEl || el.classList.contains('chat-msg-generating'))) {
    stopPendingAssistantTicker();
  }
}

function ensureVisionArtifactViewer() {
  if (visionArtifactViewerEl) return visionArtifactViewerEl;

  const viewer = document.createElement('div');
  viewer.className = 'chat-vision-viewer';
  viewer.hidden = true;
  viewer.setAttribute('role', 'dialog');
  viewer.setAttribute('aria-modal', 'true');
  viewer.setAttribute('aria-label', 'Analyzed screenshot');

  const dialog = document.createElement('div');
  dialog.className = 'chat-vision-viewer__dialog';

  const closeButton = document.createElement('button');
  closeButton.type = 'button';
  closeButton.className = 'chat-vision-viewer__close';
  closeButton.textContent = 'X';
  closeButton.title = 'Close screenshot';
  closeButton.setAttribute('aria-label', 'Close screenshot');
  closeButton.addEventListener('click', () => closeVisionArtifactViewer());

  const image = document.createElement('img');
  image.className = 'chat-vision-viewer__image';
  image.alt = 'Analyzed screen screenshot';

  dialog.appendChild(closeButton);
  dialog.appendChild(image);
  viewer.appendChild(dialog);
  viewer.addEventListener('click', (event) => {
    if (event.target === viewer) {
      closeVisionArtifactViewer();
    }
  });

  document.body.appendChild(viewer);
  visionArtifactViewerEl = viewer;
  return viewer;
}

function isVisionArtifactViewerOpen() {
  return Boolean(visionArtifactViewerEl && !visionArtifactViewerEl.hidden);
}

function closeVisionArtifactViewer() {
  if (!visionArtifactViewerEl) return;
  const image = visionArtifactViewerEl.querySelector('.chat-vision-viewer__image');
  if (image) {
    image.removeAttribute('src');
  }
  visionArtifactViewerEl.hidden = true;
}

function openVisionArtifactViewer(artifact) {
  const normalized = normalizeVisionArtifact(artifact);
  if (!normalized) return;

  const viewer = ensureVisionArtifactViewer();
  const image = viewer.querySelector('.chat-vision-viewer__image');
  if (image) {
    image.src = normalized.imageDataUrl;
    image.alt = normalized.outlineCount > 0
      ? `Analyzed screen screenshot with ${normalized.outlineCount} outlined components`
      : 'Analyzed screen screenshot';
    if (normalized.width > 0) {
      image.width = normalized.width;
    } else {
      image.removeAttribute('width');
    }
    if (normalized.height > 0) {
      image.height = normalized.height;
    } else {
      image.removeAttribute('height');
    }
  }
  viewer.hidden = false;
  viewer.querySelector('.chat-vision-viewer__close')?.focus();
}

async function openVisionArtifactImage(artifact) {
  const normalized = normalizeVisionArtifact(artifact);
  if (!normalized) return;

  if (window.api?.openVisionArtifactImage) {
    try {
      const result = await window.api.openVisionArtifactImage(normalized.imageDataUrl);
      if (result?.opened) {
        return;
      }
    } catch {
      // Fall back to the embedded viewer when the native bridge is unavailable.
    }
  }

  openVisionArtifactViewer(normalized);
}

function createVisionArtifactElement(artifact) {
  const normalized = normalizeVisionArtifact(artifact);
  if (!normalized) return null;

  const figure = document.createElement('figure');
  figure.className = 'chat-vision-artifact';

  const imageWrap = document.createElement('button');
  imageWrap.type = 'button';
  imageWrap.className = 'chat-vision-artifact__frame chat-vision-artifact__open';
  imageWrap.title = 'Open screenshot';
  imageWrap.setAttribute('aria-label', 'Open analyzed screenshot');
  imageWrap.addEventListener('click', () => {
    void openVisionArtifactImage(normalized);
  });

  const image = document.createElement('img');
  image.className = 'chat-vision-artifact__image';
  image.src = normalized.imageDataUrl;
  image.alt = normalized.outlineCount > 0
    ? `Analyzed screen screenshot with ${normalized.outlineCount} outlined components`
    : 'Analyzed screen screenshot';
  image.loading = 'lazy';
  image.decoding = 'async';
  if (normalized.width > 0) {
    image.width = normalized.width;
  }
  if (normalized.height > 0) {
    image.height = normalized.height;
  }

  imageWrap.appendChild(image);
  figure.appendChild(imageWrap);
  return figure;
}

function setMessageElementArtifacts(el, artifacts) {
  if (!el) return;
  const normalizedArtifacts = normalizeMessageArtifacts(artifacts);
  el.querySelectorAll('.chat-msg-artifacts').forEach((node) => node.remove());
  el.classList.toggle('chat-msg--with-artifacts', normalizedArtifacts.length > 0);
  if (normalizedArtifacts.length === 0) return;

  const artifactList = document.createElement('div');
  artifactList.className = 'chat-msg-artifacts';
  for (const artifact of normalizedArtifacts) {
    const artifactEl = createVisionArtifactElement(artifact);
    if (artifactEl) {
      artifactList.appendChild(artifactEl);
    }
  }
  if (artifactList.childElementCount > 0) {
    el.appendChild(artifactList);
  }
}

function createMessageElement(role, text, options = {}) {
  if (!chatMessages) return null;
  const value = typeof text === 'string' ? text.trim() : '';
  if (!value) return null;

  const pending = Boolean(options.pending);
  const ts = Number.isFinite(options.ts) ? Number(options.ts) : Date.now();
  const agentTrace = role === 'assistant'
    ? normalizeAgentTraceSnapshot(options.agentTrace)
    : null;
  const artifacts = role === 'assistant'
    ? normalizeMessageArtifacts(options.artifacts)
    : [];

  const el = document.createElement('article');
  el.className = `chat-msg ${role}${pending ? ' pending' : ''}${artifacts.length ? ' chat-msg--with-artifacts' : ''}`;

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
  setMessageElementArtifacts(el, artifacts);
  if (agentTrace) {
    appendStoredAgentWorkTrace(el, agentTrace);
  }
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

function rememberMessage(role, text, ts = Date.now(), extras = {}) {
  const entry = normalizePersistedMessage(role, text, ts, extras);
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
  const {
    pending = false,
    persist = true,
    ts = Date.now(),
    agentTrace = null,
    artifacts = [],
  } = options;
  const el = createMessageElement(role, text, { pending, ts, agentTrace, artifacts });
  if (!el) return null;

  if (persist && !pending) {
    const message = rememberMessage(role, text, ts, { agentTrace, artifacts });
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

function getAgentWorkTraceStatusLabel(status) {
  if (status === 'failed') return 'Needs attention';
  if (status === 'completed') return 'Done';
  if (status === 'running') return 'Running';
  return 'Idle';
}

function setAgentWorkTraceSectionOpen(section, toggle, body, isOpen) {
  if (!section || !body || !toggle) return;
  section.dataset.open = isOpen ? 'true' : 'false';
  toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  body.hidden = !isOpen;
}

function createAgentWorkTraceRows(state) {
  return state.entries.map((entry) => {
    const row = document.createElement('div');
    row.className = 'agent-work-trace-entry';
    row.dataset.status = entry.status || 'running';
    row.setAttribute('role', 'listitem');

    const label = document.createElement('span');
    label.className = 'agent-work-trace-entry-label';
    label.textContent = entry.label || 'Agent';

    const text = document.createElement('span');
    text.className = 'agent-work-trace-entry-text';
    text.textContent = entry.text || '';

    row.appendChild(label);
    row.appendChild(text);
    return row;
  });
}

function appendStoredAgentWorkTrace(parentEl, trace) {
  const state = normalizeAgentTraceSnapshot(trace);
  if (!parentEl || !state) return;

  agentWorkTraceId += 1;
  const bodyId = `agent-work-trace-body-${agentWorkTraceId}`;

  const section = document.createElement('section');
  section.className = 'agent-work-trace';
  section.dataset.status = state.status || 'completed';

  const toggle = document.createElement('button');
  toggle.className = 'agent-work-trace-toggle';
  toggle.type = 'button';
  toggle.setAttribute('aria-controls', bodyId);
  toggle.title = 'Toggle agent work details';

  const caret = document.createElement('span');
  caret.className = 'agent-work-trace-caret';
  caret.setAttribute('aria-hidden', 'true');
  caret.textContent = '›';

  const main = document.createElement('span');
  main.className = 'agent-work-trace-main';

  const label = document.createElement('span');
  label.className = 'agent-work-trace-label';
  label.textContent = 'Agent work';

  const summary = document.createElement('span');
  summary.className = 'agent-work-trace-summary';
  summary.textContent = state.summary || '';

  main.appendChild(label);
  main.appendChild(summary);

  const status = document.createElement('span');
  status.className = 'agent-work-trace-status';
  status.textContent = getAgentWorkTraceStatusLabel(state.status);

  toggle.appendChild(caret);
  toggle.appendChild(main);
  toggle.appendChild(status);

  const body = document.createElement('div');
  body.className = 'agent-work-trace-body';
  body.id = bodyId;

  const list = document.createElement('div');
  list.className = 'agent-work-trace-list';
  list.setAttribute('role', 'list');
  list.replaceChildren(...createAgentWorkTraceRows(state));
  body.appendChild(list);

  toggle.addEventListener('click', () => {
    setAgentWorkTraceSectionOpen(section, toggle, body, section.dataset.open !== 'true');
  });

  section.appendChild(toggle);
  section.appendChild(body);
  parentEl.after(section);
  setAgentWorkTraceSectionOpen(section, toggle, body, Boolean(state.isOpen));
}

function clearAgentWorkTraceElement() {
  if (agentWorkTraceEl && agentWorkTraceEl.isConnected) {
    agentWorkTraceEl.remove();
  }
  releaseAgentWorkTraceElement();
}

function releaseAgentWorkTraceElement() {
  agentWorkTraceEl = null;
  agentWorkTraceToggleEl = null;
  agentWorkTraceBodyEl = null;
  agentWorkTraceSummaryEl = null;
  agentWorkTraceStatusEl = null;
  agentWorkTraceListEl = null;
}

function resetAgentWorkTraceForNewTurn() {
  agentWorkTrace.reset();
  releaseAgentWorkTraceElement();
}

function setAgentWorkTraceOpen(isOpen) {
  if (!agentWorkTraceEl || !agentWorkTraceBodyEl || !agentWorkTraceToggleEl) return;
  setAgentWorkTraceSectionOpen(agentWorkTraceEl, agentWorkTraceToggleEl, agentWorkTraceBodyEl, isOpen);
}

function ensureAgentWorkTraceElement() {
  if (!pendingAssistantEl || !pendingAssistantEl.isConnected) {
    return null;
  }

  if (agentWorkTraceEl && agentWorkTraceEl.isConnected) {
    return agentWorkTraceEl;
  }

  agentWorkTraceId += 1;
  const bodyId = `agent-work-trace-body-${agentWorkTraceId}`;

  const section = document.createElement('section');
  section.className = 'agent-work-trace';
  section.dataset.status = 'running';
  section.dataset.open = 'true';

  const toggle = document.createElement('button');
  toggle.className = 'agent-work-trace-toggle';
  toggle.type = 'button';
  toggle.setAttribute('aria-expanded', 'true');
  toggle.setAttribute('aria-controls', bodyId);
  toggle.title = 'Toggle agent work details';

  const caret = document.createElement('span');
  caret.className = 'agent-work-trace-caret';
  caret.setAttribute('aria-hidden', 'true');
  caret.textContent = '›';

  const main = document.createElement('span');
  main.className = 'agent-work-trace-main';

  const label = document.createElement('span');
  label.className = 'agent-work-trace-label';
  label.textContent = 'Agent work';

  const summary = document.createElement('span');
  summary.className = 'agent-work-trace-summary';

  main.appendChild(label);
  main.appendChild(summary);

  const status = document.createElement('span');
  status.className = 'agent-work-trace-status';
  status.textContent = 'Running';

  toggle.appendChild(caret);
  toggle.appendChild(main);
  toggle.appendChild(status);

  const body = document.createElement('div');
  body.className = 'agent-work-trace-body';
  body.id = bodyId;

  const list = document.createElement('div');
  list.className = 'agent-work-trace-list';
  list.setAttribute('role', 'list');
  body.appendChild(list);

  toggle.addEventListener('click', () => {
    const isOpen = section.dataset.open !== 'true';
    setAgentWorkTraceOpen(isOpen);
  });

  section.appendChild(toggle);
  section.appendChild(body);
  pendingAssistantEl.after(section);

  agentWorkTraceEl = section;
  agentWorkTraceToggleEl = toggle;
  agentWorkTraceBodyEl = body;
  agentWorkTraceSummaryEl = summary;
  agentWorkTraceStatusEl = status;
  agentWorkTraceListEl = list;

  return section;
}

function renderAgentWorkTrace(state) {
  if (!state || !Array.isArray(state.entries) || state.entries.length === 0) {
    return;
  }

  const section = ensureAgentWorkTraceElement();
  if (!section || !agentWorkTraceListEl) {
    return;
  }

  section.dataset.status = state.status || 'running';
  if (agentWorkTraceSummaryEl) {
    agentWorkTraceSummaryEl.textContent = state.summary || '';
  }
  if (agentWorkTraceStatusEl) {
    agentWorkTraceStatusEl.textContent = getAgentWorkTraceStatusLabel(state.status);
  }

  agentWorkTraceListEl.replaceChildren(...createAgentWorkTraceRows(state));
  setAgentWorkTraceOpen(Boolean(state.isOpen));
  scrollMessagesToBottom();
}

function applyAgentWorkTraceEvent(payload) {
  if (!isAgentTraceSource(payload?.source)) {
    return false;
  }
  const state = agentWorkTrace.applyEvent(payload);
  renderAgentWorkTrace(state);
  return true;
}

function getPersistableAgentWorkTrace() {
  return normalizeAgentTraceSnapshot(agentWorkTrace.snapshot());
}

function applyFinalAssistantLifecycle(text, agentTrace) {
  const outcome = getAssistantLifecycleOutcome({ text, agentTrace });
  setLifecyclePhase(outcome.phase, {
    text: outcome.text,
    detail: outcome.detail,
  });
}

function finalizePendingAssistant(text) {
  const value = typeof text === 'string' ? text.trim() : '';
  if (!value || value === ASSISTANT_THINKING_TEXT || (pendingAssistantEl && isGeneratingPlaceholderText(value))) return;
  if (value === lastAssistantText) return;

  const ts = Date.now();
  const agentTrace = getPersistableAgentWorkTrace();

  if (pendingAssistantEl && pendingAssistantEl.isConnected) {
    setMessageElementText(pendingAssistantEl, value, {
      role: 'assistant',
      pending: false,
      ts,
    });
    const message = rememberMessage('assistant', value, ts, { agentTrace });
    if (message) {
      syncCurrentSessionMetadataFromHistory(message.ts);
      queuePersistChatHistory();
    }
  } else {
    appendMessage('assistant', value, { pending: false, persist: true, ts, agentTrace });
  }

  pendingAssistantEl = null;
  lastAssistantText = value;
  assistantMessageCache.push(value);
  if (assistantMessageCache.length > MAX_ASSISTANT_CACHE) {
    assistantMessageCache.shift();
  }
  if (terminalChatReady) {
    finalizeTerminalChatSummary();
  }
  updateActionAvailability();
  renderConversationDecorators();
}

function appendVisionArtifactMessage(payload) {
  const artifact = normalizeVisionArtifact(payload?.artifact);
  if (!artifact) return;

  const summary = truncateText(payload?.summary || '', 420) || 'Screen analysis snapshot';
  const ts = Date.now();
  const agentTrace = getPersistableAgentWorkTrace();
  const artifacts = [artifact];

  if (pendingAssistantEl && pendingAssistantEl.isConnected) {
    setMessageElementText(pendingAssistantEl, summary, {
      role: 'assistant',
      pending: false,
      ts,
    });
    setMessageElementArtifacts(pendingAssistantEl, artifacts);
    const message = rememberMessage('assistant', summary, ts, { agentTrace, artifacts });
    if (message) {
      syncCurrentSessionMetadataFromHistory(message.ts);
      queuePersistChatHistory();
    }
    pendingAssistantEl = null;
  } else {
    appendMessage('assistant', summary, {
      pending: false,
      persist: true,
      ts,
      agentTrace,
      artifacts,
    });
  }

  lastAssistantText = summary;
  applyFinalAssistantLifecycle(summary, agentTrace);
  updateActionAvailability();
  renderConversationDecorators();
}

function clearPendingAssistant() {
  let removedPendingAssistant = false;
  if (pendingAssistantEl && pendingAssistantEl.isConnected) {
    pendingAssistantEl.remove();
    removedPendingAssistant = true;
  }
  pendingAssistantEl = null;
  stopPendingAssistantTicker();
  if (removedPendingAssistant) {
    agentWorkTrace.reset();
    clearAgentWorkTraceElement();
  }
  if (terminalChatReady) {
    finalizeTerminalChatSummary();
  }
  updateActionAvailability();
  renderConversationDecorators();
}

function clearRenderedMessages() {
  if (!chatMessages) return;
  stopPendingAssistantTicker();
  chatMessages.querySelectorAll('.chat-msg, .agent-work-trace').forEach((node) => node.remove());
  renderConversationDecorators();
}

function restoreMessages(messages) {
  clearRenderedMessages();
  chatHistory.length = 0;
  let restoredLastAssistant = '';

  for (const item of messages) {
    const restored = normalizePersistedMessage(item?.role, item?.text, item?.ts, {
      agentTrace: item?.agentTrace,
      artifacts: item?.artifacts,
    });
    if (!restored) continue;
    chatHistory.push(restored);
    createMessageElement(restored.role, restored.text, {
      pending: false,
      ts: restored.ts,
      agentTrace: restored.agentTrace,
      artifacts: restored.artifacts,
    });
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

  updateVoiceButtonState();
  updateComposerActionState();

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

    const actions = document.createElement('div');
    actions.className = 'history-item-actions';

    if (summary.archivedAt) {
      const restoreButton = document.createElement('button');
      restoreButton.type = 'button';
      restoreButton.className = 'history-item-action history-item-action-icon';
      restoreButton.textContent = RESTORE_CHAT_SYMBOL;
      restoreButton.disabled = blocked;
      restoreButton.title = 'Restore chat';
      restoreButton.setAttribute('aria-label', 'Restore chat');
      restoreButton.addEventListener('click', (event) => {
        event.stopPropagation();
        void unarchiveSession(summary.sessionId);
      });
      actions.appendChild(restoreButton);

      const deleteButton = document.createElement('button');
      deleteButton.type = 'button';
      deleteButton.className = 'history-item-action history-item-action-icon danger';
      deleteButton.textContent = DELETE_CHAT_SYMBOL;
      deleteButton.disabled = blocked;
      deleteButton.title = 'Delete chat';
      deleteButton.setAttribute('aria-label', 'Delete chat');
      deleteButton.addEventListener('click', (event) => {
        event.stopPropagation();
        openDeleteConfirmation(summary);
      });
      actions.appendChild(deleteButton);
    } else {
      const actionButton = document.createElement('button');
      actionButton.type = 'button';
      actionButton.className = 'history-item-action';
      actionButton.textContent = 'Archive';
      actionButton.disabled = blocked;
      actionButton.addEventListener('click', (event) => {
        event.stopPropagation();
        void archiveSession(summary.sessionId);
      });
      actions.appendChild(actionButton);
    }
    item.appendChild(actions);

    historyList.appendChild(item);
  }

  if (historyFilterActive) {
    historyFilterActive.setAttribute('aria-selected', historyFilter === 'active' ? 'true' : 'false');
  }
  if (historyFilterArchived) {
    historyFilterArchived.setAttribute('aria-selected', historyFilter === 'archived' ? 'true' : 'false');
  }
  updateHistoryDeleteAllArchivedButton();
}

function ensureHistoryDeleteAllArchivedButton() {
  if (historyDeleteAllArchived || !historyPanelHeader) return;

  historyDeleteAllArchived = document.createElement('button');
  historyDeleteAllArchived.id = 'history-delete-all-archived';
  historyDeleteAllArchived.className = 'history-delete-all-archived';
  historyDeleteAllArchived.type = 'button';
  historyDeleteAllArchived.title = 'Delete all';
  historyDeleteAllArchived.setAttribute('aria-label', 'Delete all archived chats');
  historyDeleteAllArchived.textContent = DELETE_CHAT_SYMBOL;
  historyDeleteAllArchived.addEventListener('click', () => {
    openDeleteAllArchivedConfirmation();
  });
  historyPanelHeader.insertBefore(historyDeleteAllArchived, historyPanelClose || null);
}

function updateHistoryDeleteAllArchivedButton() {
  ensureHistoryDeleteAllArchivedButton();
  if (!historyDeleteAllArchived) return;

  const shouldShow = historyFilter === 'archived' && archivedSessions.length > 0;
  historyDeleteAllArchived.hidden = !shouldShow;
  historyDeleteAllArchived.disabled = hasActiveWork();
}

function ensureDeleteConfirmDialog() {
  if (deleteConfirmOverlay) return;

  deleteConfirmOverlay = document.createElement('div');
  deleteConfirmOverlay.className = 'delete-confirm-overlay';
  deleteConfirmOverlay.hidden = true;

  deleteConfirmDialog = document.createElement('section');
  deleteConfirmDialog.className = 'delete-confirm-dialog';
  deleteConfirmDialog.setAttribute('role', 'dialog');
  deleteConfirmDialog.setAttribute('aria-modal', 'true');
  deleteConfirmDialog.setAttribute('aria-labelledby', 'delete-confirm-title');
  deleteConfirmDialog.setAttribute('aria-describedby', 'delete-confirm-body');

  deleteConfirmTitle = document.createElement('h2');
  deleteConfirmTitle.id = 'delete-confirm-title';
  deleteConfirmTitle.textContent = 'Delete archived chat?';

  deleteConfirmBody = document.createElement('p');
  deleteConfirmBody.id = 'delete-confirm-body';

  const actions = document.createElement('div');
  actions.className = 'delete-confirm-actions';

  deleteConfirmCancelButton = document.createElement('button');
  deleteConfirmCancelButton.type = 'button';
  deleteConfirmCancelButton.className = 'delete-confirm-button';
  deleteConfirmCancelButton.textContent = 'Cancel';
  deleteConfirmCancelButton.addEventListener('click', () => {
    cancelDeleteConfirmation();
  });

  deleteConfirmDeleteButton = document.createElement('button');
  deleteConfirmDeleteButton.type = 'button';
  deleteConfirmDeleteButton.className = 'delete-confirm-button danger';
  deleteConfirmDeleteButton.textContent = `${DELETE_CHAT_SYMBOL} Delete`;
  deleteConfirmDeleteButton.addEventListener('click', () => {
    void confirmDeleteSession();
  });

  actions.appendChild(deleteConfirmCancelButton);
  actions.appendChild(deleteConfirmDeleteButton);
  deleteConfirmDialog.appendChild(deleteConfirmTitle);
  deleteConfirmDialog.appendChild(deleteConfirmBody);
  deleteConfirmDialog.appendChild(actions);
  deleteConfirmOverlay.appendChild(deleteConfirmDialog);
  deleteConfirmOverlay.addEventListener('click', (event) => {
    if (event.target === deleteConfirmOverlay) {
      cancelDeleteConfirmation();
    }
  });
  document.body.appendChild(deleteConfirmOverlay);
}

function isDeleteConfirmationOpen() {
  return Boolean(deleteConfirmOverlay && !deleteConfirmOverlay.hidden);
}

function openDeleteConfirmation(summary) {
  if (!summary?.sessionId) return;
  ensureDeleteConfirmDialog();

  pendingDeleteSession = {
    sessionId: summary.sessionId,
    title: summary.title || 'New chat',
    mode: 'single',
  };
  deleteConfirmReturnFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;

  if (deleteConfirmTitle) {
    deleteConfirmTitle.textContent = 'Delete archived chat?';
  }
  if (deleteConfirmBody) {
    deleteConfirmBody.textContent = `This will permanently delete "${pendingDeleteSession.title}" from archived chats.`;
  }
  if (deleteConfirmCancelButton) {
    deleteConfirmCancelButton.disabled = false;
  }
  if (deleteConfirmDeleteButton) {
    deleteConfirmDeleteButton.disabled = false;
  }
  deleteConfirmOverlay.hidden = false;
  requestAnimationFrame(() => {
    deleteConfirmCancelButton?.focus();
  });
}

function openDeleteAllArchivedConfirmation() {
  if (archivedSessions.length === 0) return;
  ensureDeleteConfirmDialog();

  pendingDeleteSession = {
    mode: 'all-archived',
    title: 'all archived chats',
    count: archivedSessions.length,
  };
  deleteConfirmReturnFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;

  if (deleteConfirmTitle) {
    deleteConfirmTitle.textContent = 'Delete all archived chats?';
  }
  if (deleteConfirmBody) {
    deleteConfirmBody.textContent = `This will permanently delete ${archivedSessions.length} archived chat${archivedSessions.length === 1 ? '' : 's'}.`;
  }
  if (deleteConfirmCancelButton) {
    deleteConfirmCancelButton.disabled = false;
  }
  if (deleteConfirmDeleteButton) {
    deleteConfirmDeleteButton.disabled = false;
  }
  deleteConfirmOverlay.hidden = false;
  requestAnimationFrame(() => {
    deleteConfirmCancelButton?.focus();
  });
}

function cancelDeleteConfirmation(options = {}) {
  const { restoreFocus = true } = options;
  pendingDeleteSession = null;
  if (deleteConfirmOverlay) {
    deleteConfirmOverlay.hidden = true;
  }
  if (deleteConfirmTitle) {
    deleteConfirmTitle.textContent = 'Delete archived chat?';
  }
  if (restoreFocus && deleteConfirmReturnFocus?.isConnected) {
    requestAnimationFrame(() => {
      deleteConfirmReturnFocus?.focus();
    });
  }
  deleteConfirmReturnFocus = null;
}

async function confirmDeleteSession() {
  if (!pendingDeleteSession) return;
  const request = { ...pendingDeleteSession };
  if (deleteConfirmCancelButton) {
    deleteConfirmCancelButton.disabled = true;
  }
  if (deleteConfirmDeleteButton) {
    deleteConfirmDeleteButton.disabled = true;
  }

  const deleted = request.mode === 'all-archived'
    ? await deleteArchivedSessions()
    : await deleteSession(request.sessionId);
  if (deleted) {
    cancelDeleteConfirmation({ restoreFocus: false });
    return;
  }

  if (deleteConfirmCancelButton) {
    deleteConfirmCancelButton.disabled = false;
  }
  if (deleteConfirmDeleteButton) {
    deleteConfirmDeleteButton.disabled = false;
  }
}

function openHistoryPanel() {
  closeSettingsPopover();
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
  renderHistoryList();
}

function closeHistoryPanel() {
  if (isDeleteConfirmationOpen()) {
    cancelDeleteConfirmation({ restoreFocus: false });
  }
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

async function unarchiveSession(sessionId) {
  if (!window.api?.unarchiveChatSession || !sessionId) return;
  if (hasActiveWork()) {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Restore blocked',
      detail: 'Stop current work before restoring a chat.',
    });
    return;
  }

  setLifecyclePhase(EXECUTION_PHASES.PREPARING, {
    text: 'Restoring chat…',
    detail: 'Moving the archived session back to active chats.',
  });
  try {
    const state = await window.api.unarchiveChatSession(sessionId);
    historyFilter = 'active';
    applySessionState(state, { keepHistoryOpen: false, focusInput: true });
    setLifecyclePhase(EXECUTION_PHASES.COMPLETED, {
      text: 'Chat restored',
      detail: 'You can continue from this session now.',
    });
  } catch {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Unable to restore chat',
      detail: 'The session could not be restored right now.',
    });
  }
}

async function deleteSession(sessionId) {
  if (!window.api?.deleteChatSession || !sessionId) return false;
  if (hasActiveWork()) {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Delete blocked',
      detail: 'Stop current work before deleting a chat.',
    });
    return false;
  }

  setLifecyclePhase(EXECUTION_PHASES.PREPARING, {
    text: 'Deleting chat…',
    detail: 'Removing the archived session from history.',
  });
  try {
    const state = await window.api.deleteChatSession(sessionId);
    removeSessionSummary(sessionId);
    applySessionState(state, { keepHistoryOpen: true, focusInput: false });
    setLifecyclePhase(EXECUTION_PHASES.COMPLETED, {
      text: 'Chat deleted',
      detail: 'The archived session was removed.',
    });
    return true;
  } catch {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Unable to delete chat',
      detail: 'The session could not be deleted right now.',
    });
    return false;
  }
}

async function deleteArchivedSessions() {
  if (!window.api?.deleteArchivedChatSessions) return false;
  if (hasActiveWork()) {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Delete blocked',
      detail: 'Stop current work before deleting archived chats.',
    });
    return false;
  }

  setLifecyclePhase(EXECUTION_PHASES.PREPARING, {
    text: 'Deleting archived chats…',
    detail: 'Removing archived sessions from history.',
  });
  try {
    const state = await window.api.deleteArchivedChatSessions();
    archivedSessions.length = 0;
    applySessionState(state, { keepHistoryOpen: true, focusInput: false });
    setLifecyclePhase(EXECUTION_PHASES.COMPLETED, {
      text: 'Archived chats deleted',
      detail: 'All archived sessions were removed.',
    });
    return true;
  } catch {
    setLifecyclePhase(EXECUTION_PHASES.STOPPED, {
      text: 'Unable to delete archived chats',
      detail: 'The archived sessions could not be deleted right now.',
    });
    return false;
  }
}

async function getSocketTarget() {
  const fallback = { host: '127.0.0.1', port: 8765, authToken: '' };
  try {
    if (!window.api?.getServerConfig) {
      return fallback;
    }
    const config = await window.api.getServerConfig();
    const host = typeof config?.host === 'string' && config.host.trim() ? config.host.trim() : fallback.host;
    const portValue = Number(config?.port);
    const port = Number.isInteger(portValue) && portValue > 0 ? portValue : fallback.port;
    const authToken = typeof config?.authToken === 'string' ? config.authToken.trim() : '';
    return { host, port, authToken };
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
    const stopTranscript = options.pending
      ? '[stop requested] Stop signal sent from chat controls.'
      : '[stopped] Stop signal received.';
    appendTerminalTranscript(stopTranscript);
    pushTerminalChatLine(stopTranscript);
    if (options.pending) {
      updateTerminalChatSummary('stopping');
    } else {
      terminalChatReady = true;
      finalizeTerminalChatSummary('stopped');
    }
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
  const authQuery = target.authToken ? `?${new URLSearchParams({ token: target.authToken }).toString()}` : '';
  const wsUrl = `ws://${target.host}:${target.port}${authQuery}`;
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

    if (payload.command === 'vision_capture_started') {
      visionChatHiddenForCapture = true;
      hideInputWindow();
      return;
    }

    if (payload.command === 'vision_chat_restore') {
      restoreVisionChatWindow();
      return;
    }

    if (payload.command === 'chat_vision_artifact') {
      appendVisionArtifactMessage(payload);
      return;
    }

    if (payload.command === 'draw_text' && payload.id === 'direct_response') {
      if (!shouldDisplayReplyInChat(payload)) {
        clearPendingAssistant();
        return;
      }
      const responseText = payload.text || '';
      const agentTrace = getPersistableAgentWorkTrace();
      finalizePendingAssistant(responseText);
      applyFinalAssistantLifecycle(responseText, agentTrace);
      return;
    }

    if (payload.command === 'show_status_bubble' || payload.command === 'update_status_bubble') {
      applyAgentWorkTraceEvent(payload);
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
      applyAgentWorkTraceEvent(payload);
      if (shouldDisplayReplyInChat(payload)) {
        const agentTrace = getPersistableAgentWorkTrace();
        finalizePendingAssistant(responseText);
        applyFinalAssistantLifecycle(responseText, agentTrace);
      } else {
        setLifecyclePhase(EXECUTION_PHASES.RUNNING, {
          text: 'Checking result…',
          detail: 'Verifying whether more steps are needed.',
        });
      }
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

function showInputWindow() {
  if (window.api?.showInputWindow) {
    window.api.showInputWindow();
    return;
  }
  if (window.api?.setInputMode) {
    window.api.setInputMode(true);
  }
}

function restoreVisionChatWindow() {
  if (!visionChatHiddenForCapture) return;
  visionChatHiddenForCapture = false;
  showInputWindow();
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
  resetAgentWorkTraceForNewTurn();
  lastAssistantText = '';
  appendMessage('user', text, { pending: false, persist: true, ts: now });
  pendingAssistantEl = appendMessage('assistant', 'Routing request…', {
    pending: true,
    persist: false,
    ts: now,
  });
  setLifecyclePhase(EXECUTION_PHASES.ROUTING, {
    text: 'Routing request…',
    detail: 'Choosing the right path for your request.',
  });
  updateActionAvailability();

  const activeSessionId = currentSession?.sessionId || null;
  const requestQueued = sendMessage({
    event: 'overlay_input',
    text,
    sessionId: activeSessionId,
    requestId: `overlay_${now}_${Math.random().toString(16).slice(2, 8)}`,
  });

  if (!requestQueued) {
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
function requestStopFromComposer() {
  if (window.api?.requestStopAll) {
    window.api.requestStopAll();
  }
  handleStopUi('Interrupting running actions now.', {
    pending: true,
    addSystemMessage: true,
  });
  focusCommandInput();
}

function handleComposerActionClick() {
  if (hasActiveWork()) {
    requestStopFromComposer();
    return;
  }
  submitCommand();
}

commandSend?.addEventListener('click', () => handleComposerActionClick());
chatSettingsToggle?.addEventListener('click', (event) => {
  event.stopPropagation();
  toggleSettingsPopover();
});
chatSettingsHelp?.addEventListener('click', (event) => {
  event.stopPropagation();
  showSettingsHelp();
});
chatSettingsHistory?.addEventListener('click', () => {
  closeSettingsPopover();
  openHistoryPanel();
});
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
  closeSettingsPopover();
  void createNewChat();
});

terminalPanelToggle?.addEventListener('click', () => {
  setTerminalPanelMinimized(!isTerminalPanelMinimized);
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
  if (!isSettingsPopoverOpen() || !chatSettingsMenu) return;
  if (chatSettingsMenu.contains(event.target)) return;
  closeSettingsPopover();
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (isVisionArtifactViewerOpen()) {
    event.preventDefault();
    closeVisionArtifactViewer();
    return;
  }
  if (isDeleteConfirmationOpen()) {
    event.preventDefault();
    cancelDeleteConfirmation();
    return;
  }
  event.preventDefault();
  handleEscapeKey({ restoreSettingsFocus: true });
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
    closeSettingsPopover();
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
  updateTerminalPanelControls();
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
