import tempfile
import unittest
from pathlib import Path

from brain.physical.audit import PhysicalTaskAuditor
from brain.physical.models import Marker, Point, SnakeState, TaskStatus
from brain.physical.runtime import PhysicalRuntime
from brain.physical.world import WorldState
from brain.workflow import WorkflowStore


class PhysicalTaskAuditorTests(unittest.TestCase):
    def test_terminal_task_is_persisted_with_real_outcome(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = WorkflowStore(Path(temporary_directory) / "workflows.db")
            world = WorldState(width=200, height=200, snake=SnakeState([
                Point(30, 30), Point(10, 30), Point(10, 10),
            ]))
            runtime = PhysicalRuntime(world, cell_size=20)
            auditor = PhysicalTaskAuditor(runtime, store=store)
            world.add_marker(Marker("marker_001", Point(170, 30)))
            task = runtime.submit_navigation("marker_001")
            run_id = auditor.track(task)

            for _ in range(500):
                runtime.tick(0.02)
                if task.status.is_terminal:
                    break

            self.assertEqual(TaskStatus.ARRIVED, task.status)
            self.assertEqual("success", store.get_run(run_id)["status"])
            self.assertEqual("success", store.list_steps(run_id)[0]["status"])


if __name__ == "__main__":
    unittest.main()
