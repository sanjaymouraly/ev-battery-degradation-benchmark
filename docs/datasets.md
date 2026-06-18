# Datasets & provenance

## Real experimental mode — LFP 18650 cycle ageing (Zenodo)

- **Title:** Experimental Dataset for Cycle Ageing of LFP 18650 Lithium-Ion
  Batteries under Different Charge and Discharge C-Rates
- **DOI:** [10.5281/zenodo.22286450](https://doi.org/10.5281/zenodo.22286450)
- **Creators:** Japar, Al-Sagheer & Steinberger-Wilckens
- **License:** CC-BY-4.0 (attribution required for reuse/redistribution)
- **Verified 2026-10-19** via the Zenodo API (`evbatt datasets zenodo-info`):
  one file `LFP_18650_Battery_Ageing_Raw_Data.zip`, 2,262,650,872 bytes,
  MD5 `fd778d5c1c8e35f9f348830faf374158`. LFP 18650 cells, 1.25 Ah nominal,
  25 °C, 2.50–3.65 V; discharge 0.5C/1C/2C/3C at 0.5C charge, plus 1C/2C
  charge-rate arms; Solartron 1470E/MSTAT Excel exports recorded every
  50 then 100 cycles.

The 2.26 GB archive is **not** in this repository. Download (opt-in,
MD5-verified): `evbatt datasets zenodo-download --dest data/zenodo --yes`
(a parallel downloader such as `aria2c -x16` is much faster than a single
stream: ~2 min vs ~1 h observed). Then extract cycle-level capacities
directly from the zip: `evbatt datasets mstat-to-cycles <zip> -o cycles.csv
--jobs 2` (Solartron MSTAT layout: per-cycle sheets behind an `End Header`
preamble, (t, V, I) at 1 Hz; trapezoidal Coulomb counting; see
`src/evbatt/mstat.py`). **End-to-end validated 2026-10-19:** MD5-verified
download, 121 workbooks → 9,697 cycles (`data/derived/lfp_cycles.csv`,
CC-BY-4.0 with `ATTRIBUTION.md`), full pipeline analysis in
`docs/real-data-results.md`. The derivation is independently re-checked
against the raw archive by `scripts/validate_raw_data.py`, which re-integrates
sample workbooks straight out of the zip and reproduces the shipped
capacities to 2.2e-16 Ah. Notable source quirks found and handled:
51-sheet first workbook for B6 (cycle 0), a 20-cycle archival gap in B1
(end-anchored numbering verified via capacity continuity + timestamps),
15 aborted near-zero cycles, and B5's systematic CE ≈ 1.028.

## Synthetic scientific mode

`evbatt datasets synthetic` / `evbatt.synthetic.generate_dataset` creates
physically plausible multi-cell experiments with **known** parameters:
per-cell model family, Q0 scatter, irregular sampling, heteroscedastic noise,
sensor drift, missing rows, duplicates, injected outliers. Every corruption
is recorded in the truth file. Synthetic data are always labelled synthetic
and are used for validation/benchmark calibration — never presented as
experiments. The bundled `data/example_synthetic.csv` (seed 7) and its truth
`data/example_truth.json` are small, MIT-licensed (generated here), and safe
to redistribute. Benchmark ground truth is *separate* (different seeds) and
lives only in the verifier image fixtures.

## Input contract (any source)

CSV/TSV/XLSX/Parquet, one row per measured cycle. Required:
`cell_id`, `cycle_index`, `discharge_capacity_Ah` (aliases and explicit
`*_mAh` accepted). Optional: `charge_capacity_Ah`, `temperature_C` (°C),
`discharge_crate`, `charge_crate` (C), `depth_of_discharge` (−).
