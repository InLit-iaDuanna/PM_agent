# PM Research Agent（PM 调研工作台）

[English](README.md) | 简体中文

面向产品经理（PM）的研究工作台 Monorepo：Next.js 前端 + FastAPI API + 后台 worker，用于把“规划 → 多波次证据收集 → 结构化 claims 验证 → 多资产报告合成 → PM Chat 持续追问与增量研究”串成闭环。

仓库主要目录：

- `apps/web`: Next.js 调研工作台 UI
- `apps/api`: FastAPI API + SSE 入口
- `apps/worker`: 调研工作流引擎
- `packages/ui`: 共享 React UI 基元
- `packages/types`: 共享 TypeScript DTO + JSON Schemas
- `packages/research-core`: 行业模板与调研步骤
- `packages/config`: 默认预算与限制
- `packages/prompts`: Agent Prompt 模板
- `packages/browser`: 浏览器适配器契约

## 目前项目能做什么

当前的产品闭环大致是：

1. 在 Command Center 选择 `workflow_command` 启动一次调研 run
2. Planner 将调研拆分为任务级子 agent，并附带 search intents、完成标准、skill packs 等
3. Research workers 多波次收集证据，跟踪覆盖度并按缺口补搜
4. Verifier 基于证据生成结构化 claims
5. Synthesizer 合成“报告体系”（多资产），而不是只输出一份 markdown
6. PM Chat 基于最新报告上下文继续对话
7. 追问会触发定向增量调研，并可合并回新版本报告

最近重点：

- 最终报告合成现在是中文优先：claims/evidence 作为写作上下文，而不是原样粘贴进报告
- 报告历史兼容旧版英文标题结构，同时支持新的中文交付格式
- Evidence 记录了来源分级与引用元数据；报告与阅读器展示 `[Sx]` 风格的可见来源索引
- Chat 触发的 delta research 有明确的超时降级：外部检索卡住时会退回“基于报告上下文”的保守建议而不是一直挂起

## 核心概念

- `workflow_command`: 可复用的运行模式（例如 general scan、competitor war room、user voice first）
- `project_memory`: run 的持久化 steering context
- `skill_packs`: 任务级运行行为，影响 search/query/coverage 逻辑
- `report_versions`: 多轮合成的版本历史
- `board_brief_markdown`: 一页决策 brief，便于在读全量报告前快速浏览
- `citation_label` / `source_tier`: 引用标签与来源分级的统一约定
- `output/state`: 持久化的作业、资产、运行时设置与 chat sessions

## 本地开发

推荐的通用入口：

```bash
./scripts/start_stack.sh
```

它会：

- 必要时从 `.env.example` 生成 `.env`
- 优先复用系统 `python3` / `node` / `npm`
- 如果默认 `8000/3000` 被占用，会自动选择下一个可用端口
- 启动 API + Web，把日志写到 `tmp/`
- 在支持的平台上自动打开浏览器

注意：`.env` 可能包含真实的 API Key，请勿提交到版本库。

也可以分别启动：

### API

```bash
./scripts/run_api.sh
```

### Worker 测试

```bash
npm run test:worker
```

### Web

```bash
./scripts/bootstrap_frontend.sh
./scripts/start_web.sh
```

## 健康检查

```bash
npm run check:web
npm run check
npm run benchmark
npm run benchmark:sync
```

说明：

- `npm run benchmark` 会跑确定性的 research-quality benchmark，输出 `tmp/benchmark-quality-report.json` 并给出 pass/fail。
- `npm run check` 包含严格 gate（`benchmark:ci`），如果缺少 golden case 或任一指标回退，会直接失败。

常用覆盖参数：

```bash
BENCHMARK_RESULTS_PATH=./benchmarks/sample_results.json npm run benchmark
BENCHMARK_REQUIRE_ALL_CASES=1 BENCHMARK_MINIMUM_SCORED_CASES=30 npm run benchmark
BENCHMARK_TOPICS_FILE=./packages/research-core/data/golden_research_benchmarks.json npm run benchmark
```

## 启动全栈（端口/运行时覆盖）

```bash
PM_AGENT_API_PORT=8010 PM_AGENT_WEB_PORT=3010 ./scripts/start_stack.sh
PM_AGENT_PYTHON=/path/to/python ./scripts/start_stack.sh
PM_AGENT_NODE=/path/to/node PM_AGENT_NPM=/path/to/npm ./scripts/start_stack.sh
PM_AGENT_NO_OPEN=1 ./scripts/start_stack.sh
```

## Docker 部署

仓库提供两条部署路径：

