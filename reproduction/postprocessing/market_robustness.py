# Made by Francesco Maldonato on 10/11/2026
"""Price volatility and input correlations of the three market years (paper Table 5, Section IV-F, Section VI-E).

    python3 market_robustness.py            # runs/DRJ_MultiYear_v13_executed_logs -> results/

Per year (inputs of the runs folder): volatility of the day-ahead, intraday (ID-AEP) and imbalance (reBAP) prices: mean,
standard deviation, minimum, maximum, hours below 0, daily spreads (the daily 4-hour spread: mean of the 4 highest minus the
4 lowest hourly prices of the day), and the deviation of the intraday and imbalance price from the day-ahead price; the
Pearson correlations between prices, carbon intensity, solar and wind capacity factors, native load, residual load and EV
availability; and the V2G gain per EV of each year against the volatility of its market (needs ev_per_vehicle.csv of
ev_fleet_analysis.py).

Writes into results/: market_volatility.csv (Table 5), input_correlations.csv, input_correlations_key.csv and
volatility_vs_results.csv.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import EVS, RESULTS, YEARS, ev_files, ev_units, hourly, overview, runs_folder

PRICES = {"day-ahead": "market-dayahead-prices", "intraday": "market-intraday-prices", "imbalance": "market-imbalances-prices"}
KEY_PAIRS = [("day-ahead", "intraday"), ("day-ahead", "imbalance"), ("intraday", "imbalance"), ("day-ahead", "carbon intensity"),
             ("day-ahead", "solar CF"), ("day-ahead", "wind CF"), ("day-ahead", "residual load"), ("imbalance", "RES forecast error"),
             ("carbon intensity", "residual load"), ("EV availability", "residual load")]


def inputs(folder, year, spec):
    d = Path(folder) / "data_files" / str(year)
    n = len(pd.read_csv(d / f"market-dayahead-prices_1H_germany-{year}.csv", sep=";"))
    idx = pd.date_range(f"{year}-01-01", periods=n, freq="h")
    f = lambda name: hourly(folder, f"data_files/{year}/{name}", idx)
    df = pd.DataFrame({k: f(f"{v}_1H_germany-{year}.csv") for k, v in PRICES.items()})
    df["carbon intensity"] = f(f"carbon-intensity-gCO2eq-1H_germany-{year}.csv")
    df["solar CF"] = f(f"solar-profile-ac_1H_germany-{year}.csv")
    df["wind CF"] = f(f"wind-profile-ac_1H_germany-{year}.csv")
    load = spec["households MWh"] * f("stromnetz-noise_households_normalized_demand_1h_MW.csv") + \
        spec["business MWh"] * f("stromnetz-noise_general_business_normalized_demand_1h_MW.csv")
    res = spec["solar MW"] * df["solar CF"] + spec["wind MW"] * df["wind CF"]
    df["native load"] = load
    df["residual load"] = load - res
    df["RES forecast error"] = res - (spec["solar MW"] * f(f"solar-profile-da_1H_germany-{year}.csv") + spec["wind MW"] * f(f"wind-profile-da_1H_germany-{year}.csv"))
    share = pd.read_csv(ev_files(folder, year)[0], sep=";")
    units = ev_units(spec)
    df["EV availability"] = sum(units[ev] * share[f"{ev}~CS1"].to_numpy(float) / 100 for ev in EVS) / sum(units.values())
    real = (df[list(PRICES)].abs() > 1e-6).all(axis=1)  # the two DST placeholder hours of the 2025 files
    return df[real]


def volatility(p):
    day = p.groupby(p.index.date)
    top4 = day.apply(lambda s: s.nlargest(4).mean() - s.nsmallest(4).mean())
    return {"mean [EUR/MWh]": p.mean(), "std [EUR/MWh]": p.std(), "CV [-]": p.std() / p.mean(), "min [EUR/MWh]": p.min(),
            "max [EUR/MWh]": p.max(), "hours < 0": int((p < 0).sum()), "hours > 200": int((p > 200).sum()), "hours > 500": int((p > 500).sum()),
            "mean daily max-min spread [EUR/MWh]": (day.max() - day.min()).mean(), "P90 daily max-min spread [EUR/MWh]": (day.max() - day.min()).quantile(0.9),
            "mean daily 4-h spread [EUR/MWh]": top4.mean(), "std of within-day deviation [EUR/MWh]": (p - day.transform("mean")).std()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="DRJ_MultiYear_v13_executed_logs")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    folder = runs_folder(a.folder)
    out = Path(a.out) if a.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    ov = overview(folder)
    vol, corr_rows, key_rows, data = [], [], [], {}
    for y in YEARS:
        df = inputs(folder, y, ov[f"{y}_A2"])
        data[y] = df
        for k in PRICES:
            vol.append({"year": y, "price": k, **volatility(df[k])})
        for k in ["intraday", "imbalance"]:
            dev = df[k] - df["day-ahead"]
            vol.append({"year": y, "price": f"{k} - day-ahead", "mean [EUR/MWh]": dev.mean(), "std [EUR/MWh]": dev.std(),
                        "min [EUR/MWh]": dev.min(), "max [EUR/MWh]": dev.max(), "hours |dev| > 100": int((dev.abs() > 100).sum())})
        c = df.corr()
        c.insert(0, "year", y)
        corr_rows.append(c)
        for p1, p2 in KEY_PAIRS:
            key_rows.append({"year": y, "pair": f"{p1} / {p2}", "Pearson r": df[p1].corr(df[p2]),
                             "Spearman rho": df[p1].rank().corr(df[p2].rank())})  # rank correlation without scipy
    vol = pd.DataFrame(vol)
    vol.to_csv(out / "market_volatility.csv", sep=";", index=False, float_format="%.3f")
    pd.concat(corr_rows).to_csv(out / "input_correlations.csv", sep=";", float_format="%.3f")
    key = pd.DataFrame(key_rows)
    key_w = key.pivot(index="pair", columns="year", values="Pearson r")
    key_w["range"] = key_w.max(axis=1) - key_w.min(axis=1)
    key.to_csv(out / "input_correlations_key.csv", sep=";", index=False, float_format="%.3f")

    # results of the runs against the volatility of their year
    res_rows = []
    ev = out / "ev_per_vehicle.csv"
    evd = pd.read_csv(ev, sep=";") if ev.exists() else None
    for y in YEARS:
        row = {"year": y}
        for k in PRICES:
            v = vol[(vol.year == y) & (vol.price == k)].iloc[0]
            row[f"{k} mean daily 4-h spread [EUR/MWh]"] = v["mean daily 4-h spread [EUR/MWh]"]
            row[f"{k} std [EUR/MWh]"] = v["std [EUR/MWh]"]
        if evd is not None:
            for s in "BC":
                sub = evd[(evd.year == y) & (evd.model.str.endswith(f"{s}1"))]
                row[f"{s}: gain vs V1G [EUR/EV]"] = np.average(sub["gain vs V1G [EUR/EV]"], weights=sub.units)
                row[f"{s}: V2G per EV [kWh]"] = np.average(sub["V2G, grid side [kWh]"], weights=sub.units)
        res_rows.append(row)
    resv = pd.DataFrame(res_rows)
    resv.to_csv(out / "volatility_vs_results.csv", sep=";", index=False, float_format="%.3f")
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        print(vol.round(1).to_string(index=False))
        print(key_w.round(2).to_string())
        print(resv.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
