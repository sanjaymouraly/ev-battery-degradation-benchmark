"""evbatt command-line interface (works fully offline; AI is opt-in)."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from . import __version__

app = typer.Typer(help="EV battery degradation analysis (SOH/EOL, uncertainty, benchmarking).",
                  no_args_is_help=True)
ai_app = typer.Typer(help="Optional LLM explanations (never a numerical source of truth).")
data_app = typer.Typer(help="Dataset helpers (real Zenodo data, synthetic generation).")
app.add_typer(ai_app, name="ai")
app.add_typer(data_app, name="datasets")


def _echo_json(obj) -> None:
    typer.echo(json.dumps(obj, indent=2, default=str))


@app.command()
def version() -> None:
    """Print the evbatt version."""
    typer.echo(f"evbatt {__version__}")


@app.command()
def inspect(input: Path = typer.Argument(..., help="Cycle-level CSV/XLSX file")) -> None:
    """Inspect a dataset: schema, cells, ranges, data-quality report."""
    from .io import load_cycles
    df, report = load_cycles(input)
    info = {"file": str(input), "data_quality": report.to_dict(),
            "columns": list(df.columns),
            "cycle_range": [float(df["cycle_index"].min()), float(df["cycle_index"].max())],
            "capacity_Ah_range": [float(df["discharge_capacity_Ah"].min()),
                                  float(df["discharge_capacity_Ah"].max())],
            "cells": {str(c): int(len(g)) for c, g in df.groupby("cell_id")}}
    _echo_json(info)


@app.command()
def validate(input: Path = typer.Argument(..., help="Cycle-level CSV/XLSX file")) -> None:
    """Validate schema/units and run QC flagging; exit 1 if unusable."""
    from .io import load_cycles
    from .qc import quality_control
    from .schemas import AnalysisConfig
    df, report = load_cycles(input)
    qc = quality_control(df, AnalysisConfig())
    counts = qc["qc_status"].value_counts().to_dict()
    _echo_json({"data_quality": report.to_dict(), "qc_counts": {str(k): int(v) for k, v in counts.items()}})
    if int(counts.get("ok", 0)) == 0:
        raise typer.Exit(code=1)


@app.command()
def analyze(
    input: Path = typer.Argument(...),
    output_dir: Path = typer.Option(Path("results"), "--output-dir", "-o"),
    metadata: Path | None = typer.Option(None, "--metadata"),
    plots: bool = typer.Option(True, "--plots/--no-plots"),
    report: bool = typer.Option(True, "--report/--no-report"),
) -> None:
    """Run the full degradation analysis and write standard outputs."""
    from .pipeline import run_solver
    result = run_solver(input, metadata, output_dir)
    if plots:
        from .plots import plot_degradation
        plot_degradation(result, output_dir / "figs")
    if report:
        from .report import write_report
        write_report(result, output_dir / "report.md")
    for cell, info in result.summary["cells"].items():
        typer.echo(f"{cell}: status={info.get('status')} model={info.get('selected_model')} "
                   f"EOL={info.get('eol_cycle')} RMSE={info.get('rmse')}")
    typer.echo(f"Wrote outputs to {output_dir}")


@app.command()
def compare(dirs: list[Path] = typer.Argument(..., help="Two or more analysis output dirs")) -> None:
    """Compare analysis.json summaries across runs/cells/conditions."""
    rows = []
    for d in dirs:
        s = json.loads((d / "analysis.json").read_text(encoding="utf-8"))
        for cell, info in s.get("cells", {}).items():
            rows.append({"run": str(d), "cell": cell, "model": info.get("selected_model"),
                         "eol_cycle": info.get("eol_cycle"), "rmse": info.get("rmse"),
                         "holdout_rmse": info.get("holdout_rmse")})
    _echo_json(rows)


@app.command()
def benchmark(
    input: Path = typer.Argument(..., help="Benchmark input CSV"),
    metadata: Path = typer.Argument(..., help="Benchmark metadata JSON"),
    output_dir: Path = typer.Option(Path("benchmark_results"), "--output-dir", "-o"),
) -> None:
    """Run the benchmark solver contract locally (same files as Harbor)."""
    from .pipeline import run_solver
    run_solver(input, metadata, output_dir)
    typer.echo(f"Benchmark outputs written to {output_dir}")


@data_app.command("synthetic")
def datasets_synthetic(
    output: Path = typer.Option(Path("data/synthetic.csv"), "--output", "-o"),
    truth_output: Path | None = typer.Option(None, "--truth-output"),
    n_cells: int = typer.Option(4, "--n-cells"),
    max_cycle: int = typer.Option(800, "--max-cycle"),
    seed: int = typer.Option(42, "--seed"),
) -> None:
    """Generate a synthetic dataset with recorded ground truth."""
    from .synthetic import generate_dataset
    df, truth = generate_dataset(n_cells=n_cells, max_cycle=max_cycle, seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    typer.echo(f"Wrote {len(df)} rows ({n_cells} cells) to {output} [SYNTHETIC - not a real experiment]")
    if truth_output:
        truth_output.write_text(json.dumps(truth.to_dict(), indent=2), encoding="utf-8")
        typer.echo(f"Wrote ground truth to {truth_output} (keep away from benchmark agents)")


@data_app.command("zenodo-info")
def datasets_zenodo_info() -> None:
    """Fetch live metadata for the real LFP dataset (DOI 10.5281/zenodo.22286450)."""
    from .zenodo import fetch_record, record_summary
    _echo_json(record_summary(fetch_record()))


@data_app.command("mstat-to-cycles")
def datasets_mstat(
    source: Path = typer.Argument(..., help="Zenodo .zip or extracted directory"),
    output: Path = typer.Option(Path("data/lfp_cycles.csv"), "--output", "-o"),
    jobs: int = typer.Option(1, "--jobs", help="Parallel workbook workers"),
) -> None:
    """Extract cycle-level capacities from Solartron MSTAT workbooks."""
    from .mstat import extract_cycles
    df = extract_cycles(source, jobs=jobs)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    typer.echo(f"Wrote {len(df)} cycles / {df['cell_id'].nunique()} cells to {output}")
    typer.echo("Source: Japar et al., DOI 10.5281/zenodo.22286450 (CC-BY-4.0) — attribute on reuse.")


@data_app.command("zenodo-download")
def datasets_zenodo_download(
    dest: Path = typer.Option(Path("data/zenodo"), "--dest"),
    yes: bool = typer.Option(False, "--yes", help="Confirm the 2.26 GB download"),
) -> None:
    """Download the 2.26 GB LFP archive with MD5 verification (CC-BY-4.0)."""
    if not yes:
        raise typer.BadParameter("This downloads 2.26 GB. Re-run with --yes to confirm.")
    from .zenodo import download_archive
    path = download_archive(dest)
    typer.echo(f"Downloaded and MD5-verified: {path}")


def _ai_config(provider: str | None = None, model: str | None = None,
               base_url: str | None = None):
    from .ai import config_from_env
    try:
        return config_from_env(provider=provider, model=model, base_url=base_url)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@ai_app.command("config")
def ai_config() -> None:
    """Show the effective AI configuration (keys are redacted)."""
    cfg = _ai_config()
    if cfg is None:
        _echo_json({"provider": "off", "note": "Set EVBATT_AI_PROVIDER=ollama for local use; "
                                               "see .env.example. The pipeline works fully offline."})
        return
    _echo_json(cfg.redacted())


@ai_app.command("test")
def ai_test(
    provider: str | None = typer.Option(None, "--provider", help="Override EVBATT_AI_PROVIDER"),
    model: str | None = typer.Option(None, "--model", help="Override EVBATT_AI_MODEL"),
    base_url: str | None = typer.Option(None, "--base-url", help="Override EVBATT_AI_BASE_URL"),
) -> None:
    """Check connectivity and list the provider's models (read-only, no generation)."""
    from .ai import test_connection
    cfg = _ai_config(provider, model, base_url)
    if cfg is None:
        typer.echo("AI is off (EVBATT_AI_PROVIDER unset). See .env.example.")
        raise typer.Exit(code=0)
    try:
        _echo_json(test_connection(cfg))
    except RuntimeError as exc:
        typer.echo(f"AI connection failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@ai_app.command("models")
def ai_models(
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
    base_url: str | None = typer.Option(None, "--base-url"),
    as_json: bool = typer.Option(False, "--json", help="Emit a JSON object instead of one ID per line"),
) -> None:
    """List models from the configured AI provider."""
    from .ai import list_models
    cfg = _ai_config(provider, model, base_url)
    if cfg is None:
        typer.echo("AI is off (EVBATT_AI_PROVIDER unset). See .env.example.")
        raise typer.Exit(code=0)
    try:
        models = list_models(cfg)
    except RuntimeError as exc:
        typer.echo(f"AI model listing failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json({"provider": cfg.provider, "base_url": cfg.base_url,
                    "model": cfg.model, "models": models})
    else:
        for m in models:
            typer.echo(m)


