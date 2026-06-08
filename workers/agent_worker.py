"""Agent 工作线程。

在后台线程中同步调用 AgentCore.chat()，
通过 Qt 信号将结果传递回主线程。

支持「中途插话」：GUI 线程通过 send_interrupt() 投递消息，
Worker 在工具调用间隙处理并报告进度。
"""
import queue
from PyQt5.QtCore import QThread, pyqtSignal
from brain.agent import AgentCore

_INTERRUPT_SYSTEM = """【用户中途插话】
用户刚刚说："{msg}"

请遵守以下规则回复：
1. 用1~2句话简要回复当前进度或回答用户问题（不超过50字）
2. 不要调用任何工具
3. 不要输出情绪标签
4. 如果用户说的是"取消""别做了""停下""不要了"等取消指令，
   回复"好的，已取消~"并在结尾加 [终止]
5. 如果用户说的是"改成""换个""用...代替"等修正指令，
   回复"好的，已修正~"并在结尾加 [修正]
6. 其他情况（如"进度如何""到哪了"）简要报告当前进展，
   并在结尾加 [继续]"""


class AgentWorker(QThread):
    response_ready = pyqtSignal(str)
    progress_update = pyqtSignal(str)   # 插话进度回复（仅追加文字，不改动画状态）
    tool_called    = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, agent: AgentCore, message: str, parent=None,
                 forced_tool: str = None, disable_tools: bool = False):
        super().__init__(parent)
        self.agent         = agent
        self.message       = message
        self.forced_tool   = forced_tool
        self.disable_tools = disable_tools
        self.interrupt_queue: queue.Queue = queue.Queue()

    def send_interrupt(self, msg: str):
        """GUI 线程调用：向工作线程发送一条插话消息。最多缓存 5 条。"""
        msg = msg.strip()
        if msg and self.interrupt_queue.qsize() < 5:
            self.interrupt_queue.put(msg)

    def _process_interrupt(self, interrupt_msg: str) -> str:
        """Worker 线程内调用：用 LLM 处理一条插话，返回简短回复。"""
        try:
            import litellm
            interrupt_messages = [
                {"role": "system",
                 "content": _INTERRUPT_SYSTEM.format(msg=interrupt_msg)},
            ]
            response = litellm.completion(
                model=self.agent._model,
                max_tokens=120,
                messages=interrupt_messages,
                api_key=self.agent._api_key,
                api_base=self.agent._api_base,
                timeout=12,
            )
            return response.choices[0].message.content or "（收到，正在继续…）"
        except Exception:
            return "（收到，正在处理中…）"

    def run(self):
        try:
            def on_tool_call(name, args):
                self.tool_called.emit(name)

            response = self.agent.chat(
                self.message,
                on_tool_call=on_tool_call,
                forced_tool=self.forced_tool,
                disable_tools=self.disable_tools,
                interrupt_queue=self.interrupt_queue,
                on_interrupt=self._process_interrupt,
                on_progress=lambda text: self.progress_update.emit(text),
            )
            self.response_ready.emit(response)
        except Exception as e:
            self.error_occurred.emit(str(e))
