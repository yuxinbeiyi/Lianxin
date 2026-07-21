import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from brain.emotional.appraisal import AppraisalContext, appraise_deterministic
from brain.emotional.dynamics import EmotionalDynamics
from brain.emotional.manager import EmotionManager
from brain.emotional.tone import render_prompt
from brain.emotional.v3_models import AffectDelta, EmotionalStateV3
from brain.emotional.v3_store import EmotionStore
from utils.proactive_chat import ProactiveChatScheduler


def persona(profile_id: str, name: str = "莲心"):
    return SimpleNamespace(
        enabled=True,
        profile=SimpleNamespace(
            id=profile_id,
            assistant_name=name,
            personality="知性、温柔，偶尔会克制地吐槽",
            relationship="与用户长期相处并互相信任",
            boundaries="不攻击、不羞辱、不用冷暴力",
        ),
    )


class V3ModelAndDynamicsTests(unittest.TestCase):
    def test_state_and_delta_are_bounded(self):
        state = EmotionalStateV3(connection=5, valence=-9, trust=4, rupture=-2)
        state.apply(AffectDelta(connection=8, valence=8, trust=-4, rupture=8))

        self.assertEqual(1.0, state.connection)
        self.assertGreaterEqual(state.valence, -1.0)
        self.assertLessEqual(state.valence, 1.0)
        self.assertGreater(state.trust, 0.8)
        self.assertEqual(0.5, state.rupture)

    def test_long_tick_matches_repeated_short_ticks(self):
        now = time.time()
        initial = EmotionalStateV3(
            connection=0.20,
            valence=-0.25,
            arousal=0.15,
            guardedness=0.30,
            immersion=0.45,
            last_update=now - 6 * 3600,
            last_interaction=now - 6 * 3600,
            last_user_message="我去开会了",
        )
        one_pass = EmotionalStateV3.from_mapping(initial.to_dict())
        repeated = EmotionalStateV3.from_mapping(initial.to_dict())
        dynamics = EmotionalDynamics()

        dynamics.advance(one_pass, now=now)
        cursor = initial.last_update
        while cursor < now:
            cursor = min(now, cursor + 5 * 60)
            dynamics.advance(repeated, now=cursor)

        for axis in ("connection", "valence", "arousal", "guardedness", "immersion"):
            self.assertAlmostEqual(getattr(one_pass, axis), getattr(repeated, axis), places=8)

    def test_known_sleep_context_grows_connection_more_slowly(self):
        now = time.time()
        common = dict(last_update=now - 4 * 3600, last_interaction=now - 4 * 3600)
        sleeping = EmotionalStateV3(last_user_message="晚安，我去睡了", **common)
        vanished = EmotionalStateV3(last_user_message="一会儿聊", **common)
        dynamics = EmotionalDynamics()

        dynamics.advance(sleeping, now=now)
        dynamics.advance(vanished, now=now)

        self.assertLess(sleeping.connection, vanished.connection)


class V3AppraisalAndToneTests(unittest.TestCase):
    def test_technical_discussion_is_not_relationship_damage(self):
        result = appraise_deterministic("这个情感系统架构需要重构，帮我检查代码")

        self.assertEqual("task_discussion", result.event_type)
        self.assertEqual(0.0, result.rupture)
        self.assertEqual(0.0, result.trust)

    def test_explicit_hostility_creates_bounded_rupture(self):
        result = appraise_deterministic("你就是个没用的垃圾工具，闭嘴")

        self.assertEqual("boundary_violation", result.event_type)
        self.assertGreater(result.rupture, 0.2)
        self.assertGreaterEqual(result.significance, 0.82)
        self.assertLess(result.valence, 0)

    def test_apology_moves_repair_without_instantly_erasing_rupture(self):
        state = EmotionalStateV3(rupture=0.55, repair=0.0)
        result = appraise_deterministic("对不起，刚才是我不对")

        state.apply(result)

        self.assertGreater(state.repair, 0.1)
        self.assertGreater(state.rupture, 0.2)
        self.assertLess(state.rupture, 0.55)

    def test_tone_guidance_never_authorizes_harm_or_task_refusal(self):
        state = EmotionalStateV3(
            connection=0.86, guardedness=0.85, valence=-0.7,
            arousal=0.75, rupture=0.65,
        )
        prompt = render_prompt(state, user_name="主人", mode="reactive")

        self.assertIn("不要讽刺、迁怒或攻击", prompt)
        self.assertIn("不得削弱事实准确性、任务完成", prompt)
        self.assertNotIn("不想帮忙", prompt)
        self.assertNotIn("尖锐回击都可以", prompt)


