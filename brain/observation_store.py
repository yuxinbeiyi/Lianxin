"""
观察记忆库：持久化存储肩载摄像头的观察记录。
JSON 文件位置: ~/.lianxin/observation_log.json
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


_DATA_PATH = Path.home() / ".lianxin" / "observation_log.json"


def _load() -> dict:
    if _DATA_PATH.exists():
        try:
            return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"records": []}


def _save(data: dict):
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add(description: str, attention: str = "", tags: list = None,
        image_path: str = "", pan: int = 0, tilt: int = 0,
        chain_id: str = "") -> dict:
    """添加一条观察记录。返回创建的记录。"""
    data = _load()
    record = {
        "id": f"obs_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "chain_id": chain_id,
        "pan": pan,
        "tilt": tilt,
        "image_path": image_path,
        "description": description,
        "attention": attention,
        "tags": tags or [],
    }
    data["records"].append(record)
    # 保留最近 500 条
    if len(data["records"]) > 500:
        data["records"] = data["records"][-500:]
    _save(data)
    return record


def search(keyword: str = "", time_from: str = "", time_to: str = "",
           limit: int = 10) -> list[dict]:
    """按关键词/时间范围搜索观察记录。"""
    data = _load()
    results = []
    for r in reversed(data["records"]):
        if len(results) >= limit:
            break
        # 时间范围过滤
        if time_from and r["timestamp"] < time_from:
            continue
        if time_to and r["timestamp"] > time_to:
            continue
        # 关键词过滤
        if keyword:
            kw = keyword.lower()
            text = (r["description"] + " " + r.get("attention", "") + " " +
                    " ".join(r.get("tags", []))).lower()
            if kw not in text:
                continue
        results.append(r)
    return results


def recent(limit: int = 10) -> list[dict]:
    """获取最近 N 条观察记录。"""
    data = _load()
    return data["records"][-limit:][::-1]


def get_chain(chain_id: str) -> list[dict]:
    """获取某次探索链的所有记录。"""
    data = _load()
    return [r for r in data["records"] if r.get("chain_id") == chain_id]


def get_latest_chain_id() -> Optional[str]:
    """获取最近一次观察的 chain_id。"""
    data = _load()
    if data["records"]:
        return data["records"][-1].get("chain_id")
    return None


def clear_latest_chain():
    """清除最新 chain 的引用，防止跨轮对话的脏数据。"""
    # 方案：给最新一条记录打上 cleared 标记
    data = _load()
    if data["records"]:
        data["records"][-1]["chain_id"] = f"_{data['records'][-1].get('chain_id', '')}"
        _save(data)
