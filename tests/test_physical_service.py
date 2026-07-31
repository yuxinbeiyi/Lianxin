import unittest

from aiohttp.test_utils import TestClient, TestServer, loop_context

from brain.physical.models import Point, SnakeState
from brain.physical.runtime import PhysicalRuntime
from brain.physical.service import PhysicalSimService
from brain.physical.host import PhysicalRuntimeHost
from brain.physical.world import WorldState


class PhysicalSimServiceTests(unittest.TestCase):
    def setUp(self):
        self.loop_context = loop_context()
        self.loop = self.loop_context.__enter__()
        world = WorldState(width=200, height=200, snake=SnakeState([
            Point(30, 30), Point(10, 30), Point(10, 10),
        ]))
        self.service = PhysicalSimService(PhysicalRuntime(world, cell_size=20))
        self.client = TestClient(TestServer(self.service.create_app()), loop=self.loop)
        self.loop.run_until_complete(self.client.start_server())

    def tearDown(self):
        self.loop.run_until_complete(self.client.close())
        self.loop_context.__exit__(None, None, None)

    def test_index_and_initial_websocket_snapshot(self):
        response = self.loop.run_until_complete(self.client.get("/"))
        self.assertEqual(200, response.status)
        self.assertIn("莲心虚拟世界", self.loop.run_until_complete(response.text()))

        socket = self.loop.run_until_complete(self.client.ws_connect("/ws"))
        payload = self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.close())

        self.assertEqual("world_snapshot", payload["type"])
        self.assertEqual([30, 30], payload["snake"]["body"][0])

    def test_commands_modify_authoritative_runtime_state(self):
        socket = self.loop.run_until_complete(self.client.ws_connect("/ws"))
        self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.send_json({"type": "place_marker", "x": 180, "y": 20}))
        marker_ack = self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.send_json({"type": "start_debug_navigation"}))
        navigation_ack = self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.close())

        self.assertEqual("ack", marker_ack["type"])
        self.assertEqual("marker_001", self.service.runtime.world.active_marker_id)
        self.assertEqual("ack", navigation_ack["type"])
        self.assertEqual("physical-1", navigation_ack["task_id"])

    def test_rejects_invalid_command_payload(self):
        socket = self.loop.run_until_complete(self.client.ws_connect("/ws"))
        self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.send_json({"type": "add_obstacle", "x": "bad", "y": 0, "w": 20, "h": 20}))
        payload = self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.close())

        self.assertEqual("error", payload["type"])
        self.assertIn("x 必须是数字", payload["message"])

    def test_removes_obstacle_at_requested_position(self):
        socket = self.loop.run_until_complete(self.client.ws_connect("/ws"))
        self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.send_json({"type": "add_obstacle", "x": 40, "y": 40, "w": 20, "h": 20}))
        self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.send_json({"type": "remove_obstacle", "x": 45, "y": 45}))
        payload = self.loop.run_until_complete(socket.receive_json())
        self.loop.run_until_complete(socket.close())

        self.assertEqual("障碍物已删除", payload["message"])
        self.assertEqual([], self.service.runtime.world.obstacles)

    def test_navigation_submission_is_idempotent_while_running(self):
        self.service.handle_command({"type": "place_marker", "x": 180, "y": 20})
        first = self.service.handle_command({"type": "start_debug_navigation"})
        second = self.service.handle_command({"type": "start_debug_navigation"})

        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual("导航任务已在执行中", second["message"])

    def test_debug_report_contains_authoritative_snapshot(self):
        response = self.loop.run_until_complete(self.client.get("/debug/report"))
        report = self.loop.run_until_complete(response.json())

        self.assertEqual("world_snapshot", report["type"])
        self.assertIn("service", report)
        self.assertIn("events", report)

    def test_manual_move_advances_snake_one_grid_cell(self):
        response = self.service.handle_command({"type": "manual_move", "direction": "right"})

        self.assertEqual("ack", response["type"])
        self.assertEqual(Point(50, 30), self.service.runtime.world.snake.head)

    def test_host_mode_broadcasts_snapshots_without_new_commands(self):
        host = PhysicalRuntimeHost(self.service.runtime)
        host_service = PhysicalSimService(host=host, snapshot_seconds=0.01)
        host_client = TestClient(TestServer(host_service.create_app()), loop=self.loop)
        self.loop.run_until_complete(host_client.start_server())
        socket = self.loop.run_until_complete(host_client.ws_connect("/ws"))
        self.loop.run_until_complete(socket.receive_json())
        self.service.handle_command({"type": "place_marker", "x": 180, "y": 30})
        self.service.handle_command({"type": "start_debug_navigation"})
        snapshots = []
        for _ in range(3):
            snapshots.append(self.loop.run_until_complete(socket.receive_json()))
        self.assertTrue(any(item.get("type") == "world_snapshot" for item in snapshots))
        self.loop.run_until_complete(socket.close())
        self.loop.run_until_complete(host_client.close())
        host.shutdown()

    def test_cannot_replace_marker_during_navigation(self):
        self.service.handle_command({"type": "place_marker", "x": 180, "y": 20})
        self.service.handle_command({"type": "start_debug_navigation"})

        with self.assertRaisesRegex(ValueError, "导航执行中"):
            self.service.handle_command({"type": "place_marker", "x": 100, "y": 100})


if __name__ == "__main__":
    unittest.main()
