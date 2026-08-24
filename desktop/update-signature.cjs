'use strict';

const crypto = require('crypto');

const SIGNATURE_VERSION = 1;
const TRUSTED_UPDATE_KEYS = Object.freeze({
  'memo-ed25519-21a636a075e5bc03': `-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAmtf08uuRTatRP8V90m94R7WTArYtFj73AjzWWFTrOZ8=
-----END PUBLIC KEY-----`,
});

function sortJson(value) {
  if (typeof value === 'number' && !Number.isSafeInteger(value)) {
    throw new Error('Signed update manifests may contain only safe integer numbers');
  }
  if (Array.isArray(value)) return value.map(sortJson);
  if (value && typeof value === 'object') {
    return Object.keys(value).sort().reduce((result, key) => {
      if (value[key] !== undefined) result[key] = sortJson(value[key]);
      return result;
    }, {});
  }
  return value;
}

function canonicalManifestBytes(manifest) {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) {
    throw new Error('Update manifest must be a JSON object');
  }
  const unsigned = { ...manifest };
  delete unsigned.signature;
  return Buffer.from(JSON.stringify(sortJson(unsigned)), 'utf8');
}

function strictBase64(value) {
  const text = String(value || '');
  if (!text || !/^[A-Za-z0-9+/]+={0,2}$/.test(text) || text.length % 4 !== 0) return null;
  const decoded = Buffer.from(text, 'base64');
  return decoded.toString('base64') === text ? decoded : null;
}

function verifyReleaseManifest(manifest, trustedKeys = TRUSTED_UPDATE_KEYS) {
  try {
    if (Number(manifest?.formatVersion || 0) !== 3 || Number(manifest?.signatureVersion || 0) !== SIGNATURE_VERSION) {
      return { ok: false, error: '更新清单不是受支持的签名格式' };
    }
    const signature = manifest?.signature;
    if (!signature || signature.algorithm !== 'Ed25519' || !signature.keyId) {
      return { ok: false, error: '更新清单缺少Ed25519签名' };
    }
    const publicKey = trustedKeys[signature.keyId];
    if (!publicKey) return { ok: false, error: `更新清单使用了未知签名密钥：${signature.keyId}` };
    const signatureBytes = strictBase64(signature.value);
    if (!signatureBytes || signatureBytes.length !== 64) {
      return { ok: false, error: '更新清单签名编码无效' };
    }
    const valid = crypto.verify(null, canonicalManifestBytes(manifest), publicKey, signatureBytes);
    return valid ? { ok: true, keyId: signature.keyId } : { ok: false, error: '更新清单签名验证失败，内容可能已被篡改' };
  } catch (error) {
    return { ok: false, error: `更新清单验签异常：${error?.message || error}` };
  }
}

module.exports = {
  SIGNATURE_VERSION,
  TRUSTED_UPDATE_KEYS,
  canonicalManifestBytes,
  verifyReleaseManifest,
};
