# Changelog

This file records the major product and architecture changes made during the recent PM agent overhaul so future agents can quickly understand what already landed.

## 2026-04-14

### Frontend refactor integration (opus packs)

- Integrated the two local refactor bundles from `/home/eda/桌面/opus` into the current web app codebase with compatibility fixes for the existing routes and APIs.
- Landed new UI primitives in `packages/ui` and exported them from the shared entry:
  - `sidebar`, `sheet`, `skeleton`, `tabs`, `toast`, `collapsible`, `step-indicator`, `timeline`
  - P4 additions: `tooltip`, `animated-card`, `read-progress-bar`
- Updated global app shell and providers:
  - replaced `AppChrome` with shell-layout mode (`Sidebar + TopBar + StatusBar + QuickSearchPanel`)
  - wrapped app providers with `ToastProvider`
- Switched key page entries to refactored views:
  - `/` now uses `HomeDashboardRefactored`
  - `/research/new` now uses `NewResearchFormRefactored`
  - `/research/jobs/[jobId]/report` now uses `ResearchReportPageRefactored`
- Rewired job live page from legacy workbench composition to refactored tabbed job page:
  - `ResearchJobLivePage` now renders `JobPage`
  - `JobPage` now accepts live `session/chat` props and uses `PmChatPanelRefactored`
  - agent tab now uses `AgentSwarmBoardAnimated` with task selection wiring
- Added compatibility adaptations to fit current repo contracts:
  - fixed shell import paths
  - aligned runtime-status fields to current `RuntimeStatusRecord` (`configured`, `selected_profile_label`)
  - aligned chat send API usage to current `sendChatMessage(sessionId, content)` signature
  - added safe parsing for optional message `source_refs` metadata
  - fixed refactor syntax/type issues (new-research form placeholders, depth preset options, mode/policy values)
- Frontend verification: `npm --prefix apps/web run build` passed successfully after integration.

### Server one-click update workflow

- Added `./scripts/server_update.sh` to automate routine server upgrades:
  - fetches latest refs from `origin`
  - checks out a target branch/tag (`--ref`, default `main`)
  - creates a Docker volume backup before deploy by default
  - redeploys with either `docker_deploy.sh` (default) or `docker_deploy_prod.sh` (`--prod`)
  - supports shared-host isolation via `--project-name <name>`
  - supports optional admin bootstrap flags for prod updates
- Updated `deploy/SERVER_DEPLOYMENT.md` with one-click update examples for:
  - shared hosts with custom `COMPOSE_PROJECT_NAME`
  - fixed tag deploys
  - production TLS updates

### Admin Web version/update panel

- Added admin-only update APIs:
  - `GET /api/admin/system-update` for current version/tag, selectable refs, and recent update jobs
  - `POST /api/admin/system-update` to trigger `scripts/server_update.sh` in background
  - `POST /api/admin/system-update/sync` to fetch latest refs/tags from GitHub origin before update
- Added a new `/settings/admin` panel section to:
  - display current branch/tag/commit
  - show remote origin info (`origin/main`, latest tag, sync result)
  - sync GitHub refs from the UI
  - choose target ref (branch/tag)
  - choose update mode (`default`/`prod`) and compose project name
  - one-click update to latest `main`
  - start an update job or copy the exact update command
  - inspect recent update-job status and log path
- Web-triggered update execution is gated by `PM_AGENT_WEB_UPDATE_ENABLED=true` and remains disabled by default.
- Admin page version-update panel is now simplified to a minimal flow:
  - only shows current version metadata
  - one update action button (`版本更新`) instead of multiple ref/mode controls
- Docker deploy scripts now inject build metadata (`commit/tag/branch/build_time`) into API/Web images at build time.
- `SystemUpdateService` now falls back to those build metadata env vars when running inside container images without `.git`, so admin pages can still show current version even when git is unavailable in containers.

## 2026-04-11

### Account system skeleton

- Added a minimal in-app account system built around server-side sessions and `HttpOnly` cookies.
- New API auth routes:
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `GET /api/auth/me`
  - `POST /api/auth/logout`
- Repository state now persists:
  - users
  - auth sessions
  - per-user runtime settings
- Research jobs, chat sessions, runtime settings, and job streams are now user-scoped:
  - protected API routes require login
  - jobs and chat sessions carry `owner_user_id`
  - runtime settings are isolated per account instead of being shared globally by default
- Frontend now includes:
  - `/login` page
  - global auth provider / route gate
  - header-level current-user panel with logout
  - authenticated fetch + SSE (`credentials: "include"` / `withCredentials: true`)
