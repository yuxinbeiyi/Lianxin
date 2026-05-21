"""
AgentWorker：在后台线程中运行 AI 对话，防止 GUI 卡顿。
通过 Qt 信号将结果传回主线程。
支持三层架构路由：根据 disable_tools 决定是否走工具调用。
"""

from PyQt5.QtCore import QThread, pyqtSignal
from brain.agent import AgentCore
from brain.decision import decide


class AgentWorker(QThread):
    response_ready = pyqtSignal(str)
    tool_called    = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, agent: AgentCore, message: str, parent=None,
                 forced_tool: str = None, disable_tools: bool = False):
        super().__init__(parent)
        self.agent         = agent
        self.message       = message
        self.forced_tool   = forced_tool
        self.disable_tools = disable_tools

    def run(self):
        try:
            def on_tool_call(name, args):
                self.tool_called.emit(name)

            response = self.agent.chat(
                self.message,
                on_tool_call=on_tool_call,
                forced_tool=self.forced_tool,
                disable_tools=self.disable_tools,
            )
            self.response_ready.emit(response)
        except Exception as e:
            self.error_occurred.emit(str(e))