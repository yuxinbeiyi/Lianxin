# B站视频摘要工具 — 提取字幕 + 视频信息，供 LLM 生成结构化摘要
import re
import json
import importlib.util
from pathlib import Path
import requests

from config import get_bilibili_cookie

# 动态加载同目录的 _wbi.py（避免包导入依赖）
_wbi_path = Path(__file__).parent / "_wbi.py"
_spec = importlib.util.spec_from_file_location("_lianxin_wbi", str(_wbi_path))
_wbi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wbi)
sign_params = _wbi.sign_params

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Referer": "https://www.bilibili.com/"}


def _get_headers() -> dict:
    """返回带 Cookie 的请求头，每次调用时动态读取最新 Cookie。"""
    cookie = get_bilibili_cookie()
    if cookie:
        return {**_HEADERS, "Cookie": cookie}
    return dict(_HEADERS)


_MAX_SUBTITLE_CHARS = 6000  # 字幕最大字符数，超出则均匀采样


# ═══════════════════════════════════════════════════════════════
# 工具定义
# ═══════════════════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "bilibili_video_summary",
            "description": (
                "提取B站视频的字幕和基本信息，用于生成视频摘要。"
                "当用户发送B站视频链接、要求总结视频内容、分析视频时调用。"
                "返回带时间戳的字幕文本和视频元数据，LLM 需基于此生成结构化摘要。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "B站视频链接，支持：bilibili.com/video/BVxxx、"
                            "b23.tv 短链接、www.bilibili.com/video/avxxx"
                        ),
                    }
                },
                "required": ["url"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════════
# URL 解析
# ═══════════════════════════════════════════════════════════════

def _parse_bvid(url: str) -> str | None:
    """从 B站链接中提取 bvid。支持 b23.tv 短链接自动展开。"""
    url = url.strip()

    # 处理 b23.tv 短链接
    if "b23.tv" in url or "b23.tv" in url.lower():
        try:
            resp = requests.get(
                url, headers=_get_headers(), allow_redirects=False, timeout=10
            )
            # 短链接返回 302，从 Location 头取真实 URL
            location = resp.headers.get("Location", "")
            if location:
                url = location
        except Exception:
            pass

    # 匹配 BV 号
    m = re.search(r"BV[0-9A-Za-z]{10}", url)
    if m:
        return m.group(0)

    # 匹配 av 号
    m = re.search(r"av(\d+)", url)
    if m:
        return m.group(0)  # 返回 "av12345"

    return None


# ═══════════════════════════════════════════════════════════════
# 视频信息获取
# ═══════════════════════════════════════════════════════════════

def _get_video_info(bvid: str) -> dict:
    """获取视频基本信息（aid, cid, 标题, UP主, 时长, 分区, 简介, 播放量）。

    Returns:
        {"aid": int, "cid": int, "title": str, "owner": str,
         "duration": str, "tname": str, "desc": str, "view": int}
    """
    params = {"bvid": bvid}
    # view API 部分情况需要 WBI 签名，统一加上
    params = sign_params(params)

    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/view",
        params=params,
        headers=_get_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"B站 API 返回错误: {data.get('message', '未知')}")

    v = data["data"]
    duration_sec = v.get("duration", 0)
    minutes = duration_sec // 60
    seconds = duration_sec % 60

    return {
        "aid": v["aid"],
        "cid": v.get("cid") or (v.get("pages", [{}])[0].get("cid", 0)),
        "title": v.get("title", "未知"),
        "owner": v.get("owner", {}).get("name", "未知"),
        "duration": f"{minutes}:{seconds:02d}",
        "tname": v.get("tname", "未知"),
        "desc": (v.get("desc", "") or "").strip()[:500],
        "view": v.get("stat", {}).get("view", 0),
    }


# ═══════════════════════════════════════════════════════════════
# 字幕获取
# ═══════════════════════════════════════════════════════════════

