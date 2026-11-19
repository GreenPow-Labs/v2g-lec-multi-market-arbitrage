#!/usr/bin/env python3
# Made by Francesco Maldonato on 10/11/2026
"""Statistics, validation and figures of the EV dataset (paper Section IV-G, Table 6, Figs. 3-5).

    python3 analyse_ev_dataset.py          # after make_ev_dataset.py generate; writes into ../../results/

1. Inputs: Straub's Berlin working day (inputs/): hourly arrivals and departures at home and at work, parking durations.
2. Reproduction: the generated sessions (ELVIS mixtures, chained) against those inputs, weekdays Monday-Thursday.
3. Generated dataset, per cohort and for the fleet mix: weekly connected share and driving (trip events), stays and
   absences per week, arrival/departure hours, stay durations, distances, energy per absence, en-route share (Table 6).
4. Validation of the charging shape: ELVIS simulates the sessions with its uncontrolled policy (UC: 11 kW from arrival
   until full), four weeks of March 2025, 15-min steps; the Monday-Thursday mean hourly power of residents and employees
   is compared with Straub's charging scenarios recomputed from his trips (Pearson r, peak hour, peak/mean).
5. Connected share of the fleet by hour across the fleet mix (0-100 % residents), against two reference fleets in
   inputs/: the emobpy fleet of the German mobility survey MiD 2017 (100 residents' EVs) and the first submission's
   ELVIS charging park.

Writes into results/: ev_dataset_statistics.csv (Table 6), ev_dataset_reproduction.csv, ev_dataset_validation.csv,
ev_dataset_hourly.csv, ev_dataset_weekly.csv and the figures ev_dataset_inputs.pdf (Fig. 3), ev_dataset_validation.pdf
(Fig. 4) and ev_dataset_weekly.pdf (Fig. 5).
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "postprocessing"))
import make_ev_dataset as mf  # noqa: E402

LEVELS = [0.0, 0.25, 0.5, 0.65, 0.75, 1.0]  # residents' share of the fleet: sweep levels and base
GROUP = {"residential": ["RC", "RO"], "workplace": ["WF", "WP"]}
RATE = 11.0
FIRST_UNITS = (30, 20, 30, 20)  # the first submission's fleet: units of its four EV objects


def weekly(a, idx):
    """Mean over the weeks of an hourly array (vehicles x hours or hours) -> 168 values, Monday 0 h first."""
    a = np.atleast_2d(a).mean(axis=0)
    h = idx.day_of_week * 24 + idx.hour
    return pd.Series(a).groupby(np.asarray(h)).mean().to_numpy()


def circ_mean_hour(h, day_start=mf.DAY_START):
    """Mean and std of clock hours, counted from DAY_START so that night hours stay with the evening."""
    x = np.mod(np.asarray(h) - day_start, 24)
    return (x.mean() + day_start) % 24, x.std()


def load_pool():
    idx = pd.date_range(mf.START, periods=mf.HOURS, freq="h")
    pool = {c: np.load(mf.POOL / f"{c}.npz") for c in mf.COHORTS}
    present = {c: z["present"].astype(np.float32) for c, z in pool.items()}
    km = {c: z["km"].astype(np.float32) for c, z in pool.items()}
    ses = pd.read_csv(mf.POOL / "sessions.csv.gz")
    return idx, present, km, ses


def fleet_mix(per_cohort, share, inp):
    u = mf.units(share, inputs=inp)
    w = dict(zip(mf.COHORTS, u))
    return sum(w[c] * per_cohort[c] for c in mf.COHORTS) / sum(u), w


def session_frame(ses):
    s = ses.copy()
    t0 = mf.START
    s["arrival"] = t0 + pd.to_timedelta(s.arrival_h, unit="h")
    s["departure"] = t0 + pd.to_timedelta(s.departure_h, unit="h")
    s["stay_h"] = s.departure_h - s.arrival_h
    s["arr_hour"] = s.arrival.dt.hour + s.arrival.dt.minute / 60
    s["dep_hour"] = s.departure.dt.hour + s.departure.dt.minute / 60
    s["arr_wd"] = s.arrival.dt.day_of_week
    s["dep_wd"] = s.departure.dt.day_of_week
    return s[(s.arrival_h > 0) & (s.departure_h < mf.HOURS)]


def statistics(idx, present, km, s, inp):
    rows = {}
    weeks = mf.HOURS / 168
    wd = np.asarray(idx.day_of_week)
    summ = pd.read_csv(mf.POOL / "summary.csv", sep=";").set_index("cohort")
    for c, meta in mf.COHORTS.items():
        x = s[s.cohort == c]
        n = x.vehicle.nunique()
        p = present[c]
        wk = weekly(p, idx)
        a_m, a_s = circ_mean_hour(x.arr_hour[x.arr_wd < 4])
        d_m, d_s = circ_mean_hour(x.dep_hour[x.dep_wd < 4])
        ab = x.dropna(subset=["km before arrival"])
        rows[c] = {
            "cohort": meta["name"], "PLEXOS object": meta["ev"], "Wh/km": meta["wh_km"],
            "stays per vehicle and week": len(x) / n / weeks,
            "arrival hour, Mon-Thu, mean": a_m, "arrival hour, std [h]": a_s,
            "arrival peak hour, Mon-Thu": int(np.bincount(np.floor(x.arr_hour[x.arr_wd < 4]).astype(int), minlength=24).argmax()),
            "departure hour, Mon-Thu, mean": d_m, "departure hour, std [h]": d_s,
            "departure peak hour, Mon-Thu": int(np.bincount(np.floor(x.dep_hour[x.dep_wd < 4]).astype(int) % 24, minlength=24).argmax()),
            "stay [h], mean": x.stay_h.mean(), "stay [h], std": x.stay_h.std(),
            "stay [h], p10": x.stay_h.quantile(0.1), "stay [h], median": x.stay_h.median(), "stay [h], p90": x.stay_h.quantile(0.9),
            "absences (trip tours) per vehicle and week": len(ab) / n / weeks,
            "distance per absence [km], mean": ab["km before arrival"].mean(), "distance per absence [km], std": ab["km before arrival"].std(),
            "energy per absence from the community [kWh], mean": ab["kWh before arrival (community)"].mean(),
            "energy per absence from the community [kWh], p95": ab["kWh before arrival (community)"].quantile(0.95),
            "annual distance [km]": summ.loc[c, "km/a"], "en-route share of driving energy [%]": summ.loc[c, "en-route share of driving energy [%]"],
            "connected share [%], all hours": 100 * p.mean(),
            "connected share [%], weekdays": 100 * p[:, wd < 5].mean(), "connected share [%], weekends": 100 * p[:, wd >= 5].mean(),
            "connected share of the week [%], min hour": 100 * wk.min(), "connected share of the week [%], max hour": 100 * wk.max(),
            "driving [km per vehicle and day]": km[c].sum() / km[c].shape[0] / mf.DAYS,
        }
    df = pd.DataFrame(rows).T
    # fleet rows at the sweep levels (Units-weighted)
    for share in LEVELS:
        conn, w = fleet_mix({c: present[c].mean(axis=0) for c in mf.COHORTS}, share, inp)
        kmf, _ = fleet_mix({c: km[c].mean(axis=0) for c in mf.COHORTS}, share, inp)
        wk = weekly(conn, idx)
        df.loc[f"fleet {int(100 * share)} % residents"] = pd.Series({
            "cohort": f"Units RC/RO/WF/WP = {'/'.join(str(w[c]) for c in mf.COHORTS)}",
            "connected share [%], all hours": 100 * conn.mean(),
            "connected share [%], weekdays": 100 * conn[wd < 5].mean(), "connected share [%], weekends": 100 * conn[wd >= 5].mean(),
            "connected share of the week [%], min hour": 100 * wk.min(), "connected share of the week [%], max hour": 100 * wk.max(),
            "driving [km per vehicle and day]": kmf.sum() / mf.DAYS,
            "annual distance [km]": kmf.sum() * 365 / mf.DAYS})
    return df


def reproduction(s, inp_hourly):
    """Generated Monday-Thursday arrival/departure hours against Straub's (fraction of the day's events per hour)."""
    out = {}
    pairs = {"arrival home, commuter day": ("RC", "arr"), "departure home, commuter day": ("RC", "dep"),
             "arrival home, other use": ("RO", "arr"), "departure home, other use": ("RO", "dep"),
             "arrival work, full day": ("WF", "arr"), "departure work, full day": ("WF", "dep"),
             "arrival work, part day": ("WP", "arr"), "departure work, part day": ("WP", "dep")}
    gen = {}
    for col, (c, kind) in pairs.items():
        x = s[s.cohort == c]
        h = x[f"{kind}_hour"][x[f"{kind}_wd"] < 4]
        g = np.bincount(np.floor(h).astype(int) % 24, minlength=24) / len(h)
        gen[col] = g
        ref = inp_hourly[col].to_numpy()
        out[col] = {"r": float(np.corrcoef(g, ref)[0, 1]), "sum |diff| [%]": float(50 * np.abs(g - ref).sum())}
    return pd.DataFrame(out).T, pd.DataFrame(gen)


def soc_events(x):
    """Arrival SoC of each stay of one vehicle under uncontrolled charging (full at the start)."""
    soc, out = 1.0, []
    for _, r in x.sort_values("arrival_h").iterrows():
        e = r["kWh before arrival (community)"]
        soc = max(0.0, soc - (0.0 if np.isnan(e) else e) / mf.CAPACITY)
        out.append(soc)
        soc = min(1.0, soc + RATE * r.stay_h / mf.CAPACITY)
    return out


def elvis_uc(s, cohorts, start, weeks, n_per_cohort):
    """Aggregate uncontrolled charging load [kW] of the cohorts' sessions, simulated with ELVIS (15-min steps)."""
    from elvis.config import ScenarioConfig
    from elvis.simulate import simulate
    from elvis.charging_event import ChargingEvent
    from elvis.vehicle import ElectricVehicle
    from elvis.battery import EVBattery
    from elvis.set_up_infrastructure import wallbox_infrastructure
    from elvis.utility.elvis_general import num_time_steps
    end = start + dt.timedelta(weeks=weeks) - dt.timedelta(minutes=15)
    ev = ElectricVehicle("VW", "ID", EVBattery(capacity=mf.CAPACITY, max_charge_power=RATE, min_charge_power=0, efficiency=1), 1.0)
    events = []
    for c, n in zip(cohorts, n_per_cohort):
        x = s[(s.cohort == c) & (s.vehicle < n)].copy()
        x["soc"] = np.nan
        for v, g in x.groupby("vehicle"):
            x.loc[g.index, "soc"] = soc_events(g)  # chained SoC over the whole year
        x = x[(x.arrival >= pd.Timestamp(start)) & (x.arrival < pd.Timestamp(end))]
        for _, r in x.iterrows():
            arrival = r.arrival.ceil("15min")  # ELVIS connects arrivals at its time steps (its GMM sampler rounds up too)
            stay = min(r.stay_h - (arrival - r.arrival) / pd.Timedelta(hours=1), (pd.Timestamp(end) - arrival) / pd.Timedelta(hours=1))
            if stay > 0 and arrival <= pd.Timestamp(end):
                events.append(ChargingEvent(arrival.to_pydatetime(), float(stay), float(r.soc), ev))
    events.sort(key=lambda e: e.arrival_time)
    cfg = ScenarioConfig()
    cfg.with_charging_events(events)
    cfg.with_infrastructure(wallbox_infrastructure(sum(n_per_cohort), RATE, power_transformer=10000))
    cfg.with_scheduling_policy("UC")
    cfg.with_vehicle_types([ev])
    cfg.with_disconnect_by_time(True)
    cfg.with_queue_length(len(events))
    cfg.with_transformer_preload(0)
    real = cfg.create_realisation(start, end, dt.timedelta(minutes=15))
    res = simulate(real)
    load = np.asarray(res.aggregate_load_profile(num_time_steps(start, end, dt.timedelta(minutes=15))), float)
    return pd.Series(load, index=pd.date_range(start, periods=len(load), freq="15min"))


