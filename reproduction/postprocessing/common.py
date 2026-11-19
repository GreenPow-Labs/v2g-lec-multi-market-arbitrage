# Made by Francesco Maldonato on 10/11/2026
"""Shared helpers of the post-processing scripts: where the runs and results are, how to read a run's flat files and inputs.

A runs folder is an executed copy of the PLEXOS model folder (runs/DRJ_MultiYear_v13_executed_logs, from Zenodo): the model
XML, its data_files/, model_overview.csv and one "Model <name> Solution" folder per run with the interval flat files PLEXOS
wrote (Interval/ST <Class>(<n>).<Property>.csv) and id2name.csv.
"""
import csv
import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RUNS_DIR = REPO / "runs"  # where the Zenodo archive is unpacked
RESULTS = REPO / "results"  # every output of the post-processing

YEARS = [2023, 2024, 2025]
EVS = ["EV 1-VW ID.5 Pro 01", "EV 2-VW ID.4 Pro 01", "EV 3-VW ID.4 GTX 01", "EV 4-VW ID.5 Pro 01"]  # cohorts RC, RO, WF, WP
EV_TYPES = {"EV 1-VW ID.5 Pro 01": "VW ID.5 Pro", "EV 2-VW ID.4 Pro 01": "VW ID.4 Pro",
            "EV 3-VW ID.4 GTX 01": "VW ID.4 GTX", "EV 4-VW ID.5 Pro 01": "VW ID.5 Pro"}
WH_KM = {"EV 1-VW ID.5 Pro 01": 169, "EV 2-VW ID.4 Pro 01": 173, "EV 3-VW ID.4 GTX 01": 183, "EV 4-VW ID.5 Pro 01": 169}
EV_FILES = ("EV_ELVIS-Straub_share_CS1.csv", "EV_ELVIS-Straub_distance_km.csv")  # preprocessing/ev_dataset/make_ev_dataset.py
UOS = 20.0  # EUR/MWh, charging-station use-of-system fee on charged and on discharged energy (PLEXOS "UoS Charge")
SOC0 = 0.25  # initial SoC of every EV and of the battery
# Battery wear (paper, Eq. 5): weighted Ah-throughput model of Preis & Biedenbach (2023, their Eqs. 24-25): the pack price
# spread over the throughput until the end of life (20 % capacity loss, no residual value): p_pack / (2 * N_EOL).
# NMC parameters of the vehicles studied: N_EOL 3,000 equivalent full cycles (NMC cells 1,000-4,000, Linders et al. 2025),
# range 2,000-4,000; p_pack 128 USD/kWh (BloombergNEF, Dec. 2025) / 1.13 USD/EUR (ECB 2025 mean) = 113 EUR/kWh.
# A high estimate: no residual value, all ageing attributed to cycling. Break-even wear cost (Eq. 7): gain / added throughput.
PACK = 113.0  # EUR/kWh of capacity
CYCLE_LIFE = 3000  # equivalent full cycles to 80 % SoH
CYCLE_LIFE_RANGE = [2000, 3000, 4000]
C_DEG = PACK / (2 * CYCLE_LIFE)  # EUR per kWh of battery throughput (1.88 ct/kWh)
STAGE_NAMES = {"A": "V1G day-ahead", "B": "V2G day-ahead", "C": "V2G day-ahead + intraday"}


def runs_folder(name_or_path):
    """A runs folder given as a path, or by name in runs/."""
    p = Path(name_or_path)
    if p.exists():
        return p.resolve()
    if (RUNS_DIR / name_or_path).exists():
        return (RUNS_DIR / name_or_path).resolve()
    raise SystemExit(f"runs folder '{name_or_path}' not found in {RUNS_DIR}: download and unpack the Zenodo archive (README.md)")


def overview(folder):
    """{model: row of model_overview.csv}, numbers as floats."""
    out = {}
    for r in csv.DictReader(open(Path(folder) / "model_overview.csv"), delimiter=";"):
        out[r["model"]] = {k: (float(v) if re.fullmatch(r"-?[\d.]+(e-?\d+)?", v or "") else v) for k, v in r.items()}
    return out


