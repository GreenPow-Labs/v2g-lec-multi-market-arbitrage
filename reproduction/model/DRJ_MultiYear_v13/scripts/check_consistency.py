# Made by Francesco Maldonato on 10/11/2026
"""Do the PLEXOS solution time series of every run make physical and economic sense?

    python3 check_consistency.py                      # runs next to the XML (models of run_order.csv)
    python3 check_consistency.py --folder <path>      # another runs folder (e.g. the Zenodo runs): its runs and inputs
    python3 check_consistency.py --csv out.csv        # also write the per-model table

Replays every run hour by hour from its own outputs (the REPORT set of make_multiyear_model.py) and its
input files (data_files/<year>/):
- inputs: RES generation = profile x capacity (forecast profile in X.1, actual in X.2), native load
  (region load - battery and EV charging) = normalised profiles x annual energies, market cash flow =
  sales x input price - purchases x (input price + 2) (PLEXOS Price Incr 1 and bid-ask spread 2);
- energy balance of the community: RES + battery and EV discharge + purchases = native load + battery
  and EV charge + sales, and the grid line carries the net market sales;
- battery: SoC(t) = SoC(t-1) + (eta Load - Generation / eta) / Capacity, within its SoC limits
  (1-100 % in optimisation runs), flows within 0.4 MW, no charge and discharge in one hour;
- EVs: E(t) = E(t-1) + eta charge - discharge / eta - km x Wh/km x units, within 10-90 % of the
  fleet capacity in optimisation runs, charge and discharge within rate x units x connected share,
  no V2G in V1G runs, charging-station limits;
- markets: no purchase and sale of one market in the same hour;
- end of the horizon: battery and fleet energy against their initial 25 %.
Every model's sizes, EV and battery parameters (efficiencies, units of each EV object) and price files come from
model_overview.csv (written by check_model.py), so the sweep levels are replayed with their own parameters; the EV files
are EV_FILES. Absent cohorts (0 Units, fleet-mix ends) have no solution files and are skipped; settlement runs are checked
at their solver's feasibility tolerance (TOL_SETTLEMENT, 1e-5 MW).
Exit code 1 if a check fails. Tolerances: 1e-6 MW / MWh (1e-4 EUR per hour for cash flows), 1e-5 kWh and kW for the EVs.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from make_multiyear_model import EV_FILES, EVS, LEVELS, LOAD_FILES, LOAD_SUFFIX

FOLDER = Path(__file__).resolve().parent.parent
BESS = dict(capacity=0.4, rate=0.4, soc0=25.0, soc_min=1.0)  # base values; MWh, MW, %, %
EV = dict(capacity=82.0, charge=11.0, discharge=10.0, soc0=25.0, soc_min=10.0, soc_max=90.0)  # base values; kWh, kW, kW, %
WH_KM = [169, 173, 183, 169]
CS_KW = (1100.0, 1000.0)  # CS1 charge / discharge limit for 100 EVs (base)
SOLAR_MW, WIND_MW, HOUSEHOLD_MWH, BUSINESS_MWH = 0.5, 0.2, 350.0, 150.0
TOL = 1e-6
TOL_SETTLEMENT = 1e-5  # the settlement solver's Feasibility Tolerance (SETTLEMENT_PERFORMANCE), MW
MARKETS = {1: "Day-Ahead energy price", 2: "Imbalance price", 3: "Intraday energy price"}
PRICE_FILES = {1: "market-dayahead-prices", 2: "market-imbalances-prices", 3: "market-intraday-prices"}
PRICE_COLUMNS = {1: "DA price file", 2: "imbalance price file", 3: "ID price file"}  # model_overview.csv
_overview = {}


def params(model):
    """The model's row of model_overview.csv as numbers where possible (sizes, EV and battery parameters, price files)."""
    if not _overview:
        for r in csv.DictReader(open(FOLDER / "model_overview.csv"), delimiter=";"):
            _overview[r["model"]] = {k: (float(v) if re.fullmatch(r"-?[\d.]+(e-?\d+)?", v or "") else v) for k, v in r.items()}
    p = dict(_overview[model])
    p["eta"] = p["EV efficiency %"] / 100
    p["eta battery"] = p["battery efficiency %"] / 100
    p["units"] = tuple(p[f"EV{i} units"] for i in range(1, 5))
    p["CS discharge kW"] = p["CS1 kW"] / p["EV charge kW"] * p["EV discharge kW"]  # the station = EVs x the EV rating
    return p


