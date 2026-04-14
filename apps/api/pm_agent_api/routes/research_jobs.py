from fastapi import APIRouter, Depends, HTTPException

from pm_agent_api.main import get_current_user, get_research_job_service
from pm_agent_api.schemas.auth_dto import AuthUserDto
from pm_agent_api.schemas.research_dto import (
    CancelResearchJobDto,
    CreateResearchJobDto,
    FinalizeReportDto,
    ReportVersionDiffDto,
    ResearchAssetsDto,
    ResearchJobDto,
)
from pm_agent_api.schemas.task_dto import OpenTaskSourceDto
from pm_agent_api.services.research_job_service import ResearchJobService

router = APIRouter(prefix="/api/research-jobs", tags=["research-jobs"])


@router.get("", response_model=list[ResearchJobDto])
def list_research_jobs(
    service: ResearchJobService = Depends(get_research_job_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    return service.list_jobs(current_user.id)


@router.post("", response_model=ResearchJobDto)
async def create_research_job(
    payload: CreateResearchJobDto,
    service: ResearchJobService = Depends(get_research_job_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    return await service.create_job(payload.model_dump(), current_user.id)


@router.get("/{job_id}", response_model=ResearchJobDto)
def get_research_job(
    job_id: str,
    service: ResearchJobService = Depends(get_research_job_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.get_job(job_id, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Research job not found") from error


@router.get("/{job_id}/assets", response_model=ResearchAssetsDto)
def get_research_assets(
    job_id: str,
    service: ResearchJobService = Depends(get_research_job_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.get_assets(job_id, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Research assets not found") from error


@router.post("/{job_id}/cancel", response_model=ResearchJobDto)
def cancel_research_job(
    job_id: str,
    payload: CancelResearchJobDto | None = None,
    service: ResearchJobService = Depends(get_research_job_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.cancel_job(job_id, current_user.id, payload.reason if payload else None)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Research job not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{job_id}/finalize-report", response_model=ResearchAssetsDto)
def finalize_research_report(
    job_id: str,
    payload: FinalizeReportDto | None = None,
    service: ResearchJobService = Depends(get_research_job_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.finalize_report(job_id, current_user.id, payload.source_version_id if payload else None)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Research job not found") from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{job_id}/report-versions/{version_id}/diff/{base_version_id}", response_model=ReportVersionDiffDto)
def get_research_report_version_diff(
    job_id: str,
    version_id: str,
    base_version_id: str,
    service: ResearchJobService = Depends(get_research_job_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.get_report_version_diff(job_id, version_id, base_version_id, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Research job not found") from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{job_id}/tasks/{task_id}/open-source")
def open_task_source(
    job_id: str,
    task_id: str,
    payload: OpenTaskSourceDto,
    service: ResearchJobService = Depends(get_research_job_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.open_task_source(job_id, task_id, current_user.id, payload.url)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Task not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