- Added API tests for:
  - register / me / logout flow
  - protected-route 401 behavior
  - cross-user job isolation
- Account controls were extended further:
  - first registered user becomes `admin`
  - public registration can be closed with env vars
  - registration can be switched to invite-only mode with a deploy-time invite code
  - authenticated users can now change their password from the web UI
  - added `/settings/account` for account info and password updates
  - authenticated users can now permanently delete their own account from `/settings/account` after confirming their current password
  - admins can now disable / re-enable users from `/settings/admin`
  - admins can reset another user's password from `/settings/admin`
  - admins can now switch registration policy from `/settings/admin` with `default / open / invite_only / closed`
  - disabled users are blocked from login and their existing sessions are revoked immediately
  - the last active admin is now protected from being disabled accidentally
  - self-delete also preserves the same safety invariant: if other accounts still exist, the last active admin cannot delete itself

### Docker deployment baseline

- Added first-class Docker deployment files for server hosting:
  - root `Dockerfile.api`
  - root `Dockerfile.web`
  - root `docker-compose.yml`
  - root `docker-compose.prod.yml`
  - nginx gateway config under `deploy/nginx/default.conf`
  - Caddy config under `deploy/caddy/Caddyfile`
  - `.dockerignore` and `.env.docker.example`
- Deployment model is now:
  - `api` container runs FastAPI and continues to spawn the detached worker subprocess inside the same image
  - `web` container runs the Next.js production server
  - `gateway` container exposes a single website entrypoint and proxies `/api/*` plus SSE traffic to the API
- Next.js is now configured for `output: "standalone"` with monorepo-aware output tracing, which makes Docker web runtime images smaller and easier to ship.
- Frontend API base-url handling now supports a `same-origin` mode so the web app can be deployed behind one reverse proxy without hardcoding a separate public API origin.
- README and env examples now document the Docker deployment path and the new deploy-oriented env vars.
- Added a first-pass admin console for deployed environments:
  - `GET /api/admin/users`
  - `GET /api/admin/invites`
  - `POST /api/admin/invites`
  - `POST /api/admin/invites/{inviteId}/disable`
  - `POST /api/admin/users/{userId}/role`
  - frontend route: `/settings/admin`
- Admin invite records now persist in state storage, so invite-only registration survives restarts and Docker redeploys.
- Docker API runtime now trusts forwarded proxy headers, which keeps HTTPS deployments from misclassifying cookie security when a reverse proxy sets `X-Forwarded-Proto`.
- Login redirect handling now sanitizes the `next` parameter so post-login navigation only returns to in-site paths.
- Added Docker-oriented ops helpers:
  - `./scripts/docker_deploy.sh`
  - `./scripts/docker_deploy_prod.sh`
  - `./scripts/docker_preflight_check.sh`
  - `./scripts/docker_bootstrap_admin.sh`
  - `./scripts/docker_backup_state.sh`
  - `./scripts/docker_restore_state.sh`
- Added deploy/runbook docs under `deploy/` for server rollout and backup recovery.
- The recommended public deployment path now uses bundled Caddy for automatic HTTPS and can bootstrap the first admin before opening the public entrypoint.
- Docker deploy scripts now generate a merged runtime env file before `docker compose up`, so CLI/env overrides used for local smoke runs also reach the API container instead of only affecting proxy/build-time settings.
- Runtime settings UX now makes account isolation explicit instead of describing runtime config as a shared global default:
  - `/settings/runtime` now clearly states that API keys, base URLs, and models are saved per account
  - added an API regression test that verifies two users can save different runtime configs without overwriting each other
- Runtime settings now include brand/platform presets on top of the existing provider model:
  - MiniMax domestic / global
  - OpenAI official
  - OpenRouter
  - DeepSeek
  - Alibaba Cloud DashScope (Beijing / Singapore)
  - Moonshot Kimi
  - Tencent Hunyuan
  The form now auto-fills common base URLs and recommended model IDs while keeping fields manually editable.
- Research job API responses are now normalized defensively before FastAPI response validation:
  - `quality_score_summary` is forced to a dictionary on create/list/get paths
  - added a regression assertion to the create-job route test so `POST /api/research-jobs` will not regress back to `500 Internal Server Error` when old/partial job payloads contain `None`

## 2026-04-06

### Cooperative job cancel / health / clearer failure feedback

