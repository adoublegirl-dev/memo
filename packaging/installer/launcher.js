const statusEl = document.getElementById('status');
const startBtn = document.getElementById('start');
const openBtn = document.getElementById('open');
const folderBtn = document.getElementById('folder');
const setupBtn = document.getElementById('setup');
let selectedUserRoot = '';

async function refresh() {
  const result = await window.memoInstaller.detect();
  selectedUserRoot = result.selectedUserRoot || result.paths?.user_root || '';
  if (result.ok === false) {
    statusEl.className = 'status error';
    statusEl.textContent = result.error || '安装状态读取失败。';
    return;
  }
  statusEl.className = 'status';
  statusEl.textContent = `状态：${result.mode} · 数据库：${result.paths.database}`;
}

startBtn.addEventListener('click', async () => {
  startBtn.disabled = true;
  statusEl.className = 'status';
  statusEl.textContent = '正在启动 Memo 服务…';
  try {
    const result = await window.memoInstaller.startMemo({ userRoot: selectedUserRoot });
    if (result.ok) {
      statusEl.className = 'status success';
      statusEl.textContent = 'Memo 服务已启动。正在打开工作台…';
      setTimeout(() => window.memoInstaller.openDashboard(), 600);
    } else {
      statusEl.className = 'status error';
      statusEl.textContent = `启动失败：${result.error || result.code || '未知错误'}`;
    }
  } finally {
    startBtn.disabled = false;
  }
});
openBtn.addEventListener('click', () => window.memoInstaller.openDashboard());
folderBtn.addEventListener('click', () => window.memoInstaller.openUserRoot({ userRoot: selectedUserRoot }));
setupBtn.addEventListener('click', () => window.memoInstaller.openSetup());
refresh();