- `docker-compose.yml`: nginx 网关，适合本地 Docker、staging 或外部已有 TLS 反代的场景
- `docker-compose.prod.yml`: Caddy HTTPS 网关，支持自动证书，并提供显式的边缘绑定控制

推荐公网部署：

```bash
cp .env.docker.example .env
# 先编辑 .env，至少确认 PM_AGENT_SITE_ADDRESS 和需要绑定的边缘 IP
./scripts/docker_deploy_prod.sh --admin-email admin@example.com --admin-password 'change-me-now'
```

推荐 HTTP/staging 部署：

```bash
cp .env.docker.example .env
./scripts/docker_deploy.sh
```

生产模式会启动：

- `api`: FastAPI 后端
- `worker`: 消费队列的 research worker
- `web`: Next.js 生产服务
- `postgres`: 元数据持久化（jobs/sessions/versions/evidence/auth）
- `redis`: worker 队列与事件分发
- `object-storage`: S3 兼容对象存储（默认 MinIO）
- `caddy`: TLS 终止并代理 `/api/*` 与网站的边缘入口

注意事项：

- 公网部署建议把 `PM_AGENT_SITE_ADDRESS` 设为域名，例如 `research.example.com`
- 默认会把 `PM_AGENT_HTTP_BIND_HOST` / `PM_AGENT_HTTPS_BIND_HOST` 设为 `127.0.0.1`，避免源站直接暴露在公网
- 如果前面有云负载均衡 / WAF / 反向代理，优先把这两个绑定到服务器的私网/VPC IP
- 只有在你明确要让宿主机直接接收公网流量时，才把绑定地址改成 `0.0.0.0`
- `docker-compose.yml` 的 `PM_AGENT_PUBLIC_BIND_HOST` 也默认是 `127.0.0.1`
- 如果改了 `PM_AGENT_NEXT_PUBLIC_API_BASE_URL`，需要 `docker compose up -d --build` 重新构建 web
- 详细 checklist 请看 [`deploy/SERVER_DEPLOYMENT.md`](deploy/SERVER_DEPLOYMENT.md)
- 备份与恢复请看 [`deploy/BACKUP_AND_RECOVERY.md`](deploy/BACKUP_AND_RECOVERY.md)

## 账号系统

- Web 内置账号系统，登录页是 `/login`
- 认证方式是服务端 sessions + `HttpOnly` cookies（同时兼容普通 API 调用与 SSE job stream）
- 研究任务、聊天记录、运行时设置按账号隔离
- 第一个注册账号会自动成为 `admin`
- `admin` 可在 `/settings/admin` 配置注册策略、发放/禁用邀请码、管理用户权限等
- 如果你把 Web/API 拆到不同域名，部署前需要特别关注：
  - `PM_AGENT_CORS_ORIGINS=https://your-web-origin.example`
  - `PM_AGENT_AUTH_COOKIE_SECURE=true`
  - `PM_AGENT_AUTH_COOKIE_SAMESITE=none`

## 桌面启动器（macOS）

- 双击 [`Start PM.command`](Start%20PM.command) 启动
- 双击 [`Stop PM.command`](Stop%20PM.command) 停止
- 启动器本质上只是调用 `./scripts/start_stack.sh`
- 日志写在 `tmp/api.log` 和 `tmp/web.log`
- 也可以用命令行停止：

```bash
./scripts/stop_stack.sh
```

## MiniMax

- 从 `.env` 读取 `MINIMAX_API_KEY`
- 默认模型：`MiniMax-M2.7`
- `.env.example` 默认使用国内端点 `https://api.minimaxi.com/v1`
  - 如果你的账号是国际端点，可切换为 `https://api.minimax.io/v1`
- 如果 key 缺失，系统会退回到确定性的 mock 逻辑，用于 planning/report/chat

## OpenCLI / 浏览器打开

- 优先使用 `opencli`；没有的话退回到 macOS `open` 或 Linux `xdg-open`
- 如果从 Finder 启动导致 `opencli` 不在 GUI PATH，可以在 `.env` 里设置 `OPENCLI_COMMAND`
  - 例如 Homebrew：`OPENCLI_COMMAND=/opt/homebrew/bin/opencli`

## 协作者文档（根目录）

- `README.md`: 英文快速开始与概览
- `README.zh-CN.md`: 中文快速开始与概览
- `AGENTS.md`: 给后续代码 agent 的快速上下文
- `PROJECT_HANDOFF.md`: 更详细的架构、实时模型与交接说明
- `CHANGELOG.md`: 近期重要改动记录
