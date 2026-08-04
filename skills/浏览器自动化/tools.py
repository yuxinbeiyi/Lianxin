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
                    },
                    "snapshot_id": {
                        "type": "string",
                        "description": "可选，来自最近一次 browser_snapshot 的 SNAPSHOT_ID"
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
                    },
                    "snapshot_id": {
                        "type": "string",
                        "description": "可选，来自最近一次 browser_snapshot 的 SNAPSHOT_ID"
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
    {
        "type": "function",
        "function": {
            "name": "browser_press",
            "description": (
                "向当前网页发送受控按键，例如 Enter、Tab、Escape 或方向键。"
                "可选 ref，填写时会先聚焦该元素。禁止关闭窗口或清理数据的高风险快捷键。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "按键名称，如 Enter、Tab、Escape、Control+A"},
                    "ref": {"type": "string", "description": "可选，来自最近一次 browser_snapshot 的元素 ref"},
                    "snapshot_id": {"type": "string", "description": "可选，来自最近一次 browser_snapshot 的 SNAPSHOT_ID"},
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "滚动当前网页，正数向下、负数向上；单次最多 2000 像素，操作后返回新的页面快照。",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "滚动像素，正数向下、负数向上，默认 300"},
                    "ref": {"type": "string", "description": "可选，滚动到该 ref 所在区域"},
                    "snapshot_id": {"type": "string", "description": "可选，使用 ref 时来自最近一次快照的 SNAPSHOT_ID"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait",
            "description": (
                "等待网页稳定或等待指定条件出现。until 只能使用 time、domcontentloaded、"
                "network_idle、text、ref_visible、url_contains，不允许任意 JavaScript。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number", "description": "等待秒数，默认 1，单次最多 30 秒"},
                    "until": {"type": "string", "enum": ["time", "domcontentloaded", "network_idle", "text", "ref_visible", "url_contains"], "description": "等待条件，默认 time"},
                    "text": {"type": "string", "description": "until=text 时等待出现的文字"},
                    "ref": {"type": "string", "description": "until=ref_visible 时等待的元素 ref"},
                    "value": {"type": "string", "description": "until=url_contains 时 URL 必须包含的片段"},
                    "snapshot_id": {"type": "string", "description": "until=ref_visible 时来自最近一次快照的 SNAPSHOT_ID"},
                    "refresh_snapshot": {"type": "boolean", "description": "完成后是否返回新的页面快照，默认 true"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_tabs",
            "description": "查看、切换、新建或关闭莲心浏览器标签页。list 返回 page_id；select 后返回该页新快照；最后一个标签页不能关闭。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "select", "new", "close"], "description": "标签页动作，默认 list"},
                    "page_id": {"type": "string", "description": "select/close 使用的 page_id，如 p1"},
                    "url": {"type": "string", "description": "new 时可选，创建后导航到该网址"},
                    "confirm": {"type": "boolean", "description": "close 时确认关闭可能含未提交表单的页面，默认 false"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_connect",
            "description": (
                "连接用户已启动的本机 Chrome/Edge DevTools 调试端口并接管当前标签页。"
                "仅允许 localhost、127.0.0.1 或 ::1；这是高风险动作，必须经过用户确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "本机 CDP 地址，如 http://127.0.0.1:9222；不填写则使用本地配置",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_disconnect",
            "description": "断开莲心与外部浏览器的 CDP 连接，不会关闭用户的 Chrome/Edge。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
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


def _browser_click(ref: str, snapshot_id: str = "") -> str:
    """点击 ref 标记的元素。"""
    try:
        from brain.browser_controller import get_browser
        browser = get_browser()
        return browser.click(ref, snapshot_id or None)
    except Exception as e:
        return f"点击失败: {e}"


def _browser_fill(ref: str, text: str, snapshot_id: str = "") -> str:
    """向 ref 输入框填表。"""
    try:
        from brain.browser_controller import get_browser
        browser = get_browser()
        return browser.fill(ref, text, snapshot_id or None)
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


def _browser_press(key: str, ref: str = "", snapshot_id: str = "") -> str:
    try:
        from brain.browser_controller import get_browser
        return get_browser().press(key, ref or None, snapshot_id or None)
    except Exception as e:
        return f"按键失败: {e}"


def _browser_scroll(amount: int = 300, ref: str = "", snapshot_id: str = "") -> str:
    try:
        from brain.browser_controller import get_browser
        return get_browser().scroll(amount, ref or None, snapshot_id or None)
    except Exception as e:
        return f"滚动失败: {e}"


def _browser_wait(inp: dict) -> str:
    try:
        from brain.browser_controller import get_browser
        return get_browser().wait(
            seconds=inp.get("seconds", 1.0),
            until=inp.get("until", "time"),
            text=inp.get("text", ""),
            ref=inp.get("ref", ""),
            value=inp.get("value", ""),
            refresh_snapshot=bool(inp.get("refresh_snapshot", True)),
            snapshot_id=inp.get("snapshot_id") or None,
        )
    except Exception as e:
        return f"等待失败: {e}"


def _browser_tabs(inp: dict) -> str:
    try:
        from brain.browser_controller import get_browser
        browser = get_browser()
        action = str(inp.get("action", "list") or "list").lower()
        if action == "list":
            return browser.list_tabs()
        if action == "select":
            return browser.select_tab(inp.get("page_id", ""))
        if action == "new":
            return browser.new_tab(inp.get("url") or None)
        if action == "close":
            return browser.close_tab(inp.get("page_id", ""), bool(inp.get("confirm", False)))
        return f"标签页操作失败：不支持的 action={action}。"
    except Exception as e:
        return f"标签页操作失败: {e}"


def _browser_connect(inp: dict) -> str:
    try:
        from brain.browser_controller import get_browser
        return get_browser().connect_cdp(inp.get("endpoint") or None)
    except Exception as e:
        return f"浏览器 CDP 连接失败: {e}"


def _browser_disconnect() -> str:
    try:
        from brain.browser_controller import get_browser
        return get_browser().disconnect_cdp()
    except Exception as e:
        return f"浏览器 CDP 断开失败: {e}"


TOOL_EXECUTORS = {
    "browser_navigate":   lambda inp: _browser_navigate(inp["url"]),
    "browser_snapshot":   lambda inp: _browser_snapshot(),
    "browser_click":      lambda inp: _browser_click(inp["ref"], inp.get("snapshot_id", "")),
    "browser_fill":       lambda inp: _browser_fill(inp["ref"], inp["text"], inp.get("snapshot_id", "")),
    "browser_screenshot": lambda inp: _browser_screenshot(),
    "browser_press":     lambda inp: _browser_press(inp["key"], inp.get("ref", ""), inp.get("snapshot_id", "")),
    "browser_scroll":    lambda inp: _browser_scroll(inp.get("amount", 300), inp.get("ref", ""), inp.get("snapshot_id", "")),
    "browser_wait":      _browser_wait,
    "browser_tabs":      _browser_tabs,
    "browser_connect":   _browser_connect,
    "browser_disconnect": _browser_disconnect,
}
