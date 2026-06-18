# Real-data results — LFP 18650 cycle ageing (Zenodo 10.5281/zenodo.22286450)

**Source:** Japar, Al-Sagheer & Steinberger-Wilckens, CC-BY-4.0.
Downloaded 2026-10-19; size and MD5 verified against the publisher checksum
(2,262,650,872 bytes, MD5 `fd778d5c1c8e35f9f348830faf374158`).
Cycle table extracted with `evbatt datasets mstat-to-cycles` (trapezoidal
Coulomb counting of the 1 Hz MSTAT (t, V, I) series; 121 workbooks →
**9,697 cycles, 6 cells**, `data/derived/lfp_cycles.csv`), then analysed with
the standard pipeline (`results/lfp_real/`, figures
`docs/images/lfp_real_soh.png`, `lfp_real_model_comparison.png`,
`lfp_real_residuals.png`).

## Provenance of the derived table

`scripts/validate_raw_data.py` re-reads raw workbooks **directly out of the
publisher zip** and re-runs the same integration code, then compares against
the shipped CSV:

```
OK   B1_Dis0.5C_Chg0.5C cycle 50:   raw=1.202306643 Ah derived=1.202306643 Ah |diff|=2.220e-16 Ah (sheets=50, points=14216)
OK   B4_Dis3C_Chg0.5C cycle 1600:  raw=0.926177518 Ah derived=0.926177518 Ah |diff|=0.000e+00 Ah (sheets=100, points=7431)
OK   B6_Dis0.5C_Chg2C cycle 50:   raw=1.218655333 Ah derived=1.218655333 Ah |diff|=2.220e-16 Ah (sheets=51, points=9432)

worst |difference| = 2.220e-16 Ah  (tolerance 1.0e-09 Ah)
```

## Results

| Cell (discharge/charge) | Q0 (Ah) | Final SOH | Model | RMSE | Hold-out RMSE | EOL (SOH 0.80) | 95% CI | Flagged |
|---|---:|---|---|---:|---:|---:|---|---:|
| B1 0.5C/0.5C | 1.220 | 0.897 @1500 | power | 0.0016 | 0.0019 | 4520 (extrapolated) | 4484–4554 | 159 |
| B2 1C/0.5C | 1.208 | 0.886 @1600 | knee | 0.0044 | 0.0222 | 3501 (extrapolated) | 3465–3539 | 30 |
| B3 2C/0.5C | 1.162 | 0.849 @2000 | knee | 0.0059 | 0.0110 | 2704 (extrapolated) | 2688–2722 | 155 |
| B4 3C/0.5C | 1.186 | 0.781 @1600 | power | 0.0073 | 0.0148 | **1333 (in-window)** | 1328–1339 | 6 |
| B5 0.5C/1C | 1.195 | 0.894 @1500 | knee | 0.0031 | 0.0039 | 3138 (extrapolated) | 3124–3153 | 11 |
| B6 0.5C/2C | 1.245 | 0.820 @1700 | power | 0.0028 | 0.0038 | 2261 (extrapolated) | 2253–2270 | 126 |

**Quality control over the 9,697 real rows:** 9,210 `ok`, 473 `anomaly`
(262 `robust_residual_outlier`, 211 `model_residual_outlier`), 14 `invalid`
(`capacity_nonpositive`). Every excluded row appears in
`results/lfp_real/anomalies.csv` with its reason code.

EOL confidence intervals come from the residual bootstrap (200 resamples,
seed 12345, 95% level). They are **conditional on the selected model family**
and on approximate residual independence; they do not include model-family
uncertainty, so they must not be read as a total uncertainty budget. The
"extrapolated" label is applied whenever the EOL lies beyond the observed
cycle range (all cells except B4).

## Findings (with the necessary caveats)

- Fade accelerates with discharge C-rate (B1→B4) and with 2C charging
  (B6 vs B1/B5). Only B4 (3C discharge) crosses SOH 0.80 inside the
  observed window, so only its EOL is an interpolation; all other EOLs
  are model extrapolations and are flagged as such in `analysis.json`.
- **Rate confounding:** capacities are measured at the cycling discharge
  rate (no low-rate reference cycles in this protocol), so part of the
  cross-condition Q0/SOH offset is kinetic (rate capability), not ageing.
  Within-cell degradation *trends* remain valid; cross-condition lifetime
  rankings should be read with this caveat.
- **Data-quality observations (real artefacts, all flagged with reasons):**
  15 near-zero-discharge (aborted) cycles; scattered partial cycles;
  occasional voltage excursions above the 3.65 V CV limit in raw sheets
  (max 4.35 V in B2 — transient/instrument artefact); B5's median
  Coulombic efficiency is a systematic 1.028 (> 1 is nonphysical for a
  full cycle; likely a current-range calibration offset in the source —
  discharge-capacity SOH is unaffected to first order); B6's first
  workbook contains 51 cycle sheets (numbered 0–50 here); B1 has a
  20-cycle archival gap before cycle 171 (end-anchored numbering
  verified by capacity continuity and File-List timestamps).
- Late-life scatter grows (e.g. B3 beyond cycle 1200): many flagged
  points there are high-variance genuine measurements, not gross
  corruption — the pipeline's robust loss limits their influence either way.
- Residual drift after the selected fit is reported per cell
  (`residual_drift_per_1000_cycles` in `analysis.json`); values above
  0.02 SOH/1000 cycles raise an explicit warning about unmodelled drift.

## Reproduce

```bash
evbatt datasets zenodo-download --yes            # 2.26 GB, MD5-verified
evbatt datasets mstat-to-cycles <extracted-dir> -o data/derived/lfp_cycles.csv
python scripts/validate_raw_data.py --zip <archive>          # raw vs derived
evbatt analyze data/derived/lfp_cycles.csv \
    --metadata data/derived/lfp_metadata.json -o results/lfp_real
```