def spread_rule(s, cohorts, n_per_cohort):
    """RLI's rule on the same sessions: each stay charges the energy of the absence before it at constant power over
    the whole stay. Mean hourly power over Monday-Thursday [kW]."""
    x = s[s.cohort.isin(cohorts)]
    x = pd.concat([x[(x.cohort == c) & (x.vehicle < n)] for c, n in zip(cohorts, n_per_cohort)])
    x = x.dropna(subset=["kWh before arrival (community)"])
    power = mf.hourly(list(zip(x.arrival_h, x.departure_h)), mf.HOURS, x["kWh before arrival (community)"].to_numpy())
    idx = pd.date_range(mf.START, periods=mf.HOURS, freq="h")
    keep = np.asarray(idx.day_of_week < 4)
    return pd.Series(power[keep]).groupby(np.asarray(idx.hour)[keep]).mean().to_numpy()


def first_submission():
    """Connected share by hour of the day (weekdays, units-weighted) of the first submission's ELVIS charging park, 2025."""
    s = pd.read_csv(HERE / "inputs" / "first_submission_share_2025.csv", sep=";")
    i = pd.date_range("2025-01-01", periods=len(s), freq="h")
    conn = sum(u * (s[c].to_numpy(float) > 0) for u, c in zip(FIRST_UNITS, s.columns[4:])) / sum(FIRST_UNITS)
    keep = np.asarray(i.day_of_week < 5)
    return {"first submission (ELVIS charging park)": pd.Series(conn[keep]).groupby(np.asarray(i.hour)[keep]).mean().to_numpy()}


