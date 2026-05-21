from PyQt5.QtCore import QThread, pyqtSignal
from brain.agent import AgentCore

class SmartReminderWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, reminder_name: str, is_combined: bool = False):
        super().__init__()
        self.reminder_name = reminder_name
        self.is_combined = is_combined

    def run(self):
        agent = AgentCore()
        if self.is_combined:
            prompt = f"请根据以下提醒事项列表：「{self.reminder_name}」，用莲心的口吻（可以带一点傲娇、毒舌或温柔，但保持简洁）生成一句简短的提醒，将多个提醒融合在一句话里，不超过30字。不要带多余的解释。"
        else:
            prompt = f"请根据提醒事项「{self.reminder_name}」，用莲心的口吻（可以带一点傲娇、毒舌或温柔，但保持简洁）生成一句简短的提醒，不超过20字。不要带多余的解释。"
        try:
            response = agent._call_api_with_retry([{"role": "user", "content": prompt}])
            text = response.choices[0].message.content.strip()
        except Exception:
            if self.is_combined:
                text = f"⏰ 莲心提醒：有{len(self.reminder_name.split('、'))}个事情需要你注意哦～"
            else:
                text = f"⏰ 莲心提醒：{self.reminder_name}（记得抽空完成噢）"
        self.finished.emit(text)