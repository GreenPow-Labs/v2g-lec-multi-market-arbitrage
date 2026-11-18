# Carbon-accounting module guide

The module in `src/emissions_accounting.py` transforms caller-provided pandas DataFrames. It does not read the PLEXOS archive, download third-party data, or produce the paper's full set of tables and figures.

## Quick example

This small example uses synthetic data. It shows the basic hourly calculation and scenario summary; it is not a paper result.

```python
import pandas as pd

from src.emissions_accounting import (
    add_grid_exchange_and_emissions,
    summarize_by_scenario,
)

hourly = pd.DataFrame(
    [{
        "scenario": "C",
        "net_market_sales_mwh": -0.5,
        "carbon_intensity_gco2eq_per_kwh": 300.0,
        "renewable_generation_mwh": 0.3,
        "solar_generation_mwh": 0.3,
        "wind_generation_mwh": 0.0,
        "household_load_mwh": 0.6,
        "bess_charge_mwh": 0.1,
        "bess_discharge_mwh": 0.0,
        "ev_charge_mwh": 0.1,
        "ev_discharge_mwh": 0.0,
    }]
)

hourly_with_emissions = add_grid_exchange_and_emissions(
    hourly,
    renewable_ef_gco2_per_kwh=11.0,
)
summary = summarize_by_scenario(hourly_with_emissions)
print(summary[["total_grid_import_mwh", "gross_operational_emissions_tco2eq"]])
```

The input represents 0.5 MWh of grid imports. At 300 gCO₂e/kWh, the calculated gross operational emissions are 0.15 tCO₂e. The renewable lifecycle factor in this example is an illustrative assumption, not a value supplied by the study.

## Input fields and units

The basic hourly function expects these columns:

| Column | Meaning | Unit |
|---|---|---|
| `scenario` | Scenario label, such as `A`, `B`, or `C` | Text |
| `net_market_sales_mwh` | Net market sales; positive is export and negative is import | MWh |
| `carbon_intensity_gco2eq_per_kwh` | Carbon intensity assigned to grid imports and export credit | gCO₂e/kWh |
| `renewable_generation_mwh` | Total renewable generation | MWh |
| `household_load_mwh` | Household demand | MWh |
| `bess_charge_mwh`, `bess_discharge_mwh` | Stationary battery flows | MWh |
| `ev_charge_mwh`, `ev_discharge_mwh` | EV fleet flows | MWh |

For source-specific renewable accounting, also pass `solar_generation_mwh` and `wind_generation_mwh`. State-tracking functions require additional fields such as stored energy and a chronological timestamp index. See each function's signature and implementation for its full requirements.

## What the main functions do

- `add_grid_exchange_and_emissions` derives grid imports and exports from the sign of net market sales, calculates gross operational emissions, calculates export credits separately, and adds renewable lifecycle emissions using caller-supplied factors.
- `summarize_by_scenario` aggregates the enriched hourly data. By default, it compares scenarios with scenario `C`; set `baseline_scenario` if your labels differ.
- `run_storage_carbon_attribution` tracks the carbon intensity assigned to energy stored in and discharged from the BESS and EV fleet. The first timestamp initializes storage state; the first interval calculation starts on the following row. Input rows must be in chronological order within each scenario.
- `validate_assumptions` returns warnings and informational checks for issues such as incomplete annual coverage, source-balance errors, or simultaneous storage charging and discharging. Review the returned messages; the function does not certify the data or model.

## Accounting boundaries

The default `grid_ci_boundary="operational"` labels the grid carbon-intensity basis. When a positive renewable lifecycle factor is supplied, the module also calculates a **hybrid** source footprint by combining operational grid emissions with lifecycle emissions for renewable generation. This is not a complete life-cycle assessment. The output includes a note describing this boundary.

The module reports gross operational emissions and export credits separately. A net-with-export-credit total is a separate accounting choice; do not present it as gross emissions or as a universally accepted attribution method. Storage results depend on the selected initial storage intensity, allocation method, and battery-efficiency mode. Record these assumptions when reporting results.

## Data and reuse

Use input data only when you have the right to use them. The public simulation archive omits some restricted series; see the [data inventory](ARCHIVE_DATA_INVENTORY.md). This code release grants no reuse license, and derived outputs may still be subject to source-data terms.
