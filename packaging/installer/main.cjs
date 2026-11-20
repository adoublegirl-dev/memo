const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const {
  parseCodexMemoEnv,
  inferRootFromRuntime,
  normalizeMemoRoot,
  memoDatabase,
  hasMemoDatabase,
  findMemoRootsNear,
  profileEvidencePaths,
  selectSettings,
} = require('./path_contract.cjs');

const INSTALLER_ROOT = path.resolve(__dirname, '..');
const RUNNER = path.join(INSTALLER_ROOT, 'installer', 'installer_runner.py');
const RUNTIME_PYTHON = path.join(INSTALLER_ROOT, 'runtime', 'python.exe'); // legacy Full layout
const BOOTSTRAP_PYTHON = path.join(INSTALLER_ROOT, 'bootstrap-runtime', 'python.exe');
const OFFLINE_ASSET_ARCHIVE = path.join(INSTALLER_ROOT, 'runtime-package', 'memo-offline-assets.zip');
const BOOT_URL = 'http://127.0.0.1:9120';

let mainWindow = null;
let companionMode = false;
let profileHomesCache = null;
const memoRootCandidateCache = new Map();

function settingsPath() {
  return path.join(app.getPath('appData'), 'Memo', 'memo-installer-settings.json');
}

function programDataSettingsPath() {
  return path.join(process.env.ProgramData || 'C:\\ProgramData', 'Memo', 'location.json');
}

