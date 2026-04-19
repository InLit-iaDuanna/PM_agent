from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from pm_agent_api.repositories.base import StateRepositoryProtocol
from pm_agent_api.runtime.repo_bootstrap import ensure_repo_paths

ensure_repo_paths()

import httpx
from pm_agent_worker.tools.content_extractor import fetch_and_extract_page
from pm_agent_worker.tools.llm_runtime import create_llm_client, load_llm_settings, runtime_api_key_configured
from pm_agent_worker.tools.search_provider import DuckDuckGoSearchProvider, SearchProviderUnavailable


LOGGER = logging.getLogger(__name__)

TREND_CATEGORY_ORDER = ["视觉风格", "排版趋势", "色彩体系", "交互模式", "材质纹理", "构图手法"]

DEFAULT_PALETTES: Dict[str, List[str]] = {
    "视觉风格": ["#1E293B", "#475569", "#E2E8F0", "#CBD5E1", "#F8FAFC"],
    "排版趋势": ["#0F172A", "#334155", "#64748B", "#CBD5E1", "#F1F5F9"],
    "色彩体系": ["#1D4ED8", "#0EA5E9", "#F59E0B", "#F97316", "#111827"],
    "交互模式": ["#0F766E", "#14B8A6", "#E2E8F0", "#0F172A", "#ECFEFF"],
    "材质纹理": ["#7C3AED", "#A78BFA", "#DDD6FE", "#6D28D9", "#F5F3FF"],
    "构图手法": ["#111827", "#374151", "#9CA3AF", "#E5E7EB", "#F9FAFB"],
}

DESIGN_PREFERRED_DOMAINS = [
    "adobe.com",
    "awwwards.com",
    "behance.net",
    "creativebloq.com",
    "designmodo.com",
    "designrush.com",
    "dribbble.com",
    "elementor.com",
    "medium.com",
    "uxdesign.cc",
    "webdesignerdepot.com",
    "webflow.com",
    "99designs.com",
]

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
GOOGLE_NEWS_MAX_RESULTS = 10

GOOGLE_NEWS_QUERIES_PER_CATEGORY: Dict[str, List[str]] = {
    "视觉风格": [
        "graphic design trends {year}",
        "logo design trends {year}",
        "web design trends {year}",
    ],
    "排版趋势": [
        "typography trends {year}",
        "type report {year}",
        "fonts designers love {year}",
    ],
    "色彩体系": [
        "color trends {year} graphic design",
        "design color trends {year}",
        "color palette trends {year} design",
    ],
    "交互模式": [
        "ui design trends {year}",
        "interaction design trends {year}",
        "ux design trends {year}",
    ],
    "材质纹理": [
        "material texture design trends {year}",
        "design materials trends {year}",
        "texture trends {year} design",
    ],
    "构图手法": [
        "editorial design trends {year}",
        "layout design trends {year}",
        "graphic design trends {year} editorial",
    ],
}

CATEGORY_SIGNAL_HINTS: Dict[str, List[str]] = {
    "视觉风格": ["graphic", "visual", "logo", "brand", "branding", "identity", "illustration", "imperfect", "human-centred"],
    "排版趋势": ["typography", "type", "typeface", "typefaces", "font", "fonts", "lettering", "editorial"],
    "色彩体系": ["color", "colour", "palette", "neutrals", "orange", "green", "plum", "plums", "illustration"],
    "交互模式": ["ui", "ux", "interaction", "user experience", "microinteraction", "email design", "web design", "product design"],
    "材质纹理": ["material", "materials", "texture", "textures", "textile", "textiles", "fabric", "grain", "glass", "metal"],
    "构图手法": ["layout", "composition", "editorial", "grid", "collage", "poster", "framing", "art direction"],
}

CATEGORY_NEGATIVE_HINTS: Dict[str, List[str]] = {
    "视觉风格": ["kitchen", "bathroom", "garden", "porch", "insurance", "casino", "student", "teacher"],
    "排版趋势": ["kitchen", "bathroom", "garden", "insurance", "casino", "student", "teacher"],
    "色彩体系": ["insurance", "casino", "student", "teacher", "diagnosis", "treatment"],
    "交互模式": ["kitchen", "bathroom", "garden", "insurance", "casino", "movie", "gambling"],
    "材质纹理": ["insurance", "casino", "student", "teacher", "movie"],
    "构图手法": ["insurance", "casino", "student", "teacher", "kitchen", "bathroom", "garden"],
}

DESIGN_SOURCE_HINTS = (
    "design",
    "creative",
    "bloq",
    "boom",
    "print",
    "adobe",
    "awwwards",
    "behance",
    "dribbble",
    "webflow",
    "designmodo",
    "designrush",
    "canva",
    "shopify",
    "hostinger",
    "reply",
    "deloitte",
    "ux",
    "it's nice that",
)

INTERIOR_SOURCE_HINTS = (
    "elle decor",
    "homes and gardens",
    "house beautiful",
    "veranda",
    "the spruce",
    "vogue",
    "architectural digest",
    "designcafe",
    "builder",
    "nahb",
)

HEURISTIC_TITLE_TRANSLATIONS: Dict[str, List[tuple[str, str]]] = {
    "视觉风格": [
        (r"\blogo design\b", "Logo 视觉"),
        (r"\bgraphic.*bookmark\b", "值得收藏的平面视觉"),
        (r"\bhuman cent(?:red|ered) design\b", "人本导向视觉"),
        (r"\bgraphic design\b", "平面视觉"),
        (r"\bvisual design\b", "视觉设计"),
    ],
    "排版趋势": [
        (r"\bnew typefaces\b", "新锐字体"),
        (r"\bfree fonts you should try\b", "值得尝试的免费字体"),
        (r"\bfonts?.*popular with designers\b", "设计师热门字体"),
        (r"\btypography\b", "字体编排"),
        (r"\btypefaces?\b", "字体风格"),
        (r"\bfonts?\b", "字体趋势"),
    ],
    "色彩体系": [
        (r"\bmoody plums?.*electric greens?.*orange\b", "情绪紫与电光绿"),
        (r"\bwelcoming neutrals?\b", "温和中性色"),
        (r"\billustration\b", "插画色彩"),
        (r"\bcolors?\b", "色彩组合"),
    ],
    "交互模式": [
        (r"\bui/?ux design services\b", "UI/UX 服务体验"),
        (r"\bui/?ux design\b", "UI/UX 体验"),
        (r"\binteraction design\b", "交互设计"),
        (r"\bweb design\b", "网页交互"),
        (r"\bemail design\b", "邮件体验设计"),
    ],
    "材质纹理": [
        (r"\bhigh[- ]low material mix\b", "高低材质混搭"),
        (r"\bmaterial mix\b", "材质混搭"),
        (r"\bflooring\b", "地面材质"),
        (r"\bmaterial\b", "材质表达"),
    ],
    "构图手法": [
        (r"\bemail design\b", "邮件版式"),
        (r"\bgraphic design\b", "平面构图"),
        (r"\blayout\b", "版式布局"),
        (r"\bcomposition\b", "构图节奏"),
        (r"\bbookmark\b", "收藏式构图"),
    ],
}

