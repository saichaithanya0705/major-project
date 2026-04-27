const { app, BrowserWindow, screen, ipcMain, Menu, Tray, nativeImage, globalShortcut } = require('electron');
const fs = require('fs');
const path = require('path');

let overlayWin;
let inputWin;
let tray;
let cursorPoller;
let inputWindowLastBounds = null;
const MAX_PERSISTED_CHAT_MESSAGES = 300;
const CHAT_AUTO_ARCHIVE_AFTER_DAYS = 30;
const CHAT_ARCHIVED_DELETE_AFTER_DAYS = 30;
const CHAT_AUTO_ARCHIVE_MS = CHAT_AUTO_ARCHIVE_AFTER_DAYS * 24 * 60 * 60 * 1000;
const CHAT_ARCHIVED_DELETE_MS = CHAT_ARCHIVED_DELETE_AFTER_DAYS * 24 * 60 * 60 * 1000;
let currentChatSessionId = null;

console.log('[main] boot', { cwd: process.cwd(), dir: __dirname });

function registerShortcut(accelerator, label, callback) {
  try {
    const registered = globalShortcut.register(accelerator, callback);
    if (registered) {
      console.log(`[main] shortcut registered: ${label} (${accelerator})`);
    } else {
      console.error(`[main] shortcut registration failed: ${label} (${accelerator})`);
    }
    return registered;
  } catch (error) {
    console.error(`[main] shortcut registration error: ${label} (${accelerator})`, error);
    return false;
  }
}

function getServerConfig() {
  const defaultConfig = { host: '127.0.0.1', port: 8765 };
  try {
    const settingsPath = path.join(__dirname, '..', 'settings.json');
    const raw = fs.readFileSync(settingsPath, 'utf-8');
    const parsed = JSON.parse(raw);
    const host = typeof parsed.host === 'string' && parsed.host.trim() ? parsed.host.trim() : defaultConfig.host;
    const portValue = Number(parsed.port);
    const port = Number.isInteger(portValue) && portValue > 0 ? portValue : defaultConfig.port;
    return { host, port };
  } catch (error) {
    return defaultConfig;
  }
}

function getChatSessionDir() {
  return path.join(app.getPath('userData'), 'chat_sessions');
}

function getChatSessionFilePath(sessionId) {
  return path.join(getChatSessionDir(), `${sessionId}.json`);
}

