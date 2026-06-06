---
name: 浏览器自动化
description: Playwright 驱动的浏览器控制（导航、点击、填表、截图）
version: 2.0
auto_activate: true
---

# 浏览器自动化

激活此技能后，你可以通过 Playwright 控制浏览器执行网页操作。

## 能力说明

- 打开网页（browser_navigate）
- 获取页面 ARIA 快照（browser_snapshot）
- 点击元素（browser_click）
- 填写表单（browser_fill）
- 截取页面截图（browser_screenshot）

## 使用流程

1. 用户说"打开某网页" → browser_navigate → 返回页面快照
2. 快照中标注了可交互元素的 [ref=eX] 标记
3. 需要点击时 → browser_click(ref="e3")
4. 需要填表时 → browser_fill(ref="e2", text="内容")
5. 需要查看页面变化 → browser_snapshot 刷新快照
6. 用户想看页面视觉效果 → browser_screenshot → describe_image

## 注意事项

- 浏览器默认可见模式（非 headless），会弹出窗口
- 需要等待页面加载时使用 browser_snapshot 检查状态
- 登录状态持久化到 `~/.lianxin/browser_profile/`
- 点击后建议调用 browser_snapshot 确认结果
