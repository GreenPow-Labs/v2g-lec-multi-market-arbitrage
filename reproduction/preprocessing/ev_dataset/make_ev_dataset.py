#!/usr/bin/env python3
# Made by Francesco Maldonato on 10/11/2026
"""EV dataset of the energy community (paper Section IV-G): ELVIS charging sessions fitted to Straub's Berlin trips.

    python3 make_ev_dataset.py extract --straub <fahrdaten.ftr>   # 1. Straub's trips -> fitted ELVIS inputs (inputs/)
    python3 make_ev_dataset.py generate                           # 2. sessions and trips of 400 synthetic EVs per cohort (pool/)
    python3 make_ev_dataset.py model                              # 3. PLEXOS input files of the four cohorts, 2023-2025

Step 1 needs Straub's simulated trips (not public); its output, the probability densities of the study, is shipped in
inputs/, so steps 2 and 3 run without them. Step 3 writes into ../../model/DRJ_MultiYear_v13/data_files/<year>/.

Why: the community has two user groups: residents, who park at home overnight, and employees of its ten businesses, who
park at work during the day. ELVIS's charging-event model is fitted to Straub's simulation of Berlin's private car
traffic (dissertation, TU Berlin 2023, doi:10.14279/depositonce-17741; built on the household travel survey MiD 2017 and
OpenStreetMap). The fleet mix is a model input (base: RESIDENTIAL_SHARE; sweep 0-100 %).

Method
1. extract (needs Straub's simulated trips of an average working day, Monday-Thursday: 1.22 million cars, 2.0 million
   trips, not public; only aggregated statistics leave this step):
   - Residents' cars (Berlin households): day classes commuter day / other use / unused, their shares, and per used car
     the overnight stay at home (last arrival home, parking until the first departure; the same car's departure of the
     simulated day stands for the next morning's, the usual single-day assumption).
   - Workplace stays (employee parking): arrival and parking duration of every work activity, residents and inbound
     commuters; full-day (>= 6 h) and part-day stays.
   - Daily distance per class (quantiles) and mean driving speed.
   - ELVIS's charging-event model is a Gaussian mixture of (arrival time, parking duration) (ELVIS
     create_charging_events_from_gmm, arrival counted from 05:00 so that night arrivals stay with their evening). One
     mixture per cohort is fitted (scikit-learn, full covariances, components by BIC) and written as an ELVIS scenario
     file, inputs/<cohort>.yaml, for the full week.
2. generate: N vehicles per cohort over 371 days (2025-01-01 ..., so that 2023 and 2024 can be cut with their own
   weekdays). Day by day, a vehicle draws its day class, then one session from its cohort's mixture with ELVIS's
   sampler (sklearn GMM built by elvis.charging_event_generator.init_gmm, parking < 10 min resampled as in ELVIS).
   Sessions are chained per vehicle:
   - residents: the arrival home must follow the morning departure (redrawn otherwise); an unused day extends the
     stay by 24 h; the stay's end is the next departure;
   - employees: one stay per attended day; consecutive stays at least MIN_GAP_WORK apart.
   Weekends: MiD 2017 factors (days with trips, weekend departure shift, Saturday work trips; constants MID below).
3. Trips: every absence holds the day's distance, drawn from the class's distribution in Straub's data: half on the
   way out, half on the way back, at the mean driving speed. An employee's absence holds the commute day and, for
   days without a work stay in it, the use of an unused/other day. All charging of a vehicle happens in the community
   (residents at home, employees at work). Distances are scaled per cohort to KM_PER_EV (the paper's 11,560 km/a);
   the part of an absence above E_MAX (10-90 % SoC window minus 5 kWh) is charged en route (reported).
4. model: four PLEXOS Vehicle objects, one per cohort: share connected [%] = mean time at the
   charging park in the hour, distance [km per vehicle] = mean km driven in the hour, over the cohort's vehicles.
   Units per object = fleet size x group share x cohort share (UNITS()).

Outputs
- inputs/<cohort>.yaml (ELVIS scenario files with the fitted mixtures), inputs/straub_berlin_inputs.json (classes,
  shares, distance quantiles, speeds, mixtures, MiD factors), inputs/straub_berlin_hourly.csv and
  inputs/straub_berlin_parking_quantiles.csv (Straub's hourly arrivals/departures and parking durations, for the validation).
- pool/<cohort>.npz (hourly presence and km of every vehicle), pool/sessions.csv.gz, pool/summary.csv.
- <model>/data_files/<year>/EV_ELVIS-Straub_share_CS1.csv and EV_ELVIS-Straub_distance_km.csv.

Needs: requirements-ev.txt of the repository (py-elvis 0.2.1, scikit-learn, pyyaml, networkx; pyarrow for extract).
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"  # the fitted ELVIS inputs (probability densities) of the study
POOL = HERE / "pool"  # generated sessions and hourly presence / km of every synthetic EV
MODEL = HERE.parents[1] / "model" / "DRJ_MultiYear_v13"

START = pd.Timestamp("2025-01-01")  # Wednesday
DAYS = 371
HOURS = DAYS * 24
YEARS = {2023: 4, 2024: 5, 2025: 0}  # day of the simulated period at which each year starts (same weekday)
SEED = 20251105
N_VEHICLES = 400  # per cohort; the model files are cohort means

# cohort -> PLEXOS object, energy use [Wh/km] of its VW model (ev-database.org, as in the paper's Table)
COHORTS = {
    "RC": {"name": "Residential, commuter car", "group": "residential", "ev": "EV 1-VW ID.5 Pro 01", "wh_km": 169},
    "RO": {"name": "Residential, other car", "group": "residential", "ev": "EV 2-VW ID.4 Pro 01", "wh_km": 173},
    "WF": {"name": "Workplace, full-day stay", "group": "workplace", "ev": "EV 3-VW ID.4 GTX 01", "wh_km": 183},
    "WP": {"name": "Workplace, part-day stay", "group": "workplace", "ev": "EV 4-VW ID.5 Pro 01", "wh_km": 169},
}
STATION = "CS1"
FILES = {"share": "EV_ELVIS-Straub_share_CS1.csv", "km": "EV_ELVIS-Straub_distance_km.csv"}

FLEET = 100
RESIDENTIAL_SHARE = 0.65  # base mix: Straub's data-driven Berlin scenario charges 64.8 % of the energy of homes + workplaces at home
KM_PER_EV = 11560  # km/a per EV, the paper's design mobility demand (2 MWh/a at ~173 Wh/km)
CAPACITY, SOC_MIN, SOC_MAX, RESERVE = 82.0, 0.10, 0.90, 5.0  # kWh, -, -, kWh
E_MAX = (SOC_MAX - SOC_MIN) * CAPACITY - RESERVE  # kWh one absence may use from the community's charging
FULL_DAY = 6.0  # h: work stays of at least 6 h form the full-day cohort
P_ATTEND = (251 - 30 - 15) / 251  # working days an employee commutes: 251 working days, 30 days of leave, 15 sick days
MIN_AWAY = 0.25  # h, shortest absence of a resident's car
MIN_GAP_WORK = 2.0  # h between two work stays (home and back)
MIN_PARK = 0.167  # h, ELVIS resamples shorter parking times
DAY_START = 5.0  # h, ELVIS's offset of the arrival axis (create_charging_events_from_gmm, hour_offset=5)

# MiD 2017 via emobpy's German statistics (data/eg2/config_files), for what Straub's working day does not cover
MID = {
    "share of days without trips, weekday": 0.3541,  # TripsPerDay.csv
    "share of days without trips, weekend": 0.5068,
    "workplace share of worker trips, weekdays": 0.1798,  # DepartureDestinationTrip_Worker.csv
    "workplace share of worker trips, Saturday": 0.0257,
    "workplace share of worker trips, Sunday": 0.0,
    "mean departure hour of free-time trips, weekdays": 13.79,  # DepartureDestinationTrip_Free.csv
    "mean departure hour of free-time trips, Saturday": 14.21,
    "mean departure hour of free-time trips, Sunday": 14.83,
}
WEEKEND_USE = (1 - MID["share of days without trips, weekend"]) / (1 - MID["share of days without trips, weekday"])
SATURDAY_WORK = MID["workplace share of worker trips, Saturday"] / MID["workplace share of worker trips, weekdays"]
WEEKEND_SHIFT = {5: MID["mean departure hour of free-time trips, Saturday"] - MID["mean departure hour of free-time trips, weekdays"],
                 6: MID["mean departure hour of free-time trips, Sunday"] - MID["mean departure hour of free-time trips, weekdays"]}


def units(residential_share=RESIDENTIAL_SHARE, fleet=FLEET, inputs=None):
    """Integer Units of the four objects (RC, RO, WF, WP) for a fleet and residential share."""
    inputs = inputs or json.loads((INPUTS / "straub_berlin_inputs.json").read_text())
    s = inputs["cohort shares"]
    r = round(fleet * residential_share)
    rc = round(r * s["RC"])
    wf = round((fleet - r) * s["WF"])
    return rc, r - rc, wf, fleet - r - wf


# ---------------------------------------------------------------------------------------------------------- extract
def fit_mixture(x, p, rng, n=60000, max_k=8):
    from sklearn.mixture import GaussianMixture
    X = np.column_stack([x, p])
    X = X[rng.choice(len(X), min(n, len(X)), replace=False)]
    best = None
    for k in range(2, max_k + 1):
        m = GaussianMixture(k, covariance_type="full", random_state=0, n_init=2, reg_covar=1e-3).fit(X)
        bic = m.bic(X)
        if best is None or bic < best[0] - 1e-3 * abs(best[0]):  # a component more must lower BIC by 0.1 %
            best = (bic, m)
    m = best[1]
    order = np.argsort(m.means_[:, 0])
    return {"means": m.means_[order].round(4).tolist(), "weights": (m.weights_[order] / m.weights_.sum()).round(6).tolist(),
            "covariances": m.covariances_[order].round(5).tolist(), "n fitted": int(len(X))}


def straub_base_scenarios(trips, is_res, home, kwh_km=0.17, eff=0.95):
    """Straub's base charging scenarios (dissertation Section 4.3.4.1) recomputed from his trips, as hourly shares of
    the day's charging energy: SoC 100 % before the first trip; charging starts on arrival at 95 % of the maximum power
    and runs until the energy driven since the last charge is back or the car leaves. Home-charging scenario: at home,
    11 kW. Work-charging scenario, the part charged at work: 22 kW (Straub) and 11 kW (the community's points).
    kwh_km: one consumption for all cars (his reference vehicles' measured curves are not needed for the shape)."""
    t = trips.copy()
    t["veh_res"] = is_res.to_numpy()
    g = t.groupby("global_id", sort=False)
    t["next_start"] = g.t_drive_start.shift(-1)
    after_home = t.activity.eq("home").groupby(t.global_id, sort=False).shift(fill_value=False)
    t["tour"] = after_home.astype(int).groupby(t.global_id, sort=False).cumsum()  # a trip after a home arrival opens a tour
    t["e_cum"] = t.groupby(["global_id", "tour"], sort=False).distance.cumsum() / 1000 * kwh_km
    first = g.t_drive_start.transform("min")
    out = {}
    h = t[(t.activity == "home") & t.veh_res]
    stop = h.next_start.fillna(first[h.index] + 24)
    for name, rows, start, end, kw in [
        ("charging at home, Straub home-charging scenario (recomputed)", h, h.t_drive_end, stop, 11 * eff),
        ("charging at work, Straub work-charging scenario 22 kW (recomputed)", t[t.activity == "commercial"], None, None, 22 * eff),
        ("charging at work, same rule at 11 kW (recomputed)", t[t.activity == "commercial"], None, None, 11 * eff)]:
        if start is None:
            start, end = rows.t_drive_end, rows.t_drive_end + rows.dt_activity
        dur = np.minimum(rows.e_cum / kw, end - start).clip(lower=0)
        p = hourly(list(zip(start, start + dur)), 72, (dur * kw).to_numpy())
        day = p[:24] + p[24:48] + p[48:72]
        out[name] = day / day.sum()
    return out


def extract(path):
    rng = np.random.default_rng(SEED)
    cols = ["global_id", "spatial_na_id", "activity", "t_drive_start", "dt_drive", "t_drive_end", "distance",
            "dt_activity", "t_activity_end", "loc_start"]
    df = pd.read_feather(path, columns=cols)
    inbound = df.groupby("global_id").spatial_na_id.first() == 0  # zone 0: commuters from outside Berlin (Brandenburg)
    trips = df[df.t_drive_start.notna()].sort_values(["global_id", "t_drive_start"])
    is_res = trips.spatial_na_id != 0
    r = trips[is_res]
    g = r.groupby("global_id", sort=False)
    day = pd.DataFrame({"dep": g.t_drive_start.min(), "km": g.distance.sum() / 1000,
                        "drive_h": g.dt_drive.sum(), "commute": r.activity.eq("commercial").groupby(r.global_id).any()})
    day["arr"] = r[r.activity == "home"].groupby("global_id").t_drive_end.max()
    n_res = int((~inbound).sum())
    n_used = len(day)
    home = day.dropna(subset=["arr"]).copy()
    home["park"] = home.dep + 24 - home.arr
    home = home[(home.park > MIN_PARK) & (home.arr > home.dep)]
    w = trips[trips.activity == "commercial"]
    w = w[w.dt_activity > MIN_PARK]
    commute_km = pd.concat([day.loc[day.commute, "km"],
                            trips[~is_res].groupby("global_id").distance.sum() / 1000])

    shares = {"commuter day": float(day.commute.sum() / n_res), "other use": float((~day.commute).sum() / n_res),
              "unused": float(1 - n_used / n_res)}
    s_rc = shares["commuter day"] / P_ATTEND  # commuter cars commute on P_ATTEND of the working days
    other_wd = shares["other use"] / (s_rc * (1 - P_ATTEND) + (1 - s_rc))  # other-use probability of a non-commute working day
    full = float((w.dt_activity >= FULL_DAY).mean())
    q = np.linspace(0, 1, 101)
    out = {
        "source": "Straub, Modelling and Simulation of a fully Electrified Urban Private Transport - a Future Scenario "
                  "for Berlin, Dissertation, TU Berlin 2023, doi:10.14279/depositonce-17741 (simulated trips of an "
                  "average working day, Monday-Thursday; MiD 2017 + OpenStreetMap)",
        "counts": {"cars": int(len(inbound)), "residents' cars": n_res, "inbound commuters' cars": int(inbound.sum()),
                   "residents' cars used": n_used, "overnight stays fitted": int(len(home)), "work stays": int(len(w)),
                   "trips": int(len(trips))},
        "resident day classes (working day)": shares,
        "cohort shares": {"RC": s_rc, "RO": 1 - s_rc, "WF": full, "WP": 1 - full},
        "day class probabilities": {"commute, commuter car, working day": P_ATTEND,
                                    "other use, non-commute working day": other_wd,
                                    "use, weekend day": (1 - shares["unused"]) * WEEKEND_USE,
                                    "work stay, Saturday": P_ATTEND * SATURDAY_WORK, "work stay, Sunday": 0.0},
        "distance quantiles [km]": {"commuter day": np.quantile(home.loc[home.commute, "km"], q).round(3).tolist(),
                                    "other use": np.quantile(home.loc[~home.commute, "km"], q).round(3).tolist(),
                                    "commute day (employees)": np.quantile(commute_km, q).round(3).tolist()},
        "mean distance [km/day]": {"commuter day": float(day.loc[day.commute, "km"].mean()),
                                   "other use": float(day.loc[~day.commute, "km"].mean()),
                                   "residents' car incl. unused": float(day.km.sum() / n_res),
                                   "commute day (employees)": float(commute_km.mean())},
        "speed [km/h]": {"residents": float(day.km.sum() / day.drive_h.sum()),
                         "employees": float(trips.loc[trips.global_id.isin(w.global_id), "distance"].sum() / 1000 /
                                            trips.loc[trips.global_id.isin(w.global_id), "dt_drive"].sum())},
        "work stay [h]": {"mean": float(w.dt_activity.mean()), "std": float(w.dt_activity.std()),
                          "share >= 6 h": full},
        "MiD 2017 (emobpy)": MID, "assumptions": {"P_ATTEND": P_ATTEND, "FULL_DAY h": FULL_DAY, "DAY_START h": DAY_START},
        "mixtures": {},
    }
    samples = {"RC": home[home.commute], "RO": home[~home.commute]}
    for c, s in samples.items():
        out["mixtures"][c] = fit_mixture(s.arr.to_numpy() - DAY_START, s.park.to_numpy(), rng)
    for c, s in {"WF": w[w.dt_activity >= FULL_DAY], "WP": w[w.dt_activity < FULL_DAY]}.items():
        out["mixtures"][c] = fit_mixture(s.t_drive_end.to_numpy() - DAY_START, s.dt_activity.to_numpy(), rng)

    # hourly distributions for the validation (shares of the day's events per clock hour)
    def hist(t):
        return np.histogram(np.mod(t, 24), bins=24, range=(0, 24))[0] / len(t)
    hourly = pd.DataFrame({"arrival home, commuter day": hist(home.loc[home.commute, "arr"]),
                           "arrival home, other use": hist(home.loc[~home.commute, "arr"]),
                           "departure home, commuter day": hist(home.loc[home.commute, "dep"]),
                           "departure home, other use": hist(home.loc[~home.commute, "dep"]),
                           "arrival work, full day": hist(w.loc[w.dt_activity >= FULL_DAY, "t_drive_end"]),
                           "arrival work, part day": hist(w.loc[w.dt_activity < FULL_DAY, "t_drive_end"]),
                           "departure work, full day": hist(w.loc[w.dt_activity >= FULL_DAY, "t_activity_end"]),
                           "departure work, part day": hist(w.loc[w.dt_activity < FULL_DAY, "t_activity_end"])})
    hourly.index.name = "hour"
    for k, v in straub_base_scenarios(trips, is_res, home).items():
        hourly[k] = v
    park = pd.DataFrame({"overnight stay at home, commuter day [h]": np.quantile(home.loc[home.commute, "park"], q),
                         "overnight stay at home, other use [h]": np.quantile(home.loc[~home.commute, "park"], q),
                         "work stay [h]": np.quantile(w.dt_activity, q)}, index=q.round(2))
    park.index.name = "quantile"
    INPUTS.mkdir(exist_ok=True)
    (INPUTS / "straub_berlin_inputs.json").write_text(json.dumps(out, indent=1))
    hourly.round(6).to_csv(INPUTS / "straub_berlin_hourly.csv", sep=";")
    park.round(3).to_csv(INPUTS / "straub_berlin_parking_quantiles.csv", sep=";")
    write_elvis_configs(out)
    print(json.dumps({k: out[k] for k in ["counts", "resident day classes (working day)", "cohort shares",
                                         "day class probabilities", "mean distance [km/day]", "speed [km/h]"]}, indent=1))
    print({c: len(m["weights"]) for c, m in out["mixtures"].items()}, "mixture components")


def week_mixture(c, inp):
    """The cohort's mixture over a week (Monday 0 h = 0) with each day's expected number of sessions as weight."""
    pr = inp["day class probabilities"]
    mix = inp["mixtures"]
    parts = []  # (mixture, weight, day, shift)
    for d in range(7):
        weekend = d >= 5
        if COHORTS[c]["group"] == "residential":
            if weekend:
                parts.append((mix["RO"], pr["use, weekend day"], d, WEEKEND_SHIFT[d]))
            elif c == "RC":
                parts += [(mix["RC"], P_ATTEND, d, 0.0), (mix["RO"], (1 - P_ATTEND) * pr["other use, non-commute working day"], d, 0.0)]
            else:
                parts.append((mix["RO"], pr["other use, non-commute working day"], d, 0.0))
        else:
            att = {5: pr["work stay, Saturday"], 6: pr["work stay, Sunday"]}.get(d, P_ATTEND)
            if att > 0:
                parts.append((mix[c], att, d, 0.0))
    return parts


def write_elvis_configs(inp):
    import yaml
    for c, meta in COHORTS.items():
        parts = week_mixture(c, inp)
        means, weights, covs = [], [], []
        for m, w, d, shift in parts:
            for mu, wk, cov in zip(m["means"], m["weights"], m["covariances"]):
                means.append([round(24 * d + mu[0] + shift, 4), mu[1]])
                weights.append(w * wk)
                covs.append(cov)
        total = sum(weights)
        cfg = {
            "num_charging_events": round(total),  # sessions per vehicle and week
            "gmm_means": means, "gmm_weights": [round(x / total, 8) for x in weights], "gmm_covariances": covs,
            "max_parking_time": 72, "mean_soc": 0.8, "std_deviation_soc": 0.1,  # SoC: not used, the trips set it
            "vehicle_types": [{"brand": "VW", "model": meta["ev"].split("-", 1)[1].rsplit(" ", 1)[0],
                               "probability": 1.0, "battery": {"capacity": CAPACITY, "max_charge_power": 11,
                                                               "min_charge_power": 0, "efficiency": 1}}],
            "infrastructure": {"transformers": [{"id": "transformer1", "max_power": 1000, "min_power": 0,
                                                 "charging_stations": [{"id": "cs1", "max_power": 11, "min_power": 0,
                                                                        "charging_points": [{"id": "cp1", "max_power": 11, "min_power": 0}]}]}]},
            "scheduling_policy": "UC", "queue_length": 0, "disconnect_by_time": True, "transformer_preload": 0,
        }
        head = (f"# ELVIS scenario of cohort {c} ({meta['name']}), one vehicle at one 11 kW charging point.\n"
                f"# Charging-event model: Gaussian mixture of (arrival [h from Monday 05:00 of each day, ELVIS hour_offset=5],\n"
                f"# parking [h]), fitted to Straub's Berlin trips (working days) with MiD 2017 weekend factors; written by\n"
                f"# make_ev_dataset.py extract. Use: ScenarioConfig.from_yaml(...); realisation sample_method 'gmm'.\n"
                f"# Note: ELVIS maps arrivals between 00:00 and 05:00 to the start of the same day; make_ev_dataset.py\n"
                f"# keeps them with the evening before (night arrival after a late trip).\n")
        (INPUTS / f"{c}.yaml").write_text(head + yaml.safe_dump(cfg, sort_keys=False, width=140))


# --------------------------------------------------------------------------------------------------------- generate
class Sampler:
    """Draws (arrival from DAY_START, parking) pairs of one mixture with ELVIS's sampler, in blocks."""

    def __init__(self, m, seed):
        from elvis.charging_event_generator import init_gmm, resample
        self.gmm = init_gmm(m["means"], m["weights"], m["covariances"])
        self.gmm.random_state = np.random.RandomState(seed)  # one stream per sampler (an int would repeat every block)
        self.resample = resample
        self.buf, self.i = [], 0

    def draw(self):
        if self.i >= len(self.buf):
            self.buf = self.resample(self.gmm, MIN_PARK, 20000, hour_offset=0)  # ELVIS: drops parking < MIN_PARK
            self.i = 0
        x, p = self.buf[self.i]
        self.i += 1
        return x, p


def quantile_draw(qs, rng):
    return float(np.interp(rng.random(), np.linspace(0, 1, len(qs)), qs))


def legs(t0, t1, km, speed, out):
    """Half of the absence's distance on the way out (from t0), half on the way back (until t1)."""
    if km <= 0 or t1 <= t0:
        return
    dur = min(km / 2 / speed, (t1 - t0) / 2)
    out.append((t0, t0 + dur, km / 2))
    out.append((t1 - dur, t1, km / 2))


def residential_vehicle(c, inp, samplers, rng):
    pr = inp["day class probabilities"]
    qs = inp["distance quantiles [km]"]
    speed = inp["speed [km/h]"]["residents"]
    stays, drives, absences = [], [], []  # stays (start, end); drives (start, end, km); absences (start, end, km)
    start, dep = 0.0, None  # the car is at home at the start
    for d in range(DAYS):
        wd = (START + pd.Timedelta(days=d)).day_of_week
        if wd >= 5:
            cls = "other" if rng.random() < pr["use, weekend day"] else "unused"
        elif c == "RC" and rng.random() < P_ATTEND:
            cls = "commute"
        else:
            cls = "other" if rng.random() < pr["other use, non-commute working day"] else "unused"
        if cls == "unused":
            if dep is not None:
                dep += 24
            continue
        sampler = samplers["RC" if cls == "commute" else "RO"]
        shift = WEEKEND_SHIFT.get(wd, 0.0)
        for _ in range(50):
            x, p = sampler.draw()
            a = 24 * d + DAY_START + x + shift
            if dep is None:
                dep = a + p - 24  # first trip: the stay's own departure, one day earlier
            if a >= dep + MIN_AWAY and a > start:
                break
        else:
            a = max(dep, start) + MIN_AWAY
        dep = max(dep, start)
        stays.append((start, dep))
        km = quantile_draw(qs["commuter day" if cls == "commute" else "other use"], rng)
        absences.append((dep, a, km))
        legs(dep, a, km, speed, drives)
        start, dep = a, a + p
    stays.append((start, HOURS))
    return stays, drives, absences


def workplace_vehicle(c, inp, samplers, rng):
    pr = inp["day class probabilities"]
    qs = inp["distance quantiles [km]"]
    speed = inp["speed [km/h]"]["employees"]
    use_wd = pr["other use, non-commute working day"]
    stays = []
    for d in range(DAYS):
        wd = (START + pd.Timedelta(days=d)).day_of_week
        att = {5: pr["work stay, Saturday"], 6: pr["work stay, Sunday"]}.get(wd, P_ATTEND)
        if rng.random() >= att:
            continue
        last = stays[-1][1] if stays else -np.inf
        for _ in range(50):
            x, p = samplers[c].draw()
            a = 24 * d + DAY_START + x
            if a >= last + MIN_GAP_WORK:
                break
        else:
            continue
        stays.append((a, min(a + p, HOURS)))
    drives, absences = [], []
    bounds = [(-np.inf, 0.0)] + stays + [(HOURS, np.inf)]
    for (_, t0), (t1, _) in zip(bounds[:-1], bounds[1:]):
        t0, t1 = max(t0, 0.0), min(t1, HOURS)
        if t1 <= t0:
            continue
        km = 0.0
        if 0 < t0 and t1 < HOURS:  # between two work stays: the commute day
            km_c = quantile_draw(qs["commute day (employees)"], rng)
            legs(t0, t1, km_c, speed, drives)
            km += km_c
        # days whose daytime (9-18 h) lies inside the absence: no work stay, other use (weekend factor on weekends)
        for d in range(int(t0 // 24), int(t1 // 24) + 1):
            if not (24 * d + 9 > t0 and 24 * d + 18 < t1):
                continue
            wd = (START + pd.Timedelta(days=d)).day_of_week
            if rng.random() < (pr["use, weekend day"] if wd >= 5 else use_wd):
                km_o = quantile_draw(qs["other use"], rng)
                out_h, back_h = rng.uniform(9, 13), rng.uniform(14, 20)  # a day trip from home (timing: an assumption)
                legs(24 * d + out_h, 24 * d + back_h, km_o, speed, drives)
                km += km_o
        absences.append((t0, t1, km))
    return stays, drives, absences


def hourly(intervals, n_hours, weights=None):
    """Sum over intervals [s, e) of their overlap with each hour (weights: spread uniformly over the interval)."""
    out = np.zeros(n_hours + 2)
    if not intervals:
        return out[:n_hours]
    a = np.asarray(intervals, float)
    s, e = np.clip(a[:, 0], 0, n_hours), np.clip(a[:, 1], 0, n_hours)
    w = np.ones(len(a)) if weights is None else np.asarray(weights, float) / np.maximum(a[:, 1] - a[:, 0], 1e-9)
    ok = e > s
    s, e, w = s[ok], e[ok], w[ok]
    i0, i1 = np.floor(s).astype(int), np.floor(e).astype(int)
    same = i0 == i1
    np.add.at(out, i0[same], (e[same] - s[same]) * w[same])
    d = ~same
    np.add.at(out, i0[d], (i0[d] + 1 - s[d]) * w[d])
    np.add.at(out, i1[d], (e[d] - i1[d]) * w[d])
    diff = np.zeros(n_hours + 3)
    np.add.at(diff, i0[d] + 1, w[d])
    np.add.at(diff, i1[d], -w[d])
    out += np.cumsum(diff)[: n_hours + 2]
    return out[:n_hours]


def generate(n):
    inp = json.loads((INPUTS / "straub_berlin_inputs.json").read_text())
    POOL.mkdir(parents=True, exist_ok=True)
    sim = {}
    for k, (c, meta) in enumerate(COHORTS.items()):
        rng = np.random.default_rng(SEED + k)
        samplers = {m: Sampler(inp["mixtures"][m], SEED + 10 * k + j) for j, m in enumerate(["RC", "RO", c])}
        make = residential_vehicle if meta["group"] == "residential" else workplace_vehicle
        present = np.zeros((n, HOURS), np.float32)
        km = np.zeros((n, HOURS), np.float32)
        stays_all, absences = [], []
        for v in range(n):
            stays, drives, absn = make(c, inp, samplers, rng)
            present[v] = hourly(stays, HOURS)
            km[v] = hourly([(s, e) for s, e, _ in drives], HOURS, [x for _, _, x in drives])
            absences += [(v, s, e, x) for s, e, x in absn]
            stays_all += [(v, s, e) for s, e in stays]
        sim[c] = {"present": present, "km": km, "stays": pd.DataFrame(stays_all, columns=["vehicle", "arrival_h", "departure_h"]),
                  "absences": pd.DataFrame(absences, columns=["vehicle", "start_h", "end_h", "km"])}
    # Distances: one factor per user group, so that each group drives KM_PER_EV per EV and year on average with its
    # cohorts in Straub's proportions and with their relative distances from his data (the fleet mix then changes the
    # timing of availability and driving, not the energy the fleet needs).
    shares = inp["cohort shares"]
    natural = {c: s["km"].sum() / n * 365 / DAYS for c, s in sim.items()}
    factor = {}
    for group in ["residential", "workplace"]:
        cs = [c for c in COHORTS if COHORTS[c]["group"] == group]
        mean = sum(shares[c] * natural[c] for c in cs)
        factor.update({c: KM_PER_EV / mean for c in cs})
    rows, summary = [], []
    for c, meta in COHORTS.items():
        s = sim[c]
        km, ab = s["km"] * factor[c], s["absences"]
        ab["km"] *= factor[c]
        ab["kwh"] = ab.km * meta["wh_km"] / 1000
        over = ab.kwh > E_MAX  # charged en route above E_MAX: scale the absence's hours down
        en_route = float((ab.kwh - E_MAX).clip(lower=0).sum() / ab.kwh.sum())
        for _, a in ab[over].iterrows():
            i0, i1 = int(math.floor(max(a.start_h, 0))), int(math.ceil(min(a.end_h, HOURS)))
            km[int(a.vehicle), i0:i1] *= E_MAX / a.kwh
        ab["kwh community"] = ab.kwh.clip(upper=E_MAX)
        np.savez_compressed(POOL / f"{c}.npz", present=s["present"].astype(np.float16), km=km.astype(np.float32))
        st = s["stays"][s["stays"].vehicle < 100].assign(cohort=c)
        rows.append(st.merge(ab[ab.vehicle < 100].rename(columns={"end_h": "arrival_h"})[["vehicle", "arrival_h", "start_h", "km", "kwh community"]],
                             on=["vehicle", "arrival_h"], how="left"))
        p = s["present"]
        summary.append({"cohort": c, "name": meta["name"], "object": meta["ev"], "vehicles": n,
                        "natural km/a (Straub)": natural[c], "distance factor": factor[c], "km/a": float(km.sum() / n * 365 / DAYS),
                        "en-route share of driving energy [%]": 100 * en_route, "absences above E_MAX [%]": 100 * float(over.mean()),
                        "connected share [%]": 100 * float(p.mean()), "at 03:00 [%]": 100 * float(p[:, 3::24].mean()),
                        "at 12:00 [%]": 100 * float(p[:, 12::24].mean()), "at 19:00 [%]": 100 * float(p[:, 19::24].mean())})
        print({k2: (round(v2, 2) if isinstance(v2, float) else v2) for k2, v2 in summary[-1].items()}, flush=True)
    sessions = pd.concat(rows)[["cohort", "vehicle", "start_h", "arrival_h", "departure_h", "km", "kwh community"]]
    sessions.rename(columns={"start_h": "trip start_h", "km": "km before arrival", "kwh community": "kWh before arrival (community)"}).round(4).to_csv(
        POOL / "sessions.csv.gz", index=False)  # first 100 vehicles per cohort: each stay with the absence (trips) before it
    pd.DataFrame(summary).round(4).to_csv(POOL / "summary.csv", sep=";", index=False)


# ------------------------------------------------------------------------------------------------------------ model
def cohort_series():
    idx = pd.date_range(START, periods=HOURS, freq="h")
    share, km = {}, {}
    for c, meta in COHORTS.items():
        z = np.load(POOL / f"{c}.npz")
        share[f"{meta['ev']}~{STATION}"] = pd.Series(z["present"].astype(float).mean(axis=0), index=idx)
        km[meta["ev"]] = pd.Series(z["km"].astype(float).mean(axis=0), index=idx)
    return share, km


def year_frame(series_by_column, year, scale=1.0):
    t = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    start = START + pd.Timedelta(days=YEARS[year])
    assert pd.Timestamp(f"{year}-01-01").day_of_week == start.day_of_week
    out = pd.DataFrame({"Year": t.year, "Month": t.month, "Day": t.day, "Period": t.hour + 1})
    for column, s in series_by_column.items():
        part = s.loc[start:start + pd.Timedelta(hours=len(t) - 1)].to_numpy() * scale
        assert len(part) == len(t), (year, column, len(part))
        out[column] = part
    return out


def model(folder):
    share, km = cohort_series()
    for year in YEARS:
        d = Path(folder) / "data_files" / str(year)
        d.mkdir(parents=True, exist_ok=True)
        s = year_frame(share, year, 100).round(3)
        k = year_frame(km, year).round(4)
        s.to_csv(d / FILES["share"], sep=";", index=False)
        k.to_csv(d / FILES["km"], sep=";", index=False)
        print(f"{d}: connected {s.iloc[:, 4:].mean().round(1).tolist()} %, km/a {k.iloc[:, 4:].sum().round(0).tolist()}")
    print("Units (RC, RO, WF, WP) at the base mix:", units())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stage", choices=["extract", "generate", "model"])
    ap.add_argument("--straub", help="Straub's simulated trips, fahrdaten.ftr (extract)")
    ap.add_argument("--vehicles", type=int, default=N_VEHICLES, help="vehicles per cohort (generate)")
    ap.add_argument("--model", default=str(MODEL), help="PLEXOS model folder whose data_files/<year>/ get the files (model)")
    a = ap.parse_args()
    if a.stage == "extract":
        extract(a.straub)
    elif a.stage == "generate":
        generate(a.vehicles)
    else:
        model(a.model)


if __name__ == "__main__":
    main()
