# Made by Francesco Maldonato on 10/11/2026
"""Computational performance of the PLEXOS runs (paper Section IV-C, Table 3), from their logs.

    python3 computational_performance.py            # runs/DRJ_MultiYear_v13_executed_logs -> results/

Per run (Model ( <name> ) Log.txt): PLEXOS and solver version, hardware (CPU type, cores, memory; the computer and
user names in the log are not copied), rolling-horizon steps, wall time of the model and of the ST schedule, solver time
and Gurobi work units, number of MIP solves, aggregated linear relaxation / best integer / best bound and their gap, time
limits reached, infeasibilities, peak memory, and, where the log prints them, the problem size (rows, columns, non-zeros,
integer variables) and the solver summary of each step.

Writes results/computational_performance.csv (every run) and computational_performance_summary.csv (Table 3, by stage).
"""
import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

from common import runs_folder, RESULTS


def seconds(hms):
    h, m, s = hms.split(":")
    return 3600 * int(h) + 60 * int(m) + float(s)


def field(text, label):
    """Value after '<label>....' (the last one: the run's summary)."""
    m = re.findall(rf"{re.escape(label)}:?\s*\.*\s+([-+]?\d[\d.eE+%:-]*)", text)
    return m[-1] if m else None


def parse(log):
    t = log.read_text(errors="replace").replace("\r", "")
    out = {"model": re.search(r'Started Model "(.+?)"', t).group(1)}
    out["PLEXOS"] = re.search(r"PLEXOS.*?(\d+\.\d+ R\d+)", t).group(1) if re.search(r"PLEXOS.*?(\d+\.\d+ R\d+)", t) else ""
    solver = re.search(r"(Gurobi|CPLEX|Xpress|MOSEK)[ ]?([\d.]+)?:", t)
    out["solver"] = f"{solver.group(1)} {solver.group(2) or ''}".strip() if solver else ""
    out["CPU"] = (field(t, "CPU Type") or "").strip()
    m = re.search(r"CPU Type\.+\s+(.+)", t)
    out["CPU"] = m.group(1).strip() if m else ""
    m = re.search(r"CPU/Core Count\.+\s+(\d+)", t)
    out["cores"] = int(m.group(1)) if m else np.nan
    m = re.search(r"Physical Memory\.+\s+([\d.]+) GB", t)
    out["memory [GB]"] = float(m.group(1)) if m else np.nan
    steps = re.findall(r"ST Schedule Step (\d+) of (\d+)", t)
    out["steps"] = int(steps[-1][1]) if steps else np.nan
    m = re.search(r'Model ".+?" Completed\. Time: ([\d:.]+)', t)
    out["model wall time [s]"] = seconds(m.group(1)) if m else np.nan
    m = re.search(r"ST Schedule Completed\. Time: ([\d:.]+)", t)
    out["ST schedule time [s]"] = seconds(m.group(1)) if m else np.nan
    m = re.search(r"(?:Gurobi|CPLEX|Xpress|MOSEK)[ \d.]*:\.+\s+([\d:.]+)", t)
    out["solver time [s]"] = seconds(m.group(1)) if m else np.nan
    m = re.search(r"Work Units\.+\s+([\d.]+)", t)
    out["solver work units"] = float(m.group(1)) if m else np.nan
    for label, key in [("Total MIP Solves", "MIP solves"), ("Total LP Solves", "LP solves"), ("Time Limit Reached", "time limits reached"),
                       ("No Integer Feasible Solution", "no integer solution"), ("Infeasibilities", "infeasibilities")]:
        v = field(t, label)
        out[key] = int(v) if v and v.isdigit() else (0 if key != "MIP solves" else np.nan)
    for label, key in [("Linear Relaxation", "linear relaxation [EUR]"), ("Best Integer Solution", "best integer [EUR]"),
                       ("Best Bound", "best bound [EUR]"), ("Absolute Gap", "absolute gap [EUR]")]:
        v = field(t, label)
        out[key] = float(v) if v else np.nan
    v = field(t, "Relative Gap")
    out["relative gap [%]"] = float(v.rstrip("%")) if v else np.nan
    m = re.search(r"Peak Memory\.+\s+([\d.]+) MB", t)
    out["peak memory [MB]"] = float(m.group(1)) if m else np.nan
    # per-step diagnostics: problem size of every step ("Tasks: 1   Cols 4,253   Ints 360   Rows 5,472   Nzs  10,800") and the
    # solver summary of every step (Time ... sec., Status ..., Final Gap ... %)
    sizes = [[int(v.replace(",", "")) for v in g] for g in re.findall(r"Cols ([\d,]+)\s+Ints ([\d,]+)\s+Rows ([\d,]+)\s+Nzs\s+([\d,]+)", t)]
    for j, key in enumerate(["columns", "integers", "rows", "non-zeros"]):
        out[f"max {key} per step"] = max(s[j] for s in sizes) if sizes else np.nan
    times = [float(x) for x in re.findall(r"^Time \.+\s+([\d.]+) sec\.", t, re.M)]
    status = re.findall(r"^Status \.+\s+(\w+)", t, re.M)
    gaps = [float(x) for x in re.findall(r"^Final Gap \.+\s+([\d.]+) %", t, re.M)]
    out["solves summarised"] = len(times)
    out["step solve time mean [s]"] = float(np.mean(times)) if times else np.nan
    out["step solve time max [s]"] = float(np.max(times)) if times else np.nan
    out["step final gap max [%]"] = float(np.max(gaps)) if gaps else np.nan
    out["steps not optimal"] = sum(s != "Optimal" for s in status) if status else np.nan
    warn = re.findall(r"^(\d+)\s+(.+?)\s{2,}(\d)\s+(\w+)\s+(\d+)\s*$", t, re.M)
    out["warnings/errors"] = "; ".join(f"{w[0]} x{w[4]}" for w in warn if w[3] != "Ignore")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="DRJ_MultiYear_v13_executed_logs")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    folder = runs_folder(a.folder)
    out = Path(a.out) if a.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    rows = [parse(p) for p in sorted(folder.glob("Model * Solution/Model ( * ) Log.txt"))]
    df = pd.DataFrame(rows)
    df["kind"] = np.where(df.model.str.endswith("2"), "settlement (X.2)", "optimisation (X.1)")
    df["set"] = np.where(df.model.str.match(r"^\d{4}_"), "years 2023-2025", "2025 sweeps")
    df["solver time per step [s]"] = df["solver time [s]"] / df["steps"]
    df.to_csv(out / "computational_performance.csv", sep=";", index=False, float_format="%.6g")
    agg = {"model wall time [s]": ["sum", "mean", "max"], "solver time [s]": ["mean", "max"], "solver time per step [s]": ["mean", "max"],
           "relative gap [%]": ["mean", "max"], "absolute gap [EUR]": ["max"], "infeasibilities": ["sum"], "peak memory [MB]": ["max"],
           "steps": ["max"], "model": ["count"], "max columns per step": ["max"], "max integers per step": ["max"],
           "max rows per step": ["max"], "max non-zeros per step": ["max"], "step solve time mean [s]": ["mean"],
           "step solve time max [s]": ["max"], "step final gap max [%]": ["max"], "steps not optimal": ["sum"]}
    summary = df.groupby(["kind", "set"]).agg(agg)
    summary.columns = [f"{a} {b}" for a, b in summary.columns]
    summary.to_csv(out / "computational_performance_summary.csv", sep=";", float_format="%.4g")
    hw = df.iloc[0]
    print(f"{len(df)} runs; PLEXOS {hw['PLEXOS']}, {hw['solver']}; {hw['CPU']}, {hw['cores']} cores, {hw['memory [GB]']:g} GB")
    print(f"total wall time {df['model wall time [s]'].sum() / 60:.1f} min; per run mean {df['model wall time [s]'].mean():.1f} s, "
          f"max {df['model wall time [s]'].max():.1f} s ({df.loc[df['model wall time [s]'].idxmax(), 'model']})")
    print(summary.round(3).to_string())
    print(df[["model", "model wall time [s]", "solver time [s]", "solver work units", "MIP solves", "relative gap [%]", "absolute gap [EUR]",
              "infeasibilities", "peak memory [MB]", "warnings/errors"]].to_string(index=False))
    return df


if __name__ == "__main__":
    main()
