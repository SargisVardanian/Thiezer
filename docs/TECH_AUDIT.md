# Tech Audit

Updated: 2026-03-26

## Consolidated state

The repository has been reduced to the deterministic core:

- one orchestrator
- four stage scripts
- one task runtime
- one exploration worker
- one canonical graph
- one append-only evidence log
- one source registry
- one local model config
- one prompt-role stack
- one eval/audit path for local, deterministic, OpenClaw, and optional OpenRouter comparison

## Confirmed behavior

- `daily-sync` runs `ingest -> retrieve -> graph -> publish`
- `ask` routes a freeform intent into a bounded task workflow
- `background-sync` runs the core pipeline plus a budgeted exploration pass
- `graph-explore` writes the exploration queue and exploration runtime without opening a new truth layer
- `health` reads only the canonical graph, source registry, and local model config
- derived dossiers, sessions, UI artifacts, logs, and legacy leaf scripts have been removed
- `retrieve` now emits explainable source-trust profiles per story
- `graph` now emits proposal receipts, verified story pack, graph context view, graph memory cards, and graph safety report
- `publish` now packages only verified stories and emits social outputs from verified inputs
- `task_runner.py` now records bounded task receipts in `content/system/task-runtime.json`
- `explorer.py` now records the current exploration queue and candidate set
- `scripts/eval_models.py` now produces `content/evals/latest/*` artifacts including source trust, graph safety, OpenClaw comparison, and prompt audit
- current benchmark signal: deterministic pipeline remains the strongest baseline; raw tiny local and OpenClaw paths still underperform and should be treated as evaluative or narrow-role layers, not truth engines

## Residual risks

- retrieval is now deterministic and heuristic, so quality depends on the source registry and graph richness
- graph growth is only as strong as the evidence captured during ingest and the strictness of proposal verification
- there is no fallback UI layer or parallel truth store
- optional OpenRouter/Nemotron mode depends on API availability and should remain a structured judge/critic layer, not the primary crawler

## Next rule

If new runtime artifacts appear, they must be justified against the whitelist before they are added back.
