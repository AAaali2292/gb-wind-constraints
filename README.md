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

## Picking the units

The obvious approach is to filter the reference list to Scottish wind farms. That does not
work: the only location field is the GSP group, which is a distribution concept and comes
back empty for transmission connected units. Hardcoding a list of BMU ids works right up
until a unit connects or changes hands.

So the universe is defined by behaviour instead. Take every transmission connected wind unit,
read the acceptance feed, and keep the ones the system operator actually bids off with the SO
flag set, which is the flag on actions taken for system reasons rather than energy balancing.
What comes back is the Scottish fleet, which is the point, and it stays current on its own.

The honest cost of this is that units are selected partly because of the outcome being
measured. It is the right universe for the question but it is not a neutral sample, and the
generated note says so.

## Running it

```bash
pip install -r requirements.txt
python -m src.run --start 2025-08-01 --end 2026-07-31
```

Every API response is cached under `data/raw`, so the first run is slow and every run after
that is instant. A full year takes a while on the first pass because it makes one request per unit per day. Four months is a sensible first run.

Outputs land in `outputs/`:

- `curtailment.png`, the fit and the monthly drift in one figure
- `findings.md`, a short note written from the actual numbers of that run
- `results.json`, the headline figures if you want to pull them somewhere else

Intermediate data lands in `data/processed`, including the half hourly panel per unit and
curtailment totals by unit.

## A trap worth knowing about

The physical notification endpoint documents `bmUnit` as a repeatable parameter. It is not.
The request gets redirected, the duplicates are dropped along the way, and you get a 200 back
containing only the first unit you asked for. Nothing errors.

That is a bad failure mode here, because acceptances still arrive for every unit. Units with
no notification then look like they produced nothing while being curtailed, so curtailment
comes out at 62 per cent of notified output with a beta of 1.65, which is arithmetically
impossible. The first version of this repo did exactly that.

There are now three defences: one request per unit, units with no notifications at all get
dropped loudly, and `sanity_check` refuses to let impossible results through without a
warning. `tests/test_sanity.py` pins the exact broken numbers so it cannot come back.

## Tests

```bash
pytest tests -q
```

The profile tests check the volume arithmetic against cases worked out by hand, including
partial period acceptances and overlapping acceptances. The model tests plant a known
threshold in synthetic data and check the fit finds it. The end to end test runs the whole
pipeline on a made up panel so a change in one module cannot quietly break the chart or the
note. The sanity tests pin the exact numbers the broken version produced, so that failure
cannot come back unnoticed.

## What it does not do

- The SO flag decides which units are in the universe, but once a unit is in, every bid it
  takes counts as curtailment, including energy balancing bids. Filtering acceptance by
  acceptance rather than unit by unit is the first thing I would add.
- Units are selected because they were curtailed, so the fleet is defined partly by the
  outcome being measured. Right universe for the question, not a neutral sample.
- Physical notifications stand in for available wind. A unit already being bid off may
  notify lower later, which biases the estimate down.
- Scotland is treated as one node, so intra Scottish constraints are invisible.
- No bid prices, so it cannot tell you what the constraint cost or what a generator earned.
  Energy is valued at the day ahead price purely to give the volumes a sense of scale.

## Layout

```
src/elexon.py     API client with on disk caching
src/bmus.py       the transmission connected wind universe
src/profiles.py   PN and BOALF to half hourly volumes
src/collect.py    finds the constrained units, pulls a date range, builds the panel
src/model.py      the hinge fit and the monthly refit
src/chart.py      the figure
src/run.py        orchestration and the findings note
```

## Data

Elexon Insights API, datasets PN, BOALF and MID plus the BM Unit reference list. No key
needed and no commercial data is used anywhere in this repo.

Aliyan Nawaz
