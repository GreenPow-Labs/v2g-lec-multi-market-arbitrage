# Made by Francesco Maldonato on 10/11/2026
"""Run every post-processing step on the executed PLEXOS runs, in order, and write all results into results/.

    python3 run_all.py                                  # runs/DRJ_MultiYear_v13_executed_logs (from Zenodo)
    python3 run_all.py --folder <runs folder>           # another path or name in runs/

1. plexos_kpi_extract.py --check   KPIs of every run, Tables 8 and 9, sensitivity data, settlement check
2. ev_fleet_analysis.py            results per EV, battery wear (Table 11, wear rows of Tables 8 and 9)
3. ev_user_types.py                results per EV user type (Section VI-F)
4. forecast_uncertainty.py         forecast errors, Monte Carlo, day-block bootstrap (Table 10)
5. market_robustness.py            price volatility and input correlations (Table 5, Section IV-F); uses step 2
6. computational_performance.py    solver statistics from the PLEXOS logs (Table 3)
7. ev_fees.py                      fees the EVs pay, value of the German network-charge rules (Sections V and VII)
8. lmp_capture.py                  the community's LMP against the market prices (Section VI-C)
9. paper_figures.py                Figs. 6-9; uses steps 1, 3 and 4
"""
import argparse
import subprocess
import sys
from pathlib import Path

from common import RESULTS, runs_folder

HERE = Path(__file__).resolve().parent
STEPS = [["plexos_kpi_extract.py", "--check"], ["ev_fleet_analysis.py"], ["ev_user_types.py"], ["forecast_uncertainty.py"],
         ["market_robustness.py"], ["computational_performance.py"], ["ev_fees.py"], ["lmp_capture.py"], ["paper_figures.py"]]
# inputs that may not be redistributed: preprocessing/fetch_restricted_inputs.py writes them (README.md, step 3)
RESTRICTED = [f"{y}/{name}-{y}.csv" for y in (2023, 2024, 2025)
              for name in ("carbon-intensity-gCO2eq-1H_germany", "market-intraday-prices_1H_germany")]
RESTRICTED += ["2023/market-imbalances-prices_1H_germany-2023.csv"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="DRJ_MultiYear_v13_executed_logs")
    ap.add_argument("--out", default=str(RESULTS))
    a = ap.parse_args()
    folder = runs_folder(a.folder)
    missing = [f for f in RESTRICTED if not (folder / "data_files" / f).exists()]
    if missing:
        sys.exit(f"{len(missing)} restricted input files missing in {folder / 'data_files'}: {', '.join(missing)}\n"
                 "Add them with preprocessing/fetch_restricted_inputs.py (README.md, step 3).")
    Path(a.out).mkdir(parents=True, exist_ok=True)
    for script, *args in STEPS:
        print(f"\n=== {script}", flush=True)
        r = subprocess.run([sys.executable, script, "--folder", str(folder), "--out", a.out, *args], cwd=HERE)
        if r.returncode:
            sys.exit(f"{script} failed (exit {r.returncode})")
    print(f"\nAll results are in {a.out}")


if __name__ == "__main__":
    main()
