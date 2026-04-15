# PM Research Agent

English | [简体中文](README.zh-CN.md)

A readable monorepo for a PM-oriented research workbench:

- `apps/web`: Next.js research workbench UI
- `apps/api`: FastAPI API + SSE entrypoint
- `apps/worker`: research workflow engine
- `packages/ui`: shared React UI primitives
- `packages/types`: shared TypeScript DTOs + JSON Schemas
- `packages/research-core`: industry templates and research steps
- `packages/config`: default budgets and limits
- `packages/prompts`: agent prompt templates
- `packages/browser`: browser adapter contract

## What this project does now

The current product loop is:

1. Launch a research run from the command center with a workflow command
2. Planner creates task-level sub-agents with search intents, completion criteria, and skill packs
3. Research workers run multi-wave evidence collection with coverage tracking and gap-fill search
4. Verifier turns evidence into structured claims
5. Synthesizer generates a report system, not just one markdown blob
6. PM Chat continues on top of the latest composed report context
7. Follow-up questions trigger targeted delta research and can be composed back into a newer report version

Recent emphasis:

- final report composition is now **Chinese-first** and explicitly treats structured claims/evidence as writing context for the LLM, not as raw content to paste into the report
- report history supports both legacy English-heading versions and the new Chinese-heading deliverables
- PM Chat stays anchored to the active composed report and now links users back to the dedicated full-report page more clearly
- evidence now carries source-tier and citation metadata, and reports/readers expose a visible source index with `[Sx]`-style reference labels
- chat-triggered delta research now has an explicit timeout fallback, so stalled external search will degrade to report-context guidance instead of hanging the update path

## Core concepts

- `workflow_command`: reusable run mode such as general scan, competitor war room, or user voice first
- `project_memory`: persistent steering context for a run
- `skill_packs`: task-level runtime behaviors that influence search/query/coverage logic
- `report_versions`: explicit multi-round composition history
- `board_brief_markdown`: one-page decision brief for quick review before reading the full report
- `citation_label` / `source_tier`: shared source-reference primitives used by evidence cards, report synthesis, and reading views
- `output/state`: persisted jobs, assets, runtime settings, and chat sessions

## Local development

### API

```bash
./scripts/run_api.sh
```

### Worker tests

```bash
npm run test:worker
```

### Web

```bash
./scripts/bootstrap_frontend.sh
./scripts/start_web.sh
```

## Health checks

```bash
npm run check:web
npm run check
npm run benchmark
npm run benchmark:sync
```

`npm run benchmark` runs the deterministic research-quality benchmark harness against the sample result bundles, writes a JSON summary to `tmp/benchmark-quality-report.json`, and reports pass/fail for precision, claim support, report quality, and delta usefulness.

`npm run benchmark:sync` regenerates the full 30-case sample benchmark bundles from the golden topic catalog. `npm run check` now includes the strict benchmark gate (`benchmark:ci`), so the repo-level validation fails if any golden case is missing or any benchmark section regresses.

Useful overrides:

```bash
BENCHMARK_RESULTS_PATH=./benchmarks/sample_results.json npm run benchmark
BENCHMARK_REQUIRE_ALL_CASES=1 BENCHMARK_MINIMUM_SCORED_CASES=30 npm run benchmark
BENCHMARK_TOPICS_FILE=./packages/research-core/data/golden_research_benchmarks.json npm run benchmark
```

## Start the full stack

Recommended universal entrypoint:

```bash
./scripts/start_stack.sh
```

What it does:

- creates `.env` from `.env.example` when needed
- reuses your system `python3` / `node` / `npm` when available
- falls back to repo-local runtimes only if you explicitly provide them
- builds the Next.js app if needed
- auto-selects the next free local port when default `8000/3000` is already occupied
- starts API + web and writes logs to `tmp/`
- opens the workbench in your browser when the platform supports it

Useful env overrides:

```bash
PM_AGENT_API_PORT=8010 PM_AGENT_WEB_PORT=3010 ./scripts/start_stack.sh
PM_AGENT_PYTHON=/path/to/python ./scripts/start_stack.sh
PM_AGENT_NODE=/path/to/node PM_AGENT_NPM=/path/to/npm ./scripts/start_stack.sh
PM_AGENT_NO_OPEN=1 ./scripts/start_stack.sh
```

## Docker deployment

This repo now ships with two server deploy paths:

- `docker-compose.yml`: simple HTTP stack with nginx gateway, useful for local Docker use, staging, or when you already have an external TLS reverse proxy
- `docker-compose.prod.yml`: Caddy HTTPS stack with automatic certificates and explicit edge-bind controls for server deployment

Recommended public deployment:

