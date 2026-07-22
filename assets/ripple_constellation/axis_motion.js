(function () {
  "use strict";
  const host = document.getElementById("axes");
  if (!host) return;
  const previous = new Map();
  function animate(row) {
    const fill = row.querySelector(".axis-fill");
    if (!fill) return;
    const target = {left: parseFloat(fill.style.left) || 0, width: parseFloat(fill.style.width) || 0};
    const key = row.dataset.axis || row.querySelector('.axis-head span')?.textContent || String(row);
    const old = previous.get(key) || target;
    previous.set(key, target);
    if (Math.abs(old.left - target.left) < .01 && Math.abs(old.width - target.width) < .01) return;
    const start = performance.now();
    const step = now => {
      const t = Math.min(1, (now - start) / 720), eased = 1 - Math.pow(1 - t, 3);
      fill.style.left = `${old.left + (target.left - old.left) * eased}%`;
      fill.style.width = `${old.width + (target.width - old.width) * eased}%`;
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  new MutationObserver(() => host.querySelectorAll(".axis-row").forEach(animate))
    .observe(host, {childList: true, subtree: true});
  host.querySelectorAll(".axis-row").forEach(animate);
})();