def uncontrolled(conn, energy, rate=RATE):
    """Charging power [kW] of a vehicle that charges at rate from plug-in until the energy driven is back."""
    need, p = 0.0, np.zeros(len(conn))
    for t in range(len(conn)):
        if conn[t] and need > 0:
            p[t] = min(rate, need)
            need -= p[t]
        need += energy[t]
    return p


COLUMN_IN = 3.5  # IEEE two-column template: one column (88.9 mm)
SWEEP_GRAYS = {0.0: "#bdbcb8", 0.25: "#a2a19d", 0.5: "#878682", 0.75: "#6c6b67", 1.0: "#3a3936"}  # one-hue ramp, fleet mix


def duration_density(park_q, key, lo=0.0, hi=np.inf, edges=np.arange(0, 24.5, 1.0)):
    """Share of stays per hour of parking duration [% per h] from a quantile table (Straub's stays), optionally only the
    stays in [lo, hi) h, renormalised: the work stays split at FULL_DAY into full-day and part-day stays."""
    q, d = park_q.index.to_numpy(float), park_q[key].to_numpy(float)
    cdf = lambda x: np.interp(x, d, q, left=0.0, right=1.0)
    f_lo, f_hi = cdf(lo), cdf(min(hi, d.max()))
    e = np.clip(edges, lo, min(hi, d.max()))
    return 100 * np.diff(cdf(e)) / (f_hi - f_lo) / np.diff(edges)


