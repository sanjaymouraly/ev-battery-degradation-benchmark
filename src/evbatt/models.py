"""Empirical capacity-fade models for SOH(k), k = cycle count.

All models predict dimensionless SOH with SOH(0) = 1 by construction
(the reference capacity Q0 absorbs the scale).  Parameterizations are
chosen for identifiability and bounded, monotone-decreasing behaviour:

- ``linear``:       SOH = 1 - a*k
- ``sqrt``:         SOH = 1 - a*sqrt(k)     (diffusion-limited SEI growth)
- ``power``:        SOH = 1 - a*k^b         (generalised power law)
- ``exponential``:  SOH = exp(-k/tau)
- ``knee``:         two-segment linear with slopes a1 <= a2 and a knee
                    cycle; encodes a degradation "knee" without
                    claiming a specific failure mechanism.

These are *empirical* fits.  Selecting e.g. the sqrt model does not
identify SEI growth as the operative mechanism; several mechanisms can
produce indistinguishable capacity trajectories.
"""
from __future__ import annotations

import numpy as np

MODELS: dict[str, dict] = {
    "linear": {
        "param_names": ["a"],
        "bounds": ([0.0], [0.05]),
        "p0": lambda k, y: [max((1.0 - y[-1]) / max(k[-1], 1.0), 1e-5)],
    },
    "sqrt": {
        "param_names": ["a"],
        "bounds": ([0.0], [0.5]),
        "p0": lambda k, y: [max((1.0 - y[-1]) / np.sqrt(max(k[-1], 1.0)), 1e-4)],
    },
    "power": {
        "param_names": ["a", "b"],
        "bounds": ([0.0, 0.1], [1.0, 3.0]),
        "p0": lambda k, y: [max((1.0 - y[-1]) / max(k[-1], 1.0), 1e-5), 1.0],
    },
    "exponential": {
        "param_names": ["tau"],
        "bounds": ([10.0], [1e7]),
        "p0": lambda k, y: [max(-k[-1] / np.log(max(y[-1], 0.05)), 100.0)],
    },
    "knee": {
        "param_names": ["a1", "a2", "knee"],
        "bounds": ([0.0, 0.0, 5.0], [0.05, 0.1, 50000.0]),
        "p0": lambda k, y: [max((1.0 - y[-1]) / max(k[-1], 1.0), 1e-5)] * 2 + [0.6 * k[-1]],
    },
}


def _fn(name: str):
    if name == "linear":
        return lambda k, a: 1.0 - a * k
    if name == "sqrt":
        return lambda k, a: 1.0 - a * np.sqrt(np.maximum(k, 0.0))
    if name == "power":
        return lambda k, a, b: 1.0 - a * np.power(np.maximum(k, 0.0), b)
    if name == "exponential":
        return lambda k, tau: np.exp(-k / tau)
    if name == "knee":
        def f(k, a1, a2, knee):
            k = np.asarray(k, dtype=float)
            return 1.0 - a1 * np.minimum(k, knee) - a2 * np.maximum(k - knee, 0.0)
        return f
    raise ValueError(f"Unknown model {name!r}; choose from {sorted(MODELS)}")


def predict(name: str, params: dict[str, float], cycles: np.ndarray | float) -> np.ndarray:
    """Evaluate model ``name`` with a named-parameter dict at ``cycles``."""
    spec = MODELS[name]
    values = [float(params[p]) for p in spec["param_names"]]
    return np.asarray(_fn(name)(np.asarray(cycles, dtype=float), *values), dtype=float)


def fit_model(name: str, cycles: np.ndarray, soh: np.ndarray, robust: bool = True) -> dict:
    """Bounded least-squares fit; returns params, covariance, diagnostics.

    ``scipy.optimize.curve_fit(..., absolute_sigma=False)`` already scales
    the parameter covariance by the reduced residual variance.  Do not
    multiply it by the residual variance a second time: doing so makes
    standard errors smaller by a factor of ``sigma`` (a silent
    over-confidence bug).  The covariance is returned as-is and converted
    to standard errors/CI in :func:`parameter_uncertainty`.
    """
    from scipy.optimize import curve_fit

    k = np.asarray(cycles, dtype=float)
    y = np.asarray(soh, dtype=float)
    order = np.argsort(k)
    k, y = k[order], y[order]
    if len(k) < 4:
        raise ValueError("fit_model needs at least four observations")
    spec = MODELS[name]
    lo, hi = [np.asarray(b, dtype=float) for b in spec["bounds"]]
    if name == "knee":
        hi = hi.copy()
        hi[2] = max(k[-1] * 0.98, 6.0)
    p0 = np.clip(np.asarray(spec["p0"](k, y), dtype=float), lo + 1e-12, hi - 1e-12)
    loss = "soft_l1" if robust else "linear"
    popt, pcov = curve_fit(
        _fn(name), k, y, p0=p0, bounds=(lo, hi), loss=loss,
        f_scale=0.01 if robust else 1.0, maxfev=20000, absolute_sigma=False,
    )
    yhat = _fn(name)(k, *popt)
    resid = y - yhat
    n, p = len(y), len(popt)
    rss = float(np.sum(resid**2))
    return {
        "model": name,
        "params": {pn: float(v) for pn, v in zip(spec["param_names"], popt)},
        "param_covariance": np.asarray(pcov, dtype=float),
        "n": n, "n_params": p,
        "yhat": yhat, "residuals": resid, "cycles_sorted": k,
        "rss": rss,
        "rmse": float(np.sqrt(np.mean(resid**2))),
        "mae": float(np.mean(np.abs(resid))),
        "at_bound": bool(np.any(np.isclose(popt, lo)) or np.any(np.isclose(popt, hi))),
    }


