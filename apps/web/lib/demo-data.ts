import type {
  ChatSessionRecord,
  ClaimRecord,
  CreateResearchJobDto,
  EvidenceRecord,
  ResearchAssetsRecord,
  ResearchJobRecord,
} from "@pm-agent/types";
import researchDefaults from "@pm-agent/config/defaults/research-defaults.json";

const phaseLabels: Record<string, string> = {
  scoping: "研究定义",
  planning: "研究规划",
  collecting: "证据采集",
  verifying: "校验与冲突处理",
  synthesizing: "洞察与成文",
  finalizing: "收尾与归档",
};

const demoCategoryLabels: Record<string, string> = {
  market_trends: "市场规模与趋势",
  user_jobs_and_pains: "用户任务与痛点",
  competitor_landscape: "竞争格局",
  product_experience_teardown: "体验拆解",
  reviews_and_sentiment: "评论与舆情分析",
  pricing_and_business_model: "定价、商业模式与渠道",
  acquisition_and_distribution: "获客与分发",
  opportunities_and_risks: "机会与风险评估",
};

const demoCategoryMarketSteps: Record<string, string> = {
  market_trends: "market-trends",
  user_jobs_and_pains: "user-research",
  competitor_landscape: "competitor-analysis",
  product_experience_teardown: "experience-teardown",
  reviews_and_sentiment: "reviews-and-sentiment",
  pricing_and_business_model: "business-and-channels",
  acquisition_and_distribution: "business-and-channels",
  opportunities_and_risks: "opportunities-and-risks",
};

function buildClaims(): ClaimRecord[] {
  return [
    {
      id: "claim-1",
      claim_text: "AI PM 调研产品的最大机会在于把多源证据和对话闭环合并成一个工作台。",
      market_step: "opportunities-and-risks",
      evidence_ids: ["evidence-1", "evidence-2"],
      counter_evidence_ids: ["evidence-6"],
      confidence: 0.82,
      status: "disputed",
      caveats: ["仍需补充真实用户访谈"],
      competitor_ids: ["竞品 A", "竞品 B"],
      priority: "high",
      actionability_score: 0.91,
      last_verified_at: new Date().toISOString(),
    },
    {
      id: "claim-2",
      claim_text: "SaaS 与 AI 产品用户最关注调研可追溯性、自动补研和竞品深挖。",
      market_step: "user-research",
      evidence_ids: ["evidence-3", "evidence-4"],
      counter_evidence_ids: [],
      confidence: 0.87,
      status: "verified",
      caveats: [],
      competitor_ids: ["竞品 A"],
      priority: "high",
      actionability_score: 0.89,
      last_verified_at: new Date().toISOString(),
    },
    {
      id: "claim-3",
      claim_text: "深度调查模式需要单独暴露调查量控制，否则高强度调研成本不可控。",
      market_step: "recommendations",
      evidence_ids: ["evidence-5"],
      counter_evidence_ids: [],
      confidence: 0.8,
      status: "verified",
      caveats: [],
      competitor_ids: ["竞品 C"],
      priority: "medium",
      actionability_score: 0.84,
      last_verified_at: new Date().toISOString(),
    },
  ];
}

