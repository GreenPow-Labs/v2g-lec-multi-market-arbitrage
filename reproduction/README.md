# Multi-pricing V2G arbitrage in a local energy community

This directory contains the model, included input data, preprocessing, EV-profile generation, post-processing, and result files associated with *"Multi-Pricing Arbitrage Potential for V2G Demand Response Services in Local Energy Communities"* by F. Maldonato, F. Ruilova, M. Noori, M. Azizkhani and D. Göhlich. It is part of the public GreenPow Labs repository. Check the paper's final version for its current publication status and citation details.

Use the [reproduction steps](#reproduce-the-papers-results) to regenerate the supplied analysis outputs from the executed PLEXOS runs. The [full pipeline](#full-pipeline) describes how to prepare inputs, generate the EV dataset, rebuild the PLEXOS model, and run the simulations. Some market and carbon-intensity inputs must be obtained separately from their providers; rerunning PLEXOS requires a valid PLEXOS/Gurobi environment.

## The study in brief

A residential local energy community (LEC), operated as a balance group, is simulated in PLEXOS:

- **Assets:** 100 households, 10 businesses, 0.5 MW PV, 0.2 MW wind, a 0.4 MWh / 0.4 MW battery and 100 EVs (VW ID.4 /
  ID.5, 82 kWh, 11 kW charging, 10 kW V2G, 87 % round trip): 65 residents' EVs and 35 employees' EVs.
- **Scenarios**, each for the market years 2023, 2024 and 2025:
  - **A:** smart charging (V1G) on the day-ahead market;
  - **B:** V2G on the day-ahead market;
  - **C:** V2G on the day-ahead market plus intraday trading at the German TSOs' intraday price index ID-AEP.
- **Two stages per scenario:**
  - **X.1, optimization:** the schedule is optimized with forecast data;
  - **X.2, settlement:** the X.1 schedule is replayed with the actual RES generation and load; every deviation is settled
    at the German imbalance price (reBAP). The X.1 schedule is pinned with exact "=" constraints (no slack, no penalty).
- **Sensitivity analysis (2025):** one factor at a time: EV fleet (50 to 400 EVs), RES penetration (40 %, 60 %, 100 % and
  120 %, against an 80 % base case; equivalent to 0.5×, 0.75×, 1.25× and 1.5× its PV/wind capacity), consumer load
  scaled together with RES (50 % to 200 % of the base load), and the resident share of the EV fleet (0 % to 100 %).

In total, 72 PLEXOS runs: 18 for the three years and 54 for the sensitivity analysis.

## Repository layout

```
v2g-lec-multipricing/
├── README.md                       this file
├── CITATION.cff                    how to cite
├── requirements.txt                Python packages for preprocessing and postprocessing
├── requirements-ev.txt             extra packages for the EV dataset (ELVIS)
├── data/
│   ├── entsoe/                     raw ENTSO-E exports: day-ahead and imbalance prices, 50Hertz solar and wind
│   └── load_profiles/              Stromnetz Berlin standard load profiles (households, business), 2023-2025
├── preprocessing/
│   ├── prepare_inputs.py           raw data -> model input files (prices, RES profiles, consumer load)
│   ├── fetch_restricted_inputs.py  downloads the inputs that may not be redistributed (needs your own access)
│   └── ev_dataset/
│       ├── make_ev_dataset.py      EV charging sessions and trips (ELVIS) -> model input files
│       ├── analyse_ev_dataset.py   statistics, validation and figures of the EV dataset
│       └── inputs/                 the fitted probability densities used in the study, and reference data
├── model/DRJ_MultiYear_v13/
│   ├── DRJ_MultiYear_v13.xml       the PLEXOS model (72 models in one folder)
│   ├── data_files/2023, 2024, 2025 hourly input time series
│   ├── model_overview.csv          parameters of every model; run_order.csv: the order in which PLEXOS runs them
│   ├── source/base_model_2025.xml  the base model the build script starts from
│   └── scripts/                    build the model, check it before and after the runs
├── postprocessing/
│   ├── run_all.py                  runs every step below, in order
│   └── ...                         one script per analysis (see "Where each result of the paper is")
├── results/                        all outputs: KPI tables (CSV) and figures (PDF)
└── runs/                           unpack the executed run archive here (generated locally; not in Git)
```

## Reproduce the paper's results

Requirements: Python 3.11 or newer (tested with 3.13) and about 1 GB of free disk space. Start every step from the
repository folder. The commands are for a bash shell (macOS, Linux; on Windows, Git Bash with
`source .venv/Scripts/activate`).

**Step 1. Get the code and install the Python packages.**

```bash
git clone https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage.git
cd v2g-lec-multi-market-arbitrage/reproduction
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Step 2. Download the executed PLEXOS runs from GitHub and unpack them into `runs/`.**

The `v13-results` release contains `DRJ_MultiYear_v13_executed_logs.zip` (about 200 MB compressed; about 0.7 GB unpacked): 72 executed runs, model inputs and configurations, PLEXOS logs, solution databases, and run-check scripts. The archive is attached to the [GitHub release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results), not stored in Git history.

```bash
mkdir -p runs
curl -L -o runs/DRJ_MultiYear_v13_executed_logs.zip \
  "https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/download/v13-results/DRJ_MultiYear_v13_executed_logs.zip"
sha256sum runs/DRJ_MultiYear_v13_executed_logs.zip  # Linux
shasum -a 256 runs/DRJ_MultiYear_v13_executed_logs.zip  # macOS
# expected: 495575ab480ace683792cb504d4c82277bdfe4b0189947f1bd4646b4d8f71b93
unzip -q runs/DRJ_MultiYear_v13_executed_logs.zip -d runs
rm runs/DRJ_MultiYear_v13_executed_logs.zip               # optional
ls runs/DRJ_MultiYear_v13_executed_logs                   # model, data_files/ and one folder per run
```

**Step 3. Add the three restricted input series.**

Some input series are not redistributed here because their provider terms restrict redistribution. They are absent from this repository and the GitHub run archive. `fetch_restricted_inputs.py` downloads them with your own access and writes them into the runs folder:

- Netztransparenz: the intraday price index ID-AEP (2023-2025) and the imbalance price reBAP of 2023. Register for free
  at netztransparenz.de and create an API client (client ID and secret).
- Electricity Maps: the hourly carbon intensity of Germany (2023-2025). Download the yearly hourly CSV files of Germany
  from the Electricity Maps data portal (academic access), or use an API key with `--api` instead of `--csv`.

Keys are read from environment variables only; they are never printed or stored. The options `--dst-placeholder` and
`--utc-as-period` reproduce two conventions of the 2025 files used in the paper.

```bash
cd preprocessing
RUNS=../runs/DRJ_MultiYear_v13_executed_logs
export NTP_CLIENT_ID="<your client ID>"
export NTP_CLIENT_SECRET="<your client secret>"
python3 fetch_restricted_inputs.py ntp --year 2023 --model $RUNS
python3 fetch_restricted_inputs.py ntp --year 2024 --model $RUNS
python3 fetch_restricted_inputs.py ntp --year 2025 --dst-placeholder --model $RUNS
python3 fetch_restricted_inputs.py carbon --year 2023 --csv <path>/DE_2023_hourly.csv --model $RUNS
python3 fetch_restricted_inputs.py carbon --year 2024 --csv <path>/DE_2024_hourly.csv --model $RUNS
python3 fetch_restricted_inputs.py carbon --year 2025 --csv <path>/DE_2025_hourly.csv --utc-as-period --model $RUNS
cd ..
```

**Step 4. Run the post-processing.** It takes about a minute and writes every output into `results/`.

```bash
cd postprocessing
python3 run_all.py
cd ..
```

The first step prints a settlement check; every checked schedule is compared with its ex-post value:
`SETTLEMENT CHECK: 31 check rows, max |imbalance - expected| 0.00989 kW, max |revenue - ex post| 0.0018 EUR`.
The generated tables and figures are written under `results/`. The repository includes a reference set there; compare regenerated files with that set when checking a new environment. This repository snapshot was not independently rerun as part of the documentation review.

The settlement-check count refers to output rows, including four baseline reference cases repeated in the sensitivity summaries. It is not the number of distinct PLEXOS run folders: the archive contains 72 runs in total, of which 27 are distinct settlement runs.

**Step 5 (optional). Check the PLEXOS runs themselves.**

```bash
cd model/DRJ_MultiYear_v13/scripts
python3 check_after_run.py --folder ../../../runs/DRJ_MultiYear_v13_executed_logs     # expected: 72 ok
python3 check_consistency.py --folder ../../../runs/DRJ_MultiYear_v13_executed_logs   # expected: 72 of 72 consistent
cd ../../..
```

- `check_after_run.py`: every log is clean, and every settlement run reproduces the schedule of its optimization run.
- `check_consistency.py`: replays every run hour by hour (energy balance, storage dynamics, ratings, market cash flows).

## Where each result of the paper is

All files are in `results/`. Scripts are in `postprocessing/` unless stated otherwise.

| Paper | File | Script |
|---|---|---|
| Table 3, computational performance | `computational_performance_summary.csv` (per run: `computational_performance.csv`) | `computational_performance.py` |
| Table 5, price volatility; correlations (Section IV-F) | `market_volatility.csv`, `input_correlations.csv`, `input_correlations_key.csv` | `market_robustness.py` |
| Table 6, Figs. 3-5, EV dataset | `ev_dataset_statistics.csv`, `ev_dataset_validation.csv`, `ev_dataset_inputs.pdf`, `ev_dataset_validation.pdf`, `ev_dataset_weekly.pdf` | `preprocessing/ev_dataset/analyse_ev_dataset.py` |
| Table 8, KPIs by year | `table8_kpis_by_year.csv` (every KPI of every run: `KPI_multiyear.csv`) | `plexos_kpi_extract.py` |
| Table 9, three-year mean | `table9_three_year_mean.csv` | `plexos_kpi_extract.py` |
| Table 10, forecast errors; Monte Carlo and bootstrap (Section VI-D) | `forecast_error_metrics.csv`, `forecast_mc_summary.csv`, `forecast_bootstrap_summary.csv` | `forecast_uncertainty.py` |
| Table 11, battery wear and break-even wear cost (Eqs. 5 and 7) | `battery_degradation.csv`, `battery_wear_by_year.csv`, `dod_share.csv` | `ev_fleet_analysis.py` |
| Fig. 6, community energy cost by year | `cost_by_year.pdf` | `paper_figures.py` |
| Fig. 7 and Section VI-H, sensitivity analysis | `sweeps.pdf`, `KPI_sweeps.csv` | `paper_figures.py`, `plexos_kpi_extract.py` |
| Fig. 8 and Section VI-E, price volatility and results | `market_spreads.pdf`, `volatility_vs_results.csv` | `paper_figures.py`, `market_robustness.py` |
| Fig. 9 and Section VI-F, EV user types | `user_types_gain.pdf`, `ev_user_types.csv` and `ev_user_types_*.csv` | `paper_figures.py`, `ev_user_types.py` |
| Section VI-C, the community's nodal price (LMP) | `lmp_capture.csv` | `lmp_capture.py` |
| Sections V and VII, fees and German network-charge rules | `ev_fees.csv` | `ev_fees.py` |
| Results per EV | `ev_per_vehicle.csv`, `ev_distribution.csv` | `ev_fleet_analysis.py` |
| Settlement check of every X.2 run | `settlement_check.csv` | `plexos_kpi_extract.py --check` |

Figs. 1 and 2 (scenarios and PLEXOS model diagram) are drawings, not data outputs.

The KPIs follow the definitions of Section III-F of the paper: net market profit, wheeling cost, community energy cost
(Eq. 3), nodal price (LMP), charging-station use-of-system fee, net charging cost (Eq. 4), equivalent full cycles per EV,
battery wear cost (Eq. 5), grid energies and attributed CO2eq (Eqs. 1, 2 and 6, `carbon_accounting.py`).

## Full pipeline

This is the order in which the study was made. Steps 1 to 4 run without PLEXOS; step 5 needs PLEXOS 11 with Gurobi (the
runs used PLEXOS 11.000 R05 and Gurobi 12.0.0). Each step writes into the repository, so the later steps use its output.

**1. Market, RES and load inputs** from the raw data in `data/` into `model/DRJ_MultiYear_v13/data_files/`:

```bash
cd preprocessing
python3 prepare_inputs.py               # 2023 and 2024 inputs, and the actual load of 2023-2025
python3 prepare_inputs.py --check-2025  # optional: compares a rebuild of 2025 with the shipped 2025 files
```

The 2025 files are the originals used in the study. A rebuild differs from them only in a few hours around the two
daylight-saving switches, so the shipped files are retained as the reference inputs.

**2. Restricted inputs** into the model folder: as in step 3 above, without `--model` (the default is
`model/DRJ_MultiYear_v13`).

**3. EV dataset** (ELVIS, fitted to Straub's simulation of Berlin's private car traffic):

```bash
pip install -r ../requirements-ev.txt
cd ev_dataset
python3 make_ev_dataset.py generate    # sessions and trips of 400 synthetic EVs per cohort (into pool/)
python3 make_ev_dataset.py model       # PLEXOS EV input files of 2023-2025 (into model/DRJ_MultiYear_v13/data_files/)
python3 analyse_ev_dataset.py          # Table 6, Figs. 3-5 (into results/)
cd ../..
```

The probability densities of arrival time and parking duration used in the study are in `ev_dataset/inputs/`
(`RC.yaml`, `RO.yaml`, `WF.yaml`, `WP.yaml`, one per cohort: residents' commuter cars, residents' other cars,
employees' full-day stays, employees' part-day stays). They were fitted to Straub's simulated trips with
`make_ev_dataset.py extract --straub <fahrdaten.ftr>`. Those trips are not public, so this first step cannot be
repeated; `generate` and `model` start from the shipped densities and reproduce the study's EV files exactly.

**4. Build and check the PLEXOS model:**

```bash
cd model/DRJ_MultiYear_v13/scripts
python3 make_multiyear_model.py    # writes ../DRJ_MultiYear_v13.xml from source/base_model_2025.xml
python3 check_model.py             # expected: 0 errors, 0 warnings; writes model_overview.csv and run_order.csv
```

**5. Run the simulations in PLEXOS:** open `model/DRJ_MultiYear_v13/DRJ_MultiYear_v13.xml` and run the folder
"All models (run in name order)" in one go, one model at a time (about 30 minutes on 2 cores in the documented
environment). Follow `model/DRJ_MultiYear_v13/run_order.csv`; it records the required order and dependencies.

**6. Check the runs and run the post-processing:**

```bash
cd model/DRJ_MultiYear_v13/scripts
python3 check_after_run.py
python3 check_consistency.py
cd ../../../postprocessing
python3 run_all.py --folder ../model/DRJ_MultiYear_v13
```

## Data sources

| Data | Source | In this repository |
|---|---|---|
| Day-ahead prices (DE-LU), imbalance prices 2024-2025, solar and wind generation, forecast and actual (50Hertz control area) | ENTSO-E Transparency Platform | yes, `data/entsoe/` |
| Standard load profiles, households and business | Stromnetz Berlin | yes, `data/load_profiles/` |
| Intraday price index ID-AEP (2023-2025), imbalance price reBAP (2023) | Netztransparenz (German TSOs) | no, fetched in step 3 |
| Hourly grid carbon intensity of Germany | Electricity Maps | no, fetched in step 3 |
| EV mobility | ELVIS (DAI-Labor, TU Berlin), fitted to Straub's simulated Berlin trips (dissertation, TU Berlin 2023, doi:10.14279/depositonce-17741); weekend factors from MiD 2017 via emobpy | fitted densities only, `preprocessing/ev_dataset/inputs/` |

## Citation and reuse

For repository citation metadata, see [`CITATION.cff`](CITATION.cff). Cite the paper for the scientific findings using its final bibliographic details once publication information is available.

No general reuse license is granted for this repository. Commercial reuse of GreenPow Labs materials requires prior written permission from GreenPow Labs. Third-party data and software remain subject to their own terms; the presence of a file here does not override those terms. Contact GreenPow Labs through [the company contact form](https://www.greenpow.io/en/contact) for rights questions.
