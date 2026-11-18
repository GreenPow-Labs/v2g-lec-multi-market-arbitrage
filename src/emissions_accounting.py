from __future__ import annotations

from itertools import product
from typing import Iterable

import numpy as np
import pandas as pd


SUM_COLS = [
    "renewable_generation_mwh",
    "solar_generation_mwh",
    "wind_generation_mwh",
    "household_load_mwh",
    "bess_charge_mwh",
    "bess_discharge_mwh",
    "bess_throughput_mwh",
    "ev_charge_mwh",
    "ev_discharge_mwh",
    "ev_throughput_mwh",
    "grid_import_mwh",
    "grid_export_mwh",
    "gross_operational_emissions_kgco2eq",
    "solar_lifecycle_emissions_kgco2eq",
    "wind_lifecycle_emissions_kgco2eq",
    "renewable_lifecycle_emissions_kgco2eq",
    "lifecycle_adjusted_source_emissions_kgco2eq",
    "export_credit_kgco2eq",
    "net_operational_emissions_with_export_credit_kgco2eq",
]

RENEWABLE_SOURCE_COLUMNS = {
    "solar": "solar_generation_mwh",
    "wind": "wind_generation_mwh",
}

MEAN_COLS = [
    "carbon_intensity_gco2eq_per_kwh",
    "lifecycle_adjusted_source_intensity_gco2eq_per_kwh",
]


def add_grid_exchange_and_emissions(
    data: pd.DataFrame,
    renewable_ef_gco2_per_kwh: float,
    renewable_source_ef_gco2_per_kwh: dict[str, float] | None = None,
    grid_ci_boundary: str = "operational",
) -> pd.DataFrame:
    out = data.copy()
    source_cols_available = all(
        col in out.columns for col in RENEWABLE_SOURCE_COLUMNS.values()
    )
    for col in RENEWABLE_SOURCE_COLUMNS.values():
        if col not in out.columns:
            out[col] = 0.0

    out["grid_export_mwh"] = out["net_market_sales_mwh"].clip(lower=0)
    out["grid_import_mwh"] = (-out["net_market_sales_mwh"]).clip(lower=0)

    out["gross_operational_emissions_kgco2eq"] = (
        out["grid_import_mwh"] * out["carbon_intensity_gco2eq_per_kwh"]
    )
    out["renewable_source_balance_error_mwh"] = (
        out[list(RENEWABLE_SOURCE_COLUMNS.values())].sum(axis=1)
        - out["renewable_generation_mwh"]
    )
    out["solar_lifecycle_emissions_kgco2eq"] = 0.0
    out["wind_lifecycle_emissions_kgco2eq"] = 0.0
    if renewable_source_ef_gco2_per_kwh and source_cols_available:
        renewable_lifecycle_emissions = pd.Series(0.0, index=out.index)
        for source, source_col in RENEWABLE_SOURCE_COLUMNS.items():
            ef = float(renewable_source_ef_gco2_per_kwh.get(source, 0.0))
            emissions_col = f"{source}_lifecycle_emissions_kgco2eq"
            out[emissions_col] = out[source_col] * ef
            renewable_lifecycle_emissions += out[emissions_col]
        out["renewable_lifecycle_emissions_kgco2eq"] = renewable_lifecycle_emissions
        out["renewable_ef_mode"] = "source_specific"
    else:
        out["renewable_lifecycle_emissions_kgco2eq"] = (
            out["renewable_generation_mwh"] * renewable_ef_gco2_per_kwh
        )
        out["renewable_ef_mode"] = "aggregate_fallback"
    out["lifecycle_adjusted_source_emissions_kgco2eq"] = (
        out["gross_operational_emissions_kgco2eq"]
        + out["renewable_lifecycle_emissions_kgco2eq"]
    )

    source_energy_mwh = out["grid_import_mwh"] + out["renewable_generation_mwh"]
    out["lifecycle_adjusted_source_intensity_gco2eq_per_kwh"] = np.where(
        source_energy_mwh > 0,
        out["lifecycle_adjusted_source_emissions_kgco2eq"] / source_energy_mwh,
        np.nan,
    )

    out["accounting_boundary_note"] = np.where(
        grid_ci_boundary == "operational",
        "hybrid attribution: operational grid CI plus lifecycle renewable EF; not pure operational or full LCA",
        f"grid CI boundary recorded as {grid_ci_boundary}",
    )

    out["export_credit_kgco2eq"] = (
        out["grid_export_mwh"] * out["carbon_intensity_gco2eq_per_kwh"]
    )
    out["net_operational_emissions_with_export_credit_kgco2eq"] = (
        out["gross_operational_emissions_kgco2eq"] - out["export_credit_kgco2eq"]
    )

    out["bess_throughput_mwh"] = out["bess_charge_mwh"] + out["bess_discharge_mwh"]
    out["ev_throughput_mwh"] = out["ev_charge_mwh"] + out["ev_discharge_mwh"]

    out["cumulative_gross_operational_emissions_kgco2eq"] = (
        out.groupby("scenario")["gross_operational_emissions_kgco2eq"].cumsum()
    )
    out["cumulative_lifecycle_adjusted_source_emissions_kgco2eq"] = (
        out.groupby("scenario")["lifecycle_adjusted_source_emissions_kgco2eq"].cumsum()
    )

    return out


def summarize_by_scenario(
    data: pd.DataFrame,
    baseline_scenario: str = "C",
    renewable_ef_gco2_per_kwh: float | None = None,
    renewable_source_ef_gco2_per_kwh: dict[str, float] | None = None,
    grid_ci_boundary: str = "operational",
) -> pd.DataFrame:
    grouped = data.groupby("scenario")

    summary = grouped.agg(
        total_grid_import_mwh=("grid_import_mwh", "sum"),
        total_grid_export_mwh=("grid_export_mwh", "sum"),
        total_renewable_generation_mwh=("renewable_generation_mwh", "sum"),
        total_solar_generation_mwh=("solar_generation_mwh", "sum"),
        total_wind_generation_mwh=("wind_generation_mwh", "sum"),
        max_abs_renewable_source_balance_error_mwh=(
            "renewable_source_balance_error_mwh",
            lambda x: x.abs().max(),
        ),
        total_household_load_mwh=("household_load_mwh", "sum"),
        total_bess_charge_mwh=("bess_charge_mwh", "sum"),
        total_bess_discharge_mwh=("bess_discharge_mwh", "sum"),
        total_bess_throughput_mwh=("bess_throughput_mwh", "sum"),
        total_ev_charge_mwh=("ev_charge_mwh", "sum"),
        total_ev_discharge_mwh=("ev_discharge_mwh", "sum"),
        total_ev_throughput_mwh=("ev_throughput_mwh", "sum"),
        gross_operational_emissions_kgco2eq=("gross_operational_emissions_kgco2eq", "sum"),
        solar_lifecycle_emissions_kgco2eq=("solar_lifecycle_emissions_kgco2eq", "sum"),
        wind_lifecycle_emissions_kgco2eq=("wind_lifecycle_emissions_kgco2eq", "sum"),
        renewable_lifecycle_emissions_kgco2eq=("renewable_lifecycle_emissions_kgco2eq", "sum"),
        lifecycle_adjusted_source_emissions_kgco2eq=(
            "lifecycle_adjusted_source_emissions_kgco2eq",
            "sum",
        ),
        export_credit_kgco2eq=("export_credit_kgco2eq", "sum"),
        net_operational_emissions_with_export_credit_kgco2eq=(
            "net_operational_emissions_with_export_credit_kgco2eq",
            "sum",
        ),
    )

    for kg_col in [
        "gross_operational_emissions_kgco2eq",
        "solar_lifecycle_emissions_kgco2eq",
        "wind_lifecycle_emissions_kgco2eq",
        "renewable_lifecycle_emissions_kgco2eq",
        "lifecycle_adjusted_source_emissions_kgco2eq",
        "export_credit_kgco2eq",
        "net_operational_emissions_with_export_credit_kgco2eq",
    ]:
        summary[kg_col.replace("_kgco2eq", "_tco2eq")] = summary[kg_col] / 1000.0

    summary = summary.rename(
        columns={
            "net_operational_emissions_with_export_credit_tco2eq": "net_with_export_credit_tco2eq"
        }
    )

    baseline_gross = summary.loc[baseline_scenario, "gross_operational_emissions_kgco2eq"]
    baseline_lifecycle = summary.loc[
        baseline_scenario, "lifecycle_adjusted_source_emissions_kgco2eq"
    ]
    baseline_net = summary.loc[
        baseline_scenario, "net_operational_emissions_with_export_credit_kgco2eq"
    ]

    summary["delta_vs_C_kgco2eq"] = (
        summary["gross_operational_emissions_kgco2eq"] - baseline_gross
    )
    summary["delta_vs_C_tco2eq"] = summary["delta_vs_C_kgco2eq"] / 1000.0
    summary["delta_vs_C_percent"] = np.where(
        baseline_gross != 0,
        summary["delta_vs_C_kgco2eq"] / baseline_gross * 100.0,
        np.nan,
    )

    summary["lifecycle_adjusted_delta_vs_C_kgco2eq"] = (
        summary["lifecycle_adjusted_source_emissions_kgco2eq"] - baseline_lifecycle
    )
    summary["lifecycle_adjusted_delta_vs_C_tco2eq"] = (
        summary["lifecycle_adjusted_delta_vs_C_kgco2eq"] / 1000.0
    )
    summary["lifecycle_adjusted_delta_vs_C_percent"] = np.where(
        baseline_lifecycle != 0,
        summary["lifecycle_adjusted_delta_vs_C_kgco2eq"] / baseline_lifecycle * 100.0,
        np.nan,
    )

    summary["net_with_export_credit_delta_vs_C_kgco2eq"] = (
        summary["net_operational_emissions_with_export_credit_kgco2eq"] - baseline_net
    )
    summary["net_with_export_credit_delta_vs_C_tco2eq"] = (
        summary["net_with_export_credit_delta_vs_C_kgco2eq"] / 1000.0
    )

    summary["import_weighted_grid_ci_gco2eq_per_kwh"] = np.where(
        summary["total_grid_import_mwh"] > 0,
        summary["gross_operational_emissions_kgco2eq"] / summary["total_grid_import_mwh"],
        np.nan,
    )

    source_energy_mwh = (
        summary["total_grid_import_mwh"] + summary["total_renewable_generation_mwh"]
    )
    summary["source_weighted_lifecycle_adjusted_ci_gco2eq_per_kwh"] = np.where(
        source_energy_mwh > 0,
        summary["lifecycle_adjusted_source_emissions_kgco2eq"] / source_energy_mwh,
        np.nan,
    )
    if renewable_ef_gco2_per_kwh is not None:
        summary["renewable_ef_gco2eq_per_kwh"] = renewable_ef_gco2_per_kwh
    if renewable_source_ef_gco2_per_kwh:
        for source, ef in renewable_source_ef_gco2_per_kwh.items():
            summary[f"{source}_ef_gco2eq_per_kwh"] = float(ef)
        summary["renewable_ef_mode"] = "source_specific"
    else:
        summary["renewable_ef_mode"] = "aggregate_fallback"
    summary["grid_ci_boundary"] = grid_ci_boundary

    return summary


