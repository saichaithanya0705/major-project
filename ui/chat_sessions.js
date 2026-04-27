const fs = require('fs');
const path = require('path');

const MAX_PERSISTED_CHAT_MESSAGES = 300;
const CHAT_AUTO_ARCHIVE_AFTER_DAYS = 30;
const CHAT_ARCHIVED_DELETE_AFTER_DAYS = 30;
const CHAT_AUTO_ARCHIVE_MS = CHAT_AUTO_ARCHIVE_AFTER_DAYS * 24 * 60 * 60 * 1000;
const CHAT_ARCHIVED_DELETE_MS = CHAT_ARCHIVED_DELETE_AFTER_DAYS * 24 * 60 * 60 * 1000;

function createChatSessionManager({
  app,
  fsModule = fs,
  pathModule = path,
} = {}) {
  if (!app || typeof app.getPath !== 'function') {
    throw new Error('createChatSessionManager requires an Electron app instance with getPath().');
  }

  const fsApi = fsModule;
  const pathApi = pathModule;
  let currentChatSessionId = null;

  function getChatSessionDir() {
    return pathApi.join(app.getPath('userData'), 'chat_sessions');
  }

  function getChatSessionFilePath(sessionId) {
    return pathApi.join(getChatSessionDir(), `${sessionId}.json`);
  }

  function ensureChatSessionDir() {
    const dir = getChatSessionDir();
    if (!fsApi.existsSync(dir)) {
      fsApi.mkdirSync(dir, { recursive: true });
    }
    return dir;
  }

  function isValidIsoDate(value) {
    return typeof value === 'string' && !Number.isNaN(Date.parse(value));
  }

  function normalizeIsoDate(value, fallback) {
    return isValidIsoDate(value) ? new Date(value).toISOString() : fallback;
  }

  function truncateText(value, maxLength) {
    if (typeof value !== 'string') return '';
    const normalized = value.replace(/\s+/g, ' ').trim();
    if (!normalized) return '';
    if (normalized.length <= maxLength) return normalized;
    return `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}...`;
  }

  function deriveChatSessionTitle(messages) {
    if (!Array.isArray(messages) || messages.length === 0) {
      return 'New chat';
    }

    const preferred = messages.find((item) => item.role === 'user' && item.text);
    if (preferred) {
      return truncateText(preferred.text, 58) || 'New chat';
    }

    const fallback = messages.find((item) => item.text);
    return truncateText(fallback?.text || '', 58) || 'New chat';
  }

  function deriveChatSessionPreview(messages) {
    if (!Array.isArray(messages) || messages.length === 0) {
      return 'No messages yet';
    }
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (!message || typeof message.text !== 'string') continue;
      const preview = truncateText(message.text, 96);
      if (preview) {
        return preview;
      }
    }
    return 'No messages yet';
  }

  function createChatSessionId() {
    const baseId = new Date().toISOString().replace(/[:.]/g, '-');
    let sessionId = baseId;
    let counter = 1;
    while (fsApi.existsSync(getChatSessionFilePath(sessionId))) {
      sessionId = `${baseId}-${counter}`;
      counter += 1;
    }
    return sessionId;
  }

  function sanitizeChatMessages(messages) {
    if (!Array.isArray(messages)) return [];
    const out = [];
    for (const item of messages) {
      if (!item || typeof item !== 'object') continue;
      const role = typeof item.role === 'string' ? item.role.trim().toLowerCase() : '';
      const text = typeof item.text === 'string' ? item.text.trim() : '';
      const ts = typeof item.ts === 'number' ? item.ts : Date.now();
      if (!role || !text) continue;
      if (!['user', 'assistant', 'system', 'terminal'].includes(role)) continue;
      out.push({ role, text, ts });
    }
    return out.slice(-MAX_PERSISTED_CHAT_MESSAGES);
  }

  function normalizeChatSessionData(parsed, fallbackSessionId) {
    const nowIso = new Date().toISOString();
    const messages = sanitizeChatMessages(parsed?.messages || []);
    const startedAt = normalizeIsoDate(parsed?.startedAt || parsed?.createdAt, nowIso);
    const updatedAt = normalizeIsoDate(parsed?.updatedAt, startedAt);
    const archivedAt = parsed?.archivedAt ? normalizeIsoDate(parsed.archivedAt, updatedAt) : null;
    const title = truncateText(typeof parsed?.title === 'string' ? parsed.title : '', 58) || deriveChatSessionTitle(messages);

    return {
      sessionId: typeof parsed?.sessionId === 'string' && parsed.sessionId.trim() ? parsed.sessionId.trim() : fallbackSessionId,
      startedAt,
      updatedAt,
      archivedAt,
      title,
      messages,
    };
  }

  function readChatSessionData(filePath) {
    try {
      const raw = fsApi.readFileSync(filePath, 'utf-8');
      const parsed = JSON.parse(raw);
      const fallbackSessionId = pathApi.basename(filePath, '.json');
      return normalizeChatSessionData(parsed, fallbackSessionId);
    } catch (_error) {
      return null;
    }
  }

  function writeChatSessionData(session) {
    ensureChatSessionDir();
    const normalized = normalizeChatSessionData(session, session.sessionId || createChatSessionId());
    const filePath = getChatSessionFilePath(normalized.sessionId);
    fsApi.writeFileSync(filePath, JSON.stringify(normalized, null, 2), 'utf-8');
    return normalized;
  }

  function compareSessionDatesDesc(left, right, field) {
    return Date.parse(right?.[field] || right?.updatedAt || 0) - Date.parse(left?.[field] || left?.updatedAt || 0);
  }

  function buildChatSessionSummary(session) {
    return {
      sessionId: session.sessionId,
      title: session.title || deriveChatSessionTitle(session.messages),
      preview: deriveChatSessionPreview(session.messages),
      startedAt: session.startedAt,
      updatedAt: session.updatedAt,
      archivedAt: session.archivedAt || null,
      messageCount: Array.isArray(session.messages) ? session.messages.length : 0,
    };
  }

  function listStoredChatSessions() {
    ensureChatSessionDir();
    const filePaths = fsApi.readdirSync(getChatSessionDir())
      .filter((name) => name.toLowerCase().endsWith('.json'))
      .map((name) => pathApi.join(getChatSessionDir(), name));

    return filePaths
      .map((filePath) => readChatSessionData(filePath))
      .filter(Boolean);
  }

  function reconcileChatSessionRetention() {
    ensureChatSessionDir();
    const now = Date.now();
    const sessions = [];

    for (const session of listStoredChatSessions()) {
      let nextSession = { ...session };
      let shouldWrite = false;

      if (!nextSession.archivedAt && (now - Date.parse(nextSession.updatedAt)) >= CHAT_AUTO_ARCHIVE_MS) {
        nextSession.archivedAt = new Date(now).toISOString();
        shouldWrite = true;
      }

      if (nextSession.archivedAt && (now - Date.parse(nextSession.archivedAt)) >= CHAT_ARCHIVED_DELETE_MS) {
        const filePath = getChatSessionFilePath(nextSession.sessionId);
        if (fsApi.existsSync(filePath)) {
          fsApi.unlinkSync(filePath);
        }
        if (currentChatSessionId === nextSession.sessionId) {
          currentChatSessionId = null;
        }
        continue;
      }

      if (shouldWrite) {
        nextSession = writeChatSessionData(nextSession);
      }

      sessions.push(nextSession);
    }

    return sessions;
  }

  function createChatSession(setAsCurrent = true) {
    const nowIso = new Date().toISOString();
    const session = writeChatSessionData({
      sessionId: createChatSessionId(),
      startedAt: nowIso,
      updatedAt: nowIso,
      archivedAt: null,
      title: 'New chat',
      messages: [],
    });
    if (setAsCurrent) {
      currentChatSessionId = session.sessionId;
    }
    return session;
  }

  function selectCurrentChatSession(sessions, preferredSessionId = null) {
    const preferred = preferredSessionId
      ? sessions.find((session) => session.sessionId === preferredSessionId)
      : null;
    if (preferred) {
      currentChatSessionId = preferred.sessionId;
      return preferred;
    }

    const current = currentChatSessionId
      ? sessions.find((session) => session.sessionId === currentChatSessionId)
      : null;
    if (current) {
      return current;
    }

    const latestActive = sessions
      .filter((session) => !session.archivedAt)
      .sort((left, right) => compareSessionDatesDesc(left, right, 'updatedAt'))[0];
    if (latestActive) {
      currentChatSessionId = latestActive.sessionId;
      return latestActive;
    }

    return createChatSession(true);
  }

  function getChatSessionState(preferredSessionId = null) {
    let sessions = reconcileChatSessionRetention();
    let currentSession = selectCurrentChatSession(sessions, preferredSessionId);

    if (!sessions.some((session) => session.sessionId === currentSession.sessionId)) {
      sessions = [...sessions, currentSession];
    }

    const activeSessions = sessions
      .filter((session) => !session.archivedAt)
      .sort((left, right) => compareSessionDatesDesc(left, right, 'updatedAt'))
      .map((session) => buildChatSessionSummary(session));

    const archivedSessions = sessions
      .filter((session) => Boolean(session.archivedAt))
      .sort((left, right) => compareSessionDatesDesc(left, right, 'archivedAt'))
      .map((session) => buildChatSessionSummary(session));

    return {
      retentionDays: CHAT_AUTO_ARCHIVE_AFTER_DAYS,
      purgeDays: CHAT_ARCHIVED_DELETE_AFTER_DAYS,
      currentSession: {
        ...currentSession,
        title: currentSession.title || deriveChatSessionTitle(currentSession.messages),
        messages: sanitizeChatMessages(currentSession.messages || []),
      },
      currentSessionId: currentSession.sessionId,
      activeSessions,
      archivedSessions,
    };
  }

  function loadChatSessionData(sessionId = null) {
    return getChatSessionState(sessionId).currentSession;
  }

  function saveChatSessionMessages(sessionId, messages) {
    const state = getChatSessionState(sessionId);
    const existingSession = state.currentSession;
    if (existingSession.archivedAt) {
      return {
        sessionId: existingSession.sessionId,
        count: existingSession.messages.length,
        updatedAt: existingSession.updatedAt,
        archivedAt: existingSession.archivedAt,
        readOnly: true,
      };
    }

    const sanitized = sanitizeChatMessages(messages);
    const updatedAt = sanitized.length > 0 ? new Date().toISOString() : existingSession.updatedAt;
    const savedSession = writeChatSessionData({
      ...existingSession,
      updatedAt,
      archivedAt: null,
      title: deriveChatSessionTitle(sanitized),
      messages: sanitized,
    });

    currentChatSessionId = savedSession.sessionId;
    return {
      sessionId: savedSession.sessionId,
      count: savedSession.messages.length,
      updatedAt: savedSession.updatedAt,
      archivedAt: savedSession.archivedAt,
      readOnly: false,
    };
  }

  function archiveChatSession(sessionId) {
    if (typeof sessionId !== 'string' || !sessionId.trim()) {
      return getChatSessionState();
    }

    const sessions = reconcileChatSessionRetention();
    const existingSession = sessions.find((session) => session.sessionId === sessionId.trim());
    if (!existingSession) {
      return getChatSessionState();
    }

    if (!existingSession.archivedAt) {
      writeChatSessionData({
        ...existingSession,
        archivedAt: new Date().toISOString(),
      });
    }

    if (currentChatSessionId === existingSession.sessionId) {
      currentChatSessionId = null;
    }

    return getChatSessionState();
  }

  function initialize() {
    currentChatSessionId = getChatSessionState().currentSessionId;
    return currentChatSessionId;
  }

  function getCurrentSessionId() {
    return currentChatSessionId;
  }

  return {
    archiveChatSession,
    createChatSession,
    getChatSessionState,
    getCurrentSessionId,
    initialize,
    loadChatSessionData,
    saveChatSessionMessages,
  };
}

module.exports = {
  CHAT_AUTO_ARCHIVE_AFTER_DAYS,
  CHAT_ARCHIVED_DELETE_AFTER_DAYS,
  createChatSessionManager,
};
