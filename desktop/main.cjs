const { app, BrowserWindow, Menu, Tray, nativeImage, Notification, ipcMain, shell, clipboard } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const https = require('https');
const crypto = require('crypto');
const { compareVersions } = require('./version-utils.cjs');
const { normalizeServiceRelease, planServiceUpdate } = require('./update-planner.cjs');

function candidateAncestors(startPath, maxDepth = 6) {
  const result = [];
  let current = path.resolve(startPath || process.cwd());
  for (let i = 0; i < maxDepth; i += 1) {
    result.push(current);
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return result;
}

function isPackagedResourceRoot(candidate) {
  const normalized = path.normalize(candidate).toLowerCase();
  return normalized.endsWith(path.normalize('resources/app').toLowerCase())
    || normalized.includes(`${path.sep}resources${path.sep}app${path.sep}`.toLowerCase());
}

function commonExternalMemoRoots() {
  const roots = [];
  const home = app.getPath('home');
  const execDir = path.dirname(process.execPath || process.cwd());
  const execRoot = path.parse(execDir).root;
  const cwdRoot = path.parse(process.cwd()).root;
  for (const driveRoot of new Set([execRoot, cwdRoot, 'C:\\', 'D:\\', 'E:\\'].filter(Boolean))) {
    roots.push(path.join(driveRoot, 'memo'));
    roots.push(path.join(driveRoot, 'Memo'));
  }
  roots.push(path.join(home, 'memo'));
  roots.push(path.join(home, 'Memo'));

  // 安装器常位于项目工作区的相邻目录。扫描少量祖先目录的一层子目录，
  // 例如从「Memo启动器」找到同级的「Memo_V0.1.0」，避免误用 resources/app。
  for (const parent of candidateAncestors(execDir, 6)) {
    try {
      const children = fs.readdirSync(parent, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && /memo/i.test(entry.name))
        .slice(0, 40);
      for (const child of children) roots.push(path.join(parent, child.name));
    } catch (_) {
      // 无权限或不存在时跳过。
    }
  }
  return roots;
}

function resolveMemoRoot() {
  const candidates = [
    process.env.MEMO_ROOT,
    ...(!app.isPackaged ? [path.resolve(__dirname, '..')] : []),
    process.cwd(),
    ...candidateAncestors(path.dirname(process.execPath || ''), 8),
    ...(app.isPackaged ? commonExternalMemoRoots() : []),
  ].filter(Boolean);

  for (const candidate of candidates) {
    try {
      if (app.isPackaged && isPackagedResourceRoot(candidate)) continue;
      const startScript = path.join(candidate, 'start_all.bat');
      const memoDir = path.join(candidate, 'memo');
      if (fs.existsSync(startScript) && fs.existsSync(memoDir)) {
        return candidate;
      }
    } catch (_) {
      // ignore invalid candidate
    }
  }

  // Packaged installer currently ships Memo runtime under resources/app.
  // Prefer an external MEMO_ROOT when available, but fall back to bundled runtime so the companion can still start services.
  const bundledRoot = path.resolve(__dirname, '..');
  if (app.isPackaged && fs.existsSync(path.join(bundledRoot, 'start_all.bat')) && fs.existsSync(path.join(bundledRoot, 'memo'))) {
    return bundledRoot;
  }
  return app.isPackaged ? process.cwd() : path.resolve(__dirname, '..');
}

const ROOT = resolveMemoRoot();
// Full installer keeps user secrets/data outside resources/app. Development remains project-local.
const USER_MEMO_ROOT = process.env.MEMO_USER_ROOT || path.join(process.env.LOCALAPPDATA || app.getPath('userData'), 'Memo');
const USER_MEMO_DATA_ROOT = path.join(USER_MEMO_ROOT, 'data');
const USER_MEMO_CONFIG_ROOT = path.join(USER_MEMO_ROOT, 'config');
const USER_MEMO_ENV_FILE = path.join(USER_MEMO_CONFIG_ROOT, '.env');
const SERVICE_CHAIN_STATE = path.join(USER_MEMO_ROOT, 'Programs', 'Memo', 'service-update-chain.json');
const SERVICE_RUNNER_STATE = path.join(USER_MEMO_ROOT, 'Programs', 'Memo', 'service-update-transaction.json');
const BOOT_URL = process.env.MEMO_BOOT_URL || 'http://127.0.0.1:9120';
const DASHBOARD_BASE = process.env.MEMO_DASHBOARD_URL || BOOT_URL;
const DASHBOARD_FALLBACKS = Array.from(new Set([DASHBOARD_BASE, BOOT_URL, 'http://127.0.0.1:9121']));
const POLL_INTERVAL_MS = Number(process.env.MEMO_COMPANION_POLL_MS || 60000);
const AUTO_START_SERVICES = process.env.MEMO_COMPANION_AUTO_START !== '0';
const ICON_PATH = path.join(__dirname, 'assets', process.platform === 'win32' ? 'memo-companion.ico' : 'memo-companion.png');
const RELEASE_PAGE = process.env.MEMO_RELEASE_PAGE || 'https://memo.zhaguzhagu.com/#download';
const UPDATE_MANIFEST_URL = process.env.MEMO_UPDATE_MANIFEST_URL || 'https://memo.zhaguzhagu.com/downloads/latest.json';

let mainWindow = null;
let tray = null;
let pollTimer = null;
let lastSnapshot = null;
let notificationsPausedUntil = 0;
let serviceAction = 'idle';
let serviceUpdateRunning = false;
let windowAutoHideSuspended = false;
let loginItemEnabledCache = false;
let loginItemUserSelected = false;

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
}

app.on('second-instance', () => {
  showWindow();
});

