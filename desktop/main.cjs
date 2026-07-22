const { app, BrowserWindow, Menu, Tray, nativeImage, Notification, ipcMain, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

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

function resolveMemoRoot() {
  const candidates = [
    process.env.MEMO_ROOT,
    ...(!app.isPackaged ? [path.resolve(__dirname, '..')] : []),
    process.cwd(),
    ...candidateAncestors(path.dirname(process.execPath || ''), 8),
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

  // 打包版找不到外部 Memo 根目录时，不回退到 resources/app，避免在安装包内部生成 data/.env。
  return app.isPackaged ? process.cwd() : path.resolve(__dirname, '..');
}

const ROOT = resolveMemoRoot();
const DASHBOARD_BASE = process.env.MEMO_DASHBOARD_URL || 'http://127.0.0.1:9121';
const BOOT_URL = process.env.MEMO_BOOT_URL || 'http://127.0.0.1:9120';
const POLL_INTERVAL_MS = Number(process.env.MEMO_COMPANION_POLL_MS || 60000);
const AUTO_START_SERVICES = process.env.MEMO_COMPANION_AUTO_START !== '0';
const ICON_PATH = path.join(__dirname, 'assets', process.platform === 'win32' ? 'memo-companion.ico' : 'memo-companion.png');

let mainWindow = null;
let tray = null;
let pollTimer = null;
let lastSnapshot = null;
let notificationsPausedUntil = 0;
let serviceAction = 'idle';
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
    // 首版保持不自动隐藏，避免用户误以为消失；后续可加偏好设置。
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

function buildTrayMenu() {
  const paused = notificationsPausedUntil > Date.now();
  return Menu.buildFromTemplate([
    { label: '显示/隐藏 Memo 助手', click: toggleWindow },
    { label: '打开 Memo Dashboard', click: () => openDashboard('') },
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
  const health = await fetchJson(`${DASHBOARD_BASE}/api/health`, null);
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
    fetchJson(`${DASHBOARD_BASE}/api/todos?include_done=false&limit=80`, []),
    fetchJson(`${DASHBOARD_BASE}/api/space/candidates?status=pending&limit=80`, {}),
    fetchJson(`${DASHBOARD_BASE}/api/memories?limit=20`, []),
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

function startMemoServices() {
  return runBat('start_all.bat', 'starting');
}

function stopMemoServices() {
  return runBat('stop_all.bat', 'stopping');
}

async function restartMemoServices() {
  serviceAction = 'restarting';
  refreshAndSend();
  await runBat('stop_all.bat', 'restarting');
  return runBat('start_all.bat', 'restarting');
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
  const health = await fetchJson(`${DASHBOARD_BASE}/api/health`, null);
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
