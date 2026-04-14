import { Cpu, Radar, Rocket, TrendingUp, Users2 } from "lucide-react";

import type { ResearchJobRecord, ResearchTaskRecord, WorkflowCommandId } from "@pm-agent/types";

const WORKFLOW_COMMAND_LABELS: Record<string, string> = {
  deep_general_scan: "全景深度扫描",
  competitor_war_room: "竞品作战室",
  user_voice_first: "用户原声优先",
  pricing_growth_audit: "定价与增长审计",
  launch_readiness: "发布准备度检查",
};

const INDUSTRY_TEMPLATE_LABELS: Record<string, string> = {
  industrial_design: "工业设计",
  product_design: "产品设计",
  saas: "SaaS",
  ai_product: "AI 产品",
  internet: "互联网",
  ecommerce: "电商",
};

const RESEARCH_MODE_LABELS: Record<string, string> = {
  standard: "标准调查",
  deep: "深度调查",
};

const MARKET_STEP_LABELS: Record<string, string> = {
  "research-definition": "研究定义",
  research_definition: "研究定义",
  "market-definition": "市场定义与分层",
  market_definition: "市场定义与分层",
  "market-trends": "市场规模与趋势",
  market_trends: "市场规模与趋势",
  "user-research": "用户研究",
  user_research: "用户研究",
  "competitor-analysis": "竞争产品分析",
  competitor_analysis: "竞争产品分析",
  "competitor-landscape": "竞争格局",
  competitor_landscape: "竞争格局",
  "experience-teardown": "体验拆解",
  experience_teardown: "体验拆解",
  "reviews-and-sentiment": "评论与舆情分析",
  reviews_and_sentiment: "评论与舆情分析",
  "business-and-channels": "商业与渠道研究",
  business_and_channels: "商业与渠道研究",
  "pricing-and-growth": "定价与增长",
  pricing_and_business_model: "定价、商业模式与渠道",
  "acquisition-and-distribution": "获客与分发",
  acquisition_and_distribution: "获客与分发",
  "opportunities-and-risks": "机会与风险评估",
  opportunities_and_risks: "机会与风险评估",
  recommendations: "建议与待验证假设",
  validation: "验证",
};

const SKILL_PACK_LABELS: Record<string, string> = {
  "source-triangulation": "交叉验证",
  "coverage-tracking": "覆盖跟踪",
  "decision-memo": "决策摘要",
  "market-sizing-lite": "规模估算",
  "trend-triangulation": "趋势交叉验证",
  "benchmark-scouting": "标杆扫描",
  "jtbd-extraction": "任务场景提炼",
  "pain-point-ranking": "痛点排序",
  "voice-snippet-capture": "用户原声摘录",
  "review-clustering": "评论聚类",
  "voice-of-customer": "用户声音",
  "signal-polarity": "口碑倾向判断",
  "competitive-mapping": "竞品映射",
  "segment-layering": "细分分层",
  "positioning-diff": "定位差异",
  "feature-diffing": "功能差异",
  "flow-teardown": "流程拆解",
  "friction-mapping": "摩擦点梳理",
  "pricing-benchmarking": "定价对标",
  "packaging-analysis": "套餐结构分析",
  "value-metric-check": "价值指标检查",
  "channel-diagnostics": "渠道诊断",
  "distribution-mapping": "分发路径映射",
  "growth-loop-check": "增长循环检查",
  "opportunity-ranking": "机会排序",
  "execution-risk-audit": "执行风险审视",
  "decision-briefing": "决策简报",
  "conversion-risk-review": "转化风险审视",
  "launch-risk-audit": "发布风险审计",
  "channel-readiness": "渠道准备度",
  "positioning-check": "定位检查",
};

const SOURCE_TYPE_LABELS: Record<string, string> = {
  documentation: "文档",
  pricing: "定价页",
  web: "网页",
  article: "文章",
  review: "评测",
  community: "社区",
  forum: "论坛",
  report: "报告",
  analysis: "分析",
  internal: "内部上下文",
  snippet: "搜索摘要",
  news: "新闻",
  social: "社交平台",
  video: "视频",
};