def prices(model, index):
    """{market number: hourly input price} of a model, from the files it reads (model_overview.csv)."""
    p = params(model)
    out = {}
    for k, col in PRICE_COLUMNS.items():
        s = pd.read_csv(FOLDER / p[col], sep=";")
        year = int(s.Year.iloc[0])
        out[k] = pd.Series(s.iloc[:, -1].to_numpy(float), index=pd.date_range(f"{year}-01-01", periods=len(s), freq="h")).reindex(index)
    return out


class Run:
    def __init__(self, folder, model):
        self.model, self.dir = model, folder / f"Model {model} Solution"
        self.ids = {}
        for r in csv.DictReader(open(self.dir / "id2name.csv"), delimiter=";"):
            self.ids[(r["class"], r["name"])] = r["id"]

    def __call__(self, cls, name, prop):
        f = self.dir / "Interval" / f"ST {cls}({self.ids.get((cls, name))}).{prop}.csv"
        if not f.exists():
            return None
        df = pd.read_csv(f, sep=";")
        return pd.Series(df.VALUE.to_numpy(), index=pd.to_datetime(df.DATETIME, format="%d/%m/%Y %H:%M"))


def inputs(year):
    """Hourly input profiles of a year (index = hours of the year)."""
    d = FOLDER / "data_files" / str(year)
    read = lambda f, col=-1: pd.read_csv(d / f, sep=";").iloc[:, col]
    n = len(read(f"{PRICE_FILES[1]}_1H_germany-{year}.csv"))
    idx = pd.date_range(f"{year}-01-01", periods=n, freq="h")
    out = {k: read(f"{f}_1H_germany-{year}.csv").set_axis(idx) for k, f in PRICE_FILES.items()}
    for kind, tag in [("forecast", "da"), ("actual", "ac")]:
        out[f"solar {kind}"] = read(f"solar-profile-{tag}_1H_germany-{year}.csv").set_axis(idx)
        out[f"wind {kind}"] = read(f"wind-profile-{tag}_1H_germany-{year}.csv").set_axis(idx)
    for kind, prefix in [("forecast", "Forecasted-"), ("actual", "Actual-")]:  # Stromnetz SLP / SLP with noise
        for key, obj in [("households", "Households"), ("business", "General Business")]:
            out[f"{key} {kind}"] = read(LOAD_FILES[f"{prefix}{obj} demand MW"][1] + LOAD_SUFFIX).set_axis(idx)
    share = pd.read_csv(d / EV_FILES["EV_ELVIS_share_CS1_8h.csv"], sep=";").set_axis(idx)
    km = pd.read_csv(d / EV_FILES["EV_ELVIS_demand_2MWh.csv"], sep=";").set_axis(idx)
    out["share"] = [share[f"{ev}~CS1"] / 100 for ev in EVS]
    out["km"] = [km[ev] for ev in EVS]
    return out


def describe(model):
    """(dataset, stage code, year, EV units, RES factor, load factor) of a short model name."""
    dataset, code = model.rsplit("_", 1)
    spec = LEVELS.get(dataset, {})
    year = int(dataset) if dataset.isdigit() else 2025
    return dataset, code, year, params(model)["units"], spec.get("res", 1.0), spec.get("load", 1.0)


