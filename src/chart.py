"""One figure. Left panel is the fit, right panel is how the fitted headroom moves."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

INK = "#1f3864"
ACCENT = "#c1121f"
GREY = "#6b6b6b"


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GREY)
    ax.tick_params(colors=GREY, labelsize=9)
    ax.grid(True, color="#e6e6e6", linewidth=0.8)
    ax.set_axisbelow(True)


def make_chart(series, fit, monthly, path, subtitle=""):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 5.2), gridspec_kw={"width_ratios": [1.25, 1]})

    x = series["pn_mw"].to_numpy(dtype=float)
    y = series["curtailed_mw"].to_numpy(dtype=float)

    hb = ax1.hexbin(x, y, gridsize=55, mincnt=1, cmap="Blues", bins="log", linewidths=0)
    cb = fig.colorbar(hb, ax=ax1, pad=0.02)
    cb.set_label("settlement periods (log scale)", fontsize=8, color=GREY)
    cb.ax.tick_params(labelsize=8, colors=GREY)

    grid = np.linspace(x.min(), x.max(), 200)
    ax1.plot(grid, fit.predict(grid), color=ACCENT, linewidth=2.2, label="fitted hinge")
    ax1.axvline(fit.theta_mw, color=ACCENT, linestyle=":", linewidth=1.4)
    ax1.annotate(
        f"implied headroom {fit.theta_mw:,.0f} MW",
        xy=(fit.theta_mw, ax1.get_ylim()[1] * 0.86),
        xytext=(8, 0),
        textcoords="offset points",
        fontsize=9,
        color=ACCENT,
    )

    ax1.set_xlabel("Scottish wind physical notification, MW", fontsize=10, color=GREY)
    ax1.set_ylabel("curtailed by bid acceptance, MW", fontsize=10, color=GREY)
    ax1.set_title(
        f"Curtailment starts once Scottish wind clears the boundary\n"
        f"beta {fit.beta:.2f}, R squared {fit.r_squared:.2f}, n {fit.n:,}",
        fontsize=11,
        color=INK,
        loc="left",
    )
    ax1.legend(frameon=False, fontsize=9, loc="upper left")
    _style(ax1)

    if not monthly.empty:
        months = monthly["month"].tolist()
        pos = np.arange(len(months))

        ax2.bar(pos, monthly["curtailed_gwh"], color="#cbd7ea", width=0.65, label="curtailed volume")
        ax2.set_ylabel("curtailed, GWh per month", fontsize=10, color=GREY)

        ax3 = ax2.twinx()
        theta = monthly["theta_mw"].to_numpy(dtype=float)
        ax3.plot(pos, theta, color=ACCENT, marker="o", markersize=4, linewidth=1.8, label="fitted headroom")
        ax3.set_ylabel("implied headroom, MW", fontsize=10, color=ACCENT)

        # do not let a trivial spread get autoscaled into a dramatic looking line
        spread = float(theta.max() - theta.min())
        centre = float(theta.mean())
        if centre > 0 and spread < 0.05 * centre:
            ax3.set_ylim(centre * 0.9, centre * 1.1)

        ax3.tick_params(colors=ACCENT, labelsize=9)
        for side in ("top", "left"):
            ax3.spines[side].set_visible(False)
        ax3.spines["right"].set_color(ACCENT)

        ax2.set_xticks(pos)
        ax2.set_xticklabels(months, rotation=45, ha="right", fontsize=8)
        ax2.set_title("Headroom is not a constant", fontsize=11, color=INK, loc="left")
        _style(ax2)
        ax2.grid(False)
    else:
        ax2.axis("off")

    if subtitle:
        fig.text(0.005, 0.005, subtitle, fontsize=8, color=GREY)

    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path