@ai_app.command("explain")
def ai_explain(
    results_dir: Path = typer.Argument(..., help="Directory containing analysis.json"),
    allow_chargeable: bool = typer.Option(False, "--allow-chargeable",
                                           help="Confirm you accept possible API charges"),
    provider: str | None = typer.Option(None, "--provider", help="Override EVBATT_AI_PROVIDER"),
    model: str | None = typer.Option(None, "--model", help="Override EVBATT_AI_MODEL"),
    base_url: str | None = typer.Option(None, "--base-url", help="Override EVBATT_AI_BASE_URL"),
    max_tokens: int = typer.Option(800, "--max-tokens", min=1, max=8192),
    as_json: bool = typer.Option(False, "--json", help="Emit text plus usage/cost as JSON"),
) -> None:
    """Narrate already-computed results with an LLM (opt-in for remote providers)."""
    from .ai import explain_summary_with_usage, require_charge_optin
    cfg = _ai_config(provider, model, base_url)
    if cfg is None:
        typer.echo("AI is off. Set EVBATT_AI_PROVIDER=ollama (local) or a cloud provider "
                   "and key (see .env.example), or use the deterministic report.md instead.")
        raise typer.Exit(code=0)
    try:
        require_charge_optin(cfg, allow_chargeable)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    analysis_path = results_dir / "analysis.json"
    if not analysis_path.is_file():
        raise typer.BadParameter(f"No analysis.json in {results_dir}")
    summary = json.loads(analysis_path.read_text(encoding="utf-8"))
    try:
        result = explain_summary_with_usage(cfg, summary, max_tokens=max_tokens)
    except RuntimeError as exc:
        typer.echo(f"AI request failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json(result)
        return
    typer.echo(result["text"])
    u = result["usage"]
    typer.echo(f"\n[AI] {cfg.provider}/{result['model']}  tokens: "
               f"{u.get('prompt_tokens')} in + {u.get('completion_tokens')} out"
               f" = {u.get('total_tokens')} total", err=True)
    if result["cost"].get("amount_usd") is not None:
        typer.echo(f"[AI] estimated cost: ${result['cost']['amount_usd']:.6f} USD "
                   "(user-supplied prices)", err=True)


if __name__ == "__main__":
    app()
