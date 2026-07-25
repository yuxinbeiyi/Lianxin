import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea

from gui.character_widget import CharacterWidget


class CharacterWidgetFunctionPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.widget = CharacterWidget()
        self.widget.resize(400, 760)
        self.widget.show()
        self.app.processEvents()

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    def test_keeps_all_business_button_interfaces(self):
        getters = (
            "get_accompany_button", "get_settings_button", "get_study_room_button",
            "get_api_config_button", "get_alarm_button", "get_camera_button",
            "get_emotion_button", "get_sound_button", "get_memory_button",
            "get_network_button", "get_capability_button", "get_persona_button",
            "get_constellation_button",
            "get_proactive_button",
            "get_qq_bridge_button", "get_wechat_bridge_button", "get_diary_button",
            "get_voice_stt_button",
        )
        buttons = [getattr(self.widget, name)() for name in getters]

        self.assertEqual(18, len(buttons))
        self.assertEqual(18, len({id(button) for button in buttons}))
        self.assertTrue(all(isinstance(button, QPushButton) for button in buttons))

    def test_uses_grouped_dark_cards_in_scroll_area(self):
        cards = self.widget._function_popup.findChildren(QPushButton, "function_card")
        group_titles = self.widget._function_popup.findChildren(
            QLabel, "function_group_title"
        )

        self.assertEqual(18, len(cards))
        self.assertEqual(
            ["常用", "莲心", "感知与声音", "连接与服务"],
            [label.text() for label in group_titles],
        )
        self.assertIsNotNone(
            self.widget._function_popup.findChild(QScrollArea, "function_scroll_area")
        )
        for card in cards:
            self.assertEqual(46, card.height())
            self.assertIn("background-color: #252538", card.styleSheet())
            self.assertIn("border-left: 3px solid", card.styleSheet())

    def test_toggle_fades_panel_without_changing_its_state_contract(self):
        self.assertFalse(self.widget._function_expanded)
        self.assertTrue(self.widget._function_popup.isHidden())

        self.widget._toggle_function_panel()
        QTest.qWait(220)
        self.assertTrue(self.widget._function_expanded)
        self.assertFalse(self.widget._function_popup.isHidden())
        self.assertEqual("▼ 收起", self.widget._btn_function_toggle.text())
        self.assertAlmostEqual(1.0, self.widget._function_opacity.opacity(), places=2)

        self.widget._toggle_function_panel()
        QTest.qWait(220)
        self.assertFalse(self.widget._function_expanded)
        self.assertTrue(self.widget._function_popup.isHidden())
        self.assertEqual("▲ 功能中心", self.widget._btn_function_toggle.text())


if __name__ == "__main__":
    unittest.main()