def count_simultaneous_storage_operations(
    data: pd.DataFrame, eps: float = 1e-12
) -> pd.DataFrame:
    records = []
    for scenario, scenario_data in data.groupby("scenario", sort=False):
        bess_simultaneous = (
            (scenario_data["bess_charge_mwh"] > eps)
            & (scenario_data["bess_discharge_mwh"] > eps)
        ).sum()
        ev_simultaneous = (
            (scenario_data["ev_charge_mwh"] > eps)
            & (scenario_data["ev_discharge_mwh"] > eps)
        ).sum()
        records.append(
            {
                "scenario": scenario,
                "bess_simultaneous_charge_discharge_rows": int(bess_simultaneous),
                "ev_simultaneous_charge_discharge_rows": int(ev_simultaneous),
            }
        )
    return pd.DataFrame.from_records(records).set_index("scenario")


def aggregate_by_frequency(data: pd.DataFrame, freq: str) -> pd.DataFrame:
    work = data.reset_index().set_index("timestamp")

    summed = work.groupby("scenario").resample(freq)[SUM_COLS].sum().reset_index()
    averaged = work.groupby("scenario").resample(freq)[MEAN_COLS].mean().reset_index()

    aggregated = summed.merge(averaged, on=["scenario", "timestamp"], how="left")

    for kg_col in [
        "gross_operational_emissions_kgco2eq",
        "solar_lifecycle_emissions_kgco2eq",
        "wind_lifecycle_emissions_kgco2eq",
        "renewable_lifecycle_emissions_kgco2eq",
        "lifecycle_adjusted_source_emissions_kgco2eq",
    ]:
        aggregated[kg_col.replace("_kgco2eq", "_tco2eq")] = aggregated[kg_col] / 1000.0

    aggregated["import_weighted_grid_ci_gco2eq_per_kwh"] = np.where(
        aggregated["grid_import_mwh"] > 0,
        aggregated["gross_operational_emissions_kgco2eq"] / aggregated["grid_import_mwh"],
        np.nan,
    )

    source_energy_mwh = aggregated["grid_import_mwh"] + aggregated["renewable_generation_mwh"]
    aggregated["source_weighted_lifecycle_adjusted_ci_gco2eq_per_kwh"] = np.where(
        source_energy_mwh > 0,
        aggregated["lifecycle_adjusted_source_emissions_kgco2eq"] / source_energy_mwh,
        np.nan,
    )

    return aggregated


def compare_metric_against_baseline(
    aggregated: pd.DataFrame,
    metric_col: str,
    baseline_scenario: str = "C",
) -> pd.DataFrame:
    pivot = aggregated.pivot(index="timestamp", columns="scenario", values=metric_col)
    if baseline_scenario not in pivot.columns:
        raise KeyError(f"Baseline scenario '{baseline_scenario}' not found in data.")

    comparison = pd.DataFrame(index=pivot.index)
    for scenario in pivot.columns:
        if scenario == baseline_scenario:
            continue
        comparison[f"{scenario}_minus_{baseline_scenario}_{metric_col}"] = (
            pivot[scenario] - pivot[baseline_scenario]
        )
        comparison[f"{scenario}_minus_{baseline_scenario}_{metric_col}_percent"] = np.where(
            pivot[baseline_scenario] != 0,
            (pivot[scenario] - pivot[baseline_scenario])
            / pivot[baseline_scenario]
            * 100.0,
            np.nan,
        )

    return comparison.reset_index()


def renewable_source_pools(
    row: pd.Series | dict[str, object],
    renewable_ef_gco2_per_kwh: float,
    renewable_source_ef_gco2_per_kwh: dict[str, float] | None = None,
) -> list[dict]:
    if renewable_source_ef_gco2_per_kwh and all(
        col in row for col in RENEWABLE_SOURCE_COLUMNS.values()
    ):
        return [
            {
                "name": source,
                "energy_mwh": max(float(row[source_col]), 0.0),
                "intensity_gco2eq_per_kwh": float(
                    renewable_source_ef_gco2_per_kwh.get(source, 0.0)
                ),
            }
            for source, source_col in RENEWABLE_SOURCE_COLUMNS.items()
        ]
    return [
        {
            "name": "renewable",
            "energy_mwh": max(float(row["renewable_generation_mwh"]), 0.0),
            "intensity_gco2eq_per_kwh": renewable_ef_gco2_per_kwh,
        }
    ]


def first_hour_source_mix_intensity(
    row: pd.Series | dict[str, object],
    renewable_ef: float,
    renewable_source_ef_gco2_per_kwh: dict[str, float] | None = None,
) -> float:
    source_pools = renewable_source_pools(
        row, renewable_ef, renewable_source_ef_gco2_per_kwh
    )
    source_pools.append(
        {
            "name": "grid_import",
            "energy_mwh": max(float(row["grid_import_mwh"]), 0.0),
            "intensity_gco2eq_per_kwh": float(row["carbon_intensity_gco2eq_per_kwh"]),
        }
    )
    source_energy = sum(pool["energy_mwh"] for pool in source_pools)
    source_carbon = sum(
        pool["energy_mwh"] * pool["intensity_gco2eq_per_kwh"] for pool in source_pools
    )
    return source_carbon / source_energy if source_energy > 0 else 0.0


def initial_storage_intensity(first_grid_ci: float, first_source_mix_ci: float, mode: str) -> float:
    if mode == "zero":
        return 0.0
    if mode == "first_grid_hour":
        return float(first_grid_ci)
    if mode == "first_source_mix":
        return float(first_source_mix_ci)
    raise ValueError(
        "initial storage mode must be 'zero', 'first_grid_hour', or 'first_source_mix'."
    )


def initialize_storage_state(first_row: pd.Series, initial_soci: float) -> dict[str, float]:
    bess_energy_mwh = max(float(first_row["bess_stored_mwh"]), 0.0)
    ev_energy_mwh = max(float(first_row["ev_stored_mwh"]), 0.0)
    return {
        "bess_energy_mwh": bess_energy_mwh,
        "ev_energy_mwh": ev_energy_mwh,
        "bess_carbon_kgco2eq": bess_energy_mwh * initial_soci,
        "ev_carbon_kgco2eq": ev_energy_mwh * initial_soci,
    }


def compute_storage_soci(storage_state: dict[str, float], eps: float) -> dict[str, float]:
    return {
        "bess_soci_gco2eq_per_kwh": (
            storage_state["bess_carbon_kgco2eq"] / storage_state["bess_energy_mwh"]
            if storage_state["bess_energy_mwh"] > eps
            else 0.0
        ),
        "ev_soci_gco2eq_per_kwh": (
            storage_state["ev_carbon_kgco2eq"] / storage_state["ev_energy_mwh"]
            if storage_state["ev_energy_mwh"] > eps
            else 0.0
        ),
    }


def apply_storage_discharge(
    storage_state: dict[str, float],
    bess_discharge_mwh: float,
    ev_discharge_mwh: float,
    pre_discharge_soci: dict[str, float],
    bess_efficiency_mode: str = "embedded",
    bess_eta_discharge: float = 1.0,
) -> dict[str, float]:
    if bess_efficiency_mode == "explicit":
        max_bess_delivered_mwh = storage_state["bess_energy_mwh"] * bess_eta_discharge
        bess_released_energy_mwh = min(bess_discharge_mwh, max_bess_delivered_mwh)
        bess_internal_energy_removed_mwh = (
            bess_released_energy_mwh / bess_eta_discharge if bess_eta_discharge > 0 else 0.0
        )
        bess_delivered_intensity_gco2eq_per_kwh = (
            pre_discharge_soci["bess_soci_gco2eq_per_kwh"] / bess_eta_discharge
            if bess_eta_discharge > 0
            else 0.0
        )
    else:
        bess_released_energy_mwh = min(bess_discharge_mwh, storage_state["bess_energy_mwh"])
        bess_internal_energy_removed_mwh = bess_released_energy_mwh
        bess_delivered_intensity_gco2eq_per_kwh = pre_discharge_soci[
            "bess_soci_gco2eq_per_kwh"
        ]
    ev_released_energy_mwh = min(ev_discharge_mwh, storage_state["ev_energy_mwh"])
    bess_discharge_attributed_kgco2eq = (
        bess_internal_energy_removed_mwh * pre_discharge_soci["bess_soci_gco2eq_per_kwh"]
    )
    ev_discharge_attributed_kgco2eq = (
        ev_released_energy_mwh * pre_discharge_soci["ev_soci_gco2eq_per_kwh"]
    )

    storage_state["bess_energy_mwh"] = max(
        storage_state["bess_energy_mwh"] - bess_internal_energy_removed_mwh, 0.0
    )
    storage_state["ev_energy_mwh"] = max(
        storage_state["ev_energy_mwh"] - ev_released_energy_mwh, 0.0
    )
    storage_state["bess_carbon_kgco2eq"] = max(
        storage_state["bess_carbon_kgco2eq"] - bess_discharge_attributed_kgco2eq, 0.0
    )
    storage_state["ev_carbon_kgco2eq"] = max(
        storage_state["ev_carbon_kgco2eq"] - ev_discharge_attributed_kgco2eq, 0.0
    )

    return {
        "bess_released_energy_mwh": bess_released_energy_mwh,
        "bess_internal_energy_removed_mwh": bess_internal_energy_removed_mwh,
        "bess_delivered_intensity_gco2eq_per_kwh": bess_delivered_intensity_gco2eq_per_kwh,
        "ev_released_energy_mwh": ev_released_energy_mwh,
        "bess_discharge_attributed_kgco2eq": bess_discharge_attributed_kgco2eq,
        "ev_discharge_attributed_kgco2eq": ev_discharge_attributed_kgco2eq,
    }


