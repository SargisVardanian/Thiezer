# Project Memory

- Thiezer task runs must be phase-based and bounded.
- Never report publish success without a transport receipt.
- Partial success is preferable to silence or compaction loss.
- `task-runtime.json` now carries phase receipts, checkpoint, and operator trace summary.
- OpenClaw bootstrap requires `Resources/templates/AGENTS.md`; keep the template present if the UI is expected to launch runs.
- For long-context upgrades, do not chase a hidden TurboQuant flag in Ollama; separate backend abstraction from orchestration first, baseline `num_ctx` honestly, and keep retrieval/compaction fallbacks.
- For news monitoring, diversify source selection by category and coverage debt; do not let ingest collapse to a single outlet. Use `fact_check` plus `perspective_blend` to merge alternative political/viewpoint framing instead of deleting the story.
- `perspective_blend` must stay within the same event family; do not merge stories on a shared actor alone. Infer task topic from the user query so election/internal-politics requests stay focused instead of drifting into generic world news.
- The OpenClaw bridge must preserve the full user prompt and must not collapse it to `today` for news requests. Election/internal-politics prompts should be routed before the generic news fallback so `task_runner` can classify them correctly.
- Election/internal-politics deep research should run the party crawler as a pre-pass with a larger crawl budget, so the graph gets party/affiliation coverage before retrieval and publication.
