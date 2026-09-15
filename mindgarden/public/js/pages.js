// pages.js —— 六个主流程页面的渲染与交互
import { api, ApiError, getUser, isAdmin, setUser, logout } from './api.js';
import {
  MOOD_LEVELS, moodInfo, esc, toast, emptyState, todayStr, fmtDateTime, fmtDate,
  moodSelectorHTML, readMoodSelector, moodChipsHTML, weekChartSVG,
  avatarPickerHTML, pageHeader, showPageError,
} from './ui.js';

// ============================================================ 登录 / 注册

export function renderLogin(el) {
  el.innerHTML = `
    <div class="auth-wrap"><div class="auth-card">
      <div class="auth-logo">🌻</div>
      <div class="auth-title">欢迎回到心晴花园</div>
      <div class="auth-sub">登录后继续浇灌你的心情花园</div>
      <div class="form-error hidden" id="login-err"></div>
      <form id="login-form" novalidate>
        <label class="field"><span>用户名</span>
          <input type="text" id="login-username" autocomplete="username" placeholder="请输入用户名"></label>
        <label class="field"><span>密码</span>
          <input type="password" id="login-password" autocomplete="current-password" placeholder="请输入密码"></label>
        <button class="btn btn-primary btn-block" type="submit">登 录</button>
      </form>
      <div class="auth-switch">还没有账号？<a href="#/register">立即注册</a></div>
    </div></div>`;

  el.querySelector('#login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errBox = el.querySelector('#login-err');
    const show = (m) => { errBox.textContent = m; errBox.classList.remove('hidden'); };
    errBox.classList.add('hidden');
    const username = el.querySelector('#login-username').value.trim();
    const password = el.querySelector('#login-password').value;
    if (!username) return show('请输入用户名');
    if (!password) return show('请输入密码');
    const btn = el.querySelector('button[type=submit]');
    btn.disabled = true; btn.textContent = '登录中…';
    try {
      const data = await api('/api/auth/login', { method: 'POST', body: { username, password } });
      setUser(data.user);
      toast(`欢迎回来，${data.user.displayName}`, 'success');
      location.hash = '#/garden';
    } catch (err) {
      show(err.message);
      btn.disabled = false; btn.textContent = '登 录';
    }
  });
}

export function renderRegister(el) {
  el.innerHTML = `
    <div class="auth-wrap"><div class="auth-card">
      <div class="auth-logo">🌱</div>
      <div class="auth-title">种下你的第一颗种子</div>
      <div class="auth-sub">注册即可拥有私密的心情花园与日记本</div>
      <div class="form-error hidden" id="reg-err"></div>
      <form id="reg-form" novalidate>
        <label class="field"><span>用户名（2-20 个字符）</span>
          <input type="text" id="reg-username" autocomplete="username" placeholder="用于登录，中英文均可"></label>
        <label class="field"><span>邮箱</span>
          <input type="email" id="reg-email" autocomplete="email" placeholder="you@example.com"></label>
        <label class="field"><span>昵称（可选）</span>
          <input type="text" id="reg-display" placeholder="花园里怎么称呼你？"></label>
        <label class="field"><span>密码（至少 8 位）</span>
          <input type="password" id="reg-password" autocomplete="new-password" placeholder="至少 8 个字符"></label>
        <label class="field"><span>确认密码</span>
          <input type="password" id="reg-password2" autocomplete="new-password" placeholder="再输入一次"></label>
        <button class="btn btn-primary btn-block" type="submit">注 册</button>
      </form>
      <div class="auth-switch">已有账号？<a href="#/login">直接登录</a></div>
    </div></div>`;

  el.querySelector('#reg-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errBox = el.querySelector('#reg-err');
    const show = (m) => { errBox.textContent = m; errBox.classList.remove('hidden'); };
    errBox.classList.add('hidden');
    const username = el.querySelector('#reg-username').value.trim();
    const email = el.querySelector('#reg-email').value.trim();
    const displayName = el.querySelector('#reg-display').value.trim();
    const password = el.querySelector('#reg-password').value;
    const password2 = el.querySelector('#reg-password2').value;
    if (username.length < 2) return show('用户名至少需要 2 个字符');
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return show('请输入正确的邮箱地址');
    if (password.length < 8) return show('密码至少需要 8 个字符');
    if (password !== password2) return show('两次输入的密码不一致');
    const btn = el.querySelector('button[type=submit]');
    btn.disabled = true; btn.textContent = '注册中…';
    try {
      const data = await api('/api/auth/register', {
        method: 'POST',
        body: { username, email, password, displayName: displayName || undefined },
      });
      setUser(data.user);
      toast('注册成功，开始记录今天的心情吧 🌱', 'success');
      location.hash = '#/garden';
    } catch (err) {
      show(err.message);
      btn.disabled = false; btn.textContent = '注 册';
    }
  });
}

