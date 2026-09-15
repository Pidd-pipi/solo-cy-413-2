// app.js —— 路由、导航栏、启动引导
// 页面状态可回读：hash 路由刷新后仍在原页；会话 Cookie 刷新后仍保持登录；
// 数据一律从服务端重新拉取，不存在「刷新丢状态」。
import { loadMe, getUser, onUserChange, hideServiceBanner } from './api.js';
import {
  renderLogin, renderRegister, renderGarden, renderMoods,
  renderAssessments, renderAssessmentTake, renderDiary, renderProfile,
} from './pages.js';
import { esc } from './ui.js';

const app = document.getElementById('app');
const navbar = document.getElementById('navbar');

const ROUTES = [
  { pattern: /^#\/login$/, render: renderLogin, auth: false, name: 'login' },
  { pattern: /^#\/register$/, render: renderRegister, auth: false, name: 'register' },
  { pattern: /^#\/garden$/, render: renderGarden, auth: true, name: 'garden' },
  { pattern: /^#\/moods$/, render: renderMoods, auth: true, name: 'moods' },
  { pattern: /^#\/assessments$/, render: renderAssessments, auth: true, name: 'assessments' },
  { pattern: /^#\/assessments\/(\d+)$/, render: renderAssessmentTake, auth: true, name: 'assessments' },
  { pattern: /^#\/diary$/, render: renderDiary, auth: true, name: 'diary' },
  { pattern: /^#\/profile$/, render: renderProfile, auth: true, name: 'profile' },
];

const GUEST_ROUTES = ['login', 'register'];

function currentHash() {
  return location.hash || '#/garden';
}

function route() {
  const hash = currentHash();
  const user = getUser();
  const matched = ROUTES.find((r) => r.pattern.test(hash)) || ROUTES.find((r) => r.name === 'garden');
  const params = hash.match(matched.pattern);

  // 路由守卫：未登录只能访问登录/注册页；已登录访问登录页则送回花园
  if (matched.auth && !user) {
    sessionStorage.setItem('mg_last_route', hash);
    location.hash = '#/login';
    return;
  }
  if (!matched.auth && user && GUEST_ROUTES.includes(matched.name)) {
    location.hash = '#/garden';
    return;
  }

  // 记住当前页面，刷新/重开可回读
  if (matched.auth) sessionStorage.setItem('mg_last_route', hash);

  renderNav(matched.name);
  window.scrollTo(0, 0);
  const args = params ? params.slice(1) : [];
  Promise.resolve(matched.render(app, ...args)).catch((err) => {
    console.error(err);
    app.innerHTML = `<div class="empty-state"><div class="icon">😔</div>
      <div class="title">页面出错了</div><div class="hint">${esc(err.message || '请刷新重试')}</div></div>`;
  });
}

function renderNav(activeName) {
  const user = getUser();
  if (!user) {
    navbar.classList.add('hidden');
    return;
  }
  navbar.classList.remove('hidden');
  navbar.querySelectorAll('.nav-links a').forEach((a) => {
    a.classList.toggle('active', a.dataset.route === activeName);
  });
  const userBox = document.getElementById('nav-user');
  userBox.innerHTML = `
    <span class="avatar">${esc(user.avatarEmoji)}</span>
    <span class="uname">${esc(user.displayName)}${user.role === 'admin' ? '（管理员）' : ''}</span>`;
}

async function boot() {
  // 服务不可用横幅的「重试」按钮：重新拉取当前页面
  document.getElementById('service-retry').addEventListener('click', () => {
    hideServiceBanner();
    route();
  });

  await loadMe();

  // 无 hash 时恢复上次所在页面（页面状态回读）
  if (!location.hash) {
    const last = sessionStorage.getItem('mg_last_route');
    location.hash = getUser() ? (last || '#/garden') : '#/login';
  }

  window.addEventListener('hashchange', route);
  onUserChange(() => renderNav(''));
  route();
}

boot();