function createTrayImage() {
  const image = nativeImage.createFromPath(ICON_PATH);
  if (!image.isEmpty()) return image;

  const svg = `
    <svg width="64" height="64" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#74d7ff"/>
          <stop offset="1" stop-color="#5c6cff"/>
        </linearGradient>
      </defs>
      <rect x="8" y="8" width="48" height="48" rx="16" fill="#111827"/>
      <path d="M20 42V22h6l6 10 6-10h6v20h-6V31l-5 8h-2l-5-8v11h-6z" fill="url(#g)"/>
    </svg>`;
  return nativeImage.createFromDataURL(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 370,
    height: 500,
    minWidth: 340,
    minHeight: 470,
    show: false,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    transparent: true,
    hasShadow: false,
    backgroundColor: '#00000000',
    icon: ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'companion.html'));
  mainWindow.on('blur', () => {
    if (!windowAutoHideSuspended && !serviceUpdateRunning) hideWindow();
  });
}

function positionWindow() {
  if (!mainWindow) return;
  const display = require('electron').screen.getPrimaryDisplay();
  const { width, height } = display.workAreaSize;
  const bounds = mainWindow.getBounds();
  mainWindow.setPosition(width - bounds.width - 24, height - bounds.height - 24);
}

function setSettingsExpanded(_expanded) {
  // 设置面板现在是窗口内浮层，不再改变窗口高度。
}

function showWindow() {
  if (!mainWindow) createWindow();
  positionWindow();
  mainWindow.show();
  mainWindow.focus();
  refreshAndSend();
}

function hideWindow() {
  if (mainWindow) mainWindow.hide();
}

function toggleWindow() {
  if (!mainWindow || !mainWindow.isVisible()) showWindow();
  else hideWindow();
}

function openDashboard(hash = '') {
  const url = hash ? `${BOOT_URL}/#/${hash.replace(/^#?\/?/, '')}` : BOOT_URL;
  shell.openExternal(url);
}

async function fetchDashboardJson(pathname, fallback = null) {
  for (const base of DASHBOARD_FALLBACKS) {
    const data = await fetchJson(`${base}${pathname}`, null);
    if (data) return data;
  }
  return fallback;
}

async function fetchDashboardHealth() {
  return fetchDashboardJson('/api/health', null);
}

function buildTrayMenu() {
  const paused = notificationsPausedUntil > Date.now();
  return Menu.buildFromTemplate([
    { label: '显示/隐藏 Memo 助手', click: toggleWindow },
    { label: '打开 Memo Dashboard', click: () => openDashboard('') },
    { label: '处理历史 Agent 会话', click: () => openDashboard('history-processing') },
    { label: '复制 MCP 配置', click: () => copyMcpConfig() },
    { label: '检查更新', click: async () => { const result = await checkForUpdates(); if (Notification.isSupported()) new Notification({ title: 'Memo 版本检查', body: result.message }).show(); } },
    { label: '刷新状态', click: refreshAndSend },
    { type: 'separator' },
    { label: '启动 Memo 服务', click: startMemoServices },
    { label: '重启 Memo 服务', click: restartMemoServices },
    { label: '停止 Memo 服务', click: stopMemoServices },
    { type: 'separator' },
    {
      label: paused ? '提醒已暂停' : '暂停提醒 1 小时',
      enabled: !paused,
      click: () => {
        notificationsPausedUntil = Date.now() + 60 * 60 * 1000;
        if (tray) tray.setContextMenu(buildTrayMenu());
      },
    },
    { type: 'separator' },
    { label: '退出桌面助手', click: () => app.quit() },
  ]);
}

function createTray() {
  tray = new Tray(createTrayImage());
  tray.setToolTip('Memo Desktop Companion');
  tray.setContextMenu(buildTrayMenu());
  tray.on('click', toggleWindow);
}

async function fetchJson(url, fallback = null) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) return fallback;
    return await res.json();
  } catch (_) {
    return fallback;
  }
}

function asArray(value) {
  if (Array.isArray(value)) return value;
  if (value && Array.isArray(value.items)) return value.items;
  if (value && Array.isArray(value.todos)) return value.todos;
  if (value && Array.isArray(value.memories)) return value.memories;
  if (value && Array.isArray(value.candidates)) return value.candidates;
  return [];
}

function isRiskTodo(todo) {
  const risk = String(todo.risk_level || todo.riskLevel || todo.risk || '').toLowerCase();
  if (['overdue', 'urgent', 'warning', 'high'].includes(risk)) return true;
  if (!todo.due_date || todo.status === 'done' || todo.status === 'completed') return false;
  const due = new Date(todo.due_date);
  if (Number.isNaN(due.getTime())) return false;
  const now = new Date();
  const hours = (due.getTime() - now.getTime()) / 3600000;
  return hours < 0 || hours <= 24;
}

function isTodayTodo(todo) {
  if (todo.status === 'done' || todo.status === 'completed') return false;
  if (!todo.due_date) return false;
  const due = new Date(todo.due_date);
  if (Number.isNaN(due.getTime())) return false;
  const now = new Date();
  return due.getFullYear() === now.getFullYear()
    && due.getMonth() === now.getMonth()
    && due.getDate() === now.getDate();
}

async function collectSnapshot() {
  const health = await fetchDashboardHealth();
  if (!health || !health.ok) {
    return {
      ok: false,
      statusText: 'Memo 未启动',
      checkedAt: new Date().toISOString(),
      todayTodos: 0,
      riskTodos: 0,
      pendingCandidates: 0,
      recentMemories: 0,
      serviceAction,
      autoStartServices: AUTO_START_SERVICES,
      loginItemEnabled: getLoginItemEnabled(),
      memoRoot: ROOT,
    };
  }

  const [todosRaw, candidatesRaw, memoriesRaw] = await Promise.all([
    fetchDashboardJson('/api/todos?include_done=false&limit=80', []),
    fetchDashboardJson('/api/space/candidates?status=pending&limit=80', {}),
    fetchDashboardJson('/api/memories?limit=20', []),
  ]);

  const todos = asArray(todosRaw);
  const candidates = asArray(candidatesRaw);
  const memories = asArray(memoriesRaw);
  const pendingCandidates = Number(candidatesRaw?.pending ?? candidatesRaw?.total ?? candidates.length ?? 0);

  return {
    ok: true,
    statusText: `Memo 已连接 · schema ${health.schema_version || '-'}`,
    checkedAt: new Date().toISOString(),
    todayTodos: todos.filter(isTodayTodo).length,
    riskTodos: todos.filter(isRiskTodo).length,
    pendingCandidates,
    recentMemories: memories.length,
    serviceAction,
    autoStartServices: AUTO_START_SERVICES,
    loginItemEnabled: getLoginItemEnabled(),
    memoRoot: ROOT,
  };
}

