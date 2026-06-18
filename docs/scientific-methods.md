# Scientific methods

## Quantities

For cell *i* at cycle *k*, with discharge capacity `Q_i(k)` in Ah:

- **Reference capacity** `Q0_i` = median of the first 3 valid `Q_i` in cycle
  order. Measured beginning-of-life capacity is used instead of nameplate
  rating, which routinely differs by several percent.
- **SOH** `= Q_i(k) / Q0_i` (dimensionless). **Capacity fade** `= 1 − SOH`.
- **Coulombic efficiency** `= Q_discharge / Q_charge` where both exist.
- **EOL cycle** = first *k* where the selected model's SOH crosses the
  threshold (default 0.80), found by bisection on the model — never by
  interpolating noisy points. Undefined (null) if the model does not cross
  within 20,000 cycles; extrapolations beyond the observed range are flagged.

## Candidate models (all satisfy SOH(0)=1, monotone decreasing)

| Model | SOH(k) | Common motivation (not identification) |
|---|---|---|
| linear | 1 − a·k | constant-rate loss (baseline) |
| sqrt | 1 − a·√k | diffusion-limited film growth |
| power | 1 − a·kᵇ | generalised empirical law |
| exponential | exp(−k/τ) | first-order-like decay |
| knee | two-segment linear (a₁, a₂, knee cycle) | late-life acceleration |

Fits use bounded nonlinear least squares (SciPy `curve_fit`, soft-L1 robust
loss by default). Selection is by small-sample AICc,
`AICc = n·ln(RSS/n) + 2p + 2p(p+1)/(n−p−1)`, with BIC and chronological
hold-out RMSE (last 30%) also reported. These families can mimic each other
over finite windows; **selecting a model does not identify an electrochemical
mechanism**, and the benchmark therefore grades forecasts/EOL, not model
identity.

## Quality control (flag, never silently delete)

1. `invalid` — missing/non-positive capacity, negative cycle, capacities
   above a physical ceiling, out-of-range temperature/C-rate.
2. `duplicate` — repeated (cell, cycle); first occurrence kept.
3. `anomaly` — capacity > 1.25·Q0, or |residual| > 4·(1.4826·MAD) after
   rolling-median (window 7) detrending. This screen is distribution-free
   and insensitive to the outliers it detects. A bidirectional second
   pass then (a) flags clean points with extreme residuals against the
   robustly selected model, and (b) *rescues* trend-screen flags the
   model finds consistent — the local screen over-flags genuine points
   near degradation knees (multi-seed study: median anomaly F1 0.48 →
   0.70 with the rescue pass; see `docs/validation-study.md`).

## Uncertainty

Residual bootstrap: residuals of the selected fit are centred, resampled,
added to the fitted curve, and the model refitted (default 200×). Percentiles
of refitted curves give the confidence band; adding a resampled residual
gives the prediction band. Assumes roughly independent residuals — within-cell
serial correlation makes intervals optimistic. Empirical coverage against
known synthetic truth is tested in `tests/test_science.py` and in the
benchmark evidence (oracle PI coverage 0.87 at nominal 95% on extrapolated
points — treat 95% as nominal, not guaranteed).

Two further uncertainty products are reported per cell:

- **EOL confidence interval** — the bootstrap refits also re-solve the EOL
  root, so the percentile spread of the refitted EOL roots gives a 95%
  interval for EOL (`eol_ci` in `analysis.json`, shown in the report table).
  It is **conditional on the selected model family** and on residual
  independence: it does not include the uncertainty of choosing that family,
  so it is a lower bound on the total uncertainty, and it is not reported when
  the root is unreachable in the resampled fits.
- **Parameter uncertainty** — local normal-approximation intervals from the
  fit covariance (`se`, `ci_lo`, `ci_hi` per parameter). These are only
  meaningful away from a parameter bound; a fit at a bound, or a parameter
  whose standard error exceeds its estimate, is flagged as weakly identified
  instead of being reported as if it were precise.

A **residual-drift diagnostic** (`residual_drift_per_1000_cycles`, the slope
of the residuals against cycle index) warns when the selected model leaves a
systematic trend larger than 0.02 SOH per 1000 cycles, i.e. when the
functional form is inadequate for the data rather than merely imperfect.

## Limitations

Cell-level, full-cycle laboratory models. No pack effects (imbalance,
thermal gradients, BMS derating), no partial-cycle/rainflow accounting,
no impedance-based SOH. Operating conditions are reported per cell and used
for QC ranges; condition-dependent (e.g. Arrhenius/C-rate) rate models are
only identifiable with designed multi-condition data and are intentionally
not fitted from confounded single-condition-per-cell inputs.
