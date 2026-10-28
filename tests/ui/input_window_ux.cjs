const assert = require('node:assert/strict');
const { test, before, after, afterEach } = require('node:test');
const fs = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');
const { createChatSessionManager } = require('../../ui/main/chat_sessions');

const uiRoot = path.resolve(__dirname, '../../ui');
let browser;
let server;
let origin;
const scenarios = [];

before(async () => {
  server = http.createServer(async (request, response) => {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (pathname === '/favicon.ico') {
      response.writeHead(204).end();
      return;
    }
    const file = path.resolve(uiRoot, `.${pathname === '/' ? '/input.html' : pathname}`);
    if (!file.startsWith(uiRoot + path.sep)) {
      response.writeHead(403).end();
      return;
    }
    try {
      const content = await fs.readFile(file);
      const type = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }[path.extname(file)];
      response.writeHead(200, { 'Content-Type': type || 'application/octet-stream' }).end(content);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, executablePath: process.env.UI_TEST_CHROMIUM_PATH || undefined });
});

afterEach(async () => {
  for (const scenario of scenarios.splice(0)) {
    await scenario.context.close();
    assert.ok(scenario.dataDir.startsWith(path.join(os.tmpdir(), 'jarvis-ux-')), 'Only remove this test\'s temporary session directory');
    await fs.rm(scenario.dataDir, { recursive: true, force: true });
    assert.deepEqual(scenario.errors, [], 'No browser console or runtime errors');
  }
});

after(async () => {
  await browser?.close();
  server?.closeAllConnections();
  await new Promise((resolve) => server ? server.close(resolve) : resolve());
});

async function openScenario({ messages = [], platform = 'win32', storageUnavailable = false, viewport = { width: 460, height: 680 } } = {}) {
  const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'jarvis-ux-'));
  const app = { getPath: () => dataDir };
  let manager = createChatSessionManager({ app });
  manager.initialize();
  const sessionId = manager.getChatSessionState().currentSessionId;
  manager.saveChatSessionMessages(sessionId, messages);
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) errors.push(message.text());
  });
  const calls = [];
  await page.exposeFunction('invokeSessionApi', (method, args) => {
    calls.push(method);
    if (method === 'createChatSession') {
      manager.createChatSession(true);
      return manager.getChatSessionState();
    }
    return manager[method](...args);
  });
  await page.addInitScript(({ platform, storageUnavailable }) => {
    if (storageUnavailable) {
      Storage.prototype.getItem = () => { throw new Error('Storage unavailable'); };
      Storage.prototype.setItem = () => { throw new Error('Storage unavailable'); };
    }
    const state = window.uiTest = { hideRequests: 0, stopRequests: 0, sessionReads: 0, sent: [], listeners: {} };
    window.api = {
      getPlatform: () => platform,
      getServerConfig: async () => ({ host: '127.0.0.1', port: 58870 }),
      getChatSessionState: async (id) => {
        const result = await window.invokeSessionApi('getChatSessionState', [id]);
        state.sessionReads++;
        return result;
      },
      saveChatSession: (id, messages) => window.invokeSessionApi('saveChatSessionMessages', [id, messages]),
      createChatSession: () => window.invokeSessionApi('createChatSession', []),
      unarchiveChatSession: (id) => window.invokeSessionApi('unarchiveChatSession', [id]),
      onShowInputWindow: (callback) => { state.listeners.show = callback; },
      onHideInputWindow: (callback) => { state.listeners.hide = callback; },
      onStopAll: (callback) => { state.listeners.stop = callback; },
      hideInputWindow: () => { state.hideRequests++; state.listeners.hide?.(); },
      requestStopAll: () => { state.stopRequests++; state.listeners.stop?.(); },
    };
    window.WebSocket = class extends EventTarget {
      static OPEN = 1;
      readyState = 1;
      constructor() {
        super();
        state.socket = this;
        setTimeout(() => this.dispatchEvent(new Event('open')), 0);
      }
      send(payload) { state.sent.push(JSON.parse(payload)); }
    };
  }, { platform, storageUnavailable });
  const scenario = { context, page, errors, dataDir, calls, sessionId,
    get manager() { return manager; },
    restart() { manager = createChatSessionManager({ app }); manager.initialize(); },
  };
  scenarios.push(scenario);
  await page.goto(`${origin}/input.html`);
  await page.locator('#chat-status[data-phase="idle"]').waitFor();
  assert.equal(await page.title(), 'JARVIS Chat');
  assert.equal(new URL(page.url()).pathname, '/input.html');
  assert.equal(await page.locator('#chat-title').textContent(), 'JARVIS');
  return scenario;
}

async function capture(page, name) {
  if (!process.env.UI_TEST_SCREENSHOT_DIR) return;
  await fs.mkdir(process.env.UI_TEST_SCREENSHOT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(process.env.UI_TEST_SCREENSHOT_DIR, `${name}.png`) });
}

