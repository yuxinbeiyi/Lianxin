import unittest

from brain.physical.models import Obstacle, Point, SnakeState
from brain.physical.planner import AStarPlanner
from brain.physical.world import WorldState


class AStarPlannerTests(unittest.TestCase):
    def setUp(self):
        self.world = WorldState(width=200, height=200, snake=SnakeState([
            Point(30, 30), Point(10, 30), Point(10, 10),
        ]))
        self.planner = AStarPlanner(self.world, cell_size=20)

    def test_finds_a_straight_path(self):
        path = self.planner.plan(Point(30, 30), Point(170, 30))
        self.assertEqual(Point(30, 30), path[0])
        self.assertEqual(Point(170, 30), path[-1])

    def test_routes_around_an_obstacle(self):
        self.world.add_obstacle(Obstacle(x=80, y=0, width=20, height=100))
        path = self.planner.plan(Point(30, 30), Point(170, 30))
        self.assertGreater(len(path), 2)

    def test_returns_none_when_goal_is_blocked(self):
        self.world.add_obstacle(Obstacle(x=160, y=0, width=40, height=200))
        self.assertIsNone(self.planner.plan(Point(30, 30), Point(170, 30)))


if __name__ == "__main__":
    unittest.main()
