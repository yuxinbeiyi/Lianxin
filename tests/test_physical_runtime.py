import unittest

from brain.physical.models import Marker, Obstacle, Point, SnakeState, TaskStatus
from brain.physical.runtime import PhysicalRuntime
from brain.physical.world import WorldState


class PhysicalRuntimeTests(unittest.TestCase):
    def make_runtime(self):
        world = WorldState(width=200, height=200, snake=SnakeState([
            Point(30, 30), Point(10, 30), Point(10, 10),
        ]))
        return PhysicalRuntime(world, cell_size=20)

    def tick_until_terminal(self, runtime, task, maximum_ticks=500):
        for _ in range(maximum_ticks):
            runtime.tick(0.02)
            if task.status.is_terminal:
                return
        self.fail(f"任务未在 {maximum_ticks} 个控制周期内结束：{task.status}")

    def test_navigation_eats_food_without_growing(self):
        runtime = self.make_runtime()
        original_length = len(runtime.world.snake.body)
        runtime.world.add_marker(Marker("marker_001", Point(170, 30)))
        task = runtime.submit_navigation("marker_001")

        self.tick_until_terminal(runtime, task)

        self.assertEqual(TaskStatus.ARRIVED, task.status)
        self.assertEqual(Point(170, 30), runtime.world.snake.head)
        self.assertEqual(original_length, len(runtime.world.snake.body))

    def test_missing_food_is_invalid_goal(self):
        runtime = self.make_runtime()
        task = runtime.submit_navigation("missing")
        self.tick_until_terminal(runtime, task)
        self.assertEqual(TaskStatus.INVALID_GOAL, task.status)

    def test_sealed_wall_has_no_path(self):
        runtime = self.make_runtime()
        runtime.world.add_marker(Marker("marker_001", Point(170, 30)))
        runtime.world.add_obstacle(Obstacle(x=80, y=0, width=20, height=200))
        task = runtime.submit_navigation("marker_001")
        self.tick_until_terminal(runtime, task)
        self.assertEqual(TaskStatus.NO_PATH, task.status)

    def test_manual_move_is_available_while_idle(self):
        runtime = self.make_runtime()
        self.assertTrue(runtime.manual_move("right"))
        self.assertEqual(Point(50, 30), runtime.world.snake.head)


if __name__ == "__main__":
    unittest.main()
