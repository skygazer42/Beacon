function normalizePath(value) {
  return String(value || '').replaceAll('\\', '/');
}

function sanitizeLabel(value) {
  const normalized = String(value || '').startsWith('@') ? String(value || '').slice(1) : String(value || '');
  const extensionIndex = normalized.lastIndexOf('.');
  const withoutExtension = extensionIndex > 0 ? normalized.slice(0, extensionIndex) : normalized;
  return withoutExtension
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .join('-');
}

function sanitizePackageLabel(value) {
  return sanitizeLabel(value)
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .toLowerCase();
}

const STRUCTURAL_SEGMENTS = new Set(['src', 'es', 'lib', 'dist', 'style', 'styles', 'index']);
const GENERIC_SEGMENTS = new Set([
  'index',
  'input',
  'row',
  'client',
  'collapse',
  'table',
  'pagination',
  'purepanel',
  'overflow',
  'context',
  'constant',
  'util',
  'common',
  'group',
  'grid',
  'collection',
  'supportutil',
]);

function normalizeGenericToken(value) {
  return sanitizePackageLabel(value).replaceAll('-', '');
}

function isGenericLabel(value) {
  return GENERIC_SEGMENTS.has(normalizeGenericToken(value));
}

function isGenericChunkName(name) {
  return isGenericLabel(name);
}

function getPackageName(id) {
  const normalized = normalizePath(id);
  const [, afterNodeModules = ''] = normalized.split('/node_modules/');
  if (!afterNodeModules) return '';

  const resolved = afterNodeModules.startsWith('.pnpm/')
    ? afterNodeModules.split('/node_modules/').at(-1) || ''
    : afterNodeModules;

  if (resolved.startsWith('@')) {
    const [scope, name] = resolved.split('/');
    return scope && name ? `${scope}/${name}` : resolved;
  }

  return resolved.split('/')[0] || '';
}

function getMeaningfulSegments(segments) {
  return segments
    .map((segment) => segment.replace(/\.[^.]+$/, ''))
    .filter(Boolean)
    .filter((segment) => !STRUCTURAL_SEGMENTS.has(segment));
}

function lastPackagePart(packageName) {
  const packageTail = String(packageName || '').split('/').at(-1) || '';
  return sanitizePackageLabel(packageTail.split('-').at(-1) || packageTail);
}

function deriveFromSourceModule(id, chunkName = '') {
  const normalized = normalizePath(id);
  const [, afterSrc = ''] = normalized.split('/src/');
  if (!afterSrc) return '';

  const parts = getMeaningfulSegments(afterSrc.split('/')).map(sanitizeLabel).filter(Boolean);
  const last = parts.at(-1) || '';
  const previous = parts.at(-2) || '';
  const chunkToken = sanitizeLabel(chunkName);

  if (!last) return '';
  if (isGenericLabel(last) && previous) {
    return `${previous}-${last}`;
  }
  if (isGenericLabel(last) && chunkToken && chunkToken !== last) {
    return `${last}-${chunkToken}`;
  }
  return last;
}

function deriveFromPackageModule(id, chunkName = '') {
  const normalized = normalizePath(id);
  const packageName = getPackageName(normalized);
  if (!packageName) return '';

  const [, afterNodeModules = ''] = normalized.split('/node_modules/');
  const resolved = afterNodeModules.startsWith('.pnpm/')
    ? afterNodeModules.split('/node_modules/').at(-1) || ''
    : afterNodeModules;

  const parts = resolved.split('/');
  const packageDepth = packageName.startsWith('@') ? 2 : 1;
  const packageSegments = getMeaningfulSegments(parts.slice(packageDepth)).map(sanitizePackageLabel).filter(Boolean);
  const packageLabel = sanitizePackageLabel(packageName);
  const moduleLabel = packageSegments.at(-1) || '';
  const previousLabel = packageSegments.at(-2) || '';
  const distinctPreviousLabel = previousLabel && previousLabel !== moduleLabel ? previousLabel : '';
  const chunkToken = sanitizePackageLabel(chunkName);
  const packageTail = lastPackagePart(packageName);

  if (!moduleLabel) {
    return packageLabel;
  }

  if (moduleLabel === packageTail) {
    return packageLabel;
  }

  if (isGenericLabel(moduleLabel) && distinctPreviousLabel) {
    return `${packageLabel}-${distinctPreviousLabel}-${moduleLabel}`;
  }

  if (isGenericLabel(moduleLabel) && chunkToken && chunkToken !== moduleLabel) {
    return `${packageLabel}-${moduleLabel}-${chunkToken}`;
  }

  return `${packageLabel}-${moduleLabel}`;
}

export function getChunkBaseName(chunkInfo) {
  const name = String(chunkInfo?.name || '');
  const moduleIds = Array.isArray(chunkInfo?.moduleIds) ? chunkInfo.moduleIds : [];

  if (name && !isGenericChunkName(name)) {
    return name;
  }

  for (const moduleId of moduleIds) {
    const sourceLabel = sanitizeLabel(deriveFromSourceModule(moduleId, name));
    if (sourceLabel) {
      return `shared-${sourceLabel}`;
    }
  }

  for (const moduleId of moduleIds) {
    const packageLabel = sanitizeLabel(deriveFromPackageModule(moduleId, name));
    if (packageLabel) {
      return `shared-${packageLabel}`;
    }
  }

  return name || 'shared-chunk';
}

export function createChunkFileName(chunkInfo) {
  return `chunks/${getChunkBaseName(chunkInfo)}-[hash].js`;
}
