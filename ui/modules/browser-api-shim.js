(() => {
  if (window.api) {
    return;
  }

  const DEFAULT_BACKEND_PORT = 58870;
  const STORAGE_KEY = 'jarvis-browser-ui.sessions.v1';
  const EVENT_CHANNEL = 'jarvis-browser-ui.events.v1';
  const MAX_IMAGE_DATA_URL_CHARS = 8_000_000;
  const retentionDays = 30;
  const purgeDays = 30;
  const listeners = new Map();
  const channel = typeof BroadcastChannel !== 'undefined'
    ? new BroadcastChannel(EVENT_CHANNEL)
    : null;

  function nowIso() {
    return new Date().toISOString();
  }

  function safeJsonParse(raw, fallback) {
    try {
      return raw ? JSON.parse(raw) : fallback;
    } catch {
      return fallback;
    }
  }

  function readStore() {
    const stored = safeJsonParse(window.localStorage.getItem(STORAGE_KEY), null);
    if (stored && typeof stored === 'object') {
      return stored;
    }

    const seed = {
      sessions: [
        {
          sessionId: `browser_${Date.now().toString(36)}`,
          title: 'New chat',
          startedAt: nowIso(),
          updatedAt: nowIso(),
          archivedAt: null,
          messages: [],
        },
      ],
      currentSessionId: '',
    };
    seed.currentSessionId = seed.sessions[0].sessionId;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seed));
    return seed;
  }

  function writeStore(store) {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function normalizeMessage(message) {
    if (!message || typeof message !== 'object') return null;
    const role = typeof message.role === 'string' ? message.role.trim().toLowerCase() : '';
    const text = typeof message.text === 'string' ? message.text.trim() : '';
    const ts = Number.isFinite(message.ts) ? Number(message.ts) : Date.now();
    if (!role || !text) return null;
    if (!['user', 'assistant', 'system', 'terminal'].includes(role)) return null;
    const normalized = { role, text, ts };
    const artifacts = role === 'assistant'
      ? normalizeMessageArtifacts(message.artifacts)
      : [];
    if (artifacts.length > 0) {
      normalized.artifacts = artifacts;
    }
    return normalized;
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
      title: typeof artifact.title === 'string' && artifact.title.trim() ? artifact.title.trim().slice(0, 80) : 'Analyzed screen',
      imageDataUrl,
      width: Number.isFinite(width) && width > 0 ? Math.round(width) : 0,
      height: Number.isFinite(height) && height > 0 ? Math.round(height) : 0,
      outlineCount: Number.isFinite(outlineCount) && outlineCount > 0 ? Math.round(outlineCount) : 0,
    };
  }

  function normalizeMessageArtifacts(artifacts) {
    if (!Array.isArray(artifacts)) return [];
    return artifacts.map(normalizeVisionArtifact).filter(Boolean).slice(0, 4);
  }

  function normalizeSession(session) {
    if (!session || typeof session !== 'object') return null;
    const messages = Array.isArray(session.messages)
      ? session.messages.map(normalizeMessage).filter(Boolean)
      : [];
    return {
      sessionId: typeof session.sessionId === 'string' ? session.sessionId : '',
      title: typeof session.title === 'string' && session.title.trim() ? session.title.trim() : 'New chat',
      startedAt: typeof session.startedAt === 'string' ? session.startedAt : nowIso(),
      updatedAt: typeof session.updatedAt === 'string' ? session.updatedAt : nowIso(),
      archivedAt: typeof session.archivedAt === 'string' && session.archivedAt.trim() ? session.archivedAt : null,
      messages,
    };
  }

  function getSessionList(store) {
    if (!Array.isArray(store.sessions)) {
      store.sessions = [];
    }
    store.sessions = store.sessions.map(normalizeSession).filter(Boolean);
    return store.sessions;
  }

  function ensureStoreShape() {
    const store = readStore();
    const sessions = getSessionList(store);
    if (sessions.length === 0) {
      sessions.push(normalizeSession({
        sessionId: `browser_${Date.now().toString(36)}`,
        title: 'New chat',
        startedAt: nowIso(),
        updatedAt: nowIso(),
        archivedAt: null,
        messages: [],
      }));
    }
    const knownIds = new Set(sessions.map((session) => session.sessionId));
    if (!store.currentSessionId || !knownIds.has(store.currentSessionId)) {
      const active = sessions.find((session) => !session.archivedAt) || sessions[0];
      store.currentSessionId = active.sessionId;
    }
    writeStore(store);
    return store;
  }

  function getCurrentSession(store = ensureStoreShape()) {
    const sessions = getSessionList(store);
    const current = sessions.find((session) => session.sessionId === store.currentSessionId);
    return current || sessions[0] || null;
  }

  function buildState(sessionId = null) {
    const store = ensureStoreShape();
    const sessions = getSessionList(store);
    let currentSession = sessionId
      ? sessions.find((session) => session.sessionId === sessionId) || null
      : getCurrentSession(store);
    if (!currentSession) {
      currentSession = sessions[0] || null;
    }
    if (currentSession) {
      store.currentSessionId = currentSession.sessionId;
      writeStore(store);
    }

    const activeSessions = sessions.filter((session) => !session.archivedAt).map((session) => ({
      sessionId: session.sessionId,
      title: session.title,
      preview: session.messages[session.messages.length - 1]?.text || 'No messages yet',
      startedAt: session.startedAt,
      updatedAt: session.updatedAt,
      archivedAt: null,
      messageCount: session.messages.length,
    }));

    const archivedSessions = sessions.filter((session) => Boolean(session.archivedAt)).map((session) => ({
      sessionId: session.sessionId,
      title: session.title,
      preview: session.messages[session.messages.length - 1]?.text || 'No messages yet',
      startedAt: session.startedAt,
      updatedAt: session.updatedAt,
      archivedAt: session.archivedAt,
      messageCount: session.messages.length,
    }));

    return {
      retentionDays,
      purgeDays,
      currentSession: currentSession ? clone(currentSession) : null,
      activeSessions,
      archivedSessions,
    };
  }

  function dispatch(eventName, payload) {
    const callbacks = listeners.get(eventName);
    if (callbacks) {
      for (const callback of callbacks) {
        try {
          callback(payload);
        } catch {
          // Ignore browser fallback listener failures.
        }
      }
    }

    if (channel) {
      channel.postMessage({ eventName, payload });
    }
  }

  function on(eventName, callback) {
    if (typeof callback !== 'function') {
      return () => {};
    }

    const callbacks = listeners.get(eventName) || new Set();
    callbacks.add(callback);
    listeners.set(eventName, callbacks);

    return () => {
      callbacks.delete(callback);
      if (callbacks.size === 0) {
        listeners.delete(eventName);
      }
    };
  }

  if (channel) {
    channel.onmessage = (event) => {
      const eventName = typeof event.data?.eventName === 'string' ? event.data.eventName : '';
      if (!eventName) return;
      const payload = event.data?.payload;
      const callbacks = listeners.get(eventName);
      if (!callbacks) return;
      for (const callback of callbacks) {
        try {
          callback(payload);
        } catch {
          // Ignore browser fallback listener failures.
        }
      }
    };
  }

  window.api = {
    getPlatform: () => 'win32',
    setWindowInteractive: () => {},
    reportHitTest: () => {},
    onCursorPosition: (callback) => on('cursor-position', callback),
    onResetConfigure: (callback) => on('reset-configure', callback),
    onOverlayImage: (callback) => on('overlay-image', callback),
    onHideOverlayImage: (callback) => on('hide-overlay-image', callback),
    onShowInputWindow: (callback) => on('show-input-window', callback),
    onHideInputWindow: (callback) => on('hide-input-window', callback),
    onClearOverlay: (callback) => on('clear-overlay', callback),
    onStopAll: (callback) => on('stop-all', callback),
    hideInputWindow: () => {
      dispatch('hide-input-window');
      window.close();
    },
    showInputWindow: () => {
      dispatch('show-input-window');
    },
    requestStopAll: () => {
      dispatch('stop-all');
    },
    setInputMode: (enabled) => {
      dispatch(enabled ? 'show-input-window' : 'hide-input-window');
    },
    getModelName: async () => 'Agent',
    getServerConfig: async () => {
      try {
        const response = await fetch('settings.json', { cache: 'no-store' });
        if (response.ok) {
          const config = await response.json();
          const host = typeof config?.host === 'string' && config.host.trim() ? config.host.trim() : '127.0.0.1';
          const portValue = Number(config?.port);
          const port = Number.isInteger(portValue) && portValue > 0 ? portValue : DEFAULT_BACKEND_PORT;
          const authToken = typeof config?.authToken === 'string' ? config.authToken.trim() : '';
          return { host, port, authToken };
        }
      } catch {
        // Fall through to local default.
      }
      return { host: '127.0.0.1', port: DEFAULT_BACKEND_PORT, authToken: '' };
    },
    getChatSessionInfo: async () => {
      const state = buildState();
      return {
        sessionId: state.currentSession?.sessionId || '',
        startedAt: state.currentSession?.startedAt || nowIso(),
      };
    },
    loadChatSession: async () => buildState(),
    saveChatSession: async (sessionId, messages) => {
      const store = ensureStoreShape();
      const targetSessionId = typeof sessionId === 'string' && sessionId.trim()
        ? sessionId.trim()
        : getCurrentSession(store)?.sessionId;
      if (!targetSessionId) {
        return { updatedAt: nowIso(), readOnly: false };
      }

      const sessions = getSessionList(store);
      let session = sessions.find((item) => item.sessionId === targetSessionId);
      if (!session) {
        session = normalizeSession({
          sessionId: targetSessionId,
          title: 'New chat',
          startedAt: nowIso(),
          updatedAt: nowIso(),
          archivedAt: null,
          messages: [],
        });
        sessions.push(session);
      }

      session.messages = Array.isArray(messages)
        ? messages.map(normalizeMessage).filter(Boolean)
        : [];
      session.updatedAt = nowIso();
      session.title = session.messages.find((message) => message.role === 'user')?.text?.slice(0, 58) || session.title;
      store.currentSessionId = session.sessionId;
      writeStore(store);
      return { updatedAt: session.updatedAt, readOnly: false };
    },
    getChatSessionState: async (sessionId = null) => buildState(sessionId),
    openVisionArtifactImage: async () => ({ opened: false }),
    createChatSession: async () => {
      const store = ensureStoreShape();
      const sessions = getSessionList(store);
      const session = normalizeSession({
        sessionId: `browser_${Date.now().toString(36)}`,
        title: 'New chat',
        startedAt: nowIso(),
        updatedAt: nowIso(),
        archivedAt: null,
        messages: [],
      });
      sessions.push(session);
      store.currentSessionId = session.sessionId;
      writeStore(store);
      return buildState(session.sessionId);
    },
    archiveChatSession: async (sessionId) => {
      const store = ensureStoreShape();
      const sessions = getSessionList(store);
      const targetId = typeof sessionId === 'string' ? sessionId.trim() : '';
      const session = sessions.find((item) => item.sessionId === targetId);
      if (!session) {
        return buildState();
      }
      session.archivedAt = nowIso();
      session.updatedAt = nowIso();
      if (!store.currentSessionId) {
        store.currentSessionId = session.sessionId;
      }
      writeStore(store);
      return buildState(session.sessionId);
    },
  };

  window.addEventListener('beforeunload', () => {
    if (channel) {
      channel.close();
    }
  });
})();
