const $ = (id) => document.getElementById(id);
const state = $('state');
const title = $('title');
const description = $('description');
const userRoot = $('userRoot');
const sourceList = $('sourceList');
const dataPlan = $('dataPlan');
const apiKey = $('apiKey');
const baseUrl = $('baseUrl');
const model = $('model');
const back = $('back');
const next = $('next');
const install = $('install');
const openCompanion = $('openCompanion');
const openFolder = $('openFolder');
const chooseSource = $('chooseSource');
const chooseTarget = $('chooseTarget');
const chooseFreshTarget = $('chooseFreshTarget');
const progress = $('progress');
const summary = $('summary');

const optionIds = {
  'migrate-default': 'optionMigrateDefault',
  'migrate-custom': 'optionMigrateCustom',
  'use-legacy': 'optionUseLegacy',
  'use-standard': 'optionUseStandard',
  'fresh-default': 'optionFreshDefault',
  'fresh-custom': 'optionFreshCustom',
};

let page = 0;
let currentMode = 'fresh';
let defaultRoot = '';
let preferredRoot = '';
let detectedRoots = [];
let selectedLegacy = null;
let customTarget = '';
let customTargetHasData = false;
let action = '';
let requiresExistingDataChoice = false;

function samePath(left, right) {
  return String(left || '').replace(/[\\/]+$/, '').toLowerCase() === String(right || '').replace(/[\\/]+$/, '').toLowerCase();
}

