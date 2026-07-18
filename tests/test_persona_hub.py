import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QTextEdit
from PyQt5.QtWidgets import QMessageBox

from brain.persona import PersonaManager, PersonaStore
from gui.persona_hub import PersonaHub


class PersonaHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = PersonaManager(PersonaStore(Path(self.temp.name) / "personas"))
        self.hub = PersonaHub(manager=self.manager)
        self.hub.show()
        self.app.processEvents()

    def tearDown(self):
        self.hub._dirty = False
        self.hub.close()
        self.hub.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_large_native_window_and_default_profile_are_ready(self):
        flags = self.hub.windowFlags()
        self.assertTrue(flags & Qt.WindowMinimizeButtonHint)
        self.assertTrue(flags & Qt.WindowMaximizeButtonHint)
        self.assertGreaterEqual(self.hub.minimumWidth(), 900)
        self.assertGreaterEqual(self.hub.minimumHeight(), 620)
        self.assertEqual("默认莲心", self.hub._current_profile.profile_name)
        self.assertIn("使用旧版人格 Prompt", self.hub._active_label.text())

    def test_editor_saves_draft_without_hot_applying_it(self):
        original_snapshot = self.manager.get_snapshot()
        self.hub._editors["assistant_name"].setText("新莲心")

        self.assertTrue(self.hub._dirty)
        self.assertTrue(self.hub._save_current())

        stored = self.manager.load_profile(self.hub._current_profile.id)
        self.assertEqual("新莲心", stored.assistant_name)
        self.assertEqual("莲心", original_snapshot.profile.assistant_name)
        self.assertEqual("莲心", self.manager.get_snapshot().profile.assistant_name)

    def test_preview_contains_editable_persona_and_read_only_policy(self):
        self.hub._editors["assistant_name"].setText("棱镜")
        self.app.processEvents()

        preview = self.hub._preview.toPlainText()
        self.assertIn("你的名字是“棱镜”", preview)
        self.assertIn("不可编辑的系统规则", preview)
        self.assertIn("工具优先", preview)
        self.assertGreater(len(self.hub.findChildren(QTextEdit)), 1)

    def test_switching_profiles_can_save_dirty_draft_without_stale_item_crash(self):
        default_id = self.hub._current_profile.id
        created = self.manager.create_profile("第二人格")
        self.hub._refresh_profiles(default_id)
        self.hub._editors["summary"].setPlainText("切换前保存的简介")
        target = next(
            self.hub._profile_list.item(index)
            for index in range(self.hub._profile_list.count())
            if self.hub._profile_list.item(index).data(Qt.UserRole) == created.id
        )

        with patch("gui.persona_hub.QMessageBox.question", return_value=QMessageBox.Save):
            self.hub._profile_list.setCurrentItem(target)

        self.assertEqual(created.id, self.hub._current_profile.id)
        self.assertEqual(
            "切换前保存的简介",
            self.manager.load_profile(default_id).summary,
        )

    def test_fullscreen_can_return_to_windowed_mode(self):
        self.hub._toggle_fullscreen()
        self.app.processEvents()
        self.assertTrue(self.hub.isFullScreen())
        self.hub._toggle_fullscreen()
        self.app.processEvents()
        self.assertFalse(self.hub.isFullScreen())


if __name__ == "__main__":
    unittest.main()
