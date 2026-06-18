"""Synthetic battery-ageing experiments with known ground truth.

The generator produces *physically plausible* (not electrochemically
mechanistic) capacity-fade trajectories used for validation and
benchmark calibration.  True SOH follows one of the empirical model
families in ``models.py`` with per-cell parameter draws, plus:

- heteroscedastic measurement noise (sd grows with cycle count),
- slow multiplicative sensor drift,
- missing observations, duplicated rows, injected gross outliers.

Every injected corruption is recorded in the returned truth object so
tests and the benchmark verifier can grade recovery objectively.
Synthetic data must never be presented as a real experiment; the
manifest records ``"synthetic": true``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .models import predict


@dataclass
class SyntheticTruth:
    """Ground truth for one synthetic dataset (never ship to agents)."""

    seed: int
    per_cell: dict[str, dict] = field(default_factory=dict)
    # (cell_id, cycle_index) pairs that were corrupted/injected.
    anomaly_keys: list[list] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"seed": self.seed, "per_cell": self.per_cell, "anomaly_keys": self.anomaly_keys}


def _true_params(rng: np.random.Generator, model: str, max_cycle: int) -> dict:
    """Draw identifiable parameters so SOH falls to ~0.75-0.90 by max_cycle."""
    target_loss = float(rng.uniform(0.10, 0.25))
    if model == "linear":
        return {"a": target_loss / max_cycle}
    if model == "sqrt":
        return {"a": target_loss / np.sqrt(max_cycle)}
    if model == "power":
        b = float(rng.uniform(0.6, 1.4))
        return {"a": target_loss / max_cycle**b, "b": b}
    if model == "exponential":
        tau = float(-max_cycle / np.log(1.0 - target_loss))
        return {"tau": tau}
    if model == "knee":
        knee = float(rng.uniform(0.45, 0.65) * max_cycle)
        a1 = 0.35 * target_loss / knee
        a2 = (target_loss - a1 * knee) / max(max_cycle - knee, 1.0)
        return {"a1": a1, "a2": max(a2, a1 * 1.5), "knee": knee}
    raise ValueError(f"Unknown model {model!r}")


def generate_dataset(
    n_cells: int = 4,
    max_cycle: int = 800,
    seed: int = 42,
    models: tuple[str, ...] = ("linear", "sqrt", "power", "knee"),
    noise_sd: float = 0.004,
    outlier_fraction: float = 0.03,
    missing_fraction: float = 0.05,
    duplicate_fraction: float = 0.01,
    drift_fraction: float = 0.01,
    nominal_capacity_Ah: float = 1.25,
    irregular: bool = True,
) -> tuple[pd.DataFrame, SyntheticTruth]:
    """Generate a corrupted multi-cell dataset plus its ground truth."""
    rng = np.random.default_rng(seed)
    truth = SyntheticTruth(seed=seed)
    frames: list[pd.DataFrame] = []
    for i in range(n_cells):
        cell = f"CELL-{i + 1:02d}"
        model = models[i % len(models)]
        q0 = float(nominal_capacity_Ah * rng.uniform(0.96, 1.03))
        params = _true_params(rng, model, max_cycle)
        if irregular:
            steps = rng.integers(5, 25, size=int(max_cycle / 12) + 2)
            cycles = np.unique(np.clip(np.cumsum(steps), 1, max_cycle))
            cycles = np.concatenate([[0], cycles]).astype(int)
        else:
            cycles = np.arange(0, max_cycle + 1, 10)
        soh_true = predict(model, params, cycles.astype(float))
        sd = noise_sd * (1.0 + 0.8 * cycles / max_cycle)
        drift = 1.0 + drift_fraction * (cycles / max_cycle) * rng.choice([-1.0, 1.0])
        q = q0 * soh_true * drift + rng.normal(0.0, sd) * q0
        keep = rng.random(len(cycles)) > missing_fraction
        keep[0] = True
        cycles, q, soh_true = cycles[keep], q[keep], soh_true[keep]

        n = len(cycles)
        # Respect a user-supplied zero rate: the old ``max(1, ...)`` silently
        # injected one outlier even when outlier_fraction=0.
        n_out = int(round(outlier_fraction * n))
        if n_out > 0 and n > 3:
            out_idx = rng.choice(np.arange(3, n), size=min(n_out, n - 3), replace=False)
            q_obs = q.copy()
            for j in out_idx:
                q_obs[j] = q[j] * float(rng.uniform(0.82, 1.22)) + float(rng.normal(0, 0.01))
                truth.anomaly_keys.append([cell, int(cycles[j])])
        else:
            q_obs = q.copy()

        cell_df = pd.DataFrame({
            "cell_id": cell,
            "cycle_index": cycles.astype(int),
            "discharge_capacity_Ah": np.round(q_obs, 5),
            "charge_capacity_Ah": np.round(q_obs * rng.uniform(0.99, 1.01, size=n), 5),
            "temperature_C": float(rng.choice([25.0, 30.0, 35.0])),
            "discharge_crate": float(rng.choice([0.5, 1.0, 2.0])),
            "charge_crate": 0.5,
            "depth_of_discharge": 1.0,
        })
        n_dup = int(round(duplicate_fraction * n))
        if n_dup > 0:
            dup_rows = cell_df.iloc[rng.integers(0, n, size=n_dup)]
            cell_df = pd.concat([cell_df, dup_rows], ignore_index=True)
        # Shuffle rows to mimic unsorted instrument exports.
        cell_df = cell_df.sample(frac=1.0, random_state=int(rng.integers(1 << 30)))
        frames.append(cell_df)
        truth.per_cell[cell] = {
            "model": model, "params": params, "Q0_true_Ah": q0,
            "max_cycle": int(max_cycle),
        }
    data = pd.concat(frames, ignore_index=True)
    return data, truth
