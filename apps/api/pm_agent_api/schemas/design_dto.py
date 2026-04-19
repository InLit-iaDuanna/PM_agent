from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class DesignSchemaModel(BaseModel):
    class Config:
        extra = "allow"


TrendCategory = Literal["视觉风格", "排版趋势", "色彩体系", "交互模式", "材质纹理", "构图手法"]
TagCategory = Literal["color", "style", "mood", "composition", "element", "custom"]


class DesignTrendDto(DesignSchemaModel):
    id: str
    name: str
    name_en: str = ""
    category: TrendCategory
    description: str
    keywords: List[str] = Field(default_factory=list)
    color_palette: List[str] = Field(default_factory=list)
    mood_keywords: List[str] = Field(default_factory=list)
    source_urls: List[str] = Field(default_factory=list)
    difficulty: int = 2
    example_prompt: str = ""
    fetched_at: Optional[str] = None
    summary_mode: Optional[Literal["llm", "heuristic"]] = None
    source_count: Optional[int] = None
    source_labels: List[str] = Field(default_factory=list)
    published_at: Optional[str] = None


class DailyTrendRollDto(DesignSchemaModel):
    date: str
    trend: DesignTrendDto
    dice_face: int
    dice_category: TrendCategory
    pool: List[DesignTrendDto] = Field(default_factory=list)
    pool_fetched_at: Optional[str] = None


class TrendHistoryRecordDto(DesignSchemaModel):
    date: str
    trend: DesignTrendDto
    dice_face: int
    dice_category: TrendCategory


class MaterialTagDto(DesignSchemaModel):
    name: str
    type: Literal["auto", "manual"] = "manual"
    confidence: Optional[float] = None
    category: TagCategory = "custom"


class MaterialItemDto(DesignSchemaModel):
    id: str
    user_id: str
    filename: str
    original_url: Optional[str] = None
    thumbnail_url: str
    full_url: str
    width: int
    height: int
    file_size: int
    mime_type: str
    tags: List[MaterialTagDto] = Field(default_factory=list)
    colors: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    source: Literal["upload", "url", "trend"] = "upload"
    trend_id: Optional[str] = None


class UploadUrlDto(DesignSchemaModel):
    url: str
    tags: List[str] = Field(default_factory=list)


class SaveTrendMaterialDto(DesignSchemaModel):
    trend: DesignTrendDto


class UpdateTagsDto(DesignSchemaModel):
    add: List[MaterialTagDto] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)


class MaterialListDto(DesignSchemaModel):
    items: List[MaterialItemDto] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 30


class MaterialNetworkNodeDto(DesignSchemaModel):
    id: str
    label: str
    thumbnail: str
    tags: List[str] = Field(default_factory=list)
    colors: List[str] = Field(default_factory=list)
    group: int = 0
    source: Literal["upload", "url", "trend"] = "upload"


class MaterialNetworkLinkDto(DesignSchemaModel):
    source: str
    target: str
    weight: float
    shared_tags: List[str] = Field(default_factory=list)
    shared_category: Optional[str] = None


class MaterialNetworkDto(DesignSchemaModel):
    nodes: List[MaterialNetworkNodeDto] = Field(default_factory=list)
    links: List[MaterialNetworkLinkDto] = Field(default_factory=list)
