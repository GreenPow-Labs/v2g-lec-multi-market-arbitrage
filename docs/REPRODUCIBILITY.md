# Reproducing the paper: available materials and limits

## Materials available here

- `src/emissions_accounting.py`, a study-specific module that works with pandas DataFrames.
- A dependency list and a partial description of the module's input columns.
- The separate [v13 simulation archive](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results), containing the executed PLEXOS runs and their outputs.
- A [paper artifact map](PAPER_ARTIFACT_MAP.md) that points readers to runs relevant to reported tables and figures.

The manuscript itself and the complete collaboration repository are not included.

## What you can do

You can read the accounting code, inspect its expected columns, and review the archived model configurations, logs, and result files. You can also call the dataframe functions with inputs you are permitted to use.

## What you cannot reproduce from this release alone

- The complete PLEXOS post-processing workflow (`postprocessing/run_all.py`) is not included.
- The restricted Electricity Maps and Netztransparenz input series are not included.
- The model input preparation and figure-generation workflow is incomplete here.
- Therefore, this release cannot regenerate all reported KPIs, tables, and figures or independently confirm their numerical agreement with the paper.

The archive documents executed runs. Inspecting those files is not the same as rerunning the model or reproducing the paper's analysis.

## Verification completed

The accounting module was syntax-compiled during preparation. That only checks that Python can parse the file; it does not verify numerical results. This release has no included regression tests or full clean-environment reproduction run.

## Data boundaries

Do not add licensed time series, personal or confidential information, or derived results unless redistribution is cleared. Aggregating or transforming a dataset does not automatically remove its source restrictions.
