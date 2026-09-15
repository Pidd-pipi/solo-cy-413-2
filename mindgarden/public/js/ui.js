// ui.js —— 共享 UI 组件与工具
// 心情等级（1-5）在这里只定义一次：心情花园、情绪记录、日记时间轴、周曲线全部共用，
// 与后端 app/db.py 的 MOOD_LEVELS 一一对应，保证「同一套等级」口径。

export const MOOD_LEVELS = [
  { level: 1, label: '很低落', emoji: '😞', flower: '🥀', color: '#8d99ae' },
  { level: 2, label: '低落',   emoji: '😟', flower: '🌱', color: '#6fa8dc' },
  { level: 3, label: '平静',   emoji: '😐', flower: '🌿', color: '#66bb8a' },
  { level: 4, label: '不错',   emoji: '🙂', flower: '🌷', color: '#f2b84b' },
  { level: 5, label: '很好',   emoji: '😄', flower: '🌻', color: '#ef8354' },
];

export function moodInfo(level) {
  return MOOD_LEVELS.find((m) => m.level === Number(level)) || MOOD_LEVELS[2];
}

// ---------- 基础工具 ----------
export function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function toast(message, type = 'info') {
  const root = document.getElementById('toast-root');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

export function emptyState(icon, title, hint) {
  return `<div class="empty-state">
    <div class="icon">${icon}</div>
    <div class="title">${esc(title)}</div>
    ${hint ? `<div class="hint">${esc(hint)}</div>` : ''}
  </div>`;
}

export function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function fmtDateTime(s) {
  return s ? s.slice(0, 16) : '';
}

export function fmtDate(s) {
  return s ? s.slice(0, 10) : '';
}

// ---------- 心情选择器（花园快速记录 / 情绪记录 / 日记编辑器共用） ----------
export function moodSelectorHTML(selected = null, name = 'mood') {
  const opts = MOOD_LEVELS.map((m) => `
    <button type="button" class="mood-option ${selected === m.level ? 'selected' : ''}"
            data-level="${m.level}" title="${esc(m.label)}">
      <span class="emo">${m.emoji}</span>
      <span class="lab">${esc(m.label)}</span>
    </button>`).join('');
  return `<div class="mood-selector" data-name="${esc(name)}">${opts}</div>`;
}

// 事件委托：点击任意 .mood-option 时切换选中态（同一容器内单选）
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.mood-option');
  if (!btn) return;
  const box = btn.closest('.mood-selector');
  if (!box) return;
  box.querySelectorAll('.mood-option').forEach((b) => b.classList.remove('selected'));
  btn.classList.add('selected');
});

export function readMoodSelector(container) {
  const sel = container.querySelector('.mood-selector .mood-option.selected');
  return sel ? Number(sel.dataset.level) : null;
}

// ---------- 心情等级筛选 chips（日记时间轴 / 列表筛选共用） ----------
export function moodChipsHTML(active = '') {
  const all = [`<button type="button" class="chip ${active === '' ? 'active' : ''}" data-mood="">全部</button>`];
  for (const m of MOOD_LEVELS) {
    all.push(`<button type="button" class="chip ${String(m.level) === String(active) ? 'active' : ''}"
      data-mood="${m.level}">${m.emoji} ${esc(m.label)}</button>`);
  }
  return `<div class="mood-chips">${all.join('')}</div>`;
}

// ---------- 本周情绪曲线（SVG，花园页与情绪记录页共用） ----------
export function weekChartSVG(days) {
  const W = 640, H = 210, PAD_L = 40, PAD_R = 16, PAD_T = 18, PAD_B = 34;
  const innerW = W - PAD_L - PAD_R, innerH = H - PAD_T - PAD_B;
  const xOf = (i) => PAD_L + (innerW / 6) * i;
  const yOf = (v) => PAD_T + innerH - ((v - 1) / 4) * innerH;

  let svg = `<svg viewBox="0 0 ${W} ${H}" class="week-chart" role="img" aria-label="本周情绪曲线">`;

  // 横向网格线 + 等级 emoji 刻度
  MOOD_LEVELS.forEach((m) => {
    const y = yOf(m.level);
    svg += `<line x1="${PAD_L}" y1="${y}" x2="${W - PAD_R}" y2="${y}" stroke="#e2eae4" stroke-width="1"/>`;
    svg += `<text x="${PAD_L - 8}" y="${y + 5}" text-anchor="end" font-size="13">${m.emoji}</text>`;
  });

  // 折线：只连接相邻且都有数据的点
  const pts = days.map((d, i) => (d.avg == null ? null : { x: xOf(i), y: yOf(d.avg), d, i }));
  for (let i = 0; i < pts.length - 1; i++) {
    if (pts[i] && pts[i + 1]) {
      svg += `<line x1="${pts[i].x}" y1="${pts[i].y}" x2="${pts[i + 1].x}" y2="${pts[i + 1].y}"
        stroke="#3d8b5f" stroke-width="2.5" stroke-linecap="round"/>`;
    }
  }

  // 数据点 + 日期标签
  const weekNames = ['日', '一', '二', '三', '四', '五', '六'];
  days.forEach((d, i) => {
    const x = xOf(i);
    const date = new Date(d.date + 'T00:00:00');
    const label = `周${weekNames[date.getDay()]}`;
    svg += `<text x="${x}" y="${H - 12}" text-anchor="middle" font-size="12" fill="#6b7a72">${label}</text>`;
    svg += `<text x="${x}" y="${H - 0}" text-anchor="middle" font-size="10" fill="#9aa8a0">${d.date.slice(5)}</text>`;
    if (d.avg != null) {
      const info = moodInfo(Math.round(d.avg));
      svg += `<circle cx="${x}" cy="${yOf(d.avg)}" r="6" fill="${info.color}" stroke="#fff" stroke-width="2">
        <title>${d.date} 平均心情 ${d.avg}（${d.count} 条记录）</title></circle>`;
      svg += `<text x="${x}" y="${yOf(d.avg) - 12}" text-anchor="middle" font-size="11" fill="#2e3a34">${d.avg}</text>`;
    }
  });

  svg += '</svg>';
  return svg;
}

// ---------- 头像选择 ----------
export const AVATARS = ['🌱', '🌿', '🌻', '🌷', '🍀', '🌵', '🌙', '⭐', '🐱', '🦊', '🐼', '🐳', '🌳'];

export function avatarPickerHTML(selected) {
  return `<div class="avatar-grid">${AVATARS.map((a) => `
    <button type="button" class="avatar-choice ${a === selected ? 'selected' : ''}" data-avatar="${a}">${a}</button>`).join('')}</div>`;
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('.avatar-choice');
  if (!btn) return;
  const grid = btn.closest('.avatar-grid');
  grid.querySelectorAll('.avatar-choice').forEach((b) => b.classList.remove('selected'));
  btn.classList.add('selected');
});

// ---------- 页面骨架 ----------
export function pageHeader(title, sub) {
  return `<h1 class="page-title">${esc(title)}</h1>${sub ? `<p class="page-sub">${esc(sub)}</p>` : ''}`;
}

export function showPageError(container, err) {
  container.innerHTML = emptyState('😔', '加载失败', err.message || '请稍后重试');
}
