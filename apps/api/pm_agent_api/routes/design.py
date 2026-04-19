from __future__ import annotations

import httpx

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from pm_agent_api.main import (
    get_current_user,
    get_design_material_service,
    get_design_trend_service,
)
from pm_agent_api.schemas.auth_dto import AuthUserDto
from pm_agent_api.schemas.design_dto import (
    DailyTrendRollDto,
    MaterialItemDto,
    MaterialListDto,
    MaterialNetworkDto,
    SaveTrendMaterialDto,
    TrendHistoryRecordDto,
    UpdateTagsDto,
    UploadUrlDto,
)
from pm_agent_api.services.design_material_service import DesignMaterialService
from pm_agent_api.services.design_trend_service import DesignTrendService

router = APIRouter(prefix="/api/design", tags=["design"])


@router.get("/trends/today", response_model=DailyTrendRollDto)
async def get_today_trend(
    service: DesignTrendService = Depends(get_design_trend_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        pool_payload = await service.get_today_trend_pool()
        return service.roll_trend_for_user(current_user.id, pool_payload)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/trends/refresh")
async def refresh_trend_pool(
    service: DesignTrendService = Depends(get_design_trend_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        pool_payload = await service.force_refresh_today()
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {
        "ok": True,
        "message": f"{current_user.display_name or current_user.email} 已完成今日趋势刷新。",
        "trend_count": len(pool_payload.get("pool") or []),
        "available_category_count": int(pool_payload.get("available_category_count") or 0),
        "pool_fetched_at": pool_payload.get("pool_fetched_at"),
    }


@router.get("/trends/history", response_model=list[TrendHistoryRecordDto])
def get_trend_history(
    days: int = Query(default=30, ge=1, le=60),
    service: DesignTrendService = Depends(get_design_trend_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    return service.get_user_history(current_user.id, days=days)


@router.post("/materials/upload", response_model=MaterialItemDto)
async def upload_material(
    file: UploadFile = File(...),
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件不能为空。")
    try:
        return service.upload_material(
            current_user.id,
            filename=file.filename or "uploaded-image",
            mime_type=file.content_type or "application/octet-stream",
            data=content,
            source="upload",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/materials/upload-url", response_model=MaterialItemDto)
def upload_material_from_url(
    payload: UploadUrlDto,
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.upload_material_from_url(current_user.id, payload.url, payload.tags)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except httpx.HTTPError as error:  # type: ignore[name-defined]
        raise HTTPException(status_code=400, detail=f"远程图片下载失败：{error}") from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/materials/from-trend", response_model=MaterialItemDto)
def save_trend_material(
    payload: SaveTrendMaterialDto,
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.save_trend_material(current_user.id, payload.trend.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/materials", response_model=MaterialListDto)
def list_materials(
    tag: str | None = None,
    category: str | None = None,
    color: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=120),
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    return service.list_materials(
        current_user.id,
        tag=tag,
        category=category,
        color=color,
        page=page,
        page_size=page_size,
    )


@router.get("/materials/tags/all", response_model=list[str])
def list_all_tags(
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    return service.list_all_tags(current_user.id)


@router.get("/materials/network", response_model=MaterialNetworkDto)
def get_material_network(
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    return service.get_material_network(current_user.id)


@router.get("/materials/{material_id}", response_model=MaterialItemDto)
def get_material(
    material_id: str,
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.get_material(material_id, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="素材不存在。") from error


@router.delete("/materials/{material_id}")
def delete_material(
    material_id: str,
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.delete_material(material_id, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="素材不存在。") from error


@router.patch("/materials/{material_id}/tags", response_model=MaterialItemDto)
def update_material_tags(
    material_id: str,
    payload: UpdateTagsDto,
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        add_payload = [item.model_dump() for item in payload.add]
        return service.update_material_tags(material_id, current_user.id, add_payload, payload.remove)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="素材不存在。") from error


@router.get("/materials/{material_id}/image")
def get_material_image(
    material_id: str,
    variant: str = Query(default="full"),
    service: DesignMaterialService = Depends(get_design_material_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        resolved = service.resolve_image_variant(material_id, current_user.id, variant)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="素材图片不存在。") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if resolved.get("kind") == "redirect":
        return RedirectResponse(url=str(resolved.get("url") or ""), status_code=307)
    return FileResponse(path=str(resolved.get("path") or ""), media_type=str(resolved.get("media_type") or "application/octet-stream"))