ENGLISH_TOKEN_TRANSLATIONS = {
    "logo": "Logo",
    "graphic": "平面",
    "visual": "视觉",
    "brand": "品牌",
    "branding": "品牌",
    "human": "人本",
    "centred": "中心",
    "centered": "中心",
    "typeface": "字体",
    "typefaces": "字体",
    "font": "字体",
    "fonts": "字体",
    "free": "免费",
    "new": "新",
    "popular": "热门",
    "designers": "设计师",
    "typography": "排版",
    "color": "色彩",
    "colors": "色彩",
    "colour": "色彩",
    "colours": "色彩",
    "palette": "配色",
    "moody": "情绪感",
    "plum": "梅紫",
    "plums": "梅紫",
    "electric": "电光",
    "green": "绿色",
    "greens": "绿色",
    "orange": "橙色",
    "ui": "UI",
    "ux": "UX",
    "services": "服务",
    "web": "网页",
    "email": "邮件",
    "interaction": "交互",
    "material": "材质",
    "mix": "混搭",
    "high": "高",
    "low": "低",
    "illustration": "插画",
    "neutrals": "中性色",
    "neutral": "中性色",
    "bookmark": "收藏",
    "stills": "静帧",
    "rise": "上升",
    "design": "设计",
}

FALLBACK_TRENDS: Dict[str, List[Dict[str, Any]]] = {
    "视觉风格": [
        {
            "name": "静奢留白",
            "name_en": "Quiet Luxury Minimal",
            "description": "以留白、低饱和和细腻层级建立高级感，强调克制而稳定的品牌气质。",
            "keywords": ["留白", "克制", "高级感"],
            "color_palette": ["#F8FAFC", "#E2E8F0", "#CBD5E1", "#475569", "#0F172A"],
            "mood_keywords": ["冷静", "稳重", "精致"],
            "difficulty": 1,
            "example_prompt": "设计一个极简但不冷淡的首页 Hero，突出品牌信任感与高级质感。",
        },
        {
            "name": "柔和未来感",
            "name_en": "Soft Futurism",
            "description": "通过轻雾化渐变、柔性高光和圆角容器，让未来感更易于被大众接受。",
            "keywords": ["渐变", "柔性高光", "圆角"],
            "color_palette": ["#E0F2FE", "#BFDBFE", "#C4B5FD", "#6366F1", "#1E1B4B"],
            "mood_keywords": ["轻盈", "未来", "友好"],
            "difficulty": 2,
            "example_prompt": "为 AI 助手产品设计一组带柔和未来感的卡片模块与按钮样式。",
        },
        {
            "name": "自然数码融合",
            "name_en": "Organic Digital Blend",
            "description": "将自然纹理、纸感背景与数字界面的规则布局结合，制造温和的技术感。",
            "keywords": ["纸感", "自然纹理", "数字秩序"],
            "color_palette": ["#F6F4EE", "#D6D3D1", "#A8A29E", "#4B5563", "#1F2937"],
            "mood_keywords": ["平和", "可信", "温润"],
            "difficulty": 2,
            "example_prompt": "把自然纸感与数据面板结合，做一个不显冰冷的分析页头图。",
        },
        {
            "name": "高反差焦点式",
            "name_en": "High Contrast Spotlight",
            "description": "借助高反差色块与大面积暗色背景，把用户注意力聚焦到一个关键信息点。",
            "keywords": ["聚焦", "高反差", "暗背景"],
            "color_palette": ["#020617", "#0F172A", "#F8FAFC", "#F59E0B", "#FB7185"],
            "mood_keywords": ["锋利", "张力", "强记忆"],
            "difficulty": 2,
            "example_prompt": "为新品发布落地页设计一张高对比的首屏视觉，突出唯一核心卖点。",
        },
    ],
    "排版趋势": [
        {
            "name": "超大字号引导",
            "name_en": "Oversized Type Direction",
            "description": "用超大字号承担导航、节奏和情绪表达，让排版本身成为视觉主角。",
            "keywords": ["超大字号", "节奏", "主标题"],
            "color_palette": ["#FFFFFF", "#E2E8F0", "#94A3B8", "#334155", "#0F172A"],
            "mood_keywords": ["直接", "现代", "有力"],
            "difficulty": 1,
            "example_prompt": "设计一个以超大中文标题为核心的产品介绍页首屏。",
        },
        {
            "name": "错位网格排版",
            "name_en": "Offset Grid Typography",
            "description": "在严格网格中引入轻微错位，既保留秩序，又增加页面的呼吸感与编辑感。",
            "keywords": ["错位", "网格", "编辑感"],
            "color_palette": ["#F8FAFC", "#E5E7EB", "#9CA3AF", "#4B5563", "#111827"],
            "mood_keywords": ["理性", "编辑感", "克制"],
            "difficulty": 2,
            "example_prompt": "做一版带编辑杂志气质的产品功能页排版方案。",
        },
        {
            "name": "双语层级排版",
            "name_en": "Bilingual Hierarchy",
            "description": "把中英文字体、字号和权重拉开层级，使双语信息同时清楚又有设计感。",
            "keywords": ["双语", "层级", "信息对照"],
            "color_palette": ["#F9FAFB", "#D1D5DB", "#6B7280", "#1F2937", "#111827"],
            "mood_keywords": ["国际化", "清晰", "专业"],
            "difficulty": 2,
            "example_prompt": "为品牌页面设计一套中英双语标题与说明文字的层级规则。",
        },
        {
            "name": "窄栏长文阅读",
            "name_en": "Narrow Column Reading",
            "description": "通过窄栏、稳定行高和清晰标题间距，提高长文阅读的节奏与耐读性。",
            "keywords": ["窄栏", "长文", "耐读"],
            "color_palette": ["#FFFFFF", "#F1F5F9", "#CBD5E1", "#475569", "#0F172A"],
            "mood_keywords": ["沉浸", "耐读", "稳健"],
            "difficulty": 1,
            "example_prompt": "为研究报告页面建立一套适合长篇阅读的正文排版。",
        },
    ],
    "色彩体系": [
        {
            "name": "低饱和主色体系",
            "name_en": "Muted Core Palette",
            "description": "用低饱和主色搭配高亮点缀色，在专业感和识别度之间取得平衡。",
            "keywords": ["低饱和", "点缀色", "平衡"],
            "color_palette": ["#E2E8F0", "#94A3B8", "#475569", "#2563EB", "#F59E0B"],
            "mood_keywords": ["专业", "克制", "可信"],
            "difficulty": 1,
            "example_prompt": "为 B 端产品设计一套低饱和但不无聊的品牌色系统。",
        },
        {
            "name": "高亮功能色分层",
            "name_en": "Functional Accent Layering",
            "description": "把强调色拆分成操作、提醒、成功等多个层级，减少单一主色的过载问题。",
            "keywords": ["功能色", "状态色", "层级"],
            "color_palette": ["#0F172A", "#2563EB", "#16A34A", "#F59E0B", "#DC2626"],
            "mood_keywords": ["清晰", "高效", "可操作"],
            "difficulty": 2,
            "example_prompt": "为数据后台制定一组有层次的功能状态色与使用规则。",
        },
        {
            "name": "暖冷对照配色",
            "name_en": "Warm Cool Contrast",
            "description": "用暖色强调关键动作，用冷色承载主体内容，形成稳定又鲜明的视觉分工。",
            "keywords": ["暖冷对照", "分工", "重点突出"],
            "color_palette": ["#0F172A", "#1D4ED8", "#E2E8F0", "#F59E0B", "#FB7185"],
            "mood_keywords": ["鲜明", "清楚", "有层次"],
            "difficulty": 2,
            "example_prompt": "设计一个使用冷暖分区的转化页配色方案。",
        },
        {
            "name": "单色深浅变体",
            "name_en": "Monotone Depth Range",
            "description": "围绕单一主色扩展多级明暗，靠层级和透明度建立页面的细节变化。",
            "keywords": ["单色", "深浅层级", "透明度"],
            "color_palette": ["#EFF6FF", "#BFDBFE", "#60A5FA", "#2563EB", "#1E3A8A"],
            "mood_keywords": ["统一", "干净", "系统化"],
            "difficulty": 1,
            "example_prompt": "为一个 SaaS 仪表盘设计一套蓝色单色系界面。",
        },
    ],
    "交互模式": [
        {
            "name": "渐进显露交互",
            "name_en": "Progressive Reveal",
            "description": "把复杂信息拆成逐步显露的层级，让首次使用的认知负担更低。",
            "keywords": ["渐进显露", "分步", "降低负担"],
            "color_palette": ["#FFFFFF", "#E2E8F0", "#CBD5E1", "#0EA5E9", "#0F172A"],
            "mood_keywords": ["友好", "清晰", "温和"],
            "difficulty": 2,
            "example_prompt": "为复杂设置页设计渐进显露的交互流程和卡片层级。",
        },
        {
            "name": "实时反馈微状态",
            "name_en": "Live Feedback States",
            "description": "在按钮、输入框和任务流中强化实时反馈，让系统状态始终可感知。",
            "keywords": ["实时反馈", "微状态", "任务流"],
            "color_palette": ["#F8FAFC", "#CBD5E1", "#2563EB", "#16A34A", "#0F172A"],
            "mood_keywords": ["可控", "安心", "明确"],
            "difficulty": 1,
            "example_prompt": "为 AI 生成流程设计一套等待、处理中、完成、异常的反馈状态。",
        },
        {
            "name": "卡片式操作编排",
            "name_en": "Card-Based Orchestration",
            "description": "通过卡片聚合动作和上下文，把多步骤任务变成可组合的操作块。",
            "keywords": ["卡片操作", "编排", "上下文"],
            "color_palette": ["#FFFFFF", "#F1F5F9", "#94A3B8", "#6366F1", "#111827"],
            "mood_keywords": ["模块化", "灵活", "清楚"],
            "difficulty": 2,
            "example_prompt": "将多步骤工作流改造成卡片式操作台界面。",
        },
        {
            "name": "轻量沉浸式引导",
            "name_en": "Lightweight Guided Flow",
            "description": "减少全屏打断，改用局部高亮、浮层和上下文提示完成引导。",
            "keywords": ["引导", "浮层", "上下文提示"],
            "color_palette": ["#0F172A", "#334155", "#E2E8F0", "#F8FAFC", "#38BDF8"],
            "mood_keywords": ["顺滑", "不打断", "自然"],
            "difficulty": 2,
            "example_prompt": "为新用户首次使用设计一个轻量的引导流程，不依赖全屏蒙层。",
        },
    ],
    "材质纹理": [
        {
            "name": "磨砂玻璃层",
            "name_en": "Frosted Glass Layer",
            "description": "在浅背景上用轻磨砂与半透明边框建立层次，保持界面轻盈而不失结构。",
            "keywords": ["玻璃拟态", "半透明", "轻层次"],
            "color_palette": ["#FFFFFF", "#F1F5F9", "#BFDBFE", "#93C5FD", "#1E3A8A"],
            "mood_keywords": ["轻盈", "透明", "科技"],
            "difficulty": 2,
            "example_prompt": "为控制面板设计一组轻磨砂玻璃风格的悬浮卡片。",
        },
        {
            "name": "纸张颗粒质感",
            "name_en": "Paper Grain Texture",
            "description": "用轻微纸张颗粒和柔和阴影提升触感，让数字界面更有真实介质感。",
            "keywords": ["纸张", "颗粒", "触感"],
            "color_palette": ["#FAF7F2", "#E7E0D4", "#C8BBA8", "#7C6F64", "#2F3A4A"],
            "mood_keywords": ["温和", "真实", "沉稳"],
            "difficulty": 1,
            "example_prompt": "把一张分析卡片做出轻纸感和手工触感，但保持信息清晰。",
        },
        {
            "name": "金属边缘高光",
            "name_en": "Metallic Edge Highlight",
            "description": "通过金属感边缘和冷色高光，营造更硬朗的精密工业气质。",
            "keywords": ["金属", "高光", "工业感"],
            "color_palette": ["#F8FAFC", "#D1D5DB", "#9CA3AF", "#475569", "#111827"],
            "mood_keywords": ["精密", "冷峻", "硬朗"],
            "difficulty": 3,
            "example_prompt": "为硬件控制台做一张带金属高光边缘的仪表界面。",
        },
        {
            "name": "织物软界面",
            "name_en": "Textile Soft UI",
            "description": "将织物触感、柔软阴影和暖色明度引入界面，弱化数字产品的冷感。",
            "keywords": ["织物", "软界面", "暖感"],
            "color_palette": ["#FFF7ED", "#FED7AA", "#FDBA74", "#9A3412", "#431407"],
            "mood_keywords": ["亲和", "柔软", "生活化"],
            "difficulty": 2,
            "example_prompt": "设计一套带织物触感的生活方式应用卡片界面。",
        },
    ],
    "构图手法": [
        {
            "name": "非对称重心布局",
            "name_en": "Asymmetric Balance",
            "description": "利用非对称布局创造张力，再靠视觉重心保持整体平衡。",
            "keywords": ["非对称", "重心", "张力"],
            "color_palette": ["#FFFFFF", "#E5E7EB", "#9CA3AF", "#1D4ED8", "#111827"],
            "mood_keywords": ["灵动", "张力", "现代"],
            "difficulty": 2,
            "example_prompt": "为一个品牌专题页设计非对称但稳定的首屏构图。",
        },
        {
            "name": "留白驱动构图",
            "name_en": "Whitespace Framing",
            "description": "用留白划出信息优先级与阅读路径，让页面呼吸感成为构图的一部分。",
            "keywords": ["留白", "阅读路径", "呼吸感"],
            "color_palette": ["#FFFFFF", "#F8FAFC", "#CBD5E1", "#475569", "#0F172A"],
            "mood_keywords": ["从容", "清楚", "优雅"],
            "difficulty": 1,
            "example_prompt": "重新布局一个信息较多的页面，用留白替代装饰来提升清晰度。",
        },
        {
            "name": "分区叙事构图",
            "name_en": "Sectional Story Layout",
            "description": "将页面拆成主题明确的叙事分区，通过节奏变化推动用户逐段阅读。",
            "keywords": ["分区", "叙事", "节奏"],
            "color_palette": ["#F8FAFC", "#E2E8F0", "#94A3B8", "#2563EB", "#0F172A"],
            "mood_keywords": ["有序", "流动", "沉浸"],
            "difficulty": 2,
            "example_prompt": "把一个长滚动页面改成具有叙事节奏的分区构图。",
        },
        {
            "name": "满版沉浸裁切",
            "name_en": "Immersive Full-Bleed Crop",
            "description": "通过满版图片或色块裁切制造沉浸感，再用小面积信息层打破压迫感。",
            "keywords": ["满版", "裁切", "沉浸"],
            "color_palette": ["#020617", "#1E293B", "#E2E8F0", "#38BDF8", "#F8FAFC"],
            "mood_keywords": ["沉浸", "大胆", "戏剧性"],
            "difficulty": 2,
            "example_prompt": "为一个展示型页面设计满版裁切的视觉构图，确保文案仍可读。",
        },
    ],
}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DesignTrendService:
    CACHE_MAX_AGE_HOURS = 6
    SEARCH_QUERIES_PER_CATEGORY: Dict[str, List[str]] = {
        "视觉风格": [
            "{today_en} graphic design trends",
            "{year} web design trends",
            "{year} logo design trends",
            "{today_cn} 视觉设计趋势 网站 最新",
        ],
        "排版趋势": [
            "{today_en} typography trends",
            "{year} typography design trends",
            "{year} font design trends",
            "{today_cn} 排版 字体设计趋势 网站 最新",
        ],
        "色彩体系": [
            "{today_en} color design trends",
            "{year} color palette design trends",
            "{year} brand color trends",
            "{today_cn} 设计配色趋势 流行色 最新",
        ],
        "交互模式": [
            "{today_en} UI UX interaction trends",
            "{year} interaction design trends",
            "{year} ui ux design trends",
            "{today_cn} 交互设计趋势 微交互 最新",
        ],
        "材质纹理": [
            "{today_en} material texture design trends",
            "{year} material texture design trends",
            "{year} design materials trends",
            "{today_cn} 材质纹理 设计风格趋势 最新",
        ],
        "构图手法": [
            "{today_en} layout design trends",
            "{year} editorial design trends",
            "{year} layout composition design trends",
            "{today_cn} 构图 布局设计趋势 最新",
        ],
    }

    def __init__(self, repository: StateRepositoryProtocol) -> None:
        self.repository = repository
        self.search_provider = DuckDuckGoSearchProvider()
        self.state_root = Path(getattr(repository, "_state_root"))
        self.cache_dir = self.state_root / "trends"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, target_date: date) -> Path:
        return self.cache_dir / f"{target_date.isoformat()}.json"

    def _read_cache(self, target_date: date) -> Optional[Dict[str, Any]]:
        path = self._cache_path(target_date)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as error:
            LOGGER.warning("读取趋势缓存失败 %s: %s", path, error)
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("live_only") is not True:
            return None
        fetched_at = str(payload.get("pool_fetched_at") or "").strip()
        if target_date == self._today() and fetched_at:
            try:
                fetched_at_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            except ValueError:
                return None
            fetched_at_utc = fetched_at_dt.astimezone(timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - fetched_at_utc).total_seconds()
            if age_seconds > self.CACHE_MAX_AGE_HOURS * 3600:
                return None
        pool = payload.get("pool")
        if not isinstance(pool, list) or not pool:
            return None
        return payload

    def _write_cache(self, target_date: date, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = self._cache_path(target_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def _cleanup_old_caches(self, keep_days: int = 30) -> None:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=keep_days)
        for path in self.cache_dir.glob("*.json"):
            try:
                target = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if target < cutoff:
                path.unlink(missing_ok=True)

    def _today(self) -> date:
        return datetime.now().astimezone().date()

    def _query_context_tokens(self, target_date: date) -> Dict[str, str]:
        return {
            "year": str(target_date.year),
            "month": f"{target_date.month:02d}",
            "month_name": target_date.strftime("%B"),
            "today_en": target_date.strftime("%Y-%m-%d"),
            "today_cn": f"{target_date.year}年{target_date.month}月{target_date.day}日",
        }

    def _hash_seed(self, *parts: str) -> int:
        digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _validate_hex(self, value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if len(text) == 7 and text.startswith("#"):
            try:
                int(text[1:], 16)
            except ValueError:
                return None
            return text.upper()
        return None

    def _sanitize_keywords(self, values: Any, limit: int = 6) -> List[str]:
        if not isinstance(values, list):
            return []
        seen = set()
        cleaned: List[str] = []
        for item in values:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned

    def _sanitize_source_labels(self, values: Any, limit: int = 4) -> List[str]:
        if not isinstance(values, list):
            return []
        seen = set()
        cleaned: List[str] = []
        for item in values:
            text = str(item or "").strip()
            if not text:
                continue
            signature = text.casefold()
            if signature in seen:
                continue
            seen.add(signature)
            cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned

    def _strip_html(self, value: str) -> str:
        text = html.unescape(str(value or ""))
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s{2,}", " ", text).strip()

    def _format_pubdate_label(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return ""
        return f"{dt.month}月{dt.day}日"

    def _sanitize_trend(self, category: str, raw: Dict[str, Any], *, fetched_at: str, source_urls: Sequence[str]) -> Dict[str, Any]:
        fallback_palette = DEFAULT_PALETTES.get(category, DEFAULT_PALETTES["视觉风格"])
        palette = [self._validate_hex(item) for item in (raw.get("color_palette") or [])]
        sanitized_palette = [item for item in palette if item]
        if len(sanitized_palette) < 5:
            sanitized_palette = [*sanitized_palette, *fallback_palette][:5]
        difficulty = raw.get("difficulty", 2)
        try:
            difficulty = int(difficulty)
        except (TypeError, ValueError):
            difficulty = 2
        difficulty = max(1, min(3, difficulty))
        name = str(raw.get("name") or "").strip() or f"{category}灵感"
        normalized_source_urls = [str(item).strip() for item in source_urls if str(item).strip()][:6]
        return {
            "id": str(raw.get("id") or uuid.uuid4()),
            "name": name,
            "name_en": str(raw.get("name_en") or raw.get("nameEn") or "").strip(),
            "category": category,
            "description": str(raw.get("description") or "").strip() or f"{name}强调{category}中的最新表达方式。",
            "keywords": self._sanitize_keywords(raw.get("keywords")),
            "color_palette": sanitized_palette[:5],
            "mood_keywords": self._sanitize_keywords(raw.get("mood_keywords") or raw.get("moodKeywords")),
            "source_urls": normalized_source_urls,
            "difficulty": difficulty,
            "example_prompt": str(raw.get("example_prompt") or raw.get("examplePrompt") or "").strip() or f"围绕“{name}”做一张适合数字产品首页的练习稿。",
            "fetched_at": fetched_at,
            "summary_mode": str(raw.get("summary_mode") or "").strip() or None,
            "source_count": int(raw.get("source_count") or len(normalized_source_urls) or 0) or None,
            "source_labels": self._sanitize_source_labels(raw.get("source_labels")),
            "published_at": str(raw.get("published_at") or "").strip() or None,
        }

    async def _search_query(self, query: str, preferred_domains: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        try:
            results = await self.search_provider.search(
                query,
                max_results=10,
                preferred_domains=preferred_domains or (),
            )
            return list(results)
        except SearchProviderUnavailable as error:
            LOGGER.warning("趋势搜索暂不可用 query=%s error=%s diagnostics=%s", query, error, getattr(error, "diagnostics", {}))
            return []
        except Exception as error:  # pragma: no cover - network variance
            LOGGER.warning("趋势搜索失败 query=%s error=%s", query, error)
            return []

    async def _fetch_google_news_results(self, query: str, category: str) -> List[Dict[str, Any]]:
        params = {
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
        try:
            async with httpx.AsyncClient(timeout=18.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
                response = await client.get(GOOGLE_NEWS_RSS_URL, params=params)
                response.raise_for_status()
        except Exception as error:  # pragma: no cover - network variance
            LOGGER.warning("Google News RSS 抓取失败 query=%s error=%s", query, error)
            return []
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as error:
            LOGGER.warning("Google News RSS 解析失败 query=%s error=%s", query, error)
            return []

        results: List[Dict[str, Any]] = []
        for item in root.findall("./channel/item")[:GOOGLE_NEWS_MAX_RESULTS]:
            title = self._strip_html(item.findtext("title") or "")
            link = str(item.findtext("link") or "").strip()
            description = self._strip_html(item.findtext("description") or "")
            source_element = item.find("source")
            source_label = self._strip_html(source_element.text if source_element is not None and source_element.text else "")
            source_site_url = str(source_element.get("url") or "").strip() if source_element is not None else ""
            published_at = str(item.findtext("pubDate") or "").strip()
            if not title or not link:
                continue
            results.append(
                {
                    "title": title,
                    "snippet": description,
                    "url": link,
                    "source_label": source_label,
                    "source_site_url": source_site_url,
                    "published_at": published_at,
                    "category": category,
                    "result_kind": "google_news_rss",
                }
            )
        return results

    async def _extract_pages(self, results: Sequence[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
        candidates = [
            item
            for item in results
            if str(item.get("url") or "").strip() and str(item.get("result_kind") or "").strip() != "google_news_rss"
        ][:limit]
        if not candidates:
            return []
        extracted = await asyncio.gather(
            *(fetch_and_extract_page(str(item["url"])) for item in candidates),
            return_exceptions=True,
        )
        pages: List[Dict[str, Any]] = []
        for item in extracted:
            if isinstance(item, dict):
                pages.append(item)
        return pages

    async def _gather_category_context(self, category: str, target_date: date) -> Dict[str, Any]:
        tokens = self._query_context_tokens(target_date)
        queries = [query.format(**tokens) for query in self.SEARCH_QUERIES_PER_CATEGORY.get(category, [])]
        google_news_queries = [query.format(**tokens) for query in GOOGLE_NEWS_QUERIES_PER_CATEGORY.get(category, [])]
        search_batches = await asyncio.gather(*(self._search_query(query, preferred_domains=DESIGN_PREFERRED_DOMAINS) for query in queries))
        news_batches = await asyncio.gather(*(self._fetch_google_news_results(query, category) for query in google_news_queries))
        merged: List[Dict[str, Any]] = []
        seen_urls = set()
        seen_titles = set()

        for batch in [*news_batches, *search_batches]:
            for item in batch:
                url = str(item.get("url") or "").strip()
                title = str(item.get("title") or "").strip()
                title_signature = re.sub(r"\s+", " ", title).strip().casefold()
                if not url or url in seen_urls or (title_signature and title_signature in seen_titles):
                    continue
                seen_urls.add(url)
                if title_signature:
                    seen_titles.add(title_signature)
                merged.append(
                    {
                        "title": title,
                        "snippet": str(item.get("snippet") or "").strip(),
                        "url": url,
                        "source_label": str(item.get("source_label") or "").strip(),
                        "source_site_url": str(item.get("source_site_url") or "").strip(),
                        "published_at": str(item.get("published_at") or "").strip(),
                        "result_kind": str(item.get("result_kind") or "search").strip(),
                    }
                )
                if len(merged) >= 15:
                    break
            if len(merged) >= 15:
                break
        pages = await self._extract_pages(merged, limit=2)
        return {
            "category": category,
            "queries": [*queries, *google_news_queries],
            "results": merged[:15],
            "pages": pages,
        }

    def _extract_keywords_from_text(self, *parts: str, limit: int = 5) -> List[str]:
        text = " ".join(part for part in parts if part).strip()
        if not text:
            return []
        stopwords = {
            "design",
            "trends",
            "trend",
            "latest",
            "this",
            "these",
            "what",
            "will",
            "should",
            "that",
            "with",
            "more",
            "best",
            "new",
            "free",
            "into",
            "your",
            "their",
            "about",
            "designers",
            "roundup",
            "showcase",
            "graphic",
            "visual",
            "layout",
            "composition",
            "typography",
            "color",
            "palette",
            "interaction",
            "material",
            "texture",
            "website",
            "web",
            "2026",
            "2025",
            "设计",
            "趋势",
            "最新",
            "网站",
            "视觉",
            "排版",
            "色彩",
            "交互",
            "材质",
            "构图",
        }
        keywords: List[str] = []
        seen = set()
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z-]{3,}", text):
            normalized = token.strip()
            if not normalized:
                continue
            signature = normalized.lower()
            if signature in stopwords or signature in seen:
                continue
            seen.add(signature)
            keywords.append(normalized)
            if len(keywords) >= limit:
                break
        return keywords

    def _category_design_hints(self, category: str) -> List[str]:
        mapping = {
            "视觉风格": ["design", "visual", "graphic", "branding", "brand", "ui", "网页", "视觉", "品牌"],
            "排版趋势": ["typography", "font", "lettering", "editorial", "type", "排版", "字体", "字型"],
            "色彩体系": ["color", "palette", "branding", "ui color", "配色", "色彩", "流行色"],
            "交互模式": ["interaction", "ux", "ui", "microinteraction", "product design", "user flow", "交互", "微交互", "体验"],
            "材质纹理": ["glassmorphism", "texture", "material", "ui", "材质", "纹理", "拟态"],
            "构图手法": ["layout", "composition", "grid", "editorial", "版式", "布局", "构图"],
        }
        return mapping.get(category, [])

    def _publisher_text(self, result: Dict[str, Any]) -> str:
        return " ".join(
            [
                str(result.get("source_label") or ""),
                str(result.get("source_site_url") or ""),
            ]
        ).strip().lower()

    def _category_hint_hits(self, category: str, text: str) -> int:
        lowered = str(text or "").lower()
        return sum(1 for token in CATEGORY_SIGNAL_HINTS.get(category, []) if token in lowered)

    def _negative_hint_hits(self, category: str, text: str) -> int:
        lowered = str(text or "").lower()
        return sum(1 for token in CATEGORY_NEGATIVE_HINTS.get(category, []) if token in lowered)

    def _looks_like_design_source(self, result: Dict[str, Any]) -> bool:
        publisher_text = self._publisher_text(result)
        url = str(result.get("url") or "").strip()
        host = urlparse(url).netloc.lower().removeprefix("www.") if url else ""
        haystack = f"{publisher_text} {host}"
        if any(token in haystack for token in DESIGN_SOURCE_HINTS):
            return True
        if any(domain in host for domain in DESIGN_PREFERRED_DOMAINS):
            return True
        return False

    def _looks_like_interior_source(self, result: Dict[str, Any]) -> bool:
        publisher_text = self._publisher_text(result)
        url = str(result.get("url") or "").strip()
        host = urlparse(url).netloc.lower().removeprefix("www.") if url else ""
        haystack = f"{publisher_text} {host}"
        return any(token in haystack for token in INTERIOR_SOURCE_HINTS)

    def _score_live_result(self, category: str, result: Dict[str, Any], page: Optional[Dict[str, Any]] = None) -> int:
        haystack = " ".join(
            [
                str(result.get("title") or ""),
                str(result.get("snippet") or ""),
                str(result.get("source_label") or ""),
                str(result.get("source_site_url") or ""),
                str((page or {}).get("title") or ""),
                str((page or {}).get("text") or "")[:1600],
            ]
        )
        title = str(result.get("title") or "").strip()
        score = 0
        score += self._category_hint_hits(category, haystack) * 2
        score -= self._negative_hint_hits(category, haystack) * 3
        if self._looks_like_design_source(result):
            score += 2
        elif category in {"色彩体系", "材质纹理"} and self._looks_like_interior_source(result):
            score += 1
        if str(result.get("result_kind") or "") == "google_news_rss":
            score += 2
        if page:
            score += 1
        if str(result.get("published_at") or "").strip():
            score += 1
        if self._is_generic_signal_title(title):
            score -= 1
        return score

    def _clean_signal_title(self, title: str, source_label: str = "") -> str:
        cleaned = html.unescape(str(title or "")).strip()
        if not cleaned:
            return ""
        if source_label:
            cleaned = re.sub(rf"\s*[-|]\s*{re.escape(source_label)}\s*$", "", cleaned, flags=re.IGNORECASE)
        if "?" in cleaned:
            left, right = [part.strip() for part in cleaned.split("?", 1)]
            left_clean = re.sub(r"\b20\d{2}(?:['’]s)?\b", "", left, flags=re.IGNORECASE).strip(" /,.;:-")
            right_clean = re.sub(r"\b20\d{2}(?:['’]s)?\b", "", right, flags=re.IGNORECASE).strip(" /,.;:-")
            if right_clean and not self._is_generic_signal_title(right_clean):
                cleaned = right_clean
            elif left_clean:
                cleaned = left_clean
        if ":" in cleaned:
            left, right = [part.strip() for part in cleaned.split(":", 1)]
            left_clean = re.sub(r"\b20\d{2}(?:['’]s)?\b", "", left, flags=re.IGNORECASE).strip(" /,.;:-")
            right_clean = re.sub(r"\b20\d{2}(?:['’]s)?\b", "", right, flags=re.IGNORECASE).strip(" /,.;:-")
            if left_clean and not self._is_generic_signal_title(left_clean):
                cleaned = left_clean
            elif right_clean:
                cleaned = right_clean
        cleaned = re.sub(r"\b20\d{2}(?:['’]s)?\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"(?i)^\s*(top|best|latest|most popular)\s+", "", cleaned)
        cleaned = re.sub(r"(?i)^\s*(this|these)\s+", "", cleaned)
        cleaned = re.sub(r"(?i)^\s*(what you need to know about|future of|discover)\s+", "", cleaned)
        cleaned = re.sub(r"(?i)^what\s+(.*?)(?:\s+should\b.*|\s+say\b.*|\s+need\b.*)$", r"\1", cleaned)
        cleaned = re.sub(r"(?i)^how\s+designers\s+are\s+using\s+", "", cleaned)
        cleaned = re.sub(r"(?i)^we\s+asked\s+designers\s+what\s+", "", cleaned)
        cleaned = re.sub(r"(?i)\b(you need to know|to watch|will define|going into|trend report|trends report|year in review)\b", " ", cleaned)
        cleaned = re.sub(r"(?i)\b(according to .*|for .*|this year|on their way out)\b", " ", cleaned)
        cleaned = re.sub(r"(?i)\bto create\b.*$", "", cleaned)
        cleaned = re.sub(r"(?i)\b(trend|trends|guide|roundup|forecast|report|showcase)\b", " ", cleaned)
        cleaned = re.sub(r"(设计趋势|视觉设计趋势|排版设计趋势|色彩趋势|交互设计趋势|材质纹理趋势|构图设计趋势|最新|网站)", " ", cleaned)
        cleaned = re.sub(r"[\|\-–—：·•]+", " ", cleaned)
        cleaned = re.sub(r"(?i)\b(in|for|of|to|with)\s*$", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" /、，,.;。")
        return cleaned

    def _is_generic_signal_title(self, title: str) -> bool:
        normalized = str(title or "").strip().lower()
        if not normalized or len(normalized) < 4:
            return True
        generic_patterns = (
            "blog",
            "guide",
            "academy",
            "studio",
            "conclusion",
            "pivot",
            "introduction",
            "latest trends",
            "register now",
        )
        if any(pattern in normalized for pattern in generic_patterns):
            return True
        words = [token for token in re.findall(r"[a-zA-Z]+", normalized) if token]
        if words and all(token in {"the", "and", "with", "for", "what", "expect", "watch", "keep", "design"} for token in words):
            return True
        return False

    def _heading_candidates_from_page(self, page_text: str) -> List[str]:
        candidates: List[str] = []
        seen = set()
        for chunk in re.split(r"[\n\r]+", str(page_text or "")):
            cleaned = re.sub(r"^\s*(?:\d+[\.\)\-:： ]+|[-–—•●▪■◆]+)\s*", "", chunk).strip()
            if not cleaned or "http" in cleaned.lower():
                continue
            if len(cleaned) < 4 or len(cleaned) > 60:
                continue
            signature = cleaned.lower()
            if signature in seen:
                continue
            seen.add(signature)
            candidates.append(cleaned)
            if len(candidates) >= 5:
                break
        return candidates

    def _default_mood_keywords(self, category: str) -> List[str]:
        mapping = {
            "视觉风格": ["前沿", "品牌感", "辨识度"],
            "排版趋势": ["阅读性", "层级", "秩序"],
            "色彩体系": ["鲜明", "情绪", "对比"],
            "交互模式": ["流畅", "反馈", "可控"],
            "材质纹理": ["触感", "层次", "质地"],
            "构图手法": ["节奏", "重心", "叙事"],
        }
        return mapping.get(category, ["最新", "趋势"])

    def _contains_cjk(self, value: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))

    def _translate_keyword(self, keyword: str) -> str:
        text = str(keyword or "").strip()
        if not text:
            return ""
        if self._contains_cjk(text):
            return text
        normalized = re.sub(r"[^A-Za-z0-9+/ -]+", " ", text).strip().lower()
        if not normalized:
            return ""
        translated_parts: List[str] = []
        for token in re.split(r"[\s/+-]+", normalized):
            cleaned = token.strip().lower()
            if not cleaned:
                continue
            translated = ENGLISH_TOKEN_TRANSLATIONS.get(cleaned)
            if translated and translated not in translated_parts:
                translated_parts.append(translated)
        return " / ".join(translated_parts[:3]) if translated_parts else text

    def _translate_trend_name(self, category: str, english_name: str) -> str:
        text = str(english_name or "").strip()
        if not text:
            return ""
        if self._contains_cjk(text):
            return text
        normalized = text.lower()
        for pattern, translated in HEURISTIC_TITLE_TRANSLATIONS.get(category, []):
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return translated

        translated_tokens: List[str] = []
        for token in re.findall(r"[A-Za-z][A-Za-z-]{1,}", normalized):
            translated = ENGLISH_TOKEN_TRANSLATIONS.get(token.lower())
            if translated and translated not in translated_tokens:
                translated_tokens.append(translated)

        if translated_tokens:
            if category == "视觉风格":
                return "".join(translated_tokens[:3]) if translated_tokens[0] == "Logo" else "".join(translated_tokens[:3]) + "视觉"
            if category == "排版趋势":
                return "".join(translated_tokens[:3]) + "排版"
            if category == "色彩体系":
                return "".join(translated_tokens[:3]) + "配色"
            if category == "交互模式":
                return "".join(translated_tokens[:3]) + "体验"
            if category == "材质纹理":
                return "".join(translated_tokens[:3]) + "材质"
            if category == "构图手法":
                return "".join(translated_tokens[:3]) + "构图"
        return text

    def _translated_keywords_for(self, category: str, chinese_name: str, english_name: str) -> List[str]:
        english_lower = str(english_name or "").lower()
        if category == "视觉风格":
            if "logo" in english_lower:
                return ["Logo", "品牌识别", "图形符号"]
            if "human" in english_lower:
                return ["人本设计", "温度感", "视觉叙事"]
            return ["视觉表达", "风格方向", "品牌感"]
        if category == "排版趋势":
            if "free" in english_lower:
                return ["免费字体", "尝试方向", "排版层级"]
            if "popular" in english_lower:
                return ["热门字体", "字型趋势", "阅读节奏"]
            return ["字体风格", "排版层级", "阅读节奏"]
        if category == "色彩体系":
            if "plum" in english_lower or "green" in english_lower or "orange" in english_lower:
                return ["梅紫", "电光绿", "高对比配色"]
            if "neutral" in english_lower:
                return ["中性色", "柔和配色", "空间感"]
            return ["色彩组合", "情绪表达", "配色趋势"]
        if category == "交互模式":
            if "ui" in english_lower or "ux" in english_lower:
                return ["UI", "UX", "交互体验"]
            if "email" in english_lower:
                return ["邮件体验", "版式反馈", "信息节奏"]
            return ["交互流程", "反馈状态", "体验节奏"]
        if category == "材质纹理":
            if "high" in english_lower and "mix" in english_lower:
                return ["材质混搭", "层次感", "纹理表达"]
            if "material" in english_lower:
                return ["材质表达", "触感层次", "纹理变化"]
            return ["材质感", "触感", "层次"]
        if category == "构图手法":
            if "email" in english_lower:
                return ["邮件版式", "信息层级", "阅读路径"]
            if "graphic" in english_lower:
                return ["平面构图", "视觉重心", "版式节奏"]
            return ["版式布局", "构图节奏", "信息重心"]
        return [chinese_name] if chinese_name else []

    def _example_prompt_for(self, category: str, name: str) -> str:
        prompts = {
            "视觉风格": f"围绕“{name}”做一版首页视觉概念稿，重点验证整体气质和品牌辨识度。",
            "排版趋势": f"围绕“{name}”设计一组标题、正文和说明文字层级，验证阅读节奏。",
            "色彩体系": f"围绕“{name}”整理一套界面主色、点缀色和状态色方案。",
            "交互模式": f"围绕“{name}”设计一段关键任务流，重点验证反馈和操作节奏。",
            "材质纹理": f"围绕“{name}”做一组卡片和容器样式，验证材质层次与质感表达。",
            "构图手法": f"围绕“{name}”重做一个首屏或长页面构图，验证信息重心和叙事节奏。",
        }
        return prompts.get(category, f"围绕“{name}”做一版可用于数字产品界面的练习稿。")

    def _description_from_result(self, category: str, result: Dict[str, Any], page: Optional[Dict[str, Any]]) -> str:
        snippet = str(result.get("snippet") or "").strip()
        source_label = str(result.get("source_label") or "").strip()
        published_label = self._format_pubdate_label(str(result.get("published_at") or "").strip())
        english_title = self._clean_signal_title(str(result.get("title") or ""), source_label)
        translated_title = self._translate_trend_name(category, english_title)
        if snippet and self._contains_cjk(snippet) and len(snippet) >= 24 and source_label.casefold() not in snippet.casefold():
            return snippet
        page_text = str((page or {}).get("text") or "").strip()
        if page_text and self._contains_cjk(page_text):
            for sentence in re.split(r"[。！？.!?]\s*", page_text):
                cleaned = sentence.strip()
                if len(cleaned) >= 18:
                    return cleaned[:140]
        if source_label or published_label:
            prefix = source_label or "站外来源"
            if published_label:
                prefix = f"{prefix} 在 {published_label}"
            if translated_title:
                return f"{prefix} 发布的趋势文章聚焦“{translated_title}”，可作为今天的站外设计信号。"
            return f"{prefix} 发布了当天可用的站外设计趋势文章。"
        return ""

    def _heuristic_signal_name(self, category: str, result: Dict[str, Any], page: Optional[Dict[str, Any]]) -> str:
        page_text = str((page or {}).get("text") or "")
        source_label = str(result.get("source_label") or "").strip()
        primary_candidates = [
            self._clean_signal_title(str(result.get("title") or "").strip(), source_label),
            self._clean_signal_title(str((page or {}).get("title") or "").strip()),
        ]
        for cleaned in primary_candidates:
            if cleaned and len(cleaned) >= 4 and not self._is_generic_signal_title(cleaned):
                return cleaned
        for cleaned in primary_candidates:
            if cleaned and len(cleaned) >= 6:
                return cleaned
        for candidate in self._heading_candidates_from_page(page_text):
            cleaned = self._clean_signal_title(candidate)
            if cleaned and len(cleaned) >= 4 and not self._is_generic_signal_title(cleaned):
                return cleaned
        keywords = self._extract_keywords_from_text(
            self._description_from_result(category, result, page),
            str((page or {}).get("title") or ""),
            str(result.get("title") or ""),
            limit=2,
        )
        if keywords:
            return " / ".join(keywords[:2])
        return f"{category}站外信号"

    def _extract_with_heuristics(self, category: str, context: Dict[str, Any], fetched_at: str) -> List[Dict[str, Any]]:
        results = [item for item in (context.get("results") or []) if isinstance(item, dict)]
        pages_by_url = {
            str(item.get("url") or "").strip(): item
            for item in (context.get("pages") or [])
            if isinstance(item, dict) and str(item.get("url") or "").strip()
        }
        trends: List[Dict[str, Any]] = []
        seen_names = set()
        scored_results: List[tuple[int, Dict[str, Any], Optional[Dict[str, Any]]]] = []
        for result in results:
            url = str(result.get("url") or "").strip()
            if not url:
                continue
            page = pages_by_url.get(url)
            score = self._score_live_result(category, result, page)
            if score < 2:
                continue
            scored_results.append((score, result, page))

        scored_results.sort(
            key=lambda item: (
                item[0],
                bool(str(item[1].get("published_at") or "").strip()),
                str(item[1].get("title") or "").strip(),
            ),
            reverse=True,
        )

        for _score, result, page in scored_results[:8]:
            url = str(result.get("url") or "").strip()
            english_name = self._heuristic_signal_name(category, result, page)
            name = self._translate_trend_name(category, english_name)
            signature = name.lower()
            if not name or signature in seen_names:
                continue
            if self._is_generic_signal_title(english_name) and _score < 5:
                continue
            seen_names.add(signature)
            description = self._description_from_result(category, result, page) or f"基于站外最新搜索结果整理的“{name}”趋势信号。"
            keywords = self._translated_keywords_for(category, name, english_name)
            source_label = str(result.get("source_label") or "").strip()
            if not source_label:
                try:
                    source_label = urlparse(url).netloc.lower().removeprefix("www.")
                except ValueError:
                    source_label = ""
            trends.append(
                self._sanitize_trend(
                    category,
                    {
                        "name": name,
                        "name_en": english_name if re.search(r"[A-Za-z]", english_name) else "",
                        "description": description,
                        "keywords": keywords,
                        "mood_keywords": self._default_mood_keywords(category),
                        "difficulty": 2 if page else 1,
                        "example_prompt": self._example_prompt_for(category, name),
                        "summary_mode": "heuristic",
                        "source_count": 1,
                        "source_labels": [source_label] if source_label else [],
                        "published_at": str(result.get("published_at") or "").strip() or None,
                    },
                    fetched_at=fetched_at,
                    source_urls=[url],
                )
            )
            if len(trends) >= 3:
                break
        return trends

    def _build_llm_prompt(self, category: str, context: Dict[str, Any], target_date: date) -> str:
        snippets: List[str] = []
        for index, result in enumerate(context.get("results") or [], start=1):
            snippets.append(
                f"[搜索结果 {index}]\n标题: {result.get('title')}\n摘要: {result.get('snippet')}\n链接: {result.get('url')}"
            )
        for index, page in enumerate(context.get("pages") or [], start=1):
            snippets.append(
                f"[正文摘录 {index}]\n标题: {page.get('title')}\n摘要: {page.get('snippet')}\n正文: {str(page.get('text') or '')[:1200]}\n链接: {page.get('url')}"
            )
        joined = "\n\n".join(snippets[:18])
        return (
            "你是一个设计趋势结构化助手。请只基于给定的真实站外搜索结果，提炼该类别下 3 到 4 条最新趋势。\n"
            f"类别：{category}\n"
            f"目标日期：{target_date.isoformat()}\n"
            "输出要求：\n"
            "1. 只输出 JSON，不要输出 markdown。\n"
            "2. 顶层必须是对象，结构为 {\"trends\":[...]}。\n"
            "3. 每条 trend 字段必须包含：name, name_en, description, keywords, color_palette, mood_keywords, difficulty, example_prompt。\n"
            "4. color_palette 必须是 5 个十六进制颜色值。\n"
            "5. difficulty 只能是 1、2、3。\n"
            "6. 只能基于材料中可支持的信息总结，不要虚构品牌、年份、案例或站外趋势。\n"
            "7. 如果材料明显偏旧、偏泛或只是在讲年度合集，请优先提炼其中最接近当前日期、最新发布、最新展示的趋势信号。\n\n"
            f"参考材料：\n{joined}"
        )

    async def _extract_with_llm(self, category: str, context: Dict[str, Any], target_date: date, fetched_at: str) -> List[Dict[str, Any]]:
        settings = load_llm_settings()
        if not runtime_api_key_configured(settings):
            return []
        prompt = self._build_llm_prompt(category, context, target_date)
        source_urls = [str(item.get("url") or "").strip() for item in (context.get("results") or []) if str(item.get("url") or "").strip()]
        source_labels = self._sanitize_source_labels([item.get("source_label") for item in (context.get("results") or [])])
        published_at = next((str(item.get("published_at") or "").strip() for item in (context.get("results") or []) if str(item.get("published_at") or "").strip()), None)
        try:
            client = create_llm_client()
            payload = await asyncio.to_thread(
                client.complete_json,
                [
                    {"role": "system", "content": "你输出严格 JSON，并帮助前端产品把设计趋势提炼成结构化卡片。"},
                    {"role": "user", "content": prompt},
                ],
                0.2,
                2200,
            )
        except Exception as error:  # pragma: no cover - runtime variability
            LOGGER.warning("趋势 LLM 提取失败 category=%s error=%s", category, error)
            return []

        trends_payload = payload.get("trends") if isinstance(payload, dict) else payload
        if not isinstance(trends_payload, list):
            return []
        sanitized: List[Dict[str, Any]] = []
        for item in trends_payload[:4]:
            if not isinstance(item, dict):
                continue
            item = {
                **item,
                "summary_mode": "llm",
                "source_count": len(source_urls),
                "source_labels": source_labels,
                "published_at": published_at,
            }
            sanitized.append(self._sanitize_trend(category, item, fetched_at=fetched_at, source_urls=source_urls))
        return sanitized

    def _dedupe_trends(self, trends: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in trends:
            signature = (str(item.get("category") or "").strip(), str(item.get("name") or "").strip().lower())
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(item)
        return deduped

    async def _build_daily_pool(self, target_date: date) -> Dict[str, Any]:
        fetched_at = iso_now()
        contexts = await asyncio.gather(*(self._gather_category_context(category, target_date) for category in TREND_CATEGORY_ORDER))
        pool: List[Dict[str, Any]] = []
        diagnostics: Dict[str, Any] = {"categories": []}
        for category, context in zip(TREND_CATEGORY_ORDER, contexts):
            llm_trends = await self._extract_with_llm(category, context, target_date, fetched_at)
            heuristic_trends = self._extract_with_heuristics(category, context, fetched_at)
            category_pool = llm_trends or heuristic_trends
            diagnostics["categories"].append(
                {
                    "category": category,
                    "query_count": len(context.get("queries") or []),
                    "search_result_count": len(context.get("results") or []),
                    "page_extract_count": len(context.get("pages") or []),
                    "llm_used": bool(llm_trends),
                    "heuristic_used": bool(not llm_trends and heuristic_trends),
                    "trend_count": len(category_pool),
                    "live_only": True,
                }
            )
            pool.extend(category_pool)
        deduped_pool = self._dedupe_trends(pool)
        available_categories = [category for category in TREND_CATEGORY_ORDER if any(item.get("category") == category for item in deduped_pool)]
        if not deduped_pool:
            raise ValueError("今日未抓到可用的站外设计趋势，请稍后刷新重试。")
        payload = {
            "date": target_date.isoformat(),
            "pool": deduped_pool,
            "pool_fetched_at": fetched_at,
            "diagnostics": diagnostics,
            "available_category_count": len(available_categories),
            "live_only": True,
        }
        self._cleanup_old_caches()
        return self._write_cache(target_date, payload)

    async def get_today_trend_pool(self, force_refresh: bool = False) -> Dict[str, Any]:
        target_date = self._today()
        if not force_refresh:
            cached = self._read_cache(target_date)
            if cached:
                return cached
        return await self._build_daily_pool(target_date)

    async def force_refresh_today(self) -> Dict[str, Any]:
        return await self.get_today_trend_pool(force_refresh=True)

    def force_refresh_today_sync(self) -> Dict[str, Any]:
        return asyncio.run(self.force_refresh_today())

    def roll_trend_for_user(
        self,
        user_id: str,
        pool_payload: Dict[str, Any],
        *,
        target_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        target_date = target_date or self._today()
        pool = [item for item in (pool_payload.get("pool") or []) if isinstance(item, dict)]
        if not pool:
            raise ValueError("今日趋势池为空。")
        date_key = target_date.isoformat()
        seed = self._hash_seed(user_id, date_key)
        available_categories = [category for category in TREND_CATEGORY_ORDER if any(str(item.get("category") or "").strip() == category for item in pool)]
        if not available_categories:
            raise ValueError("今日没有可展示的站外趋势类别。")
        dice_category = available_categories[seed % len(available_categories)]
        dice_face = TREND_CATEGORY_ORDER.index(dice_category) + 1
        category_pool = [item for item in pool if str(item.get("category") or "").strip() == dice_category]
        trend = category_pool[seed % len(category_pool)]
        return {
            "date": date_key,
            "trend": trend,
            "dice_face": dice_face,
            "dice_category": dice_category,
            "pool": pool,
            "pool_fetched_at": pool_payload.get("pool_fetched_at"),
        }

    def get_user_history(self, user_id: str, days: int = 30) -> List[Dict[str, Any]]:
        today = self._today()
        records: List[Dict[str, Any]] = []
        for offset in range(max(1, min(days, 60))):
            target_date = today - timedelta(days=offset)
            cached = self._read_cache(target_date)
            if not cached:
                continue
            try:
                rolled = self.roll_trend_for_user(user_id, cached, target_date=target_date)
            except ValueError:
                continue
            records.append(
                {
                    "date": rolled["date"],
                    "trend": rolled["trend"],
                    "dice_face": rolled["dice_face"],
                    "dice_category": rolled["dice_category"],
                }
            )
        return records