def build_hourly_source_pools(
    row: pd.Series | dict[str, object],
    grid_import_mwh: float,
    grid_ci: float,
    discharge_results: dict[str, float],
    pre_discharge_soci: dict[str, float],
    renewable_ef_gco2_per_kwh: float,
    renewable_source_ef_gco2_per_kwh: dict[str, float] | None = None,
) -> list[dict]:
    # Build the hourly LEC source pool used to compute the mixed source
    # carbon intensity:
    #
    #   CI_mix,t =
    #   (E_sol * CI_sol
    #    + E_wind * CI_wind
    #    + E_mkt * CI_mkt
    #    + E_BESS,dch * CI_BESS,t
    #    + E_EV,dch * CI_EV,t)
    #   /
    #   (E_sol + E_wind + E_mkt + E_BESS,dch + E_EV,dch)
    #
    # where solar, wind, and market imports are direct hourly sources,
    # while BESS and EV discharge enter with the SOCI carried into the
    # current timestep from the previous reconciled storage state. In
    # explicit BESS-efficiency mode the BESS source intensity is converted
    # to a delivered-kWh basis before it enters the DEMS node mix. This
    # mixed intensity is a node-level attribution value only; export
    # benefit uses the export carbon footprint derived from the export
    # sink allocation.
    source_pools = renewable_source_pools(
        row,
        renewable_ef_gco2_per_kwh,
        renewable_source_ef_gco2_per_kwh,
    )
    source_pools.extend(
        [
            {
                "name": "grid_import",
                "energy_mwh": grid_import_mwh,
                "intensity_gco2eq_per_kwh": grid_ci,
            },
            {
                "name": "bess_discharge",
                "energy_mwh": discharge_results["bess_released_energy_mwh"],
                "intensity_gco2eq_per_kwh": discharge_results[
                    "bess_delivered_intensity_gco2eq_per_kwh"
                ],
            },
            {
                "name": "ev_discharge",
                "energy_mwh": discharge_results["ev_released_energy_mwh"],
                "intensity_gco2eq_per_kwh": pre_discharge_soci["ev_soci_gco2eq_per_kwh"],
            },
        ]
    )
    return source_pools


def summarize_export_attribution(
    export_allocation: dict[str, float],
    grid_ci: float,
    eps: float,
) -> dict[str, float]:
    export_attributed_energy_mwh = export_allocation["energy_mwh"]
    export_carbon_footprint_kgco2eq = export_allocation["carbon_kgco2eq"]
    export_carbon_intensity_gco2eq_per_kwh = (
        export_carbon_footprint_kgco2eq / export_attributed_energy_mwh
        if export_attributed_energy_mwh > eps
        else np.nan
    )
    gross_avoided_emissions_credit_kgco2eq = (
        export_attributed_energy_mwh * grid_ci
    )
    net_export_carbon_benefit_kgco2eq = (
        gross_avoided_emissions_credit_kgco2eq - export_carbon_footprint_kgco2eq
    )
    net_export_carbon_benefit_gco2eq_per_kwh = (
        grid_ci - export_carbon_intensity_gco2eq_per_kwh
        if export_attributed_energy_mwh > eps
        else np.nan
    )
    return {
        "export_attributed_energy_mwh": export_attributed_energy_mwh,
        "export_carbon_footprint_kgco2eq": export_carbon_footprint_kgco2eq,
        "export_attributed_carbon_kgco2eq": export_carbon_footprint_kgco2eq,
        "export_carbon_intensity_gco2eq_per_kwh": export_carbon_intensity_gco2eq_per_kwh,
        "export_attributed_intensity_gco2eq_per_kwh": export_carbon_intensity_gco2eq_per_kwh,
        "gross_avoided_emissions_credit_kgco2eq": gross_avoided_emissions_credit_kgco2eq,
        "net_export_carbon_benefit_kgco2eq": net_export_carbon_benefit_kgco2eq,
        "net_export_carbon_benefit_gco2eq_per_kwh": net_export_carbon_benefit_gco2eq_per_kwh,
    }


def apply_storage_charge(
    storage_state: dict[str, float],
    bess_charge_mwh: float,
    ev_charge_mwh: float,
    bess_charge_attributed_kgco2eq: float,
    ev_charge_attributed_kgco2eq: float,
    bess_efficiency_mode: str = "embedded",
    bess_eta_charge: float = 1.0,
) -> None:
    if bess_efficiency_mode == "explicit":
        storage_state["bess_energy_mwh"] += bess_charge_mwh * bess_eta_charge
        storage_state["bess_carbon_kgco2eq"] += (
            bess_charge_attributed_kgco2eq * bess_eta_charge
        )
    else:
        storage_state["bess_energy_mwh"] += bess_charge_mwh
        storage_state["bess_carbon_kgco2eq"] += bess_charge_attributed_kgco2eq
    storage_state["ev_energy_mwh"] += ev_charge_mwh
    storage_state["ev_carbon_kgco2eq"] += ev_charge_attributed_kgco2eq


def reconcile_reported_storage_energy_preserving_soci(
    storage_state: dict[str, float],
    reported_bess_energy_mwh: float,
    reported_ev_energy_mwh: float,
    eps: float,
) -> dict[str, float]:
    post_charge_soci = compute_storage_soci(storage_state, eps)
    storage_state["bess_energy_mwh"] = reported_bess_energy_mwh
    storage_state["ev_energy_mwh"] = reported_ev_energy_mwh
    storage_state["bess_carbon_kgco2eq"] = (
        storage_state["bess_energy_mwh"] * post_charge_soci["bess_soci_gco2eq_per_kwh"]
    )
    storage_state["ev_carbon_kgco2eq"] = (
        storage_state["ev_energy_mwh"] * post_charge_soci["ev_soci_gco2eq_per_kwh"]
    )
    return compute_storage_soci(storage_state, eps)


def summarize_total_stored_state(
    storage_state: dict[str, float],
    eps: float,
) -> dict[str, float]:
    total_stored_energy_mwh = (
        storage_state["bess_energy_mwh"] + storage_state["ev_energy_mwh"]
    )
    total_stored_attributed_carbon_kgco2eq = (
        storage_state["bess_carbon_kgco2eq"] + storage_state["ev_carbon_kgco2eq"]
    )
    return {
        "total_stored_energy_mwh": total_stored_energy_mwh,
        "total_stored_attributed_carbon_kgco2eq": total_stored_attributed_carbon_kgco2eq,
        "total_stored_intensity_gco2eq_per_kwh": (
            total_stored_attributed_carbon_kgco2eq / total_stored_energy_mwh
            if total_stored_energy_mwh > eps
            else 0.0
        ),
    }


