import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from pm_agent_worker.tools.content_extractor import (
    FetchPreflightError,
    InvalidFetchUrlError,
    PrivateAccessError,
    UnsafeRedirectError,
    fetch_and_extract_page,
    infer_authority_score,
    infer_source_type,
)
from pm_agent_worker.tools.minimax_client import MiniMaxChatClient
from pm_agent_worker.tools.prompt_loader import load_prompt_template
from pm_agent_worker.tools.search_provider import DuckDuckGoSearchProvider
from pm_agent_worker.tools.prompt_injection_guard import score_prompt_injection_risk
from pm_agent_worker.workflows.control import JobCancelledError
from pm_agent_worker.workflows.presentation_labels import market_step_label
from pm_agent_worker.workflows.research_models import iso_now, top_keywords


SEARCH_STRATEGIES: Dict[str, Dict[str, tuple[str, ...]]] = {
    "market_trends": {
        "preferred_source_types": ("article", "web", "documentation"),
        "preferred_domains": ("mckinsey.com", "gartner.com", "cbinsights.com", "techcrunch.com", "forrester.com"),
        "query_hints": ("market trends report adoption", "industry analysis benchmark"),
        "query_lenses": ("market", "analysis", "official"),
    },
    "user_jobs_and_pains": {
        "preferred_source_types": ("review", "community", "article"),
        "preferred_domains": ("reddit.com", "g2.com", "capterra.com", "producthunt.com", "youtube.com"),
        "query_hints": ("user pain points customer feedback", "reviews forum reddit complaints"),
        "query_lenses": ("reviews", "community", "analysis"),
    },
    "competitor_landscape": {
        "preferred_source_types": ("web", "review", "article"),
        "preferred_domains": ("g2.com", "capterra.com", "producthunt.com", "github.com"),
        "query_hints": ("competitors alternatives comparison", "vs competitors market landscape"),
        "query_lenses": ("comparison", "reviews", "official", "analysis"),
    },
    "product_experience_teardown": {
        "preferred_source_types": ("documentation", "web", "article"),
        "preferred_domains": ("docs.", "help.", "support.", "developers.", "github.com"),
        "query_hints": ("product walkthrough onboarding docs", "features help center demo"),
        "query_lenses": ("docs", "official", "reviews", "comparison"),
    },
    "reviews_and_sentiment": {
        "preferred_source_types": ("review", "community", "article"),
        "preferred_domains": ("reddit.com", "g2.com", "capterra.com", "x.com", "twitter.com"),
        "query_hints": ("reviews reddit g2 capterra complaints", "user sentiment feedback community"),
        "query_lenses": ("reviews", "community", "analysis"),
    },
    "pricing_and_business_model": {
        "preferred_source_types": ("pricing", "web", "article"),
        "preferred_domains": ("g2.com", "capterra.com", "pricing", "plans"),
        "query_hints": ("pricing plans billing", "business model pricing page"),
        "query_lenses": ("pricing", "official", "reviews", "comparison"),
    },
    "acquisition_and_distribution": {
        "preferred_source_types": ("article", "web", "community"),
        "preferred_domains": ("hubspot.com", "substack.com", "medium.com", "linkedin.com"),
        "query_hints": ("distribution channel partnerships seo", "go to market growth channels"),
        "query_lenses": ("analysis", "community", "official"),
    },
    "opportunities_and_risks": {
        "preferred_source_types": ("article", "community", "web"),
        "preferred_domains": ("substack.com", "medium.com", "reddit.com", "techcrunch.com"),
        "query_hints": ("opportunities risks adoption blockers", "strategy recommendations constraints"),
        "query_lenses": ("analysis", "community", "market"),
    },
    "recommendations": {
        "preferred_source_types": ("article", "community", "web"),
        "preferred_domains": ("substack.com", "medium.com", "reddit.com", "techcrunch.com"),
        "query_hints": ("strategy recommendations playbook", "opportunities risks next steps"),
        "query_lenses": ("analysis", "comparison", "community"),
    },
}

SEARCH_STRATEGY_ALIASES = {
    "user_research": "user_jobs_and_pains",
    "competitor_analysis": "competitor_landscape",
    "business_and_channels": "pricing_and_business_model",
}

QUERY_STOPWORDS = {
    "如果",
    "应该",
    "优先",
    "什么",
    "怎么",
    "如何",
    "方案",
    "请给我建议",
    "补充研究",
    "question",
    "please",
    "do",
    "deeper",
    "research",
    "revise",
    "report",
    "answer",
    "directly",
    "this",
    "for",
    "should",
    "and",
    "teams",
    "围绕",
    "调研",
    "研究",
    "重点关注",
    "聚焦",
    "补充",
    "定向",
    "工作台",
    "json",
}

TASK_FOCUS_STOPWORDS = {
    "market",
    "markets",
    "trend",
    "trends",
    "research",
    "analysis",
    "official",
    "comparison",
    "review",
    "reviews",
    "community",
    "user",
    "users",
    "jobs",
    "pains",
    "customer",
    "product",
    "products",
    "business",
    "channels",
    "market_trends",
    "user_jobs_and_pains",
    "competitor_landscape",
    "product_experience_teardown",
    "reviews_and_sentiment",
    "pricing_and_business_model",
    "acquisition_and_distribution",
    "opportunities_and_risks",
    "recommendations",
    "市场",
    "趋势",
    "研究",
    "分析",
    "官方",
    "对比",
    "评测",
    "评价",
    "社区",
    "用户",
    "产品",
    "商业化",
    "渠道",
    "建议",
    "model",
    "models",
}

META_TOPIC_HINTS = {
    "test",
    "smoke",
    "demo",
    "sample",
    "example",
    "sandbox",
    "tmp",
    "debug",
    "qa",
    "测试",
    "演示",
    "示例",
    "样例",
    "沙盒",
    "调试",
}

META_TOPIC_CONTEXT_HINTS = {
    "agent",
    "agents",
    "sub-agent",
    "sub-agents",
    "workflow",
    "assistant",
    "copilot",
    "代理",
    "子agent",
    "工作流",
    "助手",
}

LOW_SIGNAL_QUERY_PHRASES = (
    "围绕",
    "重点关注",
    "补充研究",
    "只返回",
    "json",
)

INDUSTRY_TEMPLATE_QUERY_HINTS = {
    "industrial_design": "industrial design",
    "product_design": "product design",
    "saas": "saas software",
    "ai_product": "ai product",
    "internet": "internet product",
    "ecommerce": "ecommerce platform",
}

QUERY_PHRASE_PACKS = {
    "zh": {
        "official": "官网 产品介绍",
        "docs": "文档 帮助中心 使用说明",
        "pricing": "定价 套餐 计费",
        "reviews": "评测 评价 用户反馈",
        "community": "社区 论坛 reddit 讨论",
        "comparison": "竞品 替代 对比 comparison alternatives",
        "market": "市场 趋势 报告 benchmark",
        "analysis": "案例 分析 实践 调研",
    },
    "en": {
        "official": "official product overview",
        "docs": "docs help center guide",
        "pricing": "pricing plans billing",
        "reviews": "reviews customer feedback",
        "community": "reddit forum community discussion",
        "comparison": "alternatives comparison vs",
        "market": "market trends benchmark report",
        "analysis": "case study analysis best practices",
    },
}

QUERY_RETRY_PHRASE_PACKS = {
    "zh": {
        "official": "官网",
        "docs": "文档",
        "pricing": "定价",
        "reviews": "评价",
        "community": "reddit 讨论",
        "comparison": "对比",
        "market": "市场 趋势",
        "analysis": "市场 分析",
    },
    "en": {
        "official": "official",
        "docs": "docs",
        "pricing": "pricing",
        "reviews": "reviews",
        "community": "reddit reviews",
        "comparison": "comparison",
        "market": "market trends",
        "analysis": "market analysis",
    },
}

SEARCH_DOMAIN_LABELS = {
    "reddit.com": "reddit",
    "g2.com": "g2",
    "capterra.com": "capterra",
    "producthunt.com": "product hunt",
    "github.com": "github",
    "mckinsey.com": "mckinsey",
    "gartner.com": "gartner",
    "cbinsights.com": "cb insights",
    "forrester.com": "forrester",
    "meta.com": "meta",
}

CATEGORY_QUERY_FOCUS_HINTS = {
    "market_trends": {
        "zh": "增长 采用 benchmark 案例",
        "en": "growth adoption benchmark case study",
    },
    "user_jobs_and_pains": {
        "zh": "用户痛点 使用场景 真实反馈",
        "en": "pain points use cases customer feedback",
    },
    "competitor_landscape": {
        "zh": "竞品 替代 关键差异",
        "en": "competitors alternatives differentiation",
    },
    "product_experience_teardown": {
        "zh": "上手流程 核心功能 使用摩擦",
        "en": "onboarding core features friction",
    },
    "reviews_and_sentiment": {
        "zh": "好评 差评 争议点",
        "en": "positive reviews complaints controversy",
    },
    "pricing_and_business_model": {
        "zh": "定价 套餐 计费 价值反馈",
        "en": "pricing plans billing value feedback",
    },
    "acquisition_and_distribution": {
        "zh": "获客 分发 合作 反馈",
        "en": "acquisition distribution partnerships feedback",
    },
    "opportunities_and_risks": {
        "zh": "机会 风险 约束 反例",
        "en": "opportunities risks constraints counterexamples",
    },
    "recommendations": {
        "zh": "建议 动作 优先级 取舍",
        "en": "recommendations actions priorities tradeoffs",
    },
}

GEO_QUERY_HINTS = {
    "美国": {"zh": "美国", "en": "us"},
    "usa": {"zh": "美国", "en": "us"},
    "us": {"zh": "美国", "en": "us"},
    "united states": {"zh": "美国", "en": "us"},
    "中国": {"zh": "中国", "en": "china"},
    "china": {"zh": "中国", "en": "china"},
    "日本": {"zh": "日本", "en": "japan"},
    "japan": {"zh": "日本", "en": "japan"},
    "英国": {"zh": "英国", "en": "uk"},
    "uk": {"zh": "英国", "en": "uk"},
    "united kingdom": {"zh": "英国", "en": "uk"},
    "欧洲": {"zh": "欧洲", "en": "europe"},
    "europe": {"zh": "欧洲", "en": "europe"},
    "全球": {"zh": "全球", "en": "global"},
    "global": {"zh": "全球", "en": "global"},
    "海外": {"zh": "海外", "en": "global"},
    "international": {"zh": "海外", "en": "global"},
}

QUERY_COVERAGE_PATTERNS = {
    "official": ("site:", "官网", "official", "docs", "doc", "文档", "help", "support", "developer", "developers"),
    "pricing": ("pricing", "price", "plan", "plans", "billing", "cost", "定价", "套餐", "计费", "价格"),
    "community": (
        "评测",
        "评价",
        "review",
        "reviews",
        "feedback",
        "complaint",
        "complaints",
        "reddit",
        "社区",
        "论坛",
        "forum",
        "discussion",
        "discuss",
        "g2",
        "capterra",
        "producthunt",
        "pain point",
        "pain points",
    ),
    "comparison": ("竞品", "替代", "对比", "comparison", "compare", "alternatives", "alternative", "vs"),
    "analysis": (
        "趋势",
        "报告",
        "benchmark",
        "analysis",
        "analyst",
        "insight",
        "insights",
        "case study",
        "case studies",
        "案例",
        "market",
        "调研",
        "feedback",
        "pain point",
        "pain points",
        "use case",
        "use cases",
        "tradeoff",
        "tradeoffs",
    ),
}

SOURCE_TYPE_COVERAGE_TAGS = {
    "web": ("official",),
    "documentation": ("official",),
    "pricing": ("pricing", "official"),
    "community": ("community",),
    "review": ("community", "analysis"),
    "article": ("analysis",),
}

OFFICIAL_QUERY_SIGNAL_TOKENS = (
    "官网",
    "official",
    "docs",
    "doc",
    "documentation",
    "文档",
    "help",
    "support",
    "developer",
    "developers",
)

SITE_QUERY_EXCLUDED_DOMAINS = {
    "reddit.com",
    "g2.com",
    "capterra.com",
    "producthunt.com",
    "github.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "linkedin.com",
}

ENGLISH_GEO_HINTS = {
    "美国": "us",
    "中国": "china",
    "英国": "uk",
    "欧洲": "europe",
    "海外": "global",
    "全球": "global",
}

TASK_REQUIRED_QUERY_COVERAGE = {
    "market_trends": ("official", "analysis"),
    "user_jobs_and_pains": ("community", "analysis"),
    "competitor_landscape": ("official", "comparison", "community"),
    "product_experience_teardown": ("official", "comparison", "community"),
    "reviews_and_sentiment": ("community", "analysis"),
    "pricing_and_business_model": ("pricing", "official", "comparison", "community"),
    "acquisition_and_distribution": ("analysis", "official"),
    "opportunities_and_risks": ("analysis", "community"),
    "recommendations": ("analysis", "comparison"),
}

TASK_DISCOURAGED_QUERY_COVERAGE = {
    "market_trends": ("community", "comparison"),
    "user_jobs_and_pains": ("comparison",),
    "reviews_and_sentiment": ("comparison",),
}

GENERIC_RELEVANCE_TOKENS = {
    "ai",
    "app",
    "apps",
    "tool",
    "tools",
    "software",
    "platform",
    "product",
    "products",
    "saas",
    "market",
    "markets",
    "trend",
    "trends",
    "report",
    "analysis",
    "pricing",
    "research",
    "benchmark",
    "agent",
    "agents",
    "team",
    "teams",
    "pm",
    "产品",
    "工具",
    "平台",
    "软件",
    "系统",
    "市场",
    "趋势",
    "报告",
    "分析",
    "调研",
    "研究",
    "行业",
    "用户",
    "方案",
    "企业",
    "中国",
    "美国",
}

TOPIC_ALIAS_HINTS = {
    "眼镜": ("glasses", "smart glasses"),
    "智能眼镜": ("smart glasses", "ai glasses"),
    "耳机": ("earbuds", "headphones"),
    "自行车": ("bicycle", "bike"),
    "轮胎": ("tire", "tyres"),
    "手机": ("smartphone", "phone"),
    "相机": ("camera",),
    "机器人": ("robot", "robotics"),
    "汽车": ("car", "automotive"),
    "客服": ("customer support", "helpdesk"),
    "办公": ("productivity", "office"),
    "工作台": ("workbench", "workspace"),
}

TOPIC_EXEMPLAR_HINTS = {
    "智能眼镜": ("Ray-Ban Meta", "Rokid", "XREAL", "Solos"),
    "眼镜": ("Ray-Ban Meta", "Rokid", "XREAL", "Solos"),
}

SMART_GLASSES_EXEMPLAR_RECORDS = (
    {
        "name": "Ray-Ban Meta",
        "domains": ("meta.com", "ray-ban.com"),
        "query_terms": ("Ray-Ban Meta smart glasses",),
    },
    {
        "name": "Rokid",
        "domains": ("global.rokid.com", "rokid.com"),
        "query_terms": ("Rokid ai glasses",),
        "source_url": "https://global.rokid.com/products/rokid-glasses",
    },
    {
        "name": "XREAL",
        "domains": ("xreal.com",),
        "query_terms": ("XREAL augmented reality glasses",),
        "source_url": "https://www.xreal.com/",
    },
    {
        "name": "Solos",
        "domains": ("solosglasses.com",),
        "query_terms": ("Solos AI glasses",),
        "source_url": "https://solosglasses.com/",
    },
)

TOPIC_EXEMPLAR_RECORDS = {
    "智能眼镜": SMART_GLASSES_EXEMPLAR_RECORDS,
    "眼镜": SMART_GLASSES_EXEMPLAR_RECORDS,
}

TOPIC_REVIEW_DOMAINS = {
    "智能眼镜": ("techradar.com", "androidcentral.com", "tomsguide.com", "wired.com"),
    "眼镜": ("techradar.com", "androidcentral.com", "tomsguide.com", "wired.com"),
}

PHYSICAL_PRODUCT_TOPIC_HINTS = (
    "眼镜",
    "手机",
    "耳机",
    "相机",
    "汽车",
    "自行车",
    "轮胎",
    "机器人",
    "硬件",
)

PHYSICAL_PRODUCT_LOW_SIGNAL_DOMAINS = {
    "g2.com",
    "capterra.com",
    "producthunt.com",
    "github.com",
    "amazon.com",
    "lenscrafters.com",
    "visionexpress.com",
}

STRICT_TOPIC_RELEVANCE_STEPS = {
    "user-research",
    "competitor-analysis",
    "experience-teardown",
    "reviews-and-sentiment",
}

COMPETITOR_FOCUS_MARKET_STEPS = {
    "competitor-analysis",
    "business-and-channels",
}

COMPETITOR_SIGNAL_TOKENS = (
    "competitor",
    "competitors",
    "competitive",
    "alternatives",
    "alternative",
    "vs",
    "versus",
    "compare",
    "comparison",
    "landscape",
    "竞品",
    "竞争",
    "替代",
    "对比",
    "比较",
    "格局",
)

COMPETITOR_NAME_STOPWORDS = {
    "ai",
    "app",
    "apps",
    "tool",
    "tools",
    "platform",
    "platforms",
    "product",
    "products",
    "software",
    "official",
    "review",
    "reviews",
    "comparison",
    "alternatives",
    "competitor",
    "competitors",
    "pricing",
    "plans",
    "docs",
    "documentation",
    "help",
    "support",
    "市场",
    "行业",
    "产品",
    "平台",
    "官网",
    "官方",
    "文档",
    "定价",
    "套餐",
    "价格",
    "对比",
    "比较",
    "替代",
    "竞品",
    "讨论",
    "社区",
    "论坛",
    "用户",
    "功能",
    "体验",
    "details",
    "feature",
    "features",
    "lightest",
    "style",
    "officially",
    "launches",
    "integration",
    "trends",
    "statistics",
    "marketing",
    "solutions",
    "email",
    "global",
    "guide",
    "compare",
    "pricing",
    "overpaying",
    "adoption",
    "generative",
}

COMPETITOR_DOMAIN_STOPWORDS = {
    "www",
    "m",
    "news",
    "blog",
    "docs",
    "help",
    "support",
    "community",
    "forum",
    "developer",
    "developers",
    "reddit",
    "zhihu",
    "g2",
    "capterra",
    "producthunt",
    "github",
    "youtube",
    "twitter",
    "x",
    "bing",
    "google",
    "duckduckgo",
    "baidu",
    "weibo",
    "medium",
    "substack",
    "linkedin",
    "example",
}

DEFAULT_CATEGORY_SEARCH_INTENTS = {
    "market_trends": ("official", "analysis", "comparison"),
    "user_jobs_and_pains": ("community", "analysis", "official"),
    "competitor_landscape": ("official", "comparison", "community"),
    "product_experience_teardown": ("official", "comparison", "community"),
    "reviews_and_sentiment": ("community", "analysis", "comparison"),
    "pricing_and_business_model": ("pricing", "official", "comparison", "community"),
    "acquisition_and_distribution": ("analysis", "official", "community"),
    "opportunities_and_risks": ("analysis", "community", "comparison"),
    "recommendations": ("analysis", "comparison", "community"),
}

QUERY_INTENT_SOURCE_TYPES = {
    "official": ("documentation", "pricing", "web", "article"),
    "pricing": ("pricing", "documentation", "web", "article"),
    "community": ("review", "community", "article"),
    "comparison": ("review", "web", "article"),
    "analysis": ("article", "web", "documentation"),
}

SEARCH_WAVE_BLUEPRINTS = (
    ("anchor", "锚点扫描", ("official", "analysis")),
    ("validation", "外部验证", ("community", "comparison", "analysis")),
    ("gap_fill", "缺口补搜", ()),
)

SKILL_THEME_PROFILES: Dict[str, Dict[str, Any]] = {
    "market_intel": {
        "intent_bias": ("analysis", "official"),
        "required_query_tags": ("analysis", "official"),
        "priority_tags": ("analysis", "official"),
        "coverage_targets": {"analysis": 1, "official": 1},
        "preferred_domains": ("mckinsey.com", "gartner.com", "cbinsights.com"),
        "query_fragments": {
            "zh": ("市场规模 TAM SAM SOM", "趋势 报告 增长 adoption", "benchmark 案例 代表玩家"),
            "en": ("market size TAM SAM SOM", "trend report growth adoption", "benchmark case study leading players"),
        },
    },
    "voice_of_customer": {
        "intent_bias": ("community", "analysis"),
        "required_query_tags": ("community",),
        "priority_tags": ("community", "analysis"),
        "coverage_targets": {"community": 2},
        "preferred_domains": ("reddit.com", "g2.com", "capterra.com", "producthunt.com"),
        "query_fragments": {
            "zh": ("reddit 论坛 社区 讨论", "g2 capterra 评价 评论", "用户原声 痛点 抱怨 好评"),
            "en": ("reddit forum discussion", "g2 capterra reviews", "customer pain points complaints praise"),
        },
    },
    "competition": {
        "intent_bias": ("comparison", "official"),
        "required_query_tags": ("comparison", "official"),
        "priority_tags": ("comparison", "official"),
        "coverage_targets": {"comparison": 1, "official": 1},
        "preferred_domains": ("g2.com", "capterra.com", "github.com"),
        "query_fragments": {
            "zh": ("竞品 替代 对比 comparison", "vs alternatives competitor matrix", "定位 差异 细分"),
            "en": ("competitors alternatives comparison", "vs competitor matrix", "positioning differentiation segments"),
        },
    },
    "experience": {
        "intent_bias": ("official", "community", "comparison"),
        "required_query_tags": ("official", "community"),
        "priority_tags": ("official", "community"),
        "coverage_targets": {"official": 1, "community": 1},
        "preferred_domains": ("docs.", "help.", "support.", "youtube.com"),
        "query_fragments": {
            "zh": ("上手 onboarding walkthrough 教程", "文档 帮助中心 demo", "体验 摩擦 问题 评论"),
            "en": ("onboarding walkthrough tutorial", "docs help center demo", "friction issues review"),
        },
    },
    "pricing": {
        "intent_bias": ("official", "comparison", "community"),
        "required_query_tags": ("official", "comparison", "community"),
        "priority_tags": ("official", "comparison"),
        "coverage_targets": {"official": 1, "comparison": 1, "community": 1},
        "preferred_domains": ("pricing", "g2.com", "capterra.com"),
        "query_fragments": {
            "zh": ("定价 套餐 计费 席位 用量", "免费版 试用 企业版 年付 月付", "包装 value metric 性价比"),
            "en": ("pricing plans billing seat usage", "free trial enterprise annual monthly", "packaging value metric"),
        },
    },
    "channels": {
        "intent_bias": ("analysis", "official", "community"),
        "required_query_tags": ("analysis", "official"),
        "priority_tags": ("analysis", "official"),
        "coverage_targets": {"analysis": 1, "official": 1},
        "preferred_domains": ("linkedin.com", "youtube.com", "substack.com"),
        "query_fragments": {
            "zh": ("获客 渠道 分发 SEO 增长", "合作 生态 集成 marketplace", "推荐 裂变 增长循环"),
            "en": ("acquisition channels distribution SEO growth", "partnership ecosystem integrations marketplace", "referral growth loop"),
        },
    },
    "decision": {
        "intent_bias": ("analysis", "community", "comparison"),
        "required_query_tags": ("analysis", "community"),
        "priority_tags": ("analysis", "community"),
        "coverage_targets": {"analysis": 1, "community": 1},
        "preferred_domains": ("substack.com", "medium.com", "reddit.com"),
        "query_fragments": {
            "zh": ("机会 风险 约束", "执行 风险 误判 反例", "建议 优先级 决策"),
            "en": ("opportunity risk constraints", "execution risk anti-pattern counter example", "recommendation priority decision"),
        },
    },
}

