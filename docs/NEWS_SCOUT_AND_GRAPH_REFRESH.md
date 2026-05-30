# News Scout And Graph Refresh

Updated: 2026-04-17

## Goal

Refresh Thiezer's graph vertices with internet-backed biographies, event context, and more human-readable relation text while keeping `Ollama / Gemma 4` as the final synthesis model.

## Recommended Small Scout Model

Primary recommendation:

- `Alibaba-NLP/gte-multilingual-reranker-base`
- Hugging Face: <https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base>
- Paper: `mGTE: Generalized Long-Context Text Representation and Reranking Models for Multilingual Text Retrieval` (2024)
- Paper URL: <https://arxiv.org/abs/2407.19669>

Why this model:

- `306M` parameters, so comfortably under `1B`
- Apache-2.0 license
- multilingual support across `75+` languages
- `8192` token input, useful for longer news snippets and official pages
- designed specifically for multilingual retrieval and reranking rather than generic generation

Alternative:

- `jinaai/jina-reranker-v2-base-multilingual`
- Hugging Face: <https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual>
- `278.4M` parameters
- useful if non-commercial license constraints are acceptable

## Evidence Notes

- The Hugging Face model card for `gte-multilingual-reranker-base` states it is a `306M` reranker, supports `75 languages`, and `8192` max input tokens.
- The `mGTE` paper (2024) describes multilingual text representation and reranking with long-context support and reports better long-context retrieval performance than prior same-size multilingual encoders.
- NeuCLIR 2024 defines multilingual and cross-language news retrieval tasks over multilingual news corpora, which matches Thiezer's requirement to find and merge multilingual web news before long-form synthesis.

## Target Architecture

```text
web search / official links / registry sources
-> small scout reranker (<1B)
-> top multilingual evidence snippets
-> Ollama / Gemma 4
-> structured entity refresh
-> graph profile + human relation text + event-aware Graph-RAG
```

## Local Implementation State

- `scripts/retrieve.py` provides the evidence retrieval and scout-style ranking layer and falls back to deterministic lexical scoring if local runtime dependencies are unavailable.
- `content/system/news-scout-config.json` stores the selected scout model and alternatives.
- `scripts/graph.py` and `scripts/pipeline_common.py` now handle vertex updates, claim extraction, and bounded synthesis for graph refresh.
- `web/graph-viewer/app.js` now prefers human-readable relation text when present.

## Live Runtime Caveat

If `transformers` and model weights are not installed locally, the scout stage remains deterministic. The final synthesis still runs through `Ollama / Gemma 4`.
