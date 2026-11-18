# V2G multi-market analysis: code and simulation results

This repository shares a small carbon-accounting module and the executed results from 72 PLEXOS runs. It gives readers access to the archived simulation outputs and lets them inspect the accounting code. It does **not** contain the complete workflow used to produce every result in the paper.

## Download the simulation results

The 72-run archive is available from the [v13-results release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results). Download `DRJ_MultiYear_v13_executed_logs.zip` there. It is about 200 MB compressed and is attached to the release rather than stored in the Git repository. Along with the run results, the archive includes model inputs such as EV profiles, demand, renewable-generation, and market-price series. It omits the restricted Electricity Maps and Netztransparenz series listed in the [data inventory](docs/ARCHIVE_DATA_INVENTORY.md).

See the [data inventory](docs/ARCHIVE_DATA_INVENTORY.md) for included and omitted datasets, the [archive guide](docs/ARCHIVE_GUIDE.md) for help navigating the results, the [paper artifact map](docs/PAPER_ARTIFACT_MAP.md) for links between reported figures/tables and relevant runs, and the [archive release notes](docs/DRJ_V13_ARCHIVE_RELEASE_NOTES.md) for integrity and scope details. There is no separate Zenodo record or DOI yet.

## What is in this repository

- [`src/emissions_accounting.py`](src/emissions_accounting.py): dataframe functions for emissions accounting and related summaries.
- [`requirements.txt`](requirements.txt): Python dependencies.
- [`docs/INPUT_SCHEMA.md`](docs/INPUT_SCHEMA.md): input columns used by the accounting functions.
- [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md): what can be reviewed or rerun from the available materials.

This is a partial release. The companion post-processing workflow, including `postprocessing/run_all.py`, is not included. As a result, the archive and code here do not reproduce all paper KPIs, tables, or figures. The archive lets you inspect the executed simulation outputs, but the paper results have not been regenerated from the files in this release.

## Use the accounting module

Python 3.10 or newer is recommended:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

The functions accept pandas DataFrames. They do not download project or third-party data. Provide only inputs you are entitled to use and share. See [`docs/INPUT_SCHEMA.md`](docs/INPUT_SCHEMA.md) and check the function definitions for each function's exact fields and units.

## Rights and permissions

No license is granted by this repository. All rights are reserved. Contact GreenPow Labs GmbH before reusing or redistributing the code or dataset. Commercial use requires prior written permission. For permission requests, email [fr@network.berlin](mailto:fr@network.berlin). Third-party materials remain subject to their own terms.
