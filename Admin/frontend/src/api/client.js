class ApiError extends Error {
  constructor(message, code) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
  }
}

function getCsrfToken() {
  const match = /(?:^|;\s*)csrftoken=([^;]*)/.exec(document.cookie);
  return match ? decodeURIComponent(match[1]) : '';
}

async function apiRequest(url, options = {}, requestOptions = {}) {
  const { unwrapData = true, throwOnErrorCode = true } = requestOptions;
  const headers = { 'X-Beacon-App-Shell': '1', ...options.headers };

  if (options.method && options.method !== 'GET') {
    headers['X-CSRFToken'] = getCsrfToken();
  }

  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }

  const res = await fetch(url, {
    credentials: 'same-origin',
    ...options,
    headers,
  });

  if (res.status === 401 || res.status === 403) {
    globalThis.location.href = '/login';
    return undefined;
  }

  const contentType = res.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status);
    return undefined;
  }

  const json = await res.json();

  if (throwOnErrorCode && json.code !== undefined && json.code !== 1000) {
    throw new ApiError(json.msg || '请求失败', json.code);
  }

  return unwrapData && json.data !== undefined ? json.data : json;
}

function buildUrlWithQuery(url, params) {
  let fullUrl = url;
  if (!params) return fullUrl;

  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.append(k, v);
  });

  const qstr = qs.toString();
  if (qstr) fullUrl += `?${qstr}`;
  return fullUrl;
}

export async function apiGet(url, params) {
  return apiRequest(buildUrlWithQuery(url, params), { method: 'GET' });
}

export async function apiGetRaw(url, params) {
  return apiRequest(buildUrlWithQuery(url, params), { method: 'GET' }, { unwrapData: false });
}

export async function apiPost(url, body) {
  return apiRequest(url, { method: 'POST', body });
}

export async function apiPostRaw(url, body) {
  return apiRequest(url, { method: 'POST', body }, { unwrapData: false });
}

export async function apiPostForm(url, formData) {
  return apiRequest(url, { method: 'POST', body: formData });
}

export async function apiPostFormRaw(url, formData) {
  return apiRequest(url, { method: 'POST', body: formData }, { unwrapData: false, throwOnErrorCode: false });
}

export { ApiError, getCsrfToken };
export default apiRequest;
