const $ = (id) => document.getElementById(id);

const els = {
  statusDot: $('statusDot'),
  statusText: $('statusText'),
  checkedAt: $('checkedAt'),
  todayTodos: $('todayTodos'),
  riskTodos: $('riskTodos'),
  pendingCandidates: $('pendingCandidates'),
  recentMemories: $('recentMemories'),
  hideBtn: $('hideBtn'),
  settingsBtn: $('settingsBtn'),
  settingsMenu: $('settingsMenu'),
  openDashboardBtn: $('openDashboardBtn'),
  refreshBtn: $('refreshBtn'),
  startBtn: $('startBtn'),
  restartBtn: $('restartBtn'),
  stopBtn: $('stopBtn'),
  loginToggle: $('loginToggle'),
};

function formatTime(iso) {
  if (!iso) return '尚未检查';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '刚刚';
  return `更新于 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
}

function setNumber(el, value) {
  el.textContent = Number.isFinite(Number(value)) ? String(value) : '--';
}

function actionText(action) {
  if (action === 'starting') return '正在启动 Memo 服务…';
  if (action === 'stopping') return '正在停止 Memo 服务…';
  if (action === 'restarting') return '正在重启 Memo 服务…';
  return '';
}

function setBusy(action) {
  const busy = action && action !== 'idle';
  els.startBtn.disabled = busy;
  els.restartBtn.disabled = busy;
  els.stopBtn.disabled = busy;
  els.refreshBtn.disabled = busy;
}

function render(snapshot) {
  if (!snapshot) return;
  els.statusDot.classList.toggle('ok', Boolean(snapshot.ok));
  els.statusDot.classList.toggle('bad', !snapshot.ok);
  els.statusText.textContent = actionText(snapshot.serviceAction) || snapshot.statusText || (snapshot.ok ? 'Memo 已连接' : 'Memo 未启动');
  els.checkedAt.textContent = formatTime(snapshot.checkedAt);
  setNumber(els.todayTodos, snapshot.todayTodos);
  setNumber(els.riskTodos, snapshot.riskTodos);
  setNumber(els.pendingCandidates, snapshot.pendingCandidates);
  setNumber(els.recentMemories, snapshot.recentMemories);
  if (typeof snapshot.loginItemEnabled === 'boolean') {
    els.loginToggle.checked = snapshot.loginItemEnabled;
  }
  setBusy(snapshot.serviceAction);
}

async function refresh() {
  els.refreshBtn.disabled = true;
  els.refreshBtn.textContent = '刷新中';
  try {
    const snapshot = await window.memoCompanion.getSnapshot();
    render(snapshot);
  } finally {
    els.refreshBtn.disabled = false;
    els.refreshBtn.textContent = '刷新';
  }
}

els.hideBtn.addEventListener('click', () => window.memoCompanion.hideWindow());

function setSettingsOpen(open) {
  els.settingsMenu.classList.toggle('open', open);
}

els.settingsBtn.addEventListener('click', (event) => {
  event.stopPropagation();
  setSettingsOpen(!els.settingsMenu.classList.contains('open'));
});
document.addEventListener('click', (event) => {
  if (!els.settingsMenu.contains(event.target) && event.target !== els.settingsBtn) {
    setSettingsOpen(false);
  }
});
els.openDashboardBtn.addEventListener('click', () => window.memoCompanion.openDashboard(''));
els.refreshBtn.addEventListener('click', refresh);
async function runServiceAction(button, label, action) {
  button.disabled = true;
  button.textContent = `${label}中`;
  try {
    await action();
    setTimeout(refresh, 3000);
  } finally {
    button.disabled = false;
    button.textContent = label;
    setSettingsOpen(false);
  }
}

els.startBtn.addEventListener('click', () => runServiceAction(els.startBtn, '启动服务', () => window.memoCompanion.startServices()));
els.restartBtn.addEventListener('click', () => runServiceAction(els.restartBtn, '重启', () => window.memoCompanion.restartServices()));
els.stopBtn.addEventListener('click', () => runServiceAction(els.stopBtn, '停止', () => window.memoCompanion.stopServices()));
els.loginToggle.addEventListener('click', (event) => event.stopPropagation());
els.loginToggle.addEventListener('change', async () => {
  const wanted = els.loginToggle.checked;
  els.loginToggle.disabled = true;
  const enabled = await window.memoCompanion.setLoginItemEnabled(wanted);
  els.loginToggle.checked = Boolean(enabled);
  els.loginToggle.disabled = false;
});

document.querySelectorAll('[data-route]').forEach((button) => {
  button.addEventListener('click', () => {
    window.memoCompanion.openDashboard(button.dataset.route || '');
  });
});

window.memoCompanion.onSnapshot(render);
refresh();
