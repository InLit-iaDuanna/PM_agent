from __future__ import annotations

from typing import Dict


MARKET_STEP_LABELS: Dict[str, str] = {
    "research-definition": "研究定义",
    "research_definition": "研究定义",
    "market-definition": "市场定义与分层",
    "market_definition": "市场定义与分层",
    "market-trends": "市场规模与趋势",
    "market_trends": "市场规模与趋势",
    "user-research": "用户研究",
    "user_research": "用户研究",
    "competitor-analysis": "竞争产品分析",
    "competitor_analysis": "竞争产品分析",
    "competitor-landscape": "竞争格局",
    "competitor_landscape": "竞争格局",
    "experience-teardown": "体验拆解",
    "experience_teardown": "体验拆解",
    "reviews-and-sentiment": "评论与舆情分析",
    "reviews_and_sentiment": "评论与舆情分析",
    "business-and-channels": "商业与渠道研究",
    "business_and_channels": "商业与渠道研究",
    "pricing-and-growth": "定价与增长",
    "pricing_and_business_model": "定价、商业模式与渠道",
    "acquisition-and-distribution": "获客与分发",
    "acquisition_and_distribution": "获客与分发",
    "opportunities-and-risks": "机会与风险评估",
    "opportunities_and_risks": "机会与风险评估",
    "recommendations": "建议与待验证假设",
    "validation": "验证",
}

SOURCE_TYPE_LABELS: Dict[str, str] = {
    "documentation": "文档",
    "pricing": "定价页",
    "web": "网页",
    "article": "文章",
    "review": "评测",
    "community": "社区",
    "forum": "论坛",
    "report": "报告",
    "analysis": "分析",
    "internal": "内部上下文",
    "snippet": "搜索摘要",
    "news": "新闻",
    "social": "社交平台",
    "video": "视频",
}

WORKFLOW_COMMAND_LABELS: Dict[str, str] = {
    "deep_general_scan": "全景深度扫描",
    "competitor_war_room": "竞品作战室",
    "user_voice_first": "用户原声优先",
    "pricing_growth_audit": "定价与增长审计",
    "launch_readiness": "发布准备度检查",
}

INDUSTRY_TEMPLATE_LABELS: Dict[str, str] = {
    "industrial_design": "工业设计",
    "product_design": "产品设计",
    "saas": "SaaS",
    "ai_product": "AI 产品",
    "internet": "互联网",
    "ecommerce": "电商",
}

RESEARCH_MODE_LABELS: Dict[str, str] = {
    "standard": "标准调查",
    "deep": "深度调查",
}

DEPTH_PRESET_LABELS: Dict[str, str] = {
    "light": "轻量",
    "standard": "标准",
    "deep": "深入",
}


def _humanize_identifier(value: str) -> str:
    return value.replace("_", " ").replace("-", " ")


def market_step_label(value: str) -> str:
    normalized = str(value or "").strip()
    return MARKET_STEP_LABELS.get(normalized, _humanize_identifier(normalized)) if normalized else "未分类步骤"


def source_type_label(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return SOURCE_TYPE_LABELS.get(normalized, normalized or "未知来源")


def workflow_command_label(value: str) -> str:
    normalized = str(value or "").strip()
    return WORKFLOW_COMMAND_LABELS.get(normalized, _humanize_identifier(normalized)) if normalized else "全景深度扫描"


def industry_template_label(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return INDUSTRY_TEMPLATE_LABELS.get(normalized, _humanize_identifier(normalized)) if normalized else "未指定"


def research_mode_label(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return RESEARCH_MODE_LABELS.get(normalized, normalized or "标准调查")


def depth_preset_label(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return DEPTH_PRESET_LABELS.get(normalized, normalized or "标准")
