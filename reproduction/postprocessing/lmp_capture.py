# Made by Francesco Maldonato on 10/11/2026
"""The community's nodal price (LMP): where it sits against the market prices, and which price each flow captures.

    python3 lmp_capture.py            # runs/DRJ_MultiYear_v13_executed_logs -> results/

The community (DEMS node) trades through one grid connection. Without congestion its LMP lies in a band set by the
market price p of the hour: p when the community exports (export parity: the marginal MWh is sold), p + 42 EUR/MWh when it
imports (import parity: market price + 2 EUR/MWh trading hurdle + 2 x 20 EUR/MWh wheeling to and from the DEMS node), and
in between when a local resource (storage, EVs) is marginal. The reference market is the day-ahead price in A.1 and B.1,
the intraday price in C.1 and the imbalance price in the settlement runs (X.2).
Per run (2023-2025, A/B/C, X.1 and X.2):
- share of hours at export parity (|LMP - p| < 0.5), at import parity (|LMP - p - 42| < 0.5), inside the band, outside;
- the time-average LMP and the LMP weighted by each flow: native load, EV charging, V2G discharging, battery charging and
  discharging. The LMP of a flow is the price it sees; the spread between them is the value of shifting energy in time.
Writes results/lmp_capture.csv (paper Section VI-C: the time-average LMP differs by at most 6 EUR/MWh between scenarios).
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import EVS, RESULTS, YEARS, Run, hourly, overview, runs_folder

BAND = 42.0  # EUR/MWh: trading hurdle 2 + wheeling 2 x 20
REGION = "Distribution BG Region"


def analyse(folder, model, spec):
    r = Run(folder, model)
    lmp = r("Region", REGION, "Price")
    idx = lmp.index
    key = "imbalance price file" if model.endswith("2") else ("ID price file" if model.endswith("C1") else "DA price file")
    p = hourly(folder, spec[key], idx)
    d = lmp - p
    load, bl = r("Region", REGION, "Load"), r("Region", REGION, "Battery Load")
    evc = sum(r("Vehicle", ev, "Charging", 0 * lmp) for ev in EVS) / 1000
    evd = sum(r("Vehicle", ev, "Discharging", 0 * lmp) for ev in EVS) / 1000
    flows = {"native load": load - bl - evc, "EV charging": evc, "V2G discharging": evd,
             "battery charging": r("Battery", "Stationary Battery", "Load"), "battery discharging": r("Battery", "Stationary Battery", "Generation")}
    out = {"model": model, "year": int(spec["year"]), "scenario": model[-2], "stage": model[-1], "reference market": key.split(" ")[0],
           "export parity [% h]": 100 * (d.abs() < 0.5).mean(), "inside the band [% h]": 100 * ((d >= 0.5) & (d <= BAND - 0.5)).mean(),
           "import parity [% h]": 100 * ((d - BAND).abs() < 0.5).mean(), "outside the band [% h]": 100 * ((d < -0.5) | (d > BAND + 0.5)).mean(),
           "market price, time average [EUR/MWh]": p.mean(), "LMP, time average [EUR/MWh]": lmp.mean()}
    for k, f in flows.items():
        f = f.clip(lower=0)
        out[f"LMP of {k} [EUR/MWh]"] = float(np.average(lmp, weights=f)) if f.sum() > 1e-6 else np.nan
        out[f"{k} [MWh]"] = float(f.sum())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="DRJ_MultiYear_v13_executed_logs")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    folder = runs_folder(a.folder)
    out = Path(a.out) if a.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    ov = overview(folder)
    rows = [analyse(folder, f"{y}_{s}{k}", ov[f"{y}_{s}{k}"]) for y in YEARS for s in "ABC" for k in "12" if Run(folder, f"{y}_{s}{k}").exists()]
    df = pd.DataFrame(rows)
    df.to_csv(out / "lmp_capture.csv", sep=";", index=False, float_format="%.3f")
    pd.set_option("display.width", 250)
    print(df.drop(columns=[c for c in df.columns if c.endswith("[MWh]")]).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
