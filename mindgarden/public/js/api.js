// api.js —— 统一请求封装 + 会话状态 + 服务不可用反馈
// 所有页面都通过这里访问后端：401 统一跳登录，5xx/断网统一亮「服务暂时不可用」横幅。

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

let currentUser = null;
const listeners = new Set();

export function getUser() { return currentUser; }
export function isAdmin() { return !!currentUser && currentUser.role === 'admin'; }

export function setUser(user) {
  currentUser = user;
  listeners.forEach((fn) => fn(user));
}

export function onUserChange(fn) { listeners.add(fn); }

// ---------- 服务不可用横幅 ----------
function banner() { return document.getElementById('service-banner'); }

export function showServiceBanner() {
  const b = banner();
  if (b) b.classList.remove('hidden');
}

export function hideServiceBanner() {
  const b = banner();
  if (b) b.classList.add('hidden');
}

// ---------- 请求封装 ----------
export async function api(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'fetch',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    showServiceBanner();
    throw new ApiError(0, '网络连接失败，请检查网络后重试');
  }

  let data = null;
  try { data = await res.json(); } catch (e) { /* 非 JSON 响应 */ }

  if (!res.ok) {
    if (res.status >= 500 || res.status === 503) showServiceBanner();
    if (res.status === 401 && !path.startsWith('/api/auth/')) {
      setUser(null);
      if (!location.hash.startsWith('#/login') && !location.hash.startsWith('#/register')) {
        location.hash = '#/login';
      }
    }
    throw new ApiError(res.status, (data && data.error) || '请求失败，请稍后再试');
  }

  hideServiceBanner();
  return data;
}

// ---------- 会话 ----------
export async function loadMe() {
  try {
    const data = await api('/api/auth/me');
    setUser(data.user);
    return data.user;
  } catch (e) {
    setUser(null);
    return null;
  }
}

export async function logout() {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) { /* 忽略 */ }
  setUser(null);
  location.hash = '#/login';
}
