# Made by Francesco Maldonato on 10/11/2026
"""Results per EV and battery wear (paper Sections III-I and VI-G, Table 11, wear rows of Tables 8 and 9, Section VI-F).

    python3 ev_fleet_analysis.py            # runs/DRJ_MultiYear_v13_executed_logs -> results/

The fleet is modelled as four cohorts (PLEXOS Vehicle objects RC, RO, WF, WP), each with its own availability and trip
profile and vehicle type, standing for 19 / 46 / 27 / 8 identical vehicles (Units). Every result per EV is per vehicle of
a cohort; statistics over "the 100 EVs" weight the cohorts by their units.

Per cohort and optimisation run (X.1; the X.2 settlement replays the same EV schedule):
- energy bill at the charging station's hourly prices (Charge Cost / fleet charging, Discharge Revenue / fleet discharge),
  use-of-system fee, gain against the same cohort under V1G (scenario A);
- battery throughput (energy into the battery + out of it for V2G and driving, battery side), equivalent full cycles (EFC),
  rainflow depth of the SoC cycles, C-rates, mean SoC and time at high SoC;
- wear cost (Eq. 5, weighted Ah-throughput model of Preis & Biedenbach 2023) = 1.88 ct/kWh x throughput for the
  nickel-manganese-cobalt (NMC) packs of the vehicles (113 EUR/kWh, 3,000 EFC; 2,000-4,000 EFC as range; common.py);
- capacity loss of the V2G cycles if the cycle life were consumed linearly: V2G EFC x 20 % / cycle life [pp per year];
- break-even wear cost (Eq. 7): the gain against V1G divided by the added throughput, from the means over the EVs and years.

Writes into results/: ev_per_vehicle.csv (every cohort and run), ev_distribution.csv (min / max / mean / std over the
100 EVs per scenario and year), battery_degradation.csv (Table 11), battery_wear_by_year.csv (wear rows of Table 8) and
dod_share.csv (share of the cycled energy per depth of discharge).
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import (C_DEG, CYCLE_LIFE_RANGE, EVS, EV_TYPES, PACK, RESULTS, SOC0, UOS, WH_KM, YEARS, Run, ev_profiles, ev_units,
                    overview, rainflow, runs_folder, weighted_stats)

CYCLE_LIFE = CYCLE_LIFE_RANGE  # EFC to 80 % SoH
DOD_BINS = [0, 0.05, 0.10, 0.20, 0.40, 1.0]
SCEN = ["A", "B", "C"]


def station_prices(run, evs):
    """Hourly charge and discharge price at the charging station [EUR/kWh]: Charge Cost / fleet charging, Discharge Revenue /
    fleet discharging (NaN in hours without the flow)."""
    ch = sum(run("Vehicle", ev, "Charging") for ev in evs)
    dis = sum(run("Vehicle", ev, "Discharging") for ev in evs)
    cost, rev = run("Charging Station", "CS1", "Charge Cost"), run("Charging Station", "CS1", "Discharge Revenue", 0 * ch)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (cost / ch).where(ch > 1e-9), (rev / dis).where(dis > 1e-9)


def per_vehicle(folder, model, spec, year):
    """Per-vehicle results of the four cohorts of one run, and their rainflow cycles."""
    run = Run(folder, model)
    idx = run("Generator", "Solar G1", "Generation").index
    prof = ev_profiles(folder, year, idx)
    p_ch, p_dis = station_prices(run, EVS)
    cap, eta = spec["EV kWh"], spec["EV efficiency %"] / 100
    units = ev_units(spec)
    rows, cycles = [], []
    for ev in EVS:
        n = units[ev]
        if n < 0.5:  # a cohort absent from the fleet (fleet-mix ends)
            continue
        ch = run("Vehicle", ev, "Charging") / n  # kW per vehicle, grid side
        dis = run("Vehicle", ev, "Discharging", 0 * ch) / n
        e = run("Vehicle", ev, "Energy") / n  # kWh per vehicle
        conn, km = prof[ev]
        drive = km * WH_KM[ev] / 1000  # kWh per vehicle and hour
        soc = e / cap
        bill = (ch * p_ch.fillna(0)).sum() - (dis * p_dis.fillna(0)).sum()
        e_in, e_v2g_out, e_drive = (ch * eta).sum(), (dis / eta).sum(), drive.sum()
        thr = e_in + e_v2g_out + e_drive  # battery side
        rf = rainflow(np.r_[SOC0, soc.to_numpy()])
        rng, cnt = np.array([r for r, _ in rf]), np.array([c for _, c in rf])
        dod_efc = float((rng * cnt).sum())  # rainflow EFC (a cycle of depth d = d full cycles)
        for lo, hi in zip(DOD_BINS[:-1], DOD_BINS[1:]):
            m = (rng > lo) & (rng <= hi)
            cycles.append({"model": model, "EV": ev, "DoD bin": f"{100 * lo:.0f}-{100 * hi:.0f} %", "cycles": float(cnt[m].sum()),
                           "EFC in bin": float((rng[m] * cnt[m]).sum())})
        c_rate = pd.concat([ch * eta, dis / eta], axis=1).max(axis=1) / cap
        rows.append({
            "model": model, "year": year, "EV": ev, "type": EV_TYPES[ev], "units": n,
            "connected share [%]": 100 * conn.mean(), "driving [km]": km.sum(), "driving energy [kWh]": e_drive,
            "charged, grid side [kWh]": ch.sum(), "V2G, grid side [kWh]": dis.sum(),
            "energy bill [EUR/EV]": bill, "UoS fee [EUR/EV]": UOS / 1000 * (ch.sum() + dis.sum()),
            "avg charge price [ct/kWh]": 100 * (ch * p_ch.fillna(0)).sum() / ch.sum(),
            "avg V2G price [ct/kWh]": 100 * (dis * p_dis.fillna(0)).sum() / dis.sum() if dis.sum() > 0 else np.nan,
            "throughput, battery side [kWh]": thr, "EFC [-]": thr / 2 / cap, "of which V2G EFC [-]": e_v2g_out / cap,
            "rainflow EFC [-]": dod_efc, "rainflow cycles [-]": float(cnt.sum()),
            "DoD p50 [%]": 100 * float(np.median(np.repeat(rng, np.maximum(1, (2 * cnt).astype(int))))) if len(rng) else np.nan,
            "DoD max [%]": 100 * float(rng.max()) if len(rng) else np.nan,
            "mean SoC [%]": 100 * soc.mean(), "time at SoC > 80 % [%]": 100 * (soc > 0.8).mean(),
            "C-rate p95 when active [1/h]": float(c_rate[c_rate > 1e-6].quantile(0.95)) if (c_rate > 1e-6).any() else 0.0,
            "C-rate max [1/h]": float(c_rate.max()),
        })
    return rows, cycles


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="DRJ_MultiYear_v13_executed_logs")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    folder = runs_folder(a.folder)
    out = Path(a.out) if a.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    ov = overview(folder)
    rows, cycles = [], []
    for y in YEARS:
        for s in SCEN:
            m = f"{y}_{s}1"
            r, cy = per_vehicle(folder, m, ov[m], y)
            rows += r
            cycles += cy
    df = pd.DataFrame(rows)
    df["scenario"] = df.model.str[-2]
    # gain of each EV against the same EV under V1G (scenario A, same year)
    a_bill = df[df.scenario == "A"].set_index(["year", "EV"])["energy bill [EUR/EV]"]
    a_uos = df[df.scenario == "A"].set_index(["year", "EV"])["UoS fee [EUR/EV]"]
    a_thr = df[df.scenario == "A"].set_index(["year", "EV"])["throughput, battery side [kWh]"]
    key = list(zip(df.year, df.EV))
    df["gain vs V1G [EUR/EV]"] = [a_bill[k] for k in key] - df["energy bill [EUR/EV]"]
    df["gain vs V1G incl. UoS [EUR/EV]"] = [a_bill[k] + a_uos[k] for k in key] - df["energy bill [EUR/EV]"] - df["UoS fee [EUR/EV]"]
    df["extra throughput vs V1G [kWh]"] = df["throughput, battery side [kWh]"] - [a_thr[k] for k in key]
    for n in CYCLE_LIFE:
        df[f"degradation cost, NMC {n} EFC [EUR/EV]"] = PACK / (2 * n) * df["throughput, battery side [kWh]"]
    with np.errstate(invalid="ignore", divide="ignore"):
        df["break-even degradation factor [ct/kWh]"] = 100 * df["gain vs V1G [EUR/EV]"] / df["extra throughput vs V1G [kWh]"]
        df["break-even degradation factor incl. UoS [ct/kWh]"] = 100 * df["gain vs V1G incl. UoS [EUR/EV]"] / df["extra throughput vs V1G [kWh]"]
    df.to_csv(out / "ev_per_vehicle.csv", sep=";", index=False, float_format="%.4f")

    # distribution over the 100 EVs (units-weighted), per scenario and year, and over all three years (Section VI-F)
    stats_rows = []
    kpis = ["energy bill [EUR/EV]", "UoS fee [EUR/EV]", "gain vs V1G [EUR/EV]", "gain vs V1G incl. UoS [EUR/EV]",
            "V2G, grid side [kWh]", "EFC [-]", "degradation cost, NMC 3000 EFC [EUR/EV]"]
    for s in SCEN:
        for y in YEARS + ["2023-2025"]:
            sub = df[(df.scenario == s) & ((df.year == y) if y != "2023-2025" else True)]
            for k in kpis:
                st = weighted_stats(sub[k], sub.units)
                stats_rows.append({"scenario": s, "year": y, "KPI": k, **st, "n EV-years": int(sub.units.sum())})
    dist = pd.DataFrame(stats_rows)
    dist.to_csv(out / "ev_distribution.csv", sep=";", index=False, float_format="%.3f")

    # battery wear per scenario (Table 11; units-weighted means over EVs and years)
    deg_cols = ["throughput, battery side [kWh]", "EFC [-]", "of which V2G EFC [-]", "rainflow EFC [-]", "rainflow cycles [-]",
                "DoD p50 [%]", "DoD max [%]", "mean SoC [%]", "time at SoC > 80 % [%]", "C-rate p95 when active [1/h]",
                "C-rate max [1/h]"] + [f"degradation cost, NMC {n} EFC [EUR/EV]" for n in CYCLE_LIFE] + \
               ["gain vs V1G [EUR/EV]", "gain vs V1G incl. UoS [EUR/EV]", "extra throughput vs V1G [kWh]"]
    deg = df.groupby("scenario").apply(lambda g: pd.Series({c: np.average(g[c], weights=g.units) for c in deg_cols}), include_groups=False)
    for s in deg.index:  # break-even from the mean gain and mean extra throughput
        x = deg.loc[s, "extra throughput vs V1G [kWh]"]
        deg.loc[s, "break-even degradation factor [ct/kWh]"] = 100 * deg.loc[s, "gain vs V1G [EUR/EV]"] / x if x > 0 else np.nan
        deg.loc[s, "break-even degradation factor incl. UoS [ct/kWh]"] = 100 * deg.loc[s, "gain vs V1G incl. UoS [EUR/EV]"] / x if x > 0 else np.nan
    deg["wear cost, paper (NMC 3000 EFC) [EUR/EV]"] = C_DEG * deg["throughput, battery side [kWh]"]
    deg["added wear vs V1G (NMC 3000 EFC) [EUR/EV]"] = C_DEG * deg["extra throughput vs V1G [kWh]"]
    for n in CYCLE_LIFE:
        deg[f"capacity loss of the V2G cycles, {n} EFC life [pp/a]"] = 20.0 * deg["of which V2G EFC [-]"] / n
    for yrs in [10, 15]:
        deg[f"EFC after {yrs} years [-]"] = yrs * deg["EFC [-]"]
        for n in CYCLE_LIFE:
            deg[f"share of {n}-EFC cycle life used in {yrs} years [%]"] = 100 * yrs * deg["EFC [-]"] / n
    deg.T.to_csv(out / "battery_degradation.csv", sep=";", float_format="%.3f")
    # per year (wear rows of Table 8; break-even per year): units-weighted fleet means
    by_year = []
    for (y, s), g in df.groupby(["year", "scenario"]):
        w = g.units
        thr, x, gain = (np.average(g[c], weights=w) for c in
                        ["throughput, battery side [kWh]", "extra throughput vs V1G [kWh]", "gain vs V1G [EUR/EV]"])
        by_year.append({"year": y, "scenario": s, "throughput, battery side [kWh]": thr, "EFC [-]": np.average(g["EFC [-]"], weights=w),
                        "wear cost, NMC 3000 EFC [EUR/EV]": C_DEG * thr, "gain vs V1G [EUR/EV]": gain,
                        "extra throughput vs V1G [kWh]": x, "added wear vs V1G [EUR/EV]": C_DEG * x,
                        "break-even wear cost [ct/kWh]": 100 * gain / x if x > 0 else np.nan})
    pd.DataFrame(by_year).to_csv(out / "battery_wear_by_year.csv", sep=";", index=False, float_format="%.3f")
    # share of the cycled energy per depth of discharge (Table 11: energy in cycles deeper than 40 %)
    share = pd.DataFrame(cycles).merge(df[["model", "EV", "units", "scenario"]], on=["model", "EV"])
    share["w EFC"] = share["EFC in bin"] * share.units
    share["w cycles"] = share["cycles"] * share.units
    dod_share = share.groupby(["scenario", "DoD bin"], sort=False)[["w cycles", "w EFC"]].sum()
    dod_share = dod_share.div(dod_share.groupby(level=0).transform("sum")) * 100
    dod_share.columns = ["share of cycles [%]", "share of cycled energy [%]"]
    dod_share.to_csv(out / "dod_share.csv", sep=";", float_format="%.2f")

    print(deg.T.round(2).to_string())
    print(dist[dist.year == "2023-2025"].round(1).to_string(index=False))
    print(dod_share.round(1).to_string())


if __name__ == "__main__":
    main()