function shouldNotify(next) {
  if (notificationsPausedUntil > Date.now()) return null;
  if (!lastSnapshot) return null;
  if (lastSnapshot.ok && !next.ok) return { title: 'Memo 服务不可用', body: '桌面助手暂时连接不到 Memo。' };
  if (!next.ok) return null;
  if (next.riskTodos > (lastSnapshot.riskTodos || 0)) {
    return { title: 'Memo 风险待办提醒', body: `当前有 ${next.riskTodos} 条风险待办需要关注。` };
  }
  if (next.pendingCandidates > (lastSnapshot.pendingCandidates || 0)) {
    return { title: 'Memo 项目候选提醒', body: `有 ${next.pendingCandidates} 条项目候选等待整理。` };
  }
  return null;
}

async function refreshAndSend() {
  const snapshot = await collectSnapshot();
  const notice = shouldNotify(snapshot);
  lastSnapshot = snapshot;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('memo:snapshot', snapshot);
  }
  if (tray) {
    tray.setToolTip(snapshot.ok ? `Memo · 今日待办 ${snapshot.todayTodos} · 风险 ${snapshot.riskTodos}` : 'Memo 未启动');
  }
  if (notice && Notification.isSupported()) {
    new Notification(notice).show();
  }
  return snapshot;
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  refreshAndSend();
  pollTimer = setInterval(refreshAndSend, POLL_INTERVAL_MS);
}

function serviceRuntimeEnv() {
  if (!app.isPackaged && !process.env.MEMO_USER_ROOT) return {};
  const pythonCommand = getPythonCommand();
  return {
    MEMO_USER_ROOT: USER_MEMO_ROOT,
    MEMO_DATA_ROOT: USER_MEMO_DATA_ROOT,
    MEMO_ENV_FILE: USER_MEMO_ENV_FILE,
    MEMO_LOG_DIR: path.join(USER_MEMO_DATA_ROOT, 'logs'),
    MEMO_PID_DIR: path.join(USER_MEMO_DATA_ROOT, 'pids'),
    MEMO_RUNTIME_ROOT: pythonCommand && pythonCommand !== 'python' ? path.dirname(pythonCommand) : '',
    PYTHON_EXE: pythonCommand,
  };
}

function runBat(scriptName, actionLabel) {
  const script = path.join(ROOT, scriptName);
  serviceAction = actionLabel;
  refreshAndSend();

  return new Promise((resolve) => {
    const child = spawn('cmd.exe', ['/c', script], {
      cwd: ROOT,
      detached: false,
      stdio: 'ignore',
      windowsHide: true,
      env: { ...process.env, ...serviceRuntimeEnv() },
    });

    child.on('error', () => {
      serviceAction = 'idle';
      refreshAndSend();
      resolve({ ok: false });
    });

    child.on('exit', (code) => {
      serviceAction = 'idle';
      setTimeout(refreshAndSend, 2500);
      resolve({ ok: code === 0, code });
    });
  });
}

async function waitForMemoServices(timeoutSeconds = 45) {
  const waiter = path.join(ROOT, 'scripts', 'wait_for_services.py');
  if (!fs.existsSync(waiter)) return { ok: false, message: '缺少服务就绪检查脚本。' };
  const result = await runCommand(getPythonCommand(), [waiter, '--timeout', String(timeoutSeconds)], { cwd: ROOT });
  const raw = String(result.stdout || result.stderr || '').trim();
  try {
    const status = JSON.parse(raw);
    return { ok: Boolean(result.ok && status.ok), message: status.ok ? 'Memo 服务已就绪。' : compactOutput(JSON.stringify(status, null, 2)) };
  } catch (_) {
    return { ok: false, message: compactOutput(raw || '服务就绪检查没有返回有效结果。') };
  }
}

async function startMemoServices() {
  const started = await runBat('start_all.bat', 'starting');
  if (!started.ok) return { ok: false, message: '启动脚本执行失败。' };
  serviceAction = 'starting';
  refreshAndSend();
  const ready = await waitForMemoServices();
  serviceAction = 'idle';
  refreshAndSend();
  return ready;
}

async function stopMemoServices() {
  const stopped = await runBat('stop_all.bat', 'stopping');
  return stopped.ok ? { ok: true, message: 'Memo 服务已停止。' } : { ok: false, message: '停止 Memo 服务失败，端口可能仍被占用。' };
}

async function restartMemoServices() {
  serviceAction = 'restarting';
  refreshAndSend();
  const stopped = await runBat('stop_all.bat', 'restarting');
  if (!stopped.ok) {
    serviceAction = 'idle';
    refreshAndSend();
    return { ok: false, message: '停止旧服务失败，因此未继续重启。请查看端口 9120/9121。' };
  }
  return startMemoServices();
}

function runCommand(command, args = [], options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd || ROOT,
      env: { ...process.env, ...(options.env || {}) },
      windowsHide: true,
      shell: Boolean(options.shell),
    });
    let stdout = '';
    let stderr = '';
    child.stdout?.on('data', (data) => { stdout += data.toString(); });
    child.stderr?.on('data', (data) => { stderr += data.toString(); });
    child.on('error', (error) => resolve({ ok: false, code: -1, stdout, stderr: stderr || String(error.message || error) }));
    child.on('exit', (code) => resolve({ ok: code === 0, code, stdout, stderr }));
  });
}

