"""
BrowserController: Playwright 浏览器自动化单例控制器。

直接使用 Playwright Python 绑定控制 Chromium，无需 Node.js 桥接层。
通过 JS 注入提取可交互元素并分配自定义 ref 标记，让 LLM 理解页面结构并与之交互。
"""

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from config import get_browser_config
from brain.browser_security import append_browser_audit, redact_browser_text, redact_url

logger = logging.getLogger("BrowserController")

_ALLOWED_BROWSER_KEYS = {
    "Enter", "Tab", "Escape", "Space", "Backspace", "Delete",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "Home", "End", "PageUp", "PageDown",
}
_ALLOWED_BROWSER_MODIFIERS = {"Control", "Shift", "Alt", "Meta"}
_BLOCKED_BROWSER_KEYS = {
    "Alt+F4", "Control+W", "Control+Shift+Delete", "Meta+W",
}

_USER_DATA_DIR = Path.home() / ".lianxin" / "browser_profile"

_lock = threading.Lock()
_instance: Optional["BrowserController"] = None

# JS 脚本：提取页面可交互元素并打上自定义 ref 标记
_EXTRACT_SCRIPT = r"""
() => {
    const results = [];
    let refCounter = 0;
    const interactiveRoles = new Set([
        'button', 'link', 'textbox', 'searchbox', 'combobox', 'listbox',
        'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option',
        'radio', 'checkbox', 'switch', 'tab', 'slider', 'spinbutton',
        'listitem', 'gridcell', 'row', 'columnheader', 'rowheader',
        'treeitem', 'heading', 'img', 'navigation', 'separator', 'tooltip'
    ]);

    // 先清除旧的标记
    document.querySelectorAll('[data-lx-ref]').forEach(el => el.removeAttribute('data-lx-ref'));

    function isVisible(el) {
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0'
            && el.offsetWidth > 0 && el.offsetHeight > 0;
    }

    function getSelector(el) {
        // 构建一个可靠的 CSS 选择器用于后续定位
        if (el.id) return `#${CSS.escape(el.id)}`;
        const tag = el.tagName.toLowerCase();
        if (el.className && typeof el.className === 'string') {
            const cls = el.className.trim().split(/\s+/).filter(c => c && !c.startsWith('lx-')).slice(0, 2).join('.');
            if (cls) return `${tag}.${CSS.escape(cls)}`;
        }
        return tag;
    }

    function addRef(el, role, info) {
        const ref = 'e' + (refCounter++);
        el.setAttribute('data-lx-ref', ref);
        info.ref = ref;
        info.selector = getSelector(el);
        // 也记录文本用于 text-based lookup 回退
        const text = (el.textContent || '').trim().substring(0, 100);
        if (text) info.text = text;
        info.tag = el.tagName.toLowerCase();
        if (el.id) info.id = el.id;
        if (el.name) info.name = el.name;
        if (el.placeholder) info.placeholder = el.placeholder;
        if (el.type) info.type = el.type;
        if (el.href) info.href = el.href;
        results.push(info);
    }

    // 扫描所有可交互的原生元素
    const selectors = [
        'button', 'a[href]', 'input', 'textarea', 'select',
        '[role]', '[onclick]', '[tabindex]', '[contenteditable="true"]'
    ];

    const seen = new Set();
    for (const sel of selectors) {
        try {
            document.querySelectorAll(sel).forEach(el => {
                if (seen.has(el) || !isVisible(el)) return;
                seen.add(el);

                const tag = el.tagName.toLowerCase();
                let role = el.getAttribute('role') || '';
                let name = '';

                if (tag === 'button') {
                    role = role || 'button';
                    name = el.textContent || '';
                } else if (tag === 'a' && el.href) {
                    role = role || 'link';
                    name = el.textContent || '';
                } else if (tag === 'input') {
                    const t = (el.type || 'text').toLowerCase();
                    if (t === 'submit' || t === 'button' || t === 'reset') {
                        role = 'button';
                        name = el.value || el.name || '';
                    } else if (t === 'checkbox' || t === 'radio') {
                        role = t;
                        name = (el.labels?.[0]?.textContent || el.name || el.value || '');
                    } else {
                        role = 'textbox';
                        // 不把输入框当前值放进快照，避免密码、验证码和个人资料进入模型上下文。
                        name = el.placeholder || el.name || (t === 'password' ? '[密码输入框]' : '');
                    }
                } else if (tag === 'textarea') {
                    role = 'textbox';
                    name = el.placeholder || el.name || '';
                } else if (tag === 'select') {
                    role = 'combobox';
                    name = el.name || '';
                } else if (role) {
                    name = el.textContent || '';
                }

                if (!role) return;

                const info = { role: role, name: name.trim().substring(0, 100) };
                addRef(el, role, info);
            });
        } catch(e) {}
    }

    return { refs: results, url: location.href, title: document.title };
}
"""


