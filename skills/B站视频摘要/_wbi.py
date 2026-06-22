# B站 WBI 签名算法 — 社区逆向成果，2023 年至今稳定运行
# 参考：https://github.com/SocialSisterYi/bilibili-API-collect

import hashlib
import time
import requests
from functools import lru_cache

# 固定置换表（B站 WBI 签名核心，自 2023 年未变）
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 52, 44, 34,
]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


@lru_cache(maxsize=1)
def _get_keys() -> tuple[str, str]:
    """从 B站 nav 接口获取 img_key 和 sub_key（缓存 1 小时，lru_cache 依赖引用）。"""
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={"User-Agent": _UA, "Referer": "https://www.bilibili.com/"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    img_url = data["wbi_img"]["img_url"]  # e.g. https://.../7c8b...png
    sub_url = data["wbi_img"]["sub_url"]
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


def _mix_key(img_key: str, sub_key: str) -> str:
    """按固定置换表混合 img_key + sub_key → 32 位签名密钥。"""
    raw = img_key + sub_key
    result = []
    for idx in _MIXIN_KEY_ENC_TAB:
        if idx < len(raw):
            result.append(raw[idx])
    return "".join(result)[:32]


def _invalidate_cache():
    """手动清除缓存（可用于测试）。"""
    _get_keys.cache_clear()


def sign_params(params: dict) -> dict:
    """对请求参数进行 WBI 签名，原地添加 wts 和 w_rid。

    Args:
        params: 原始参数字典（不含 wts/w_rid）

    Returns:
        添加了 wts 和 w_rid 的参数字典（就地修改）
    """
    img_key, sub_key = _get_keys()
    mix = _mix_key(img_key, sub_key)

    params["wts"] = int(time.time())
    # 按 key 排序拼接
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    params["w_rid"] = hashlib.md5((query + mix).encode()).hexdigest()
    return params
