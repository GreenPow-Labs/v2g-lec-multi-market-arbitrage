# Inputs for the emissions accounting functions

`src/emissions_accounting.py` transforms pandas DataFrames. It does not load the project files or fetch external data. Required columns depend on which function you call; inspect that function's definition for its complete fields and units.

The hourly workflows use columns such as:

- `scenario`
- `carbon_intensity_gco2eq_per_kwh`
- `net_market_sales_mwh`
- `renewable_generation_mwh`
- `household_load_mwh`
- `bess_charge_mwh`, `bess_discharge_mwh`
- `ev_charge_mwh`, `ev_discharge_mwh`
- `bess_stored_mwh`, `ev_stored_mwh` when state of charge is needed

Some functions accept `solar_generation_mwh` and `wind_generation_mwh` separately. Others use `renewable_generation_mwh`.

This module does not include Electricity Maps values or personal mobility profiles. Bring only data you are entitled to use, and check its terms before sharing inputs or derived results. Aggregation or transformation does not automatically clear data for redistribution.

Some summaries use scenario labels and assumptions from the study. Treat those assumptions as study-specific; they have not been established as general-purpose defaults.
