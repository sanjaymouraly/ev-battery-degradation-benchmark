"""AI provider layer tests: local HTTP servers only, no real credentials."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from typer.testing import CliRunner

from evbatt.ai import (chat, config_from_env, list_models, require_charge_optin,
                       test_connection as check_ai_connection)
from evbatt.cli import app

runner = CliRunner()


class _Handler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, *args):  # silence test output
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        type(self).requests.append({"method": "GET", "path": self.path,
                                    "headers": dict(self.headers)})
        if self.path.startswith("/err"):
            self._send(401, {"error": {"message": "bad key"}})
        elif self.path.endswith("/models"):
            self._send(200, {"object": "list", "data": [
                {"id": "gemma2:2b"}, {"id": "qwen2.5:1.5b"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append({"method": "POST", "path": self.path,
                                    "headers": dict(self.headers), "body": body})
        if self.path.endswith("/v1/messages"):
            self._send(200, {
                "id": "msg_1", "model": body.get("model"),
                "content": [{"type": "text", "text": "Anthropic summary."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 80, "output_tokens": 15}})
        else:
            self._send(200, {
                "id": "chat_1", "model": body.get("model"),
                "choices": [{"message": {"role": "assistant", "content": "Local summary."},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})


@pytest.fixture()
def server():
    handler = type("Handler", (_Handler,), {"requests": []})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1", handler
    httpd.shutdown()
    thread.join(timeout=5)


def _clear_ai_env(monkeypatch):
    for name in ["EVBATT_AI_PROVIDER", "EVBATT_AI_BASE_URL", "EVBATT_AI_API_KEY",
                 "EVBATT_AI_MODEL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                 "OPENROUTER_API_KEY", "EVBATT_AI_INPUT_COST_PER_MTOK",
                 "EVBATT_AI_OUTPUT_COST_PER_MTOK", "EVBATT_AI_TIMEOUT_SEC"]:
        monkeypatch.delenv(name, raising=False)


def test_ollama_local_needs_no_key_and_no_charge_flag(monkeypatch):
    _clear_ai_env(monkeypatch)
    cfg = config_from_env(provider="local", model="gemma2:2b")
    assert cfg is not None
    assert cfg.provider == "ollama"
    assert cfg.is_local and not cfg.needs_charge_confirmation
    assert cfg.base_url == "http://localhost:11434/v1"
    require_charge_optin(cfg, allow_chargeable=False)  # must not raise


def test_cloud_requires_key_and_optin(monkeypatch):
    _clear_ai_env(monkeypatch)
    with pytest.raises(ValueError, match="no API key"):
        config_from_env(provider="openai")
    cfg = config_from_env(provider="openai", api_key="sk-test-not-real")
    assert cfg is not None and cfg.needs_charge_confirmation
    with pytest.raises(ValueError, match="allow-chargeable"):
        require_charge_optin(cfg, allow_chargeable=False)
    require_charge_optin(cfg, allow_chargeable=True)
    assert "sk-test-not-real" not in json.dumps(cfg.redacted())


def test_openai_compatible_listing_and_chat_usage(server, monkeypatch):
    base, handler = server
    cfg = config_from_env(provider="ollama", base_url=base, model="gemma2:2b",
                          api_key="local")
    assert list_models(cfg) == ["gemma2:2b", "qwen2.5:1.5b"]
    status = check_ai_connection(cfg)
    assert status["ok"] and status["selected_model_available"] is True
    assert status["n_models"] == 2

    monkeypatch.setenv("EVBATT_AI_INPUT_COST_PER_MTOK", "1.0")
    monkeypatch.setenv("EVBATT_AI_OUTPUT_COST_PER_MTOK", "2.0")
    cfg = config_from_env(provider="ollama", base_url=base, model="gemma2:2b")
    out = chat(cfg, "Summarise this.", max_tokens=50)
    assert out["text"] == "Local summary."
    assert out["usage"] == {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    # 100/1e6*1 + 20/1e6*2
    assert out["cost"]["amount_usd"] == pytest.approx(0.00014)
    post = [r for r in handler.requests if r["method"] == "POST"][-1]
    assert post["path"].endswith("/chat/completions")
    assert post["body"]["model"] == "gemma2:2b"
    headers = {k.lower(): v for k, v in post["headers"].items()}
    assert "authorization" not in headers  # no key needed for local Ollama


def test_anthropic_request_shape(server):
    base, handler = server
    # Anthropic base URL has no /v1 suffix; endpoints are /v1/messages.
    root = base[:-3]
    cfg = config_from_env(provider="anthropic", base_url=root, api_key="sk-ant-test",
                          model="claude-haiku-4-5")
    assert list_models(cfg) == ["gemma2:2b", "qwen2.5:1.5b"]
    out = chat(cfg, "Explain.", max_tokens=64)
    assert out["text"] == "Anthropic summary."
    assert out["usage"]["prompt_tokens"] == 80
    post = [r for r in handler.requests if r["method"] == "POST"][-1]
    assert post["path"] == "/v1/messages"
    headers = {k.lower(): v for k, v in post["headers"].items()}
    assert headers.get("x-api-key") == "sk-ant-test"
    assert headers.get("anthropic-version") == "2023-06-01"
    assert "authorization" not in headers


def test_http_error_is_actionable_and_does_not_leak_key(server):
    base, _ = server
    cfg = config_from_env(provider="custom", base_url=base.replace("/v1", "/err"),
                          api_key="sk-super-secret", model="m")
    with pytest.raises(RuntimeError) as exc:
        list_models(cfg)
    msg = str(exc.value)
    assert "401" in msg and "API key" in msg
    assert "sk-super-secret" not in msg


def test_cli_ai_test_and_explain_against_local_server(server, monkeypatch, tmp_path):
    base, _ = server
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("EVBATT_AI_PROVIDER", "ollama")
    monkeypatch.setenv("EVBATT_AI_BASE_URL", base)
    monkeypatch.setenv("EVBATT_AI_MODEL", "gemma2:2b")
    r = runner.invoke(app, ["ai", "test"])
    assert r.exit_code == 0, r.output
    assert '"n_models": 2' in r.output
    r2 = runner.invoke(app, ["ai", "models"])
    assert r2.exit_code == 0 and "gemma2:2b" in r2.output
    r3 = runner.invoke(app, ["ai", "config"])
    assert r3.exit_code == 0 and "not required" in r3.output

    (tmp_path / "analysis.json").write_text(json.dumps({"cells": {"A": {"eol_cycle": 500}}}))
    r4 = runner.invoke(app, ["ai", "explain", str(tmp_path)])
    assert r4.exit_code == 0, r4.output
    assert "Local summary." in r4.output
    r5 = runner.invoke(app, ["ai", "explain", str(tmp_path), "--json"])
    assert r5.exit_code == 0
    payload = json.loads(r5.output)
    assert payload["usage"]["total_tokens"] == 120


def test_remote_explain_requires_flag(monkeypatch, tmp_path):
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("EVBATT_AI_PROVIDER", "openai")
    monkeypatch.setenv("EVBATT_AI_API_KEY", "sk-test-not-real")
    (tmp_path / "analysis.json").write_text('{"cells": {}}')
    r = runner.invoke(app, ["ai", "explain", str(tmp_path)])
    assert r.exit_code != 0
    assert "allow-chargeable" in r.output


def test_missing_analysis_json_is_clear(server, monkeypatch, tmp_path):
    base, _ = server
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("EVBATT_AI_PROVIDER", "ollama")
    monkeypatch.setenv("EVBATT_AI_BASE_URL", base)
    r = runner.invoke(app, ["ai", "explain", str(tmp_path)])
    assert r.exit_code != 0
    assert "No analysis.json" in r.output
