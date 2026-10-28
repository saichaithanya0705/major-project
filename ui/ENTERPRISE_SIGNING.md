# Electron On Managed Windows

This project's `npm run dev` path uses Electron's development runtime from `node_modules/electron`.

On managed Windows machines with AppLocker / WDAC / Code Integrity enabled, that runtime can be blocked even if it is locally re-signed with a self-signed certificate. On this machine, Windows Code Integrity reported that Electron did not meet the enterprise signing level requirements.

## Root Cause

The Electron framework itself is not broken here. The blocked component is the Windows executable trust chain:

- the development Electron runtime from `node_modules/electron/dist/electron.exe`
- locally self-signed copies of that runtime

Managed Windows only allows binaries that satisfy the machine's enterprise signing policy.

## Real Fix

Run a trusted, enterprise-signed Electron build instead of the unsigned development runtime.

This repo now supports that in two ways:

1. Build a signed Windows package with Electron Forge.
2. Launch a trusted packaged executable by setting `JARVIS_UI_EXECUTABLE`.

`npm run dev` now launches the Electron runtime from `node_modules/electron` by default. If you need to launch a packaged enterprise-signed executable, set `JARVIS_UI_EXECUTABLE` explicitly.

## Building A Signed Windows Package

The Forge config reads Electron's official Windows signing inputs:

- `WINDOWS_CERTIFICATE_FILE`
- `WINDOWS_CERTIFICATE_PASSWORD`
- `WINDOWS_CERTIFICATE_SHA1`
- `WINDOWS_CERTIFICATE_STORE_NAME`
- `WINDOWS_CERTIFICATE_STORE_LOCATION`
- `WINDOWS_SIGNTOOL_PATH`
- `WINDOWS_SIGN_WITH_PARAMS`
- `WINDOWS_SIGN_HOOK_MODULE`
- `WINDOWS_TIMESTAMP_SERVER`
- `WINDOWS_SIGN_DESCRIPTION`
- `WINDOWS_SIGN_WEBSITE`

Useful commands:

```powershell
cd ui
npm run package:win
npm run make:win
```

If your organization uses an HSM or cloud signing provider, prefer `WINDOWS_SIGN_WITH_PARAMS` or `WINDOWS_SIGN_HOOK_MODULE`.

If your organization installs a code-signing certificate into the Windows certificate store instead of giving you a `.pfx`, you can point Forge at the store-backed signer directly:

```powershell
$env:WINDOWS_SIGNTOOL_PATH = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe'
$env:WINDOWS_CERTIFICATE_SHA1 = '0123456789ABCDEF0123456789ABCDEF01234567'
$env:WINDOWS_CERTIFICATE_STORE_NAME = 'My'
$env:WINDOWS_CERTIFICATE_STORE_LOCATION = 'CurrentUser'
cd ui
npm run package:win
```

`WINDOWS_SIGN_WITH_PARAMS` still takes precedence if you need a fully custom `signtool.exe` command line.

## Launching A Trusted Native Electron Build

For local development on Windows, start both `app.py` and the UI from the **project root** with one command:

```powershell
.\start-dev.ps1
```

The launcher prefers the project `.venv`, falls back to `.venv-1`, and accepts `-PythonCommand 'C:\Path\To\python.exe'` for another environment. The app starts the UI after the server is ready. Press **Ctrl+C** in that terminal to stop both, including the UI's child processes.

If you already have a packaged and enterprise-approved executable, set it before launching:

```powershell
$env:JARVIS_UI_EXECUTABLE = 'C:\Path\To\JARVIS.exe'
.\start-dev.ps1
```

`app.py` launches this executable directly, so npm and `node_modules/electron` are not required for this UI path. It passes the project's runtime-state location to the packaged UI so both processes use the same backend connection settings. An explicit missing path fails startup; it does not fall back to an unsigned runtime. Use an absolute path where possible; relative override paths resolve from `ui`.

Without `JARVIS_UI_EXECUTABLE`, the app uses the normal `npm run dev` flow in `ui`.

If you have an enterprise-approved Electron runtime instead, use:

```powershell
$env:JARVIS_ELECTRON_BINARY = 'C:\Path\To\electron.exe'
.\start-dev.ps1
```

For UI-only development, `cd ui` followed by `npm run dev` still honors both overrides. `JARVIS_UI_EXECUTABLE` takes precedence over `JARVIS_ELECTRON_BINARY`. To return to the default development runtime, remove the overrides with `Remove-Item Env:JARVIS_UI_EXECUTABLE, Env:JARVIS_ELECTRON_BINARY -ErrorAction SilentlyContinue`.

## What Will Not Fix This

The following are not sufficient on a machine enforcing enterprise signing levels:

- copying `electron.exe` to another folder
- re-signing Electron with a local self-signed certificate
- trusting that certificate only in the current user store

Those steps may produce a valid Authenticode signature, but they still do not satisfy the machine's enterprise code integrity policy.
