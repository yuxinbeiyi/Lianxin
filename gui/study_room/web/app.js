const STUDY_ROOM_UI_VERSION = '2026.07.25.5';
const RING_LENGTH = 860.8;
const q = (selector) => document.querySelector(selector);
const qa = (selector) => [...document.querySelectorAll(selector)];

let bridge = null;
let allTasks = [];
let taskFilter = 'all';
let selectedRange = 'today';
let currentView = 'home';
let editingTaskId = null;
let toastTimer = null;
let roomSettings = {
  focus_minutes: 25,
  break_minutes: 5,
  auto_break: true,
  auto_fullscreen: true,
  show_completion: true,
  animations: true,
};
let timerState = {
  remaining: 1500,
  total: 1500,
  phase: 'idle',
  task_name: '',
  active: false,
  paused: false,
};

function formatDuration(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  if (hours) return minutes ? `${hours}小时${minutes}分钟` : `${hours}小时`;
  return `${minutes}分钟`;
}

function showToast(message, duration = 2600) {
  const toast = q('#toast');
  toast.textContent = message;
  toast.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add('hidden'), duration);
}

function setCompanion(text) {
  q('#companion-text').textContent = text;
  if (currentView === 'focus' && text) q('#focus-companion').textContent = text;
}

function renderClock(clock) {
  if (!clock) return;
  q('#sidebar-time').textContent = clock.time || '--:--';
  q('#sidebar-date').textContent = clock.date || '日期不可用';
  q('#sidebar-weekday').textContent = clock.weekday || '';
  q('#sidebar-lunar').textContent = clock.lunar || '农历日期不可用';
}

function phaseLabel() {
  if (timerState.paused) return '已暂停';
  if (timerState.phase === 'break') return '休息时间';
  if (timerState.phase === 'focus') return '专注进行中';
  return '准备开始';
}