def parameter_uncertainty(fit: dict, level: float = 0.95) -> dict:
    """Return standard errors and normal-approximation CIs for fitted parameters.

    The covariance comes from the local Jacobian at the optimum.  It is a
    *local* approximation and is not trustworthy for parameters sitting on a
    bound or for strongly non-quadratic robust-loss surfaces; those are
    reported with a warning by the pipeline.  This is why forecast intervals
    use a residual bootstrap rather than this covariance alone.
    """
    from scipy.stats import norm

    names = list(fit["params"])
    cov = np.asarray(fit.get("param_covariance"), dtype=float)
    out: dict[str, dict[str, float | None]] = {}
    if cov.shape != (len(names), len(names)) or not np.all(np.isfinite(cov)):
        return {n: {"se": None, "ci_lo": None, "ci_hi": None} for n in names}
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    z = float(norm.ppf(0.5 + level / 2.0))
    for i, n in enumerate(names):
        out[n] = {
            "se": float(se[i]),
            "ci_lo": float(fit["params"][n] - z * se[i]),
            "ci_hi": float(fit["params"][n] + z * se[i]),
        }
    return out


def aicc(rss: float, n: int, p: int) -> float:
    """Small-sample corrected Akaike information criterion (Gaussian)."""
    if n - p - 1 <= 0 or rss <= 0:
        return float("inf")
    aic = n * np.log(rss / n) + 2 * p
    return float(aic + (2 * p * (p + 1)) / (n - p - 1))


def bic(rss: float, n: int, p: int) -> float:
    if rss <= 0 or n <= 0:
        return float("inf")
    return float(n * np.log(rss / n) + p * np.log(n))


def compare_models(cycles: np.ndarray, soh: np.ndarray, robust: bool = True,
                   holdout_fraction: float = 0.30) -> list[dict]:
    """Fit every candidate; add AICc/BIC and chronological hold-out RMSE."""
    k = np.asarray(cycles, dtype=float)
    y = np.asarray(soh, dtype=float)
    order = np.argsort(k)
    k, y = k[order], y[order]
    n = len(k)
    n_train = max(int(round((1.0 - holdout_fraction) * n)), 5)
    results = []
    for name in MODELS:
        try:
            fit = fit_model(name, k, y, robust=robust)
        except Exception as exc:  # a failed fit is a result, not a crash
            results.append({"model": name, "status": f"failed: {exc}", "aicc": float("inf")})
            continue
        fit["aicc"] = aicc(fit["rss"], n, fit["n_params"])
        fit["bic"] = bic(fit["rss"], n, fit["n_params"])
        fit["status"] = "ok"
        try:
            train = fit_model(name, k[:n_train], y[:n_train], robust=robust)
            pred = predict(name, train["params"], k[n_train:])
            fit["holdout_rmse"] = float(np.sqrt(np.mean((y[n_train:] - pred) ** 2)))
        except Exception:
            fit["holdout_rmse"] = float("nan")
        results.append(fit)
    results.sort(key=lambda r: r.get("aicc", float("inf")))
    return results


def eol_cycle(name: str, params: dict[str, float], threshold: float = 0.80,
              max_cycles: float = 20000.0) -> float | None:
    """Cycle at which model SOH crosses ``threshold`` (bisection), or None."""
    lo, hi = 0.0, float(max_cycles)
    f_lo = float(predict(name, params, lo)) - threshold
    f_hi = float(predict(name, params, hi)) - threshold
    if f_lo < 0:
        return 0.0
    if f_hi > 0:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if float(predict(name, params, mid)) - threshold > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
