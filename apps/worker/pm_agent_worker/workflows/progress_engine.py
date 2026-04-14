from typing import Any, Dict, List

from pm_agent_worker.tools.config_loader import load_research_defaults


def set_phase_progress(job: Dict[str, Any], phase: str, progress: float, status: str) -> None:
    phases: List[Dict[str, Any]] = job["phase_progress"]
    for item in phases:
        if item["phase"] == phase:
            item["progress"] = round(progress, 1)
            item["status"] = status
        elif status == "running" and item["status"] == "pending" and item["phase"] != phase:
            continue
        elif item["phase"] != phase and progress >= 100 and item["status"] == "pending":
            continue


def recompute_overall_progress(job: Dict[str, Any]) -> None:
    stage_weights = load_research_defaults()["stageWeights"]
    total = 0.0
    for item in job["phase_progress"]:
        weight = stage_weights[item["phase"]]
        total += weight * (item["progress"] / 100)
    job["overall_progress"] = round(total, 1)


def update_collecting_progress(job: Dict[str, Any]) -> None:
    completed_tasks = sum(1 for task in job["tasks"] if task["status"] == "completed")
    total_tasks = max(1, len(job["tasks"]))
    task_ratio = completed_tasks / total_tasks
    source_ratio = min(1.0, job["source_count"] / max(1, job["max_sources"]))
    progress = (task_ratio * 70) + (source_ratio * 30)
    set_phase_progress(job, "collecting", progress, "running" if progress < 100 else "completed")
    recompute_overall_progress(job)

