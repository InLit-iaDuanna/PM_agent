# PM Research Agent — Quick Context

This file applies to the whole repository.

## Project Summary

- This repo is a PM-oriented research workbench monorepo.
- Root path: the current repository root; resolve commands relative to the repo instead of assuming a machine-specific absolute path
- The repo is currently **not a git repository** in this environment.
- Main user flow:
  1. Create a research job in the web UI
  2. API starts a background research workflow
  3. Workflow collects evidence, builds claims, and synthesizes a report
  4. PM Chat uses `report + claims + evidence + chat history` as context
  5. If context is insufficient, PM Chat triggers delta research and appends results back into the report

## Repo Structure

- `apps/web` — Next.js frontend
- `apps/api/pm_agent_api` — FastAPI backend
- `apps/worker/pm_agent_worker` — research workflow, agents, tools
- `packages/types` — shared TS types
- `packages/research-core` — research templates and steps
- `packages/prompts` — LLM prompt templates
- `packages/config` — default limits and presets

## Important Runtime Facts On This Machine

- `.env` now uses a **real local MiniMax credential** (do not print or commit it) and the **China endpoint** `MINIMAX_BASE_URL=https://api.minimaxi.com/v1`.
- For this machine/account, using the international endpoint `https://api.minimax.io/v1` returns `401 Unauthorized`; use the China endpoint above for real LLM calls.
- `opencli` is **not installed** on this machine right now.
- Browser fallback uses the system opener when available (`open` / `xdg-open` depending on environment).
- Startup scripts now prefer system `python3` / `node` / `npm` and only rely on repo-local runtimes if you explicitly point to them with env vars.
- Research jobs / assets / chat sessions now persist under `output/state`; restarting the API keeps history, but any job that was mid-run during restart is marked as interrupted and needs a fresh rerun if you want completion.

## Commands

### Full-stack start

- `./scripts/start_stack.sh`
- Desktop wrapper: `./PM Research Agent.command`

### API

- `./scripts/run_api.sh`

### Worker tests

- `python3 -m unittest discover -s apps/worker/tests -v`

### Web build

- `./scripts/bootstrap_frontend.sh`

## Key Files

### Research flow

- `apps/worker/pm_agent_worker/workflows/research_workflow.py`
- `apps/worker/pm_agent_worker/agents/research_worker_agent.py`
- `apps/worker/pm_agent_worker/agents/verifier_agent.py`
- `apps/worker/pm_agent_worker/agents/synthesizer_agent.py`
- `apps/worker/pm_agent_worker/agents/dialogue_agent.py`

### API services

- `apps/api/pm_agent_api/services/research_job_service.py`
- `apps/api/pm_agent_api/services/chat_service.py`

### Frontend

- `apps/web/features/research/components/research-job-live-page.tsx`
- `apps/web/features/research/components/report-reader.tsx`
- `apps/web/features/research/components/research-report-page.tsx`
- `apps/web/features/research/components/pm-chat-panel.tsx`
- `apps/web/features/research/components/task-detail-panel.tsx`
- `apps/web/features/research/components/workflow-command-center.tsx`
- `apps/web/lib/api-client.ts`

## Current Behavior / Recent Fixes

- Launch flow now centers around `workflow_command` and `project_memory`, so runs can be steered more deliberately from the start.
- Planner now assigns task-level `skill_packs`, `search_intents`, `completion_criteria`, `command_label`, and orchestration notes.
- Research worker now has a real skill runtime:
  1. skill packs bias query generation
  2. they can frontload certain query types into earlier search waves
  3. they expand required coverage
  4. they add skill-aware gap-fill search when coverage is weak
  5. they affect sufficiency checks before a task stops searching
- Task detail UI now exposes skill-runtime observability such as:
  - active themes
  - covered query tags
  - missing tags
  - signal mix
  - remaining skill targets
- Search now merges DuckDuckGo HTML + Bing results, deduplicates URLs, applies task-specific source preferences, and keeps domain diversity before fetching pages.
- Search result scoring is now stricter about low-value pages:
  - listicles / roundup pages are penalized harder
  - weak off-site hits on `site:` queries are penalized
  - stale year markers and low-information navigation pages are downgraded
  - once enough decent results exist, very low-score filler results are dropped
