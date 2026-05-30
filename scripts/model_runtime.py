#!/usr/bin/env python3
"""Model selection and structured command planning for Thiezer command workflows."""

from __future__ import annotations

import json
import os
import re
import time
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import active_chain_snapshot, iso_now, load_graph, load_model_config, normalize_text  # noqa: E402


COMMAND_MODEL_MODES = (
    "auto",
    "local/ollama",
    "openrouter/api",
    "openrouter/free",
    "deterministic only",
)

DEFAULT_OPENROUTER_FREE_MODELS = (
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "qwen/qwen3-4b:free",
    "qwen/qwen3-coder:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-3-27b-it:free",
)

BACKEND_CAPABILITY_FIELDS = (
    "backend_type",
    "base_url",
    "model",
    "native_max_ctx",
    "effective_max_ctx",
    "supports_kv_compression",
    "supports_prefix_cache",
    "supports_speculative_decode",
    "streaming",
    "structured_output",
)

ROSTER_PARTY_ALIASES: dict[str, tuple[str, ...]] = {
    "party-civil-contract": (
        "civil contract",
        "qaghaqaciakan paymanagir",
        "քաղաքացիական պայմանագիր",
        "քպ",
    ),
    "party-republican-party-of-armenia": (
        "republican party of armenia",
        "armenian republican party",
        "հայաստանի հանրապետական կուսակցություն",
        "հհկ",
        "hhk",
    ),
    "party-armenia-alliance": (
        "armenia alliance",
        "hayastan alliance",
        "hayastan bloc",
        "kocharyan faction",
        "kocharyan bloc",
        "robert kocharyan faction",
        "kocharyan",
        "ռոբերտ քոչարյան",
        "քոչարյան",
        "кочарян",
        "альянс армения",
        "блок армения",
        "հայաստան դաշինք",
        "հայաստան",
    ),
    "party-with-honor": (
        "with honor",
        "i have honor",
        "pativ unem",
        "պատիվ ունեմ",
    ),
}