const BROWSER_MODE_LABELS: Record<string, string> = {
  opencli: "增强浏览",
  "mac-open": "系统浏览器",
  "xdg-open": "系统浏览器",
  "static-fetch": "静态抓取",
  "static-fetch-degraded": "降级抓取",
  unavailable: "不可用",
};

const RUNTIME_SOURCE_LABELS: Record<string, string> = {
  saved: "已保存配置",
  environment: "环境变量",
  default: "默认配置",
};

const VALIDATION_STATUS_LABELS: Record<string, string> = {
  valid: "可用",
  invalid: "不可用",
  unknown: "未知",
};

export const commandIcons: Record<WorkflowCommandId, typeof Radar> = {
  deep_general_scan: Radar,
  competitor_war_room: Cpu,
  user_voice_first: Users2,
  pricing_growth_audit: TrendingUp,
  launch_readiness: Rocket,
};

function normalizeDisplayToken(value?: string | null) {
  return String(value || "").trim();
}

export function formatWorkflowCommand(value?: string | null) {
  const normalized = normalizeDisplayToken(value);
  return WORKFLOW_COMMAND_LABELS[normalized] ?? normalized.replace(/[_-]/g, " ");
}

export function formatMarketStep(value?: string | null) {
  const normalized = normalizeDisplayToken(value);
  return MARKET_STEP_LABELS[normalized] ?? normalized.replace(/[_-]/g, " ");
}

export function formatIndustryTemplate(value?: string | null) {
  const normalized = normalizeDisplayToken(value);
  return INDUSTRY_TEMPLATE_LABELS[normalized] ?? normalized.replace(/[_-]/g, " ");
}

export function formatResearchMode(value?: string | null) {
  const normalized = normalizeDisplayToken(value).toLowerCase();
  return (RESEARCH_MODE_LABELS[normalized] ?? normalized) || "未设置";
}

export function formatSkillPack(value?: string | null) {
  const normalized = normalizeDisplayToken(value);
  return SKILL_PACK_LABELS[normalized] ?? normalized.replace(/[_-]/g, " ");
}

export function formatSourceType(value?: string | null) {
  const normalized = normalizeDisplayToken(value).toLowerCase();
  return (SOURCE_TYPE_LABELS[normalized] ?? normalized) || "未知来源";
}

export function formatBrowserMode(value?: string | null) {
  const normalized = normalizeDisplayToken(value).toLowerCase();
  return (BROWSER_MODE_LABELS[normalized] ?? normalized.replace(/[_-]/g, " ")) || "未知";
}

export function formatRuntimeSource(value?: string | null) {
  const normalized = normalizeDisplayToken(value).toLowerCase();
  return (RUNTIME_SOURCE_LABELS[normalized] ?? normalized.replace(/[_-]/g, " ")) || "未知来源";
}

export function formatValidationStatus(value?: string | null) {
  const normalized = normalizeDisplayToken(value).toLowerCase();
  return (VALIDATION_STATUS_LABELS[normalized] ?? normalized) || "未知";
}

export function commandUsage(jobs: ResearchJobRecord[], commandId: WorkflowCommandId) {
  const matchedJobs = jobs.filter((job) => (job.workflow_command || "deep_general_scan") === commandId);
  return {
    total: matchedJobs.length,
    latest: matchedJobs[0],
  };
}

export function sourceTierTone(sourceTier?: string) {
  if (sourceTier === "t1") return "success";
  if (sourceTier === "t2") return "default";
  if (sourceTier === "t3") return "warning";
  return "danger";
}

export function taskStatusTone(status?: ResearchTaskRecord["status"]) {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "cancelled") return "warning";
  return "default";
}

export function taskStatusLabel(status?: ResearchTaskRecord["status"]) {
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已停止";
  if (status === "queued") return "排队中";
  return "执行中";
}

export function activityLevelLabel(level?: string) {
  if (level === "error") return "错误";
  if (level === "warning") return "提醒";
  return "进展";
}