function renderTimer() {
  const remaining = Math.max(0, Number(timerState.remaining) || 0);
  const total = Math.max(1, Number(timerState.total) || 1);
  const display = `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
  const progress = Math.max(0, Math.min(1, remaining / total));
  const dashOffset = RING_LENGTH * (1 - progress);
  const isBreak = timerState.phase === 'break';
  const status = timerState.paused ? '计时已暂停，准备好再继续' : (isBreak ? '让眼睛和思绪都休息一下' : (timerState.active ? '保持自己的节奏' : '选择一个任务或常用时长'));

  q('#timer-value').textContent = display;
  q('#focus-timer-value').textContent = display;
  q('#phase-value').textContent = phaseLabel();
  q('#focus-phase-value').textContent = phaseLabel();
  q('#timer-status').textContent = status;
  q('#focus-status').textContent = status;
  q('#ring-progress').style.strokeDashoffset = String(dashOffset);
  q('#focus-ring-progress').style.strokeDashoffset = String(dashOffset);
  qa('.timer-wrap').forEach(item => item.classList.toggle('is-break', isBreak));
  qa('.ring-gradient-start').forEach(stop => stop.setAttribute('stop-color', isBreak ? '#a9d0bb' : '#f3cf72'));
  qa('.ring-gradient-end').forEach(stop => stop.setAttribute('stop-color', isBreak ? '#5b927d' : '#a9633c'));

  const selectedText = q('#task-select').selectedOptions[0]?.textContent;
  q('#focus-task-name').textContent = timerState.task_name || (selectedText && q('#task-select').value !== '-1' ? selectedText : '未绑定任务');
  q('#focus-badge').textContent = timerState.paused ? '莲心在等你回来' : (isBreak ? '莲心陪你休息' : '莲心陪伴中');
  q('#pause-focus').textContent = timerState.paused ? '继续' : '暂停';
  q('#focus-pause').textContent = timerState.paused ? '继续' : '暂停';
}

function updateGoal(tasks = allTasks) {
  const selectedId = Number(q('#task-select').value);
  const selected = tasks.find(item => item.id === selectedId) || tasks.find(item => !item.completed);
  q('#goal-title').textContent = selected ? selected.title : '还没有选择任务';
  q('#goal-detail').textContent = selected
    ? `专注 ${selected.estimate_minutes} 分钟 · 休息 ${selected.break_minutes ?? 5} 分钟${selected.repeat_enabled ? ' · 循环执行' : ''}`
    : '前往任务清单写下一件想完成的事，或直接使用常用时长。';
}

function renderTasks(tasks) {
  allTasks = tasks || [];
  const list = q('#task-list');
  const query = (q('#task-search').value || '').trim().toLowerCase();
  const visible = allTasks
    .filter(task => task.title.toLowerCase().includes(query))
    .filter(task => taskFilter === 'all' || (taskFilter === 'completed' ? task.completed : !task.completed));
  list.innerHTML = '';

  if (!visible.length) {
    const title = query ? '没有找到匹配的任务' : (taskFilter === 'completed' ? '还没有已完成任务' : '任务清单还是空的');
    const detail = query ? '换一个关键词试试。' : '从上方写下一件具体、可以开始的事情。';
    list.innerHTML = `<div class="empty-state"><strong>${title}</strong><span>${detail}</span></div>`;
    return;
  }

  visible.forEach(task => {
    const row = document.createElement('div');
    row.className = `task-row${task.completed ? ' completed' : ''}`;
    row.dataset.taskId = String(task.id);
    row.innerHTML = `
      <button class="task-check" aria-label="${task.completed ? '恢复任务' : '完成任务'}">${task.completed ? '✓' : ''}</button>
      <span class="task-title"></span>
      <span class="task-estimate">专注 ${task.estimate_minutes}分 · 休息 ${task.break_minutes ?? 5}分${task.repeat_enabled ? ' · 循环' : ''}</span>
      <button class="task-start" ${task.completed ? 'disabled' : ''}>开始</button>
      <button class="task-delete" aria-label="删除任务">删除</button>`;
    row.querySelector('.task-title').textContent = task.title;
    row.querySelector('.task-check').onclick = () => bridge?.toggle_task(task.id);
    row.querySelector('.task-start').onclick = () => {
      q('#task-select').value = String(task.id);
      previewSelectedTask();
      startSelectedFocus();
    };
    row.querySelector('.task-delete').onclick = () => bridge?.delete_task(task.id);
    row.addEventListener('dblclick', () => openTaskEditor(task));
    row.addEventListener('contextmenu', event => {
      event.preventDefault();
      openTaskEditor(task);
    });
    list.appendChild(row);
  });
}

function openTaskEditor(task) {
  editingTaskId = task.id;
  q('#edit-task-title').value = task.title;
  q('#edit-task-estimate').value = task.estimate_minutes;
  q('#edit-task-break').value = task.break_minutes ?? 5;
  q('#edit-task-repeat').checked = Boolean(task.repeat_enabled);
  q('#task-modal').classList.remove('hidden');
  q('#edit-task-title').focus();
}

function closeTaskEditor() {
  editingTaskId = null;
  q('#task-modal').classList.add('hidden');
}

function validMinutes(value, minimum, maximum) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= minimum && parsed <= maximum;
}

function saveTaskEditor() {
  if (editingTaskId === null) return;
  const title = q('#edit-task-title').value.trim();
  const focus = Number(q('#edit-task-estimate').value);
  const rest = Number(q('#edit-task-break').value);
  if (!title) return showToast('请先填写任务名称。');
  if (!validMinutes(focus, 1, 600) || !validMinutes(rest, 0, 60)) return showToast('请检查专注和休息时长。');
  bridge?.update_task(editingTaskId, title, focus, rest, q('#edit-task-repeat').checked);
  closeTaskEditor();
  showToast('任务设置已保存。');
}

function renderTaskSelect(tasks) {
  const select = q('#task-select');
  const selected = select.value;
  select.innerHTML = '<option value="-1">选择今天要做的任务（可选）</option>';
  tasks.filter(task => !task.completed).forEach(task => {
    const option = document.createElement('option');
    option.value = String(task.id);
    option.textContent = task.title;
    option.dataset.estimate = String(task.estimate_minutes);
    option.dataset.break = String(task.break_minutes ?? 5);
    option.dataset.repeat = task.repeat_enabled ? '1' : '0';
    select.appendChild(option);
  });
  if ([...select.options].some(option => option.value === selected)) select.value = selected;
}

function comparisonText(stats) {
  const current = Number(stats.focus_seconds || 0);
  const previous = Number(stats.previous_focus_seconds || 0);
  const label = stats.previous_label || '上一周期';
  if (!current && !previous) return `${label}也还没有记录`;
  const delta = current - previous;
  if (!delta) return `与${label}持平`;
  return `${delta > 0 ? '比' : '较'}${label}${delta > 0 ? '多' : '少'} ${formatDuration(Math.abs(delta))}`;
}

function positionChartTooltip(bar, event) {
  const plot = q('.chart-plot');
  const tooltip = q('#chart-tooltip');
  const plotRect = plot.getBoundingClientRect();
  const barRect = bar.getBoundingClientRect();
  const x = event?.clientX ? event.clientX - plotRect.left : barRect.left - plotRect.left + barRect.width / 2;
  const y = barRect.top - plotRect.top;
  tooltip.style.left = `${Math.max(50, Math.min(plotRect.width - 50, x))}px`;
  tooltip.style.top = `${Math.max(32, y)}px`;
}

function renderStats(stats) {
  q('#stat-focus').textContent = formatDuration(stats.focus_seconds);
  q('#stat-streak').textContent = `${stats.streak || 0}天`;
  q('#stat-completed').textContent = `${stats.completed_sessions || 0}次`;
  q('#stat-interrupted').textContent = `${stats.interrupted_sessions || 0}次`;
  q('#stat-room').textContent = formatDuration(stats.room_seconds);
  q('#stat-focus-compare').textContent = comparisonText(stats);
  const focusLabels = { today: '今日专注', week: '本周专注', month: '本月专注', year: '本年专注' };
  const roomLabels = { today: '今日打开时长', week: '本周打开时长', month: '本月打开时长', year: '本年打开时长' };
  q('#metric-focus-title').textContent = focusLabels[stats.period] || '今日专注';
  q('#metric-room-title').textContent = roomLabels[stats.period] || '今日打开时长';

  const trend = (stats.trend || []).slice(0, 7);
  const total = trend.reduce((sum, row) => sum + Number(row.focus_seconds || 0), 0);
  q('#week-total').textContent = `累计 ${formatDuration(total)}`;
  q('#chart-empty').classList.toggle('hidden', total > 0);
  const peakSeconds = Math.max(0, ...trend.map(row => Number(row.focus_seconds || 0)));
  const minuteMode = peakSeconds <= 3600;
  const axisMax = minuteMode ? 60 : Math.max(1, Math.ceil(peakSeconds / 3600));
  const axisStep = minuteMode ? 15 : 1;

  const axis = q('#chart-y-axis');
  axis.innerHTML = '';
  for (let value = axisMax; value >= 0; value -= axisStep) {
    const label = document.createElement('span');
    label.textContent = minuteMode ? `${value}分` : `${value}时`;
    axis.appendChild(label);
  }
  const grid = q('#chart-grid');
  grid.innerHTML = '';
  for (let value = 0; value <= axisMax; value += axisStep) {
    const line = document.createElement('i');
    line.style.bottom = `${value / axisMax * 100}%`;
    grid.appendChild(line);
  }

  const chart = q('#chart');
  const xAxis = q('#chart-x-axis');
  const tooltip = q('#chart-tooltip');
  chart.innerHTML = '';
  xAxis.innerHTML = '';
  tooltip.classList.add('hidden');
  trend.forEach(row => {
    const seconds = Number(row.focus_seconds || 0);
    const col = document.createElement('div');
    const bar = document.createElement('div');
    const date = document.createElement('span');
    const parsed = new Date(`${row.date}T00:00:00`);
    const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    const month = Number(row.date.slice(5, 7));
    const day = Number(row.date.slice(8, 10));
    const description = `${weekdays[parsed.getDay()]} ${month}月${day}日 · ${formatDuration(seconds)}`;
    col.className = 'bar-col';
    bar.className = 'bar';
    bar.tabIndex = 0;
    bar.setAttribute('aria-label', description);
    bar.style.height = `${Math.min(100, Math.max(seconds ? 2 : 0, seconds / (axisMax * (minuteMode ? 60 : 3600)) * 100))}%`;
    date.textContent = `${weekdays[parsed.getDay()]}\n${month}月${day}日`;
    const show = event => {
      tooltip.textContent = description;
      tooltip.classList.remove('hidden');
      positionChartTooltip(bar, event);
    };
    bar.addEventListener('mouseenter', show);
    bar.addEventListener('mousemove', event => positionChartTooltip(bar, event));
    bar.addEventListener('mouseleave', () => tooltip.classList.add('hidden'));
    bar.addEventListener('focus', show);
    bar.addEventListener('blur', () => tooltip.classList.add('hidden'));
    col.appendChild(bar);
    chart.appendChild(col);
    xAxis.appendChild(date);
  });

  const completed = Number(stats.completed_sessions || 0);
  const interrupted = Number(stats.interrupted_sessions || 0);
  let note = '莲心记录：先从一个短短的专注开始吧。';
  if (Number(stats.focus_seconds || 0) > 0) {
    note = `莲心记录：${focusLabels[stats.period] || '这段时间'}累计 ${formatDuration(stats.focus_seconds)}，完整完成 ${completed} 次。`;
    if (interrupted > completed && interrupted > 1) note += ' 中断次数稍多，可以把下一次目标调短一些。';
    else if (Number(stats.streak || 0) >= 3) note += ` 已连续坚持 ${stats.streak} 天，节奏正在稳定下来。`;
    else note += ` ${comparisonText(stats)}。`;
  }
  q('#growth-note').textContent = note;
}

function switchView(view) {
  currentView = view;
  document.body.classList.toggle('focus-mode', view === 'focus');
  qa('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.view === view));
  qa('.view').forEach(section => section.classList.toggle('active', section.id === `view-${view}`));
  const labels = { home: '开始专注', tasks: '任务清单', focus: '沉浸专注', stats: '成长记录', space: '我的空间', settings: '设置' };
  q('#page-kicker').textContent = labels[view] || '';
  if (view === 'stats') refreshStats();
}

function enterFocusView() {
  switchView('focus');
  if (roomSettings.auto_fullscreen) bridge?.set_focus_fullscreen(true);
}

function leaveFocusView() {
  switchView('home');
  if (roomSettings.auto_fullscreen) bridge?.set_focus_fullscreen(false);
}

function refreshStats() {
  if (!bridge || currentView !== 'stats') return;
  bridge.get_statistics(selectedRange, payload => renderStats(JSON.parse(payload)));
}

function previewSelectedTask() {
  if (timerState.active) return;
  const option = q('#task-select').selectedOptions[0];
  const activePreset = q('.preset.active');
  const minutes = Number(option?.dataset.estimate || activePreset?.dataset.focus || roomSettings.focus_minutes || 25);
  timerState = { ...timerState, remaining: minutes * 60, total: minutes * 60, phase: 'idle', active: false, paused: false };
  updateGoal();
  renderTimer();
}

function startSelectedFocus() {
  if (!bridge) return showToast('自习室后端尚未连接，请稍后重试。');
  if (timerState.active) return enterFocusView();
  const preset = q('.preset.active');
  const selected = q('#task-select').selectedOptions[0];
  const taskEstimate = Number(selected?.dataset.estimate || 0);
  const focus = taskEstimate > 0 ? taskEstimate : Number(preset?.dataset.focus || roomSettings.focus_minutes || 25);
  const rest = roomSettings.auto_break ? Number(selected?.dataset.break || preset?.dataset.break || roomSettings.break_minutes || 5) : 0;
  timerState = { ...timerState, remaining: focus * 60, total: focus * 60, phase: 'focus', active: true, paused: false, task_name: selected?.dataset.estimate ? selected.textContent : '' };
  renderTimer();
  bridge.start_focus(focus, rest, Number(q('#task-select').value));
  enterFocusView();
}

function loadSettings(settings) {
  roomSettings = { ...roomSettings, ...(settings || {}) };
  q('#setting-focus').value = roomSettings.focus_minutes;
  q('#setting-break').value = roomSettings.break_minutes;
  q('#setting-auto').checked = Boolean(roomSettings.auto_break);
  q('#setting-fullscreen').checked = Boolean(roomSettings.auto_fullscreen);
  q('#setting-completion').checked = Boolean(roomSettings.show_completion);
  q('#setting-animation').checked = Boolean(roomSettings.animations);
  document.body.classList.toggle('no-motion', !roomSettings.animations);
  const preset = qa('.preset').find(item => Number(item.dataset.focus) === Number(roomSettings.focus_minutes));
  if (preset) {
    qa('.preset').forEach(item => item.classList.remove('active'));
    preset.classList.add('active');
  }
}

function saveSettings() {
  const focus = Number(q('#setting-focus').value);
  const rest = Number(q('#setting-break').value);
  if (!validMinutes(focus, 1, 180) || !validMinutes(rest, 0, 60)) return showToast('请检查默认专注和休息时长。');
  roomSettings = {
    focus_minutes: focus,
    break_minutes: rest,
    auto_break: q('#setting-auto').checked,
    auto_fullscreen: q('#setting-fullscreen').checked,
    show_completion: q('#setting-completion').checked,
    animations: q('#setting-animation').checked,
  };
  document.body.classList.toggle('no-motion', !roomSettings.animations);
  bridge?.save_settings(focus, rest, roomSettings.auto_break, roomSettings.auto_fullscreen, roomSettings.show_completion, roomSettings.animations);
  q('#settings-status').textContent = '已保存';
  setTimeout(() => { q('#settings-status').textContent = ''; }, 2400);
  showToast('自习室设置已保存。');
}

function resetSettings() {
  loadSettings({ focus_minutes: 25, break_minutes: 5, auto_break: true, auto_fullscreen: true, show_completion: true, animations: true });
  saveSettings();
}

function connectBridge() {
  if (typeof QWebChannel === 'undefined' || typeof qt === 'undefined') {
    showToast('无法连接自习室后端，请重新打开窗口。', 5000);
    console.error('[自习室Web] QWebChannel 不可用');
    return;
  }
  new QWebChannel(qt.webChannelTransport, channel => {
    bridge = channel.objects.studyBridge;
    bridge.get_initial_state(payload => {
      const initial = JSON.parse(payload);
      renderTasks(initial.tasks);
      renderTaskSelect(initial.tasks);
      renderStats(initial.stats);
      timerState = { ...timerState, ...initial.timer };
      loadSettings(initial.settings);
      renderClock(initial.clock);
      const hour = new Date().getHours();
      const greeting = hour < 12 ? '早上好' : (hour < 18 ? '下午好' : '晚上好');
      q('#time-greeting').textContent = `${greeting}，${initial.user_name || '朋友'}`;
      updateGoal(initial.tasks);
      renderTimer();
      if (timerState.active) enterFocusView();
    });

    bridge.timer_tick.connect(payload => {
      timerState = { ...timerState, ...JSON.parse(payload), active: true };
      renderTimer();
    });
    bridge.clock_changed.connect(payload => renderClock(JSON.parse(payload)));
    bridge.phase_changed.connect(phase => {
      if (phase === 'paused') {
        timerState.paused = true;
      } else {
        timerState.paused = false;
        timerState.phase = phase;
        timerState.active = phase !== 'idle';
      }
      q('#timer-controls').classList.toggle('hidden', !timerState.active);
      q('#start-focus').classList.toggle('hidden', timerState.active);
      q('#focus-pause').disabled = !timerState.active;
      q('#focus-stop').disabled = !timerState.active;
      if (phase === 'paused') setCompanion('我会在这里安静等你，准备好后再继续。');
      if (phase === 'break') q('#focus-companion').textContent = '这一段已经完成了。站起来走走，喝口水，再回来也不迟。';
      if (phase === 'idle') {
        if (currentView === 'focus') leaveFocusView();
        q('#focus-companion').textContent = '这一段专注已经结束，可以回到自习室看看今天的记录。';
      }
      renderTimer();
    });
    bridge.tasks_changed.connect(payload => {
      const tasks = JSON.parse(payload);
      renderTasks(tasks);
      renderTaskSelect(tasks);
      updateGoal(tasks);
    });
    bridge.statistics_changed.connect(() => refreshStats());
    bridge.companion_message.connect(setCompanion);
    bridge.focus_completed.connect(payload => {
      const data = JSON.parse(payload);
      if (roomSettings.show_completion) {
        q('#completion-note').textContent = `本次专注已完成 · ${formatDuration(data.duration)}${data.task_name ? ` · 任务：${data.task_name}` : ''}`;
        q('#completion-note').classList.remove('hidden');
      }
    });
  });
}

function bindEvents() {
  qa('.nav-item').forEach(button => button.onclick = () => switchView(button.dataset.view));
  qa('.preset').forEach(button => button.onclick = () => {
    if (timerState.active) return showToast('当前计时进行中，结束后才能更换时长。');
    qa('.preset').forEach(item => item.classList.remove('active'));
    button.classList.add('active');
    q('#task-select').value = '-1';
    previewSelectedTask();
  });
  q('#start-focus').onclick = startSelectedFocus;
  q('#task-select').onchange = previewSelectedTask;
  q('#reenter-focus').onclick = enterFocusView;
  q('#pause-focus').onclick = () => bridge?.toggle_pause();
  q('#stop-focus').onclick = () => bridge?.stop_focus();
  q('#focus-pause').onclick = () => bridge?.toggle_pause();
  q('#focus-stop').onclick = () => bridge?.stop_focus();
  q('#focus-back').onclick = leaveFocusView;
  q('#add-task').onclick = () => {
    const input = q('#new-task');
    const focus = Number(q('#task-estimate').value);
    const rest = Number(q('#task-break').value);
    if (!input.value.trim()) return showToast('请先填写任务名称。');
    if (!validMinutes(focus, 1, 600) || !validMinutes(rest, 0, 60)) return showToast('请检查专注和休息时长。');
    bridge?.add_task(input.value.trim(), focus, rest, q('#task-repeat').checked);
    input.value = '';
    q('#task-repeat').checked = false;
    showToast('任务已加入清单。');
  };
  q('#new-task').addEventListener('keydown', event => { if (event.key === 'Enter') q('#add-task').click(); });
  q('#task-search').oninput = () => renderTasks(allTasks);
  q('#task-modal-close').onclick = closeTaskEditor;
  q('#task-modal-cancel').onclick = closeTaskEditor;
  q('#task-modal-save').onclick = saveTaskEditor;
  q('#task-modal').onclick = event => { if (event.target === q('#task-modal')) closeTaskEditor(); };
  qa('.task-filter').forEach(button => button.onclick = () => {
    taskFilter = button.dataset.filter;
    qa('.task-filter').forEach(item => item.classList.toggle('active', item === button));
    renderTasks(allTasks);
  });
  qa('.range-tab').forEach(button => button.onclick = () => {
    selectedRange = button.dataset.range;
    qa('.range-tab').forEach(item => item.classList.toggle('active', item === button));
    refreshStats();
  });
  q('#save-settings').onclick = saveSettings;
  q('#reset-settings').onclick = resetSettings;
  ['#minimize', '#focus-minimize'].forEach(selector => { q(selector).onclick = () => bridge?.minimize_window(); });
  ['#fullscreen', '#focus-fullscreen'].forEach(selector => { q(selector).onclick = () => bridge?.toggle_fullscreen(); });
  ['#close', '#focus-close'].forEach(selector => { q(selector).onclick = () => bridge?.close_window(); });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!q('#task-modal').classList.contains('hidden')) closeTaskEditor();
    else if (currentView === 'focus') leaveFocusView();
  });
}

function runDiagnostics() {
  const required = ['#view-home', '#view-focus', '#view-tasks', '#view-stats', '#view-settings', '#timer-value', '#task-list', '#chart'];
  const missing = required.filter(selector => !q(selector));
  window.studyRoomDiagnostics = {
    version: STUDY_ROOM_UI_VERSION,
    missingElements: missing,
    loadedAt: new Date().toISOString(),
  };
  if (missing.length) console.error(`[自习室Web] 缺少关键界面元素: ${missing.join(', ')}`);
  else console.info(`[自习室Web] 界面版本 ${STUDY_ROOM_UI_VERSION} 已加载，结构检查通过`);
}

window.addEventListener('error', event => console.error(`[自习室Web] 未捕获错误: ${event.message}`));
runDiagnostics();
bindEvents();
connectBridge();
