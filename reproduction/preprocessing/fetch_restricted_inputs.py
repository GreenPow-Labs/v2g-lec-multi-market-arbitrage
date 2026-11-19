# Made by Francesco Maldonato on 10/11/2026
"""Download the model inputs this repository may not redistribute, and write them into the model's data_files/<year>/.

    # grid carbon intensity (Electricity Maps), from the yearly CSV of the Electricity Maps data portal ...
    python3 fetch_restricted_inputs.py carbon --year 2024 --csv DE_2024_hourly.csv
    # ... or from the Electricity Maps API (an API key whose plan includes the past-range endpoint)
    export ELECTRICITYMAPS_API_KEY=...
    python3 fetch_restricted_inputs.py carbon --year 2024 --api

    # intraday price ID-AEP (all years) and reBAP (2023) from the Netztransparenz API (free registration at
    # netztransparenz.de: client id and secret of an API client)
    export NTP_CLIENT_ID=...  NTP_CLIENT_SECRET=...
    python3 fetch_restricted_inputs.py ntp --year 2024

Options: --model <folder> (default ../model/DRJ_MultiYear_v13; for the Zenodo runs: ../runs/DRJ_MultiYear_v13_executed_logs). Keys and secrets are read from the environment only
and never printed or written.

Why: Electricity Maps' terms of service do not allow redistributing its carbon-intensity series, and the Netztransparenz
data (the German TSOs' ID-AEP index and reBAP) are obtained through a personal API client. The repository therefore ships
neither; this script recreates the files the PLEXOS model and the post-processing read:
- data_files/<year>/carbon-intensity-gCO2eq-1H_germany-<year>.csv  (direct carbon intensity, gCO2eq/kWh; post-processing only)
- data_files/<year>/market-intraday-prices_1H_germany-<year>.csv  (ID-AEP, EUR/MWh; PLEXOS input)
- data_files/2023/market-imbalances-prices_1H_germany-2023.csv     (reBAP, EUR/MWh; PLEXOS input; 2024 and 2025 come from
  the ENTSO-E imbalance price export, which the repository ships)

Processing (as prepare_inputs.py): quarter-hours / UTC hours -> local clock hours (the repeated autumn hour
averaged, the skipped spring hour interpolated), a price of exactly 0 written as 1e-6 (PLEXOS reads 0 as 'no value'),
file format Year;Month;Day;Period;Value. Two conventions of the paper's 2025 files can be reproduced exactly:
--utc-as-period (2025 carbon intensity: the UTC hour used as the local period) and --dst-placeholder (2025 prices:
1e-6 in the two daylight-saving hours instead of the averaged / interpolated values).
"""
import argparse
import io
import os
import sys
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
TZ = "Europe/Berlin"
ZERO = 1e-6
EM_API = "https://api.electricitymaps.com/v3/carbon-intensity/past-range"
EM_CHUNK_DAYS = 7  # past-range returns a limited span per request
NTP_TOKEN_URL = "https://identity.netztransparenz.de/users/connect/token"
NTP_API = "https://ds.netztransparenz.de/api/v1/data"
NTP_SERIES = {"ID_AEP": ("IdAep", "AEP"), "reBAP": ("NrvSaldo/reBAP/Qualitaetsgesichert", "reBAP")}


def year_hours(year):
    return pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")


def local_hourly(s_utc, year):
    """UTC series -> local clock hours: repeated autumn hour averaged, skipped spring hour interpolated."""
    h = s_utc.resample("h").mean()
    h.index = h.index.tz_convert(TZ).tz_localize(None)
    h = h.groupby(level=0).mean().reindex(year_hours(year))
    return h.interpolate(limit_direction="both"), int(h.isna().sum())


def dst_hours(year):
    """The local hour 02:00-03:00 of the two DST change days (spring: skipped, autumn: repeated), period 3 in the files."""
    t = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz=TZ, inclusive="left")
    offsets = t.map(lambda x: x.utcoffset())
    changes = [i for i in range(1, len(t)) if offsets[i] != offsets[i - 1]]
    return [pd.Timestamp(t[i].date()) + pd.Timedelta(hours=2) for i in changes]