- Added cooperative research-job cancellation instead of forcing users to wait for a failing job to time out:
  - new API route: `POST /api/research-jobs/{jobId}/cancel`
  - service-level cancellation state is persisted on the job record with `cancel_requested`, `cancellation_reason`, and `status=cancelled`
  - detached workers stop cooperatively by reading persisted cancellation state during execution instead of being hard-killed
- Added API health reporting:
  - new endpoint: `GET /api/health`
  - returns `active_job_count`, `active_detached_worker_count`, `runtime_configured`, and `timestamp`
- Frontend workbench usability improved around long-running / failing jobs:
  - job stream now accepts `job.cancelled`
  - workbench dashboard exposes a `取消任务` action for active jobs
  - job-level `latest_error` and `cancellation_reason` are surfaced directly instead of only living in logs
  - execution mode and detached worker metadata are now visible in the dashboard
  - homepage now shows compact API health status and distinguishes cancelled jobs from failed ones visually
- Failure feedback is clearer now:
  - background execution failures now write `latest_error` on the job record
  - no-evidence failures already keep a diagnostic draft, and the UI now actually surfaces the job-level reason
- Added tests for:
  - `POST /cancel`
  - `GET /api/health`
  - workflow cancellation not being misclassified as `failed`

### Detached worker / workspace install fix

- Research jobs no longer run inside the API server as `threading.Thread(daemon=True)`.
- `ResearchJobService.create_job(...)` now launches a detached `pm_agent_api.worker_entry` subprocess, which lets long-running research continue even if the API process restarts.
- Job state and SSE events are now mirrored to disk:
  - REST reads refresh jobs/assets from persisted state
  - `/api/stream/jobs/{jobId}` can consume both in-memory fan-out and persisted event files
  - orphaned active jobs still fail closed, but active jobs with a live detached worker no longer get mis-recovered as failed
- Frontend stream handling now explicitly accepts `report.finalize_blocked`, so blocked finalization is visible without waiting for fallback polling.
- `apps/web/package.json` local workspace dependencies were switched to `file:` references so both `npm` and `pnpm` install the monorepo correctly instead of `pnpm` trying to fetch private workspace packages from npm.
- Added tests for:
  - detached worker launch metadata
  - cross-process repository refresh
  - cross-process `report.finalize_blocked` SSE delivery
  - live detached-worker job recovery on repository reload

### Usability hardening loop

- PM Chat was upgraded into a much more usable composer:
  - textarea input instead of single-line only
  - IME-safe `Enter` send / `Shift+Enter` newline behavior
  - optimistic user-message append with rollback on failure
  - realtime-vs-polling status cues
  - starter prompt chips
  - empty-state guidance when the conversation has not started yet
- Research workbench resilience improved:
  - if PM Chat session bootstrap fails, the report/evidence workbench still loads and chat degrades to read-only instead of taking down the whole page
  - sticky workbench navigation now exposes current phase, progress, connection mode, and tab-level counts
- New research form is now harder to break with bad input:
  - empty topic validation
  - numeric draft sanitization and range checks
  - clearer runtime-status error and degraded-mode warning
- Runtime settings became safer for real editing:
  - provider switches preserve unsaved drafts
  - dirty-state is visible
  - saved config can be restored without reload
  - validation catches empty/duplicate backup URLs before save/test
- Direct chat-session page now refetches session + assets + job together when the stream becomes healthy, closing a stale-context gap on reconnect.
- Evidence explorer now shows active-result count, supports clearing claim focus, and exposes a single-click clear-filter path.
- Report reader and full report page now have stronger empty states and auto-correct invalid stale `version` params.
- Added iterative desktop handoff snapshots under `-优化快照` so future agents can resume by round instead of reverse-engineering the entire conversation.
- App shell and launch flow received another usability pass:
  - top navigation now highlights the active route
  - shell spacing is friendlier on mobile
  - API switcher is now a compact connection panel instead of a permanently expanded header control
  - switching API base URL refreshes active data without a hard reload
  - React Query no longer pointlessly retries known 4xx API failures by default
  - command center can reopen the latest job for a given workflow template
  - new research defaults were softened from heavy demo-style values to a more realistic first-use starting point, and the form now has an explicit `重置草稿` action

### SSE fan-out / realtime consistency fix

- Fixed a real SSE architecture bug where each research job only had a single shared event queue. Under that design, multiple subscribers to the same job would compete for events, so opening the workbench and report/chat pages for the same job at the same time could make one tab “steal” updates from another.
- `InMemoryStateRepository` now keeps:
  - a history queue for tests and internal inspection
  - a separate per-job subscriber list for live stream fan-out
