# PM Research Agent — Detailed Handoff

This document is a deeper handoff for future agents. It complements `README.md` and `AGENTS.md`.

Snapshot date: 2026-04-06

## 0. Fast Resume Path

If you are a new agent taking over, read in this order:

1. `PROJECT_HANDOFF.md`
2. `CHANGELOG.md`
3. desktop round snapshots in `-优化快照`

The desktop snapshot directory is now part of the working process. Each optimization round should leave a markdown breadcrumb there so another agent can resume without reconstructing the whole session from chat logs.

## 1. What This Repo Is

This is a PM-oriented research workbench monorepo. The product loop is:

1. User launches a research job from the web UI.
2. API creates a persisted research job and hands execution to a detached worker subprocess.
3. Worker plans tasks, collects evidence, verifies claims, and synthesizes a report.
4. PM Chat uses `report + claims + evidence + chat history` as the conversation context.
5. If the current report is insufficient, PM Chat triggers targeted delta research.
6. Delta outputs are merged into structured assets first, then can be explicitly recomposed into a newer report version.

The project is now closer to a real PM delivery workflow than a one-shot markdown generator.

## 2. Repo Layout

- `apps/web`
  Next.js app for the command center, workbench, report page, PM Chat, runtime settings.
- `apps/api/pm_agent_api`
  FastAPI app, REST routes, SSE stream route, in-memory/persisted state repository, service layer.
- `apps/worker/pm_agent_worker`
  Workflow engine, planner, research worker, verifier, synthesizer, dialogue logic, browser/search tools.
- `packages/types`
  Shared TypeScript DTOs and JSON schema.
- `packages/ui`
  Shared UI components.
- `packages/research-core`
  Industry templates, steps, orchestration presets.
- `packages/config`
  Shared default budgets, presets, and limits.
- `packages/prompts`
  Prompt templates for planner / worker / verifier / synthesizer / dialogue.
- `packages/browser`
  Browser adapter contract and related integration surface.
- `output/state`
  Persisted jobs, assets, chat sessions, runtime settings.

Notes:

- In this environment, `` is not a git repo.
- There is a noisy `__MACOSX/` directory in the root. Ignore it for product work.

## 3. Current Architecture

### 3.1 Backend

Main entrypoints:

- `apps/api/pm_agent_api/main.py`
- `apps/api/pm_agent_api/routes/research_jobs.py`
- `apps/api/pm_agent_api/routes/chat.py`
- `apps/api/pm_agent_api/routes/streams.py`

Core services:

- `apps/api/pm_agent_api/services/research_job_service.py`
- `apps/api/pm_agent_api/services/chat_service.py`
- `apps/api/pm_agent_api/repositories/in_memory_store.py`

Important behavior:

- Jobs, assets, chat sessions, and runtime config are persisted to disk.
- Research jobs now run in a detached subprocess (`pm_agent_api.worker_entry`) instead of a daemon thread inside the API process.
- Active research jobs can now be cancelled via `POST /api/research-jobs/{jobId}/cancel`, and workers stop cooperatively from persisted cancel state.
- Job events are persisted to disk as well as fanned out in-memory, so SSE can survive cross-process worker execution.
- API reads job/assets state back from disk on access, which keeps REST reads in sync with detached worker progress.
- `/api/health` now reports active jobs, active detached workers, runtime configuration state, and timestamp.
- Runtime config writes are atomic and invalid JSON is quarantined instead of silently reused.
- If the API restarts while a detached worker is still alive, the job stays active; only orphaned active jobs are recovered as failed.
- CORS defaults are tightened to loopback origins; explicit origins come from `PM_AGENT_CORS_ORIGINS`.
- `create_app()` exists, so API tests can build isolated app instances cleanly.

### 3.2 Worker / Research Flow

Important files:

- `apps/worker/pm_agent_worker/workflows/research_workflow.py`
- `apps/worker/pm_agent_worker/agents/research_worker_agent.py`
- `apps/worker/pm_agent_worker/agents/verifier_agent.py`
- `apps/worker/pm_agent_worker/agents/synthesizer_agent.py`
- `apps/worker/pm_agent_worker/agents/dialogue_agent.py`

