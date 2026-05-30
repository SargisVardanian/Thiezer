# Project Mode

## Operating rules

- One control plane: `scripts/orchestrator.py`
- One canonical graph: `content/graph/country-graph.json`
- One append-only evidence log: `content/graph/evidence-log.jsonl`
- One task runtime: `content/system/task-runtime.json`
- One exploration queue: `content/system/exploration-queue.jsonl`
- Publish only after the graph stage has updated the graph snapshot
- Publish only from the verified story pack
- No competing memory truth layer
- Writer cannot choose truth
- Writer cannot mutate the graph
- Story mention must not become a durable office edge automatically
- Weak or partisan claims stay attributed unless independently verified

## Work order

1. Read `docs/`
2. Update intake in `ingest`
3. Rank and cluster in `retrieve`
4. Build proposal, verify, critique, and only then mutate the graph in `graph`
5. Package verified stories only in `publish`
6. For interactive use, route through `ask` or `graph-audit` instead of calling a stage directly
7. For autonomous expansion, use `background-sync` or `graph-explore`

## Model policy

- Use small models or deterministic heuristics for filtering and ranking
- Use structured judge/critic models for source trust, graph critique, and cross-source conflict checks when available
- Use the writer only for final wording when a writer is available
- Never let a writer choose sources or mutate the graph
- Keep task routing bounded: the router may choose a workflow, but it may not rewrite graph truth

## Editing rule

If a fact is not backed by evidence in the graph or evidence log, it does not become durable state.
