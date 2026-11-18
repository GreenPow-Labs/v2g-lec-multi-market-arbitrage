# Research carbon-accounting code (release candidate)

This is a code-only review candidate extracted from a private research repository. It contains no project datasets, third-party carbon-intensity values, simulation profiles, workbooks, notebooks, figures, generated results, or prior Git history. It includes only the carbon-accounting module; it is not the full `v2g-lec-multipricing` pipeline and does not reproduce the complete paper workflow on its own.

## Executed PLEXOS archive

The 72-run v13 simulation results are intended for public release as a separate Zenodo dataset because the archive is approximately 200 MB. The archive is available as the [v13-results GitHub Release](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results); it is attached as a release asset rather than committed to Git history. A separate Zenodo deposit has not been made. See [archive release notes](docs/DRJ_V13_ARCHIVE_RELEASE_NOTES.md) and [SHA-256 checksum](docs/DRJ_V13_ARCHIVE_SHA256SUMS). The companion post-processing pipeline required to regenerate all paper tables and figures is not included in this minimal release.

## Repository boundary

The complete collaboration repository remains private. This folder is a staging copy for a separate, minimal public release intended for a new repository under GreenPow's GitHub organization. It must not be used to make the private repository public or to mirror the full research workspace. The executed PLEXOS archive is a separate dataset candidate for Zenodo, not a GitHub repository file.

## Status

## Rights and permissions

No software license is granted by this repository; all rights are reserved. Commercial reuse requires prior written permission from GreenPow Labs GmbH. For permission inquiries, contact [fr@network.berlin](mailto:fr@network.berlin). This notice does not grant rights in third-party materials or dependencies.

## Contents

- `src/emissions_accounting.py`: dataframe-based accounting and aggregation functions.
- `requirements.txt`: bounded runtime dependencies.
- `docs/INPUT_SCHEMA.md`: required columns and data-boundary notes.
- `docs/PAPER_ARTIFACT_MAP.md`: what the available archive and code can support when reviewing the paper.
- `docs/ARCHIVE_GUIDE.md`: archive layout and interpretation limits.
- `docs/REPRODUCIBILITY.md`: what can and cannot be rerun from this candidate.

The module does not fetch or embed Electricity Maps data. A caller supplies carbon-intensity values and all other input data. Users must obtain inputs through their own licensed access and follow all applicable terms. Derived outputs may remain restricted by the source-data terms. Some reporting helpers refer to the originating study's scenarios and assumptions; this snapshot is not represented as a generic validated package.

## Relationship to the PLEXOS archive and paper

The separate `DRJ_MultiYear_v13_executed_logs.zip` archive contains the executed PLEXOS model and run outputs. Its internal `README_runs.md` describes a companion repository with `postprocessing/run_all.py`, which is not included in this code candidate. This candidate therefore cannot regenerate the paper's PLEXOS KPIs, tables, or figures from the archive. See the artifact map and reproducibility note before interpreting the files.

## Environment

Python 3.10 or newer is recommended. Install dependencies with:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Import the module from `src` and pass a pandas DataFrame to the desired public function. Input values should be synthetic or independently cleared for use. See `docs/INPUT_SCHEMA.md`.

This is a limited code release, not the complete study pipeline. The archive and workflow limitations are documented above and in `docs/`. The module contains study-specific scenario labels, methodological assumptions, and reporting language.
