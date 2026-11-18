# Caller-provided input schema

`emissions_accounting.py` contains dataframe transformations; it does not load project files or retrieve external datasets. The functions require input columns according to the selected function. The core hourly workflow uses fields such as:

- `scenario`
- `carbon_intensity_gco2eq_per_kwh`
- `net_market_sales_mwh`
- `renewable_generation_mwh`
- `household_load_mwh`
- `bess_charge_mwh`, `bess_discharge_mwh`
- `ev_charge_mwh`, `ev_discharge_mwh`
- `bess_stored_mwh`, `ev_stored_mwh` (where the selected storage workflow requires state values)

Some functions support source-specific `solar_generation_mwh` and `wind_generation_mwh`; otherwise they use the aggregate renewable factor. Check each function's implementation for its exact columns and units.

Do not include Electricity Maps values, researcher/operator profiles, personal data, confidential company inputs, or derived outputs unless you have explicit permission for that use and redistribution. Keep source data outside this code repository. An aggregate or transformed result is not automatically safe or redistributable.

This extracted module is study-specific: some reporting helpers assume named scenarios and describe dataset-specific storage behavior. Treat those assumptions as unverified outside the originating study, and review the source and its methodology text for authorship and intellectual-property clearance before reuse or release.