- Search result filtering now drops obvious ad / tracking / redirect URLs before evidence collection.
- When page fetch fails, the worker still keeps snippet-based evidence instead of returning an empty report.
- The worker is now **LLM-first** during collection: it uses the LLM to generate search queries and normalize source content into evidence records.
- Fallback claim verification no longer marks everything as `disputed`; it now uses conflict signals plus confidence.
- Planner task generation now uses a corrected `category -> market_step` mapping instead of relying on index order.
- PM Chat now follows a **report-first loop**:
  1. research workflow produces a **report draft**
  2. PM Chat uses `report + claims + evidence + chat history` as primary context
  3. user feedback / uncovered questions trigger delta research
  4. report is revised into a longer **final report**
- Report composition is now intended to be **dossier rewrite**, not direct structured-data fill-in:
  1. claims/evidence/feedback become writing context
  2. the LLM rewrites a coherent Chinese report
  3. old report versions are kept for history, but PM Chat should anchor to the active composed version
- Greetings like `你好` should not trigger delta research anymore.
- PM Chat now blocks early conversation until the initial report draft exists; before that it explicitly tells the user to wait for draft generation.
- Delta research now revises the main report body, keeps a `## 补充问答` section for traceability, and bumps `report_version_id`.
- Delta research now tries real targeted search first; if no high-signal external source is found, it records an explicit report-context fallback instead of inventing fake web evidence.
- Delta research is now also explicitly time-bounded inside the workflow; if evidence collection stalls, it falls back to the conservative report-context path instead of hanging.
- Report assets now carry explicit stage metadata such as `draft_pending` / `draft` / `final`, plus revision and feedback counters.
- Report assets now include multiple reading surfaces:
  - `board_brief_markdown`
  - `executive_memo_markdown`
  - `conflict_summary_markdown`
  - `appendix_markdown`
  - `decision_snapshot`
- Report reading now defaults to a decision-brief-first flow instead of dumping users directly into raw markdown.
- Full report composition can be run multiple times; each pass keeps a report version snapshot and the full report page can browse those versions.
- Canonical report headings are now Chinese-first. When editing report utilities or PM Chat section extraction, preserve compatibility with old English-heading versions.
- Report dossier now includes `argument_chains`; if you improve synthesis quality further, prefer using that structure rather than re-reading raw claim/evidence arrays first.
- Competitor extraction is now based on evidence / LLM output; the old fake `Topic Competitor 1..N` placeholder pattern has been removed from the main workflow.
- If static fetch fails and a browser launcher is available, the worker auto-opens one failed page per task and marks that source as `opened_in_browser`.
- Job runtime summary now exposes whether MiniMax is really enabled, which model is selected, and which browser mode is active.
- Claim verification now distinguishes `confirmed / verified / directional / inferred / disputed` instead of collapsing everything into a binary verified-vs-inferred model.
- Claim synthesis now prefers cross-domain support evidence and stores `independent_source_count` so downstream reporting can reason about source diversity explicitly.
- Research sufficiency checks now enforce both independent-domain ratio and high-confidence-evidence ratio before a task is allowed to stop searching.
- Coverage snapshots now expose per-step domain counts, high-confidence evidence counts, and richer step-level diversity gaps for downstream diagnostics.
- Anchor search waves can now rewrite later validation waves using discovered competitors, claims, and topic-specific review domains instead of only replaying static query sets.
- Report dossier assembly now includes `section_sufficiency`, so each report section can decide whether it has enough external support to be fully written.
- Fallback report generation now suppresses low-evidence sections more aggressively and pushes those weak sections into the `待验证问题` backlog instead of pretending the material is complete.
- Draft workflow execution now has a bounded quality gate: if only a minority of dimensions are weak, it will run targeted supplemental collection before composing the report draft.
- Draft `quality_score_summary` now records real claim/domain counts plus `confirmed / verified / directional / disputed` breakdowns, rather than hardcoding empty placeholders.

