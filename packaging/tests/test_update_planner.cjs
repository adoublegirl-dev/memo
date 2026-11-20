'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { findPatchChain, planServiceUpdate } = require('../desktop/update-planner.cjs');

function patch(from, to) {
  return { from, to, url: `https://example.invalid/${from}-${to}.zip`, sha256: 'a'.repeat(64), size: 10 };
}

test('finds a multi-version patch chain', () => {
  const chain = findPatchChain('1.0.0', '1.3.0', [patch('1.0.0', '1.1.0'), patch('1.1.0', '1.2.0'), patch('1.2.0', '1.3.0')]);
  assert.deepEqual(chain.map((item) => `${item.from}->${item.to}`), ['1.0.0->1.1.0', '1.1.0->1.2.0', '1.2.0->1.3.0']);
});

test('prefers the shortest valid chain and ignores overshoot', () => {
  const chain = findPatchChain('1.0.0', '1.3.0', [
    patch('1.0.0', '1.1.0'), patch('1.1.0', '1.3.0'),
    patch('1.0.0', '1.3.0'), patch('1.0.0', '2.0.0'),
  ]);
  assert.equal(chain.length, 1);
  assert.equal(chain[0].to, '1.3.0');
});

test('uses delta only with installedFiles baseline and otherwise falls back to full service', () => {
  const manifest = {
    service: {
      version: '1.2.0',
      full: { url: 'https://example.invalid/full.zip', sha256: 'b'.repeat(64), size: 100 },
      patches: [patch('1.0.0', '1.1.0'), patch('1.1.0', '1.2.0')],
    },
  };
  assert.equal(planServiceUpdate(manifest, { version: '1.0.0', hasBaseline: true }).kind, 'delta-chain');
  assert.equal(planServiceUpdate(manifest, { version: '1.0.0', hasBaseline: false }).kind, 'full-service');
});

test('runtime changes force installer and missing chains never guess', () => {
  const runtimeManifest = { service: { version: '2.0.0', runtimeChanged: true, patches: [patch('1.0.0', '2.0.0')] } };
  assert.equal(planServiceUpdate(runtimeManifest, { version: '1.0.0', hasBaseline: true }).kind, 'installer');
  const noPath = { service: { version: '1.5.0', patches: [patch('1.1.0', '1.5.0')] } };
  assert.equal(planServiceUpdate(noPath, { version: '1.0.0', hasBaseline: true }).kind, 'unavailable');
});