test('first-run guidance exposes controls, remembers minimization, and supports keyboard recall', async () => {
  const { page } = await openScenario();
  const toggle = page.locator('#chat-guidance-toggle');
  assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  assert.deepEqual(await page.locator('#chat-guidance-details kbd').allTextContents(), ['Ctrl + Shift + Space', 'Ctrl + Shift + C', 'Esc']);
  assert.match(await page.locator('#chat-guidance-details').textContent(), /Hide leaves actions running\. Stop interrupts them/);
  await capture(page, 'first-run');
  await toggle.click();
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
  await page.reload();
  await page.locator('#chat-status[data-phase="idle"]').waitFor();
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('#chat-guidance-recall').isVisible(), true);
  await toggle.focus();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Shift+Tab');
  assert.notEqual(await toggle.evaluate((el) => getComputedStyle(el).boxShadow), 'none');
  await page.keyboard.press('Enter');
  assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  await page.keyboard.press('Space');
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
});

test('Mac shortcut labels match both help surfaces', async () => {
  const { page } = await openScenario({ platform: 'darwin' });
  assert.deepEqual(await page.locator('#chat-guidance-details kbd').allTextContents(), ['Cmd + Shift + Space', 'Cmd + Shift + C', 'Esc']);
  await page.locator('#chat-settings-toggle').click();
  await page.locator('#chat-settings-help').click();
  assert.deepEqual(await page.locator('#chat-help-panel kbd').allTextContents(), ['Cmd + Shift + Space', 'Cmd + Shift + C', 'Esc']);
});

test('unavailable preference storage does not block guidance or input', async () => {
  const { page } = await openScenario({ storageUnavailable: true });
  await page.locator('#chat-guidance-toggle').click();
  assert.equal(await page.locator('#chat-guidance-details').isVisible(), false);
  await page.locator('#command-input').fill('Technical command');
  assert.equal(await page.locator('#command-input').inputValue(), 'Technical command');
});

test('hide leaves work running, Escape closes menus first, and Stop interrupts work', async () => {
  const { page } = await openScenario();
  await page.locator('#chat-settings-toggle').click();
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#chat-settings-popover').isVisible(), false);
  await page.locator('#chat-history').click();
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#history-panel').isVisible(), false);
  assert.equal(await page.evaluate(() => window.uiTest.hideRequests), 0);
  await page.locator('#command-input').fill('Inspect project');
  await page.locator('#command-input').press('Enter');
  assert.equal(await page.locator('#command-send').getAttribute('data-mode'), 'stop');
  await page.locator('#command-input').press('Escape');
  assert.equal(await page.evaluate(() => window.uiTest.hideRequests), 1);
  assert.equal(await page.evaluate(() => window.uiTest.stopRequests), 0);
  assert.equal(await page.locator('#command-send').getAttribute('data-mode'), 'stop');
  await page.locator('#command-send').click();
  assert.equal(await page.evaluate(() => window.uiTest.stopRequests), 1);
  assert.equal(await page.locator('#command-send').getAttribute('data-mode'), 'send');
  assert.equal(await page.locator('#chat-status').getAttribute('data-phase'), 'stopped');
});

function savedMessages(count = 24) {
  return Array.from({ length: count }, (_, index) => ({ role: index % 2 ? 'assistant' : 'user', text: `Saved message ${index + 1}`, ts: Date.now() - 60000 + index }));
}