def emobpy_reference(year=2025):
    """emobpy / MiD 2017 fleet of 100 residents' EVs (inputs/): connected share by hour on Monday-Friday and the uncontrolled
    charging shape on Monday-Thursday (11 kW from plug-in until the energy driven is back), normalised to its daily mean."""
    plugged = pd.read_csv(HERE / "inputs" / "emobpy_MiD2017_plugged.csv", sep=";", index_col=0, parse_dates=True)
    kmp = pd.read_csv(HERE / "inputs" / "emobpy_MiD2017_km.csv", sep=";", index_col=0, parse_dates=True)
    yr = slice(f"{year}-01-01", f"{year}-12-31 23:00")
    plugged, kmp = plugged.loc[yr], kmp.loc[yr]
    idx = plugged.index
    conn = plugged.to_numpy() > 0
    charge = sum(uncontrolled(conn[:, j], kmp.iloc[:, j].to_numpy(float) * 173 / 1000) for j in range(conn.shape[1]))
    wd5, wd4, hr = np.asarray(idx.dayofweek < 5), np.asarray(idx.dayofweek < 4), np.asarray(idx.hour)
    connected = pd.Series(conn.mean(axis=1)[wd5]).groupby(hr[wd5]).mean().to_numpy()
    shape = pd.Series(charge[wd4]).groupby(hr[wd4]).mean().to_numpy()
    return connected, shape


