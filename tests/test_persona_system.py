import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import config
from brain.agent import AgentCore
from brain.persona import (
    DEFAULT_PERSONA_ID,
    PersonaManager,
    PersonaProfile,
    PersonaPromptComposer,
    PersonaSnapshot,
    PersonaStore,
    PersonaStoreError,
    PersonaValidationError,
    build_default_persona,
    compose_scene_prompt,
)
from utils.diary import _build_diary_prompt
from workers.proactive_worker import _PROACTIVE_SYSTEM, _format_prompt
from workers.slack_worker import SlackWorker


class LegacyPersonaBaselineTests(unittest.TestCase):
    def test_legacy_base_prompt_contract_remains_intact(self):
        with (
            patch("config.get_user_name", return_value="测试用户"),
            patch("config.get_search_fallback_config", return_value={}),
            patch("config.get_builtin_tool_config", return_value={}),
        ):
            prompt = config.get_base_prompt()

        self.assertIn("你是莲心", prompt)
        self.assertIn('称呼用户为"测试用户"', prompt)
        self.assertIn("【聊天风格要求】", prompt)
        self.assertIn("【最高铁律——工具优先，不可违反】", prompt)
        self.assertIn("【表情：XXX】", prompt)

    def test_core_policy_excludes_legacy_identity_when_marker_exists(self):
        legacy = "旧人格内容\n【最高铁律——工具优先，不可违反】\n核心规则"
        with patch("config.get_base_prompt", return_value=legacy):
            policy = config.get_core_system_policy()
        self.assertNotIn("旧人格内容", policy)
        self.assertTrue(policy.startswith("【最高铁律——工具优先，不可违反】"))


class PersonaModelAndStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "personas"
        self.store = PersonaStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_default_profile_is_initialized_without_enabling_new_runtime(self):
        self.store.ensure_initialized()

        default = self.store.load_profile(DEFAULT_PERSONA_ID)
        state = self.store.read_state()

        self.assertEqual("莲心", default.assistant_name)
        self.assertTrue(default.is_builtin)
        self.assertEqual(DEFAULT_PERSONA_ID, state["active_id"])
        self.assertFalse(state["enabled"])

    def test_profile_round_trip_and_backup(self):
        self.store.ensure_initialized()
        original = self.store.load_profile(DEFAULT_PERSONA_ID)
        edited = original.updated(speaking_style="更简洁，但仍然自然。")

        self.store.save_profile(edited)

        self.assertEqual(edited, self.store.load_profile(DEFAULT_PERSONA_ID))
        backup_path = self.store.profile_path(DEFAULT_PERSONA_ID).with_suffix(".json.bak")
        backup = PersonaProfile.from_dict(json.loads(backup_path.read_text(encoding="utf-8")))
        self.assertEqual(original.speaking_style, backup.speaking_style)
        self.assertEqual([], list(self.root.glob("*.tmp.*")))

    def test_invalid_profile_is_rejected_before_write(self):
        profile = replace(build_default_persona(), id="../escape", is_builtin=False)
        with self.assertRaises(PersonaValidationError):
            self.store.save_profile(profile)
        self.assertFalse((self.root.parent / "escape.json").exists())

    def test_damaged_active_profile_falls_back_to_disabled_default(self):
        self.store.ensure_initialized()
        broken_id = "broken-profile"
        broken_path = self.store.profile_path(broken_id)
        broken_path.write_text("{not-json", encoding="utf-8")
        self.store.write_state({"enabled": True, "active_id": broken_id})

        manager = PersonaManager(self.store)
        snapshot = manager.get_snapshot()

        self.assertEqual(DEFAULT_PERSONA_ID, snapshot.profile.id)
        self.assertFalse(snapshot.enabled)
        self.assertEqual(DEFAULT_PERSONA_ID, self.store.read_state()["active_id"])


class PersonaManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PersonaStore(Path(self.temp.name) / "personas")
        self.manager = PersonaManager(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_save_is_draft_until_explicit_activation(self):
        created = self.manager.create_profile("冷静研究员")
        draft = created.updated(assistant_name="棱镜")
        self.manager.save_profile(draft)

        self.assertEqual("莲心", self.manager.get_snapshot().profile.assistant_name)

        snapshot = self.manager.activate(created.id)
        self.assertEqual("棱镜", snapshot.profile.assistant_name)
        self.assertTrue(snapshot.enabled)
        self.assertGreater(snapshot.revision, 0)

    def test_activation_notifies_listener_and_unsubscribe_stops_it(self):
        created = self.manager.create_profile("测试人格")
        received = []
        unsubscribe = self.manager.subscribe(received.append)

        first = self.manager.activate(created.id)
        unsubscribe()
        self.manager.activate(DEFAULT_PERSONA_ID)

        self.assertEqual([first], received)

    def test_listener_can_safely_trigger_another_activation(self):
        created = self.manager.create_profile("跳转人格")

        def return_to_default(snapshot):
            if snapshot.profile.id == created.id:
                self.manager.activate(DEFAULT_PERSONA_ID)

        self.manager.subscribe(return_to_default)
        self.manager.activate(created.id)

        self.assertEqual(DEFAULT_PERSONA_ID, self.manager.get_snapshot().profile.id)
        self.assertEqual(DEFAULT_PERSONA_ID, self.store.read_state()["active_id"])

    def test_active_and_builtin_profiles_cannot_be_deleted(self):
        created = self.manager.create_profile("临时人格")
        self.manager.activate(created.id)
        with self.assertRaises(PersonaStoreError):
            self.manager.delete_profile(created.id)
        self.manager.activate(DEFAULT_PERSONA_ID)
        with self.assertRaises(PersonaStoreError):
            self.manager.delete_profile(DEFAULT_PERSONA_ID)

    def test_concurrent_activation_keeps_disk_and_snapshot_consistent(self):
        first = self.manager.create_profile("人格一")
        second = self.manager.create_profile("人格二")

        def switch(profile_id):
            for _ in range(15):
                self.manager.activate(profile_id)

        threads = [
            threading.Thread(target=switch, args=(first.id,)),
            threading.Thread(target=switch, args=(second.id,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(
            self.manager.get_snapshot().profile.id,
            self.store.read_state()["active_id"],
        )
        self.assertEqual(30, self.manager.get_snapshot().revision)


class PersonaPromptComposerTests(unittest.TestCase):
    def test_compiler_keeps_editable_persona_separate_from_core_policy(self):
        profile = build_default_persona().updated(
            assistant_name="测试莲心",
            user_address="队长 {user_name}",
            custom_instructions="回答时保持克制。",
        )
        snapshot = PersonaSnapshot(
            profile=profile,
            revision=7,
            enabled=True,
            activated_at="2026-07-18T00:00:00+00:00",
        )

        compiled = PersonaPromptComposer.compose(
            snapshot,
            user_name="雨心",
            core_policy="必须通过真实工具执行操作。",
            scene_policy="当前是 QQ 私聊。",
            dynamic_context=["当前时间：20:30"],
        )

        self.assertEqual(profile.id, compiled.persona_id)
        self.assertEqual(7, compiled.persona_revision)
        self.assertIn("你的名字是“测试莲心”", compiled.layers[0].content)
        self.assertIn("队长 雨心", compiled.layers[0].content)
        self.assertTrue(compiled.layers[0].editable)
        self.assertEqual("不可编辑的系统规则", compiled.layers[-1].name)
        self.assertFalse(compiled.layers[-1].editable)
        self.assertIn("必须通过真实工具执行操作", compiled.text)
        self.assertGreater(compiled.estimated_tokens, 0)
        self.assertTrue(all(message["role"] == "system" for message in compiled.as_messages()))

    def test_peripheral_scene_adapter_preserves_legacy_when_disabled(self):
        snapshot = PersonaSnapshot(
            profile=build_default_persona(),
            revision=0,
            enabled=False,
            activated_at="now",
        )
        prompt = compose_scene_prompt(
            "你是莲心。请称呼{user_name}。",
            user_name="雨心",
            snapshot=snapshot,
        )
        self.assertEqual("你是莲心。请称呼雨心。", prompt)

    def test_peripheral_generators_use_active_persona(self):
        profile = PersonaProfile(
            id="quiet-researcher",
            profile_name="冷静研究员",
            assistant_name="棱镜",
            identity="你是专注于分析问题的研究员。",
            personality="克制而耐心。",
            speaking_style="简洁、准确。",
            user_address="研究搭档 {user_name}",
        )
        snapshot = PersonaSnapshot(
            profile=profile,
            revision=3,
            enabled=True,
            activated_at="now",
        )

        proactive = _format_prompt(_PROACTIVE_SYSTEM, snapshot)
        slack = SlackWorker("random_question", "上下文")._get_system_prompt(snapshot)
        diary = _build_diary_prompt(
            [{"role": "assistant", "content": "旧回复"}], snapshot
        )

        for prompt in (proactive, slack, diary):
            self.assertIn("你的名字是“棱镜”", prompt)
            self.assertIn("简洁、准确", prompt)
            self.assertNotIn("你是莲心，一个", prompt)
        self.assertIn("[你（棱镜）]", diary)


class AgentPersonaHotSwitchTests(unittest.TestCase):
    @staticmethod
    def _profile(profile_id: str, name: str) -> PersonaProfile:
        return PersonaProfile(
            id=profile_id,
            profile_name=name,
            assistant_name=name,
            identity=f"你是{name}。",
            speaking_style="表达冷静、简洁。",
            user_address="{user_name}",
        )

    @staticmethod
    def _agent(history=None):
        agent = AgentCore.__new__(AgentCore)
        agent.history = list(history or [])
        agent._system_prompt = "LEGACY_PROMPT"
        agent._user_desc = "桌面端主人会话"
        agent._use_local = False
        agent._last_persona_key = None
        agent._persona_transition_remaining = 0
        return agent

    def test_disabled_persona_system_uses_exact_legacy_prompt(self):
        agent = self._agent([{"role": "assistant", "content": "旧回复"}])
        snapshot = PersonaSnapshot(
            profile=self._profile("researcher", "研究员"),
            revision=1,
            enabled=False,
            activated_at="now",
        )
        manager = type("Manager", (), {"get_snapshot": lambda self: snapshot})()

        with patch("brain.persona.get_persona_manager", return_value=manager):
            captured, transition = agent._prepare_persona_request()
        messages = agent._build_request_system_messages(captured)

        self.assertEqual([{"role": "system", "content": "LEGACY_PROMPT"}], messages)
        self.assertEqual("", transition)

    def test_existing_conversation_gets_two_transition_rounds(self):
        agent = self._agent([{"role": "assistant", "content": "旧人格回复"}])
        snapshot = PersonaSnapshot(
            profile=self._profile("researcher", "冷静研究员"),
            revision=4,
            enabled=True,
            activated_at="now",
        )
        manager = type("Manager", (), {"get_snapshot": lambda self: snapshot})()

        with patch("brain.persona.get_persona_manager", return_value=manager):
            _, first = agent._prepare_persona_request()
            _, second = agent._prepare_persona_request()
            _, third = agent._prepare_persona_request()

        self.assertIn("人格切换 — 内部指令", first)
        self.assertIn("只用于保留客观事实", first)
        self.assertIn("人格切换强化", second)
        self.assertEqual("", third)

    def test_new_request_composes_current_persona_without_mutating_legacy_prompt(self):
        agent = self._agent()
        snapshot = PersonaSnapshot(
            profile=self._profile("researcher", "冷静研究员"),
            revision=9,
            enabled=True,
            activated_at="now",
        )

        with (
            patch("brain.agent.get_user_name", return_value="雨心"),
            patch("brain.agent.get_core_system_policy", return_value="CORE_POLICY"),
        ):
            messages = agent._build_request_system_messages(snapshot)

        contents = [message["content"] for message in messages]
        self.assertIn("你的名字是“冷静研究员”", contents[0])
        self.assertTrue(any("桌面端主人会话" in item for item in contents))
        self.assertEqual("CORE_POLICY", contents[-1])
        self.assertNotIn("LEGACY_PROMPT", contents)
        self.assertEqual("LEGACY_PROMPT", agent._system_prompt)

    def test_chat_passes_one_snapshot_through_the_whole_request(self):
        class HistoryStub:
            def save_message(self, *_args):
                pass

        agent = self._agent()
        agent._session_titled = True
        agent._history_mgr = HistoryStub()
        agent._session_id = 3
        agent._disable_tools = False
        agent._track_emotion = False
        agent._auto_extract = False
        agent._last_emotion = None
        agent._last_raw_response = None
        snapshot = PersonaSnapshot(
            profile=self._profile("researcher", "冷静研究员"),
            revision=12,
            enabled=True,
            activated_at="now",
        )
        agent._prepare_persona_request = lambda: (snapshot, "TRANSITION")
        captured = {}

        def fake_loop(*_args, **kwargs):
            captured.update(kwargs)
            return "处理完成"

        agent._function_calling_loop = fake_loop
        agent.chat("继续分析")

        self.assertIs(snapshot, captured["persona_snapshot"])
        self.assertEqual("TRANSITION", captured["persona_transition"])


if __name__ == "__main__":
    unittest.main()
