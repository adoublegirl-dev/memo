const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const {
  discoverDataRoots,
  migrateDataRoot,
  readLocationPreference,
  writeLocationPreference,
} = require('../desktop/data-location.cjs');

function temporaryRoot() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'memo-data-location-'));
}

function writeFakeDb(directory, name = 'memo_source_aware.db', content = 'sqlite-fixture') {
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, name), content);
}

test('discovers standard and legacy data without duplicating paths', () => {
  const root = temporaryRoot();
  const standard = path.join(root, 'official', 'data');
  const legacy = path.join(root, 'dev', 'data');
  writeFakeDb(standard, 'official.db');
  writeFakeDb(legacy, 'legacy.db');
  const found = discoverDataRoots({ standardDataRoot: standard, legacyRoots: [legacy, legacy] });
  assert.equal(found.length, 2);
  assert.equal(found[0].kind, 'standard');
  assert.equal(found[1].kind, 'legacy');
});

test('persists a valid selected data root and ignores a stale selection', () => {
  const root = temporaryRoot();
  const dataRoot = path.join(root, 'data');
  const preference = path.join(root, 'config', 'data-location.json');
  writeFakeDb(dataRoot);
  writeLocationPreference(preference, dataRoot, 'test');
  assert.equal(readLocationPreference(preference), path.resolve(dataRoot));
  fs.rmSync(dataRoot, { recursive: true });
  assert.equal(readLocationPreference(preference), '');
});

test('migration copies database, WAL and SHM to target and backup without deleting source', () => {
  const root = temporaryRoot();
  const source = path.join(root, 'legacy');
  const target = path.join(root, 'official');
  const backups = path.join(root, 'backups');
  writeFakeDb(source, 'memo.db', 'database');
  fs.writeFileSync(path.join(source, 'memo.db-wal'), 'wal');
  fs.writeFileSync(path.join(source, 'memo.db-shm'), 'shm');

  const result = migrateDataRoot({ sourceDataRoot: source, standardDataRoot: target, backupRoot: backups });
  for (const name of ['memo.db', 'memo.db-wal', 'memo.db-shm']) {
    assert.equal(fs.readFileSync(path.join(target, name), 'utf8'), fs.readFileSync(path.join(source, name), 'utf8'));
    assert.equal(fs.readFileSync(path.join(result.backupDir, name), 'utf8'), fs.readFileSync(path.join(source, name), 'utf8'));
  }
  assert.equal(fs.existsSync(path.join(source, 'memo.db')), true);
});

test('migration refuses to overwrite an existing official database', () => {
  const root = temporaryRoot();
  const source = path.join(root, 'legacy');
  const target = path.join(root, 'official');
  writeFakeDb(source, 'legacy.db');
  writeFakeDb(target, 'official.db');
  assert.throws(
    () => migrateDataRoot({ sourceDataRoot: source, standardDataRoot: target, backupRoot: path.join(root, 'backups') }),
    /不能自动迁移/,
  );
  assert.equal(fs.readFileSync(path.join(target, 'official.db'), 'utf8'), 'sqlite-fixture');
});