- `publish_job_event(...)` now broadcasts each event to all active stream subscribers instead of delivering it to only one consumer.
- `ResearchJobService.stream(...)` now subscribes/unsubscribes explicitly instead of directly draining the shared history queue, which makes multi-tab realtime behavior correct.
- Added API tests covering multi-subscriber fan-out and unsubscribe behavior.

### Stream-open resync fix

- `research-job-live-page.tsx` now performs a one-time refetch when the SSE stream becomes healthy, matching the safer behavior already used by the report/chat live pages.
- This closes the “stream connected after initial fetch” race where an event emitted during the connection window could leave the workbench briefly stale until the next event or fallback polling cycle.

### Web validation script cleanup

- The web workspace `typecheck` script no longer reuses `next build` as a fake type-check command.
- It now runs `tsc --noEmit -p tsconfig.json`, which avoids flaky `.next` build-artifact failures during `npm run check` and makes the intent of the script match its name.
- The root `package.json` scripts were aligned with that split again:
  - `typecheck:web` now runs workspace type-checking
  - `check:web` now runs lint + typecheck + production build instead of collapsing everything into build-only behavior

## 2026-04-02

### Source credibility / citation layer

- Evidence records now carry `source_domain`, `source_tier`, `source_tier_label`, and `citation_label`, so the same source can be referenced consistently across evidence review, report composition, and full-report reading.
- Synthesizer dossier construction now includes source-tier distribution and a `citation_registry`, and argument chains now pass citation labels plus source-tier cues into final composition.
- Fallback report generation now produces stronger citation feel:
  - key evidence tables include source labels and trust tiers
  - section-level “判断依据” lines now show `[Sx] + domain + tier`
  - core fallback claims can append inline source notes such as `（见 [S1]）`
- Full report page and in-workbench report reader now expose a visible source index so users can jump from report references back to the underlying evidence more naturally.
- Evidence explorer was redesigned into a more legible research ledger view with:
  - source-tier filtering
  - citation labels
  - domain display
  - quote / extraction blocks
  - confidence, authority, and freshness cues

### Delta research stability / deeper fallback writing

- Delta research now has an explicit timeout/fallback path. If the chat-triggered补研搜索 stalls or fails, the system now falls back quickly to conservative report-context guidance instead of hanging the test or the chat update path.
- The `ChatServiceDeltaResearchTest` path was isolated from live network behavior, and full worker resilience tests now run cleanly again.
- Search scoring received another intent-alignment pass so `official`, `community`, `comparison`, and `pricing` style queries rank more fitting source types ahead of mismatched pages.
- Fallback report writing now expands `argument_chains` into fuller paragraph-level reasoning, so degraded reports still read more like a professional research note than a sparse checklist.

### UX cleanup from real usage pass

- The new research page was still shipping with obvious English leakage such as `New Research` and English workflow-command descriptions. The command-center presets and new-research title are now Chinese-first.
- Runtime settings copy was cleaned so OpenAI-compatible routing is described in Chinese rather than mixed-language UI strings.
- `site:` search behavior is now stricter: if a query explicitly targets a domain and the result set contains matching-domain results, off-site hits are discarded instead of being merely down-ranked.
- Worker-side low-signal filtering now also rejects off-site hits on `site:` queries, which closes a real-world failure mode where searches like `site:capterra.com ...` could still end up capturing unrelated Zhihu pages.

### Chinese deliverable / report rewrite refresh

- Report composition now uses the structured research dossier as a writing context and asks the LLM to rewrite a complete Chinese report, instead of encouraging field-by-field transcription of structured assets.
- Canonical report section headings are now Chinese-first, with compatibility aliases kept so older English-heading report versions still render and can still be cited by PM Chat.
- Final composition metadata now marks the result as `llm-dossier-rewrite` to distinguish it from older explicit compose behavior.
- PM Chat, report utilities, and report-history browsing were updated together so old and new report versions can still be reopened safely.

### Search quality / argument density pass

- Search result scoring now penalizes listicles, roundups, low-value navigation pages, off-site misses on `site:` queries, and obviously stale or weakly aligned results more aggressively.
- Search diversification now drops very low-score results once a usable result set already exists, which reduces generic filler pages entering evidence collection.
- Research worker low-signal gating now rejects listicle-style results for non-comparison tasks more aggressively while preserving the snippet-fallback path for fetch failures.
- Report dossier now includes `argument_chains`, which package claim, supporting evidence, PM implication, and usage boundary into a writing-friendly structure for synthesis.
- Fallback report generation now adds clearer “判断依据” support lines so degraded/fallback reports still carry a visible reasoning chain instead of sparse conclusions.

