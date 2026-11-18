# Reproducibility and review limits

## What is available here

- The study-specific dataframe accounting module `src/emissions_accounting.py`.
- A dependency file and a partial input schema.
- A separate executed-run archive candidate described in [Archive guide](ARCHIVE_GUIDE.md).
- The supplied manuscript, used to prepare [the paper artifact map](PAPER_ARTIFACT_MAP.md), is not included in this code candidate.

## What this candidate can support

A reviewer can read the accounting implementation, inspect its expected fields, and assess archived PLEXOS output files if they have the separate dataset. With caller-supplied, independently cleared input data, the accounting functions can be invoked as dataframe transformations.

## What this candidate cannot reproduce

- It does not contain or run the complete PLEXOS post-processing pipeline referenced by the archive README (`postprocessing/run_all.py`).
- It cannot regenerate all paper tables, KPIs, or figures from the archived runs on its own.
- It does not include the restricted Electricity Maps or Netztransparenz time series named in the archive README.
- It does not provide the paper's full model input preparation and figure-generation workflow.
- No results in this candidate establish numerical parity against the paper or validate the PLEXOS simulations.

## Existing verification scope

The accounting module was syntax-compiled during candidate preparation. That is a syntax check only. This candidate does not include numerical unit/regression tests or a clean-environment end-to-end run. Do not describe it as fully validated or fully reproducible.

## Data boundary

Do not add licensed time series, researcher-specific mobility profiles, personal or confidential data, or derived outputs unless their redistribution is explicitly cleared. A transformed or aggregated value is not automatically free of source-data restrictions.