function buildEvidence(): EvidenceRecord[] {
  return [
    {
      id: "evidence-1",
      task_id: "task-1",
      market_step: "market-trends",
      source_url: "https://example.com/market-trends",
      source_domain: "example.com",
      source_type: "web",
      source_tier: "t2",
      source_tier_label: "T2 高可信交叉来源",
      citation_label: "[S1]",
      title: "市场趋势信号",
      captured_at: new Date().toISOString(),
      quote: "AI PM teams need one place to run long-form market investigations.",
      summary: "公开资料表明 PM 团队正在寻找研究与讨论一体化工具。",
      extracted_fact: "调研和讨论工作台是一条清晰需求。",
      authority_score: 0.84,
      freshness_score: 0.9,
      confidence: 0.81,
      injection_risk: 0.04,
      tags: ["market-trends", "ai_product"],
      competitor_name: "竞品 A",
    },
    {
      id: "evidence-2",
      task_id: "task-2",
      market_step: "competitor-analysis",
      source_url: "https://example.com/competitors",
      source_domain: "example.com",
      source_type: "web",
      source_tier: "t2",
      source_tier_label: "T2 高可信交叉来源",
      citation_label: "[S2]",
      title: "竞品定价观察",
      captured_at: new Date().toISOString(),
      quote: "Most competitors separate research reports from question-answer workflows.",
      summary: "竞品普遍割裂报告与后续讨论。",
      extracted_fact: "报告和对话割裂是现有竞品缺口。",
      authority_score: 0.79,
      freshness_score: 0.88,
      confidence: 0.8,
      injection_risk: 0.02,
      tags: ["competitor-analysis", "saas"],
      competitor_name: "竞品 B",
    },
    {
      id: "evidence-3",
      task_id: "task-3",
      market_step: "user-research",
      source_url: "https://example.com/reviews",
      source_domain: "example.com",
      source_type: "review",
      source_tier: "t3",
      source_tier_label: "T3 补充佐证",
      citation_label: "[S3]",
      title: "用户原声摘录",
      captured_at: new Date().toISOString(),
      quote: "Users want claims to link back to underlying evidence without leaving the conversation.",
      summary: "用户最在意可追溯性。",
      extracted_fact: "claim 级引用是关键基础能力。",
      authority_score: 0.77,
      freshness_score: 0.92,
      confidence: 0.86,
      injection_risk: 0,
      tags: ["user-research"],
      competitor_name: "竞品 A",
    },
    {
      id: "evidence-4",
      task_id: "task-4",
      market_step: "reviews-and-sentiment",
      source_url: "https://example.com/sentiment",
      source_domain: "example.com",
      source_type: "community",
      source_tier: "t3",
      source_tier_label: "T3 补充佐证",
      citation_label: "[S4]",
      title: "社区讨论线索",
      captured_at: new Date().toISOString(),
      quote: "Auto follow-up research is valuable when a question exceeds the original report scope.",
      summary: "自动补研能延长报告寿命。",
      extracted_fact: "对话中自动补研是高价值能力。",
      authority_score: 0.73,
      freshness_score: 0.86,
      confidence: 0.81,
      injection_risk: 0.01,
      tags: ["reviews-and-sentiment"],
      competitor_name: "竞品 C",
    },
    {
      id: "evidence-5",
      task_id: "task-5",
      market_step: "recommendations",
      source_url: "https://example.com/recommendation",
      source_domain: "example.com",
      source_type: "analysis",
      source_tier: "t2",
      source_tier_label: "T2 高可信交叉来源",
      citation_label: "[S5]",
      title: "预算控制机制",
      captured_at: new Date().toISOString(),
      quote: "Depth controls are mandatory for trust and cost predictability.",
      summary: "深度档位让用户更容易理解成本。",
      extracted_fact: "预设 + 高级参数是合理的平衡。",
      authority_score: 0.82,
      freshness_score: 0.89,
      confidence: 0.8,
      injection_risk: 0,
      tags: ["recommendations"],
      competitor_name: "竞品 C",
    },
    {
      id: "evidence-6",
      task_id: "task-6",
      market_step: "opportunities-and-risks",
      source_url: "https://example.com/risk",
      source_domain: "example.com",
      source_type: "analysis",
      source_tier: "t3",
      source_tier_label: "T3 补充佐证",
      citation_label: "[S6]",
      title: "执行风险提示",
      captured_at: new Date().toISOString(),
      quote: "Teams may resist heavy workflows if the UI feels too operational.",
      summary: "过度复杂的工作台有 adoption 风险。",
      extracted_fact: "UI 需要高级但保持简洁。",
      authority_score: 0.71,
      freshness_score: 0.84,
      confidence: 0.75,
      injection_risk: 0,
      tags: ["opportunities-and-risks"],
      competitor_name: "竞品 D",
    },
  ];
}