Current flow:

1. Planner builds task list from topic, workflow command, and project memory.
2. Research worker runs search waves, coverage checks, gap-fill queries, and evidence collection.
3. Verifier builds structured claims from evidence.
4. Synthesizer creates a report system:
   - full report
   - board brief
   - executive memo
   - appendix
   - conflict summary
   - decision snapshot
5. PM Chat answers from current report context.
6. Delta research adds structured assets and marks report stage as `feedback_pending`.
7. Explicit finalization recomposes a new report version and preserves history.

## 4. Frontend Architecture

Main pages/components:

- `apps/web/features/research/components/home-dashboard.tsx`
- `apps/web/features/research/components/new-research-form.tsx`
- `apps/web/features/research/components/research-job-live-page.tsx`
- `apps/web/features/research/components/research-workbench.tsx`
- `apps/web/features/research/components/report-reader.tsx`
- `apps/web/features/research/components/research-report-page.tsx`
- `apps/web/features/research/components/pm-chat-panel.tsx`
- `apps/web/features/research/components/chat-session-live-page.tsx`
- `apps/web/features/research/components/workflow-command-center.tsx`

Shared infra:

- `apps/web/lib/api-client.ts`
- `apps/web/lib/api-base-url.ts`
- `apps/web/lib/polling.ts`
- `apps/web/features/research/hooks/use-research-job-stream.ts`

Current UI model:

- Homepage acts as a command center plus history view.
- Workbench has tabs for dashboard, evidence, report, and chat, plus a sticky status-aware navigation strip.
- Workbench dashboard now exposes job-level failure/cancellation feedback, execution-mode diagnostics, and a direct `取消任务` action for active jobs.
- Full report page is a dedicated delivery surface with version browsing.
- PM Chat stays anchored to the active composed report version and now supports optimistic send, IME-safe enter handling, and starter prompts.
- Runtime settings preserve per-provider draft edits locally instead of wiping unsaved inputs on provider switch.

## 5. Realtime Model

This area changed significantly and is important for future agents.

### 5.1 Old model

The app previously depended mainly on React Query polling for:

- job state
- assets
- chat session
- report readiness

This worked, but it was wasteful and made the UI feel less live.

### 5.2 Current model

The frontend now uses SSE as the primary realtime source and keeps polling only as a fallback.

Main file:

- `apps/web/features/research/hooks/use-research-job-stream.ts`

What it does:

- connects to `/api/stream/jobs/{jobId}`
- tries API base URL candidates from `api-base-url.ts`
- updates React Query caches directly
- reconnects when the stream drops
- sets `shouldPoll` to `false` when the stream is healthy
- accepts `job.cancelled` and `report.finalize_blocked` in addition to finalized / delta / task events

Backend note:

- SSE now reads from both in-memory event fanout and persisted per-job event files.
- This matters because research execution now happens in a detached subprocess, not inside the API process.

It currently updates these cache families:

- `["research-job", jobId]`
- `["research-assets", jobId]`
- `["chat-session-job", jobId]`
- `["chat-session-assets", jobId]`
- `["research-jobs"]`
- `["chat-session", sessionId]`
- `["chat-session-page", sessionId]`

### 5.3 Pages already migrated to stream-first

- `apps/web/features/research/components/research-job-live-page.tsx`
- `apps/web/features/research/components/chat-session-live-page.tsx`
- `apps/web/features/research/components/research-report-page.tsx`

Related UI consumers also now assume `realtimeConnected` can be passed in:

- `apps/web/features/research/components/research-workbench.tsx`
- `apps/web/features/research/components/report-reader.tsx`
- `apps/web/features/research/components/pm-chat-panel.tsx`

### 5.4 Backend event payloads

Delta chat events now carry enough session context for the frontend to update PM Chat without a full session re-fetch in many cases.

Important file:

- `apps/api/pm_agent_api/services/chat_service.py`

Key detail:

