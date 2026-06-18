"""Validated schemas and configuration for cycle-level battery data.

Canonical cycle-level schema (one row per measured cycle):

- ``cell_id`` (str): unique cell identifier.
- ``cycle_index`` (int >= 0): cumulative cycle count at measurement.
- ``discharge_capacity_Ah`` (float > 0): measured discharge capacity in Ah.
- ``charge_capacity_Ah`` (float > 0, optional): charge capacity in Ah.
- ``temperature_C`` (float, optional): ambient/cell temperature in degC.
- ``discharge_crate`` / ``charge_crate`` (float > 0, optional): C-rates.
- ``depth_of_discharge`` (float in (0, 1], optional).

Definitions used everywhere in this package:

- Reference capacity ``Q0`` per cell = median discharge capacity of the
  first ``n_reference`` *valid* (physically admissible) observations by
  cycle order.  SOH = Q / Q0 (dimensionless, typically ~1 at beginning
  of life).  Nominal capacity is *not* used as Q0 because measured
  beginning-of-life capacity routinely differs from nameplate rating.
- End of life (EOL) cycle = first cycle at which the *selected model's*
  fitted SOH crosses ``eol_soh`` (default 0.80), obtained by root
  finding on the model (not by interpolating noisy points).  If the
  model never crosses within ``eol_max_cycles``, EOL is reported as
  undefined (null) with an extrapolation warning.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

CANONICAL_COLUMNS = [
    "cell_id",
    "cycle_index",
    "discharge_capacity_Ah",
    "charge_capacity_Ah",
    "temperature_C",
    "discharge_crate",
    "charge_crate",
    "depth_of_discharge",
]

REQUIRED_COLUMNS = ["cell_id", "cycle_index", "discharge_capacity_Ah"]


class AnalysisConfig(BaseModel):
    """Configuration for one degradation analysis run."""

    eol_soh: float = Field(default=0.80, gt=0.0, lt=1.0)
    n_reference: int = Field(default=3, ge=1, le=20)
    robust_loss: bool = True
    anomaly_mad_threshold: float = Field(default=4.0, gt=0.0)
    min_cycles_per_cell: int = Field(default=8, ge=5)
    holdout_fraction: float = Field(default=0.30, gt=0.0, lt=0.8)
    n_bootstrap: int = Field(default=200, ge=0, le=5000)
    bootstrap_seed: int = 12345
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    eol_max_cycles: float = Field(default=20000.0, gt=0.0)
    # Hard physical plausibility bounds for Li-ion cycling data.
    max_capacity_Ah: float = Field(default=500.0, gt=0.0)
    temperature_range_C: tuple[float, float] = (-40.0, 80.0)
    max_crate: float = Field(default=20.0, gt=0.0)
    # A single measurement above this multiple of Q0 is physically
    # implausible for a check-up cycle and is treated as corruption.
    max_capacity_multiple: float = Field(default=1.25, gt=1.0)
