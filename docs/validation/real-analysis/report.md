# EV Battery Degradation Analysis

## Method
- Reference capacity: median of first 3 valid discharge capacities per cell.
- SOH definition: discharge_capacity_Ah / reference_capacity_Ah.
- EOL definition: first cycle where selected model SOH crosses 0.8.
- Candidates: linear, sqrt, power, exponential, knee (bounded nonlinear least squares; selection by AICc with chronological hold-out RMSE reported).
- Intervals: residual-bootstrap confidence/prediction intervals.
- Flagged observations are listed in `anomalies.csv` with reason codes; nothing is silently discarded.

## Results by cell

| Cell | Status | Model | Q0 (Ah) | RMSE | Hold-out RMSE | EOL (95% CI) | Flagged n |
|---|---|---|---:|---:|---:|---:|---:|
| B1_Dis0.5C_Chg0.5C | ok | power | 1.2202 | 0.0016 | 0.0019 | 4520 (4490–4556) | 159 |
| B2_Dis1C_Chg0.5C | ok | knee | 1.2080 | 0.0044 | 0.0222 | 3501 (3465–3539) | 30 |
| B3_Dis2C_Chg0.5C | ok | knee | 1.1617 | 0.0059 | 0.0110 | 2704 (2688–2723) | 155 |
| B4_Dis3C_Chg0.5C | ok | power | 1.1859 | 0.0073 | 0.0148 | 1333 (1327–1339) | 6 |
| B5_Dis0.5C_Chg1C | ok | knee | 1.1951 | 0.0031 | 0.0039 | 3138 (3123–3155) | 11 |
| B6_Dis0.5C_Chg2C | ok | power | 1.2454 | 0.0028 | 0.0038 | 2261 (2253–2270) | 126 |

## Parameter uncertainty

Local normal-approximation intervals from the fit covariance. They condition on the selected model family and are not valid at a bound.

| Cell | Parameter | Estimate | SE | 95% CI |
|---|---|---:|---:|---|
| B1_Dis0.5C_Chg0.5C | a | 0.00104466 | 1.19e-05 | [0.00102139, 0.00106793] |
| B1_Dis0.5C_Chg0.5C | b | 0.624343 | 0.00164 | [0.62112, 0.627566] |
| B2_Dis1C_Chg0.5C | a1 | 0.000146988 | 1.11e-06 | [0.000144804, 0.000149172] |
| B2_Dis1C_Chg0.5C | a2 | 4.68822e-05 | 3.61e-07 | [4.61743e-05, 4.75901e-05] |
| B2_Dis1C_Chg0.5C | knee | 358.373 | 4.73 | [349.098, 367.648] |
| B3_Dis2C_Chg0.5C | a1 | 9.78141e-05 | 1.06e-06 | [9.57386e-05, 9.98896e-05] |
| B3_Dis2C_Chg0.5C | a2 | 6.95503e-05 | 3.42e-07 | [6.88804e-05, 7.02203e-05] |
| B3_Dis2C_Chg0.5C | knee | 421.197 | 18.5 | [384.881, 457.513] |
| B4_Dis3C_Chg0.5C | a | 0.00132903 | 3.16e-05 | [0.00126711, 0.00139095] |
| B4_Dis3C_Chg0.5C | b | 0.696836 | 0.00342 | [0.690127, 0.703546] |
| B5_Dis0.5C_Chg1C | a1 | 0.000336361 | 1.04e-05 | [0.000315992, 0.00035673] |
| B5_Dis0.5C_Chg1C | a2 | 5.78756e-05 | 2.06e-07 | [5.7471e-05, 5.82802e-05] |
| B5_Dis0.5C_Chg1C | knee | 66.0006 | 2.54 | [61.0247, 70.9766] |
| B6_Dis0.5C_Chg2C | a | 0.00312416 | 2.89e-05 | [0.0030675, 0.00318081] |
| B6_Dis0.5C_Chg2C | b | 0.538504 | 0.00133 | [0.535904, 0.541104] |

## Warnings

- **B1_Dis0.5C_Chg0.5C**: EOL (4520) lies beyond observed range (max 1500 cycles); extrapolated value.
- **B2_Dis1C_Chg0.5C**: EOL (3501) lies beyond observed range (max 1600 cycles); extrapolated value.
- **B3_Dis2C_Chg0.5C**: EOL (2704) lies beyond observed range (max 2000 cycles); extrapolated value.
- **B5_Dis0.5C_Chg1C**: EOL (3138) lies beyond observed range (max 1500 cycles); extrapolated value.
- **B6_Dis0.5C_Chg2C**: EOL (2261) lies beyond observed range (max 1699 cycles); extrapolated value.

## Limitations

- Empirical SOH(k) fits do not identify electrochemical degradation mechanisms.
- Residual bootstrap assumes approximately independent residuals; serial correlation within a cell makes intervals optimistic.
- Extrapolation beyond the observed cycle range is model-dependent; treat forecasts past the data range as provisional.
- Cell-level laboratory results do not directly predict EV pack-level life (imbalance, thermal gradients, BMS limits are not modelled).

## Reproducibility

- Input SHA-256: `fe128baeda0b9c55f136097743fcfafc0f120fbed4453a1796c0fd80b39d92dc`
- Config: `{'eol_soh': 0.8, 'n_reference': 3, 'robust_loss': True, 'anomaly_mad_threshold': 4.0, 'min_cycles_per_cell': 8, 'holdout_fraction': 0.3, 'n_bootstrap': 200, 'bootstrap_seed': 12345, 'confidence_level': 0.95, 'eol_max_cycles': 20000.0, 'max_capacity_Ah': 500.0, 'temperature_range_C': (-40.0, 80.0), 'max_crate': 20.0, 'max_capacity_multiple': 1.25}`
