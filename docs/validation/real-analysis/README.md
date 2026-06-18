# Real-data analysis outputs (committed evidence)

These are the outputs of

```bash
evbatt analyze data/derived/lfp_cycles.csv \
    --metadata data/derived/lfp_metadata.json -o results/lfp_real
```

run against the **real** LFP 18650 ageing dataset
(DOI `10.5281/zenodo.22286450`, 9,697 cycles, 6 cells).

| File | Contents |
|---|---|
| `analysis.json` | full summary: per-cell fit, parameter uncertainty, EOL + 95% CI, warnings, data-quality block, input SHA-256 |
| `report.md` | human-readable report (per-cell table, EOL CI, parameter-uncertainty table, warnings, limitations) |
| `model_comparison.csv` | every candidate model per cell with RMSE/MAE/AICc/BIC/hold-out RMSE and the selection flag |
| `uncertainty.csv` | bootstrap confidence & prediction bands on the evaluation grid |
| `predictions.csv` | fitted/forecast SOH and capacity with an `is_extrapolation` flag |
| `anomalies.csv` | every flagged row with its reason code (473 `anomaly` + 14 `invalid`) |

`clean_cycles.csv` (~1.2 MB) is **not** committed: it is a direct function of
the committed source table `data/derived/lfp_cycles.csv` and can be regenerated
with the command above. The figures live in `docs/images/`
(`lfp_real_soh.png`, `lfp_real_model_comparison.png`, `lfp_real_residuals.png`).
