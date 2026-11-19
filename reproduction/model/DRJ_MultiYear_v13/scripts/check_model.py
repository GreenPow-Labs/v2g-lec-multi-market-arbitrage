# Made by Francesco Maldonato on 10/11/2026
"""Check the PLEXOS XML before loading it: structure, references, scenarios, data files, run order.

    python3 check_model.py    # checks <folder name>.xml, writes run_order.csv and model_overview.csv

Errors stop a PLEXOS load or run, or make a settlement run invalid; warnings are worth a look.
Data files that do not exist yet are listed as pending: PLEXOS solution CSVs (written by an
earlier run, see run_order.csv) and the restricted series written by preprocessing/fetch_restricted_inputs.py. The longest PLEXOS output path is reported, because Windows paths
above 259 characters send a solution to a temp folder (WARNING 3132).

Settlement models (X.2), all pins reading the model's own X.1 run, exact (unscaled RHS file):
- battery SoC = ST Battery(1).SoC.csv; V2G: EV n energy = ST Vehicle(n).Energy.csv (ENERGY_PINS), V1G: EV n
  charging = ST Vehicle(n).Charging.csv (CHARGE_PINS); the pins of the other chain off;
- the SoC limits of the battery and the EVs replaced (Min SoC 0, Max SoC 100), no SoC file pins left;
- their power ratings RATING_FACTOR x the real ones (V1G vehicles: discharge 0), the scenario at Read Order
  SETTLEMENT_READ_ORDER so that it overrides scenario V2G's discharge rating;
- the battery: no simultaneous charge and discharge, one unit;
- the charging station's limits RATING_FACTOR x the source's; grid connection 10 MW (SETTLEMENT_GRID);
Optimisation models: pins off, their own SoC limits and ratings, grid connection 2 MW.
Every model: solver Gurobi with every setting at its default; where two of its scenarios set the same property,
the one with the higher Read Order (PLEXOS: the last read scenario has the highest priority) decides, a tie is an error;
no EV coefficient PLEXOS would ignore (Energy Coefficient on a V1G vehicle, WARNING 3230), no
line with infinite limits (PLEXOS takes it out of service, WARNING 3236), 20 EUR/MWh wheeling on every line
(plexos_kpi_extract.py), report rows = REPORT.
Also checked:
- every model in MODEL_CATEGORY; the name order and the object order of the models are valid run orders (each model after
  the models whose solutions it reads), so PLEXOS can run the whole folder in one go;
- inputs: load files LOAD_FILES (forecast = Stromnetz SLP, actual = SLP with noise), RES VO&M RES_VOM, EV files EV_FILES,
  EV units BASE_UNITS (or the sweep level's), efficiencies EV_EFFICIENCY / BESS_EFFICIENCY, the battery 0.4 MWh per 0.7 MW
  of RES at 1 C (the RES and load sweeps scale it with the RES);
- Read Order: settlement scenarios SETTLEMENT_READ_ORDER, sweep sizing scenarios SIZING_READ_ORDER, all others 0;
- settlement pins: also the discharging (DISCHARGE_PINS: battery Generation, V2G EVs Discharging, Generation Coefficient 1,
  exact RHS file of the source run); simultaneous charge and discharge of the pinned objects (SETTLEMENT_SIMULTANEOUS), so
  the settlement runs are LPs, while the optimisation models keep the vehicles' binaries; battery pin coefficient 100 /
  the model's battery capacity; absent cohorts (Units 0, fleet-mix ends) have no pins;
- solver: the ST phase uses the Performance object of the model's ST Schedule (PLEXOS ignores the model-level one for it):
  optimisation models ST_SCHEDULE -> ST_PERFORMANCE with MIP gap ST_MIP_GAP[1] and MIP Start Solution ST_MIP_START[1],
  settlement models SETTLEMENT_ST -> SETTLEMENT_PERFORMANCE (presolve off, feasibility tolerance 1e-5);
- the region's VoLL and Price of Dump Energy lie beyond every price the model reads (PLEXOS bounds the LMP by them); the
  Diagnostic object prints no per-step task size or solver summary (DIAGNOSTIC_REMOVED);
- every EV can keep its SoC limits with its trips when it charges at full rate whenever connected (else the optimisation
  run would be infeasible).
model_overview.csv keeps 10 significant digits.
"""
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from make_multiyear_model import (BASE_UNITS, BESS_EFFICIENCY, CHARGE_PINS, CODES, DIAGNOSTIC_REMOVED, DIAGNOSTIC_SETTINGS, DISCHARGE_PINS,
                                  ENERGY_PINS, EV_EFFICIENCY, EV_FILES, SETTLEMENT_SIMULTANEOUS, ST_MIP_START, num,
                                  EVS, LEVELS, LOAD_FILES, LOAD_SUFFIX, MODEL_CATEGORY, PERFORMANCE, PINNED_LIMITS, PINNED_RATINGS,
                                  RATING_FACTOR, REGION, REGION_PRICE_BOUNDS, REPORT, RES_VOM, SETTLEMENT_GRID, SETTLEMENT_PERFORMANCE,
                                  SETTLEMENT_ST, ST_MIP_GAP, ST_PERFORMANCE, ST_SCHEDULE,
                                  SETTLEMENT_READ_ORDER, SIZING_READ_ORDER, STATION, SWEEP_STAGES, YEARS)

HERE = Path(__file__).resolve().parent
FOLDER = HERE.parent
XML = FOLDER / f"{FOLDER.name}.xml"
SRC = FOLDER / "source" / "base_model_2025.xml"  # the authors' 2025 base model (formerly "DR Model Journal WORKING project - 29-10-2026 - ImbalanceSettlementFix-2")
NS = "{http://tempuri.org/MasterDataSet.xsd}"
REQUIRED_COLLECTIONS = {"Horizon", "Report", "ST Schedule", "Production", "Performance", "Transmission", "Diagnostic"}
GRID_LIMIT_MW = 2.0  # DEMS-Transmission Max Flow / -Min Flow in the optimisation models
BESS_PER_RES = 0.4 / 0.7  # battery MWh (= MW) per MW of RES capacity in every model
SHARE_FILE, KM_FILE = EV_FILES["EV_ELVIS_share_CS1_8h.csv"], EV_FILES["EV_ELVIS_demand_2MWh.csv"]
LONGEST_OUTPUT = "Interval\\ST Charging Station(1).Discharge Revenue.csv"  # longest file PLEXOS writes here (REPORT)
WHEELING = 20.0  # EUR/MWh, Wheeling Charge and Wheeling Charge Back of every line (plexos_kpi_extract.py)
PINS = ENERGY_PINS + CHARGE_PINS + DISCHARGE_PINS
WINDOWS_MAX_PATH = 259