def build_storage_result_row(
    timestamp,
    scenario: str,
    allocation_method: str,
    initial_mode: str,
    bess_efficiency_mode: str,
    bess_eta_charge: float,
    bess_eta_discharge: float,
    renewable_ef_gco2eq_per_kwh: float,
    renewable_source_ef_gco2_per_kwh: dict[str, float] | None,
    allocation: dict,
    household_attributed_kgco2eq: float,
    bess_charge_attributed_kgco2eq: float,
    ev_charge_attributed_kgco2eq: float,
    export_summary: dict[str, float],
    post_reconciliation_soci: dict[str, float],
    storage_state: dict[str, float],
    total_storage_summary: dict[str, float],
    discharge_results: dict[str, float],
) -> dict:
    # Column names retain the pre-existing schema; these stored-intensity
    # outputs correspond to the literature term State of Carbon Intensity (SOCI).
    return {
        "timestamp": timestamp,
        "scenario": scenario,
        "storage_allocation_method": allocation_method,
        "initial_storage_intensity_mode": initial_mode,
        "bess_efficiency_mode": bess_efficiency_mode,
        "bess_eta_charge": bess_eta_charge,
        "bess_eta_discharge": bess_eta_discharge,
        "renewable_ef_gco2eq_per_kwh": renewable_ef_gco2eq_per_kwh,
        "solar_ef_gco2eq_per_kwh": (renewable_source_ef_gco2_per_kwh or {}).get(
            "solar", np.nan
        ),
        "wind_ef_gco2eq_per_kwh": (renewable_source_ef_gco2_per_kwh or {}).get(
            "wind", np.nan
        ),
        "mixed_source_intensity_gco2eq_per_kwh": allocation[
            "mixed_source_intensity_gco2eq_per_kwh"
        ],
        "source_carbon_available_kgco2eq": allocation["total_source_carbon_kgco2eq"],
        "source_energy_available_mwh": allocation["total_source_energy_mwh"],
        "household_load_attributed_carbon_kgco2eq": household_attributed_kgco2eq,
        "bess_charge_attributed_carbon_kgco2eq": bess_charge_attributed_kgco2eq,
        "ev_charge_attributed_carbon_kgco2eq": ev_charge_attributed_kgco2eq,
        "export_attributed_energy_mwh": export_summary["export_attributed_energy_mwh"],
        "export_carbon_footprint_kgco2eq": export_summary[
            "export_carbon_footprint_kgco2eq"
        ],
        "export_attributed_carbon_kgco2eq": export_summary[
            "export_attributed_carbon_kgco2eq"
        ],
        "export_carbon_intensity_gco2eq_per_kwh": export_summary[
            "export_carbon_intensity_gco2eq_per_kwh"
        ],
        "export_attributed_intensity_gco2eq_per_kwh": export_summary[
            "export_attributed_intensity_gco2eq_per_kwh"
        ],
        "gross_avoided_emissions_credit_kgco2eq": export_summary[
            "gross_avoided_emissions_credit_kgco2eq"
        ],
        "net_export_carbon_benefit_kgco2eq": export_summary[
            "net_export_carbon_benefit_kgco2eq"
        ],
        "net_export_carbon_benefit_gco2eq_per_kwh": export_summary[
            "net_export_carbon_benefit_gco2eq_per_kwh"
        ],
        "storage_attributed_consumption_emissions_kgco2eq": (
            household_attributed_kgco2eq
            + bess_charge_attributed_kgco2eq
            + ev_charge_attributed_kgco2eq
        ),
        "unallocated_source_carbon_kgco2eq": allocation[
            "unallocated_source_carbon_kgco2eq"
        ],
        "unmet_sink_energy_mwh": allocation["unmet_sink_energy_mwh"],
        "bess_stored_intensity_gco2eq_per_kwh": post_reconciliation_soci[
            "bess_soci_gco2eq_per_kwh"
        ],
        "ev_stored_intensity_gco2eq_per_kwh": post_reconciliation_soci[
            "ev_soci_gco2eq_per_kwh"
        ],
        "bess_stored_attributed_carbon_kgco2eq": storage_state["bess_carbon_kgco2eq"],
        "ev_stored_attributed_carbon_kgco2eq": storage_state["ev_carbon_kgco2eq"],
        "total_stored_energy_mwh": total_storage_summary["total_stored_energy_mwh"],
        "total_stored_attributed_carbon_kgco2eq": total_storage_summary[
            "total_stored_attributed_carbon_kgco2eq"
        ],
        "total_stored_intensity_gco2eq_per_kwh": total_storage_summary[
            "total_stored_intensity_gco2eq_per_kwh"
        ],
        "bess_discharge_attributed_carbon_kgco2eq": discharge_results[
            "bess_discharge_attributed_kgco2eq"
        ],
        "ev_discharge_attributed_carbon_kgco2eq": discharge_results[
            "ev_discharge_attributed_kgco2eq"
        ],
    }


def allocate_source_carbon_to_sinks(
    source_pools: list[dict],
    sink_demands_mwh: dict,
    method: str = "proportional",
    eps: float = 1e-12,
) -> dict:
    clean_pools = [
        {
            "name": pool["name"],
            "energy_mwh": max(float(pool["energy_mwh"]), 0.0),
            "intensity_gco2eq_per_kwh": max(float(pool["intensity_gco2eq_per_kwh"]), 0.0),
        }
        for pool in source_pools
        if max(float(pool["energy_mwh"]), 0.0) > eps
    ]
    clean_sinks = {name: max(float(value), 0.0) for name, value in sink_demands_mwh.items()}

    source_energy = sum(pool["energy_mwh"] for pool in clean_pools)
    source_carbon = sum(
        pool["energy_mwh"] * pool["intensity_gco2eq_per_kwh"] for pool in clean_pools
    )
    sink_energy = sum(clean_sinks.values())

    allocations = {name: {"energy_mwh": 0.0, "carbon_kgco2eq": 0.0} for name in clean_sinks}

    if source_energy <= eps or sink_energy <= eps:
        return {
            "allocations": allocations,
            "total_source_energy_mwh": source_energy,
            "total_source_carbon_kgco2eq": source_carbon,
            "mixed_source_intensity_gco2eq_per_kwh": 0.0,
            "unallocated_source_energy_mwh": source_energy,
            "unallocated_source_carbon_kgco2eq": source_carbon,
            "unmet_sink_energy_mwh": sink_energy,
        }

    if method == "proportional":
        # Proportional allocation applies a single hourly mixed source intensity,
        # computed as total source carbon divided by total source energy.
        mixed_intensity = source_carbon / source_energy
        if sink_energy > source_energy:
            scale = source_energy / sink_energy
            unmet_sink_energy = sink_energy - source_energy
            unallocated_energy = 0.0
        else:
            scale = 1.0
            unmet_sink_energy = 0.0
            unallocated_energy = source_energy - sink_energy

        for sink_name, demand in clean_sinks.items():
            supplied_energy = demand * scale
            allocations[sink_name]["energy_mwh"] = supplied_energy
            allocations[sink_name]["carbon_kgco2eq"] = supplied_energy * mixed_intensity

        allocated_carbon = sum(item["carbon_kgco2eq"] for item in allocations.values())
        return {
            "allocations": allocations,
            "total_source_energy_mwh": source_energy,
            "total_source_carbon_kgco2eq": source_carbon,
            "mixed_source_intensity_gco2eq_per_kwh": mixed_intensity,
            "unallocated_source_energy_mwh": unallocated_energy,
            "unallocated_source_carbon_kgco2eq": max(source_carbon - allocated_carbon, 0.0),
            "unmet_sink_energy_mwh": unmet_sink_energy,
        }

    if method == "renewable_first":
        source_order = [
            "solar",
            "wind",
            "renewable",
            "bess_discharge",
            "ev_discharge",
            "grid_import",
        ]
    elif method == "grid_first":
        source_order = [
            "grid_import",
            "bess_discharge",
            "ev_discharge",
            "solar",
            "wind",
            "renewable",
        ]
    else:
        raise ValueError("allocation method must be 'proportional', 'renewable_first', or 'grid_first'.")

    pool_by_name = {pool["name"]: dict(pool) for pool in clean_pools}
    for pool_name in source_order:
        pool_by_name.setdefault(
            pool_name,
            {"name": pool_name, "energy_mwh": 0.0, "intensity_gco2eq_per_kwh": 0.0},
        )

    sink_order = ["household_load", "ev_charge", "bess_charge", "grid_export"]
    for sink_name in sink_order:
        remaining_demand = clean_sinks.get(sink_name, 0.0)
        for pool_name in source_order:
            pool = pool_by_name[pool_name]
            take = min(remaining_demand, pool["energy_mwh"])
            if take <= eps:
                continue
            allocations[sink_name]["energy_mwh"] += take
            allocations[sink_name]["carbon_kgco2eq"] += (
                take * pool["intensity_gco2eq_per_kwh"]
            )
            pool["energy_mwh"] -= take
            remaining_demand -= take
            if remaining_demand <= eps:
                break

    allocated_energy = sum(item["energy_mwh"] for item in allocations.values())
    allocated_carbon = sum(item["carbon_kgco2eq"] for item in allocations.values())

    return {
        "allocations": allocations,
        "total_source_energy_mwh": source_energy,
        "total_source_carbon_kgco2eq": source_carbon,
        "mixed_source_intensity_gco2eq_per_kwh": source_carbon / source_energy,
        "unallocated_source_energy_mwh": max(source_energy - allocated_energy, 0.0),
        "unallocated_source_carbon_kgco2eq": max(source_carbon - allocated_carbon, 0.0),
        "unmet_sink_energy_mwh": max(sink_energy - allocated_energy, 0.0),
    }


