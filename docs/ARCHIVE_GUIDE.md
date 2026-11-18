# Executed PLEXOS archive guide

This guide summarizes the archive's own `README_runs.md` and its observed top-level structure. The archive is a separate dataset candidate, not part of this code repository.

## Archive contents

- `DRJ_MultiYear_v13.xml`: PLEXOS model XML.
- `data_files/`, model overview/run-order files, and `scripts/`: model inputs/configuration and model-build/check scripts, as described by the archive README.
- One `Model <name> Solution/` directory per run, containing PLEXOS logs, interval result CSVs, annual result CSVs, and a ZIP of the PLEXOS solution database.
- `MANIFEST.csv`: paths, byte sizes, and SHA-256 hashes for archive files.
- `README_runs.md`: run scope, file overview, and omitted-input notes.

The archive README describes 72 runs across 2023–2025, scenarios A/B/C and optimization/settlement stages, including 2025 sensitivity sweeps. It names PLEXOS 11.000 R05 and Gurobi 12.0.0 as the execution environment.

## Run naming and index

Use `run_order.csv` as the execution index and `model_overview.csv` for the configuration row keyed by each run name. In the baseline names, the year is followed by scenario and stage: for example, `2025_C1` is scenario C, optimization stage; `2025_C2` is its settlement stage. The `needs` column in `run_order.csv` records prerequisite runs, so the runs should not be interpreted as 72 independent cases.

The baseline matrix is six runs per year:

| Year | Scenario A (V1G) | Scenario B (V2G day-ahead) | Scenario C (V2G day-ahead + intraday) |
|---|---|---|---|
| 2023 | `2023_A1`, `2023_A2` | `2023_B1`, `2023_B2` | `2023_C1`, `2023_C2` |
| 2024 | `2024_A1`, `2024_A2` | `2024_B1`, `2024_B2` | `2024_C1`, `2024_C2` |
| 2025 | `2025_A1`, `2025_A2` | `2025_B1`, `2025_B2` | `2025_C1`, `2025_C2` |

Within the baseline naming convention, stage `1` is the optimization run and stage `2` is the settlement run. Confirm scenario labels and dependencies against the corresponding `model_overview.csv` and `run_order.csv` rows when analyzing a run.

The remaining 54 runs are sensitivity runs: 18 parameter levels, each represented by `B1`, `C1`, and `C2` runs. The prefixes identify the varied factor:

| Prefix | Varied factor | Levels encoded in run names |
|---|---|---|
| `S-EV` | EV fleet size | 50, 75, 150, 200, 400 EVs |
| `S-RES` | Renewable capacity | 40%, 60%, 100%, 120% RES penetration labels; `model_overview.csv` gives the corresponding PV/wind capacities |
| `S-LOAD` | Consumer load scaled together with RES | 50, 75, 150, 200 percent of base |
| `S-MIX` | Residents' share of EV fleet | 0, 25, 50, 75, 100 percent |

The percentages/levels above are encoded in the model index; the physical parameter values for each case are in `model_overview.csv`. For example, the S-RES rows list PV/wind capacities of 0.25/0.10 MW (`S-RES40`), 0.375/0.15 MW (`S-RES60`), 0.625/0.25 MW (`S-RES100`), and 0.75/0.30 MW (`S-RES120`). The manuscript describes a 100-EV base case, 80% RES penetration and 65% resident EV share for Figure 7. Use the index rather than inferring configurations from a folder name alone.

Each run folder is named `Model <run name> Solution/`. Inspect its `Model ( <run name> ) Log.txt` for solver/run evidence and its `Interval/` CSVs for time-series properties. `Year/` files contain annual aggregates. The class/property names in the CSV filenames identify the PLEXOS object stream; they are not paper KPI names.

## Omitted inputs and companion workflow

The archive README says restricted Electricity Maps carbon-intensity data and some Netztransparenz ID-AEP/reBAP series are not included. It points to a companion repository that downloads the three restricted series and runs `postprocessing/run_all.py`. That companion repository and script are not in this code candidate. The archive's logs/results can be inspected, but reproducing the paper's post-processing from the archive requires the missing workflow and access to any inputs that workflow requires.

## Integrity

The separate Zenodo candidate README records the archive's size, SHA-256, and ZIP-integrity check. Verify the checksum against that README before using a downloaded copy. `MANIFEST.csv` provides per-file checksums for inspecting archive contents after extraction.

## Interpretation cautions

- Executed outputs are evidence of archived model runs, not by themselves a complete reproduction package.
- A run log or output CSV should be interpreted using the model configuration, scenario/run identifiers, units, and manuscript definitions.
- The archive's own README reports that computer and user names in logs were replaced. This is contributor-provided provenance, not a substitute for an independent rights or privacy review.
- The archive is not included in this code candidate and should remain a separate dataset release.
