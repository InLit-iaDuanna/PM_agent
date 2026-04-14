from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from pm_agent_api.repositories import create_state_repository
from pm_agent_api.runtime.repo_bootstrap import ensure_repo_paths
from pm_agent_api.services.research_job_service import ResearchJobService
from pm_agent_worker.workflows.research_models import iso_now

ensure_repo_paths()


LOGGER = logging.getLogger(__name__)


def _mark_worker_started(repository, job_id: str) -> None:
    job = repository.get_job(job_id)
    if not job:
        return
    background_process = job.get("background_process") or {}
    if not isinstance(background_process, dict):
        background_process = {}
    background_process.update(
        {
            "mode": "worker",
            "queue": "redis",
            "active": True,
            "worker_pid": os.getpid(),
            "started_at": background_process.get("started_at") or iso_now(),
        }
    )
    job["execution_mode"] = "worker"
    job["background_process"] = background_process
    repository.update_job(job_id, job)
    repository.publish_job_event(
        job_id,
        "job.progress",
        {
            "job": repository.get_job(job_id),
            "assets": repository.get_assets(job_id),
            "message": "后台 worker 已领取任务，开始执行研究流程。",
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the shared PM research worker daemon.")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Redis blocking pop timeout in seconds")
    args = parser.parse_args(argv)

    repository = create_state_repository()
    if not repository.supports_background_worker():
        LOGGER.error("The configured repository does not support shared background workers.")
        return 2

    service = ResearchJobService(repository, background_mode="inline")
    LOGGER.info("PM research worker daemon is running.")
    while True:
        job_id = repository.dequeue_background_job(timeout_seconds=max(1.0, float(args.poll_seconds)))
        if not job_id:
            continue
        job = repository.get_job(job_id)
        if not job:
            LOGGER.warning("Worker skipped missing job %s.", job_id)
            continue
        if str(job.get("status") or "").strip() not in repository.ACTIVE_JOB_STATUSES:
            continue
        try:
            _mark_worker_started(repository, job_id)
            service.run_job_foreground(job_id)
        except KeyboardInterrupt:
            raise
        except Exception:
            LOGGER.exception("Shared worker failed while running job %s.", job_id)
            time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