def run_storage_carbon_attribution(
    data: pd.DataFrame,
    initial_mode: str = "first_grid_hour",
    allocation_method: str = "proportional",
    bess_efficiency_mode: str = "embedded",
    bess_eta_charge: float = 1.0,
    bess_eta_discharge: float = 1.0,
    renewable_ef_gco2_per_kwh: float = 43.0,
    renewable_source_ef_gco2_per_kwh: dict[str, float] | None = None,
    eps: float = 1e-12,
) -> pd.DataFrame:
    if bess_efficiency_mode not in {"embedded", "explicit"}:
        raise ValueError("bess_efficiency_mode must be 'embedded' or 'explicit'.")
    if bess_efficiency_mode == "explicit" and (
        bess_eta_charge <= 0 or bess_eta_discharge <= 0
    ):
        raise ValueError("explicit BESS efficiency mode requires positive eta values.")

    results = []

    for scenario, scenario_data in data.groupby("scenario", sort=False):
        scenario_data = scenario_data.sort_index()
        if len(scenario_data) < 2:
            continue
        first_row = scenario_data.iloc[0]
        first_ci = float(first_row["carbon_intensity_gco2eq_per_kwh"])
        first_mix_ci = first_hour_source_mix_intensity(
            first_row,
            renewable_ef_gco2_per_kwh,
            renewable_source_ef_gco2_per_kwh,
        )
        init_ci = initial_storage_intensity(first_ci, first_mix_ci, initial_mode)
        storage_state = initialize_storage_state(first_row, init_ci)

        # Each row t is treated as the interval from state t-1 to state t.
        # The first row therefore initializes the starting storage state and
        # the first computable timestep is the second row.
        timestamps = scenario_data.index[1:]
        records = scenario_data.iloc[1:].to_dict("records")
        for timestamp, row in zip(timestamps, records):
            grid_ci = float(row["carbon_intensity_gco2eq_per_kwh"])
            grid_import_mwh = max(float(row["grid_import_mwh"]), 0.0)
            bess_charge_mwh = max(float(row["bess_charge_mwh"]), 0.0)
            bess_discharge_mwh = max(float(row["bess_discharge_mwh"]), 0.0)
            ev_charge_mwh = max(float(row["ev_charge_mwh"]), 0.0)
            ev_discharge_mwh = max(float(row["ev_discharge_mwh"]), 0.0)
            household_load_mwh = max(float(row["household_load_mwh"]), 0.0)
            grid_export_mwh = max(float(row["grid_export_mwh"]), 0.0)

            pre_discharge_soci = compute_storage_soci(storage_state, eps)
            discharge_results = apply_storage_discharge(
                storage_state,
                bess_discharge_mwh,
                ev_discharge_mwh,
                pre_discharge_soci,
                bess_efficiency_mode=bess_efficiency_mode,
                bess_eta_discharge=bess_eta_discharge,
            )
            source_pools = build_hourly_source_pools(
                row,
                grid_import_mwh,
                grid_ci,
                discharge_results,
                pre_discharge_soci,
                renewable_ef_gco2_per_kwh,
                renewable_source_ef_gco2_per_kwh,
            )
            allocation = allocate_source_carbon_to_sinks(
                source_pools,
                {
                    "household_load": household_load_mwh,
                    "ev_charge": ev_charge_mwh,
                    "bess_charge": bess_charge_mwh,
                    "grid_export": grid_export_mwh,
                },
                method=allocation_method,
                eps=eps,
            )
            allocations = allocation["allocations"]

            household_attributed_kg = allocations["household_load"]["carbon_kgco2eq"]
            bess_charge_attributed_kg = allocations["bess_charge"]["carbon_kgco2eq"]
            ev_charge_attributed_kg = allocations["ev_charge"]["carbon_kgco2eq"]
            export_summary = summarize_export_attribution(
                allocations["grid_export"],
                grid_ci,
                eps,
            )

            apply_storage_charge(
                storage_state,
                bess_charge_mwh,
                ev_charge_mwh,
                bess_charge_attributed_kg,
                ev_charge_attributed_kg,
                bess_efficiency_mode=bess_efficiency_mode,
                bess_eta_charge=bess_eta_charge,
            )
            post_reconciliation_soci = reconcile_reported_storage_energy_preserving_soci(
                storage_state,
                max(float(row["bess_stored_mwh"]), 0.0),
                max(float(row["ev_stored_mwh"]), 0.0),
                eps,
            )
            total_storage_summary = summarize_total_stored_state(storage_state, eps)

            results.append(
                build_storage_result_row(
                    timestamp=timestamp,
                    scenario=scenario,
                    allocation_method=allocation_method,
                    initial_mode=initial_mode,
                    bess_efficiency_mode=bess_efficiency_mode,
                    bess_eta_charge=bess_eta_charge,
                    bess_eta_discharge=bess_eta_discharge,
                    renewable_ef_gco2eq_per_kwh=renewable_ef_gco2_per_kwh,
                    renewable_source_ef_gco2_per_kwh=renewable_source_ef_gco2_per_kwh,
                    allocation=allocation,
                    household_attributed_kgco2eq=household_attributed_kg,
                    bess_charge_attributed_kgco2eq=bess_charge_attributed_kg,
                    ev_charge_attributed_kgco2eq=ev_charge_attributed_kg,
                    export_summary=export_summary,
                    post_reconciliation_soci=post_reconciliation_soci,
                    storage_state=storage_state,
                    total_storage_summary=total_storage_summary,
                    discharge_results=discharge_results,
                )
            )

    return pd.DataFrame(results).set_index("timestamp")


def summarize_storage_attribution(storage_attribution: pd.DataFrame) -> pd.DataFrame:
    storage_summary = storage_attribution.groupby("scenario").agg(
        storage_allocation_method=("storage_allocation_method", "first"),
        initial_storage_intensity_mode=("initial_storage_intensity_mode", "first"),
        bess_efficiency_mode=("bess_efficiency_mode", "first"),
        bess_eta_charge=("bess_eta_charge", "first"),
        bess_eta_discharge=("bess_eta_discharge", "first"),
        renewable_ef_gco2eq_per_kwh=("renewable_ef_gco2eq_per_kwh", "first"),
        avg_mixed_source_intensity_gco2eq_per_kwh=("mixed_source_intensity_gco2eq_per_kwh", "mean"),
        avg_bess_stored_intensity_gco2eq_per_kwh=("bess_stored_intensity_gco2eq_per_kwh", "mean"),
        avg_ev_stored_intensity_gco2eq_per_kwh=("ev_stored_intensity_gco2eq_per_kwh", "mean"),
        avg_total_stored_intensity_gco2eq_per_kwh=("total_stored_intensity_gco2eq_per_kwh", "mean"),
        avg_total_stored_energy_mwh=("total_stored_energy_mwh", "mean"),
        max_total_stored_attributed_carbon_kgco2eq=(
            "total_stored_attributed_carbon_kgco2eq",
            "max",
        ),
        source_carbon_available_kgco2eq=("source_carbon_available_kgco2eq", "sum"),
        household_load_attributed_carbon_kgco2eq=("household_load_attributed_carbon_kgco2eq", "sum"),
        bess_charge_attributed_carbon_kgco2eq=("bess_charge_attributed_carbon_kgco2eq", "sum"),
        ev_charge_attributed_carbon_kgco2eq=("ev_charge_attributed_carbon_kgco2eq", "sum"),
        export_attributed_energy_mwh=("export_attributed_energy_mwh", "sum"),
        export_carbon_footprint_kgco2eq=("export_carbon_footprint_kgco2eq", "sum"),
        export_attributed_carbon_kgco2eq=("export_attributed_carbon_kgco2eq", "sum"),
        gross_avoided_emissions_credit_kgco2eq=(
            "gross_avoided_emissions_credit_kgco2eq",
            "sum",
        ),
        net_export_carbon_benefit_kgco2eq=("net_export_carbon_benefit_kgco2eq", "sum"),
        storage_attributed_consumption_emissions_kgco2eq=(
            "storage_attributed_consumption_emissions_kgco2eq",
            "sum",
        ),
        unallocated_source_carbon_kgco2eq=("unallocated_source_carbon_kgco2eq", "sum"),
        unmet_sink_energy_mwh=("unmet_sink_energy_mwh", "sum"),
        bess_discharge_attributed_carbon_kgco2eq=(
            "bess_discharge_attributed_carbon_kgco2eq",
            "sum",
        ),
        ev_discharge_attributed_carbon_kgco2eq=(
            "ev_discharge_attributed_carbon_kgco2eq",
            "sum",
        ),
    )
    for kg_col in [col for col in storage_summary.columns if col.endswith("_kgco2eq")]:
        storage_summary[kg_col.replace("_kgco2eq", "_tco2eq")] = (
            storage_summary[kg_col] / 1000.0
        )
    storage_summary["weighted_export_attributed_intensity_gco2eq_per_kwh"] = np.where(
        storage_summary["export_attributed_energy_mwh"] > 0,
        storage_summary["export_carbon_footprint_kgco2eq"]
        / storage_summary["export_attributed_energy_mwh"],
        np.nan,
    )
    storage_summary["weighted_gross_avoided_emissions_credit_gco2eq_per_kwh"] = np.where(
        storage_summary["export_attributed_energy_mwh"] > 0,
        storage_summary["gross_avoided_emissions_credit_kgco2eq"]
        / storage_summary["export_attributed_energy_mwh"],
        np.nan,
    )
    storage_summary["net_export_carbon_benefit_tco2eq"] = (
        storage_summary["net_export_carbon_benefit_kgco2eq"] / 1000.0
    )
    storage_summary["weighted_net_export_carbon_benefit_gco2eq_per_kwh"] = np.where(
        storage_summary["export_attributed_energy_mwh"] > 0,
        storage_summary["net_export_carbon_benefit_kgco2eq"]
        / storage_summary["export_attributed_energy_mwh"],
        np.nan,
    )
    explicit_bess = (storage_summary["bess_efficiency_mode"] == "explicit").all()
    storage_summary["storage_attribution_note"] = (
        "Allocation layer only; do not add storage discharge attribution to source emissions. "
        + (
            "BESS uses explicit charge/discharge efficiency in storage and export attribution; EV losses remain embedded in the reported time series."
            if explicit_bess
            else "Battery and EV losses are treated as embedded in the reported time series."
        )
    )
    return storage_summary


def run_sensitivity_analysis(
    base_long_df: pd.DataFrame,
    renewable_factors: dict[str, float],
    allocation_methods: Iterable[str],
    initial_storage_modes: Iterable[str],
    bess_efficiency_mode: str = "embedded",
    bess_eta_charge: float = 1.0,
    bess_eta_discharge: float = 1.0,
    baseline_scenario: str = "C",
    grid_ci_boundary: str = "operational",
) -> pd.DataFrame:
    rows = []
    for (factor_label, renewable_ef), allocation_method, initial_mode in product(
        renewable_factors.items(), allocation_methods, initial_storage_modes
    ):
        emissions_df = add_grid_exchange_and_emissions(
            base_long_df,
            renewable_ef_gco2_per_kwh=renewable_ef,
            grid_ci_boundary=grid_ci_boundary,
        )
        summary = summarize_by_scenario(
            emissions_df,
            baseline_scenario=baseline_scenario,
            renewable_ef_gco2_per_kwh=renewable_ef,
            grid_ci_boundary=grid_ci_boundary,
        )
        storage = run_storage_carbon_attribution(
            emissions_df,
            initial_mode=initial_mode,
            allocation_method=allocation_method,
            bess_efficiency_mode=bess_efficiency_mode,
            bess_eta_charge=bess_eta_charge,
            bess_eta_discharge=bess_eta_discharge,
            renewable_ef_gco2_per_kwh=renewable_ef,
        )
        storage_summary = summarize_storage_attribution(storage)
        for scenario in summary.index:
            rows.append(
                {
                    "renewable_factor_case": factor_label,
                    "renewable_ef_gco2eq_per_kwh": renewable_ef,
                    "allocation_method": allocation_method,
                    "initial_storage_intensity_mode": initial_mode,
                    "scenario": scenario,
                    "gross_operational_emissions_tco2eq": summary.loc[
                        scenario, "gross_operational_emissions_tco2eq"
                    ],
                    "lifecycle_adjusted_source_emissions_tco2eq": summary.loc[
                        scenario, "lifecycle_adjusted_source_emissions_tco2eq"
                    ],
                    "lifecycle_adjusted_delta_vs_C_tco2eq": summary.loc[
                        scenario, "lifecycle_adjusted_delta_vs_C_tco2eq"
                    ],
                    "avg_bess_stored_intensity_gco2eq_per_kwh": storage_summary.loc[
                        scenario, "avg_bess_stored_intensity_gco2eq_per_kwh"
                    ],
                    "avg_ev_stored_intensity_gco2eq_per_kwh": storage_summary.loc[
                        scenario, "avg_ev_stored_intensity_gco2eq_per_kwh"
                    ],
                    "unmet_sink_energy_mwh": storage_summary.loc[
                        scenario, "unmet_sink_energy_mwh"
                    ],
                    "unallocated_source_carbon_tco2eq": storage_summary.loc[
                        scenario, "unallocated_source_carbon_tco2eq"
                    ],
                }
            )
    return pd.DataFrame(rows)


