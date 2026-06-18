"""Quality control, anomaly flagging, and reference-capacity estimation.

Philosophy: flag with reason codes, never silently delete.  Three tiers:

1. ``invalid`` — unparseable/non-positive capacity, negative cycle,
   out-of-range metadata.  These cannot enter any calculation.
2. ``duplicate`` — repeated (cell, cycle) rows; the first occurrence is
   kept and later copies flagged (instrument re-exports are common).
3. ``anomaly`` — physically implausible values (capacity far above the
   reference) or large robust residuals vs. a preliminary per-cell
   trend.  These are *candidate* corruptions: excluded from fitting
   but always reported so a researcher can override the decision.

The residual screen uses a rolling-median detrending with a
median-absolute-deviation (MAD) scale, which needs no parametric
assumption and is itself insensitive to the outliers it detects.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schemas import AnalysisConfig


def reference_capacity(capacities: np.ndarray, n_reference: int = 3) -> float:
    """Median of the first ``n_reference`` valid capacities (cycle order)."""
    vals = np.asarray(capacities, dtype=float)
    vals = vals[np.isfinite(vals) & (vals > 0)]
    if len(vals) == 0:
        raise ValueError("No valid capacity measurements for reference-capacity estimation")
    return float(np.median(vals[:n_reference]))


def _mad_residual_flags(soh: np.ndarray, threshold: float) -> np.ndarray:
    """Flag points whose detrended residual exceeds threshold * robust sigma."""
    y = np.asarray(soh, dtype=float)
    n = len(y)
    if n < 7:
        return np.zeros(n, dtype=bool)
    s = pd.Series(y)
    window = min(7, n if n % 2 == 1 else n - 1)
    trend = s.rolling(window=window, center=True, min_periods=3).median().to_numpy()
    trend = pd.Series(trend).ffill().bfill().to_numpy()
    resid = y - trend
    mad = np.median(np.abs(resid - np.median(resid)))
    sigma = 1.4826 * mad
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = float(np.std(resid)) or 1e-9
    return np.abs(resid) > threshold * sigma


def quality_control(df: pd.DataFrame, config: AnalysisConfig) -> pd.DataFrame:
    """Return ``df`` with qc_status/qc_reason/soh columns (no rows dropped)."""
    out = df.copy()
    out["qc_status"] = "ok"
    out["qc_reason"] = ""
    out["reference_capacity_Ah"] = np.nan
    out["soh"] = np.nan
    tmin, tmax = config.temperature_range_C

    def mark(mask: pd.Series, status: str, reason: str, only_ok: bool = True) -> None:
        sel = mask & (out["qc_status"] == "ok") if only_ok else mask
        out.loc[sel & (out["qc_status"] == "ok"), "qc_status"] = status
        out.loc[sel & (out["qc_reason"] == ""), "qc_reason"] = reason

    mark(out["cycle_index"].isna() | (out["cycle_index"] < 0), "invalid", "cycle_index_missing_or_negative")
    mark(out["discharge_capacity_Ah"].isna(), "invalid", "capacity_missing")
    mark(out["discharge_capacity_Ah"] <= 0, "invalid", "capacity_nonpositive")
    mark(out["discharge_capacity_Ah"] > config.max_capacity_Ah, "invalid", "capacity_above_physical_limit")
    bad_temp = out["temperature_C"].notna() & ~out["temperature_C"].between(tmin, tmax)
    crates = out["discharge_crate"]
    bad_crate = crates.notna() & ~crates.between(0, config.max_crate, inclusive="right")
    mark(bad_temp | bad_crate, "invalid", "operating_condition_out_of_range")

    dup = out.duplicated(subset=["cell_id", "cycle_index"], keep="first")
    mark(dup, "duplicate", "duplicate_cell_cycle")

    for cell, idx in out.groupby("cell_id").groups.items():
        sub_idx = out.index[out["cell_id"] == cell]
        valid = sub_idx[out.loc[sub_idx, "qc_status"] == "ok"]
        if len(valid) == 0:
            continue
        ordered = out.loc[valid].sort_values("cycle_index")
        q0 = reference_capacity(ordered["discharge_capacity_Ah"].to_numpy(), config.n_reference)
        out.loc[sub_idx, "reference_capacity_Ah"] = q0
        out.loc[sub_idx, "soh"] = out.loc[sub_idx, "discharge_capacity_Ah"] / q0
        too_high = out["soh"] > config.max_capacity_multiple
        mark(too_high & (out["cell_id"] == cell), "anomaly", "capacity_far_above_reference")
        ok_rows = out[(out["cell_id"] == cell) & (out["qc_status"] == "ok")].sort_values("cycle_index")
        if len(ok_rows) >= 7:
            flags = _mad_residual_flags(ok_rows["soh"].to_numpy(), config.anomaly_mad_threshold)
            flagged_idx = ok_rows.index[flags]
            mark(out.index.isin(flagged_idx), "anomaly", "robust_residual_outlier")
    return out.sort_values(["cell_id", "cycle_index"], kind="mergesort").reset_index(drop=True)


def coulombic_efficiency(df: pd.DataFrame) -> pd.Series:
    """Discharge/charge capacity where both exist (NaN otherwise)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        ce = df["discharge_capacity_Ah"] / df["charge_capacity_Ah"]
    return ce.where(df["charge_capacity_Ah"] > 0)
