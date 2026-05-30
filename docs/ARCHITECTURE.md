# Thiezer Architecture

## Minimal Core

Thiezer now has one deterministic control plane and one canonical claim-first graph store.

On top of the core there is a task runtime for two user-facing modes:

- `ask`: route a user intent into a bounded workflow
- `background-sync`: run the core pipeline and then a budgeted exploration pass

The long-term product shape is a continuously updated Armenia-first national knowledge graph, not a chatbot. The graph stores public-source evidence about people, offices, state bodies, municipalities, companies, NGOs, media outlets, legal cases, procurement records, policies, events, and political/financial networks. A newsroom/research layer reads from that graph, but cannot create truth by itself.

### Repository contract

- `config/pipeline.yaml` and `config/source_capabilities.yaml` define pipeline policy.
- `content/graph/country-graph.json` is the canonical mutable graph bundle.
- `content/graph/evidence-log.jsonl` is the append-only evidence log.
- `content/graph/schema-v3.json` is the primary graph contract.
- `content/graph/schema-v2.json` remains a compatibility artifact during migration.
- `content/graph/migrations/latest-report.json` records the latest v2 -> v3 migration.
- `content/graph/relation-types.json` defines relation classes.
- `content/sources/source-registry.json` and `content/sources/armenia-source-seed.json` define intake sources.
- `content/system/local-model-config.json` defines model routing.
- `content/system/task-runtime.json` records the latest task receipt.
- `content/system/exploration-runtime.json` records the latest exploration pass.
- `content/system/exploration-queue.jsonl` stores the current exploration budget queue.
- `content/system/subgraphs/latest.json` stores compact source-aware subgraphs selected for expansion.
- `content/system/national-graph-operator-report.json` stores the latest daily graph maintenance receipt.
- `content/prompts/prompt-stack.json` defines role contracts and tool contracts.
- `scripts/task_runner.py` routes user intents into bounded workflows.
- `scripts/explorer.py` performs the budgeted exploration pass and feeds new candidates back into retrieval.
- `scripts/national_graph_cycle.py` generates prioritized research questions, builds subgraphs, and writes the operator report.
- `scripts/living_graph/question_generator.py` deterministically turns graph gaps into queued research tasks.
- `scripts/living_graph/subgraph_builder.py` builds compact graph-context packets for expansion.

### Stage order

1. `ingest`
2. `retrieve`
3. `graph`
4. `publish`

The task runtime can also run:

1. `ask`
2. `graph-audit`
3. `graph-explore`
4. `deep-research`
5. `background-sync`

Publish only happens after the graph stage writes the latest graph snapshot and verified story pack.

### Internal graph write order

1. `retrieve` creates Armenia-relevant story clusters and explainable source-trust profiles.
2. `graph` builds claims, evidence, sources, perspectives, and events per story.
3. `graph` runs graph safety verification.
4. `graph` runs a separate critic pass.
5. Class-based canonical admission decides which claims become durable edges.
6. `publish` reads only the verified story pack and applies a separate feed gate.

### National graph maintenance cycle

`scripts/national_graph_cycle.py` is the deterministic daily maintenance wrapper. It does not fetch the internet by itself; it audits the current graph state and prepares the next research work:

1. Load the canonical graph.
2. Generate prioritized research questions from missing biography fields, missing office tenures, party/faction gaps, municipality roster gaps, company ownership gaps, procurement/legal relation gaps, stale claims, disputed claims, and dense subgraphs.
3. Write `content/system/exploration-queue.jsonl`.
4. Build compact subgraphs for the highest-priority seed entities.
5. Write `content/system/subgraphs/latest.json`.
6. Write `content/system/national-graph-operator-report.json` with counters, failures, and next recommended tasks.
7. Optionally consume the highest-priority queued question with `scripts/national_graph_cycle.py --consume-next`, which starts one bounded agent-runtime run and writes an exploration queue receipt.

The fetch/research workers consume the queue later. This keeps daily orchestration auditable and prevents the LLM from inventing relations to fill gaps.

### Model roles

- local small/mid models: routing, cheap extraction, cheap classification
- deterministic rules: final graph safety gate
- OpenRouter/Nemotron optional layer: source judge, graph critic, long-context structured synthesis
- writer: may package verified content only, never choose truth or mutate the graph

### LLM-facing graph views

- `canonical_graph`: durable vertices and admitted edges
- `claim_layer`: atomic assertions with provenance and separate confidence dimensions
- `perspective_layer`: partisan, institutional, civic, and analytical frames around a vertex
- `graph_context_view`: compact subgraph for prompts
- `graph_memory_cards`: actor-centric summaries derived from the graph runtime
- `verified_story_pack`: only accepted stories survive into publication and task answers
- `exploration_queue`: budgeted URLs and links queued for the next exploration pass
- `research_questions`: deterministic graph-gap tasks with source-type hints and multilingual search queries
- `subgraph_packets`: compact graph-context views for a seed entity/topic, including canonical edges, active claims, disputed claims, evidence, missing fields, and expansion questions

### Truth rules

- No competing memory layer.
- No UI-derived truth.
- No separate dossier store.
- No public/editorial shadow graph.
- Everything durable must land in the graph bundle or the evidence log.
- Articles never write canonical edges directly.
- Mentions are weak observational signals only.
- Rumors and disputed interpretations may shape perspectives and narratives, but do not become canonical edges by default.
- `PERSON` vertices must never be merged with `OFFICE` vertices. The relation is a temporal `holds_office_in` claim/edge with provenance.
- Company ownership, procurement, legal, allegation, political alignment, and financial relations require stronger source provenance than ordinary mentions.
