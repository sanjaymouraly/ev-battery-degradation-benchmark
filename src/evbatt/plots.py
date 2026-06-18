"""Publication-quality Matplotlib figures (headless-safe, Agg backend)."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .pipeline import AnalysisResult  # noqa: E402


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def plot_degradation(result: AnalysisResult, output_dir: str | Path) -> list[Path]:
    """Per-cell SOH with fit, intervals, anomalies + residual panels."""
    out = Path(output_dir)
    paths: list[Path] = []
    cells = sorted(result.clean_cycles["cell_id"].unique()) if len(result.clean_cycles) else []
    if not cells:
        return paths
    # Overview: all cells.
    fig, ax = plt.subplots(figsize=(9, 5))
    for cell in cells:
        g = result.clean_cycles[result.clean_cycles["cell_id"] == cell]
        ax.plot(g["cycle_index"], g["soh"], ".", ms=4, alpha=0.7, label=f"{cell} clean")
        u = result.uncertainty
        if len(u) and "cell_id" in u.columns:
            u = u[u["cell_id"] == cell].sort_values("cycle_index")
        else:
            u = u.iloc[0:0]
        if len(u):
            ax.plot(u["cycle_index"], u["soh_predicted"], "-", lw=1.5, label=f"{cell} fit")
            ax.fill_between(u["cycle_index"], u["pi_lo"], u["pi_hi"], alpha=0.15)
        a = result.anomalies
        if len(a) and "cell_id" in a.columns:
            a = a[a["cell_id"] == cell]
        else:
            a = a.iloc[0:0]
        if len(a):
            ax.plot(a["cycle_index"], a["soh"], "x", ms=8, mew=2, label=f"{cell} flagged")
    ax.axhline(0.8, color="red", ls="--", lw=1, label="EOL SOH=0.80")
    ax.set_xlabel("Cycle index (cycles)")
    ax.set_ylabel("SOH = Q / Q0 (-)")
    ax.set_title("Capacity degradation: clean data, selected fit, 95% prediction band")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    paths.append(_save(fig, out / "fig_soh_overview.png"))

    # Residuals per fitted cell.
    fig, axes = plt.subplots(len(cells), 1, figsize=(9, 2.2 * len(cells)), squeeze=False)
    for ax, cell in zip(axes[:, 0], cells):
        fit = result.fits.get(str(cell))
        if fit is None:
            ax.set_title(f"{cell}: no fit")
            continue
        ax.plot(fit["cycles_sorted"], fit["residuals"], ".", ms=4)
        ax.axhline(0, color="k", lw=1)
        ax.set_ylabel("Residual SOH (-)")
        ax.grid(alpha=0.3)
        ax.set_title(f"{cell} residuals ({fit['model']}, RMSE={fit['rmse']:.4f})", fontsize=10)
    axes[-1, 0].set_xlabel("Cycle index (cycles)")
    paths.append(_save(fig, out / "fig_residuals.png"))

    # Model comparison (AICc by cell/model).
    comp = result.model_comparison
    ok = comp[comp["status"] == "ok"] if len(comp) and "status" in comp.columns else comp
    if len(ok):
        pivot = ok.pivot_table(index="cell_id", columns="model", values="aicc")
        delta = pivot.sub(pivot.min(axis=1), axis=0)
        fig, ax = plt.subplots(figsize=(9, 4))
        delta.plot(kind="bar", ax=ax)
        ax.set_ylabel("ΔAICc vs best (-)")
        ax.set_xlabel("Cell")
        ax.set_title("Model comparison (lower is better; 0 = selected)")
        ax.legend(title="Model", fontsize=8)
        ax.grid(axis="y", alpha=0.3)
        paths.append(_save(fig, out / "fig_model_comparison.png"))
    return paths
