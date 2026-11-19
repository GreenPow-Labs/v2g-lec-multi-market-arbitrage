# Made by Francesco Maldonato on 10/11/2026
"""After the PLEXOS runs: did every model run cleanly, and does each settlement run reproduce its source run?

    python3 check_after_run.py                       # all models of run_order.csv
    python3 check_after_run.py 2025_B2 2023_C2       # only these models
    python3 check_after_run.py --folder <path> ...   # another runs folder (e.g. the Zenodo runs)

Per model (solution folder next to the XML):
- NOT RUN: no solution folder (or PLEXOS wrote it to a temp folder: WARNING 3132, path too long);
- FAILED: the folder holds no results, only PLEXOS's '~Model ( ... ) Log.txt' (the run stopped);
- the error and warning table of the log, its infeasibility count, and the constraints PLEXOS
  repaired after an infeasible step (WARNING 210).
Per settlement model (X.2; source run from model_overview.csv, column 'flexibility pinned to'):
- the pinned quantities equal to the source run: battery SoC, and each EV's stored energy (V2G) or
  charging (V1G, A.2; its stored energy follows the charging and is reported as a note);
- battery Load and Generation equal to the source run, except hours in which the source run has a
  negative battery Load (PLEXOS solution noise; reported as a note);
- day-ahead and intraday positions identical to the source run;
- imbalance = forecast error (actual - forecast RES, minus actual - forecast load) + any change of the
  battery's net injection;
- the pinned discharging (V2G EVs, battery Generation), compared like the stored energy;
- hours in which the grid connection carries more than 2 MW (reported; settlement runs have a 10 MW connection).
Every run: no 3-day step whose results equal the step before in most interval files (REPEATED_STEP; PLEXOS can write a
step's solution twice without a message in its log). Market positions are compared at the settlement solver's feasibility
tolerance (1e-5 MW); absent cohorts (0 Units, fleet-mix ends) have no files and are skipped.
Stray '~Model ( ... ) Log.txt' files in the folder are logs PLEXOS could not move into a solution.
Exit code 1 if anything is off.
"""
import csv
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from make_multiyear_model import SETTLEMENT_GRID

FOLDER = Path(__file__).resolve().parent.parent
TOL_MW = 1e-6   # battery flows and market positions
TOL_PCT = 1e-6  # battery SoC [%]
TOL_KWH = 1e-6  # EV stored energy [kWh]
TOL_KW = 1e-6  # EV charging [kW]
TOL_POSITION = 1e-5  # market positions [MW], the settlement solver's Feasibility Tolerance
STEP_HOURS = 72  # 3-day steps
REPEATED_STEP = 0.5  # share of the interval files (with a non-constant step) in which a step equals the one before
GRID_LIMIT_MW = 2.0
MARKETS = {"DA": "Day-Ahead energy price", "IMB": "Imbalance price", "ID": "Intraday energy price"}


class Solution:
    def __init__(self, folder, model):
        self.model, self.dir = model, folder / f"Model {model} Solution"
        self.ids = {}
        if (self.dir / "id2name.csv").exists():
            for r in csv.DictReader(open(self.dir / "id2name.csv"), delimiter=";"):
                self.ids[(r["class"], r["name"])] = r["id"]

    def __call__(self, cls, name, prop):
        i = self.ids.get((cls, name))
        f = self.dir / "Interval" / f"ST {cls}({i}).{prop}.csv"
        if i is None or not f.exists():
            return None
        return pd.read_csv(f, sep=";", index_col=0)["VALUE"]

    def net(self, market):  # sales - purchases, MW; 0 if the market is not in the model
        s, p = self("Market", MARKETS[market], "Sales"), self("Market", MARKETS[market], "Purchases")
        return 0.0 if s is None else s - p

    def res(self):
        return self("Generator", "Solar G1", "Generation") + self("Generator", "Wind G1", "Generation")

    def vehicles(self):  # only vehicles with results (PLEXOS writes none for 0 Units)
        return [n for (c, n) in self.ids if c == "Vehicle" and self(c, n, "Energy") is not None]

    def load(self):  # native load = region load - battery charging - EV charging (MW)
        region = lambda p: self("Region", "Distribution BG Region", p)
        return region("Load") - region("Battery Load") - sum(self("Vehicle", n, "Charging") for n in self.vehicles()) / 1000


