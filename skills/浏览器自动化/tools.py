"""
浏览器自动化技能 — 自定义工具
Playwright 驱动 Chromium/Edge 浏览器控制
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": (
                "打开指定网址，返回页面结构和可交互元素列表（ARIA 快照）。"
                "页面元素会标注 [ref=eX] 标记，供后续点击或填表使用。"
                "适用：打开网页、导航到新页面。"
                "注：此工具会自动启动浏览器，无需先调用 open_app 打开浏览器。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要打开的网页 URL，如 https://www.baidu.com"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": (
                "获取当前浏览器页面的最新 ARIA 快照，显示所有可交互元素及其 [ref=eX] 标记。"
                "在点击按钮、填写表单后页面内容发生变化时，用此工具刷新页面结构。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": (
                "点击页面上指定 ref 标记对应的元素（按钮、链接等）。"
                "ref 值来自 browser_navigate 或 browser_snapshot 返回的快照中的 [ref=eX]。"
                "点击后建议调用 browser_snapshot 查看页面变化。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {
                        "type": "string",
                        "description": "要点击的元素 ref 标记，如 e3"
                    }
                },
                "required": ["ref"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": (
                "向页面上指定 ref 标记的输入框填写文字。"
                "ref 值来自快照中的 [ref=eX]。"
                "填写后建议调用 browser_snapshot 查看效果。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {
                        "type": "string",
                        "description": "要填写的输入框 ref 标记，如 e2"
                    },
                    "text": {
                        "type": "string",
                        "description": "要填入的文字内容"
                    }
                },
                "required": ["ref", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": (
                "截取当前浏览器页面的可见区域，保存为 PNG 图片。"
                "返回临时文件路径，可用于 describe_image 进行视觉分析。"
                "适用：用户想看页面长什么样、页面快照不够直观时。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
]


# ── 浏览器自动化工具函数 ──────────────────────────────────────

def _browser_navigate(url: str) -> str:
    """打开网页，返回 ARIA 快照。"""
    try:
        from brain.browser_controller import get_browser
        browser = get_browser()
        return browser.navigate(url)
    except Exception as e:
        return f"浏览器导航失败: {e}"


def _browser_snapshot() -> str:
    """获取当前页面 ARIA 快照。"""
    try:
        from brain.browser_controller import get_browser
        browser = get_browser()
        return browser.snapshot()
    except Exception as e:
        return f"获取页面快照失败: {e}"


def _browser_click(ref: str) -> str:
    """点击 ref 标记的元素。"""
    try:
        from brain.browser_controller import get_browser
        browser = get_browser()
        return browser.click(ref)
    except Exception as e:
        return f"点击失败: {e}"


def _browser_fill(ref: str, text: str) -> str:
    """向 ref 输入框填表。"""
    try:
        from brain.browser_controller import get_browser
        browser = get_browser()
        return browser.fill(ref, text)
    except Exception as e:
        return f"填写失败: {e}"


def _browser_screenshot() -> str:
    """截取当前页面并返回文件路径。"""
    try:
        from brain.browser_controller import get_browser
        browser = get_browser()
        path = browser.screenshot()
        return f"截图已保存: {path}\n可使用 describe_image 工具查看截图内容。"
    except Exception as e:
        return f"截图失败: {e}"


TOOL_EXECUTORS = {
    "browser_navigate":   lambda inp: _browser_navigate(inp["url"]),
    "browser_snapshot":   lambda inp: _browser_snapshot(),
    "browser_click":      lambda inp: _browser_click(inp["ref"]),
    "browser_fill":       lambda inp: _browser_fill(inp["ref"], inp["text"]),
    "browser_screenshot": lambda inp: _browser_screenshot(),
}
