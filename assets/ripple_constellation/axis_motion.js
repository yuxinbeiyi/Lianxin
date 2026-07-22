(function () {
  "use strict";
  const host = document.getElementById("axes");
  if (!host) return;
  const targets = new Map();
  const visual = new Map();
  const phase = new Map();
  let last = performance.now();

  const keyOf = row => row.dataset.axis || row.querySelector(".axis-head span")?.textContent || "";
  const readRows = () => host.querySelectorAll(".axis-row").forEach(row => {
    const fill = row.querySelector(".axis-fill");
    const key = keyOf(row);
    if (!fill || !key) return;
    const target = {left: parseFloat(fill.style.left) || 0, width: parseFloat(fill.style.width) || 0};
    targets.set(key, target);
    if (!visual.has(key)) visual.set(key, {...target});
    if (!phase.has(key)) phase.set(key, Math.random() * Math.PI * 2);
  });

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const tick = now => {
    const dt = Math.min(0.05, Math.max(0.001, (now - last) / 1000));
    last = now;
    host.querySelectorAll(".axis-row").forEach(row => {
      const fill = row.querySelector(".axis-fill");
      const key = keyOf(row);
      const target = targets.get(key);
      if (!fill || !target) return;
      fill.style.transition = "none";
      const value = visual.get(key) || {...target};
      // 约 250ms 的跟随速度，模拟 Jiwen tick 的平滑涨潮/落潮。
      const follow = 1 - Math.exp(-dt * 8);
      value.left += (target.left - value.left) * follow;
      value.width += (target.width - value.width) * follow;
      // 仅视觉层的微弱呼吸，不写回后端状态，幅度小于半个百分点。
      const wave = Math.sin(now / 1300 + (phase.get(key) || 0));
      const widthWave = Math.cos(now / 1700 + (phase.get(key) || 0)) * 0.28;
      fill.style.left = `${clamp(value.left + wave * 0.18, 0, 100)}%`;
      fill.style.width = `${clamp(value.width + widthWave, 0, 100)}%`;
      visual.set(key, value);
    });
    requestAnimationFrame(tick);
  };

  new MutationObserver(readRows).observe(host, {childList: true, subtree: true});
  readRows();
  requestAnimationFrame(tick);
})();
