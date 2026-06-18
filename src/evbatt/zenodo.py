"""Real-dataset support: LFP 18650 cycle-ageing data (Zenodo).

Dataset: "Experimental Dataset for Cycle Ageing of LFP 18650
Lithium-Ion Batteries under Different Charge and Discharge C-Rates"
DOI 10.5281/zenodo.22286450, license CC-BY-4.0, creators Japar,
Al-Sagheer & Steinberger-Wilckens.  Verified via the Zenodo API on
2026-10-19: single file ``LFP_18650_Battery_Ageing_Raw_Data.zip``
(2,262,650,872 bytes, MD5 fd778d5c1c8e35f9f348830faf374158).

The 2.26 GB archive is intentionally NOT committed to this repo.
``evbatt datasets zenodo-info`` prints live metadata; ``evbatt
datasets zenodo-download`` downloads with checksum verification to a
user-chosen directory.  The raw files are Solartron MSTAT Excel
exports with per-condition folders; cycle-level capacities must be
extracted per-file (see docs/datasets.md for the mapping notes and
the honest limits of what was validated without the full download).
Attribution (CC-BY-4.0) is required for any redistribution or
derived publication.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

RECORD_ID = 22286450
API_URL = f"https://zenodo.org/api/records/{RECORD_ID}"
EXPECTED_FILE = "LFP_18650_Battery_Ageing_Raw_Data.zip"
EXPECTED_MD5 = "fd778d5c1c8e35f9f348830faf374158"
EXPECTED_SIZE = 2262650872


def fetch_record(timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(API_URL, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def record_summary(record: dict) -> dict:
    m = record.get("metadata", {})
    return {
        "title": m.get("title"),
        "doi": record.get("doi"),
        "license": (m.get("license") or {}).get("id"),
        "creators": [c.get("name") for c in m.get("creators", [])],
        "files": [{"key": f["key"], "size": f["size"], "checksum": f.get("checksum"),
                   "download": f.get("links", {}).get("self")} for f in record.get("files", [])],
    }


def download_archive(dest_dir: str | Path, record: dict | None = None) -> Path:
    """Download the archive with MD5 verification (2.26 GB; opt-in only)."""
    record = record or fetch_record()
    files = [f for f in record.get("files", []) if f["key"] == EXPECTED_FILE]
    if not files:
        raise RuntimeError(f"Expected file {EXPECTED_FILE} not found in Zenodo record")
    url = files[0]["links"]["self"]
    dest = Path(dest_dir) / EXPECTED_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    h = hashlib.md5()  # noqa: S324 - checksum comparison with publisher value, not security
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as fh:  # noqa: S310
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            h.update(chunk)
    if h.hexdigest() != EXPECTED_MD5:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"MD5 mismatch: got {h.hexdigest()}, expected {EXPECTED_MD5}")
    tmp.replace(dest)
    return dest
