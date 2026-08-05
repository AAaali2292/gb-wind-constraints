"""Pull a date range off the API and build the half hourly panel.

One day at a time. Physical notifications are requested per unit in chunks
because the endpoint filters on BM unit, acceptances are pulled market wide once
per day and filtered locally, which is cheaper than asking per unit.
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pandas as pd

from . import elexon, profiles

# One request per unit, run a few at a time. See fetch_pn for why it cannot be batched.
PN_WORKERS = 6


def _day_window(settlement_date):
    """UTC start and end of a GB settlement day."""
    start_local = pd.Timestamp(settlement_date).tz_localize(profiles.LONDON)
    end_local = (pd.Timestamp(settlement_date) + timedelta(days=1)).tz_localize(profiles.LONDON)
    return start_local.tz_convert("UTC"), end_local.tz_convert("UTC")


def _iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%MZ")


def fetch_pn(bm_units, start_utc, end_utc, use_cache=True):
    """Physical notifications, one request per unit.

    The endpoint documents bmUnit as a repeatable parameter, but the request gets
    redirected and the duplicates are dropped on the way, so asking for ten units
    quietly returns only the first one. That failure is silent and it wrecks the
    numbers, because every unit with no notification looks like it produced
    nothing while its acceptances still show up. One unit per request is the only
    reliable form, so they run a few at a time to make up the difference.
    """

    def one(unit):
        return elexon.rows(
            "/balancing/physical",
            params={
                "bmUnit": unit,
                "dataset": "PN",
                "from": _iso(start_utc),
                "to": _iso(end_utc),
            },
            use_cache=use_cache,
        )

    out = []
    with ThreadPoolExecutor(max_workers=PN_WORKERS) as pool:
        for result in pool.map(one, list(bm_units)):
            out.extend(result)
    return out


def fetch_boalf(start_utc, end_utc, use_cache=True):
    return elexon.rows(
        "/datasets/BOALF",
        params={"from": _iso(start_utc), "to": _iso(end_utc)},
        use_cache=use_cache,
    )


def fetch_prices(settlement_date, use_cache=True):
    rows = elexon.rows(
        "/datasets/MID",
        params={"from": str(settlement_date), "to": str(settlement_date)},
        use_cache=use_cache,
    )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame[frame["dataProvider"] == "APXMIDP"]
    return frame[["settlementDate", "settlementPeriod", "price", "volume"]].rename(
        columns={
            "settlementDate": "settlement_date",
            "settlementPeriod": "settlement_period",
            "price": "day_ahead_price",
            "volume": "day_ahead_volume",
        }
    )


def discover_constrained_units(start_date, end_date, candidates, min_days=3, sample_days=40, use_cache=True):
    """Which wind units does the system operator actually bid off.

    Reads the acceptance feed and counts the days each candidate appears with the
    SO flag set, which is the flag NESO puts on actions taken for system reasons
    rather than for energy balancing. Units that never show up are not part of
    the constraint story, so there is no point spending API calls pulling their
    notifications.

    This replaces trying to label units by geography. The reference feed has no
    usable location for transmission connected units, and in practice the set
    that comes back here is the Scottish fleet, which is the point.
    """
    dates = pd.date_range(start_date, end_date, freq="D").date
    if sample_days and len(dates) > sample_days:
        step = max(1, len(dates) // sample_days)
        dates = dates[::step]

    wanted = set(candidates)
    seen = {}

    print(f"  scanning {len(dates)} days of acceptances to find the constrained units", file=sys.stderr)
    for day in dates:
        start_utc, end_utc = _day_window(day)
        for rec in fetch_boalf(start_utc, end_utc, use_cache=use_cache):
            unit = rec.get("bmUnit")
            if unit in wanted and rec.get("soFlag"):
                seen.setdefault(unit, set()).add(day)

    return sorted(unit for unit, days in seen.items() if len(days) >= min_days)


def build_day(settlement_date, bm_units, use_cache=True):
    start_utc, end_utc = _day_window(settlement_date)

    pn_rows = fetch_pn(bm_units, start_utc, end_utc, use_cache=use_cache)
    boalf_rows = fetch_boalf(start_utc, end_utc, use_cache=use_cache)

    pn_by_unit = {}
    for rec in pn_rows:
        pn_by_unit.setdefault(rec["bmUnit"], []).append(rec)

    wanted = set(bm_units)
    boalf_by_unit = {}
    for rec in boalf_rows:
        unit = rec.get("bmUnit")
        if unit in wanted:
            boalf_by_unit.setdefault(unit, []).append(rec)

    frames = []
    for unit in bm_units:
        if unit not in pn_by_unit and unit not in boalf_by_unit:
            continue
        frame = profiles.unit_half_hourly(
            pn_by_unit.get(unit, []),
            boalf_by_unit.get(unit, []),
            start_utc,
            end_utc,
        )
        frame.insert(0, "bm_unit", unit)
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def build_range(start_date, end_date, bm_units, use_cache=True, progress=True):
    dates = pd.date_range(start_date, end_date, freq="D").date
    daily_frames = []
    price_frames = []

    for n, day in enumerate(dates, start=1):
        if progress:
            print(f"  {day}  ({n}/{len(dates)})", file=sys.stderr)
        frame = build_day(day, bm_units, use_cache=use_cache)
        if not frame.empty:
            daily_frames.append(frame)
        prices = fetch_prices(day, use_cache=use_cache)
        if not prices.empty:
            price_frames.append(prices)

    if not daily_frames:
        raise RuntimeError("no data came back, check the date range")

    panel = drop_units_without_notifications(pd.concat(daily_frames, ignore_index=True))
    prices = pd.concat(price_frames, ignore_index=True) if price_frames else pd.DataFrame()
    return panel, prices


def drop_units_without_notifications(panel):
    """Remove units that have acceptances but no physical notifications at all.

    A unit that never notified anything across a whole window has not been idle,
    it has failed to download. Leaving it in makes curtailment look enormous
    relative to notified output, so it gets dropped loudly rather than quietly
    averaged in.
    """
    totals = panel.groupby("bm_unit")["pn_mwh"].sum()
    empty = totals[totals <= 0].index.tolist()

    if empty:
        print(
            f"  dropping {len(empty)} units with no physical notifications in this window: "
            f"{', '.join(empty[:6])}{' and others' if len(empty) > 6 else ''}",
            file=sys.stderr,
        )
        panel = panel[~panel["bm_unit"].isin(empty)].reset_index(drop=True)

    return panel


def aggregate(panel, prices):
    """Collapse the per unit panel to a Scotland wide half hourly series."""
    grouped = (
        panel.groupby(["settlement_date", "settlement_period"], as_index=False)
        .agg(
            pn_mw=("pn_mw", "sum"),
            accepted_mw=("accepted_mw", "sum"),
            pn_mwh=("pn_mwh", "sum"),
            bid_mwh=("bid_mwh", "sum"),
            offer_mwh=("offer_mwh", "sum"),
            units=("bm_unit", "nunique"),
        )
    )
    grouped["curtailed_mw"] = grouped["bid_mwh"] * 2.0

    if not prices.empty:
        prices = prices.copy()
        prices["settlement_date"] = pd.to_datetime(prices["settlement_date"]).dt.date
        grouped = grouped.merge(prices, on=["settlement_date", "settlement_period"], how="left")

    return grouped