def _scenario_value(summary: pd.DataFrame, scenario: str, col: str, decimals: int = 3):
    if scenario not in summary.index:
        return np.nan
    value = summary.loc[scenario, col]
    if isinstance(value, str):
        return value
    if pd.isna(value):
        return np.nan
    return round(float(value), decimals)


def scenario_metric_row(
    summary: pd.DataFrame,
    scenarios: list[str],
    parameter: str,
    unit: str,
    metric: str,
    baseline_scenario: str | None = None,
) -> dict:
    data = {"Parameter": parameter, "Unit": unit}
    for scenario in scenarios:
        col = f"Scen. {scenario}"
        data[col] = (
            "Baseline"
            if baseline_scenario is not None and scenario == baseline_scenario
            else _scenario_value(summary, scenario, metric)
        )
    return data


def storage_metric_row(
    storage_summary: pd.DataFrame,
    scenarios: list[str],
    parameter: str,
    unit: str,
    metric: str,
) -> dict:
    return {
        "Parameter": parameter,
        "Unit": unit,
        **{
            f"Scen. {scenario}": _scenario_value(storage_summary, scenario, metric)
            for scenario in scenarios
        },
    }


def combined_metric_row(
    scenario_summary: pd.DataFrame,
    storage_summary: pd.DataFrame,
    scenarios: list[str],
    parameter: str,
    unit: str,
    scenario_metric: str,
    storage_metric: str,
    operation: str = "subtract",
) -> dict:
    data = {"Parameter": parameter, "Unit": unit}
    for scenario in scenarios:
        left = _scenario_value(scenario_summary, scenario, scenario_metric, decimals=6)
        right = _scenario_value(storage_summary, scenario, storage_metric, decimals=6)
        if pd.isna(left) or pd.isna(right):
            value = np.nan
        elif operation == "subtract":
            value = round(float(left) - float(right), 3)
        elif operation == "add":
            value = round(float(left) + float(right), 3)
        else:
            raise ValueError("operation must be 'subtract' or 'add'.")
        data[f"Scen. {scenario}"] = value
    return data


def add_calculation_words(table: pd.DataFrame, explanations: dict[str, str]) -> pd.DataFrame:
    table = table.copy()
    table["Calculation in words"] = table["Parameter"].map(explanations).fillna("")
    cols = list(table.columns)
    calc_col = cols.pop(cols.index("Calculation in words"))
    unit_idx = cols.index("Unit")
    cols.insert(unit_idx + 1, calc_col)
    return table[cols]


def build_main_environmental_table(
    scenario_summary: pd.DataFrame,
    scenarios: list[str],
    baseline_scenario: str,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Parameter": "Grid-import operational emissions",
                "Unit": "",
                **{f"Scen. {s}": "" for s in scenarios},
            },
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "External-grid imports",
                "MWh",
                "total_grid_import_mwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "External-grid exports",
                "MWh",
                "total_grid_export_mwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "LEC renewable generation",
                "MWh",
                "total_renewable_generation_mwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Grid-import operational emissions",
                "tCO2eq",
                "gross_operational_emissions_tco2eq",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "External-grid import-weighted carbon intensity",
                "gCO2eq/kWh",
                "import_weighted_grid_ci_gco2eq_per_kwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Emissions difference vs Scenario C",
                "tCO2eq",
                "delta_vs_C_tco2eq",
                baseline_scenario=baseline_scenario,
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Emissions difference vs Scenario C",
                "%",
                "delta_vs_C_percent",
                baseline_scenario=baseline_scenario,
            ),
        ]
    )


def build_export_sensitivity_table(
    scenario_summary: pd.DataFrame,
    storage_summary: pd.DataFrame,
    scenarios: list[str],
    baseline_scenario: str,
) -> pd.DataFrame:
    table = pd.DataFrame(
        [
            {
                "Parameter": "Supplementary external-grid exchange and export-credit KPIs",
                "Unit": "",
                **{f"Scen. {s}": "" for s in scenarios},
            },
            storage_metric_row(
                storage_summary,
                scenarios,
                "Exported electricity used for attribution",
                "MWh",
                "export_attributed_energy_mwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Imported energy attributed CO2-equivalent emissions",
                "tCO2eq",
                "gross_operational_emissions_tco2eq",
            ),
            storage_metric_row(
                storage_summary,
                scenarios,
                "Export carbon footprint (CO2-equivalent emissions)",
                "tCO2eq",
                "export_carbon_footprint_tco2eq",
            ),
            storage_metric_row(
                storage_summary,
                scenarios,
                "Export carbon footprint intensity",
                "gCO2eq/kWh",
                "weighted_export_attributed_intensity_gco2eq_per_kwh",
            ),
            storage_metric_row(
                storage_summary,
                scenarios,
                "Displaced external-grid carbon intensity (gCO2eq/kWh)",
                "gCO2eq/kWh",
                "weighted_gross_avoided_emissions_credit_gco2eq_per_kwh",
            ),
            storage_metric_row(
                storage_summary,
                scenarios,
                "Net export CO2-equivalent emissions benefit intensity (gCO2eq/kWh, + avoided / - harmful)",
                "gCO2eq/kWh",
                "weighted_net_export_carbon_benefit_gco2eq_per_kwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Gross avoided emissions credit from exports",
                "tCO2eq",
                "export_credit_tco2eq",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Net emissions after gross export credit",
                "tCO2eq",
                "net_with_export_credit_tco2eq",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Difference in net emissions after gross export credit vs Scenario C",
                "tCO2eq",
                "net_with_export_credit_delta_vs_C_tco2eq",
                baseline_scenario=baseline_scenario,
            ),
            storage_metric_row(
                storage_summary,
                scenarios,
                "Net export CO2-equivalent emissions benefit (tCO2eq, + avoided / - harmful)",
                "tCO2eq",
                "net_export_carbon_benefit_tco2eq",
            ),
            combined_metric_row(
                scenario_summary,
                storage_summary,
                scenarios,
                "Net attributed CO2-equivalent carbon balance",
                "tCO2eq",
                "gross_operational_emissions_tco2eq",
                "net_export_carbon_benefit_tco2eq",
                operation="subtract",
            ),
        ]
    )
    return add_calculation_words(
        table,
        {
            "Supplementary external-grid exchange and export-credit KPIs": "",
            "Exported electricity used for attribution": (
                "Exported energy from the allocation layer used as the basis for export carbon attribution."
            ),
            "Imported energy attributed CO2-equivalent emissions": (
                "Imported external-grid energy multiplied by hourly external-grid carbon intensity."
            ),
            "Export carbon footprint (CO2-equivalent emissions)": (
                "Exported attributed energy multiplied by export carbon intensity from the export sink allocation."
            ),
            "Export carbon footprint intensity": (
                "Export carbon footprint divided by exported electricity used for attribution."
            ),
            "Displaced external-grid carbon intensity (gCO2eq/kWh)": (
                "Displaced external-grid carbon intensity used for the gross avoided emissions credit from exports."
            ),
            "Net export CO2-equivalent emissions benefit intensity (gCO2eq/kWh, + avoided / - harmful)": (
                "Displaced external-grid carbon intensity minus export carbon footprint intensity. Positive values mean avoided emissions; negative values mean the export was more carbon-intensive than the displaced external-grid supply."
            ),
            "Net export CO2-equivalent emissions benefit (tCO2eq, + avoided / - harmful)": (
                "Gross avoided emissions credit from exports minus export carbon footprint. Positive values mean net avoided emissions; negative values mean net harmful export."
            ),
            "Gross avoided emissions credit from exports": (
                "Exported attributed energy multiplied by displaced external-grid carbon intensity."
            ),
            "Net emissions after gross export credit": (
                "Imported energy attributed emissions minus gross avoided emissions credit from exports."
            ),
            "Difference in net emissions after gross export credit vs Scenario C": (
                "Net emissions after gross export credit minus Scenario C net emissions after gross export credit."
            ),
            "Net attributed CO2-equivalent carbon balance": (
                "Imported energy attributed CO2-equivalent emissions minus net export CO2-equivalent emissions benefit."
            ),
        },
    )


def build_region_environment_impact_kpis_table(
    scenario_summary: pd.DataFrame,
    storage_summary: pd.DataFrame,
    scenarios: list[str] | None = None,
) -> pd.DataFrame:
    if scenarios is None:
        scenarios = [s for s in ["A", "B", "C"] if s in scenario_summary.index]
    return pd.DataFrame(
        [
            {
                "KPI": "Grid imported energy",
                "Unit": "MWh",
                **{
                    s: float(scenario_summary.loc[s, "total_grid_import_mwh"])
                    for s in scenarios
                },
            },
            {
                "KPI": "Imported energy attributed CO2-equivalent emissions",
                "Unit": "tCO2eq",
                **{
                    s: float(scenario_summary.loc[s, "gross_operational_emissions_tco2eq"])
                    for s in scenarios
                },
            },
            {
                "KPI": "Exported electricity used for attribution",
                "Unit": "MWh",
                **{
                    s: float(storage_summary.loc[s, "export_attributed_energy_mwh"])
                    for s in scenarios
                },
            },
            {
                "KPI": "Export carbon footprint",
                "Unit": "tCO2eq",
                **{
                    s: float(storage_summary.loc[s, "export_carbon_footprint_tco2eq"])
                    for s in scenarios
                },
            },
            {
                "KPI": "Net export CO2-equivalent emissions benefit",
                "Unit": "tCO2eq",
                **{
                    s: float(storage_summary.loc[s, "net_export_carbon_benefit_tco2eq"])
                    for s in scenarios
                },
            },
        ]
    )