function ensureChatSessionDir() {
  const dir = getChatSessionDir();
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
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
  return `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
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
  while (fs.existsSync(getChatSessionFilePath(sessionId))) {
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
    const raw = fs.readFileSync(filePath, 'utf-8');
    const parsed = JSON.parse(raw);
    const fallbackSessionId = path.basename(filePath, '.json');
    return normalizeChatSessionData(parsed, fallbackSessionId);
  } catch (error) {
    return null;
  }
}

function writeChatSessionData(session) {
  ensureChatSessionDir();
  const normalized = normalizeChatSessionData(session, session.sessionId || createChatSessionId());
  const filePath = getChatSessionFilePath(normalized.sessionId);
  fs.writeFileSync(filePath, JSON.stringify(normalized, null, 2), 'utf-8');
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
  const filePaths = fs.readdirSync(getChatSessionDir())
    .filter((name) => name.toLowerCase().endsWith('.json'))
    .map((name) => path.join(getChatSessionDir(), name));

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
      if (fs.existsSync(filePath)) {
        fs.unlinkSync(filePath);
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

function getVirtualBounds() {
  const displays = screen.getAllDisplays();
  const bounds = displays.reduce((acc, display) => {
    acc.minX = Math.min(acc.minX, display.bounds.x);
    acc.minY = Math.min(acc.minY, display.bounds.y);
    acc.maxX = Math.max(acc.maxX, display.bounds.x + display.bounds.width);
    acc.maxY = Math.max(acc.maxY, display.bounds.y + display.bounds.height);
    return acc;
  }, { minX: 0, minY: 0, maxX: 0, maxY: 0 });

  return {
    x: bounds.minX,
    y: bounds.minY,
    width: bounds.maxX - bounds.minX,
    height: bounds.maxY - bounds.minY
  };
}

function getInputWindowBounds() {
  const vb = getVirtualBounds();
  const width = 460;
  const height = Math.min(680, Math.max(520, Math.round(vb.height * 0.72)));
  const margin = 24;
  return {
    x: Math.round(vb.x + vb.width - width - margin),
    y: Math.round(vb.y + Math.max(margin, ((vb.height - height) / 2))),
    width,
    height
  };
}

function clampInputWindowBounds(bounds) {
  const vb = getVirtualBounds();
  const width = Math.min(Math.max(320, bounds.width || 460), vb.width);
  const height = Math.min(Math.max(420, bounds.height || 520), vb.height);
  const maxX = vb.x + vb.width - width;
  const maxY = vb.y + vb.height - height;
  const x = Math.min(Math.max(bounds.x ?? vb.x, vb.x), maxX);
  const y = Math.min(Math.max(bounds.y ?? vb.y, vb.y), maxY);
  return { x, y, width, height };
}

function resolveInputWindowBounds() {
  const preferred = inputWindowLastBounds || getInputWindowBounds();
  return clampInputWindowBounds(preferred);
}

function startCursorPoller() {
  if (cursorPoller) {
    clearInterval(cursorPoller);
    cursorPoller = null;
  }
  cursorPoller = setInterval(() => {
    if (!overlayWin || overlayWin.isDestroyed()) return;
    const point = screen.getCursorScreenPoint();
    const bounds = overlayWin.getBounds();
    overlayWin.webContents.send('cursor-position', {
      x: point.x - bounds.x,
      y: point.y - bounds.y,
      screenX: point.x,
      screenY: point.y
    });
  }, 30);
}

function createOverlayWindow() {
  const { x, y, width, height } = getVirtualBounds();
  const platformOptions = process.platform === 'darwin'
    ? { type: 'panel', hiddenInMissionControl: true }
    : { type: 'toolbar' };

  overlayWin = new BrowserWindow({
    x,
    y,
    width,
    height,
    transparent: true,
    backgroundColor: '#00000000',
    frame: false,
    hasShadow: false,
    enableLargerThanScreen: true,
    alwaysOnTop: true,
    resizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    focusable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true
    },
    ...platformOptions
  });

  overlayWin.setMenuBarVisibility(false);
  const overlayPath = path.join(__dirname, 'overlay.html');
  overlayWin.loadFile(overlayPath);
  overlayWin.webContents.on('console-message', (event, level, message) => {
    console.log('[overlay-renderer]', message);
  });
  overlayWin.webContents.on('did-finish-load', () => {
    console.log('[main] overlay renderer loaded', overlayPath);
  });
  overlayWin.webContents.on('did-fail-load', (event, code, desc) => {
    console.error('[main] overlay renderer failed to load', code, desc);
  });

  if (process.platform === 'darwin') {
    overlayWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    overlayWin.setAlwaysOnTop(true, 'screen-saver');
    overlayWin.setIgnoreMouseEvents(true);
    // macOS still uses explicit polling for hit-testing and cursor status.
    startCursorPoller();
  } else {
    // Fullscreen visualization remains click-through; input is handled in the
    // dedicated command window.
    overlayWin.setIgnoreMouseEvents(true, { forward: true });
  }
}

function createInputWindow() {
  const bounds = resolveInputWindowBounds();
  const platformOptions = process.platform === 'darwin'
    ? { type: 'panel', hiddenInMissionControl: true }
    : { type: 'toolbar' };

  inputWin = new BrowserWindow({
    ...bounds,
    transparent: true,
    backgroundColor: '#00000000',
    frame: false,
    hasShadow: false,
    alwaysOnTop: true,
    resizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    focusable: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true
    },
    ...platformOptions
  });

  inputWin.setMenuBarVisibility(false);
  const inputPath = path.join(__dirname, 'input.html');
  inputWin.loadFile(inputPath);
  inputWin.webContents.on('console-message', (event, level, message) => {
    console.log('[input-renderer]', message);
  });
  inputWin.webContents.on('did-finish-load', () => {
    console.log('[main] input renderer loaded', inputPath);
  });
  inputWin.webContents.on('did-fail-load', (event, code, desc) => {
    console.error('[main] input renderer failed to load', code, desc);
  });
  inputWin.on('move', () => {
    if (!inputWin || inputWin.isDestroyed()) return;
    inputWindowLastBounds = clampInputWindowBounds(inputWin.getBounds());
  });
  inputWindowLastBounds = clampInputWindowBounds(inputWin.getBounds());

  if (process.platform === 'darwin') {
    inputWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    inputWin.setAlwaysOnTop(true, 'screen-saver');
  } else {
    inputWin.setAlwaysOnTop(true);
  }
}

function showInputWindow() {
  if (!inputWin || inputWin.isDestroyed()) return;
  const bounds = resolveInputWindowBounds();
  inputWin.setBounds(bounds, false);
  inputWindowLastBounds = bounds;
  if (!inputWin.isVisible()) {
    inputWin.show();
  }
  app.focus();
  inputWin.focus();
  inputWin.webContents.focus();
  inputWin.webContents.send('show-input-window');
}

function hideInputWindow() {
  if (!inputWin || inputWin.isDestroyed()) return;
  inputWin.webContents.send('hide-input-window');
  if (inputWin.isVisible()) {
    inputWin.hide();
  }
}

function dispatchStopAll() {
  if (overlayWin && !overlayWin.isDestroyed()) {
    console.log('[main] stop-all shortcut triggered');
    overlayWin.webContents.send('stop-all');
  }
  if (inputWin && !inputWin.isDestroyed()) {
    inputWin.webContents.send('stop-all');
  }
  hideInputWindow();
}

function createTray() {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">
      <circle cx="8" cy="8" r="5" fill="black"/>
    </svg>
  `;
  const icon = nativeImage.createFromDataURL(`data:image/svg+xml;utf8,${encodeURIComponent(svg)}`);
  if (process.platform === 'darwin') {
    icon.setTemplateImage(true);
  }

  tray = new Tray(icon);
  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Reset/Configure',
      click: () => {
        if (overlayWin && !overlayWin.isDestroyed()) {
          overlayWin.webContents.send('tray-reset-configure');
        }
      }
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => app.quit()
    }
  ]);
  tray.setToolTip('Python-Powered Desktop Overlay');
  tray.setContextMenu(contextMenu);
}

