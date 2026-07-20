import json
import unittest
from pathlib import Path


class MemoryConstellationWebTests(unittest.TestCase):
    def test_canvas_assets_and_data_placeholder_exist(self):
        root = Path(__file__).resolve().parents[1] / "assets" / "memory_constellation"
        html = (root / "index.html").read_text(encoding="utf-8")
        script = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn("<!-- LIANXIN_DATA -->", html)
        self.assertIn("requestAnimationFrame", script)
        self.assertIn("parallax", script)
        self.assertIn("人物星系", script)
        self.assertIn("星尘观测日志", html)
        self.assertIn("qrc:///qtwebchannel/qwebchannel.js", html)
        self.assertTrue((root / "styles.css").exists())
        json.dumps({"entities": []}, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