### Frontend localization / reading polish

- Cleaned up remaining obvious English frontend labels in the home page, job dashboard, PM Chat badges, and demo content.
- Report rendering now uses a more formal Chinese reading style with improved typography, section framing, and paper-like presentation.
- PM Chat now exposes direct links back to the full report page so users can review the exact active report context while chatting.

### API error clarity / runtime verification

- API connection failures now show a more helpful message with the active base URL, retry candidates, and a direct hint to check backend startup or runtime settings.
- Re-verified Python worker tests, frontend TypeScript, and production web build after the report-system changes.
- Real runtime smoke test passed with:
  - API responding on `http://127.0.0.1:8000/api/runtime`
  - web responding on `http://127.0.0.1:3002/`

### Research runtime overhaul

- Upgraded search from simple query fan-out to a more deliberate deep-research loop in `apps/worker/pm_agent_worker/agents/research_worker_agent.py`.
- Search now works through query coverage, search waves, gap-fill queries, diversity checks, and sufficiency checks instead of stopping after a shallow first pass.
- Search preferences now bias by task intent and source type, with stronger filtering of low-signal result pages.
- Evidence collection now preserves progress and coverage state on the task record, so the UI can show what the sub-agent is trying to cover.

### Command / memory / orchestration layer

- Added `workflow_command` as a first-class job input and persisted job field.
- Added `project_memory` so a run can carry persistent steering context across planning, synthesis, and chat.
- Added orchestration presets in `packages/research-core/data/orchestration-presets.json`.
- Planner now injects:
  - command metadata
  - search intents
  - completion criteria
  - skill packs
  - orchestration notes
- Command center UI was added to the home page and new research flow so launch-time mode selection is explicit.

### Skill runtime activation

- `skill_packs` are no longer passive metadata.
- Skill packs now actively affect:
  - fallback query generation
  - query ranking
  - search wave ordering
  - required query coverage
  - coverage targets
  - gap-fill query generation
  - research sufficiency checks
- Added visible skill-runtime state on task detail views:
  - active themes
  - covered tags
  - missing tags
  - signal mix
  - remaining skill targets

### Report system upgrade

- Reporting moved from a single raw markdown blob to a multi-asset report model.
- Report assets now include:
  - `board_brief_markdown`
  - `executive_memo_markdown`
  - `conflict_summary_markdown`
  - `appendix_markdown`
  - `decision_snapshot`
- Added explicit report stages and versioning behavior so multiple rounds of “成文” can coexist cleanly.
- Added complete report page and report history browsing.
- PM Chat remains anchored to the currently active composed report instead of drifting onto raw intermediate context.

### Report quality upgrade

- Synthesizer now writes in a more consulting-style, decision-oriented structure.
- Reports more explicitly separate:
  - current view
  - PM implication
  - strongest evidence
  - validation boundary
- Added a new default report-first reading mode: `决策简报`.
- Report views now support:
  - 决策简报
  - 管理摘要
  - 完整报告
  - 冲突与边界
  - 附录

### Runtime resilience / connectivity

- Added backup API connection support so the runtime can fail over when one upstream stalls.
- Runtime settings support OpenAI-compatible providers and preserve masked API state.
- Search, assets, jobs, and chat session state persist under `output/state`.
- Restarts preserve history rather than silently wiping progress, although interrupted active jobs still require a fresh rerun to finish.

### UX / launch improvements

- Added generic stack start/stop scripts and desktop wrappers in the repo root.
- Startup flow now prefers system `python3` / `node` / `npm` and supports env overrides.
- Web/API port selection is more tolerant when defaults are already occupied.
- Report reading and task detail views now expose more of the real agent process instead of raw markdown-only state.

### Tests and verification

- Expanded `apps/worker/tests/test_runtime_resilience.py` to cover:
  - planner / orchestration behavior
  - search fallback behavior
  - skill-aware search behavior
  - report finalization and versioning
  - runtime failover behavior
- Latest verified checks:
  - `python3 -m py_compile ...`
  - `./node_modules/.bin/tsc -p apps/web/tsconfig.json --noEmit`
  - `python3 -m unittest apps/worker/tests/test_runtime_resilience.py`

## Current open follow-ups

- Improve full report page visual design further so it feels closer to a polished research deliverable than a workbench panel.
- Continue improving vertical source quality and freshness handling for search.
- Consider true resumable active-job recovery after restart instead of interruption-only preservation.
- Consider richer agent observability for multi-round orchestration and report composition history.