def check(folder, model, cache):
    dataset, code, year, units, res_f, load_f = describe(model)
    inp = cache.setdefault(year, inputs(year))
    p = params(model)
    eta, bess = p["eta"], dict(BESS, capacity=p["battery MWh"], rate=p["battery MW"])
    ev = dict(EV, capacity=p["EV kWh"], charge=p["EV charge kW"], discharge=p["EV discharge kW"])
    cs_kw = (p["CS1 kW"], p["CS discharge kW"])
    r = Run(folder, model)
    settlement = code.endswith("2")
    v2g = not code.startswith("A")
    kind = "actual" if settlement else "forecast"
    fails, stats = [], {}

    def bad(what, value, tol=None):
        tol = (TOL_SETTLEMENT if settlement else TOL) if tol is None else tol
        stats[what] = value
        if value > tol:
            fails.append(f"{what} {value:.3g}")

    solar, wind = r("Generator", "Solar G1", "Generation"), r("Generator", "Wind G1", "Generation")
    idx = solar.index
    x = lambda s: s.reindex(idx).to_numpy(float)
    stats["hours"] = len(idx)
    inp = {**inp, **prices(model, idx)}  # the model's own price files
    bad("solar vs profile [MW]", np.abs(solar.to_numpy() - p["solar MW"] * x(inp[f"solar {kind}"])).max())
    bad("wind vs profile [MW]", np.abs(wind.to_numpy() - p["wind MW"] * x(inp[f"wind {kind}"])).max())
    bl, bg, soc = (r("Battery", "Stationary Battery", p).to_numpy() for p in ["Load", "Generation", "SoC"])
    present = [units[i] > 0 for i in range(len(EVS))]  # absent cohorts have no files
    get = lambda ev, prop, i: r("Vehicle", ev, prop).to_numpy() if present[i] else np.zeros(len(idx))
    evc = [get(ev, "Charging", i) for i, ev in enumerate(EVS)]
    evd = [get(ev, "Discharging", i) for i, ev in enumerate(EVS)]
    eve = [get(ev, "Energy", i) for i, ev in enumerate(EVS)]
    region = lambda p: r("Region", "Distribution BG Region", p).to_numpy()
    native = region("Load") - region("Battery Load") - sum(evc) / 1000
    profile = p["households MWh"] * x(inp[f"households {kind}"]) + p["business MWh"] * x(inp[f"business {kind}"])
    bad("native load vs profiles [MW]", np.abs(native - profile).max())
    bad("region battery load vs battery [MW]", np.abs(region("Battery Load") - bl).max())

    net = np.zeros(len(idx))
    for k, name in MARKETS.items():
        s, b, rev = r("Market", name, "Sales"), r("Market", name, "Purchases"), r("Market", name, "Net Revenue")
        if s is None:
            continue
        price = x(inp[k])
        bad(f"{name} cash flow vs sales x input - purchases x (input + 2) [EUR/h]",
            np.abs(rev.to_numpy() - s.to_numpy() * price + b.to_numpy() * (price + 2)).max(), 1e-4)
        both = int(((s > TOL_SETTLEMENT) & (b > TOL_SETTLEMENT)).sum())
        if both:
            fails.append(f"{name}: purchase and sale in {both} h")
        net += (s - b).to_numpy()

    supply = solar.to_numpy() + wind.to_numpy() + bg + sum(evd) / 1000
    demand = native + bl + sum(evc) / 1000
    bad("energy balance [MW]", np.abs(supply - demand - net).max())
    grid = r("Line", "DEMS-Transmission", "Flow")
    bad("grid flow vs net sales [MW]", np.abs(np.abs(grid.to_numpy()) - np.abs(net)).max())

    # battery
    prev = np.concatenate([[bess["soc0"]], soc[:-1]])
    eb = p["eta battery"]
    bad("battery SoC replay [%]", np.abs(soc - prev - (eb * bl - bg / eb) / bess["capacity"] * 100).max(), 1e-5)
    soc_min = 0.0 if settlement else bess["soc_min"]
    # in MWh, like every other energy check (1e-6 % of the 0.4 MWh battery is 4e-9 MWh)
    bad("battery SoC outside limits [MWh]", max(soc_min - soc.min(), soc.max() - 100, 0) / 100 * bess["capacity"])
    bad("battery flow outside 0..rating [MW]", max(-bl.min(), -bg.min(), bl.max() - bess["rate"], bg.max() - bess["rate"], 0))
    stats["battery charge+discharge h"] = int(((bl > TOL) & (bg > TOL)).sum())

    # EVs
    for i, name in enumerate(EVS):
        if not present[i]:
            continue
        cap = ev["capacity"] * units[i]
        e_prev = np.concatenate([[cap * ev["soc0"] / 100], eve[i][:-1]])
        drive = x(inp["km"][i]) * WH_KM[i] * units[i] / 1000
        bad(f"EV{i + 1} energy replay [kWh]", np.abs(eve[i] - e_prev - eta * evc[i] + evd[i] / eta + drive).max(), 1e-5)
        lo, hi = (0, 100) if settlement else (ev["soc_min"], ev["soc_max"])
        bad(f"EV{i + 1} energy outside SoC limits [kWh]", max(lo / 100 * cap - eve[i].min(), eve[i].max() - hi / 100 * cap, 0), 1e-5)
        conn = x(inp["share"][i]) * units[i]
        bad(f"EV{i + 1} charge above rate x connected [kW]", max((evc[i] - ev["charge"] * conn).max(), -evc[i].min(), 0), 1e-5)
        dmax = ev["discharge"] * conn if v2g else 0 * conn
        bad(f"EV{i + 1} discharge above rate x connected [kW]", max((evd[i] - dmax).max(), -evd[i].min(), 0), 1e-5)
        stats[f"EV{i + 1} charge+discharge h"] = int(((evc[i] > 1e-5) & (evd[i] > 1e-5)).sum())
    bad("CS1 charge limit [kW]", max((sum(evc) - cs_kw[0]).max(), 0), 1e-5)
    bad("CS1 discharge limit [kW]", max((sum(evd) - cs_kw[1]).max(), 0), 1e-5)
    stats["hours at a CS1 limit"] = int(((sum(evc) >= cs_kw[0] - 1e-3) | ((sum(evd) >= cs_kw[1] - 1e-3) & (cs_kw[1] > 0))).sum())

    stats["battery end SoC [%]"] = soc[-1]
    stats["fleet end SoC [%]"] = 100 * sum(e[-1] for e in eve) / (ev["capacity"] * sum(units))
    stats["min negative flow [kW]"] = min(0, bl.min() * 1000, bg.min() * 1000, min(c.min() for c in evc), min(d.min() for d in evd))
    return fails, stats


