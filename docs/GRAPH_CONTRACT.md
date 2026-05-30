# Graph Contract

Thiezer uses a claim-first national graph contract. Source material never writes canonical edges directly. It produces evidence-backed claims, and deterministic admission decides whether a claim can become a compact canonical edge.

## Layers

Entity layer:

- Canonical vertices represent `PERSON`, `OFFICE`, `GOVERNMENT_BODY`, `MUNICIPALITY`, `PARTY`, `FACTION`, `COMPANY`, `NGO`, `MEDIA_OUTLET`, `COURT`, `LEGAL_CASE`, `PROCUREMENT_CONTRACT`, `POLICY`, `LAW`, `EVENT`, `LOCATION`, `DOCUMENT`, and `SOURCE`.
- Roles and offices are separate from people. `Nikol Pashinyan` is a `PERSON`; `Prime Minister of Armenia` is an `OFFICE`.
- Aliases can include Armenian, Russian, English, and transliteration variants.
- Merge history belongs on entity metadata; incompatible kinds cannot auto-merge.

Claim layer:

- Claims are atomic assertions with subject/object candidates or linked vertices.
- Required fields include `claim_type`, `statement`, `polarity`, `source_ids`, `evidence_ids`, `observed_at`, optional `valid_from` / `valid_to`, confidence dimensions, `publication_risk`, `interpretive_degree`, and status.
- Status values are `proposed`, `candidate`, `rejected`, `disputed`, `admitted`, `confirmed`, `superseded`, and `stale`.

Evidence layer:

- Evidence records preserve URL, title, publisher/source, publication date when known, retrieval date, quote/span, language, source type, and reliability score.
- Financial, procurement, legal, and allegation claims require stronger evidence than ordinary mentions.

Canonical edge layer:

- Only admitted or confirmed claims can become canonical edges.
- Canonical edges must preserve `claim_ids`, `evidence_ids`, and `source_ids`.
- Mentions are weak signals and do not become strong relations by default.

Perspective layer:

- Rumors, allegations, partisan framing, government/opposition narratives, media interpretations, and watchdog interpretations are preserved separately.
- Perspective data may guide research questions but cannot silently become factual graph edges.

Question layer:

- `scripts/living_graph/question_generator.py` creates research questions from graph gaps.
- Questions include target entities, expected claim types, priority score, reason, suggested source types, multilingual search queries, budget estimate, and status.
- The current queue is `content/system/exploration-queue.jsonl`.

Subgraph layer:

- `scripts/living_graph/subgraph_builder.py` creates compact packets around seed entities.
- Each packet includes canonical edges, active claims, disputed claims, source-backed evidence, missing fields, and expansion questions.
- The latest bundle is `content/system/subgraphs/latest.json`.

Daily receipt layer:

- `scripts/national_graph_cycle.py` writes `content/system/national-graph-operator-report.json`.
- The receipt includes sources checked, URLs fetched, claims extracted/admitted/rejected, disputed claims stored, vertices, merges, edges, stale claims, generated questions, updated subgraphs, failures, and next research tasks.

## Admission Policy

- Official and legal sources can admit low-risk institutional facts when provenance is exact.
- Procurement and financial relations require exact documents or registry records.
- Watchdog allegations remain disputed unless independently confirmed.
- Media claims remain proposed unless backed by reliable evidence and source policy.
- Social/anonymous material never creates canonical edges by default.
- Political alignment, opposition/support, ownership/control, legal accusations, and corruption/favoritism relations are high-risk and require stronger provenance.

## Runtime Commands

Generate queue, subgraphs, and operator report:

```bash
python3 scripts/national_graph_cycle.py --question-limit 50 --subgraph-limit 5
```

Repeated daily runs preserve queue execution metadata (`status`, `run_id`, `attempt_count`, `max_attempts`) for stable question IDs, so retries and completed questions are not silently reset by graph-gap regeneration.

Start one bounded runtime run from the highest-priority queued question:

```bash
python3 scripts/national_graph_cycle.py --consume-next --json
python3 scripts/national_graph_cycle.py --consume-next --run-steps 1 --json
```

Inspect without writing:

```bash
python3 scripts/national_graph_cycle.py --dry-run --json
```

Run the local hard eval:

```bash
python3 scripts/eval_armenian_politics_hard.py --timeout 120
```
