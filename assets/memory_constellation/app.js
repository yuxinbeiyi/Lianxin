(() => {
  // A self-contained Canvas 2D renderer with mouse parallax. It intentionally mirrors the
  // MemoryConstellations interaction model while using Lianxin's own records.
  let data = window.LIANXIN_MEMORY_DATA || {};
  if (window.qt && window.QWebChannel) {
    new QWebChannel(qt.webChannelTransport, channel => {
      window.lianxinBridge = channel.objects.lianxinBridge;
    });
  }

  const bg = document.getElementById('bg');
  const map = document.getElementById('map');
  const bx = bg.getContext('2d');
  const ctx = map.getContext('2d');
  let W = 0, H = 0, dpr = 1, time = 0;
  let mx = 0, my = 0, zoom = 1, panX = 0, panY = 0;
  let dragging = false, moved = false, lastX = 0, lastY = 0;
  let level = 'universe', activeGalaxy = null, selected = null, hover = null;
  let hitPoints = [];
  const nebulaCache = new Map();
  const stars = Array.from({ length: 520 }, (_, i) => ({
    x: (i * 0.61803398875) % 1, y: (i * 0.38196601125) % 1,
    r: .2 + (i % 9) * .13, phase: i * .73, alpha: .08 + (i % 7) * .035
  }));
  const core = data.core || { user: '主人', assistant: '莲心' };
  // Legacy 人物星系 is intentionally presented as the clearer 社交星系 in Lianxin.
  const GALAXIES = [
    { id: 'hobbies', name: '爱好星系', color: '#ff91c8', match: ['interest', 'preference', 'hobby', 'preferences', '爱好', '偏好'] },
    { id: 'contribution', name: '贡献星系', color: '#f5e4a9', match: ['contribution', 'project', 'work', 'achievement', '贡献', '项目'] },
    { id: 'places', name: '地点星系', color: '#72d9b2', match: ['place', 'location', '地点'] },
    { id: 'social', name: '社交星系', color: '#d5ae72', match: ['person', 'people', 'organization', 'social', '人物', '社交'] },
    { id: 'events', name: '事件星系', color: '#71e19a', match: ['event', 'events', 'episode', '经历', '事件'] },
    { id: 'persona', name: '人格星系', color: '#b98cff', match: ['profile', 'behavior', 'behaviors', 'persona', '人格', '行为'] }
  ];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const arr = value => { try { return typeof value === 'string' ? JSON.parse(value || '[]') : (value || []); } catch (_) { return []; } };
  const typeOf = item => String(item.entity_type || item.category || '').toLowerCase();
  const keyOf = item => `${item.kind || 'entity'}:${item.id}`;
  const galaxyFor = item => {
    const type = typeOf(item);
    return GALAXIES.find(g => g.match.some(token => type.includes(token))) || GALAXIES[1];
  };
  const entities = () => (data.entities || []).map(item => ({ ...item, kind: 'entity', label: item.name || '未命名实体' }));
  const facts = () => (data.facts || []).map(item => ({ ...item, kind: 'fact', label: item.label || item.content || '未命名记忆' }));
  function galaxyItems(galaxy) {
    const items = [...entities(), ...facts()].filter(item => galaxyFor(item).id === galaxy.id);
    if (galaxy.id === 'events') {
      items.push(...(data.episodes || []).map(item => ({ ...item, kind: 'episode', label: item.title || '未命名经历', entity_type: 'event' })));
    }
    if (galaxy.id === 'contribution') {
      items.push(...(data.sagas || []).map(item => ({ ...item, kind: 'saga', label: item.title || '未命名故事', entity_type: 'project' })));
    }
    if (galaxy.id === 'persona') {
      items.unshift({ id: 'user-core', kind: 'core', side: 'user', label: core.user, entity_type: 'profile' });
      items.unshift({ id: 'assistant-core', kind: 'core', side: 'ai', label: core.assistant, entity_type: 'persona' });
    }
    return items;
  }
  function sourceIds(item) { return data.source_ids?.[keyOf(item)] || data.source_ids?.[String(item.id)] || []; }
  function relatedItems(item) {
    const ids = new Set(arr(item.entity_ids).map(Number));
    const factIds = new Set(arr(item.source_fact_ids).map(Number));
    if (item.kind === 'saga') {
      for (const episodeId of arr(item.episode_ids)) {
        const episode = (data.episodes || []).find(row => Number(row.id) === Number(episodeId));
        if (episode) arr(episode.entity_ids).forEach(id => ids.add(Number(id)));
      }
    }
    const rows = entities().filter(row => ids.has(Number(row.id)));
    rows.push(...facts().filter(row => factIds.has(Number(row.id))));
    if (item.kind === 'entity') {
      rows.push(...(data.episodes || []).filter(row => arr(row.entity_ids).map(Number).includes(Number(item.id))).map(row => ({ ...row, kind: 'episode', label: row.title || '未命名经历', entity_type: 'event' })));
    }
    return rows.filter(row => keyOf(row) !== keyOf(item)).slice(0, 80);
  }
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2); W = innerWidth; H = innerHeight;
    [bg, map].forEach(canvas => { canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.width = `${W}px`; canvas.style.height = `${H}px`; });
    bx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); nebulaCache.clear();
  }
  const rgba = (hex, alpha) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${n >> 8 & 255},${n & 255},${alpha})`; };
  function drawBackground() {
    bx.clearRect(0, 0, W, H); bx.fillStyle = '#020410'; bx.fillRect(0, 0, W, H);
    const gradient = bx.createRadialGradient(W * .5, H * .44, 0, W * .5, H * .44, Math.max(W, H) * .78);
    gradient.addColorStop(0, '#141d4a'); gradient.addColorStop(1, '#020410'); bx.fillStyle = gradient; bx.fillRect(0, 0, W, H);
    for (const [x, y, hue] of [[.18, .23, 235], [.78, .62, 280], [.47, .86, 205]]) {
      const neb = bx.createRadialGradient(W * x + mx * 35, H * y + my * 24, 0, W * x + mx * 35, H * y + my * 24, Math.max(W, H) * .36);
      neb.addColorStop(0, `hsla(${hue},65%,55%,.12)`); neb.addColorStop(1, 'transparent'); bx.fillStyle = neb; bx.fillRect(0, 0, W, H);
    }
    for (const star of stars) { bx.beginPath(); bx.arc(star.x * W + mx * 9, star.y * H + my * 7, star.r, 0, Math.PI * 2); bx.fillStyle = `rgba(210,225,255,${star.alpha * (.65 + .35 * Math.sin(time * .8 + star.phase))})`; bx.fill(); }
  }
  function prerenderNebula(galaxy) {
    const canvas = document.createElement('canvas'); const size = Math.ceil(Math.min(W, H) * .4); canvas.width = canvas.height = size;
    const neb = canvas.getContext('2d'), radius = size * .5;
    let seed = galaxy.id.split('').reduce((sum, char) => sum + char.charCodeAt(0), 17);
    const random = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
    for (let i = 0; i < 12; i++) { const x = radius + (random() - .5) * radius, y = radius + (random() - .5) * radius, br = radius * (.22 + random() * .34); const glow = neb.createRadialGradient(x, y, 0, x, y, br); glow.addColorStop(0, rgba(galaxy.color, .18)); glow.addColorStop(1, 'transparent'); neb.fillStyle = glow; neb.beginPath(); neb.arc(x, y, br, 0, Math.PI * 2); neb.fill(); }
    nebulaCache.set(galaxy.id, canvas);
  }
  const world = (x, y, depth = 1) => ({ x: W / 2 + (x - W / 2) * zoom + panX * depth, y: H / 2 + (y - H / 2) * zoom + panY * depth });
  function nebula(galaxy, x, y, radius) { if (!nebulaCache.has(galaxy.id)) prerenderNebula(galaxy); const image = nebulaCache.get(galaxy.id); ctx.globalAlpha = .8; ctx.drawImage(image, x - image.width * .5 + mx * 22, y - image.height * .5 + my * 16, image.width, image.height); ctx.globalAlpha = 1; ctx.strokeStyle = rgba(galaxy.color, .22); ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, radius * (1 + .025 * Math.sin(time * .5)), 0, Math.PI * 2); ctx.stroke(); }
  function galaxyLayout() { const centerX = W / 2, centerY = H / 2, radius = Math.min(W, H) * .29; return GALAXIES.map((galaxy, index) => { const angle = index * Math.PI * 2 / GALAXIES.length - .5; return { galaxy, x: centerX + Math.cos(angle) * radius * (W > H ? 1.28 : .92), y: centerY + Math.sin(angle) * radius, radius: Math.min(W, H) * .105 + Math.sqrt(galaxyItems(galaxy).length + 1) * 4 }; }); }
  function itemLayout(galaxy) { const list = galaxyItems(galaxy), centerX = W / 2, centerY = H / 2, radius = Math.min(W, H) * .37; return list.map((item, index) => { const angle = index * 2.399 + Math.sin(index * 5) * .1, distance = radius * Math.sqrt((index + .5) / Math.max(1, list.length)); return { item, x: centerX + Math.cos(angle) * distance, y: centerY + Math.sin(angle) * distance, radius: 7 + Math.min(11, Math.sqrt(Number(item.mention_count) || 1)), depth: .94 }; }); }
  function detailLayout(item) { const rows = relatedItems(item), centerX = W / 2, centerY = H / 2; return [{ item, x: centerX, y: centerY, radius: 19, depth: 1 }, ...rows.map((row, index) => { const angle = index * 2.399, distance = Math.min(W, H) * (.18 + .15 * Math.sqrt((index + 1) / Math.max(1, rows.length))); return { item: row, x: centerX + Math.cos(angle) * distance, y: centerY + Math.sin(angle) * distance, radius: 7 + Math.min(8, Math.sqrt(Number(row.mention_count) || 1)), depth: .95 }; })]; }
  function star(x, y, radius, color, alpha = 1, hot = false) { const glow = ctx.createRadialGradient(x, y, 0, x, y, radius * 4); glow.addColorStop(0, rgba(color, .4 * alpha)); glow.addColorStop(1, 'transparent'); ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(x, y, radius * 4, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = alpha; ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, radius * (hot ? 1.35 : 1), 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1; if (hot) { ctx.strokeStyle = rgba(color, .8); ctx.beginPath(); ctx.arc(x, y, radius * 2.3, 0, Math.PI * 2); ctx.stroke(); } }
  function drawCore() { const position = world(W / 2, H / 2), x = position.x + mx * 25, y = position.y + my * 18; ctx.strokeStyle = 'rgba(190,220,255,.3)'; ctx.beginPath(); ctx.moveTo(x - 48, y); ctx.lineTo(x + 48, y); ctx.stroke(); star(x - 48, y, 10, '#ffd58a', 1, hover?.type === 'core' && hover.side === 'user'); star(x + 48, y, 9, '#b98cff', 1, hover?.type === 'core' && hover.side === 'ai'); ctx.textAlign = 'center'; ctx.font = '12px Microsoft YaHei'; ctx.fillStyle = '#ffe0aa'; ctx.fillText(core.user, x - 48, y + 30); ctx.fillStyle = '#d9c4ff'; ctx.fillText(core.assistant, x + 48, y + 30); }
  function drawBridges(points) { const byId = Object.fromEntries(points.map(point => [point.item.id, point])); for (const episode of data.episodes || []) { const ids = arr(episode.entity_ids).map(Number).filter(id => byId[id]); for (let i = 1; i < ids.length; i++) { const a = byId[ids[i - 1]], b = byId[ids[i]], pa = world(a.x, a.y, .9), pb = world(b.x, b.y, .9); ctx.save(); ctx.setLineDash([3, 8]); ctx.lineDashOffset = -time * 28; ctx.strokeStyle = 'rgba(140,190,255,.28)'; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke(); ctx.restore(); } } }
  function draw() {
    drawBackground(); ctx.clearRect(0, 0, W, H); drawCore(); hitPoints = [];
    if (level === 'universe') {
      for (const point of galaxyLayout()) { const position = world(point.x, point.y, .55); nebula(point.galaxy, position.x, position.y, point.radius); star(position.x, position.y, 15, point.galaxy.color, .9, hover?.galaxy === point.galaxy); ctx.fillStyle = rgba(point.galaxy.color, .9); ctx.font = '13px Microsoft YaHei'; ctx.textAlign = 'center'; ctx.fillText(point.galaxy.name, position.x, position.y + point.radius + 19); ctx.fillStyle = 'rgba(190,205,245,.65)'; ctx.font = '11px Microsoft YaHei'; ctx.fillText(`${galaxyItems(point.galaxy).length} 星座`, position.x, position.y + point.radius + 36); hitPoints.push({ type: 'galaxy', galaxy: point.galaxy, x: position.x, y: position.y, radius: point.radius }); }
    } else if (level === 'galaxy') {
      const galaxy = activeGalaxy || GALAXIES[0], points = itemLayout(galaxy); drawBridges(points);
      points.forEach(point => { const position = world(point.x, point.y, point.depth), color = point.item.kind === 'core' ? (point.item.side === 'ai' ? '#b98cff' : '#ffd58a') : galaxy.color; star(position.x, position.y, point.radius, color, .85, hover?.item === point.item); ctx.fillStyle = 'rgba(225,235,255,.84)'; ctx.font = '12px Microsoft YaHei'; ctx.textAlign = 'left'; ctx.fillText(point.item.label, position.x + 14, position.y + 4); hitPoints.push({ type: 'item', item: point.item, x: position.x, y: position.y, radius: point.radius * 2.5 }); });
    } else {
      const points = selected ? (level === 'constellation' ? detailLayout(selected) : [{ item: selected, x: W / 2, y: H / 2, radius: 25, depth: 1 }]) : [];
      if (points.length) { const center = points[0], centerPosition = world(center.x, center.y, center.depth); points.slice(1).forEach(point => { const position = world(point.x, point.y, point.depth); ctx.strokeStyle = 'rgba(140,190,255,.28)'; ctx.setLineDash([2, 7]); ctx.lineDashOffset = -time * 24; ctx.beginPath(); ctx.moveTo(centerPosition.x, centerPosition.y); ctx.lineTo(position.x, position.y); ctx.stroke(); ctx.setLineDash([]); }); points.forEach(point => { const position = world(point.x, point.y, point.depth), galaxy = galaxyFor(point.item); star(position.x, position.y, point.radius, galaxy.color, .95, hover?.item === point.item || point === center); ctx.fillStyle = 'rgba(225,235,255,.88)'; ctx.textAlign = 'center'; ctx.font = `${point === center ? 14 : 11}px Microsoft YaHei`; ctx.fillText(point.item.label, position.x, position.y + point.radius + 17); hitPoints.push({ type: 'item', item: point.item, x: position.x, y: position.y, radius: point.radius * 2.5 }); }); }
    }
    requestAnimationFrame(draw); time += .015;
  }
  function hit(x, y) { for (let i = hitPoints.length - 1; i >= 0; i--) { const point = hitPoints[i]; if (Math.hypot(x - point.x, y - point.y) < point.radius) return point; } const center = world(W / 2, H / 2); if (Math.hypot(x - center.x, y - center.y) < 80) return { type: 'core', side: x < center.x ? 'user' : 'ai' }; return null; }
  function updateBottom(item) {
    const title = document.getElementById('journal-title'), body = document.getElementById('journal-body');
    if (!item) { title.textContent = '观星手记'; body.textContent = '点击星体查看记忆详情'; return; }
    title.textContent = item.label || '未命名记忆'; body.textContent = item.summary || item.content || item.current_status || '暂无摘要';
  }
  function showDetail(item) {
    selected = item; updateBottom(item); const ids = sourceIds(item); const kind = item.kind === 'episode' ? '经历星座' : item.kind === 'saga' ? '长期故事' : item.kind === 'fact' ? '历史记忆' : item.kind === 'core' ? '人格核心' : '实体星体';
    document.getElementById('panel-content').innerHTML = `<h2>${esc(item.label)}</h2><div class="meta">${kind} · 置信度 ${Math.round((Number(item.confidence ?? item.quality_score ?? .6)) * 100)}%</div><div class="summary">${esc(item.summary || item.content || item.current_status || '暂无摘要')}</div><div class="tags"><span class="tag">${esc(item.entity_type || item.category || 'memory')}</span><span class="tag">来源 ${ids.length ? `${ids.length} 条` : '待补充'}</span></div>${item.kind === 'core' ? '' : '<button class="panel-action" id="open-source">打开原始消息</button>'}`;
    const sourceButton = document.getElementById('open-source'); if (sourceButton) sourceButton.onclick = () => window.lianxinBridge?.openOriginalMessages(JSON.stringify(ids));
    document.getElementById('panel').classList.remove('hidden');
  }
  function renderDust() { const dateSelect = document.getElementById('dust-date'); if (dateSelect && dateSelect.options.length === 1) { [...new Set((data.events || []).map(event => String(event.created_at || '').slice(0, 10)).filter(Boolean))].sort().reverse().forEach(date => { const option = document.createElement('option'); option.value = date; option.textContent = date; dateSelect.appendChild(option); }); } const query = (document.getElementById('dust-query')?.value || '').trim().toLowerCase(), date = dateSelect?.value || 'all'; let events = [...(data.events || [])].reverse(); if (query) events = events.filter(event => JSON.stringify(event).toLowerCase().includes(query)); if (date !== 'all') events = events.filter(event => String(event.created_at || '').startsWith(date)); document.getElementById('dust-body').innerHTML = events.slice(0, 40).map(event => `<div class="dust-row"><b>${esc(event.event_type || 'memory')}</b><span>${esc(event.created_at || '')}</span><small>${esc(event.entity_type || '')} #${esc(event.entity_id || '')}</small></div>`).join('') || '<div class="empty">暂无符合条件的星尘事件</div>'; }
  function showDust() { document.getElementById('dust-panel').classList.toggle('collapsed'); renderDust(); }
  function showModel() { const model = data.model || {}, maintenance = data.maintenance || {}, stats = maintenance.stats || {}; document.getElementById('model-body').innerHTML = `<h3>认知模型状态</h3><span>叙事整合：${esc(model.status || '未运行')}</span><span>候选碎片：${esc(model.candidates || 0)}</span><span>最近完成：${esc(model.finished_at || '暂无')}</span><hr><span>后台维护：${esc(maintenance.status || '未运行')}</span><span>维护统计：清理 ${esc(stats.expired || 0)} · 合并 ${esc(stats.merged || 0)} · 冲突 ${esc(stats.conflicts || 0)}</span><span>维护完成：${esc(maintenance.finished_at || '暂无')}</span>`; document.getElementById('model-panel').classList.toggle('collapsed'); }
  function showTooltip(target, x, y) { const tip = document.getElementById('tooltip'); if (!target) { tip.style.display = 'none'; return; } const label = target.type === 'galaxy' ? `${target.galaxy.name} · ${galaxyItems(target.galaxy).length} 星座` : target.type === 'core' ? `${target.side === 'user' ? core.user : core.assistant} · 双星核心` : target.item?.label || ''; tip.textContent = label; tip.style.left = `${Math.min(innerWidth - 280, x + 14)}px`; tip.style.top = `${Math.min(innerHeight - 46, y + 14)}px`; tip.style.display = 'block'; }
  function setLevel(next, galaxy = activeGalaxy) { level = next; activeGalaxy = galaxy || activeGalaxy; const path = next === 'universe' ? '记忆宇宙 · 双星核心' : `记忆宇宙 · ${activeGalaxy?.name || ''} · ${next === 'galaxy' ? '星座导航' : next === 'constellation' ? '星体关联' : '记忆详情'}`; document.getElementById('breadcrumb').textContent = path; document.getElementById('back').style.display = next === 'universe' ? 'none' : 'block'; }
  function rebuildFilters() { const nav = document.getElementById('filters'); nav.querySelectorAll('.galaxy-pill').forEach(button => button.remove()); GALAXIES.forEach(galaxy => { const button = document.createElement('button'); button.className = 'pill galaxy-pill'; button.textContent = galaxy.name; button.onclick = () => { activeGalaxy = galaxy; selected = null; setLevel('galaxy', galaxy); nav.querySelectorAll('.pill').forEach(item => item.classList.remove('active')); button.classList.add('active'); }; nav.appendChild(button); }); }
  function updateCount() { document.getElementById('count').textContent = `· ${(data.entities || []).length + (data.facts || []).length} fragments / ${GALAXIES.length} galaxies`; }
  function refreshSnapshot() { if (!window.lianxinBridge?.refreshSnapshot) { location.reload(); return; } window.lianxinBridge.refreshSnapshot(raw => { try { const next = JSON.parse(raw || '{}'); if (next.error) throw new Error(next.error); data = next; selected = null; rebuildFilters(); updateCount(); const dateSelect = document.getElementById('dust-date'); if (dateSelect) dateSelect.innerHTML = '<option value="all">全部日期</option>'; setLevel('universe', null); updateBottom(null); toast('记忆快照已刷新'); } catch (error) { toast(`刷新失败：${error.message}`); } }); }
  let toastTimer; function toast(message) { const element = document.getElementById('toast'); element.textContent = message; element.classList.add('toast-show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => element.classList.remove('toast-show'), 2200); }
  function init() {
    resize(); rebuildFilters(); setLevel('universe', null); updateBottom(null); updateCount();
    document.getElementById('close').onclick = () => document.getElementById('panel').classList.add('hidden'); document.getElementById('refresh').onclick = refreshSnapshot; document.getElementById('stardust').onclick = showDust; document.getElementById('model-toggle').onclick = showModel; document.getElementById('dust-close').onclick = () => document.getElementById('dust-panel').classList.add('collapsed'); document.getElementById('model-close').onclick = () => document.getElementById('model-panel').classList.add('collapsed');
    document.getElementById('dust-query')?.addEventListener('input', renderDust); document.getElementById('dust-date')?.addEventListener('change', renderDust); document.getElementById('cognition-open')?.addEventListener('click', showModel);
    map.addEventListener('mousemove', event => { mx = (event.offsetX / W - .5) * 2; my = (event.offsetY / H - .5) * 2; if (!dragging) { hover = hit(event.offsetX, event.offsetY); showTooltip(hover, event.clientX, event.clientY); } }); map.addEventListener('mouseleave', () => { mx = my = 0; hover = null; showTooltip(null); }); map.addEventListener('wheel', event => { event.preventDefault(); zoom = Math.max(.55, Math.min(2.5, zoom * (event.deltaY < 0 ? 1.1 : .9))); }, { passive: false }); map.addEventListener('mousedown', event => { dragging = true; moved = false; map.classList.add('dragging'); lastX = event.clientX; lastY = event.clientY; }); window.addEventListener('mouseup', () => { dragging = false; map.classList.remove('dragging'); }); window.addEventListener('mousemove', event => { if (dragging) { const dx = event.clientX - lastX, dy = event.clientY - lastY; if (Math.abs(dx) + Math.abs(dy) > 2) moved = true; panX += dx; panY += dy; lastX = event.clientX; lastY = event.clientY; } });
    let touchDistance = 0; map.addEventListener('touchstart', event => { if (event.touches.length === 2) touchDistance = Math.hypot(event.touches[1].clientX - event.touches[0].clientX, event.touches[1].clientY - event.touches[0].clientY); }, { passive: true }); map.addEventListener('touchmove', event => { if (event.touches.length === 2 && touchDistance) { event.preventDefault(); const distance = Math.hypot(event.touches[1].clientX - event.touches[0].clientX, event.touches[1].clientY - event.touches[0].clientY); zoom = Math.max(.55, Math.min(2.5, zoom * distance / touchDistance)); touchDistance = distance; } }, { passive: false }); map.addEventListener('touchend', () => { touchDistance = 0; });
    map.addEventListener('click', event => { if (moved) return; const target = hit(event.offsetX, event.offsetY); if (!target) return; if (target.type === 'galaxy') { activeGalaxy = target.galaxy; setLevel('galaxy', target.galaxy); } else if (target.type === 'item') { if (level === 'galaxy') { activeGalaxy = activeGalaxy || galaxyFor(target.item); showDetail(target.item); setLevel('constellation', activeGalaxy); } else if (level === 'constellation') { showDetail(target.item); setLevel('star', activeGalaxy); } else { showDetail(target.item); } } else if (target.type === 'core') showModel(); });
    document.getElementById('back').onclick = () => { if (level === 'star') { setLevel('constellation', activeGalaxy); } else if (level === 'constellation') { selected = null; setLevel('galaxy', activeGalaxy); } else setLevel('universe', null); }; window.addEventListener('keydown', event => { if (event.target.matches('input,select,textarea')) return; if (event.key === '0' || event.key === '`') setLevel('universe', null); else if (event.key === 'Escape') document.getElementById('back').click(); else if (/^[1-6]$/.test(event.key)) { activeGalaxy = GALAXIES[Number(event.key) - 1]; setLevel('galaxy', activeGalaxy); } }); window.addEventListener('resize', resize); draw();
  }
  init();
})();
