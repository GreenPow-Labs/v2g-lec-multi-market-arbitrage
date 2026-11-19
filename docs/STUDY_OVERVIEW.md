# Study overview

## What the study asks

How can a local energy community use electric vehicles to respond to electricity prices while meeting its mobility needs and settling deviations from its market schedule?

The study models a Berlin-area community as a balance group. The system includes households and businesses, photovoltaic and wind generation, a stationary battery, and 100 electric vehicles belonging to residents and employees. The EV availability patterns are generated with the ELVIS simulator from simulated Berlin travel data. The fitted EV-profile distributions and generated hourly model profiles are included under `reproduction/`; the original trip-level Straub dataset used to fit the distributions is not included. See the [data inventory](ARCHIVE_DATA_INVENTORY.md).

## Strategies compared

The model studies three strategies for 2023–2025. Each is optimized using forecast data and then settled using actual load and renewable generation, so the analysis includes imbalance costs from forecast errors.

| Scenario | Charging and trading strategy |
|---|---|
| A | Unidirectional smart charging (V1G) in the day-ahead market |
| B | Bidirectional charging (V2G) in the day-ahead market |
| C | V2G in the day-ahead market, with additional intraday trading |

Scenario C assumes the intraday price index is known in advance. The manuscript treats it as an upper bound on the value of intraday trading, rather than a forecast-based operating result.

## Findings reported in the current manuscript

In its reported base case, the manuscript says day-ahead V2G reduces community energy costs by 22% relative to V1G. Adding intraday trading increases the modeled reduction to 93%; the reported average annual gain is €419 per EV relative to V1G. The results also show that the value depends on short-term price volatility, how long vehicles are connected, market-year conditions, and the community's grid connection. The manuscript includes carbon attribution and battery-cycling analyses as well.

These figures are reported in the current manuscript. The analysis scripts and output tables/figures are now included under `reproduction/`; regenerating them requires the executed-run archive and access to the restricted inputs described in [Reproducibility](REPRODUCIBILITY.md).

## Research areas and search terms

This work connects:

- vehicle-to-grid (V2G) and smart charging;
- demand response and distributed energy resources;
- local energy communities and balance-group settlement;
- day-ahead and intraday electricity markets;
- power-system simulation and sequential market optimization;
- battery operation and energy storage;
- carbon accounting and emissions attribution.

The paper focuses on coordinating **distributed energy resources** in an energy system. That is different from distributed-computing infrastructure, so the repository uses the energy-systems terminology in its description and metadata.

## Paper and GreenPow Labs

The current manuscript is titled “Multi-Pricing Arbitrage Potential for V2G Demand Response Services in Local Energy Communities” and lists Federico Ruilova's affiliation as GreenPow Labs. The public repository is hosted by GreenPow Labs. Confirm the final author list, publication details, and DOI against the published article before citing it. The placeholder DOI printed in the current manuscript is not used as a citation.

This repository contains the carbon-accounting module and the full post-processing, EV-profile, input-preparation, and model-building source tree. The separate release contains 72 executed PLEXOS runs and their input and output files. Some restricted inputs must be obtained separately, and running PLEXOS requires a valid license.
