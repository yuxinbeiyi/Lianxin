import unittest

from brain.physical.controller import SnakeController
from brain.physical.models import Obstacle, Point, SnakeState
from brain.physical.world import WorldState


class SnakeControllerTests(unittest.TestCase):
    def make_world(self):
        return WorldState(width=200, height=200, snake=SnakeState([
            Point(50, 50), Point(30, 50), Point(10, 50),
        ]))

    def test_moves_three_cell_snake_without_growing(self):
        world = self.make_world()
        controller = SnakeController(step_seconds=0.02)

        moved = controller.move(world, Point(70, 50))

        self.assertTrue(moved)
        self.assertEqual([Point(70, 50), Point(50, 50), Point(30, 50)], world.snake.body)
        self.assertEqual("right", world.snake.direction)

    def test_blocks_obstacle_or_own_body(self):
        world = self.make_world()
        controller = SnakeController()
        world.add_obstacle(Obstacle(x=60, y=40, width=20, height=20))

        self.assertFalse(controller.move(world, Point(70, 50)))
        self.assertFalse(controller.move(world, Point(30, 50)))


if __name__ == "__main__":
    unittest.main()
