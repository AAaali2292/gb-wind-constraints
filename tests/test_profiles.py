"""Checks on the volume arithmetic, done against cases I can work out by hand."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import profiles

START = pd.Timestamp("2026-01-15T00:00Z")
END = pd.Timestamp("2026-01-15T02:00Z")


def pn(time_from, time_to, level_from, level_to):
    return {"timeFrom": time_from, "timeTo": time_to, "levelFrom": level_from, "levelTo": level_to}


def boalf(time_from, time_to, level_from, level_to, acceptance_time, number=1):
    return {
        "timeFrom": time_from,
        "timeTo": time_to,
        "levelFrom": level_from,
        "levelTo": level_to,
        "acceptanceTime": acceptance_time,
        "acceptanceNumber": number,
    }


def test_flat_pn_gives_half_the_mw_as_mwh():
    records = [pn("2026-01-15T00:00Z", "2026-01-15T00:30Z", 100, 100)]
    out = profiles.unit_half_hourly(records, [], START, END)
    first = out.iloc[0]
    assert first["pn_mw"] == pytest.approx(100.0)
    assert first["pn_mwh"] == pytest.approx(50.0)
    assert first["bid_mwh"] == pytest.approx(0.0)


def test_ramp_averages_to_the_midpoint():
    records = [pn("2026-01-15T00:00Z", "2026-01-15T00:30Z", 0, 100)]
    out = profiles.unit_half_hourly(records, [], START, END)
    # minute midpoints run 0.5 to 29.5 minutes in, so the mean sits on 50 MW
    assert out.iloc[0]["pn_mw"] == pytest.approx(50.0, abs=0.5)


def test_bid_acceptance_is_counted_as_curtailment():
    records = [
        pn("2026-01-15T00:00Z", "2026-01-15T00:30Z", 100, 100),
        pn("2026-01-15T00:30Z", "2026-01-15T01:00Z", 100, 100),
    ]
    acceptances = [boalf("2026-01-15T00:00Z", "2026-01-15T00:30Z", 40, 40, "2026-01-14T23:00Z")]
    out = profiles.unit_half_hourly(records, acceptances, START, END)

    assert out.iloc[0]["accepted_mw"] == pytest.approx(40.0)
    assert out.iloc[0]["bid_mwh"] == pytest.approx(30.0)
    # the untouched period should show nothing
    assert out.iloc[1]["bid_mwh"] == pytest.approx(0.0)


def test_offer_acceptance_is_not_counted_as_curtailment():
    records = [pn("2026-01-15T00:00Z", "2026-01-15T00:30Z", 100, 100)]
    acceptances = [boalf("2026-01-15T00:00Z", "2026-01-15T00:30Z", 160, 160, "2026-01-14T23:00Z")]
    out = profiles.unit_half_hourly(records, acceptances, START, END)

    assert out.iloc[0]["bid_mwh"] == pytest.approx(0.0)
    assert out.iloc[0]["offer_mwh"] == pytest.approx(30.0)


def test_later_acceptance_wins_where_two_overlap():
    records = [pn("2026-01-15T00:00Z", "2026-01-15T00:30Z", 100, 100)]
    acceptances = [
        boalf("2026-01-15T00:00Z", "2026-01-15T00:30Z", 40, 40, "2026-01-14T23:00Z", number=1),
        boalf("2026-01-15T00:00Z", "2026-01-15T00:30Z", 10, 10, "2026-01-14T23:20Z", number=2),
    ]
    out = profiles.unit_half_hourly(records, acceptances, START, END)
    assert out.iloc[0]["accepted_mw"] == pytest.approx(10.0)


def test_partial_period_acceptance_is_pro_rated():
    records = [pn("2026-01-15T00:00Z", "2026-01-15T00:30Z", 100, 100)]
    # bid to zero for the last fifteen minutes only, so half the period is lost
    acceptances = [boalf("2026-01-15T00:15Z", "2026-01-15T00:30Z", 0, 0, "2026-01-14T23:00Z")]
    out = profiles.unit_half_hourly(records, acceptances, START, END)
    assert out.iloc[0]["accepted_mw"] == pytest.approx(50.0, abs=1.0)
    assert out.iloc[0]["bid_mwh"] == pytest.approx(25.0, abs=0.5)


def test_missing_pn_is_treated_as_zero_not_dropped():
    out = profiles.unit_half_hourly([], [], START, END)
    assert len(out) == 4
    assert out["pn_mwh"].sum() == pytest.approx(0.0)


def test_settlement_periods_number_from_one():
    records = [pn("2026-01-15T00:00Z", "2026-01-15T00:30Z", 50, 50)]
    out = profiles.unit_half_hourly(records, [], START, END)
    assert list(out["settlement_period"]) == [1, 2, 3, 4]
