# Scottish wind curtailment in the Balancing Mechanism

Measures how much Scottish transmission connected wind gets bid off in the BM, works out
the level of Scottish wind at which curtailment starts, and checks whether that level holds
still over time. Public data only, from the Elexon Insights API.

I built this because constraint costs are the biggest single moving part in GB power at the
moment and I wanted to see how much of the picture you can rebuild from market data without
any network model at all. The answer is more than I expected.

## The idea

Scotland can only export so much south. Below that level nothing gets turned down. Above it,
roughly a fixed share of the excess gets bid off. So the shape to fit is

```
curtailed_MW = beta * max(0, scottish_wind_MW - theta)
```

`theta` is an implied export headroom in MW. It is not a boundary limit and I am not
claiming it is. It is the level of Scottish wind above which the system operator starts
paying wind to turn down, inferred purely from acceptances. `beta` is how much of each extra
MW lands on wind rather than somewhere else.

The useful part is not the fit itself, it is that `theta` moves. Refit it month by month and
you get a market implied read on how tight the boundary was, which you can compare against
outage plans.

## How curtailment is measured

For each Scottish wind BM Unit:

1. Physical notifications and bid offer acceptances are laid on a one minute timeline. Both
   arrive as sloped segments with a level at each end, so each one is interpolated across
   the minutes it covers.
2. Where two acceptances overlap, the later acceptance time wins.
3. Both timelines are integrated to half hourly MWh.
4. Curtailment is the positive part of physical notification minus accepted level.

The unit universe is not hardcoded. It comes from the Elexon BM Unit reference list filtered
to wind, transmission connected, and a North Scotland or South Scotland GSP group, so it
stays current as units connect.

## Running it

```bash
pip install -r requirements.txt
python -m src.run --start 2025-08-01 --end 2026-07-31
```

Every API response is cached under `data/raw`, so the first run is slow and every run after
that is instant. A full year takes a while on the first pass because it walks day by day.

Outputs land in `outputs/`:

- `curtailment.png`, the fit and the monthly drift in one figure
- `findings.md`, a short note written from the actual numbers of that run
- `results.json`, the headline figures if you want to pull them somewhere else

Intermediate data lands in `data/processed`, including the half hourly panel per unit and
curtailment totals by unit.

## Tests

```bash
pytest tests -q
```

The profile tests check the volume arithmetic against cases worked out by hand, including
partial period acceptances and overlapping acceptances. The model tests plant a known
threshold in synthetic data and check the fit finds it. The end to end test runs the whole
pipeline on a made up panel so a change in one module cannot quietly break the chart or the
note.

## What it does not do

- It does not separate constraint driven bids from energy balancing bids. Using the SO flag
  on acceptances would get closer and is the first thing I would add.
- Physical notifications stand in for available wind. A unit already being bid off may
  notify lower later, which biases the estimate down.
- Scotland is treated as one node, so intra Scottish constraints are invisible.
- No bid prices, so it cannot tell you what the constraint cost or what a generator earned.
  Energy is valued at the day ahead price purely to give the volumes a sense of scale.

## Layout

```
src/elexon.py     API client with on disk caching
src/bmus.py       finds the Scottish wind BM Units
src/profiles.py   PN and BOALF to half hourly volumes
src/collect.py    pulls a date range and builds the panel
src/model.py      the hinge fit and the monthly refit
src/chart.py      the figure
src/run.py        orchestration and the findings note
```

## Data

Elexon Insights API, datasets PN, BOALF and MID plus the BM Unit reference list. No key
needed and no commercial data is used anywhere in this repo.

Aliyan Nawaz
