'use strict';

function parseVersion(value) {
  const normalized = String(value || '').trim().replace(/^v/i, '').split('+', 1)[0];
  const separator = normalized.indexOf('-');
  const coreText = separator >= 0 ? normalized.slice(0, separator) : normalized;
  const prereleaseText = separator >= 0 ? normalized.slice(separator + 1) : '';
  const core = coreText.split('.').map((part) => {
    const parsed = Number.parseInt(part, 10);
    return Number.isFinite(parsed) ? parsed : 0;
  });
  const prerelease = prereleaseText ? prereleaseText.split('.') : [];
  return { core, prerelease };
}

function compareIdentifier(left, right) {
  if (left === right) return 0;
  const leftNumeric = /^\d+$/.test(left);
  const rightNumeric = /^\d+$/.test(right);
  if (leftNumeric && rightNumeric) return Number(left) > Number(right) ? 1 : -1;
  if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1;
  const compared = left.toLowerCase().localeCompare(right.toLowerCase(), 'en');
  return compared === 0 ? 0 : (compared > 0 ? 1 : -1);
}

function compareVersions(left, right) {
  const a = parseVersion(left);
  const b = parseVersion(right);
  for (let i = 0; i < Math.max(a.core.length, b.core.length); i += 1) {
    const leftPart = a.core[i] || 0;
    const rightPart = b.core[i] || 0;
    if (leftPart !== rightPart) return leftPart > rightPart ? 1 : -1;
  }

  if (a.prerelease.length === 0 && b.prerelease.length === 0) return 0;
  if (a.prerelease.length === 0) return 1;
  if (b.prerelease.length === 0) return -1;

  for (let i = 0; i < Math.max(a.prerelease.length, b.prerelease.length); i += 1) {
    if (i >= a.prerelease.length) return -1;
    if (i >= b.prerelease.length) return 1;
    const compared = compareIdentifier(a.prerelease[i], b.prerelease[i]);
    if (compared !== 0) return compared;
  }
  return 0;
}

module.exports = { compareVersions, parseVersion };
