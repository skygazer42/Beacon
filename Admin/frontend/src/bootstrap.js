let _bootstrapData = null;

function cleanupLegacyDebugBadges() {
  if (globalThis.document === undefined) return;

  globalThis.document.querySelectorAll('#beacon_debug_badge, .bcn-debug-badge').forEach((node) => {
    node.remove();
  });
}

function createFallbackBootstrap(path = '/', search = '') {
  return {
    path,
    queryString: search.replace(/^\?/, ''),
    siteName: 'Beacon',
    siteTitle: 'Beacon 新一代 AI 视频分析系统',
    siteLogo: '/static/images/logo.png',
    themeColor: '',
    docsUrl: '',
    downloadUrl: '',
    deploymentMode: 'edge',
    debugEnabled: false,
    user: { id: '', username: '', isStaff: false, isSuperuser: false },
  };
}

function getFallbackBootstrap() {
  if (globalThis.window === undefined) {
    return createFallbackBootstrap();
  }

  return createFallbackBootstrap(globalThis.location.pathname || '/', globalThis.location.search || '');
}

export function readBootstrap() {
  if (_bootstrapData) return _bootstrapData;

  cleanupLegacyDebugBadges();

  const el = document.getElementById('beacon-bootstrap');
  if (!el) {
    _bootstrapData = getFallbackBootstrap();
    return _bootstrapData;
  }

  try {
    _bootstrapData = JSON.parse(el.textContent || '{}');
  } catch {
    _bootstrapData = getFallbackBootstrap();
  }

  return _bootstrapData;
}

export function getBootstrapPath() {
  const data = readBootstrap();
  return data.path || '/';
}

export function getBootstrapQueryString() {
  const data = readBootstrap();
  return data.queryString || '';
}

export function getBootstrapQuery() {
  const data = readBootstrap();
  return new URLSearchParams(data.queryString || '');
}

export function isBootstrapPopupMode() {
  return getBootstrapQuery().get('popup') === '1';
}

export function getBootstrapUser() {
  const data = readBootstrap();
  return data.user || { id: '', username: '', isStaff: false, isSuperuser: false };
}

export function getBootstrapDeploymentMode() {
  return readBootstrap().deploymentMode === 'cloud' ? 'cloud' : 'edge';
}

export function getSiteBranding() {
  const data = readBootstrap();
  return {
    name: data.siteName || 'Beacon',
    title: data.siteTitle || 'Beacon 新一代 AI 视频分析系统',
    logo: data.siteLogo || '/static/images/logo.png',
    themeColor: data.themeColor || '',
    docsUrl: data.docsUrl || '',
    downloadUrl: data.downloadUrl || '',
  };
}

export function resetBootstrapCache() {
  _bootstrapData = null;
}