function compactOutput(text, max = 2200) {
  const clean = String(text || '').trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, 900)}\n...\n${clean.slice(-1200)}`;
}

function installedServiceState() {
  for (const candidate of [path.join(ROOT, 'memo-install-manifest.json'), path.join(ROOT, 'memo-build-manifest.json')]) {
    try {
      const parsed = JSON.parse(fs.readFileSync(candidate, 'utf8'));
      const version = parsed.serviceVersion || parsed.version;
      if (version) {
        const installedFiles = parsed.installedFiles;
        return {
          version: String(version),
          hasBaseline: Boolean(installedFiles && typeof installedFiles === 'object' && Object.keys(installedFiles).length),
          sourceCommit: String(parsed.sourceCommit || ''),
        };
      }
    } catch (_) {}
  }
  return { version: appVersion(), hasBaseline: false, sourceCommit: '' };
}

function installedServiceVersion() {
  return installedServiceState().version;
}

function servicePatchRunner() {
  const packaged = path.resolve(__dirname, '..', 'installer', 'service_patch_runner.py');
  return fs.existsSync(packaged) ? packaged : path.join(ROOT, 'scripts', 'service_patch_runner.py');
}

async function runServicePatchRunner(args) {
  const runner = servicePatchRunner();
  if (!fs.existsSync(runner)) return { ok: false, error: '当前启动器不包含Service Patch执行器，请先更新一次Lite。' };
  const result = await runCommand(getPythonCommand(), [runner, ...args, '--user-root', USER_MEMO_ROOT], { cwd: path.dirname(ROOT), env: serviceRuntimeEnv() });
  const raw = String(result.stdout || result.stderr || '').trim();
  try { return { ...JSON.parse(raw), exitCode: result.code }; } catch (_) {
    return { ok: false, error: compactOutput(raw || `Service Patch runner exit ${result.code}`) };
  }
}

function writeServiceChainState(state) {
  fs.mkdirSync(path.dirname(SERVICE_CHAIN_STATE), { recursive: true });
  const temporary = `${SERVICE_CHAIN_STATE}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify({ schemaVersion: 1, ...state }, null, 2)}\n`, 'utf8');
  fs.renameSync(temporary, SERVICE_CHAIN_STATE);
}

function readServiceChainState() {
  if (!fs.existsSync(SERVICE_CHAIN_STATE)) return null;
  try { return JSON.parse(fs.readFileSync(SERVICE_CHAIN_STATE, 'utf8')); } catch (error) {
    throw new Error(`服务更新状态文件损坏，未自动删除：${SERVICE_CHAIN_STATE}。${error?.message || error}`);
  }
}

function clearServiceChainState() {
  if (fs.existsSync(SERVICE_CHAIN_STATE)) fs.unlinkSync(SERVICE_CHAIN_STATE);
}

async function recoverInterruptedServiceUpdate() {
  const chain = readServiceChainState();
  const interrupted = Boolean(chain || fs.existsSync(SERVICE_RUNNER_STATE));
  if (!interrupted) return { ok: true, recovered: false, residuals: [] };
  const stopped = await stopMemoServices();
  if (!stopped.ok) return { ok: false, message: '检测到中断更新，但停止现有服务失败；为避免带进程切换程序目录，已取消自动恢复。' };
  const recoveredRunner = await runServicePatchRunner(['--action', 'recover']);
  if (!recoveredRunner.ok) {
    return { ok: false, message: `发现未完成的服务更新，但无法安全恢复；未删除任何未知残留。\n${recoveredRunner.error || ''}` };
  }
  if (!chain) {
    return { ok: true, recovered: Boolean(recoveredRunner.recovered), residuals: recoveredRunner.residuals || [] };
  }
  if (chain.phase === 'health-ok') {
    clearServiceChainState();
    return { ok: true, recovered: Boolean(recoveredRunner.recovered), residuals: recoveredRunner.residuals || [] };
  }
  let ok = true;
  const backups = Array.isArray(chain.appliedBackups) ? chain.appliedBackups : [];
  for (const item of [...backups].reverse()) {
    const backup = String(item?.backup || '');
    if (!backup || !fs.existsSync(backup)) continue;
    const rolledBack = await runServicePatchRunner(['--action', 'rollback', '--backup', backup]);
    if (!rolledBack.ok) ok = false;
  }
  if (!ok) return { ok: false, message: '补丁链中断恢复未完全成功，状态文件已保留，未自动删除未知残留。' };
  clearServiceChainState();
  return { ok: true, recovered: true, residuals: recoveredRunner.residuals || [] };
}

async function archiveUserStateBeforeServicePatch() {
  const archiveScript = path.join(ROOT, 'scripts', 'archive_current_db.py');
  if (!fs.existsSync(archiveScript)) {
    return { ok: false, message: '当前服务缺少数据库归档脚本。为保护数据，已取消增量更新；请先使用Lite更新启动器。' };
  }
  const archive = await runCommand(
    getPythonCommand(),
    [archiveScript, '--apply', '--confirm', 'ARCHIVE', '--label', 'service-patch'],
    { cwd: ROOT, env: serviceRuntimeEnv() },
  );
  return archive.ok
    ? { ok: true, detail: compactOutput(archive.stdout) }
    : { ok: false, message: `数据库和配置归档失败，程序文件尚未修改。\n${compactOutput(archive.stderr || archive.stdout).replace(/\uFFFD/g, '?')}` };
}

async function updateGitServiceRuntime(steps) {
  steps.push('停止 Memo 服务');
  const stopped = await stopMemoServices();
  if (!stopped.ok) return { ok: false, message: '停止Memo服务失败，未拉取代码。' };
  const archived = await archiveUserStateBeforeServicePatch();
  if (!archived.ok) {
    await startMemoServices();
    return archived;
  }
  steps.push('归档数据库和配置', 'Git fast-forward更新');
  const pull = await runCommand('git', ['-c', 'http.proxy=', '-c', 'https.proxy=', 'pull', '--ff-only', 'origin', 'main'], { cwd: ROOT });
  if (!pull.ok) {
    await startMemoServices();
    return { ok: false, message: `git pull失败，已恢复启动旧服务。\n${compactOutput(pull.stderr || pull.stdout)}` };
  }
  const started = await startMemoServices();
  return started.ok
    ? { ok: true, message: `Git源码服务已更新。\n${steps.join(' → ')}` }
    : { ok: false, message: '代码已拉取，但服务未能恢复启动。' };
}

async function downloadAndVerifyServiceAsset(asset, tempDir, index) {
  const fallbackName = `Memo-Service-patch-${index + 1}.zip`;
  const safeName = path.basename(String(asset?.name || fallbackName));
  const target = path.join(tempDir, `${String(index + 1).padStart(2, '0')}-${safeName}`);
  await downloadFileWithRetry(asset.url, target, 3);
  const size = fs.statSync(target).size;
  if (Number(asset.size || 0) > 0 && size !== Number(asset.size)) {
    throw new Error(`${safeName}大小与发布清单不一致。`);
  }
  const digest = await sha256File(target);
  if (!asset.sha256 || digest !== String(asset.sha256).replace(/^sha256:/i, '').toLowerCase()) {
    throw new Error(`${safeName} SHA-256校验失败。`);
  }
  return { target, digest };
}

async function rollbackAppliedPatchChain(appliedBackups) {
  let ok = true;
  for (const applied of [...appliedBackups].reverse()) {
    if (!applied?.backup) {
      ok = false;
      continue;
    }
    const rolledBack = await runServicePatchRunner(['--action', 'rollback', '--backup', String(applied.backup)]);
    if (!rolledBack.ok) ok = false;
  }
  return ok;
}

async function updateMemoService() {
  if (serviceUpdateRunning) return { ok: false, message: 'Memo服务更新已在进行中，请稍候。' };
  serviceUpdateRunning = true;
  serviceAction = 'updating';
  refreshAndSend();
  const steps = [];
  const appliedBackups = [];
  let servicesStopped = false;
  const finish = async (result) => {
    serviceUpdateRunning = false;
    serviceAction = 'idle';
    setTimeout(refreshAndSend, 2500);
    return result;
  };

  try {
    if (fs.existsSync(path.join(ROOT, '.git'))) return await finish(await updateGitServiceRuntime(steps));
    const recovery = await recoverInterruptedServiceUpdate();
    if (!recovery.ok) return await finish(recovery);
    if (recovery.recovered) {
      steps.push('恢复上次中断的服务更新');
      await startMemoServices();
    }
    const latest = await loadUpdateManifest();
    const installed = installedServiceState();
    const plan = planServiceUpdate(latest, installed);
    if (plan.kind === 'none') {
      return await finish({ ok: true, message: `Memo服务已是最新版本 ${installed.version}。` });
    }
    if (plan.kind === 'installer') {
      return await finish({ ok: false, message: '本次更新包含启动器或Runtime变化，请使用Lite更新。' });
    }
    if (plan.kind === 'unavailable') {
      return await finish({ ok: false, message: installed.hasBaseline
        ? '没有找到从当前版本到目标版本的完整差分链，请使用Lite更新。'
        : '当前安装缺少installedFiles基线，不能安全使用差分补丁；请先使用Lite或完整服务包更新一次。' });
    }

    const patchItems = plan.kind === 'delta-chain'
      ? plan.chain.map((asset) => ({ kind: 'delta', asset, from: String(asset.from), to: String(asset.to) }))
      : [{ kind: 'full', asset: plan.asset, from: installed.version, to: plan.target }];

    steps.push(plan.kind === 'delta-chain' ? `下载并校验${patchItems.length}段差分补丁` : '下载并校验完整服务包');
    const tempDir = path.join(app.getPath('temp'), 'memo-service-patch');
    fs.mkdirSync(tempDir, { recursive: true });
    const downloaded = [];
    for (let index = 0; index < patchItems.length; index += 1) {
      const item = patchItems[index];
      downloaded.push({ ...item, ...(await downloadAndVerifyServiceAsset(item.asset, tempDir, index)) });
    }

    steps.push('停止 Memo 服务');
    const stopped = await stopMemoServices();
    if (!stopped.ok) return await finish({ ok: false, message: '停止Memo服务失败，补丁尚未应用。' });
    servicesStopped = true;
    steps.push('归档数据库和配置');
    const archived = await archiveUserStateBeforeServicePatch();
    if (!archived.ok) {
      await startMemoServices();
      servicesStopped = false;
      return await finish(archived);
    }

    steps.push(plan.kind === 'delta-chain' ? `依次应用${downloaded.length}段差分并原子切换` : '原子切换完整程序目录');
    writeServiceChainState({ phase: 'applying', from: installed.version, to: plan.target, appliedBackups: [] });
    let skippedDeleteCount = 0;
    for (const item of downloaded) {
      const runnerArgs = item.kind === 'delta'
        ? ['--action', 'apply-delta', '--archive', item.target, '--sha256', item.digest, '--from-version', item.from, '--version', item.to]
        : ['--action', 'apply', '--archive', item.target, '--sha256', item.digest, '--version', item.to];
      const applied = await runServicePatchRunner(runnerArgs);
      if (!applied.ok) {
        const rolledBack = await rollbackAppliedPatchChain(appliedBackups);
        if (rolledBack) clearServiceChainState();
        const restored = await startMemoServices();
        servicesStopped = false;
        return await finish({
          ok: false,
          message: `Service Patch应用失败，已${rolledBack && restored.ok ? '恢复到更新前版本' : '尝试整链回滚但需要人工检查'}。\n${applied.error || ''}`,
        });
      }
      appliedBackups.push(applied);
      writeServiceChainState({ phase: 'applying', from: installed.version, to: plan.target, appliedBackups });
      const finalizedHop = await runServicePatchRunner(['--action', 'finalize', '--backup', String(applied.backup || '')]);
      if (!finalizedHop.ok) throw new Error(`补丁事务落盘失败：${finalizedHop.error || ''}`);
      skippedDeleteCount += Array.isArray(applied.skippedDeletes) ? applied.skippedDeletes.length : 0;
    }

    writeServiceChainState({ phase: 'health-check', from: installed.version, to: plan.target, appliedBackups });
    steps.push('启动并健康检查');
    const started = await startMemoServices();
    servicesStopped = false;
    const ready = started.ok ? await waitForMemoServices(60) : { ok: false, message: started.message };
    if (!ready.ok) {
      steps.push('健康检查失败，整链回滚');
      await stopMemoServices();
      servicesStopped = true;
      const rolledBack = await rollbackAppliedPatchChain(appliedBackups);
      if (rolledBack) clearServiceChainState();
      const restored = await startMemoServices();
      servicesStopped = false;
      return await finish({
        ok: false,
        message: `新版本未通过健康检查，已${rolledBack && restored.ok ? '自动恢复到更新前版本' : '尝试整链回滚但需要人工检查'}。数据库备份保持不动。\n${ready.message || ''}`,
      });
    }
    writeServiceChainState({ phase: 'health-ok', from: installed.version, to: plan.target, appliedBackups });
    clearServiceChainState();
    const mode = plan.kind === 'delta-chain' ? `${downloaded.length}段差分补丁链` : '完整服务包';
    return await finish({
      ok: true,
      message: `Memo服务已通过${mode}更新到 ${plan.target}。\n执行步骤：${steps.join(' → ')}${skippedDeleteCount ? `\n为保护本地修改，${skippedDeleteCount}个待删除文件已保留。` : ''}\n本地数据库、WAL/SHM和.env均未被补丁覆盖。`,
    });
  } catch (error) {
    try {
      if (appliedBackups.length) {
        if (!servicesStopped) await stopMemoServices();
        const rolledBack = await rollbackAppliedPatchChain(appliedBackups);
        if (rolledBack) clearServiceChainState();
      }
      await startMemoServices();
    } catch (_) {}
    return await finish({ ok: false, message: `Memo服务更新失败：${error?.message || error}` });
  }
}

function getLoginItemEnabled() {
  if (loginItemUserSelected) return loginItemEnabledCache;
  try {
    loginItemEnabledCache = app.getLoginItemSettings().openAtLogin;
  } catch (_) {
    // 开发态或 portable 模式下系统可能不立即回读；保留默认值。
  }
  return loginItemEnabledCache;
}

function readEnvValue(name, fallback = '') {
  try {
    const envPath = process.env.MEMO_ENV_FILE || path.join(ROOT, '.env');
    if (!fs.existsSync(envPath)) return fallback;
    const lines = fs.readFileSync(envPath, 'utf8').split(/\r?\n/);
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const idx = trimmed.indexOf('=');
      if (idx <= 0) continue;
      if (trimmed.slice(0, idx).trim() === name) {
        return trimmed.slice(idx + 1).trim().replace(/^['\"]|['\"]$/g, '') || fallback;
      }
    }
  } catch (_) {}
  return fallback;
}

function getPythonCommand() {
  const stableRuntimeCandidates = [
    path.join(USER_MEMO_ROOT, 'Programs', 'Memo', 'runtime', 'python.exe'),
    path.resolve(ROOT, '..', 'runtime', 'python.exe'),
  ];
  const stableRuntime = stableRuntimeCandidates.find((candidate) => fs.existsSync(candidate));
  if (stableRuntime) return stableRuntime;
  if (process.env.PYTHON_EXE && fs.existsSync(process.env.PYTHON_EXE)) return process.env.PYTHON_EXE;
  const runtimePython = process.env.MEMO_RUNTIME_ROOT ? path.join(process.env.MEMO_RUNTIME_ROOT, 'python.exe') : '';
  if (runtimePython && fs.existsSync(runtimePython)) return runtimePython;
  const bundledPython = path.join(ROOT, 'runtime', 'python.exe');
  if (fs.existsSync(bundledPython)) return bundledPython;
  const localPython = path.join(ROOT, '.venv', 'Scripts', 'python.exe');
  return fs.existsSync(localPython) ? localPython : 'python';
}

function buildMcpConfig() {
  const pythonCommand = getPythonCommand();
  const dbPath = path.join(USER_MEMO_DATA_ROOT, 'memo_source_aware.db');
  const config = {
    mcpServers: {
      memo: {
        command: pythonCommand,
        args: [path.join(ROOT, 'scripts', 'run_mcp.py')],
        cwd: ROOT,
        env: {
          MEMO_ENV: 'production',
          MEMO_USER_ROOT: USER_MEMO_ROOT,
          MEMO_DATA_ROOT: USER_MEMO_DATA_ROOT,
          MEMO_DB_PATH: dbPath,
          MEMO_ENV_FILE: USER_MEMO_ENV_FILE,
          MEMO_LOG_DIR: path.join(USER_MEMO_DATA_ROOT, 'logs'),
          MEMO_PID_DIR: path.join(USER_MEMO_DATA_ROOT, 'pids'),
          MEMO_RUNTIME_ROOT: path.dirname(pythonCommand),
          PYTHON_EXE: pythonCommand,
          PYTHONUTF8: '1',
          PYTHONIOENCODING: 'utf-8',
        },
      },
    },
  };
  return {
    memoRoot: ROOT,
    userRoot: USER_MEMO_ROOT,
    dataRoot: USER_MEMO_DATA_ROOT,
    envFile: USER_MEMO_ENV_FILE,
    database: dbPath,
    python: pythonCommand,
    config,
    configText: JSON.stringify(config, null, 2),
  };
}

function copyMcpConfig(text) {
  clipboard.writeText(String(text || buildMcpConfig().configText));
  return { ok: true };
}

function openMemoRoot() {
  shell.openPath(USER_MEMO_ROOT);
  return { ok: true };
}

async function openDataLocationManager() {
  // Data-path changes require every Memo process to release SQLite first.
  // Relaunching the installer in explicit manager mode also reloads all runtime
  // environment variables after the selected path is persisted.
  try { await stopMemoServices(); } catch (_) {}
  const args = process.argv.slice(1).filter((item) => item !== '--memo-data-manager');
  args.push('--memo-data-manager');
  app.relaunch({ args });
  app.exit(0);
  return { ok: true };
}

function appVersion() {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
    return pkg.version || app.getVersion();
  } catch (_) {
    return app.getVersion();
  }
}

function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const input = fs.createReadStream(filePath);
    input.on('data', (chunk) => hash.update(chunk));
    input.on('end', () => resolve(hash.digest('hex')));
    input.on('error', reject);
  });
}

function downloadFile(url, destination) {
  return new Promise((resolve, reject) => {
    const request = https.get(url, { headers: { 'User-Agent': 'Memo-Desktop-Companion' } }, (response) => {
      if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
        response.resume();
        const redirected = new URL(response.headers.location, url).toString();
        downloadFile(redirected, destination).then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) { response.resume(); reject(new Error(`下载更新失败：HTTP ${response.statusCode}`)); return; }
      const output = fs.createWriteStream(destination);
      response.pipe(output);
      output.on('finish', () => output.close(() => resolve(destination)));
      output.on('error', reject);
    });
    request.setTimeout(120000, () => request.destroy(new Error('下载更新超时')));
    request.on('error', reject);
  });
}

async function downloadFileWithRetry(url, destination, attempts = 3) {
  const partial = `${destination}.part`;
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      // Only our exact .part path is cleaned. Unknown residual files are left alone.
      if (fs.existsSync(partial)) fs.unlinkSync(partial);
      await downloadFile(url, partial);
      if (fs.existsSync(destination)) fs.unlinkSync(destination);
      fs.renameSync(partial, destination);
      return destination;
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, attempt * 700));
    }
  }
  throw new Error(`下载重试${attempts}次仍失败：${lastError?.message || lastError}`);
}

function stableRuntimeReady() {
  return fs.existsSync(path.join(USER_MEMO_ROOT, 'Programs', 'Memo', 'runtime', 'python.exe'));
}

function persistInstallerDataRoot() {
  try {
    const target = path.join(app.getPath('appData'), 'Memo', 'memo-installer-settings.json');
    let existing = {};
    try { existing = JSON.parse(fs.readFileSync(target, 'utf8')); } catch (_) {}
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, JSON.stringify({ ...existing, userRoot: USER_MEMO_ROOT, updatedBy: 'desktop-auto-update', updatedAt: new Date().toISOString() }, null, 2), 'utf8');
    return true;
  } catch (error) {
    console.warn(`无法持久化安装器数据目录，继续使用当前进程环境：${error?.message || error}`);
    return false;
  }
}

async function loadUpdateManifest() {
  const manifest = await fetchJson(UPDATE_MANIFEST_URL, null);
  if (!manifest || !(manifest.launcher?.version || manifest.version || manifest.service?.version)) return null;
  return manifest;
}

function launcherRelease(manifest) {
  if (manifest?.launcher?.version) return manifest.launcher;
  return {
    version: manifest?.version || '',
    full: manifest?.full || null,
    lite: manifest?.lite || null,
    notes: manifest?.notes || '',
  };
}

function serviceRelease(manifest) {
  return normalizeServiceRelease(manifest);
}

async function installDesktopUpdate() {
  const latest = await loadUpdateManifest();
  if (!latest) return { ok: false, message: '无法连接 Memo 官网更新源，请稍后重试。' };
  const launcher = launcherRelease(latest);
  const current = appVersion();
  const version = launcher.version || '';
  if (!version || compareVersions(version, current) <= 0) return { ok: true, message: `当前启动器已是最新版本 ${current}。` };
  const runtimeReady = stableRuntimeReady();
  const asset = runtimeReady && launcher.lite?.url ? launcher.lite : launcher.full;
  if (!asset?.url) return { ok: false, message: `版本 ${version} 未配置可用的 Windows 安装包。` };
  const tempDir = path.join(app.getPath('temp'), 'memo-desktop-update');
  fs.mkdirSync(tempDir, { recursive: true });
  const target = path.join(tempDir, asset.name || (runtimeReady ? 'Memo-Lite-Setup-latest.exe' : 'Memo-Setup-latest.exe'));
  try {
    await downloadFileWithRetry(asset.url, target, 3);
    const size = fs.statSync(target).size;
    if (size < 1024 * 1024) throw new Error('下载文件异常小，已取消安装。');
    if (Number(asset.size || 0) > 0 && size !== Number(asset.size)) throw new Error('安装包大小与服务器清单不一致，已取消安装。');
    const publishedDigest = String(asset.sha256 || '').replace(/^sha256:/i, '').toLowerCase();
    if (publishedDigest) {
      const actualDigest = await sha256File(target);
      if (actualDigest !== publishedDigest) throw new Error('安装包 SHA-256 校验不一致，已取消安装。');
    }
    persistInstallerDataRoot();
    const child = spawn(target, [], {
      detached: true,
      stdio: 'ignore',
      windowsHide: false,
      env: {
        ...process.env,
        MEMO_USER_ROOT: USER_MEMO_ROOT,
        MEMO_DATA_ROOT: USER_MEMO_DATA_ROOT,
        MEMO_DB_PATH: path.join(USER_MEMO_DATA_ROOT, 'memo_source_aware.db'),
        MEMO_RUNTIME_ROOT: path.join(USER_MEMO_ROOT, 'Programs', 'Memo', 'runtime'),
        PYTHON_EXE: path.join(USER_MEMO_ROOT, 'Programs', 'Memo', 'runtime', 'python.exe'),
      },
    });
    await new Promise((resolve, reject) => {
      child.once('spawn', resolve);
      child.once('error', reject);
    });
    child.unref();
    setTimeout(() => app.quit(), 1200);
    const channel = asset === launcher.lite ? '轻量版' : '全量版';
    return { ok: true, message: `已从 Memo 官网下载 ${version} ${channel}并打开安装程序。安装器会保留本地数据和配置。` };
  } catch (error) {
    return { ok: false, message: `启动器更新失败：${error?.message || error}` };
  }
}

async function checkForUpdates() {
  const currentLauncher = appVersion();
  const installed = installedServiceState();
  const currentService = installed.version;
  const latest = await loadUpdateManifest();
  if (!latest) return { ok: false, currentLauncher, currentService, message: '暂时无法连接 Memo 官网更新源。' };
  const launcher = launcherRelease(latest);
  const service = serviceRelease(latest);
  const servicePlan = planServiceUpdate(latest, installed);
  const launcherUpdate = Boolean(launcher.version && compareVersions(launcher.version, currentLauncher) > 0);
  const serviceUpdate = Boolean(service?.version && compareVersions(service.version, currentService) > 0);
  const runtimeChanged = Boolean(service?.runtimeChanged);
  const serviceNeedsInstaller = serviceUpdate && ['installer', 'unavailable'].includes(servicePlan.kind);
  const mustUseInstaller = launcherUpdate || serviceNeedsInstaller;
  let channel = '无需更新';
  if (mustUseInstaller) {
    channel = stableRuntimeReady() && launcher.lite?.url ? 'Lite启动器更新' : 'Full全量更新';
  } else if (servicePlan.kind === 'delta-chain') {
    channel = `${servicePlan.chain.length}段Service Patch差分链`;
  } else if (servicePlan.kind === 'full-service') {
    channel = '完整Service Patch';
  }
  const notes = launcher.notes || latest.notes || '';
  return {
    ok: true,
    current: currentLauncher,
    currentLauncher,
    currentService,
    latest: launcher.version || currentLauncher,
    latestLauncher: launcher.version || currentLauncher,
    latestService: service?.version || currentService,
    page: latest.page || RELEASE_PAGE,
    hasUpdate: launcherUpdate || serviceUpdate,
    launcherUpdate,
    serviceUpdate,
    runtimeChanged,
    servicePlan: servicePlan.kind,
    channel,
    action: mustUseInstaller ? 'launcher' : (serviceUpdate ? 'service' : 'none'),
    message: launcherUpdate || serviceUpdate
      ? `启动器 ${currentLauncher} → ${launcher.version || currentLauncher}；服务 ${currentService} → ${service?.version || currentService}。将使用 ${channel}。${notes}`
      : `启动器 ${currentLauncher}、服务 ${currentService} 均已是最新版本。`,
  };
}

async function applyAvailableUpdate() {
  const check = await checkForUpdates();
  if (!check.ok || !check.hasUpdate) return check;
  return check.action === 'service' ? updateMemoService() : installDesktopUpdate();
}

function openReleasePage() {
  shell.openExternal(RELEASE_PAGE);
  return { ok: true };
}

function setLoginItemEnabled(enabled) {
  loginItemUserSelected = true;
  loginItemEnabledCache = Boolean(enabled);
  try {
    app.setLoginItemSettings({
      openAtLogin: loginItemEnabledCache,
      openAsHidden: true,
      name: 'Memo Desktop Companion',
    });
  } catch (_) {
    // portable/dev 模式可能无法写入，UI 仍保留用户意图。
  }
  refreshAndSend();
  return loginItemEnabledCache;
}

async function ensureServicesOnLaunch() {
  const recovery = await recoverInterruptedServiceUpdate();
  if (!recovery.ok) {
    console.error(recovery.message);
    try { new Notification({ title: 'Memo 更新恢复需要检查', body: recovery.message }).show(); } catch (_) {}
    return;
  }
  if (!AUTO_START_SERVICES) return;
  const health = await fetchDashboardHealth();
  if (!health || !health.ok) {
    await startMemoServices();
  }
}

ipcMain.handle('memo:getSnapshot', refreshAndSend);
ipcMain.handle('memo:openDashboard', (_event, hash) => openDashboard(hash || ''));
ipcMain.handle('memo:hideWindow', hideWindow);
ipcMain.handle('memo:startServices', () => startMemoServices());
ipcMain.handle('memo:stopServices', () => stopMemoServices());
ipcMain.handle('memo:restartServices', () => restartMemoServices());
ipcMain.handle('memo:setLoginItemEnabled', (_event, enabled) => setLoginItemEnabled(enabled));
ipcMain.handle('memo:setSettingsExpanded', (_event, expanded) => setSettingsExpanded(Boolean(expanded)));
ipcMain.handle('memo:getMcpConfig', () => buildMcpConfig());
ipcMain.handle('memo:copyMcpConfig', (_event, text) => copyMcpConfig(text));
ipcMain.handle('memo:openMemoRoot', () => openMemoRoot());
ipcMain.handle('memo:openDataLocationManager', () => openDataLocationManager());
ipcMain.handle('memo:checkForUpdates', () => checkForUpdates());
ipcMain.handle('memo:installDesktopUpdate', () => installDesktopUpdate());
ipcMain.handle('memo:applyAvailableUpdate', () => applyAvailableUpdate());
ipcMain.handle('memo:setWindowAutoHideSuspended', (_event, suspended) => {
  windowAutoHideSuspended = Boolean(suspended);
  if (windowAutoHideSuspended) showWindow();
  return windowAutoHideSuspended;
});
ipcMain.handle('memo:updateMemoService', () => updateMemoService());
ipcMain.handle('memo:openReleasePage', () => openReleasePage());

app.whenReady().then(() => {
  app.setAppUserModelId('Memo.DesktopCompanion');
  loginItemEnabledCache = getLoginItemEnabled();
  createWindow();
  createTray();
  showWindow();
  startPolling();
  ensureServicesOnLaunch();
});

app.on('window-all-closed', (event) => {
  event.preventDefault();
});

app.on('before-quit', () => {
  if (pollTimer) clearInterval(pollTimer);
});
