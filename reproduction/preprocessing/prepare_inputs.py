# Made by Francesco Maldonato on 10/11/2026
"""Model inputs from the raw data in data/: prices, wind and solar profiles, consumer load (paper Section IV-F).

    python3 prepare_inputs.py               # 2023 and 2024 inputs, and the actual load of 2023-2025
    python3 prepare_inputs.py --check-2025  # rebuild 2025 in memory and compare it with the shipped 2025 files

Writes into model/DRJ_MultiYear_v13/data_files/<year>/ the hourly PLEXOS files (Year;Month;Day;Period;Value):
- market-dayahead-prices_1H_germany-<year>.csv     ENTSO-E day-ahead price, bidding zone DE-LU (sequence 1);
- market-imbalances-prices_1H_germany-<year>.csv   ENTSO-E imbalance price of Germany (2024, 2025; 2023: restricted, below);
- {solar,wind}-profile-{da,ac}_1H_germany-<year>.csv  day-ahead forecast and actual generation of the 50Hertz control area,
                                                      per MW of its installed capacity (CAPACITY);
- stromnetz_{households,general_business}_normalized_demand_1h_MW.csv  load forecast: Stromnetz Berlin's standard load
                                                      profile of the year, summing to 1;
- stromnetz-noise_{households,general_business}_normalized_demand_1h_MW.csv  actual load: the forecast x (1 + e_t), e_t
                                                      uniform within +-20 %, persistent (Gaussian AR(1) copula, lag-1
                                                      correlation 0.8), one fixed seed per year, rescaled to sum to 1.
Processing: quarter-hours on a UTC axis, averaged to local clock hours (the repeated autumn hour averaged, the skipped
spring hour interpolated); a price of exactly 0 is written as 1e-6 (PLEXOS reads 0 as "no value"); prices rounded to 4
decimals (lossless for hourly means of 2-decimal quarter-hour prices).

Not built here (restricted, fetch_restricted_inputs.py): the intraday price ID-AEP of all years and the 2023 imbalance price
(Netztransparenz), and the grid carbon intensity (Electricity Maps).

The 2023 and 2024 files are rebuilt exactly. The shipped 2025 files are the originals of the study: they differ from this
method only in a few hours around the two daylight-saving switches (placeholder values 1e-6; --check-2025 lists them), so
they are kept as they are.
"""
import argparse
import csv
import math
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "entsoe"
SLP = REPO / "data" / "load_profiles"
OUT = REPO / "model" / "DRJ_MultiYear_v13" / "data_files"
TZ = "Europe/Berlin"

# raw ENTSO-E Transparency Platform exports (data/entsoe/) and Stromnetz Berlin standard load profiles (data/load_profiles/)
RAW_FILES = {y: dict(da=f"day_ahead_prices_DE-LU_{y}.csv.gz", imb=f"imbalance_prices_DE_{y}.csv.gz",
                     solar=f"solar_generation_50Hertz_{y}.csv.gz", wind=f"wind_onshore_generation_50Hertz_{y}.csv.gz",
                     hh=f"standard_load_profile_households_{y}.xlsx", gb=f"standard_load_profile_business_{y}.xlsx")
             for y in (2023, 2024, 2025)}
# installed capacity of the 50Hertz control area (ENTSO-E "Installed capacity per production type"), MW: (solar, onshore wind)
CAPACITY = {2023: (16250.38, 20756.41), 2024: (20738.0, 20794.0), 2025: (21413.0, 21617.0)}
ZERO = 1e-6  # PLEXOS reads a price of exactly 0 as "no value"
PRICE_DECIMALS = 4
# actual consumer load: forecast x (1 + e_t), e_t uniform in [-BOUND, +BOUND], persistent (lag-1 correlation RHO)
BOUND, RHO, SEED = 0.20, 0.8, 9000  # rng seed = SEED + year
LOAD_KINDS = ["households", "general_business"]


def year_hours(year):
    return pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")


def quarter_hours_utc(year):
    return pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="15min", tz=TZ, inclusive="left").tz_convert("UTC")


def local_hourly(s_utc, year):
    """UTC series -> local clock hours: repeated autumn hour averaged, skipped spring hour interpolated."""
    h = s_utc.resample("h").mean()
    h.index = h.index.tz_convert(TZ).tz_localize(None)
    h = h.groupby(level=0).mean().reindex(year_hours(year))
    return h.interpolate(limit_direction="both")


def gui_quarter_hours(path, year, value_col, sequence=None):
    """ENTSO-E GUI export -> UTC quarter-hour series (rows are consecutive quarter-hours of the local year), and its area."""
    df = pd.read_csv(path, dtype=str)
    if sequence is not None:
        df = df[df["Sequence"].str.replace("Sequence ", "").str.strip() == str(sequence)]
    idx = quarter_hours_utc(year)
    assert len(df) == len(idx), f"{path.name}: {len(df)} rows, expected {len(idx)}"
    start = df.iloc[:, 0].str.split(" - ").str[0]
    plain = ~start.str.contains("(", regex=False).values
    parsed = pd.to_datetime(start[plain].str[:16], format="%d/%m/%Y %H:%M").values
    assert (parsed == idx.tz_convert(TZ).tz_localize(None)[plain].values).all(), f"{path.name}: rows are not consecutive quarter-hours"
    return pd.Series(pd.to_numeric(df[value_col].str.strip(), errors="coerce").values, index=idx), df["Area"].iloc[0]


