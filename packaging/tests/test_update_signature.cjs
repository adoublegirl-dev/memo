'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('crypto');
const { canonicalManifestBytes, verifyReleaseManifest } = require('../desktop/update-signature.cjs');

function signedFixture() {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519');
  const keyId = 'test-key';
  const manifest = {
    formatVersion: 3,
    signatureVersion: 1,
    signedAt: '2026-08-24T00:00:00Z',
    version: '1.2.0',
    serviceVersion: '1.1.0',
    launcher: {
      version: '1.2.0',
      full: { name: 'Full.exe', url: 'https://example.invalid/Full.exe', size: 100, sha256: `sha256:${'a'.repeat(64)}` },
      lite: { name: 'Lite.exe', url: 'https://example.invalid/Lite.exe', size: 50, sha256: `sha256:${'b'.repeat(64)}` },
    },
    service: {
      version: '1.1.0',
      runtimeChanged: false,
      full: { name: 'Service.zip', url: 'https://example.invalid/service.zip', size: 10, sha256: `sha256:${'c'.repeat(64)}` },
      patches: [],
    },
  };
  manifest.signature = {
    algorithm: 'Ed25519',
    keyId,
    value: crypto.sign(null, canonicalManifestBytes(manifest), privateKey).toString('base64'),
  };
  const trusted = { [keyId]: publicKey.export({ type: 'spki', format: 'pem' }) };
  return { manifest, trusted };
}

test('accepts an authentic Ed25519 release manifest', () => {
  const { manifest, trusted } = signedFixture();
  assert.deepEqual(verifyReleaseManifest(manifest, trusted), { ok: true, keyId: 'test-key' });
});

test('rejects a tampered asset URL after signing', () => {
  const { manifest, trusted } = signedFixture();
  manifest.service.full.url = 'https://attacker.invalid/payload.zip';
  const result = verifyReleaseManifest(manifest, trusted);
  assert.equal(result.ok, false);
  assert.match(result.error, /篡改|验证失败/);
});

test('rejects unsigned manifests and unknown signing keys', () => {
  const { manifest, trusted } = signedFixture();
  const unsigned = { ...manifest };
  delete unsigned.signature;
  assert.equal(verifyReleaseManifest(unsigned, trusted).ok, false);

  manifest.signature.keyId = 'unknown-key';
  const result = verifyReleaseManifest(manifest, trusted);
  assert.equal(result.ok, false);
  assert.match(result.error, /未知签名密钥/);
});

test('rejects malformed base64 signatures', () => {
  const { manifest, trusted } = signedFixture();
  manifest.signature.value = 'not-base64!';
  const result = verifyReleaseManifest(manifest, trusted);
  assert.equal(result.ok, false);
  assert.match(result.error, /编码无效/);
});