SKILL_PACK_THEME_BY_ID: Dict[str, str] = {
    "market-sizing-lite": "market_intel",
    "trend-triangulation": "market_intel",
    "benchmark-scouting": "market_intel",
    "jtbd-extraction": "voice_of_customer",
    "pain-point-ranking": "voice_of_customer",
    "voice-snippet-capture": "voice_of_customer",
    "review-clustering": "voice_of_customer",
    "voice-of-customer": "voice_of_customer",
    "signal-polarity": "voice_of_customer",
    "competitive-mapping": "competition",
    "segment-layering": "competition",
    "positioning-diff": "competition",
    "feature-diffing": "competition",
    "flow-teardown": "experience",
    "friction-mapping": "experience",
    "pricing-benchmarking": "pricing",
    "packaging-analysis": "pricing",
    "value-metric-check": "pricing",
    "channel-diagnostics": "channels",
    "distribution-mapping": "channels",
    "growth-loop-check": "channels",
    "opportunity-ranking": "decision",
    "execution-risk-audit": "decision",
    "decision-briefing": "decision",
}

MAX_SEARCH_WAVES = 4


class ResearchWorkerAgent:
    LOW_SIGNAL_HOST_TOKENS = ("duckduckgo.com", "bing.com", "google.com", "googleadservices.com")
    LOW_SIGNAL_TITLE_TOKENS = ("advertisement", "sponsored", "登录", "注册", "下载", "打开app")
    LOW_SIGNAL_PATH_TOKENS = ("/tag/", "/topics/", "/topic/", "/categories/", "/login", "/signup", "/register", "/search")
    LISTICLE_TITLE_TOKENS = ("best ", "top ", "alternatives", "roundup", "大全", "合集", "盘点", "推荐")

    def __init__(self, llm_client: Optional[MiniMaxChatClient] = None) -> None:
        self.search_provider = DuckDuckGoSearchProvider()
        self.llm_client = llm_client

    def infer_market_step_from_question(self, question: str) -> str:
        normalized = question.lower()
        routing_rules = [
            (("competitor", "竞争", "竞品", "替代"), "competitor-analysis"),
            (("pricing", "price", "收费", "定价"), "business-and-channels"),
            (("user", "用户", "pain", "jtbd", "需求"), "user-research"),
            (("review", "评价", "口碑", "sentiment", "反馈"), "reviews-and-sentiment"),
            (("channel", "distribution", "获客", "渠道"), "business-and-channels"),
            (("risk", "constraint", "风险", "阻力"), "opportunities-and-risks"),
        ]
        for keywords, market_step in routing_rules:
            if any(keyword in normalized for keyword in keywords):
                return market_step
        return "recommendations"

    def build_delta_task(self, request: Dict[str, Any], question: str, delta_job_id: str) -> Dict[str, Any]:
        market_step = self.infer_market_step_from_question(question)
        return {
            "id": f"{delta_job_id}-task-1",
            "category": "opportunities_and_risks" if market_step == "recommendations" else market_step.replace("-", "_"),
            "title": f"PM 追问补充研究 · {question[:32]}",
            "brief": f"围绕追问“{question}”补充定向搜索、抓取和证据整理。",
            "market_step": market_step,
            "question": question,
            "status": "queued",
            "source_count": 0,
            "retry_count": 0,
            "latest_error": None,
        }

    def _search_strategy_for_task(self, task: Dict[str, Any]) -> Dict[str, tuple[str, ...]]:
        strategy_key = str(task.get("category") or task.get("market_step") or "").replace("-", "_")
        strategy_key = SEARCH_STRATEGY_ALIASES.get(strategy_key, strategy_key)
        return SEARCH_STRATEGIES.get(
            strategy_key,
            {
                "preferred_source_types": ("web", "article", "documentation"),
                "preferred_domains": (),
                "query_hints": ("market analysis", "customer feedback"),
            },
        )

    def _extract_query_terms(self, text: str) -> List[str]:
        terms: List[str] = []
        for token in re.findall(r"[a-z0-9][a-z0-9\-_/.]+|[\u4e00-\u9fff]{2,}", text.lower()):
            cleaned = token.strip()
            if not cleaned or cleaned in QUERY_STOPWORDS:
                continue
            if cleaned not in terms:
                terms.append(cleaned)
        return terms[:8]

    def _industry_query_anchor(self, request: Dict[str, Any]) -> str:
        industry_template = str(request.get("industry_template") or "").strip()
        return INDUSTRY_TEMPLATE_QUERY_HINTS.get(industry_template, industry_template.replace("_", " ").strip() or "market")

    def _looks_like_meta_topic(self, topic: str) -> bool:
        normalized = str(topic or "").lower()
        has_meta_hint = any(hint in normalized for hint in META_TOPIC_HINTS)
        has_context_hint = any(hint in normalized for hint in META_TOPIC_CONTEXT_HINTS)
        return has_meta_hint and has_context_hint

    def _search_topic_anchor(self, request: Dict[str, Any]) -> str:
        topic = str(request.get("topic") or "").strip()
        if not topic:
            return self._industry_query_anchor(request)
        if self._looks_like_meta_topic(topic):
            return self._industry_query_anchor(request)
        topic_terms = self._extract_query_terms(topic)
        return " ".join(topic_terms[:4]) or topic

    def _task_focus_terms(self, task: Dict[str, Any]) -> str:
        title_terms = self._extract_query_terms(str(task.get("title") or ""))
        brief_terms = self._extract_query_terms(str(task.get("brief") or ""))
        market_step_terms = self._extract_query_terms(str(task.get("market_step") or "").replace("-", " "))
        category_terms = self._extract_query_terms(str(task.get("category") or "").replace("_", " "))
        must_cover_terms = self._extract_query_terms(" ".join(str(item or "") for item in task.get("must_cover") or []))
        completion_terms = self._extract_query_terms(" ".join(str(item or "") for item in task.get("completion_criteria") or []))
        english_scaffold = bool(
            any(re.search(r"[a-z]", term) for term in market_step_terms)
            or any(re.search(r"[a-z]", term) for term in category_terms)
        )
        category_key = str(task.get("category") or task.get("market_step") or "").replace("-", "_")
        has_chinese_context = any(
            re.search(r"[\u4e00-\u9fff]", term)
            for term in title_terms + brief_terms + must_cover_terms + completion_terms
        )
        locale_key = "zh" if has_chinese_context else ("en" if english_scaffold else "en")
        category_focus_terms = self._extract_query_terms(CATEGORY_QUERY_FOCUS_HINTS.get(category_key, {}).get(locale_key, ""))
        if english_scaffold and not has_chinese_context:
            title_terms = [term for term in title_terms if not re.search(r"[\u4e00-\u9fff]", term)]
            brief_terms = [term for term in brief_terms if not re.search(r"[\u4e00-\u9fff]", term)]
            must_cover_terms = [term for term in must_cover_terms if not re.search(r"[\u4e00-\u9fff]", term)]
            completion_terms = [term for term in completion_terms if not re.search(r"[\u4e00-\u9fff]", term)]
        combined_terms: List[str] = []
        primary_buckets = (
            title_terms,
            market_step_terms,
            category_terms,
            category_focus_terms,
        )
        secondary_buckets = (
            must_cover_terms,
            completion_terms,
            brief_terms,
        )
        for bucket in primary_buckets:
            for term in bucket:
                if (
                    term in GENERIC_RELEVANCE_TOKENS
                    or term in META_TOPIC_HINTS
                    or term in TASK_FOCUS_STOPWORDS
                ):
                    continue
                if term not in combined_terms:
                    combined_terms.append(term)
                if len(combined_terms) >= 2:
                    break
            if len(combined_terms) >= 2:
                break
        if len(combined_terms) < 2:
            for bucket in secondary_buckets:
                for term in bucket:
                    if (
                        term in GENERIC_RELEVANCE_TOKENS
                        or term in META_TOPIC_HINTS
                        or term in TASK_FOCUS_STOPWORDS
                    ):
                        continue
                    if term not in combined_terms:
                        combined_terms.append(term)
        return " ".join(combined_terms[:4])

    def _topic_alias_terms(self, request: Dict[str, Any]) -> List[str]:
        topic = str(request.get("topic") or "").lower()
        aliases: List[str] = []
        for hint, expansions in TOPIC_ALIAS_HINTS.items():
            if hint not in topic:
                continue
            for expansion in expansions:
                cleaned = expansion.strip()
                if cleaned and cleaned not in aliases:
                    aliases.append(cleaned)
        if "ai" in topic and aliases:
            with_ai = []
            for alias in aliases:
                candidate = f"ai {alias}"
                if candidate not in with_ai:
                    with_ai.append(candidate)
            aliases = with_ai + aliases
        return aliases[:3]

    def _needs_global_query_mix(self, request: Dict[str, Any]) -> bool:
        geo_scope = " ".join(request.get("geo_scope") or []).lower()
        return any(token in geo_scope for token in ("美国", "us", "usa", "global", "海外", "international"))

    def _query_topic_anchors(self, request: Dict[str, Any]) -> List[str]:
        primary_anchor = self._search_topic_anchor(request)
        anchors = [primary_anchor] if primary_anchor else []
        topic = str(request.get("topic") or "")
        has_chinese_topic = bool(re.search(r"[\u4e00-\u9fff]", topic))
        prefer_alias_mix = has_chinese_topic or self._needs_global_query_mix(request)
        for alias in self._topic_alias_terms(request):
            if alias in anchors:
                continue
            if prefer_alias_mix or len(anchors) < 2:
                anchors.append(alias)
            if len(anchors) >= 3:
                break
        if not anchors:
            anchors.append(self._industry_query_anchor(request))
        return anchors[:3]

    def _domain_query_intent(
        self,
        strategy: Dict[str, tuple[str, ...]],
        pack: Dict[str, str],
        searchable_domains: List[str],
    ) -> str:
        if "docs" in strategy.get("query_lenses", ()):
            return pack.get("docs", "")
        if "pricing" in strategy.get("query_lenses", ()):
            return pack.get("pricing", "")
        if any(domain in {"g2.com", "capterra.com", "reddit.com"} for domain in searchable_domains):
            return pack.get("reviews", "")
        if "comparison" in strategy.get("query_lenses", ()):
            return pack.get("comparison", "")
        if "market" in strategy.get("query_lenses", ()):
            return pack.get("market", "")
        if "analysis" in strategy.get("query_lenses", ()):
            return pack.get("analysis", "")
        return pack.get("official", "")

    def _strong_topic_tokens(self, request: Dict[str, Any]) -> List[str]:
        topic_terms = [
            term
            for term in self._extract_query_terms(str(request.get("topic") or ""))
            if term not in GENERIC_RELEVANCE_TOKENS and term not in META_TOPIC_HINTS
        ]
        alias_terms = [
            term
            for term in self._extract_query_terms(" ".join(self._query_topic_anchors(request)))
            if term not in GENERIC_RELEVANCE_TOKENS and term not in META_TOPIC_HINTS
        ]
        topic_terms = self._merge_unique(topic_terms, alias_terms, limit=6)
        if topic_terms:
            return topic_terms[:6]
        industry_terms = [
            term
            for term in self._extract_query_terms(self._industry_query_anchor(request))
            if term not in GENERIC_RELEVANCE_TOKENS
        ]
        return industry_terms[:3]

    def _task_relevance_tokens(self, request: Dict[str, Any], task: Dict[str, Any]) -> List[str]:
        del request
        raw_terms = self._extract_query_terms(
            " ".join(
                [
                    str(task.get("title") or ""),
                    str(task.get("brief") or ""),
                    str(task.get("question") or ""),
                    str(task.get("market_step") or "").replace("-", " "),
                    str(task.get("category") or "").replace("_", " "),
                ]
            )
        )
        task_terms = [
            term
            for term in raw_terms
            if term not in GENERIC_RELEVANCE_TOKENS and term not in META_TOPIC_HINTS and len(term) >= 2
        ]
        return task_terms[:6]

    def _topic_relevance_assessment(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        title: str,
        source_url: str,
        source_text: str,
        snippet: str,
    ) -> Dict[str, Any]:
        strong_topic_tokens = self._strong_topic_tokens(request)
        task_tokens = self._task_relevance_tokens(request, task)
        industry_tokens = [
            term
            for term in self._extract_query_terms(self._industry_query_anchor(request))
            if term not in GENERIC_RELEVANCE_TOKENS
        ][:3]
        headline_text = f"{title} {source_url}".lower()
        full_text = f"{title} {source_url} {snippet} {source_text}".lower()
        topic_hits = sum(1 for token in strong_topic_tokens if token in full_text)
        headline_topic_hits = sum(1 for token in strong_topic_tokens if token in headline_text)
        task_hits = sum(1 for token in task_tokens if token in full_text)
        industry_hits = sum(1 for token in industry_tokens if token in full_text)
        market_step = str(task.get("market_step") or "")
        is_strict_step = market_step in STRICT_TOPIC_RELEVANCE_STEPS
        if not strong_topic_tokens and not task_tokens and not industry_tokens:
            return {
                "keep": True,
                "reason": "insufficient-anchor",
                "topic_hits": 0,
                "task_hits": 0,
                "industry_hits": 0,
            }
        keep = True
        reason = ""

        if is_strict_step and strong_topic_tokens and topic_hits == 0 and headline_topic_hits == 0:
            keep = False
            reason = "strict-topic-miss"
        elif topic_hits == 0 and headline_topic_hits == 0 and task_hits == 0 and industry_hits == 0:
            keep = False
            reason = "no-relevance-signal"
        elif is_strict_step and strong_topic_tokens and topic_hits == 0 and task_hits < 2 and industry_hits == 0:
            keep = False
            reason = "weak-topic-signal"

        return {
            "keep": keep,
            "reason": reason,
            "topic_hits": topic_hits + headline_topic_hits,
            "task_hits": task_hits,
            "industry_hits": industry_hits,
        }

    def _prefers_chinese_queries(self, request: Dict[str, Any]) -> bool:
        topic = str(request.get("topic") or "")
        if bool(re.search(r"[\u4e00-\u9fff]", topic)):
            return True
        if bool(re.search(r"[a-zA-Z]", topic)):
            return False
        output_locale = str(request.get("output_locale") or request.get("language") or "").lower()
        geo_scope = " ".join(request.get("geo_scope") or [])
        return bool(re.search(r"[\u4e00-\u9fff]", f"{topic} {geo_scope}")) or output_locale.startswith("zh")

    def _query_geo_hint(self, request: Dict[str, Any]) -> str:
        prefer_chinese = self._prefers_chinese_queries(request)
        locale_key = "zh" if prefer_chinese else "en"
        hints: List[str] = []
        for item in request.get("geo_scope") or []:
            cleaned = str(item or "").strip()
            if not cleaned:
                continue
            normalized = cleaned.lower()
            mapped = GEO_QUERY_HINTS.get(normalized)
            if mapped is None:
                for key, values in GEO_QUERY_HINTS.items():
                    if key in normalized or normalized in key:
                        mapped = values
                        break
            hint = mapped[locale_key] if mapped else cleaned
            if not prefer_chinese and re.search(r"[\u4e00-\u9fff]", hint):
                continue
            if hint and hint not in hints:
                hints.append(hint)
        return " ".join(hints[:2]).strip()

    def _english_geo_hint(self, request: Dict[str, Any]) -> str:
        hints: List[str] = []
        for item in request.get("geo_scope") or []:
            cleaned = str(item or "").strip()
            if not cleaned:
                continue
            normalized = cleaned.lower()
            mapped = GEO_QUERY_HINTS.get(normalized)
            if mapped is None:
                for key, values in GEO_QUERY_HINTS.items():
                    if key in normalized or normalized in key:
                        mapped = values
                        break
            hint = mapped["en"] if mapped else ENGLISH_GEO_HINTS.get(cleaned, cleaned)
            if not hint or re.search(r"[\u4e00-\u9fff]", hint):
                continue
            if hint not in hints:
                hints.append(hint)
        return " ".join(hints[:2]).strip()

    def _query_anchor_prefers_english(self, topic_anchor: str) -> bool:
        anchor = str(topic_anchor or "")
        return bool(re.search(r"[a-zA-Z]", anchor)) and not bool(re.search(r"[\u4e00-\u9fff]", anchor))

    def _topic_seed_queries(self, request: Dict[str, Any]) -> List[str]:
        topic = str(request.get("topic") or "")
        anchors = self._query_topic_anchors(request)
        english_aliases = [anchor for anchor in anchors if self._query_anchor_prefers_english(anchor)]
        localized_anchors = [anchor for anchor in anchors if anchor not in english_aliases]
        ordered_anchors = anchors
        if bool(re.search(r"[\u4e00-\u9fff]", topic)) and english_aliases:
            ordered_anchors = [*english_aliases[:1], *localized_anchors[:1]]
        elif ordered_anchors:
            ordered_anchors = ordered_anchors[:1]

        seeds: List[str] = []
        for anchor in ordered_anchors:
            cleaned = self._normalize_query(anchor)
            if cleaned and cleaned not in seeds:
                seeds.append(cleaned)
        return seeds[:2]

    def _query_anchor_profiles(self, request: Dict[str, Any], task: Dict[str, Any], limit: int = 2) -> List[Dict[str, Any]]:
        default_pack = self._query_phrase_pack(request)
        task_focus = self._task_focus_terms(task) or str(task.get("category") or "").replace("_", " ")
        geo_hint = self._query_geo_hint(request)
        english_geo_hint = self._english_geo_hint(request)
        anchors = self._query_topic_anchors(request)
        english_aliases = [anchor for anchor in anchors if self._query_anchor_prefers_english(anchor)]
        localized_anchors = [anchor for anchor in anchors if anchor not in english_aliases]
        ordered_anchors = [*english_aliases[:1], *localized_anchors[:1], *anchors]
        profiles: List[Dict[str, Any]] = []
        for anchor in ordered_anchors:
            cleaned_anchor = self._normalize_query(anchor)
            if not cleaned_anchor or any(item["anchor"] == cleaned_anchor for item in profiles):
                continue
            prefers_english = self._query_anchor_prefers_english(cleaned_anchor)
            profiles.append(
                {
                    "anchor": cleaned_anchor,
                    "pack": QUERY_PHRASE_PACKS["en"] if prefers_english else default_pack,
                    "focus": self._focus_terms_for_anchor(task, cleaned_anchor, task_focus),
                    "geo_hint": english_geo_hint if prefers_english else geo_hint,
                    "prefers_english": prefers_english,
                }
            )
            if len(profiles) >= max(1, limit):
                break
        return profiles

    def _focus_terms_for_anchor(self, task: Dict[str, Any], anchor: str, default_focus: str) -> str:
        if not self._query_anchor_prefers_english(anchor):
            return default_focus
        category_key = str(task.get("category") or task.get("market_step") or "").replace("-", "_")
        english_focus = CATEGORY_QUERY_FOCUS_HINTS.get(category_key, {}).get("en", "")
        if english_focus:
            return english_focus
        if re.search(r"[\u4e00-\u9fff]", default_focus):
            return ""
        return default_focus

    def _topic_exemplar_entities(self, request: Dict[str, Any]) -> List[str]:
        topic = str(request.get("topic") or "").lower()
        entities: List[str] = []
        for record in self._topic_exemplar_records(request):
            name = str(record.get("name") or "").strip()
            if name and name not in entities:
                entities.append(name)
        for hint, names in TOPIC_EXEMPLAR_HINTS.items():
            if hint not in topic:
                continue
            for name in names:
                cleaned = str(name or "").strip()
                if cleaned and cleaned not in entities:
                    entities.append(cleaned)
        return entities[:3]

    def _topic_exemplar_records(self, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        topic = str(request.get("topic") or "").lower()
        records: List[Dict[str, Any]] = []
        seen = set()
        for hint, candidates in TOPIC_EXEMPLAR_RECORDS.items():
            if hint not in topic:
                continue
            for candidate in candidates:
                name = str(candidate.get("name") or "").strip()
                signal = self._normalize_phrase_signal(name)
                if not signal or signal in seen:
                    continue
                records.append(
                    {
                        "name": name,
                        "domains": tuple(candidate.get("domains") or ()),
                        "query_terms": tuple(candidate.get("query_terms") or ()),
                        "source_url": str(candidate.get("source_url") or "").strip() or None,
                    }
                )
                seen.add(signal)
        return records[:6]

    def _topic_review_domains(self, request: Dict[str, Any]) -> List[str]:
        topic = str(request.get("topic") or "").lower()
        domains: List[str] = []
        for hint, candidates in TOPIC_REVIEW_DOMAINS.items():
            if hint not in topic:
                continue
            for domain in candidates:
                cleaned = str(domain or "").strip().lower()
                if cleaned and cleaned not in domains:
                    domains.append(cleaned)
        return domains[:4]

    def _topic_is_physical_product(self, request: Optional[Dict[str, Any]]) -> bool:
        topic = str((request or {}).get("topic") or "").lower()
        return any(hint in topic for hint in PHYSICAL_PRODUCT_TOPIC_HINTS)

    def _topic_exemplar_domains(self, request: Optional[Dict[str, Any]]) -> List[str]:
        domains: List[str] = []
        for record in self._topic_exemplar_records(request or {}):
            for domain in record.get("domains") or ():
                cleaned = str(domain or "").strip().lower()
                if cleaned.startswith("www."):
                    cleaned = cleaned[4:]
                if cleaned and cleaned not in domains:
                    domains.append(cleaned)
        return domains[:6]

    def _effective_preferred_domains(
        self,
        request: Optional[Dict[str, Any]],
        task: Dict[str, Any],
        strategy: Dict[str, tuple[str, ...]],
        limit: int = 6,
    ) -> List[str]:
        strategy_domains = self._searchable_preferred_domains(strategy)
        skill_domains = self._skill_preferred_domains(task)
        if not self._topic_is_physical_product(request):
            return self._merge_unique(skill_domains, strategy_domains, limit=limit)

        filtered_strategy_domains = [
            domain
            for domain in strategy_domains
            if domain not in PHYSICAL_PRODUCT_LOW_SIGNAL_DOMAINS and domain not in {"substack.com", "medium.com", "techcrunch.com", "hubspot.com"}
        ]
        filtered_skill_domains = [
            domain
            for domain in skill_domains
            if domain not in PHYSICAL_PRODUCT_LOW_SIGNAL_DOMAINS and domain not in {"substack.com", "medium.com", "linkedin.com", "hubspot.com"}
        ]
        return self._merge_unique(
            self._topic_exemplar_domains(request),
            self._topic_review_domains(request or {}),
            filtered_skill_domains,
            filtered_strategy_domains,
            limit=limit,
        )

    def _normalize_competitor_name(self, value: Any) -> str:
        name = re.sub(r"\s+", " ", str(value or "").strip())
        name = re.sub(r"^[,.;:：;、/|+\-]+|[,.;:：;、/|+\-]+$", "", name).strip()
        name = re.sub(r"^(?:vs\.?|versus)\s+", "", name, flags=re.IGNORECASE).strip()
        if not name or len(name) < 2 or len(name) > 48:
            return ""
        if re.fullmatch(r"[0-9.\-_/ ]+", name):
            return ""
        normalized = self._normalize_phrase_signal(name)
        if not normalized:
            return ""
        if normalized in COMPETITOR_NAME_STOPWORDS:
            return ""
        terms = self._extract_query_terms(name)
        if not terms:
            return ""
        if all(term in COMPETITOR_NAME_STOPWORDS for term in terms):
            return ""
        if len(terms) == 1:
            token = terms[0]
            if token in COMPETITOR_NAME_STOPWORDS:
                return ""
            if re.fullmatch(r"[a-z]{1,3}", token) and not re.fullmatch(r"[A-Z0-9]{2,6}", name):
                return ""
        return name

    def _merge_competitor_names(self, *groups: Any, limit: int = 8) -> List[str]:
        merged: List[str] = []
        seen = set()
        for group in groups:
            if not group:
                continue
            for item in group:
                raw = item
                if isinstance(item, dict):
                    raw = item.get("competitor_name") or item.get("name") or item.get("brand")
                candidate = self._normalize_competitor_name(raw)
                if not candidate:
                    continue
                candidate_key = self._normalize_phrase_signal(candidate)
                if candidate_key and candidate_key not in seen:
                    merged.append(candidate)
                    seen.add(candidate_key)
                if len(merged) >= limit:
                    return merged
        return merged

    def _known_competitor_names(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        competitor_names: Optional[List[str]] = None,
    ) -> List[str]:
        task_candidates: List[Any] = []
        for key in ("competitor_names", "known_competitor_names", "validated_competitors", "competitors"):
            value = task.get(key)
            if isinstance(value, list):
                task_candidates.extend(value)
        return self._merge_competitor_names(competitor_names or [], task_candidates, self._topic_exemplar_entities(request), limit=8)

    def _candidate_matches_topic(self, request: Dict[str, Any], candidate: str) -> bool:
        topic_terms = set(
            self._extract_query_terms(" ".join([str(request.get("topic") or ""), *self._query_topic_anchors(request)]))
        )
        candidate_terms = set(self._extract_query_terms(candidate))
        return bool(topic_terms and candidate_terms and candidate_terms.issubset(topic_terms))

    def _has_competitor_context(self, task: Dict[str, Any], query: str, title: str, summary: str) -> bool:
        market_step = str(task.get("market_step") or "").strip().lower()
        category = str(task.get("category") or "").replace("-", "_")
        if market_step in COMPETITOR_FOCUS_MARKET_STEPS:
            return True
        if category in {"competitor_landscape", "pricing_and_business_model"}:
            return True
        combined = self._normalize_phrase_signal(" ".join(part for part in (query, title, summary) if part))
        return any(token in combined for token in COMPETITOR_SIGNAL_TOKENS)

    def _extract_domain_competitor_candidate(self, source_url: str) -> str:
        host = self._source_domain(source_url)
        if not host:
            return ""
        segments = [segment for segment in host.split(".") if segment]
        if len(segments) < 2:
            return ""
        root = segments[-2]
        if root in {"co", "com", "net", "org", "gov", "edu"} and len(segments) >= 3:
            root = segments[-3]
        if root in COMPETITOR_DOMAIN_STOPWORDS or len(root) < 3:
            return ""
        return self._normalize_competitor_name(root.replace("-", " "))

    def _extract_competitor_candidates_from_text(self, text: str) -> List[str]:
        if not text:
            return []
        candidates: List[str] = []
        candidate_keys = set()

        def append_candidate(raw: Any) -> None:
            candidate = self._normalize_competitor_name(raw)
            if not candidate:
                return
            key = self._normalize_phrase_signal(candidate)
            if not key or key in candidate_keys:
                return
            candidates.append(candidate)
            candidate_keys.add(key)

        for match in re.findall(
            r"(?i)(?:vs\.?|versus|对比|比较|竞品|替代|alternatives?|competitors?)[:：]?\s*([^\n。；;|]{3,120})",
            text,
        ):
            for part in re.split(r"(?:、|，|,|/|\\|\||;|；|与|和|及|以及|\s+vs\.?\s+|\s+versus\s+)", str(match)):
                append_candidate(part)

        for match in re.findall(r"\b[A-Z][A-Za-z0-9]*(?:[- ][A-Z0-9][A-Za-z0-9]*){0,3}\b", text):
            append_candidate(match)

        for match in re.findall(r"(?i)(?:vs\.?|versus|alternatives?|competitors?)\s+([a-z][a-z0-9\-]{2,24})", text):
            append_candidate(match)

        for match in re.findall(r"([\u4e00-\u9fff]{2,8})(?:\s*(?:AI|ai)\s*)?(?:眼镜|耳机|手机|产品|平台|系统|品牌)", text):
            append_candidate(match)

        return candidates[:10]

    def _infer_competitor_name(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        title: str,
        summary: str,
        quote: str,
        source_url: str,
        query: str = "",
        competitor_names: Optional[List[str]] = None,
    ) -> Optional[str]:
        known_names = self._known_competitor_names(request, task, competitor_names)
        combined_text = " ".join(part for part in (title, summary, quote, query) if part)
        if not combined_text:
            return None

        has_context = self._has_competitor_context(task, query, title, summary)
        if not has_context and not known_names:
            return None

        normalized_title = self._normalize_phrase_signal(title)
        normalized_combined = self._normalize_phrase_signal(combined_text)
        normalized_query = self._normalize_phrase_signal(query)
        scores: Dict[str, float] = {}

        def score_candidate(name: str, score: float) -> None:
            if not name:
                return
            current = float(scores.get(name, 0.0) or 0.0)
            if score > current:
                scores[name] = score

        known_by_signal: Dict[str, str] = {
            self._normalize_phrase_signal(name): name
            for name in known_names
            if self._normalize_phrase_signal(name)
        }
        for known_name in known_names:
            signal = self._normalize_phrase_signal(known_name)
            if not signal or signal not in normalized_combined:
                continue
            score = 5.0
            if signal in normalized_title:
                score += 1.4
            if normalized_query and signal in normalized_query:
                score += 0.6
            score_candidate(known_name, score)

        extracted_candidates = self._extract_competitor_candidates_from_text(combined_text)
        domain_candidate = self._extract_domain_competitor_candidate(source_url)
        if domain_candidate:
            extracted_candidates.append(domain_candidate)

        for extracted in extracted_candidates:
            signal = self._normalize_phrase_signal(extracted)
            if not signal or signal in COMPETITOR_NAME_STOPWORDS:
                continue
            canonical = known_by_signal.get(signal, extracted)
            if self._candidate_matches_topic(request, canonical):
                continue
            score = 0.0
            if signal in normalized_combined:
                score += 2.6
            if signal in normalized_title:
                score += 1.8
            if normalized_query and signal in normalized_query:
                score += 0.7
            if source_url and signal.replace(" ", "") in self._normalize_phrase_signal(source_url):
                score += 0.6
            if signal in known_by_signal:
                score += 2.2
            elif any(signal in key or key in signal for key in known_by_signal):
                score += 1.4
            if re.search(r"[A-Z]", canonical) or "-" in canonical:
                score += 0.5
            if score >= 2.8:
                score_candidate(canonical, score)

        if not scores:
            return None
        best_name, best_score = max(scores.items(), key=lambda item: item[1])
        minimum_score = 3.0 if (has_context or known_names) else 4.2
        if best_score < minimum_score:
            return None
        return best_name

    def _query_mentions_known_competitors(self, query: str, competitor_names: List[str]) -> bool:
        query_signal = self._normalize_phrase_signal(query)
        if not query_signal:
            return False
        for name in competitor_names:
            name_signal = self._normalize_phrase_signal(name)
            if name_signal and name_signal in query_signal:
                return True
        return False

    def _competitor_query_expansions(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        competitor_names: Optional[List[str]],
    ) -> List[str]:
        known_names = self._known_competitor_names(request, task, competitor_names)
        if not known_names:
            return []

        market_step = str(task.get("market_step") or "").strip().lower()
        category = str(task.get("category") or "").replace("-", "_")
        if market_step not in COMPETITOR_FOCUS_MARKET_STEPS and category not in {"competitor_landscape", "pricing_and_business_model"}:
            return []

        topic_anchor = self._search_topic_anchor(request)
        pack = self._query_phrase_pack(request)
        zh_geo_hint = self._query_geo_hint(request)
        en_geo_hint = self._english_geo_hint(request)
        exemplar_record_by_signal = {
            self._normalize_phrase_signal(str(record.get("name") or "")): record
            for record in self._topic_exemplar_records(request)
            if self._normalize_phrase_signal(str(record.get("name") or ""))
        }
        expanded_queries: List[str] = []
        for name in known_names[:2]:
            name_prefers_english = self._query_anchor_prefers_english(name)
            geo_hint = en_geo_hint if name_prefers_english else zh_geo_hint
            exemplar_record = exemplar_record_by_signal.get(self._normalize_phrase_signal(name)) or {}
            for query_term in exemplar_record.get("query_terms") or ():
                normalized_query_term = self._normalize_query(query_term)
                if normalized_query_term and normalized_query_term not in expanded_queries:
                    expanded_queries.append(normalized_query_term)
            comparison_query = self._normalize_query(
                " ".join(part for part in (topic_anchor, name, pack.get("comparison", "comparison"), geo_hint) if part).strip()
            )
            official_query = self._normalize_query(
                " ".join(part for part in (name, pack.get("official", "official")) if part).strip()
            )
            pricing_query = self._normalize_query(
                " ".join(part for part in (name, pack.get("pricing", "pricing")) if part).strip()
            )
            query_order = [comparison_query, official_query]
            if market_step == "business-and-channels" or category == "pricing_and_business_model":
                query_order.insert(1, pricing_query)
            for query in query_order:
                if query and query not in expanded_queries:
                    expanded_queries.append(query)
        return expanded_queries[:4]

    def _ensure_competitor_anchor_query(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        queries: List[str],
        candidate_queries: List[str],
        competitor_names: Optional[List[str]],
    ) -> List[str]:
        known_names = self._known_competitor_names(request, task, competitor_names)
        if not known_names:
            return list(queries)
        market_step = str(task.get("market_step") or "").strip().lower()
        category = str(task.get("category") or "").replace("-", "_")
        if market_step not in COMPETITOR_FOCUS_MARKET_STEPS and category not in {"competitor_landscape", "pricing_and_business_model"}:
            return list(queries)
        next_queries = [query for query in queries if query]
        if any(self._query_mentions_known_competitors(query, known_names) for query in next_queries):
            return next_queries

        candidate = next(
            (
                query
                for query in candidate_queries
                if query and query not in next_queries and self._query_mentions_known_competitors(query, known_names)
            ),
            "",
        )
        if not candidate:
            return next_queries
        if len(next_queries) >= 6:
            next_queries[-1] = candidate
        else:
            next_queries.append(candidate)
        deduped: List[str] = []
        for query in next_queries:
            if query not in deduped:
                deduped.append(query)
        return deduped[:6]

    def _build_exemplar_queries(self, request: Dict[str, Any], task: Dict[str, Any]) -> List[str]:
        entities = self._topic_exemplar_entities(request)
        if not entities:
            return []
        exemplar_records = self._topic_exemplar_records(request)
        anchors = self._query_topic_anchors(request)
        english_anchor = next((anchor for anchor in anchors if self._query_anchor_prefers_english(anchor)), "")
        product_phrase = english_anchor or "ai product"
        category = str(task.get("category") or task.get("market_step") or "").replace("-", "_")
        required_tags = set(self._required_query_coverage(task))
        analysis_entity = entities[1] if len(entities) > 1 else entities[0]
        queries: List[str] = []
        if category == "competitor_landscape" and exemplar_records:
            for record in exemplar_records[:4]:
                for query_term in record.get("query_terms") or ():
                    queries.append(self._normalize_query(query_term))
                    break
        if category == "market_trends":
            analysis_phrase = "market trends benchmark report"
        elif category in {"user_jobs_and_pains", "reviews_and_sentiment"}:
            analysis_phrase = "user review feedback pain points"
        else:
            analysis_phrase = "market launch"

        if "official" in required_tags or category in {"market_trends", "competitor_landscape", "product_experience_teardown"}:
            queries.append(self._normalize_query(f"{entities[0]} {product_phrase} official product overview"))
        if "analysis" in required_tags or category in {"market_trends", "opportunities_and_risks", "recommendations"}:
            queries.append(self._normalize_query(f"{analysis_entity} {product_phrase} {analysis_phrase}"))
        if "community" in required_tags or category in {"user_jobs_and_pains", "reviews_and_sentiment"}:
            queries.append(self._normalize_query(f"{analysis_entity} {product_phrase} review"))
        if "comparison" in required_tags and len(entities) > 1:
            queries.append(self._normalize_query(f"{entities[0]} {entities[1]} {product_phrase} comparison"))

        deduped: List[str] = []
        for query in queries:
            if query and query not in deduped:
                deduped.append(query)
        return deduped[:4]

    def _query_phrase_for_tag(self, pack: Dict[str, str], tag: str) -> str:
        if tag == "official":
            return pack.get("official") or pack.get("docs", "")
        if tag == "analysis":
            return pack.get("market") or pack.get("analysis", "")
        if tag == "community":
            return pack.get("community") or pack.get("reviews", "")
        if tag == "comparison":
            return pack.get("comparison", "")
        if tag == "pricing":
            return pack.get("pricing", "")
        return pack.get("analysis", "")

    def _topic_anchor_has_pricing_intent(self, topic_anchor: str) -> bool:
        lowered = str(topic_anchor or "").lower()
        return any(token in lowered for token in ("pricing", "price", "plan", "plans", "billing", "定价", "套餐", "计费", "价格"))

    def _build_direct_topic_queries(self, request: Dict[str, Any], task: Dict[str, Any]) -> List[str]:
        default_pack = self._query_phrase_pack(request)
        english_pack = QUERY_PHRASE_PACKS["en"]
        topic_anchors = self._query_topic_anchors(request)
        topic_anchor = topic_anchors[0] if topic_anchors else self._search_topic_anchor(request)
        geo_hint = self._query_geo_hint(request)
        english_geo_hint = self._english_geo_hint(request)
        target_tags = self._merge_unique(self._required_query_coverage(task), self._task_search_intents(task), limit=4)
        queries: List[str] = []
        for index, anchor in enumerate(topic_anchors[:3] or [topic_anchor]):
            anchor_prefers_english = self._query_anchor_prefers_english(anchor)
            pack = english_pack if anchor_prefers_english else default_pack
            anchor_geo_hint = english_geo_hint if anchor_prefers_english else geo_hint
            per_anchor_tags = list(target_tags[:2] if index > 0 else target_tags)
            base_query = self._normalize_query(anchor)
            if base_query and base_query not in queries:
                queries.append(base_query)
            for tag in per_anchor_tags:
                phrase = self._query_phrase_for_tag(pack, tag)
                if tag == "pricing" and self._topic_anchor_has_pricing_intent(anchor):
                    phrase = ""
                if tag == "pricing":
                    query_geo_hint = ""
                elif tag == "official":
                    query_geo_hint = anchor_geo_hint if anchor_prefers_english else ""
                else:
                    query_geo_hint = anchor_geo_hint
                query = self._normalize_query(" ".join(part for part in (anchor, phrase, query_geo_hint) if part).strip())
                if query and query not in queries:
                    queries.append(query)
        if geo_hint:
            regional_query = self._normalize_query(" ".join(part for part in (topic_anchor, geo_hint) if part).strip())
            if regional_query and regional_query not in queries:
                queries.append(regional_query)
        return queries[:7]

    def _query_phrase_pack(self, request: Dict[str, Any]) -> Dict[str, str]:
        return QUERY_PHRASE_PACKS["zh" if self._prefers_chinese_queries(request) else "en"]

    def _search_domain_label(self, domain: str) -> str:
        normalized = str(domain or "").strip().lower()
        if not normalized:
            return ""
        if normalized in SEARCH_DOMAIN_LABELS:
            return SEARCH_DOMAIN_LABELS[normalized]
        parts = [part for part in normalized.split(".") if part]
        if len(parts) >= 2:
            return parts[-2].replace("-", " ")
        return normalized.replace("-", " ")

    def _compact_retry_phrase(self, prefers_english: bool, tag: str, site_domain: str = "") -> str:
        locale_key = "en" if prefers_english else "zh"
        pack = QUERY_RETRY_PHRASE_PACKS[locale_key]
        normalized_domain = str(site_domain or "").strip().lower()
        domain_label = self._search_domain_label(normalized_domain)
        if tag == "community":
            if normalized_domain == "reddit.com":
                return "reddit reviews" if prefers_english else "reddit 讨论"
            if normalized_domain in {"g2.com", "capterra.com", "producthunt.com"}:
                return f"{domain_label} {pack['reviews']}".strip()
            return pack["community"]
        if tag == "official":
            return pack["official"]
        if tag == "pricing":
            return pack["pricing"]
        if tag == "comparison":
            return pack["comparison"]
        if tag == "market":
            return pack["market"]
        if tag == "docs":
            return pack["docs"]
        return pack["analysis"]

    def _build_zero_result_retry_queries(self, request: Dict[str, Any], task: Dict[str, Any], query: str) -> List[str]:
        normalized_query = self._normalize_query(query)
        anchor_profiles = self._query_anchor_profiles(request, task, limit=2)
        if not anchor_profiles:
            topic_anchor = self._search_topic_anchor(request)
            anchor_profiles = [
                {
                    "anchor": topic_anchor,
                    "prefers_english": self._query_anchor_prefers_english(topic_anchor),
                    "geo_hint": self._english_geo_hint(request) if self._query_anchor_prefers_english(topic_anchor) else self._query_geo_hint(request),
                }
            ]

        query_tags = self._query_coverage_tags(query) or self._task_search_intents(task)
        ordered_tags = [tag for tag in ("community", "pricing", "official", "comparison", "analysis") if tag in query_tags]
        if not ordered_tags:
            ordered_tags = ["analysis"]
        site_domains = self._query_site_domains(query)
        site_domain = site_domains[0] if site_domains else ""
        site_is_soft_constraint = site_domain in SITE_QUERY_EXCLUDED_DOMAINS
        lowered_query = str(query or "").lower()
        if site_is_soft_constraint and "official" in ordered_tags:
            explicit_official_signal = any(token in lowered_query for token in ("official", "官网", "docs", "文档", "help", "support"))
            if not explicit_official_signal:
                ordered_tags = [tag for tag in ordered_tags if tag != "official"]
                if not ordered_tags:
                    ordered_tags = ["community", "analysis"]
        candidates: List[str] = []

        for profile in anchor_profiles:
            anchor = str(profile.get("anchor") or "").strip()
            if not anchor:
                continue
            prefers_english = bool(profile.get("prefers_english"))
            geo_hint = str(profile.get("geo_hint") or "").strip()
            domain_label = self._search_domain_label(site_domain)
            for tag in ordered_tags[:2]:
                compact_phrase = self._compact_retry_phrase(prefers_english, tag, site_domain=site_domain)
                generic_query = self._normalize_query(" ".join(part for part in (anchor, compact_phrase, geo_hint) if part).strip())
                site_query = self._normalize_query(f"site:{site_domain} {anchor} {compact_phrase}".strip()) if site_domain else ""
                named_domain_query = ""
                if site_domain and domain_label and domain_label not in compact_phrase.lower():
                    named_domain_query = self._normalize_query(
                        " ".join(part for part in (domain_label, anchor, compact_phrase, geo_hint) if part).strip()
                    )
                ordered_candidates = (
                    [generic_query, named_domain_query, site_query]
                    if site_is_soft_constraint
                    else [site_query, named_domain_query, generic_query]
                )
                for candidate in ordered_candidates:
                    if candidate:
                        candidates.append(candidate)
            if "analysis" not in ordered_tags:
                analysis_query = self._normalize_query(
                    " ".join(
                        part
                        for part in (
                            anchor,
                            self._compact_retry_phrase(prefers_english, "analysis", site_domain=site_domain),
                            geo_hint,
                        )
                        if part
                    ).strip()
                )
                if analysis_query:
                    candidates.append(analysis_query)

        deduped_candidates: List[str] = []
        for candidate in candidates:
            if not candidate or candidate == normalized_query or candidate in deduped_candidates:
                continue
            deduped_candidates.append(candidate)
        ranked_candidates = self._rank_queries_for_task(task, deduped_candidates, request=request)
        if "community" in ordered_tags:
            ranked_candidates = self._merge_unique(
                [
                    candidate
                    for candidate in ranked_candidates
                    if "community" in self._query_coverage_tags(candidate) and not candidate.startswith("site:")
                ],
                [
                    candidate
                    for candidate in ranked_candidates
                    if "community" in self._query_coverage_tags(candidate) and candidate.startswith("site:")
                ],
                [
                    candidate
                    for candidate in ranked_candidates
                    if "community" not in self._query_coverage_tags(candidate) and not candidate.startswith("site:")
                ],
                [
                    candidate
                    for candidate in ranked_candidates
                    if "community" not in self._query_coverage_tags(candidate) and candidate.startswith("site:")
                ],
                limit=len(ranked_candidates) or 3,
            )
        elif site_is_soft_constraint:
            ranked_candidates = self._merge_unique(
                [candidate for candidate in ranked_candidates if not candidate.startswith("site:")],
                [candidate for candidate in ranked_candidates if candidate.startswith("site:")],
                limit=len(ranked_candidates) or 3,
            )
        prioritized_candidates = self._ensure_alias_anchor_query(task, request, ranked_candidates[:3], ranked_candidates)
        return prioritized_candidates[:3]

    def _searchable_preferred_domains(self, strategy: Dict[str, tuple[str, ...]]) -> List[str]:
        domains: List[str] = []
        for domain in strategy.get("preferred_domains", ()):
            cleaned = str(domain or "").strip().lower()
            if "." not in cleaned or cleaned.endswith("."):
                continue
            if cleaned in SITE_QUERY_EXCLUDED_DOMAINS:
                continue
            if cleaned not in domains:
                domains.append(cleaned)
        return domains[:3]

    def _build_strategy_queries(self, request: Dict[str, Any], task: Dict[str, Any], strategy: Dict[str, tuple[str, ...]]) -> List[str]:
        pack = self._query_phrase_pack(request)
        topic_anchors = self._query_topic_anchors(request)
        topic_anchor = topic_anchors[0]
        industry_anchor = self._industry_query_anchor(request)
        task_focus = self._task_focus_terms(task) or task["category"].replace("_", " ")
        geo_hint = self._query_geo_hint(request)
        primary_focus = self._focus_terms_for_anchor(task, topic_anchor, task_focus)
        category_key = str(task.get("category") or task.get("market_step") or "").replace("-", "_")
        query_candidates: List[str] = []

        for lens in strategy.get("query_lenses", ()):
            lens_phrase = pack.get(lens, "")
            if not lens_phrase:
                continue
            focus_terms = primary_focus
            if category_key == "pricing_and_business_model" and lens in {"pricing", "official"}:
                focus_terms = ""
            query_candidates.append(" ".join(part for part in (topic_anchor, focus_terms, lens_phrase, geo_hint) if part).strip())

        query_hints = strategy.get("query_hints", ())
        if query_hints:
            query_candidates.append(" ".join(part for part in (topic_anchor, query_hints[0], geo_hint) if part).strip())
        if len(query_hints) > 1:
            query_candidates.append(" ".join(part for part in (topic_anchor, query_hints[1], geo_hint) if part).strip())
            query_candidates.append(" ".join(part for part in (industry_anchor, task_focus, query_hints[1]) if part).strip())

        searchable_domains = self._effective_preferred_domains(request, task, strategy)
        domain_intent = self._domain_query_intent(strategy, pack, searchable_domains)
        for domain in searchable_domains[:2]:
            query_candidates.append(" ".join(part for part in (f"site:{domain}", topic_anchor, domain_intent, primary_focus) if part).strip())

        alias_anchor = topic_anchors[1] if len(topic_anchors) > 1 else ""
        if alias_anchor:
            alias_pack = QUERY_PHRASE_PACKS["en"] if self._query_anchor_prefers_english(alias_anchor) else pack
            alias_focus = self._focus_terms_for_anchor(task, alias_anchor, task_focus)
            alias_geo_hint = self._english_geo_hint(request) if self._query_anchor_prefers_english(alias_anchor) else geo_hint
            alias_lens_order = [
                alias_pack.get("comparison", ""),
                alias_pack.get("reviews", ""),
                alias_pack.get("market", ""),
                alias_pack.get("docs", ""),
            ]
            for alias_lens in alias_lens_order:
                if not alias_lens:
                    continue
                query_candidates.append(" ".join(part for part in (alias_anchor, alias_focus, alias_lens, alias_geo_hint) if part).strip())
                if len(query_candidates) >= 10:
                    break

        deduped_queries: List[str] = []
        for query in query_candidates:
            cleaned_query = self._normalize_query(query)
            if cleaned_query and cleaned_query not in deduped_queries:
                deduped_queries.append(cleaned_query)
        return deduped_queries[:10]

    def _normalize_query(self, query: str) -> str:
        normalized = " ".join(str(query or "").replace("，", " ").replace(",", " ").split())
        if not normalized:
            return ""
        if len(normalized) > 120 or any(phrase in normalized.lower() for phrase in LOW_SIGNAL_QUERY_PHRASES):
            terms = self._extract_query_terms(normalized)
            normalized = " ".join(terms[:8])
        return normalized[:120].strip()

    def _build_delta_queries(self, request: Dict[str, Any], task: Dict[str, Any], strategy: Dict[str, tuple[str, ...]]) -> List[str]:
        question = str(task.get("question") or "")
        topic_anchor = self._search_topic_anchor(request)
        pack = self._query_phrase_pack(request)
        question_terms = self._extract_query_terms(question)
        english_terms = [term for term in question_terms if re.search(r"[a-z]", term)]
        chinese_terms = [term for term in question_terms if re.search(r"[\u4e00-\u9fff]", term)]
        focus_terms = " ".join((english_terms[:4] or chinese_terms[:3]))
        lowered_question = question.lower()
        enterprise_hint = "enterprise b2b" if ("enterprise" in lowered_question or "企业" in question) else ""
        pricing_hint = ""
        if any(token in lowered_question for token in ("pricing", "price", "seat", "usage")) or any(
            token in question for token in ("定价", "席位", "用量", "混合")
        ):
            pricing_hint = "pricing seat usage hybrid saas"
        if pricing_hint:
            query_candidates = [
                f"{topic_anchor} pricing {focus_terms} {enterprise_hint}".strip(),
                "enterprise saas pricing seat based vs usage based hybrid",
                "b2b ai product pricing model seats usage enterprise",
            ]
        else:
            query_candidates = [
                f"{topic_anchor} {focus_terms} {enterprise_hint}".strip(),
                f"{topic_anchor} {strategy['query_hints'][0]} {enterprise_hint}".strip(),
                f"{enterprise_hint or topic_anchor} {strategy['query_hints'][1]} {focus_terms}".strip(),
            ]
        for domain in self._effective_preferred_domains(request, task, strategy)[:2]:
            query_candidates.append(f"site:{domain} {topic_anchor} {focus_terms or pack['analysis']}".strip())
        deduped_queries: List[str] = []
        for query in query_candidates:
            cleaned_query = self._normalize_query(" ".join(query.split()))
            if cleaned_query and cleaned_query not in deduped_queries:
                deduped_queries.append(cleaned_query)
        return deduped_queries[:5]

    def _build_fallback_queries(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        competitor_names: Optional[List[str]] = None,
    ) -> List[str]:
        strategy = self._search_strategy_for_task(task)
        if task.get("question"):
            return self._build_delta_queries(request, task, strategy)
        known_competitor_names = self._known_competitor_names(request, task, competitor_names)
        strategy_queries = self._build_strategy_queries(request, task, strategy)
        skill_queries = self._build_skill_queries(request, task, strategy)
        direct_queries = self._build_direct_topic_queries(request, task)
        exemplar_queries = self._build_exemplar_queries(request, task)
        competitor_queries = self._competitor_query_expansions(request, task, known_competitor_names)
        seed_queries = self._topic_seed_queries(request)
        if not self._prefers_chinese_queries(request):
            official_seed = next((query for query in direct_queries if "official" in query.lower()), None)
            if official_seed and official_seed not in seed_queries:
                seed_queries.append(official_seed)
        topic_anchor = self._search_topic_anchor(request)
        industry_anchor = self._industry_query_anchor(request)
        keyword_candidates = [term for term in top_keywords(topic_anchor, limit=3) if term not in META_TOPIC_HINTS]
        primary_keyword = keyword_candidates[0] if keyword_candidates else industry_anchor
        combined_queries = list(seed_queries)
        for query in direct_queries:
            if query not in combined_queries:
                combined_queries.append(query)
        for query in exemplar_queries:
            if query not in combined_queries:
                combined_queries.append(query)
        for query in competitor_queries:
            if query not in combined_queries:
                combined_queries.append(query)
        for query in strategy_queries:
            if query not in combined_queries:
                combined_queries.append(query)
        for query in skill_queries:
            if query not in combined_queries:
                combined_queries.append(query)
        for query in (
            f"{primary_keyword} {industry_anchor} {strategy['query_hints'][0]}".strip(),
            f"{topic_anchor} {strategy['query_hints'][1]}".strip(),
        ):
            cleaned_query = self._normalize_query(query)
            if cleaned_query and cleaned_query not in combined_queries:
                combined_queries.append(cleaned_query)
        frontload_queries = self._merge_unique(seed_queries[:2], competitor_queries[:1], exemplar_queries[:1], direct_queries[:2], limit=5)
        ranked_queries = self._frontload_seed_queries(task, combined_queries, frontload_queries, request=request)
        category_key = str(task.get("category") or task.get("market_step") or "").replace("-", "_")
        if category_key == "pricing_and_business_model":
            prioritized_queries: List[str] = []
            for query in [*seed_queries, *exemplar_queries, *direct_queries, *ranked_queries]:
                if query and query not in prioritized_queries:
                    prioritized_queries.append(query)
            final_queries = self._ensure_query_coverage(task, prioritized_queries[:6], combined_queries, seed_queries=frontload_queries)
        else:
            final_queries = self._ensure_query_coverage(task, ranked_queries[:6] or combined_queries, combined_queries, seed_queries=frontload_queries)
        final_queries = self._ensure_site_anchor_query(task, request, final_queries, combined_queries)
        final_queries = self._ensure_alias_anchor_query(task, request, final_queries, combined_queries)
        return self._ensure_competitor_anchor_query(
            request,
            task,
            final_queries,
            self._merge_unique(competitor_queries, combined_queries, limit=12),
            known_competitor_names,
        )

    def _query_has_explicit_official_signal(self, query: str) -> bool:
        lowered = str(query or "").lower()
        return any(token in lowered for token in OFFICIAL_QUERY_SIGNAL_TOKENS)

    def _query_coverage_tags(self, query: str) -> List[str]:
        lowered = str(query or "").lower()
        site_domains = self._query_site_domains(query)
        soft_site_only = bool(site_domains) and all(domain in SITE_QUERY_EXCLUDED_DOMAINS for domain in site_domains)
        tags: List[str] = []
        for tag, patterns in QUERY_COVERAGE_PATTERNS.items():
            if any(pattern in lowered for pattern in patterns):
                if tag == "official" and soft_site_only and not self._query_has_explicit_official_signal(query):
                    continue
                tags.append(tag)
        if site_domains and not soft_site_only and "official" not in tags:
            tags.append("official")
        return tags

    def _combined_query_coverage_tags(self, *queries: str) -> List[str]:
        return self._merge_unique(*(self._query_coverage_tags(query) for query in queries), limit=5)

    def _coverage_tags_from_source(self, source_type: str, *text_fragments: Any) -> List[str]:
        tags = list(SOURCE_TYPE_COVERAGE_TAGS.get(str(source_type or "").strip().lower(), ()))
        combined_text = " ".join(str(fragment or "").strip().lower() for fragment in text_fragments if str(fragment or "").strip())
        if combined_text:
            for tag, patterns in QUERY_COVERAGE_PATTERNS.items():
                if any(pattern in combined_text for pattern in patterns) and tag not in tags:
                    tags.append(tag)
        return self._dedupe_tags(tags)

    def _coverage_tags_for_result(
        self,
        query: str,
        source_type: str,
        source_url: str,
        title: str,
        snippet: str,
        analysis: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        analysis_payload = analysis or {}
        return self._dedupe_tags(
            [
                *self._query_coverage_tags(query),
                *(analysis_payload.get("tags") or []),
                *self._coverage_tags_from_source(
                    source_type,
                    source_url,
                    title,
                    snippet,
                    analysis_payload.get("summary"),
                    analysis_payload.get("quote"),
                ),
            ]
        )

    def _host_matches_domains(self, host: str, domains: set[str]) -> bool:
        cleaned_host = str(host or "").strip().lower()
        if not cleaned_host:
            return False
        return any(cleaned_host == domain or cleaned_host.endswith(f".{domain}") for domain in domains)

    def _evidence_coverage_tags(self, item: Dict[str, Any]) -> List[str]:
        explicit_tags = [tag for tag in (item.get("tags") or []) if tag in QUERY_COVERAGE_PATTERNS]
        source_url = str(item.get("source_url") or "")
        host = self._source_domain(source_url)
        source_type = str(item.get("source_type") or "").strip().lower()
        combined_text = " ".join(
            str(item.get(field) or "")
            for field in ("title", "summary", "quote", "extracted_fact", "source_url")
        )
        inferred_tags = list(self._query_coverage_tags(combined_text))
        inferred_tags.extend(SOURCE_TYPE_COVERAGE_TAGS.get(source_type, ()))
        if self._host_matches_domains(host, SITE_QUERY_EXCLUDED_DOMAINS):
            inferred_tags.append("community")
        if host.startswith(("docs.", "help.", "support.", "developers.")):
            inferred_tags.append("official")

        return self._dedupe_tags(explicit_tags + inferred_tags)

    def _required_query_coverage(self, task: Dict[str, Any]) -> tuple[str, ...]:
        category = str(task.get("category") or task.get("market_step") or "").replace("-", "_")
        base_required = list(TASK_REQUIRED_QUERY_COVERAGE.get(category, ("official", "analysis")))
        return tuple(self._merge_unique(base_required, self._skill_extra_required_coverage(task), limit=4))

    def _discouraged_query_coverage(self, task: Dict[str, Any]) -> tuple[str, ...]:
        category = str(task.get("category") or task.get("market_step") or "").replace("-", "_")
        return TASK_DISCOURAGED_QUERY_COVERAGE.get(category, ())

    def _sanitize_string_list(self, value: Any, fallback: tuple[str, ...], limit: int = 6) -> List[str]:
        if not isinstance(value, list):
            return list(fallback)
        cleaned: List[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned or list(fallback)

    def _task_skill_packs(self, task: Dict[str, Any]) -> List[str]:
        return self._sanitize_string_list(task.get("skill_packs"), (), limit=8)

    def _task_skill_themes(self, task: Dict[str, Any]) -> List[str]:
        themes: List[str] = []
        for pack in self._task_skill_packs(task):
            theme = SKILL_PACK_THEME_BY_ID.get(pack)
            if theme and theme not in themes:
                themes.append(theme)
        return themes

    def _skill_theme_profiles(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [SKILL_THEME_PROFILES[theme] for theme in self._task_skill_themes(task) if theme in SKILL_THEME_PROFILES]

    def _merge_unique(self, *groups: Any, limit: int = 8) -> List[str]:
        merged: List[str] = []
        for group in groups:
            if not group:
                continue
            for item in group:
                cleaned = str(item or "").strip()
                if cleaned and cleaned not in merged:
                    merged.append(cleaned)
                if len(merged) >= limit:
                    return merged
        return merged

    def _skill_extra_required_coverage(self, task: Dict[str, Any]) -> List[str]:
        return self._merge_unique(*(profile.get("required_query_tags", ()) for profile in self._skill_theme_profiles(task)), limit=4)

    def _skill_priority_tags(self, task: Dict[str, Any]) -> List[str]:
        return self._merge_unique(*(profile.get("priority_tags", ()) for profile in self._skill_theme_profiles(task)), limit=4)

    def _skill_intent_bias(self, task: Dict[str, Any]) -> List[str]:
        return self._merge_unique(*(profile.get("intent_bias", ()) for profile in self._skill_theme_profiles(task)), limit=4)

    def _skill_coverage_targets(self, task: Dict[str, Any]) -> Dict[str, int]:
        targets: Dict[str, int] = {}
        for profile in self._skill_theme_profiles(task):
            for tag, value in dict(profile.get("coverage_targets") or {}).items():
                targets[str(tag)] = max(targets.get(str(tag), 0), int(value))
        return targets

    def _skill_runtime_summary(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill_packs": self._task_skill_packs(task),
            "skill_themes": self._task_skill_themes(task),
            "priority_tags": self._skill_priority_tags(task),
            "coverage_targets": self._skill_coverage_targets(task),
        }

    def _skill_query_fragments(self, request: Dict[str, Any], task: Dict[str, Any]) -> List[str]:
        locale_key = "zh" if self._prefers_chinese_queries(request) else "en"
        fragments: List[str] = []
        for profile in self._skill_theme_profiles(task):
            for fragment in profile.get("query_fragments", {}).get(locale_key, ()):
                if fragment not in fragments:
                    fragments.append(fragment)
        return fragments[:6]

    def _skill_preferred_domains(self, task: Dict[str, Any]) -> List[str]:
        domains: List[str] = []
        for profile in self._skill_theme_profiles(task):
            for domain in profile.get("preferred_domains", ()):
                cleaned = str(domain or "").strip().lower()
                if "." not in cleaned or cleaned.endswith("."):
                    continue
                if cleaned and cleaned not in domains:
                    domains.append(cleaned)
        return domains[:4]

    def _build_skill_queries(self, request: Dict[str, Any], task: Dict[str, Any], strategy: Dict[str, tuple[str, ...]]) -> List[str]:
        topic_anchor = self._search_topic_anchor(request)
        task_focus = self._task_focus_terms(task) or str(task.get("category") or "").replace("_", " ")
        geo_hint = self._query_geo_hint(request)
        fragments = self._skill_query_fragments(request, task)
        candidates: List[str] = []
        for fragment in fragments[:3]:
            candidates.append(self._normalize_query(" ".join(part for part in (topic_anchor, task_focus, fragment, geo_hint) if part).strip()))
        domain_hint = fragments[0] if fragments else self._query_phrase_pack(request).get("analysis", "analysis")
        preferred_domains = self._effective_preferred_domains(request, task, strategy, limit=4)
        for domain in preferred_domains[:2]:
            candidates.append(self._normalize_query(f"site:{domain} {topic_anchor} {domain_hint} {task_focus}".strip()))
        return [query for query in candidates if query]

    def _task_search_intents(self, task: Dict[str, Any]) -> List[str]:
        category = str(task.get("category") or task.get("market_step") or "").replace("-", "_")
        fallback = DEFAULT_CATEGORY_SEARCH_INTENTS.get(category, ("official", "analysis", "community"))
        raw_intents = self._sanitize_string_list(task.get("search_intents"), fallback, limit=4)
        return self._merge_unique(self._skill_intent_bias(task), raw_intents, limit=4)

    def _query_site_domains(self, query: str) -> List[str]:
        domains: List[str] = []
        for match in re.findall(r"site:([a-z0-9][a-z0-9.-]+\.[a-z]{2,})", str(query or "").lower()):
            domain = match.strip().strip(".")
            if domain and domain not in domains:
                domains.append(domain)
        return domains

    def _host_matches_site_domains(self, host: str, site_domains: List[str]) -> bool:
        normalized_host = str(host or "").strip().lower()
        return any(normalized_host == domain or normalized_host.endswith(f".{domain}") for domain in site_domains)

    def _runtime_retrieval_profile(self, request: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        runtime_config = (request or {}).get("runtime_config") or {}
        retrieval_profile = runtime_config.get("retrieval_profile") or {}
        return retrieval_profile if isinstance(retrieval_profile, dict) else {}

    def _runtime_official_domains(self, request: Optional[Dict[str, Any]]) -> List[str]:
        domains: List[str] = []
        for item in (self._runtime_retrieval_profile(request).get("official_domains") or []):
            cleaned = str(item or "").strip().lower()
            if cleaned.startswith("www."):
                cleaned = cleaned[4:]
            if cleaned and cleaned not in domains:
                domains.append(cleaned)
        for cleaned in self._topic_exemplar_domains(request):
            if cleaned and cleaned not in domains:
                domains.append(cleaned)
        return domains[:8]

    def _runtime_negative_keywords(self, request: Optional[Dict[str, Any]]) -> List[str]:
        keywords: List[str] = []
        for item in (self._runtime_retrieval_profile(request).get("negative_keywords") or []):
            cleaned = str(item or "").strip()
            if cleaned and cleaned not in keywords:
                keywords.append(cleaned)
        return keywords[:12]

    def _normalize_phrase_signal(self, value: Any) -> str:
        normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", str(value or "").lower())
        return " ".join(normalized.split())

    def _negative_keyword_match(self, request: Optional[Dict[str, Any]], result: Dict[str, Any]) -> Optional[str]:
        negative_keywords = self._runtime_negative_keywords(request)
        if not negative_keywords:
            return None

        parsed = urlparse(str(result.get("url") or "").strip())
        haystack = self._normalize_phrase_signal(
            " ".join(
                part
                for part in (
                    result.get("title"),
                    result.get("snippet"),
                    parsed.netloc,
                    parsed.path,
                    parsed.query,
                )
                if str(part or "").strip()
            )
        )
        if not haystack:
            return None

        for keyword in negative_keywords:
            normalized_keyword = self._normalize_phrase_signal(keyword)
            if normalized_keyword and normalized_keyword in haystack:
                return keyword
        return None

    def _prefers_runtime_official_domains(self, query_tags: List[str], request: Optional[Dict[str, Any]]) -> bool:
        retrieval_profile = self._runtime_retrieval_profile(request)
        official_source_bias = bool(retrieval_profile.get("official_source_bias", True))
        if not official_source_bias:
            return False
        return bool({"official", "pricing"}.intersection(set(query_tags)))

    def _pipeline_entity_terms(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        queries: Optional[List[str]] = None,
        competitor_names: Optional[List[str]] = None,
    ) -> List[str]:
        query_terms = [
            token
            for query in (queries or [])
            for token in self._extract_query_terms(query)
            if len(str(token or "").strip()) >= 2 and str(token or "").strip().lower() not in QUERY_STOPWORDS
        ]
        return self._merge_unique(
            self._task_alias_tokens(request, task, competitor_names),
            query_terms,
            self._known_competitor_names(request, task, competitor_names),
            limit=10,
        )

    def _build_round_pipeline(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        queries: List[str],
        competitor_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        retrieval_profile = self._runtime_retrieval_profile(request)
        return {
            "retrieval_profile_id": str(retrieval_profile.get("profile_id") or "").strip() or None,
            "entity_terms": self._pipeline_entity_terms(request, task, queries, competitor_names),
            "official_domains": self._runtime_official_domains(request),
            "negative_keywords": self._runtime_negative_keywords(request),
            "planned_query_count": len(queries),
            "recalled_result_count": 0,
            "reranked_result_count": 0,
            "fetch_attempt_count": 0,
            "extracted_page_count": 0,
            "normalized_evidence_count": 0,
            "official_hit_count": 0,
            "negative_keyword_block_count": 0,
        }

    def _increment_round_pipeline(self, round_record: Dict[str, Any], key: str, amount: int = 1) -> None:
        pipeline = round_record.setdefault("pipeline", {})
        pipeline[key] = int(pipeline.get(key, 0) or 0) + amount

    def _is_runtime_official_hit(self, request: Dict[str, Any], source_url: str) -> bool:
        source_domain = self._source_domain(source_url)
        return any(
            source_domain == domain or source_domain.endswith(f".{domain}")
            for domain in self._runtime_official_domains(request)
        )

    def _merge_source_type_preferences(self, *groups: tuple[str, ...]) -> tuple[str, ...]:
        merged: List[str] = []
        for group in groups:
            for item in group:
                cleaned = str(item or "").strip()
                if cleaned and cleaned not in merged:
                    merged.append(cleaned)
        return tuple(merged)

    def _query_search_preferences(
        self,
        query: str,
        strategy: Dict[str, tuple[str, ...]],
        task: Dict[str, Any],
        request: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, tuple[str, ...]]:
        query_tags = self._query_coverage_tags(query) or self._task_search_intents(task)
        intent_source_types = tuple(
            source_type
            for tag in query_tags[:2]
            for source_type in QUERY_INTENT_SOURCE_TYPES.get(tag, ())
        )
        preferred_domains: List[str] = []
        strategy_domains = self._effective_preferred_domains(request, task, strategy)
        for domain in [*self._query_site_domains(query), *strategy_domains]:
            cleaned = str(domain or "").strip().lower()
            if cleaned and cleaned not in preferred_domains:
                preferred_domains.append(cleaned)
        if self._prefers_runtime_official_domains(query_tags, request):
            preferred_domains = self._merge_unique(preferred_domains, self._runtime_official_domains(request), limit=8)
        return {
            "preferred_source_types": self._merge_source_type_preferences(intent_source_types, strategy.get("preferred_source_types", ())),
            "preferred_domains": tuple(preferred_domains),
        }

    def _merge_search_preferences(self, *groups: Dict[str, tuple[str, ...]]) -> Dict[str, tuple[str, ...]]:
        preferred_source_types: tuple[str, ...] = ()
        preferred_domains: List[str] = []
        for group in groups:
            preferred_source_types = self._merge_source_type_preferences(
                preferred_source_types,
                tuple(group.get("preferred_source_types") or ()),
            )
            preferred_domains = self._merge_unique(preferred_domains, tuple(group.get("preferred_domains") or ()), limit=8)
        return {
            "preferred_source_types": preferred_source_types,
            "preferred_domains": tuple(preferred_domains),
        }

    def _build_search_waves(self, task: Dict[str, Any], queries: List[str]) -> List[Dict[str, Any]]:
        anchor_queries: List[str] = []
        validation_queries: List[str] = []
        expansion_queries: List[str] = []
        task_intents = set(self._task_search_intents(task))
        frontload_tags = set(self._skill_priority_tags(task)[:1])
        for query in queries:
            tags = set(self._query_coverage_tags(query))
            if frontload_tags and tags.intersection(frontload_tags):
                anchor_queries.append(query)
                continue
            if tags.intersection({"community", "comparison"}):
                validation_queries.append(query)
                continue
            if not tags or tags.intersection({"official", "analysis", "pricing"}):
                anchor_queries.append(query)
                continue
            if tags.intersection(task_intents):
                validation_queries.append(query)
                continue
            expansion_queries.append(query)

        def prioritize_wave_queries(items: List[str], highlight_tags: List[str], preserve_first_query: bool = False) -> List[str]:
            if not items:
                return []
            lead = items[:1] if preserve_first_query else []
            tail = items[1:] if preserve_first_query else list(items)
            highlight_set = {str(tag or "").strip() for tag in highlight_tags if str(tag or "").strip()}
            if lead and highlight_set and not set(self._query_coverage_tags(lead[0])).intersection(highlight_set):
                tail = list(lead) + tail
                lead = []
            highlighted = [query for query in tail if set(self._query_coverage_tags(query)).intersection(highlight_set)]
            remaining = [query for query in tail if query not in highlighted]
            return self._merge_unique(
                lead,
                self._rank_queries_for_task(task, highlighted),
                self._rank_queries_for_task(task, remaining),
                limit=max(1, len(items)),
            )

        waves: List[Dict[str, Any]] = []
        required_tags = self._merge_unique(self._required_query_coverage(task), self._skill_priority_tags(task), limit=4)
        if anchor_queries:
            ordered_anchor_queries = prioritize_wave_queries(
                anchor_queries,
                highlight_tags=required_tags or list(frontload_tags),
                preserve_first_query=True,
            )
            waves.append({"key": "anchor", "label": "锚点扫描", "queries": ordered_anchor_queries[:3]})
        used_queries = {item for wave in waves for item in wave["queries"]}
        if validation_queries or expansion_queries:
            validation_candidates = [query for query in (validation_queries + expansion_queries) if query not in used_queries]
            ordered_validation_queries = prioritize_wave_queries(
                validation_candidates,
                highlight_tags=self._merge_unique(self._skill_priority_tags(task), ["community", "comparison", "analysis"], limit=4),
            )
            if ordered_validation_queries:
                waves.append({"key": "validation", "label": "外部验证", "queries": ordered_validation_queries[:3]})
        remaining_queries = [query for query in queries if query not in {item for wave in waves for item in wave["queries"]}]
        if remaining_queries:
            waves.append({"key": "expansion", "label": "扩展补证", "queries": remaining_queries[:2]})
        return waves[:3] or [{"key": "anchor", "label": "锚点扫描", "queries": queries[:3]}]

    def _dedupe_tags(self, tags: List[str]) -> List[str]:
        deduped: List[str] = []
        for item in tags:
            cleaned = str(item or "").strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)
        return deduped

    def _build_coverage_snapshot(self, task: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        covered_query_tags = set()
        query_tag_counts: Dict[str, int] = {}
        unique_domains = set()
        source_types = set()
        high_confidence_count = 0
        primary_source_count = 0
        for item in evidence:
            source_url = str(item.get("source_url") or "")
            host = urlparse(source_url).netloc.lower()
            if host:
                unique_domains.add(host)
            source_type = str(item.get("source_type") or "").strip()
            if source_type:
                source_types.add(source_type)
            if float(item.get("confidence", 0) or 0) >= 0.72:
                high_confidence_count += 1
            if source_type in {"documentation", "pricing", "web"}:
                primary_source_count += 1
            for tag in self._evidence_coverage_tags(item):
                if tag in QUERY_COVERAGE_PATTERNS:
                    covered_query_tags.add(tag)
                    query_tag_counts[tag] = query_tag_counts.get(tag, 0) + 1
        required_query_tags = list(self._required_query_coverage(task))
        skill_coverage_targets = self._skill_coverage_targets(task)
        return {
            "required_query_tags": required_query_tags,
            "covered_query_tags": sorted(covered_query_tags),
            "missing_required": [tag for tag in required_query_tags if tag not in covered_query_tags],
            "query_tag_counts": query_tag_counts,
            "skill_coverage_targets": skill_coverage_targets,
            "missing_skill_targets": {
                tag: target - int(query_tag_counts.get(tag, 0))
                for tag, target in skill_coverage_targets.items()
                if int(query_tag_counts.get(tag, 0)) < target
            },
            "unique_domains": len(unique_domains),
            "source_types": sorted(source_types),
            "evidence_count": len(evidence),
            "high_confidence_evidence": high_confidence_count,
            "primary_source_evidence": primary_source_count,
        }

    def build_task_coverage_status(self, task: Dict[str, Any], evidence: List[Dict[str, Any]], target_sources: int) -> Dict[str, Any]:
        snapshot = self._build_coverage_snapshot(task, evidence)
        gaps = self._coverage_gaps(task, snapshot, target_sources)
        skill_runtime = task.get("skill_runtime")
        if not isinstance(skill_runtime, dict):
            skill_runtime = self._skill_runtime_summary(task)
        return {
            "required_query_tags": snapshot["required_query_tags"],
            "covered_query_tags": snapshot["covered_query_tags"],
            "missing_required": gaps["missing_required"],
            "query_tag_counts": snapshot.get("query_tag_counts", {}),
            "skill_runtime_active": bool(skill_runtime.get("skill_packs")),
            "skill_themes": list(skill_runtime.get("skill_themes") or []),
            "skill_coverage_targets": snapshot.get("skill_coverage_targets", {}),
            "missing_skill_targets": gaps.get("missing_skill_targets", {}),
            "unique_domains": snapshot["unique_domains"],
            "high_confidence_evidence": snapshot["high_confidence_evidence"],
            "target_sources": target_sources,
        }

    def _coverage_gaps(self, task: Dict[str, Any], snapshot: Dict[str, Any], target_sources: int) -> Dict[str, Any]:
        required_tags = list(snapshot.get("required_query_tags") or self._required_query_coverage(task))
        missing_required = [tag for tag in required_tags if tag not in set(snapshot.get("covered_query_tags") or [])]
        missing_skill_targets = dict(snapshot.get("missing_skill_targets") or {})
        return {
            "missing_required": missing_required,
            "missing_skill_targets": missing_skill_targets,
            "needs_more_diversity": int(snapshot.get("unique_domains", 0)) < min(3, max(2, target_sources)),
            "needs_stronger_evidence": int(snapshot.get("high_confidence_evidence", 0)) < min(2, max(1, target_sources)),
            "needs_primary_source": "official" in required_tags and int(snapshot.get("primary_source_evidence", 0)) == 0,
            "evidence_shortfall": max(0, target_sources - int(snapshot.get("evidence_count", 0))),
        }

    def _research_is_sufficient(self, task: Dict[str, Any], snapshot: Dict[str, Any], target_sources: int) -> bool:
        gaps = self._coverage_gaps(task, snapshot, target_sources)
        if gaps["missing_required"] or gaps["missing_skill_targets"]:
            return False
        if gaps["needs_primary_source"] or gaps["needs_more_diversity"] or gaps["needs_stronger_evidence"]:
            return False
        return int(snapshot.get("evidence_count", 0)) >= target_sources

    def _build_gap_fill_queries(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        snapshot: Dict[str, Any],
        existing_queries: List[str],
        competitor_names: Optional[List[str]] = None,
    ) -> List[str]:
        strategy = self._search_strategy_for_task(task)
        pack = self._query_phrase_pack(request)
        known_competitor_names = self._known_competitor_names(request, task, competitor_names)
        anchor_profiles = self._query_anchor_profiles(request, task, limit=2)
        if not anchor_profiles:
            anchor_profiles = [
                {
                    "anchor": self._normalize_query(self._search_topic_anchor(request)),
                    "pack": pack,
                    "focus": self._task_focus_terms(task) or str(task.get("category") or "").replace("_", " "),
                    "geo_hint": self._query_geo_hint(request),
                    "prefers_english": False,
                }
            ]
        primary_anchor = str(anchor_profiles[0]["anchor"] or "")
        primary_pack = anchor_profiles[0]["pack"]
        primary_focus = str(anchor_profiles[0]["focus"] or "")
        primary_geo_hint = str(anchor_profiles[0]["geo_hint"] or "")
        missing_required = list(snapshot.get("missing_required") or [])
        missing_skill_targets = dict(snapshot.get("missing_skill_targets") or {})
        fallback_queries = self._build_fallback_queries(request, task, known_competitor_names)
        competitor_queries = self._competitor_query_expansions(request, task, known_competitor_names)
        candidates: List[str] = []
        missing_tags = self._merge_unique(missing_required, missing_skill_targets.keys(), limit=4)

        if int(snapshot.get("evidence_count", 0)) == 0:
            candidates.extend(self._build_convergence_queries(request, task, existing_queries, missing_tags, known_competitor_names))
        candidates.extend(competitor_queries)

        for tag in missing_tags:
            for anchor_profile in anchor_profiles:
                anchor = str(anchor_profile["anchor"] or "")
                anchor_pack = anchor_profile["pack"]
                anchor_focus = str(anchor_profile["focus"] or "")
                anchor_geo_hint = str(anchor_profile["geo_hint"] or "")
                lens = anchor_pack.get(tag if tag in anchor_pack else "analysis", anchor_pack.get("analysis", "analysis"))
                if not lens:
                    continue
                focus_terms = "" if tag in {"official", "pricing"} else anchor_focus
                query_geo_hint = "" if tag == "pricing" else anchor_geo_hint
                direct_query = self._normalize_query(" ".join(part for part in (anchor, focus_terms, lens, query_geo_hint) if part).strip())
                if direct_query:
                    candidates.append(direct_query)
            if tag == "official":
                for domain in self._effective_preferred_domains(request, task, strategy)[:2]:
                    for anchor_profile in anchor_profiles:
                        anchor = str(anchor_profile["anchor"] or "")
                        anchor_pack = anchor_profile["pack"]
                        candidates.append(self._normalize_query(f"site:{domain} {anchor} {anchor_pack.get('official', '')}".strip()))
            if tag == "community":
                for domain in self._effective_preferred_domains(request, task, strategy)[:2]:
                    if "." in domain:
                        for anchor_profile in anchor_profiles:
                            anchor = str(anchor_profile["anchor"] or "")
                            anchor_pack = anchor_profile["pack"]
                            candidates.append(self._normalize_query(f"site:{domain} {anchor} {anchor_pack.get('community', anchor_pack.get('reviews', 'reviews'))}".strip()))
            if tag == "comparison":
                for anchor_profile in anchor_profiles:
                    anchor = str(anchor_profile["anchor"] or "")
                    anchor_pack = anchor_profile["pack"]
                    anchor_focus = str(anchor_profile["focus"] or "")
                    candidates.append(self._normalize_query(f"{anchor} {anchor_focus} {anchor_pack.get('comparison', '')}".strip()))

        if int(snapshot.get("unique_domains", 0)) < 3:
            alias_terms = self._topic_alias_terms(request)
            if alias_terms:
                candidates.append(self._normalize_query(f"{alias_terms[0]} {pack.get('analysis', '')} benchmark case study".strip()))
        if int(snapshot.get("high_confidence_evidence", 0)) == 0:
            analysis_profile = next((profile for profile in anchor_profiles if profile.get("prefers_english")), anchor_profiles[0])
            analysis_pack = analysis_profile["pack"]
            candidates.append(
                self._normalize_query(
                    " ".join(
                        part
                        for part in (
                            str(analysis_profile["anchor"] or ""),
                            str(analysis_profile["focus"] or ""),
                            analysis_pack.get("analysis", analysis_pack.get("market", "analysis")),
                            str(analysis_profile["geo_hint"] or ""),
                        )
                        if part
                    ).strip()
                )
            )

        for query in fallback_queries:
            if query in existing_queries:
                continue
            if missing_tags and not any(tag in self._query_coverage_tags(query) for tag in missing_tags):
                continue
            candidates.append(query)

        gap_fill_queries: List[str] = []
        ranked_candidates = self._rank_queries_for_task(task, [query for query in candidates if query], request=request)
        for query in ranked_candidates:
            if not query or query in existing_queries or query in gap_fill_queries:
                continue
            gap_fill_queries.append(query)
            if len(gap_fill_queries) >= 3:
                break
        for tag in missing_tags:
            if any(tag in self._query_coverage_tags(query) for query in gap_fill_queries):
                continue
            backfill_query = next(
                (
                    query
                    for query in ranked_candidates
                    if query not in gap_fill_queries and tag in self._query_coverage_tags(query)
                ),
                None,
            )
            if not backfill_query:
                continue
            if len(gap_fill_queries) >= 3:
                gap_fill_queries[-1] = backfill_query
            else:
                gap_fill_queries.append(backfill_query)
        if "community" in missing_tags:
            community_hint_tokens = ("reddit", "reviews", "社区", "论坛", "评价")
            combined_queries = " || ".join(gap_fill_queries).lower()
            if not any(token in combined_queries for token in community_hint_tokens):
                community_query = self._normalize_query(
                    f"{primary_anchor} {primary_focus} {primary_pack.get('community', primary_pack.get('reviews', 'reviews'))} {primary_geo_hint}".strip()
                )
                if community_query and community_query not in existing_queries:
                    if len(gap_fill_queries) >= 3:
                        gap_fill_queries[-1] = community_query
                    else:
                        gap_fill_queries.append(community_query)
        gap_fill_queries = self._ensure_alias_anchor_query(task, request, gap_fill_queries, ranked_candidates)
        return self._ensure_competitor_anchor_query(
            request,
            task,
            gap_fill_queries,
            self._merge_unique(competitor_queries, ranked_candidates, limit=12),
            known_competitor_names,
        )

    def _build_convergence_queries(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        existing_queries: List[str],
        missing_tags: Optional[List[str]] = None,
        competitor_names: Optional[List[str]] = None,
    ) -> List[str]:
        strategy = self._search_strategy_for_task(task)
        known_competitor_names = self._known_competitor_names(request, task, competitor_names)
        anchor_profiles = self._query_anchor_profiles(request, task, limit=2)
        pack = self._query_phrase_pack(request)
        task_focus = self._task_focus_terms(task) or str(task.get("category") or "").replace("_", " ")
        if anchor_profiles:
            primary_profile = anchor_profiles[0]
            primary_anchor = str(primary_profile["anchor"] or "")
            primary_focus = str(primary_profile["focus"] or "")
            primary_geo_hint = str(primary_profile["geo_hint"] or "")
            primary_pack = primary_profile["pack"]
            alias_profile = anchor_profiles[1] if len(anchor_profiles) > 1 else None
            alias_anchor = str(alias_profile["anchor"] or "") if alias_profile else ""
        else:
            topic_anchors = self._query_topic_anchors(request)
            primary_anchor = topic_anchors[0] if topic_anchors else self._search_topic_anchor(request)
            alias_anchor = topic_anchors[1] if len(topic_anchors) > 1 else ""
            primary_focus = self._focus_terms_for_anchor(task, primary_anchor, task_focus)
            primary_geo_hint = self._query_geo_hint(request)
            primary_pack = pack
        focus_tags = missing_tags or list(self._required_query_coverage(task))
        seed_queries = self._topic_seed_queries(request)
        candidates: List[str] = list(seed_queries)
        candidates.extend(self._build_exemplar_queries(request, task))
        candidates.extend(self._competitor_query_expansions(request, task, known_competitor_names))

        for tag in focus_tags[:3]:
            lens = primary_pack.get(tag if tag in primary_pack else "analysis", primary_pack.get("analysis", "analysis"))
            candidates.append(self._normalize_query(" ".join(part for part in (primary_anchor, primary_focus, lens, primary_geo_hint) if part).strip()))
            if alias_anchor:
                alias_pack = alias_profile["pack"] if anchor_profiles and alias_profile else (QUERY_PHRASE_PACKS["en"] if self._query_anchor_prefers_english(alias_anchor) else pack)
                alias_focus = str(alias_profile["focus"] or "") if anchor_profiles and alias_profile else self._focus_terms_for_anchor(task, alias_anchor, task_focus)
                alias_geo_hint = str(alias_profile["geo_hint"] or "") if anchor_profiles and alias_profile else (
                    self._english_geo_hint(request) if self._query_anchor_prefers_english(alias_anchor) else self._query_geo_hint(request)
                )
                candidates.append(
                    self._normalize_query(
                        " ".join(
                            part
                            for part in (
                                alias_anchor,
                                alias_focus,
                                alias_pack.get(tag if tag in alias_pack else "analysis", alias_pack.get("analysis", "")),
                                alias_geo_hint,
                            )
                            if part
                        ).strip()
                    )
                )

        preferred_domains = self._effective_preferred_domains(request, task, strategy, limit=4)
        official_lens = pack.get("official", pack.get("docs", "official"))
        for domain in preferred_domains[:2]:
            candidates.append(self._normalize_query(f"site:{domain} {primary_anchor} {official_lens} {primary_focus}".strip()))
            if "comparison" in focus_tags:
                candidates.append(self._normalize_query(f"site:{domain} {primary_anchor} {pack.get('comparison', '')} {primary_focus}".strip()))

        if alias_anchor and alias_anchor != primary_anchor:
            alias_pack = alias_profile["pack"] if anchor_profiles and alias_profile else (QUERY_PHRASE_PACKS["en"] if self._query_anchor_prefers_english(alias_anchor) else pack)
            alias_geo_hint = str(alias_profile["geo_hint"] or "") if anchor_profiles and alias_profile else (
                self._english_geo_hint(request) if self._query_anchor_prefers_english(alias_anchor) else self._query_geo_hint(request)
            )
            candidates.append(
                self._normalize_query(
                    f"{alias_anchor} {alias_pack.get('analysis', alias_pack.get('market', ''))} {alias_geo_hint}".strip()
                )
            )

        topic_tokens = self._merge_unique(
            self._strong_topic_tokens(request),
            self._extract_query_terms(primary_anchor),
            self._extract_query_terms(alias_anchor),
            limit=8,
        )
        ranked_candidates = self._frontload_seed_queries(
            task,
            [query for query in candidates if query],
            seed_queries,
            request=request,
        )
        convergence_queries: List[str] = []
        for query in ranked_candidates:
            lowered = query.lower()
            if topic_tokens and not any(token in lowered for token in topic_tokens):
                continue
            if query in existing_queries or query in convergence_queries:
                continue
            convergence_queries.append(query)
            if len(convergence_queries) >= 3:
                break
        return self._ensure_competitor_anchor_query(
            request,
            task,
            convergence_queries,
            ranked_candidates,
            known_competitor_names,
        )

    def _query_topic_specificity_score(self, request: Dict[str, Any], query: str) -> float:
        topic_anchors = self._query_topic_anchors(request)
        topic_tokens = self._merge_unique(
            self._strong_topic_tokens(request),
            self._extract_query_terms(" ".join(topic_anchors)),
            limit=8,
        )
        if not topic_tokens:
            return 0.0
        lowered = str(query or "").lower()
        hits = sum(1 for token in topic_tokens if token in lowered)
        if hits == 0:
            return -6.0
        score = min(7.0, hits * 2.2)
        if query.startswith("site:"):
            score += 1.0
        return score

    def _query_alignment_score(self, task: Dict[str, Any], query: str, request: Optional[Dict[str, Any]] = None) -> float:
        tags = set(self._query_coverage_tags(query))
        required = set(self._required_query_coverage(task))
        discouraged = set(self._discouraged_query_coverage(task))
        priority = set(self._skill_priority_tags(task))
        score = 0.0
        score += sum(4.0 for tag in tags if tag in required)
        score += sum(2.0 for tag in tags if tag in priority)
        score -= sum(3.0 for tag in tags if tag in discouraged)
        if query.startswith("site:"):
            score += 2.5
        if 10 <= len(query) <= 110:
            score += 0.5
        if not tags:
            score -= 1.0
        if request is not None:
            score += self._query_topic_specificity_score(request, query)
        return score

    def _rank_queries_for_task(self, task: Dict[str, Any], queries: List[str], request: Optional[Dict[str, Any]] = None) -> List[str]:
        return sorted(
            queries,
            key=lambda query: (
                self._query_alignment_score(task, query, request=request),
                len(query),
            ),
            reverse=True,
        )

    def _frontload_seed_queries(
        self,
        task: Dict[str, Any],
        queries: List[str],
        seed_queries: List[str],
        request: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        ordered: List[str] = []
        for query in seed_queries:
            if query and query in queries and query not in ordered:
                ordered.append(query)
        ranked_tail = self._rank_queries_for_task(task, [query for query in queries if query not in ordered], request=request)
        return ordered + ranked_tail

    def _english_alias_anchors(self, request: Dict[str, Any]) -> List[str]:
        topic = str(request.get("topic") or "")
        if not re.search(r"[\u4e00-\u9fff]", topic):
            return []
        aliases: List[str] = []
        for anchor in self._query_topic_anchors(request):
            cleaned = self._normalize_query(anchor).lower()
            if cleaned and self._query_anchor_prefers_english(cleaned) and cleaned not in aliases:
                aliases.append(cleaned)
        return aliases[:2]

    def _query_uses_english_alias(self, request: Dict[str, Any], query: str) -> bool:
        lowered = str(query or "").lower()
        return any(alias in lowered for alias in self._english_alias_anchors(request))

    def _ensure_alias_anchor_query(
        self,
        task: Dict[str, Any],
        request: Dict[str, Any],
        queries: List[str],
        candidate_queries: List[str],
    ) -> List[str]:
        alias_anchors = self._english_alias_anchors(request)
        if not alias_anchors:
            return queries[:5]
        next_queries = list(queries[:5])
        if any(self._query_uses_english_alias(request, query) for query in next_queries):
            return next_queries

        alias_candidates = self._rank_queries_for_task(
            task,
            [query for query in candidate_queries if self._query_uses_english_alias(request, query)],
            request=request,
        )
        if not alias_candidates:
            return next_queries

        required_tags = set(self._required_query_coverage(task))
        alias_candidate = next(
            (
                query
                for query in alias_candidates
                if set(self._query_coverage_tags(query)).intersection(required_tags)
            ),
            None,
        )
        if not alias_candidate:
            alias_candidate = alias_candidates[0]
        if alias_candidate in next_queries:
            return next_queries

        seed_queries = set(self._topic_seed_queries(request))
        replace_index = next(
            (
                index
                for index in range(len(next_queries) - 1, -1, -1)
                if next_queries[index] not in seed_queries
                and not next_queries[index].startswith("site:")
                and not set(self._query_coverage_tags(next_queries[index])).intersection(required_tags)
            ),
            None,
        )
        if replace_index is None:
            replace_index = next(
                (
                    index
                    for index in range(len(next_queries) - 1, -1, -1)
                    if next_queries[index] not in seed_queries and not next_queries[index].startswith("site:")
                ),
                None,
            )
        if replace_index is None:
            replace_index = len(next_queries) - 1 if next_queries else 0
        if len(next_queries) >= 5:
            next_queries[replace_index] = alias_candidate
        else:
            next_queries.append(alias_candidate)
        deduped: List[str] = []
        for query in next_queries:
            if query and query not in deduped:
                deduped.append(query)
        return deduped[:5]

    def _ensure_site_anchor_query(
        self,
        task: Dict[str, Any],
        request: Dict[str, Any],
        queries: List[str],
        candidate_queries: List[str],
    ) -> List[str]:
        if any(query.startswith("site:") for query in queries):
            return queries[:5]

        site_candidates = self._rank_queries_for_task(
            task,
            [query for query in candidate_queries if query.startswith("site:")],
            request=request,
        )
        required_tags = set(self._required_query_coverage(task))
        site_candidate = next(
            (
                query
                for query in candidate_queries
                if query.startswith("site:") and set(self._query_coverage_tags(query)).intersection(required_tags)
            ),
            None,
        )
        if not site_candidate:
            site_candidate = next((query for query in site_candidates if query), None)
        if not site_candidate:
            return queries[:5]

        next_queries = list(queries[:5])
        if site_candidate in next_queries:
            return next_queries

        seed_queries = set(self._topic_seed_queries(request))
        replace_index = next(
            (index for index in range(len(next_queries) - 1, -1, -1) if next_queries[index] not in seed_queries),
            len(next_queries) - 1 if next_queries else 0,
        )
        if len(next_queries) >= 5:
            next_queries[replace_index] = site_candidate
        else:
            next_queries.append(site_candidate)
        deduped: List[str] = []
        for query in next_queries:
            if query and query not in deduped:
                deduped.append(query)
        return deduped[:5]

    def _ensure_query_coverage(
        self,
        task: Dict[str, Any],
        queries: List[str],
        fallback_queries: List[str],
        seed_queries: Optional[List[str]] = None,
    ) -> List[str]:
        max_queries = 5
        required_tags = list(self._required_query_coverage(task))
        normalized_seed_queries = list(seed_queries or [])
        reserved_by_tag: Dict[str, str] = {}
        reserved_queries: List[str] = []
        for target_tag in required_tags:
            candidate = next(
                (
                    query
                    for query in fallback_queries
                    if target_tag in self._query_coverage_tags(query)
                ),
                None,
            )
            if not candidate:
                continue
            reserved_by_tag[target_tag] = candidate
            if candidate not in reserved_queries:
                reserved_queries.append(candidate)

        headroom = max(0, max_queries - len(reserved_queries))
        final_queries: List[str] = []
        for query in queries:
            if query in final_queries:
                continue
            if query in reserved_queries and query not in normalized_seed_queries:
                continue
            final_queries.append(query)
            if len(final_queries) >= headroom:
                break

        covered = set()
        for query in final_queries:
            covered.update(self._query_coverage_tags(query))

        for target_tag in required_tags:
            if target_tag in covered:
                continue
            candidate = reserved_by_tag.get(target_tag)
            if not candidate:
                continue
            if candidate not in final_queries:
                final_queries.append(candidate)
            covered.update(self._query_coverage_tags(candidate))

        for query in [*queries, *fallback_queries]:
            if query in final_queries:
                continue
            final_queries.append(query)
            if len(final_queries) >= max_queries:
                break
        return final_queries[:max_queries]

    def _sanitize_queries(
        self,
        raw_queries: Any,
        request: Dict[str, Any],
        task: Dict[str, Any],
        competitor_names: Optional[List[str]] = None,
    ) -> List[str]:
        if not isinstance(raw_queries, list):
            return []
        sanitized = []
        meta_topic = self._looks_like_meta_topic(str(request.get("topic") or ""))
        for item in raw_queries:
            query = self._normalize_query(str(item).strip())
            if len(query) < 4:
                continue
            if meta_topic and any(hint in query.lower() for hint in META_TOPIC_HINTS):
                continue
            if query not in sanitized:
                sanitized.append(query)
        fallback_queries = self._build_fallback_queries(request, task, competitor_names)
        known_competitor_names = self._known_competitor_names(request, task, competitor_names)
        candidate_queries = list(sanitized)
        for query in fallback_queries:
            if query not in candidate_queries:
                candidate_queries.append(query)
        ranked_queries = self._frontload_seed_queries(
            task,
            candidate_queries or fallback_queries,
            self._topic_seed_queries(request),
            request=request,
        )
        final_queries = self._ensure_query_coverage(
            task,
            ranked_queries[:5] or fallback_queries,
            fallback_queries,
            seed_queries=self._topic_seed_queries(request),
        )
        final_queries = self._ensure_site_anchor_query(task, request, final_queries, candidate_queries)
        final_queries = self._ensure_alias_anchor_query(task, request, final_queries, candidate_queries)
        return self._ensure_competitor_anchor_query(
            request,
            task,
            final_queries,
            candidate_queries,
            known_competitor_names,
        )

    def _build_queries(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        competitor_names: Optional[List[str]] = None,
    ) -> List[str]:
        known_competitor_names = self._known_competitor_names(request, task, competitor_names)
        fallback_queries = self._build_fallback_queries(request, task, known_competitor_names)
        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback_queries

        try:
            system_prompt = load_prompt_template("research-worker")
            result = self.llm_client.complete_json(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "请为当前调研任务生成 4 到 6 条 JSON 数组 search_queries。"
                            "这些 query 必须覆盖不同搜索意图："
                            "1）官方/产品/定价/文档；2）第三方评测或社区反馈；3）对比/替代品；4）行业趋势或案例分析。"
                            "至少有 1 条 query 优先命中官网/文档域名，必要时可以使用 site:domain 的形式。"
                            "不要把具体 topic 偷换成泛词，例如不要把“AI眼镜”写成“AI 产品 / 软件 / 工具”。"
                            "如果 geo_scope 包含美国且 topic 是中文，请至少给 1 条英文 query。"
                            "query 要短、具体、可直接用于搜索引擎，不要写成自然语言指令，不要包含元话术。"
                            f"\ntopic={request['topic']}"
                            f"\nindustry_template={request['industry_template']}"
                            f"\nresearch_mode={request['research_mode']}"
                            f"\ngeo_scope={request.get('geo_scope') or []}"
                            f"\ntask_title={task.get('title')}"
                            f"\ntask_brief={task.get('brief')}"
                            f"\nmarket_step={task.get('market_step')}"
                            f"\nagent_mode={task.get('agent_mode')}"
                            f"\nresearch_goal={task.get('research_goal')}"
                            f"\nskill_packs={self._task_skill_packs(task)}"
                            f"\nskill_runtime={json.dumps(self._skill_runtime_summary(task), ensure_ascii=False)}"
                            f"\nsearch_intents={task.get('search_intents') or self._task_search_intents(task)}"
                            f"\nmust_cover={task.get('must_cover') or []}"
                            f"\ncompletion_criteria={task.get('completion_criteria') or []}"
                            f"\nsearch_strategy={json.dumps(self._search_strategy_for_task(task), ensure_ascii=False)}"
                            f"\nfallback_queries={json.dumps(fallback_queries, ensure_ascii=False)}"
                            "\n只返回 JSON，例如 {\"search_queries\": [\"...\", \"...\"]}。"
                        ),
                    },
                ],
                temperature=0.12,
                max_tokens=650,
            )
            if isinstance(result, dict):
                return self._sanitize_queries(result.get("search_queries", []), request, task, known_competitor_names)
        except Exception:
            return fallback_queries
        return fallback_queries

    def _is_low_signal_result(
        self,
        result: Dict[str, Any],
        task: Optional[Dict[str, Any]] = None,
        request: Optional[Dict[str, Any]] = None,
    ) -> bool:
        parsed = urlparse(result["url"])
        host = parsed.netloc.lower()
        title = (result.get("title") or "").lower()
        snippet = (result.get("snippet") or "").lower()
        path = parsed.path.lower()
        score = float(result.get("score", 0) or 0)
        site_domains = self._query_site_domains(str(result.get("query") or ""))
        if site_domains and not self._host_matches_site_domains(host, site_domains):
            return True
        if self._negative_keyword_match(request, result):
            return True
        if any(token in host for token in self.LOW_SIGNAL_HOST_TOKENS):
            return True
        if request is not None and self._topic_is_physical_product(request):
            normalized_host = host[4:] if host.startswith("www.") else host
            if any(
                normalized_host == domain or normalized_host.endswith(f".{domain}")
                for domain in PHYSICAL_PRODUCT_LOW_SIGNAL_DOMAINS
            ):
                return True
        if any(token in title for token in self.LOW_SIGNAL_TITLE_TOKENS):
            return True
        if any(token in path for token in self.LOW_SIGNAL_PATH_TOKENS):
            return True
        if len(snippet.strip()) < 5 and len(title.strip()) < 4:
            return True
        if score < -2:
            return True
        if task is not None:
            task_market_step = str(task.get("market_step") or "")
            listicle_like = any(token in title for token in self.LISTICLE_TITLE_TOKENS) or any(
                token in path for token in ("/best-", "/top-", "/roundup", "/alternatives")
            )
            if listicle_like and task_market_step not in {"competitor-analysis", "business-and-channels"}:
                return True
        return False

    def _fallback_analysis(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        title: str,
        summary: str,
        quote: str,
        source_url: str,
        is_snippet: bool,
        query: str = "",
    ) -> Dict[str, Any]:
        domain = urlparse(source_url).netloc or source_url
        condensed_summary = (summary or quote or title).strip()
        if len(condensed_summary) > 220:
            condensed_summary = condensed_summary[:217].rstrip() + "..."
        confidence = 0.5 if is_snippet else 0.78
        if len(condensed_summary) < 40:
            confidence = min(confidence, 0.42)
        if is_snippet and len(condensed_summary) < 80:
            confidence = min(confidence, 0.36)
        relevance = self._topic_relevance_assessment(
            request=request,
            task=task,
            title=title,
            source_url=source_url,
            source_text=summary,
            snippet=quote,
        )
        competitor_name = self._infer_competitor_name(
            request=request,
            task=task,
            title=title,
            summary=summary,
            quote=quote,
            source_url=source_url,
            query=query,
        )
        keep_threshold = 6 if is_snippet and str(title or "").strip() else 12 if is_snippet else 30
        return {
            "keep": len(condensed_summary) >= keep_threshold and relevance["keep"],
            "summary": condensed_summary or f"来自 {domain} 的页面内容被纳入研究证据。",
            "quote": (quote or condensed_summary or title)[:260],
            "extracted_fact": f"{request['topic']} 在{market_step_label(str(task.get('market_step') or ''))}维度从 {domain} 获得了新的证据。",
            "competitor_name": competitor_name,
            "confidence": confidence if relevance["keep"] else min(confidence, 0.3),
            "tags": [task["category"], task["market_step"], request["industry_template"], "search-snippet" if is_snippet else "page-content"],
        }

    def _http_status_code(self, error: Exception) -> Optional[int]:
        if isinstance(error, httpx.HTTPStatusError) and error.response is not None:
            return int(error.response.status_code)
        return None

    def _user_facing_runtime_error(self, error: Exception, stage: str) -> str:
        status_code = self._http_status_code(error)
        normalized_stage = str(stage or "").strip().lower()
        if normalized_stage == "search":
            if status_code in {401, 403, 451}:
                return "部分搜索来源限制访问，系统已自动切换到其他来源继续检索。"
            if status_code == 429:
                return "部分搜索来源触发访问频率限制，系统已自动切换到其他来源继续检索。"
            if isinstance(error, (httpx.TimeoutException, TimeoutError)):
                return "部分搜索来源响应较慢，系统已跳过超时来源并继续检索。"
            return "当前搜索来源暂时不可用，系统已继续尝试其他检索来源。"

        if isinstance(error, PrivateAccessError):
            return "部分页面需要登录或属于受限页面，系统已回退到搜索摘要并继续补充其他来源。"
        if isinstance(error, UnsafeRedirectError):
            return "部分结果跳转到了其他站点，系统已跳过风险跳转并继续补充其他来源。"
        if isinstance(error, InvalidFetchUrlError):
            return "部分结果链接异常，系统已跳过并继续补充其他来源。"
        if isinstance(error, FetchPreflightError):
            return "部分结果在抓取前校验中被跳过，系统已回退到搜索摘要并继续补充其他来源。"
        if status_code in {401, 403, 451}:
            return "部分页面限制直接访问，系统已保留搜索摘要并继续补充其他来源。"
        if status_code == 429:
            return "部分页面触发访问频率限制，系统已回退到搜索摘要并继续补充其他来源。"
        if isinstance(error, (httpx.TimeoutException, TimeoutError)):
            return "部分页面加载超时，系统已回退到搜索摘要并继续补充其他来源。"
        if isinstance(error, ValueError) and "Unsupported content type" in str(error):
            return "部分结果不是可直接解析的网页，系统已跳过并继续补充其他来源。"
        return "部分页面暂时无法解析，系统已回退到搜索摘要并继续补充其他来源。"

    def _should_open_browser_for_fetch_error(self, error: Exception) -> bool:
        return not isinstance(error, FetchPreflightError)

    def _browser_auto_open_mode(self, request: Dict[str, Any]) -> str:
        runtime_config = request.get("runtime_config") or {}
        debug_policy = runtime_config.get("debug_policy") or {}
        mode = str(debug_policy.get("auto_open_mode") or "").strip().lower()
        if mode in {"off", "debug_only", "always"}:
            return mode
        if bool(debug_policy.get("browser_auto_open")):
            return "debug_only"
        return "off"

    def _browser_auto_open_enabled(self, request: Dict[str, Any]) -> bool:
        return self._browser_auto_open_mode(request) in {"debug_only", "always"}

    def _access_blocked_snippet_analysis(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        result: Dict[str, Any],
        query: str,
        error: Exception,
    ) -> Optional[Dict[str, Any]]:
        status_code = self._http_status_code(error)
        if status_code not in {401, 403, 429, 451}:
            return None

        title = str(result.get("title") or result["url"]).strip()
        snippet = str(result.get("snippet") or "").strip()
        combined_text = " ".join(part for part in (title, snippet) if part).strip()
        if len(combined_text) < 8:
            return None

        relevance = self._topic_relevance_assessment(
            request=request,
            task=task,
            title=title,
            source_url=result["url"],
            source_text=combined_text,
            snippet=snippet or title,
        )
        if not relevance["keep"]:
            query_tokens = [
                token
                for token in self._extract_query_terms(query)
                if token not in GENERIC_RELEVANCE_TOKENS and token not in META_TOPIC_HINTS and "." not in token
            ]
            combined_lower = combined_text.lower()
            query_hits = sum(1 for token in query_tokens[:6] if token in combined_lower)
            if query_hits < 2 and relevance["topic_hits"] == 0 and relevance["task_hits"] == 0:
                return None

        analysis = self._fallback_analysis(
            request=request,
            task=task,
            title=title,
            summary=snippet or combined_text,
            quote=snippet or title,
            source_url=result["url"],
            is_snippet=True,
            query=query,
        )
        analysis["keep"] = True
        analysis["summary"] = (snippet or analysis["summary"] or title)[:220]
        analysis["quote"] = (snippet or title or result["url"])[:260]
        analysis["extracted_fact"] = f"{title} 的搜索摘要为 {request['topic']} 在{market_step_label(str(task.get('market_step') or ''))}维度提供了受限来源线索。"
        analysis["confidence"] = max(0.3, min(0.44, float(analysis.get("confidence", 0.36) or 0.36)))
        analysis["tags"] = self._dedupe_tags(
            list(analysis.get("tags") or []) + ["access-blocked-snippet", f"http-{status_code}"]
        )
        return analysis

    def _analyze_with_llm(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        title: str,
        source_url: str,
        source_text: str,
        snippet: str,
        is_snippet: bool,
        query: str = "",
    ) -> Dict[str, Any]:
        fallback = self._fallback_analysis(
            request,
            task,
            title,
            source_text or snippet,
            snippet or source_text[:260],
            source_url,
            is_snippet,
            query=query,
        )
        relevance = self._topic_relevance_assessment(
            request=request,
            task=task,
            title=title,
            source_url=source_url,
            source_text=source_text,
            snippet=snippet,
        )
        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback

        try:
            system_prompt = load_prompt_template("research-worker")
            result = self.llm_client.complete_json(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "请把下面的来源内容归一化为 JSON 对象，字段必须包含 "
                            "keep/summary/quote/extracted_fact/competitor_name/confidence/tags。"
                            "\n要求："
                            "\n1. 如果是广告、导航页、聚合页、登录页、低信息量页面，keep=false。"
                            "\n2. summary 要像专业研究员写的证据摘要，直接说明这个来源支持了什么判断，不要空话。"
                            "\n3. extracted_fact 必须是可用于后续 claim/report 的具体事实或判断线索。"
                            "\n4. 如果页面只提供模糊营销文案，没有明确信息，keep=false。"
                            "\n5. 如果页面主体与 topic 或当前 task 没有直接关联，keep=false。"
                            "对于 business-and-channels / market-trends / recommendations，可保留跨品牌行业基准；"
                            "但如果页面只是泛 AI、泛科技或泛资讯内容，且没有明显 task 相关性，也必须 keep=false。"
                            f"\ntopic={request['topic']}"
                            f"\nindustry_template={request['industry_template']}"
                            f"\nmarket_step={task['market_step']}"
                            f"\ntask_title={task.get('title')}"
                            f"\ntask_brief={task.get('brief')}"
                            f"\ntopic_anchor_tokens={self._strong_topic_tokens(request)}"
                            f"\ntask_relevance_tokens={self._task_relevance_tokens(request, task)}"
                            f"\nsource_url={source_url}"
                            f"\nsource_title={title}"
                            f"\nis_snippet={is_snippet}"
                            f"\nsource_snippet={snippet[:500]}"
                            f"\nsource_text={source_text[:4200]}"
                            "\n只返回 JSON。"
                        ),
                    },
                ],
                temperature=0.1,
                max_tokens=700,
            )
            if isinstance(result, dict):
                analysis = {
                    "keep": bool(result.get("keep", True)),
                    "summary": str(result.get("summary") or fallback["summary"]).strip(),
                    "quote": str(result.get("quote") or fallback["quote"]).strip()[:260],
                    "extracted_fact": str(result.get("extracted_fact") or fallback["extracted_fact"]).strip(),
                    "competitor_name": self._normalize_competitor_name(result.get("competitor_name")) if result.get("competitor_name") else None,
                    "confidence": float(result.get("confidence", fallback["confidence"])),
                    "tags": result.get("tags") if isinstance(result.get("tags"), list) else fallback["tags"],
                }
                if not analysis["summary"]:
                    analysis["summary"] = fallback["summary"]
                if not analysis["quote"]:
                    analysis["quote"] = fallback["quote"]
                if not analysis["competitor_name"]:
                    analysis["competitor_name"] = fallback.get("competitor_name") or self._infer_competitor_name(
                        request=request,
                        task=task,
                        title=title,
                        summary=source_text,
                        quote=snippet,
                        source_url=source_url,
                        query=query,
                    )
                if not relevance["keep"]:
                    analysis["keep"] = False
                    analysis["confidence"] = min(analysis["confidence"], fallback["confidence"], 0.3)
                analysis["confidence"] = max(0.25, min(0.95, analysis["confidence"]))
                return analysis
        except Exception:
            return fallback
        return fallback

    def _source_domain(self, source_url: str) -> str:
        parsed = urlparse(str(source_url or "").strip())
        domain = (parsed.netloc or parsed.path or "").strip().lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def _remember_admitted_source(self, seen_urls: set, seen_hosts: Dict[str, int], *source_urls: str) -> None:
        counted_hosts = set()
        for source_url in source_urls:
            normalized_url = str(source_url or "").strip()
            if not normalized_url:
                continue
            seen_urls.add(normalized_url)
            host = self._source_domain(normalized_url)
            if not host or host in counted_hosts:
                continue
            seen_hosts[host] = seen_hosts.get(host, 0) + 1
            counted_hosts.add(host)

    def _exemplar_competitor_signals(self, request: Dict[str, Any]) -> set[str]:
        return {
            self._normalize_phrase_signal(str(record.get("name") or ""))
            for record in self._topic_exemplar_records(request)
            if self._normalize_phrase_signal(str(record.get("name") or ""))
        }

    async def _seed_topic_exemplar_evidence(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        seen_urls: set,
        seen_hosts: Dict[str, int],
        on_progress: Optional[Callable[[Dict[str, Any], str], Awaitable[None]]] = None,
    ) -> List[Dict[str, Any]]:
        market_step = str(task.get("market_step") or "").strip().lower()
        category = str(task.get("category") or "").replace("-", "_")
        if not self._topic_is_physical_product(request):
            return evidence
        if market_step not in COMPETITOR_FOCUS_MARKET_STEPS and category not in {"competitor_landscape", "product_experience_teardown"}:
            return evidence

        exemplar_records = self._topic_exemplar_records(request)
        exemplar_signals = self._exemplar_competitor_signals(request)
        if not exemplar_records or not exemplar_signals:
            return evidence

        existing_signals = {
            self._normalize_phrase_signal(str(item.get("competitor_name") or ""))
            for item in evidence
            if self._normalize_phrase_signal(str(item.get("competitor_name") or ""))
        }
        if len(existing_signals.intersection(exemplar_signals)) >= min(3, len(exemplar_signals)):
            return evidence

        for record in exemplar_records[:4]:
            name = str(record.get("name") or "").strip()
            signal = self._normalize_phrase_signal(name)
            source_url = str(record.get("source_url") or "").strip()
            if not name or not signal or signal in existing_signals or not source_url or source_url in seen_urls:
                continue
            task["current_action"] = f"补充官方竞品页：{name}"
            if on_progress:
                await on_progress(task, f"搜索覆盖不足，补充官方竞品页：{name}")
            try:
                page = await fetch_and_extract_page(source_url)
            except Exception:
                continue

            title = page.get("title") or name
            snippet = (page.get("snippet") or page.get("meta_description") or title)[:240]
            page_text = page.get("text") or page.get("meta_description") or snippet
            analysis = self._analyze_with_llm(
                request=request,
                task=task,
                title=title,
                source_url=page["url"],
                source_text=page_text,
                snippet=snippet or title,
                is_snippet=False,
                query=name,
            )
            if not analysis.get("keep"):
                analysis = self._fallback_analysis(
                    request=request,
                    task=task,
                    title=title,
                    summary=page_text,
                    quote=snippet or title,
                    source_url=page["url"],
                    is_snippet=False,
                    query=name,
                )
            analysis["keep"] = True
            analysis["competitor_name"] = name
            analysis["summary"] = str(analysis.get("summary") or snippet or title).strip()
            analysis["extracted_fact"] = str(analysis.get("extracted_fact") or analysis["summary"] or title).strip()
            analysis["tags"] = self._dedupe_tags(list(analysis.get("tags") or []) + ["official", "exemplar-seed"])
            evidence.append(
                self._build_evidence_record(
                    request=request,
                    task=task,
                    result={"title": title},
                    analysis=analysis,
                    evidence_index=len(evidence) + 1,
                    source_url=page["url"],
                    source_type=page["source_type"],
                    published_at=page.get("published_at"),
                    authority_score=round(page["authority_score"], 2),
                    retrieval_trace={
                        "query": f"topic exemplar {name}",
                        "effective_query": name,
                        "wave_key": "seed",
                        "wave_label": "品牌补种",
                        "provider": "topic_exemplar",
                        "rank": 1,
                        "score": 99.0,
                        "query_tags": ["official", "comparison"],
                        "preferred_source_types": ["web", "article"],
                        "preferred_domains": list(record.get("domains") or []),
                    },
                )
            )
            existing_signals.add(signal)
            self._remember_admitted_source(seen_urls, seen_hosts, page["url"])
            task["source_count"] = len(evidence)
            task["progress"] = 100
            if len(existing_signals.intersection(exemplar_signals)) >= min(3, len(exemplar_signals)):
                break
        return evidence

    def _round_diagnostics(self, round_record: Dict[str, Any]) -> Dict[str, int]:
        diagnostics = round_record.setdefault(
            "diagnostics",
            {
                "search_errors": 0,
                "duplicates": 0,
                "low_signal": 0,
                "host_quota": 0,
                "fetch_fallbacks": 0,
                "browser_opens": 0,
                "rejected": 0,
                "admitted": 0,
                "negative_keyword_blocks": 0,
            },
        )
        return diagnostics

    def _increment_round_diagnostic(self, round_record: Dict[str, Any], key: str, amount: int = 1) -> None:
        diagnostics = self._round_diagnostics(round_record)
        diagnostics[key] = int(diagnostics.get(key, 0) or 0) + amount

    def _source_tier(self, source_type: str, authority_score: float, freshness_score: float, confidence: float, tags: List[str]) -> str:
        normalized_type = str(source_type or "").strip().lower()
        normalized_tags = {str(tag or "").strip().lower() for tag in tags if str(tag or "").strip()}
        if "search-snippet" in normalized_tags or confidence < 0.48:
            return "t4"
        if normalized_type in {"documentation", "pricing"} and authority_score >= 0.72 and confidence >= 0.66:
            return "t1"
        if authority_score >= 0.84 and freshness_score >= 0.68 and confidence >= 0.72:
            return "t1"
        if authority_score >= 0.68 and confidence >= 0.62:
            return "t2"
        if normalized_type in {"community", "review"} or confidence >= 0.54:
            return "t3"
        return "t4"

    def _source_tier_label(self, tier: str) -> str:
        return {
            "t1": "T1 一手/高权威",
            "t2": "T2 高可信交叉来源",
            "t3": "T3 补充佐证",
            "t4": "T4 待核验线索",
        }.get(str(tier or "").strip().lower(), "T4 待核验线索")

    def _citation_label(self, evidence_index: int) -> str:
        return f"[S{max(1, int(evidence_index))}]"

    def _normalized_fact_text(self, text: Any) -> str:
        return " ".join(str(text or "").split()).strip()

    def _extraction_method(self, tags: List[str]) -> str:
        normalized_tags = {str(tag or "").strip().lower() for tag in tags if str(tag or "").strip()}
        if "search-snippet" in normalized_tags:
            return "search_snippet"
        if "browser-capture" in normalized_tags:
            return "browser_capture"
        return "page_content"

    def _freshness_bucket(self, published_at: Optional[str]) -> str:
        text = str(published_at or "").strip()
        if not text:
            return "unknown"
        try:
            normalized = text.replace("Z", "+00:00")
            published = datetime.fromisoformat(normalized)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except ValueError:
            return "unknown"
        age_days = max(0.0, (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 86400)
        if age_days <= 30:
            return "last_30_days"
        if age_days <= 180:
            return "last_180_days"
        if age_days <= 365:
            return "last_12_months"
        return "older"

    def _entity_slug(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", str(value or "").strip().lower()).strip("-")

    def _entity_ids(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        source_domain: str,
        competitor_name: Optional[str],
    ) -> List[str]:
        topic_anchor = self._search_topic_anchor(request)
        topic_slug = self._entity_slug(topic_anchor or request.get("topic"))
        market_step_slug = self._entity_slug(task.get("market_step"))
        domain_slug = self._entity_slug(source_domain)
        competitor_slug = self._entity_slug(competitor_name)
        entity_ids: List[str] = []
        for candidate in (
            f"topic:{topic_slug}" if topic_slug else "",
            f"step:{market_step_slug}" if market_step_slug else "",
            f"competitor:{competitor_slug}" if competitor_slug else "",
            f"domain:{domain_slug}" if domain_slug else "",
        ):
            if candidate and candidate not in entity_ids:
                entity_ids.append(candidate)
            if len(entity_ids) >= 4:
                break
        return entity_ids

    def _reliability_scores(
        self,
        authority_score: float,
        freshness_score: float,
        confidence: float,
        tags: List[str],
    ) -> Dict[str, float]:
        normalized_tags = {str(tag or "").strip().lower() for tag in tags if str(tag or "").strip()}
        corroboration = confidence + (0.08 if "official" in normalized_tags else 0.0) - (0.12 if "search-snippet" in normalized_tags else 0.0)
        return {
            "authority": round(max(0.0, min(1.0, authority_score)), 2),
            "freshness": round(max(0.0, min(1.0, freshness_score)), 2),
            "relevance": round(max(0.0, min(1.0, confidence)), 2),
            "corroboration": round(max(0.0, min(1.0, corroboration)), 2),
        }

    def _normalized_retrieval_trace(self, retrieval_trace: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(retrieval_trace, dict):
            return None
        query = str(retrieval_trace.get("query") or "").strip()
        if not query:
            return None

        trace: Dict[str, Any] = {"query": query[:280]}
        effective_query = str(retrieval_trace.get("effective_query") or "").strip()
        if effective_query:
            trace["effective_query"] = effective_query[:280]

        query_id = str(retrieval_trace.get("query_id") or "").strip()
        if query_id:
            trace["query_id"] = query_id

        wave_key = str(retrieval_trace.get("wave_key") or "").strip()
        if wave_key:
            trace["wave_key"] = wave_key
        wave_label = str(retrieval_trace.get("wave_label") or "").strip()
        if wave_label:
            trace["wave_label"] = wave_label[:80]

        try:
            wave_index = int(retrieval_trace.get("wave_index") or 0)
        except (TypeError, ValueError):
            wave_index = 0
        if wave_index > 0:
            trace["wave_index"] = wave_index

        provider = str(retrieval_trace.get("provider") or "").strip().lower()
        if provider:
            trace["provider"] = provider

        try:
            rank = int(retrieval_trace.get("rank") or 0)
        except (TypeError, ValueError):
            rank = 0
        if rank > 0:
            trace["rank"] = rank

        for key in ("score", "topic_match_score"):
            value = retrieval_trace.get(key)
            try:
                numeric = round(float(value), 2)
            except (TypeError, ValueError):
                continue
            trace[key] = numeric

        try:
            strong_query_hits = int(retrieval_trace.get("strong_query_hits") or 0)
        except (TypeError, ValueError):
            strong_query_hits = 0
        if strong_query_hits > 0:
            trace["strong_query_hits"] = strong_query_hits

        alias_match_tokens: List[str] = []
        for token in retrieval_trace.get("alias_match_tokens") or []:
            normalized = str(token or "").strip()
            if normalized and normalized not in alias_match_tokens:
                alias_match_tokens.append(normalized)
            if len(alias_match_tokens) >= 8:
                break
        if alias_match_tokens:
            trace["alias_match_tokens"] = alias_match_tokens

        query_tags: List[str] = []
        for token in retrieval_trace.get("query_tags") or []:
            normalized = str(token or "").strip().lower()
            if normalized and normalized not in query_tags:
                query_tags.append(normalized)
            if len(query_tags) >= 8:
                break
        if query_tags:
            trace["query_tags"] = query_tags

        for key, limit in (("preferred_source_types", 6), ("preferred_domains", 8)):
            normalized_values: List[str] = []
            for token in retrieval_trace.get(key) or []:
                normalized = str(token or "").strip().lower()
                if normalized and normalized not in normalized_values:
                    normalized_values.append(normalized)
                if len(normalized_values) >= limit:
                    break
            if normalized_values:
                trace[key] = normalized_values
        return trace

    def _task_alias_tokens(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        competitor_names: Optional[List[str]] = None,
    ) -> List[str]:
        task_terms = self._extract_query_terms(
            " ".join(
                [
                    str(task.get("title") or ""),
                    str(task.get("brief") or ""),
                    str(task.get("market_step") or "").replace("-", " "),
                ]
            )
        )
        return self._merge_unique(
            self._query_topic_anchors(request),
            self._topic_alias_terms(request),
            self._known_competitor_names(request, task, competitor_names),
            task_terms,
            limit=8,
        )

    async def _search_with_task_aliases(
        self,
        query: str,
        max_results: int,
        preferred_source_types: List[str],
        preferred_domains: List[str],
        topic_alias_tokens: List[str],
    ) -> List[Dict[str, Any]]:
        search_kwargs = {
            "max_results": max_results,
            "preferred_source_types": preferred_source_types,
            "preferred_domains": preferred_domains,
            "topic_alias_tokens": topic_alias_tokens,
        }
        try:
            return await self.search_provider.search(query, **search_kwargs)
        except TypeError as error:
            if "topic_alias_tokens" not in str(error):
                raise
            fallback_kwargs = {
                "max_results": max_results,
                "preferred_source_types": preferred_source_types,
                "preferred_domains": preferred_domains,
            }
            return await self.search_provider.search(query, **fallback_kwargs)

    def _build_evidence_record(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        result: Dict[str, Any],
        analysis: Dict[str, Any],
        evidence_index: int,
        source_url: str,
        source_type: str,
        published_at: Optional[str],
        authority_score: float,
        retrieval_trace: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tags = [str(tag or "").strip() for tag in (analysis.get("tags") or []) if str(tag or "").strip()]
        freshness_score = 0.58 if "search-snippet" in tags else 0.82
        confidence = round(float(analysis["confidence"]), 2)
        source_domain = self._source_domain(source_url)
        normalized_fact = self._normalized_fact_text(analysis.get("extracted_fact") or analysis.get("summary") or result.get("title"))
        raw_support = self._normalized_fact_text(analysis.get("quote") or analysis.get("summary") or result.get("snippet"))
        source_tier = self._source_tier(
            source_type=source_type,
            authority_score=authority_score,
            freshness_score=freshness_score,
            confidence=confidence,
            tags=tags,
        )
        record = {
            "id": f"{task['id']}-evidence-{evidence_index}",
            "task_id": task["id"],
            "market_step": task["market_step"],
            "source_url": source_url,
            "source_domain": source_domain,
            "source_type": source_type,
            "source_tier": source_tier,
            "source_tier_label": self._source_tier_label(source_tier),
            "citation_label": self._citation_label(evidence_index),
            "title": result.get("title") or source_url,
            "published_at": published_at or datetime.now(timezone.utc).isoformat(),
            "captured_at": iso_now(),
            "quote": analysis["quote"],
            "summary": analysis["summary"],
            "extracted_fact": analysis["extracted_fact"],
            "normalized_fact": normalized_fact,
            "raw_support": raw_support,
            "extraction_method": self._extraction_method(tags),
            "entity_ids": self._entity_ids(request, task, source_domain, analysis.get("competitor_name")),
            "freshness_bucket": self._freshness_bucket(published_at),
            "reliability_scores": self._reliability_scores(authority_score, freshness_score, confidence, tags),
            "authority_score": authority_score,
            "freshness_score": freshness_score,
            "confidence": confidence,
            "injection_risk": score_prompt_injection_risk([analysis["quote"], analysis["summary"]]),
            "tags": tags,
            "competitor_name": analysis.get("competitor_name"),
        }
        normalized_retrieval_trace = self._normalized_retrieval_trace(retrieval_trace)
        if normalized_retrieval_trace:
            record["retrieval_trace"] = normalized_retrieval_trace
            if normalized_retrieval_trace.get("query_id"):
                record["query_plan_id"] = normalized_retrieval_trace["query_id"]
        return record

    async def collect_evidence(
        self,
        request: Dict[str, Any],
        task: Dict[str, Any],
        competitor_names: List[str],
        browser_tool,
        on_progress: Optional[Callable[[Dict[str, Any], str], Awaitable[None]]] = None,
        cancel_probe: Optional[Callable[[], Optional[str]]] = None,
    ) -> List[Dict[str, Any]]:
        known_competitor_names = self._known_competitor_names(request, task, competitor_names)
        if known_competitor_names:
            task["known_competitor_names"] = list(known_competitor_names)
        per_task_sources = max(3, min(12, request["max_sources"] // max(1, request["max_subtasks"])))
        queries = self._build_queries(request, task, known_competitor_names)
        task["agent_mode"] = str(task.get("agent_mode") or "deep_research_harness").strip() or "deep_research_harness"
        task["search_queries"] = queries
        task.setdefault("research_rounds", [])
        task["skill_runtime"] = self._skill_runtime_summary(task)
        task["coverage_status"] = {
            "required_query_tags": list(self._required_query_coverage(task)),
            "covered_query_tags": [],
            "missing_required": list(self._required_query_coverage(task)),
            "skill_runtime_active": bool(task["skill_runtime"]["skill_packs"]),
            "skill_themes": task["skill_runtime"]["skill_themes"],
            "skill_coverage_targets": task["skill_runtime"]["coverage_targets"],
            "missing_skill_targets": dict(task["skill_runtime"]["coverage_targets"]),
            "target_sources": per_task_sources,
        }
        evidence: List[Dict[str, Any]] = []
        seen_urls = set()
        seen_hosts: Dict[str, int] = {}
        browser_opened_count = 0
        strategy = self._search_strategy_for_task(task)
        search_waves = self._build_search_waves(task, queries)
        executed_queries: List[str] = []
        consecutive_empty_queries = 0
        consecutive_empty_rounds = 0
        convergence_injected = False
        query_plan = task.setdefault("query_plan", [])
        query_plan_lookup: Dict[str, str] = {
            str(item.get("query") or "").strip(): str(item.get("id") or "").strip()
            for item in query_plan
            if isinstance(item, dict) and str(item.get("query") or "").strip() and str(item.get("id") or "").strip()
        }
        next_query_plan_index = len(query_plan_lookup) + 1

        def ensure_query_plan_entry(
            query: str,
            wave: Dict[str, Any],
            wave_number: int,
            search_preferences: Dict[str, tuple[str, ...]],
        ) -> str:
            nonlocal next_query_plan_index
            normalized_query = str(query or "").strip()
            if not normalized_query:
                return ""
            existing_id = query_plan_lookup.get(normalized_query)
            if existing_id:
                return existing_id
            entry_id = f"{task['id']}-query-{next_query_plan_index}"
            next_query_plan_index += 1
            query_tags = self._query_coverage_tags(normalized_query)
            entry = {
                "id": entry_id,
                "query": normalized_query,
                "wave_key": str(wave.get("key") or "").strip(),
                "wave_label": str(wave.get("label") or "").strip(),
                "wave_index": wave_number,
                "retrieval_profile_id": str(self._runtime_retrieval_profile(request).get("profile_id") or "").strip() or None,
                "query_tags": query_tags,
                "preferred_source_types": list(search_preferences.get("preferred_source_types") or []),
                "preferred_domains": list(search_preferences.get("preferred_domains") or []),
                "official_domains": self._runtime_official_domains(request),
                "negative_keywords": self._runtime_negative_keywords(request),
            }
            query_plan.append(entry)
            query_plan_lookup[normalized_query] = entry_id
            return entry_id

        def ensure_not_cancelled() -> None:
            if not cancel_probe:
                return
            reason = str(cancel_probe() or "").strip()
            if reason:
                raise JobCancelledError(reason, partial_evidence=evidence)

        def refresh_live_coverage() -> None:
            task["source_count"] = len(evidence)
            task["coverage_status"] = self.build_task_coverage_status(task, evidence, per_task_sources)
            task["partial_evidence"] = [dict(item) for item in evidence]

        if on_progress:
            ensure_not_cancelled()
            await on_progress(task, "已生成深度研究查询，并按波次组织搜索。")

        wave_index = 0
        while wave_index < len(search_waves) and wave_index < MAX_SEARCH_WAVES:
            ensure_not_cancelled()
            wave = search_waves[wave_index]
            wave_queries = [query for query in wave["queries"] if query not in executed_queries]
            if not wave_queries:
                wave_index += 1
                continue

            round_record = {
                "wave": wave_index + 1,
                "key": wave["key"],
                "label": wave["label"],
                "queries": wave_queries,
                "query_summaries": [],
                "started_at": iso_now(),
                "evidence_before": len(evidence),
                "diagnostics": {
                    "search_errors": 0,
                    "duplicates": 0,
                    "low_signal": 0,
                    "host_quota": 0,
                    "fetch_fallbacks": 0,
                    "browser_opens": 0,
                    "rejected": 0,
                    "admitted": 0,
                    "negative_keyword_blocks": 0,
                },
                "pipeline": self._build_round_pipeline(request, task, wave_queries, known_competitor_names),
            }
            task.setdefault("research_rounds", []).append(round_record)
            task["current_action"] = f"第 {wave_index + 1} 轮研究：{wave['label']}"
            if on_progress:
                ensure_not_cancelled()
                await on_progress(task, f"第 {wave_index + 1} 轮研究：{wave['label']}")

            round_result_count = 0
            fast_converge_requested = False
            convergence_inserted_this_wave = False
            for query in wave_queries:
                ensure_not_cancelled()
                executed_queries.append(query)
                search_preferences = self._query_search_preferences(query, strategy, task, request=request)
                ensure_query_plan_entry(query, wave, wave_index + 1, search_preferences)
                evidence_before_query = len(evidence)
                query_summary = {
                    "query": query,
                    "status": "running",
                    "search_result_count": 0,
                    "evidence_added": 0,
                }
                round_record.setdefault("query_summaries", []).append(query_summary)
                try:
                    task["current_action"] = f"第 {wave_index + 1} 轮搜索：{query}"
                    if on_progress:
                        ensure_not_cancelled()
                        await on_progress(task, f"正在搜索（{wave['label']}）：{query}")
                    results = await self._search_with_task_aliases(
                        query,
                        max_results=max(7, per_task_sources * 2),
                        preferred_source_types=search_preferences["preferred_source_types"],
                        preferred_domains=search_preferences["preferred_domains"],
                        topic_alias_tokens=self._task_alias_tokens(request, task, known_competitor_names),
                    )
                    effective_search_preferences = search_preferences
                    retry_attempts: List[Dict[str, Any]] = []
                    if not results:
                        retry_queries = self._build_zero_result_retry_queries(request, task, query)
                        if retry_queries:
                            query_summary["retry_queries"] = retry_queries
                        for retry_query in retry_queries:
                            if retry_query in executed_queries:
                                continue
                            executed_queries.append(retry_query)
                            retry_preferences = self._merge_search_preferences(
                                search_preferences,
                                self._query_search_preferences(retry_query, strategy, task, request=request),
                            )
                            ensure_query_plan_entry(retry_query, wave, wave_index + 1, retry_preferences)
                            try:
                                task["current_action"] = f"第 {wave_index + 1} 轮重试搜索：{retry_query}"
                                if on_progress:
                                    ensure_not_cancelled()
                                    await on_progress(task, f"当前 query 无结果，改用更短查询重试：{retry_query}")
                                retry_results = await self._search_with_task_aliases(
                                    retry_query,
                                    max_results=max(7, per_task_sources * 2),
                                    preferred_source_types=retry_preferences["preferred_source_types"],
                                    preferred_domains=retry_preferences["preferred_domains"],
                                    topic_alias_tokens=self._task_alias_tokens(request, task, known_competitor_names),
                                )
                            except JobCancelledError:
                                raise
                            except Exception as retry_error:
                                self._increment_round_diagnostic(round_record, "search_errors")
                                retry_attempts.append({"query": retry_query, "status": "search_error", "search_result_count": 0})
                                task["latest_error"] = self._user_facing_runtime_error(retry_error, "search")
                                continue
                            retry_attempts.append(
                                {
                                    "query": retry_query,
                                    "status": "results_found" if retry_results else "zero_results",
                                    "search_result_count": len(retry_results),
                                }
                            )
                            if retry_results:
                                results = retry_results
                                query_summary["effective_query"] = retry_query
                                effective_search_preferences = retry_preferences
                                break
                        if retry_attempts:
                            query_summary["retry_attempts"] = retry_attempts
                    ensure_not_cancelled()
                    round_result_count += len(results)
                    self._increment_round_pipeline(round_record, "recalled_result_count", len(results))
                    query_summary["search_result_count"] = len(results)
                except JobCancelledError:
                    raise
                except Exception as error:
                    self._increment_round_diagnostic(round_record, "search_errors")
                    query_summary["status"] = "search_error"
                    task["latest_error"] = self._user_facing_runtime_error(error, "search")
                    consecutive_empty_queries += 1
                    if on_progress:
                        ensure_not_cancelled()
                        await on_progress(task, task["latest_error"])
                    if (
                        len(evidence) == 0
                        and not convergence_injected
                        and consecutive_empty_queries >= 2
                        and len(search_waves) < MAX_SEARCH_WAVES
                    ):
                        convergence_queries = self._build_convergence_queries(
                            request,
                            task,
                            executed_queries,
                            competitor_names=known_competitor_names,
                        )
                        if convergence_queries:
                            search_waves.insert(
                                wave_index + 1,
                                {"key": "convergence", "label": "主题收敛改写", "queries": convergence_queries},
                            )
                            convergence_injected = True
                            convergence_inserted_this_wave = True
                            fast_converge_requested = True
                            consecutive_empty_queries = 0
                            if on_progress:
                                ensure_not_cancelled()
                                await on_progress(task, f"连续无结果，已改写并追加 {len(convergence_queries)} 条收敛查询。")
                        break
                    continue

                executed_query = str(query_summary.get("effective_query") or query)
                executed_query_id = ensure_query_plan_entry(executed_query, wave, wave_index + 1, effective_search_preferences)
                executed_query_tags = self._query_coverage_tags(executed_query)
                for result_rank, result in enumerate(results, start=1):
                    ensure_not_cancelled()
                    if len(evidence) >= per_task_sources and self._research_is_sufficient(task, self._build_coverage_snapshot(task, evidence), per_task_sources):
                        break
                    if result["url"] in seen_urls:
                        self._increment_round_diagnostic(round_record, "duplicates")
                        continue
                    negative_keyword = self._negative_keyword_match(request, result)
                    if negative_keyword:
                        self._increment_round_diagnostic(round_record, "negative_keyword_blocks")
                        self._increment_round_pipeline(round_record, "negative_keyword_block_count")
                        continue
                    if self._is_low_signal_result(result, task, request=request):
                        self._increment_round_diagnostic(round_record, "low_signal")
                        continue
                    self._increment_round_pipeline(round_record, "reranked_result_count")
                    host = self._source_domain(result["url"])
                    result_source_type = result.get("source_type") or infer_source_type(result["url"])
                    max_per_host = 3 if result_source_type in {"documentation", "pricing"} else 2
                    if seen_hosts.get(host, 0) >= max_per_host and len(seen_hosts) >= 2:
                        self._increment_round_diagnostic(round_record, "host_quota")
                        continue
                    task["current_url"] = result["url"]
                    task["current_action"] = f"抓取：{result['title']}"
                    if on_progress:
                        ensure_not_cancelled()
                        await on_progress(task, f"正在抓取页面：{result['title']}")
                    self._increment_round_pipeline(round_record, "fetch_attempt_count")
                    try:
                        page = await fetch_and_extract_page(result["url"])
                        ensure_not_cancelled()
                    except JobCancelledError:
                        raise
                    except Exception as error:
                        self._increment_round_diagnostic(round_record, "fetch_fallbacks")
                        task["latest_error"] = self._user_facing_runtime_error(error, "fetch")
                        blocked_analysis = self._access_blocked_snippet_analysis(request, task, result, query, error)
                        blocked_status_code = self._http_status_code(error)
                        opened_in_browser = False
                        browser_result = None
                        if (
                            browser_tool.is_available()
                            and browser_opened_count < 1
                            and self._browser_auto_open_enabled(request)
                            and self._should_open_browser_for_fetch_error(error)
                        ):
                            browser_result = browser_tool.open(result["url"])
                            opened_in_browser = browser_result.get("status") == "ready"
                            if opened_in_browser:
                                browser_opened_count += 1
                                self._increment_round_diagnostic(round_record, "browser_opens")
                        task.setdefault("visited_sources", []).append(
                            {
                                "url": result["url"],
                                "title": result["title"],
                                "source_type": infer_source_type(result["url"]),
                                "snippet": result.get("snippet", ""),
                                "opened_in_browser": opened_in_browser,
                                "query": query,
                                "wave": wave["key"],
                            }
                        )
                        analysis = self._analyze_with_llm(
                            request=request,
                            task=task,
                            title=result.get("title") or result["url"],
                            source_url=result["url"],
                            source_text=result.get("snippet") or "",
                            snippet=result.get("snippet") or result.get("title") or result["url"],
                            is_snippet=True,
                            query=executed_query,
                        )
                        coverage_tags = self._coverage_tags_for_result(
                            query=executed_query,
                            source_type=result_source_type,
                            source_url=result["url"],
                            title=result.get("title") or result["url"],
                            snippet=result.get("snippet") or "",
                            analysis=analysis,
                        )
                        extra_tags = coverage_tags + [wave["key"], result_source_type]
                        if blocked_status_code is not None:
                            extra_tags.extend(["access-blocked-snippet", f"http-{blocked_status_code}"])
                        analysis["tags"] = self._dedupe_tags(list(analysis.get("tags") or []) + extra_tags)
                        if not analysis.get("keep") and blocked_analysis:
                            blocked_analysis["tags"] = self._dedupe_tags(list(blocked_analysis.get("tags") or []) + extra_tags)
                            analysis = blocked_analysis
                        if not analysis.get("keep"):
                            self._increment_round_diagnostic(round_record, "rejected")
                            continue
                        retrieval_trace = {
                            "query": query,
                            "effective_query": executed_query,
                            "query_id": executed_query_id,
                            "wave_key": wave["key"],
                            "wave_label": wave["label"],
                            "wave_index": wave_index + 1,
                            "provider": result.get("provider"),
                            "rank": result_rank,
                            "score": result.get("score"),
                            "topic_match_score": result.get("topic_match_score"),
                            "strong_query_hits": result.get("strong_query_hits"),
                            "alias_match_tokens": result.get("alias_match_tokens") or [],
                            "query_tags": executed_query_tags,
                            "preferred_source_types": list(effective_search_preferences["preferred_source_types"]),
                            "preferred_domains": list(effective_search_preferences["preferred_domains"]),
                        }
                        evidence.append(
                            self._build_evidence_record(
                                request=request,
                                task=task,
                                result=result,
                                analysis=analysis,
                                evidence_index=len(evidence) + 1,
                                source_url=result["url"],
                                source_type=infer_source_type(result["url"]),
                                published_at=datetime.now(timezone.utc).isoformat(),
                                authority_score=max(0.35, round(infer_authority_score(result["url"]) - 0.1, 2)),
                                retrieval_trace=retrieval_trace,
                            )
                        )
                        self._increment_round_diagnostic(round_record, "admitted")
                        self._increment_round_pipeline(round_record, "normalized_evidence_count")
                        if self._is_runtime_official_hit(request, result["url"]):
                            self._increment_round_pipeline(round_record, "official_hit_count")
                        self._remember_admitted_source(seen_urls, seen_hosts, result["url"])
                        if analysis.get("competitor_name"):
                            known_competitor_names = self._merge_competitor_names(
                                known_competitor_names,
                                [analysis.get("competitor_name")],
                                limit=8,
                            )
                            task["known_competitor_names"] = list(known_competitor_names)
                            round_record.setdefault("pipeline", {})["entity_terms"] = self._pipeline_entity_terms(
                                request,
                                task,
                                wave_queries,
                                known_competitor_names,
                            )
                        task["source_count"] = len(evidence)
                        task["progress"] = min(95, int((len(evidence) / max(1, per_task_sources)) * 100))
                        refresh_live_coverage()
                        if opened_in_browser:
                            task["current_action"] = f"页面抓取失败，已通过浏览器打开：{result['url']}"
                        elif browser_tool.is_available():
                            task["current_action"] = f"页面抓取失败，已保留搜索摘要：{result['url']}"
                        if on_progress:
                            message = f"页面抓取失败，已回退到搜索摘要：{result['title']}"
                            if opened_in_browser:
                                message = f"页面抓取失败，已自动在浏览器打开：{result['title']}"
                            ensure_not_cancelled()
                            await on_progress(task, message)
                        continue

                    snippet = page["snippet"][:240]
                    analysis = self._analyze_with_llm(
                        request=request,
                        task=task,
                        title=page["title"],
                        source_url=page["url"],
                        source_text=page.get("text") or page.get("meta_description") or snippet,
                        snippet=snippet or result.get("snippet") or page["title"],
                        is_snippet=False,
                        query=executed_query,
                    )
                    coverage_tags = self._coverage_tags_for_result(
                        query=executed_query,
                        source_type=page["source_type"],
                        source_url=page["url"],
                        title=page["title"],
                        snippet=snippet or result.get("snippet") or page["title"],
                        analysis=analysis,
                    )
                    analysis["tags"] = self._dedupe_tags(list(analysis.get("tags") or []) + coverage_tags + [wave["key"], page["source_type"]])
                    if not analysis.get("keep"):
                        self._increment_round_diagnostic(round_record, "rejected")
                        continue
                    self._increment_round_pipeline(round_record, "extracted_page_count")
                    retrieval_trace = {
                        "query": query,
                        "effective_query": executed_query,
                        "query_id": executed_query_id,
                        "wave_key": wave["key"],
                        "wave_label": wave["label"],
                        "wave_index": wave_index + 1,
                        "provider": result.get("provider"),
                        "rank": result_rank,
                        "score": result.get("score"),
                        "topic_match_score": result.get("topic_match_score"),
                        "strong_query_hits": result.get("strong_query_hits"),
                        "alias_match_tokens": result.get("alias_match_tokens") or [],
                        "query_tags": executed_query_tags,
                        "preferred_source_types": list(effective_search_preferences["preferred_source_types"]),
                        "preferred_domains": list(effective_search_preferences["preferred_domains"]),
                    }
                    task.setdefault("visited_sources", []).append(
                        {
                            "url": page["url"],
                            "title": page["title"],
                            "source_type": page["source_type"],
                            "snippet": snippet,
                            "opened_in_browser": False,
                            "query": query,
                            "wave": wave["key"],
                        }
                    )
                    evidence.append(
                        self._build_evidence_record(
                            request=request,
                            task=task,
                            result={"title": page["title"]},
                            analysis=analysis,
                            evidence_index=len(evidence) + 1,
                            source_url=page["url"],
                            source_type=page["source_type"],
                            published_at=page["published_at"] or datetime.now(timezone.utc).isoformat(),
                            authority_score=round(page["authority_score"], 2),
                            retrieval_trace=retrieval_trace,
                        )
                    )
                    self._increment_round_diagnostic(round_record, "admitted")
                    self._increment_round_pipeline(round_record, "normalized_evidence_count")
                    if self._is_runtime_official_hit(request, page["url"]):
                        self._increment_round_pipeline(round_record, "official_hit_count")
                    self._remember_admitted_source(seen_urls, seen_hosts, result["url"], page["url"])
                    if analysis.get("competitor_name"):
                        known_competitor_names = self._merge_competitor_names(
                            known_competitor_names,
                            [analysis.get("competitor_name")],
                            limit=8,
                        )
                        task["known_competitor_names"] = list(known_competitor_names)
                        round_record.setdefault("pipeline", {})["entity_terms"] = self._pipeline_entity_terms(
                            request,
                            task,
                            wave_queries,
                            known_competitor_names,
                        )
                    task["source_count"] = len(evidence)
                    task["progress"] = min(95, int((len(evidence) / max(1, per_task_sources)) * 100))
                    refresh_live_coverage()
                    if on_progress:
                        ensure_not_cancelled()
                        await on_progress(task, f"已抓取 {len(evidence)} / {per_task_sources} 个来源。")

                if len(evidence) == evidence_before_query:
                    consecutive_empty_queries += 1
                else:
                    consecutive_empty_queries = 0
                query_summary["evidence_added"] = len(evidence) - evidence_before_query
                if query_summary["status"] != "search_error":
                    if int(query_summary.get("search_result_count", 0) or 0) == 0:
                        query_summary["status"] = "zero_results"
                    elif int(query_summary.get("evidence_added", 0) or 0) > 0:
                        query_summary["status"] = "evidence_added"
                    else:
                        query_summary["status"] = "filtered"
                if (
                    len(evidence) == 0
                    and not convergence_injected
                    and consecutive_empty_queries >= 2
                    and len(search_waves) < MAX_SEARCH_WAVES
                ):
                    convergence_queries = self._build_convergence_queries(
                        request,
                        task,
                        executed_queries,
                        competitor_names=known_competitor_names,
                    )
                    if convergence_queries:
                        search_waves.insert(
                            wave_index + 1,
                            {"key": "convergence", "label": "主题收敛改写", "queries": convergence_queries},
                        )
                        convergence_injected = True
                        convergence_inserted_this_wave = True
                        fast_converge_requested = True
                        consecutive_empty_queries = 0
                        if on_progress:
                            ensure_not_cancelled()
                            await on_progress(task, f"连续 0 来源，已追加 {len(convergence_queries)} 条主题收敛查询。")
                        break

            snapshot = self._build_coverage_snapshot(task, evidence)
            gaps = self._coverage_gaps(task, snapshot, per_task_sources)
            round_record["completed_at"] = iso_now()
            round_record["evidence_added"] = len(evidence) - round_record["evidence_before"]
            round_record["result_count"] = round_result_count
            round_record["coverage"] = snapshot
            round_record["gaps"] = gaps
            task["coverage_status"] = self.build_task_coverage_status(task, evidence, per_task_sources)
            if round_record["evidence_added"] == 0 and round_result_count == 0:
                consecutive_empty_rounds += 1
            else:
                consecutive_empty_rounds = 0
            if (
                len(evidence) == 0
                and not convergence_injected
                and consecutive_empty_rounds >= 1
                and len(search_waves) < MAX_SEARCH_WAVES
            ):
                convergence_queries = self._build_convergence_queries(
                    request,
                    task,
                    executed_queries,
                    competitor_names=known_competitor_names,
                )
                if convergence_queries:
                    search_waves.insert(
                        wave_index + 1,
                        {"key": "convergence", "label": "主题收敛改写", "queries": convergence_queries},
                    )
                    convergence_injected = True
                    convergence_inserted_this_wave = True
                    consecutive_empty_rounds = 0
                    if on_progress:
                        ensure_not_cancelled()
                        await on_progress(task, f"当前轮次无有效结果，已追加 {len(convergence_queries)} 条收敛查询。")
            if self._research_is_sufficient(task, snapshot, per_task_sources):
                break
            if fast_converge_requested or convergence_inserted_this_wave:
                wave_index += 1
                continue

            gap_fill_queries = self._build_gap_fill_queries(
                request,
                task,
                {**snapshot, **gaps},
                executed_queries,
                known_competitor_names,
            )
            if gap_fill_queries and len(search_waves) < MAX_SEARCH_WAVES:
                search_waves.append({"key": "gap_fill", "label": "缺口补搜", "queries": gap_fill_queries})
                if on_progress:
                    ensure_not_cancelled()
                    await on_progress(task, f"发现证据缺口，追加 {len(gap_fill_queries)} 条补搜查询。")
            wave_index += 1

        ensure_not_cancelled()
        evidence = await self._seed_topic_exemplar_evidence(
            request,
            task,
            evidence,
            seen_urls,
            seen_hosts,
            on_progress=on_progress,
        )
        task["current_action"] = "证据采集完成"
        task["progress"] = 100
        if evidence:
            task["latest_error"] = None
        task.pop("partial_evidence", None)
        if not task.get("coverage_status"):
            task["coverage_status"] = self.build_task_coverage_status(task, evidence, per_task_sources)
        return evidence
