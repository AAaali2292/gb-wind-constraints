"""Work out which BM Units are Scottish transmission connected wind.

Rather than hardcoding a list of BMU ids that goes stale, this pulls the Elexon
reference list and filters on fuel type, unit type and GSP group. North Scotland
and South Scotland are the two groups sitting above the B6 boundary, which is
where the constraint we care about binds.
"""

import pandas as pd

from . import elexon

SCOTTISH_GSP_GROUPS = {"North Scotland", "South Scotland"}


def all_units(use_cache=True):
    data = elexon.rows("/reference/bmunits/all", use_cache=use_cache)
    df = pd.DataFrame(data)
    for col in ("generationCapacity", "demandCapacity"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def scottish_wind(min_capacity_mw=10.0, use_cache=True):
    """Transmission connected wind BMUs sitting in a Scottish GSP group.

    min_capacity_mw drops the handful of tiny embedded units that carry a T
    prefix but contribute nothing to the constraint picture.
    """
    df = all_units(use_cache=use_cache)

    mask = (
        (df["fuelType"] == "WIND")
        & (df["bmUnitType"] == "T")
        & (df["gspGroupName"].isin(SCOTTISH_GSP_GROUPS))
        & (df["generationCapacity"] >= min_capacity_mw)
    )

    cols = [
        "elexonBmUnit",
        "nationalGridBmUnit",
        "bmUnitName",
        "leadPartyName",
        "gspGroupName",
        "generationCapacity",
    ]
    out = df.loc[mask, cols].copy()
    out = out.sort_values("generationCapacity", ascending=False).reset_index(drop=True)
    return out


def summarise(units):
    by_group = units.groupby("gspGroupName")["generationCapacity"].agg(["count", "sum"])
    return by_group.rename(columns={"count": "units", "sum": "capacity_mw"})
