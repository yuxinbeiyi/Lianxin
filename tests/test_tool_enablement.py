import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from brain.tool_enablement import EnablementTarget, enable_target, resolve_disabled_target


class ToolEnablementTests(unittest.TestCase):
    def test_only_disabled_builtin_tool_can_be_resolved(self):
        with patch("config.get_builtin_tool_config", return_value={"web_search": False}):
            target = resolve_disabled_target("web_search")
            self.assertIsNotNone(target)
            self.assertEqual("builtin", target.kind)
            self.assertEqual(("web_search",), target.tool_names)
            self.assertIsNone(resolve_disabled_target("unknown_tool"))

    def test_enable_builtin_uses_existing_configuration_writer(self):
        state = {"web_search": False}

        def get_config():
            return dict(state)

        def save_config(updated):
            state.update(updated)

        target = EnablementTarget("web_search", "联网搜索", "builtin", ("web_search",))
        with patch("config.get_builtin_tool_config", side_effect=get_config), \
             patch("config.save_builtin_tool_config", side_effect=save_config):
            self.assertTrue(enable_target(target))
        self.assertTrue(state["web_search"])

    def test_enabled_tool_is_not_an_authorization_target(self):
        with patch("config.get_builtin_tool_config", return_value={"web_search": True}):
            self.assertIsNone(resolve_disabled_target("web_search"))


class CapabilityCatalogTests(unittest.TestCase):
    def test_core_catalog_matches_tool_definitions(self):
        from brain.capability_catalog import CATEGORY_ORDER, list_capabilities
        from brain.tools import TOOL_DEFINITIONS, TOOL_EXECUTORS

        defined = {item["function"]["name"] for item in TOOL_DEFINITIONS}
        catalog = {item.name: item for item in list_capabilities() if item.source_kind == "builtin"}
        self.assertEqual(defined, set(catalog))
        self.assertEqual(defined, set(TOOL_EXECUTORS))
        self.assertTrue(all(item.category in CATEGORY_ORDER for item in catalog.values()))

    def test_catalog_search_and_favorite_compatibility(self):
        from brain.capability_catalog import load_favorites, search_capabilities, toggle_favorite

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "favorite_tools.json"
            path.write_text(json.dumps({"favorites": ["web_search"]}), encoding="utf-8")
            with patch("brain.capability_catalog._favorites_path", return_value=path):
                self.assertEqual({"web_search"}, load_favorites())
                self.assertFalse(toggle_favorite("web_search"))
                self.assertIn("read_file", {item.name for item in search_capabilities("文件")})


class CapabilityKnowledgeTests(unittest.TestCase):
    def test_self_knowledge_is_an_index_not_a_full_tool_prompt(self):
        from brain.self_model import build_self_knowledge_context

        context = build_self_knowledge_context()
        self.assertIn("query_capabilities", context)
        self.assertNotIn("当前可调用能力清单", context)

    def test_capability_inquiry_detection_is_explicit(self):
        from brain.capability_knowledge import is_capability_inquiry

        self.assertTrue(is_capability_inquiry("你有哪些功能？"))
        self.assertTrue(is_capability_inquiry("你能不能看图片？"))
        self.assertFalse(is_capability_inquiry("今天心情怎么样？"))
        self.assertFalse(is_capability_inquiry("帮我整理这份文档"))

    def test_capability_tool_uses_unified_runtime_catalog(self):
        from brain.tools import TOOL_DEFINITIONS, TOOL_EXECUTORS

        names = {item["function"]["name"] for item in TOOL_DEFINITIONS}
        self.assertIn("query_capabilities", names)
        self.assertIn("query_capabilities", TOOL_EXECUTORS)
        result = TOOL_EXECUTORS["query_capabilities"]({"query": "", "limit": 1})
        self.assertIn("能力目录版本", result)


