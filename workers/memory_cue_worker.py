"""Background semantic evaluator for memory-driven proactive candidates."""
import json
from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI
from config import get_api_config, get_agnes_config

class MemoryCueEvaluationWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, *, max_candidates=8, parent=None):
        super().__init__(parent); self.max_candidates=max_candidates

    def _client(self):
        cfg=get_api_config()
        if cfg.get("provider")=="agnes": cfg=get_agnes_config()
        return OpenAI(api_key=cfg.get("api_key",""),base_url=cfg.get("base_url")),cfg.get("model","")

    def run(self):
        try:
            from datetime import datetime
            from brain.memory_proactive import collect_candidates, apply_evaluations, record_evaluation_batch
            candidates=collect_candidates(self.max_candidates)
            if not candidates:
                record_evaluation_batch("无新候选"); self.completed.emit({"evaluated":0,"approved":0}); return
            client,model=self._client()
            prompt=f"""当前本地时间：{datetime.now().astimezone().isoformat(timespec='seconds')}
下面是用户明确表达、且仍有效的 Current State。请判断哪些适合在未来由 AI 主动关心、询问或提醒。

边界：
- 语义判断由你完成；不要因为状态有 expires_at 就把它当作事件发生时间。
- 只有确实能带来帮助或自然关怀时才 contact/check_in/remind，否则 skip。
- 生病、休息、情绪低落等更适合少打扰时可返回 suppress，并给出 window_end。
- due_at/window_end 必须是带时区 ISO 8601，最长不超过 30 天。
- message_instruction 是给当前激活人格的写作意图，不要直接冒充最终消息。
- 每个 fingerprint 必须原样返回一次。

仅返回 JSON：{{"evaluations":[{{"fingerprint":"...","action":"contact|check_in|remind|suppress|skip","due_at":"...","window_end":"...","confidence":0.0,"rationale":"...","message_instruction":"..."}}]}}

候选：{json.dumps(candidates,ensure_ascii=False)}"""
            response=client.chat.completions.create(model=model,temperature=0.1,max_tokens=1800,messages=[{"role":"system","content":"你是谨慎的主动关怀决策器，只做判断，不直接聊天。"},{"role":"user","content":prompt}],timeout=45)
            raw=(response.choices[0].message.content or "{}").strip()
            if raw.startswith("```"):
                raw=raw.split("\n",1)[-1].rsplit("```",1)[0].strip()
            start,end=raw.find("{"),raw.rfind("}")
            data=json.loads(raw[start:end+1] if start>=0 and end>=start else "{}")
            by_fp={c["fingerprint"]:c for c in candidates}
            valid=[]
            for decision in data.get("evaluations",[]):
                fp=decision.get("fingerprint")
                if fp in by_fp: valid.append({"fingerprint":fp,"decision":decision})
            # Missing decisions are explicitly dismissed to prevent endless retries.
            seen={v["fingerprint"] for v in valid}
            valid.extend({"fingerprint":fp,"decision":{"action":"skip","rationale":"模型未返回该候选"}} for fp in by_fp if fp not in seen)
            apply_evaluations(valid); record_evaluation_batch(f"评估 {len(valid)} 条")
            self.completed.emit({"evaluated":len(valid),"approved":sum(v["decision"].get("action") in ("contact","check_in","remind") for v in valid)})
        except Exception as exc:
            try:
                from brain.memory_proactive import record_evaluation_batch
                record_evaluation_batch(f"失败：{exc}")
            except Exception:
                pass
            self.failed.emit(str(exc))