def main(argv):
    global FOLDER
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=str(FOLDER))
    ap.add_argument("--csv")
    ap.add_argument("models", nargs="*")
    a = ap.parse_args(argv)
    folder = FOLDER = Path(a.folder).resolve()  # runs, model files and input files all from this folder
    models = [r["model"] for r in csv.DictReader(open(FOLDER / "run_order.csv"), delimiter=";")]
    models = [m for m in models if not a.models or m in a.models]
    cache, table, n_bad, n_missing = {}, {}, 0, 0
    for m in sorted(models, key=lambda s: (re.sub(r"\d.*", "", s), s)):
        if not (folder / f"Model {m} Solution" / "Interval").exists():
            print(f"{m:14s} NOT RUN")
            n_missing += 1
            continue
        fails, stats = check(folder, m, cache)
        table[m] = stats
        n_bad += bool(fails)
        print(f"{m:14s} {'FAIL ' if fails else 'ok   '} {stats['hours']} h, end SoC battery {stats['battery end SoC [%]']:.1f} % / "
              f"fleet {stats['fleet end SoC [%]']:.1f} %" + ("; " + "; ".join(fails) if fails else ""))
    df = pd.DataFrame(table).T
    if a.csv:
        df.to_csv(a.csv, sep=";")
    worst = df.drop(columns=[c for c in df.columns if c in ("hours", "battery end SoC [%]", "fleet end SoC [%]")]).max()
    print("\nlargest value of each check over all runs:\n" + worst.to_string())
    print(f"\n{len(table) - n_bad} of {len(table)} runs consistent" + (f", {n_missing} of {len(models)} not run" if n_missing else ""))
    return 1 if n_bad or n_missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
