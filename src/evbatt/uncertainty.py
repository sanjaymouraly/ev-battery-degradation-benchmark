"""Uncertainty quantification: residual bootstrap prediction intervals.

Method: semi-parametric residual bootstrap.  The fitted curve is held
fixed, residuals are resampled with replacement (centred), added back,
and the model refitted.  The spread of refitted predictions gives a
confidence band; adding a resampled residual to each bootstrap
prediction gives a prediction band that also reflects measurement
noise.  This assumes exchangeable, roughly independent residuals —
serial correlation within a cell makes intervals optimistic, which is
stated in every report.  Interval coverage is validated empirically
on synthetic data in the test suite rather than assumed.
"""
from __future__ import annotations

import numpy as np

from .models import eol_cycle, fit_model, predict


def _empty(point: np.ndarray, eval_cycles: np.ndarray) -> dict:
    nan = np.full_like(point, np.nan, dtype=float)
    return {"cycles": eval_cycles, "prediction": point, "ci_lo": nan, "ci_hi": nan.copy(),
            "pi_lo": nan.copy(), "pi_hi": nan.copy(), "n_successful": 0,
            "eol_samples": np.array([], dtype=float),
            "eol_ci_lo": None, "eol_ci_hi": None}


def bootstrap_intervals(
    model: str,
    cycles: np.ndarray,
    soh: np.ndarray,
    fit: dict,
    eval_cycles: np.ndarray,
    n_bootstrap: int = 200,
    seed: int = 12345,
    level: float = 0.95,
    eol_threshold: float | None = None,
    eol_max_cycles: float = 20000.0,
) -> dict:
    """Return point predictions with confidence and prediction intervals.

    A residual bootstrap is used because the data are a single trajectory per
    cell and the forecast is a nonlinear functional of the fitted parameters.
    When ``eol_threshold`` is supplied, the same bootstrap also yields a
    percentile interval for the EOL crossing, which propagates parameter and
    residual uncertainty into that derived quantity.  The interval is
    conditional on the selected model family and is *not* a model-selection
    interval; extrapolated EOLs remain provisional.
    """
    k = np.asarray(cycles, dtype=float)
    y = np.asarray(soh, dtype=float)
    order = np.argsort(k)
    k, y = k[order], y[order]
    yhat = predict(model, fit["params"], k)
    resid = y - yhat
    resid_c = resid - np.mean(resid)
    eval_cycles = np.asarray(eval_cycles, dtype=float)
    point = np.maximum(predict(model, fit["params"], eval_cycles), 0.0)
    if n_bootstrap <= 0 or len(resid) < 5:
        return _empty(point, eval_cycles)
    rng = np.random.default_rng(seed)
    boot_mean, boot_pred, eol_samples = [], [], []
    for _ in range(n_bootstrap):
        y_star = yhat + rng.choice(resid_c, size=len(y), replace=True)
        try:
            refit = fit_model(model, k, y_star, robust=False)
        except Exception:
            try:
                refit = fit_model(model, k, y_star, robust=True)
            except Exception:
                continue
        pred = np.maximum(predict(model, refit["params"], eval_cycles), 0.0)
        boot_mean.append(pred)
        boot_pred.append(pred + rng.choice(resid_c, size=len(eval_cycles), replace=True))
        if eol_threshold is not None:
            e = eol_cycle(model, refit["params"], eol_threshold, eol_max_cycles)
            if e is not None:
                eol_samples.append(float(e))
    if not boot_mean:
        return _empty(point, eval_cycles)
    alpha = (1.0 - level) / 2.0
    qs = [100 * alpha, 100 * (1 - alpha)]
    ci = np.percentile(np.asarray(boot_mean), qs, axis=0)
    pi = np.percentile(np.asarray(boot_pred), qs, axis=0)
    # Numerically enforce the documented contract: intervals contain the
    # point prediction and are ordered.  This matters for skewed hats and
    # for a forecast at the edge of the observed window.
    ci[0] = np.minimum(ci[0], point)
    ci[1] = np.maximum(ci[1], point)
    pi[0] = np.minimum(pi[0], point)
    pi[1] = np.maximum(pi[1], point)
    eol_arr = np.asarray(eol_samples, dtype=float)
    eol_ci_lo = float(np.percentile(eol_arr, 100 * alpha)) if len(eol_arr) >= 10 else None
    eol_ci_hi = float(np.percentile(eol_arr, 100 * (1 - alpha))) if len(eol_arr) >= 10 else None
    return {"cycles": eval_cycles, "prediction": point,
            "ci_lo": ci[0], "ci_hi": ci[1], "pi_lo": pi[0], "pi_hi": pi[1],
            "n_successful": len(boot_mean),
            "eol_samples": eol_arr,
            "eol_ci_lo": eol_ci_lo, "eol_ci_hi": eol_ci_hi}