test('disk-backed restored history stays visible at the latest message without replay or duplicate markers', async () => {
  const scenario = await openScenario({ messages: savedMessages() });
  const { page } = scenario;
  const marker = page.locator('#chat-session-marker');
  await page.locator('.chat-msg').last().waitFor();
  assert.match(await marker.textContent(), /Resumed session · 24 saved messages/);
  assert.match(await marker.textContent(), /History restored; no actions restarted/);
  assert.equal(await page.locator('.chat-msg').count(), 24);
  assert.equal(scenario.calls.includes('saveChatSessionMessages'), false, 'Restoration does not rewrite history');
  assert.deepEqual(await page.evaluate(() => window.uiTest.sent), [], 'Restoration never sends a command');
  const markerBounds = await marker.boundingBox();
  assert.ok(markerBounds.y > 0 && markerBounds.y + markerBounds.height < 680);
  assert.ok(await page.locator('#chat-messages').evaluate((el) => el.scrollTop > 0));
  await page.locator('#chat-guidance-toggle').click();
  await capture(page, 'resumed-compact');
  const originalSummary = await marker.textContent();
  await marker.evaluate((el) => {
    window.uiTest.markerMutations = 0;
    new MutationObserver((mutations) => { window.uiTest.markerMutations += mutations.length; })
      .observe(el, { subtree: true, childList: true, characterData: true });
  });
  await page.locator('#command-input').fill('Continue');
  await page.locator('#command-input').press('Enter');
  assert.equal(await marker.textContent(), originalSummary, 'New messages do not change restored message count');
  assert.equal(await page.evaluate(() => window.uiTest.markerMutations), 0, 'Unchanged resume metadata does not repeat live announcements');
  await page.evaluate(() => window.uiTest.socket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ command: 'chat_response', text: 'Continued response' }) })));
  await page.waitForFunction(() => document.querySelector('#command-send').dataset.mode === 'send');
  await page.waitForFunction(() => document.querySelectorAll('.chat-msg').length === 26);
  // Reload a fresh manager from disk, then refresh the real session API path.
  await page.waitForFunction(async () => (await window.api.getChatSessionState()).currentSession.messages.length === 26);
  scenario.restart();
  await page.reload();
  await page.locator('#chat-status[data-phase="idle"]').waitFor();
  assert.match(await marker.textContent(), /26 saved messages/);
  const sessionReads = await page.evaluate(() => window.uiTest.sessionReads);
  await page.evaluate(() => window.uiTest.listeners.show());
  await page.waitForFunction((previousReads) => window.uiTest.sessionReads > previousReads, sessionReads);
  assert.equal(await page.locator('.chat-msg').count(), 26);
  assert.equal(await page.locator('#chat-session-marker').count(), 1);
  assert.equal(scenario.manager.loadChatSessionData(scenario.sessionId).messages.length, 26);
  await page.locator('#chat-new').click();
  await page.locator('#chat-empty-state').waitFor();
  assert.equal(await marker.isVisible(), false);
  assert.equal(await page.locator('.chat-msg').count(), 0);
  await page.locator('#chat-history').click();
  await page.locator('.history-item-main').filter({ hasText: 'Saved message 1' }).click();
  await marker.waitFor();
  assert.match(await marker.textContent(), /Resumed session · 26 saved messages/);
});

test('empty and archived sessions are distinguished from resumed active sessions', async () => {
  const scenario = await openScenario();
  const { page } = scenario;
  assert.equal(await page.locator('#chat-session-marker').isVisible(), false);
  assert.equal(await page.locator('#chat-empty-state').isVisible(), true);
  scenario.manager.saveChatSessionMessages(scenario.sessionId, savedMessages(1));
  scenario.manager.archiveChatSession(scenario.sessionId);
  await page.reload();
  await page.locator('#chat-status[data-phase="idle"]').waitFor();
  await page.locator('#chat-history').click();
  await page.locator('#history-filter-archived').click();
  await page.locator('.history-item-main').click();
  await page.locator('#chat-session-marker').waitFor();
  assert.match(await page.locator('#chat-session-summary').textContent(), /Archived session · 1 saved message$/);
  assert.match(await page.locator('#chat-session-detail').textContent(), /Read-only history; no actions restarted/);
  assert.equal(await page.locator('#command-input').isDisabled(), true);
  await page.locator('#chat-history').click();
  await page.locator('#history-filter-archived').click();
  await page.getByRole('button', { name: 'Restore chat', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#chat-session-summary').textContent.startsWith('Resumed session'));
  assert.match(await page.locator('#chat-session-detail').textContent(), /History restored; no actions restarted/);
  assert.equal(await page.locator('#command-input').isDisabled(), false);
});

test('guidance and restored state keep composer usable at compact window sizes', async () => {
  const { page } = await openScenario({ messages: savedMessages(4) });
  for (const viewport of [{ width: 460, height: 680 }, { width: 320, height: 520 }, { width: 320, height: 420 }]) {
    await page.setViewportSize(viewport);
    for (const expanded of [true, false]) {
      if ((await page.locator('#chat-guidance-toggle').getAttribute('aria-expanded')) !== String(expanded)) {
        await page.locator('#chat-guidance-toggle').click();
      }
      for (const selector of ['#command-input', '#command-send', '#chat-guidance-toggle', '#chat-session-marker']) {
        const bounds = await page.locator(selector).boundingBox();
        assert.ok(bounds && bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= viewport.width && bounds.y + bounds.height <= viewport.height, `${selector} stays inside ${JSON.stringify(viewport)}`);
      }
      assert.equal(await page.locator('#chat-shell').evaluate((el) => el.scrollWidth <= el.clientWidth), true);
      const transcriptHeight = (await page.locator('#chat-messages').boundingBox()).height;
      assert.ok(transcriptHeight >= 80, `Useful transcript space remains: ${transcriptHeight}px at ${JSON.stringify(viewport)}, expanded=${expanded}`);
      if (!expanded) assert.ok((await page.locator('#chat-guidance').boundingBox()).height <= 40, 'Recall guidance is one compact row');
    }
    await capture(page, `compact-${viewport.width}x${viewport.height}`);
  }
});
