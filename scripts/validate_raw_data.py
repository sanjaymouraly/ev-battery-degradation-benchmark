#!/usr/bin/env python3
"""Cross-check the derived LFP cycle table against the *raw* Zenodo archive.

The shipped table ``data/derived/lfp_cycles.csv`` is produced by
``evbatt datasets mstat-to-cycles`` from the 2.26 GB publisher archive
(DOI 10.5281/zenodo.22286450, MD5 ``fd778d5c1c8e35f9f348830faf374158``).
This script proves the derivation is faithful: it re-reads a sample of raw
MSTAT workbooks straight out of the zip, integrates the 1 Hz (t, V, I) series
with the *same* trapezoidal Coulomb-counting code path used for the table, and
compares the result against the shipped CSV.

Usage::

    python scripts/validate_raw_data.py \\
        --zip /path/to/LFP_18650_Battery_Ageing_Raw_Data.zip \\
        --derived data/derived/lfp_cycles.csv

Exit status is 0 only when every checked cycle matches within
``--tolerance`` Ah (default 1e-9 Ah, i.e. far below measurement resolution).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from evbatt.mstat import parse_workbook_bytes  # noqa: E402

EXPECTED_MD5 = "fd778d5c1c8e35f9f348830faf374158"
EXPECTED_SIZE = 2262650872

# (cell folder fragment, workbook file) samples covering early, mid and late
# life and three different rate conditions.
DEFAULT_SAMPLES = [
    ("B1_Discharge0.5C_Charge0.5C/Cycle_0050.xlsx", "B1_Dis0.5C_Chg0.5C", 50),
    ("B4_Discharge3C_Charge0.5C/Cycle_1600.xlsx", "B4_Dis3C_Chg0.5C", 1600),
    ("B6_Discharge0.5C_Charge2C/Cycle_0050.xlsx", "B6_Dis0.5C_Chg2C", 50),
]


def md5_of(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def locate(zf: zipfile.ZipFile, suffix: str) -> str:
    """Find a workbook by its trailing path fragment, whatever the root dir."""
    hits = [n for n in zf.namelist() if n.replace("\\", "/").endswith(suffix)]
    if not hits:
        raise KeyError(suffix)
    return sorted(hits)[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", type=Path, required=True, help="publisher .zip archive")
    ap.add_argument("--derived", type=Path, default=REPO_ROOT / "data/derived/lfp_cycles.csv")
    ap.add_argument("--tolerance", type=float, default=1e-9, help="max |diff| in Ah")
    ap.add_argument("--skip-md5", action="store_true", help="skip the 2.2 GB checksum pass")
    args = ap.parse_args()

    if not args.zip.is_file():
        print(f"ERROR: archive not found: {args.zip}", file=sys.stderr)
        return 2

    size = args.zip.stat().st_size
    print(f"archive : {args.zip}")
    print(f"size    : {size} bytes (expected {EXPECTED_SIZE})")
    if size != EXPECTED_SIZE:
        print("ERROR: unexpected archive size", file=sys.stderr)
        return 2
    if not args.skip_md5:
        digest = md5_of(args.zip)
        print(f"md5     : {digest} (expected {EXPECTED_MD5})")
        if digest != EXPECTED_MD5:
            print("ERROR: MD5 mismatch", file=sys.stderr)
            return 2
    else:
        print("md5     : skipped (--skip-md5)")

    derived = pd.read_csv(args.derived)
    print(f"derived : {len(derived)} rows, {derived['cell_id'].nunique()} cells\n")

    worst = 0.0
    failures = 0
    with zipfile.ZipFile(args.zip) as zf:
        for suffix, cell_id, cycle_index in DEFAULT_SAMPLES:
            member = locate(zf, suffix)
            folder = "/".join(member.replace("\\", "/").split("/")[:-1])
            records = parse_workbook_bytes(zf.read(member), folder, Path(member).name)
            match = next((r for r in records if r["cycle_index"] == cycle_index), None)
            if match is None:
                print(f"FAIL {cell_id} cycle {cycle_index}: not extracted from {member}")
                failures += 1
                continue
            row = derived[(derived["cell_id"] == cell_id)
                          & (derived["cycle_index"] == cycle_index)]
            if row.empty:
                print(f"FAIL {cell_id} cycle {cycle_index}: absent from derived table")
                failures += 1
                continue
            derived_q = float(row["discharge_capacity_Ah"].iloc[0])
            raw_q = float(match["discharge_capacity_Ah"])
            diff = abs(raw_q - derived_q)
            worst = max(worst, diff)
            status = "OK  " if diff <= args.tolerance else "FAIL"
            if diff > args.tolerance:
                failures += 1
            print(f"{status} {cell_id} cycle {cycle_index}: raw={raw_q:.9f} Ah "
                  f"derived={derived_q:.9f} Ah |diff|={diff:.3e} Ah "
                  f"(sheets={len(records)}, points={match['n_points']})")

    print(f"\nworst |difference| = {worst:.3e} Ah  (tolerance {args.tolerance:.1e} Ah)")
    if failures:
        print(f"RESULT: {failures} check(s) FAILED", file=sys.stderr)
        return 1
    print("RESULT: raw archive and derived table agree (within tolerance)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
