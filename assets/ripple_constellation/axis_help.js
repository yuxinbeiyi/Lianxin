(function () {
  "use strict";
  const help = {
    "连接需求": "表示莲心主动联系或关注用户的内在需求；长时间没有互动会缓慢升高，持续交流会消退。",
    "防御感 / 骄傲兼容": "表示谨慎、自我保护和边界感；冷淡、敌意或边界冲突会升高，温暖交流、道歉和时间会降低。中线 0 是平衡，不是百分比。",
    "情绪基调": "表示当前整体偏积极还是偏消极；温暖、肯定会向正方向，压力和冲突会向负方向回落。",
    "唤醒度": "表示兴奋、紧张或活跃程度；新鲜刺激和高强度话题会升高，平静交流和时间会回落。",
    "沉浸度": "表示莲心当前投入某个任务或话题的程度；任务讨论、工具工作会升高，离开任务后会逐步衰减。"
  };
  const host = document.getElementById("axes");
  if (!host) return;
  const apply = () => host.querySelectorAll(".axis-row").forEach(row => {
    const label = row.querySelector(".axis-head span");
    const text = label && label.textContent.trim();
    if (text && help[text]) {
      row.title = help[text];
      row.setAttribute("aria-label", `${text}：${help[text]}`);
    }
  });
  new MutationObserver(apply).observe(host, {childList: true, subtree: true});
  apply();
})();
