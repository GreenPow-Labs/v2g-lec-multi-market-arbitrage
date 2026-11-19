# Reproducing the study

## Materials in this repository

The repository now includes the full analysis source tree under [`reproduction/`](../reproduction/): source input files included in the project, input-preparation scripts, fitted EV-profile inputs and generator, the PLEXOS model and checks, post-processing and figure scripts, and the CSV/PDF results.

The separate [v13-results release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results) contains the 72 executed PLEXOS runs, logs, solution databases, and associated run files. Follow [`reproduction/README.md`](../reproduction/README.md) for download commands, checksums, dependencies, and workflow order.

## What can be rerun

- **Post-processing:** after downloading and unpacking the run archive and obtaining the restricted inputs listed below, run `reproduction/postprocessing/run_all.py` to regenerate KPI tables and figures under `reproduction/results/`.
- **Input preparation and EV profiles:** scripts and fitted EV-profile distributions are included. The source Straub trip records used to fit the distributions are not included, so that original fitting step cannot be independently repeated from this repository.
- **Model build and validation:** model-generation and check scripts are included. The execution checks operate on the archived runs.
- **PLEXOS simulations:** rebuilding and executing the model requires PLEXOS 11 and Gurobi. The executed runs in the release let readers inspect results without those tools.

The study README records expected check outputs and the clean-copy reproduction procedure reported by the maintainers. This repository snapshot has not been independently rerun as part of this documentation update.

## Restricted inputs

The repository and run archive omit Electricity Maps carbon-intensity data, Netztransparenz ID-AEP series for 2023–2025, and the 2023 Netztransparenz reBAP series. Users must obtain these directly under the providers' access and use terms. See [data inventory](ARCHIVE_DATA_INVENTORY.md) and `reproduction/preprocessing/fetch_restricted_inputs.py`.

## Interpretation

The archive documents executed runs; inspecting those files is not the same as rerunning PLEXOS. Recreating the full analysis also depends on access to the restricted inputs and the versions of software and data described in `reproduction/README.md`. Scenario C assumes the intraday price index is known in advance and represents an upper bound rather than a forecast-based operating result.
