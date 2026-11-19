# Data inventory: project files and simulation archive

This page inventories the input data in [`reproduction/`](../reproduction/) and the separate [v13-results release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results). The source project includes input-preparation scripts; the release contains a fixed snapshot of the executed PLEXOS runs and their inputs/outputs.

## Input datasets in the source project

| Data | Location | Coverage and notes |
|---|---|---|
| Day-ahead and imbalance prices; 50Hertz solar and wind generation | `reproduction/data/entsoe/` | ENTSO-E source exports for the years/files identified by name. Preprocessing produces model-ready hourly series. |
| Household and business standard load profiles | `reproduction/data/load_profiles/` | Stromnetz Berlin spreadsheets for 2023–2025. |
| EV profile fitting inputs and reference data | `reproduction/preprocessing/ev_dataset/inputs/` | Fitted cohort distributions and reference statistics. Original Straub trip-level source data are not included. |
| Generated EV model profiles | `reproduction/model/DRJ_MultiYear_v13/data_files/` | Hourly distance and charging-availability profiles for the modeled fleet, organized by year. |
| Restricted carbon intensity and selected market series | Not included | Obtain them directly from Electricity Maps and Netztransparenz under their access and use terms. |

## Included inputs in the v13 run archive

The release archive includes the model XML and run indexes, configuration files, scripts, logs, solution databases, and hourly/annual results for 72 runs. Input series in the archive include:

| Data | Archive filenames | Coverage / notes |
|---|---|---|
| EV driving distance and charging availability | `EV_ELVIS-Straub_distance_km.csv`, `EV_ELVIS-Straub_share_CS1.csv` | Files for 2023, 2024, and 2025; modeled cohort/vehicle-type profiles. |
| Solar and wind generation profiles | `solar-profile-{ac,da}_1H_germany-YYYY.csv`, `wind-profile-{ac,da}_1H_germany-YYYY.csv` | Actual (`ac`) and day-ahead (`da`) series for 2023–2025. |
| Household and general-business demand | `stromnetz_households_normalized_demand_1h_MW.csv`, `stromnetz_general_business_normalized_demand_1h_MW.csv` | One pair per year, 2023–2025. |
| Demand-noise series | `stromnetz-noise_households_normalized_demand_1h_MW.csv`, `stromnetz-noise_general_business_normalized_demand_1h_MW.csv` | One pair per year, 2023–2025. |
| Day-ahead market prices | `market-dayahead-prices_1H_germany-YYYY.csv`; `market-dayahead-prices-seq2_1H_germany-2025.csv` | Day-ahead prices for 2023–2025; second sequence present for 2025. |
| Imbalance prices | `market-imbalances-prices_1H_germany-2024.csv`, `market-imbalances-prices_1H_germany-2025.csv` | Present for 2024 and 2025. |

## Omitted inputs

The archive documentation identifies these restricted inputs as omitted:

- Electricity Maps carbon-intensity data for Germany.
- Netztransparenz ID-AEP intraday price index for 2023–2025.
- Netztransparenz reBAP imbalance price for 2023.

The source project includes `reproduction/preprocessing/fetch_restricted_inputs.py` to retrieve restricted inputs with the user's own access. The archive and source project do not include provider credentials or the restricted series.

## Rights and reuse

This inventory describes file presence; it does not grant reuse rights. No general license is granted for GreenPow Labs materials, and commercial reuse requires prior written permission from GreenPow Labs. Third-party data and software remain subject to their source terms; inclusion in this repository does not relicense those materials. Contact GreenPow Labs through [the company contact form](https://www.greenpow.io/en/contact) with rights questions.
