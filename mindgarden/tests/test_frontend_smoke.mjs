// test_frontend_smoke.mjs —— 前端无头冒烟测试
// 用最小 DOM 桩加载真实的前端模块（api.js / ui.js / pages.js / app.js），
// 配合真实的后端服务器，验证：模块可导入、路由可渲染、各页面关键内容出现、
// 未登录跳转登录页。运行：node tests/test_frontend_smoke.mjs
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const PORT = 18098;
const BASE = `http://127.0.0.1:${PORT}`;

let passed = 0, failed = 0;
const failures = [];
function check(name, cond, detail = '') {
  if (cond) { passed++; console.log('  ✓ ' + name); }
  else { failed++; failures.push(name); console.log('  ✗ ' + name + '  ' + detail); }
}

// ---------------- 最小浏览器环境桩 ----------------
const elements = new Map();
function makeEl(id = '') {
  const el = {
    id,
    _html: '',
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    dataset: {},
    style: {},
    value: '',
    textContent: '',
    disabled: false,
    addEventListener() {},
    removeEventListener() {},
    appendChild() {},
    remove() {},
    scrollIntoView() {},
    closest: () => null,
    querySelector: () => makeEl(),
    querySelectorAll: () => [],
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
  };
  return el;
}
function getEl(id) {
  if (!elements.has(id)) elements.set(id, makeEl(id));
  return elements.get(id);
}

const hashchangeHandlers = [];
const cookies = new Map();

globalThis.document = {
  getElementById: getEl,
  createElement: () => makeEl(),
  addEventListener() {},
  querySelectorAll: () => [],
  documentElement: { dataset: {} },
};
globalThis.window = {
  addEventListener: (ev, fn) => { if (ev === 'hashchange') hashchangeHandlers.push(fn); },
  scrollTo() {},
};
globalThis.location = { hash: '' };
globalThis.sessionStorage = {
  _m: new Map(),
  getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
  setItem(k, v) { this._m.set(k, String(v)); },
  removeItem(k) { this._m.delete(k); },
};
globalThis.confirm = () => true;

const realFetch = globalThis.fetch;
globalThis.fetch = async (url, opts = {}) => {
  const full = String(url).startsWith('http') ? url : BASE + url;
  const headers = { ...(opts.headers || {}) };
  if (cookies.size) {
    headers.Cookie = [...cookies.entries()].map(([k, v]) => `${k}=${v}`).join('; ');
  }
  const res = await realFetch(full, { ...opts, headers });
  const setCookie = res.headers.get('set-cookie');
  if (setCookie) {
    for (const part of setCookie.split(/,(?=\s*\w+=)/)) {
      const pair = part.split(';')[0];
      const idx = pair.indexOf('=');
      const k = pair.slice(0, idx).trim();
      const v = pair.slice(idx + 1).trim();
      if (v) cookies.set(k, v); else cookies.delete(k);
    }
  }
  return res;
};

// ---------------- 启动后端 ----------------
const tmp = mkdtempSync(path.join(tmpdir(), 'mg_fe_'));
const server = spawn('python3', [path.join(ROOT, 'server.py')], {
  env: { ...process.env, DB_PATH: path.join(tmp, 'fe.db'), PORT: String(PORT) },
  stdio: 'ignore',
});

async function waitServer() {
  for (let i = 0; i < 50; i++) {
    try {
      const r = await realFetch(BASE + '/api/health');
      if (r.ok) return;
    } catch (e) { /* 还没起来 */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error('后端启动超时');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const appEl = () => getEl('app');

async function main() {
  await waitServer();

  console.log('\n[1] 模块加载与首屏（未登录 → 登录页）');
  const api = await import('../public/js/api.js');
  await import('../public/js/app.js'); // boot() 自动执行
  await sleep(300);
  check('未登录自动跳到 #/login', location.hash === '#/login', location.hash);
  check('登录页渲染', appEl().innerHTML.includes('欢迎回到心晴花园'));

  console.log('\n[2] 注册后进入花园');
  const reg = await api.api('/api/auth/register', {
    method: 'POST',
    body: { username: 'fe_user', email: 'fe@test.com', password: 'password123' },
  });
  api.setUser(reg.user);
  check('注册接口返回用户', reg.user.username === 'fe_user');
  await api.api('/api/moods', { method: 'POST', body: { level: 5, note: '冒烟测试' } });
  location.hash = '#/garden';
  for (const fn of hashchangeHandlers) fn();
  await sleep(400);
  check('花园页渲染：本周曲线', appEl().innerHTML.includes('本周情绪曲线'));
  check('花园页渲染：花园区域', appEl().innerHTML.includes('我的心情花园'));
  check('刚种的花出现在花园里', appEl().innerHTML.includes('🌻'));

  console.log('\n[3] 其余页面渲染');
  const routes = [
    ['#/moods', ['记一笔心情', '按日查看']],
    ['#/assessments', ['焦虑情绪自评', '开始测评']],
    ['#/assessments/1', ['提交并查看结果']],
    ['#/diary', ['写新日记', '时间轴']],
    ['#/profile', ['编辑资料', '我的测评报告']],
  ];
  for (const [hash, markers] of routes) {
    location.hash = hash;
    for (const fn of hashchangeHandlers) fn();
    await sleep(400);
    for (const m of markers) {
      check(`${hash} 包含「${m}」`, appEl().innerHTML.includes(m));
    }
  }

  console.log('\n[4] 登出后私人页面回到登录页');
  await api.logout();
  location.hash = '#/moods';
  for (const fn of hashchangeHandlers) fn();
  await sleep(300);
  check('登出后访问 #/moods 被送回登录页', location.hash === '#/login', location.hash);
  // 真实浏览器里 hash 变化会再次触发 hashchange → 渲染登录页；这里手动补一次
  for (const fn of hashchangeHandlers) fn();
  await sleep(300);
  check('登录页重新渲染', appEl().innerHTML.includes('欢迎回到心晴花园'));

  console.log(`\n结果：${passed} 通过，${failed} 失败`);
  if (failures.length) console.log('失败用例：\n' + failures.map((f) => '  - ' + f).join('\n'));
  return failed === 0 ? 0 : 1;
}

let code = 1;
try {
  code = await main();
} catch (e) {
  console.error('冒烟测试异常：', e);
} finally {
  server.kill();
}
process.exit(code);
