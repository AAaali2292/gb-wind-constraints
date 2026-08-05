"""The guards that stop a broken run being mistaken for a finding.

These exist because of a real failure. The physical notification endpoint takes a
repeatable bmUnit parameter, drops all but the first on redirect, and returns 200
either way. The result was a run reporting 62 per cent curtailment and a beta of
1.65, both impossible, with nothing raising an error.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import collect, model, run


def context(curtail_pct=8.0, periods_pct=30.0, n_units=40):
    return {"curtail_pct": curtail_pct, "periods_pct": periods_pct, "n_units": n_units}


def fit(beta=0.4):
    return model.HingeFit(theta_mw=3000.0, beta=beta, r_squared=0.7, n=5000)


def test_a_plausible_run_raises_nothing():
    assert run.sanity_check(context(), fit()) == []


def test_impossible_curtailment_share_is_caught():
    problems = run.sanity_check(context(curtail_pct=62.1), fit())
    assert len(problems) == 1
    assert "notifications are probably missing" in problems[0]


def test_beta_above_one_is_caught():
    problems = run.sanity_check(context(), fit(beta=1.65))
    assert any("cannot happen" in p for p in problems)


def test_the_real_broken_run_would_have_been_stopped():
    problems = run.sanity_check(context(curtail_pct=62.1, periods_pct=95.0), fit(beta=1.65))
    assert len(problems) == 3


def test_units_with_no_notifications_are_dropped():
    panel = pd.DataFrame(
        {
            "bm_unit": ["T_GOOD-1"] * 3 + ["T_BROKEN-1"] * 3,
            "pn_mwh": [10.0, 12.0, 8.0, 0.0, 0.0, 0.0],
            "bid_mwh": [1.0, 2.0, 0.0, 5.0, 6.0, 4.0],
        }
    )
    cleaned = collect.drop_units_without_notifications(panel)

    assert set(cleaned["bm_unit"]) == {"T_GOOD-1"}
    # the phantom curtailment goes with it
    assert cleaned["bid_mwh"].sum() == 3.0


def test_a_clean_panel_is_left_alone():
    panel = pd.DataFrame({"bm_unit": ["T_A-1", "T_B-1"], "pn_mwh": [5.0, 7.0], "bid_mwh": [1.0, 0.0]})
    assert len(collect.drop_units_without_notifications(panel)) == 2
