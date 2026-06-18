"""End-to-end degradation analysis pipeline and benchmark solver contract.

``run_analysis`` takes a normalised cycle table and returns all
scientific products as DataFrames/dicts.  ``run_solver`` implements
the file contract shared by the CLI and the Harbor benchmark task:

Inputs:  ``--input cycling.csv --metadata metadata.json --output-dir DIR``
Outputs in DIR: ``analysis.json``, ``clean_cycles.csv``,
``anomalies.csv``, ``model_comparison.csv``, ``uncertainty.csv``,
``predictions.csv``.  ``metadata.json`` may specify
``forecast_cycles`` (list per cell or global), ``eol_soh`` and
``config`` overrides.  Writes are atomic (temp file + rename).
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .io import load_cycles, load_metadata
from .models import compare_models, eol_cycle, parameter_uncertainty, predict
from .qc import coulombic_efficiency, quality_control
from .schemas import AnalysisConfig
from .uncertainty import bootstrap_intervals

OUTPUT_FILES = ["analysis.json", "clean_cycles.csv", "anomalies.csv",
                "model_comparison.csv", "uncertainty.csv", "predictions.csv"]

# Fixed column orders keep the CSV contract stable even when a table is empty
# (e.g. no cell produced a successful fit).
UNCERTAINTY_COLUMNS = ["cell_id", "cycle_index", "model", "soh_predicted", "ci_lo",
                        "ci_hi", "pi_lo", "pi_hi", "confidence_level", "is_extrapolation"]
PREDICTION_COLUMNS = ["cell_id", "cycle_index", "model", "soh_predicted",
                      "capacity_predicted_Ah", "is_extrapolation"]
MODEL_COMPARISON_COLUMNS = ["cell_id", "model", "status", "params_json", "rmse", "mae",
                            "aicc", "bic", "holdout_rmse", "n_params", "at_bound", "selected"]


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        # mkstemp creates the file 0600 (owner-only).  Analysis outputs are
        # meant to be readable by collaborators and CI jobs, so relax to the
        # process umask default before publishing the file.
        os.chmod(tmp, 0o666 & ~_current_umask())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _current_umask() -> int:
    """The process umask, read once at import time.

    ``os.umask`` is process-global and not thread-safe, so it is queried a
    single time (import) rather than on every write.
    """
    return _UMASK


_UMASK = os.umask(0)
os.umask(_UMASK)


def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    _atomic_write_text(path, df.to_csv(index=False))


@dataclass
class AnalysisResult:
    qc_table: pd.DataFrame
    clean_cycles: pd.DataFrame
    anomalies: pd.DataFrame
    model_comparison: pd.DataFrame
    uncertainty: pd.DataFrame
    predictions: pd.DataFrame
    summary: dict = field(default_factory=dict)
    fits: dict = field(default_factory=dict)


def _default_forecast_cycles(max_cycle: float) -> np.ndarray:
    extra = [max_cycle + d for d in (50, 100, 200)]
    grid = np.unique(np.concatenate([np.linspace(0, max_cycle, 21), extra]))
    return np.round(grid).astype(int)


def run_analysis(
    df: pd.DataFrame,
    config: AnalysisConfig | None = None,
    forecast_cycles: dict[str, list[float]] | list[float] | None = None,
    metadata: dict | None = None,
    input_sha256: str | None = None,
) -> AnalysisResult:
    config = config or AnalysisConfig()
    qc = quality_control(df, config)
    qc["coulombic_efficiency"] = coulombic_efficiency(qc)
    clean = qc[qc["qc_status"] == "ok"].copy()
    anomalies = qc[qc["qc_status"] != "ok"][
        ["cell_id", "cycle_index", "discharge_capacity_Ah", "soh", "qc_status", "qc_reason"]
    ].copy()

    comp_rows, unc_rows, pred_rows = [], [], []
    summary: dict = {
        "schema_version": "1.0",
        "units": {"capacity": "Ah", "cycle_index": "cycles (count)", "soh": "dimensionless (Q/Q0)",
                  "temperature": "degC", "crate": "C (1/h)"},
        "definitions": {
            "reference_capacity": f"median of first {config.n_reference} valid discharge capacities per cell",
            "soh": "discharge_capacity_Ah / reference_capacity_Ah",
            "eol": f"first cycle where selected model SOH crosses {config.eol_soh}",
        },
        "config": config.model_dump(),
        "input_sha256": input_sha256,
        "metadata": metadata or {},
        "limitations": [
            "Empirical SOH(k) fits do not identify electrochemical degradation mechanisms.",
            "Residual bootstrap assumes approximately independent residuals; serial "
            "correlation within a cell makes intervals optimistic.",
            "Extrapolation beyond the observed cycle range is model-dependent; "
            "treat forecasts past the data range as provisional.",
            "Cell-level laboratory results do not directly predict EV pack-level life "
            "(imbalance, thermal gradients, BMS limits are not modelled).",
        ],
        "cells": {},
    }
    fits: dict = {}
    for cell, group in clean.groupby("cell_id"):
        g = group.sort_values("cycle_index")
        k = g["cycle_index"].to_numpy(dtype=float)
        y = g["soh"].to_numpy(dtype=float)
        q0 = float(g["reference_capacity_Ah"].iloc[0])
        cell_info: dict = {"n_clean": int(len(g)), "reference_capacity_Ah": q0,
                           "temperature_C_median": (float(np.nanmedian(g["temperature_C"]))
                           if g["temperature_C"].notna().any() else None),
                           "warnings": []}
        if len(g) < config.min_cycles_per_cell:
            cell_info["status"] = "insufficient_data"
            cell_info["warnings"].append(
                f"Only {len(g)} clean cycles (< {config.min_cycles_per_cell}); no model fitted.")
            summary["cells"][str(cell)] = cell_info
            continue
        try:
            comparisons = compare_models(k, y, robust=config.robust_loss,
                                         holdout_fraction=config.holdout_fraction)
        except Exception as exc:
            cell_info["status"] = f"fit_failed: {exc}"
            summary["cells"][str(cell)] = cell_info
            continue
        ok = [c for c in comparisons if c.get("status") == "ok"]
        if not ok:
            cell_info["status"] = "all_fits_failed"
            summary["cells"][str(cell)] = cell_info
            continue
        best = ok[0]
        # Second pass, bidirectional (one iteration):
        # (a) flag clean points with extreme residuals vs the robustly
        #     fitted best model (missed corruptions), and
        # (b) rescue first-pass trend-screen flags that the model finds
        #     consistent (the local-median screen over-flags genuine
        #     points near degradation knees; measured on synthetic
        #     truth: FN~0 but many knee FPs without rescue).
        # Guard: if >10% of clean points would be newly flagged,
        # suspect model mismatch and keep the first-pass result.
        resid = y - predict(best["model"], best["params"], k)
        mad = np.median(np.abs(resid - np.median(resid)))
        sigma = 1.4826 * mad if mad > 0 else float(np.std(resid))
        cell_info["n_second_pass_flagged"] = 0
        cell_info["n_restored"] = 0
        if sigma > 0:
            extra = np.abs(resid) > config.anomaly_mad_threshold * sigma
            do_flag = bool(extra.any() and extra.mean() <= 0.10
                           and int((~extra).sum()) >= config.min_cycles_per_cell)
            cand = qc[(qc["cell_id"] == cell) & (qc["qc_status"] == "anomaly")
                      & (qc["qc_reason"] == "robust_residual_outlier")]
            rescue_idx = cand.index[
                np.abs(cand["soh"].to_numpy(dtype=float)
                       - predict(best["model"], best["params"],
                                 cand["cycle_index"].to_numpy(dtype=float))) <= 2.5 * sigma
            ] if len(cand) else cand.index
            if do_flag or len(rescue_idx):
                if do_flag:
                    drop_idx = g.index[extra]
                    qc.loc[drop_idx, "qc_status"] = "anomaly"
                    qc.loc[drop_idx, "qc_reason"] = "model_residual_outlier"
                    cell_info["n_second_pass_flagged"] = int(extra.sum())
                if len(rescue_idx):
                    qc.loc[rescue_idx, "qc_status"] = "ok"
                    qc.loc[rescue_idx, "qc_reason"] = ""
                    cell_info["n_restored"] = int(len(rescue_idx))
                g = qc[(qc["cell_id"] == cell) & (qc["qc_status"] == "ok")] \
                    .sort_values("cycle_index")
                k = g["cycle_index"].to_numpy(dtype=float)
                y = g["soh"].to_numpy(dtype=float)
                cell_info["n_clean"] = int(len(g))
                comparisons = compare_models(k, y, robust=config.robust_loss,
                                             holdout_fraction=config.holdout_fraction)
                ok = [c for c in comparisons if c.get("status") == "ok"]
                if ok:
                    best = ok[0]
        fits[str(cell)] = best
        for rank, c in enumerate(comparisons):
            if c.get("status") != "ok":
                comp_rows.append({"cell_id": cell, "model": c["model"], "status": c["status"],
                                  "selected": False})
                continue
            comp_rows.append({
                "cell_id": cell, "model": c["model"], "status": "ok",
                "params_json": json.dumps(c["params"]), "rmse": c["rmse"], "mae": c["mae"],
                "aicc": c["aicc"], "bic": c["bic"], "holdout_rmse": c.get("holdout_rmse", np.nan),
                "n_params": c["n_params"], "at_bound": bool(c.get("at_bound", False)),
                "selected": c["model"] == best["model"] and rank == 0,
            })
        eol = eol_cycle(best["model"], best["params"], config.eol_soh, config.eol_max_cycles)
        max_k = float(k.max())
        fc = forecast_cycles
        if isinstance(fc, dict):
            fc = fc.get(str(cell)) or fc.get("default")
        # An absent or empty forecast specification means "use the automatic
        # grid"; an empty grid would otherwise produce empty output tables.
        eval_cycles = (np.asarray(fc, dtype=float) if fc is not None and len(fc) > 0
                       else _default_forecast_cycles(max_k))
        intervals = bootstrap_intervals(
            best["model"], k, y, best, eval_cycles,
            n_bootstrap=config.n_bootstrap, seed=config.bootstrap_seed,
            level=config.confidence_level,
            eol_threshold=config.eol_soh, eol_max_cycles=config.eol_max_cycles)
        param_unc = parameter_uncertainty(best, config.confidence_level)
        # A local covariance is not meaningful at a bound or for a nearly
        # flat likelihood surface; expose that rather than hiding it.
        if any(v["se"] is None for v in param_unc.values()):
            cell_info["warnings"].append(
                "Parameter covariance is not available; parameter intervals are undefined.")
        elif any(v["se"] > abs(best["params"][name]) for name, v in param_unc.items()
                 if abs(best["params"][name]) > 1e-12):
            cell_info["warnings"].append(
                "At least one parameter has a standard error larger than its estimate "
                "(weakly identified); treat its value and intervals cautiously.")
        resid_trend = np.polyfit(k, best["residuals"], 1)[0] * 1000.0
        cell_info["residual_drift_per_1000_cycles"] = float(resid_trend)
        if abs(resid_trend) > 0.02:
            cell_info["warnings"].append(
                f"Residual trend {resid_trend:+.4f} SOH/1000 cycles suggests unmodelled "
                "drift or changing measurement conditions.")
        for j, cyc in enumerate(intervals["cycles"]):
            pred_rows.append({
                "cell_id": cell, "cycle_index": float(cyc), "model": best["model"],
                "soh_predicted": float(intervals["prediction"][j]),
                "capacity_predicted_Ah": float(intervals["prediction"][j] * q0),
                "is_extrapolation": bool(cyc > max_k),
            })
            unc_rows.append({
                "cell_id": cell, "cycle_index": float(cyc), "model": best["model"],
                "soh_predicted": float(intervals["prediction"][j]),
                "ci_lo": float(intervals["ci_lo"][j]), "ci_hi": float(intervals["ci_hi"][j]),
                "pi_lo": float(intervals["pi_lo"][j]), "pi_hi": float(intervals["pi_hi"][j]),
                "confidence_level": config.confidence_level,
                "is_extrapolation": bool(cyc > max_k),
            })
        # Physical-validity diagnostics.
        pred_grid = predict(best["model"], best["params"], eval_cycles)
        if np.any(pred_grid > 1.05) or np.any(pred_grid < 0):
            cell_info["warnings"].append("Selected model predicts SOH outside [0, 1.05] on the eval grid.")
        if best.get("at_bound"):
            cell_info["warnings"].append(
                "Selected fit sits on a parameter bound; parameters weakly identified.")
        if eol is None:
            cell_info["warnings"].append(
                f"EOL undefined: selected model does not reach SOH={config.eol_soh} within "
                f"{config.eol_max_cycles:.0f} cycles (extrapolation not warranted).")
        elif eol > max_k:
            cell_info["warnings"].append(
                f"EOL ({eol:.0f}) lies beyond observed range (max {max_k:.0f} cycles); extrapolated value.")
        eol_lo, eol_hi = intervals.get("eol_ci_lo"), intervals.get("eol_ci_hi")
        if eol is not None and eol_lo is not None and eol_hi is not None:
            cell_info["eol_ci"] = [float(eol_lo), float(eol_hi)]
            cell_info["eol_ci_level"] = config.confidence_level
        else:
            cell_info["eol_ci"] = None
        cell_info.update({
            "status": "ok", "selected_model": best["model"], "params": best["params"],
            "parameter_uncertainty": param_unc,
            "rmse": best["rmse"], "mae": best["mae"], "aicc": best["aicc"],
            "bic": best.get("bic"), "holdout_rmse": best.get("holdout_rmse"), "eol_cycle": eol,
            "eol_soh_threshold": config.eol_soh, "max_observed_cycle": max_k,
            "n_anomalies": int(((qc["cell_id"] == cell) & (qc["qc_status"] != "ok")).sum()),
            "bootstrap_successful": int(intervals["n_successful"]),
        })
        summary["cells"][str(cell)] = cell_info

    # Rebuild clean/anomalies so second-pass flags are reflected.
    clean_final = qc[qc["qc_status"] == "ok"]
    anomalies = qc[qc["qc_status"] != "ok"][
        ["cell_id", "cycle_index", "discharge_capacity_Ah", "soh", "qc_status", "qc_reason"]
    ].copy()
    clean_out = clean_final[["cell_id", "cycle_index", "discharge_capacity_Ah", "charge_capacity_Ah",
                             "temperature_C", "discharge_crate", "charge_crate", "depth_of_discharge",
                             "reference_capacity_Ah", "soh", "coulombic_efficiency"]].copy()
    return AnalysisResult(
        qc_table=qc, clean_cycles=clean_out, anomalies=anomalies,
        model_comparison=pd.DataFrame(comp_rows, columns=MODEL_COMPARISON_COLUMNS),
        uncertainty=pd.DataFrame(unc_rows, columns=UNCERTAINTY_COLUMNS),
        predictions=pd.DataFrame(pred_rows, columns=PREDICTION_COLUMNS),
        summary=summary, fits=fits)


def write_outputs(result: AnalysisResult, output_dir: str | Path) -> list[Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(out / "analysis.json", json.dumps(result.summary, indent=2, default=str))
    _atomic_write_csv(result.clean_cycles, out / "clean_cycles.csv")
    _atomic_write_csv(result.anomalies, out / "anomalies.csv")
    _atomic_write_csv(result.model_comparison, out / "model_comparison.csv")
    _atomic_write_csv(result.uncertainty, out / "uncertainty.csv")
    _atomic_write_csv(result.predictions, out / "predictions.csv")
    return [out / f for f in OUTPUT_FILES]


def run_solver(input_path: str | Path, metadata_path: str | Path | None,
               output_dir: str | Path) -> AnalysisResult:
    """Benchmark/CLI solver contract: files in, standard outputs out."""
    from .io import file_sha256

    df, _report = load_cycles(input_path)
    metadata = load_metadata(metadata_path)
    overrides = dict(metadata.get("config", {}))
    if "eol_soh" in metadata:
        overrides["eol_soh"] = metadata["eol_soh"]
    config = AnalysisConfig(**overrides)
    result = run_analysis(df, config=config,
                          forecast_cycles=metadata.get("forecast_cycles"),
                          metadata=metadata, input_sha256=file_sha256(input_path))
    result.summary["data_quality"] = _report.to_dict()
    write_outputs(result, output_dir)
    # Re-write analysis.json now that data_quality was added.
    _atomic_write_text(Path(output_dir) / "analysis.json",
                       json.dumps(result.summary, indent=2, default=str))
    return result
