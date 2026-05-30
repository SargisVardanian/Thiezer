# Project Agent Profile

## Scope
Project root: `/Users/sargisvardanyan/Thiezer`

## Mission
Improve Thiezer's local-model internet research and long-chain reasoning without assuming Ollama has native TurboQuant support.

## Startup Routine
1. Read `/Users/sargisvardanyan/Thiezer/.agent/memory.md`.
2. Read `/Users/sargisvardanyan/Thiezer/docs/ARCHITECTURE.md`.
3. Read `/Users/sargisvardanyan/Thiezer/content/system/local-model-config.json`.
4. Read `/Users/sargisvardanyan/Thiezer/scripts/model_runtime.py`.
5. Run `/Users/sargisvardanyan/.agent/scripts/capability_handshake.sh <report_path>`.
6. Inspect local runtime reality before proposing changes:
   - `ollama ps`
   - `system_profiler SPHardwareDataType SPDisplaysDataType`
   - active endpoints and providers in `content/system/local-model-config.json`

## Confirmed Local Facts
- Thiezer already has a runtime abstraction point in `scripts/model_runtime.py`.
- Thiezer already routes across multiple providers: `ollama`, `openrouter`, `mlx`, `gliner`, and deterministic fallbacks.
- Thiezer already has retrieval and graph-context artifacts; this is not a blank-slate chatbot.
- Current host baseline is Apple Silicon (`MacBook Pro`, `Apple M3 Pro`, `18 GB` unified memory, Metal available).

## Required External Reads
Open these first and treat them as the external evidence pack:

1. Google Research TurboQuant blog
   - https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/
   - Purpose: confirm TurboQuant is KV-cache compression, not weight quantization.
2. TurboQuant arXiv paper
   - https://arxiv.org/abs/2504.19874
   - Purpose: use paper claims and caveats, not third-party retellings.
3. Ollama context-length docs
   - https://docs.ollama.com/context-length
   - Purpose: baseline what Ollama officially supports today.
4. Ollama issue `#15051`
   - https://github.com/ollama/ollama/issues/15051
   - Purpose: verify native TurboQuant/RotorQuant is still a feature request.
5. `0xSero/turboquant`
   - https://github.com/0xSero/turboquant
   - Purpose: use as an external backend reference, not as proof that Ollama already supports it.

## Main Architectural Rule
Do not look for a hidden Ollama flag for TurboQuant. Separate the API contract from the inference backend first.

Interpretation for this repository:
- Keep the existing Ollama path working.
- Add backend capability metadata instead of hard-coding provider assumptions.
- Treat long-context compression as a backend concern, not a prompt-orchestration concern.

## Implementation Priorities
1. Identify where Thiezer chooses runtime/provider/model today.
2. Baseline Ollama honestly with larger `num_ctx` and real `ollama ps` checks.
3. Extend runtime abstraction so a second backend can be added without changing upper orchestration.
4. Add task-aware routing for short-context vs long-context work.
5. Add fallback memory behavior when the long-context backend is absent.
6. Benchmark quality and latency, not just raw token fit.

## Expected Deliverables
1. A backend abstraction that can represent:
   - `backend_type`
   - `base_url`
   - `model`
   - `native_max_ctx`
   - `effective_max_ctx`
   - `supports_kv_compression`
   - `supports_prefix_cache`
   - `supports_speculative_decode`
   - `streaming`
   - `structured_output`
2. Two runtime modes:
   - `ollama-native`
   - `longctx-backend`
3. A fallback memory policy:
   - retrieval
   - summarization or compaction
   - rolling window
   - chunked ingestion
4. A benchmark artifact with:
   - max usable context
   - prefill latency
   - decode tok/s
   - offload behavior
   - quality checks on long-context tasks
5. A rollback path that restores the current Ollama-first route.

## Benchmark Minimum
Measure at least:
- `16k`
- `32k`
- `64k`
- `128k` if hardware/runtime permits

Use task classes relevant to Thiezer:
- long source pack review
- multi-hop repo or graph QA
- multi-turn agent trace
- quote-accurate long document summary

## Non-Goals
- Do not fork Ollama before backend abstraction exists.
- Do not confuse weight quantization with KV-cache compression.
- Do not claim success from a larger context window without quality checks.
- Do not remove deterministic or retrieval fallbacks.

## Deliverable Artifact
Keep the detailed implementation brief in:
- `/Users/sargisvardanyan/Thiezer/docs/LONG_CONTEXT_AGENT_PACKAGE.md`