```bash
cp .env.docker.example .env
# edit .env and set PM_AGENT_SITE_ADDRESS plus the edge bind host(s) you actually want
./scripts/docker_deploy_prod.sh --admin-email admin@example.com --admin-password 'change-me-now'
```

Recommended HTTP/staging deployment:

```bash
cp .env.docker.example .env
./scripts/docker_deploy.sh
```

What gets started in production mode:

- `api`: FastAPI backend
- `worker`: shared research worker service that consumes queued jobs
- `web`: Next.js production server
- `postgres`: durable metadata store for jobs, sessions, versions, evidence metadata, and auth data
- `redis`: shared worker queue plus fast event fanout
- `object-storage`: S3-compatible artifact/object store (MinIO by default)
- `caddy`: edge entrypoint that terminates TLS and proxies `/api/*` plus the website on one domain

Default production behavior:

- Caddy uses `PM_AGENT_SITE_ADDRESS` as the public domain or site address
- host ports default to `${PM_AGENT_HTTP_PORT:-80}` and `${PM_AGENT_HTTPS_PORT:-443}`
- host bind addresses default to loopback via `PM_AGENT_HTTP_BIND_HOST=127.0.0.1` and `PM_AGENT_HTTPS_BIND_HOST=127.0.0.1`
- the web container is built with `PM_AGENT_NEXT_PUBLIC_API_BASE_URL=same-origin`
- storage defaults to `PM_AGENT_STORAGE_BACKEND=flagship`, which wires `PostgreSQL + Redis + S3-compatible object storage`
- API/worker scratch files and logs still use the named Docker volume `pm_agent_state`
- if admin bootstrap credentials are passed to `docker_deploy_prod.sh`, the script creates the first admin before opening the public Caddy entrypoint
- if you prefer to bootstrap later, `./scripts/docker_bootstrap_admin.sh --prod ...` can create the first admin directly inside the running API container

Useful commands:

```bash
./scripts/docker_preflight_check.sh --prod
./scripts/docker_deploy_prod.sh --pull --admin-email admin@example.com --admin-password 'change-me-now'
./scripts/docker_bootstrap_admin.sh --prod --email admin@example.com --password 'change-me-now'
DOCKER_COMPOSE_FILES=docker-compose.prod.yml ./scripts/docker_backup_state.sh
docker compose -f docker-compose.prod.yml logs -f caddy web api worker
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml down
```

Notes:

- for real public deploys, set `PM_AGENT_SITE_ADDRESS` to your domain such as `research.example.com`
- for a cloud LB / WAF / reverse proxy, bind `PM_AGENT_HTTP_BIND_HOST` and `PM_AGENT_HTTPS_BIND_HOST` to the server's private/VPC IP
- use `0.0.0.0` only if you intentionally want the host itself to accept direct internet traffic
- for the staging gateway, `PM_AGENT_PUBLIC_BIND_HOST` also defaults to `127.0.0.1`; change it only when you intentionally want external reachability
- for local validation of the production stack, you can temporarily use `PM_AGENT_SITE_ADDRESS=:80` with non-default host ports
- if you change `PM_AGENT_NEXT_PUBLIC_API_BASE_URL`, rebuild the web image with `docker compose up -d --build`
- if you want host-visible scratch files instead of a named volume, replace `pm_agent_state:/data/state` in the compose file with a bind mount such as `./output/state:/data/state`
- in Docker, durable runtime metadata now lives in PostgreSQL/Object Storage by default; `pm_agent_state` is mainly used for logs, cache, and compatibility scratch space
- browser automation inside containers still depends on `OPENCLI_COMMAND`; without it, the app keeps the current degraded browser-open fallback behavior
- for a fuller production checklist, see [`deploy/SERVER_DEPLOYMENT.md`](deploy/SERVER_DEPLOYMENT.md)
- for backup/restore procedures, see [`deploy/BACKUP_AND_RECOVERY.md`](deploy/BACKUP_AND_RECOVERY.md)

## Account system

- The web app now includes a built-in account layer with a dedicated `/login` page.
- Authentication uses server-side sessions plus `HttpOnly` cookies, which works with both normal API calls and SSE job streams.
- Research jobs, chat sessions, and saved runtime settings are isolated per account.
- The first registered account automatically becomes the `admin` user.
- Admins can open `/settings/admin` to:
  - switch the registration policy between deploy defaults, open signup, invite-only signup, and closed signup
  - issue or disable invite codes
  - promote users to `admin` or demote them back to `member`
  - disable or re-enable accounts
  - reset another user's password
- You can control registration behavior at deploy time:
  - `PM_AGENT_ALLOW_PUBLIC_REGISTRATION=false` keeps public sign-up closed after the first bootstrap user; this is the safer default for internet-facing Docker deploys
  - `PM_AGENT_REGISTRATION_INVITE_CODE=...` turns registration into invite-only mode
