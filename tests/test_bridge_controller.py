import unittest

from gui.bridge_controller import BridgeController


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in self.callbacks:
            callback(*args)


class _QQWorker:
    def __init__(self):
        self.debug_log = _Signal()
        self.connected = _Signal()
        self.disconnected = _Signal()
        self.error_occurred = _Signal()
        self.running = False
        self.stopped = False
        self.timing_reloads = 0
        self.fast_reply_enabled = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def stop(self):
        self.stopped = True
        self.running = False

    def wait(self, _timeout):
        return True

    def reload_timing_config(self):
        self.timing_reloads += 1

    def reload_bridge_config(self):
        pass

    def set_fast_reply_enabled(self, enabled):
        self.fast_reply_enabled = bool(enabled)


class _WeChatWorker:
    def __init__(self):
        self.log_message = _Signal()
        self.connection_changed = _Signal()
        self.running = False
        self.reloads = 0

    def start_bridge(self):
        self.running = True
        self.connection_changed.emit(True)

    def stop_bridge(self):
        self.running = False
        self.connection_changed.emit(False)

    def is_running(self):
        return self.running

    def reload_config(self):
        self.reloads += 1


class _Widget:
    def __init__(self):
        self.tips = []

    def add_system_tip(self, text):
        self.tips.append(text)


class _Button:
    def __init__(self):
        self.text = ""
        self.style = ""

    def setText(self, text):
        self.text = text

    def setStyleSheet(self, style):
        self.style = style


class BridgeControllerTests(unittest.TestCase):
    def setUp(self):
        self.chat = _Widget()
        self.button = _Button()
        self.warnings = []
        self.registered = []
        self.qq_worker = _QQWorker()
        self.wechat_worker = _WeChatWorker()
        self.qq_config = {"enabled": True, "auto_start": True, "qq_account": "123"}
        self.wechat_config = {"auto_start": True}
        self.controller = BridgeController(
            chat_widget=self.chat,
            qq_button=self.button,
            warning_func=lambda title, text: self.warnings.append((title, text)),
            qq_worker_factory=lambda: self.qq_worker,
            wechat_worker_factory=lambda: self.wechat_worker,
            register_qq_bridge_func=self.registered.append,
            qq_config_func=lambda: self.qq_config,
            wechat_config_func=lambda: self.wechat_config,
        )

    def tearDown(self):
        self.controller.shutdown()

    def test_qq_lifecycle_registers_worker_and_updates_connection_state(self):
        self.assertTrue(self.controller.start_qq())
        self.assertIs(self.qq_worker, self.registered[-1])
        self.qq_worker.connected.emit()
        self.assertTrue(self.controller.is_qq_connected())
        self.assertEqual("✅ QQ聊天", self.button.text)

        self.controller.stop_qq()
        self.assertTrue(self.qq_worker.stopped)
        self.assertIsNone(self.registered[-1])

    def test_missing_qq_account_is_rejected_before_worker_creation(self):
        self.qq_config["qq_account"] = ""
        self.assertFalse(self.controller.start_qq())
        self.assertEqual(1, len(self.warnings))
        self.assertIsNone(self.controller.qq_bridge)

    def test_auto_start_respects_each_bridge_configuration(self):
        self.assertTrue(self.controller.should_auto_start_qq())
        self.assertTrue(self.controller.should_auto_start_wechat())
        self.qq_config["enabled"] = False
        self.wechat_config["auto_start"] = False
        self.assertFalse(self.controller.should_auto_start_qq())
        self.assertFalse(self.controller.should_auto_start_wechat())

    def test_fast_reply_state_is_runtime_only_and_reaches_worker(self):
        self.controller.set_qq_fast_reply_enabled(True)
        self.assertTrue(self.controller.is_qq_fast_reply_enabled())

        self.assertTrue(self.controller.start_qq())
        self.assertTrue(self.qq_worker.fast_reply_enabled)

        self.controller.set_qq_fast_reply_enabled(False)
        self.assertFalse(self.qq_worker.fast_reply_enabled)

    def test_wechat_lifecycle_and_shutdown(self):
        self.assertTrue(self.controller.start_wechat())
        self.assertTrue(self.controller.is_wechat_running())
        self.assertTrue(self.controller.reload_wechat_config())
        self.assertEqual(1, self.wechat_worker.reloads)

        self.controller.shutdown()
        self.assertFalse(self.wechat_worker.running)
        self.assertIsNone(self.controller.wechat_bridge)


if __name__ == "__main__":
    unittest.main()