export function buildDemoJob(jobId = "demo-job"): ResearchJobRecord {
  return {
    id: jobId,
    topic: "AI PM 深度调查工作台",
    industry_template: "ai_product",
    research_mode: "deep",
    depth_preset: "deep",
    failure_policy: "graceful",
    completion_mode: "formal",
    workflow_command: "deep_general_scan",
    workflow_label: "全景深度扫描",
    project_memory: "结论优先面向 PM 负责人和产品负责人，重点强调可追溯性、后续补研闭环和竞品对比，不写空泛市场套话。",
    orchestration_summary: "先做全景扫描，再围绕决策风险补齐缺口，最后输出可直接进评审会的管理摘要和完整报告。",
    max_sources: 90,
    max_subtasks: 8,
    max_competitors: 8,
    review_sample_target: 400,
    time_budget_minutes: 45,
    status: "completed",
    overall_progress: 100,
    current_phase: "finalizing",
    eta_seconds: 0,
    source_count: 88,
    competitor_count: 8,
    completed_task_count: 8,
    running_task_count: 0,
    failed_task_count: 0,
    claims_count: 12,
    report_version_id: `${jobId}-report-v2`,
    phase_progress: Object.entries(researchDefaults.stageWeights).map(([phase]) => ({
      phase: phase as ResearchJobRecord["current_phase"],
      label: phaseLabels[phase],
      progress: 100,
      status: "completed",
    })),
    tasks: [
      "market_trends",
      "user_jobs_and_pains",
      "competitor_landscape",
      "product_experience_teardown",
      "reviews_and_sentiment",
      "pricing_and_business_model",
      "acquisition_and_distribution",
      "opportunities_and_risks",
    ].map((category, index) => {
      const categoryLabel = demoCategoryLabels[category] ?? category;
      const marketStep = demoCategoryMarketSteps[category] ?? category;
      return {
      id: `task-${index + 1}`,
      category,
      title: `任务 ${index + 1}`,
      brief: `围绕${categoryLabel}展开深度调查`,
      market_step: marketStep,
      command_id: "deep_general_scan",
      command_label: "全景深度扫描",
      skill_packs: ["source-triangulation", "coverage-tracking", "decision-memo"],
      orchestration_notes: "先覆盖全景，再补齐决策风险最大的研究缺口。",
      status: "completed",
      source_count: 11,
      retry_count: 0,
      progress: 100,
      agent_name: `研究任务 ${index + 1}`,
      current_action: "已完成",
      current_url: `https://example.com/${category}`,
      browser_mode: "mac-open",
      browser_available: true,
      search_queries: [`${categoryLabel} AI PM`, `${categoryLabel} 竞品`],
      research_rounds: [
        {
          wave: 1,
          key: "anchor",
          label: "锚点扫描",
          queries: [`${categoryLabel} AI PM`, `${categoryLabel} 竞品`],
          query_summaries: [
            {
              query: `${categoryLabel} AI PM`,
              status: "evidence_added",
              search_result_count: 5,
              evidence_added: 2,
            },
            {
              query: `${categoryLabel} 竞品`,
              status: "filtered",
              search_result_count: 3,
              evidence_added: 0,
            },
          ],
          started_at: new Date().toISOString(),
          completed_at: new Date().toISOString(),
          evidence_before: 0,
          evidence_added: 3,
          result_count: 8,
          diagnostics: {
            admitted: 3,
            fetch_fallbacks: 1,
            low_signal: 2,
            duplicates: 1,
          },
        },
      ],
      visited_sources: [
        {
          url: `https://example.com/${category}`,
          title: `${categoryLabel} 来源`,
          source_type: "web",
          snippet: "这里展示该步骤访问过的来源和内容摘录。",
          opened_in_browser: false,
        },
      ],
      logs: [
        {
          id: `log-${index + 1}-1`,
          timestamp: new Date().toISOString(),
          level: "info",
          message: "已生成查询并完成页面抓取。",
        },
      ],
    };
    }),
    activity_log: [
      {
        id: "activity-1",
        timestamp: new Date().toISOString(),
        level: "info",
        message: "研究任务已完成，所有步骤可查看详情。",
      },
    ],
  };
}

