const q = selector => document.querySelector(selector);
const qa = selector => [...document.querySelectorAll(selector)];
const iconForKind = { photo: 'camera', music: 'music', study: 'study', game: 'game', chat: 'chat', file: 'file', location: 'map' };
const collectionLabels = { photo: '图片', music: '音乐', study: '自习', game: '游戏', chat: '聊天', file: '文件', location: '地点' };
let bridge = null;
let state = null;
let currentDay = localDateKey(new Date());
let saveTimer = null;
let currentMemoryDate = '';

function localDateKey(value) {
  const date = value instanceof Date ? value : new Date(value);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

function parse(payload, fallback = {}) {
  try { return typeof payload === 'string' ? JSON.parse(payload) : payload; }
  catch (_) { return fallback; }
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

function displayDate(value) {
  if (!value) return '';
  const [year, month, day] = value.split('-').map(Number);
  return `${year}年${month}月${day}日`;
}

function weekday(value) {
  const names = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];
  return names[new Date(`${value}T12:00:00`).getDay()];
}

function excerpt(item, length = 90) {
  const text = String(item?.user_content || item?.lianxin_content || '').replace(/\s+/g, ' ').trim();
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

function showToast(message) {
  const toast = q('#toast');
  toast.textContent = message;
  toast.classList.remove('hidden');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add('hidden'), 2400);
}

function call(method, ...args) {
  return new Promise(resolve => {
    if (!bridge || typeof bridge[method] !== 'function') return resolve(null);
    bridge[method](...args, result => resolve(parse(result, result)));
  });
}

function switchPage(page) {
  qa('.page').forEach(section => section.classList.toggle('active', section.id === `page-${page}`));
  qa('.c-sidebar-item').forEach(item => item.classList.toggle('selected', item.dataset.page === page));
  const labels = { today: '今天', corridor: '时间长廊', tree: '树洞', museum: '收藏馆' };
  q('#topbar-title').textContent = labels[page] || '时间胶囊';
  q('.main-content').scrollTop = 0;
}

function render(data) {
  state = data || state;
  if (!state) return;
  renderToday(state.today || {});
  renderContribution(state.contribution || {});
  renderCollections(q('#featured-collections'), state.recent_collections || [], true);
  renderTimeline(state.timeline || []);
  renderTree(state.tree_notes || []);
  renderMuseum(state.memories || []);
  const companion = state.companion || {};
  q('#companion-message').textContent = companion.message || '我会在这里陪你慢慢看。';
  q('#user-page-name').textContent = state.user_name || '主人';
  q('#footer-status').textContent = `已经收藏 ${state.timeline?.length || 0} 个日子`;
  q('#loading-state')?.classList.add('hidden');
}

function renderToday(day) {
  currentDay = day.date || currentDay;
  q('#today-date').textContent = displayDate(currentDay);
  q('#today-weekday').textContent = weekday(currentDay);
  const editor = q('#user-paper');
  if (document.activeElement !== editor && editor.textContent !== (day.user_content || '')) editor.textContent = day.user_content || '';
  const lianxin = q('#lianxin-paper');
  lianxin.textContent = day.lianxin_content || '今天还没有留下故事。\n\n但书页已经准备好了。';
  lianxin.classList.toggle('empty-paper', !day.lianxin_content);
  q('#lianxin-weather').textContent = day.weather || '';
  q('#seal-day span').textContent = day.sealed ? '今天已经封存' : '封存今天';
  q('#seal-note').textContent = day.sealed ? '这一天已经被好好收进时间长廊，仍然可以继续留下笔迹。' : '封存后仍然可以继续留下笔迹。';
  renderTraces(day.traces || []);
  renderCollections(q('#today-collections'), day.collections || []);
}

function renderTraces(traces) {
  const root = q('#trace-list');
  root.innerHTML = '';
  if (!traces.length) root.innerHTML = '<div class="empty-state">这一页还没有后来的笔迹。<br>时间会继续向下生长。</div>';
  traces.forEach(trace => {
    const card = document.createElement('article');
    card.className = `trace-card ${trace.author === 'lianxin' ? 'lianxin' : 'user'}`;
    card.innerHTML = `<small>${trace.author === 'lianxin' ? '莲心' : (state?.user_name || '主人')} · ${formatTime(trace.created_at)}</small><div>${escapeHtml(trace.content).replace(/\n/g, '<br>')}</div>`;
    root.appendChild(card);
  });
}

function collectionCard(item) {
  const card = document.createElement('article');
  card.className = 'collection-card';
  const icon = iconForKind[item.kind] || 'file';
  card.innerHTML = `<svg><use href="#i-${icon}"/></svg><strong>${escapeHtml(item.title || collectionLabels[item.kind] || '共同收藏')}</strong><small>${item.capsule_date || formatTime(item.created_at)}</small>`;
  return card;
}

function renderCollections(root, items, featured = false) {
  root.innerHTML = '';
  if (!items.length) {
    if (featured) root.innerHTML = '<div class="empty-state">最近还没有共同收藏。<br>下一件值得留下的东西正在等待你们。</div>';
    return;
  }
  items.forEach(item => root.appendChild(collectionCard(item)));
}

function renderContribution(data) {
  const grid = q('#contribution-grid');
  grid.innerHTML = '';
  (data.days || []).forEach(item => {
    const cell = document.createElement('button');
    const level = item.value <= 0 ? 0 : Math.min(3, item.value);
    cell.className = `heat-cell level-${level}${item.future ? ' future' : ''}${item.date === localDateKey(new Date()) ? ' today' : ''}`;
    cell.dataset.date = item.date;
    cell.dataset.value = item.value;
    cell.onmouseenter = event => showHeatTooltip(event, item);
    cell.onmousemove = event => moveHeatTooltip(event);
    cell.onmouseleave = hideHeatTooltip;
    cell.onclick = () => openDay(item.date);
    grid.appendChild(cell);
  });
  q('#active-days').textContent = data.active_days || 0;
  q('#longest-streak').textContent = `${data.longest_streak || 0}天`;
  q('#current-streak').textContent = `${data.current_streak || 0}天`;
}

function showHeatTooltip(event, item) {
  const tooltip = q('#heat-tooltip');
  tooltip.innerHTML = `<strong>${displayDate(item.date)}</strong><br><span>${item.future ? '未来的书页' : item.value ? `留下了 ${item.value} 道足迹` : '这一天还很安静'}</span>`;
  tooltip.classList.remove('hidden');
  moveHeatTooltip(event);
}
function moveHeatTooltip(event) { const tooltip = q('#heat-tooltip'); tooltip.style.left = `${event.clientX + 16}px`; tooltip.style.top = `${event.clientY + 16}px`; }
function hideHeatTooltip() { q('#heat-tooltip').classList.add('hidden'); }

function renderTimeline(items) {
  const root = q('#timeline');
  root.innerHTML = '';
  if (!items.length) { root.innerHTML = '<div class="empty-state">时间长廊还没有故事。<br>第一张书页正等待被写下。</div>'; return; }
  const groups = new Map();
  items.forEach(item => {
    const key = item.date.slice(0, 7);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  groups.forEach((days, key) => {
    const section = document.createElement('section');
    section.className = 'month-group';
    const [year, month] = key.split('-');
    section.innerHTML = `<h3 class="month-title"><span>${year}年${Number(month)}月</span></h3>`;
    days.forEach(item => {
      const button = document.createElement('button');
      button.className = 'diary-card';
      button.innerHTML = `<time>${Number(item.date.slice(8))}日 · ${weekday(item.date).replace('星期','周')}</time><p>${escapeHtml(excerpt(item) || '这一天被安静地封存了。')}</p><span>${item.sealed ? '已封存' : '仍在书写'}</span>`;
      button.onclick = () => openDay(item.date);
      section.appendChild(button);
    });
    root.appendChild(section);
  });
}

function renderTree(items) {
  const root = q('#tree-notes');
  root.innerHTML = '';
  if (!items.length) { root.innerHTML = '<div class="empty-state">今晚，<br><br>这里还很安静。</div>'; return; }
  items.forEach(item => {
    const note = document.createElement('article');
    note.className = 'tree-note';
    note.innerHTML = `<p>${escapeHtml(item.content).replace(/\n/g,'<br>')}</p><small>${item.author === 'lianxin' ? '莲心留下的纸条' : '你放进树洞的纸条'} · ${formatTime(item.created_at)}</small><button>${item.favorite ? '★ 已收进回响' : '☆ 收进回响'}</button>`;
    note.querySelector('button').onclick = async () => { await call('toggle_tree_favorite', item.id); };
    root.appendChild(note);
  });
}

function renderMuseum(items) {
  const root = q('#memory-grid');
  root.innerHTML = '';
  if (!items.length) { root.innerHTML = '<div class="empty-state">第一段值得珍藏的回忆，<br><br>正在等待诞生。</div>'; return; }
  items.forEach(item => {
    const card = document.createElement('article');
    card.className = 'memory-card';
    card.innerHTML = `<div class="memory-cover"><svg><use href="#i-star"/></svg></div><footer><h3>${escapeHtml(item.title)}</h3><p>${displayDate(item.source_date)}<br>${escapeHtml(item.description || '').slice(0, 72)}</p></footer>`;
    card.onclick = () => openMemory(item);
    root.appendChild(card);
  });
}

async function openDay(day) {
  const item = await call('get_day', day);
  if (!item) return;
  currentMemoryDate = day;
  q('#detail-date').textContent = `${displayDate(day)} · ${weekday(day)}`;
  q('#detail-title').textContent = firstLine(item.user_content || item.lianxin_content) || '这一天的故事';
  q('#detail-user').textContent = item.user_content || '';
  q('#detail-user').classList.toggle('hidden', !item.user_content);
  q('#detail-lianxin').textContent = item.lianxin_content || '';
  q('#detail-lianxin').classList.toggle('hidden', !item.lianxin_content);
  const traces = q('#detail-traces'); traces.innerHTML = '';
  (item.traces || []).forEach(trace => { const el = document.createElement('div'); el.className = `trace-card ${trace.author === 'lianxin' ? 'lianxin' : ''}`; el.textContent = trace.content; traces.appendChild(el); });
  renderCollections(q('#detail-collections'), item.collections || []);
  q('#detail-panel').classList.remove('hidden');
}

function firstLine(value = '') { return String(value).split(/\n/).find(line => line.trim())?.replace(/^#+\s*/, '').slice(0, 32) || ''; }
function openMemory(item) { call('visit_memory', item.id); openDay(item.source_date); }
function closeDetail() { q('#detail-panel').classList.add('hidden'); }

function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16).replace('T', ' ');
  return `${date.getMonth()+1}月${date.getDate()}日 ${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`;
}

function bindEvents() {
  qa('.c-sidebar-item').forEach(item => item.onclick = () => switchPage(item.dataset.page));
  q('#minimize').onclick = () => bridge?.request_minimize();
  q('#fullscreen').onclick = () => bridge?.request_fullscreen();
  q('#close').onclick = () => bridge?.request_close();
  q('#open-settings').onclick = openSettings;
  q('.settings-close').onclick = closeSettings;
  q('.settings-backdrop').onclick = closeSettings;
  q('#save-settings').onclick = saveSettings;
  q('.detail-close').onclick = closeDetail;
  q('.detail-backdrop').onclick = closeDetail;
  q('.companion-close').onclick = () => q('#companion-panel').classList.add('hidden');
  q('#user-paper').addEventListener('input', () => {
    q('#save-status').textContent = '正在留住笔迹…';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      await call('save_user_content', currentDay, q('#user-paper').textContent);
      q('#save-status').textContent = '已保存';
    }, 650);
  });
  q('#user-paper').addEventListener('dragover', event => event.preventDefault());
  q('#user-paper').addEventListener('drop', async event => {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (!file) return;
    const kind = file.type?.startsWith('image/') ? 'photo' : file.type?.startsWith('audio/') ? 'music' : 'file';
    await call('add_collection', currentDay, kind, file.name, file.path || file.name);
    showToast('已经放进今日共同收藏。');
  });
  q('#add-trace').onclick = async () => {
    const input = q('#trace-input'); const value = input.value.trim(); if (!value) return;
    await call('add_trace', currentDay, 'user', value); input.value = ''; showToast('这道笔迹已经留在书页旁边。');
  };
  q('#seal-day').onclick = async () => {
    const book = q('#book-layout'); book.classList.add('closing');
    await call('seal_day', currentDay, q('#user-paper').textContent);
    setTimeout(() => { book.classList.remove('closing'); switchPage('corridor'); showToast('今天已经被好好封存。'); }, 800);
  };
  q('#send-tree').onclick = async () => {
    const input = q('#tree-input'); const value = input.value.trim(); if (!value) return;
    const result = await call('add_tree_note', value); if (result?.ok) { input.value = ''; showToast('纸条已经飞进树洞。'); }
  };
  q('#invite-lianxin').onclick = async () => {
    const source = currentMemoryDate || state?.memories?.[0]?.source_date || '';
    q('#companion-reading').textContent = '我正在从共同的回忆里，找一条通往这一页的小路……';
    q('#companion-panel').classList.remove('hidden');
    await call('invite_lianxin', source);
  };
  q('#global-search').addEventListener('input', debounce(async event => {
    const value = event.target.value.trim(); const box = q('#search-results');
    if (!value) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    const results = await call('search', value); box.innerHTML = '';
    (results || []).forEach(item => { const button = document.createElement('button'); button.className = 'search-result'; button.innerHTML = `<strong>${displayDate(item.date)}</strong><small>${escapeHtml(excerpt(item))}</small>`; button.onclick = () => { box.classList.add('hidden'); openDay(item.date); }; box.appendChild(button); });
    if (!(results || []).length) box.innerHTML = '<div class="empty-state">没有找到这段回忆。</div>';
    box.classList.remove('hidden');
  }, 240));
}

async function openSettings() {
  const settings = await call('get_settings') || {};
  q('#scheduled-enabled').checked = Boolean(settings.scheduled_enabled);
  q('#scheduled-time').value = settings.scheduled_time || '23:55';
  q('#max-messages').value = settings.max_messages || 30;
  q('#message-direction').value = settings.direction || 'latest';
  q('#settings-panel').classList.remove('hidden');
}

function closeSettings() { q('#settings-panel').classList.add('hidden'); }

async function saveSettings() {
  await call('save_settings', q('#scheduled-enabled').checked, q('#scheduled-time').value || '23:55', Number(q('#max-messages').value || 30), q('#message-direction').value);
  closeSettings();
  showToast('书页设置已经保存。');
}

function renderCollectionActions() {
  const root = q('#collection-actions');
  root.innerHTML = '';
  Object.entries(collectionLabels).forEach(([kind, label]) => {
    const button = document.createElement('button'); button.className = 'collection-action';
    button.innerHTML = `<span><svg><use href="#i-${iconForKind[kind]}"/></svg></span><span>${label}</span>`;
    button.onclick = async () => {
      let uri = ''; let title = '';
      if (['photo','music','file'].includes(kind)) { uri = await call('choose_collection_file', kind); if (!uri) return; title = String(uri).split(/[\\/]/).pop(); }
      if (kind === 'chat') title = firstLine(q('#user-paper').textContent) || '一句想记住的话';
      await call('add_collection', currentDay, kind, title, uri); showToast(`${label}已经一起收藏。`);
    };
    root.appendChild(button);
  });
}

function debounce(fn, delay) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); }; }

function initialize() {
  bindEvents(); renderCollectionActions();
  if (typeof QWebChannel === 'undefined' || !window.qt?.webChannelTransport) {
    q('#footer-status').textContent = '桥接加载失败，请重新打开时间胶囊';
    q('#loading-state').innerHTML = '<strong>书页没有顺利展开</strong><span>请关闭后重新打开时间胶囊。</span>';
    return;
  }
  new QWebChannel(qt.webChannelTransport, channel => {
    bridge = channel.objects.capsuleBridge;
    bridge.state_changed.connect(payload => render(parse(payload)));
    bridge.companion_ready.connect(payload => {
      const result = parse(payload);
      q('#companion-reading').textContent = result?.message || '我在这里。';
      q('#companion-panel').classList.remove('hidden');
    });
    call('get_initial_state').then(render);
  });
}

document.addEventListener('DOMContentLoaded', initialize);
