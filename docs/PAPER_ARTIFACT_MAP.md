# Paper artifact map

This map is based on the supplied pre-final manuscript and the `README_runs.md` inside `DRJ_MultiYear_v13_executed_logs.zip`. It describes what the available materials appear to support; it does not claim that this code candidate regenerates the paper.

## Main PLEXOS study

The manuscript reports three scenarios (A, B, C), optimization and settlement stages (X.1 and X.2), results for 2023–2025, and sensitivity runs. The archive README identifies 72 executed runs and describes one solution folder per run, with PLEXOS logs, interval result CSVs, annual summaries, and solution database ZIPs. It also includes the model XML, build/check scripts, and a manifest.

| Manuscript item | Relevant archive material | What can be checked from this candidate |
|---|---|---|
| Tables 1–2: nomenclature and prior-work comparison | Manuscript | Not simulation artifacts; not generated here |
| Tables 3–7: solver/model setup, price characteristics, EV profiles and technical inputs | `model_overview.csv`, `run_order.csv`, XML/model files, scripts, and price/input files where included | Configuration can be inspected. The archive README identifies restricted price series and omitted inputs; these tables cannot all be regenerated from this candidate |
| Table 8: yearly settled-schedule results | Baseline settlement runs `2023_A2`–`2025_A2`, `2023_B2`–`2025_B2`, and `2023_C2`–`2025_C2`; inspect each corresponding `Model <run> Solution/` folder | Run outputs are available in the separate archive. KPI extraction and comparison with the published table require the absent companion post-processing workflow |
| Table 9: three-year means for both stages | Baseline runs `2023/2024/2025_{A,B,C}{1,2}` | Both optimization (`1`) and settlement (`2`) stages are represented. The aggregation code and reconciliation to the table are absent here |
| Table 10: forecast errors and short-term price deviations | Model inputs and run artifacts may provide parts of the underlying series; the archive README explicitly says some price series are omitted | Cannot independently recalculate all reported statistics from this candidate |
| Table 11: battery throughput, cycles and estimated degradation | Battery and vehicle interval outputs in the baseline solution folders | Raw operating series are archived; cycle/degradation calculation and comparison with reported values require the absent analysis workflow |
| Figures 1–5: scenario design, model diagram, EV data and validation | Manuscript figures plus model/configuration archive | The manuscript can be read; underlying figure regeneration is not provided here, and profile/source inputs may be restricted or omitted |
| Figure 6: annual community energy cost | Baseline settlement runs A2/B2/C2 for 2023–2025; inspect market and charging-station outputs in their solution folders | Source results are archived; figure-generation and numeric reconciliation are not included |
| Figure 7: 2025 sensitivity analysis | 18 sensitivity levels, each with `B1`, `C1`, `C2` runs: `S-EV*`, `S-RES*`, `S-LOAD*`, `S-MIX*` | Run design can be enumerated from `run_order.csv` and `model_overview.csv`; plotted KPI calculations are absent |
| Figure 8: daily four-hour price spreads | Day-ahead, intraday and imbalance price series, where present in the archive | The archive README says restricted intraday/imbalance series are omitted; full regeneration is not supported here |
| Figure 9: annual EV gain against V1G | Baseline scenario results plus charging/discharging and cost outputs for 2023–2025 | Inputs to the comparison are partly inspectable; EV-cohort weighting and figure calculation are not provided here |

Run identifiers and file classes above are a traceability aid based on the archive index and manuscript captions; they are not a verified numerical reconstruction. The archive's internal README names the missing companion workflow as `postprocessing/run_all.py` and says it produces the paper's KPI tables, figures, and analysis. Do not infer exact property-to-KPI formulas or claim numerical agreement without that workflow and an output comparison.

## Carbon-accounting code in this candidate

`src/emissions_accounting.py` provides calculations for grid exchanges, emissions attribution, storage carbon accounting, aggregation, sensitivity analysis, and reporting tables. Related carbon-accounting outputs with names such as `paper_environmental_main_table.csv`, `paper_environmental_export_credit_sensitivity_table.csv`, and `paper_environmental_lifecycle_adjusted_table.csv` are not part of this candidate and are not mapped here to numbered manuscript tables. Their source data and redistribution status require separate review.

## Reviewer takeaway

The archive permits inspection of executed PLEXOS outputs. The current public code candidate documents a separate carbon-accounting module and does not include the companion post-processing workflow. Therefore, this package alone is not sufficient to independently reproduce all paper tables and figures. See [Reproducibility](REPRODUCIBILITY.md) and [Archive guide](ARCHIVE_GUIDE.md).
