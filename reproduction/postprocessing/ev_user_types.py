# Made by Francesco Maldonato on 10/11/2026
"""EV user types (paper Section VI-F, Fig. 9): cost and profit, cycling and wear, and statistical inference per type.

    python3 ev_user_types.py            # runs/DRJ_MultiYear_v13_executed_logs -> results/

User types are the four PLEXOS Vehicle objects of the fleet (cohorts; preprocessing/ev_dataset/make_ev_dataset.py):
RC residents' commuter EVs, RO residents' other EVs, WF employees' EVs with full-day stays, WP employees' EVs with part-day
stays; groups: residents (RC + RO) and employees (WF + WP). Every value "per EV" is the cohort's value divided by its Units,
i.e. the mean EV of the cohort (the cohort pools the energy of its EVs; individual EVs are not modelled).

Per user type, scenario (A.1, B.1, C.1: the settlement stage replays the same EV schedule) and year:
- net charging cost = energy bill at the charging station's hourly prices (Charge Cost / fleet charging, Discharge
  Revenue / fleet discharge). PLEXOS's Charge Cost and Discharge Revenue of the charging station already contain its
  use-of-system (UoS) fee of 20 EUR/MWh on charged and on discharged energy (charge price = node price + UoS, discharge
  price = node price - UoS; verified hour by hour), so the UoS is NOT added again; it is reported for information, with
  the ex-post cost without the UoS (bill - UoS);
- gain against V1G = net cost in A - net cost in B or C (same user type and year), and the captured spread (mean
  discharge price - mean charge price, both net of the UoS);
- battery throughput (energy into the battery + out of it for V2G and driving, battery side), equivalent full cycles (EFC,
  of which V2G), wear cost at 1.88 ct/kWh (weighted Ah-throughput model of Preis & Biedenbach 2023 with an NMC pack at
  113 EUR/kWh and 3,000 EFC to 80 % SoH; common.py, paper Eq. 5), the net gain after the added wear against V1G, and the
  break-even wear cost (paper Eq. 7);
- availability: connected share of all hours and of the four cheapest and four dearest day-ahead hours of each day.
Inference over the days of each year (the day is the unit; daily net cost per EV of each user type):
- daily gain against V1G: mean, standard deviation, 5/50/95 % quantiles, share of days with a positive gain;
- 95 % confidence interval of the annual gain per EV by a moving-block bootstrap of the days (blocks of 7 days, which keep
  the weekly pattern and the autocorrelation of prices; 2,000 resamples);
- the user types share the days, so they are compared paired by day: Friedman test over the four types; for pairs
  (residents - employees, units-weighted mean EV of each group; RO - RC; WF - WP; RC - WF) the annual sum of the daily
  difference with its moving-block bootstrap interval and a Wilcoxon signed-rank test (Holm correction). The daily gains
  are skewed (a minority of volatile days carries most of the gain: share of the gain on the best 10 % of days), so tests
  of medians between unpaired samples (Mann-Whitney) have little power here; days are autocorrelated, so p-values are
  indicative and the block-bootstrap intervals are the main result;
- ordinary least squares of the daily gain per EV on the day's 4-hour price spread (mean of the 4 highest minus the 4
  lowest hourly prices) of the market that drives it: day-ahead for B, intraday for C: slope per 100 EUR/MWh, R^2.
Fleet mix (2025, S-MIX levels and the base, B.1 and C.1): net cost per EV of each user type and of the fleet, against the
share of residents' EVs: does the value of a user type depend on the composition of the fleet?

Writes into results/: ev_user_types.csv (every user type, group, scenario, year and the three-year mean; the data of
Fig. 9), ev_user_types_spread.csv (spread over the 100 EVs and the years), ev_user_types_inference.csv (daily statistics,
bootstrap intervals, regressions), ev_user_types_tests.csv (paired comparisons) and ev_user_types_mix.csv (fleet mix).
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from common import C_DEG, EVS, RESULTS, UOS, WH_KM, YEARS, Run, ev_profiles, ev_units, hourly, overview, runs_folder

COHORT = dict(zip(EVS, ["RC", "RO", "WF", "WP"]))
NAME = {"RC": "residents, commuter", "RO": "residents, other use", "WF": "employees, full day", "WP": "employees, part day"}
GROUPS = {"residents": ["RC", "RO"], "employees": ["WF", "WP"]}
NMC = C_DEG  # EUR per kWh of battery throughput (common.py)
SCEN = ["A", "B", "C"]
BLOCK, N_BOOT, SEED = 7, 2000, 20251106
MIX = {"S-MIX0": 0, "S-MIX25": 25, "S-MIX50": 50, None: 65, "S-MIX75": 75, "S-MIX100": 100}


def station_prices(run):
    ch = sum(run("Vehicle", ev, "Charging", 0.0) for ev in EVS)
    dis = sum(run("Vehicle", ev, "Discharging", 0.0) for ev in EVS)
    cost = run("Charging Station", "CS1", "Charge Cost")
    rev = run("Charging Station", "CS1", "Discharge Revenue", 0 * cost)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (cost / ch).where(ch > 1e-9).fillna(0), (rev / dis).where(dis > 1e-9).fillna(0)


def cohort_series(folder, model, spec, year):
    """{cohort: DataFrame of hourly per-EV quantities} of one run (cohorts with Units > 0)."""
    run = Run(folder, model)
    idx = run("Generator", "Solar G1", "Generation").index
    prof = ev_profiles(folder, year, idx)
    p_ch, p_dis = station_prices(run)
    eta, cap = spec["EV efficiency %"] / 100, spec["EV kWh"]
    out = {}
    for ev, n in ev_units(spec).items():
        if n < 0.5:
            continue
        ch = run("Vehicle", ev, "Charging") / n
        dis = run("Vehicle", ev, "Discharging", 0 * ch) / n
        conn, km = prof[ev]
        out[COHORT[ev]] = pd.DataFrame({"charged kWh": ch, "V2G kWh": dis, "bill EUR": ch * p_ch - dis * p_dis,
                                        "UoS EUR": UOS / 1000 * (ch + dis), "charge price": p_ch, "discharge price": p_dis,
                                        "throughput kWh": ch * eta + dis / eta + km * WH_KM[ev] / 1000, "connected": conn,
                                        "units": n, "cap": cap, "eta": eta})
    return out, idx


def annual(df):
    ch, dis = df["charged kWh"].sum(), df["V2G kWh"].sum()
    thr = df["throughput kWh"].sum()
    cap = df["cap"].iloc[0]
    return {"connected [%]": 100 * df.connected.mean(), "charged [kWh/EV]": ch, "V2G [kWh/EV]": dis,
            "bill [EUR/EV]": df["bill EUR"].sum(), "UoS [EUR/EV]": df["UoS EUR"].sum(),
            "net cost [EUR/EV]": df["bill EUR"].sum(),  # the station prices already contain the UoS fee
            "net cost without UoS [EUR/EV]": df["bill EUR"].sum() - df["UoS EUR"].sum(),
            "charge price [ct/kWh]": 100 * (df["charged kWh"] * df["charge price"]).sum() / ch if ch else np.nan,
            "V2G price [ct/kWh]": 100 * (df["V2G kWh"] * df["discharge price"]).sum() / dis if dis > 1e-6 else np.nan,
            "throughput [kWh/EV]": thr, "EFC [-]": thr / 2 / cap, "V2G EFC [-]": df["V2G kWh"].sum() / df["eta"].iloc[0] / cap,
            "degradation NMC 1.88 ct/kWh [EUR/EV]": NMC * thr}


def spread4(p, idx):
    d = pd.Series(np.asarray(p, float), index=idx)
    return d.groupby(d.index.date).apply(lambda x: np.sort(x.to_numpy())[-4:].mean() - np.sort(x.to_numpy())[:4].mean())


def block_bootstrap(x, rng):
    """Moving-block bootstrap of the annual sum of a daily series: 95 % interval."""
    x = np.asarray(x, float)
    n = len(x)
    starts = np.arange(n - BLOCK + 1)
    k = int(np.ceil(n / BLOCK))
    sums = np.empty(N_BOOT)
    for i in range(N_BOOT):
        s = rng.choice(starts, k)
        sums[i] = np.concatenate([x[j:j + BLOCK] for j in s])[:n].sum()
    return np.percentile(sums, [2.5, 97.5])


def block_bootstrap_paired(d, rng):
    """95 % interval of the annual sum of a paired daily difference, moving blocks of BLOCK days."""
    return block_bootstrap(d, rng)


def holm(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    adj = np.empty_like(p)
    m = len(p)
    running = 0.0
    for r, i in enumerate(order):
        running = max(running, min(1.0, (m - r) * p[i]))
        adj[i] = running
    return adj


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="DRJ_MultiYear_v13_executed_logs")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    folder = runs_folder(a.folder)
    out = Path(a.out) if a.out else RESULTS
    out.mkdir(parents=True, exist_ok=True)
    ov = overview(folder)
    rng = np.random.default_rng(SEED)
    rows, daily = [], []
    series = {}
    for y in YEARS:
        prices = {}
        for s in SCEN:
            m = f"{y}_{s}1"
            if not Run(folder, m).exists():
                raise SystemExit(f"{m}: not run")
            series[(y, s)], idx = cohort_series(folder, m, ov[m], y)
            prices = {"DA": hourly(folder, ov[m]["DA price file"], idx), "ID": hourly(folder, ov[m]["ID price file"], idx)}
            for c, df in series[(y, s)].items():
                r = annual(df)
                da = prices["DA"].to_numpy()
                day = pd.Series(da, index=idx).groupby(idx.date)
                cheap = day.transform(lambda x: x.rank(method="first") <= 4).to_numpy(bool)
                dear = day.transform(lambda x: x.rank(method="first", ascending=False) <= 4).to_numpy(bool)
                r["connected, 4 cheapest DA h [%]"] = 100 * df.connected[cheap].mean()
                r["connected, 4 dearest DA h [%]"] = 100 * df.connected[dear].mean()
                rows.append({"year": y, "scenario": s, "user type": c, "units": df.units.iloc[0], **r})
                d = df["bill EUR"].groupby(idx.date).sum()  # UoS included in the station prices
                daily.append(pd.DataFrame({"year": y, "scenario": s, "user type": c, "date": d.index, "net cost [EUR/EV]": d.to_numpy()}))
        spreads = {k: spread4(v, idx) for k, v in prices.items()}
        series[(y, "spread")] = spreads
    df = pd.DataFrame(rows)
    # gain against V1G, net of the extra degradation
    a_ = df[df.scenario == "A"].set_index(["year", "user type"])
    key = list(zip(df.year, df["user type"]))
    df["gain vs V1G [EUR/EV]"] = [a_.loc[k, "net cost [EUR/EV]"] for k in key] - df["net cost [EUR/EV]"]
    df["gain vs V1G without UoS [EUR/EV]"] = [a_.loc[k, "net cost without UoS [EUR/EV]"] for k in key] - df["net cost without UoS [EUR/EV]"]
    df["extra throughput vs V1G [kWh/EV]"] = df["throughput [kWh/EV]"] - [a_.loc[k, "throughput [kWh/EV]"] for k in key]
    df["gain after degradation NMC [EUR/EV]"] = df["gain vs V1G [EUR/EV]"] - NMC * df["extra throughput vs V1G [kWh/EV]"]
    with np.errstate(invalid="ignore", divide="ignore"):
        df["break-even degradation [ct/kWh]"] = np.where(df["extra throughput vs V1G [kWh/EV]"] > 1,
                                                         100 * df["gain vs V1G [EUR/EV]"] / df["extra throughput vs V1G [kWh/EV]"], np.nan)
    df["captured spread [ct/kWh]"] = df["V2G price [ct/kWh]"] - df["charge price [ct/kWh]"]
    # groups (Units-weighted) and three-year means
    num = [c for c in df.columns if c not in ("year", "scenario", "user type", "units")]
    grp = []
    for g, cs in GROUPS.items():
        for (y, s), sub in df[df["user type"].isin(cs)].groupby(["year", "scenario"]):
            w = sub.units.to_numpy()
            grp.append({"year": y, "scenario": s, "user type": g, "units": w.sum(),
                        **{c: np.average(sub[c].fillna(0) if "price" not in c and "spread" not in c else sub[c], weights=w) for c in num}})
    for (y, s), sub in df.groupby(["year", "scenario"]):
        w = sub.units.to_numpy()
        grp.append({"year": y, "scenario": s, "user type": "fleet", "units": w.sum(),
                    **{c: np.average(sub[c].fillna(0) if "price" not in c and "spread" not in c else sub[c], weights=w) for c in num}})
    full = pd.concat([df, pd.DataFrame(grp)], ignore_index=True)
    mean = full.groupby(["scenario", "user type"], sort=False)[num + ["units"]].mean().reset_index()
    lo = full.groupby(["scenario", "user type"], sort=False)[num].min().add_suffix(" min").reset_index(drop=True)
    hi = full.groupby(["scenario", "user type"], sort=False)[num].max().add_suffix(" max").reset_index(drop=True)
    mean = pd.concat([mean, lo, hi], axis=1)
    mean.insert(0, "year", "2023-2025")
    pd.concat([full, mean], ignore_index=True).to_csv(out / "ev_user_types.csv", sep=";", index=False, float_format="%.4f")
    # spread of the annual result per EV over the fleet's EVs and the years (Section VI-F): every cohort-year
    # weighted by its EVs (Units); cohorts are aggregate objects, so the spread between the cars of a cohort is not resolved
    spread = []
    for s in ["A", "B", "C"]:
        sub = full[(full.scenario == s) & full["user type"].isin(list(COHORT.values()))]
        for k in ["net cost [EUR/EV]", "gain vs V1G [EUR/EV]"]:
            x, w = sub[k].to_numpy(float), sub.units.to_numpy(float)
            m = np.average(x, weights=w)
            spread.append({"scenario": s, "KPI": k, "mean": m, "std": np.sqrt(np.average((x - m) ** 2, weights=w)),
                           "min": x.min(), "max": x.max(), "min at": " ".join(sub.iloc[x.argmin()][["user type", "year"]].astype(str)),
                           "max at": " ".join(sub.iloc[x.argmax()][["user type", "year"]].astype(str))})
    pd.DataFrame(spread).to_csv(out / "ev_user_types_spread.csv", sep=";", index=False, float_format="%.2f")

    # ---------------- inference over the days
    dd = pd.concat(daily, ignore_index=True)
    piv = dd.pivot_table(index=["year", "user type", "date"], columns="scenario", values="net cost [EUR/EV]").reset_index()
    inf_rows, test_rows = [], []
    for s, mkt in [("B", "DA"), ("C", "ID")]:
        piv[f"gain {s}"] = piv["A"] - piv[s]
        for y in YEARS:
            sp = series[(y, "spread")][mkt]
            gains = {}
            for c in COHORT.values():
                g = piv[(piv.year == y) & (piv["user type"] == c)].set_index("date")[f"gain {s}"]
                gains[c] = g.to_numpy()
                ci = block_bootstrap(g.to_numpy(), rng)
                x = sp.reindex(g.index).to_numpy() / 100
                ok = np.isfinite(x)
                reg = stats.linregress(x[ok], g.to_numpy()[ok])
                inf_rows.append({"scenario": s, "year": y, "user type": c, "annual gain [EUR/EV]": g.sum(),
                                 "95% CI low": ci[0], "95% CI high": ci[1], "daily mean [EUR/EV]": g.mean(), "daily std [EUR/EV]": g.std(),
                                 "daily p5": np.percentile(g, 5), "daily p50": np.percentile(g, 50), "daily p95": np.percentile(g, 95),
                                 "days with gain > 0 [%]": 100 * (g > 0).mean(),
                                 "share of the gain on the best 10 % of days [%]": 100 * np.sort(g.to_numpy())[-int(round(0.1 * len(g))):].sum() / g.sum()
                                 if g.sum() > 0 else np.nan, "spread market": mkt,
                                 "slope [EUR/EV per day per 100 EUR/MWh]": reg.slope, "R2": reg.rvalue ** 2, "p slope": reg.pvalue})
            # the user types share the days: paired comparisons (Friedman over the four types; for pairs the daily difference,
            # its annual sum with a block-bootstrap interval and a Wilcoxon signed-rank test)
            fr = stats.friedmanchisquare(*gains.values())
            test_rows.append({"scenario": s, "year": y, "test": "Friedman, four user types (paired by day)", "statistic": fr.statistic,
                              "annual difference [EUR/EV]": np.nan, "95% CI low": np.nan, "95% CI high": np.nan, "p": fr.pvalue, "p (Holm)": fr.pvalue})
            pairs = [("residents", "employees"), ("RO", "RC"), ("WF", "WP"), ("RC", "WF")]
            pv, stat_rows = [], []
            w = {"residents": None, "employees": None}
            for p1, p2 in pairs:
                x1 = np.mean([gains[c] for c in GROUPS[p1]], axis=0) if p1 in GROUPS else gains[p1]
                x2 = np.mean([gains[c] for c in GROUPS[p2]], axis=0) if p2 in GROUPS else gains[p2]
                d = x1 - x2
                ci = block_bootstrap_paired(d, rng)
                wt = stats.wilcoxon(d[np.abs(d) > 1e-9]) if (np.abs(d) > 1e-9).sum() > 10 else None
                pv.append(wt.pvalue if wt else 1.0)
                stat_rows.append({"scenario": s, "year": y, "test": f"{p1} - {p2} (paired by day; Wilcoxon signed-rank)",
                                  "statistic": wt.statistic if wt else np.nan, "annual difference [EUR/EV]": d.sum(),
                                  "95% CI low": ci[0], "95% CI high": ci[1], "days with a positive difference [%]": 100 * (d > 1e-9).mean()})
            for r_, p_adj, p_raw in zip(stat_rows, holm(pv), pv):
                test_rows.append({**r_, "p": p_raw, "p (Holm)": p_adj})
    inf = pd.DataFrame(inf_rows)
    inf.to_csv(out / "ev_user_types_inference.csv", sep=";", index=False, float_format="%.4f")
    tests = pd.DataFrame(test_rows)
    tests.to_csv(out / "ev_user_types_tests.csv", sep=";", index=False, float_format="%.4g")

    # ---------------- fleet mix (2025)
    mix_rows = []
    for lvl, share in MIX.items():
        for s in ["B", "C"]:
            m = f"{lvl}_{s}1" if lvl else f"2025_{s}1"
            if not Run(folder, m).exists():
                continue
            ser, _ = cohort_series(folder, m, ov[m], 2025)
            tot_u, tot_c = 0.0, 0.0
            for c, d_ in ser.items():
                r = annual(d_)
                mix_rows.append({"residents' EVs [%]": share, "scenario": s, "user type": c, "units": d_.units.iloc[0], **r})
                tot_u += d_.units.iloc[0]
                tot_c += d_.units.iloc[0] * r["net cost [EUR/EV]"]
            for g, cs in GROUPS.items():
                sub = [(ser[c].units.iloc[0], annual(ser[c])["net cost [EUR/EV]"]) for c in cs if c in ser]
                if sub:
                    mix_rows.append({"residents' EVs [%]": share, "scenario": s, "user type": g, "units": sum(u for u, _ in sub),
                                     "net cost [EUR/EV]": sum(u * v for u, v in sub) / sum(u for u, _ in sub)})
            mix_rows.append({"residents' EVs [%]": share, "scenario": s, "user type": "fleet", "units": tot_u, "net cost [EUR/EV]": tot_c / tot_u})
    mix = pd.DataFrame(mix_rows)
    mix.to_csv(out / "ev_user_types_mix.csv", sep=";", index=False, float_format="%.4f")

    pd.set_option("display.width", 220)
    cols = ["scenario", "user type", "connected [%]", "net cost [EUR/EV]", "gain vs V1G [EUR/EV]", "gain vs V1G min", "gain vs V1G max",
            "captured spread [ct/kWh]", "EFC [-]", "V2G EFC [-]", "gain after degradation NMC [EUR/EV]", "break-even degradation [ct/kWh]",
            "connected, 4 cheapest DA h [%]", "connected, 4 dearest DA h [%]"]
    mean = mean.rename(columns={"gain vs V1G [EUR/EV] min": "gain vs V1G min", "gain vs V1G [EUR/EV] max": "gain vs V1G max"})
    print(mean[cols].round(1).to_string(index=False))
    print(inf.round(2).to_string(index=False))
    print(tests.round(4).to_string(index=False))
    print(mix[mix["user type"].isin(["RC", "RO", "WF", "WP", "fleet"])][["residents' EVs [%]", "scenario", "user type", "net cost [EUR/EV]", "EFC [-]"]].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
