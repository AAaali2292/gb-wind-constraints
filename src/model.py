"""A hinge model of Scottish wind curtailment.

The physical story is simple. Scotland can export a certain amount south. Below
that level nothing gets bid off. Above it, roughly a fixed share of the excess
gets bid off. So the shape to fit is

    curtailed_MW = beta * max(0, scottish_wind_MW - theta)

theta is the interesting number because it is an implied export headroom in MW
that you can read off market data without knowing anything about the network,
and it moves when circuits go out or when reinforcements land. beta says how
much of the excess lands on wind rather than on other actions.

The fit is a grid search on theta with ordinary least squares through the origin
for beta at each candidate, which is exact rather than iterative and takes no
time at this sample size.
"""

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd


@dataclass
class HingeFit:
    theta_mw: float
    beta: float
    r_squared: float
    n: int
    theta_low: float = float("nan")
    theta_high: float = float("nan")

    def predict(self, x):
        return self.beta * np.clip(np.asarray(x, dtype=float) - self.theta_mw, 0, None)

    def to_dict(self):
        return asdict(self)


def _beta_and_sse(x, y, theta):
    hinge = np.clip(x - theta, 0, None)
    denom = float(np.dot(hinge, hinge))
    if denom <= 0:
        return 0.0, float(np.dot(y, y))
    beta = float(np.dot(hinge, y) / denom)
    resid = y - beta * hinge
    return beta, float(np.dot(resid, resid))


def fit_hinge(x, y, grid_points=200):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    if len(x) < 50:
        raise ValueError(f"only {len(x)} usable observations, that is not enough to fit anything")

    lo, hi = np.quantile(x, 0.05), np.quantile(x, 0.95)
    grid = np.linspace(lo, hi, grid_points)

    best = None
    for theta in grid:
        beta, sse = _beta_and_sse(x, y, theta)
        if best is None or sse < best[2]:
            best = (theta, beta, sse)

    theta, beta, sse = best
    total = float(np.dot(y - y.mean(), y - y.mean()))
    r2 = 1.0 - sse / total if total > 0 else float("nan")

    return HingeFit(theta_mw=float(theta), beta=float(beta), r_squared=float(r2), n=int(len(x)))


def bootstrap_theta(x, y, draws=200, grid_points=120, seed=7):
    """Rough confidence interval on theta by resampling observations."""
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]

    thetas = []
    n = len(x)
    for _ in range(draws):
        idx = rng.integers(0, n, n)
        try:
            fit = fit_hinge(x[idx], y[idx], grid_points=grid_points)
        except ValueError:
            continue
        thetas.append(fit.theta_mw)

    if not thetas:
        return float("nan"), float("nan")
    return float(np.quantile(thetas, 0.05)), float(np.quantile(thetas, 0.95))


def fit_overall(series, x_col="pn_mw", y_col="curtailed_mw", with_bootstrap=True):
    fit = fit_hinge(series[x_col], series[y_col])
    if with_bootstrap:
        low, high = bootstrap_theta(series[x_col], series[y_col])
        fit.theta_low, fit.theta_high = low, high
    return fit


def fit_monthly(series, x_col="pn_mw", y_col="curtailed_mw", min_obs=300):
    """Refit month by month. If theta moves around, that is the network changing, not the wind."""
    frame = series.copy()
    frame["month"] = pd.to_datetime(frame["settlement_date"]).dt.to_period("M")

    records = []
    for month, chunk in frame.groupby("month"):
        if len(chunk) < min_obs:
            continue
        try:
            fit = fit_hinge(chunk[x_col], chunk[y_col])
        except ValueError:
            continue
        records.append(
            {
                "month": str(month),
                "theta_mw": fit.theta_mw,
                "beta": fit.beta,
                "r_squared": fit.r_squared,
                "n": fit.n,
                "curtailed_gwh": chunk["bid_mwh"].sum() / 1000.0,
            }
        )

    return pd.DataFrame(records)
