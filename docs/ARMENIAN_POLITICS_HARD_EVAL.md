# Armenian Politics Hard Eval

This eval pack stress-tests local-model behavior on Armenian politics workflows where Thiezer must keep political facts, source claims, temporal office history, and graph safety separate.

## Task Pack

Tracked task file:

- `content/evals/armenian-politics-hard-tasks.json`

The pack contains 10 self-contained hard tasks:

1. Separate `Nikol Pashinyan` as `PERSON` from `Prime Minister of Armenia` as `OFFICE`.
2. Avoid collapsing `Civil Contract`, `Civil Contract faction`, and `President of the National Assembly`.
3. Compare conflicting ministry/watchdog procurement-reform claims without choosing an unsupported winner.
4. Refuse or downgrade an anonymous party-switch claim.
5. Resolve Armenian, Russian, and English aliases without merging person and office aliases.
6. Treat accusation/favoritism relations as high-risk candidate claims unless the evidence threshold is met.
7. Preserve temporal office-holder history instead of overwriting older holders.
8. Produce a quote-disciplined political brief from official, opposition, and NGO source snippets.
9. Keep speculative reshuffle material in the claims log instead of the validated country graph.
10. Do multi-hop election reasoning across candidate, party, alliance, and prior office links.

## Runner

Tracked runner:

- `scripts/eval_armenian_politics_hard.py`

Example commands:

```bash
python3 scripts/eval_armenian_politics_hard.py --dry-run --limit 2
python3 scripts/eval_armenian_politics_hard.py --timeout 120
```

The runner writes ignored local artifacts under `content/evals/latest/`:

- `armenian-politics-hard-results.jsonl`
- `armenian-politics-hard-summary.json`
- `armenian-politics-hard-report.md`

## Local Run

Run date: 2026-05-30.

Runtime:

- Host: Apple M3 Pro, 18 GB unified memory, Metal available.
- Ollama available locally.
- Model: `gemma4:e4b`.

Result summary:

- tasks: 10
- valid JSON responses: 10
- strict passes: 0
- pass rate: 0.0
- average score: 0.75

Observed failure classes:

- Translates or normalizes canonical entity labels instead of preserving exact graph labels.
- Sometimes repeats contested source language as a claim even when a caution says it is weak.
- Often omits explicit caution markers required by the graph-safety contract.
- Does not reliably emit schema terms such as `valid_from`, `valid_to`, `claims_log`, and `validated_graph`.

Interpretation:

- The local model is useful as a draft extractor/writer.
- It should not be the sole validator for Armenian politics graph updates.
- Deterministic checks should remain the gate for `PERSON != OFFICE`, source thresholds, temporal dates, and claims-log versus validated-graph writes.
