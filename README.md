# EV Battery Degradation Scientific Benchmark

A scientific benchmark for EV battery degradation modelling, validation, and comparison.

## Features

- Ingestion: CSV/TSV/XLSX/Parquet, alias mapping, explicit mAh→Ah conversion, schema + physical-range validation with a data-quality report (nothing silently dropped)
- QC: Three-tier flagging (invalid / duplicate / anomaly) with reason codes; robust rolling-median/MAD screen plus a bidirectional second pass (model-residual outliers flagged *and* restored)
- Models: linear, √k, power-law, exponential, knee — bounded robust fits, AICc/BIC + chronological hold-out comparison
- Uncertainty: Residual-bootstrap confidence & prediction intervals; bootstrap EOL confidence intervals; local parameter-uncertainty intervals with identifiability warnings; residual-drift diagnostics
- SOH/EOL: Q0 from measured beginning-of-life capacity; EOL by model root-finding, null + warning when unidentifiable
- Outputs: analysis.json, 5 CSVs, Markdown report, publication plots; SHA-256 provenance; atomic writes; deterministic seeds
- Benchmark: Harbor task (separate verifier, binary reward, held-out generalisation test, privilege-dropped solver execution)

## Stack

Python, NumPy, pandas, SciPy, Matplotlib, Pydantic, Typer, openpyxl, Docker

## Clone

```bash
git clone https://github.com/sanjaymouraly/ev-battery-degradation-benchmark.git
cd ev-battery-degradation-benchmark
```

## Setup

```bash
# The project ships a Docker Compose setup.
docker compose up --build
```

See `docs/` or the compose file for environment variables and ports.

## Run

```bash
docker compose up --build
```

## Tests

```bash
pytest -q
```

## Notes

- Sample data, when included, is synthetic.

## License

MIT © 2026 [Sanjay Mouraly](https://github.com/sanjaymouraly)