class V3StoreTests(unittest.TestCase):
    def test_persona_scopes_are_isolated_and_events_are_idempotent(self):
        store = EmotionStore(":memory:")
        a = EmotionalStateV3(persona_id="a", valence=0.4)
        b = EmotionalStateV3(persona_id="b", valence=-0.4)
        store.save_state(a)
        store.save_state(b)

        first = store.append_event(a, AffectDelta(valence=0.1), idempotency_key="msg:1")
        duplicate = store.append_event(a, AffectDelta(valence=0.1), idempotency_key="msg:1")

        self.assertEqual(0.4, store.load_state("a", "owner").valence)
        self.assertEqual(-0.4, store.load_state("b", "owner").valence)
        self.assertIsInstance(first, int)
        self.assertIsNone(duplicate)

    def test_concurrent_event_writes_remain_valid(self):
        store = EmotionStore(":memory:")
        state = EmotionalStateV3()
        results = []

        def write(index):
            results.append(store.append_event(
                state, AffectDelta(event_type="test"), idempotency_key=f"event:{index}"
            ))

        threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(12, len([value for value in results if value is not None]))
        self.assertEqual(12, len(store.recent_events("default-lianxin", "owner", limit=20)))

    def test_v2_snapshot_migrates_once(self):
        with TemporaryDirectory() as temp_dir:
            legacy = Path(temp_dir) / "emotional_state.json"
            legacy.write_text(json.dumps({
                "needs": {"needed": 40, "security": 55, "autonomy": 70},
                "deep_layer": 78,
                "emotions": {"hurt": 30, "loneliness": 50, "excitement": 5},
                "enabled": True,
                "last_update": time.time(),
                "last_interaction": time.time(),
            }), encoding="utf-8")
            store = EmotionStore(":memory:")

            self.assertTrue(store.migrate_v2_json(legacy))
            self.assertFalse(store.migrate_v2_json(legacy))
            state = store.load_state("default-lianxin", "owner")

        self.assertAlmostEqual(0.78, state.trust, places=2)
        self.assertGreater(state.connection, 0.35)
        self.assertLess(state.valence, 0)

    def test_duplicate_event_cannot_replace_committed_state(self):
        store = EmotionStore(":memory:")
        first = EmotionalStateV3(valence=0.25)
        second = EmotionalStateV3(valence=-0.85)

        self.assertTrue(store.save_state_with_event(
            first, AffectDelta(valence=0.1), idempotency_key="turn:7"
        ))
        self.assertFalse(store.save_state_with_event(
            second, AffectDelta(valence=-0.3), idempotency_key="turn:7"
        ))

        self.assertAlmostEqual(0.25, store.load_state("default-lianxin", "owner").valence)


