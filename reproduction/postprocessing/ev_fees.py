# Made by Francesco Maldonato on 10/11/2026
"""The fees that the EVs pay through their nodal prices, and what the German network-charge rules for feed-in and for
bidirectional charging points would be worth to them (paper: fees section and discussion).

    python3 ev_fees.py            # runs/DRJ_MultiYear_v13_executed_logs -> results/

How PLEXOS prices the EVs: every line of the community's star network (each node -> DEMS -> grid connection) carries a
wheeling charge of 20 EUR/MWh in both directions; purchases on a market pay its price + 2 EUR/MWh (price increment 1 +
half of the bid-ask spread 2), sales receive the price. The EVs are billed at the nodal price of the charging-station node
+ UoS (20 EUR/MWh) when charging and - UoS when discharging ("Charge Cost", "Discharge Revenue"). That nodal price carries
the wheeling of every line between the station and the marginal source or sink:
- the community imports (DEMS-Transmission flow < 0): charging costs market + 2 + 20 + 20 + 20 = market + 62;
- the community exports (flow > 0): V2G discharge earns market - 20 - 20 - 20 = market - 60;
- in between, a local resource is marginal and the price lies inside that band.
Per X.1 run (the X.2 runs replay the same EV schedule) and per EV and year:
- UoS fee: 20 EUR/MWh x (charged + discharged energy);
- network charges: 20 EUR/MWh on the charging-station line for every MWh charged or discharged, and 20 EUR/MWh on the
  grid-connection line for every MWh charged while the community imports or discharged while it exports;
- trading hurdle: 2 EUR/MWh on the energy charged while the community imports;
- ex-post value of the German rules (no re-optimization): feed-in pays no network charge (Sec. 15(1) StromNEV), and since
  December 2025 Sec. 118(6) EnWG exempts the energy that a bidirectional charging point draws as far as it is fed back.
  Value = network charges on the discharged energy + discharged energy x the mean network charge per MWh charged.
- check: the measured charge and discharge prices against the market price in import and export hours.
Writes results/ev_fees.csv (per run and the three-year mean of each scenario).
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import EVS, UOS, YEARS, Run, ev_units, hourly, overview, runs_folder, RESULTS

WHEEL = 20.0  # EUR/MWh per line and direction
HURDLE = 2.0  # EUR/MWh on market purchases
EPS = 1e-6


def analyse(folder, model, spec):
    r = Run(folder, model)
    ch = sum(r("Vehicle", ev, "Charging", None).fillna(0) for ev in EVS) / 1000  # kW -> MWh per hour
    idx = ch.index
    dis = sum(r("Vehicle", ev, "Discharging", pd.Series(0.0, index=idx)).reindex(idx).fillna(0) for ev in EVS) / 1000
    tx = r("Line", "DEMS-Transmission", "Flow", pd.Series(0.0, index=idx)).reindex(idx).fillna(0)
    cost = r("Charging Station", "CS1", "Charge Cost", pd.Series(0.0, index=idx)).reindex(idx).fillna(0)
    rev = r("Charging Station", "CS1", "Discharge Revenue", pd.Series(0.0, index=idx)).reindex(idx).fillna(0)
    p = hourly(folder, spec["ID price file" if model.endswith("C1") else "DA price file"], idx)
    imp, exp = tx < -EPS, tx > EPS
    n = sum(ev_units(spec).values())
    net_ch = WHEEL * ch.sum() + WHEEL * ch[imp].sum()
    net_dis = WHEEL * dis.sum() + WHEEL * dis[exp].sum()
    w_ch = net_ch / ch.sum()
    c_imp, d_exp = (ch > EPS) & imp, (dis > EPS) & exp
    return {"model": model, "scenario": model.split("_")[1][0], "EVs": n,
            "charged [MWh/EV]": ch.sum() / n, "discharged [MWh/EV]": dis.sum() / n,
            "charged in import hours [%]": 100 * ch[imp].sum() / ch.sum(),
            "discharged in export hours [%]": 100 * dis[exp].sum() / dis.sum() if dis.sum() else np.nan,
            "UoS [EUR/EV]": UOS * (ch.sum() + dis.sum()) / n,
            "network charges [EUR/EV]": (net_ch + net_dis) / n,
            "UoS + network [EUR/EV]": (UOS * (ch.sum() + dis.sum()) + net_ch + net_dis) / n,
            "trading hurdle [EUR/EV]": HURDLE * ch[imp].sum() / n,
            "network on feed-in [EUR/EV]": net_dis / n,
            "network on charged energy fed back [EUR/EV]": dis.sum() * w_ch / n,
            "German rules value [EUR/EV]": (net_dis + dis.sum() * w_ch) / n,
            "check: charge price - market, import hours [EUR/MWh]": (cost[c_imp] / ch[c_imp] - p[c_imp]).median(),
            "check: discharge price - market, export hours [EUR/MWh]": (rev[d_exp] / dis[d_exp] - p[d_exp]).median() if d_exp.any() else np.nan}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="DRJ_MultiYear_v13_executed_logs")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    folder = runs_folder(a.folder)
    out = Path(a.out) if a.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    ov = overview(folder)
    rows = [analyse(folder, f"{y}_{s}1", ov[f"{y}_{s}1"]) for y in YEARS for s in "ABC" if Run(folder, f"{y}_{s}1").exists()]
    df = pd.DataFrame(rows)
    mean = df.groupby("scenario").mean(numeric_only=True).reset_index().assign(model=lambda d: d.scenario + " mean 2023-2025")
    df = pd.concat([df, mean], ignore_index=True)
    df.to_csv(out / "ev_fees.csv", sep=";", index=False, float_format="%.3f")
    pd.set_option("display.width", 250)
    print(df.set_index("model").drop(columns=["scenario", "EVs"]).round(1).T.to_string())


if __name__ == "__main__":
    main()