errors, warnings = [], []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def load(path):
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    tables, order = defaultdict(list), defaultdict(Counter)
    for el in ET.fromstring(text):
        t = el.tag.replace(NS, "")
        fields = [c.tag.replace(NS, "") for c in el]
        order[t][tuple(fields)] += 1
        tables[t].append({f: (c.text or "") for f, c in zip(fields, el)})
    return raw, text, tables, order


def excel_date(serial):
    return date(1899, 12, 30) + timedelta(days=int(float(serial)))


_price_range = {}


def price_range(path):
    """(min, max) of the last column of an input file (cached)."""
    if path not in _price_range:
        s = pd.read_csv(FOLDER / path, sep=";").iloc[:, -1].astype(float)
        _price_range[path] = (float(s.min()), float(s.max()))
    return _price_range[path]


def ev_reserve(year, ev, wh_km, capacity, rate, eta):
    """Smallest stored energy above the 10 % SoC floor [kWh per vehicle] of one EV object that charges at full rate on its
    connected share whenever it can (the most favourable schedule for its SoC). Negative: its trips cannot be driven within
    the SoC limits. The objects are cohorts: the share is their mean connected share (0-100 %), the energy the
    cohort's mean per vehicle."""
    d = FOLDER / "data_files" / str(year)
    share = pd.read_csv(d / SHARE_FILE, sep=";")[f"{ev}~CS1"].to_numpy(float) / 100
    drive = pd.read_csv(d / KM_FILE, sep=";")[ev].to_numpy(float) * wh_km / 1000
    e, low = 0.25 * capacity, np.inf
    for s, km in zip(share, drive):
        if s > 0 and e < 0.9 * capacity:
            e += min(s * rate * eta, 0.9 * capacity - e)
        e -= km
        low = min(low, e - 0.1 * capacity)
    return low