## Known Gaps

- Without a valid MiniMax key **or the correct regional base URL**, PM Chat and other agents still fall back to deterministic behavior.
- Without a real `opencli` binary, browser control is limited to opening a URL in the default browser; no click/type/snapshot automation exists yet.
- Search quality is materially better now, but it can still be improved further with stronger vertical source adapters, richer freshness scoring, and more domain-specific evidence normalization.
- Search scoring now has a second-pass intent alignment layer:
  - `official` queries prefer docs/pricing/web and penalize community mismatches
  - `community` queries prefer forum/review sources
  - `pricing` queries strongly prefer actual pricing pages
- `site:` query handling is now stricter in two places:
  - the search provider discards off-site results when matching-domain results exist
  - the research worker treats off-site `site:` hits as low-signal and drops them before evidence extraction
- Chinese frontend cleanup is still ongoing, but the command-center preset labels and new-research entry surface are now Chinese-first. If you see English in the UI again, check:
  - `packages/research-core/data/orchestration-presets.json`
  - `apps/web/features/research/components/new-research-form.tsx`
  - `apps/web/features/research/components/runtime-settings-page.tsx`
- Evidence records now already carry citation and trust metadata:
  - `citation_label`
  - `source_domain`
  - `source_tier`
  - `source_tier_label`
  When improving report quality, prefer preserving and reusing these instead of inventing a second citation system.
- Active jobs are not resumable after a process restart; they are preserved as interrupted history instead of being continued automatically.
- The report page is much more usable now, but it still has room to feel more like a polished research deliverable and less like a tool panel.
- Startup verification in this environment succeeded when API and web were launched directly:
  - API: `http://127.0.0.1:8000/api/runtime`
  - Web: `http://127.0.0.1:3000/`

## Current architecture shorthand

Use this mental model when editing:

1. `Command`
   Launch-time operating mode selected in the command center
2. `Task`
   Planner breaks the run into focused subtasks
3. `Skill`
   `skill_packs` make each task search differently at runtime
4. `Memory`
   `project_memory` keeps steering context stable across planning, synthesis, and chat
5. `Orchestration`
   Search waves, coverage checks, gap-fill loops, versioned report composition, and PM-chat-driven delta research

## Recommended root docs to read first

If you are a future agent picking up work, read these in order:

1. `PROJECT_HANDOFF.md`
2. `CHANGELOG.md`
3. `AGENTS.md`
4. `README.md`
5. Then inspect the specific files in the feature area you are changing

## Fast Debug Checklist

If PM Chat feels “not connected”:

1. Check `./.env`
2. Verify `MINIMAX_API_KEY` is real and **do not print it in logs**
3. Verify `MINIMAX_BASE_URL` matches the account region; on this machine use `https://api.minimaxi.com/v1`
4. Run a direct MiniMax sanity check from `apps/worker`
5. Restart the API after changing `.env`
6. Create a **new** research job/session if you need a fresh recomputation; persisted history is kept, but interrupted runs are not resumed automatically

If browser automation feels “not working”:

1. Check whether `opencli` actually exists on disk
2. If installed outside PATH, set `OPENCLI_COMMAND=/absolute/path/to/opencli` in `.env`
3. Restart the API after changing `.env`
4. Remember: current code only auto-opens failed pages; full browser-agent control is not implemented yet

## Guidance For Future AI Helpers

- Prefer minimal, surgical edits; this repo is still in active iteration.
- Validate Python changes with worker tests.
- Validate web changes with `./scripts/bootstrap_frontend.sh` or `npm --prefix apps/web run build`.
- Do not assume LLM failures are code bugs before checking both the API key and the MiniMax regional base URL.
- Do not assume browser automation is available before confirming `opencli` exists.
- Preserve the intended product loop: **draft report first -> PM Chat on report context -> feedback-triggered delta research -> revised long final report**.
- If you touch report assets or versioning, update both the worker-side snapshot logic and the frontend report view utilities together.
- If you land a meaningful architecture or product behavior change, update `CHANGELOG.md` at the repo root so the next agent does not have to rediscover it.