class BrowserController:
    """Playwright 浏览器单例控制器。

    使用 chromium.launch_persistent_context 保持 cookie/login 状态。
    JS 注入提取交互元素并分配 [ref=eX] 标记用于 LLM 交互。
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._headless = True
        self._timeout = 30_000
        self._last_refs = []  # 当前页面的 ref 信息列表
        self._owner_thread: Optional[int] = None  # 创建浏览器的线程 ID
        self._page_ids: dict[str, object] = {}
        self._active_page_id: Optional[str] = None
        self._next_page_index = 0
        self._snapshot_counter = 0
        self._last_snapshot_id: Optional[str] = None
        self._connection_mode = "launch"
        self._cdp_endpoint = ""

    # ── 公开方法 ──────────────────────────────────────────────

    def navigate(self, url: str) -> str:
        """导航到 URL，返回带 ref 标记的页面快照。"""
        page = self._ensure_page()
        url = str(url or "").strip()
        if not url:
            return "浏览器导航失败：URL 不能为空。"
        if url.lower().startswith(("javascript:", "data:", "vbscript:")):
            return "浏览器导航失败：不允许使用脚本或数据协议。"
        if not url.startswith(("http://", "https://", "file://")):
            url = "https://" + url
        logger.info(f"导航: {redact_url(url)}")
        page.goto(url, timeout=self._timeout, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)  # 等待动态内容渲染
        return self.snapshot()

    def connect_cdp(self, endpoint: Optional[str] = None) -> str:
        """连接本机已启动的 Chrome/Edge DevTools 端口。

        只允许 loopback 地址，且不会读取或返回调试端口中的 Cookie/Profile 信息。
        断开控制器时仅断开 Playwright 连接，不关闭用户的外部浏览器。
        """
        cfg = get_browser_config()
        endpoint = str(endpoint or cfg.get("cdp_endpoint", "http://127.0.0.1:9222")).strip()
        allowed, reason = self._validate_cdp_endpoint(endpoint)
        if not allowed:
            return f"浏览器 CDP 连接失败：{reason}"
        current_thread = threading.get_ident()
        if self._owner_thread is not None and self._owner_thread != current_thread:
            self.close()
        if self._context is not None and self._connection_mode == "cdp" and self._cdp_endpoint == endpoint:
            return self.snapshot()
        if self._context is not None:
            self.close()
        try:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            timeout = max(1000, int(cfg.get("cdp_timeout", 10_000)))
            self._browser = self._playwright.chromium.connect_over_cdp(
                endpoint, timeout=timeout
            )
            contexts = list(self._browser.contexts)
            if not contexts:
                self._reset_connection_state(stop_playwright=True)
                return "浏览器 CDP 连接失败：远程浏览器没有可用上下文。"
            self._context = contexts[0]
            pages = list(self._context.pages)
            self._page_ids = {}
            self._next_page_index = 0
            for page in pages:
                self._register_page(page)
            if not pages:
                self._page = self._context.new_page()
                self._register_page(self._page)
            else:
                self._page = pages[0]
            self._active_page_id = self._page_id_for(self._page)
            self._owner_thread = current_thread
            self._connection_mode = "cdp"
            self._cdp_endpoint = endpoint
            logger.info("已连接本机浏览器 CDP：%s", redact_url(endpoint))
            append_browser_audit({
                "event": "connection",
                "status": "connected",
                "mode": "cdp",
                "endpoint": redact_url(endpoint),
            })
            return self.snapshot()
        except Exception as exc:
            self._reset_connection_state(stop_playwright=True)
            return f"浏览器 CDP 连接失败：{redact_browser_text(exc, max_chars=300)}"

    def disconnect_cdp(self) -> str:
        """断开 CDP 控制，不关闭用户的 Chrome/Edge。"""
        if self._connection_mode != "cdp":
            return "当前不是 CDP 接管模式。"
        endpoint = redact_url(self._cdp_endpoint)
        self._reset_connection_state(stop_playwright=True)
        append_browser_audit({
            "event": "connection",
            "status": "disconnected",
            "mode": "cdp",
            "endpoint": endpoint,
        })
        return f"已断开浏览器 CDP 连接：{endpoint}；外部浏览器未关闭。"

    def connection_status(self) -> dict:
        """返回不含凭据的浏览器连接状态。"""
        try:
            self._sync_pages()
        except Exception:
            pass
        return {
            "mode": self._connection_mode,
            "connected": bool(self._context is not None),
            "endpoint": redact_url(self._cdp_endpoint) if self._connection_mode == "cdp" else "",
            "page_count": len(self._page_ids),
            "active_page_id": self._active_page_id,
        }

    def snapshot(self) -> str:
        """获取当前页面快照，包含所有可交互元素及其 [ref=eX] 标记。"""
        page = self._ensure_page()
        self._snapshot_counter += 1
        snapshot_id = f"snap_{self._snapshot_counter}"
        self._last_snapshot_id = snapshot_id
        page_id = self._page_id_for(page) or self._active_page_id or "p0"
        try:
            result = page.evaluate(_EXTRACT_SCRIPT)
            self._last_refs = result.get("refs", [])
            result["snapshot_id"] = snapshot_id
            result["page_id"] = page_id
            return self._build_snapshot(result)
        except Exception as e:
            logger.warning(f"快照提取失败: {e}")
            self._last_refs = []
            return self._fallback_snapshot(page, snapshot_id=snapshot_id, page_id=page_id)

    def click(self, ref: str, snapshot_id: Optional[str] = None) -> str:
        """点击 ref 对应的元素，返回新页面快照。"""
        page = self._ensure_page()
        error = self._validate_ref(ref, snapshot_id, action="browser_click")
        if error:
            return error
        el_info = self._find_ref_info(ref)
        if not el_info:
            return self._browser_error(
                "STALE_REF",
                f"未找到 ref={ref} 对应的元素，页面可能已刷新。",
                next_tool="browser_snapshot",
            )

        locator = self._build_locator(page, el_info)
        try:
            locator.click(timeout=self._timeout)
        except Exception:
            try:
                locator.scroll_into_view_if_needed(timeout=self._timeout // 2)
                locator.click(timeout=self._timeout, force=True)
            except Exception as e:
                return f"点击失败 (ref={ref}): {e}"
        page.wait_for_timeout(1000)
        return self.snapshot()

    def fill(self, ref: str, text: str, snapshot_id: Optional[str] = None) -> str:
        """向 ref 对应的输入框填入文字，返回新页面快照。"""
        page = self._ensure_page()
        error = self._validate_ref(ref, snapshot_id, action="browser_fill")
        if error:
            return error
        el_info = self._find_ref_info(ref)
        if not el_info:
            return self._browser_error(
                "STALE_REF",
                f"未找到 ref={ref} 对应的元素，页面可能已刷新。",
                next_tool="browser_snapshot",
            )

        locator = self._build_locator(page, el_info)
        try:
            locator.fill(text, timeout=self._timeout)
        except Exception as e:
            return f"填写失败 (ref={ref}): {e}"
        return self.snapshot()

    def screenshot(self) -> str:
        """截取当前页面 PNG，保存到临时文件并返回路径。"""
        page = self._ensure_page()
        tmp_dir = Path.home() / ".lianxin" / "temp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        path = tmp_dir / f"browser_screenshot_{_timestamp()}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path)

    def scroll(self, amount: int = 300, ref: Optional[str] = None,
               snapshot_id: Optional[str] = None) -> str:
        """滚动页面（正数向下，负数向上），返回新快照。"""
        page = self._ensure_page()
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return "滚动失败：amount 必须是整数。"
        amount = max(-2000, min(2000, amount))
        if ref:
            error = self._validate_ref(ref, snapshot_id, action="browser_scroll")
            if error:
                return error
            el_info = self._find_ref_info(ref)
            if not el_info:
                return self._browser_error(
                    "STALE_REF",
                    f"滚动失败：未找到 ref={ref}。",
                    next_tool="browser_snapshot",
                )
            try:
                self._build_locator(page, el_info).scroll_into_view_if_needed(timeout=self._timeout)
            except Exception as e:
                return f"滚动到 ref={ref} 失败：{e}"
        page.evaluate("amount => window.scrollBy(0, amount)", amount)
        page.wait_for_timeout(500)
        return self.snapshot()

    def press(self, key: str, ref: Optional[str] = None,
              snapshot_id: Optional[str] = None) -> str:
        """向当前页面发送受控按键，完成后返回新快照。"""
        page = self._ensure_page()
        key = str(key or "").strip()
        if not self._is_allowed_key(key):
            return f"按键被拒绝：{key or '(空)'}。仅允许常用页面交互按键。"

        if ref:
            error = self._validate_ref(ref, snapshot_id, action="browser_press")
            if error:
                return error
            el_info = self._find_ref_info(ref)
            if not el_info:
                return self._browser_error(
                    "STALE_REF",
                    f"未找到 ref={ref} 对应的元素。",
                    next_tool="browser_snapshot",
                )
            try:
                self._build_locator(page, el_info).focus(timeout=self._timeout)
            except Exception as e:
                return f"按键前聚焦失败 (ref={ref}): {e}"

        try:
            page.keyboard.press(key)
            page.wait_for_timeout(300)
            return self.snapshot()
        except Exception as e:
            return f"按键失败 ({key}): {e}"

    def wait(self, seconds: float = 1.0, until: str = "time",
             text: str = "", ref: str = "", value: str = "",
             refresh_snapshot: bool = True,
             snapshot_id: Optional[str] = None) -> str:
        """等待页面达到受控条件，禁止执行任意 JavaScript 条件。"""
        page = self._ensure_page()
        try:
            seconds = max(0.0, min(30.0, float(seconds)))
        except (TypeError, ValueError):
            return "等待失败：seconds 必须是数字。"

        until = str(until or "time").strip().lower()
        deadline = time.monotonic() + (seconds or 10.0)
        try:
            if until == "time":
                page.wait_for_timeout(int(seconds * 1000))
            elif until == "domcontentloaded":
                page.wait_for_load_state("domcontentloaded", timeout=max(1000, int(seconds * 1000)))
            elif until == "network_idle":
                page.wait_for_load_state("networkidle", timeout=max(1000, int(seconds * 1000)))
            elif until == "text":
                if not text:
                    return "等待失败：until=text 时必须提供 text。"
                page.get_by_text(text, exact=False).first.wait_for(
                    state="visible", timeout=max(1000, int(seconds * 1000)))
            elif until == "ref_visible":
                if not ref:
                    return "等待失败：until=ref_visible 时必须提供 ref。"
                error = self._validate_ref(ref, snapshot_id, action="browser_wait")
                if error:
                    return error
                el_info = self._find_ref_info(ref)
                if not el_info:
                    return self._browser_error(
                        "STALE_REF",
                        f"等待失败：ref={ref} 已失效。",
                        next_tool="browser_snapshot",
                    )
                self._build_locator(page, el_info).wait_for(
                    state="visible", timeout=max(1000, int(seconds * 1000)))
            elif until == "url_contains":
                if not value:
                    return "等待失败：until=url_contains 时必须提供 value。"
                while value not in page.url and time.monotonic() < deadline:
                    page.wait_for_timeout(100)
                if value not in page.url:
                    return f"等待超时：当前 URL 未包含 {value!r}。"
            else:
                return f"等待失败：不支持的条件 {until!r}。"
        except Exception as e:
            return f"等待失败 ({until}): {e}"

        if refresh_snapshot:
            return self.snapshot()
        return f"等待完成：until={until}。"

    def list_tabs(self) -> str:
        """列出当前浏览器标签页，仅返回安全的页面摘要。"""
        self._ensure_page()
        self._sync_pages()
        rows = []
        for page_id, page in self._page_ids.items():
            try:
                rows.append({
                    "page_id": page_id,
                    "active": page_id == self._active_page_id,
                    "url": redact_url(page.url),
                    "title": redact_browser_text(page.title(), max_chars=200),
                })
            except Exception:
                continue
        return "标签页列表：\n" + json.dumps(rows, ensure_ascii=False, indent=2)

    def select_tab(self, page_id: str) -> str:
        """切换到指定标签页并返回该页面的新快照。"""
        self._ensure_page()
        self._sync_pages()
        page = self._page_ids.get(str(page_id or ""))
        if page is None:
            return f"切换标签页失败：未找到 page_id={page_id}。请先调用 browser_tabs(action='list')。"
        self._active_page_id = str(page_id)
        self._page = page
        return self.snapshot()

    def new_tab(self, url: Optional[str] = None) -> str:
        """新建标签页，可选导航到 URL。"""
        self._ensure_page()
        page = self._context.new_page()
        page_id = self._register_page(page)
        self._active_page_id = page_id
        self._page = page
        try:
            if url:
                url = str(url).strip()
                if url.lower().startswith(("javascript:", "data:", "vbscript:")):
                    return "新建标签页失败：不允许使用脚本或数据协议。"
                if not url.startswith(("http://", "https://", "file://")):
                    url = "https://" + url
                page.goto(str(url), timeout=self._timeout, wait_until="domcontentloaded")
                page.wait_for_timeout(500)
            return self.snapshot()
        except Exception as e:
            return f"新建标签页失败 (page_id={page_id}): {e}"

    def close_tab(self, page_id: str, confirm: bool = False) -> str:
        """关闭指定标签页；存在未提交表单或最后一个标签页时拒绝静默关闭。"""
        self._ensure_page()
        self._sync_pages()
        page_id = str(page_id or "")
        if page_id not in self._page_ids:
            return f"关闭标签页失败：未找到 page_id={page_id}。"
        if len(self._page_ids) <= 1:
            return "关闭标签页失败：至少保留一个标签页。"
        page = self._page_ids[page_id]
        if not confirm and self._has_unsaved_form(page):
            return "[PERMISSION_REQUIRED] 当前标签页可能有未提交表单，请用户确认后再次调用 confirm=true。"
        try:
            page.close()
        except Exception as e:
            return f"关闭标签页失败 (page_id={page_id}): {e}"
        self._page_ids.pop(page_id, None)
        if self._active_page_id == page_id:
            self._active_page_id, self._page = next(iter(self._page_ids.items()))
        return self.snapshot()

    def close(self):
        """关闭浏览器实例。"""
        global _instance
        self._reset_connection_state(stop_playwright=True)
        _instance = None

    # ── 内部方法 ──────────────────────────────────────────────
    def _ensure_page(self):
        """确保页面可用，必要时重建浏览器。"""
        cfg = get_browser_config()
        self._headless = cfg.get("headless", True)
        self._timeout = cfg.get("timeout", 30_000)

        current_thread = threading.get_ident()
        connection_mode = str(cfg.get("connection_mode", "launch") or "launch").lower()
        if connection_mode not in {"launch", "cdp"}:
            connection_mode = "launch"
        if self._owner_thread is not None and self._owner_thread != current_thread:
            logger.info("检测到线程切换，重建浏览器实例")
            self.close()
            self._owner_thread = None
        # 手动 browser_connect 建立的 CDP 会话优先于 launch 默认值，
        # 后续 browser_snapshot/click 不能因为配置仍是 launch 就立刻切回新浏览器。
        if self._context is not None and connection_mode == "cdp" and self._connection_mode != "cdp":
            self.close()

        # 检查页面是否可用，如果浏览器被用户手动关闭了也重建
        try:
            if self._page is not None and not self._page.is_closed():
                self._sync_pages()
                return self._page
        except Exception:
            pass
        if connection_mode == "cdp":
            result = self.connect_cdp(cfg.get("cdp_endpoint"))
            if self._page is None:
                raise RuntimeError(result)
        else:
            if self._connection_mode == "cdp":
                self.close()
            self._launch()
        self._owner_thread = current_thread
        return self._page

    def _launch(self):
        """启动 Chromium 持久化上下文。"""
        from playwright.sync_api import sync_playwright

        _USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._playwright = sync_playwright().start()

        launch_kwargs = {
            "user_data_dir": str(_USER_DATA_DIR),
            "headless": self._headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=UseDnsHttpsSvcb",
                "--disable-features=msEdgeNoSandbox",
                "--no-first-run",
            ],
            "viewport": {"width": 1280, "height": 720},
            "locale": "zh-CN",
        }

        channel = get_browser_config().get("channel", "")
        if channel:
            launch_kwargs["channel"] = channel

        self._context = self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = self._context.new_page()
        self._page_ids = {}
        for page in self._context.pages:
            self._register_page(page)
        self._active_page_id = self._page_id_for(self._page)
        self._connection_mode = "launch"
        self._cdp_endpoint = ""
        logger.info("浏览器已启动")
        append_browser_audit({
            "event": "connection",
            "status": "connected",
            "mode": "launch",
        })

    def _is_allowed_key(self, key: str) -> bool:
        if key in _BLOCKED_BROWSER_KEYS:
            return False
        if key in _ALLOWED_BROWSER_KEYS:
            return True
        parts = key.split("+")
        if len(parts) == 2 and parts[0] in _ALLOWED_BROWSER_MODIFIERS:
            return parts[1] in _ALLOWED_BROWSER_KEYS or len(parts[1]) == 1
        if len(parts) == 3 and parts[0] in _ALLOWED_BROWSER_MODIFIERS and parts[1] in _ALLOWED_BROWSER_MODIFIERS:
            return parts[2] in _ALLOWED_BROWSER_KEYS or len(parts[2]) == 1
        return len(key) == 1

    @staticmethod
    def _validate_cdp_endpoint(endpoint: str) -> tuple[bool, str]:
        """只接受本机 HTTP(S) DevTools 端点，避免把控制权暴露给远程主机。"""
        try:
            parts = urlsplit(str(endpoint or ""))
            host = (parts.hostname or "").lower()
            if parts.scheme not in {"http", "https"}:
                return False, "端点必须使用 http 或 https。"
            if host not in {"127.0.0.1", "localhost", "::1"}:
                return False, "出于安全原因，只允许连接本机 loopback 地址。"
            if parts.username or parts.password:
                return False, "CDP 端点不允许携带用户名或密码。"
            if not parts.port:
                return False, "CDP 端点必须包含端口，例如 9222。"
            return True, ""
        except Exception:
            return False, "CDP 端点格式无效。"

    def _reset_connection_state(self, stop_playwright: bool = False) -> None:
        """清理本地连接引用；CDP 模式不会调用远程 browser/context.close。"""
        playwright = self._playwright
        context = self._context
        mode = self._connection_mode
        try:
            if mode != "cdp" and context is not None:
                context.close()
        except Exception:
            pass
        if stop_playwright and playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        self._context = None
        self._browser = None
        self._page = None
        self._playwright = None
        self._last_refs = []
        self._page_ids = {}
        self._active_page_id = None
        self._next_page_index = 0
        self._snapshot_counter = 0
        self._last_snapshot_id = None
        self._owner_thread = None
        self._connection_mode = "launch"
        self._cdp_endpoint = ""

    def _page_id_for(self, page) -> Optional[str]:
        for page_id, known_page in self._page_ids.items():
            if known_page is page:
                return page_id
        return None

    def _register_page(self, page) -> str:
        existing = self._page_id_for(page)
        if existing:
            return existing
        while f"p{self._next_page_index}" in self._page_ids:
            self._next_page_index += 1
        page_id = f"p{self._next_page_index}"
        self._next_page_index += 1
        self._page_ids[page_id] = page
        return page_id

    def _sync_pages(self):
        if not self._context:
            return
        live_pages = list(self._context.pages)
        live_ids = {id(page) for page in live_pages}
        self._page_ids = {
            page_id: page for page_id, page in self._page_ids.items()
            if id(page) in live_ids
        }
        for page in live_pages:
            self._register_page(page)
        if self._active_page_id not in self._page_ids:
            if self._page_ids:
                self._active_page_id, self._page = next(iter(self._page_ids.items()))
            else:
                self._active_page_id = None
                self._page = None

    @staticmethod
    def _has_unsaved_form(page) -> bool:
        """用固定脚本检测未提交输入，不接受模型传入脚本。"""
        try:
            return bool(page.evaluate("""() => Array.from(
                document.querySelectorAll('input, textarea, select')
            ).some(el => {
                if (el.disabled || el.readOnly) return false;
                if (el.type === 'checkbox' || el.type === 'radio') {
                    return el.checked !== el.defaultChecked;
                }
                return String(el.value || '') !== String(el.defaultValue || '');
            })"""))
        except Exception:
            return False

    def _find_ref_info(self, ref: str) -> Optional[dict]:
        """根据 ref 查找元素信息。"""
        for info in self._last_refs:
            if info.get("ref") == ref:
                return info
        return None

    def _validate_ref(self, ref: str, snapshot_id: Optional[str], action: str = "") -> Optional[str]:
        """校验动作引用的快照生命周期。

        snapshot_id 为空时保留旧版调用兼容性；一旦调用方提供 ID，就严格拒绝旧快照。
        """
        if snapshot_id and snapshot_id != self._last_snapshot_id:
            return self._browser_error(
                "STALE_SNAPSHOT",
                f"{action or 'browser_action'} 使用了过期快照 {snapshot_id}，当前快照为 {self._last_snapshot_id or '(无)'}。",
                next_tool="browser_snapshot",
                expected=snapshot_id,
                actual=self._last_snapshot_id or "",
            )
        if not ref:
            return self._browser_error(
                "INVALID_REF",
                "ref 不能为空，请先调用 browser_snapshot 获取元素引用。",
                next_tool="browser_snapshot",
            )
        return None

    @staticmethod
    def _browser_error(code: str, message: str, next_tool: str = "",
                       expected: str = "", actual: str = "") -> str:
        parts = [f"[BROWSER_ERROR] code={code} recoverable=true"]
        if next_tool:
            parts.append(f"next={next_tool}")
        if expected:
            parts.append(f"expected={expected}")
        if actual:
            parts.append(f"actual={actual}")
        return " ".join(parts) + f"\n{message}"

    def _build_locator(self, page, el_info: dict):
        """根据元素信息构建 Playwright locator。优先使用 data-lx-ref 属性。"""
        # 首选：通过我们注入的 data-lx-ref 属性定位
        ref = el_info.get("ref", "")
        try:
            loc = page.locator(f"[data-lx-ref={ref}]")
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass

        # 回退 1：通过 ID
        if el_info.get("id"):
            try:
                loc = page.locator(f"#{el_info['id']}")
                if loc.count() > 0:
                    return loc.first
            except Exception:
                pass

        # 回退 2：通过 placeholder + tag
        if el_info.get("placeholder"):
            tag = el_info.get("tag", "")
            try:
                if tag == "input":
                    loc = page.get_by_placeholder(el_info["placeholder"])
                    if loc.count() > 0:
                        return loc.first
                elif tag == "textarea":
                    loc = page.get_by_placeholder(el_info["placeholder"])
                    if loc.count() > 0:
                        return loc.first
            except Exception:
                pass

        # 回退 3：通过文本内容
        text = el_info.get("text", "")
        role = el_info.get("role", "")
        if text and role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=text)
                if loc.count() > 0:
                    return loc.first
            except Exception:
                pass

        # 回退 4：通过 CSS 选择器
        if el_info.get("selector"):
            try:
                loc = page.locator(el_info["selector"])
                if loc.count() > 0:
                    return loc.first
            except Exception:
                pass

        # 最终回退：直接用 data-lx-ref 属性
        return page.locator(f"[data-lx-ref={ref}]").first

    def _build_snapshot(self, result: dict) -> str:
        """根据 JS 提取结果构建 LLM 友好的页面快照文本。"""
        refs = result.get("refs", [])
        url = redact_url(result.get("url", "?"))
        title = redact_browser_text(result.get("title", "?"), max_chars=200)

        lines = [
            f"【页面快照】",
            f"SNAPSHOT_ID: {result.get('snapshot_id', self._last_snapshot_id or '?')}",
            f"PAGE_ID: {result.get('page_id', self._active_page_id or '?')}",
            f"URL: {url}",
            f"标题: {title}",
            f"可交互元素: {len(refs)} 个",
            f"",
        ]

        if not refs:
            lines.append("  (未检测到可交互元素)")
            return "\n".join(lines)

        # 按角色分组
        groups = {}
        for r in refs:
            role = r.get("role", "other")
            groups.setdefault(role, []).append(r)

        # 优先显示的组件顺序
        role_order = ["textbox", "searchbox", "combobox", "button", "link", "checkbox", "radio", "listitem", "navigation", "heading", "img", "other"]
        seen_roles = set()

        for role in role_order:
            items = groups.get(role, [])
            if not items:
                continue
            seen_roles.add(role)
            role_label = {
                "textbox": "输入框",
                "searchbox": "搜索框",
                "combobox": "下拉框",
                "button": "按钮",
                "link": "链接",
                "checkbox": "复选框",
                "radio": "单选按钮",
                "listitem": "列表项",
                "navigation": "导航",
                "heading": "标题",
                "img": "图片",
            }.get(role, role)

            lines.append(f"[{role_label}]")
            for item in items[:20]:  # 每类最多 20 个
                ref = item.get("ref", "?")
                name = redact_browser_text(item.get("name", ""), max_chars=100)
                item_type = item.get("type", "")
                placeholder = item.get("placeholder", "")
                href = item.get("href", "")

                label = name or placeholder or item_type or "(无标签)"
                # 截断长文本
                if len(label) > 60:
                    label = label[:57] + "..."

                extra = ""
                if item_type and role in ("textbox", "searchbox"):
                    extra = f" type={item_type}"
                if href:
                    extra += f" -> {redact_url(href)[:80]}"

                lines.append(f"  [{ref}] {label}{extra}")
            lines.append("")

        # 显示未在优先列表中的角色
        for role, items in groups.items():
            if role in seen_roles:
                continue
            lines.append(f"[{role}]")
            for item in items[:10]:
                ref = item.get("ref", "?")
                name = redact_browser_text(item.get("name", "(无标签)"), max_chars=60)
                if len(name) > 60:
                    name = name[:57] + "..."
                lines.append(f"  [{ref}] {name}")
            lines.append("")

        return "\n".join(lines)

    def _fallback_snapshot(self, page, snapshot_id: str = "", page_id: str = "") -> str:
        """JS 提取失败时的回退方案。"""
        try:
            title = page.title()
            url = page.url
            text = page.evaluate("""() => {
                const body = document.body;
                if (!body) return '';
                return body.innerText.substring(0, 3000);
            }""")
            return (
                f"【页面信息】(简化模式)\n"
                f"SNAPSHOT_ID: {snapshot_id or self._last_snapshot_id or '?'}\n"
                f"PAGE_ID: {page_id or self._active_page_id or '?'}\n"
                f"URL: {redact_url(url)}\n"
                f"标题: {redact_browser_text(title, max_chars=200)}\n\n"
                f"页面文本:\n{redact_browser_text(text, max_chars=3000)}"
            )
        except Exception as e:
            return f"无法获取页面快照: {e}"


def _timestamp() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_browser() -> BrowserController:
    """获取浏览器单例（线程安全）。"""
    global _instance
    with _lock:
        if _instance is None:
            _instance = BrowserController()
        return _instance


def close_browser():
    """关闭浏览器单例。"""
    global _instance
    with _lock:
        if _instance is not None:
            _instance.close()
            _instance = None
