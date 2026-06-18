"""Optional LLM explanations.  NEVER a numerical source of truth.

Modes (``EVBATT_AI_PROVIDER``): ``off`` (default), ``openai``,
``openrouter``, ``anthropic``, ``ollama`` (alias ``local``), or
``custom`` for any OpenAI-compatible endpoint (vLLM, LM Studio,
llama.cpp server, ...).  Configuration comes only from environment
variables (or explicit CLI overrides) -- secrets are never hardcoded,
printed, or written to results:

- ``EVBATT_AI_BASE_URL`` (optional override; required for ``custom``)
- ``EVBATT_AI_API_KEY``  (or ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` /
  ``OPENROUTER_API_KEY``; not required for a local endpoint)
- ``EVBATT_AI_MODEL``    (optional; defaults per provider)
- ``EVBATT_AI_TIMEOUT_SEC``
- ``EVBATT_AI_INPUT_COST_PER_MTOK`` / ``EVBATT_AI_OUTPUT_COST_PER_MTOK``
  (optional; cost is reported only when you supply your own prices)

Remote/paid calls require explicit opt-in (``--allow-chargeable`` on the
CLI) because API calls may cost money.  A ChatGPT/Claude *subscription*
does not include API credits.  Loopback endpoints (Ollama, LM Studio)
are treated as free/local and do not require the flag.

The module uses only the standard library, so the scientific core keeps
zero AI dependencies and works fully with AI off.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# provider -> (default base URL, default model, needs a cloud API key)
_DEFAULTS: dict[str, tuple[str, str, bool]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini", True),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini", True),
    "anthropic": ("https://api.anthropic.com", "claude-haiku-4-5", True),
    "ollama": ("http://localhost:11434/v1", "gemma2:2b", False),
    "custom": ("", "", True),
}
_ALIASES = {"local": "ollama", "ollama-local": "ollama", "none": "off", "": "off"}
_KEY_ENV = {
    "openai": ("EVBATT_AI_API_KEY", "OPENAI_API_KEY"),
    "openrouter": ("EVBATT_AI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"),
    "anthropic": ("EVBATT_AI_API_KEY", "ANTHROPIC_API_KEY"),
    "ollama": ("EVBATT_AI_API_KEY",),
    "custom": ("EVBATT_AI_API_KEY", "OPENAI_API_KEY"),
}


@dataclass
class AIConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_sec: float = 60.0
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None

    @property
    def is_local(self) -> bool:
        host = urllib.parse.urlparse(self.base_url).hostname or ""
        return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or \
            host.startswith("127.") or host.endswith(".local")

    @property
    def needs_charge_confirmation(self) -> bool:
        return not self.is_local

    def redacted(self) -> dict:
        """Safe-to-print configuration; never includes the key itself."""
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "api_key": "not required" if self.is_local and not self.api_key
                       else ("set" if self.api_key else "not required"),
            "local": self.is_local,
            "chargeable": self.needs_charge_confirmation,
            "input_cost_per_mtok": self.input_cost_per_mtok,
            "output_cost_per_mtok": self.output_cost_per_mtok,
        }


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def config_from_env(provider: str | None = None, model: str | None = None,
                    base_url: str | None = None, api_key: str | None = None) -> AIConfig | None:
    """Build a config from explicit overrides + environment, or ``None`` if off.

    No network call happens here.  ``api_key`` is only used for tests and
    interactive callers; the CLI deliberately does not accept it as an
    argument so it cannot leak into shell history.
    """
    raw = (provider or os.environ.get("EVBATT_AI_PROVIDER") or "off").strip().lower()
    raw = _ALIASES.get(raw, raw)
    if raw == "off":
        return None
    if raw not in _DEFAULTS:
        raise ValueError(f"Unknown EVBATT_AI_PROVIDER {raw!r}; choose from "
                         f"{sorted(_DEFAULTS) + ['off', 'local']}")
    default_url, default_model, cloud = _DEFAULTS[raw]
    key = api_key
    if not key:
        for env_name in _KEY_ENV[raw]:
            key = os.environ.get(env_name, "").strip()
            if key:
                break
    url = (base_url or os.environ.get("EVBATT_AI_BASE_URL") or default_url).rstrip("/")
    chosen_model = model or os.environ.get("EVBATT_AI_MODEL") or default_model
    timeout_raw = os.environ.get("EVBATT_AI_TIMEOUT_SEC", "").strip()
    timeout = 60.0
    if timeout_raw:
        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise ValueError("EVBATT_AI_TIMEOUT_SEC must be a number") from exc
        if timeout <= 0:
            raise ValueError("EVBATT_AI_TIMEOUT_SEC must be positive")
    cfg = AIConfig(
        provider=raw, base_url=url, api_key=key or "", model=chosen_model,
        timeout_sec=timeout,
        input_cost_per_mtok=_env_float("EVBATT_AI_INPUT_COST_PER_MTOK"),
        output_cost_per_mtok=_env_float("EVBATT_AI_OUTPUT_COST_PER_MTOK"),
    )
    if not cfg.base_url:
        raise ValueError("Custom provider requires EVBATT_AI_BASE_URL "
                         "(an OpenAI-compatible endpoint such as http://localhost:8000/v1).")
    if not cfg.model:
        raise ValueError("Set EVBATT_AI_MODEL for the custom provider (or run `evbatt ai models`).")
    # Loopback endpoints (Ollama, LM Studio, vLLM) commonly accept any/no
    # bearer token.  Only demand a key for non-local endpoints.
    if cloud and not cfg.api_key and not cfg.is_local:
        raise ValueError("AI provider selected but no API key found. Set EVBATT_AI_API_KEY "
                         "(see .env.example). The scientific pipeline works fully with AI off.")
    return cfg


def require_charge_optin(cfg: AIConfig, allow_chargeable: bool) -> None:
    """Raise unless the caller has opted in to a potentially billable call."""
    if cfg.needs_charge_confirmation and not allow_chargeable:
        raise ValueError(
            "Refusing to make a possibly chargeable API call without --allow-chargeable. "
            "Note: a ChatGPT/Claude subscription does not include API credits. "
            "Local endpoints (Ollama/LM Studio) do not need this flag.")


def _request(cfg: AIConfig, method: str, path: str, payload: dict | None) -> dict:
    url = f"{cfg.base_url}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if cfg.provider == "anthropic":
        req.add_header("x-api-key", cfg.api_key)
        req.add_header("anthropic-version", "2023-06-01")
    elif cfg.api_key:
        req.add_header("Authorization", f"Bearer {cfg.api_key}")
    if cfg.provider == "openrouter":
        req.add_header("HTTP-Referer", "https://github.com/ev-battery-science-benchmark")
        req.add_header("X-Title", "evbatt")
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_sec) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500] if exc.fp else ""
        hint = ""
        if exc.code in (401, 403):
            hint = " Check that the API key is valid and has access to this model."
        elif exc.code == 404:
            hint = (" Check EVBATT_AI_BASE_URL (include /v1 for OpenAI-compatible servers) "
                    "and the model name.")
        raise RuntimeError(f"AI provider HTTP {exc.code}: {detail.strip()}{hint}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            f"Cannot reach AI provider at {cfg.base_url}: {reason}. "
            "For local Ollama run `ollama serve` and check `evbatt ai test`.") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"AI provider timed out after {cfg.timeout_sec:.0f}s") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI provider returned non-JSON response: {body[:300]!r}") from exc


def list_models(cfg: AIConfig) -> list[str]:
    """Model discovery where the provider supports it (GET /models)."""
    path = "/v1/models" if cfg.provider == "anthropic" else "/models"
    data = _request(cfg, "GET", path, None)
    rows = data.get("data")
    if rows is None:  # some native servers nest models differently
        rows = data.get("models", [])
    ids = []
    for row in rows:
        if isinstance(row, str):
            ids.append(row)
        else:
            ident = row.get("id") or row.get("name") or row.get("model")
            if ident:
                ids.append(str(ident))
    return sorted(set(ids))


def test_connection(cfg: AIConfig, check_model: bool = True) -> dict:
    """Perform a real, read-only connectivity check (model listing)."""
    started = time.monotonic()
    models = list_models(cfg)
    elapsed = (time.monotonic() - started) * 1000.0
    selected_available = None
    if check_model and models:
        selected_available = cfg.model in models or any(
            m.split(":")[0] == cfg.model.split(":")[0] for m in models)
    return {
        "ok": True,
        "provider": cfg.provider,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "selected_model_available": selected_available,
        "n_models": len(models),
        "models": models[:20],
        "latency_ms": round(elapsed, 1),
        "local": cfg.is_local,
        "chargeable": cfg.needs_charge_confirmation,
        "hint": None if selected_available is not False else
                f"Model {cfg.model!r} not listed; run `ollama pull {cfg.model}` or set EVBATT_AI_MODEL.",
    }


def _normalise_usage(raw: dict | None) -> dict:
    raw = raw or {}
    prompt = raw.get("prompt_tokens", raw.get("input_tokens"))
    completion = raw.get("completion_tokens", raw.get("output_tokens"))
    total = raw.get("total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = int(prompt) + int(completion)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def _cost(cfg: AIConfig, usage: dict) -> dict:
    p, c = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if p is None or c is None or (cfg.input_cost_per_mtok is None
                                  and cfg.output_cost_per_mtok is None):
        return {"amount_usd": None, "currency": "USD",
                "note": "Set EVBATT_AI_INPUT_COST_PER_MTOK / "
                        "EVBATT_AI_OUTPUT_COST_PER_MTOK to estimate cost."}
    amount = ((p or 0) / 1e6) * (cfg.input_cost_per_mtok or 0.0) + \
             ((c or 0) / 1e6) * (cfg.output_cost_per_mtok or 0.0)
    return {"amount_usd": round(amount, 8), "currency": "USD",
            "note": "Estimate from user-supplied per-million-token prices."}


def chat(cfg: AIConfig, prompt: str, max_tokens: int = 800,
         temperature: float = 0.2) -> dict:
    """Send one prompt; return text, normalised usage, and an optional cost estimate."""
    if not prompt.strip():
        raise ValueError("Prompt must not be empty")
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    if cfg.provider == "anthropic":
        data = _request(cfg, "POST", "/v1/messages",
                        {"model": cfg.model, "max_tokens": max_tokens,
                         "temperature": temperature,
                         "messages": [{"role": "user", "content": prompt}]})
        text = "".join(block.get("text", "") for block in data.get("content", [])
                       if block.get("type", "text") == "text")
        stop = data.get("stop_reason")
    else:
        data = _request(cfg, "POST", "/chat/completions",
                        {"model": cfg.model, "temperature": temperature,
                         "max_tokens": max_tokens,
                         "messages": [{"role": "user", "content": prompt}]})
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"AI provider returned no choices: {json.dumps(data)[:400]}")
        text = choices[0].get("message", {}).get("content") or ""
        stop = choices[0].get("finish_reason")
    text = text.strip()
    if not text:
        raise RuntimeError("AI provider returned an empty response. If using Ollama, check "
                           f"that the model is pulled (`ollama pull {cfg.model}`).")
    usage = _normalise_usage(data.get("usage"))
    return {"text": text, "usage": usage, "cost": _cost(cfg, usage),
            "model": data.get("model", cfg.model), "provider": cfg.provider,
            "finish_reason": stop}


def explain_summary_with_usage(cfg: AIConfig, summary: dict, max_tokens: int = 800) -> dict:
    """Ask the LLM to *narrate* already-computed numbers (no new numerics)."""
    cells = summary.get("cells", {})
    prompt = (
        "You are explaining battery-degradation results that were already computed by a "
        "deterministic pipeline. Do not invent or change any numbers. Summarize each cell's "
        "selected model, EOL, fit quality, warnings, and the stated limitations in plain "
        "language for a battery researcher. Clearly mark anything that is extrapolated. "
        "Do not give safety-critical advice.\n\nDATA:\n"
        + json.dumps({"cells": cells, "limitations": summary.get("limitations", [])})[:12000])
    return chat(cfg, prompt, max_tokens=max_tokens)


def explain_summary(cfg: AIConfig, summary: dict, max_tokens: int = 800) -> str:
    """Backwards-compatible text-only helper."""
    return explain_summary_with_usage(cfg, summary, max_tokens=max_tokens)["text"]