function formatBytes(bytes) {
  if (!bytes) return '大小未知';
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function standardData() {
  return detectedRoots.find((item) => item.kind === 'standard') || null;
}

function legacyData() {
  return detectedRoots.filter((item) => item.kind !== 'standard');
}

function setVisible(value, visible) {
  const element = $(optionIds[value]);
  element.hidden = !visible;
}

function selectAction(value) {
  action = value;
  const radio = document.querySelector(`input[name="dataAction"][value="${value}"]`);
  if (radio) radio.checked = true;
  document.querySelectorAll('.choice-card').forEach((card) => card.classList.toggle('selected', card.querySelector('input')?.checked));
  updatePlan();
}

function setPage(nextPage) {
  page = Math.max(0, Math.min(3, nextPage));
  document.querySelectorAll('.page').forEach((element) => element.classList.toggle('active', Number(element.dataset.page) === page));
  document.querySelectorAll('[data-nav]').forEach((element) => {
    const index = Number(element.dataset.nav);
    element.classList.toggle('active', index === page);
    element.classList.toggle('done', index < page);
  });
  back.disabled = page === 0;
  next.hidden = page === 3;
  install.hidden = page !== 3;
  updateSummary();
}

function setStep(active, done = []) {
  progress.hidden = false;
  document.querySelectorAll('.step').forEach((element) => {
    const name = element.dataset.step;
    element.classList.toggle('active', name === active);
    element.classList.toggle('done', done.includes(name));
  });
}

function targetForAction() {
  if (action === 'migrate-default' || action === 'use-standard' || action === 'fresh-default') return defaultRoot;
  if (action === 'migrate-custom' || action === 'fresh-custom') return customTarget;
  if (action === 'use-legacy') return selectedLegacy?.root || '';
  return '';
}

function migrateSource() {
  return action === 'migrate-default' || action === 'migrate-custom' ? selectedLegacy?.root || '' : '';
}

function validatePlan(showError = false) {
  let message = '';
  if (requiresExistingDataChoice && !selectedLegacy && !standardData()) message = 'Lite 更新没有识别到原数据目录。请点击“选择其他旧数据”，不要创建新的 Memo。';
  else if (!action) message = '请选择一种数据处理方式。';
  else if ((action === 'migrate-default' || action === 'migrate-custom' || action === 'use-legacy') && !selectedLegacy) message = '请先选择一份已有旧数据。';
  else if ((action === 'migrate-custom' || action === 'fresh-custom') && !customTarget) message = '请先选择新的数据位置。';
  else if ((action === 'migrate-custom' || action === 'fresh-custom') && customTargetHasData) message = '所选新位置已经有 Memo 数据。为避免覆盖，请选择空目录或新建目录。';
  else if (action === 'migrate-custom' && samePath(customTarget, selectedLegacy?.root)) message = '新位置不能与旧数据位置相同。';
  if (message && showError) {
    state.className = 'state error';
    state.textContent = message;
  }
  return !message;
}

function updatePlan() {
  const target = targetForAction();
  userRoot.value = target;
  document.querySelectorAll('.choice-card').forEach((card) => card.classList.toggle('selected', card.querySelector('input')?.checked));
  const plans = {
    'migrate-default': `旧数据来源：${selectedLegacy?.root || '未选择'}\n最终位置：${defaultRoot}\n执行方式：复制、校验并切换；原数据保留。以后更新自动沿用新位置。`,
    'migrate-custom': `旧数据来源：${selectedLegacy?.root || '未选择'}\n最终位置：${customTarget || '尚未选择'}\n执行方式：复制、校验并切换；原数据保留。以后更新自动沿用新位置。`,
    'use-legacy': `最终位置：${selectedLegacy?.root || '未选择'}\n执行方式：不复制，继续使用旧位置。以后更新自动沿用该位置。`,
    'use-standard': `最终位置：${defaultRoot}\n执行方式：继续使用正式版数据，不覆盖、不合并。以后更新不再询问。`,
    'fresh-default': `最终位置：${defaultRoot}\n执行方式：创建全新 Memo 数据。`,
    'fresh-custom': `最终位置：${customTarget || '尚未选择'}\n执行方式：创建全新 Memo 数据，不复制旧记忆。`,
  };
  dataPlan.textContent = plans[action] || '请选择一种数据处理方式。';
  updateSummary();
}

function updateSummary() {
  if (!summary) return;
  const target = targetForAction() || '未选择';
  const source = migrateSource();
  if (source) summary.textContent = `旧数据来源：${source}。最终位置：${target}。安装时会先备份，再复制、校验并切换；原数据不会删除。`;
  else summary.textContent = `最终使用位置：${target}。确认后将写入程序文件和配置；现有数据不会被自动覆盖。`;
}

function renderSources() {
  sourceList.innerHTML = '';
  if (!detectedRoots.length) {
    sourceList.textContent = '没有检测到已有数据库。新用户可以直接使用推荐位置创建 Memo。';
    return;
  }
  for (const item of detectedRoots) {
    const row = document.createElement('div');
    row.className = 'source-item';
    const label = item.kind === 'standard' ? '正式版数据' : (item.kind === 'selected' ? '当前正在使用的数据' : (samePath(item.root, selectedLegacy?.root) ? '已选择的旧数据' : '开发版/旧版数据')); 
    row.innerHTML = `<strong>${label}</strong><code>${item.root}</code><small>数据库：${item.database} · ${formatBytes(item.size)} · 最近更新 ${new Date(item.modifiedAt).toLocaleString()}</small>`;
    sourceList.appendChild(row);
  }
}

function configureActions() {
  const formal = standardData();
  const old = legacyData();
  if (!selectedLegacy || !old.some((item) => samePath(item.root, selectedLegacy.root))) selectedLegacy = old.find((item) => item.kind === 'selected') || old[0] || null;

  const hasFormal = Boolean(formal);
  const hasLegacy = Boolean(selectedLegacy);
  setVisible('migrate-default', hasLegacy && !hasFormal);
  setVisible('migrate-custom', hasLegacy && !hasFormal);
  setVisible('use-legacy', hasLegacy);
  setVisible('use-standard', hasFormal);
  setVisible('fresh-default', !requiresExistingDataChoice && !hasFormal);
  setVisible('fresh-custom', !requiresExistingDataChoice);

  $('defaultTargetPath').textContent = defaultRoot;
  $('standardTargetPath').textContent = defaultRoot;
  $('freshDefaultPath').textContent = defaultRoot;
  $('legacyTargetPath').textContent = selectedLegacy?.root || '';
  $('customTargetPath').textContent = customTarget || '尚未选择新位置';
  $('freshCustomPath').textContent = customTarget || '尚未选择新位置';

  if (hasFormal && samePath(preferredRoot, defaultRoot)) selectAction('use-standard');
  else if (hasLegacy && samePath(preferredRoot, selectedLegacy?.root)) selectAction('use-legacy');
  else if (hasFormal) selectAction('use-standard');
  else if (hasLegacy) selectAction('migrate-default');
  else if (!requiresExistingDataChoice) selectAction('fresh-default');
  else {
    action = '';
    document.querySelectorAll('input[name="dataAction"]').forEach((radio) => { radio.checked = false; });
    updatePlan();
  }
  renderSources();
}

async function pickTarget(nextAction) {
  const picked = await window.memoInstaller.chooseTargetRoot({ defaultPath: customTarget || defaultRoot });
  if (picked?.canceled || !picked?.path) return;
  customTarget = picked.path;
  customTargetHasData = Boolean(picked.existingData);
  $('customTargetPath').textContent = customTarget;
  $('freshCustomPath').textContent = customTarget;
  selectAction(nextAction);
  if (customTargetHasData) {
    state.className = 'state error';
    state.textContent = '这个目标目录已经包含 Memo 数据。为避免覆盖，请选择空目录或新建目录。';
  }
}

async function boot() {
  progress.hidden = true;
  const result = await window.memoInstaller.detect({});
  currentMode = result.mode || 'fresh';
  if (result.ok === false) {
    title.textContent = '检测失败';
    description.textContent = '请检查安装包是否完整。';
    state.textContent = result.error || '未知错误';
    state.className = 'state error';
    return;
  }
  defaultRoot = result.defaultUserRoot;
  preferredRoot = result.selectedUserRoot || '';
  detectedRoots = result.detectedDataRoots || [];
  requiresExistingDataChoice = Boolean(result.requiresExistingDataChoice);
  if (result.runtimeMissing) {
    title.textContent = 'Lite 版需要 Full Runtime';
    description.textContent = '当前电脑没有找到可复用的 Python Runtime。';
    state.className = 'state error';
    state.textContent = `请先安装最新版 Full 版一次。Full 会把 Runtime 固化到：${result.runtime?.expectedStablePath || 'Memo\\Programs\\Memo\\runtime'}。以后更新即可继续使用 Lite。你的现有数据不会被删除。`;
    install.disabled = true;
    configureActions();
    setPage(0);
    return;
  }
  state.className = 'state';
  state.textContent = detectedRoots.length
    ? `已检测到 ${detectedRoots.length} 份 Memo 数据。请确认复制或继续使用。`
    : (requiresExistingDataChoice
      ? '这是 Lite 更新，但没有识别到原数据目录。请在下一步手动选择已有数据，安装器不会创建第二份空数据。'
      : '未检测到旧数据，将使用推荐位置创建新的 Memo。');
  state.className = requiresExistingDataChoice && !detectedRoots.length ? 'state error' : 'state';
  title.textContent = currentMode === 'healthy_latest' ? 'Memo 已就绪' : '欢迎使用 Memo';
  description.textContent = '选择一次数据位置，后续更新会自动沿用。';
  openCompanion.hidden = currentMode !== 'healthy_latest';
  install.textContent = currentMode === 'healthy_latest' ? '应用选择' : '开始安装';
  configureActions();
  setPage(0);
}

back.addEventListener('click', () => setPage(page - 1));
next.addEventListener('click', () => {
  if (page === 1 && !validatePlan(true)) return;
  state.className = 'state';
  if (page === 1) state.textContent = '数据处理方案已确认。';
  setPage(page + 1);
});
document.querySelectorAll('input[name="dataAction"]').forEach((radio) => radio.addEventListener('change', () => selectAction(radio.value)));
chooseTarget.addEventListener('click', (event) => { event.preventDefault(); event.stopPropagation(); pickTarget('migrate-custom'); });
chooseFreshTarget.addEventListener('click', (event) => { event.preventDefault(); event.stopPropagation(); pickTarget('fresh-custom'); });
chooseSource.addEventListener('click', async () => {
  const picked = await window.memoInstaller.chooseLegacyRoot();
  if (picked?.canceled) return;
  if (!picked?.ok) {
    state.className = 'state error';
    state.textContent = picked?.error || '所选位置没有找到 Memo 数据。';
    return;
  }
  const item = picked.data;
  selectedLegacy = item;
  preferredRoot = item.root;
  requiresExistingDataChoice = false;
  if (!detectedRoots.some((candidate) => samePath(candidate.root, item.root))) detectedRoots.push(item);
  state.className = 'state success';
  state.textContent = `已确认旧数据：${item.database}（${formatBytes(item.size)}）。将继续使用：${item.root}`;
  configureActions();
  selectAction('use-legacy');
});

install.addEventListener('click', async () => {
  if (!validatePlan(true)) {
    setPage(1);
    return;
  }
  install.disabled = true;
  state.className = 'state';
  setStep('copy', []);
  state.textContent = migrateSource() ? '1/3 正在备份并复制旧数据…' : '1/3 正在写入 Memo 程序与配置…';
  try {
    const timer = setTimeout(() => {
      setStep('db', ['copy']);
      state.textContent = '2/3 正在校验并初始化本地数据库…';
    }, 900);
    const result = await window.memoInstaller.install({
      userRoot: targetForAction(),
      migrateFrom: migrateSource(),
      apiKey: apiKey.value,
      baseUrl: baseUrl.value,
      model: model.value,
    });
    clearTimeout(timer);
    if (result.ok) {
      setStep('done', ['copy', 'db', 'done']);
      state.className = 'state success';
      state.textContent = result.migration?.backup
        ? `复制和安装完成。旧数据仍在原位置，迁移备份：${result.migration.backup}`
        : '安装完成。以后更新将自动沿用当前数据位置。';
      openCompanion.hidden = false;
      setTimeout(() => window.memoInstaller.openCompanion({ userRoot: targetForAction() }), 900);
    } else {
      state.className = 'state error';
      state.textContent = `安装失败：${result.error || '未知错误'}`;
    }
  } catch (error) {
    state.className = 'state error';
    state.textContent = `安装失败：${error?.message || error}`;
  } finally {
    install.disabled = false;
  }
});

openCompanion.addEventListener('click', () => window.memoInstaller.openCompanion({ userRoot: targetForAction() || defaultRoot }));
openFolder.addEventListener('click', () => window.memoInstaller.openUserRoot({ userRoot: targetForAction() || defaultRoot }));
boot();
