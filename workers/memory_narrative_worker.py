"""Low-frequency semantic consolidation for entities, episodes and sagas."""
from __future__ import annotations

import json
from datetime import datetime

from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI

from config import get_api_config, get_agnes_config


class MemoryNarrativeWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, *, max_candidates: int = 36, parent=None):
        super().__init__(parent)
        self.max_candidates = max_candidates

    def _client(self):
        config = get_api_config()
        if config.get("provider") == "agnes":
            config = get_agnes_config()
        return OpenAI(api_key=config.get("api_key", ""), base_url=config.get("base_url", "")), config.get("model", "")

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = (raw or "{}").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end < start:
            return {}
        return json.loads(raw[start:end + 1])

    def run(self):
        try:
            from brain.memory_narrative import (
                apply_narrative_result, collect_narrative_candidates,
                finish_narrative_run, merge_narrative_duplicates, start_narrative_run,
            )
            candidates = collect_narrative_candidates(self.max_candidates)
            run_id = start_narrative_run(len(candidates))
            if not candidates:
                finish_narrative_run(run_id, status="success")
                self.completed.emit({"candidates": 0, "episodes_created": 0, "entities_updated": 0})
                return

            client, model = self._client()
            prompt = f"""当前时间：{datetime.now().astimezone().isoformat(timespec='seconds')}
你是长期记忆整理器。下面是已经通过来源校验的记忆碎片，请将它们整理成实体档案、叙事 Episode 和跨 Episode 的 Saga。

规则：
1. 只能使用碎片中明确出现的信息，不得补写事实。
2. 一个 Episode 至少引用 2 个相关碎片；不相关碎片不要强行合并。
3. entity 的 name 必须是文本中明确出现的人物、项目、地点、作品或概念。
4. current_status 只写实体在这些碎片中可确认的最新状态。
5. Saga 只有在至少两个 Episode 属于同一件长期经历时才创建，episode_indices 使用返回 episodes 数组的下标。
6. 不要删除原始碎片；这是可重建的派生层。

只返回 JSON：{{"entities":[{{"name":"","entity_type":"person|project|place|event|concept|other","summary":"","current_status":"","confidence":0.0}}],"episodes":[{{"title":"","summary":"","category":"event|project|relationship|other","fragment_ids":[1,2],"entities":[{{"name":"","entity_type":""}}],"occurred_from":"","occurred_to":"","confidence":0.0}}],"sagas":[{{"title":"","summary":"","episode_indices":[0,1],"confidence":0.0}}]}}

碎片：{json.dumps(candidates, ensure_ascii=False)}"""
            response = client.chat.completions.create(
                model=model, temperature=0.1, max_tokens=3000,
                messages=[
                    {"role": "system", "content": "你是谨慎的记忆整理器，只输出结构化结果。"},
                    {"role": "user", "content": prompt},
                ], timeout=60,
            )
            result = self._parse_json(response.choices[0].message.content or "{}")
            # Entity profiles may be useful even when the model did not form an episode.
            if result.get("entities") and not result.get("episodes"):
                result["episodes"] = []
            stats = apply_narrative_result(result, candidates)
            stats.update(merge_narrative_duplicates())
            finish_narrative_run(
                run_id, status="success",
                episodes_created=stats.get("episodes_created", 0),
                entities_updated=stats.get("entities_updated", 0),
            )
            self.completed.emit({"candidates": len(candidates), **stats})
        except Exception as exc:
            try:
                from brain.memory_narrative import finish_narrative_run, start_narrative_run
                finish_narrative_run(start_narrative_run(0), status="failed", error=str(exc))
            except Exception:
                pass
            self.failed.emit(str(exc))