def plexos_file(series, path):
    t = series.index
    df = pd.DataFrame({"Year": t.year, "Month": t.month, "Day": t.day, "Period": t.hour + 1, "Value": series.values})
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, sep=";", index=False)
    print(f"wrote {path} ({len(df)} h, mean {series.mean():.2f}, min {series.min():.2f}, max {series.max():.2f})")


# ---------------------------------------------------------------- Electricity Maps
def carbon_from_csv(path):
    """Electricity Maps data-portal CSV -> UTC-indexed direct carbon intensity."""
    df = pd.read_csv(path)
    col = next(c for c in df.columns if c.lower().startswith("carbon intensity") and "direct" in c.lower())
    t = pd.to_datetime(df[next(c for c in df.columns if c.lower().startswith("datetime"))], utc=True)
    return pd.Series(df[col].astype(float).values, index=t).sort_index()


def carbon_from_api(year, zone="DE"):
    key = os.environ.get("ELECTRICITYMAPS_API_KEY")
    if not key:
        sys.exit("Set ELECTRICITYMAPS_API_KEY first (Electricity Maps API key with access to past-range).")
    start = pd.Timestamp(f"{year}-01-01", tz=TZ).tz_convert("UTC")
    end = pd.Timestamp(f"{year + 1}-01-01", tz=TZ).tz_convert("UTC")
    parts = []
    a = start
    while a < end:
        b = min(a + pd.Timedelta(days=EM_CHUNK_DAYS), end)
        r = requests.get(EM_API, headers={"auth-token": key}, timeout=120,
                         params={"zone": zone, "start": a.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": b.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "emissionFactorType": "direct", "temporalGranularity": "hourly"})
        if r.status_code != 200:
            sys.exit(f"Electricity Maps {a:%Y-%m-%d}: HTTP {r.status_code} {r.text[:200]}")
        rows = r.json().get("data", [])
        parts.append(pd.Series({pd.Timestamp(d["datetime"]): d["carbonIntensity"] for d in rows}, dtype=float))
        a = b
    s = pd.concat(parts)
    return s[~s.index.duplicated()].sort_index()


def carbon(args):
    s = carbon_from_api(args.year) if args.api else carbon_from_csv(args.csv)
    if args.utc_as_period:  # the paper's 2025 file: the UTC hour as the local period
        s = pd.Series(s.values, index=s.index.tz_localize(None)).reindex(year_hours(args.year)).interpolate(limit_direction="both")
    else:
        s, gaps = local_hourly(s, args.year)
        print(f"{gaps} hours interpolated")
    plexos_file(s.round(2), args.model / "data_files" / str(args.year) / f"carbon-intensity-gCO2eq-1H_germany-{args.year}.csv")


# ---------------------------------------------------------------- Netztransparenz
def ntp_token():
    cid, secret = os.environ.get("NTP_CLIENT_ID"), os.environ.get("NTP_CLIENT_SECRET")
    if not (cid and secret):
        sys.exit("Set NTP_CLIENT_ID and NTP_CLIENT_SECRET first (Netztransparenz API client).")
    r = requests.post(NTP_TOKEN_URL, timeout=60, data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret})
    if r.status_code != 200:
        sys.exit(f"Netztransparenz token request failed: HTTP {r.status_code}")
    return r.json()["access_token"]


def parse_ntp_csv(text, value_pattern):
    """Netztransparenz CSV (';'-separated, German decimals) -> UTC-indexed Series.

    Dates are dd.mm.yyyy for most series and yyyy-mm-dd for ID-AEP; the start-of-period
    column contains 'von'; the 'Zeitzone' column gives UTC/CET/CEST. Matching value
    columns are averaged (reBAP's identical 'unterdeckt'/'ueberdeckt' pair).
    """
    df = pd.read_csv(io.StringIO(text), sep=";", dtype=str).rename(columns=str.strip)
    if df.empty:
        return pd.Series(dtype=float)
    date_col = next(c for c in df.columns if c.lower().startswith("datum"))
    from_col = next(c for c in df.columns if c != date_col and "von" in c.lower())
    tz_col = next((c for c in df.columns if c.lower().startswith("zeitzone")), None)
    val_cols = [c for c in df.columns if value_pattern.lower() in c.lower()]
    if not val_cols:
        raise ValueError(f"No column matching '{value_pattern}' in {list(df.columns)}")

    date_str = df[date_col].str.strip()
    date_fmt = "%Y-%m-%d" if date_str.iloc[0].count("-") == 2 else "%d.%m.%Y"
    ts = pd.to_datetime(date_str + " " + df[from_col].str.strip(), format=f"{date_fmt} %H:%M")
    tz = df[tz_col].str.strip().str.upper() if tz_col else pd.Series("UTC", index=df.index)
    offset = tz.map({"UTC": 0, "CET": 1, "MEZ": 1, "CEST": 2, "MESZ": 2}).fillna(0)
    ts_utc = (ts - pd.to_timedelta(offset, unit="h")).dt.tz_localize("UTC")

    def num(c):
        c = c.str.strip()
        de = c.str.contains(",", na=False)
        c = c.where(~de, c.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
        return pd.to_numeric(c, errors="coerce")

    vals = df[val_cols].apply(num)
    return pd.Series(vals.mean(axis=1).values, index=ts_utc).sort_index()


def ntp_series(year, name, token):
    """One Netztransparenz series for one German local year, quarter-hours in UTC (month by month)."""
    path, pattern = NTP_SERIES[name]
    edges = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="MS", tz=TZ).tz_convert("UTC")
    parts = []
    for a, b in zip(edges[:-1], edges[1:]):
        r = requests.get(f"{NTP_API}/{path}/{a:%Y-%m-%dT%H:%M:%S}/{b:%Y-%m-%dT%H:%M:%S}",
                         headers={"Authorization": f"Bearer {token}"}, timeout=180)
        if r.status_code != 200:
            sys.exit(f"Netztransparenz {name} {a:%Y-%m}: HTTP {r.status_code}")
        parts.append(parse_ntp_csv(r.content.decode("utf-8-sig", errors="replace"), pattern))
    s = pd.concat(parts)
    s = s[(s.index >= edges[0]) & (s.index < edges[-1])]
    return s.groupby(level=0).mean()


def ntp(args):
    token = ntp_token()
    wanted = [("ID_AEP", "market-intraday-prices")] + ([("reBAP", "market-imbalances-prices")] if args.year == 2023 else [])
    for name, stem in wanted:
        s, gaps = local_hourly(ntp_series(args.year, name, token).replace(0, ZERO), args.year)
        if args.dst_placeholder:
            s.loc[[h for h in dst_hours(args.year) if h in s.index]] = ZERO
        print(f"{name} {args.year}: {gaps} hours interpolated")
        plexos_file(s, args.model / "data_files" / str(args.year) / f"{stem}_1H_germany-{args.year}.csv")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="what", required=True)
    for name in ["carbon", "ntp"]:
        p = sub.add_parser(name)
        p.add_argument("--year", type=int, required=True)
        p.add_argument("--model", type=Path, default=HERE.parent / "model" / "DRJ_MultiYear_v13")
    c = sub.choices["carbon"]
    src = c.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=Path, help="yearly hourly CSV of the Electricity Maps data portal")
    src.add_argument("--api", action="store_true", help="Electricity Maps API (ELECTRICITYMAPS_API_KEY)")
    c.add_argument("--utc-as-period", action="store_true", help="UTC hour as local period (the paper's 2025 file)")
    sub.choices["ntp"].add_argument("--dst-placeholder", action="store_true", help="1e-6 in the two DST hours (the paper's 2025 files)")
    args = ap.parse_args()
    {"carbon": carbon, "ntp": ntp}[args.what](args)


if __name__ == "__main__":
    main()
