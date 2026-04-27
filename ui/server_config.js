const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const DEFAULT_SERVER_CONFIG = Object.freeze({ host: '127.0.0.1', port: 8765 });

function readJsonObject(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_error) {
    return {};
  }
}

function getRuntimeStatePath(projectRoot, env = process.env) {
  const explicit = env?.JARVIS_RUNTIME_STATE_PATH;
  if (typeof explicit === 'string' && explicit.trim()) {
    return explicit.trim();
  }

  const digest = crypto
    .createHash('sha1')
    .update(projectRoot, 'utf8')
    .digest('hex')
    .slice(0, 12);
  const fileName = `${path.basename(projectRoot)}-${digest}.json`;
  return path.join(os.tmpdir(), 'jarvis-runtime', fileName);
}

function getServerConfig({
  projectRoot = path.resolve(__dirname, '..'),
  env = process.env,
  defaultConfig = DEFAULT_SERVER_CONFIG,
} = {}) {
  const settingsPath = path.join(projectRoot, 'settings.json');
  const runtimeStatePath = getRuntimeStatePath(projectRoot, env);
  const settings = readJsonObject(settingsPath);
  const runtime = readJsonObject(runtimeStatePath);

  const runtimeHost = typeof runtime.host === 'string' ? runtime.host.trim() : '';
  const settingsHost = typeof settings.host === 'string' ? settings.host.trim() : '';
  const host = runtimeHost || settingsHost || defaultConfig.host;

  const runtimePort = Number(runtime.port);
  const settingsPort = Number(settings.port);
  const port = Number.isInteger(runtimePort) && runtimePort > 0
    ? runtimePort
    : (Number.isInteger(settingsPort) && settingsPort > 0 ? settingsPort : defaultConfig.port);
  return { host, port };
}

module.exports = {
  DEFAULT_SERVER_CONFIG,
  getRuntimeStatePath,
  getServerConfig,
  readJsonObject,
};
