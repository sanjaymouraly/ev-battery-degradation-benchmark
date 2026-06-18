"""Ingestion, unit normalization, and schema validation.

Supported inputs: CSV/TSV and Excel (.xlsx, requires openpyxl).
Column aliases are mapped to the canonical schema in ``schemas.py``.
Capacities supplied in mAh are converted to Ah; the conversion is only
applied when the *column name* explicitly says mAh, never guessed from
magnitudes (magnitude guessing silently corrupts valid small cells).
Validation never silently drops rows: problems are returned as a
``DataQualityReport`` and flagged rows are carried through QC.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .schemas import REQUIRED_COLUMNS

# Alias -> canonical. Keys are lower-cased and punctuation-stripped.
_ALIASES: dict[str, str] = {
    "cell_id": "cell_id", "cell": "cell_id", "cellid": "cell_id", "battery_id": "cell_id",
    "cycle_index": "cycle_index", "cycle": "cycle_index", "cycle_number": "cycle_index",
    "cycleindex": "cycle_index", "n_cycle": "cycle_index",
    "discharge_capacity_ah": "discharge_capacity_Ah", "capacity_ah": "discharge_capacity_Ah",
    "q_discharge_ah": "discharge_capacity_Ah", "discharge_capacity": "discharge_capacity_Ah",
    "charge_capacity_ah": "charge_capacity_Ah", "q_charge_ah": "charge_capacity_Ah",
    "temperature_c": "temperature_C", "temp_c": "temperature_C", "temperature": "temperature_C",
    "discharge_crate": "discharge_crate", "c_rate_discharge": "discharge_crate",
    "charge_crate": "charge_crate", "c_rate_charge": "charge_crate",
    "depth_of_discharge": "depth_of_discharge", "dod": "depth_of_discharge",
}
_MAH_ALIASES: dict[str, str] = {
    "discharge_capacity_mah": "discharge_capacity_Ah", "capacity_mah": "discharge_capacity_Ah",
    "charge_capacity_mah": "charge_capacity_Ah",
}


def _norm(col: str) -> str:
    return col.strip().lower().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "")


@dataclass
class DataQualityReport:
    n_rows: int = 0
    n_cells: int = 0
    missing_required: list[str] = field(default_factory=list)
    n_missing_capacity: int = 0
    n_nonpositive_capacity: int = 0
    n_duplicate_cycle_rows: int = 0
    n_nonmonotonic_cells: int = 0
    unit_conversions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_table(path: str | Path, sheet: str | None = None) -> pd.DataFrame:
    """Read a CSV/TSV/Excel file into a DataFrame (no interpretation)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Input file not found: {p}")
    suffix = p.suffix.lower()
    if suffix in {".csv", ".tsv", ".txt"}:
        sep = "\t" if suffix == ".tsv" else ","
        return pd.read_csv(p, sep=sep)
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(p, sheet_name=sheet or 0, engine="openpyxl")
    if suffix == ".parquet":
        return pd.read_parquet(p)
    raise ValueError(f"Unsupported input format {suffix!r}; use .csv, .tsv, .xlsx or .parquet")


def normalize_cycles(df: pd.DataFrame) -> tuple[pd.DataFrame, DataQualityReport]:
    """Map aliases, convert mAh->Ah where declared, coerce types, report QC."""
    report = DataQualityReport(n_rows=int(len(df)))
    rename: dict[str, str] = {}
    mah_cols: list[str] = []
    used: set[str] = set()
    for col in df.columns:
        key = _norm(str(col))
        if key in _MAH_ALIASES and _MAH_ALIASES[key] not in used:
            rename[col] = _MAH_ALIASES[key]
            mah_cols.append(_MAH_ALIASES[key])
            used.add(_MAH_ALIASES[key])
        elif key in _ALIASES and _ALIASES[key] not in used:
            rename[col] = _ALIASES[key]
            used.add(_ALIASES[key])
    out = df.rename(columns=rename).copy()
    for c in mah_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce") / 1000.0
        report.unit_conversions.append(f"{c}: mAh -> Ah (divided by 1000)")

    report.missing_required = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if report.missing_required:
        raise ValueError(
            "Missing required columns after alias mapping: "
            f"{report.missing_required}. Canonical columns are {REQUIRED_COLUMNS} "
            f"(see evbatt.schemas). Got: {list(df.columns)}"
        )
    out["cell_id"] = out["cell_id"].astype(str)
    out["cycle_index"] = pd.to_numeric(out["cycle_index"], errors="coerce")
    out["discharge_capacity_Ah"] = pd.to_numeric(out["discharge_capacity_Ah"], errors="coerce")
    for opt in ["charge_capacity_Ah", "temperature_C", "discharge_crate", "charge_crate",
                "depth_of_discharge"]:
        if opt in out.columns:
            out[opt] = pd.to_numeric(out[opt], errors="coerce")
        else:
            out[opt] = np.nan

    report.n_cells = int(out["cell_id"].nunique())
    report.n_missing_capacity = int(out["discharge_capacity_Ah"].isna().sum())
    report.n_nonpositive_capacity = int((out["discharge_capacity_Ah"] <= 0).sum())
    dup = out.duplicated(subset=["cell_id", "cycle_index"], keep=False)
    report.n_duplicate_cycle_rows = int(dup.sum())
    nonmono = 0
    for _, g in out.groupby("cell_id"):
        cyc = g["cycle_index"].dropna().to_numpy(dtype=float)
        if len(cyc) > 1 and not np.all(np.diff(cyc) >= 0):
            nonmono += 1
    report.n_nonmonotonic_cells = nonmono
    if out["cycle_index"].isna().any():
        report.warnings.append("Rows with unparseable cycle_index present; they are flagged invalid in QC.")
    if (out["cycle_index"] < 0).any():
        report.warnings.append("Negative cycle_index values present; they are flagged invalid in QC.")
    out = out.sort_values(["cell_id", "cycle_index"], kind="mergesort").reset_index(drop=True)
    return out, report


def load_cycles(path: str | Path, sheet: str | None = None) -> tuple[pd.DataFrame, DataQualityReport]:
    return normalize_cycles(read_table(path, sheet=sheet))


def load_metadata(path: str | Path | None) -> dict:
    if path is None:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))
