"""Can the fit recover a threshold I planted myself."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import model

TRUE_THETA = 3200.0
TRUE_BETA = 0.55


def synthetic(n=4000, noise=60.0, seed=3):
    rng = np.random.default_rng(seed)
    wind = rng.uniform(0, 6000, n)
    curtailed = TRUE_BETA * np.clip(wind - TRUE_THETA, 0, None)
    curtailed = np.clip(curtailed + rng.normal(0, noise, n), 0, None)
    return wind, curtailed


def test_recovers_the_planted_threshold():
    wind, curtailed = synthetic()
    fit = model.fit_hinge(wind, curtailed)
    assert fit.theta_mw == pytest.approx(TRUE_THETA, abs=250)
    assert fit.beta == pytest.approx(TRUE_BETA, abs=0.05)
    assert fit.r_squared > 0.9


def test_flat_data_does_not_produce_a_confident_fit():
    rng = np.random.default_rng(11)
    wind = rng.uniform(0, 6000, 2000)
    curtailed = rng.normal(100, 20, 2000)
    fit = model.fit_hinge(wind, curtailed)
    assert fit.r_squared < 0.2


def test_too_few_points_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        model.fit_hinge(np.arange(10), np.arange(10))


def test_bootstrap_interval_brackets_the_estimate():
    wind, curtailed = synthetic(n=2000)
    low, high = model.bootstrap_theta(wind, curtailed, draws=40, grid_points=80)
    assert low < TRUE_THETA < high


def test_monthly_fit_returns_one_row_per_month_with_enough_data():
    wind, curtailed = synthetic(n=3000)
    dates = pd.date_range("2026-01-01", periods=3000, freq="30min")
    frame = pd.DataFrame(
        {
            "settlement_date": dates.date,
            "pn_mw": wind,
            "curtailed_mw": curtailed,
            "bid_mwh": curtailed / 2,
        }
    )
    monthly = model.fit_monthly(frame, min_obs=200)
    assert len(monthly) >= 2
    assert monthly["theta_mw"].between(TRUE_THETA - 600, TRUE_THETA + 600).all()
