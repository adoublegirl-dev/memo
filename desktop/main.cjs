const { app, BrowserWindow, Menu, Tray, nativeImage, Notification, ipcMain, shell, clipboard } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const https = require('https');
const crypto = require('crypto');

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
const BOOT_URL = process.env.MEMO_BOOT_URL || 'http://127.0.0.1:9120';
const DASHBOARD_BASE = process.env.MEMO_DASHBOARD_URL || BOOT_URL;
const DASHBOARD_FALLBACKS = Array.from(new Set([DASHBOARD_BASE, BOOT_URL, 'http://127.0.0.1:9121']));
const POLL_INTERVAL_MS = Number(process.env.MEMO_COMPANION_POLL_MS || 60000);
const AUTO_START_SERVICES = process.env.MEMO_COMPANION_AUTO_START !== '0';
const ICON_PATH = path.join(__dirname, 'assets', process.platform === 'win32' ? 'memo-companion.ico' : 'memo-companion.png');
const RELEASE_PAGE = process.env.MEMO_RELEASE_PAGE || 'https://github.com/adoublegirl-dev/memo/releases';
const RELEASE_API = process.env.MEMO_RELEASE_API || 'https://api.github.com/repos/adoublegirl-dev/memo/releases/latest';

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
  const bundledPython = path.join(ROOT, 'runtime', 'python.exe');
  return {
    MEMO_USER_ROOT: USER_MEMO_ROOT,
    MEMO_DATA_ROOT: USER_MEMO_DATA_ROOT,
    MEMO_ENV_FILE: USER_MEMO_ENV_FILE,
    MEMO_LOG_DIR: path.join(USER_MEMO_DATA_ROOT, 'logs'),
    MEMO_PID_DIR: path.join(USER_MEMO_DATA_ROOT, 'pids'),
    PYTHON_EXE: fs.existsSync(bundledPython) ? bundledPython : process.env.PYTHON_EXE || '',
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

async function updateMemoService() {
  if (serviceUpdateRunning) {
    return { ok: false, message: 'Memo 服务更新已在进行中，请稍候。' };
  }
  serviceUpdateRunning = true;
  serviceAction = 'updating';
  refreshAndSend();
  const steps = [];
  const finish = async (result) => {
    serviceUpdateRunning = false;
    serviceAction = 'idle';
    setTimeout(refreshAndSend, 2500);
    return result;
  };

  try {
    const isGitRuntime = fs.existsSync(path.join(ROOT, '.git'));

    steps.push('停止 Memo 服务');
    await runBat('stop_all.bat', 'updating');

    steps.push('确认 Source-Aware 新库为唯一运行库');
    const prepareScript = path.join(ROOT, 'scripts', 'prepare_source_aware_runtime.py');
    if (!fs.existsSync(prepareScript)) {
      await runBat('start_all.bat', 'updating');
      return await finish({
        ok: false,
        message: '当前安装版缺少 Source-Aware 数据库准备器。请先安装最新 Release；安装后旧 memo.db 将只备份，不会再被服务使用。',
      });
    }
    const prepared = await runCommand(
      getPythonCommand(),
      [prepareScript, '--apply', '--confirm', 'PREPARE_SOURCE_AWARE'],
      { cwd: ROOT },
    );
    if (!prepared.ok) {
      await runBat('start_all.bat', 'updating');
      return await finish({
        ok: false,
        message: `Source-Aware 新库准备失败，未下载或覆盖任何服务文件，更新已安全停止。\n${compactOutput(prepared.stderr || prepared.stdout).replace(/\uFFFD/g, '?')}`,
      });
    }
    steps.push('归档当前 Source-Aware 数据库和 .env');
    const archiveScript = path.join(ROOT, 'scripts', 'archive_current_db.py');
    if (fs.existsSync(archiveScript)) {
      const archive = await runCommand(getPythonCommand(), [archiveScript, '--apply', '--confirm', 'ARCHIVE', '--label', 'desktop-update'], { cwd: ROOT });
      if (!archive.ok) {
        const archiveDetail = compactOutput(archive.stderr || archive.stdout).replace(/\uFFFD/g, '?');
        return await finish({
          ok: false,
          message: `数据库归档失败，未下载或覆盖任何服务文件，更新已安全停止。\n${archiveDetail}\n\n请确认 Memo 安装目录的 .env 中 MEMO_DB_PATH 指向当前实际数据库后重试。`,
        });
      }
    } else {
      steps.push('未找到 archive_current_db.py，跳过脚本归档');
    }

    let updateOutput = '';
    if (isGitRuntime) {
      steps.push('拉取 GitHub 最新代码');
      const pull = await runCommand('git', ['-c', 'http.proxy=', '-c', 'https.proxy=', 'pull', '--ff-only', 'origin', 'main'], { cwd: ROOT });
      if (!pull.ok) {
        await runBat('start_all.bat', 'updating');
        return await finish({ ok: false, message: `git pull 失败，已尝试重新启动服务。\n${compactOutput(pull.stderr || pull.stdout)}` });
      }
      updateOutput = pull.stdout;
    } else {
      steps.push('下载 GitHub 最新服务代码包');
      const bundledUpdater = path.join(ROOT, 'scripts', 'update_bundled_runtime.py');
      if (!fs.existsSync(bundledUpdater)) {
        await runBat('start_all.bat', 'updating');
        return await finish({
          ok: false,
          message: '当前是 exe 安装版，且旧版本尚不支持安装版在线更新。请先安装最新 Release；以后即可在启动器内更新 Memo 服务。',
        });
      }
      const update = await runCommand(
        getPythonCommand(),
        [bundledUpdater, '--apply', '--confirm', 'UPDATE_BUNDLED', '--target-root', ROOT],
        { cwd: ROOT },
      );
      if (!update.ok) {
        await runBat('start_all.bat', 'updating');
        return await finish({ ok: false, message: `安装版服务代码更新失败，已尝试重新启动服务。\n${compactOutput(update.stderr || update.stdout)}` });
      }
      updateOutput = update.stdout;
      steps.push('保留 data / .env / Source-Aware 数据库 / WAL / SHM');
    }

    steps.push('编译检查');
    const pycheck = await runCommand(getPythonCommand(), ['-m', 'py_compile', path.join(ROOT, 'scripts', 'memo_dashboard.py'), path.join(ROOT, 'memo', 'core', 'engine.py')], { cwd: ROOT });
    if (!pycheck.ok) {
      await runBat('start_all.bat', 'updating');
      return await finish({ ok: false, message: `代码编译检查失败，已尝试重新启动服务。\n${compactOutput(pycheck.stderr || pycheck.stdout)}` });
    }

    steps.push('启动 Memo 服务');
    const start = await runBat('start_all.bat', 'updating');
    if (!start.ok) {
      return await finish({ ok: false, message: 'Memo 服务代码已更新，但启动脚本返回异常。请查看 data/logs。' });
    }
    steps.push('确认 9120 启动页与 9121 Dashboard 均已就绪');
    const ready = await waitForMemoServices(60);
    return await finish({
      ok: ready.ok,
      message: ready.ok
        ? `Memo 服务已更新并重启，启动页和 Dashboard 均已就绪。\n更新模式：${isGitRuntime ? 'Git 源码版' : 'exe 安装版安全覆盖'}\n执行步骤：${steps.join(' → ')}\n${compactOutput(updateOutput)}`
        : `Memo 服务代码已更新，但未能完成启动。\n${ready.message}`,
    });
  } catch (error) {
    try { await runBat('start_all.bat', 'updating'); } catch (_) {}
    return await finish({ ok: false, message: `Memo 服务更新失败：${error?.message || error}` });
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
    const envPath = path.join(ROOT, '.env');
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
  const localPython = path.join(ROOT, '.venv', 'Scripts', 'python.exe');
  return fs.existsSync(localPython) ? localPython : 'python';
}

function buildMcpConfig() {
  const dbPath = readEnvValue('MEMO_DB_PATH', 'data/memo_source_aware.db');
  const config = {
    mcpServers: {
      memo: {
        command: getPythonCommand(),
        args: [path.join(ROOT, 'scripts', 'run_mcp.py')],
        cwd: ROOT,
        env: {
          MEMO_DB_PATH: dbPath,
        },
      },
    },
  };
  return {
    memoRoot: ROOT,
    config,
    configText: JSON.stringify(config, null, 2),
  };
}

function copyMcpConfig(text) {
  clipboard.writeText(String(text || buildMcpConfig().configText));
  return { ok: true };
}

function openMemoRoot() {
  shell.openPath(ROOT);
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

function compareVersions(left, right) {
  const normalize = (value) => String(value || '').replace(/^v/, '').split(/[-+]/)[0].split('.').map((n) => Number(n) || 0);
  const a = normalize(left); const b = normalize(right);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) > (b[i] || 0) ? 1 : -1;
  }
  return 0;
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
        response.resume(); downloadFile(response.headers.location, destination).then(resolve, reject); return;
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

async function installDesktopUpdate() {
  const latest = await fetchJson(RELEASE_API, null);
  if (!latest) return { ok: false, message: '无法连接 GitHub Release 更新源。' };
  const current = appVersion();
  const tag = latest.tag_name || latest.name || '';
  if (compareVersions(tag, current) <= 0) return { ok: true, message: `当前已是最新版本 ${current}。` };
  const asset = (latest.assets || []).find((item) => /Setup.*\.exe$/i.test(item.name || ''));
  if (!asset?.browser_download_url) return { ok: false, message: `Release ${tag} 未找到 Windows Setup 安装包。` };
  const tempDir = path.join(app.getPath('temp'), 'memo-desktop-update');
  fs.mkdirSync(tempDir, { recursive: true });
  const target = path.join(tempDir, asset.name);
  try {
    if (fs.existsSync(target)) fs.unlinkSync(target);
    await downloadFile(asset.browser_download_url, target);
    const size = fs.statSync(target).size;
    if (size < 1024 * 1024) throw new Error('下载文件异常小，已取消安装。');
    const publishedDigest = String(asset.digest || '').replace(/^sha256:/i, '').toLowerCase();
    if (publishedDigest) {
      const actualDigest = await sha256File(target);
      if (actualDigest !== publishedDigest) throw new Error('安装包 SHA-256 校验不一致，已取消安装。');
    }
    const child = spawn(target, [], { detached: true, stdio: 'ignore', windowsHide: false });
    child.unref();
    setTimeout(() => app.quit(), 1200);
    return { ok: true, message: `已下载 ${tag} 并打开安装程序。请按安装向导完成覆盖安装，安装器会保留本地 data 和 .env。` };
  } catch (error) {
    return { ok: false, message: `启动器更新失败：${error?.message || error}` };
  }
}

async function checkForUpdates() {
  const current = appVersion();
  const latest = await fetchJson(RELEASE_API, null);
  if (!latest) {
    return { ok: false, current, message: `当前版本 ${current}。暂时无法连接更新源。` };
  }
  const tag = latest.tag_name || latest.name || '';
  const page = latest.html_url || RELEASE_PAGE;
  const assets = Array.isArray(latest.assets) ? latest.assets.map((a) => ({ name: a.name, url: a.browser_download_url })) : [];
  return {
    ok: true,
    current,
    latest: tag,
    page,
    assets,
    message: `当前版本 ${current}；最新版本 ${tag || '未知'}。可点击“打开下载页”获取安装包。`,
  };
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
ipcMain.handle('memo:checkForUpdates', () => checkForUpdates());
ipcMain.handle('memo:installDesktopUpdate', () => installDesktopUpdate());
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
