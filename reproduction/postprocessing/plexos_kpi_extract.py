# Made by Francesco Maldonato on 10/11/2026
"""KPIs of every PLEXOS run (paper Section III-F, Tables 8 and 9, sensitivity analysis), from the runs' flat files.

    python3 plexos_kpi_extract.py --check          # runs/DRJ_MultiYear_v13_executed_logs -> results/

Every run is read as it is: optimisation runs (X.1, forecast data) and settlement runs (X.2: the X.1 schedule with the
actual RES and load, every deviation settled at the imbalance price). Scenarios: A = V1G day-ahead, B = V2G day-ahead,
C = V2G day-ahead + intraday. The e-mobility KPIs of a settlement run are those of the X.1 schedule it replays.

Writes into results/:
- KPI_multiyear.csv              every KPI of the 18 year runs (2023-2025, A.1 ... C.2);
- KPI_sweeps.csv                 every KPI of the 2025 sensitivity runs (C.2), the base run as the reference level;
- table8_kpis_by_year.csv        the paper's Table 8: the settled schedules (A.2, B.2, C.2) of each year;
- table9_three_year_mean.csv     the paper's Table 9: three-year mean of every stage, change of B.2 and C.2 against A.2;
- settlement_check.csv (--check) every settlement run against its ex-post value (imbalance = net forecast error).
The battery wear rows of Tables 8 and 9 come from ev_fleet_analysis.py.

Units: money in EUR; vehicle and charging-station flows in kW, battery, market and line flows in MW (hourly intervals).
Markets buy at the input price + 2 EUR/MWh and sell at the input price; PLEXOS Net Revenue includes it.
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import carbon_accounting as ca  # noqa: E402
from common import RESULTS, overview as read_overview, runs_folder  # noqa: E402

DEFAULT = "DRJ_MultiYear_v13_executed_logs"
RUNS = None  # the runs folder (set in main)
DATA = None  # its input files (set in main)

YEARS = [2023, 2024, 2025]
STAGES = {"A.1": "A1", "A.2": "A2", "B.1": "B1", "B.2": "B2", "C.1": "C1", "C.2": "C2"}  # column label -> model name code
SCENARIOS = {"A": "V1G DA", "B": "V2G DA", "C": "V2G DA+ID"}
# 2025 sensitivity sweeps: (model prefixes, level labels); None = the 2025 base run
SWEEPS = {"EV fleet [EVs]": (["S-EV50", "S-EV75", None, "S-EV150", "S-EV200", "S-EV400"], ["50", "75", "100", "150", "200", "400"]),
          "RES capacity [% penetration]": (["S-RES40", "S-RES60", None, "S-RES100", "S-RES120"], ["40", "60", "80", "100", "120"]),
          "Load with RES [% of base load]": (["S-LOAD50", "S-LOAD75", None, "S-LOAD150", "S-LOAD200"], ["50", "75", "100", "150", "200"]),
          "Fleet mix [% residents]": (["S-MIX0", "S-MIX25", "S-MIX50", None, "S-MIX75", "S-MIX100"], ["0", "25", "50", "65", "75", "100"])}
SWEEP_STAGE = "C.2"
BASELINE = {"B.1": "A.1", "C.1": "A.1", "B.2": "A.2", "C.2": "A.2"}  # three-year mean: each V2G stage against V1G's
# rows of Tables 8 and 9: (paper label, KPI, scale); money in kEUR (scale 1e-3)
PAPER_ROWS = [
    ("Community energy cost [EUR/MWh]", "Community energy cost, cash-flow [EUR/MWh]", 1),
    ("Net market profit [kEUR]", "Net market profit [EUR]", 1e-3),
    ("Total wheeling cost [kEUR]", "Total wheeling cost [EUR]", 1e-3),
    ("Community's LMP [EUR/MWh]", "Community LMP, demand-weighted [EUR/MWh]", 1),
    ("Charging station UoS [kEUR]", "CS operator UoS [EUR]", 1e-3),
    ("EVs av. charging price [ct/kWh]", "EVs av. charging price [ct/kWh]", 1),
    ("EVs av. discharging price [ct/kWh]", "EVs av. discharging price [ct/kWh]", 1),
    ("EVs av. net charging cost [EUR/EV/a]", "EVs av. net charging cost [EUR/EV]", 1),
    ("Fleet utilization [EFC]", "Fleet utilization [EFC per EV]", 1),
    ("Grid-imported energy [MWh]", "Grid imported energy [MWh]", 1),
    ("Imported energy attributed CO2eq [tCO2eq]", "Imported energy CO2eq [tCO2eq]", 1),
    ("Grid-exported energy [MWh]", "Grid exported energy [MWh]", 1),
    ("Export attributed CO2eq benefit [tCO2eq]", "Export CO2eq benefit [tCO2eq]", 1),
    ("Net CO2eq balance [tCO2eq]", "Net attributed CO2eq balance [tCO2eq]", 1),
]

SOC0 = 0.25  # initial SoC of the battery and of every EV
WHEELING = 20.0  # EUR/MWh on every line, both directions
# RES operation and maintenance (Fraunhofer ISE 2024): PV 21.5 EUR/kW/a; onshore wind 32 EUR/kW/a + 7 EUR/MWh. The RES are
# must-run, so their O&M never changes the dispatch; it is added here: (capacity column, EUR/kW/a, EUR/MWh)
RES_OM = {"Solar G1": ("solar MW", 21.5, 0.0), "Wind G1": ("wind MW", 32.0, 7.0)}
MARKETS = {"DA": "Day-Ahead energy price", "IMB": "Imbalance price", "ID": "Intraday energy price"}
LINES = ["Business-DEMS", "CS-DEMS", "DEMS-Transmission", "Household-DEMS", "Solar-DEMS", "StationaryStorage-DEMS", "Wind-DEMS"]


class Run:
    """The interval flat files of one PLEXOS run, as hourly series."""

    def __init__(self, folder, model):
        self.model, self.dir = model, folder / f"Model {model} Solution"
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

    def vehicles(self, prop):
        # PLEXOS writes no file for a vehicle without units (absent cohorts at the fleet-mix ends)
        return sum(s for s in (self("Vehicle", n, prop) for (c, n) in self.ids if c == "Vehicle") if s is not None)

    def market(self, key, prop):
        return self("Market", MARKETS[key], prop, 0.0)


def carbon_intensity(year, index):
    f = DATA / str(year) / f"carbon-intensity-gCO2eq-1H_germany-{year}.csv"
    ci = pd.read_csv(f, sep=";").iloc[:, -1]
    ci.index = pd.date_range(f"{year}-01-01", periods=len(ci), freq="h")
    return ci.reindex(index)


def kpis(run, year, n_ev, flex):
    """KPIs of one run; flex = the run whose EV schedule and nodal prices give the e-mobility KPIs (the run itself, or for a
    settlement run its source: same schedule, while the settlement run's nodal price is the imbalance price)."""
    solar, wind = run("Generator", "Solar G1", "Generation"), run("Generator", "Wind G1", "Generation")
    idx = solar.index
    net = {k: run.market(k, "Sales") - run.market(k, "Purchases") for k in MARKETS}
    rev = {k: float(np.sum(run.market(k, "Net Revenue"))) for k in MARKETS}
    vol = {k: float(np.sum(run.market(k, "Sales") + run.market(k, "Purchases"))) for k in MARKETS}
    nms = sum(net.values()) * pd.Series(1.0, index=idx)
    profit = sum(rev.values())
    wheeling = WHEELING * sum(run("Line", line, "Flow").abs().sum() for line in LINES)
    uos = run("Charging Station", "CS1", "UoS Cost").sum()
    vom = run("Battery", "Stationary Battery", "VO&M Cost").sum()
    load, bat_load = run("Region", "Distribution BG Region", "Load"), run("Region", "Distribution BG Region", "Battery Load")
    delivered = (load - bat_load).sum()  # native load + EV charging [MWh]
    consumed = delivered - run.vehicles("Discharging").sum() / 1000  # minus V2G: what the consumers use
    year_share = len(idx) / (pd.Timestamp(f"{year + 1}-01-01") - pd.Timestamp(f"{year}-01-01")).days / 24  # 8712 h of the year
    res_om = sum(1000 * float(run.spec[cap]) * fixed * year_share + var * run("Generator", g, "Generation").sum()
                 for g, (cap, fixed, var) in RES_OM.items())
    region_price = (run("Region", "Distribution BG Region", "Price") * (load - bat_load)).sum() / delivered

    cs = lambda p: flex("Charging Station", "CS1", p).sum()
    ch, dis, e = flex.vehicles("Charging"), flex.vehicles("Discharging"), flex.vehicles("Energy")
    eta, ev_kwh, bess_mwh = run.spec["EV efficiency %"] / 100, run.spec["EV kWh"], run.spec["battery MWh"]
    eta_b = run.spec["battery efficiency %"] / 100
    ev_in, v2g = ch.sum() / 1000 * eta, dis.sum() / 1000
    e0 = SOC0 * ev_kwh * n_ev / 1000
    driving = ev_in - v2g / eta - (e.iloc[-1] / 1000 - e0)
    fleet_mwh = n_ev * ev_kwh / 1000
    bl, bg, soc = (run("Battery", "Stationary Battery", p) for p in ["Load", "Generation", "SoC"])

    flows = pd.DataFrame({"solar": solar, "wind": wind, "imp": (-nms).clip(lower=0), "exp": nms.clip(lower=0),
                          "bess_ch": bl, "bess_dis": bg, "bess_e": soc / 100 * bess_mwh,
                          "ev_ch": run.vehicles("Charging") / 1000, "ev_dis": run.vehicles("Discharging") / 1000,
                          "ev_e": run.vehicles("Energy") / 1000, "ci_grid": carbon_intensity(year, idx)})
    attributed = ca.attribute(flows, SOC0 * bess_mwh, e0, eta_bess=eta_b, eta_ev=eta)
    carbon = ca.kpis(attributed)
    del carbon["Mean SOCI BESS / EV [gCO2eq/kWh]"]  # text "x / y"; as two numbers instead
    carbon["Mean SOCI BESS [gCO2eq/kWh]"] = attributed.soci_bess.mean()
    carbon["Mean SOCI EVs [gCO2eq/kWh]"] = attributed.soci_ev.mean()
    carbon["Net grid import, imported - exported [MWh]"] = carbon["Grid imported energy [MWh]"] - carbon["Grid exported energy [MWh]"]
    return {
        "Net market profit [EUR]": profit,
        "  of which day-ahead [EUR]": rev["DA"],
        "  of which intraday [EUR]": rev["ID"],
        "  of which imbalance settlement [EUR]": rev["IMB"],
        "Total wheeling cost [EUR]": wheeling,
        "CS operator UoS [EUR]": uos,
        "BESS VO&M [EUR]": vom,
        "RES O&M, fixed + variable [EUR]": res_om,
        "Delivered energy, native load + EV charging [MWh]": delivered,
        "Consumed energy, native load + EV charging - V2G [MWh]": consumed,
        "Community energy cost, cash-flow [EUR/MWh]": (wheeling + uos + vom + res_om - profit) / consumed,
        "Community LMP, demand-weighted [EUR/MWh]": region_price,
        "Day-ahead traded volume [MWh]": vol["DA"],
        "Intraday traded volume [MWh]": vol["ID"],
        "Imbalance volume, |imbalance| [MWh]": float(np.abs(net["IMB"]).sum()),
        "EVs av. charging price [ct/kWh]": cs("Charge Cost") / ch.sum() * 100,
        "EVs av. discharging price [ct/kWh]": cs("Discharge Revenue") / dis.sum() * 100 if dis.sum() > 0 else np.nan,
        "EVs av. net charging cost [EUR/EV]": (cs("Charge Cost") - cs("Discharge Revenue")) / n_ev,
        "EV energy charged into batteries [MWh]": ev_in,
        "  V2G energy discharged to grid [MWh]": v2g,
        "  mobility consumption [MWh]": driving,
        "Fleet utilization [EFC per EV]": (ev_in + driving + v2g / eta) / 2 / fleet_mwh,
        "  of which V2G [EFC per EV]": v2g / eta / fleet_mwh,
        "BESS utilization [EFC]": (bl.sum() * eta_b + bg.sum() / eta_b) / 2 / bess_mwh,
        "Stored energy at the end, BESS + fleet [% of capacity]": 100 * (soc.iloc[-1] / 100 * bess_mwh + e.iloc[-1] / 1000) / (bess_mwh + fleet_mwh),
        **carbon,
    }


def price_series(run, key, index):
    """The run's input price (model_overview.csv column key: DA / ID / imbalance price file) on index."""
    s = pd.read_csv(RUNS / run.spec[key], sep=";")
    year = int(s.Year.iloc[0])
    return pd.Series(s.iloc[:, -1].to_numpy(float), index=pd.date_range(f"{year}-01-01", periods=len(s), freq="h")).reindex(index)


def ex_post_check(run, source):
    """Settlement run vs its ex-post value: imbalance = forecast error (+ battery change of the source), cash flow = source
    cash flow + imbalance settlement."""
    res = lambda r: r("Generator", "Solar G1", "Generation") + r("Generator", "Wind G1", "Generation")
    native = lambda r: r("Region", "Distribution BG Region", "Load") - r("Region", "Distribution BG Region", "Battery Load") - r.vehicles("Charging") / 1000
    bat = lambda r: r("Battery", "Stationary Battery", "Generation") - r("Battery", "Stationary Battery", "Load")
    expected = (res(run) - res(source)) - (native(run) - native(source)) + (bat(run) - bat(source))
    imb = run.market("IMB", "Sales") - run.market("IMB", "Purchases")
    p = price_series(run, "imbalance price file", expected.index)
    ex_post_rev = (expected.clip(lower=0) * p - (-expected).clip(lower=0) * (p + 2)).sum()
    return {"max |imbalance - expected| [kW]": 1000 * float((imb - expected).abs().max()),
            "PLEXOS imbalance revenue [EUR]": float(run.market("IMB", "Net Revenue").sum()),
            "ex-post imbalance revenue [EUR]": float(ex_post_rev)}


def load_runs(folder):
    out = {}
    for model, r in read_overview(folder).items():
        if not (folder / f"Model {model} Solution" / "Interval").exists():
            continue
        run = Run(folder, model)
        run.year, run.n_ev, run.source = int(r["year"]), int(r["EVs"]), r["flexibility pinned to"] or None
        run.spec = r  # sizing of the run: solar MW, wind MW, households MWh, business MWh, EV and battery parameters
        out[model] = run
    return out


def table(runs, models, check=False):
    """{column: KPI dict} of the given {column: model name}, and the settlement checks."""
    cols, checks = {}, {}
    for col, m in models.items():
        if m not in runs:
            continue
        run = runs[m]
        flex = runs[run.source] if run.source and run.source in runs else run
        cols[col] = kpis(run, run.year, run.n_ev, flex)
        if check and run.source and run.source in runs:
            checks[col] = ex_post_check(run, runs[run.source])
    return pd.DataFrame(cols), pd.DataFrame(checks)


def multiyear(runs, check=False):
    df, chk = table(runs, {(s, y): f"{y}_{code}" for s, code in STAGES.items() for y in YEARS}, check)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["scenario", "year"])
    return df, chk


