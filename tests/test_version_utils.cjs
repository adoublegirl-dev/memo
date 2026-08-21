const test = require('node:test');
const assert = require('node:assert/strict');

const { compareVersions } = require('../desktop/version-utils.cjs');

test('compares numeric release components', () => {
  assert.equal(compareVersions('0.10.8-alpha', '0.10.7-alpha'), 1);
  assert.equal(compareVersions('v0.10.6', '0.10.7'), -1);
  assert.equal(compareVersions('0.10.7', '0.10.7.0'), 0);
});

test('orders prerelease versions before the matching stable release', () => {
  assert.equal(compareVersions('0.10.7-alpha', '0.10.7-beta'), -1);
  assert.equal(compareVersions('0.10.7-beta', '0.10.7-rc'), -1);
  assert.equal(compareVersions('0.10.7-rc', '0.10.7'), -1);
  assert.equal(compareVersions('0.10.7', '0.10.7-alpha'), 1);
});

test('compares prerelease sequence numbers and ignores build metadata', () => {
  assert.equal(compareVersions('0.10.7-alpha.2', '0.10.7-alpha.10'), -1);
  assert.equal(compareVersions('0.10.7+build.2', '0.10.7+build.1'), 0);
});
