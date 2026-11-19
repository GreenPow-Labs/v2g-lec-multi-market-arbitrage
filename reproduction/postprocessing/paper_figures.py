# Made by Francesco Maldonato on 10/11/2026
"""Figures 6 to 9 of the paper, from the outputs of the other post-processing scripts and the runs folder.

    python3 paper_figures.py            # runs/DRJ_MultiYear_v13_executed_logs -> results/

- cost_by_year:   community energy cost of the settled schedules (A.2, B.2, C.2) per year, grouped by year, with the 95 %
                  interval of the day-block bootstrap (forecast_bootstrap_summary.csv; forecast_uncertainty.py).
- market_spreads: daily 4-hour spread of the day-ahead, intraday (ID-AEP) and imbalance prices per year (boxes: quartiles,
                  whiskers: 5-95 %), from the price files of the runs.
- sweeps:         the four one-factor sweeps of 2025 (C.2), EV fleet, RES capacity, load with RES and fleet mix, each KPI
                  against the level in % of the base case (fleet mix: share of residents' EVs relative to the base 65 %).
                  The axis is linear up to 200 % and compressed beyond (only the 400-EV level lies there).
- user_types:     annual gain of an EV against V1G (net charging cost, UoS fee included) against its connected share, per user type
                  (ev_user_types.csv; ev_user_types.py): C (filled) and B (open), mean of 2023-2025 with the
                  range of the years, and the groups and the fleet.
All one IEEE column wide except sweeps (page width).
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import GRID, INK, MUTED, PALETTE, RESULTS, YEARS, Run, hourly, overview, paper_style, runs_folder

SCEN = {"A": "A: V1G, day-ahead", "B": "B: V2G, day-ahead", "C": "C: V2G, day-ahead + intraday"}
COHORT = {"RC": ("residents, commuter", PALETTE[0]), "RO": ("residents, other use", PALETTE[1]),
          "WF": ("employees, full day", PALETTE[2]), "WP": ("employees, part day", PALETTE[3])}


def style(plt):
    plt.rcParams.update({"font.size": 6.5, "axes.titlesize": 6.5, "axes.labelsize": 6.5, "xtick.labelsize": 6, "ytick.labelsize": 6,
                         "legend.fontsize": 5.8, "axes.linewidth": 0.5, "xtick.major.width": 0.5, "ytick.major.width": 0.5,
                         "xtick.major.size": 2, "ytick.major.size": 2, "axes.titlepad": 3, "axes.labelpad": 1.5})


LEG = dict(frameon=False, handlelength=1.4, handletextpad=0.4, borderaxespad=0.2, labelspacing=0.25, columnspacing=0.9)


def cost_by_year(res):
    plt = paper_style()
    style(plt)
    my = pd.read_csv(res / "KPI_multiyear.csv", sep=";", index_col=0, header=[0, 1])
    row = next(i for i in my.index if i.strip().startswith("Community energy cost"))
    bs = pd.read_csv(res / "forecast_bootstrap_summary.csv", sep=";")
    bs = bs[bs.KPI == "community energy cost [EUR/MWh]"]
    fig, ax = plt.subplots(figsize=(3.5, 1.95))
    fig.subplots_adjust(left=0.12, right=0.99, top=0.84, bottom=0.12)
    for g, y in enumerate(YEARS):
        if g % 2 == 0:
            ax.axvspan(g * 4 - 0.6, g * 4 + 2.6, color=GRID, alpha=0.45, lw=0, zorder=0)
        for i, s in enumerate("ABC"):
            v = float(my.loc[row, (f"{s}.2", str(y))])
            b = bs[(bs.year == y) & (bs.scenario == f"{s}.2")].iloc[0]
            x = g * 4 + i
            ax.bar(x, v, width=0.8, color=PALETTE[i], label=SCEN[s] if g == 0 else None, zorder=2)
            ax.errorbar(x, v, yerr=[[v - b["bootstrap 2.5 %"]], [b["bootstrap 97.5 %"] - v]], fmt="none", ecolor=INK, elinewidth=0.6,
                        capsize=1.5, zorder=3)
            ax.text(x, b["bootstrap 97.5 %"] + 2.5, f"{v:.0f}".replace("-", "−"), ha="center", va="bottom", fontsize=5.4, color=MUTED)
        ax.text(g * 4 + 1, -66, str(y), ha="center", va="top", fontsize=6.5, color=INK, weight="bold")
    ax.axhline(0, color=MUTED, lw=0.5)
    ax.set_xticks([g * 4 + i for g in range(3) for i in range(3)], ["A", "B", "C"] * 3)
    ax.tick_params(axis="x", length=0, pad=1.5)
    ax.set_xlim(-0.7, 10.7)
    ax.set_ylim(-55, 112)
    ax.set_ylabel("Community energy cost [€/MWh]")
    ax.legend(ncol=3, loc="lower center", bbox_to_anchor=(0.45, 1.0), **{**LEG, "columnspacing": 0.7})
    ax.grid(axis="y", color=GRID, lw=0.4)
    ax.set_axisbelow(True)
    fig.savefig(res / "cost_by_year.pdf", dpi=300, metadata={"CreationDate": None})  # no time stamp
    plt.close(fig)


def market_spreads(folder, res):
    plt = paper_style()
    style(plt)
    ov = overview(folder)
    keys = [("DA price file", "day-ahead"), ("ID price file", "intraday (ID-AEP)"), ("imbalance price file", "imbalance")]
    fig, ax = plt.subplots(figsize=(3.5, 1.85))
    fig.subplots_adjust(left=0.13, right=0.99, top=0.97, bottom=0.12)
    for j, (k, lab) in enumerate(keys):
        for i, y in enumerate(YEARS):
            m = f"{y}_C1"
            idx = Run(folder, m)("Generator", "Solar G1", "Generation").index
            p = hourly(folder, ov[m][k], idx)
            spread = p.groupby(p.index.date).apply(lambda s: s.nlargest(4).mean() - s.nsmallest(4).mean())
            b = ax.boxplot([spread.to_numpy()], positions=[j * 4 + i], widths=0.75, patch_artist=True, showfliers=False, whis=(5, 95),
                           medianprops=dict(color=INK, lw=0.8), whiskerprops=dict(lw=0.6, color=MUTED), capprops=dict(lw=0.6, color=MUTED),
                           boxprops=dict(lw=0.5))
            b["boxes"][0].set(facecolor=PALETTE[i], alpha=0.75, edgecolor=PALETTE[i])
    ax.set_xticks([j * 4 + 1 for j in range(3)], [lab for _, lab in keys])
    ax.tick_params(axis="x", length=0)
    ax.set_yscale("log")
    ax.set_yticks([30, 100, 300, 1000], ["30", "100", "300", "1000"])
    ax.set_ylim(20, 1300)
    ax.set_ylabel("Daily 4-h spread [€/MWh]")
    handles = [plt.Rectangle((0, 0), 1, 1, color=PALETTE[i], alpha=0.75) for i in range(3)]
    ax.legend(handles, YEARS, loc="upper left", ncol=3, **LEG)
    ax.grid(axis="y", color=GRID, lw=0.4)
    ax.set_axisbelow(True)
    fig.savefig(res / "market_spreads.pdf", dpi=300, metadata={"CreationDate": None})  # no time stamp
    plt.close(fig)


def sweeps(res):
    plt = paper_style()
    style(plt)
    d = pd.read_csv(res / "KPI_sweeps.csv", sep=";", header=[0, 1], index_col=0)
    groups = [("EV fleet [EVs]", 100.0, "EV fleet (base 100 EVs)", "o"),
              ("RES capacity [% penetration]", 80.0, "RES capacity (base 80 % penetration)", "s"),
              ("Load with RES [% of base load]", 100.0, "load with RES (base 100 %)", "^"),
              ("Fleet mix [% residents]", 65.0, "residents' EVs (base 65 % of the 100 EVs)", "D")]
    kpis = [("Community energy cost, cash-flow [EUR/MWh]", "Community energy cost [€/MWh]", 1),
            ("Net market profit [EUR]", "Net market profit [k€]", 1e-3), ("Total wheeling cost [EUR]", "Total wheeling cost [k€]", 1e-3),
            ("CS operator UoS [EUR]", "Charging station UoS [k€]", 1e-3), ("EVs av. net charging cost [EUR/EV]", "EV net charging cost [€/EV/a]", 1),
            ("Fleet utilization [EFC per EV]", "Fleet utilization [cycles]", 1), ("Net grid import, imported - exported [MWh]", "Net grid import [MWh]", 1),
            ("Net attributed CO2eq balance [tCO2eq]", "Net CO$_2$eq balance [tCO$_2$eq]", 1)]
    cut, squeeze = 200.0, 0.2  # linear to 200 %, compressed beyond (400 % sits at 240)
    f = lambda x: np.where(np.asarray(x) <= cut, x, cut + (np.asarray(x) - cut) * squeeze)
    fig, axes = plt.subplots(2, 4, figsize=(7.16, 3.3), sharex=True)
    fig.subplots_adjust(left=0.06, right=0.99, top=0.86, bottom=0.12, wspace=0.42, hspace=0.36)
    colors = [PALETTE[0], PALETTE[1], PALETTE[2], PALETTE[3]]
    for ax, (row, title, scale) in zip(axes.flat, kpis):
        for (g, base, lab, mk), c in zip(groups, colors):
            lv = [l for (s, l) in d.columns if s == g]
            x = np.array([float(l) for l in lv]) / base * 100
            y = np.array([float(d.loc[row, (g, l)]) for l in lv]) * scale
            order = np.argsort(x)
            x, y = x[order], y[order]
            inside = x <= cut
            ax.plot(f(x[inside]), y[inside], color=c, lw=1.0, marker=mk, ms=2.6, label=lab, zorder=3)
            if (~inside).any():  # the compressed stretch: dashed
                k = np.where(inside)[0][-1]
                ax.plot(f(x[k:]), y[k:], color=c, lw=0.9, ls="--", marker=mk, ms=2.6, zorder=3)
        ax.axvline(100, color=MUTED, lw=0.5, ls=":", zorder=1)
        ax.axhline(0, color=GRID, lw=0.6, zorder=0)
        ax.set_title(title, loc="left")
        ax.grid(axis="y", color=GRID, lw=0.4)
        ax.set_axisbelow(True)
        ax.set_xlim(-8, f(400) + 8)
        ax.set_xticks(list(f([0, 50, 100, 150, 200, 400])), ["0", "50", "100", "150", "200", "400"])
        for xb in [cut + 18]:  # axis break marks
            ax.plot([xb - 2, xb + 2], [-0.02, 0.02], transform=ax.get_xaxis_transform(), color=MUTED, lw=0.7, clip_on=False)
            ax.plot([xb + 1, xb + 5], [-0.02, 0.02], transform=ax.get_xaxis_transform(), color=MUTED, lw=0.7, clip_on=False)
    for ax in axes[1]:
        ax.set_xlabel("Level [% of base case]")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.0), **LEG)
    fig.savefig(res / "sweeps.pdf", dpi=300, metadata={"CreationDate": None})  # no time stamp
    plt.close(fig)


def user_types(res):
    plt = paper_style()
    style(plt)
    u = pd.read_csv(res / "ev_user_types.csv", sep=";")
    yrs = u[u.year.astype(str).isin([str(y) for y in YEARS])]
    fig, ax = plt.subplots(figsize=(3.5, 2.15))
    fig.subplots_adjust(left=0.13, right=0.98, top=0.97, bottom=0.17)
    xs, ys = [], []
    for t, (lab, c) in COHORT.items():
        for s, filled in [("C", True), ("B", False)]:
            sub = yrs[(yrs["user type"] == t) & (yrs.scenario == s)]
            x = sub["connected [%]"].mean()
            g = sub["gain vs V1G [EUR/EV]"]
            ax.plot([x, x], [g.min(), g.max()], color=c, lw=0.8, alpha=0.9 if filled else 0.5)
            ax.plot(x, g.mean(), "o", ms=4, color=c, mfc=c if filled else "white", mew=0.9)
            if filled:
                xs.append(x), ys.append(g.mean())
                ax.text(x + 1.8, g.mean(), t, fontsize=5.8, color=MUTED, va="center")
    for grp, mk in [("residents", "D"), ("employees", "D"), ("fleet", "s")]:
        sub = yrs[(yrs["user type"] == grp) & (yrs.scenario == "C")]
        ax.plot(sub["connected [%]"].mean(), sub["gain vs V1G [EUR/EV]"].mean(), mk, ms=3.6, color=INK, zorder=4)
        x0, y0 = sub["connected [%]"].mean(), sub["gain vs V1G [EUR/EV]"].mean()
        if grp == "employees":
            ax.text(x0 + 5, y0 - 32, grp, fontsize=5.6, color=INK, ha="left")
        else:
            ax.text(x0 - 1.8, y0 + 18, grp, fontsize=5.6, color=INK, ha="right")
    k = np.polyfit(xs, ys, 1)
    xx = np.array([0, 100])
    ax.plot(xx, np.polyval(k, xx), color=MUTED, lw=0.6, ls="--", zorder=1)
    ax.axhline(0, color=MUTED, lw=0.5)
    ax.set_xlim(0, 100)
    ax.set_ylim(-60, 880)
    ax.set_xlabel("Connected to the LEC's charging points [% of the hours]")
    ax.set_ylabel("Gain vs V1G incl. fees [€/EV/a]")
    ax.grid(color=GRID, lw=0.4)
    ax.set_axisbelow(True)
    ax.text(3, 840, "filled: C (V2G DA+ID)   open: B (V2G DA)\nlines: range 2023–2025", fontsize=5.6, color=MUTED, va="top")
    fig.savefig(res / "user_types_gain.pdf", dpi=300, metadata={"CreationDate": None})  # no time stamp
    plt.close(fig)
    return k


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="DRJ_MultiYear_v13_executed_logs")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    folder = runs_folder(a.folder)
    res = Path(a.out) if a.out else RESULTS
    cost_by_year(res)
    market_spreads(folder, res)
    sweeps(res)
    k = user_types(res)
    print(f"user types: gain in C = {k[0]:.2f} EUR/EV per %-point of connected share + {k[1]:.0f} EUR/EV")


if __name__ == "__main__":
    main()