def main():
    raw, text, T, field_orders = load(XML)

    # --- file format
    if not raw.startswith(b"\xef\xbb\xbf"):
        err("file has no UTF-8 BOM")
    if re.search(r"(?<!\r)\n", text):
        err("file contains LF line endings without CR")
    _, _, S, src_orders = load(SRC)
    for table in ["t_category", "t_object", "t_membership", "t_data", "t_text", "t_attribute_data", "t_tag"]:
        new = set(field_orders[table]) - set(src_orders[table])
        if new:
            err(f"{table}: field order {new} not used by the source file")

    cls = {r["class_id"]: r["name"] for r in T["t_class"]}
    cid = {v: k for k, v in cls.items()}
    obj = {r["object_id"]: r for r in T["t_object"]}
    oname = {k: r["name"] for k, r in obj.items()}
    ocls = {k: cls[r["class_id"]] for k, r in obj.items()}
    coll = {r["collection_id"]: r for r in T["t_collection"]}
    props = {r["property_id"]: r for r in T["t_property"]}
    attrs = {r["attribute_id"]: r for r in T["t_attribute"]}
    cats = {r["category_id"]: r for r in T["t_category"]}
    actions = {r["action_id"] for r in T["t_action"]}

    # --- keys
    for table, key in [("t_object", "object_id"), ("t_membership", "membership_id"), ("t_data", "data_id"),
                       ("t_category", "category_id"), ("t_data", "uid")]:
        dup = [k for k, n in Counter(r[key] for r in T[table]).items() if n > 1]
        if dup:
            err(f"{table}.{key} not unique: {dup[:5]}")
    for table, keys in [("t_attribute_data", ("object_id", "attribute_id")), ("t_tag", ("data_id", "object_id")), ("t_text", ("data_id", "class_id"))]:
        dup = [k for k, n in Counter(tuple(r[k] for k in keys) for r in T[table]).items() if n > 1]
        if dup:
            err(f"{table} {keys} not unique: {dup[:5]}")
    dup = [k for k, n in Counter((r["class_id"], r["name"]) for r in T["t_object"]).items() if n > 1]
    if dup:
        err(f"object names not unique per class: {dup[:5]}")

    # --- references
    for r in T["t_object"]:
        if r["class_id"] not in cls:
            err(f"object {r['name']}: unknown class {r['class_id']}")
        c = cats.get(r["category_id"])
        if c is None or c["class_id"] != r["class_id"]:
            err(f"object {r['name']}: category {r['category_id']} missing or of another class")
    for r in T["t_category"]:
        if r["class_id"] not in cls:
            err(f"category {r['name']}: unknown class")
    dup = [k for k, n in Counter((r["class_id"], r["name"]) for r in T["t_category"]).items() if n > 1]
    if dup:
        err(f"category names not unique per class: {dup}")
    mem = {r["membership_id"]: r for r in T["t_membership"]}
    sys_count = Counter()
    for r in T["t_membership"]:
        for side in ["parent", "child"]:
            o = obj.get(r[f"{side}_object_id"])
            if o is None or o["class_id"] != r[f"{side}_class_id"]:
                err(f"membership {r['membership_id']}: {side} object/class mismatch")
        c = coll.get(r["collection_id"])
        if c is None or c["parent_class_id"] != r["parent_class_id"] or c["child_class_id"] != r["child_class_id"]:
            err(f"membership {r['membership_id']}: collection {r['collection_id']} does not join these classes")
        if r["parent_object_id"] == "1":
            sys_count[r["child_object_id"]] += 1
    for k in obj:
        if k != "1" and sys_count[k] != 1:
            err(f"object {oname[k]} ({ocls[k]}) has {sys_count[k]} System memberships")
    dup = [k for k, n in Counter((r["parent_object_id"], r["collection_id"], r["child_object_id"]) for r in T["t_membership"]).items() if n > 1]
    if dup:
        err(f"duplicate memberships: {dup[:5]}")
    data = {r["data_id"]: r for r in T["t_data"]}
    for r in T["t_data"]:
        m = mem.get(r["membership_id"])
        p = props.get(r["property_id"])
        if m is None or p is None or p["collection_id"] != m["collection_id"]:
            err(f"data {r['data_id']}: membership/property mismatch")
        try:
            float(r["value"])
        except ValueError:
            err(f"data {r['data_id']}: value '{r['value']}' is not a number")
    tags = defaultdict(list)
    for r in T["t_tag"]:
        if r["data_id"] not in data:
            err(f"tag on missing data {r['data_id']}")
        if r["object_id"] not in obj:
            err(f"tag {r['data_id']} -> missing object {r['object_id']}")
            continue
        if r.get("action_id") and r["action_id"] not in actions:
            err(f"tag {r['data_id']}: unknown action {r['action_id']}")
        tags[r["data_id"]].append(r)
    for did, ts in tags.items():
        kinds = Counter(ocls[t["object_id"]] for t in ts)
        if kinds["Scenario"] > 1 or kinds["Data File"] > 1:
            err(f"data {did}: {dict(kinds)} tags")
        bad = set(kinds) - {"Scenario", "Data File", "Variable", "Timeslice"}
        if bad:
            warn(f"data {did}: tagged with {bad}")
    texts = {}
    for r in T["t_text"]:
        d = data.get(r["data_id"])
        if d is None:
            err(f"text on missing data {r['data_id']}")
            continue
        own = obj[mem[d["membership_id"]]["child_object_id"]]["class_id"]
        if r["class_id"] != own and cls.get(r["class_id"]) != "Variable":  # Variable texts hold expressions
            err(f"text {r['data_id']}: class differs from the data's object")
        if r["class_id"] == cid["Data File"]:
            texts[r["data_id"]] = r["value"]
    # the EV data files in use (tagged on a data row) are exactly the files of EV_FILES, one per year (a swapped name is
    # caught here); the source model's unused EV data files (EV Share simple, EV1-4 charging profile MW) are not tagged
    used_files = {t["object_id"] for t in T["t_tag"]}
    ev_texts = sorted(v for d_id, v in texts.items() if v.startswith("data_files") and "EV" in re.split(r"[\\/]", v)[-1]
                      and mem[data[d_id]["membership_id"]]["child_object_id"] in used_files)
    want_ev = sorted(f"data_files/{y}/{f}" for y in [2023, 2024, 2025] for f in EV_FILES.values())
    if ev_texts != want_ev:
        err(f"EV data files {sorted(set(ev_texts) ^ set(want_ev))} differ from EV_FILES per year")
    for r in T["t_attribute_data"]:
        a = attrs.get(r["attribute_id"])
        o = obj.get(r["object_id"])
        if a is None or o is None or a["class_id"] != o["class_id"]:
            err(f"attribute_data object {r['object_id']} attribute {r['attribute_id']}: mismatch")
    attr = defaultdict(dict)
    for r in T["t_attribute_data"]:
        attr[r["object_id"]][attrs[r["attribute_id"]]["name"]] = r["value"]

    # --- data file names and locale
    df_file = {}
    for r in T["t_data"]:
        m = mem[r["membership_id"]]
        if m["parent_object_id"] == "1" and ocls[m["child_object_id"]] == "Data File" and props[r["property_id"]]["name"] == "Filename":
            df_file.setdefault(m["child_object_id"], texts.get(r["data_id"], ""))
    solution_re = re.compile(r"^Model (.+) Solution\\")
    for d, f in df_file.items():
        if solution_re.match(f) and attr[d].get("Locale") != "2057":
            err(f"data file {oname[d]} reads a solution CSV but has no Locale 2057 (ERROR 3116)")

    # --- models
    models = {k for k, c in ocls.items() if c == "Model"}
    children = defaultdict(lambda: defaultdict(list))
    for r in T["t_membership"]:
        if r["parent_object_id"] in models:
            children[r["parent_object_id"]][ocls[r["child_object_id"]]].append(r["child_object_id"])
    scen_rows = defaultdict(list)
    base_rows = defaultdict(list)
    for did, r in data.items():
        s = [t["object_id"] for t in tags[did] if ocls[t["object_id"]] == "Scenario"]
        key = (r["membership_id"], r["property_id"])
        if s:
            scen_rows[s[0]].append((key, did))
        else:
            base_rows[key].append(did)
    used_scen = set()
    deps, model_year, model_scen, pending, overview = {}, {}, {}, set(), []
    ev_reserves = {}  # (year, EV kWh, EV kW, efficiency) -> smallest reserve above the SoC floor [kWh]
    ratings = {}  # model -> {(object, rating): effective value}; optimisation runs come first in name order
    perf_cls = cid["Performance"]
    perf_defaults = {a["name"]: a["default_value"] for a in attrs.values() if a["class_id"] == perf_cls}
    for mdl in sorted(models, key=lambda k: oname[k]):
        name = oname[mdl]
        ch = children[mdl]
        for c in REQUIRED_COLLECTIONS:
            if len(ch.get(c, [])) != 1:
                err(f"model {name}: {len(ch.get(c, []))} {c} memberships")
        if not ch.get("Horizon"):
            continue
        hz = ch["Horizon"][0]
        year = excel_date(attr[hz]["Date From"]).year
        if attr[hz].get("Chrono Date From") != attr[hz]["Date From"]:
            err(f"horizon {oname[hz]}: Chrono Date From differs from Date From")
        model_year[name] = year
        scen = ch.get("Scenario", [])
        used_scen |= set(scen)
        model_scen[name] = {oname[s] for s in scen}
        active = defaultdict(list)
        for s in scen:
            for key, did in scen_rows[s]:
                active[key].append((s, did))
        read_order = lambda s: float(attr[s].get("Read Order", 0))
        for key, lst in active.items():
            owners = {s for s, _ in lst}
            if len(owners) > 1:
                top = max(map(read_order, owners))
                winners = {s for s in owners if read_order(s) == top}
                vals = {(data[d]["value"], tuple(sorted(t["object_id"] for t in tags[d] if ocls[t["object_id"]] != "Scenario")))
                        for s, d in lst if s in winners}
                if len(vals) > 1:
                    m = mem[key[0]]
                    err(f"model {name}: scenarios {sorted(oname[s] for s in winners)} both set {oname[m['child_object_id']]}.{props[key[1]]['name']}"
                        " at the same Read Order")
                active[key] = [(s, d) for s, d in lst if s in winners]  # the rows PLEXOS uses
        effective = [d for key, lst in active.items() for _, d in lst]
        effective += [d for key, ds in base_rows.items() if key not in active for d in ds]
        files = {t["object_id"] for d in effective for t in tags[d] if ocls[t["object_id"]] == "Data File"}
        deps[name] = set()
        for f in files:
            path = df_file.get(f, "")
            m = solution_re.match(path)
            if m:
                src = m.group(1)
                if src not in {oname[k] for k in models}:
                    err(f"model {name}: data file {oname[f]} reads from unknown model '{src}'")
                elif src == name:
                    err(f"model {name}: reads its own solution ({oname[f]})")
                deps[name].add(src)
                if not (FOLDER / path.replace("\\", "/")).exists():
                    pending.add(path)
                continue
            if not path:
                err(f"model {name}: data file {oname[f]} has no Filename")
                continue
            p = FOLDER / path.replace("\\", "/")
            if not p.exists():
                pending.add(path)
                continue
            first = p.open().readline()
            if first.startswith("Year"):
                lines = p.read_text().splitlines()
                y0, y1 = int(lines[1].split(";")[0]), int(lines[-1].split(";")[0])
                if not (y0 <= year <= y1):
                    err(f"model {name} ({year}): {path} covers {y0}-{y1}")
        # effective sizes and the battery flow pins
        def rows_of(obj_name, prop_name):
            keys = [k for k in set(active) | set(base_rows) if oname[mem[k[0]]["child_object_id"]] == obj_name
                    and mem[k[0]]["parent_object_id"] == "1" and props[k[1]]["name"] == prop_name]
            return [d for k in keys for d in ([d for _, d in active[k]] if k in active else base_rows[k])]

        def value(obj_name, prop_name):
            out = []
            for d in rows_of(obj_name, prop_name):
                v = float(data[d]["value"])
                for t in tags[d]:
                    if ocls[t["object_id"]] == "Variable" and t.get("action_id") == "1":
                        v *= value(oname[t["object_id"]], "Profile")[0]
                out.append(v)
            return out or [float("nan")]

        sizes = {"EVs": sum(value(ev, "Units")[0] for ev in EVS), "CS1 kW": value("CS1", "Max Charge Rate")[0],
                 "CS feeder MW": value("CS-DEMS", "Max Flow")[0], "solar MW": value("Solar capacity 0.5 MW", "Profile")[0],
                 "wind MW": value("Wind capacity 0.2 MW", "Profile")[0], "households MWh": value("Household-demand/y 350 MWh", "Profile")[0],
                 "business MWh": value("Business-demand/y 150 MWh", "Profile")[0], "battery units": value("Stationary Battery", "Units")[0]}
        # the EV and battery parameters the sweeps change, and the price files the model reads
        sizes.update({"EV kWh": value(EVS[0], "Capacity")[0], "EV charge kW": value(EVS[0], "Max Charge Rate")[0],
                      "EV discharge kW": value(EVS[0], "Max Discharge Rate")[0], "EV efficiency %": value(EVS[0], "Charge Efficiency")[0],
                      "battery MWh": value("Stationary Battery", "Capacity")[0], "battery MW": value("Stationary Battery", "Max Power")[0]})
        # units per EV object, battery efficiency; efficiencies at the referenced values; the battery sized to the RES
        sizes.update({f"EV{i} units": value(ev, "Units")[0] for i, ev in enumerate(EVS, 1)})
        sizes["battery efficiency %"] = value("Stationary Battery", "Charge Efficiency")[0]
        level = name.rsplit("_", 1)[0]
        want_units = LEVELS.get(level, {}).get("units", BASE_UNITS)
        if [sizes[f"EV{i} units"] for i in range(1, 5)] != [float(u) for u in want_units]:
            err(f"model {name}: EV units {[sizes[f'EV{i} units'] for i in range(1, 5)]}, expected {want_units}")
        if any(ocls[t["object_id"]] == "Variable" for ev in EVS for d in rows_of(ev, "Units") for t in tags[d]):
            err(f"model {name}: EV units still scaled by a Variable")
        for o, want in [(EVS[0], EV_EFFICIENCY), ("Stationary Battery", BESS_EFFICIENCY)]:
            for p in ["Charge Efficiency", "Discharge Efficiency"]:
                if len(value(o, p)) != 1 or not np.isclose(value(o, p)[0], want, rtol=0, atol=1e-6):
                    err(f"model {name}: {o} {p} {value(o, p)}, expected {want:.8g}")
        res_mw = sizes["solar MW"] + sizes["wind MW"]
        settl_run = "Imbalance settlement" in model_scen[name]  # settlement runs: battery power x RATING_FACTOR, checked below
        if not (np.isclose(sizes["battery MWh"], BESS_PER_RES * res_mw) and (settl_run or np.isclose(sizes["battery MW"], sizes["battery MWh"]))):
            err(f"model {name}: battery {sizes['battery MWh']:g} MWh / {sizes['battery MW']:g} MW for {res_mw:g} MW of RES, "
                f"expected {BESS_PER_RES:.4g} MWh per MW of RES at 1 C")
        for ev in EVS[1:]:
            for p in ["Capacity", "Charge Efficiency", "Discharge Efficiency"]:
                if value(ev, p) != value(EVS[0], p):
                    err(f"model {name}: {ev} {p} {value(ev, p)} differs from {EVS[0]}'s {value(EVS[0], p)}")
        if value(EVS[0], "Discharge Efficiency") != value(EVS[0], "Charge Efficiency"):
            err(f"model {name}: EV charge and discharge efficiency differ")
        for market, key in [("Day-Ahead energy price", "DA price file"), ("Intraday energy price", "ID price file"),
                            ("Imbalance price", "imbalance price file")]:
            pf = sorted({df_file[t["object_id"]] for d in rows_of(market, "Price") for t in tags[d] if ocls[t["object_id"]] == "Data File"})
            if len(pf) != 1:
                err(f"model {name}: {market} price read from {pf}")
            sizes[key] = pf[0] if pf else ""
        sizes["flexibility pinned to"] = ""
        settl = "Imbalance settlement" in model_scen[name]
        grid = (value(SETTLEMENT_GRID[1], "Max Flow")[0], value(SETTLEMENT_GRID[1], "Min Flow")[0])
        # the region's price bounds lie beyond every price the model reads (PLEXOS bounds the LMP by them)
        bounds = {p: value(REGION, p) for p, _ in REGION_PRICE_BOUNDS}
        if bounds != {p: [float(v)] for p, v in REGION_PRICE_BOUNDS}:
            err(f"model {name}: region price bounds {bounds}, expected {REGION_PRICE_BOUNDS}")
        lo = min(price_range(sizes[k])[0] for k in ["DA price file", "ID price file", "imbalance price file"] if sizes[k])
        hi = max(price_range(sizes[k])[1] for k in ["DA price file", "ID price file", "imbalance price file"] if sizes[k])
        if not (bounds["Price of Dump Energy"][0] < lo and bounds["VoLL"][0] > hi + 2):
            err(f"model {name}: prices {lo:g} ... {hi:g} EUR/MWh reach the region's price bounds {bounds}")
        # solver diagnostics
        for dg in ch.get("Diagnostic", []):
            dname, settings = DIAGNOSTIC_SETTINGS
            if oname[dg] != dname or any(attr[dg].get(a) != str(v) for a, v in settings):
                err(f"model {name}: Diagnostic {oname[dg]} {dict(attr[dg])}, expected {dname} with {settings}")
            if any(a in attr[dg] for a in DIAGNOSTIC_REMOVED):  # no per-step logs
                err(f"model {name}: Diagnostic {oname[dg]} prints per-step output {[a for a in DIAGNOSTIC_REMOVED if a in attr[dg]]}")
        # every EV can drive its trips within its SoC limits (full-rate charging whenever connected)
        sizes["EV reserve kWh"] = float("nan")  # optimisation runs only (a settlement run replays its source)
        if not settl:
            wh = {ev: value(ev, "Efficiency")[0] for ev in EVS}
            key = (year, sizes["EV kWh"], sizes["EV charge kW"], sizes["EV efficiency %"])
            if key not in ev_reserves:
                ev_reserves[key] = min(ev_reserve(year, ev, wh[ev], key[1], key[2], key[3] / 100) for ev in EVS)
            if ev_reserves[key] < 0:
                err(f"model {name}: an EV cannot drive its trips within 10-90 % SoC ({ev_reserves[key]:.2f} kWh short)")
            sizes["EV reserve kWh"] = ev_reserves[key]

        def pin_file(d, output):  # source model of an unscaled pin row reading ST <output>.csv, else None
            files = [df_file[t["object_id"]] for t in tags[d] if ocls[t["object_id"]] == "Data File"]
            scaled = any(ocls[t["object_id"]] == "Variable" for t in tags[d])
            ok = len(files) == 1 and not scaled and solution_re.match(files[0]) and files[0].endswith(f"ST {output}.csv")
            return solution_re.match(files[0]).group(1) if ok else None

        included = {c[0]: [float(data[d]["value"]) for d in rows_of(c[0], "Include in ST Schedule")] for c in PINS}
        v1g = "V1G" in model_scen[name]
        absent = {ev for ev, n in zip(EVS, want_units) if float(n) == 0}  # fleet-mix ends, no pins
        on = ENERGY_PINS[:1] + DISCHARGE_PINS[:1] + (CHARGE_PINS if v1g else ENERGY_PINS[1:] + DISCHARGE_PINS[1:])
        on = [c for c in on if c[2] not in absent]

        def coefficients(obj_name):  # effective (constraint, property, value) rows of an object's constraint memberships
            keys = [k for k in set(active) | set(base_rows) if oname[mem[k[0]]["parent_object_id"]] == obj_name
                    and ocls[mem[k[0]]["child_object_id"]] == "Constraint"]
            return sorted((oname[mem[k[0]]["child_object_id"]], props[k[1]]["name"], float(data[d]["value"]))
                          for k in keys for d in ([d for _, d in active[k]] if k in active else base_rows[k]))

        for i, ev in enumerate(EVS):
            want = [(CHARGE_PINS[i][0], "Load Coefficient", 1.0)] if v1g else sorted(
                [(ENERGY_PINS[i + 1][0], "Energy Coefficient", 1.0), (DISCHARGE_PINS[i + 1][0], "Generation Coefficient", 1.0)])
            if coefficients(ev) != want:
                err(f"model {name}: {ev} constraint coefficients {coefficients(ev)}, expected {want} "
                    "(PLEXOS ignores an Energy Coefficient of a vehicle without V2G, WARNING 3230)")
        # the solver of the ST phase is the Performance object of the model's ST Schedule: "Nodal" -> "Solver" (MIP gap
        # ST_MIP_GAP[1]) for optimisation models, "Nodal settlement" -> "Settlement Gurobi" ("Solver" + presolve off and
        # feasibility tolerance 1e-5) for settlement models; the model-level Performance object matches (settlement) or is
        # one of the source's, at Gurobi's defaults (optimisation)
        settl_run = "Imbalance settlement" in model_scen[name]
        st = ch.get("ST Schedule", [None])[0]
        st_perf = [r["child_object_id"] for r in T["t_membership"] if r["parent_object_id"] == st and ocls[r["child_object_id"]] == "Performance"]
        solver = next(k for k, n in oname.items() if ocls[k] == "Performance" and n == ST_PERFORMANCE)
        want_st, want_perf = (SETTLEMENT_ST, SETTLEMENT_PERFORMANCE[0]) if settl_run else (ST_SCHEDULE, ST_PERFORMANCE)
        want_attr = dict(attr[solver]) | ({a: f"{float(v):G}" for a, v in SETTLEMENT_PERFORMANCE[1]} if settl_run else {})
        if st is None or oname[st] != want_st or len(st_perf) != 1 or oname[st_perf[0]] != want_perf or dict(attr[st_perf[0]]) != want_attr:
            err(f"model {name}: ST Schedule {oname.get(st)} -> {[oname[s] for s in st_perf]}, expected {want_st} -> {want_perf} with {want_attr}")
        if float(attr[solver].get("MIP Relative Gap", perf_defaults.get("MIP Relative Gap"))) != ST_MIP_GAP[1] or attr[solver].get("SOLVER", "4") != "4":
            err(f"Performance {ST_PERFORMANCE}: MIP Relative Gap {attr[solver].get('MIP Relative Gap')}, expected {ST_MIP_GAP[1]} (Gurobi)")
        if attr[solver].get("MIP Start Solution", perf_defaults.get("MIP Start Solution")) != str(ST_MIP_START[1]):
            err(f"Performance {ST_PERFORMANCE}: MIP Start Solution {attr[solver].get('MIP Start Solution')}, expected {ST_MIP_START[1]}")
        for p in ch.get("Performance", []):
            changed = {a: v for a, v in attr[p].items() if v != perf_defaults.get(a)}
            ok = oname[p] == SETTLEMENT_PERFORMANCE[0] if settl_run else (oname[p] in (PERFORMANCE, "Default Gurobi") and not changed)
            if not ok:
                err(f"model {name}: model-level Performance {oname[p]} {changed}")
        pinned = ["Stationary Battery"] + EVS
        rated = {o: "Battery" if o == "Stationary Battery" else "Vehicle" for o in pinned} | {STATION: "Charging Station"}
        file_pins = [f"{o} {p}" for o in pinned for p in ["Min SoC", "Max SoC"]
                     if any(ocls[t["object_id"]] == "Data File" for d in rows_of(o, p) for t in tags[d])]
        # battery pin coefficient = 100 / the model's battery capacity (both sides in %)
        bat_coef = [c for c in coefficients("Stationary Battery") if c[1] == "Energy Coefficient"]
        bat_gen = [c for c in coefficients("Stationary Battery") if c[1] != "Energy Coefficient"]
        if bat_gen != [(DISCHARGE_PINS[0][0], "Generation Coefficient", 1.0)]:
            err(f"model {name}: battery discharge pin coefficients {bat_gen}, expected {DISCHARGE_PINS[0][0]} Generation Coefficient 1")
        if len(bat_coef) != 1 or not np.isclose(bat_coef[0][2], 100 / sizes["battery MWh"]):
            err(f"model {name}: battery pin coefficient {bat_coef}, expected 100 / {sizes['battery MWh']} MWh")
        if settl:
            pin_src = set()
            for c, cls_name, obj_name, output, label in on:  # stored energy and discharging (battery, V2G EVs) or charging (V1G EVs)
                rhs = rows_of(c, "RHS")
                src = pin_file(rhs[0], output) if len(rhs) == 1 else None
                if included[c] != [-1.0] or src is None:
                    err(f"model {name}: constraint {c} is not on with an exact RHS = ST {output}.csv (Include {included[c]})")
                pin_src.add(src)
            off = [c[0] for c in PINS if c not in on and included[c[0]] != [0.0]]
            if off:
                err(f"model {name}: pins of the other chain switched on: {off}")
            expected = re.sub(r"2(i?)$", r"1\1", name)
            if pin_src != {expected}:
                err(f"model {name}: flexibility pinned to {sorted(map(str, pin_src))}, expected {expected}")
            if file_pins:
                err(f"model {name}: SoC still pinned by file: {file_pins}")
            limits = {(o, p): value(o, p) for o in pinned for p, _ in PINNED_LIMITS}
            if any(v != [float(want)] for (o, p), v in limits.items() for q, want in PINNED_LIMITS if q == p):
                err(f"model {name}: SoC limits of the pinned objects not replaced by {PINNED_LIMITS}: {limits}")
            # power ratings: RATING_FACTOR x those of the source run, which a V2G discharge rating of the settlement
            # scenario only reaches if that scenario is read after scenario V2G
            flex = [s for s in scen if oname[s].endswith("Flexibility fixed")]
            if len(flex) != 1 or read_order(flex[0]) != SETTLEMENT_READ_ORDER:
                err(f"model {name}: settlement scenario {[oname[s] for s in flex]} not at Read Order {SETTLEMENT_READ_ORDER}")
            src_ratings = ratings.get(expected)
            for o, c in rated.items():
                for p in PINNED_RATINGS[c]:
                    want = RATING_FACTOR * src_ratings[(o, p)] if src_ratings else None
                    got = value(o, p)
                    if want is None or len(got) != 1 or not np.isclose(got[0], want, rtol=1e-9, atol=0):
                        err(f"model {name}: {o} {p} {got}, expected {RATING_FACTOR} x the source's = {want}")
            # the settlement uses the source's real ratings and the source's sizing (same sizing scenario)
            if src_ratings:
                sizes.update({"EV charge kW": src_ratings[(EVS[0], "Max Charge Rate")], "EV discharge kW": src_ratings[(EVS[0], "Max Discharge Rate")],
                              "battery MW": src_ratings[("Stationary Battery", "Max Power")], "CS1 kW": src_ratings[(STATION, "Max Charge Rate")]})
            # the pins fix charging and discharging; no binaries (LP)
            for o in ["Stationary Battery"] + [ev for ev in EVS if ev not in absent]:
                if value(o, "Simultaneous Charge and Discharge") != [float(SETTLEMENT_SIMULTANEOUS)]:
                    err(f"model {name}: {o} Simultaneous Charge and Discharge {value(o, 'Simultaneous Charge and Discharge')}, "
                        f"expected {SETTLEMENT_SIMULTANEOUS} (settlement LP)")
            if sizes["battery units"] != 1:
                err(f"model {name}: battery units {sizes['battery units']}, expected 1 as in the optimisation runs")
            for p in ["Max Load", "Min Charge Level", "Max Power", "Min Discharge Level"]:
                if any(ocls[t["object_id"]] == "Data File" for d in rows_of("Stationary Battery", p) for t in tags[d]):
                    err(f"model {name}: battery {p} is still read from a file")
            if rows_of("StationaryBattery", "Fixed Load") or rows_of("StationaryBattery", "Fixed Generation"):
                err(f"model {name}: battery flows are also replayed at the StationaryBattery node")
            sizes["flexibility pinned to"] = ", ".join(sorted(map(str, pin_src)))
        else:
            if any(v != [0.0] for v in included.values()):
                err(f"model {name}: settlement constraints are switched on in an optimisation run ({included})")
            ratings[name] = {(o, p): value(o, p)[0] for o, c in rated.items() for p in PINNED_RATINGS[c]}
            bad_order = [oname[s] for s in scen if read_order(s) != (SIZING_READ_ORDER if oname[s].endswith(" sizing") else 0)]
            if bad_order:
                err(f"model {name}: optimisation run with scenarios at an unexpected Read Order: {bad_order}")
            if file_pins:
                err(f"model {name}: optimisation run with SoC file pins {file_pins}")
            if any(value(ev, "Simultaneous Charge and Discharge") != [0.0] for ev in EVS):  # the optimisation keeps the binaries
                err(f"model {name}: a vehicle may charge and discharge in the same hour in an optimisation run")
        if not settl:  # sizing scenarios (sweep levels) also in the settlement runs: same Read Order rule
            pass
        elif any(read_order(s) != SIZING_READ_ORDER for s in scen if oname[s].endswith(" sizing")):
            err(f"model {name}: a sizing scenario not at Read Order {SIZING_READ_ORDER}")
        mw = SETTLEMENT_GRID[2] if settl else GRID_LIMIT_MW
        if grid != (mw, -mw) or (SETTLEMENT_GRID[0] in model_scen[name]) != settl:
            err(f"model {name}: grid connection {grid}, expected +-{mw:g} MW")
        overview.append({"model": name, "folder": cats[obj[mdl]["category_id"]]["name"], "year": year, "horizon": oname[hz],
                         **sizes, "scenarios": ", ".join(sorted(model_scen[name]))})

        # optimisation vs settlement horizon settings
        la = attr[hz].get("Look-ahead Indicator", "0")
        if settl and la == "-1":
            err(f"model {name}: settlement model with look-ahead ({oname[hz]})")
        if not settl and (la != "-1" or attr[hz].get("Look-ahead At a Time") != "4"):
            err(f"model {name}: optimisation horizon {oname[hz]} is not 3 days + 4-day look-ahead")
        if attr[hz].get("Step Type", "1") != "1" or attr[hz].get("Step Count") != "367":
            err(f"model {name}: horizon {oname[hz]} planning horizon is not 367 days")
        if attr[hz].get("Chrono Step Count") != "121" or attr[hz].get("Chrono At a Time") != "3":
            err(f"model {name}: horizon {oname[hz]} is not 121 x 3-day steps")

    # the model set: every stage per year, the SWEEP_STAGES per sweep level, nothing else (no C*, no Delivery)
    expected = {f"{y}_{c}" for y in [2025] + YEARS for c in CODES.values()} | {f"{lv}_{CODES[s]}" for lv in LEVELS for s in SWEEP_STAGES}
    names = {oname[k] for k in models}
    if names != expected:
        err(f"models: extra {sorted(names - expected)}, missing {sorted(expected - names)}")
    # scenarios no model uses: only those the source model already left unused (IGNORE)
    src_cls = {r["class_id"]: r["name"] for r in S["t_class"]}
    src_scen = {r["object_id"] for r in S["t_object"] if src_cls[r["class_id"]] == "Scenario"}
    src_used = {r["child_object_id"] for r in S["t_membership"] if src_cls[r["parent_class_id"]] == "Model"}
    for s in {k for k, c in ocls.items() if c == "Scenario"} - used_scen:
        if s not in src_scen - src_used:
            err(f"scenario {oname[s]} is used by no model")

    # settlement constraints: Energy Coefficient on their object (battery 100 / Capacity, EVs 1), '=', hard,
    # off unless a scenario switches them on
    con = {oname[k]: k for k, c in ocls.items() if c == "Constraint"}
    if set(con) != {c[0] for c in PINS}:
        err(f"constraints {sorted(con)}, expected only {[c[0] for c in PINS]}")
    capacity = [float(data[d]["value"]) for key, ds in base_rows.items() for d in ds
                if oname[mem[key[0]]["child_object_id"]] == "Stationary Battery" and props[key[1]]["name"] == "Capacity"]
    for c, cls_name, obj_name, output, label in PINS:
        if c not in con:
            continue
        coef = 100 / capacity[0] if cls_name == "Battery" else 1.0
        pin = (c, cls_name, obj_name, output, label)
        coef_prop, chain = (("Load Coefficient", ["V1G"]) if pin in CHARGE_PINS else
                            ("Generation Coefficient", ["V2G"]) if pin in DISCHARGE_PINS else ("Energy Coefficient", ["V2G"]))
        if pin in DISCHARGE_PINS:
            coef = 1.0  # MW (battery) or kW (EVs) = source file
        chain = [] if cls_name == "Battery" else chain
        lhs = [(oname[mem[d["membership_id"]]["parent_object_id"]], props[d["property_id"]]["name"], float(d["value"]),
                sorted(oname[t["object_id"]] for t in tags[d["data_id"]]))
               for d in data.values() if mem[d["membership_id"]]["child_object_id"] == con[c] and mem[d["membership_id"]]["parent_object_id"] != "1"]
        lhs = [r for r in lhs if not any(s.endswith(" sizing") for s in r[3])]  # sweep sizing levels (checked per model)
        base = {props[key[1]]["name"]: float(data[ds[0]]["value"]) for key, ds in base_rows.items()
                if mem[key[0]]["child_object_id"] == con[c] and mem[key[0]]["parent_object_id"] == "1"}
        if lhs != [(obj_name, coef_prop, coef, chain)]:
            err(f"constraint {c}: left-hand side {lhs}, expected {obj_name} {coef_prop} = {coef:g} {chain}")
        if base != {"Sense": 0, "Penalty Price": -1, "Include in ST Schedule": 0, "Include in MT Schedule": 0, "Include in LT Plan": 0}:
            err(f"constraint {c}: base rows {base}")
    # PLEXOS takes a line with infinite limits out of service ("unconstrained DC link", WARNING 3236)
    for d in data.values():
        m = mem[d["membership_id"]]
        if ocls[m["child_object_id"]] == "Line" and props[d["property_id"]]["name"] in ("Max Flow", "Min Flow") and abs(float(d["value"])) >= 1e30:
            err(f"line {oname[m['child_object_id']]} {props[d['property_id']]['name']} = {d['value']}: PLEXOS would take it out of service")

    # wheeling: plexos_kpi_extract.py prices every line flow at WHEELING, both directions
    for d in data.values():
        m = mem[d["membership_id"]]
        if ocls[m["child_object_id"]] == "Line" and props[d["property_id"]]["name"] in ("Wheeling Charge", "Wheeling Charge Back") \
                and (float(d["value"]) != WHEELING or tags[d["data_id"]]):
            err(f"line {oname[m['child_object_id']]} {props[d['property_id']]['name']} = {d['value']} {[oname[t['object_id']] for t in tags[d['data_id']]]}, "
                f"expected {WHEELING:g} for every model")
    # report rows: REPORT's properties in the ST phase, interval and year flat files, nothing else
    rprops = {r["property_id"]: r for r in T["t_property_report"]}
    rows = []
    for r in T["t_report"]:
        c = coll[rprops[r["property_id"]]["collection_id"]]
        rows.append((cls[c["parent_class_id"]], cls[c["child_class_id"]], rprops[r["property_id"]]["name"], r["phase_id"],
                     r["report_period"], r["report_summary"], r["report_statistics"], r["report_samples"], r["write_flat_files"]))
    want = sorted(("System", k, p, "4", "true", "true", "false", "false", "true") for k, ps in REPORT.items() for p in ps)
    if sorted(rows) != want:
        err(f"report rows {len(rows)} differ from REPORT: extra {sorted(set(rows) - set(want))[:4]}, missing {sorted(set(want) - set(rows))[:4]}")

    # data files no row uses (the source model's own unused ones are left alone)
    def unused(tables):
        used_objects = {r["object_id"] for r in tables["t_tag"]}
        dfc = next(r["class_id"] for r in tables["t_class"] if r["name"] == "Data File")
        return {r["name"] for r in tables["t_object"] if r["class_id"] == dfc and r["object_id"] not in used_objects}
    extra = sorted(unused(T) - unused(S))
    if extra:
        warn(f"{len(extra)} data files are used by no row: {extra[:8]}")

    # Windows path limit: PLEXOS writes Model <name> Solution\Model <name> Solution.zip and Interval\*.csv
    out_paths = {n: max(len(f"Model {n} Solution\\Model {n} Solution.zip"), len(f"Model {n} Solution\\{LONGEST_OUTPUT}"))
                 for n in (oname[k] for k in models)}
    longest = max(out_paths, key=out_paths.get)
    folder_budget = WINDOWS_MAX_PATH - out_paths[longest] - 1
    if folder_budget < 120:
        warn(f"model {longest}: output paths of {out_paths[longest]} characters leave only {folder_budget} for the project folder path")

    # sources must share the year and the sweep level of the reading model
    tagset = lambda n: {s for s in model_scen[n] if s.endswith(" sizing") or s.endswith(" inputs")}
    for name, ds in deps.items():
        for src in ds:
            if src not in model_scen:  # reported above as an unknown model
                continue
            if model_year.get(src) != model_year[name]:
                err(f"model {name} ({model_year[name]}) reads {src} ({model_year.get(src)})")
            if tagset(src) != tagset(name):
                err(f"model {name} {sorted(tagset(name))} reads {src} {sorted(tagset(src))}")

    # run order (waves of models whose inputs exist once the earlier waves ran)
    order, done = [], set()
    while len(done) < len(deps):
        wave = sorted(n for n in deps if n not in done and deps[n] <= done)
        if not wave:
            err(f"circular dependencies among {sorted(set(deps) - done)}")
            break
        order.append(wave)
        done |= set(wave)
    # one folder, run in one go. PLEXOS lists a folder's models by name; the object order is checked as well.
    for k in models:
        if cats[obj[k]["category_id"]]["name"] != MODEL_CATEGORY:
            err(f"model {oname[k]} is in folder '{cats[obj[k]['category_id']]['name']}', expected '{MODEL_CATEGORY}'")
    queues = {"name": sorted(deps), "name, case-insensitive": sorted(deps, key=str.lower),
              "object id": [oname[k] for k in sorted(models, key=int)]}
    for label, queue in queues.items():
        pos = {n: i for i, n in enumerate(queue)}
        late = [(n, src) for n in queue for src in deps.get(n, ()) if pos[src] > pos[n]]
        if late:
            err(f"run in {label} order, {len(late)} models would start before their source: {late[:4]}")
    wave_of = {n: i for i, wave in enumerate(order, 1) for n in wave}
    with open(FOLDER / "run_order.csv", "w") as f:
        f.write("queue;model;wave;year;needs\n")
        for i, n in enumerate(queues["name"], 1):
            f.write(f"{i};{n};{wave_of.get(n, '')};{model_year[n]};{', '.join(sorted(deps[n]))}\n")

    # inputs: load files (forecast = Stromnetz SLP, actual = SLP + noise) and RES VO&M
    for k, f in df_file.items():
        base = re.sub(r"^\d{4} ", "", oname[k])
        if base in LOAD_FILES and not f.endswith("/" + LOAD_FILES[base][1] + LOAD_SUFFIX):
            err(f"data file {oname[k]} reads {f}, expected {LOAD_FILES[base][1]}{LOAD_SUFFIX}")
    for var, (_, new) in RES_VOM.items():
        vals = [float(data[d]["value"]) for key, ds in base_rows.items() for d in ds if oname[mem[key[0]]["child_object_id"]] == var]
        if vals != [float(new)]:
            err(f"variable {var} = {vals}, expected {new}")

    # rows of the source model that were changed or removed (everything else is only added)
    src_text = SRC.read_bytes().decode("utf-8-sig")
    changed = Counter()
    for table in ["t_object", "t_attribute_data", "t_category", "t_membership", "t_data", "t_tag", "t_text"]:
        new_blocks = Counter(re.findall(rf"  <{table}>\r\n.*?  </{table}>\r\n", text, re.S))
        for b, n in Counter(re.findall(rf"  <{table}>\r\n.*?  </{table}>\r\n", src_text, re.S)).items():
            if new_blocks[b] < n:
                changed[table] += n - new_blocks[b]

    with open(FOLDER / "model_overview.csv", "w") as f:
        cols = list(overview[0])
        f.write(";".join(cols + ["needs"]) + "\n")
        for o in sorted(overview, key=lambda o: (o["folder"], o["model"])):
            f.write(";".join(num(o[c]) if isinstance(o[c], float) and o[c] == o[c] else str(o[c]) for c in cols) + ";"
                    + ", ".join(sorted(deps[o["model"]])) + "\n")  # 10 significant digits

    # --- report
    print(f"{XML.name}")
    print(f"  {len(models)} models, {sum(1 for c in ocls.values() if c == 'Scenario')} scenarios, "
          f"{sum(1 for c in ocls.values() if c == 'Data File')} data files, {len(T['t_data'])} property rows")
    by_year = Counter(model_year.values())
    print("  models per horizon year: " + ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items())))
    print(f"  run order: {len(order)} waves -> run_order.csv")
    print(f"  longest output path inside the folder: {out_paths[longest]} characters ({longest}); "
          f"on Windows the project folder path may have up to {folder_budget} characters")
    sol = sorted(p for p in pending if solution_re.match(p))
    inp = sorted(p for p in pending if not solution_re.match(p))
    print(f"  pending solution files (written by earlier runs): {len(sol)}")
    print(f"  pending input files: {len(inp)}" + "".join(f"\n      {p}" for p in inp))
    print("  source rows changed or removed: " + ", ".join(f"{t} {n}" for t, n in changed.items()))
    for w in warnings:
        print("  WARNING:", w)
    for e in errors:
        print("  ERROR:", e)
    print(f"  {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
