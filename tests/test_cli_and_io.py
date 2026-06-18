"""CLI, file-contract, Excel, and AI-config tests (no network, no charges)."""
import json

import pandas as pd
import pytest
from typer.testing import CliRunner

from evbatt.ai import config_from_env
from evbatt.cli import app
from evbatt.pipeline import OUTPUT_FILES, run_solver
from evbatt.synthetic import generate_dataset

runner = CliRunner()


def test_cli_help_and_version():
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert "evbatt" in runner.invoke(app, ["version"]).output


def test_solver_file_contract(tmp_path):
    df, _ = generate_dataset(n_cells=2, max_cycle=400, seed=5)
    inp = tmp_path / "in.csv"
    df.to_csv(inp, index=False)
    meta = tmp_path / "metadata.json"
    meta.write_text(json.dumps({"forecast_cycles": [400, 500],
                                "config": {"n_bootstrap": 20}}), encoding="utf-8")
    out = tmp_path / "out"
    run_solver(inp, meta, out)
    for name in OUTPUT_FILES:
        assert (out / name).is_file(), name
    summary = json.loads((out / "analysis.json").read_text(encoding="utf-8"))
    assert summary["input_sha256"]
    assert set(summary["cells"]) == {"CELL-01", "CELL-02"}
    pred = pd.read_csv(out / "predictions.csv")
    assert set(pred["cycle_index"].unique()) == {400.0, 500.0}
    assert pred["soh_predicted"].between(0, 1.1).all()


def test_cli_analyze_end_to_end(tmp_path):
    df, _ = generate_dataset(n_cells=2, max_cycle=300, seed=9)
    inp = tmp_path / "in.csv"
    df.to_csv(inp, index=False)
    r = runner.invoke(app, ["analyze", str(inp), "-o", str(tmp_path / "res"), "--no-plots"])
    assert r.exit_code == 0, r.output
    r2 = runner.invoke(app, ["inspect", str(inp)])
    assert r2.exit_code == 0 and "data_quality" in r2.output
    r3 = runner.invoke(app, ["validate", str(inp)])
    assert r3.exit_code == 0


def test_empty_forecast_cycles_falls_back_to_default_grid(tmp_path):
    """An empty forecast list must not crash plotting or emit column-less CSVs."""
    df, _ = generate_dataset(n_cells=1, max_cycle=120, seed=11)
    inp = tmp_path / "in.csv"
    df.to_csv(inp, index=False)
    meta = tmp_path / "metadata.json"
    meta.write_text(json.dumps({"forecast_cycles": [],
                                "config": {"n_bootstrap": 10}}), encoding="utf-8")
    out = tmp_path / "out"
    r = runner.invoke(app, ["analyze", str(inp), "--metadata", str(meta),
                            "-o", str(out)])
    assert r.exit_code == 0, r.output
    for name in ("uncertainty.csv", "predictions.csv", "model_comparison.csv"):
        df_out = pd.read_csv(out / name)
        assert len(df_out.columns) > 0, name
    unc = pd.read_csv(out / "uncertainty.csv")
    assert len(unc) > 0 and {"cell_id", "cycle_index", "ci_lo", "ci_hi"} <= set(unc.columns)


def test_output_files_are_readable_not_owner_only(tmp_path):
    """Atomic writes must not leave artefacts at mode 0600 (owner-only)."""
    df, _ = generate_dataset(n_cells=1, max_cycle=100, seed=3)
    inp = tmp_path / "in.csv"
    df.to_csv(inp, index=False)
    out = tmp_path / "out"
    r = runner.invoke(app, ["analyze", str(inp), "-o", str(out), "--no-plots"])
    assert r.exit_code == 0, r.output
    for name in OUTPUT_FILES:
        mode = (out / name).stat().st_mode & 0o777
        assert mode & 0o044, f"{name} is not group/other readable (mode {mode:o})"


def test_excel_roundtrip(tmp_path):
    df, _ = generate_dataset(n_cells=1, max_cycle=100, seed=2)
    p = tmp_path / "in.xlsx"
    df.to_excel(p, index=False)
    from evbatt.io import load_cycles
    out, report = load_cycles(p)
    assert report.n_rows == len(df)


def test_ai_off_by_default_and_missing_key_errors(monkeypatch):
    monkeypatch.delenv("EVBATT_AI_PROVIDER", raising=False)
    assert config_from_env() is None
    monkeypatch.setenv("EVBATT_AI_PROVIDER", "openai")
    monkeypatch.delenv("EVBATT_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="no API key"):
        config_from_env()
    monkeypatch.setenv("EVBATT_AI_API_KEY", "sk-test-not-real")
    cfg = config_from_env()
    assert cfg.provider == "openai" and cfg.model  # config only; no network call made


def test_ai_explain_refuses_without_optin(tmp_path, monkeypatch):
    monkeypatch.setenv("EVBATT_AI_PROVIDER", "custom")
    monkeypatch.setenv("EVBATT_AI_BASE_URL", "http://localhost:9/v1")
    monkeypatch.setenv("EVBATT_AI_API_KEY", "x")
    monkeypatch.setenv("EVBATT_AI_MODEL", "m")
    (tmp_path / "analysis.json").write_text('{"cells": {}}', encoding="utf-8")
    r = runner.invoke(app, ["ai", "explain", str(tmp_path)])
    assert r.exit_code != 0  # must refuse chargeable call without --allow-chargeable


def test_corrupt_file_gives_clear_error(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    r = runner.invoke(app, ["inspect", str(p)])
    assert r.exit_code != 0