- `_build_delta_event_payload(...)` now normalizes payloads for:
  - `delta_research.started`
  - `delta_research.completed`
  - `delta_research.failed`

These payloads include:

- `delta_job_id`
- `question`
- `session_id`
- `session` when available
- plus `job/assets/message/error/claim_id` when relevant

This is the main reason SSE-based PM Chat sync works cleanly now.

## 6. Data / State Concepts

Important shared types live in:

- `packages/types/src/index.ts`

Key records:

- `ResearchJobRecord`
- `ResearchAssetsRecord`
- `ChatSessionRecord`
- `ReportAssetRecord`
- `ReportVersionRecord`

Important fields future agents should respect:

- `workflow_command`
- `workflow_label`
- `project_memory`
- `runtime_summary`
- `latest_error`
- `cancel_requested`
- `cancellation_reason`
- `execution_mode`
- `background_process`
- `report_version_id`
- `report.stage`
- `report.feedback_notes`
- `report_versions`
- `citation_label`
- `source_tier`
- `source_tier_label`
- `triggered_delta_job_id`

Current report stages commonly seen:

- `draft`
- `feedback_pending`
- `final`

## 7. Recent High-Value Fixes Already Landed

### Stability / correctness

- Background thread crashes now mark jobs failed instead of hanging forever.
- Research runs now fail honestly when no evidence is collected.
- Runtime config persistence moved away from unsafe repo-default behavior.
- Runtime config JSON writes are atomic.
- Corrupt state files are quarantined.
- Start script port selection order was fixed.

### API / platform

- App factory `create_app()` added.
- CORS defaults tightened to loopback origins.
- API route tests expanded.

### Frontend / UX / accessibility

- `Button` gained `asChild`.
- Invalid nested interactive markup like `<a><button>` was removed.
- Polling logic became terminal-state aware.
- Progress bar accessibility improved.
- Workflow command center moved away from `div role="button"` to a more correct button/radiogroup pattern.
- PM Chat was upgraded from a thin input row to a more usable composer:
  - textarea input
  - `Enter` to send
  - `Shift+Enter` for newline
  - IME-safe send handling
  - optimistic user-message append with rollback on failure
  - quick starter prompts
  - chat-only degradation if session bootstrap fails, instead of crashing the whole workbench
- New research form now has real launch guardrails:
  - empty topic validation
  - numeric draft sanitization instead of raw `Number(...)`
  - clearer runtime-status warnings and retry path
- Runtime settings page now behaves more like a real config surface:
  - per-provider unsaved draft preservation
  - dirty-state badge
  - restore-saved-config action
  - pre-save validation for base URL / timeout / backup URL duplication
- Homepage now has a stronger “continue current work” path with manual refresh, last-sync time, and faster access back into active jobs.
- Evidence explorer now exposes active result count, claim-focus banner, clear-filter action, and an explicit escape hatch from claim-linked mode.
- Full report page now corrects stale invalid `version` params automatically instead of leaving dead URLs in place.
- Report reader and full report surface now show empty states in places that previously failed silent, such as missing claims or source index data.
- App shell usability was improved further:
  - active nav highlighting in the top bar
  - tighter mobile spacing in header/main shell
  - API switcher moved from always-expanded inline control to a compact connection panel
  - API switching now refreshes data without forcing a full page reload
- Query behavior is now less noisy for known failures:
  - React Query no longer retries 400/401/403/404 API failures by default
  - mutation retries are disabled by default
- New research launch defaults are now closer to real first-use behavior:
  - blank topic
  - standard preset
  - lighter default scope
  - explicit `重置草稿` action
- Workflow command center can now reopen the latest job that used the same command template, which helps users continue a previous research lane instead of always starting over.

### Realtime

- Stream-first cache sync is now in place for core live pages.
- Delta research SSE payloads now include session snapshots.
- Report finalization and PM Chat interactions now write more directly into cache and rely less on broad invalidation.

## 8. Known Gaps / Opportunities

These are good next targets if another agent continues:

