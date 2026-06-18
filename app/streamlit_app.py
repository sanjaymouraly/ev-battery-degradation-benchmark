"""evbatt explorer — visual interface over the real analysis pipeline.

Run:  streamlit run app/streamlit_app.py

Everything shown is computed by ``evbatt.pipeline`` on the selected data;
the app adds no analytics of its own.  Real measured data, a labelled
synthetic example, and user uploads all go through the same QC/fit/
uncertainty path.  The benchmark and CLI work fully without this UI.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from evbatt.io import load_cycles  # noqa: E402
from evbatt.pipeline import run_analysis  # noqa: E402
from evbatt.schemas import AnalysisConfig  # noqa: E402

REAL = ROOT / "data" / "derived" / "lfp_cycles.csv"
EXAMPLE = ROOT / "data" / "example_synthetic.csv"

st.set_page_config(page_title="evbatt — Battery Degradation Explorer", layout="wide")
st.title("🔋 evbatt — Battery Degradation Explorer")
st.caption("Uncertainty-aware SOH/EOL analysis. Empirical fits do not identify "
           "degradation mechanisms; extrapolated regions are shaded and warned.")


@st.cache_data(show_spinner=False, max_entries=4)
def _load_real():
    return load_cycles(REAL)


@st.cache_data(show_spinner=False, max_entries=4)
def _load_example():
    return load_cycles(EXAMPLE)


@st.cache_data(show_spinner=False, max_entries=8)
def _analyse(df: pd.DataFrame, eol_soh: float, n_boot: int):
    config = AnalysisConfig(eol_soh=float(eol_soh), n_bootstrap=int(n_boot))
    return run_analysis(df, config=config)


options = []
if REAL.is_file():
    options.append("Real LFP dataset (Zenodo, CC-BY-4.0)")
options += ["Bundled synthetic example", "Upload CSV/XLSX"]
src = st.sidebar.radio("Data source", options)
df = None
report = None

if src.startswith("Real LFP"):
    try:
        df, report = _load_real()
        st.sidebar.success("Measured LFP 18650 cycling data — 6 cells, 9,697 cycles.")
        st.sidebar.caption("Japar, Al-Sagheer & Steinberger-Wilckens · "
                           "DOI 10.5281/zenodo.22286450 · CC-BY-4.0")
    except Exception as exc:  # noqa: BLE001 - surface, never crash the UI
        st.sidebar.error(f"Could not load the bundled real-data table: {exc}")
        st.stop()
elif src == "Bundled synthetic example":
    try:
        df, report = _load_example()
        st.sidebar.warning("SYNTHETIC example data — not a real experiment.")
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"Could not load the bundled example: {exc}")
        st.stop()
else:
    up = st.sidebar.file_uploader("Cycle-level file", type=["csv", "tsv", "xlsx", "xlsm"])
    if up is None:
        st.info("Upload a cycle-level file (cell_id, cycle_index, discharge_capacity_Ah, …) "
                "or choose a bundled dataset.")
        st.stop()
    suffix = Path(up.name).suffix.lower()
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
            fh.write(up.getbuffer())
            tmp_path = fh.name
        df, report = load_cycles(tmp_path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read {up.name}: {exc}")
        st.stop()

eol_soh = st.sidebar.slider("EOL SOH threshold", 0.70, 0.95, 0.80, 0.01)
n_boot = st.sidebar.select_slider("Bootstrap resamples", [0, 50, 100, 200, 400], value=100)
st.sidebar.caption("Intervals are conditional on the selected model family. "
                   "Increase resamples for smoother percentile bands.")

if df is None or report is None:
    st.stop()

try:
    with st.spinner("Running evbatt pipeline…"):
        result = _analyse(df, eol_soh, n_boot)
except Exception as exc:  # noqa: BLE001
    st.error(f"Analysis failed: {exc}")
    with st.expander("Traceback"):
        st.exception(exc)
    st.stop()

counts = result.qc_table["qc_status"].value_counts().to_dict()
st.success(f"Analysed {report.n_cells} cells / {report.n_rows:,} rows. QC: {counts}")

cell = st.selectbox("Cell", sorted(result.summary["cells"]))
info = result.summary["cells"][cell]
if info.get("status") != "ok":
    st.error(f"Cell {cell}: {info.get('status')}")
    for w in info.get("warnings", []):
        st.warning(w)
    st.stop()

eol = info.get("eol_cycle")
eol_ci = info.get("eol_ci")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Selected model", str(info.get("selected_model", "—")))
c2.metric("Q0 (Ah)", f"{info.get('reference_capacity_Ah', float('nan')):.4f}")
if eol is None:
    c3.metric("EOL cycle", "undefined")
elif eol_ci:
    c3.metric("EOL cycle", f"{eol:,.0f}", help=f"95% bootstrap CI [{eol_ci[0]:,.0f}, {eol_ci[1]:,.0f}]")
else:
    c3.metric("EOL cycle", f"{eol:,.0f}")
c4.metric("Hold-out RMSE", "—" if info.get("holdout_rmse") is None else f"{info['holdout_rmse']:.4f}")
c5.metric("Flagged rows", f"{info.get('n_anomalies', 0):,}")
if eol_ci:
    st.caption(f"EOL 95% bootstrap interval: {eol_ci[0]:,.0f}–{eol_ci[1]:,.0f} cycles "
               f"(conditional on the {info.get('selected_model')} model family).")
for w in info.get("warnings", []):
    st.warning(w)

fig, ax = plt.subplots(figsize=(11, 4.6))
g = result.clean_cycles[result.clean_cycles.cell_id == cell]
ax.plot(g.cycle_index, g.soh, ".", ms=3, alpha=0.7, label="Clean measurements")
u = result.uncertainty[result.uncertainty.cell_id == cell].sort_values("cycle_index")
obs_max = float(g.cycle_index.max())
if len(u):
    ax.plot(u.cycle_index, u.soh_predicted, "-", lw=2, label="Selected fit + forecast")
    ax.fill_between(u.cycle_index, u.pi_lo, u.pi_hi, alpha=0.20, label="95% prediction interval")
    ax.axvspan(obs_max, float(u.cycle_index.max()), color="grey", alpha=0.08)
    ax.axvline(obs_max, color="grey", ls=":", lw=1)
a = result.anomalies[result.anomalies.cell_id == cell]
if len(a):
    ax.plot(a.cycle_index, a.soh, "x", ms=6, color="crimson", label="Flagged (see table)")
if eol is not None:
    ax.axvline(eol, color="darkorange", ls="--", lw=1.2,
               label=f"EOL ≈ {eol:,.0f} cycles")
ax.axhline(eol_soh, color="red", ls=":", lw=1, label=f"EOL SOH={eol_soh:.2f}")
ax.set_xlabel("Cycle index (cycles)")
ax.set_ylabel("SOH = Q/Q0 (-)")
ax.set_ylim(max(0.0, float(g.soh.min()) - 0.05), 1.05)
ax.legend(loc="lower left", fontsize=8, ncol=2)
ax.grid(alpha=0.3)
st.pyplot(fig)

tab_models, tab_forecast, tab_qc, tab_flagged, tab_export = st.tabs(
    ["Model comparison", "Forecasts", "Data quality", "Flagged rows", "Export"])

with tab_models:
    comp = result.model_comparison[result.model_comparison.cell_id == cell]
    st.dataframe(comp, width="stretch", hide_index=True)
    unc = info.get("parameter_uncertainty") or {}
    if unc:
        st.markdown("**Parameter uncertainty** (local normal approximation; not valid at a bound)")
        st.dataframe(pd.DataFrame(unc).T, width="stretch")

with tab_forecast:
    st.dataframe(u, width="stretch", hide_index=True)
    if len(u):
        st.caption("is_extrapolation marks cycles beyond the last observed cycle. "
                   "Prediction intervals widen with extrapolation but assume the model family is correct.")

with tab_qc:
    st.markdown("**Ingestion report**")
    st.json(report.to_dict())
    st.markdown("**QC counts**")
    st.dataframe(result.qc_table["qc_status"].value_counts().rename_axis("status").reset_index(name="rows"),
                 width="stretch", hide_index=True)

with tab_flagged:
    st.dataframe(a, width="stretch", hide_index=True)
    st.caption("Every input row appears exactly once across clean_cycles + anomalies; "
               "nothing is silently dropped.")

with tab_export:
    st.download_button("analysis.json", json.dumps(result.summary, indent=2, default=str),
                       "analysis.json", "application/json")
    for name, frame in [("clean_cycles.csv", result.clean_cycles),
                        ("anomalies.csv", result.anomalies),
                        ("model_comparison.csv", result.model_comparison),
                        ("uncertainty.csv", result.uncertainty),
                        ("predictions.csv", result.predictions)]:
        st.download_button(name, frame.to_csv(index=False), name, "text/csv")

st.caption("Limitations: " + " ".join(result.summary.get("limitations", [])))