def _get_subtitle_url(aid: int, cid: int, bvid: str) -> str | None:
    """通过 WBI 签名的 player API 获取字幕 JSON 地址。

    优先取 UP 主手动上传的 CC 字幕；若无，则取 B站自动生成的 AI 字幕。
    需要 Cookie 登录态（BILIBILI_COOKIE），否则 need_login_subtitle 为 True 时无数据。

    Returns:
        subtitle_url（完整 https URL）或 None
    """
    params = {"aid": aid, "cid": cid, "bvid": bvid}
    params = sign_params(params)

    try:
        resp = requests.get(
            "https://api.bilibili.com/x/player/wbi/v2",
            params=params,
            headers=_get_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return None

        # 检测 Cookie 是否过期：need_login_subtitle=True 且已配置 Cookie → 过期
        need_login = data.get("data", {}).get("need_login_subtitle", False)
        if need_login and get_bilibili_cookie():
            return "__COOKIE_EXPIRED__"

        # 1. 手动上传 CC 字幕
        subtitle = data.get("data", {}).get("subtitle", {})
        if subtitle is None:
            subtitle = {}
        subtitles = subtitle.get("subtitles", []) or subtitle.get("list", [])

        # 2. 无手动字幕 → 尝试 AI 自动字幕
        if not subtitles:
            vs_info = data.get("data", {}).get("video_subtitle_info", {})
            if vs_info:
                ai_subs = vs_info.get("ai_subtitle", []) or vs_info.get("subtitle_list", [])
                if ai_subs:
                    subtitles = ai_subs

        if not subtitles:
            return None

        # 优先选择中文简体，其次选第一个
        url = None
        for sub in subtitles:
            url = sub.get("subtitle_url", "")
            lan = sub.get("lan", "") or sub.get("language", "")
            if lan == "zh-CN" or "zh" in lan or lan == "":
                break
        if not url:
            return None

        if url.startswith("//"):
            url = "https:" + url
        return url
    except Exception:
        return None


def _fetch_subtitle_json(subtitle_url: str) -> list[dict] | None:
    """下载字幕 JSON 并返回 body 列表。

    Returns:
        [{"from": 0.0, "to": 2.5, "content": "..."}, ...] 或 None
    """
    try:
        resp = requests.get(subtitle_url, headers=_get_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("body", [])
    except Exception:
        return None


def _format_timestamp(seconds: float) -> str:
    """秒 → [MM:SS]"""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"[{m:02d}:{s:02d}]"


def _clean_subtitle(body: list[dict]) -> str:
    """清洗字幕：去空、去重相邻、时间戳格式化、超长截断。

    Returns:
        格式化的字幕文本
    """
    if not body:
        return ""

    # 过滤空内容
    items = [
        {"from": b["from"], "content": b["content"].strip()}
        for b in body
        if b.get("content", "").strip()
    ]
    if not items:
        return ""

    # 合并相邻相同内容
    merged = []
    for item in items:
        if merged and merged[-1]["content"] == item["content"]:
            continue
        merged.append(item)

    # 格式化
    lines = []
    for item in merged:
        ts = _format_timestamp(item["from"])
        lines.append(f"{ts} {item['content']}")

    # 超长截断：均匀采样
    total = sum(len(l) + 1 for l in lines)
    if total > _MAX_SUBTITLE_CHARS:
        step = max(1, len(lines) // 80)  # 保留约 80 条
        sampled = [lines[i] for i in range(0, len(lines), step)]
        # 确保首尾保留
        if sampled[-1] != lines[-1]:
            sampled.append(lines[-1])
        lines = sampled
        lines.insert(0, f"（字幕过长，已均匀采样，共 {len(lines)} 条核心段）")
        lines.insert(1, "")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════════

def bilibili_video_summary(url: str) -> str:
    """提取 B站视频的字幕和基本信息。

    Args:
        url: B站视频链接

    Returns:
        格式化的字幕文本 + 视频元数据，供 LLM 阅读并生成摘要
    """
    # ① 解析 bvid
    bvid = _parse_bvid(url)
    if not bvid:
        return "【错误】无法从链接中提取 BV 号，请确认链接格式正确。"

    # ② 获取视频信息
    try:
        info = _get_video_info(bvid)
    except Exception as e:
        return f"【错误】获取视频信息失败：{e}\n请确认视频存在且未下架。"

    # 格式化视频信息
    info_lines = [
        "【视频信息】",
        f"标题：{info['title']}",
        f"UP主：{info['owner']}",
        f"时长：{info['duration']}",
        f"分区：{info['tname']}",
    ]
    if info["desc"]:
        info_lines.append(f"简介：{info['desc']}")

    # ③ 获取字幕
    subtitle_url = _get_subtitle_url(info["aid"], info["cid"], bvid)
    if subtitle_url == "__COOKIE_EXPIRED__":
        info_lines.append("")
        info_lines.append(
            "⚠️ 你的 B站登录 Cookie 已过期！字幕需要登录态才能获取。\n"
            "请在莲心主界面 → 联网搜索 → 「📺 B站账号」选项卡中更新 SESSDATA 和 bili_jct。\n"
            "获取方式：浏览器登录 B站 → F12 → Application → Cookies → bilibili.com → 复制 SESSDATA 和 bili_jct 的值。"
        )
        return "\n".join(info_lines)
    if not subtitle_url:
        info_lines.append("")
        info_lines.append(
            "⚠️ 该视频未开启 AI 字幕/CC 字幕，无法提取完整时间线。"
            "请基于以上标题和简介进行概述。"
        )
        return "\n".join(info_lines)

    body = _fetch_subtitle_json(subtitle_url)
    if not body:
        info_lines.append("")
        info_lines.append(
            "⚠️ 字幕数据获取失败或为空。"
            "请基于以上标题和简介进行概述。"
        )
        return "\n".join(info_lines)

    # ④ 清洗字幕
    subtitle_text = _clean_subtitle(body)
    if not subtitle_text:
        info_lines.append("")
        info_lines.append(
            "⚠️ 字幕内容为空。请基于以上标题和简介进行概述。"
        )
        return "\n".join(info_lines)

    return "\n".join(info_lines) + "\n\n【字幕时间线】\n" + subtitle_text


# ═══════════════════════════════════════════════════════════════
# 工具执行器
# ═══════════════════════════════════════════════════════════════

TOOL_EXECUTORS = {
    "bilibili_video_summary": lambda inp: bilibili_video_summary(
        inp.get("url", "")
    ),
}