const fs = require('fs');
const path = require('path');

const DB_EXTENSIONS = ['.db', '.sqlite', '.sqlite3'];

function uniquePaths(paths) {
  const seen = new Set();
  return paths.filter(Boolean).filter((item) => {
    const resolved = path.resolve(item);
    const key = process.platform === 'win32' ? resolved.toLowerCase() : resolved;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map((item) => path.resolve(item));
}

function listDatabaseFiles(dataRoot) {
  if (!dataRoot || !fs.existsSync(dataRoot)) return [];
  try {
    return fs.readdirSync(dataRoot, { withFileTypes: true })
      .filter((entry) => entry.isFile() && DB_EXTENSIONS.includes(path.extname(entry.name).toLowerCase()))
      .map((entry) => {
        const filePath = path.join(dataRoot, entry.name);
        const stat = fs.statSync(filePath);
        return { name: entry.name, path: filePath, size: stat.size, mtimeMs: stat.mtimeMs };
      })
      .filter((entry) => entry.size > 0)
      .sort((a, b) => b.mtimeMs - a.mtimeMs);
  } catch (_) {
    return [];
  }
}

function inspectDataRoot(dataRoot, kind = 'legacy') {
  const databases = listDatabaseFiles(dataRoot);
  return {
    kind,
    path: path.resolve(dataRoot),
    databases,
    totalBytes: databases.reduce((sum, item) => sum + item.size, 0),
    latestMtimeMs: databases.reduce((latest, item) => Math.max(latest, item.mtimeMs), 0),
    hasData: databases.length > 0,
  };
}

function discoverDataRoots({ standardDataRoot, legacyRoots = [] }) {
  const roots = uniquePaths([standardDataRoot, ...legacyRoots]);
  return roots.map((root, index) => inspectDataRoot(root, index === 0 ? 'standard' : 'legacy'))
    .filter((item, index) => index === 0 || item.hasData);
}

function readLocationPreference(preferenceFile) {
  try {
    const parsed = JSON.parse(fs.readFileSync(preferenceFile, 'utf8'));
    if (parsed && typeof parsed.dataRoot === 'string' && listDatabaseFiles(parsed.dataRoot).length > 0) {
      return path.resolve(parsed.dataRoot);
    }
  } catch (_) {
    // Missing, invalid, or stale preferences are ignored.
  }
  return '';
}

function writeLocationPreference(preferenceFile, dataRoot, source = 'user-selection') {
  fs.mkdirSync(path.dirname(preferenceFile), { recursive: true });
  const payload = {
    version: 1,
    dataRoot: path.resolve(dataRoot),
    source,
    updatedAt: new Date().toISOString(),
  };
  const temporary = `${preferenceFile}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  fs.renameSync(temporary, preferenceFile);
  return payload;
}

function copyFileVerified(source, target) {
  fs.copyFileSync(source, target, fs.constants.COPYFILE_EXCL);
  const sourceStat = fs.statSync(source);
  const targetStat = fs.statSync(target);
  if (sourceStat.size !== targetStat.size) throw new Error(`复制校验失败：${path.basename(source)}`);
}

function migrateDataRoot({ sourceDataRoot, standardDataRoot, backupRoot }) {
  const source = inspectDataRoot(sourceDataRoot, 'legacy');
  if (!source.hasData) throw new Error('源目录中没有可迁移的数据库。');
  const target = inspectDataRoot(standardDataRoot, 'standard');
  if (target.hasData) throw new Error('正式数据目录已经包含数据库，为避免覆盖，不能自动迁移。');

  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const backupDir = path.join(backupRoot, `legacy-before-migration-${stamp}`);
  fs.mkdirSync(backupDir, { recursive: true });
  fs.mkdirSync(standardDataRoot, { recursive: true });

  const names = new Set(source.databases.map((item) => item.name));
  for (const database of source.databases) {
    for (const suffix of ['', '-wal', '-shm']) {
      const name = `${database.name}${suffix}`;
      const sourceFile = path.join(sourceDataRoot, name);
      if (!fs.existsSync(sourceFile)) continue;
      copyFileVerified(sourceFile, path.join(backupDir, name));
      copyFileVerified(sourceFile, path.join(standardDataRoot, name));
      names.add(name);
    }
  }

  return { dataRoot: path.resolve(standardDataRoot), backupDir, files: Array.from(names) };
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function describeDataRoot(item) {
  const latest = item.latestMtimeMs ? new Date(item.latestMtimeMs).toLocaleString() : '未知';
  return `${item.kind === 'standard' ? '正式版' : '开发版/旧版'}：${item.path}\n数据库：${item.databases.map((db) => db.name).join('、') || '无'}\n大小：${formatBytes(item.totalBytes)}，最近更新：${latest}`;
}

module.exports = {
  describeDataRoot,
  discoverDataRoots,
  inspectDataRoot,
  listDatabaseFiles,
  migrateDataRoot,
  readLocationPreference,
  writeLocationPreference,
};
