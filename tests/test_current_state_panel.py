import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox

from brain import current_state
from brain import graph_memory
from gui.current_state_panel import CurrentStateEditor, CurrentStatePanel
from gui.memory_settings_dialog import MemorySettingsDialog


class CurrentStatePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = graph_memory._DB_PATH
        self.old_conn = getattr(graph_memory._local, "conn", None)
        graph_memory._local.conn = None
        graph_memory._DB_PATH = Path(self.tmp.name) / "state-panel.db"

    def tearDown(self):
        conn = getattr(graph_memory._local, "conn", None)
        if conn is not None:
            conn.close()
        graph_memory._local.conn = self.old_conn
        graph_memory._DB_PATH = self.old_db
        self.tmp.cleanup()

    @staticmethod
    def _row_count(panel):
        return sum(
            panel._list_layout.itemAt(index).widget() is not None
            and panel._list_layout.itemAt(index).widget().objectName() == "current_state_row"
            for index in range(panel._list_layout.count())
        )

    def test_editor_returns_user_editable_state_values(self):
        editor = CurrentStateEditor()
        editor.content_edit.setPlainText("用户正在准备产品发布")
        editor.type_combo.setCurrentIndex(editor.type_combo.findData("project"))
        values = editor.values()

        self.assertEqual("用户正在准备产品发布", values["content"])
        self.assertEqual("project", values["state_type"])
        self.assertTrue(values["expires_at"])
        editor.close()

    def test_panel_filters_active_and_historical_states(self):
        active = current_state.set_current_state(
            "用户正在准备产品发布", "project", duration_days=7
        )
        current_state.resolve_current_state(active["id"], "项目已完成")
        current_state.set_current_state("用户正在杭州出差", "location", duration_days=7)

        panel = CurrentStatePanel()
        self.assertEqual(1, self._row_count(panel))
        panel.filter_combo.setCurrentIndex(panel.filter_combo.findData("all"))
        self.app.processEvents()
        self.assertEqual(2, self._row_count(panel))
        panel.close()

    def test_resolve_action_updates_store_and_refreshes_panel(self):
        state = current_state.set_current_state("用户今天心情低落", "emotion")
        panel = CurrentStatePanel()
        with patch(
            "gui.current_state_panel.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ), patch.object(panel, "_reason_dialog", return_value=("已经恢复", True)):
            panel._resolve_state(state)

        self.assertEqual([], current_state.list_current_states())
        panel.close()

    def test_memory_settings_embeds_current_state_tab(self):
        dialog = MemorySettingsDialog()
        tab_titles = [dialog._tabs.tabText(index) for index in range(dialog._tabs.count())]

        self.assertEqual(5, dialog._tabs.count())
        self.assertTrue(any("当前状态" in title for title in tab_titles))
        self.assertIs(dialog._current_state_panel, dialog._tabs.widget(3))
        dialog.close()

if __name__ == "__main__":
    unittest.main()
