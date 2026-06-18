"""MSTAT extractor tests on a synthetic MSTAT-layout workbook."""
import io

import pytest
from openpyxl import Workbook

from evbatt.mstat import parse_workbook_bytes


def _make_workbook(n_cycles: int = 3) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for c in range(1, n_cycles + 1):
        ws = wb.create_sheet(f"Run01_Un1Ch7_Step2_Cycle{c:02d}")
        ws.append(["Begin Header: MultiStat_DCData"])
        ws.append(["    Exp Title: synthetic fixture"])
        ws.append(["End Header: MultiStat_DCData_1.0"])
        # 1800 s charge at +0.625 A, then 1800 s discharge at -0.625 A
        t = 0
        for _ in range(1800):
            ws.append([t, 3.4, 0.625])
            t += 1
        for _ in range(1800):
            ws.append([t, 3.2, -0.625])
            t += 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_mstat_coulomb_counting_exact():
    data = _make_workbook()
    recs = parse_workbook_bytes(data, "B1_Discharge0.5C_Charge0.5C", "Cycle_0150.xlsx")
    assert len(recs) == 3
    # 0.625 A * 1800 s / 3600 = 0.3125 Ah (trapezoid on 1 Hz grid: 1799 intervals)
    assert recs[0]["discharge_capacity_Ah"] == pytest.approx(0.3125 * 1799 / 1800, rel=1e-3)
    assert recs[0]["charge_capacity_Ah"] == pytest.approx(recs[0]["discharge_capacity_Ah"], rel=1e-9)
    # Block ends at 150 with 3 sheets -> global cycles 148, 149, 150
    assert [r["cycle_index"] for r in recs] == [148, 149, 150]
    assert recs[0]["cell_id"] == "B1_Dis0.5C_Chg0.5C"
    assert recs[0]["discharge_crate"] == 0.5


def test_mstat_ignores_nonmatching_names():
    assert parse_workbook_bytes(b"not a workbook", "random", "foo.xlsx") == []
