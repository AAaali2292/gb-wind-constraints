"""Runs the aggregation, fit, chart and note on a made up panel.

This does not touch the API. It is here so that a change to one module cannot
quietly break the chart or the note without anything failing.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import chart, collect, model, run

UNITS = ["T_AAAAW-1", "T_BBBBW-1", "T_CCCCW-1"]


def fake_panel(days=120, seed=5):
    rng = np.random.default_rng(seed)
    stamps = pd.date_range("2025-09-01", periods=days * 48, freq="30min", tz="UTC")

    # label periods the same way the real pipeline does, so the clock change day
    # in October gets its fifty periods rather than a duplicated forty eight
    calendar = pd.DataFrame(
        {"bin": stamps, "settlement_date": stamps.tz_convert("Europe/London").normalize().tz_localize(None).date}
    )
    calendar["settlement_period"] = calendar.groupby("settlement_date").cumcount() + 1

    rows = []
    for unit_no, unit in enumerate(UNITS):
        scale = [1.0, 0.7, 0.45][unit_no]
        wind = np.clip(rng.weibull(2.0, len(stamps)) * 700 * scale, 0, 1400 * scale)
        frame = calendar.copy()
        frame.insert(0, "bm_unit", unit)
        frame["pn_mw"] = wind
        rows.append(frame)

    panel = pd.concat(rows, ignore_index=True)

    # curtail once the fleet total clears a threshold, share it out by unit size
    total = panel.groupby("bin")["pn_mw"].transform("sum")
    excess = np.clip(total - 1500, 0, None) * 0.5
    share = panel["pn_mw"] / total.replace(0, np.nan)
    panel["curtailed_mw"] = (excess * share).fillna(0).clip(lower=0)
    panel["curtailed_mw"] = np.minimum(panel["curtailed_mw"], panel["pn_mw"])

    panel["accepted_mw"] = panel["pn_mw"] - panel["curtailed_mw"]
    panel["pn_mwh"] = panel["pn_mw"] / 2
    panel["accepted_mwh"] = panel["accepted_mw"] / 2
    panel["bid_mwh"] = panel["curtailed_mw"] / 2
    panel["offer_mwh"] = 0.0
    return panel.drop(columns=["curtailed_mw"])


def fake_prices(panel, seed=6):
    rng = np.random.default_rng(seed)
    keys = panel[["settlement_date", "settlement_period"]].drop_duplicates().reset_index(drop=True)
    keys["day_ahead_price"] = np.round(rng.normal(85, 30, len(keys)), 2)
    keys["day_ahead_volume"] = 900.0
    return keys


def fake_units():
    return pd.DataFrame(
        {
            "elexonBmUnit": UNITS,
            "nationalGridBmUnit": [u[2:] for u in UNITS],
            "bmUnitName": ["Alpha Wind Farm", "Bravo Wind Farm", "Charlie Wind Farm"],
            "leadPartyName": ["Alpha Gen", "Bravo Gen", "Charlie Gen"],
            "gspGroupName": ["North Scotland", "South Scotland", "North Scotland"],
            "generationCapacity": [1400.0, 980.0, 630.0],
        }
    )


def test_pipeline_produces_a_chart_and_a_note(tmp_path):
    panel = fake_panel()
    prices = fake_prices(panel)
    units = fake_units()

    series = collect.aggregate(panel, prices)
    assert {"pn_mw", "curtailed_mw", "day_ahead_price"} <= set(series.columns)
    assert len(series) == panel["bin"].nunique()

    fit = model.fit_overall(series)
    assert fit.theta_mw == pytest.approx(1500, abs=200)
    assert fit.beta == pytest.approx(0.5, abs=0.08)
    assert fit.r_squared > 0.8

    monthly = model.fit_monthly(series)
    assert len(monthly) >= 3

    ctx, per_unit = run.build_context(series, panel, units, fit, monthly, "2025-09-01", "2025-12-29")

    assert ctx["curtailed_gwh"] > 0
    assert 0 < ctx["curtail_pct"] < 100
    assert len(ctx["top_units"]) == 3
    assert per_unit.iloc[0]["curtailed_mwh"] >= per_unit.iloc[-1]["curtailed_mwh"]

    png = chart.make_chart(series, fit, monthly, tmp_path / "curtailment.png", subtitle="test run")
    assert Path(png).stat().st_size > 40_000

    note = run.write_note(tmp_path / "findings.md", ctx)
    text = Path(note).read_text()

    assert "implied export headroom" in text
    assert "What this does not do" in text
    assert "{" not in text and "}" not in text  # nothing left unformatted
    assert len(text.split()) > 400