class V3ManagerTests(unittest.TestCase):
    def make_manager(self):
        return EmotionManager(
            store=EmotionStore(":memory:"),
            semantic_mode="off",
            legacy_state_path=Path("__missing_emotional_state__.json"),
        )

    def test_current_message_changes_current_prompt_and_is_idempotent(self):
        manager = self.make_manager()
        snap = persona("persona-a")

        result = manager.prepare_turn(
            "你就是个没用的垃圾工具，闭嘴",
            persona_snapshot=snap,
            source_channel="desktop",
            source_session_id=3,
            source_message_id=9,
        )
        before_duplicate = manager.get_debug_info(persona_snapshot=snap)["axes"].copy()
        duplicate = manager.prepare_turn(
            "你就是个没用的垃圾工具，闭嘴",
            persona_snapshot=snap,
            source_channel="desktop",
            source_session_id=3,
            source_message_id=9,
        )
        prompt = manager.build_prompt_snippet(persona_snapshot=snap)

        self.assertEqual("boundary_violation", result.event_type)
        self.assertEqual("duplicate", duplicate.event_type)
        self.assertEqual(before_duplicate, manager.get_debug_info(persona_snapshot=snap)["axes"])
        self.assertIn("明确贬低或敌意表达", prompt)

    def test_persona_tone_profile_can_override_cluster_guidance(self):
        manager = self.make_manager()
        manager._config["tone_profiles"] = {
            "persona-a": {"clusters": {"neutral": {"2": "使用莲心专属的克制语调。"}}}
        }
        prompt = manager.build_prompt_snippet(persona_snapshot=persona("persona-a"))

        self.assertIn("莲心专属的克制语调", prompt)

    def test_persona_switch_does_not_leak_state(self):
        manager = self.make_manager()
        first = persona("persona-a")
        second = persona("persona-b", "另一人格")
        manager.prepare_turn("你就是个没用的垃圾", persona_snapshot=first, source_message_id=1)

        a = manager.get_debug_info(persona_snapshot=first)
        b = manager.get_debug_info(persona_snapshot=second)

        self.assertLess(a["axes"]["valence"], b["axes"]["valence"])
        self.assertGreater(a["relationship"]["rupture"], b["relationship"]["rupture"])

    def test_emotion_never_blocks_tools(self):
        manager = self.make_manager()
        manager.set_relationship(rupture=1.0)

        self.assertEqual((True, ""), manager.check_tool_allowed("capture_from_camera"))
        self.assertEqual((True, ""), manager.check_tool_allowed("delete_file"))

    def test_successful_proactive_action_partially_relaxes_connection(self):
        manager = self.make_manager()
        manager.set_axes(connection=0.90)
        motive = manager.get_proactive_motive()
        manager.record_proactive_action("normal")

        self.assertTrue(motive["should_contact"])
        self.assertLess(manager.get_debug_info()["axes"]["connection"], 0.90)
        self.assertGreater(manager.get_debug_info()["axes"]["connection"], 0.0)

    def test_ui_simulation_is_bounded_and_auditable(self):
        manager = self.make_manager()
        result = manager.simulate_scenario("cold_reply")
        info = manager.get_debug_info()
        self.assertTrue(result["ok"])
        self.assertGreater(info["event_count"], 0)
        self.assertEqual("simulation_cold_reply", info["recent_events"][0]["type"])
        self.assertLessEqual(info["axes"]["guardedness"], 1.0)

    def test_significant_memory_uses_existing_events_category_and_provenance(self):
        manager = self.make_manager()
        add_fact = Mock(return_value=17)
        add_fragment = Mock(return_value=23)
        with patch("brain.graph_memory.add_fact", add_fact), patch(
            "brain.graph_memory.add_memory_fragment", add_fragment
        ):
            manager.prepare_turn(
                "你就是个没用的垃圾工具，闭嘴",
                source_channel="desktop",
                source_session_id=4,
                source_message_id=19,
                allow_memory=True,
            )

        self.assertEqual("events", add_fact.call_args.kwargs["category"])
        self.assertEqual("emotion_v3", add_fact.call_args.kwargs["source"])
        self.assertEqual("events", add_fragment.call_args.args[2])
        self.assertEqual([19], add_fragment.call_args.kwargs["source_message_ids"])

    def test_persisted_disabled_state_is_not_overridden_without_events(self):
        store = EmotionStore(":memory:")
        store.save_state(EmotionalStateV3(enabled=False))
        manager = EmotionManager(
            store=store,
            semantic_mode="off",
            legacy_state_path=Path("__missing_emotional_state__.json"),
        )

        self.assertFalse(manager.enabled)


class V3ProactivePolicyTests(unittest.TestCase):
    @staticmethod
    def scheduler():
        scheduler = ProactiveChatScheduler.__new__(ProactiveChatScheduler)
        scheduler._settings = scheduler._default_settings()
        scheduler._last_fire_time = None
        scheduler._defer_until = None
        scheduler._empty_session_started_at = None
        scheduler._empty_session_waiting = False
        scheduler.desktop_enabled = True
        scheduler.normal_enabled = True
        scheduler.weights = [10] * 24
        return scheduler

    def test_emotional_motive_respects_user_defer_and_cooldown(self):
        scheduler = self.scheduler()
        self.assertTrue(scheduler.can_deliver_emotional_motive())

        scheduler._defer_until = datetime.now() + timedelta(minutes=5)
        self.assertFalse(scheduler.can_deliver_emotional_motive())

        scheduler._defer_until = None
        scheduler._last_fire_time = datetime.now() - timedelta(minutes=2)
        self.assertFalse(scheduler.can_deliver_emotional_motive())

    def test_emotional_motive_respects_quiet_hours(self):
        scheduler = self.scheduler()
        scheduler.weights[datetime.now().hour] = 0

        self.assertFalse(scheduler.can_deliver_emotional_motive())


if __name__ == "__main__":
    unittest.main()
