"""Run the whole thing: pull data, fit the model, write the chart and the note.

    python -m src.run --start 2025-08-01 --end 2026-07-31
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import bmus, chart, collect, model

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PROCESSED = ROOT / "data" / "processed"


def parse_args():
    today = date.today()
    ap = argparse.ArgumentParser(description="Scottish wind curtailment model")
    ap.add_argument("--start", default=str(today - timedelta(days=365)))
    ap.add_argument("--end", default=str(today - timedelta(days=7)))
    ap.add_argument("--min-capacity", type=float, default=10.0)
    ap.add_argument("--min-days", type=int, default=3, help="days a unit must be bid off to count as constrained")
    ap.add_argument("--all-wind", action="store_true", help="skip discovery and use every wind unit")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--panel", default=None, help="skip fetching and use a saved half hourly panel")
    return ap.parse_args()


def money(value):
    """Round to something a reader can hold in their head rather than to the pound."""
    if value != value:
        return "n/a"
    if abs(value) >= 1e9:
        return f"£{value / 1e9:.2f} billion"
    if abs(value) >= 1e6:
        return f"£{value / 1e6:.0f} million"
    return f"£{value:,.0f}"


def write_note(path, ctx):
    lines = []
    add = lines.append

    add("# Scottish wind curtailment in the Balancing Mechanism")
    add("")
    add(f"Aliyan Nawaz. Data covers {ctx['start']} to {ctx['end']}, pulled from the Elexon Insights API.")
    add("Everything below comes from public data and can be reproduced by running the repo.")
    add("")

    add("## The question")
    add("")
    add(
        "Scotland regularly generates more wind than the network can move south. NESO deals with that "
        "by paying wind farms to turn down. I wanted to know three things from market data alone: how "
        "much Scottish wind actually gets bid off, at what point on the wind curve it starts, and "
        "whether that point is stable."
    )
    add("")

    add("## Method")
    add("")
    add(
        "The Elexon reference feed has no usable location for transmission connected units, so rather than "
        "label wind farms by geography I let the data pick the universe. I took every transmission "
        "connected wind BM Unit and kept the ones the system operator actually bids off, using the SO flag "
        "that marks actions taken for system reasons rather than energy balancing. That leaves "
        f"{ctx['n_units']} units, {ctx['capacity_gw']:.1f} GW of registered capacity, and in practice it is "
        "the Scottish fleet."
    )
    add("")
    add(
        "For every unit I laid physical notifications and bid offer acceptances on a one minute timeline, "
        "integrated both to half hourly volumes, and treated the gap where the accepted level sits below "
        "the physical notification as curtailment. Where acceptances overlap, the later one wins."
    )
    add("")
    add("Then I fitted")
    add("")
    add("    curtailed_MW = beta * max(0, scottish_wind_MW - theta)")
    add("")
    add(
        "by grid search on theta with least squares through the origin for beta at each candidate. "
        "Theta is an implied export headroom in MW. It is not a boundary limit and I am not claiming it "
        "is, it is the level of Scottish wind above which the system operator starts bidding wind off."
    )
    add("")

    add("## What the data shows")
    add("")
    add(
        f"Over the window, the Scottish wind fleet notified {ctx['pn_twh']:.2f} TWh and had "
        f"{ctx['curtailed_gwh']:,.0f} GWh bid off, which is {ctx['curtail_pct']:.1f} per cent of notified output. "
        f"Curtailment shows up in {ctx['periods_pct']:.0f} per cent of settlement periods."
    )
    add("")
    add(
        f"The fitted headroom is {ctx['theta']:,.0f} MW"
        + (
            f" with a bootstrap 90 per cent interval of {ctx['theta_low']:,.0f} to {ctx['theta_high']:,.0f} MW"
            if ctx["theta_low"] == ctx["theta_low"]
            else ""
        )
        + f". Above that level, {ctx['beta']:.0%} of every extra MW of Scottish wind gets bid off. "
        f"The fit explains {ctx['r2']:.0%} of the variance in half hourly curtailment."
    )
    add("")
    add(ctx["fit_comment"])
    add("")

    if ctx["value_gbp"] == ctx["value_gbp"]:
        add(
            f"Valued at the day ahead price in the same half hour, the curtailed energy is worth "
            f"{money(ctx['value_gbp'])}. That is the market value of energy not delivered, not the cost of "
            "the constraint. What NESO actually pays depends on bid prices, and what a generator nets "
            "depends on its own bid, neither of which I have modelled here."
        )
        add("")
        add(
            f"The average day ahead price across curtailed periods is {money(ctx['price_curtailed'])} per MWh "
            f"against {money(ctx['price_all'])} per MWh across all periods. "
            + ctx["price_comment"]
        )
        add("")

    add("## The headroom is not a constant")
    add("")
    if ctx["monthly_rows"]:
        add(
            f"Refitting month by month, theta ranges from {ctx['theta_min']:,.0f} MW in {ctx['theta_min_month']} "
            f"to {ctx['theta_max']:,.0f} MW in {ctx['theta_max_month']}, a spread of {ctx['theta_spread']:,.0f} MW."
        )
        add("")
        add(ctx["headroom_comment"])
    else:
        add("The window is too short to refit month by month. Rerun with a longer range to see the drift.")
    add("")

    add("## Where the volume sits")
    add("")
    add("| BM Unit | Name | Lead party | Curtailed GWh | Share of own notified output |")
    add("| --- | --- | --- | ---: | ---: |")
    for row in ctx["top_units"]:
        add(
            f"| {row['bm_unit']} | {row['name']} | {row['lead_party']} | "
            f"{row['curtailed_gwh']:,.0f} | {row['share']:.1f}% |"
        )
    add("")

    add("## What I would use this for")
    add("")
    add(
        "Three things. It gives a same day view of curtailment risk for a Scottish position once you have "
        "a wind forecast, since the model only needs notified output. It gives a way to check whether an "
        "expensive month was unusual wind or a network that got tighter, by looking at whether theta moved. "
        "And it gives a baseline to test reform against, because if balancing and dispatch changes do what "
        "they are meant to do, beta should fall even when theta does not move."
    )
    add("")

    add("## What this does not do")
    add("")
    add(
        "- The SO flag decides which units are in the universe, but once a unit is in, every bid it takes "
        "counts as curtailment, including energy balancing bids. Filtering acceptance by acceptance rather "
        "than unit by unit is the first thing I would add."
    )
    add(
        "- Selecting units because they were curtailed is a selection rule, so the fleet is defined partly "
        "by the outcome. It is the right universe for the question but it is not a neutral sample."
    )
    add(
        "- Physical notifications are a stand in for available wind. A unit that is already bid off may "
        "notify lower in later periods, which biases the curtailment estimate down."
    )
    add("- It treats Scotland as one node, so it will not see intra Scottish constraints.")
    add(
        "- It says nothing about bid prices, so it cannot tell you what the constraint costs or what any "
        "generator earned."
    )
    add("")

    add("## Sources")
    add("")
    add("- Elexon Insights API, datasets PN, BOALF and MID, and the BM Unit reference list")
    add("- No commercial or proprietary data is used anywhere in this repo")
    add("")

    path.write_text("\n".join(lines))
    return path


def build_context(series, panel, units, fit, monthly, start, end):
    pn_twh = series["pn_mwh"].sum() / 1e6
    curtailed_gwh = series["bid_mwh"].sum() / 1e3
    curtail_pct = 100 * series["bid_mwh"].sum() / max(series["pn_mwh"].sum(), 1)
    periods_pct = 100 * (series["bid_mwh"] > 1).mean()

    if "day_ahead_price" in series.columns and series["day_ahead_price"].notna().any():
        valued = series.dropna(subset=["day_ahead_price"])
        value_gbp = float((valued["bid_mwh"] * valued["day_ahead_price"]).sum())
        curtailed_mask = valued["bid_mwh"] > 1
        price_curtailed = float(valued.loc[curtailed_mask, "day_ahead_price"].mean())
        price_all = float(valued["day_ahead_price"].mean())
        if price_curtailed < price_all:
            price_comment = (
                "Curtailment lands in cheaper hours, which is what you would expect when the thing causing "
                "it is a lot of wind on the system."
            )
        else:
            price_comment = (
                "Curtailment is not concentrated in cheap hours over this window, which is worth a second "
                "look before drawing conclusions from it."
            )
    else:
        value_gbp = float("nan")
        price_curtailed = price_all = float("nan")
        price_comment = ""

    if fit.r_squared >= 0.6:
        fit_comment = (
            "A single threshold and a single slope get most of the way there, which says the behaviour is "
            "close to mechanical once the boundary is full."
        )
    elif fit.r_squared >= 0.35:
        fit_comment = (
            "The shape is clearly there but a fair amount sits outside it, so the boundary is not the only "
            "thing driving these acceptances."
        )
    else:
        fit_comment = (
            "The hinge shape explains less than a third of the variation, so on this window curtailment is "
            "being driven by more than a simple boundary threshold and I would not lean on the fit alone."
        )

    per_unit = (
        panel.groupby("bm_unit", as_index=False)
        .agg(curtailed_mwh=("bid_mwh", "sum"), pn_mwh=("pn_mwh", "sum"))
        .merge(units, left_on="bm_unit", right_on="elexonBmUnit", how="left")
        .sort_values("curtailed_mwh", ascending=False)
    )

    top_units = [
        {
            "bm_unit": r.bm_unit,
            "name": (r.bmUnitName or "")[:34],
            "lead_party": (r.leadPartyName or "")[:26],
            "curtailed_gwh": r.curtailed_mwh / 1000.0,
            "share": 100 * r.curtailed_mwh / max(r.pn_mwh, 1),
        }
        for r in per_unit.head(8).itertuples()
    ]

    ctx = {
        "start": str(start),
        "end": str(end),
        "n_units": len(units),
        "capacity_gw": units["generationCapacity"].sum() / 1000.0,
        "pn_twh": pn_twh,
        "curtailed_gwh": curtailed_gwh,
        "curtail_pct": curtail_pct,
        "periods_pct": periods_pct,
        "theta": fit.theta_mw,
        "theta_low": fit.theta_low,
        "theta_high": fit.theta_high,
        "beta": fit.beta,
        "r2": fit.r_squared,
        "fit_comment": fit_comment,
        "value_gbp": value_gbp,
        "price_curtailed": price_curtailed,
        "price_all": price_all,
        "price_comment": price_comment,
        "monthly_rows": len(monthly),
        "top_units": top_units,
    }

    if len(monthly):
        lo = monthly.loc[monthly["theta_mw"].idxmin()]
        hi = monthly.loc[monthly["theta_mw"].idxmax()]
        spread = hi["theta_mw"] - lo["theta_mw"]
        centre = monthly["theta_mw"].mean()

        if centre > 0 and spread > 0.15 * centre:
            headroom_comment = (
                "A threshold that moves by that much month to month is not describing a static network. "
                "Planned outages, reduced circuit ratings and changes in how the constraint is managed all "
                "land in this one number. For anyone holding Scottish wind, that spread is the difference "
                "between a normal month and an expensive one."
            )
        elif centre > 0 and spread > 0.05 * centre:
            headroom_comment = (
                "That is a modest drift rather than a step change. It is enough to matter for a month by "
                "month view of curtailment risk, but not enough to argue that the network behaved very "
                "differently across the window."
            )
        else:
            headroom_comment = (
                "On this window the threshold is close to stable, so the variation in monthly curtailment "
                "volume is coming from the wind rather than from the network. That is a useful negative "
                "result: it means a wind forecast alone gets you most of the way to a curtailment view."
            )

        ctx.update(
            theta_min=lo["theta_mw"],
            theta_min_month=lo["month"],
            theta_max=hi["theta_mw"],
            theta_max_month=hi["month"],
            theta_spread=spread,
            headroom_comment=headroom_comment,
        )

    return ctx, per_unit


def main():
    args = parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)

    wind = bmus.wind_units(min_capacity_mw=args.min_capacity, use_cache=not args.no_cache)
    if wind.empty:
        raise RuntimeError("no transmission connected wind units came back from the reference feed")
    print(f"{len(wind)} transmission connected wind BM Units in the reference list")

    if args.all_wind:
        units = wind
    else:
        constrained = collect.discover_constrained_units(
            args.start,
            args.end,
            wind["elexonBmUnit"].tolist(),
            min_days=args.min_days,
            use_cache=not args.no_cache,
        )
        if not constrained:
            raise RuntimeError(
                "no wind unit was bid off with the SO flag in this window. Try a longer range, "
                "a winter month, or --min-days 1"
            )
        units = wind[wind["elexonBmUnit"].isin(constrained)].reset_index(drop=True)

    units.to_csv(PROCESSED / "constrained_wind_units.csv", index=False)
    print(f"{len(units)} of them get bid off, {units['generationCapacity'].sum() / 1000:.1f} GW between them")

    if args.panel:
        panel = pd.read_csv(args.panel, parse_dates=["bin"])
        panel["settlement_date"] = pd.to_datetime(panel["settlement_date"]).dt.date
        prices = pd.DataFrame()
    else:
        panel, prices = collect.build_range(
            args.start, args.end, units["elexonBmUnit"].tolist(), use_cache=not args.no_cache
        )
        panel.to_csv(PROCESSED / "half_hourly_by_unit.csv", index=False)

    series = collect.aggregate(panel, prices)
    series.to_csv(PROCESSED / "scotland_half_hourly.csv", index=False)

    fit = model.fit_overall(series)
    monthly = model.fit_monthly(series)
    monthly.to_csv(PROCESSED / "monthly_fits.csv", index=False)

    ctx, per_unit = build_context(series, panel, units, fit, monthly, args.start, args.end)
    per_unit.to_csv(PROCESSED / "curtailment_by_unit.csv", index=False)

    chart.make_chart(
        series,
        fit,
        monthly,
        OUT / "curtailment.png",
        subtitle=f"Elexon Insights data, {args.start} to {args.end}. Public data only.",
    )
    write_note(OUT / "findings.md", ctx)

    with open(OUT / "results.json", "w") as fh:
        json.dump({k: v for k, v in ctx.items() if k != "top_units"} | {"fit": fit.to_dict()}, fh, indent=2, default=str)

    print(f"curtailed {ctx['curtailed_gwh']:,.0f} GWh, {ctx['curtail_pct']:.1f}% of notified output")
    print(f"theta {fit.theta_mw:,.0f} MW, beta {fit.beta:.2f}, R2 {fit.r_squared:.2f}")
    print(f"wrote {OUT / 'curtailment.png'} and {OUT / 'findings.md'}")


if __name__ == "__main__":
    main()
