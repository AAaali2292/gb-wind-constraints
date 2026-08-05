"""Work out which BM Units are transmission connected wind.

The obvious way to find the Scottish ones would be the GSP group field, but that
is a distribution concept and comes back empty for transmission connected units,
so it is no use here. Hardcoding a list of BMU ids works until a unit connects or
changes hands.

So this module only does the easy half, which is finding every transmission
connected wind unit. Deciding which of them sit behind the constraint is done in
collect.discover_constrained_units, from the acceptances themselves.
"""

import pandas as pd

from . import elexon


def all_units(use_cache=True):
    data = elexon.rows("/reference/bmunits/all", use_cache=use_cache)
    df = pd.DataFrame(data)
    for col in ("generationCapacity", "demandCapacity"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


COLUMNS = [
    "elexonBmUnit",
    "nationalGridBmUnit",
    "bmUnitName",
    "leadPartyName",
    "gspGroupName",
    "generationCapacity",
]


def wind_units(min_capacity_mw=10.0, use_cache=True):
    """Every transmission connected wind BM Unit above a size floor.

    min_capacity_mw drops the handful of very small units that carry a T prefix
    but contribute nothing to the constraint picture.
    """
    df = all_units(use_cache=use_cache)

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(f"the reference feed no longer has {missing}, check the API")

    mask = (
        (df["fuelType"] == "WIND")
        & (df["bmUnitType"] == "T")
        & (df["generationCapacity"] >= min_capacity_mw)
    )

    out = df.loc[mask, COLUMNS].copy()
    return out.sort_values("generationCapacity", ascending=False).reset_index(drop=True)