def log_summary(solution_dir, model):
    """Log messages (not 'Ignore'), infeasibility count, repaired constraints; None if there is no log."""
    log = next((p for p in [solution_dir / f"Model ( {model} ) Log.txt", solution_dir / f"~Model ( {model} ) Log.txt"] if p.exists()), None)
    if log is None:
        return None
    text = log.read_text(errors="replace").replace("\r", "")
    table = re.search(r"Error and Warning Messages.*?\n-+\n.*?\n-+\n(.*?)\n-+", text, re.S)
    messages = []
    for line in (table.group(1).splitlines() if table else []):
        m = re.match(r"(\d+)\s+(.*?)\s+(\d+)\s+(\w+)\s+(\d+)\s*$", line.strip())
        if m and m.group(4) != "Ignore":
            messages.append(f"{m.group(4).upper()} {m.group(1)} x{m.group(5)}: {m.group(2)[:50]}")
    infeasible = sum(int(n) for n in re.findall(r"Infeasibilities:\.*\s+(\d+)", text))
    num = r"(?:NONE|[-+\d.eE]+)"
    repaired = Counter(re.findall(rf"^\d+\s+([A-Za-z_][\w.\-]*?)(?:\{{[^}}]*\}})?\s+{num}\s+{num}\s+{num}\s+{num}\s*$", text, re.M))
    return messages, infeasible, repaired


def repeated_steps(solution_dir):
    """Steps whose results equal the previous step's in at least REPEATED_STEP of the interval files that vary within
    the step (PLEXOS wrote a solution twice). Returns {step: 'n/m files'}."""
    same, varying = Counter(), Counter()
    for f in sorted((solution_dir / "Interval").glob("*.csv")):
        v = pd.read_csv(f, sep=";")["VALUE"].to_numpy(float)
        n = len(v) // STEP_HOURS
        b = v[:n * STEP_HOURS].reshape(n, STEP_HOURS)
        for k in range(1, n):
            if b[k].max() - b[k].min() > 1e-9:
                varying[k + 1] += 1
                same[k + 1] += bool((b[k] == b[k - 1]).all())
    return {k: f"{same[k]}/{varying[k]} files" for k in same if varying[k] >= 5 and same[k] >= REPEATED_STEP * varying[k]}


def settlement_issues(folder, model, source):
    """(issues, notes) of a settlement run against its source run."""
    a, b = Solution(folder, model), Solution(folder, source)
    issues, worst = [], {}

    def compare(x, y, tol, what, unit, skip=None):
        dev = (x - y.reindex(x.index)).abs()
        if skip is not None:
            dev = dev[~skip.reindex(dev.index, fill_value=False)]
        worst[unit] = max(worst.get(unit, 0.0), float(dev.max()))
        if (dev > tol).any():
            issues.append(f"{what} off in {int((dev > tol).sum())} h (max {dev.max():.3g} {unit})")

    bat = lambda s, p: s("Battery", "Stationary Battery", p)
    compare(bat(a, "SoC"), bat(b, "SoC"), TOL_PCT, "battery SoC", "%")
    v1g = model.split("_")[-1].startswith("A")
    for n in a.vehicles():
        if v1g:
            compare(a("Vehicle", n, "Charging"), b("Vehicle", n, "Charging"), TOL_KW, f"{n} charging", "kW")
            worst["kWh"] = max(worst.get("kWh", 0.0), float((a("Vehicle", n, "Energy") - b("Vehicle", n, "Energy")).abs().max()))
        else:
            compare(a("Vehicle", n, "Energy"), b("Vehicle", n, "Energy"), TOL_KWH, f"{n} energy", "kWh")
            compare(a("Vehicle", n, "Discharging"), b("Vehicle", n, "Discharging"), TOL_POSITION * 1000, f"{n} discharging", "kW")  # pin, at the solver tolerance
    negative = (bat(b, "Load") < 0) | (bat(b, "Generation") < 0)
    for flow in ["Load", "Generation"]:
        compare(bat(a, flow), bat(b, flow), TOL_MW, f"battery {flow}", "MW", skip=negative)
    for market in ["DA", "ID"]:
        x, y = a.net(market), b.net(market)
        if not isinstance(x, float) and (x - y).abs().max() > TOL_POSITION:
            issues.append(f"{market} position differs by up to {(x - y).abs().max():.3g} MW")
    imbalance = a.net("IMB")
    forecast_error = (a.res() - b.res()) - (a.load() - b.load())
    battery_change = (bat(a, "Generation") - bat(a, "Load")) - (bat(b, "Generation") - bat(b, "Load"))
    residual = imbalance - (forecast_error + battery_change)
    if residual.abs().max() > 1e-4:
        issues.append(f"imbalance differs from the forecast error by up to {residual.abs().max() * 1000:.3g} kW")
    total = abs(imbalance) if isinstance(imbalance, float) else float(imbalance.abs().sum())
    ev = f"EV charging {worst.get('kW', 0):.1g} kW (energy {worst.get('kWh', 0):.1g} kWh)" if v1g else f"EV energy {worst.get('kWh', 0):.1g} kWh"
    notes = [f"pins within {worst.get('%', 0):.1g} % / {ev}, battery flows {worst.get('MW', 0):.1g} MW", f"|imbalance| {total:.1f} MWh"]
    if negative.any():
        notes.append(f"source has a negative battery Load/Generation in {int(negative.sum())} h (flows not compared there)")
    grid = a("Line", SETTLEMENT_GRID[1], "Flow")
    if grid is None:
        issues.append(f"no flow output for {SETTLEMENT_GRID[1]} (line out of service?)")
    elif (grid.abs() > GRID_LIMIT_MW + TOL_MW).any():
        over = grid.abs() > GRID_LIMIT_MW + TOL_MW
        notes.append(f"grid connection above {GRID_LIMIT_MW:g} MW in {int(over.sum())} h (max {grid.abs().max():.3f} MW)")
    return issues, notes


