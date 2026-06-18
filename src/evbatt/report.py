"""Human-readable Markdown research reports (deterministic, no AI)."""
from __future__ import annotations

from pathlib import Path

from .pipeline import AnalysisResult, _atomic_write_text


def render_report(result: AnalysisResult, title: str = "EV Battery Degradation Analysis") -> str:
    s = result.summary
    lines = [f"# {title}", "",
             "## Method",
             f"- Reference capacity: {s['definitions']['reference_capacity']}.",
             f"- SOH definition: {s['definitions']['soh']}.",
             f"- EOL definition: {s['definitions']['eol']}.",
             "- Candidates: linear, sqrt, power, exponential, knee (bounded nonlinear least "
             "squares; selection by AICc with chronological hold-out RMSE reported).",
             "- Intervals: residual-bootstrap confidence/prediction intervals.",
             "- Flagged observations are listed in `anomalies.csv` with reason codes; "
             "nothing is silently discarded.", "",
             "## Results by cell", "",
             "| Cell | Status | Model | Q0 (Ah) | RMSE | Hold-out RMSE | EOL (95% CI) | Flagged n |",
             "|---|---|---|---:|---:|---:|---:|---:|"]
    for cell, info in s.get("cells", {}).items():
        def fmt(v, spec=".4f"):
            return "—" if v is None else format(v, spec)
        eol = info.get("eol_cycle")
        eol_s = fmt(eol, ".0f")
        ci = info.get("eol_ci")
        if ci:
            eol_s += f" ({ci[0]:.0f}–{ci[1]:.0f})"
        lines.append(
            f"| {cell} | {info.get('status', '?')} | {info.get('selected_model', '—')} "
            f"| {fmt(info.get('reference_capacity_Ah'), '.4f')} | {fmt(info.get('rmse'))} "
            f"| {fmt(info.get('holdout_rmse'))} | {eol_s} | {info.get('n_anomalies', 0)} |")
    param_rows = []
    for cell, info in s.get("cells", {}).items():
        for name, val in (info.get("parameter_uncertainty") or {}).items():
            if val.get("se") is not None:
                param_rows.append(
                    f"| {cell} | {name} | {info['params'].get(name):.6g} "
                    f"| {val['se']:.3g} | [{val['ci_lo']:.6g}, {val['ci_hi']:.6g}] |")
    if param_rows:
        lines += ["", "## Parameter uncertainty", "",
                  "Local normal-approximation intervals from the fit covariance. "
                  "They condition on the selected model family and are not valid at a bound.",
                  "", "| Cell | Parameter | Estimate | SE | 95% CI |", "|---|---|---:|---:|---|"]
        lines += param_rows
    lines += ["", "## Warnings", ""]
    any_w = False
    for cell, info in s.get("cells", {}).items():
        for w in info.get("warnings", []):
            lines.append(f"- **{cell}**: {w}")
            any_w = True
    if not any_w:
        lines.append("- None.")
    lines += ["", "## Limitations", ""]
    lines += [f"- {x}" for x in s.get("limitations", [])]
    lines += ["", "## Reproducibility", "",
              f"- Input SHA-256: `{s.get('input_sha256')}`",
              f"- Config: `{s.get('config')}`", ""]
    return "\n".join(lines)


def write_report(result: AnalysisResult, path: str | Path) -> Path:
    p = Path(path)
    _atomic_write_text(p, render_report(result))
    return p
