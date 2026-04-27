const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  setWindowInteractive: (interactive) => ipcRenderer.send('toggle-mouse', interactive),
  reportHitTest: (isOver) => ipcRenderer.send('cursor-hit-test', isOver),
  onCursorPosition: (callback) =>
    ipcRenderer.on('cursor-position', (event, point) => callback(point)),
  onResetConfigure: (callback) =>
    ipcRenderer.on('tray-reset-configure', () => callback()),
  onOverlayImage: (callback) =>
    ipcRenderer.on('show-overlay-image', () => callback()),
  onHideOverlayImage: (callback) =>
    ipcRenderer.on('hide-overlay-image', () => callback()),
  onShowInputWindow: (callback) =>
    ipcRenderer.on('show-input-window', () => callback()),
  onHideInputWindow: (callback) =>
    ipcRenderer.on('hide-input-window', () => callback()),
  onClearOverlay: (callback) =>
    ipcRenderer.on('clear-overlay', () => callback()),
  onStopAll: (callback) =>
    ipcRenderer.on('stop-all', () => callback()),
  hideInputWindow: () => ipcRenderer.send('input-window-hide-request'),
  requestStopAll: () => ipcRenderer.send('request-stop-all'),
  setInputMode: (enabled) => ipcRenderer.send('toggle-input-mode', enabled),
  getPlatform: () => process.platform,
  getModelName: () => ipcRenderer.invoke('get-model-name'),
  getServerConfig: () => ipcRenderer.invoke('get-server-config'),
  getChatSessionInfo: () => ipcRenderer.invoke('get-chat-session-info'),
  getChatSessionState: (sessionId) => ipcRenderer.invoke('get-chat-session-state', { sessionId }),
  createChatSession: () => ipcRenderer.invoke('create-chat-session'),
  archiveChatSession: (sessionId) => ipcRenderer.invoke('archive-chat-session', { sessionId }),
  loadChatSession: (sessionId) => ipcRenderer.invoke('load-chat-session', { sessionId }),
  saveChatSession: (sessionId, messages) => ipcRenderer.invoke('save-chat-session', { sessionId, messages })
});
