"""Scientific correctness tests (numerics, not just imports)."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evbatt.io import normalize_cycles
from evbatt.models import MODELS, compare_models, eol_cycle, fit_model, predict
from evbatt.pipeline import run_analysis
from evbatt.qc import quality_control, reference_capacity
from evbatt.schemas import AnalysisConfig
from evbatt.synthetic import generate_dataset
from evbatt.uncertainty import bootstrap_intervals


def test_models_start_at_one_and_decrease():
    k = np.array([0.0, 100.0, 500.0])
    cases = {"linear": {"a": 1e-4}, "sqrt": {"a": 0.005}, "power": {"a": 1e-4, "b": 1.2},
             "exponential": {"tau": 3000.0}, "knee": {"a1": 5e-5, "a2": 3e-4, "knee": 200.0}}
    for name, params in cases.items():
        y = predict(name, params, k)
        assert y[0] == pytest.approx(1.0)
        assert np.all(np.diff(y) <= 0), name


def test_linear_parameter_recovery_noiseless(clean_linear):
    k, y = clean_linear
    fit = fit_model("linear", k, y, robust=False)
    assert fit["params"]["a"] == pytest.approx(0.0004, rel=1e-6)
    assert fit["rmse"] < 1e-10
    assert eol_cycle("linear", fit["params"], 0.80) == pytest.approx(500.0, abs=1.0)


def test_eol_undefined_when_never_crosses():
    assert eol_cycle("linear", {"a": 1e-9}, 0.80, max_cycles=1000) is None
    assert eol_cycle("linear", {"a": 0.01}, 0.80) == pytest.approx(20.0, abs=0.1)


@given(a=st.floats(min_value=5e-5, max_value=8e-4))
@settings(max_examples=8, deadline=None)
def test_sqrt_recovery_with_noise(a):
    rng = np.random.default_rng(3)
    k = np.arange(0, 801, 10, dtype=float)
    y = 1 - (a * 30) * np.sqrt(k) / 30 + rng.normal(0, 0.002, len(k))
    fit = fit_model("sqrt", k, y)
    pred_err = np.max(np.abs(predict("sqrt", fit["params"], k) - (1 - (a * 30) * np.sqrt(k) / 30)))
    assert pred_err < 0.02


def test_mah_unit_conversion_and_wrong_unit_guard():
    df = pd.DataFrame({"cell_id": ["A"] * 3, "cycle": [0, 1, 2],
                       "discharge_capacity_mah": [1250.0, 1240.0, 1230.0]})
    out, report = normalize_cycles(df)
    assert out["discharge_capacity_Ah"].iloc[0] == pytest.approx(1.25)
    assert any("mAh" in u for u in report.unit_conversions)


def test_missing_required_column_raises():
    with pytest.raises(ValueError, match="Missing required"):
        normalize_cycles(pd.DataFrame({"cell_id": ["A"], "foo": [1]}))


def test_qc_flags_invalid_duplicate_anomaly():
    rows = [{"cell_id": "A", "cycle_index": i * 10, "discharge_capacity_Ah": 1.25 - 0.0002 * i * 10}
            for i in range(30)]
    rows.append({"cell_id": "A", "cycle_index": 100, "discharge_capacity_Ah": -1.0})       # invalid
    rows.append({"cell_id": "A", "cycle_index": 50, "discharge_capacity_Ah": 1.24})         # duplicate
    rows.append({"cell_id": "A", "cycle_index": 310, "discharge_capacity_Ah": 2.50})        # far above Q0
    df, _ = normalize_cycles(pd.DataFrame(rows))
    qc = quality_control(df, AnalysisConfig())
    counts = qc["qc_status"].value_counts().to_dict()
    assert counts.get("invalid", 0) >= 1
    assert counts.get("duplicate", 0) >= 1
    assert counts.get("anomaly", 0) >= 1
    assert len(qc) == 33  # never silently drops rows


def test_reference_capacity_median():
    assert reference_capacity(np.array([1.2, 1.3, 1.25, 0.5]), 3) == pytest.approx(1.25)


def test_pipeline_recovers_synthetic_forecasts(synthetic_data, fast_config):
    df, truth = synthetic_data
    norm, _ = normalize_cycles(df)
    result = run_analysis(norm, config=fast_config, forecast_cycles=[600, 700, 800])
    for cell, info in result.summary["cells"].items():
        assert info["status"] == "ok", cell
        true_q0 = truth.per_cell[cell]["Q0_true_Ah"]
        assert info["reference_capacity_Ah"] == pytest.approx(true_q0, rel=0.03)
        u = result.uncertainty[result.uncertainty["cell_id"] == cell]
        true_soh = predict(truth.per_cell[cell]["model"], truth.per_cell[cell]["params"],
                            u["cycle_index"].to_numpy(dtype=float))
        rmse = float(np.sqrt(np.mean((u["soh_predicted"].to_numpy() - true_soh) ** 2)))
        assert rmse < 0.03, (cell, rmse)


def test_anomaly_detection_f1_on_synthetic():
    df, truth = generate_dataset(n_cells=4, max_cycle=800, seed=7)
    norm, _ = normalize_cycles(df)
    qc = quality_control(norm, AnalysisConfig())
    flagged = {(r.cell_id, int(r.cycle_index)) for r in qc[qc.qc_status == "anomaly"].itertuples()}
    true = {tuple(x) for x in truth.anomaly_keys}
    tp, fp, fn = len(flagged & true), len(flagged - true), len(true - flagged)
    f1 = 2 * tp / (2 * tp + fp + fn)
    assert f1 >= 0.6, f"F1={f1:.2f}"


def test_bootstrap_intervals_ordered_and_cover_noiseless(clean_linear):
    k, y = clean_linear
    rng = np.random.default_rng(0)
    yn = y + rng.normal(0, 0.003, len(k))
    fit = fit_model("linear", k, yn)
    iv = bootstrap_intervals("linear", k, yn, fit, np.array([300.0, 600.0]),
                             n_bootstrap=60, seed=1)
    assert np.all(iv["pi_lo"] <= iv["prediction"]) and np.all(iv["prediction"] <= iv["pi_hi"])
    assert np.all(iv["ci_lo"] <= iv["ci_hi"])
    true = 1 - 0.0004 * np.array([300.0, 600.0])
    assert np.all((true >= iv["pi_lo"]) & (true <= iv["pi_hi"]))


def test_compare_models_returns_all_with_aicc(clean_linear):
    k, y = clean_linear
    comps = compare_models(k, y)
    assert {c["model"] for c in comps} == set(MODELS)
    ok = [c for c in comps if c.get("status") == "ok"]
    assert len(ok) >= 4
    assert ok[0]["aicc"] == min(c["aicc"] for c in ok)


def test_insufficient_data_handled_not_crash(fast_config):
    df, _ = normalize_cycles(pd.DataFrame(
        {"cell_id": ["A"] * 5, "cycle_index": [0, 1, 2, 3, 4],
         "discharge_capacity_Ah": [1.25, 1.24, 1.23, 1.22, 1.21]}))
    result = run_analysis(df, config=fast_config)
    assert result.summary["cells"]["A"]["status"] == "insufficient_data"


def test_determinism(synthetic_data, fast_config):
    df, _ = synthetic_data
    norm, _ = normalize_cycles(df)
    r1 = run_analysis(norm, config=fast_config)
    r2 = run_analysis(norm, config=fast_config)
    pd.testing.assert_frame_equal(r1.predictions, r2.predictions)