def main(args):
    folder = FOLDER
    if "--folder" in args:
        i = args.index("--folder")
        folder = Path(args[i + 1]).resolve()
        args = args[:i] + args[i + 2:]
    only = set(args)
    runs = list(csv.DictReader(open(folder / "run_order.csv"), delimiter=";"))
    source = {r["model"]: r["flexibility pinned to"] for r in csv.DictReader(open(folder / "model_overview.csv"), delimiter=";")}
    count = Counter()
    for r in runs:
        m = r["model"]
        if only and m not in only:
            continue
        sol = folder / f"Model {m} Solution"
        if not sol.exists():
            print(f"{m:14s} NOT RUN  no solution folder (or PLEXOS wrote it to a temp folder: WARNING 3132)")
            count["not run"] += 1
            continue
        log = log_summary(sol, m)
        messages, infeasible, repaired = log if log else (None, 0, Counter())
        notes = ["no log"] if messages is None else messages + ([f"{infeasible} infeasibilities"] if infeasible else [])
        if repaired:
            notes.append("repaired: " + ", ".join(f"{n} x{k}" for n, k in repaired.most_common(4)))
        if not (sol / "Interval").exists():
            print(f"{m:14s} FAILED   " + "; ".join(notes))
            count["failed"] += 1
            continue
        issues = []
        repeated = repeated_steps(sol)
        if repeated:
            issues.append("PLEXOS wrote a step's solution twice (step: files equal to the step before): "
                          + ", ".join(f"{k}: {v}" for k, v in repeated.items()) + "; rerun this model and the models that read it")
        if source.get(m):
            more_issues, more = settlement_issues(folder, m, source[m])
            issues += more_issues
            notes += more_issues + more
        elif repeated:
            notes += issues
        bad = messages is None or bool(messages) or bool(infeasible) or bool(issues)
        count["to check" if bad else "ok"] += 1
        print(f"{m:14s} {'CHECK' if bad else 'ok   '}    " + "; ".join(notes))
    stray = sorted(p.name for p in folder.glob("~Model*Log.txt"))
    if stray:
        print("stray logs PLEXOS could not move (the run wrote its solution elsewhere): " + ", ".join(stray))
        count["stray logs"] += len(stray)
    print(", ".join(f"{n} {k}" for k, n in count.items()) if count else "nothing to check")
    return 1 if set(count) - {"ok"} else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
