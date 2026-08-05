"""Turn PN and BOALF records into half hourly volumes.

The BM publishes physical notifications and bid offer acceptances as sloped
segments with a start time, an end time and a level at each end. To get a volume
you have to lay those segments on a timeline and integrate. This module does it
on a one minute grid, which is fine given acceptances are published to the
minute, and keeps the arithmetic easy to check by hand.

Curtailment is the gap between what the unit said it would produce and what it
was instructed to produce, so bid volume equals PN minus accepted level whenever
that difference is positive.
"""

import numpy as np
import pandas as pd

LONDON = "Europe/London"


def _to_utc(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _minute_grid(start_utc, end_utc):
    """Midpoints of every minute in the window, which is what we sample levels at."""
    edges = pd.date_range(start_utc, end_utc, freq="1min", tz="UTC", inclusive="left")
    return edges + pd.Timedelta(seconds=30)


def _apply_segment(levels, midpoints, time_from, time_to, level_from, level_to):
    t0 = _to_utc(time_from)
    t1 = _to_utc(time_to)

    if t1 < t0:
        return
    if t1 == t0:
        # a zero length segment still pins the level for the minute it sits in
        mask = (midpoints >= t0 - pd.Timedelta(seconds=30)) & (midpoints < t0 + pd.Timedelta(seconds=30))
        levels[mask] = level_to
        return

    mask = (midpoints >= t0) & (midpoints < t1)
    if not mask.any():
        return

    span = (t1 - t0).total_seconds()
    elapsed = (midpoints[mask] - t0).total_seconds()
    levels[mask] = level_from + (level_to - level_from) * (elapsed / span)


def pn_profile(pn_records, start_utc, end_utc):
    """Minute by minute physical notification level in MW. Gaps count as zero."""
    midpoints = _minute_grid(start_utc, end_utc)
    levels = np.zeros(len(midpoints))

    for rec in pn_records:
        _apply_segment(
            levels,
            midpoints,
            rec["timeFrom"],
            rec["timeTo"],
            float(rec["levelFrom"]),
            float(rec["levelTo"]),
        )

    return midpoints, levels


def accepted_profile(pn_levels, midpoints, boalf_records):
    """Overlay acceptances on the PN. Where two acceptances overlap the later one wins."""
    levels = pn_levels.copy()

    ordered = sorted(boalf_records, key=lambda r: (r.get("acceptanceTime") or "", r.get("acceptanceNumber") or 0))

    for rec in ordered:
        _apply_segment(
            levels,
            midpoints,
            rec["timeFrom"],
            rec["timeTo"],
            float(rec["levelFrom"]),
            float(rec["levelTo"]),
        )

    return levels


def to_half_hourly(midpoints, pn_levels, accepted_levels):
    """Average MW per settlement period, labelled with settlement date and period.

    Periods are cut on Europe/London local time so short and long clock change
    days fall out correctly rather than needing a special case.
    """
    frame = pd.DataFrame(
        {"pn_mw": pn_levels, "accepted_mw": accepted_levels},
        index=pd.DatetimeIndex(midpoints, name="minute"),
    )

    # Settlement periods always sit on UTC half hours, so floor in UTC and only
    # convert to local time to work out which settlement day a period belongs to.
    bins_utc = frame.index.floor("30min")
    frame["bin"] = bins_utc
    frame["settlement_date"] = bins_utc.tz_convert(LONDON).normalize().tz_localize(None).date

    grouped = frame.groupby(["settlement_date", "bin"], as_index=False)[["pn_mw", "accepted_mw"]].mean()
    grouped = grouped.sort_values("bin").reset_index(drop=True)
    grouped["settlement_period"] = grouped.groupby("settlement_date").cumcount() + 1

    grouped["pn_mwh"] = grouped["pn_mw"] / 2.0
    grouped["accepted_mwh"] = grouped["accepted_mw"] / 2.0
    grouped["bid_mwh"] = (grouped["pn_mwh"] - grouped["accepted_mwh"]).clip(lower=0)
    grouped["offer_mwh"] = (grouped["accepted_mwh"] - grouped["pn_mwh"]).clip(lower=0)

    return grouped[
        [
            "settlement_date",
            "settlement_period",
            "bin",
            "pn_mw",
            "accepted_mw",
            "pn_mwh",
            "accepted_mwh",
            "bid_mwh",
            "offer_mwh",
        ]
    ]


def unit_half_hourly(pn_records, boalf_records, start_utc, end_utc):
    midpoints, pn_levels = pn_profile(pn_records, start_utc, end_utc)
    accepted = accepted_profile(pn_levels, midpoints, boalf_records)
    return to_half_hourly(midpoints, pn_levels, accepted)