def plexos_frame(series):
    t = series.index
    return pd.DataFrame({"Year": t.year, "Month": t.month, "Day": t.day, "Period": t.hour + 1, "Value": series.values})


def stromnetz(path, year):
    """Stromnetz Berlin profile (kWh per quarter-hour, local time) -> hourly profile summing to 1."""
    df = pd.read_excel(path)
    vc = df.columns[2]
    df = df.dropna(subset=[vc])
    t = pd.to_datetime(df["Datum"])
    if t.iloc[0] == pd.Timestamp(f"{year}-01-01 00:15"):  # the 2023 files stamp the end of the quarter-hour
        t = t - pd.to_timedelta(15, unit="min")
    h = pd.Series(df[vc].astype(float).values * 4, index=t.values).resample("h").mean().reindex(year_hours(year)).interpolate()
    return h / h.sum()


def build(year):
    """{file name: DataFrame} of one year's market, RES and load-forecast files."""
    f = RAW_FILES[year]
    files = {}
    s, _ = gui_quarter_hours(RAW / f["da"], year, "Day-ahead Price (EUR/MWh)", sequence=1)
    files[f"market-dayahead-prices_1H_germany-{year}.csv"] = local_hourly(s.replace(0, ZERO), year)
    if (RAW / f["imb"]).exists():  # 2023: the reBAP from Netztransparenz (restricted)
        s, area = gui_quarter_hours(RAW / f["imb"], year, "+Imbalance Price (EUR/MWh)")
        assert area == "IPA|DE", f"{f['imb']}: area {area}"
        files[f"market-imbalances-prices_1H_germany-{year}.csv"] = local_hourly(s.ffill().bfill().replace(0, ZERO), year)
    for tech, k in [("solar", 0), ("wind", 1)]:
        for col, tag in [("Day-ahead (MW)", "da"), ("Actual (MW)", "ac")]:
            s, area = gui_quarter_hours(RAW / f[tech], year, col)
            assert area == "CTA|DE(50Hertz)", f"{f[tech]}: area {area}"
            files[f"{tech}-profile-{tag}_1H_germany-{year}.csv"] = local_hourly(s / CAPACITY[year][k], year)
    for kind, key in [("households", "hh"), ("general_business", "gb")]:
        files[f"stromnetz_{kind}_normalized_demand_1h_MW.csv"] = stromnetz(SLP / f[key], year)
    out = {}
    for name, s in files.items():
        df = plexos_frame(s)
        assert len(df) == len(year_hours(year)) and not df.isna().any().any(), name
        if name.startswith("market-"):
            df["Value"] = df["Value"].round(PRICE_DECIMALS).replace(0.0, ZERO)
        out[name] = df
    return out


def relative_load_error(n, year):
    """e_t, t = 1..n: uniform on [-BOUND, BOUND], persistent (Gaussian AR(1) copula with lag-1 correlation RHO)."""
    rng = np.random.default_rng(SEED + year)
    w = rng.standard_normal(n)
    z = np.empty(n)
    z[0] = w[0]
    for t in range(1, n):
        z[t] = RHO * z[t - 1] + math.sqrt(1 - RHO ** 2) * w[t]
    u = 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))  # standard normal CDF
    return BOUND * (2 * u - 1)


def load_actuals(year):
    """Actual load files of one year from its forecast files: the same e_t for households and businesses (the error of the
    community's aggregate load forecast), rescaled so that the year sums to 1 again (the annual energy is unchanged)."""
    d = OUT / str(year)
    frames = {k: pd.read_csv(d / f"stromnetz_{k}_normalized_demand_1h_MW.csv", sep=";") for k in LOAD_KINDS}
    e = relative_load_error(len(frames["households"]), year)
    for kind, f in frames.items():
        raw = f.Value.to_numpy() * (1 + e)
        a = f.copy()
        a["Value"] = raw / raw.sum()
        a.to_csv(d / f"stromnetz-noise_{kind}_normalized_demand_1h_MW.csv", sep=";", index=False, quoting=csv.QUOTE_MINIMAL)
    return 100 * np.abs(e).mean()


def check_2025():
    """Rebuild 2025 with this method and compare with the shipped files."""
    print("2025 rebuilt vs data_files/2025:")
    for name, df in build(2025).items():
        ref = pd.read_csv(OUT / "2025" / name, sep=";")
        bad = np.flatnonzero(np.abs(df["Value"].values - ref["Value"].values) > 1e-9 * max(1.0, np.abs(ref["Value"]).max()))
        where = ", ".join(f"{ref.Month[i]:02d}-{ref.Day[i]:02d} hour {ref.Period[i]}" for i in bad[:4])
        print(f"  {name:58s} {len(bad):2d} differing hours  {where}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check-2025", action="store_true", help="compare a rebuild of 2025 with the shipped 2025 files")
    a = ap.parse_args()
    if a.check_2025:
        return check_2025()
    for year in [2023, 2024]:
        files = build(year)
        (OUT / str(year)).mkdir(parents=True, exist_ok=True)
        for name, df in files.items():
            df.to_csv(OUT / str(year) / name, sep=";", index=False)
        print(f"{year}: wrote {len(files)} files to {OUT.relative_to(REPO)}/{year}/")
    for year in [2023, 2024, 2025]:
        print(f"{year}: actual load written, mean |e_t| = {load_actuals(year):.1f} %")
    print("Restricted inputs still needed: preprocessing/fetch_restricted_inputs.py (README.md, step 3).")


if __name__ == "__main__":
    main()