// ============================================================ 心情花园（首页）

export async function renderGarden(el) {
  const user = getUser();
  el.innerHTML = pageHeader(`${greeting()}，${user.displayName}`,
    `${todayCN()} · 每一天的心情都会在这里开成一朵花`) + '<div class="loading-page">🌷 花园加载中…</div>';

  let garden, week;
  try {
    [garden, week] = await Promise.all([api('/api/garden'), api('/api/moods/week')]);
  } catch (err) {
    showPageError(el, err);
    return;
  }

  const weekAvgText = week.weekAvg != null
    ? `${moodInfo(Math.round(week.weekAvg)).emoji} ${week.weekAvg}` : '—';

  el.innerHTML = pageHeader(`${greeting()}，${user.displayName}`,
    `${todayCN()} · 每一天的心情都会在这里开成一朵花`) + `
    <div class="stats-row">
      <div class="stat-card"><div class="num">${garden.stats.streak}</div><div class="lab">连续记录（天）</div></div>
      <div class="stat-card"><div class="num">${garden.stats.total}</div><div class="lab">累计心情记录</div></div>
      <div class="stat-card"><div class="num">${weekAvgText}</div><div class="lab">本周平均心情</div></div>
    </div>

    <div class="card">
      <h3>📝 现在感觉怎么样？</h3>
      <div id="quick-mood">${moodSelectorHTML()}</div>
      <div style="margin-top:12px">
        <input type="text" id="quick-note" maxlength="500" placeholder="想记点什么吗？（可选，500 字以内）">
      </div>
      <div style="margin-top:12px; display:flex; gap:10px; align-items:center">
        <button class="btn btn-primary" id="quick-save">种下这朵心情</button>
        <span class="hint">记录后会同步进入本周曲线与情绪记录</span>
      </div>
    </div>

    <div class="card">
      <h3>📈 本周情绪曲线 <span class="week-avg-tag" style="margin-left:auto">周平均 <b>${weekAvgText}</b></span></h3>
      ${week.days.some((d) => d.avg != null)
        ? weekChartSVG(week.days)
        : emptyState('📭', '本周还没有情绪记录', '在上方记录第一条心情，曲线就会长出来')}
    </div>

    <div class="card">
      <h3>🌷 我的心情花园 <span class="hint" style="font-weight:400">（最近 30 天，每朵花对应一条记录）</span></h3>
      ${garden.flowers.length
        ? `<div class="garden-bed">${garden.flowers.map((f) => `
            <div class="flower">${f.flower}
              <span class="tip">${esc(f.date)} · ${esc(f.label)}${f.note ? '\n' + esc(f.note) : ''}</span>
            </div>`).join('')}</div>`
        : emptyState('🌱', '花园还是空的', '记录第一条心情，这里就会开出第一朵花')}
    </div>`;

  el.querySelector('#quick-save').addEventListener('click', async () => {
    const level = readMoodSelector(el.querySelector('#quick-mood'));
    if (!level) return toast('先选一个心情等级吧', 'error');
    const note = el.querySelector('#quick-note').value.trim();
    const btn = el.querySelector('#quick-save');
    btn.disabled = true;
    try {
      await api('/api/moods', { method: 'POST', body: { level, note } });
      toast('已种下今天的心情 ' + moodInfo(level).flower, 'success');
      renderGarden(el);
    } catch (err) {
      toast(err.message, 'error');
      btn.disabled = false;
    }
  });
}

function greeting() {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 11) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