app.whenReady().then(() => {
  if (process.platform === 'darwin' && app.dock) {
    app.dock.hide();
  }

  createOverlayWindow();
  createInputWindow();
  createTray();
  currentChatSessionId = getChatSessionState().currentSessionId;

  registerShortcut('CommandOrControl+Shift+Space', 'show input', () => {
    showInputWindow();
  });
  registerShortcut('CommandOrControl+Shift+X', 'stop + hide input', () => {
    dispatchStopAll();
  });
  registerShortcut('CommandOrControl+Shift+C', 'stop all', () => {
    dispatchStopAll();
  });
  registerShortcut('CommandOrControl+Alt+Shift+C', 'stop all (legacy alias)', () => {
    dispatchStopAll();
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createOverlayWindow();
      createInputWindow();
    }
  });
});

app.on('before-quit', () => {
  globalShortcut.unregisterAll();
  if (cursorPoller) {
    clearInterval(cursorPoller);
    cursorPoller = null;
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// Keep compatibility with legacy renderer channels. Overlay window is now
// permanently click-through; these no longer change mode.
ipcMain.on('toggle-mouse', () => {});
ipcMain.on('cursor-hit-test', () => {});
ipcMain.on('toggle-input-mode', (event, enabled) => {
  if (enabled) {
    showInputWindow();
  }
});

ipcMain.on('input-window-hide-request', () => {
  hideInputWindow();
});

ipcMain.on('request-stop-all', () => {
  dispatchStopAll();
});

ipcMain.handle('get-model-name', async () => {
  return 'Agent';
});

ipcMain.handle('get-server-config', async () => {
  return getServerConfig();
});

ipcMain.handle('get-chat-session-info', async () => {
  const state = getChatSessionState();
  return {
    sessionId: state.currentSessionId,
    startedAt: state.currentSession.startedAt,
    archivedAt: state.currentSession.archivedAt,
  };
});

ipcMain.handle('get-chat-session-state', async (event, payload) => {
  return getChatSessionState(payload?.sessionId || null);
});

ipcMain.handle('create-chat-session', async () => {
  createChatSession(true);
  return getChatSessionState();
});

ipcMain.handle('archive-chat-session', async (event, payload) => {
  return archiveChatSession(payload?.sessionId || '');
});

ipcMain.handle('load-chat-session', async (event, payload) => {
  return loadChatSessionData(payload?.sessionId || null);
});

ipcMain.handle('save-chat-session', async (event, payload) => {
  return saveChatSessionMessages(payload?.sessionId || currentChatSessionId, payload?.messages || []);
});
