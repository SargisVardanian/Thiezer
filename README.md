# Thiezer

Deterministic Armenia-first newsroom + claim-first knowledge-graph core with explicit proposal, verification, critique, canonical admission, and publication stages.

## Core Loop

`ingest -> retrieve -> graph -> publish`

The graph stage now operates as:

`story -> claims/evidence/events -> graph safety verify -> critic -> canonical admission -> verified story pack`

## Task Runtime

Use these user-facing modes when you want the system to do the work for you:

- `python3 scripts/orchestrator.py ask --query "..."` for a bounded task route
- `python3 scripts/orchestrator.py background-sync` for a pipeline run plus exploration
- `python3 scripts/orchestrator.py graph-audit` for a safety-only graph check
- `python3 scripts/orchestrator.py graph-explore` for a budgeted link-expansion pass
- `python3 scripts/orchestrator.py deep-research` for topic-oriented expansion
- `python3 scripts/orchestrator.py ask --query "..." --deliver-public-telegram @thiezerarm --deliver-ops-telegram <chat_id>` to send public posts and operator trace via OpenClaw Telegram transport

## Canonical Data

- `content/graph/country-graph.json`
- `content/graph/evidence-log.jsonl`
- `content/graph/schema-v2.json`
- `content/graph/schema-v3.json`
- `content/graph/relation-types.json`
- `content/sources/source-registry.json`
- `content/sources/armenia-source-seed.json`
- `content/system/local-model-config.json`
- `content/prompts/prompt-stack.json`
- `content/evals/tasks.json`

## Prompt Roles

- `router`
- `news_research_analyst`
- `source_judge`
- `graph_proposer`
- `graph_critic`
- `writer`
- `social_operator`
- `graph_native_assistant`

## Run

- `python3 scripts/orchestrator.py health`
- `python3 scripts/orchestrator.py daily-sync`
- `python3 scripts/orchestrator.py ask --query "дай новости сегодня по Армении" --budget 2 --deliver-public-telegram @thiezerarm --deliver-ops-telegram 870013583`
- `python3 scripts/orchestrator.py background-sync --topic internal_politics --budget 4 --deliver-ops-telegram 870013583`
- `python3 scripts/run_graph_web.py` for the local graph explorer
- `python3 scripts/export_knowledge_graph.py` to rebuild the generated `web/graph-viewer/knowledge_graph.json` explorer payload; the viewer boots from this artifact and overlays live graph/runtime data when available

## Claim-First Model

- Articles do not write canonical edges directly.
- Articles produce `claims`, `evidence`, `sources`, and `events`.
- Only class-admitted claims can produce canonical `edges`.
- Rumors and disputed interpretations stay in `claims`, `perspectives`, and `narratives`, not in canonical edges.
- Viewer terminology is standardized around `вершины`, `рёбра`, `утверждения`, and `перспективы`.

## Eval

- `python3 scripts/eval_models.py smoke`
- `python3 scripts/eval_models.py run`
- `python3 scripts/eval_models.py report`

## Operator Artifacts

- `content/evals/latest/summary.json`
- `content/evals/latest/results.jsonl`
- `content/evals/latest/leaderboard.json`
- `content/evals/latest/failures.json`
- `content/evals/latest/report.md`
- `content/evals/latest/source-trust-report.json`
- `content/evals/latest/graph-safety-report.json`
- `content/evals/latest/openclaw-comparison.json`
- `content/evals/latest/prompt-audit.json`
- `content/system/task-runtime.json`
- `content/system/exploration-runtime.json`
- `content/system/exploration-queue.jsonl`
- `content/graph/migrations/latest-report.json`
