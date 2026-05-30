# Thiezer Long Context / Research Runtime Package

## Goal

Keep Thiezer usable for long, source-heavy research tasks without forcing a single model call to hold the whole problem in context.

The system now uses:

- adaptive temporal planning
- search/fetch/extract/admit separation
- append-only live research events
- claim-first graph updates
- non-fatal profile rebuilds
- model tiering with fallback

## What changed

### Temporal research

Role-history queries now build a temporal plan first.

For the PM staff query, the run resolves:

- `target_role = Head/Chief of Staff of the Prime Minister of Armenia`
- `context_person = Nikol Pashinyan`
- `date_from = 2018`
- `date_to = 2026`
- `temporal_granularity = year`

The planner expands evidence windows adaptively:

1. year windows first
2. month windows when a year has useful evidence
3. day-level detail only when the source itself contains dated events

This avoids brute-forcing every date bucket.

### Research event stream

Every meaningful action writes an append-only event record:

- `search_query_started`
- `search_results_received`
- `source_opened`
- `source_scraped`
- `candidate_entity_found`
- `candidate_claim_extraction_started`
- `candidate_claim_accepted`
- `candidate_claim_rejected`
- `graph_vertex_created`
- `graph_vertex_updated`
- `graph_edge_created`
- `graph_edge_updated`
- `profile_rebuild_warning`

The UI reads these events live and renders them as a journal.

### Claim-first admission

Extraction does not write canonical graph vertices or edges directly.

The pipeline is:

`search -> fetch -> scrape -> extract candidate claims -> validate -> admit -> merge graph -> rebuild profiles`

Admission gates reject:

- hash-like labels
- office titles pretending to be people
- person vertices without readable human names
- claims without source URL or evidence quote
- broken endpoints

### Model routing

The model config is tiered:

- planner / router / critic roles can use `gpt-5.4-nano` when available
- Ollama remains the local fallback path
- deterministic fallback is reserved for obvious parsing and recovery

Current implementation keeps the provider/model contract separate from orchestration.

### UI

Research Run panel now shows:

- current stage
- current entity
- current source title and URL
- visited sources
- accepted / rejected sources
- extracted evidence
- live events
- graph diff by name, not only counters

The graph view also highlights updated nodes/edges.

## Key files

- `scripts/living_graph/research_tools/event_stream.py`
- `scripts/living_graph/research_tools/temporal_planner.py`
- `scripts/living_graph/research_tools/claim_extractor.py`
- `scripts/living_graph/agent_runtime/workers.py`
- `scripts/living_graph/agent_runtime/task_db.py`
- `scripts/living_graph/agent_runtime/runtime.py`
- `scripts/run_graph_web.py`
- `web/graph-viewer/app.js`

## Verification commands

Run these after touching research/runtime code:

```bash
python3 -m unittest -q test_agent_runtime.py test_graph_rag_contracts.py
python3 -m py_compile scripts/living_graph/research_tools/claim_extractor.py scripts/living_graph/agent_runtime/workers.py scripts/living_graph/agent_runtime/task_db.py scripts/run_graph_web.py
node --check web/graph-viewer/app.js
python3 scripts/audit_graph.py content/graph/country-graph.json
```

## Live smoke pattern

Use a fresh local server and verify the PM staff query:

```text
Найди всех руководителей аппарата премьер-министра Никола Пашиняна за период 2018-2026 годов, дай их биографии и найди, с какими структурами, компаниями, партиями, государственными органами и другими лицами они ассоциируются.
```

Success means the live trace shows:

- real searched URLs
- opened and scraped pages
- extracted claims
- admitted graph changes
- no hash-like rendered nodes
- no broken endpoints

## External evidence pack reviewed

- Google Research TurboQuant blog, 2025: https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/
- TurboQuant paper, 2025: https://arxiv.org/abs/2504.19874
- Ollama context length docs: https://docs.ollama.com/context-length
- Ollama issue #15051: https://github.com/ollama/ollama/issues/15051
- TurboQuant backend reference: https://github.com/0xSero/turboquant