def _int_value(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except Exception:
        return default


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _runtime_ollama_options(model_config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = model_config if isinstance(model_config, dict) else load_model_config()
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
    options = runtime.get("ollama_options", {}) if isinstance(runtime.get("ollama_options", {}), dict) else {}
    return options


def _runtime_ollama_url(model_config: dict[str, Any] | None = None) -> str:
    config = model_config if isinstance(model_config, dict) else load_model_config()
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
    return str(runtime.get("ollama_url") or "http://127.0.0.1:11434").rstrip("/")


def _normalize_backend_capability(mode: str, raw: dict[str, Any], model_config: dict[str, Any]) -> dict[str, Any]:
    runtime = model_config.get("runtime", {}) if isinstance(model_config, dict) else {}
    ollama_options = _runtime_ollama_options(model_config)
    default_ctx = _int_value(ollama_options.get("default_num_ctx"), 8192)
    long_ctx = _int_value(ollama_options.get("long_num_ctx"), 65536)
    backend_type = str(raw.get("backend_type") or raw.get("provider") or ("ollama" if mode == "ollama-native" else "")).strip()
    native_max_ctx = _int_value(raw.get("native_max_ctx"), default_ctx if backend_type == "ollama" else long_ctx)
    effective_max_ctx = _int_value(raw.get("effective_max_ctx"), max(native_max_ctx, long_ctx if backend_type == "ollama" else native_max_ctx))
    model = str(raw.get("model") or "").strip()
    if not model and backend_type == "ollama":
        model = "gemma4:e4b"
    base_url = str(raw.get("base_url") or "").strip()
    if not base_url and backend_type == "ollama":
        base_url = _runtime_ollama_url(model_config)
    return {
        "mode": mode,
        "enabled": _bool_value(raw.get("enabled"), mode == "ollama-native"),
        "backend_type": backend_type or "unknown",
        "base_url": base_url.rstrip("/"),
        "model": model,
        "native_max_ctx": native_max_ctx,
        "effective_max_ctx": effective_max_ctx,
        "supports_kv_compression": _bool_value(raw.get("supports_kv_compression")),
        "supports_prefix_cache": _bool_value(raw.get("supports_prefix_cache")),
        "supports_speculative_decode": _bool_value(raw.get("supports_speculative_decode")),
        "streaming": _bool_value(raw.get("streaming"), True),
        "structured_output": _bool_value(raw.get("structured_output"), backend_type in {"ollama", "openai-compatible", "openrouter"}),
    }


def backend_capability_catalog(model_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return normalized backend capabilities without assuming a concrete provider."""
    config = model_config if isinstance(model_config, dict) else load_model_config()
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
    raw_backends = config.get("backends", {}) if isinstance(config, dict) else {}
    if not isinstance(raw_backends, dict):
        raw_backends = {}
    synthetic_backends: dict[str, dict[str, Any]] = dict(raw_backends)
    synthetic_backends.setdefault(
        "ollama-native",
        {
            "enabled": True,
            "backend_type": "ollama",
            "base_url": _runtime_ollama_url(config),
            "model": "gemma4:e4b",
            "native_max_ctx": _int_value(_runtime_ollama_options(config).get("default_num_ctx"), 8192),
            "effective_max_ctx": _int_value(_runtime_ollama_options(config).get("long_num_ctx"), 65536),
            "streaming": True,
            "structured_output": True,
        },
    )
    synthetic_backends.setdefault(
        "longctx-backend",
        {
            "enabled": False,
            "backend_type": "openai-compatible",
            "native_max_ctx": _int_value(_runtime_ollama_options(config).get("experimental_num_ctx"), 131072),
            "effective_max_ctx": _int_value(_runtime_ollama_options(config).get("experimental_num_ctx"), 131072),
            "supports_kv_compression": True,
            "streaming": True,
            "structured_output": True,
        },
    )
    backends = [
        _normalize_backend_capability(mode, raw if isinstance(raw, dict) else {}, config)
        for mode, raw in sorted(synthetic_backends.items())
    ]
    fallback_policy = config.get("fallback_memory_policy", {}) if isinstance(config, dict) else {}
    if not isinstance(fallback_policy, dict):
        fallback_policy = {}
    return {
        "updated_at": iso_now(),
        "default_mode": str(runtime.get("default_backend_mode") or "ollama-native"),
        "backends": backends,
        "fallback_memory_policy": fallback_policy,
        "contract_fields": list(BACKEND_CAPABILITY_FIELDS),
    }


def resolve_runtime_backend(
    *,
    required_context: int = 0,
    prefer_long_context: bool = False,
    model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Choose a backend mode and state whether memory fallback is required."""
    catalog = backend_capability_catalog(model_config)
    backends = [item for item in catalog["backends"] if item.get("enabled")]
    by_mode = {str(item.get("mode")): item for item in backends}
    default_mode = str(catalog.get("default_mode") or "ollama-native")
    requested_ctx = max(0, int(required_context or 0))
    long_candidates = [
        item
        for item in backends
        if str(item.get("mode")) == "longctx-backend" or bool(item.get("supports_kv_compression"))
    ]
    selected = None
    reason = "default_backend"
    if prefer_long_context and long_candidates:
        selected = max(long_candidates, key=lambda item: int(item.get("effective_max_ctx") or 0))
        reason = "selected_long_context_backend"
    if selected is None and default_mode in by_mode:
        selected = by_mode[default_mode]
    if selected is None and backends:
        selected = max(backends, key=lambda item: int(item.get("effective_max_ctx") or 0))
        reason = "selected_largest_enabled_backend"
    if selected is None:
        selected = _normalize_backend_capability("deterministic", {"enabled": True, "backend_type": "deterministic", "model": "rules"}, model_config or load_model_config())
        reason = "no_enabled_backend"
    effective_ctx = int(selected.get("effective_max_ctx") or 0)
    fallback_required = bool(requested_ctx and effective_ctx and requested_ctx > effective_ctx)
    if prefer_long_context and not long_candidates and str(selected.get("mode")) != "longctx-backend":
        fallback_required = True
        reason = "long_context_backend_unavailable"
    return {
        "backend": selected,
        "required_context": requested_ctx,
        "fallback_memory_required": fallback_required,
        "fallback_memory_policy": catalog.get("fallback_memory_policy", {}),
        "reason": reason,
    }

ROSTER_PARTY_QUERY_LABELS: dict[str, str] = {
    "party-civil-contract": "Civil Contract",
    "party-republican-party-of-armenia": "Republican Party of Armenia",
    "party-armenia-alliance": "Armenia Alliance",
    "party-with-honor": "With Honor",
}


def _first_json_object(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _ollama_url() -> str:
    return _runtime_ollama_url()


def _ollama_num_ctx(prompt: str = "", *, long_task: bool = False) -> int:
    options = _runtime_ollama_options()
    default_num_ctx = int(options.get("default_num_ctx", 8192) or 8192)
    long_num_ctx = int(options.get("long_num_ctx", 65536) or 65536)
    experimental_num_ctx = int(options.get("experimental_num_ctx", 131072) or 131072)
    allow_experimental = bool(options.get("recommended_max_num_ctx", 65536) and int(options.get("recommended_max_num_ctx", 65536)) >= 131072)
    text = str(prompt or "")
    if long_task or len(text) > 12000:
        return experimental_num_ctx if allow_experimental and len(text) > 30000 else long_num_ctx
    return default_num_ctx


def _native_model_id(provider: str, model_id: str) -> str:
    value = str(model_id or "").strip()
    if provider == "ollama" and value.startswith("ollama/"):
        return value.split("/", 1)[1].strip()
    if provider == "openrouter" and value.startswith("openrouter/"):
        return value.split("/", 1)[1].strip()
    return value


def command_model_catalog() -> dict[str, Any]:
    model_config = load_model_config()
    chain = active_chain_snapshot(model_config)
    backend_catalog = backend_capability_catalog(model_config)
    openrouter_available = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    configured_modes = list(model_config.get("command_models", [])) if isinstance(model_config, dict) else []
    preferred_models = list(model_config.get("preferred_models", [])) if isinstance(model_config, dict) else []
    free_models: list[str] = []
    seen_free: set[str] = set()
    for raw in preferred_models:
      value = str(raw or "").strip()
      if not value.startswith("openrouter/") or ":free" not in value:
          continue
      model_id = value.split("/", 1)[1].strip()
      if not model_id or model_id in seen_free:
          continue
      seen_free.add(model_id)
      free_models.append(model_id)
    if not free_models:
        free_models = list(DEFAULT_OPENROUTER_FREE_MODELS)
    free_modes = [
        {
            "id": f"openrouter/free-{re.sub(r'[^a-z0-9]+', '-', model.lower()).strip('-')}",
            "label": f"OpenRouter / Free · {model}",
            "provider": "openrouter",
            "model": model,
            "fallback": "deterministic",
        }
        for model in free_models
    ]
    custom_modes: list[dict[str, Any]] = []
    default_mode = "auto"
    for raw in configured_modes:
        if not isinstance(raw, dict):
            continue
        mode_id = str(raw.get("id") or "").strip()
        if not mode_id:
            continue
        mode = {
            "id": mode_id,
            "label": str(raw.get("label") or mode_id).strip() or mode_id,
            "provider": str(raw.get("provider") or "openrouter").strip() or "openrouter",
            "model": str(raw.get("model") or "").strip(),
            "fallback": str(raw.get("fallback") or "deterministic").strip() or "deterministic",
        }
        if raw.get("tier"):
            mode["tier"] = str(raw.get("tier")).strip()
        if raw.get("notes"):
            mode["notes"] = str(raw.get("notes")).strip()
        if raw.get("default") and default_mode == "auto":
            default_mode = mode_id
        custom_modes.append(mode)
    if custom_modes and default_mode == "auto":
        default_mode = custom_modes[0]["id"]
    return {
        "updated_at": iso_now(),
        "ok": True,
        "modes": [
            {"id": "auto", "label": "Auto", "provider": "auto", "fallback": "deterministic"},
            *custom_modes,
            {"id": "local/ollama", "label": "Local / Ollama", "provider": "ollama", "model": _native_model_id("ollama", str(chain.get("classifier", {}).get("preferred") or chain.get("reranker", {}).get("preferred") or "gemma4:e4b")), "fallback": "deterministic"},
            {"id": "openrouter/api", "label": "OpenRouter / API", "provider": "openrouter", "model": _native_model_id("openrouter", str(chain.get("writer", {}).get("preferred") or "nvidia/nemotron-3-super-120b-a12b:free")), "fallback": "deterministic"},
            *free_modes,
            {"id": "deterministic only", "label": "Deterministic only", "provider": "deterministic", "model": "rules", "fallback": ""},
        ],
        "active_chain": chain,
        "backend_capabilities": backend_catalog,
        "openrouter_available": openrouter_available,
        "ollama_url": _ollama_url(),
        "default_mode": default_mode,
    }


def resolve_command_model(mode: str = "auto", requested_model: str = "") -> dict[str, Any]:
    catalog = command_model_catalog()
    modes = {item["id"]: item for item in catalog["modes"]}
    normalized_mode = normalize_text(mode).replace(" ", "/") or "auto"
    if normalized_mode in {"local", "ollama", "local/ollama"}:
        normalized_mode = "local/ollama"
    elif normalized_mode in {"openrouter", "api", "openrouter/api"}:
        normalized_mode = "openrouter/api"
    elif normalized_mode in {"deterministic", "rules", "deterministic/only"}:
        normalized_mode = "deterministic only"
    elif normalized_mode not in modes:
        normalized_mode = "auto"

    choice = modes.get(normalized_mode, modes["auto"])
    provider = str(choice.get("provider") or "auto")
    model = str(requested_model or choice.get("model") or "")
    fallback_used = False
    reason = "requested"

    if normalized_mode == "auto":
        free_modes = [item for item in catalog.get("modes", []) if str(item.get("id") or "").startswith("openrouter/free-")]
        if catalog.get("openrouter_available") and free_modes:
            provider = "openrouter"
            model = model or str(free_modes[0].get("model") or "")
            reason = "auto_selected_openrouter_free"
        elif catalog.get("openrouter_available"):
            provider = "openrouter"
            model = model or str(modes["openrouter/api"].get("model") or "")
            reason = "auto_selected_openrouter"
        else:
            provider = "ollama"
            model = model or str(modes.get("local/ollama", {}).get("model") or "gemma4:e4b")
            reason = "auto_selected_local"
    elif normalized_mode == "local/ollama":
        provider = "ollama"
        model = _native_model_id("ollama", model or str(modes["local/ollama"].get("model") or ""))
    elif normalized_mode == "openrouter/api":
        provider = "openrouter"
        model = _native_model_id("openrouter", model or str(modes["openrouter/api"].get("model") or ""))
        if not catalog.get("openrouter_available"):
            fallback_used = True
            provider = "deterministic"
            model = "rules"
            reason = "openrouter_key_missing"
    elif normalized_mode == "deterministic only":
        provider = "deterministic"
        model = "rules"
        fallback_used = True
        reason = "deterministic_only"

    backend_resolution = resolve_runtime_backend(
        required_context=0,
        prefer_long_context=False,
        model_config=load_model_config(),
    )
    return {
        "mode": normalized_mode,
        "provider": provider,
        "model": model,
        "fallback_used": fallback_used,
        "reason": reason,
        "backend": backend_resolution["backend"],
        "fallback_memory_required": backend_resolution["fallback_memory_required"],
        "fallback_memory_policy": backend_resolution["fallback_memory_policy"],
        "catalog": catalog,
    }


def _call_ollama_json(model_name: str, prompt: str, timeout: int = 30) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": _ollama_num_ctx(prompt)},
    }
    request = Request(
        f"{_ollama_url()}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        raw_payload = response.read().decode("utf-8", errors="replace")
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    parsed = _first_json_object(raw_payload) or {}
    content = ""
    if isinstance(parsed, dict):
        content = str(parsed.get("response") or parsed.get("thinking") or "")
    plan = _first_json_object(content) or _first_json_object(raw_payload) or {}
    meta = {"ok": True, "provider": "ollama", "model": model_name, "elapsed_ms": elapsed_ms, "raw": raw_payload}
    return plan if isinstance(plan, dict) else {}, meta


def _call_ollama_text(model_name: str, prompt: str, timeout: int = 45, temperature: float = 0.3) -> tuple[str, dict[str, Any]]:
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": _ollama_num_ctx(prompt, long_task=True)},
    }
    request = Request(
        f"{_ollama_url()}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        raw_payload = response.read().decode("utf-8", errors="replace")
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    parsed = _first_json_object(raw_payload) or {}
    text = ""
    if isinstance(parsed, dict):
        text = str(parsed.get("response") or parsed.get("thinking") or "")
    if not text:
        text = raw_payload.strip()
    meta = {"ok": True, "provider": "ollama", "model": model_name, "elapsed_ms": elapsed_ms, "raw": raw_payload}
    return text.strip(), meta


def _call_openrouter_json(model_name: str, prompt: str, timeout: int = 30) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return {}, {"ok": False, "provider": "openrouter", "model": model_name, "error": "OPENROUTER_API_KEY missing", "elapsed_ms": 0.0}
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    request = Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://thiezer.local",
            "X-Title": "Thiezer Command Planner",
        },
        method="POST",
    )
    start = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        raw_payload = response.read().decode("utf-8", errors="replace")
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    parsed = _first_json_object(raw_payload) or {}
    content = ""
    if isinstance(parsed, dict):
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
    plan = _first_json_object(content) or _first_json_object(raw_payload) or {}
    meta = {"ok": True, "provider": "openrouter", "model": model_name, "elapsed_ms": elapsed_ms, "raw": raw_payload}
    return plan if isinstance(plan, dict) else {}, meta


def _resolve_role_model(role: str) -> tuple[str, str]:
    """Return (provider, model_id) for a given role from local-model-config."""
    model_config = load_model_config()
    roles = model_config.get("roles", {}) if isinstance(model_config, dict) else {}
    role_config = roles.get(role, {}) if isinstance(roles, dict) else {}
    preferred = role_config.get("preferred", []) if isinstance(role_config, dict) else []
    if not isinstance(preferred, list) or not preferred:
        return ("deterministic", "rules")
    first = preferred[0] if isinstance(preferred[0], dict) else {}
    provider = str(first.get("provider") or "deterministic")
    model_id = str(first.get("id") or "rules")
    if provider == "openrouter" and not os.environ.get("OPENROUTER_API_KEY", "").strip():
        for alt in preferred[1:]:
            if isinstance(alt, dict) and str(alt.get("provider") or "") != "openrouter":
                return (str(alt.get("provider") or "deterministic"), str(alt.get("id") or "rules"))
        fallback = str(role_config.get("fallback") or "deterministic_rules")
        return ("deterministic", fallback)
    return (provider, model_id)


def call_parser_model(content: str, extraction_prompt: str, *, timeout: int = 30) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the local parser model (Ollama) for HTML/text extraction."""
    provider, model_id = _resolve_role_model("parser")
    full_prompt = f"{extraction_prompt}\n\n---\nCONTENT (first 6000 chars):\n{content[:6000]}"
    if provider == "ollama":
        try:
            return _call_ollama_json(model_id, full_prompt, timeout=timeout)
        except Exception as exc:
            return {}, {"ok": False, "provider": "ollama", "model": model_id, "elapsed_ms": 0.0, "error": str(exc)}
    elif provider == "openrouter":
        try:
            return _call_openrouter_json(model_id, full_prompt, timeout=timeout)
        except Exception as exc:
            return {}, {"ok": False, "provider": "openrouter", "model": model_id, "elapsed_ms": 0.0, "error": str(exc)}
    return {}, {"ok": False, "provider": "deterministic", "model": "rules", "elapsed_ms": 0.0, "error": "parser_fallback"}


def call_graph_creator_model(context: str, proposal_prompt: str, *, timeout: int = 45) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the smart graph creator model (OpenRouter) for graph reasoning and proposals."""
    provider, model_id = _resolve_role_model("graph_creator")
    full_prompt = f"{proposal_prompt}\n\n---\nCONTEXT:\n{context[:8000]}"
    if provider == "openrouter":
        try:
            return _call_openrouter_json(model_id, full_prompt, timeout=timeout)
        except Exception as exc:
            fallback_models = ["openai/gpt-oss-20b:free", "qwen/qwen3-4b:free"]
            for fb in fallback_models:
                if fb == model_id:
                    continue
                try:
                    return _call_openrouter_json(fb, full_prompt, timeout=timeout)
                except Exception:
                    continue
            return {}, {"ok": False, "provider": "openrouter", "model": model_id, "elapsed_ms": 0.0, "error": str(exc)}
    elif provider == "ollama":
        try:
            return _call_ollama_json(model_id, full_prompt, timeout=timeout)
        except Exception as exc:
            return {}, {"ok": False, "provider": "ollama", "model": model_id, "elapsed_ms": 0.0, "error": str(exc)}
    return {}, {"ok": False, "provider": "deterministic", "model": "rules", "elapsed_ms": 0.0, "error": "graph_creator_fallback"}


def call_role_json(role: str, prompt: str, *, timeout: int = 30) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call any configured role model and return a strict JSON object when possible."""
    provider, model_id = _resolve_role_model(role)
    if provider == "openrouter":
        try:
            return _call_openrouter_json(model_id, prompt, timeout=timeout)
        except Exception as exc:
            fallback_models = ["openai/gpt-oss-20b:free", "qwen/qwen3-4b:free"]
            for fb in fallback_models:
                if fb == model_id:
                    continue
                try:
                    return _call_openrouter_json(fb, prompt, timeout=timeout)
                except Exception:
                    continue
            return {}, {"ok": False, "provider": "openrouter", "model": model_id, "elapsed_ms": 0.0, "error": str(exc)}
    if provider == "ollama":
        try:
            return _call_ollama_json(model_id, prompt, timeout=timeout)
        except Exception as exc:
            return {}, {"ok": False, "provider": "ollama", "model": model_id, "elapsed_ms": 0.0, "error": str(exc)}
    return {}, {"ok": False, "provider": "deterministic", "model": "rules", "elapsed_ms": 0.0, "error": f"{role}_fallback"}


def call_rag_model(prompt: str, *, timeout: int = 45) -> tuple[str, dict[str, Any]]:
    provider, model_id = _resolve_role_model("rag_answer")
    if provider == "deterministic":
        provider, model_id = _resolve_role_model("graph_native_assistant")
    if provider != "ollama":
        provider, model_id = ("ollama", "gemma4:e4b")
    try:
        return _call_ollama_text(model_id or "gemma4:e4b", prompt, timeout=timeout, temperature=0.3)
    except Exception as exc:
        return "", {"ok": False, "provider": "ollama", "model": model_id or "gemma4:e4b", "elapsed_ms": 0.0, "error": str(exc)}


def _infer_topic(prompt: str, selected_node: dict[str, Any] | None = None) -> str:
    text = normalize_text(prompt)
    node_blob = normalize_text(" ".join([
        str((selected_node or {}).get("name", "")),
        str((selected_node or {}).get("subtype", "")),
        " ".join(str(tag) for tag in (selected_node or {}).get("tags", []) or []),
    ]))
    blob = f"{text} {node_blob}"
    if any(token in blob for token in ["district", "district heads", "marz", "municipal", "mayor", "community", "local governance", "район", "мэр", "մարզ"]):
        return "local_governance"
    if any(token in blob for token in ["party", "civil contract", "republican party", "հհկ", "քաղաքացիական պայմանագիր", "parliament", "assembly", "civil"]):
        return "internal_politics"
    if any(token in blob for token in ["econom", "budget", "finance", "business", "tax"]):
        return "economy"
    if any(token in blob for token in ["foreign", "diplom", "eu", "russia", "iran", "azerbaijan", "border"]):
        return "foreign_policy"
    if any(token in blob for token in ["court", "rights", "legal", "corruption", "prosecut"]):
        return "legal_human_rights"
    return "internal_politics"


def roster_target_party_ids(prompt: str) -> list[str]:
    blob = normalize_text(prompt)
    matched: list[str] = []
    for party_id, aliases in ROSTER_PARTY_ALIASES.items():
        if any(alias in blob for alias in aliases):
            matched.append(party_id)
    return matched


def _is_roster_graph_prompt(text: str) -> bool:
    blob = normalize_text(text)
    structure_markers = [
        "all members",
        "members of",
        "party members",
        "political party members",
        "add them to graph",
        "connect them to graph",
        "connect all edges to each other",
        "connect all edges",
        "roster",
        "member roster",
        "faction",
        "factions",
        "deputies",
        "mps",
        "parliamentary group",
        "which deputies",
        "who are the deputies",
        "list of deputies",
        "composition",
        "parliament members",
        "депутаты",
        "депутатов",
        "депутат",
        "фракция",
        "фракции",
        "состав",
        "список депутатов",
        "история депутатов",
        "биографии депутатов",
        "члены фракции",
        "members and history",
        "history of these deputies",
    ]
    graph_markers = [
        "graph",
        "connect",
        "build relation",
        "build links",
        "построй связь",
        "связь",
        "добавь в граф",
        "обнови граф",
    ]
    actor_markers = [
        "parliament",
        "assembly",
        "парламент",
        "нацсобрание",
        *[alias for aliases in ROSTER_PARTY_ALIASES.values() for alias in aliases],
    ]
    has_structure = any(marker in blob for marker in structure_markers)
    has_actor = any(marker in blob for marker in actor_markers)
    has_graphish = any(marker in blob for marker in graph_markers)
    return has_actor and (has_structure or has_graphish)


def _is_media_graph_prompt(text: str) -> bool:
    blob = normalize_text(text)
    media_markers = [
        "media",
        "news channel",
        "news channels",
        "news outlet",
        "news outlets",
        "tv channel",
        "channel",
        "channels",
        "канал",
        "каналы",
        "новостные каналы",
        "новостные сайты",
        "сми",
        "медиа",
        "outlet",
        "press",
    ]
    affiliation_markers = [
        "kocharyan",
        "kochary",
        "кочар",
        "кочарян",
        "opposition",
        "оппозици",
        "armenia alliance",
        "hayastan",
        "with honor",
        "патив",
        *[alias for aliases in ROSTER_PARTY_ALIASES.values() for alias in aliases],
    ]
    action_markers = [
        "add to graph",
        "graph",
        "update graph",
        "find links",
        "links",
        "ссылки",
        "добавь в граф",
        "обнови граф",
        "найди ссылки",
    ]
    return any(marker in blob for marker in media_markers) and any(marker in blob for marker in affiliation_markers) and any(marker in blob for marker in action_markers)


def _is_cabinet_graph_prompt(text: str) -> bool:
    blob = normalize_text(text)
    ministerial_markers = [
        "minister",
        "ministers",
        "ministry",
        "ministries",
        "cabinet",
        "министр",
        "министры",
        "министер",
        "кабинет",
        "նախարար",
        "նախարարներ",
        "gov-members",
        "government team members",
        "government composition",
        "ministry of",
    ]
    government_markers = [
        "government",
        "government of armenia",
        "prime minister",
        "правительство",
        "премьер",
        "կառավարություն",
        "վարչապետ",
    ]
    structure_markers = [
        "current",
        "now",
        "history",
        "who are",
        "list",
        "all",
        "period",
        "current and former",
        "сейчас",
        "какие",
        "список",
        "в целом",
        "за период",
        "все",
        "нынешн",
        "были",
        "current roster",
        "composition",
        "состав",
    ]
    graph_markers = [
        "graph",
        "add to graph",
        "update graph",
        "connect",
        "links",
        "history",
        "timeline",
        "разбери",
        "глубин",
        "добавь в граф",
        "обнови граф",
    ]
    governance_structure_markers = [
        "structure",
        "gov-members",
        "team members",
        "composition",
        "government composition",
        "government structure",
        "minister roster",
        "cabinet roster",
        "structure of government",
        "структур",
        "состав",
        "կառուցվածք",
    ]
    has_ministerial = any(marker in blob for marker in ministerial_markers)
    has_government = any(marker in blob for marker in government_markers)
    has_scope = any(marker in blob for marker in structure_markers)
    has_graphish = any(marker in blob for marker in graph_markers)
    has_government_structure = has_government and any(marker in blob for marker in governance_structure_markers)
    return (has_ministerial or has_government_structure) and (has_scope or has_graphish)


def _is_institutional_roster_graph_prompt(text: str) -> bool:
    blob = normalize_text(text)
    if not blob:
        return False
    if _is_cabinet_graph_prompt(text):
        return True
    staff_markers = [
        "general staff",
        "chief of the general staff",
        "chief of general staff",
        "chiefs of the general staff",
        "chiefs of general staff",
        "defence staff",
        "defense staff",
        "armed forces leadership",
        "military leadership",
        "генштаб",
        "начальник генштаба",
        "начальники генштаба",
        "генеральный штаб",
        "начальник генерального штаба",
        "գլխավոր շտաբ",
        "գլխավոր շտաբի պետ",
        "գլխավոր շտաբի պետեր",
        "զինված ուժերի գլխավոր շտաբ",
    ]
    structure_markers = [
        "current",
        "now",
        "history",
        "former",
        "period",
        "list",
        "who are",
        "who was",
        "appointments",
        "dismissals",
        "changes",
        "timeline",
        "сейчас",
        "были",
        "за период",
        "назнач",
        "сняти",
        "изменени",
        "истори",
        "в целом",
        "перечень",
        "պատմ",
        "նշանակ",
        "ազատ",
        "փոփոխ",
    ]
    graph_markers = [
        "graph",
        "add to graph",
        "update graph",
        "connect",
        "links",
        "timeline",
        "разбери",
        "глубин",
        "добавь в граф",
        "обнови граф",
    ]
    has_staff = any(marker in blob for marker in staff_markers)
    has_scope = any(marker in blob for marker in structure_markers)
    has_graphish = any(marker in blob for marker in graph_markers)
    return has_staff and (has_scope or has_graphish)


def _deterministic_plan(prompt: str, selected_node: dict[str, Any] | None = None) -> dict[str, Any]:
    text = normalize_text(prompt)
    node_name = str((selected_node or {}).get("name", "")).strip()
    topic = _infer_topic(prompt, selected_node)
    if _is_institutional_roster_graph_prompt(prompt) and not _is_cabinet_graph_prompt(prompt):
        query = " ".join(
            part
            for part in [
                prompt,
                "Armenia General Staff official roster history",
                "Chief of the General Staff",
                "acting chief of general staff",
                "appointments dismissals",
                "gov.am",
                "mil.am",
                "official sources",
                "graph relations",
            ]
            if part
        ).strip()
        seed_queries = [
            "site:mil.am Armenia Chief of the General Staff official",
            "site:gov.am Armenia Chief of General Staff official",
            "site:mil.am Armenia acting Chief of General Staff Kamo Kochunts",
            "site:gov.am Onik Gasparyan Chief of General Staff relieved",
            "site:mil.am Edvard Asryan Chief of the General Staff",
            "Armenia General Staff appointments dismissals official",
        ]
        return {
            "workflow": "graph_improve",
            "topic": "internal_politics",
            "query": query,
            "seed_queries": seed_queries,
            "tool_plan": [
                "prompt_parser",
                "graph_search",
                "source_registry",
                "web_search",
                "evidence_collection",
                "retrieve_cluster",
                "graph_propose",
                "graph_verify",
                "critic",
            ],
            "summary": "graph improve on Armenia General Staff roster history",
        }
    if _is_cabinet_graph_prompt(prompt):
        query = " ".join(
            part
            for part in [
                prompt,
                "Government of Armenia cabinet ministers official roster",
                "current ministers",
                "former ministers during Pashinyan premiership",
                "gov.am",
                "primeminister.am",
                "ministry official sites",
                "appointment dismissal history",
                "official sources",
                "graph relations",
            ]
            if part
        ).strip()
        seed_queries = [
            "Government of Armenia ministers official roster gov.am",
            "site:gov.am Armenia ministers official",
            "site:primeminister.am Armenia government composition",
            "Armenia minister appointment dismissal official",
            "Armenia cabinet ministers Pashinyan official history",
            "Ministry of Foreign Affairs Armenia minister official",
            "Ministry of Economy Armenia minister official",
            "Ministry of Defense Armenia minister official",
        ]
        return {
            "workflow": "graph_improve",
            "topic": "internal_politics",
            "query": query,
            "seed_queries": seed_queries,
            "tool_plan": [
                "prompt_parser",
                "graph_search",
                "source_registry",
                "web_search",
                "evidence_collection",
                "retrieve_cluster",
                "graph_propose",
                "graph_verify",
                "critic",
            ],
            "summary": "graph improve on Armenia cabinet and minister roster history",
        }
    if _is_media_graph_prompt(prompt):
        target_party_ids = roster_target_party_ids(prompt)
        labels = [ROSTER_PARTY_QUERY_LABELS.get(party_id, party_id) for party_id in target_party_ids] or ["Armenia Alliance", "With Honor", "Opposition"]
        query = " ".join(
            part
            for part in [
                " / ".join(labels),
                "affiliated media news channels outlets links armenia",
                "official site",
                "youtube",
                "facebook",
                "telegram",
                "graph relations",
                "media alignment",
            ]
            if part
        ).strip()
        seed_queries = []
        for label in labels:
            seed_queries.extend(
                [
                    f"{label} affiliated media Armenia links",
                    f"{label} news channels opposition Armenia",
                    f"{label} media Telegram YouTube Facebook site",
                ]
            )
        return {
            "workflow": "graph_improve",
            "topic": "internal_politics",
            "query": query,
            "seed_queries": seed_queries[:8],
            "tool_plan": [
                "prompt_parser",
                "graph_search",
                "source_registry",
                "web_search",
                "evidence_collection",
                "retrieve_cluster",
                "graph_propose",
                "graph_verify",
                "critic",
            ],
            "summary": "graph improve on opposition or Kocharyan affiliated media discovery",
        }
    if _is_roster_graph_prompt(prompt):
        target_party_ids = roster_target_party_ids(prompt)
        labels = [ROSTER_PARTY_QUERY_LABELS.get(party_id, party_id) for party_id in target_party_ids] or [
            "Civil Contract",
            "Republican Party of Armenia",
            "Armenia Alliance",
            "With Honor",
        ]
        workflow = "graph_improve"
        query = " ".join(
            part
            for part in [
                " / ".join(labels),
                "parliament faction deputies roster biographies",
                "member history",
                "official parliament sources",
                "armenia",
                "official sources",
                "member_of",
                "holds_office_in",
                "aligned_with",
                "connect deputies to faction not clique",
            ]
            if part
        ).strip()
        seed_queries = []
        for label in labels:
            seed_queries.extend(
                [
                    f"{label} parliament faction deputies official sources Armenia",
                    f"{label} MPs biographies parliament Armenia",
                ]
            )
        seed_queries.extend(
            [
                "National Assembly factions deputies list Armenia official sources",
                "Armenia parliamentary faction member_of holds_office_in official sources",
            ]
        )
        tool_plan = [
            "prompt_parser",
            "graph_search",
            "source_registry",
            "web_search",
            "evidence_collection",
            "retrieve_cluster",
            "graph_propose",
            "graph_verify",
            "critic",
        ]
        return {
            "workflow": workflow,
            "topic": "internal_politics",
            "query": query,
            "seed_queries": seed_queries,
            "tool_plan": tool_plan,
            "summary": "graph improve on internal politics roster discovery",
        }
    if any(token in text for token in ["graph audit", "graph check", "audit graph", "проверь граф"]):
        workflow = "graph_check"
        query = prompt
    elif any(token in text for token in ["timeline", "history", "chronology"]):
        workflow = "node_timeline" if selected_node else "graph_audit"
        query = node_name or prompt
    elif any(token in text for token in ["expand", "connections", "neighbors", "broaden", "enrich"]):
        workflow = "node_expand" if selected_node else "graph_improve"
        query = node_name or prompt
    elif any(token in text for token in ["research", "study", "investigate", "search", "evidence", "find information"]):
        workflow = "node_research" if selected_node else "topic_deep_research"
        query = node_name or prompt
    else:
        workflow = "graph_improve" if any(token in text for token in ["graph", "память", "граф", "улучш", "add them to graph", "connect"]) else "topic_deep_research"
        query = prompt
    if workflow == "graph_improve":
        query = " ".join(
            part for part in [
                query,
                "Armenia",
                "official sources",
                "graph relations",
                "history",
                topic.replace("_", " "),
            ]
            if part
        ).strip()
    seed_queries = [query]
    if node_name:
        seed_queries.extend([
            f"Search latest evidence for {node_name}",
            f"Build timeline for {node_name}",
        ])
    if topic == "local_governance":
        seed_queries.extend([
            "Armenia marz governors official links",
            "district heads Armenia municipality official sources",
        ])
    elif topic == "internal_politics":
        seed_queries.extend([
            "Republican Party of Armenia members",
            "Civil Contract party members Armenia",
        ])
    tool_plan = ["prompt_parser", "graph_search", "source_registry"]
    if workflow in {"node_research", "topic_deep_research", "graph_improve"}:
        tool_plan.extend(["web_search", "evidence_collection"])
    if workflow in {"graph_improve", "graph_check", "node_expand"}:
        tool_plan.extend(["retrieve_cluster", "graph_propose", "graph_verify", "critic"])
    if workflow in {"node_timeline"}:
        tool_plan.append("timeline_builder")
    return {
        "workflow": workflow,
        "topic": topic,
        "query": query,
        "seed_queries": seed_queries[:8],
        "tool_plan": tool_plan,
        "summary": f"{workflow.replace('_', ' ')} on {topic.replace('_', ' ')}",
    }


def _merge_model_plan(base_plan: dict[str, Any], model_plan: dict[str, Any]) -> dict[str, Any]:
    result = dict(base_plan)
    for key in ("workflow", "topic", "query", "summary"):
        value = model_plan.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    for key in ("seed_queries", "tool_plan"):
        value = model_plan.get(key)
        if isinstance(value, list) and value:
            result[key] = [str(item) for item in value if str(item).strip()][:8]
    return result


def plan_command_workflow(
    prompt: str,
    *,
    selected_node: dict[str, Any] | None = None,
    model_mode: str = "auto",
    requested_model: str = "",
) -> dict[str, Any]:
    selection = resolve_command_model(model_mode, requested_model=requested_model)
    base_plan = _deterministic_plan(prompt, selected_node)
    models_used = [
        {
            "role": "planner",
            "mode": selection["mode"],
            "provider": selection["provider"],
            "model": selection["model"],
            "fallback_used": bool(selection["fallback_used"]),
            "reason": selection["reason"],
        }
    ]
    planner_prompt = json.dumps(
        {
            "command": prompt,
            "selected_node": selected_node or {},
            "graph_context": {
                "graph_stats": load_graph().get("runtime", {}).get("graph", {}).get("graph_context_view", {}),
                "selected_node_name": str((selected_node or {}).get("name", "")),
            },
            "instructions": [
                "Return strict JSON only.",
                "Schema: {\"workflow\": string, \"topic\": string, \"query\": string, \"seed_queries\": [string], \"tool_plan\": [string], \"summary\": string}",
                "Prefer graph_improve for graph expansion, node_research for node lookups, graph_check for audits.",
                "Keep query grounded in Armenia and source-backed evidence.",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    model_plan: dict[str, Any] = {}
    model_meta: dict[str, Any] = {"ok": False, "provider": selection["provider"], "model": selection["model"], "elapsed_ms": 0.0, "error": ""}
    if selection["provider"] == "ollama":
        try:
            model_plan, model_meta = _call_ollama_json(selection["model"], planner_prompt, timeout=20)
        except Exception as exc:
            model_meta = {"ok": False, "provider": "ollama", "model": selection["model"], "elapsed_ms": 0.0, "error": str(exc)}
    elif selection["provider"] == "openrouter":
        try:
            model_plan, model_meta = _call_openrouter_json(selection["model"], planner_prompt, timeout=25)
        except Exception as exc:
            model_meta = {"ok": False, "provider": "openrouter", "model": selection["model"], "elapsed_ms": 0.0, "error": str(exc)}
    else:
        model_meta = {"ok": False, "provider": "deterministic", "model": "rules", "elapsed_ms": 0.0, "error": "deterministic_only"}

    fallback_used = bool(selection["fallback_used"]) or not bool(model_meta.get("ok"))
    if model_plan and isinstance(model_plan, dict):
        base_plan = _merge_model_plan(base_plan, model_plan)
    if _is_roster_graph_prompt(prompt) or _is_cabinet_graph_prompt(prompt) or _is_institutional_roster_graph_prompt(prompt):
        base_plan = _deterministic_plan(prompt, selected_node)
    models_used.append(
        {
            "role": "planner_result",
            "provider": model_meta.get("provider"),
            "model": model_meta.get("model"),
            "ok": bool(model_meta.get("ok")),
            "fallback_used": fallback_used,
            "elapsed_ms": model_meta.get("elapsed_ms", 0.0),
            "error": model_meta.get("error", ""),
        }
    )
    if fallback_used:
        models_used.append(
            {
                "role": "fallback",
                "provider": "deterministic",
                "model": "rules",
                "ok": True,
                "fallback_used": True,
                "reason": "planner_fallback",
            }
        )
    tool_plan = list(base_plan.get("tool_plan", []))
    if selection["provider"] == "ollama":
        tool_plan.insert(0, "ollama_generate")
    elif selection["provider"] == "openrouter":
        tool_plan.insert(0, "openrouter_chat_completions")
    elif selection["provider"] == "deterministic":
        tool_plan.insert(0, "deterministic_rules")
    return {
        "models_used": models_used,
        "model_selection": {
            "mode": selection["mode"],
            "provider": selection["provider"],
            "model": selection["model"],
            "fallback_used": fallback_used,
            "reason": selection["reason"],
            "backend": selection.get("backend", {}),
            "fallback_memory_required": bool(selection.get("fallback_memory_required", False)),
            "fallback_memory_policy": selection.get("fallback_memory_policy", {}),
            "openrouter_available": command_model_catalog().get("openrouter_available", False),
        },
        "workflow": base_plan.get("workflow", "topic_deep_research"),
        "topic": base_plan.get("topic", ""),
        "query": base_plan.get("query", prompt),
        "seed_queries": base_plan.get("seed_queries", []),
        "tool_plan": tool_plan,
        "summary": base_plan.get("summary", prompt),
        "planner_prompt": planner_prompt,
        "planner_response": model_plan,
        "planner_meta": model_meta,
    }
