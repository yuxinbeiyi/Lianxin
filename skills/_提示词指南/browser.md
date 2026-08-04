---
triggers: ["登录", "浏览器", "打开网页并", "截图", "填表", "browser", "网页", "网站", "点击", "填", "导航", "自动化", "页面", "自动填写", "自动登录", "注册", "下单", "抢", "访问", "跳转", "表单", "接管浏览器", "CDP"]
---

## 浏览器交互指南

当用户需网页交互时使用以下工具：
- browser_navigate(url) → 打开网页，返回可交互元素列表（含 [ref=eX] 标记）
- browser_fill(ref, text, snapshot_id?) → 在输入框填写文字
- browser_click(ref, snapshot_id?) → 点击按钮/链接
- browser_snapshot() → 刷新页面结构并生成新的 SNAPSHOT_ID
- browser_press(key, ref?, snapshot_id?) → 发送 Enter、Tab、Escape 等受控按键
- browser_scroll(amount, ref?, snapshot_id?) → 滚动页面并刷新快照
- browser_wait(until, ...) → 等待页面加载、文字、元素或 URL 条件
- browser_tabs(action, page_id?, url?) → 查看、切换、新建或关闭标签页
- browser_screenshot() → 截取页面全貌
- browser_connect(endpoint?) → 用户明确要求时接管本机已启动的 Chrome/Edge（必须等待安全确认）
- browser_disconnect() → 断开外部浏览器控制，不关闭浏览器

典型工作流：navigate → snapshot（记住 SNAPSHOT_ID）→ fill/click/press（携带 snapshot_id）→ wait（如需要）→ snapshot 查看结果。
长页面先使用 browser_scroll；多页面使用 browser_tabs list/select，切换后必须重新 snapshot。
注意：每次导航/操作后 ref 标记和 SNAPSHOT_ID 都可能变化；出现 STALE_SNAPSHOT/STALE_REF 时必须重新 snapshot。纯读取网页内容优先用 fetch_webpage（更快）。
只有用户明确要求“接管我已经打开的浏览器”时才调用 browser_connect；不得主动连接未知调试端口。
