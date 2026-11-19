# Made by Francesco Maldonato on 10/11/2026
"""Forecast uncertainty (paper Sections III-H and VI-D, Table 10, Fig. 6): error metrics, Monte Carlo of the load error,
day-block bootstrap.

    python3 forecast_uncertainty.py [--n 1000]     # runs/DRJ_MultiYear_v13_executed_logs -> results/

Every settlement run (X.2) replays its X.1 schedule with the actual RES and load, so its imbalance is the net forecast
error e_t = (RES actual - forecast) - (load actual - forecast), settled at the imbalance price (sold at p, bought at
p + 2 EUR/MWh). Its KPIs therefore follow from the X.1 run and the inputs, which this script reconstructs and checks
against the PLEXOS X.2 runs before using it:
1. Error metrics per year (community scale): MAE, RMSE, normalised MAE and RMSE, bias, 5/95 % quantiles and lag-1
   autocorrelation of the hourly errors of solar, wind, RES, households, businesses, native load and the net error; and
   the deviation of the intraday and imbalance prices from the day-ahead price (what a day-ahead schedule is exposed to).
2. Monte Carlo of the load forecast error (N realisations per year, the generator of preprocessing/prepare_inputs.py
   with other seeds): uniform +-20 %, Gaussian AR(1) copula, lag-1 correlation 0.8, rescaled to the annual energy); the RES error stays
   the measured one. Gives the distribution of the imbalance volume and cost and of the community energy cost of A.2,
   B.2 and C.2, and of the differences B.2 - A.2 and C.2 - A.2 (paired: the same realisation in every scenario).
3. Day-block bootstrap (N resamples of the run's days with replacement, every series of a day kept together): the
   sampling uncertainty of the annual imbalance cost and community energy cost of the measured year.
4. Error scaling: the settlement is linear in the error, so the imbalance cost of an error k times larger is k times
   the measured one (reported for k = 0.5, 1.5, 2).

Writes into results/: forecast_error_metrics.csv (Table 10), forecast_mc_summary.csv, forecast_bootstrap_summary.csv (the
intervals of Fig. 6) and forecast_reconstruction_check.csv (the reconstruction against the PLEXOS settlement runs).
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import RESULTS, YEARS, Run, hourly, overview, runs_folder

BOUND, RHO, SEED = 0.20, 0.8, 9000  # load error model of preprocessing/prepare_inputs.py
WHEELING = 20.0  # EUR/MWh per line and direction
LINES = ["Business-DEMS", "CS-DEMS", "DEMS-Transmission", "Household-DEMS", "Solar-DEMS", "StationaryStorage-DEMS", "Wind-DEMS"]
SOLAR_OM, WIND_OM, WIND_VOM = 21.5, 32.0, 7.0  # EUR/kW/a, EUR/kW/a, EUR/MWh (Fraunhofer ISE 2024)


def erf(x):
    """Vectorised error function (Abramowitz & Stegun 7.1.26, |error| < 1.5e-7)."""
    s = np.sign(x)
    x = np.abs(x)
    t = 1 / (1 + 0.3275911 * x)
    y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return s * y


def load_errors(n, seeds):
    """Relative load errors e (len(seeds) x n), as prepare_inputs.relative_load_error for each seed."""
    w = np.stack([np.random.default_rng(s).standard_normal(n) for s in seeds])
    z = np.empty_like(w)
    z[:, 0] = w[:, 0]
    c = np.sqrt(1 - RHO ** 2)
    for t in range(1, n):
        z[:, t] = RHO * z[:, t - 1] + c * w[:, t]
    return BOUND * erf(z / np.sqrt(2))  # = BOUND * (2 Phi(z) - 1)


def year_inputs(folder, year, spec):
    """Full-year forecast and actual series of the community [MW] (load: the measured-seed actual as in the runs)."""
    d = f"data_files/{year}"
    idx = pd.date_range(f"{year}-01-01", periods=len(pd.read_csv(Path(folder) / d / f"solar-profile-da_1H_germany-{year}.csv", sep=";")), freq="h")
    f = lambda name: hourly(folder, f"{d}/{name}", idx).to_numpy()
    out = {"index": idx,
           "solar fc": spec["solar MW"] * f(f"solar-profile-da_1H_germany-{year}.csv"), "solar ac": spec["solar MW"] * f(f"solar-profile-ac_1H_germany-{year}.csv"),
           "wind fc": spec["wind MW"] * f(f"wind-profile-da_1H_germany-{year}.csv"), "wind ac": spec["wind MW"] * f(f"wind-profile-ac_1H_germany-{year}.csv"),
           "hh shape": f("stromnetz_households_normalized_demand_1h_MW.csv"), "bu shape": f("stromnetz_general_business_normalized_demand_1h_MW.csv"),
           "hh ac shape": f("stromnetz-noise_households_normalized_demand_1h_MW.csv"), "bu ac shape": f("stromnetz-noise_general_business_normalized_demand_1h_MW.csv"),
           "imb": f(f"market-imbalances-prices_1H_germany-{year}.csv"), "da": f(f"market-dayahead-prices_1H_germany-{year}.csv"),
           "id": f(f"market-intraday-prices_1H_germany-{year}.csv")}
    out["hh MWh"], out["bu MWh"] = spec["households MWh"], spec["business MWh"]
    return out


def actual_load(inp, e):
    """Actual household and business load [MW] for relative errors e (rows = realisations), rescaled to the annual energy."""
    out = []
    for shape, mwh in [("hh shape", "hh MWh"), ("bu shape", "bu MWh")]:
        raw = inp[shape] * (1 + e)
        out.append(inp[mwh] * raw / raw.sum(axis=-1, keepdims=True))
    return out


def schedule(folder, model, idx_year):
    """What an X.2 run keeps from its X.1 source: the day-ahead + intraday position, the station and battery line flows,
    the X.1 cash flows, EV energies; as arrays on the run's hours, plus the positions of those hours in the year."""
    r = Run(folder, model)
    idx = r("Generator", "Solar G1", "Generation").index
    pos = idx_year.get_indexer(idx)
    net = sum(r("Market", m, "Sales", pd.Series(0.0, index=idx)) - r("Market", m, "Purchases", pd.Series(0.0, index=idx))
              for m in ["Day-Ahead energy price", "Intraday energy price"])
    rev = sum(float(r("Market", m, "Net Revenue", pd.Series(0.0, index=idx)).sum()) for m in ["Day-Ahead energy price", "Intraday energy price"])
    ev = [n for (c, n) in r.ids if c == "Vehicle"]
    return {"pos": pos, "index": idx, "net": net.to_numpy(), "cs": r("Line", "CS-DEMS", "Flow").to_numpy(),
            "bess": r("Line", "StationaryStorage-DEMS", "Flow").to_numpy(), "profit": rev,
            "uos": float(r("Charging Station", "CS1", "UoS Cost").sum()), "vom": float(r("Battery", "Stationary Battery", "VO&M Cost").sum()),
            "ev ch": sum(r("Vehicle", n, "Charging") for n in ev).to_numpy() / 1000,
            "ev dis": sum(r("Vehicle", n, "Discharging", pd.Series(0.0, index=idx)) for n in ev).to_numpy() / 1000}


