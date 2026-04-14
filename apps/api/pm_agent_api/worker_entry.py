import argparse
import logging
import sys

from pm_agent_api.repositories import create_state_repository
from pm_agent_api.runtime.repo_bootstrap import ensure_repo_paths
from pm_agent_api.services.research_job_service import ResearchJobService

ensure_repo_paths()


LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a PM research job in a detached worker process.")
    parser.add_argument("--job-id", required=True, help="Research job ID to execute")
    args = parser.parse_args(argv)

    repository = create_state_repository()
    service = ResearchJobService(repository, background_mode="inline")

    try:
        service.run_job_foreground(args.job_id)
    except KeyError:
        LOGGER.error("Research job %s not found for detached worker execution.", args.job_id)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
