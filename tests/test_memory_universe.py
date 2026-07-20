import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication


class MemoryUniverseUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_universe_window_has_layers_navigation_and_controls(self):
        from gui.memory_universe import MemoryUniverseWindow
        window = MemoryUniverseWindow()
        self.assertEqual(4, window._layer.count())
        self.assertTrue(window._back_btn)
        self.assertTrue(window._search)
        self.assertTrue(window._timeline)
        self.assertTrue(window._motion_btn)
        self.assertEqual("经历星座", window._layer.itemText(2))
        self.assertEqual("长期故事", window._layer.itemText(3))
        window._on_parallax(0.5, -0.5)
        self.assertEqual(0.5, window._parallax_x)
        previous_motion = window._reduced_motion
        window._toggle_motion()
        self.assertNotEqual(previous_motion, window._reduced_motion)
        self.assertLessEqual(window._max_visible_nodes, 1000)
        window._layer.setCurrentIndex(2)
        self.assertTrue(window._back_btn.isEnabled())
        window._go_back()
        self.assertEqual("universe", window._layer.currentData())
        window.close()


if __name__ == "__main__":
    unittest.main()