function todayCN() {
  const weekNames = ['日', '一', '二', '三', '四', '五', '六'];
  const d = new Date();
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日 · 周${weekNames[d.getDay()]}`;
}

// ============================================================ 情绪记录

export async function renderMoods(el) {
  el.innerHTML = pageHeader('情绪记录', '记录当下的心情，按日期回看，本周曲线一目了然')
    + '<div class="loading-page">加载中…</div>';

  let week;
  try {
    week = await api('/api/moods/week');
  } catch (err) {
    showPageError(el, err);
    return;
  }

  el.innerHTML = pageHeader('情绪记录', '记录当下的心情，按日期回看，本周曲线一目了然') + `
    <div class="grid-2">
      <div class="card">
        <h3>✏️ 记一笔心情</h3>
        <label class="field"><span>日期（默认为今天）</span>
          <input type="date" id="mood-date" value="${todayStr()}" max="${todayStr()}"></label>
        <div id="mood-form-selector">${moodSelectorHTML()}</div>
        <div style="margin-top:12px">
          <textarea id="mood-note" rows="2" maxlength="500" placeholder="这一刻在想什么？（可选）"></textarea>
        </div>
        <button class="btn btn-primary" id="mood-save" style="margin-top:12px">保存记录</button>
      </div>
      <div class="card">
        <h3>📈 本周情绪曲线</h3>
        ${week.days.some((d) => d.avg != null)
          ? weekChartSVG(week.days)
          : emptyState('📭', '本周还没有记录', '先在左侧记一笔心情吧')}
      </div>
    </div>

    <div class="card">
      <h3>🗓️ 按日查看
        <input type="date" id="filter-date" value="${todayStr()}" max="${todayStr()}"
               style="width:auto; margin-left:12px; padding:4px 10px; font-size:13.5px">
      </h3>
      <div id="day-list"><div class="loading-page">加载中…</div></div>
    </div>`;

  async function loadDay(dateStr) {
    const box = el.querySelector('#day-list');
    box.innerHTML = '<div class="loading-page">加载中…</div>';
    try {
      const data = await api(`/api/moods?date=${encodeURIComponent(dateStr)}`);
      renderDayList(data.moods, dateStr);
    } catch (err) {
      box.innerHTML = emptyState('😔', '加载失败', err.message);
    }
  }

  function renderDayList(moods, dateStr) {
    const box = el.querySelector('#day-list');
    if (!moods.length) {
      box.innerHTML = emptyState('🍃', `${dateStr} 这一天还没有记录`, '换个日期看看，或在上方补记一笔');
      return;
    }
    box.innerHTML = moods.map((m) => {
      const info = moodInfo(m.level);
      return `<div class="mood-item">
        <div class="emo">${info.emoji}</div>
        <div class="item-main">
          <div><b>${esc(info.label)}</b>（${m.level} 级）${m.note ? ' · ' + esc(m.note) : ''}</div>
          <div class="item-meta">记录于 ${esc(fmtDateTime(m.createdAt))}</div>
        </div>
        <div class="item-actions">
          <button class="btn btn-danger-ghost btn-sm" data-del-mood="${m.id}">删除</button>
        </div>
      </div>`;
    }).join('');
  }

  el.querySelector('#filter-date').addEventListener('change', (e) => loadDay(e.target.value));

  el.querySelector('#mood-save').addEventListener('click', async () => {
    const level = readMoodSelector(el.querySelector('#mood-form-selector'));
    if (!level) return toast('先选一个心情等级吧', 'error');
    const date = el.querySelector('#mood-date').value;
    const note = el.querySelector('#mood-note').value.trim();
    const btn = el.querySelector('#mood-save');
    btn.disabled = true;
    try {
      await api('/api/moods', { method: 'POST', body: { level, note, date } });
      toast('心情已保存', 'success');
      renderMoods(el); // 重新拉取周曲线与当日列表，保证两处数据一致
    } catch (err) {
      toast(err.message, 'error');
      btn.disabled = false;
    }
  });

  el.querySelector('#day-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-del-mood]');
    if (!btn) return;
    if (!confirm('确定删除这条情绪记录吗？')) return;
    try {
      await api(`/api/moods/${btn.dataset.delMood}`, { method: 'DELETE' });
      toast('已删除', 'success');
      renderMoods(el);
    } catch (err) {
      toast(err.message, 'error');
    }
  });

  loadDay(todayStr());
}

// ============================================================ 心理测评

export async function renderAssessments(el) {
  el.innerHTML = pageHeader('心理测评', '选择一份测评，更好地了解自己（结果仅自己可见）')
    + '<div class="loading-page">加载中…</div>';
  let data;
  try {
    data = await api('/api/assessments');
  } catch (err) {
    showPageError(el, err);
    return;
  }

  const adminBtn = isAdmin()
    ? '<button class="btn btn-ghost btn-sm" id="toggle-admin">＋ 新建测评</button>' : '';

  el.innerHTML = pageHeader('心理测评', '选择一份测评，更好地了解自己（结果仅自己可见）') + `
    ${adminBtn ? `<div class="card" id="admin-panel-wrap">
      <div style="display:flex; justify-content:space-between; align-items:center">
        <h3 style="margin:0">🛠️ 管理员</h3>${adminBtn}
      </div>
      <div id="admin-panel" class="hidden" style="margin-top:16px"></div>
    </div>` : ''}
    ${data.assessments.length
      ? `<div class="assess-grid">${data.assessments.map((a) => `
          <div class="assess-card">
            <span class="tag">${esc(a.categoryLabel)}</span>
            <h3 style="margin:0">${esc(a.title)}</h3>
            <div class="desc">${esc(a.description)}</div>
            <div class="meta">共 ${a.questionCount} 题
              ${a.myAttempts ? ` · 我已完成 ${a.myAttempts} 次` : ' · 尚未完成'}</div>
            <a class="btn btn-primary" href="#/assessments/${a.id}" style="text-decoration:none">开始测评</a>
          </div>`).join('')}</div>`
      : `<div class="card">${emptyState('📋', '暂时没有可用的测评', '请等待管理员发布新的测评')}</div>`}`;

  if (isAdmin()) {
    el.querySelector('#toggle-admin').addEventListener('click', () => {
      const panel = el.querySelector('#admin-panel');
      panel.classList.toggle('hidden');
      if (!panel.dataset.ready) {
        panel.dataset.ready = '1';
        renderAdminForm(panel, el);
      }
    });
  }
}

// ---------- 管理员：创建测评 ----------
function renderAdminForm(panel, pageEl) {
  panel.innerHTML = `
    <div class="form-error hidden" id="admin-err"></div>
    <div class="grid-2">
      <label class="field"><span>测评标题 *</span><input type="text" id="a-title" maxlength="80" placeholder="例如：情绪状态自评"></label>
      <label class="field"><span>分类 *</span>
        <select id="a-category">
          <option value="anxiety">焦虑</option><option value="depression">抑郁</option>
          <option value="stress">压力</option><option value="sleep">睡眠</option>
          <option value="general" selected>综合</option>
        </select></label>
    </div>
    <label class="field"><span>测评简介</span><textarea id="a-desc" rows="2" maxlength="500" placeholder="告诉参与者这份测评是做什么的"></textarea></label>

    <h3>题目（每题 2-6 个选项，选项分值 0-20）</h3>
    <div id="a-questions"></div>
    <button class="btn btn-ghost btn-sm" id="a-add-q">＋ 添加题目</button>

    <h3 style="margin-top:18px">结果区间（按总分给出结论与建议）</h3>
    <div id="a-bands"></div>
    <button class="btn btn-ghost btn-sm" id="a-add-band">＋ 添加区间</button>

    <div style="margin-top:18px">
      <button class="btn btn-primary" id="a-submit">发布测评</button>
    </div>`;

  const qsBox = panel.querySelector('#a-questions');
  const bandsBox = panel.querySelector('#a-bands');

  function addQuestion() {
    const div = document.createElement('div');
    div.className = 'admin-question';
    div.innerHTML = `
      <div style="display:flex; gap:8px; align-items:center; margin-bottom:8px">
        <input type="text" class="q-text" maxlength="200" placeholder="题干，例如：我感到紧张或心烦" style="flex:1">
        <button type="button" class="icon-btn q-del" title="删除题目">✕</button>
      </div>
      ${[0, 1, 2, 3].map((i) => `
        <div class="admin-option-row">
          <input type="text" class="opt-label" maxlength="60" placeholder="选项 ${i + 1} 文字">
          <input type="number" class="opt-score" min="0" max="20" value="${i}" title="分值">
        </div>`).join('')}`;
    qsBox.appendChild(div);
  }

  function addBand() {
    const div = document.createElement('div');
    div.className = 'admin-band-row';
    div.innerHTML = `
      <input type="number" class="b-min" min="0" max="1000" placeholder="下限">
      <input type="number" class="b-max" min="0" max="1000" placeholder="上限">
      <input type="text" class="b-label" maxlength="30" placeholder="结论，如：状态良好">
      <input type="text" class="b-advice" maxlength="300" placeholder="给参与者的建议">
      <button type="button" class="icon-btn b-del" title="删除区间">✕</button>`;
    bandsBox.appendChild(div);
  }

  panel.querySelector('#a-add-q').addEventListener('click', addQuestion);
  panel.querySelector('#a-add-band').addEventListener('click', addBand);
  panel.addEventListener('click', (e) => {
    if (e.target.closest('.q-del')) e.target.closest('.admin-question').remove();
    if (e.target.closest('.b-del')) e.target.closest('.admin-band-row').remove();
  });

  addQuestion(); addQuestion(); addQuestion();
  addBand(); addBand();

  panel.querySelector('#a-submit').addEventListener('click', async () => {
    const errBox = panel.querySelector('#admin-err');
    const show = (m) => { errBox.textContent = m; errBox.classList.remove('hidden'); };
    errBox.classList.add('hidden');

    const questions = [...qsBox.querySelectorAll('.admin-question')].map((q) => ({
      text: q.querySelector('.q-text').value.trim(),
      options: [...q.querySelectorAll('.admin-option-row')].map((r) => ({
        label: r.querySelector('.opt-label').value.trim(),
        score: Number(r.querySelector('.opt-score').value),
      })),
    }));
    const bands = [...bandsBox.querySelectorAll('.admin-band-row')].map((b) => ({
      min: Number(b.querySelector('.b-min').value),
      max: Number(b.querySelector('.b-max').value),
      label: b.querySelector('.b-label').value.trim(),
      advice: b.querySelector('.b-advice').value.trim(),
    }));
    const payload = {
      title: panel.querySelector('#a-title').value.trim(),
      description: panel.querySelector('#a-desc').value.trim(),
      category: panel.querySelector('#a-category').value,
      questions, bands,
    };
    if (!payload.title) return show('请填写测评标题');
    if (!questions.length || questions.some((q) => !q.text)) return show('每道题都要填写题干');
    if (questions.some((q) => q.options.some((o) => !o.label))) return show('每个选项都要填写文字');
    if (!bands.length || bands.some((b) => !b.label)) return show('每个结果区间都要填写结论名称');

    const btn = panel.querySelector('#a-submit');
    btn.disabled = true;
    try {
      await api('/api/assessments', { method: 'POST', body: payload });
      toast('测评已发布', 'success');
      renderAssessments(pageEl);
    } catch (err) {
      show(err.message);
      btn.disabled = false;
    }
  });
}

// ---------- 答题页 ----------
export async function renderAssessmentTake(el, id) {
  el.innerHTML = '<div class="loading-page">加载测评中…</div>';
  let data;
  try {
    data = await api(`/api/assessments/${id}`);
  } catch (err) {
    showPageError(el, err);
    return;
  }
  const a = data.assessment;

  el.innerHTML = `
    <a href="#/assessments" style="color:var(--green); text-decoration:none">← 返回测评列表</a>
    <div class="card" style="margin-top:14px">
      <span class="tag">${esc(a.categoryLabel)}</span>
      <h2 style="margin:8px 0 4px">${esc(a.title)}</h2>
      <p class="page-sub">${esc(a.description)}</p>
      <div class="form-error hidden" id="take-err"></div>
      ${a.questions.map((q, i) => `
        <div class="question-block" data-q="${i}">
          <div class="question-text">${i + 1}. ${esc(q.text)}</div>
          ${q.options.map((o, j) => `
            <label class="option-row" data-opt>
              <input type="radio" name="q${i}" value="${j}">
              <span>${esc(o.label)}</span>
            </label>`).join('')}
        </div>`).join('')}
      <button class="btn btn-primary btn-block" id="take-submit" style="margin-top:16px">提交并查看结果</button>
    </div>`;

  // 选中高亮（监听挂在卡片上，随页面重渲染自动销毁，不会累积）
  el.querySelector('.card').addEventListener('change', (e) => {
    const row = e.target.closest('[data-opt]');
    if (!row) return;
    row.closest('.question-block').querySelectorAll('[data-opt]')
      .forEach((r) => r.classList.remove('selected'));
    row.classList.add('selected');
  });

  el.querySelector('#take-submit').addEventListener('click', async () => {
    const errBox = el.querySelector('#take-err');
    errBox.classList.add('hidden');
    const answers = [];
    let missing = -1;
    a.questions.forEach((q, i) => {
      const checked = el.querySelector(`input[name="q${i}"]:checked`);
      answers.push(checked ? Number(checked.value) : -1);
      if (!checked && missing === -1) missing = i + 1;
    });
    if (missing !== -1) {
      errBox.textContent = `第 ${missing} 题还没有作答，请完成全部题目`;
      errBox.classList.remove('hidden');
      return;
    }
    const btn = el.querySelector('#take-submit');
    btn.disabled = true; btn.textContent = '正在生成报告…';
    try {
      const result = await api(`/api/assessments/${id}/submit`, {
        method: 'POST', body: { answers },
      });
      renderAssessmentResult(el, result.report, a.title);
    } catch (err) {
      errBox.textContent = err.message;
      errBox.classList.remove('hidden');
      btn.disabled = false; btn.textContent = '提交并查看结果';
    }
  });
}

function renderAssessmentResult(el, report, title) {
  el.innerHTML = `
    <div class="card">
      <div class="result-hero">
        <div style="font-size:15px; color:var(--ink-soft)">${esc(title)} · 测评完成</div>
        <div class="result-score">${report.score}<span style="font-size:16px; color:var(--ink-soft)"> 分</span></div>
        <div class="band-badge">${esc(report.bandLabel)}</div>
      </div>
      <div class="result-advice">💡 ${esc(report.advice)}</div>
      <p class="hint" style="text-align:center">结果已保存到「我的 → 测评报告」，仅自己可见。测评仅供自我了解，不构成医疗诊断。</p>
      <div style="display:flex; gap:10px; justify-content:center; margin-top:14px; flex-wrap:wrap">
        <a class="btn btn-primary" href="#/profile" style="text-decoration:none">查看我的报告</a>
        <a class="btn btn-ghost" href="#/assessments" style="text-decoration:none">返回测评列表</a>
      </div>
    </div>`;
  toast('测评完成，报告已生成', 'success');
}

// ============================================================ 日记本

const diaryState = { editing: null, mood: '', q: '' };

export async function renderDiary(el) {
  diaryState.editing = null; // 离开页面后再回来，不残留编辑状态
  el.innerHTML = pageHeader('日记本', '写下今天的故事，用心情等级给每篇日记做标记')
    + '<div class="loading-page">加载中…</div>';

  el.innerHTML = pageHeader('日记本', '写下今天的故事，用心情等级给每篇日记做标记') + `
    <div class="card" id="diary-editor-card">
      <h3 id="diary-editor-title">✏️ 写新日记</h3>
      <div class="form-error hidden" id="diary-err"></div>
      <label class="field"><span>标题</span>
        <input type="text" id="diary-title" maxlength="80" placeholder="给今天起个名字"></label>
      <label class="field"><span>今天的心情</span>
        <div id="diary-mood">${moodSelectorHTML()}</div></label>
      <label class="field"><span>正文</span>
        <textarea id="diary-content" rows="5" maxlength="10000" placeholder="想写什么就写什么，这里只有你自己能看到…"></textarea></label>
      <div style="display:flex; gap:10px">
        <button class="btn btn-primary" id="diary-save">保存日记</button>
        <button class="btn btn-ghost hidden" id="diary-cancel">取消编辑</button>
      </div>
    </div>

    <div class="card">
      <h3>🕰️ 时间轴</h3>
      <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-bottom:14px">
        <div id="diary-filter">${moodChipsHTML(diaryState.mood)}</div>
        <input type="text" id="diary-search" placeholder="搜索标题或正文…" value="${esc(diaryState.q)}"
               style="max-width:220px; padding:6px 12px; font-size:13.5px">
      </div>
      <div id="diary-list"><div class="loading-page">加载中…</div></div>
    </div>`;

  async function loadList() {
    const box = el.querySelector('#diary-list');
    box.innerHTML = '<div class="loading-page">加载中…</div>';
    const params = new URLSearchParams();
    if (diaryState.mood) params.set('mood', diaryState.mood);
    if (diaryState.q) params.set('q', diaryState.q);
    try {
      const data = await api('/api/diaries?' + params.toString());
      renderList(data.diaries);
    } catch (err) {
      box.innerHTML = emptyState('😔', '加载失败', err.message);
    }
  }

  function renderList(diaries) {
    const box = el.querySelector('#diary-list');
    if (!diaries.length) {
      box.innerHTML = (diaryState.mood || diaryState.q)
        ? emptyState('🔍', '没有符合条件的日记', '换个心情等级或关键词试试')
        : emptyState('📖', '还没有日记', '在上方写下第一篇日记吧');
      return;
    }
    box.innerHTML = `<div class="timeline">${diaries.map((d) => {
      const info = moodInfo(d.moodLevel);
      return `<div class="diary-item" data-open="${d.id}">
        <div class="emo" style="font-size:24px">${info.emoji}</div>
        <div class="item-main">
          <div class="diary-title">${esc(d.title)}</div>
          <div class="diary-content collapsed" data-content="${d.id}">${esc(d.content)}</div>
          <div class="item-meta">${esc(fmtDateTime(d.createdAt))} · 心情：${esc(info.label)}
            ${d.updatedAt !== d.createdAt ? ' · 已编辑' : ''}</div>
        </div>
        <div class="item-actions">
          <button class="btn btn-ghost btn-sm" data-edit="${d.id}">编辑</button>
          <button class="btn btn-danger-ghost btn-sm" data-del="${d.id}">删除</button>
        </div>
      </div>`;
    }).join('')}</div>`;
    box.dataset.diaries = JSON.stringify(diaries.map((d) => d.id));
    box._diaries = diaries;
  }

  // 筛选 chips
  el.querySelector('#diary-filter').addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    diaryState.mood = chip.dataset.mood;
    el.querySelector('#diary-filter').innerHTML = moodChipsHTML(diaryState.mood);
    loadList();
  });

  // 搜索（防抖）
  let searchTimer = null;
  el.querySelector('#diary-search').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      diaryState.q = e.target.value.trim();
      loadList();
    }, 350);
  });

  // 保存 / 更新
  el.querySelector('#diary-save').addEventListener('click', async () => {
    const errBox = el.querySelector('#diary-err');
    const show = (m) => { errBox.textContent = m; errBox.classList.remove('hidden'); };
    errBox.classList.add('hidden');
    const title = el.querySelector('#diary-title').value.trim();
    const content = el.querySelector('#diary-content').value.trim();
    const moodLevel = readMoodSelector(el.querySelector('#diary-mood'));
    if (!title) return show('请填写日记标题');
    if (!moodLevel) return show('请选择今天的心情等级');
    if (!content) return show('日记内容不能为空');

    const btn = el.querySelector('#diary-save');
    btn.disabled = true;
    try {
      if (diaryState.editing) {
        await api(`/api/diaries/${diaryState.editing}`, { method: 'PUT', body: { title, content, moodLevel } });
        toast('日记已更新', 'success');
      } else {
        await api('/api/diaries', { method: 'POST', body: { title, content, moodLevel } });
        toast('日记已保存', 'success');
      }
      diaryState.editing = null;
      renderDiary(el);
    } catch (err) {
      show(err.message);
      btn.disabled = false;
    }
  });

  el.querySelector('#diary-cancel').addEventListener('click', () => {
    diaryState.editing = null;
    renderDiary(el);
  });

  // 列表操作：展开 / 编辑 / 删除
  el.querySelector('#diary-list').addEventListener('click', async (e) => {
    const editBtn = e.target.closest('[data-edit]');
    const delBtn = e.target.closest('[data-del]');
    const item = e.target.closest('.diary-item');

    if (delBtn) {
      e.stopPropagation();
      if (!confirm('确定删除这篇日记吗？删除后无法恢复。')) return;
      try {
        await api(`/api/diaries/${delBtn.dataset.del}`, { method: 'DELETE' });
        toast('日记已删除', 'success');
        loadList();
      } catch (err) {
        toast(err.message, 'error');
      }
      return;
    }
    if (editBtn) {
      e.stopPropagation();
      const diary = el.querySelector('#diary-list')._diaries
        .find((d) => d.id === Number(editBtn.dataset.edit));
      if (!diary) return;
      diaryState.editing = diary.id;
      el.querySelector('#diary-editor-title').textContent = '✏️ 编辑日记';
      el.querySelector('#diary-title').value = diary.title;
      el.querySelector('#diary-content').value = diary.content;
      el.querySelector('#diary-mood').innerHTML = moodSelectorHTML(diary.moodLevel);
      el.querySelector('#diary-cancel').classList.remove('hidden');
      el.querySelector('#diary-editor-card').scrollIntoView({ behavior: 'smooth' });
      return;
    }
    if (item) {
      const content = item.querySelector('.diary-content');
      content.classList.toggle('collapsed');
    }
  });

  loadList();
}

// ============================================================ 个人资料 + 我的报告

export async function renderProfile(el) {
  el.innerHTML = '<div class="loading-page">加载中…</div>';
  let profile, reports;
  try {
    [profile, reports] = await Promise.all([api('/api/profile'), api('/api/reports')]);
  } catch (err) {
    showPageError(el, err);
    return;
  }
  const u = profile.user;
  const s = profile.stats;

  el.innerHTML = pageHeader('我的', '管理个人资料，查看自己的测评报告') + `
    <div class="card">
      <div class="profile-head">
        <div class="big-avatar">${esc(u.avatarEmoji)}</div>
        <div>
          <div class="name">${esc(u.displayName)}
            <span class="role-badge">${u.role === 'admin' ? '管理员' : '用户'}</span></div>
          <div class="sub">@${esc(u.username)} · ${esc(u.email)} · ${esc(fmtDate(u.createdAt))} 加入</div>
        </div>
        <button class="btn btn-danger-ghost btn-sm" id="logout-btn" style="margin-left:auto">退出登录</button>
      </div>
      <div class="stats-row" style="margin-bottom:0">
        <div class="stat-card"><div class="num">${s.moodCount}</div><div class="lab">情绪记录</div></div>
        <div class="stat-card"><div class="num">${s.diaryCount}</div><div class="lab">日记</div></div>
        <div class="stat-card"><div class="num">${s.reportCount}</div><div class="lab">测评报告</div></div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>✏️ 编辑资料</h3>
        <div class="form-error hidden" id="profile-err"></div>
        <label class="field"><span>头像</span>
          <div id="avatar-picker">${avatarPickerHTML(u.avatarEmoji)}</div></label>
        <label class="field"><span>昵称</span>
          <input type="text" id="p-display" maxlength="30" value="${esc(u.displayName)}"></label>
        <label class="field"><span>个人简介</span>
          <textarea id="p-bio" rows="3" maxlength="200" placeholder="用一句话介绍自己（200 字以内）">${esc(u.bio)}</textarea></label>
        <button class="btn btn-primary" id="profile-save">保存资料</button>
      </div>

      <div class="card">
        <h3>📊 我的测评报告</h3>
        <div id="report-list">
          ${reports.reports.length
            ? reports.reports.map((r) => `
              <div class="report-item">
                <div style="font-size:24px">${categoryEmoji(r.category)}</div>
                <div class="item-main">
                  <div><b>${esc(r.assessmentTitle)}</b>
                    <span class="band-badge" style="font-size:12px; padding:1px 10px; margin-left:6px">${esc(r.bandLabel)}</span></div>
                  <div class="item-meta">得分 ${r.score} · ${esc(fmtDateTime(r.createdAt))}</div>
                  <div class="diary-content" style="font-size:13.5px; color:var(--ink-soft)">💡 ${esc(r.advice)}</div>
                </div>
              </div>`).join('')
            : emptyState('📋', '还没有测评报告', '去完成一次心理测评，报告会出现在这里')}
        </div>
      </div>
    </div>`;

  el.querySelector('#logout-btn').addEventListener('click', () => {
    if (confirm('确定退出登录吗？')) logout();
  });

  el.querySelector('#profile-save').addEventListener('click', async () => {
    const errBox = el.querySelector('#profile-err');
    errBox.classList.add('hidden');
    const displayName = el.querySelector('#p-display').value.trim();
    const bio = el.querySelector('#p-bio').value.trim();
    const avatarBtn = el.querySelector('#avatar-picker .avatar-choice.selected');
    const avatarEmoji = avatarBtn ? avatarBtn.dataset.avatar : u.avatarEmoji;
    if (!displayName) {
      errBox.textContent = '昵称不能为空';
      errBox.classList.remove('hidden');
      return;
    }
    const btn = el.querySelector('#profile-save');
    btn.disabled = true;
    try {
      const data = await api('/api/profile', {
        method: 'PUT', body: { displayName, bio, avatarEmoji },
      });
      setUser(data.user);
      toast('资料已保存', 'success');
      renderProfile(el);
    } catch (err) {
      errBox.textContent = err.message;
      errBox.classList.remove('hidden');
      btn.disabled = false;
    }
  });
}

function categoryEmoji(category) {
  return { anxiety: '🌧️', depression: '🌫️', stress: '⛰️', sleep: '🌙', general: '🧭' }[category] || '🧭';
}