class PersonaGrowthTests(unittest.TestCase):
    def test_feedback_becomes_structured_whitelisted_preference(self):
        from brain.persona.growth import PersonaGrowthService, PersonaGrowthStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = PersonaGrowthService(PersonaGrowthStore(root / "growth.db"), root / "settings.json")
            event = service.observe_feedback("default", "以后你可以先给结论，再补充细节")
            self.assertEqual("response_structure", event.field)
            self.assertEqual("conclusion_first", event.proposed_value)
            self.assertNotIn("以后你可以", event.detail)
            self.assertIsNone(service.observe_feedback("default", "以后你可以做任何事"))

    def test_conflict_requires_confirmation_and_versions_can_roll_back(self):
        from brain.persona.growth import PersonaGrowthService, PersonaGrowthStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = PersonaGrowthService(PersonaGrowthStore(root / "growth.db"), root / "settings.json")
            compact = service.observe_feedback("default", "以后你可以回答更简短一些")
            compact = service.store.set_status(compact.id, "applied")
            detailed = service.observe_feedback("default", "以后你可以回答更详细一些")
            self.assertEqual("pending", detailed.status)
            self.assertEqual("confirmation_required", detailed.risk)
            detailed = service.store.set_status(detailed.id, "applied")
            self.assertGreater(detailed.version_id, compact.version_id)
            reverted = service.store.rollback_to_version("default", compact.version_id)
            self.assertEqual([detailed.id], [item.id for item in reverted])
            self.assertIn("compact", service.dynamic_context("default"))

    def test_growth_candidate_is_deduplicated_and_can_be_reverted(self):
        from brain.persona.growth import PersonaGrowthService, PersonaGrowthStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = PersonaGrowthService(
                PersonaGrowthStore(root / "growth.db"), root / "settings.json"
            )
            event = service.propose(
                persona_id="default", kind="interaction_style", title="test",
                detail="explicit preference", evidence="test", confidence=0.9,
            )
            self.assertIsNotNone(event)
            self.assertIsNone(service.propose(
                persona_id="default", kind="interaction_style", title="test",
                detail="explicit preference", evidence="test", confidence=0.9,
            ))
            applied = service.store.set_status(event.id, "applied")
            self.assertIn("explicit preference", service.dynamic_context("default"))
            reverted = service.store.set_status(applied.id, "reverted")
            self.assertEqual("reverted", reverted.status)
            self.assertEqual("", service.dynamic_context("default"))

    def test_low_risk_auto_and_proactive_cooldown(self):
        from brain.persona.growth import PersonaGrowthService, PersonaGrowthStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = PersonaGrowthService(
                PersonaGrowthStore(root / "growth.db"), root / "settings.json"
            )
            service.save_settings({"mode": "low_risk_auto"})
            event = service.observe_feedback("default", "以后你可以先给结论")
            self.assertEqual("pending", event.status)
            event = service.observe_feedback("default", "希望你以后先给结论")
            self.assertEqual("applied", event.status)
            self.assertIsNotNone(service.next_proactive_request("default"))
            service.save_settings({"last_proactive_request_at": "2099-01-01T00:00:00+00:00"})
            self.assertIsNone(service.next_proactive_request("default"))

    def test_growth_pause_export_and_proactive_rejection_policy(self):
        from brain.persona.growth import PersonaGrowthService, PersonaGrowthStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = PersonaGrowthService(PersonaGrowthStore(root / "growth.db"), root / "settings.json")
            event = service.observe_feedback("default", "以后你可以先给结论")
            self.assertIn("events", service.export_events("default"))
            service.pause_growth(1)
            self.assertIsNone(service.observe_feedback("default", "以后你可以回答更简短一些"))
            service.record_proactive_result("photo_invite", "reject")
            service.record_proactive_result("photo_invite", "reject")
            settings = service.settings()
            self.assertEqual(2, settings["proactive_rejections"]["photo_invite"])
            service.clear_events("default")
            self.assertEqual([], service.store.list("default"))

    def test_growth_summary_and_expiry_keep_audit_record(self):
        from brain.persona.growth import PersonaGrowthService, PersonaGrowthStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = PersonaGrowthStore(root / "growth.db")
            service = PersonaGrowthService(store, root / "settings.json")
            event = service.observe_feedback("default", "以后你可以先给结论")
            event = store.set_status(event.id, "applied")
            conn = store._connect()
            try:
                conn.execute("UPDATE persona_growth_events SET applied_at='2000-01-01T00:00:00+00:00' WHERE id=?", (event.id,))
            finally:
                conn.close()
            expired = service.review_expired("default", days=30)
            self.assertEqual("expired", expired[0].status)
            summary = service.summary("default")
            self.assertEqual(1, summary["counts"]["expired"])
            self.assertTrue(summary["local_only"])


if __name__ == "__main__":
    unittest.main()
