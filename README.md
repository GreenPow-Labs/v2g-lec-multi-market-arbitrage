# Vehicle-to-Grid Optimization and Multi-Market Energy Arbitrage

### GreenPow Labs research | Berlin, Germany

How can a local energy community coordinate renewable generation, stationary storage, and electric vehicles across electricity markets? This repository contains the study source code, input-preparation and EV-profile workflows, PLEXOS model files, post-processing scripts, and analysis outputs for a Berlin-area V2G demand-response study. The 72 executed PLEXOS runs are a separate downloadable asset in the [v13-results GitHub Release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results).

The study compares smart charging and bidirectional EV charging in day-ahead and intraday markets, with settlement against actual conditions. In the manuscript's modeled base case, day-ahead V2G reduces community energy cost by 22%; adding intraday trading gives a 93% modeled reduction and an average €419 annual gain per EV relative to V1G. These are simulation results for German market data from 2023–2025, not guaranteed real-world savings. Scenario C assumes advance knowledge of the intraday price index, so it represents an upper-bound case rather than a forecast-based operating result. See the [study overview](docs/STUDY_OVERVIEW.md) for assumptions and findings.

## What is included

| Location | Contents |
|---|---|
| [`src/`](src/) | DataFrame utilities for emissions accounting. |
| [`reproduction/data/`](reproduction/data/) | Source market, renewable-generation, and standard-load-profile datasets; review the provider terms before reuse. |
| [`reproduction/preprocessing/`](reproduction/preprocessing/) | Input preparation, restricted-input retrieval helpers, and EV-profile generation and analysis. |
| [`reproduction/model/DRJ_MultiYear_v13/`](reproduction/model/DRJ_MultiYear_v13/) | PLEXOS model, 2023–2025 model inputs, model-building tools, and run checks. |
| [`reproduction/postprocessing/`](reproduction/postprocessing/) | KPI extraction, analysis, and figure-generation scripts. |
| [`reproduction/results/`](reproduction/results/) | CSV analysis tables and PDF figures generated for the manuscript. |
| [v13-results release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results) | `DRJ_MultiYear_v13_executed_logs.zip`: the 72 executed runs, run outputs, solution databases, logs, and run-check materials. SHA-256: `495575ab480ace683792cb504d4c82277bdfe4b0189947f1bd4646b4d8f71b93`. |

Start with the [`reproduction README`](reproduction/README.md) for the directory map, requirements, and step-by-step instructions. The [reproducibility guide](docs/REPRODUCIBILITY.md) explains what can and cannot be reproduced; the [archive guide](docs/ARCHIVE_GUIDE.md) describes the 72-run release.

## Reproducing the analysis

The post-processing scripts use the archived PLEXOS runs and write analysis tables and figures under `reproduction/results/`. Some restricted inputs must first be obtained from their providers; see the [data inventory](docs/ARCHIVE_DATA_INVENTORY.md) and the detailed reproduction steps. Rebuilding the model and running PLEXOS require PLEXOS 11 and Gurobi. The source trip records used to fit the EV mobility distributions are not included; the fitted distributions and generated simulation profiles are provided.

The [paper artifact map](docs/PAPER_ARTIFACT_MAP.md) links manuscript tables and figures to output files and scripts. The archive is a record of executed simulations; it is distinct from rerunning the model or regenerating the analysis.

## Research and collaboration

At GreenPow Labs, this work contributes to research on energy-aware optimization across energy systems and distributed infrastructure. The study examines flexible demand, storage, electricity-market operation, and carbon accounting. It does not evaluate computing workloads or establish computing-performance results. For collaboration inquiries, visit the [GreenPow contact page](https://www.greenpow.io/en/contact).

## Citation

Repository citation metadata are in [`CITATION.cff`](CITATION.cff). The paper is the source to cite for the scientific findings; update its bibliography details when the final publication citation is available.

## Rights and permissions

No general license is granted for this repository. All rights are reserved for GreenPow Labs materials; commercial reuse requires prior written permission from GreenPow Labs. Third-party software and datasets remain subject to their own terms, and this repository does not grant rights to those materials. See the [data inventory](docs/ARCHIVE_DATA_INVENTORY.md) before reusing any input data.