function profileHomes() {
  if (profileHomesCache) return [...profileHomesCache];
  const homes = [app.getPath('home'), process.env.USERPROFILE || ''];
  const usersRoot = path.join(process.env.SystemDrive || 'C:', 'Users');
  try {
    for (const entry of fs.readdirSync(usersRoot, { withFileTypes: true })) {
      if (entry.isDirectory() && !entry.isSymbolicLink()) homes.push(path.join(usersRoot, entry.name));
    }
  } catch (_) {}
  const seen = new Set();
  profileHomesCache = homes.filter(Boolean).filter((home) => {
    const key = path.resolve(home).toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return [...profileHomesCache];
}

function legacySettingsPaths() {
  return [path.join(app.getPath('userData'), 'memo-installer-settings.json'), ...profileEvidencePaths(profileHomes()).settings];
}

function defaultUserRoot() {
  return path.join(process.env.LOCALAPPDATA || app.getPath('userData'), 'Memo');
}

function readJson(candidate) {
  try {
    const parsed = JSON.parse(fs.readFileSync(candidate, 'utf8'));
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (_) { return null; }
}

function readSettings() {
  const records = [];
  const seen = new Set();
  for (const candidate of [settingsPath(), programDataSettingsPath(), ...legacySettingsPaths()]) {
    const key = path.resolve(candidate).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const parsed = readJson(candidate);
    if (parsed) records.push(parsed);
  }
  return selectSettings(records, hasMemoDatabase);
}

function readCodexMemoEnvs() {
  const result = [];
  for (const target of profileEvidencePaths(profileHomes()).codex) {
    try {
      const parsed = parseCodexMemoEnv(fs.readFileSync(target, 'utf8'));
      if (Object.keys(parsed).length) result.push(parsed);
    } catch (_) {}
  }
  return result;
}

function writeJsonBestEffort(target, values) {
  try {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, JSON.stringify(values, null, 2), 'utf8');
    return true;
  } catch (_) { return false; }
}

function writeSettings(values) {
  const merged = { ...readSettings(), ...values };
  writeJsonBestEffort(settingsPath(), merged);
  writeJsonBestEffort(programDataSettingsPath(), merged);
  if (merged.userRoot) writeJsonBestEffort(path.join(merged.userRoot, 'config', 'memo-location.json'), merged);
  memoRootCandidateCache.clear();
}

function inspectMemoRoot(root, kind = 'legacy') {
  const normalized = normalizeMemoRoot(root);
  if (!hasMemoDatabase(normalized)) return null;
  const database = memoDatabase(normalized);
  const stat = fs.statSync(database);
  return { root: normalized, database, kind, size: stat.size, modifiedAt: stat.mtime.toISOString() };
}

function appendCodexRoots(roots, codex) {
  roots.push(codex.MEMO_USER_ROOT);
  roots.push(codex.MEMO_DATA_ROOT ? path.dirname(codex.MEMO_DATA_ROOT) : '');
  roots.push(codex.MEMO_DB_PATH ? path.dirname(path.dirname(codex.MEMO_DB_PATH)) : '');
  roots.push(inferRootFromRuntime(codex.PYTHON_EXE));
  roots.push(codex.MEMO_RUNTIME_ROOT ? inferRootFromRuntime(path.join(codex.MEMO_RUNTIME_ROOT, 'python.exe')) : '');
}

function boundedDriveScanRoots() {
  const found = [];
  for (let code = 67; code <= 90; code += 1) {
    const drive = `${String.fromCharCode(code)}:\\`;
    if (!fs.existsSync(drive)) continue;
    try {
      for (const entry of fs.readdirSync(drive, { withFileTypes: true })) {
        if (!entry.isDirectory() || entry.isSymbolicLink() || !/(memo|memory)/i.test(entry.name)) continue;
        found.push(...findMemoRootsNear(path.join(drive, entry.name), 2, 300));
      }
    } catch (_) {}
  }
  return found;
}

function candidateMemoRoots(deepScan = true) {
  const cacheKey = deepScan ? 'deep' : 'evidence';
  if (memoRootCandidateCache.has(cacheKey)) return [...memoRootCandidateCache.get(cacheKey)];
  // Explicit handoff and currently configured Agent paths are stronger evidence
  // than installer settings: a failed install may have written a newer empty
  // C-drive database while Codex is still using the real D-drive database.
  const roots = [
    process.env.MEMO_USER_ROOT,
    process.env.MEMO_DATA_ROOT ? path.dirname(process.env.MEMO_DATA_ROOT) : '',
    process.env.MEMO_DB_PATH ? path.dirname(path.dirname(process.env.MEMO_DB_PATH)) : '',
    inferRootFromRuntime(process.env.PYTHON_EXE),
    process.env.MEMO_RUNTIME_ROOT ? inferRootFromRuntime(path.join(process.env.MEMO_RUNTIME_ROOT, 'python.exe')) : '',
  ];
  for (const codex of readCodexMemoEnvs()) appendCodexRoots(roots, codex);
  roots.push(readSettings().userRoot, defaultUserRoot());
  for (const home of profileHomes()) {
    roots.push(path.join(home, 'Memo'));
    roots.push(path.join(home, 'Documents', 'Memo'));
    roots.push(path.join(home, 'Desktop', 'Memo'));
  }
  if (deepScan) {
    roots.push(...boundedDriveScanRoots());
    let current = path.dirname(process.execPath || process.cwd());
    for (let depth = 0; depth < 7; depth += 1) {
      roots.push(current);
      roots.push(...findMemoRootsNear(current, 1, 80));
      const parent = path.dirname(current);
      if (parent === current) break;
      current = parent;
    }
  }
  const seen = new Set();
  const normalized = roots.map(normalizeMemoRoot).filter(Boolean).filter((root) => {
    const key = root.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  memoRootCandidateCache.set(cacheKey, normalized);
  return [...normalized];
}

function discoverMemoData() {
  const standard = normalizeMemoRoot(defaultUserRoot());
  const preferred = normalizeMemoRoot(userRoot());
  return candidateMemoRoots().map((root) => {
    const kind = root.toLowerCase() === standard.toLowerCase() ? 'standard' : (preferred && root.toLowerCase() === preferred.toLowerCase() ? 'selected' : 'legacy');
    return inspectMemoRoot(root, kind);
  }).filter(Boolean).sort((a, b) => Date.parse(b.modifiedAt) - Date.parse(a.modifiedAt));
}

function userRoot(overrideRoot = '') {
  if (overrideRoot) return normalizeMemoRoot(overrideRoot);
  const evidenceCandidates = candidateMemoRoots(false);
  const evidenceMatch = evidenceCandidates.find((candidate) => hasMemoDatabase(candidate));
  if (evidenceMatch) return evidenceMatch;
  const deepMatch = candidateMemoRoots(true).find((candidate) => hasMemoDatabase(candidate));
  return deepMatch || normalizeMemoRoot(readSettings().userRoot || process.env.MEMO_USER_ROOT || defaultUserRoot());
}

function installedAppRoot(overrideRoot = '') {
  return path.join(userRoot(overrideRoot), 'Programs', 'Memo', 'app');
}

function installedRuntimePython(overrideRoot = '') {
  const root = userRoot(overrideRoot);
  const stableRuntime = path.join(root, 'Programs', 'Memo', 'runtime', 'python.exe');
  if (fs.existsSync(stableRuntime)) return stableRuntime;
  for (const candidateRoot of candidateMemoRoots()) {
    const candidateRuntime = path.join(candidateRoot, 'Programs', 'Memo', 'runtime', 'python.exe');
    if (fs.existsSync(candidateRuntime)) return candidateRuntime;
  }
  if (fs.existsSync(RUNTIME_PYTHON)) return RUNTIME_PYTHON;
  const legacyRuntimeCandidates = [
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Memo', 'resources', 'app', 'runtime', 'python.exe'),
    path.join(path.dirname(process.execPath || ''), 'resources', 'app', 'runtime', 'python.exe'),
  ];
  const legacy = legacyRuntimeCandidates.find((candidate) => candidate && fs.existsSync(candidate));
  return legacy || '';
}

function fullOfflineAssetsAvailable() {
  return fs.existsSync(BOOTSTRAP_PYTHON) && fs.existsSync(OFFLINE_ASSET_ARCHIVE);
}

function runtimeStatus(overrideRoot = '') {
  const python = installedRuntimePython(overrideRoot);
  const bundled = fs.existsSync(RUNTIME_PYTHON) || fullOfflineAssetsAvailable();
  return {
    available: Boolean(python || bundled),
    python: python || (bundled ? runnerPython(overrideRoot) : ''),
    bundled,
    offlineArchive: fullOfflineAssetsAvailable(),
    expectedStablePath: path.join(userRoot(overrideRoot), 'Programs', 'Memo', 'runtime', 'python.exe'),
  };
}

function runnerPython(overrideRoot = '') {
  // Full uses a minimal bootstrap so the large pruned runtime can be extracted
  // directly into its stable destination instead of being copied twice.
  if (fullOfflineAssetsAvailable()) return BOOTSTRAP_PYTHON;
  if (fs.existsSync(RUNTIME_PYTHON)) return RUNTIME_PYTHON;
  const runtime = installedRuntimePython(overrideRoot);
  if (runtime) return runtime;
  return app.isPackaged ? '' : (process.env.PYTHON_EXE || 'python');
}

function serviceEnv(overrideRoot = '') {
  const root = userRoot(overrideRoot);
  const data = path.join(root, 'data');
  const stableRuntime = path.join(root, 'Programs', 'Memo', 'runtime');
  const stableModel = path.join(root, 'Programs', 'Memo', 'models', 'bge-small-zh-v1.5');
  const python = installedRuntimePython(root) || path.join(stableRuntime, 'python.exe');
  const environment = {
    ...process.env,
    MEMO_USER_ROOT: root,
    MEMO_DATA_ROOT: data,
    MEMO_DB_PATH: path.join(data, 'memo_source_aware.db'),
    MEMO_ENV_FILE: path.join(root, 'config', '.env'),
    MEMO_LOG_DIR: path.join(data, 'logs'),
    MEMO_PID_DIR: path.join(data, 'pids'),
    MEMO_RUNTIME_ROOT: stableRuntime,
    PYTHON_EXE: python,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
  };
  if (fs.existsSync(path.join(stableModel, 'model-manifest.json'))) environment.MEMO_EMBEDDING_MODEL = stableModel;
  return environment;
}

function runPython(args, overrideRoot = '') {
  const root = userRoot(overrideRoot);
  const python = runnerPython(root);
  if (!python) return Promise.resolve({ ok: false, mode: 'runtime_missing', runtimeMissing: true, error: `Lite 版没有找到可复用的 Python Runtime。请先安装最新版 Full 版一次；之后的 Lite 更新将自动复用 ${runtimeStatus(root).expectedStablePath}` });
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    const timeoutMs = args.includes('--detect') ? 45_000 : 10 * 60_000;
    const timer = setTimeout(() => {
      try { child.kill(); } catch (_) {}
      finish({ ok: false, error: `安装步骤超过 ${Math.round(timeoutMs / 60000)} 分钟，已停止等待。请重新选择已有数据目录后重试。` });
    }, timeoutMs);
    const stableRuntime = path.join(root, 'Programs', 'Memo', 'runtime');
    const child = spawn(python, [RUNNER, '--user-root', root, ...args], {
      cwd: INSTALLER_ROOT,
      env: { ...process.env, MEMO_USER_ROOT: root, MEMO_RUNTIME_ROOT: stableRuntime, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk.toString('utf8'); });
    child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8'); });
    child.on('error', (error) => finish({ ok: false, error: error.message }));
    child.on('exit', (code) => {
      const raw = (stdout || stderr || '').trim();
      try {
        const parsed = JSON.parse(raw);
        finish({ ...parsed, exitCode: code });
      } catch (_) {
        finish({ ok: code === 0, exitCode: code, stdout, stderr, error: code === 0 ? '' : (stderr || stdout || `exit ${code}`) });
      }
    });
  });
}

function runBat(scriptName, overrideRoot = '') {
  const appRoot = installedAppRoot(overrideRoot);
  const script = path.join(appRoot, scriptName);
  if (!fs.existsSync(script)) return Promise.resolve({ ok: false, error: `缺少脚本：${script}` });
  return new Promise((resolve) => {
    const child = spawn('cmd.exe', ['/c', script, '--no-browser'], {
      cwd: appRoot,
      env: serviceEnv(overrideRoot),
      detached: false,
      stdio: 'ignore',
      windowsHide: true,
    });
    child.on('error', (error) => resolve({ ok: false, error: error.message }));
    child.on('exit', (code) => resolve({ ok: code === 0, code }));
  });
}

function createWindow(page = 'first_run_wizard.html') {
  const isLauncher = page === 'launcher.html';
  mainWindow = new BrowserWindow({
    width: isLauncher ? 500 : 980,
    height: isLauncher ? 560 : 720,
    minWidth: isLauncher ? 500 : 900,
    minHeight: isLauncher ? 560 : 660,
    resizable: !isLauncher,
    backgroundColor: '#f7f8fb',
    title: isLauncher ? 'Memo 启动器' : 'Memo 安装向导',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow.removeMenu();
  mainWindow.loadFile(path.join(__dirname, page));
}

function launchCompanion(overrideRoot = '') {
  const root = userRoot(overrideRoot);
  companionMode = true;
  process.env.MEMO_ROOT = installedAppRoot(root);
  process.env.MEMO_USER_ROOT = root;
  process.env.MEMO_DATA_ROOT = path.join(root, 'data');
  process.env.MEMO_DB_PATH = path.join(root, 'data', 'memo_source_aware.db');
  process.env.MEMO_ENV_FILE = path.join(root, 'config', '.env');
  process.env.MEMO_LOG_DIR = path.join(root, 'data', 'logs');
  process.env.MEMO_PID_DIR = path.join(root, 'data', 'pids');
  process.env.MEMO_RUNTIME_ROOT = path.dirname(installedRuntimePython(root));
  process.env.PYTHON_EXE = installedRuntimePython(root);
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.close();
    mainWindow = null;
  }
  require(path.join(INSTALLER_ROOT, 'desktop', 'main.cjs'));
}

async function createInitialWindow() {
  const root = userRoot();
  const forceDataManager = process.argv.includes('--memo-data-manager');
  if (!runtimeStatus(root).available) {
    createWindow('first_run_wizard.html');
    return;
  }
  const detected = await runPython(['--detect'], root);
  // A persisted root with a valid database is strong evidence. Do not rescan
  // every drive on every normal launch; the data manager remains available for
  // explicit discovery and migration.
  if (detected?.mode === 'healthy_latest' && hasMemoDatabase(root) && !forceDataManager) {
    launchCompanion(root);
    return;
  }
  discoverMemoData(); // one deep scan, cached for the wizard IPC call
  createWindow('first_run_wizard.html');
}

ipcMain.handle('memo-installer:detect', (_event, options = {}) => {
  const root = String(options.userRoot || userRoot());
  const runtime = runtimeStatus(root);
  if (!runtime.available) {
    return {
      ok: true,
      mode: 'runtime_missing',
      runtimeMissing: true,
      runtime,
      selectedUserRoot: root,
      defaultUserRoot: defaultUserRoot(),
      detectedExistingData: hasMemoDatabase(root),
      requiresExistingDataChoice: !runtime.bundled && !hasMemoDatabase(root),
      detectedDataRoots: discoverMemoData(),
      paths: { user_root: root, database: memoDatabase(root), runtime_python: runtime.expectedStablePath },
    };
  }
  return runPython(['--detect'], root).then((result) => {
    const normalized = result?.paths?.user_root || root;
    return {
      ...result,
      selectedUserRoot: normalized,
      defaultUserRoot: defaultUserRoot(),
      detectedExistingData: hasMemoDatabase(normalized),
      requiresExistingDataChoice: !runtime.bundled && !hasMemoDatabase(normalized),
      detectedDataRoots: discoverMemoData(),
    };
  });
});
ipcMain.handle('memo-installer:install', async (_event, options = {}) => {
  const root = String(options.userRoot || userRoot());
  const runtime = runtimeStatus(root);
  if (!runtime.available) {
    return { ok: false, runtimeMissing: true, error: `当前 Lite 安装包没有找到可复用的 Python Runtime。旧版 Full 没有把 Runtime 固化到长期目录。请先安装最新版 Full 版一次，Runtime 将保存到：${runtime.expectedStablePath}。以后即可继续使用 Lite 更新。` };
  }
  const result = await runPython([
    '--api-key', String(options.apiKey || ''),
    '--base-url', String(options.baseUrl || ''),
    '--model', String(options.model || ''),
    '--migrate-from', String(options.migrateFrom || ''),
  ], root);
  if (result.ok) {
    // Persist only after copy/validation succeeds. Failed migrations keep the
    // previous known-good path, so a later update cannot switch to an empty root.
    writeSettings({ userRoot: root, dataLocationConfirmedAt: new Date().toISOString() });
    return { ...result, selectedUserRoot: root, serviceStarted: false, installOnly: true };
  }
  return result;
});
ipcMain.handle('memo-installer:startMemo', (_event, options = {}) => runBat('start_all.bat', String(options.userRoot || userRoot())));
ipcMain.handle('memo-installer:openDashboard', () => shell.openExternal(BOOT_URL));
ipcMain.handle('memo-installer:openUserRoot', (_event, options = {}) => {
  const root = userRoot(String(options.userRoot || ''));
  fs.mkdirSync(root, { recursive: true });
  return shell.openPath(root);
});
ipcMain.handle('memo-installer:chooseLegacyRoot', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择已有 Memo 数据',
    properties: ['openDirectory'],
    defaultPath: userRoot(),
    message: '可选择 Memo 根目录、data 目录、Programs\\Memo 程序目录，或它们的上级目录。',
  });
  if (result.canceled || !result.filePaths[0]) return { canceled: true };
  const selected = path.resolve(result.filePaths[0]);
  const matches = findMemoRootsNear(selected, 3, 500);
  const inferred = normalizeMemoRoot(selected);
  if (hasMemoDatabase(inferred) && !matches.some((root) => root.toLowerCase() === inferred.toLowerCase())) matches.unshift(inferred);
  if (!matches.length) {
    return {
      canceled: false,
      ok: false,
      path: selected,
      error: `在“${selected}”及其下三级目录中没有找到有效的 data\\memo_source_aware.db。请确认选中的是原 Memo 数据所在目录，而不是安装包所在目录。`,
    };
  }
  const normalized = matches[0];
  return { canceled: false, ok: true, path: normalized, data: inspectMemoRoot(normalized, 'legacy'), matches: matches.map((root) => inspectMemoRoot(root, 'legacy')).filter(Boolean) };
});
ipcMain.handle('memo-installer:chooseTargetRoot', async (_event, options = {}) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择新的 Memo 数据位置',
    properties: ['openDirectory', 'createDirectory'],
    defaultPath: String(options.defaultPath || defaultUserRoot()),
    message: '可以选择空目录或新建目录。Memo 将在这里创建 data、config 和 Programs。',
  });
  if (result.canceled || !result.filePaths[0]) return { canceled: true };
  const normalized = normalizeMemoRoot(result.filePaths[0]);
  const existing = inspectMemoRoot(normalized, normalized.toLowerCase() === normalizeMemoRoot(defaultUserRoot()).toLowerCase() ? 'standard' : 'legacy');
  return { canceled: false, ok: true, path: normalized, existingData: existing };
});
ipcMain.handle('memo-installer:openSetup', () => {
  if (mainWindow) mainWindow.loadFile(path.join(__dirname, 'first_run_wizard.html'));
  else createWindow('first_run_wizard.html');
  return { ok: true };
});
ipcMain.handle('memo-installer:openCompanion', (_event, options = {}) => {
  launchCompanion(String(options.userRoot || userRoot()));
  return { ok: true };
});
ipcMain.handle('memo-installer:quit', () => app.quit());

app.whenReady().then(createInitialWindow);
app.on('window-all-closed', (event) => {
  if (companionMode) {
    event.preventDefault();
    return;
  }
  app.quit();
});