def settle(e, p):
    """Imbalance revenue of net errors e [MW] (last axis = hours) at prices p: long sold at p, short bought at p + 2."""
    return (np.clip(e, 0, None) * p - np.clip(-e, 0, None) * (p + 2)).sum(axis=-1)


def x2_kpis(inp, sch, spec, hh, bu, year):
    """KPIs of the X.2 run of schedule sch for actual loads hh, bu [MW, full year; rows = realisations]."""
    p = sch["pos"]
    hh, bu = np.atleast_2d(hh)[:, p], np.atleast_2d(bu)[:, p]
    sol_a, win_a = inp["solar ac"][p], inp["wind ac"][p]
    e_res = (sol_a + win_a) - (inp["solar fc"][p] + inp["wind fc"][p])
    e_load = (hh + bu) - (inp["hh MWh"] * inp["hh shape"][p] + inp["bu MWh"] * inp["bu shape"][p])
    e = e_res - e_load  # imbalance [MW], + = long
    imb_rev = settle(e, inp["imb"][p])
    wheel = WHEELING * (np.abs(hh).sum(axis=1) + np.abs(bu).sum(axis=1) + sol_a.sum() + win_a.sum()
                        + np.abs(sch["cs"]).sum() + np.abs(sch["bess"]).sum() + np.abs(sch["net"] + e).sum(axis=1))
    share = len(p) / (pd.Timestamp(f"{year + 1}-01-01") - pd.Timestamp(f"{year}-01-01")).days / 24
    res_om = 1000 * (spec["solar MW"] * SOLAR_OM + spec["wind MW"] * WIND_OM) * share + WIND_VOM * win_a.sum()
    consumed = (hh + bu).sum(axis=1) + sch["ev ch"].sum() - sch["ev dis"].sum()
    cost = wheel + sch["uos"] + sch["vom"] + res_om - sch["profit"] - imb_rev
    return {"imbalance volume [MWh]": np.abs(e).sum(axis=1), "imbalance revenue [EUR]": imb_rev, "wheeling [EUR]": wheel,
            "community energy cost [EUR/MWh]": cost / consumed, "e": e}


