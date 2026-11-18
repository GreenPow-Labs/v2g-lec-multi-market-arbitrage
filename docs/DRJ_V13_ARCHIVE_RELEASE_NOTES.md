# DRJ MultiYear v13 execution archive

The simulation results are intended for public release as a separate dataset so reviewers can inspect all 72 executed runs. The archive is prepared for Zenodo, rather than stored in this Git repository; it has not yet been deposited publicly. The exact archive filename, size, and checksum are listed in [`DRJ_V13_ARCHIVE_SHA256SUMS`](DRJ_V13_ARCHIVE_SHA256SUMS).

## Contents

The verified archive contains 72 executed PLEXOS run folders, the model XML, run/configuration indexes, model-build and validation scripts, interval and annual result CSVs, run logs, and a per-file manifest. The archive README identifies PLEXOS 11.000 R05 and Gurobi 12.0.0 as the run environment. The top-level ZIP is about 200 MB; its extracted contents are about 672 MB.

The archive README says restricted Electricity Maps and Netztransparenz input series are omitted. It also says machine and user names in run logs were replaced. Inspection confirmed the user field is `[removed]`; the machine name field is also `[removed]` in the sampled logs. The logs retain hardware specifications.

## Review and reproduction limits

The dataset is intended to make the executed simulation results and their run context available for review. The archive preserves the outputs and model files needed to inspect run configurations. It does not include the companion repository's `postprocessing/run_all.py` workflow or the restricted input series. Therefore, these archive files alone do not regenerate all paper KPIs, tables, or figures. Read [`PAPER_ARTIFACT_MAP.md`](PAPER_ARTIFACT_MAP.md) and [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) for the limitations of this minimal code release.

The archive contains aggregate scenario-level EV charge, discharge, and energy series, not individual researcher profiles. Its XML and run index include input/model labels and configurations. Redistribution rights for all embedded third-party or collaboration materials must be confirmed before public dataset deposit. The dataset's permitted reuse terms also need rights-holder approval; this note does not grant a license.

## Integrity check

Verify the archive before use:

```bash
sha256sum --check docs/DRJ_V13_ARCHIVE_SHA256SUMS
unzip -t DRJ_MultiYear_v13_executed_logs.zip
```

After the dataset is deposited, update this document and the README with its public DOI and download instructions. The repository README links to this dataset plan; the actual archive remains a separate download.
