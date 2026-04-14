import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.workflows.progress_engine import recompute_overall_progress, set_phase_progress, update_collecting_progress
from pm_agent_worker.workflows.research_models import build_phase_progress


class ProgressEngineTest(unittest.TestCase):
    def test_collecting_progress_uses_tasks_and_sources(self) -> None:
        job = {
            "phase_progress": build_phase_progress(),
            "tasks": [
                {"status": "completed"},
                {"status": "completed"},
                {"status": "running"},
                {"status": "queued"},
            ],
            "source_count": 20,
            "max_sources": 40,
        }
        update_collecting_progress(job)
        collecting_phase = next(item for item in job["phase_progress"] if item["phase"] == "collecting")
        self.assertGreater(collecting_phase["progress"], 40)
        self.assertLess(collecting_phase["progress"], 100)

    def test_overall_progress_reaches_full_completion(self) -> None:
        job = {"phase_progress": build_phase_progress()}
        for phase in ("scoping", "planning", "collecting", "verifying", "synthesizing", "finalizing"):
            set_phase_progress(job, phase, 100, "completed")
        recompute_overall_progress(job)
        self.assertEqual(job["overall_progress"], 100.0)


if __name__ == "__main__":
    unittest.main()