def metrics(err, actual):
    e = np.asarray(err, float)
    return {"MAE [kW]": 1000 * np.abs(e).mean(), "RMSE [kW]": 1000 * np.sqrt((e ** 2).mean()),
            "nMAE [% of mean actual]": 100 * np.abs(e).mean() / np.mean(actual), "nRMSE [% of mean actual]": 100 * np.sqrt((e ** 2).mean()) / np.mean(actual),
            "bias [% of mean actual]": 100 * e.mean() / np.mean(actual), "P5 [kW]": 1000 * np.percentile(e, 5), "P95 [kW]": 1000 * np.percentile(e, 95),
            "lag-1 autocorrelation": float(np.corrcoef(e[1:], e[:-1])[0, 1])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="DRJ_MultiYear_v13_executed_logs")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    folder = runs_folder(a.folder)
    out = Path(a.out) if a.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    ov = overview(folder)
    met, check, mc_rows, bs_rows = [], [], [], []
    rng = np.random.default_rng(20261104)
    for year in YEARS:
        spec = ov[f"{year}_A2"]
        inp = year_inputs(folder, year, spec)
        hh_ac, bu_ac = inp["hh MWh"] * inp["hh ac shape"], inp["bu MWh"] * inp["bu ac shape"]
        hh_fc, bu_fc = inp["hh MWh"] * inp["hh shape"], inp["bu MWh"] * inp["bu shape"]
        sch = {s: schedule(folder, f"{year}_{s}1", inp["index"]) for s in "ABC"}
        p = sch["A"]["pos"]  # the run's hours (identical in A, B, C)
        # 1. error metrics on the run's hours
        series = {"solar": (inp["solar ac"] - inp["solar fc"], inp["solar ac"]), "wind": (inp["wind ac"] - inp["wind fc"], inp["wind ac"]),
                  "RES": (inp["solar ac"] + inp["wind ac"] - inp["solar fc"] - inp["wind fc"], inp["solar ac"] + inp["wind ac"]),
                  "households": (hh_ac - hh_fc, hh_ac), "businesses": (bu_ac - bu_fc, bu_ac), "native load": (hh_ac + bu_ac - hh_fc - bu_fc, hh_ac + bu_ac)}
        for name, (e, act) in series.items():
            met.append({"year": year, "series": name, **metrics(e[p], act[p])})
        net = series["RES"][0] - series["native load"][0]
        met.append({"year": year, "series": "net error (= imbalance)", **metrics(net[p], (hh_ac + bu_ac)[p])})
        for name, dev in [("intraday - day-ahead price", inp["id"] - inp["da"]), ("imbalance - day-ahead price", inp["imb"] - inp["da"])]:
            d = dev[p]
            met.append({"year": year, "series": name, "MAE [EUR/MWh]": np.abs(d).mean(), "RMSE [EUR/MWh]": np.sqrt((d ** 2).mean()),
                        "P5 [EUR/MWh]": np.percentile(d, 5), "P95 [EUR/MWh]": np.percentile(d, 95), "lag-1 autocorrelation": float(np.corrcoef(d[1:], d[:-1])[0, 1])})
        # reconstruction check against the PLEXOS X.2 runs (measured load realisation)
        base = {s: x2_kpis(inp, sch[s], spec, hh_ac, bu_ac, year) for s in "ABC"}
        for s in "ABC":
            r2 = Run(folder, f"{year}_{s}2")
            plx_rev = float(r2("Market", "Imbalance price", "Net Revenue").sum())
            plx_wheel = WHEELING * sum(float(r2("Line", line, "Flow").abs().sum()) for line in LINES)
            check.append({"model": f"{year}_{s}2", "imbalance revenue, PLEXOS [EUR]": plx_rev, "reconstructed [EUR]": float(base[s]["imbalance revenue [EUR]"][0]),
                          "wheeling, PLEXOS [EUR]": plx_wheel, "wheeling reconstructed [EUR]": float(base[s]["wheeling [EUR]"][0]),
                          "community energy cost reconstructed [EUR/MWh]": float(base[s]["community energy cost [EUR/MWh]"][0])})
        # 2. Monte Carlo of the load error
        n = len(inp["index"])
        e = load_errors(n, [SEED + year + 10_000 * (k + 1) for k in range(a.n)])
        hh, bu = actual_load(inp, e)
        sims = {s: x2_kpis(inp, sch[s], spec, hh, bu, year) for s in "ABC"}
        for s in "ABC":
            for k in ["imbalance volume [MWh]", "imbalance revenue [EUR]", "community energy cost [EUR/MWh]"]:
                v = sims[s][k]
                mc_rows.append({"year": year, "scenario": f"{s}.2", "KPI": k, "measured realisation": float(base[s][k][0]), "MC mean": v.mean(),
                                "MC std": v.std(), "MC 2.5 %": np.percentile(v, 2.5), "MC 50 %": np.percentile(v, 50), "MC 97.5 %": np.percentile(v, 97.5)})
        for s in "BC":
            d = sims[s]["community energy cost [EUR/MWh]"] - sims["A"]["community energy cost [EUR/MWh]"]
            d0 = float(base[s]["community energy cost [EUR/MWh]"][0] - base["A"]["community energy cost [EUR/MWh]"][0])
            mc_rows.append({"year": year, "scenario": f"{s}.2 - A.2", "KPI": "community energy cost [EUR/MWh]", "measured realisation": d0,
                            "MC mean": d.mean(), "MC std": d.std(), "MC 2.5 %": np.percentile(d, 2.5), "MC 50 %": np.percentile(d, 50), "MC 97.5 %": np.percentile(d, 97.5)})
        # 3. day-block bootstrap of the measured year (paired over scenarios)
        days = len(p) // 24
        idx_days = rng.integers(0, days, size=(a.n, days))
        for s in "ABC":
            sc = sch[s]
            k = base[s]
            e_s = k["e"][0][: days * 24].reshape(days, 24)
            imb_d = settle(e_s, inp["imb"][p][: days * 24].reshape(days, 24))
            # daily cost terms of the community energy cost
            hh_d, bu_d = hh_ac[p][: days * 24].reshape(days, 24), bu_ac[p][: days * 24].reshape(days, 24)
            sol_d, win_d = inp["solar ac"][p][: days * 24].reshape(days, 24), inp["wind ac"][p][: days * 24].reshape(days, 24)
            grid_d = np.abs(sc["net"][: days * 24] + e_s.ravel()).reshape(days, 24)
            wheel_d = WHEELING * (np.abs(hh_d) + np.abs(bu_d) + sol_d + win_d + grid_d + np.abs(sc["cs"][: days * 24]).reshape(days, 24)
                                  + np.abs(sc["bess"][: days * 24]).reshape(days, 24)).sum(axis=1)
            r1 = Run(folder, f"{year}_{s}1")
            prof_d = sum(r1("Market", m, "Net Revenue", pd.Series(0.0, index=sc["index"])).to_numpy()[: days * 24] for m in ["Day-Ahead energy price", "Intraday energy price"]).reshape(days, 24).sum(axis=1)
            uos_d = r1("Charging Station", "CS1", "UoS Cost").to_numpy()[: days * 24].reshape(days, 24).sum(axis=1)
            vom_d = r1("Battery", "Stationary Battery", "VO&M Cost").to_numpy()[: days * 24].reshape(days, 24).sum(axis=1)
            om_d = 1000 * (spec["solar MW"] * SOLAR_OM + spec["wind MW"] * WIND_OM) / (365 + (year == 2024)) + WIND_VOM * win_d.sum(axis=1)
            cons_d = (hh_d + bu_d).sum(axis=1) + (sc["ev ch"] - sc["ev dis"])[: days * 24].reshape(days, 24).sum(axis=1)
            cost_d = wheel_d + uos_d + vom_d + om_d - prof_d - imb_d
            boot_cost = cost_d[idx_days].sum(axis=1) / cons_d[idx_days].sum(axis=1)
            boot_imb = imb_d[idx_days].sum(axis=1) * len(p) / (days * 24)
            for kname, v, v0 in [("imbalance revenue [EUR]", boot_imb, float(base[s]["imbalance revenue [EUR]"][0])),
                                 ("community energy cost [EUR/MWh]", boot_cost, cost_d.sum() / cons_d.sum())]:
                bs_rows.append({"year": year, "scenario": f"{s}.2", "KPI": kname, "measured": v0, "bootstrap std": v.std(),
                                "bootstrap 2.5 %": np.percentile(v, 2.5), "bootstrap 97.5 %": np.percentile(v, 97.5)})
            if s == "A":
                boot_a = boot_cost
            else:
                d = boot_cost - boot_a
                bs_rows.append({"year": year, "scenario": f"{s}.2 - A.2", "KPI": "community energy cost [EUR/MWh]", "measured": float(np.mean(d)),
                                "bootstrap std": d.std(), "bootstrap 2.5 %": np.percentile(d, 2.5), "bootstrap 97.5 %": np.percentile(d, 97.5)})
        # 4. error scaling (linear): imbalance revenue for k x the measured error
        for s in "ABC":
            for kf in [0.5, 1.5, 2.0]:
                mc_rows.append({"year": year, "scenario": f"{s}.2", "KPI": f"imbalance revenue, error x{kf:g} [EUR]",
                                "measured realisation": float(settle(kf * base[s]["e"][0], inp["imb"][p]))})
    pd.DataFrame(met).to_csv(out / "forecast_error_metrics.csv", sep=";", index=False, float_format="%.4f")
    chk = pd.DataFrame(check)
    chk.to_csv(out / "forecast_reconstruction_check.csv", sep=";", index=False, float_format="%.4f")
    mc = pd.DataFrame(mc_rows)
    mc.to_csv(out / "forecast_mc_summary.csv", sep=";", index=False, float_format="%.4f")
    bs = pd.DataFrame(bs_rows)
    bs.to_csv(out / "forecast_bootstrap_summary.csv", sep=";", index=False, float_format="%.4f")
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print(chk.round(3).to_string(index=False))
        print(pd.DataFrame(met).round(2).to_string(index=False))
        print(mc.round(2).to_string(index=False))
        print(bs.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
