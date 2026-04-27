const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function normalizeEnvValue(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function normalizeThumbprint(value) {
  const normalized = normalizeEnvValue(value)?.replace(/\s+/g, '').toUpperCase();
  if (!normalized) {
    return undefined;
  }

  if (!/^[0-9A-F]{40}$/.test(normalized)) {
    throw new Error('WINDOWS_CERTIFICATE_SHA1 must be a 40-character hexadecimal thumbprint.');
  }

  return normalized;
}

function resolveMaybeAbsolute(baseDir, value) {
  if (!value) return undefined;
  return path.isAbsolute(value) ? value : path.resolve(baseDir, value);
}

function escapePowerShellString(value) {
  return String(value).replace(/'/g, "''");
}

function getPowerShellBinary() {
  const candidates = [];
  const systemRoot = process.env.SystemRoot || 'C:\\Windows';

  if (process.env.PWSH_PATH) {
    candidates.push(process.env.PWSH_PATH);
  }
  if (process.env.POWERSHELL_PATH) {
    candidates.push(process.env.POWERSHELL_PATH);
  }

  candidates.push(
    'pwsh.exe',
    'powershell.exe',
    path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'),
  );

  for (const candidate of candidates) {
    try {
      if (path.isAbsolute(candidate) && !fs.existsSync(candidate)) {
        continue;
      }
      return candidate;
    } catch {
      // Keep trying other candidates.
    }
  }

  return 'powershell.exe';
}

function runPowerShell(script) {
  if (process.platform !== 'win32') {
    return '';
  }

  const encoded = Buffer.from(script, 'utf16le').toString('base64');
  return execFileSync(
    getPowerShellBinary(),
    [
      '-NoLogo',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy',
      'Bypass',
      '-EncodedCommand',
      encoded,
    ],
    {
      encoding: 'utf8',
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'ignore'],
    },
  ).trim();
}

function detectWindowsStoreSigningIdentity() {
  if (process.platform !== 'win32') {
    return undefined;
  }

  const certificateSubject = normalizeEnvValue(process.env.WINDOWS_CERTIFICATE_SUBJECT) || 'JARVIS Electron';
  const subjectPattern = `*${escapePowerShellString(certificateSubject)}*`;
  const script = `
    $subjectPattern = '${subjectPattern}';
    $codeSigningOid = '1.3.6.1.5.5.7.3.3';
    $stores = @('Cert:\\CurrentUser\\My', 'Cert:\\LocalMachine\\My');
    $cert = foreach ($store in $stores) {
      $match = Get-ChildItem $store -ErrorAction SilentlyContinue |
        Where-Object {
          $_.HasPrivateKey -and
          $_.Subject -like $subjectPattern -and
          ($_.EnhancedKeyUsageList | Where-Object { $_.ObjectId -eq $codeSigningOid })
        } |
        Select-Object -First 1
      if ($match) {
        $match
        break
      }
    }
    if ($cert) {
      $storeLocation = if ($cert.PSParentPath -match 'LocalMachine') { 'localmachine' } else { 'currentuser' };
      @{
        thumbprint = $cert.Thumbprint;
        storeLocation = $storeLocation;
        storeName = 'My';
        subject = $cert.Subject;
      } | ConvertTo-Json -Compress
    }
  `;

  try {
    const raw = runPowerShell(script);
    return raw ? JSON.parse(raw) : undefined;
  } catch {
    return undefined;
  }
}

function findDefaultWindowsSignTool() {
  if (process.platform !== 'win32') {
    return undefined;
  }

  const explicit = resolveMaybeAbsolute(process.cwd(), normalizeEnvValue(process.env.WINDOWS_SIGNTOOL_PATH));
  if (explicit && fs.existsSync(explicit)) {
    return explicit;
  }

  const programFilesX86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
  const candidateRoots = [
    path.join(programFilesX86, 'Windows Kits', '10', 'bin'),
    path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Windows Kits', '10', 'bin'),
  ];

  for (const root of candidateRoots) {
    if (!fs.existsSync(root)) {
      continue;
    }

    const versions = fs.readdirSync(root, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort((left, right) => right.localeCompare(left, undefined, { numeric: true }));

    for (const version of versions) {
      for (const arch of ['x64', 'arm64', 'x86']) {
        const candidate = path.join(root, version, arch, 'signtool.exe');
        if (fs.existsSync(candidate)) {
          return candidate;
        }
      }
    }
  }

  return undefined;
}

function getWindowsStoreSignParams() {
  const explicitThumbprint = normalizeThumbprint(process.env.WINDOWS_CERTIFICATE_SHA1);
  const detectedIdentity = explicitThumbprint
    ? undefined
    : detectWindowsStoreSigningIdentity();
  const thumbprint = explicitThumbprint || normalizeThumbprint(detectedIdentity?.thumbprint);

  if (!thumbprint) {
    return undefined;
  }

  const storeName = normalizeEnvValue(process.env.WINDOWS_CERTIFICATE_STORE_NAME)
    || detectedIdentity?.storeName
    || 'My';
  const storeLocation = normalizeEnvValue(process.env.WINDOWS_CERTIFICATE_STORE_LOCATION)?.toLowerCase()
    || detectedIdentity?.storeLocation;
  const params = [`/sha1 ${thumbprint}`, `/s ${storeName}`];

  if (storeLocation === 'localmachine' || storeLocation === 'machine') {
    params.push('/sm');
  } else if (storeLocation && storeLocation !== 'currentuser' && storeLocation !== 'user') {
    throw new Error(
      'WINDOWS_CERTIFICATE_STORE_LOCATION must be one of: currentuser, user, localmachine, machine.',
    );
  }

  return params.join(' ');
}

function getWindowsSignOptions(baseDir = process.cwd()) {
  if (process.platform !== 'win32') {
    return undefined;
  }

  const certificateFile = resolveMaybeAbsolute(baseDir, normalizeEnvValue(process.env.WINDOWS_CERTIFICATE_FILE));
  const certificatePassword = normalizeEnvValue(process.env.WINDOWS_CERTIFICATE_PASSWORD);
  const signToolPath = findDefaultWindowsSignTool();
  const signWithParams = normalizeEnvValue(process.env.WINDOWS_SIGN_WITH_PARAMS)
    || getWindowsStoreSignParams();
  const hookModulePath = resolveMaybeAbsolute(baseDir, normalizeEnvValue(process.env.WINDOWS_SIGN_HOOK_MODULE));
  const timestampServer = normalizeEnvValue(process.env.WINDOWS_TIMESTAMP_SERVER);
  const description = normalizeEnvValue(process.env.WINDOWS_SIGN_DESCRIPTION) || 'JARVIS';
  const website = normalizeEnvValue(process.env.WINDOWS_SIGN_WEBSITE);
  const debug = normalizeEnvValue(process.env.WINDOWS_SIGN_DEBUG) === '1';

  const hasSigningConfig = Boolean(
    certificateFile || signWithParams || hookModulePath,
  );

  if (!hasSigningConfig) {
    return undefined;
  }

  return {
    continueOnError: false,
    certificateFile,
    certificatePassword,
    signToolPath,
    signWithParams,
    hookModulePath,
    timestampServer,
    description,
    website,
    debug,
  };
}

function isWindowsExecutableSigned(filePath) {
  if (process.platform !== 'win32') {
    return false;
  }
  if (!filePath || !fs.existsSync(filePath)) {
    return false;
  }

  const normalizedPath = escapePowerShellString(path.resolve(filePath));
  const script = `
    $signature = Get-AuthenticodeSignature -FilePath '${normalizedPath}';
    if ($signature.Status -eq 'Valid' -and $signature.SignerCertificate) {
      'true'
    } else {
      'false'
    }
  `;

  try {
    return runPowerShell(script).toLowerCase() === 'true';
  } catch {
    return false;
  }
}

module.exports = {
  getWindowsSignOptions,
  isWindowsExecutableSigned,
  normalizeEnvValue,
  normalizeThumbprint,
  resolveMaybeAbsolute,
};
