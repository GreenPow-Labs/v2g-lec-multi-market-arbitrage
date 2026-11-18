# Data included in the v13 simulation archive

The [v13-results release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results) contains both simulation outputs and input series used by the model. This inventory is based on filenames in the archive and the supplied `README_runs.md`.

## Included input series

| Data | Archive files | Coverage / notes |
|---|---|---|
| EV driving distance and charging availability | `EV_ELVIS-Straub_distance_km.csv`, `EV_ELVIS-Straub_share_CS1.csv` | One file of each type for 2023, 2024, and 2025. The hourly columns describe four modeled EVs and are labeled with vehicle models. These are per-vehicle model profiles labelled by vehicle type; the headers do not identify researchers. |
| Solar and wind generation profiles | `solar-profile-{ac,da}_1H_germany-YYYY.csv`, `wind-profile-{ac,da}_1H_germany-YYYY.csv` | Actual (`ac`) and day-ahead (`da`) series for 2023–2025. |
| Household and general-business demand | `stromnetz_households_normalized_demand_1h_MW.csv`, `stromnetz_general_business_normalized_demand_1h_MW.csv` | One pair per year, 2023–2025. |
| Demand-noise series | `stromnetz-noise_households_normalized_demand_1h_MW.csv`, `stromnetz-noise_general_business_normalized_demand_1h_MW.csv` | One pair per year, 2023–2025. |
| Day-ahead market prices | `market-dayahead-prices_1H_germany-YYYY.csv`; `market-dayahead-prices-seq2_1H_germany-2025.csv` | Day-ahead prices for 2023–2025; the second sequence is present for 2025. |
| Imbalance prices | `market-imbalances-prices_1H_germany-2024.csv`, `market-imbalances-prices_1H_germany-2025.csv` | Present for 2024 and 2025. |

The archive also includes the model XML, model/run indexes, scripts, logs, and all 72 runs' hourly and annual PLEXOS result files. See the [archive guide](ARCHIVE_GUIDE.md) for navigating those outputs.

## Inputs the archive says are omitted

The archive README identifies these restricted inputs as omitted:

- Electricity Maps carbon-intensity data.
- Netztransparenz ID-AEP data for all years.
- Netztransparenz reBAP data for 2023.

The filenames above show imbalance-price series for 2024 and 2025 in the archive; do not assume that every market-price series has the same source terms or redistribution rights. Check the source terms for each dataset.

## Reuse and data rights

This inventory describes what is present; it does not grant permission to reuse it. The repository provides no data license. Contact GreenPow Labs GmbH before reusing or redistributing the dataset; commercial use requires prior written permission. Third-party data remain subject to their source terms. Contact GreenPow Labs through [greenpow.io](https://www.greenpow.io/en/contact) with rights questions.