class Run:
    """The interval flat files of one PLEXOS run, as hourly pandas Series."""

    def __init__(self, folder, model):
        self.model, self.dir = model, Path(folder) / f"Model {model} Solution"
        self.ids = {(r["class"], r["name"]): r["id"] for r in csv.DictReader(open(self.dir / "id2name.csv"), delimiter=";")}
        self.cache = {}

    def __call__(self, cls, name, prop, default=None):
        key = (cls, name, prop)
        if key not in self.cache:
            f = self.dir / "Interval" / f"ST {cls}({self.ids.get((cls, name))}).{prop}.csv"
            if f.exists():
                df = pd.read_csv(f, sep=";")
                self.cache[key] = pd.Series(df.VALUE.to_numpy(), index=pd.to_datetime(df.DATETIME, format="%d/%m/%Y %H:%M"))
            else:
                self.cache[key] = None
        s = self.cache[key]
        return default if s is None else s

    def exists(self):
        return (self.dir / "Interval").exists()


def hourly(folder, path, index):
    """One input file of the runs folder (last column) on the hours of a run; path relative to the runs folder."""
    s = pd.read_csv(Path(folder) / path, sep=";")
    year = int(s.Year.iloc[0])
    return pd.Series(s.iloc[:, -1].to_numpy(float), index=pd.date_range(f"{year}-01-01", periods=len(s), freq="h")).reindex(index)


def ev_files(folder, year):
    """(availability file, distance file) of a runs folder and year."""
    d = Path(folder) / "data_files" / str(year)
    return d / EV_FILES[0], d / EV_FILES[1]


def ev_units(spec):
    """{EV: units} of a run (model_overview.csv row)."""
    return {ev: spec[f"EV{i} units"] for i, ev in enumerate(EVS, 1)}


def ev_profiles(folder, year, index):
    """{EV: (connected share 0-1, km per vehicle and hour)} of a year, on the hours of a run."""
    share_file, km_file = ev_files(folder, year)
    share = pd.read_csv(share_file, sep=";")
    km = pd.read_csv(km_file, sep=";")
    idx = pd.date_range(f"{year}-01-01", periods=len(share), freq="h")
    return {ev: ((share[f"{ev}~CS1"].set_axis(idx).astype(float) / 100).reindex(index), km[ev].set_axis(idx).astype(float).reindex(index))
            for ev in EVS}


def rainflow(x):
    """Rainflow cycle count (ASTM E1049, three-point method with the starting-point rule) of a series.
    Returns a list of (range, count), count 1 for a full cycle and 0.5 for a half cycle."""
    x = np.asarray(x, float)
    x = x[np.r_[True, np.diff(x) != 0]]  # drop flat repeats
    if len(x) < 3:
        return [(abs(x[-1] - x[0]), 0.5)] if len(x) == 2 else []
    d = np.sign(np.diff(x))
    turn = np.r_[True, d[1:] != d[:-1], True]
    tp = x[turn]
    stack, cycles = [], []
    for p in tp:
        stack.append(p)
        while len(stack) >= 3:
            r_old, r_new = abs(stack[-2] - stack[-3]), abs(stack[-1] - stack[-2])
            if r_new < r_old:
                break
            if len(stack) == 3:
                cycles.append((r_old, 0.5))
                stack.pop(0)
            else:
                cycles.append((r_old, 1.0))
                last = stack.pop()
                stack.pop()
                stack.pop()
                stack.append(last)
    cycles += [(abs(b - a), 0.5) for a, b in zip(stack[:-1], stack[1:])]
    return cycles


def weighted_stats(values, weights):
    """min, max, mean, standard deviation (population, weighted) and the weighted 10/50/90 % quantiles."""
    v, w = np.asarray(values, float), np.asarray(weights, float)
    mean = np.average(v, weights=w)
    std = np.sqrt(np.average((v - mean) ** 2, weights=w))
    order = np.argsort(v)
    cw = np.cumsum(w[order]) / w.sum()
    q = lambda p: v[order][np.searchsorted(cw, p)]
    return {"min": v.min(), "max": v.max(), "mean": mean, "std": std, "p10": q(0.1), "p50": q(0.5), "p90": q(0.9)}


PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#8b5cf6"]  # categorical colours 1-4
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def paper_style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"], "font.size": 7,
                         "mathtext.fontset": "stix", "axes.edgecolor": MUTED, "axes.labelcolor": MUTED,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42})  # TrueType fonts in the PDF figures
    return plt