1. `home-dashboard.tsx` still primarily uses polling for the jobs list.
2. Browser automation is still limited unless `opencli` exists.
3. Search quality can still improve with stronger vertical source adapters and evidence normalization.
4. The report page is much better now, but there is still room to push it further toward a polished “deliverable” feel.
5. Some PM Chat / report interactions still use targeted invalidation when stream-first direct cache updates could be pushed further.
6. Homepage jobs list is more usable now, but it still does not have a dedicated list-level realtime stream.
7. The API switcher still does not actively call `/api/health` before switching candidates, even though the endpoint now exists.
8. Pause/resume is still not implemented; current control surface supports cancel only.

## 9. Important Tests And Commands

Root scripts:

- `npm run lint:web`
- `npm run build:web`
- `npm run test:api`
- `npm run test:worker`
- `npm run check`

Useful direct commands:

```bash
./scripts/start_stack.sh
./scripts/run_api.sh
npm run check
python3 -m unittest discover -s apps/api/tests -v
python3 -m unittest discover -s apps/worker/tests -v
```

Current validated state before this handoff:

- `npm run lint:web` passed
- `npm run build:web` passed
- `npm run test:api` passed
- `npm run test:worker` passed
- `npm run check` passed
- `python3 -m unittest apps/api/tests/test_api_routes.py -v` passed
- `python3 -m unittest apps/worker/tests/test_runtime_resilience.py -v` passed
- `npm --prefix apps/web run typecheck` passed
- `python3 -m py_compile` passed on the touched API / worker files

Current caveat:

- I did not rerun a full web production build in this round because touching `apps/web/.next` while a local stack may already be serving can recreate the build/process mismatch that previously broke port `3000`.

Note:

- Worker tests intentionally print mocked traceback output for failure-handling scenarios. That output is expected when the suite still ends with `OK`.
- Run frontend validation serially. Do not overlap build-like commands that touch `.next`.
- Safe pattern when things look odd:
  - `rm -rf apps/web/.next`
  - `npm run build:web`
  - or `npm run check`

## 10. Runtime / Machine Notes

- `.env` may contain real credentials. Do not print or copy secrets into logs or docs.
- The MiniMax regional base URL matters; wrong region can look like a code bug.
- `opencli` is not guaranteed to exist on the machine.
- State is persisted under `output/state`.

## 11. Suggested Read Order For A Future Agent

If you are picking up work fresh, read these in order:

1. `PROJECT_HANDOFF.md`
2. `AGENTS.md`
3. `CHANGELOG.md`
4. latest round snapshot in `-优化快照`
5. `README.md`
6. Then the feature-area files you are about to edit

If working on realtime:

1. `apps/web/features/research/hooks/use-research-job-stream.ts`
2. `apps/api/pm_agent_api/services/chat_service.py`
3. `apps/api/pm_agent_api/services/research_job_service.py`
4. `apps/web/features/research/components/research-job-live-page.tsx`
5. `apps/web/features/research/components/chat-session-live-page.tsx`
6. `apps/web/features/research/components/research-report-page.tsx`

If working on report composition:

1. `apps/worker/pm_agent_worker/workflows/research_workflow.py`
2. `apps/api/pm_agent_api/services/research_job_service.py`
3. `apps/web/features/research/components/report-reader.tsx`
4. `apps/web/features/research/components/research-report-page.tsx`
5. `apps/web/features/research/components/report-version-utils.ts`

If working on PM Chat:

1. `apps/api/pm_agent_api/services/chat_service.py`
2. `apps/worker/pm_agent_worker/agents/dialogue_agent.py`
3. `apps/web/features/research/components/pm-chat-panel.tsx`
4. `apps/web/features/research/components/chat-session-live-page.tsx`

## 12. Handoff Summary

The project is in a healthier state than before:

- persistence and failure handling are less fragile
- the report workflow is more explicit and versioned
- PM Chat is better grounded in report context
- frontend live pages now behave more like a realtime app than a polling dashboard
- active jobs can now be cancelled explicitly instead of waiting for timeout/failure
- health state and job-level failure reasons are visible in both API and UI

If you continue from here, prefer extending the stream-first architecture instead of reintroducing broad polling.