def build_lifecycle_environmental_table(
    scenario_summary: pd.DataFrame,
    scenarios: list[str],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Parameter": "Lifecycle-adjusted source footprint",
                "Unit": "",
                **{f"Scen. {s}": "" for s in scenarios},
            },
            {
                "Parameter": "Source-specific renewable lifecycle emissions",
                "Unit": "",
                **{f"Scen. {s}": "" for s in scenarios},
            },
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Aggregate renewable lifecycle emissions factor fallback",
                "gCO2eq/kWh",
                "renewable_ef_gco2eq_per_kwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Solar lifecycle emissions factor used",
                "gCO2eq/kWh",
                "solar_ef_gco2eq_per_kwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Wind lifecycle emissions factor used",
                "gCO2eq/kWh",
                "wind_ef_gco2eq_per_kwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "LEC solar generation",
                "MWh",
                "total_solar_generation_mwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "LEC wind generation",
                "MWh",
                "total_wind_generation_mwh",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Solar lifecycle-attributed emissions",
                "tCO2eq",
                "solar_lifecycle_emissions_tco2eq",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Wind lifecycle-attributed emissions",
                "tCO2eq",
                "wind_lifecycle_emissions_tco2eq",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Renewable lifecycle-attributed emissions",
                "tCO2eq",
                "renewable_lifecycle_emissions_tco2eq",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Grid-import operational emissions",
                "tCO2eq",
                "gross_operational_emissions_tco2eq",
            ),
            scenario_metric_row(
                scenario_summary,
                scenarios,
                "Lifecycle-adjusted source footprint",
                "tCO2eq",
                "lifecycle_adjusted_source_emissions_tco2eq",
            ),
        ]
    )


def build_table_4_caption() -> str:
    return (
        "Table 4. Summary of economic, LEC energy-balance, and environmental KPIs across "
        "simulation scenarios. Scenario C represents the validated real-consumption baseline, "
        "while Scenarios A and B represent forecast-based market operation cases. Grid-import "
        "operational emissions are calculated from hourly imports from the external grid multiplied by the "
        "corresponding external-grid carbon intensity. Positive net market sales are treated "
        "as electricity exports to the external grid, while negative values are treated as imports from the external grid. "
        "Source-specific renewable lifecycle emissions are calculated hourly from observed "
        "LEC solar and wind generation multiplied by their configured lifecycle emissions "
        "factors. Export carbon footprint, gross avoided emissions credit from exports, "
        "signed net export CO2-equivalent emissions benefit, and net attributed CO2-equivalent carbon balance are reported in a supplementary external-grid exchange block so they are not mixed with the primary operational metric. "
        "The lifecycle-adjusted source footprint combines "
        "grid-import operational emissions with source-specific renewable lifecycle "
        "attribution; when the grid carbon-intensity column is operational, this is a "
        "hybrid attribution metric, not a pure operational metric or ISO 14040-compliant "
        "lifecycle assessment."
    )


def build_table_4_notes() -> list[str]:
    return [
        "Note 1: Grid-import operational emissions include only emissions associated with imported electricity from the external grid.",
        "Note 2: LEC renewable generation is treated as zero operational emissions in the primary grid-import operational metric. Source-specific renewable lifecycle emissions are excluded from the primary metric and reported separately as lifecycle-adjusted source footprint sensitivity analysis.",
        "Note 3: Exported electricity is not subtracted from grid-import operational emissions in the primary result. Export carbon footprint, gross avoided emissions credit from exports, signed net export CO2-equivalent emissions benefit, and net attributed CO2-equivalent carbon balance are reported only in the supplementary external-grid exchange block. Positive benefit values mean avoided emissions; negative values mean the export was more harmful than the displaced external-grid supply.",
        "Note 4: The lifecycle-adjusted source footprint combines grid-import operational emissions with source-specific renewable lifecycle emissions. If the grid carbon-intensity column is operational-only, this is a hybrid attribution metric rather than a pure ISO 14040-compliant lifecycle assessment.",
        "Note 5: BESS and EV batteries are included within the LEC system boundary as storage assets. Stored-energy attributed carbon stock and the corresponding State of Carbon Intensity (SOCI) are attribution variables, not new emission sources. In the current v2 workbook, BESS can optionally apply explicit charge/discharge efficiency while EV losses remain embedded in the reported time series unless a separate EV efficiency model is introduced. The update3 dataset supports a mutually exclusive charge/discharge interpretation for BESS, but the aggregate EV series still contains simultaneous charge/discharge rows, so EV remains on the general stock-and-flow update.",
        "Note 6: The CSV gives LEC source generation by type, but not exact source-to-load routing. Storage/load/export allocation therefore uses the configured proportional, renewable-first, or grid-first allocation assumption.",
        "Note 7: Scenario C is the baseline for all emissions-difference calculations.",
    ]


def build_paper_environmental_tables(
    scenario_summary: pd.DataFrame,
    storage_summary: pd.DataFrame,
    baseline_scenario: str = "C",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, list[str]]:
    scenarios = list(scenario_summary.index)
    main_table = build_main_environmental_table(
        scenario_summary, scenarios, baseline_scenario
    )
    export_table = build_export_sensitivity_table(
        scenario_summary, storage_summary, scenarios, baseline_scenario
    )
    lifecycle_table = build_lifecycle_environmental_table(
        scenario_summary, scenarios
    )
    caption = build_table_4_caption()
    notes = build_table_4_notes()
    return main_table, export_table, lifecycle_table, caption, notes


def build_results_dashboard(
    scenario_summary: pd.DataFrame,
    storage_summary: pd.DataFrame,
) -> pd.DataFrame:
    dashboard = scenario_summary[
        [
            "total_grid_import_mwh",
            "total_grid_export_mwh",
            "total_renewable_generation_mwh",
            "total_solar_generation_mwh",
            "total_wind_generation_mwh",
            "gross_operational_emissions_tco2eq",
            "solar_lifecycle_emissions_tco2eq",
            "wind_lifecycle_emissions_tco2eq",
            "lifecycle_adjusted_source_emissions_tco2eq",
            "delta_vs_C_tco2eq",
            "delta_vs_C_percent",
            "import_weighted_grid_ci_gco2eq_per_kwh",
        ]
    ].copy()
    dashboard = dashboard.join(
        storage_summary[
            [
                "avg_bess_stored_intensity_gco2eq_per_kwh",
                "avg_ev_stored_intensity_gco2eq_per_kwh",
                "weighted_export_attributed_intensity_gco2eq_per_kwh",
                "weighted_net_export_carbon_benefit_gco2eq_per_kwh",
            ]
        ],
        how="left",
    )
    dashboard = dashboard.rename(
        columns={
            "total_grid_import_mwh": "External-grid imports (MWh)",
            "total_grid_export_mwh": "External-grid exports (MWh)",
            "total_renewable_generation_mwh": "LEC renewable generation (MWh)",
            "total_solar_generation_mwh": "LEC solar generation (MWh)",
            "total_wind_generation_mwh": "LEC wind generation (MWh)",
            "gross_operational_emissions_tco2eq": "Grid-import operational emissions (tCO2eq)",
            "solar_lifecycle_emissions_tco2eq": "Solar lifecycle-attributed emissions, supplementary (tCO2eq)",
            "wind_lifecycle_emissions_tco2eq": "Wind lifecycle-attributed emissions, supplementary (tCO2eq)",
            "lifecycle_adjusted_source_emissions_tco2eq": "Supplementary hybrid lifecycle-adjusted source footprint (tCO2eq)",
            "delta_vs_C_tco2eq": "Grid-import operational emissions difference vs Scenario C (tCO2eq)",
            "delta_vs_C_percent": "Grid-import operational emissions difference vs Scenario C (%)",
            "import_weighted_grid_ci_gco2eq_per_kwh": "External-grid import-weighted carbon intensity (gCO2eq/kWh)",
            "avg_bess_stored_intensity_gco2eq_per_kwh": "Average BESS SOCI (gCO2eq/kWh)",
            "avg_ev_stored_intensity_gco2eq_per_kwh": "Average EV SOCI (gCO2eq/kWh)",
            "weighted_export_attributed_intensity_gco2eq_per_kwh": "Weighted export carbon footprint intensity (gCO2eq/kWh)",
            "weighted_net_export_carbon_benefit_gco2eq_per_kwh": "Net export carbon benefit intensity (gCO2eq/kWh, + avoided / - harmful)",
        }
    )
    return dashboard