- Those env vars now act as the initial/default registration policy; after bootstrap, admins can still override the live policy from `/settings/admin`.
- Logged-in users can now update their password under `/settings/account`.
- Disabled accounts cannot log in, and any existing session is cleared on the next authenticated request.
- The last active admin cannot be disabled, which avoids locking the deployment out of admin access.
- The recommended deployment shape is still the single-site gateway setup (`same-origin` web + API), because cookie/session behavior is simplest there.
- If you intentionally split web and API across different public domains, review these env vars before deploy:
  - `PM_AGENT_CORS_ORIGINS=https://your-web-origin.example`
  - `PM_AGENT_AUTH_COOKIE_SECURE=true`
  - `PM_AGENT_AUTH_COOKIE_SAMESITE=none`
- If you keep the default same-origin gateway deployment, you normally do not need custom CORS settings.

## Desktop launcher

- Double-click [`Start PM.command`](Start%20PM.command) to start everything
- Double-click [`Stop PM.command`](Stop%20PM.command) to stop everything
- Double-click [`PM Research Agent.command`](PM%20Research%20Agent.command)
- The launcher now just delegates to the same generic `./scripts/start_stack.sh` flow
- Logs are written to `tmp/api.log` and `tmp/web.log`
- Stop both services with:

```bash
./scripts/stop_stack.sh
```

## MiniMax

- The project reads `MINIMAX_API_KEY` from `.env`
- Default model is `MiniMax-M2.7`
- `.env.example` defaults to `https://api.minimaxi.com/v1`; switch to `https://api.minimax.io/v1` if your account uses the international endpoint
- If the key is missing, the app falls back to deterministic mock logic for planning/report/chat

## OpenCLI / browser launch

- The app will prefer `opencli` when available and fall back to macOS `open` / Linux `xdg-open`
- If you start the app from Finder and `opencli` is installed outside the default GUI PATH, set `OPENCLI_COMMAND` in `.env`
- Example macOS Homebrew config: `OPENCLI_COMMAND=/opt/homebrew/bin/opencli`

## Recent improvements

- Report composition now rewrites from a structured dossier into a cleaner Chinese deliverable instead of encouraging field-by-field structured-data fill-in
- Canonical report headings are now Chinese-first, while frontend utilities still support reopening older English-heading versions
- Frontend labels were further localized so the home page, job dashboard, PM Chat badges, and demo reading surfaces are more consistently Chinese
- Report rendering now has a more formal reading style intended to feel closer to a real research deliverable than raw markdown
- API connection failures now explain the active base URL and retry candidates more clearly
- Added a command-center style launch flow with workflow commands and project memory
- Planner now injects orchestration metadata, search intents, completion criteria, and skill packs into each task
- Search now behaves more like a deep-research loop with search waves, coverage checks, gap-fill queries, and stronger diversity logic
- Skill packs now actively change runtime search behavior instead of being passive labels
- Task detail views now expose skill runtime state, covered signals, missing coverage, and signal mix
- Reports now support multiple structured assets:
  - decision brief
  - executive memo
  - full report
  - conflicts and boundaries
  - appendix
- Full report composition can happen multiple times, with history preserved under explicit report versions
- Complete report pages now open in a dedicated reading surface instead of forcing everything into the main workbench pane
- Evidence explorer and report pages now expose source-tier badges, citation labels, and domain-level source indexing to make report review feel more like a formal research deliverable
- Research jobs, assets, and chat sessions now persist under `output/state`, so API restarts do not wipe history
- If the API restarts during an active run, the unfinished job is recovered as interrupted/failed instead of silently disappearing
- Search now merges DuckDuckGo + Bing results, deduplicates URLs, diversifies domains, and ranks sources by task-specific preferences
- PM Chat delta research now performs targeted real search/evidence collection before revising the report; if no high-signal external source is found, it falls back honestly to report-context guidance instead of inserting fake external evidence
- Delta research is now explicitly time-bounded so a slow search path degrades quickly instead of blocking the whole chat follow-up cycle
- Runtime settings now support ordered backup API connections, so a stuck upstream can fail over to the next gateway automatically
- The active LLM route and per-request timeout are now visible in the runtime page, and the client temporarily deprioritizes flaky endpoints after repeated failures

## Root docs for collaborators

- `README.md`: human-facing quick start and product overview
- `AGENTS.md`: quick context for future coding agents
- `PROJECT_HANDOFF.md`: detailed architecture, realtime model, current fixes, and takeover notes for future agents
- `CHANGELOG.md`: recent architecture and product changes worth preserving across sessions