def sweeps(runs, stage, check=False):
    code = STAGES[stage]
    models = {(sweep, level): f"{lvl or '2025'}_{code}" for sweep, (lvls, labels) in SWEEPS.items() for lvl, level in zip(lvls, labels)}
    df, chk = table(runs, models, check)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["sweep", "level"])
    return df, chk


def paper_rows(df):
    return pd.DataFrame({label: df.loc[kpi] * scale for label, kpi, scale in PAPER_ROWS}).T


def table8(my):
    """Table 8: the settled schedules (A.2, B.2, C.2) of each year."""
    cols = [(f"{s}.2", y) for y in YEARS for s in SCENARIOS]
    t = paper_rows(my[cols])
    t.columns = pd.MultiIndex.from_tuples([(y, s[0]) for s, y in cols], names=["year", "scenario"])
    return t


def table9(my):
    """Table 9: mean of 2023-2025 per stage, and the change of B.2 and C.2 against A.2: relative where the KPI is positive in
    every stage, else the difference (KPIs that are zero in A or change sign)."""
    m = my.T.groupby(level=0, sort=False).mean().T
    relative = (m.min(axis=1) > 0) & m[list(set(BASELINE.values()))].notna().all(axis=1)
    out = {}
    for label, kpi, scale in PAPER_ROWS:
        row = {s: m.loc[kpi, s] * scale for s in STAGES}
        for s in ["B.2", "C.2"]:
            d = m.loc[kpi, s] / m.loc[kpi, "A.2"] - 1 if relative[kpi] else (m.loc[kpi, s] - m.loc[kpi, "A.2"]) * scale
            row[f"change {s} vs A.2"] = f"{100 * d:+.1f} %" if relative[kpi] else (f"{d:+.1f}" if pd.notna(d) else "")
        out[label] = row
    return pd.DataFrame(out).T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=DEFAULT, help="runs folder: a path, or a name in ../runs/")
    ap.add_argument("--check", action="store_true", help="ex-post check of every settlement run")
    ap.add_argument("--out", default=None, help="output folder (default: results/)")
    args = ap.parse_args()
    global DATA, RUNS
    RUNS = runs_folder(args.folder)
    DATA = RUNS / "data_files"
    out = Path(args.out) if args.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    runs = load_runs(RUNS)

    my, my_chk = multiyear(runs, args.check)
    sw, sw_chk = sweeps(runs, SWEEP_STAGE, args.check)
    my.to_csv(out / "KPI_multiyear.csv", sep=";")
    sw.to_csv(out / "KPI_sweeps.csv", sep=";")
    t8, t9 = table8(my), table9(my)
    t8.to_csv(out / "table8_kpis_by_year.csv", sep=";", float_format="%.2f")
    t9.to_csv(out / "table9_three_year_mean.csv", sep=";", float_format="%.2f")
    with pd.option_context("display.width", 200, "display.float_format", "{:,.2f}".format):
        print("TABLE 8, settled schedules by year\n" + t8.to_string() + "\n\nTABLE 9, three-year mean\n" + t9.to_string())
    if args.check:
        chk = pd.concat([my_chk, sw_chk], axis=1).T
        chk.to_csv(out / "settlement_check.csv", sep=";", float_format="%.6g")
        worst = chk["max |imbalance - expected| [kW]"].max()
        gap = (chk["PLEXOS imbalance revenue [EUR]"] - chk["ex-post imbalance revenue [EUR]"]).abs().max()
        print(f"\nSETTLEMENT CHECK: {len(chk)} settlement runs, max |imbalance - expected| {worst:.3g} kW, "
              f"max |revenue - ex post| {gap:.3g} EUR")


if __name__ == "__main__":
    main()
