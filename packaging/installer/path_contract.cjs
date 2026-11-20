const path = require('path');
const fs = require('fs');

const CURRENT_DB_NAME = 'memo_source_aware.db';

function parseCodexMemoEnv(text) {
  const values = {};
  let inMemoEnv = false;
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim();
    if (/^\[.+\]$/.test(line)) {
      inMemoEnv = line === '[mcp_servers.memo.env]';
      continue;
    }
    if (!inMemoEnv) continue;
    const match = line.match(/^(MEMO_USER_ROOT|MEMO_DATA_ROOT|MEMO_DB_PATH|MEMO_RUNTIME_ROOT|PYTHON_EXE)\s*=\s*(['"])(.*?)\2\s*$/);
    if (match) values[match[1]] = match[3];
  }
  return values;
}

function inferRootFromRuntime(pythonPath) {
  if (!pythonPath) return '';
  const runtimeDir = path.dirname(path.resolve(pythonPath));
  const memoDir = path.dirname(runtimeDir);
  const programsDir = path.dirname(memoDir);
  if (path.basename(runtimeDir).toLowerCase() === 'runtime' && path.basename(memoDir).toLowerCase() === 'memo' && path.basename(programsDir).toLowerCase() === 'programs') return path.dirname(programsDir);
  return '';
}

function inferRootFromProgramPath(candidate) {
  if (!candidate) return '';
  let current = path.resolve(candidate);
  try { if (fs.statSync(current).isFile()) current = path.dirname(current); } catch (_) {}
  for (let depth = 0; depth < 6; depth += 1) {
    const parent = path.dirname(current);
    if (path.basename(current).toLowerCase() === 'memo' && path.basename(parent).toLowerCase() === 'programs') return path.dirname(parent);
    if (parent === current) break;
    current = parent;
  }
  return '';
}

function isSqliteFile(filePath) {
  try {
    const stat = fs.statSync(filePath);
    if (!stat.isFile() || stat.size < 16) return false;
    const fd = fs.openSync(filePath, 'r');
    try {
      const header = Buffer.alloc(16);
      fs.readSync(fd, header, 0, 16, 0);
      return header.toString('binary') === 'SQLite format 3\u0000';
    } finally {
      fs.closeSync(fd);
    }
  } catch (_) {
    return false;
  }
}

function normalizeMemoRoot(candidate) {
  if (!candidate) return '';
  let resolved = path.resolve(candidate);
  try {
    if (fs.statSync(resolved).isFile()) {
      if (path.basename(resolved).toLowerCase() === CURRENT_DB_NAME && path.basename(path.dirname(resolved)).toLowerCase() === 'data') return path.dirname(path.dirname(resolved));
      resolved = path.dirname(resolved);
    }
  } catch (_) {}
  if (path.basename(resolved).toLowerCase() === 'data') return path.dirname(resolved);
  return inferRootFromProgramPath(resolved) || resolved;
}

function memoDatabase(root) {
  const normalized = normalizeMemoRoot(root);
  return normalized ? path.join(normalized, 'data', CURRENT_DB_NAME) : '';
}

function hasMemoDatabase(root) {
  const database = memoDatabase(root);
  return Boolean(database && isSqliteFile(database));
}

function findMemoRootsNear(candidate, maxDepth = 2, maxDirectories = 300) {
  if (!candidate) return [];
  let start = path.resolve(candidate);
  try { if (fs.statSync(start).isFile()) start = path.dirname(start); } catch (_) {}
  const queue = [{ dir: start, depth: 0 }];
  const seenDirs = new Set();
  const found = [];
  const foundKeys = new Set();
  while (queue.length && seenDirs.size < maxDirectories) {
    const { dir, depth } = queue.shift();
    const dirKey = dir.toLowerCase();
    if (seenDirs.has(dirKey)) continue;
    seenDirs.add(dirKey);
    const normalized = normalizeMemoRoot(dir);
    if (hasMemoDatabase(normalized)) {
      const key = normalized.toLowerCase();
      if (!foundKeys.has(key)) {
        foundKeys.add(key);
        found.push(normalized);
      }
    }
    if (depth >= maxDepth) continue;
    try {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory() && !entry.isSymbolicLink()) queue.push({ dir: path.join(dir, entry.name), depth: depth + 1 });
      }
    } catch (_) {}
  }
  return found;
}

function profileEvidencePaths(homes) {
  const settings = [];
  const codex = [];
  for (const home of homes || []) {
    const roaming = path.join(home, 'AppData', 'Roaming');
    settings.push(path.join(roaming, 'Memo', 'memo-installer-settings.json'));
    settings.push(path.join(roaming, 'memo-full-installer', 'memo-installer-settings.json'));
    settings.push(path.join(roaming, 'memo-lite-installer', 'memo-installer-settings.json'));
    codex.push(path.join(home, '.codex', 'config.toml'));
  }
  return { settings, codex };
}

function selectSettings(records, hasDatabase = hasMemoDatabase) {
  let fallback = {};
  for (const parsed of records) {
    if (!parsed || typeof parsed !== 'object') continue;
    if (!Object.keys(fallback).length) fallback = parsed;
    if (parsed.userRoot && hasDatabase(parsed.userRoot)) return parsed;
  }
  return fallback;
}

module.exports = {
  CURRENT_DB_NAME,
  parseCodexMemoEnv,
  inferRootFromRuntime,
  inferRootFromProgramPath,
  isSqliteFile,
  normalizeMemoRoot,
  memoDatabase,
  hasMemoDatabase,
  findMemoRootsNear,
  profileEvidencePaths,
  selectSettings,
};
