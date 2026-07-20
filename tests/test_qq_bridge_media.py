import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workers.qq_bridge_worker import QQBridgeWorker


class QQBridgeMediaTests(unittest.TestCase):
    def test_observation_capture_is_sent_as_image_segment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "capture.png"
            image_path.write_bytes(b"png")

            class BridgeStub:
                def __init__(self):
                    self.params = None
                    self.logs = []

                def _send_msg(self, params):
                    self.params = params
                    return True

                def _log(self, message):
                    self.logs.append(message)

            bridge = BridgeStub()
            observation = {"path": str(image_path), "desc": "desktop"}
            with patch("brain.tools.get_observation_image", return_value=observation):
                sent = QQBridgeWorker._send_observation_image(
                    bridge,
                    {"message_type": "private", "user_id": 123},
                )

            self.assertTrue(sent)
            self.assertEqual("image", bridge.params["message"][0]["type"])
            self.assertTrue(
                bridge.params["message"][0]["data"]["file"].startswith("file:///")
            )


if __name__ == "__main__":
    unittest.main()
