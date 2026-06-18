#!/usr/bin/env python3
"""Local simulation of Harbor separate-verifier mode (for hosts w/o Docker).

Usage: python3 scripts/validate_task_local.py [oracle|noop|forged|alternative|all]

Mimics the real flow: the "agent" phase produces /results artifacts in
an isolated directory; the verifier phase then sees ONLY those
artifacts plus the baked-in tests/private fixtures.  Reward is
binary, exactly as tests/test.sh writes it.  This does NOT replace
`harbor run` with Docker — see docs/handoff notes.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tasks/engineering-sciences/electrical-engineering/ev-battery-science-benchmark"
ARTIFACTS = ["analysis.json", "clean_cycles.csv", "anomalies.csv", "model_comparison.csv",
             "uncertainty.csv", "predictions.csv", "solve.py"]


def run_verifier(results: Path) -> int:
    env = dict(os.environ, EVBATT_RESULTS_DIR=str(results),
               EVBATT_PRIVATE_DIR=str(TASK / "tests" / "private"))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(TASK / "tests" / "test_outputs.py"), "-q"],
        env=env, capture_output=True, text=True, timeout=1800)
    reward = 1 if proc.returncode == 0 else 0
    print(proc.stdout[-3000:])
    if proc.returncode != 0:
        print(proc.stderr[-2000:])
    return reward


def fresh(name: str) -> Path:
    d = ROOT / "validation_runs" / name / "results"
    shutil.rmtree(d.parent, ignore_errors=True)
    d.mkdir(parents=True)
    return d


def scenario_oracle() -> int:
    results = fresh("oracle")
    subprocess.run([sys.executable, str(TASK / "solution" / "solve.py"),
                    "--input", str(TASK / "environment/data/cycling_data.csv"),
                    "--metadata", str(TASK / "environment/data/metadata.json"),
                    "--output-dir", str(results)], check=True)
    shutil.copy(TASK / "solution" / "solve.py", results / "solve.py")
    return run_verifier(results)


def scenario_noop() -> int:
    return run_verifier(fresh("noop"))  # agent did nothing


def scenario_forged() -> int:
    """Present-but-fabricated outputs + hardcoded solver must fail."""
    results = fresh("forged")
    cells = ["CELL-01", "CELL-02", "CELL-03", "CELL-04", "CELL-05"]
    (results / "analysis.json").write_text(json.dumps({"cells": {
        c: {"reference_capacity_Ah": 1.25, "selected_model": "linear", "eol_cycle": 1000}
        for c in cells}}))
    for name, header in [
        ("clean_cycles.csv", "cell_id,cycle_index,discharge_capacity_Ah,reference_capacity_Ah,soh\n"),
        ("anomalies.csv", "cell_id,cycle_index,qc_status,qc_reason\n"),
        ("model_comparison.csv", "cell_id,model,aicc,rmse,selected\n"),
        ("uncertainty.csv", "cell_id,cycle_index,soh_predicted,ci_lo,ci_hi,pi_lo,pi_hi\n"),
        ("predictions.csv", "cell_id,cycle_index,soh_predicted\n"),
    ]:
        (results / name).write_text(header)
    (results / "solve.py").write_text(
        "# hardcoded stub\nimport sys\nprint('pretend solved')\n")
    (results / "reward.txt").write_text("1")  # forged reward must be ignored
    return run_verifier(results)


def scenario_alternative() -> int:
    results = fresh("alternative")
    alt = TASK / "authoring/evidence/alternative_solver.py"
    subprocess.run([sys.executable, str(alt),
                    "--input", str(TASK / "environment/data/cycling_data.csv"),
                    "--metadata", str(TASK / "environment/data/metadata.json"),
                    "--output-dir", str(results)], check=True)
    shutil.copy(alt, results / "solve.py")
    return run_verifier(results)


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "oracle"
    scenarios = {"oracle": scenario_oracle, "noop": scenario_noop,
                 "forged": scenario_forged, "alternative": scenario_alternative}
    names = list(scenarios) if which == "all" else [which]
    rewards = {}
    for name in names:
        print(f"\n===== {name} =====")
        rewards[name] = scenarios[name]()
        out = ROOT / "validation_runs" / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "reward.txt").write_text(str(rewards[name]))
        print(f"{name}: reward={rewards[name]}")
    print("\nSummary:", rewards)


if __name__ == "__main__":
    main()
