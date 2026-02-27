const { app, BrowserWindow, screen, ipcMain, Menu, Tray, nativeImage, globalShortcut } = require('electron');
const fs = require('fs');
const path = require('path');

let overlayWin;
let inputWin;
let tray;
let cursorPoller;
let inputWindowLastBounds = null;
const chatSessionStartedAt = new Date().toISOString();
const chatSessionId = chatSessionStartedAt.replace(/[:.]/g, '-');
const MAX_PERSISTED_CHAT_MESSAGES = 300;

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

function getChatSessionFilePath() {
  return path.join(getChatSessionDir(), `${chatSessionId}.json`);
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
    if (!['user', 'assistant', 'system'].includes(role)) continue;
    out.push({ role, text, ts });
  }
  return out.slice(-MAX_PERSISTED_CHAT_MESSAGES);
}

function ensureChatSessionStorage() {
  const dir = getChatSessionDir();
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  const filePath = getChatSessionFilePath();
  if (!fs.existsSync(filePath)) {
    const initialPayload = {
      sessionId: chatSessionId,
      startedAt: chatSessionStartedAt,
      updatedAt: chatSessionStartedAt,
      messages: [],
    };
    fs.writeFileSync(filePath, JSON.stringify(initialPayload, null, 2), 'utf-8');
  }
  return filePath;
}

function loadChatSessionData() {
  const filePath = ensureChatSessionStorage();
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const parsed = JSON.parse(raw);
    return {
      sessionId: chatSessionId,
      startedAt: chatSessionStartedAt,
      updatedAt: parsed?.updatedAt || chatSessionStartedAt,
      messages: sanitizeChatMessages(parsed?.messages || []),
    };
  } catch (error) {
    return {
      sessionId: chatSessionId,
      startedAt: chatSessionStartedAt,
      updatedAt: chatSessionStartedAt,
      messages: [],
    };
  }
}

function saveChatSessionMessages(messages) {
  const filePath = ensureChatSessionStorage();
  const sanitized = sanitizeChatMessages(messages);
  const payload = {
    sessionId: chatSessionId,
    startedAt: chatSessionStartedAt,
    updatedAt: new Date().toISOString(),
    messages: sanitized,
  };
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), 'utf-8');
  return {
    sessionId: chatSessionId,
    count: sanitized.length,
    updatedAt: payload.updatedAt,
  };
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
  ensureChatSessionStorage();

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
  return {
    sessionId: chatSessionId,
    startedAt: chatSessionStartedAt,
  };
});

ipcMain.handle('load-chat-session', async () => {
  return loadChatSessionData();
});

ipcMain.handle('save-chat-session', async (event, payload) => {
  return saveChatSessionMessages(payload?.messages || []);
});
