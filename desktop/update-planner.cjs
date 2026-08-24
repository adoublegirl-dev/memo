'use strict';

const { compareVersions } = require('./version-utils.cjs');

function validPatch(patch) {
  if (!patch || typeof patch !== 'object') return false;
  const from = String(patch.from || '');
  const to = String(patch.to || '');
  return Boolean(
    from && to && patch.url && patch.sha256
    && compareVersions(to, from) > 0
  );
}

function findPatchChain(currentVersion, targetVersion, patches, maxHops = 12) {
  const current = String(currentVersion || '');
  const target = String(targetVersion || '');
  if (!current || !target || compareVersions(target, current) <= 0) return [];
  const edges = (Array.isArray(patches) ? patches : [])
    .filter(validPatch)
    .filter((patch) => compareVersions(String(patch.to), target) <= 0);
  const queue = [{ version: current, chain: [] }];
  const visited = new Set([current]);
  while (queue.length) {
    const state = queue.shift();
    if (state.chain.length >= maxHops) continue;
    for (const patch of edges.filter((item) => String(item.from) === state.version)) {
      const next = String(patch.to);
      const chain = [...state.chain, patch];
      if (next === target) return chain;
      if (!visited.has(next)) {
        visited.add(next);
        queue.push({ version: next, chain });
      }
    }
  }
  return null;
}

function normalizeServiceRelease(manifest) {
  const service = manifest?.service;
  if (!service?.version) return null;
  const full = service.full?.url
    ? service.full
    : (service.url ? {
        name: service.name,
        url: service.url,
        size: service.size,
        sha256: service.sha256,
      } : null);
  return {
    ...service,
    version: String(service.version),
    full,
    patches: Array.isArray(service.patches) ? service.patches : [],
  };
}

function planServiceUpdate(manifest, installedState) {
  const service = normalizeServiceRelease(manifest);
  const current = String(installedState?.version || '');
  if (!service || !current) {
    return { kind: 'unavailable', service, current, target: service?.version || current };
  }
  if (compareVersions(service.version, current) <= 0) {
    return { kind: 'none', service, current, target: service.version };
  }
  if (service.runtimeChanged) {
    return { kind: 'installer', service, current, target: service.version };
  }
  if (installedState?.hasBaseline) {
    const chain = findPatchChain(current, service.version, service.patches);
    if (chain?.length) return { kind: 'delta-chain', service, current, target: service.version, chain };
  }
  if (service.full?.url) {
    return { kind: 'full-service', service, current, target: service.version, asset: service.full };
  }
  return { kind: 'unavailable', service, current, target: service.version };
}

module.exports = { findPatchChain, normalizeServiceRelease, planServiceUpdate };
