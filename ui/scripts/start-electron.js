const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const env = { ...process.env };
const uiRoot = path.resolve(process.cwd());

// Some environments export this globally and force Electron into Node mode.
delete env.ELECTRON_RUN_AS_NODE;

function normalizePathEnv(value) {
  if (!value || typeof value !== "string" || !value.trim()) {
    return undefined;
  }
  const trimmed = value.trim();
  return path.isAbsolute(trimmed) ? trimmed : path.resolve(uiRoot, trimmed);
}

function getExecutableOverride() {
  const appExecutable = normalizePathEnv(process.env.JARVIS_UI_EXECUTABLE);
  if (appExecutable && fs.existsSync(appExecutable)) {
    return { command: appExecutable, args: [], label: "packaged UI executable" };
  }

  const electronOverride = normalizePathEnv(process.env.JARVIS_ELECTRON_BINARY);
  if (electronOverride && fs.existsSync(electronOverride)) {
    return { command: electronOverride, args: ["."], label: "override Electron runtime" };
  }

  return { command: require("electron"), args: ["."], label: "npm Electron runtime" };
}

function launchElectron() {
  const launchTarget = getExecutableOverride();
  console.warn(`[ui-launcher] Launching ${launchTarget.label}: ${launchTarget.command}`);

  let child;
  try {
    child = spawn(launchTarget.command, launchTarget.args, {
      cwd: process.cwd(),
      env,
      stdio: "inherit",
    });
  } catch (error) {
    console.error("[ui-launcher] Failed to launch Electron:", error?.message || error);
    process.exit(1);
  }

  child.on("error", (error) => {
    console.error("[ui-launcher] Electron process error:", error?.message || error);
    process.exit(1);
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }

    process.exit(code ?? 1);
  });
}

launchElectron();
