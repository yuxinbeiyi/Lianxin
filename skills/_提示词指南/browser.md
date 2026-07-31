---
triggers: ["登录", "浏览器", "打开网页并", "截图", "填表", "browser", "网页", "网站", "点击", "填", "导航", "自动化", "页面", "自动填写", "自动登录", "注册", "下单", "抢", "访问", "跳转", "表单"]
---

## 浏览器交互指南

当用户需网页交互时使用以下工具：
- browser_navigate(url) → 打开网页，返回可交互元素列表（含 [ref=eX] 标记）
- browser_fill(ref, text) → 在输入框填写文字
- browser_click(ref) → 点击按钮/链接
- browser_snapshot() → 刷新页面结构（点击/填表后使用）
- browser_screenshot() → 截取页面全貌

典型工作流：navigate → fill/click → snapshot 查看结果。
注意：每次导航/操作后 ref 标记可能变化。纯读取网页内容优先用 fetch_webpage（更快）。