def build_final_text(
    scenario_summary: pd.DataFrame,
    export_credit_summary: pd.DataFrame,
    lifecycle_summary: pd.DataFrame,
    storage_summary: pd.DataFrame,
) -> str:
    def fmt(value, digits: int = 3) -> str:
        if pd.isna(value):
            return "n/a"
        return f"{float(value):.{digits}f}"

    scenarios = [s for s in ["A", "B", "C"] if s in scenario_summary.index]
    baseline = "C" if "C" in scenario_summary.index else scenarios[-1]

    def row_values(frame: pd.DataFrame, metric: str) -> list[str]:
        return [fmt(frame.loc[s, metric]) if s in frame.index else "n/a" for s in scenarios]

    gross = row_values(scenario_summary, "gross_operational_emissions_tco2eq")
    export_credit = row_values(export_credit_summary, "export_credit_tco2eq")
    net_credit = row_values(export_credit_summary, "net_with_export_credit_tco2eq")
    export_cf = row_values(
        storage_summary, "weighted_export_attributed_intensity_gco2eq_per_kwh"
    )
    export_benefit_cf = row_values(
        storage_summary, "weighted_net_export_carbon_benefit_gco2eq_per_kwh"
    )
    export_benefit = row_values(storage_summary, "net_export_carbon_benefit_tco2eq")
    net_attributed_balance = [
        f"{round(float(g) - float(b), 3):.3f}"
        for g, b in zip(gross, export_benefit)
    ]
    lifecycle = row_values(scenario_summary, "lifecycle_adjusted_source_emissions_tco2eq")
    delta_vs_c = row_values(scenario_summary, "delta_vs_C_tco2eq")
    delta_vs_c_pct = row_values(scenario_summary, "delta_vs_C_percent")
    lifecycle_delta_vs_c = row_values(
        scenario_summary, "lifecycle_adjusted_delta_vs_C_tco2eq"
    )
    lifecycle_pct = row_values(scenario_summary, "lifecycle_adjusted_delta_vs_C_percent")

    def row(label: str, unit: str, values: list[str]) -> str:
        cols = " | ".join(values)
        return f"| {label} | {unit} | {cols} |"

    methodology = [
        "# Final Text",
        "",
        "## Methodology",
        "This text uses three separate accounting views.",
        "1. Grid-import operational emissions: hourly imports from the external grid multiplied by hourly external-grid carbon intensity.",
        "2. Source-specific renewable lifecycle emissions: hourly LEC solar and wind generation multiplied by source-specific lifecycle factors.",
        "3. Avoided emissions vs reference-grid baseline: the difference between a reference all-grid service and the actual scenario footprint for the same LEC service boundary.",
        "4. Equation 3 is applied with a t-1 to t storage convention: discharge and export during timestep t use the SOCI carried into that timestep, charging during timestep t adds new carbon at the charging intensity, and the updated SOCI is used only from timestep t+1 onward. In explicit BESS-efficiency mode, BESS charging and delivered discharge are adjusted by eta_charge and eta_discharge while EV storage remains on the embedded-loss convention. In the update3 dataset this simpler piecewise interpretation is exact for BESS because charge and discharge do not occur in the same BESS row, but it is not exact for the aggregate EV series because some EV rows still charge and discharge simultaneously.",
        "5. Equation 4: imported energy attributed CO2-equivalent emissions = imported external-grid energy multiplied by external-grid carbon intensity.",
        "6. Equation 5: export carbon footprint = exported energy multiplied by the export carbon footprint intensity derived from the export sink allocation, while gross avoided emissions credit from exports is exported energy multiplied by displaced external-grid carbon intensity.",
        "7. Equation 6: signed net export CO2-equivalent emissions benefit = gross avoided emissions credit from exports minus export carbon footprint. Positive values mean avoided emissions; negative values mean the export was more harmful than the displaced external-grid supply.",
        "8. Net attributed CO2-equivalent carbon balance = imported energy attributed CO2-equivalent emissions minus signed net export CO2-equivalent emissions benefit.",
        "",
        "## Region's environment impact KPIs",
        "The image crop only shows the KPI labels, so the values below are taken from the exported tables in `outputs3/`.",
        "",
        "| Parameter | Unit | Scen. A | Scen. B | Scen. C |",
        "|---|---:|---:|---:|---:|",
        row(
            "Imported energy attributed CO2-equivalent emissions",
            "tCO2eq",
            gross,
        ),
        row(
            "Export carbon footprint (CO2-equivalent emissions)",
            "tCO2eq",
            row_values(storage_summary, "export_carbon_footprint_tco2eq"),
        ),
        row("Gross avoided emissions credit from exports", "tCO2eq", export_credit),
        row("Net emissions after gross export credit", "tCO2eq", net_credit),
        row("Export carbon footprint intensity", "gCO2eq/kWh", export_cf),
        row(
            "Net export CO2-equivalent emissions benefit intensity (gCO2eq/kWh, + avoided / - harmful)",
            "gCO2eq/kWh",
            export_benefit_cf,
        ),
        row(
            "Net export CO2-equivalent emissions benefit (tCO2eq, + avoided / - harmful)",
            "tCO2eq",
            export_benefit,
        ),
        row(
            "Net attributed CO2-equivalent carbon balance",
            "tCO2eq",
            net_attributed_balance,
        ),
        "",
        "## Missing Values Added For Completeness",
        "These are the supporting values needed to present the result clearly and to avoid mixing boundaries.",
        "",
        "| Parameter | Unit | Scen. A | Scen. B | Scen. C |",
        "|---|---:|---:|---:|---:|",
        row("Grid-import operational emissions difference vs Scenario C", "tCO2eq", delta_vs_c),
        row("Grid-import operational emissions difference vs Scenario C", "%", delta_vs_c_pct),
        row("Lifecycle-adjusted source footprint", "tCO2eq", lifecycle),
        row("Lifecycle-adjusted source footprint difference vs Scenario C", "tCO2eq", lifecycle_delta_vs_c),
        row("Lifecycle-adjusted source footprint difference vs Scenario C", "%", lifecycle_pct),
        "",
        "## Conclusions",
        f"Scenario {baseline} remains the operational baseline. Scenario A has the lowest gross operational emissions, while Scenario C is the highest of the three on the operational metric in the current tables.",
        "Gross export-credit values are a sensitivity case rather than the primary accounting result.",
        "Weighted export carbon footprint intensity is reported separately from the gross export-credit calculation. It represents the carbon content of the exported energy itself, not the displaced external-grid carbon intensity used for the gross avoided-emissions credit.",
        "Net export CO2-equivalent emissions benefit is reported separately from gross export credit. It equals gross avoided emissions credit from exports minus export carbon footprint, both per exported kWh and as a total exported-carbon benefit. Positive values mean the export avoided emissions; negative values mean the export was more carbon-intensive than the displaced external-grid supply.",
        "The lifecycle-adjusted source footprint is higher than the operational-only result because it adds LEC renewable lifecycle emissions to the external-grid import emissions.",
        "For a pure LCA, the external-grid factor must also be lifecycle-based. For avoided-emissions comparisons, the baseline and scenario must use the same LEC service boundary.",
    ]
    return "\n".join(methodology)


def validate_assumptions(
    data: pd.DataFrame,
    storage_summary: pd.DataFrame,
    grid_ci_boundary: str,
    renewable_ef_gco2_per_kwh: float,
    expected_hours: int = 8760,
    unallocated_carbon_tco2_threshold: float = 1.0,
    unmet_energy_mwh_threshold: float = 1.0,
) -> pd.DataFrame:
    warnings = []
    simultaneous = count_simultaneous_storage_operations(data)
    valid_hours = data.reset_index()["timestamp"].nunique()
    if grid_ci_boundary == "operational" and renewable_ef_gco2_per_kwh > 0:
        warnings.append(
            {
                "severity": "warning",
                "check": "mixed_boundary",
                "message": "Lifecycle renewable EF is combined with operational grid CI; label lifecycle-adjusted source footprint as hybrid.",
            }
        )
    if valid_hours != expected_hours:
        warnings.append(
            {
                "severity": "warning",
                "check": "time_coverage",
                "message": f"Valid hourly records are {valid_hours}, not {expected_hours}; avoid calling this a complete annual total without qualification.",
            }
        )
    warnings.append(
        {
            "severity": "info",
            "check": "net_market_exchange",
            "message": "Grid import/export are derived from net hourly market sales; simultaneous import/export cannot be tested without separate columns.",
        }
    )
    if (simultaneous["bess_simultaneous_charge_discharge_rows"] == 0).all():
        warnings.append(
            {
                "severity": "info",
                "check": "bess_mutual_exclusivity",
                "message": "BESS charge/discharge are mutually exclusive in the current dataset, so the simpler piecewise BESS SOCI interpretation is valid.",
            }
        )
    else:
        for scenario, row in simultaneous.iterrows():
            if row["bess_simultaneous_charge_discharge_rows"] > 0:
                warnings.append(
                    {
                        "severity": "warning",
                        "check": "bess_simultaneous_charge_discharge",
                        "message": (
                            f"Scenario {scenario} contains "
                            f"{int(row['bess_simultaneous_charge_discharge_rows'])} BESS rows "
                            "with simultaneous charge and discharge; the piecewise BESS SOCI rule is not exact for those rows."
                        ),
                    }
                )
    for scenario, row in simultaneous.iterrows():
        if row["ev_simultaneous_charge_discharge_rows"] > 0:
            warnings.append(
                {
                    "severity": "warning",
                    "check": "ev_simultaneous_charge_discharge",
                    "message": (
                        f"Scenario {scenario} contains "
                        f"{int(row['ev_simultaneous_charge_discharge_rows'])} EV rows "
                        "with simultaneous charge and discharge; EV storage remains on the general stock-and-flow update instead of the simpler piecewise rule."
                    ),
                }
            )
    max_balance_error = data.get(
        "renewable_source_balance_error_mwh", pd.Series([0.0])
    ).abs().max()
    if max_balance_error > 1e-3:
        warnings.append(
            {
                "severity": "warning",
                "check": "renewable_source_balance",
                "message": f"Solar plus wind differs from aggregate renewable generation by up to {max_balance_error:.6f} MWh in an hourly row.",
            }
        )
    for scenario, row in storage_summary.iterrows():
        if row.get("unmet_sink_energy_mwh", 0) > unmet_energy_mwh_threshold:
            warnings.append(
                {
                    "severity": "warning",
                    "check": "unmet_sink_energy",
                    "message": f"Scenario {scenario} has {row['unmet_sink_energy_mwh']:.3f} MWh unmet sink energy in allocation diagnostics.",
                }
            )
        if row.get("unallocated_source_carbon_tco2eq", 0) > unallocated_carbon_tco2_threshold:
            warnings.append(
                {
                    "severity": "warning",
                    "check": "unallocated_source_carbon",
                    "message": f"Scenario {scenario} has {row['unallocated_source_carbon_tco2eq']:.3f} tCO2eq unallocated source carbon in allocation diagnostics.",
                }
            )
    return pd.DataFrame(warnings)