export function buildDemoAssets(jobId = "demo-job"): ResearchAssetsRecord {
  const claims = buildClaims();
  const evidence = buildEvidence();
  const generatedAt = new Date().toISOString();
  const reportClaimIds = claims.map((item) => item.id);
  const reportEvidenceIds = evidence.map((item) => item.id);
  const reportSourceDomains = Array.from(new Set(evidence.map((item) => item.source_domain).filter((item): item is string => Boolean(item))));
  const draftMarkdown = `# AI PM 深度调查报告（初稿）

## 核心结论摘要
- 市场正在从“单次报告”转向“研究工作台 + 对话闭环”（见 [S1]、[S2]）。
- 用户已经明确表达对 claim 级引用、自动补研和竞品深挖的需求（见 [S3]、[S4]）。

## 决策快照
- 当前决策成熟度：中等。
- 可以直接讨论方向与优先级，但还不能跳过成本和真实付费意愿验证。

## 关键证据摘录
- [S1] example.com / T2 高可信交叉来源：公开资料表明 PM 团队正在寻找研究与讨论一体化工具。
- [S3] example.com / T3 补充佐证：用户最在意结论和来源之间能否直接跳转追溯。

## 待验证问题
- 仍需验证不同团队对调查深度和成本控制的容忍度。
- 需要更多真实 PM 场景来确认高频提问链路。`;
  const finalMarkdown = `# AI PM 深度调查报告

## 核心结论摘要
- 市场正在从“单次报告”转向“研究工作台 + 对话闭环”（见 [S1]、[S2]）。
- 产品机会集中在 claim 级引用、自动补研、竞品深挖和可视化进度管理（见 [S3]、[S5]）。

## 决策快照
- 当前决策成熟度：较高。
- 可以进入下一轮产品策略和范围讨论，但仍需验证不同客群的付费意愿差异。

## 竞争格局
- 竞品 A：擅长报告生成，但对话追溯弱。
- 竞品 B：流程重，任务透明度高。
- 竞品 C：适合轻量研究，但对深度调查支持不足。

## 建议动作
- 先做深度调查模式 + 调查量控制。
- 让报告、claims、evidence 三层资产都能在 UI 被检索。
- 把进度条做成“总进度 + 阶段进度 + 子任务状态”三层。

## 关键证据摘录
- [S1] example.com / T2 高可信交叉来源：公开资料表明 PM 团队正在寻找研究与讨论一体化工具。
- [S3] example.com / T3 补充佐证：用户最在意结论和来源之间能否直接跳转追溯。
- [S5] example.com / T2 高可信交叉来源：深度档位和预算控制决定了方案是否能被长期采用。
`;
  const draftMemoMarkdown = `# AI PM 深度调查管理摘要（初稿）

## 核心结论摘要
- 市场已经出现“研究工作台 + 持续对话”的明确需求。

## 决策快照
- 当前适合讨论产品方向和研究范围，不适合直接承诺重投入。`;
  const finalMemoMarkdown = `# AI PM 深度调查管理摘要

## 核心结论摘要
- 机会集中在 claim 可追溯、自动补研和报告后的连续追问闭环。

## 决策快照
- 当前决策成熟度较高，建议先做深度研究闭环，再补足不同客群的定价验证。`;
  const appendixMarkdown = `# AI PM 深度调查附录

## 方法与覆盖
- 使用官网、评论、社区与竞品资料进行交叉验证。

## 证据附录
- 重点来源覆盖官网、帮助中心、评论社区与媒体分析。`;
  const conflictMarkdown = `# AI PM 深度调查冲突与验证边界

## 证据冲突与使用边界
- 仍需验证不同客户分层下对深度研究成本的接受度。`;
  return {
    report: {
      generated_at: generatedAt,
      updated_at: generatedAt,
      stage: "final",
      revision_count: 1,
      feedback_count: 0,
      long_report_ready: true,
      markdown: finalMarkdown,
      executive_memo_markdown: finalMemoMarkdown,
      appendix_markdown: appendixMarkdown,
      conflict_summary_markdown: conflictMarkdown,
      claim_ids: reportClaimIds,
      evidence_ids: reportEvidenceIds,
      source_domains: reportSourceDomains,
      decision_snapshot: {
        readiness: "较高",
        readiness_reason: "已有较完整的需求、竞品和体验证据，足以支持方向与范围判断。",
        high_confidence_claims: 3,
        inferred_claims: 1,
        disputed_claims: 0,
        open_questions: 2,
        unique_domains: 6,
        next_step: "先做深度研究闭环，再验证不同客群的付费意愿。",
      },
    },
    claims,
    evidence,
    competitors: [
      { name: "竞品 A", category: "direct", pricing: "$79/mo", positioning: "报告优先" },
      { name: "竞品 B", category: "direct", pricing: "$129/mo", positioning: "流程偏重" },
      { name: "竞品 C", category: "indirect", pricing: "$49/mo", positioning: "轻量体验" },
      { name: "竞品 D", category: "indirect", pricing: "$99/mo", positioning: "浏览器代理" },
    ],
    market_map: {
      segments: ["AI 产品团队", "增长 PM", "SaaS 创业团队"],
      opportunity_score: 0.84,
    },
    progress_snapshot: {
      source_growth: [
        { label: "规划", value: 4 },
        { label: "采集", value: 38 },
        { label: "校验", value: 66 },
        { label: "成文", value: 88 },
      ],
      source_mix: [
        { name: "官网/博客", value: 28 },
        { name: "帮助中心", value: 12 },
        { name: "评论/社区", value: 24 },
        { name: "媒体/分析", value: 24 },
      ],
      competitor_coverage: [
        { name: "A", value: 8 },
        { name: "B", value: 7 },
        { name: "C", value: 6 },
        { name: "D", value: 5 },
      ],
    },
    report_versions: [
      {
        version_id: `${jobId}-report-v1`,
        version_number: 1,
        label: "初稿",
        stage: "draft",
        markdown: draftMarkdown,
        executive_memo_markdown: draftMemoMarkdown,
        appendix_markdown: appendixMarkdown,
        conflict_summary_markdown: conflictMarkdown,
        claim_ids: reportClaimIds,
        evidence_ids: reportEvidenceIds,
        source_domains: reportSourceDomains,
        decision_snapshot: {
          readiness: "中等",
          readiness_reason: "方向已经明确，但仍缺少对预算和深度偏好的稳定验证。",
          high_confidence_claims: 2,
          inferred_claims: 1,
          disputed_claims: 0,
          open_questions: 2,
          unique_domains: 4,
          next_step: "先确认目标客群对深度研究成本的容忍度。",
        },
        generated_at: generatedAt,
        updated_at: generatedAt,
        evidence_count: evidence.length,
        section_count: 3,
        feedback_count: 0,
        revision_count: 0,
        long_report_ready: false,
      },
      {
        version_id: `${jobId}-report-v2`,
        version_number: 2,
        label: "终稿",
        stage: "final",
        markdown: finalMarkdown,
        executive_memo_markdown: finalMemoMarkdown,
        appendix_markdown: appendixMarkdown,
        conflict_summary_markdown: conflictMarkdown,
        claim_ids: reportClaimIds,
        evidence_ids: reportEvidenceIds,
        source_domains: reportSourceDomains,
        decision_snapshot: {
          readiness: "较高",
          readiness_reason: "已有较完整的需求、竞品和体验证据，足以支持方向与范围判断。",
          high_confidence_claims: 3,
          inferred_claims: 1,
          disputed_claims: 0,
          open_questions: 2,
          unique_domains: 6,
          next_step: "先做深度研究闭环，再验证不同客群的付费意愿。",
        },
        generated_at: generatedAt,
        updated_at: generatedAt,
        evidence_count: evidence.length,
        section_count: 3,
        feedback_count: 0,
        revision_count: 1,
        long_report_ready: true,
      },
    ],
  };
}

export function buildDemoChatSession(sessionId = "demo-session", researchJobId = "demo-job"): ChatSessionRecord {
  return {
    id: sessionId,
    research_job_id: researchJobId,
    messages: [
      {
        id: "message-1",
        role: "assistant",
        content: "欢迎回来。你可以继续追问竞品、用户痛点、定价，或让我补充新的深度调查。",
        cited_claim_ids: ["claim-1", "claim-2"],
        created_at: new Date().toISOString(),
      },
    ],
  };
}

export const defaultResearchForm: CreateResearchJobDto = {
  topic: "",
  industry_template: "ai_product",
  research_mode: "deep",
  depth_preset: "standard",
  failure_policy: "graceful",
  workflow_command: "deep_general_scan",
  project_memory: "",
  max_sources: 45,
  max_subtasks: 6,
  time_budget_minutes: 25,
  max_competitors: 5,
  review_sample_target: 150,
  geo_scope: ["中国"],
  language: "zh-CN",
  output_locale: "zh-CN",
};