def figures(out, inp_hourly, park_q, wk, wkm, val, hourly_cmp):
    """Figs. 3-5 of the paper, one IEEE column each; only Straub's data, the emobpy / MiD 2017 reference and our own
    computations are drawn (the RLI curves digitised in Straub's material and the first submission's fleet are not).
    ev_dataset_inputs (2 x 2): arrivals and departures by hour of (a) the residents' EVs at home and (b) the employees' EVs at
    work, and their parking durations (c, d; work stays split into full-day and part-day stays), Straub's Berlin working day.
    ev_dataset_validation (1 x 2): (a) uncontrolled-charging shape of the generated sessions (ELVIS) against Straub's rule
    recomputed from his trips and the emobpy / MiD 2017 fleet; (b) connected share of the fleet by hour at the fleet-mix
    levels, the base fleet and the emobpy / MiD 2017 fleet. Legend below the panels.
    ev_dataset_weekly (2 x 1): (a) connected share per cohort and of the fleet, (b) driving (trip events) per EV and hour."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from common import GRID, INK, MUTED, PALETTE, paper_style
    paper_style()
    plt.rcParams.update({"font.size": 6.5, "axes.titlesize": 6.5, "axes.labelsize": 6.5, "xtick.labelsize": 6, "ytick.labelsize": 6,
                         "legend.fontsize": 5.8, "axes.linewidth": 0.5, "xtick.major.width": 0.5, "ytick.major.width": 0.5,
                         "xtick.major.size": 2, "ytick.major.size": 2, "axes.titlepad": 3, "axes.labelpad": 1.5})
    col = {"RC": PALETTE[0], "RO": PALETTE[1], "WF": PALETTE[2], "WP": PALETTE[3]}
    EMOBPY = "#3a3936"  # text-ink gray: a reference, not a cohort
    hrs = np.arange(24)
    x24 = np.arange(25)
    step = lambda a, v, **kw: a.step(x24, np.r_[v, v[-1]], where="post", **kw)
    leg = dict(frameon=False, handlelength=1.6, handletextpad=0.4, borderaxespad=0.2, labelspacing=0.25, columnspacing=0.9)

    # ---------------- inputs: (a, b) arrivals and departures, (c, d) parking durations
    fig, ax = plt.subplots(2, 2, figsize=(COLUMN_IN, 3.05), gridspec_kw={"height_ratios": [1.0, 0.72], "hspace": 0.62, "wspace": 0.34})
    fig.subplots_adjust(left=0.115, right=0.985, top=0.955, bottom=0.11)
    style = [Line2D([], [], color=MUTED, lw=0.9, ls="-", label="arrival"), Line2D([], [], color=MUTED, lw=0.9, ls="--", label="departure")]
    groups = [("Residents' EVs at home", [("RC", "home, commuter day"), ("RO", "home, other use")],
               [("commuter day", "RC", "overnight stay at home, commuter day [h]", 0, np.inf),
                ("other use", "RO", "overnight stay at home, other use [h]", 0, np.inf)], 30),
              ("Employees' EVs at work", [("WF", "work, full day"), ("WP", "work, part day")],
               [(f"full day ($\\geq${mf.FULL_DAY:g} h)", "WF", "work stay [h]", mf.FULL_DAY, np.inf),
                (f"part day (<{mf.FULL_DAY:g} h)", "WP", "work stay [h]", 0, mf.FULL_DAY)], 60)]
    edges = np.arange(0, 24.5, 1.0)
    for j, (who, events, stays, ymax) in enumerate(groups):
        a = ax[0, j]
        for c, key in events:
            where, kind = key.split(", ", 1)
            step(a, 100 * inp_hourly[f"arrival {where}, {kind}"].to_numpy(), color=col[c], lw=0.9, ls="-")
            step(a, 100 * inp_hourly[f"departure {where}, {kind}"].to_numpy(), color=col[c], lw=0.9, ls="--")
        a.set_xlim(0, 24); a.set_xticks(range(0, 25, 6)); a.set_ylim(0, 40); a.set_yticks(range(0, 41, 10))
        a.set_xlabel("Hour of the working day", labelpad=1)
        a.set_title(f"({'ab'[j]}) {who}: events", loc="left")
        a.legend(handles=style, loc="upper right", **leg)
        b = ax[1, j]
        for lab, c, key, lo, hi in stays:
            v = duration_density(park_q, key, lo, hi, edges)
            b.step(edges, np.r_[v, v[-1]], where="post", color=col[c], lw=0.9, label=lab)
        b.set_xlim(0, 24); b.set_xticks(range(0, 25, 6)); b.set_ylim(0, ymax); b.set_yticks(range(0, ymax + 1, ymax // 3))
        b.set_xlabel("Parking duration [h]", labelpad=1)
        b.set_title(f"({'cd'[j]}) {who}: stays", loc="left")
        b.legend(loc="upper left" if j == 0 else "upper right", **leg)
    ax[0, 0].set_ylabel("Events [% per h]"); ax[1, 0].set_ylabel("Stays [% per h]")
    for a in ax.flat:
        a.grid(color=GRID, lw=0.4)
    fig.savefig(out / "ev_dataset_inputs.pdf", dpi=300, metadata={"CreationDate": None})  # no time stamp
    plt.close(fig)

    # ---------------- validation: (a) uncontrolled charging, (b) connected share; legend below
    emob_conn, emob_uc = val.get("emobpy (MiD 2017) connected"), val.get("emobpy (MiD 2017) UC")
    fig, ax = plt.subplots(1, 2, figsize=(COLUMN_IN, 2.0), gridspec_kw={"wspace": 0.34})
    fig.subplots_adjust(left=0.115, right=0.985, top=0.915, bottom=0.335)
    a = ax[0]
    lines = [("ELVIS UC, residents", col["RO"], "-", 1.1, "ELVIS, residents"),
             ("charging at home, Straub home-charging scenario", col["RO"], "--", 0.8, "Straub, home"),
             ("ELVIS UC, employees", col["WF"], "-", 1.1, "ELVIS, employees"),
             ("charging at work, Straub work-charging scenario 22 kW", col["WF"], "--", 0.8, "Straub, work")]
    handles = []
    for key, color, ls, lw, lab in lines:
        handles += a.plot(hrs + 0.5, val[key] / val[key].mean(), color=color, ls=ls, lw=lw, label=lab)
    if emob_uc is not None:
        handles += a.plot(hrs + 0.5, emob_uc / emob_uc.mean(), color=EMOBPY, ls=":", lw=1.0, label="emobpy (MiD 2017)")
    a.set_xlim(0, 24); a.set_xticks(range(0, 25, 6)); a.set_ylim(0, 6); a.set_yticks(range(0, 7, 2))
    a.set_xlabel("Hour (Monday–Thursday)", labelpad=1); a.set_ylabel("Power / daily mean [–]")
    a.set_title("(a) Uncontrolled charging", loc="left")
    a = ax[1]
    for share, color in SWEEP_GRAYS.items():
        a.plot(hrs + 0.5, 100 * hourly_cmp[f"fleet, {int(100 * share)} % residents"], color=color, lw=0.8)
    base = 100 * hourly_cmp[f"base fleet, {int(100 * mf.RESIDENTIAL_SHARE)} % residents"]
    a.plot(hrs + 0.5, base, color=INK, lw=1.4)
    if emob_conn is not None:
        a.plot(hrs + 0.5, 100 * emob_conn, color=EMOBPY, ls=":", lw=1.0)
    for share in SWEEP_GRAYS:  # direct labels at the line ends, in text ink
        v = 100 * hourly_cmp[f"fleet, {int(100 * share)} % residents"]
        a.text(23.7, v[-1] + 1.5, f"{int(100 * share)}", color=MUTED, fontsize=5.2, ha="right", va="bottom")
    a.set_xlim(0, 24); a.set_xticks(range(0, 25, 6)); a.set_ylim(0, 105); a.set_yticks(range(0, 101, 25))
    a.set_xlabel("Hour (Monday–Friday)", labelpad=1); a.set_ylabel("Fleet connected [%]")
    a.set_title("(b) Connected share of the fleet", loc="left")
    handles += [Line2D([], [], color=SWEEP_GRAYS[0.5], lw=0.8, label="fleet mix, 0–100 % residents' EVs"),
                Line2D([], [], color=INK, lw=1.4, label=f"base fleet, {int(100 * mf.RESIDENTIAL_SHARE)} % residents' EVs")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.53, 0.0), ncol=3, **leg)
    for a in ax:
        a.grid(color=GRID, lw=0.4)
    fig.savefig(out / "ev_dataset_validation.pdf", dpi=300, metadata={"CreationDate": None})  # no time stamp
    plt.close(fig)

    # ---------------- generated week (one column)
    fig, ax = plt.subplots(2, 1, figsize=(COLUMN_IN, 2.6), gridspec_kw={"hspace": 0.38, "height_ratios": [1.2, 1]})
    fig.subplots_adjust(left=0.115, right=0.985, top=0.915, bottom=0.07)
    t = np.arange(168)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    a = ax[0]
    for c in mf.COHORTS:
        a.plot(t, 100 * wk[c], color=col[c], lw=0.7, label=c)
    a.plot(t, 100 * wk["fleet"], color=INK, lw=1.2, label=f"fleet ({int(100 * mf.RESIDENTIAL_SHARE)} % res.)")
    a.set_ylabel("Connected [%]"); a.set_ylim(0, 100); a.set_yticks(range(0, 101, 25))
    a.set_title("(a) Connected to the community's charging points", loc="left", pad=11)
    a.legend(ncol=5, loc="lower left", bbox_to_anchor=(-0.01, 0.985), **{**leg, "handlelength": 1.2, "columnspacing": 0.9})
    a = ax[1]
    for g, cs in GROUP.items():
        a.plot(t, wkm[g], color=col[cs[0]], lw=0.7, label={"residential": "residents' EVs", "workplace": "employees' EVs"}[g])
    a.plot(t, wkm["fleet"], color=INK, lw=1.2, label="fleet")
    a.set_ylabel("Avg. hourly km per EV"); a.set_ylim(0, 4.8); a.set_yticks(range(0, 5))
    a.set_title("(b) Trip events: distance driven by user type", loc="left")
    a.legend(ncol=3, loc="upper right", **leg)
    for a in ax:  # both panels: day boundaries, day names at noon
        a.set_xlim(0, 168)
        a.set_xticks(range(0, 169, 24)); a.set_xticklabels([])
        a.set_xticks(range(12, 168, 24), minor=True); a.set_xticklabels(days, minor=True)
        a.tick_params(axis="x", which="minor", length=0)
        a.grid(color=GRID, lw=0.4)
    fig.savefig(out / "ev_dataset_weekly.pdf", dpi=300, metadata={"CreationDate": None})  # no time stamp
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(HERE.parents[1] / "results"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    inp = json.loads((mf.INPUTS / "straub_berlin_inputs.json").read_text())
    inp_hourly = pd.read_csv(mf.INPUTS / "straub_berlin_hourly.csv", sep=";", index_col="hour")
    park_q = pd.read_csv(mf.INPUTS / "straub_berlin_parking_quantiles.csv", sep=";", index_col="quantile")
    idx, present, km, ses = load_pool()
    s = session_frame(ses)

    stats = statistics(idx, present, km, s, inp)
    stats.to_csv(out / "ev_dataset_statistics.csv", sep=";")
    rep, gen = reproduction(s, inp_hourly)

    # weekly profiles
    wk = {c: weekly(present[c], idx) for c in mf.COHORTS}
    wk["fleet"], _ = fleet_mix(wk, mf.RESIDENTIAL_SHARE, inp)
    kmw = {c: weekly(km[c], idx) for c in mf.COHORTS}
    sh = inp["cohort shares"]
    wkm = {g: sum(sh[c] * kmw[c] for c in cs) for g, cs in GROUP.items()}
    wkm["fleet"], _ = fleet_mix(kmw, mf.RESIDENTIAL_SHARE, inp)
    pd.DataFrame({**{f"connected {k} [-]": v for k, v in wk.items()}, **{f"km per car and h, {k}": v for k, v in wkm.items()}}).round(5).to_csv(
        out / "ev_dataset_weekly.csv", sep=";", index_label="hour of week (Monday 0 h)")

    # charging shapes: ELVIS uncontrolled, RLI rule
    n_res = (30, 70)  # vehicles per cohort in the simulation, in the cohorts' proportions
    n_emp = (78, 22)
    val = {}
    start = dt.datetime(2025, 3, 3)
    for name, cs, n in [("residents", GROUP["residential"], n_res), ("employees", GROUP["workplace"], n_emp)]:
        load = elvis_uc(s, cs, start, 4, n)
        keep = load.index.day_of_week < 4
        val[f"ELVIS UC, {name}"] = load[keep].groupby(load.index[keep].hour).mean().to_numpy()
        val[f"RLI rule, {name}"] = spread_rule(s, cs, n)
    rows = {}
    for k in [c for c in inp_hourly.columns if c.startswith("charging at")]:
        val[k.replace(" (recomputed)", "")] = inp_hourly[k].to_numpy()
    for mine, k in [("ELVIS UC, residents", "charging at home, Straub home-charging scenario"),
                    ("ELVIS UC, employees", "charging at work, same rule at 11 kW"),
                    ("ELVIS UC, employees", "charging at work, Straub work-charging scenario 22 kW")]:
        rows[(mine, k + " (recomputed from his trips)")] = {
            "r": float(np.corrcoef(val[mine], val[k])[0, 1]), "peak hour (mine)": int(np.argmax(val[mine])),
            "peak hour (reference)": int(np.argmax(val[k])), "peak/mean (mine)": float(val[mine].max() / val[mine].mean()),
            "peak/mean (reference)": float(val[k].max() / val[k].mean())}
    valdf = pd.DataFrame(rows).T
    valdf.index.names = ["profile", "reference"]
    valdf.round(3).to_csv(out / "ev_dataset_validation.csv", sep=";")
    rep.round(3).to_csv(out / "ev_dataset_reproduction.csv", sep=";")

    # connected share by hour, weekdays: the fleet mixes and the first submission's fleet
    cmp = first_submission()
    keep = np.asarray(idx.day_of_week < 5)
    for share in [mf.RESIDENTIAL_SHARE, 1.0, 0.75, 0.5, 0.25, 0.0]:
        conn, _ = fleet_mix({c: present[c].mean(axis=0) for c in mf.COHORTS}, share, inp)
        label = f"base fleet, {int(100 * share)} % residents" if share == mf.RESIDENTIAL_SHARE else f"fleet, {int(100 * share)} % residents"
        cmp[label] = pd.Series(conn[keep]).groupby(np.asarray(idx.hour)[keep]).mean().to_numpy()
    hourly_cmp = cmp
    val["emobpy (MiD 2017) connected"], val["emobpy (MiD 2017) UC"] = emobpy_reference()  # reference fleet in Fig. 4
    ours = val
    pd.DataFrame({**{f"connected, {k} [-]": v for k, v in hourly_cmp.items()}, **{f"charging shape, {k}": v for k, v in ours.items()},
                  **{f"generated: {k}": v for k, v in gen.items()}}).round(5).to_csv(out / "ev_dataset_hourly.csv", sep=";", index_label="hour")
    figures(out, inp_hourly, park_q, wk, wkm, val, hourly_cmp)
    pd.set_option("display.width", 200)
    print(stats.T.to_string(max_colwidth=30))
    print("\nreproduction of Straub's working day (Mon-Thu):\n", rep.round(3).to_string())
    print("\nvalidation:\n", valdf.round(2).to_string())
    print("\nconnected share by hour (weekdays), 0/5/12/14/19/22 h:")
    for k, v in hourly_cmp.items():
        print(f"  {k:32s}", (100 * v[[0, 5, 12, 14, 19, 22]]).round(0).tolist(), " mean", round(100 * v.mean(), 1))


if __name__ == "__main__":
    main()
