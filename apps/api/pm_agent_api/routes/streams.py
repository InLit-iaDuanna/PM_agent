from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from pm_agent_api.main import get_current_user, get_research_job_service
from pm_agent_api.schemas.auth_dto import AuthUserDto
from pm_agent_api.services.research_job_service import ResearchJobService

router = APIRouter(prefix="/api/stream", tags=["streams"])


@router.get("/jobs/{job_id}")
async def stream_job(
    job_id: str,
    service: ResearchJobService = Depends(get_research_job_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        service.get_job(job_id, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Research job not found") from error
    return StreamingResponse(service.stream(job_id, current_user.id), media_type="text/event-stream")
