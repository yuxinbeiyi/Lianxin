"""
BrowserController: Playwright 浏览器自动化单例控制器。

直接使用 Playwright Python 绑定控制 Chromium，无需 Node.js 桥接层。
通过 JS 注入提取可交互元素并分配自定义 ref 标记，让 LLM 理解页面结构并与之交互。
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from config import get_browser_config

logger = logging.getLogger("BrowserController")

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
                        name = el.placeholder || el.name || el.value || '';
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

    # ── 公开方法 ──────────────────────────────────────────────

    def navigate(self, url: str) -> str:
        """导航到 URL，返回带 ref 标记的页面快照。"""
        page = self._ensure_page()
        if not url.startswith("http"):
            url = "https://" + url
        logger.info(f"导航: {url}")
        page.goto(url, timeout=self._timeout, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)  # 等待动态内容渲染
        return self.snapshot()

    def snapshot(self) -> str:
        """获取当前页面快照，包含所有可交互元素及其 [ref=eX] 标记。"""
        page = self._ensure_page()
        try:
            result = page.evaluate(_EXTRACT_SCRIPT)
            self._last_refs = result.get("refs", [])
            return self._build_snapshot(result)
        except Exception as e:
            logger.warning(f"快照提取失败: {e}")
            return self._fallback_snapshot(page)

    def click(self, ref: str) -> str:
        """点击 ref 对应的元素，返回新页面快照。"""
        page = self._ensure_page()
        el_info = self._find_ref_info(ref)
        if not el_info:
            return f"未找到 ref={ref} 对应的元素（页面可能已刷新）。请先调用 browser_snapshot 获取最新页面结构。"

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

    def fill(self, ref: str, text: str) -> str:
        """向 ref 对应的输入框填入文字，返回新页面快照。"""
        page = self._ensure_page()
        el_info = self._find_ref_info(ref)
        if not el_info:
            return f"未找到 ref={ref} 对应的元素（页面可能已刷新）。请先调用 browser_snapshot 获取最新页面结构。"

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

    def scroll(self, amount: int = 300) -> str:
        """滚动页面（正数向下，负数向上），返回新快照。"""
        page = self._ensure_page()
        page.evaluate(f"window.scrollBy(0, {amount})")
        page.wait_for_timeout(500)
        return self.snapshot()

    def close(self):
        """关闭浏览器实例。"""
        global _instance
        try:
            if self._context:
                self._context.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        finally:
            self._context = None
            self._browser = None
            self._page = None
            self._playwright = None
            self._last_refs = []
            _instance = None

    # ── 内部方法 ──────────────────────────────────────────────

    def _ensure_page(self):
        """确保浏览器和页面已启动（自动检测线程切换并重建）。"""
        cfg = get_browser_config()
        self._headless = cfg.get("headless", True)
        self._timeout = cfg.get("timeout", 30_000)

        current_thread = threading.get_ident()
        if self._owner_thread is not None and self._owner_thread != current_thread:
            # 线程已切换（上一轮 AgentWorker 的 QThread 已退出）
            # 必须重建浏览器，Playwright 不允许跨线程访问
            logger.info("检测到线程切换，重建浏览器实例")
            self.close()
            self._owner_thread = None

        if self._page is None or self._page.is_closed():
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
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
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
        logger.info("浏览器已启动")

    def _find_ref_info(self, ref: str) -> Optional[dict]:
        """根据 ref 查找元素信息。"""
        for info in self._last_refs:
            if info.get("ref") == ref:
                return info
        return None

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
        url = result.get("url", "?")
        title = result.get("title", "?")

        lines = [
            f"【页面快照】",
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
                name = item.get("name", "")
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
                    extra += f" -> {href[:80]}"

                lines.append(f"  [{ref}] {label}{extra}")
            lines.append("")

        # 显示未在优先列表中的角色
        for role, items in groups.items():
            if role in seen_roles:
                continue
            lines.append(f"[{role}]")
            for item in items[:10]:
                ref = item.get("ref", "?")
                name = item.get("name", "(无标签)")
                if len(name) > 60:
                    name = name[:57] + "..."
                lines.append(f"  [{ref}] {name}")
            lines.append("")

        return "\n".join(lines)

    def _fallback_snapshot(self, page) -> str:
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
                f"URL: {url}\n"
                f"标题: {title}\n\n"
                f"页面文本:\n{text}"
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
