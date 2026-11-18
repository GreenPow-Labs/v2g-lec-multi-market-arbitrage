# Paper artifact map

This map connects items in the supplied pre-final manuscript with the run files in the [public v13 archive](https://github.com/GreenPow-Labs/v2g-lec-multi-market-arbitrage/releases/tag/v13-results). It is a guide to where relevant outputs may be found; it does not show that the paper results have been regenerated.

## Main PLEXOS study

The manuscript describes scenarios A, B, and C; optimization and settlement stages (X.1 and X.2); results for 2023–2025; and sensitivity runs. The archive contains 72 run folders, each with PLEXOS logs and result files, plus the model XML, build/check scripts, and a file manifest.

| Manuscript item | Relevant archive material | What the files in this release support |
|---|---|---|
| Tables 1–2: nomenclature and prior-work comparison | Manuscript | Not simulation artifacts; not generated here |
| Tables 3–7: solver/model setup, price characteristics, EV profiles and technical inputs | `model_overview.csv`, `run_order.csv`, XML/model files, scripts, and price/input files where included | Configuration can be inspected. The archive README identifies restricted price series and omitted inputs; these tables cannot all be regenerated from the files in this release |
| Table 8: yearly settled-schedule results | Baseline settlement runs `2023_A2`–`2025_A2`, `2023_B2`–`2025_B2`, and `2023_C2`–`2025_C2`; inspect each corresponding `Model <run> Solution/` folder | Run outputs are available in the separate archive. KPI extraction and comparison with the published table require the absent companion post-processing workflow |
| Table 9: three-year means for both stages | Baseline runs `2023/2024/2025_{A,B,C}{1,2}` | Both optimization (`1`) and settlement (`2`) stages are represented. The aggregation code and reconciliation to the table are absent here |
| Table 10: forecast errors and short-term price deviations | Model inputs and run artifacts may provide parts of the underlying series; the archive README explicitly says some price series are omitted | Cannot independently recalculate all reported statistics from the files in this release |
| Table 11: battery throughput, cycles and estimated degradation | Battery and vehicle interval outputs in the baseline solution folders | Raw operating series are archived; cycle/degradation calculation and comparison with reported values require the absent analysis workflow |
| Figures 1–5: scenario design, model diagram, EV data and validation | Manuscript figures plus model/configuration archive | The manuscript can be read; underlying figure regeneration is not provided here, and profile/source inputs may be restricted or omitted |
| Figure 6: annual community energy cost | Baseline settlement runs A2/B2/C2 for 2023–2025; inspect market and charging-station outputs in their solution folders | Source results are archived; figure-generation and numeric reconciliation are not included |
| Figure 7: 2025 sensitivity analysis | 18 sensitivity levels, each with `B1`, `C1`, `C2` runs: `S-EV*`, `S-RES*`, `S-LOAD*`, `S-MIX*` | Run design can be enumerated from `run_order.csv` and `model_overview.csv`; plotted KPI calculations are absent |
| Figure 8: daily four-hour price spreads | Day-ahead, intraday and imbalance price series, where present in the archive | The archive README says restricted intraday/imbalance series are omitted; full regeneration is not supported here |
| Figure 9: annual EV gain against V1G | Baseline scenario results plus charging/discharging and cost outputs for 2023–2025 | Inputs to the comparison are partly inspectable; EV-cohort weighting and figure calculation are not provided here |

The run names and file types in this table are navigation hints drawn from the archive index and manuscript captions. They do not verify the reported numbers. The archive README says the missing `postprocessing/run_all.py` workflow produces the paper's KPI tables, figures, and analysis. Without that workflow and a comparison against the manuscript, this map cannot confirm that archived outputs match the reported values.

## Carbon-accounting code in this repository

`src/emissions_accounting.py` provides calculations for grid exchanges, emissions attribution, storage carbon accounting, aggregation, sensitivity analysis, and reporting tables. Related carbon-accounting outputs with names such as `paper_environmental_main_table.csv`, `paper_environmental_export_credit_sensitivity_table.csv`, and `paper_environmental_lifecycle_adjusted_table.csv` are not included or mapped to numbered manuscript tables. Their source data and redistribution status require separate review.

## Reviewer takeaway

The archive lets readers inspect the executed PLEXOS outputs. This repository also contains a separate carbon-accounting module, but not the companion post-processing workflow. The materials available here are therefore not enough to regenerate all paper tables and figures. See [Reproducibility](REPRODUCIBILITY.md) and the [archive guide](ARCHIVE_GUIDE.md).
