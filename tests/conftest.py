import numpy as np
import pytest

from evbatt.schemas import AnalysisConfig
from evbatt.synthetic import generate_dataset


@pytest.fixture(scope="session")
def fast_config() -> AnalysisConfig:
    return AnalysisConfig(n_bootstrap=40)


@pytest.fixture(scope="session")
def synthetic_data():
    return generate_dataset(n_cells=3, max_cycle=600, seed=11)


@pytest.fixture()
def clean_linear():
    """Noise-free linear trajectory: analytic checks must hold exactly."""
    k = np.arange(0, 501, 10, dtype=float)
    return k, 1.0 - 0.0004 * k
