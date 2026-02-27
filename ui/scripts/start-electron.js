const { spawn } = require("node:child_process");

const electronPath = require("electron");
const env = { ...process.env };

// Some environments export this globally and force Electron into Node mode.
delete env.ELECTRON_RUN_AS_NODE;

const child = spawn(electronPath, ["."], {
  cwd: process.cwd(),
  env,
  stdio: "inherit",
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
