from PyQt5.QtCore import QThread, pyqtSignal
from brain.agent import AgentCore
from config import get_user_name
from brain.persona.runtime import (
    active_assistant_name,
    capture_persona_snapshot,
    compose_scene_prompt,
)

class SmartReminderWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, reminder_name: str, is_combined: bool = False):
        super().__init__()
        self.reminder_name = reminder_name
        self.is_combined = is_combined

    def run(self):
        agent = AgentCore()
        snapshot = capture_persona_snapshot()
        assistant_name = active_assistant_name(snapshot)
        if self.is_combined:
            legacy_prompt = f"请根据以下提醒事项列表：「{self.reminder_name}」，用莲心的口吻（可以带一点傲娇、毒舌或温柔，但保持简洁）生成一句简短的提醒，将多个提醒融合在一句话里，不超过30字。不要带多余的解释。"
        else:
            legacy_prompt = f"请根据提醒事项「{self.reminder_name}」，用莲心的口吻（可以带一点傲娇、毒舌或温柔，但保持简洁）生成一句简短的提醒，不超过20字。不要带多余的解释。"
        prompt = compose_scene_prompt(
            legacy_prompt, user_name=get_user_name(), snapshot=snapshot,
            scene="proactive",
        )
        try:
            response = agent._call_api_with_retry([{"role": "user", "content": prompt}])
            text = response.choices[0].message.content.strip()
        except Exception:
            if self.is_combined:
                text = f"⏰ {assistant_name}提醒：有{len(self.reminder_name.split('、'))}个事情需要你注意哦～"
            else:
                text = f"⏰ {assistant_name}提醒：{self.reminder_name}（记得抽空完成噢）"
        self.finished.emit(text)
