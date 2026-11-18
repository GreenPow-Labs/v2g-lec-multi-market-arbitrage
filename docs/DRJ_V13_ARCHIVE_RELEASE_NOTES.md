# DRJ MultiYear v13 simulation archive

The archive contains the outputs from all 72 executed PLEXOS runs. Download `DRJ_MultiYear_v13_executed_logs.zip` from the [v13-results GitHub Release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results). The archive is attached to the release so the large file does not live in Git history. A separate Zenodo deposit and DOI are not available yet.

## What is included

The archive contains the PLEXOS model XML, run indexes and configuration tables, model-build and validation scripts, run logs, hourly and annual result CSVs, solution database ZIPs, and a manifest with file sizes and SHA-256 hashes. It covers 72 runs across the 2023–2025 baseline scenarios and the 2025 sensitivity cases. The run README identifies PLEXOS 11.000 R05 and Gurobi 12.0.0 as the execution environment.

The compressed archive is 199,572,373 bytes; its extracted contents are about 672 MB. Its SHA-256 is recorded in [`DRJ_V13_ARCHIVE_SHA256SUMS`](DRJ_V13_ARCHIVE_SHA256SUMS).

## Inputs and identifying details

The archive omits the restricted Electricity Maps and Netztransparenz series. The run logs show `[removed]` for computer and user names; hardware specifications remain in the logs. The outputs contain scenario-level EV charging, discharging, and energy series, rather than individual researcher mobility profiles. Model labels and configuration details are included.

## What the archive lets you check

You can inspect the executed run outputs, logs, and model configurations. The archive does not include the companion repository's `postprocessing/run_all.py` workflow or the restricted input series, so it cannot regenerate all paper KPIs, tables, and figures by itself. See the [archive guide](ARCHIVE_GUIDE.md), [paper artifact map](PAPER_ARTIFACT_MAP.md), and [reproducibility notes](REPRODUCIBILITY.md) for more detail.

## Verify the download

From the directory containing the downloaded ZIP, run:

```bash
sha256sum --check /path/to/DRJ_V13_ARCHIVE_SHA256SUMS
unzip -t DRJ_MultiYear_v13_executed_logs.zip
```

The checksum file is also in this repository at [`docs/DRJ_V13_ARCHIVE_SHA256SUMS`](DRJ_V13_ARCHIVE_SHA256SUMS). After extracting the archive, use its `MANIFEST.csv` to check individual files.

## Reuse

This release grants no license to reuse the archive. Contact GreenPow Labs GmbH before reusing or redistributing it; commercial use requires prior written permission. Email [fr@network.berlin](mailto:fr@network.berlin). Third-party materials remain subject to their own terms. This note does not grant rights beyond those terms.
