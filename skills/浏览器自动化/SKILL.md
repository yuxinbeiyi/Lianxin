---
name: 浏览器自动化
description: Playwright 驱动的浏览器控制（导航、点击、填表、按键、滚动、等待、标签页和截图）
version: 2.0
auto_activate: true
---

# 浏览器自动化

激活此技能后，你可以通过 Playwright 控制浏览器执行网页操作。

## 能力说明

- 打开网页（browser_navigate）
- 获取页面 ARIA 快照（browser_snapshot）
- 点击元素（browser_click，建议携带 snapshot_id）
- 填写表单（browser_fill，建议携带 snapshot_id）
- 发送受控按键（browser_press）
- 滚动页面（browser_scroll）
- 等待页面条件（browser_wait）
- 管理标签页（browser_tabs）
- 截取页面截图（browser_screenshot）
- 接管本机已启动浏览器（browser_connect，CDP，高风险需确认）
- 断开外部浏览器连接（browser_disconnect，不关闭外部浏览器）

## 使用流程

1. 用户说"打开某网页" → browser_navigate → 返回页面快照
2. 快照中标注 SNAPSHOT_ID 和可交互元素的 [ref=eX] 标记
3. 需要点击时 → browser_click(ref="e3", snapshot_id="snap_1")
4. 需要填表时 → browser_fill(ref="e2", text="内容", snapshot_id="snap_1")
5. 需要按 Enter/Tab 等键 → browser_press(key="Enter", ref="e2", snapshot_id="snap_1")
6. 页面内容在下方 → browser_scroll(amount=500, snapshot_id="snap_1")
7. 等待动态内容 → browser_wait(until="text", text="结果")
8. 如果返回 STALE_SNAPSHOT 或 STALE_REF → 重新调用 browser_snapshot，不要继续使用旧 ref
9. 需要查看页面变化 → browser_snapshot 刷新快照
10. 用户想看页面视觉效果 → browser_screenshot → describe_image

## 注意事项

- 浏览器默认可见模式（非 headless），会弹出窗口
- 需要等待页面加载时使用 browser_snapshot 检查状态
- 登录状态持久化到 `~/.lianxin/browser_profile/`
- 点击后建议调用 browser_snapshot 确认结果
- 每次页面变化后 ref 可能失效，必须使用最新快照中的 ref
- browser_wait 不接受任意 JavaScript 条件
- 标签页使用 page_id 管理，切换后必须重新获取页面快照
- 浏览器能力可在能力中心关闭；关闭后工具不会注入模型，也会被执行层拒绝
- 提交、发送、删除、上传、支付、登录和关闭标签页等高风险动作必须经过用户确认
- 用户可选择“仅此操作”或“本次任务允许”；授权只在当前任务内生效，不会写入配置
- 输入框当前值不会进入页面快照；密码、Cookie、Token、邮箱和 URL 查询凭据会在界面与审计日志中脱敏
- 每次任务的脱敏审计日志写入 `logs/browser_tasks.jsonl`，可用于定位工具未调用、快照过期和动作失败
- 用户发送“取消/停止”或点击任务取消后，浏览器任务会立即进入 cancelled 状态，不会继续执行后续动作
- 每条审计事件包含 task_id、step、tool、ref、snapshot_id、url、duration_ms、ok 和 error_code 等字段
- 能力中枢顶部的“浏览器日志”可以查看最近任务步骤；日志文件超过 5 MiB 时会自动轮换
- CDP 接管只允许连接本机 loopback 地址（127.0.0.1、localhost、::1），不会连接远程调试主机
- CDP 断开时只释放 Playwright 连接，不会关闭用户已经打开的浏览器窗口
