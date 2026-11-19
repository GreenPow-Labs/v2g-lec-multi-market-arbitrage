# DRJ MultiYear v13 simulation archive

The archive contains the outputs from all 72 executed PLEXOS runs. Download `DRJ_MultiYear_v13_executed_logs.zip` from the [v13-results GitHub Release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results). The archive is attached to the release so the large file does not live in Git history. The source code and analysis workflow are included in the repository under `reproduction/`; the run archive remains a separate GitHub release asset.

## What is included

The archive contains the PLEXOS model XML, run indexes and configuration tables, model-build and validation scripts, run logs, hourly and annual result CSVs, solution database ZIPs, and a manifest with file sizes and SHA-256 hashes. It covers 72 runs across the 2023–2025 baseline scenarios and the 2025 sensitivity cases. The run README identifies PLEXOS 11.000 R05 and Gurobi 12.0.0 as the execution environment.

The compressed archive is 199,572,373 bytes; its extracted contents are about 672 MB. Its SHA-256 is recorded in [`DRJ_V13_ARCHIVE_SHA256SUMS`](DRJ_V13_ARCHIVE_SHA256SUMS).

## Inputs and identifying details

The archive includes EV distance and charging-availability profiles for four modeled EVs, along with demand, renewable-generation, and market-price series. The EV files use vehicle-model labels rather than researcher names. The archive also contains scenario-level EV charging, discharging, and energy results. See the [data inventory](ARCHIVE_DATA_INVENTORY.md) for filenames and coverage.

The archive README identifies omitted restricted inputs: Electricity Maps carbon-intensity data, Netztransparenz ID-AEP data, and 2023 reBAP data. Computer and user names appear as `[removed]` in the run logs; hardware specifications remain. Included third-party datasets may still carry reuse restrictions.

## What the archive lets you check

The archive provides the executed run outputs, logs, model configurations, and run-check scripts. The source repository now includes `reproduction/postprocessing/run_all.py` and the paper-analysis scripts. Regenerating the full analysis still requires the restricted input series described in the [data inventory](ARCHIVE_DATA_INVENTORY.md). See the [archive guide](ARCHIVE_GUIDE.md), [paper artifact map](PAPER_ARTIFACT_MAP.md), and [reproducibility notes](REPRODUCIBILITY.md).

## Verify the download

From the directory containing the downloaded ZIP, point `sha256sum` to the checksum file in your repository checkout (Linux):

```bash
sha256sum --check /path/to/v2g-lec-multi-market-arbitrage/docs/DRJ_V13_ARCHIVE_SHA256SUMS
unzip -t DRJ_MultiYear_v13_executed_logs.zip
```

On macOS, run `shasum -a 256 DRJ_MultiYear_v13_executed_logs.zip` and compare the printed digest with the value in `docs/DRJ_V13_ARCHIVE_SHA256SUMS`.

The checksum file is also in this repository at [`docs/DRJ_V13_ARCHIVE_SHA256SUMS`](DRJ_V13_ARCHIVE_SHA256SUMS). After extracting the archive, use its `MANIFEST.csv` to check individual files.

## Reuse

No standard licence is granted for this archive. Prior written permission from GreenPow Labs GmbH is required before reusing GreenPow Labs materials, including for noncommercial purposes. Third-party materials remain subject to their own terms. See the repository's [Rights and permissions](../RIGHTS.md) notice or contact GreenPow Labs through [greenpow.io](https://www.greenpow.io/en/contact).
