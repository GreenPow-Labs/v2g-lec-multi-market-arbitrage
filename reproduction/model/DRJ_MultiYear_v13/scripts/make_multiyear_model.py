# Made by Francesco Maldonato on 10/11/2026
"""Build the PLEXOS model of the study (DRJ_MultiYear_v13.xml) from the 2025 base model (source/base_model_2025.xml).

    python3 make_multiyear_model.py      # writes ../DRJ_MultiYear_v13.xml; then: python3 check_model.py (0 errors, 0 warnings)

Edits are applied row by row to the PLEXOS XML (MasterDataSet); untouched rows stay byte-identical (BOM, CRLF line endings).
The model file is named after its folder. The model holds 72 models in one folder, "All models (run in name order)":
- 2023, 2024, 2025: A.1, A.2, B.1, B.2, C.1, C.2 (18 models). A = V1G day-ahead, B = V2G day-ahead, C = V2G day-ahead +
  intraday (C.1 trades intraday at the ID-AEP on top of B.1's fixed day-ahead position). X.1 = optimisation with forecast
  data: 3-day steps with a 4-day look-ahead (121 steps), MIP relative gap 1e-4. X.2 = settlement: the X.1 schedule with the
  actual RES and load, every deviation settled at the imbalance price; 3-day steps without look-ahead.
- 2025 sensitivity sweeps, one factor at a time, each level a chain B.1 -> C.1 -> C.2 (54 models): EV fleet 50-400 EVs,
  RES capacity 50-150 %, consumer load with RES 50-200 %, fleet mix 0-100 % residents' EVs.
Every model reads only solutions of models whose names sort before its own, so the name order is a valid run order.

Settlement pins (exact "=" constraints, no slack or penalty): in each "* Flexibility fixed" scenario the stored energy and
the discharging of every V2G EV and of the battery equal those of the source X.1 run (V1G EVs: their charging), read from
its solution files. Stored energy and discharging fix the charging, so the settlement runs are linear programs
(simultaneous charge and discharge allowed); the ratings of the pinned assets are RATING_FACTOR times the real ones and the
grid connection is 10 MW, so that solver noise of the source run cannot make a replay infeasible. The DA and ID positions
are fixed to the source's; only the imbalance market is free.

Inputs: data_files/<year>/ (preprocessing/prepare_inputs.py, fetch_restricted_inputs.py; EV files from
preprocessing/ev_dataset/make_ev_dataset.py). Consumer load: forecast = Stromnetz Berlin's standard load profile of the year
(X.1), actual = that profile with a persistent +-20 % error (X.2). EVs: four cohorts (RC, RO, WF, WP), base mix 65 %
residents' EVs, Units 19/46/27/8, 82 kWh, 11 kW charging, 10 kW V2G, 87 % round trip (also the battery). Wheeling 20 EUR/MWh
on every line and direction, use-of-system fee 20 EUR/MWh at the charging station and the battery, market purchases at
the price + 2 EUR/MWh. Node price bounds +-15,000 EUR/MWh. Solver: Gurobi, MIP focus 2, 4 threads, no MIP start between
steps; settlement runs on their own ST schedule (presolve off, feasibility tolerance 1e-5). Report: the interval and year
flat files that the settlement pins, the checks and the post-processing read.
"""

import re
import uuid
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
FOLDER = HERE.parent
SRC = FOLDER / "source" / "base_model_2025.xml"  # the authors' 2025 base model (formerly "DR Model Journal WORKING project - 29-10-2026 - ImbalanceSettlementFix-2")
DST = FOLDER / f"{FOLDER.name}.xml"
NL = "\r\n"
LOCALE_EN_GB = 2057

# model names of the source file; the builder works with these and shortens them at the end
STAGES = {"A.1": "0-V1G_DA_DR-BG_1year", "A.2": "0-V1G_DA_DR-BG_1year_Imbalance-settl",
          "B.1": "1-V2G_DA_DR-BG_1year", "B.2": "1-V2G_DA_DR-BG_1year_Imbalance-settl",
          "C.1": "2-V2G_Intraday_DR-BG_1year", "C.2": "2-V2G_Intraday_DR-BG_1year_Imbalance-settl"}
# source models removed with the scenarios and objects only they use (intraday-only C*, delivery D)
DROPPED_MODELS = ["2-V2G_Intraday_ONLY-DR-BG_1year", "2-V2G_Intraday_ONLY-DR-BG_1year_Imbalance-settl",
                  "3-V2G_Delivery_DR-BG_1year", "3-V2G_Delivery_DR-BG_1year_Imbalance-settl"]
DROPPED = [("Scenario", "No Day-Ahead market"), ("Scenario", "Intraday-ONLY Flexibility fixed"),
           ("Scenario", "Delivery balancing"), ("Scenario", "Delivery Flexibility fixed"),
           ("Market", "Mismatch-Shortage"), ("Market", "Mismatch-Surplus")]
SWEEP_STAGES = ["B.1", "C.1", "C.2"]

# short names: <year or sweep level>_<code>; 1 = optimisation with forecast data, 2 = imbalance settlement
CODES = {"A.1": "A1", "A.2": "A2", "B.1": "B1", "B.2": "B2", "C.1": "C1", "C.2": "C2"}
STAGE_TEXT = {"A.1": "V1G, day-ahead market, forecast data",
              "A.2": "A.1 schedule with actual data, settled at the imbalance price",
              "B.1": "V2G, day-ahead market, forecast data",
              "B.2": "B.1 schedule with actual data, settled at the imbalance price",
              "C.1": "V2G, intraday market on top of the B.1 day-ahead position, forecast data",
              "C.2": "C.1 schedule with actual data, settled at the imbalance price"}

OPT_HORIZON = ("1 year - 3d-LT-3dLA", "2025 - 3d-LT-4dLA (121 steps)")
SETTL_HORIZON = ("1 year - 3d-LT-NoLA (Imbalance-settl)", "2025 - 3d-LT-NoLA (Imbalance-settl)")
OPT_MODELS = {STAGES[s] for s in ["A.1", "B.1", "C.1"]}
SETTL_MODELS = {STAGES[s] for s in ["A.2", "B.2", "C.2"]}

# scenarios whose rows read PLEXOS solution files of an earlier stage
FIXED = ["V1G-Day-Ahead market Fixed", "V1G-DA Flexibility fixed", "Day-Ahead market Fixed", "DA Flexibility fixed",
         "Intraday market Fixed", "Intraday Flexibility fixed"]
PLANNING_DAYS = 367  # planning horizon (Step Type = Day); PLEXOS needs it to cover the 121 x 3-day steps
FLEX_FIXED = ["V1G-DA Flexibility fixed", "DA Flexibility fixed", "Intraday Flexibility fixed"]
SWEEP_FIXED = ["Day-Ahead market Fixed", "Intraday market Fixed", "Intraday Flexibility fixed"]  # the FIXED scenarios of SWEEP_STAGES

# input files that change with the year (same names in data_files/<year>/, 2025 -> <year>)
YEAR_INPUTS = ["market-dayahead-prices_1H_germany-2025.csv", "market-imbalances-prices_1H_germany-2025.csv",
               "market-intraday-prices_1H_germany-2025.csv", "carbon-intensity-gCO2eq-1H_germany-2025.csv",
               "solar-profile-da_1H_germany-2025.csv", "solar-profile-ac_1H_germany-2025.csv",
               "wind-profile-da_1H_germany-2025.csv", "wind-profile-ac_1H_germany-2025.csv",
               "stromnetz_households_normalized_demand_1h_MW.csv", "stromnetz_general_business_normalized_demand_1h_MW.csv",
               "stromnetz-noise_households_normalized_demand_1h_MW.csv", "stromnetz-noise_general_business_normalized_demand_1h_MW.csv",
               "EV_ELVIS-Straub_distance_km.csv", "EV_ELVIS-Straub_share_CS1.csv"]
# EV data files: file in the source model -> file of the study (preprocessing/ev_dataset/make_ev_dataset.py)
EV_FILES = {"EV_ELVIS_demand_2MWh.csv": "EV_ELVIS-Straub_distance_km.csv", "EV_ELVIS_share_CS1_8h.csv": "EV_ELVIS-Straub_share_CS1.csv"}
MOVED_2025 = YEAR_INPUTS + ["market-dayahead-prices-seq2_1H_germany-2025.csv"]
# consumer load: data file -> (file in the source model, file of the study); forecast = Stromnetz SLP, actual = SLP + noise
LOAD_FILES = {"Forecasted-Households demand MW": ("bdew_households", "stromnetz_households"),
              "Forecasted-General Business demand MW": ("bdew_general_business", "stromnetz_general_business"),
              "Actual-Households demand MW": ("stromnetz_households", "stromnetz-noise_households"),
              "Actual-General Business demand MW": ("stromnetz_general_business", "stromnetz-noise_general_business")}
LOAD_SUFFIX = "_normalized_demand_1h_MW.csv"
# RES variable O&M [EUR/MWh] (Fraunhofer ISE 2024): Variable -> (source value, new value)
RES_VOM = {"Solar-VO-Charge [EUR/MWh]": (1, 0), "Wind-VO-Charge [EUR/MWh]": (5, 7)}
MODEL_CATEGORY = "All models (run in name order)"  # one PLEXOS folder for every model
YEARS = [2024, 2023]

EVS = ["EV 1-VW ID.5 Pro 01", "EV 2-VW ID.4 Pro 01", "EV 3-VW ID.4 GTX 01", "EV 4-VW ID.5 Pro 01"]
# settlement pins: stored energy = source file, Sense 0 (=), Penalty Price -1 (no violation allowed; the
# schema default 0 lets a constraint be violated for free). The battery's Energy Coefficient is
# 100 / Capacity, so both sides are in % (SoC file); the EVs' is 1 (kWh, Energy file).
# name, class, object, source output (ST <output>.csv), label of new data files
ENERGY_PINS = [("Settlement BESS SoC", "Battery", "Stationary Battery", "Battery(1).SoC", None)]
ENERGY_PINS += [(f"Settlement EV{i} energy", "Vehicle", ev, f"Vehicle({i}).Energy", f"EV Energy {i}") for i, ev in enumerate(EVS, 1)]
# settlement discharging = source file: battery Generation [MW], V2G EVs Discharging [kW], Generation Coefficient 1.
# With the stored energy pinned it fixes the charging, so the settlement runs need no binaries (SETTLEMENT_SIMULTANEOUS).
DISCHARGE_PINS = [("Settlement BESS discharge", "Battery", "Stationary Battery", "Battery(1).Generation", "BESS Generation")]
DISCHARGE_PINS += [(f"Settlement EV{i} discharge", "Vehicle", ev, f"Vehicle({i}).Discharging", f"EV Discharging {i}") for i, ev in enumerate(EVS, 1)]
SETTLEMENT_SIMULTANEOUS = -1  # Simultaneous Charge and Discharge of the pinned vehicles and battery allowed
# V1G settlement (V1G_PINS scenario and its year clones): EV charging = source file [kW], Load Coefficient 1
CHARGE_PINS = [(f"Settlement EV{i} charging", "Vehicle", ev, f"Vehicle({i}).Charging", f"EV Charging {i}") for i, ev in enumerate(EVS, 1)]
V1G_PINS = "V1G-DA Flexibility fixed"
PINNED_LIMITS = [("Min SoC", 0), ("Max SoC", 100)]  # replace the SoC limits of pinned objects
# power ratings of the pinned objects, x RATING_FACTOR in the settlement scenarios (V1G vehicles keep discharge 0);
# also the charging station's limits, which the replayed fleet flows can touch
PINNED_RATINGS = {"Battery": ["Max Load", "Max Power"], "Vehicle": ["Max Charge Rate", "Max Discharge Rate"],
                  "Charging Station": ["Max Charge Rate", "Max Discharge Rate"]}
STATION = "CS1"
RATING_FACTOR = 10  # above any hourly flow a 0-100 % SoC allows (EVs 82 kWh at 11/10 kW, battery 0.4 MWh at 0.4 MW)
SETTLEMENT_READ_ORDER = 2  # Scenario Read Order of the settlement scenarios (above the sweep sizing scenarios)
SIZING_READ_ORDER = 1  # sweep sizing scenarios, above scenario V2G (Read Order 0), below the settlement scenarios
# region price bounds beyond every input price (PLEXOS bounds the LMP by VoLL and Price of Dump Energy)
REGION = "Distribution BG Region"
REGION_PRICE_BOUNDS = [("VoLL", 15000), ("Price of Dump Energy", -15000)]
# Diagnostic object of every model: no per-step task size or solver summary (DIAGNOSTIC_REMOVED must stay unset)
DIAGNOSTIC_SETTINGS = ("MT - Balancing - Default", [])
DIAGNOSTIC_REMOVED = ["Task Size", "Solver Summary"]
# solver settings. PLEXOS solves the ST phase with the Performance object of the model's ST Schedule ("Nodal" ->
# "Solver": Gurobi, MIP Focus 2, 4 threads), not with the model's own Performance object ("Default" / "Default Gurobi").
# Its MIP Relative Gap is set to ST_MIP_GAP for every model, and the settlement models get their own ST Schedule (SETTLEMENT_ST, a copy of "Nodal") whose Performance object is "Solver" plus presolve off and a
# feasibility tolerance of 1e-5 (SETTLEMENT_PERFORMANCE); their model-level Performance object points to it as well.
PERFORMANCE = "Default"  # model-level Performance object of the source's models (C.1: "Default Gurobi"); not used for ST
ST_SCHEDULE, ST_PERFORMANCE = "Nodal", "Solver"
ST_MIP_GAP = (0.02, 0.0001)  # "Solver" MIP Relative Gap: source value, study value
ST_MIP_START = (2, 0)  # "Solver" MIP Start Solution: source value (within and between steps), study value (never)
SETTLEMENT_ST = "Nodal settlement"
SETTLEMENT_PERFORMANCE = ("Settlement Gurobi", [("Presolve", 0), ("Feasibility Tolerance", 1e-05)])
# units of the four vehicle objects, which are cohorts (fleet objects whose connected share is the cohort's mean):
# residents' commuter cars, residents' other cars, employees' full-day stays, employees' part-day stays. 100 EVs, 65 %
# residents (RESIDENTIAL_SHARE of make_ev_dataset.py: Straub's Berlin data-driven scenario charges 64.8 % of the energy
# of homes and workplaces at home), split in the cohorts' proportions in Straub's data (commuter cars 29.7 % of
# residents' cars, full-day stays 78.2 % of work stays): make_ev_dataset.units().
BASE_UNITS = (19, 46, 27, 8)
# charge and discharge efficiency [%], each the square root of the round trip
EV_ROUND_TRIP = 0.87  # Schram et al. 2020 (IEEE SEST), measured V2G round trip 87.0 +- 1 % at 3 x 16 A, 25-75 % SoC
BESS_ROUND_TRIP = 0.87  # as the EVs (same chain: Li-ion battery + bidirectional converter)
EV_EFFICIENCY = 100 * EV_ROUND_TRIP ** 0.5
BESS_EFFICIENCY = 100 * BESS_ROUND_TRIP ** 0.5
SOURCE_EFFICIENCY = 98  # the source model's charge and discharge efficiency of the EVs and the battery
# solution output: properties (ST phase) written to the interval and year flat files and the solution zip
REPORT = {"Battery": ["SoC", "Load", "Generation", "VO&M Cost"],
          "Charging Station": ["Charge Cost", "Discharge Revenue", "UoS Cost"],
          "Generator": ["Generation"], "Line": ["Flow"], "Market": ["Sales", "Purchases", "Net Revenue"],
          "Region": ["Load", "Battery Load", "Price"], "Vehicle": ["Energy", "Charging", "Discharging"]}
# scenario name, line, finite limit [MW], used in every settlement model
SETTLEMENT_GRID = ("Settlement grid 10 MW", "DEMS-Transmission", 10, "every settlement model")
# Base case: 100 EVs (BASE_UNITS of the four vehicle objects), 0.5 MW solar + 0.2 MW wind (80 % RES
# penetration), 350 MWh households + 150 MWh businesses per year; per EV 82 kWh, 11 kW charging, 10 kW V2G,
# 87 % round trip; stationary battery 0.4 MWh / 0.4 MW, 87 % round trip; measured prices of the year.
# Keys: units = EVs per vehicle object; res, load = factors on RES capacity, load; bess = factor on the battery's energy
# and power (= the RES factor: the battery is sized to the RES).
LEVELS = {  # units: make_ev_dataset.units(share of residents, fleet size)
    "S-EV50": {"units": (10, 22, 14, 4)},
    "S-EV75": {"units": (15, 34, 20, 6)},
    "S-EV150": {"units": (29, 69, 41, 11)},
    "S-EV200": {"units": (39, 91, 55, 15)},
    "S-EV400": {"units": (77, 183, 110, 30)},  # grid-connection saturation (the 2 MW connection binds 790 h in C.1)
    # fleet mix, 100 EVs, share of residents' cars 0 / 25 / 50 / 75 / 100 % (base 65 %). An absent cohort has Units 0
    # (PLEXOS drops the object) and its settlement pins stay off.
    "S-MIX0": {"units": (0, 0, 78, 22)},
    "S-MIX25": {"units": (7, 18, 59, 16)},
    "S-MIX50": {"units": (15, 35, 39, 11)},
    "S-MIX75": {"units": (22, 53, 20, 5)},
    "S-MIX100": {"units": (30, 70, 0, 0)},
    "S-RES40": {"res": 0.5, "bess": 0.5},
    "S-RES60": {"res": 0.75, "bess": 0.75},
    "S-RES100": {"res": 1.25, "bess": 1.25},
    "S-RES120": {"res": 1.5, "bess": 1.5},
    "S-LOAD50": {"load": 0.5, "res": 0.5, "bess": 0.5},
    "S-LOAD75": {"load": 0.75, "res": 0.75, "bess": 0.75},
    "S-LOAD150": {"load": 1.5, "res": 1.5, "bess": 1.5},
    "S-LOAD200": {"load": 2.0, "res": 2.0, "bess": 2.0},
}
# the fleet levels keep the base mix (residents' share within one car of 65 %, cohorts within one car of their
# share of the group); the mix levels keep 100 EVs
for _lv, _s in LEVELS.items():
    if "units" in _s:
        _u = _s["units"]
        if _lv.startswith("S-EV"):
            _n, _r = sum(_u), _u[0] + _u[1]
            _tol = lambda g: 1 + 0.02 * g  # rounding of the base Units' own ratios (19/65, 27/35)
            assert abs(_r - 0.65 * _n) <= 1 and abs(_u[0] - BASE_UNITS[0] / 65 * _r) <= _tol(_r), _lv
            assert abs(_u[2] - BASE_UNITS[2] / 35 * (_n - _r)) <= _tol(_n - _r), _lv
        else:
            assert _lv.startswith("S-MIX") and abs(sum(_u) - sum(BASE_UNITS)) < 1e-9 and min(_u) >= 0, _lv
SWEEP_CATEGORY = "2025 - Sensitivity"
RES_VARIABLES = ["Solar capacity 0.5 MW", "Wind capacity 0.2 MW"]
LOAD_VARIABLES = ["Household-demand/y 350 MWh", "Business-demand/y 150 MWh"]


def excel_serial(year):
    return (date(year, 1, 1) - date(1899, 12, 30)).days


def num(v):
    """A property value as written to the XML (10 significant digits, no trailing zeros)."""
    return f"{float(v):.10g}"


class Xml:
    """Row-level view of the PLEXOS XML: ElementTree for lookups, text edits for writing."""

    def __init__(self, path):
        self.text = path.read_bytes().decode("utf-8-sig")
        self.new = {t: [] for t in ["t_category", "t_object", "t_membership", "t_data", "t_tag", "t_text", "t_attribute_data"]}
        self.next, self.next_uid = {}, 0
        self.parse()
        self.removed = set()  # data_id of source rows taken out of the text
        self.removed_memberships = set()

    def parse(self):
        """(Re)read the rows from the text, before any row is added; ids of removed rows are not reused."""
        assert not any(self.new.values()), "parse() after rows were added"
        ns = "{http://tempuri.org/MasterDataSet.xsd}"
        self.rows = {}
        for el in ET.fromstring(self.text):
            self.rows.setdefault(el.tag.replace(ns, ""), []).append({c.tag.replace(ns, ""): (c.text or "") for c in el})
        ids = {t: max(int(r[k]) for r in self.rows[t]) + 1 for t, k in
               [("t_object", "object_id"), ("t_membership", "membership_id"), ("t_data", "data_id"), ("t_category", "category_id")]}
        self.next = {t: max(i, self.next.get(t, 0)) for t, i in ids.items()}
        self.next_uid = max([int(r["uid"]) + 1 for r in self.rows["t_data"]] + [self.next_uid])
        self.names = {(r["class_id"], r["name"]) for r in self.rows["t_object"]}
        self.class_of = {r["object_id"]: r["class_id"] for r in self.rows["t_object"]}

    # lookups on the source rows
    def cls(self, name):
        return next(r["class_id"] for r in self.rows["t_class"] if r["name"] == name)

    def obj(self, cls_name, name):
        c = self.cls(cls_name)
        return next(r for r in self.rows["t_object"] if r["class_id"] == c and r["name"] == name)

    def obj_by_id(self, object_id):
        return next(r for r in self.rows["t_object"] if r["object_id"] == str(object_id))

    def oid(self, cls_name, name):
        return self.obj(cls_name, name)["object_id"]

    def name_of(self, object_id):
        return next(r["name"] for r in self.rows["t_object"] if r["object_id"] == str(object_id))

    def memberships(self, **kw):
        return [r for r in self.rows["t_membership"] if all(r[k] == str(v) for k, v in kw.items())]

    def sys_membership(self, object_id):
        return next(r for r in self.memberships(parent_object_id=1, child_object_id=object_id))

    def prop(self, collection_id, name):
        return next(r["property_id"] for r in self.rows["t_property"] if r["collection_id"] == str(collection_id) and r["name"] == name)

    def attr(self, cls_name, name):
        c = self.cls(cls_name)
        return next(r["attribute_id"] for r in self.rows["t_attribute"] if r["class_id"] == c and r["name"] == name)

    def data(self, **kw):
        return [r for r in self.rows["t_data"] if all(r[k] == str(v) for k, v in kw.items())]

    def tags(self, data_id):
        return [r for r in self.rows["t_tag"] if r["data_id"] == str(data_id)]

    def tagged(self, scenario_id):
        ids = {r["data_id"] for r in self.rows["t_tag"] if r["object_id"] == str(scenario_id)}
        return [r for r in self.rows["t_data"] if r["data_id"] in ids]

    def filename(self, datafile_id):
        sysm = self.sys_membership(datafile_id)
        rows = self.data(membership_id=sysm["membership_id"], property_id=self.prop(sysm["collection_id"], "Filename"))
        texts = [r["value"] for d in rows for r in self.rows["t_text"] if r["data_id"] == d["data_id"] and r["class_id"] == self.cls("Data File")]
        return texts[0] if texts else ""

    def is_class(self, object_id, cls_name):
        return self.class_of.get(str(object_id)) == self.cls(cls_name)

    # new rows
    def _id(self, table):
        i = self.next[table]
        self.next[table] += 1
        return i

    def add_category(self, cls_name, name):
        c = self.cls(cls_name)
        ranks = [int(r["rank"]) for r in self.rows["t_category"] if r["class_id"] == c]
        ranks += [int(re.search(r"<rank>(\d+)</rank>", r).group(1)) for r in self.new["t_category"] if f"<class_id>{c}</class_id>" in r]
        cid = self._id("t_category")
        self.new["t_category"].append(row("t_category", category_id=cid, class_id=c, rank=max(ranks) + 1, name=name))
        return cid

    def add_object(self, template, name, category_id=None, description=""):
        assert (template["class_id"], name) not in self.names, f"duplicate name {name}"
        self.names.add((template["class_id"], name))
        oid = self._id("t_object")
        self.class_of[str(oid)] = template["class_id"]
        self.new["t_object"].append(row("t_object", object_id=oid, class_id=template["class_id"], name=name,
                                        category_id=category_id or template["category_id"], description=escape(description), GUID=uuid.uuid4()))
        for a in self.rows["t_attribute_data"]:
            if a["object_id"] == template["object_id"]:
                self.new["t_attribute_data"].append(row("t_attribute_data", object_id=oid, attribute_id=a["attribute_id"], value=a["value"]))
        sysm = self.sys_membership(template["object_id"])
        self.add_membership(sysm["parent_class_id"], 1, sysm["collection_id"], template["class_id"], oid)
        return oid

    def add_system_object(self, cls_name, name, description=""):
        """New object of a class with no object to copy (default '-' category, System membership)."""
        c = self.cls(cls_name)
        assert (c, name) not in self.names, f"duplicate name {name}"
        self.names.add((c, name))
        oid = self._id("t_object")
        self.class_of[str(oid)] = c
        cat = next(r["category_id"] for r in self.rows["t_category"] if r["class_id"] == c and r["rank"] == "0")
        self.new["t_object"].append(row("t_object", object_id=oid, class_id=c, name=name, category_id=cat,
                                        description=escape(description), GUID=uuid.uuid4()))
        mid = self.add_membership(self.cls("System"), 1, self.collection("System", cls_name), c, oid)
        return oid, mid

    def collection(self, parent_cls, child_cls):
        p, c = self.cls(parent_cls), self.cls(child_cls)
        return next(r["collection_id"] for r in self.rows["t_collection"] if r["parent_class_id"] == p and r["child_class_id"] == c)

    def set_new_attribute(self, oid, cls_name, attr_name, value):
        aid = self.attr(cls_name, attr_name)
        key = f"<object_id>{oid}</object_id>{NL}    <attribute_id>{aid}</attribute_id>"
        rows = [i for i, r in enumerate(self.new["t_attribute_data"]) if key in r]
        new = row("t_attribute_data", object_id=oid, attribute_id=aid, value=value)
        if rows:
            self.new["t_attribute_data"][rows[0]] = new
        else:
            self.new["t_attribute_data"].append(new)

    def add_membership(self, pcls, pobj, coll, ccls, cobj):
        mid = self._id("t_membership")
        self.new["t_membership"].append(row("t_membership", membership_id=mid, parent_class_id=pcls, parent_object_id=pobj,
                                            collection_id=coll, child_class_id=ccls, child_object_id=cobj))
        return mid

    def add_data(self, membership, prop, value, tag_objects=(), text=None, text_class=None):
        """tag_objects: object ids, or (object id, action id) pairs for Variable tags."""
        did = self._id("t_data")
        self.new["t_data"].append(row("t_data", data_id=did, membership_id=membership, property_id=prop, value=value, uid=self.next_uid))
        self.next_uid += 1
        for t in tag_objects:
            o, action = t if isinstance(t, tuple) else (t, None)
            fields = dict(data_id=did, object_id=o) if action in (None, "") else dict(data_id=did, object_id=o, action_id=action)
            self.new["t_tag"].append(row("t_tag", **fields))
        if text is not None:
            self.new["t_text"].append(row("t_text", data_id=did, class_id=text_class, value=text))
        return did

    def add_datafile(self, template_id, name, path, category_id=None, solution=True):
        """New Data File like template_id, reading path. The template's Filename tags (e.g. a x1000 Variable) are kept."""
        tpl = next(r for r in self.rows["t_object"] if r["object_id"] == str(template_id))
        oid = self.add_object(tpl, name, category_id)
        coll = self.sys_membership(template_id)["collection_id"]
        fn_prop = self.prop(coll, "Filename")
        tpl_row = self.data(membership_id=self.sys_membership(template_id)["membership_id"], property_id=fn_prop)[0]
        tags = [(t["object_id"], t.get("action_id")) for t in self.tags(tpl_row["data_id"])]
        self.add_data(self.new_membership_of(oid), fn_prop, tpl_row["value"], tags, text=path, text_class=tpl["class_id"])
        if solution:
            self.set_new_attribute(oid, "Data File", "Locale", LOCALE_EN_GB)
        return oid

    def new_membership_of(self, oid):
        for r in self.new["t_membership"]:
            if f"<child_object_id>{oid}</child_object_id>" in r and "<parent_object_id>1</parent_object_id>" in r:
                return int(re.search(r"<membership_id>(\d+)</membership_id>", r).group(1))
        raise KeyError(oid)

    # text edits on existing rows
    def replace_in_block(self, table, key, value, old, new):
        b = block(self.text, table, key, value)
        assert b.count(old) == 1, f"{table} {key}={value}: '{old}' not found once"
        self.text = self.text.replace(b, b.replace(old, new))

    def remove_data(self, data_id):
        self.text = self.text.replace(block(self.text, "t_data", "data_id", data_id), "")
        self.text = re.sub(rf"  <t_tag>\r\n    <data_id>{data_id}</data_id>\r\n.*?  </t_tag>\r\n", "", self.text, flags=re.S)
        self.text = re.sub(rf"  <t_text>\r\n    <data_id>{data_id}</data_id>\r\n.*?  </t_text>\r\n", "", self.text, flags=re.S)
        self.removed.add(str(data_id))

    def remove_datafile(self, datafile_id):
        """Delete a Data File that no row refers to any more: object, System membership, Filename row, attributes."""
        users = [t["data_id"] for t in self.rows["t_tag"] if t["object_id"] == str(datafile_id) and t["data_id"] not in self.removed]
        assert not users, f"data file {self.name_of(datafile_id)} is still used by rows {users}"
        sysm = self.sys_membership(datafile_id)
        assert self.memberships(child_object_id=datafile_id) == [sysm] and not self.memberships(parent_object_id=datafile_id)
        for d in self.data(membership_id=sysm["membership_id"]):
            self.remove_data(d["data_id"])
        self.text = self.text.replace(block(self.text, "t_membership", "membership_id", sysm["membership_id"]), "")
        self.text = self.text.replace(block(self.text, "t_object", "object_id", datafile_id), "")
        self.text = re.sub(rf"  <t_attribute_data>\r\n    <object_id>{datafile_id}</object_id>\r\n.*?  </t_attribute_data>\r\n",
                           "", self.text, flags=re.S)

    def remove_object(self, object_id):
        """Delete an object: the rows tagged with it, its memberships with their rows, its attributes, the object."""
        oid = str(object_id)
        for t in self.rows["t_tag"]:
            if t["object_id"] == oid and t["data_id"] not in self.removed:
                self.remove_data(t["data_id"])
        for m in self.rows["t_membership"]:
            if oid in (m["parent_object_id"], m["child_object_id"]) and m["membership_id"] not in self.removed_memberships:
                self.removed_memberships.add(m["membership_id"])
                for d in self.data(membership_id=m["membership_id"]):
                    if d["data_id"] not in self.removed:
                        self.remove_data(d["data_id"])
                self.text = self.text.replace(block(self.text, "t_membership", "membership_id", m["membership_id"]), "")
        self.text = re.sub(rf"  <t_attribute_data>\r\n    <object_id>{oid}</object_id>\r\n.*?  </t_attribute_data>\r\n",
                           "", self.text, flags=re.S)
        self.text = self.text.replace(block(self.text, "t_object", "object_id", oid), "")

    def write(self, path):
        for table, rows in self.new.items():
            end = self.text.rindex(f"  </{table}>{NL}") + len(f"  </{table}>{NL}")
            self.text = self.text[:end] + "".join(rows) + self.text[end:]
        path.write_bytes(b"\xef\xbb\xbf" + self.text.encode("utf-8"))


def row(table, **fields):
    body = "".join(f"    <{k}>{v}</{k}>{NL}" if v != "" else f"    <{k} />{NL}" for k, v in fields.items())
    return f"  <{table}>{NL}{body}  </{table}>{NL}"


def block(text, table, key, value):
    m = re.search(rf"  <{table}>\r\n    <{key}>{value}</{key}>\r\n.*?  </{table}>\r\n", text, re.S)
    assert m, f"{table} {key}={value} not found"
    return m.group(0)


# ---------------------------------------------------------------- 2025 base model
def drop_models(x):
    """Remove DROPPED_MODELS and the DROPPED objects (scenarios only these models use, Delivery mismatch markets),
    then the data files only their rows read, and the categories left empty."""
    model_cls = x.cls("Model")
    for cls_name, name in DROPPED:
        users = {x.name_of(m["parent_object_id"]) for m in x.memberships(child_object_id=x.oid(cls_name, name)) if m["parent_class_id"] == model_cls}
        assert users <= set(DROPPED_MODELS), f"{cls_name} {name} is used by {users - set(DROPPED_MODELS)}"
    objects = [x.obj("Model", m) for m in DROPPED_MODELS] + [x.obj(c, n) for c, n in DROPPED]
    files = {t["object_id"] for o in objects for r in x.tagged(o["object_id"]) for t in x.tags(r["data_id"]) if x.is_class(t["object_id"], "Data File")}
    for o in objects:
        x.remove_object(o["object_id"])
    files = [f for f in files if not any(t["object_id"] == f and t["data_id"] not in x.removed for t in x.rows["t_tag"])]
    cats = {o["category_id"] for o in objects} | {x.obj_by_id(f)["category_id"] for f in files}
    for f in files:
        x.remove_datafile(f)
    x.parse()
    for c in cats:
        cat = next(r for r in x.rows["t_category"] if r["category_id"] == c)
        if cat["rank"] != "0" and not any(r["category_id"] == c for r in x.rows["t_object"]):
            x.text = x.text.replace(block(x.text, "t_category", "category_id", c), "")
    x.parse()


def swap_load_files(x):
    """The forecast load data files read Stromnetz's SLP, the actual ones the SLP with noise (LOAD_FILES)."""
    for name, (old, new) in LOAD_FILES.items():
        sysm = x.sys_membership(x.oid("Data File", name))
        row = x.data(membership_id=sysm["membership_id"], property_id=x.prop(sysm["collection_id"], "Filename"))[0]
        x.replace_in_block("t_text", "data_id", row["data_id"], f"<value>data_files/{old}{LOAD_SUFFIX}</value>",
                           f"<value>data_files/{new}{LOAD_SUFFIX}</value>")
    x.parse()


def set_res_vom(x):
    """RES VO&M Charge variables at the Fraunhofer ISE values (RES_VOM)."""
    for var, (old, new) in RES_VOM.items():
        rows = x.data(membership_id=x.sys_membership(x.oid("Variable", var))["membership_id"])
        assert len(rows) == 1 and float(rows[0]["value"]) == old, f"{var}: {[r['value'] for r in rows]}"
        x.replace_in_block("t_data", "data_id", rows[0]["data_id"], f"<value>{rows[0]['value']}</value>", f"<value>{new}</value>")


def rename_horizons(x):
    la = x.attr("Horizon", "Look-ahead At a Time")
    for (old, new), users in [(OPT_HORIZON, OPT_MODELS), (SETTL_HORIZON, SETTL_MODELS)]:
        hz = x.obj("Horizon", old)
        models = {x.name_of(r["parent_object_id"]) for r in x.memberships(child_object_id=hz["object_id"]) if r["parent_class_id"] == x.cls("Model")}
        assert models == users, f"unexpected users of {old}: {models}"
        x.replace_in_block("t_object", "object_id", hz["object_id"], f"<name>{old}</name>", f"<name>{new}</name>")
    pat = f"    <object_id>{x.oid('Horizon', OPT_HORIZON[0])}</object_id>{NL}    <attribute_id>{la}</attribute_id>{NL}    <value>3</value>{NL}"
    assert x.text.count(pat) == 1, "look-ahead attribute not found"
    x.text = x.text.replace(pat, pat.replace("<value>3</value>", "<value>4</value>"))
    sc = x.attr("Horizon", "Step Count")
    for name in [OPT_HORIZON[0], SETTL_HORIZON[0]]:
        pat = f"    <object_id>{x.oid('Horizon', name)}</object_id>{NL}    <attribute_id>{sc}</attribute_id>{NL}    <value>366</value>{NL}"
        assert x.text.count(pat) == 1, f"{name}: planning Step Count 366 not found"
        x.text = x.text.replace(pat, pat.replace("<value>366</value>", f"<value>{PLANNING_DAYS}</value>"))


def add_settlement_constraints(x):
    """The constraints of ENERGY_PINS (stored energy = RHS) and CHARGE_PINS (EV charging = RHS), hard. They are
    off (Include in ST/MT/LT = No) unless a settlement scenario switches them on and sets their RHS file. An EV
    coefficient exists only in the chain that uses it: Energy Coefficient with scenario V2G, Load Coefficient
    with scenario V1G (PLEXOS ignores an Energy Coefficient of a vehicle without V2G, WARNING 3230)."""
    bm = x.sys_membership(x.oid("Battery", "Stationary Battery"))["membership_id"]
    base = lambda p: [r["value"] for r in x.data(membership_id=bm, property_id=x.prop(x.collection("System", "Battery"), p)) if not x.tags(r["data_id"])]
    assert base("Units") == ["1"], f"battery base Units should be 1, found {base('Units')}"
    capacity = float(base("Capacity")[0])
    sys_coll = x.collection("System", "Constraint")
    x.energy_constraints, x.charge_constraints, x.discharge_constraints = [], [], []
    x.pin_membership = {}  # constraint name -> membership (object -> constraint) holding its coefficient
    chains = [(ENERGY_PINS, x.energy_constraints, "Energy Coefficient", "stored energy", x.oid("Scenario", "V2G")),
              (CHARGE_PINS, x.charge_constraints, "Load Coefficient", "charging", x.oid("Scenario", "V1G")),
              (DISCHARGE_PINS, x.discharge_constraints, "Generation Coefficient", "discharging", x.oid("Scenario", "V2G"))]
    for pins, store, coef_prop, what, chain in chains:
        for name, cls_name, obj_name, output, label in pins:
            battery = cls_name == "Battery"
            if what == "stored energy":
                coef, unit = (100 / capacity, "% (Energy Coefficient = 100 / Capacity)") if battery else (1, "kWh")
            else:  # charging, discharging
                coef, unit = 1, "MW" if battery else "kW"
            oid, mid = x.add_system_object("Constraint", name, f"Settlement: {what} of {obj_name} = ST {output} of the source run [{unit}], "
                                                               "every hour (on only in the Flexibility fixed scenarios)")
            for prop, value in [("Sense", 0), ("Penalty Price", -1), ("Include in ST Schedule", 0),
                                ("Include in MT Schedule", 0), ("Include in LT Plan", 0)]:
                x.add_data(mid, x.prop(sys_coll, prop), value)
            o = x.obj(cls_name, obj_name)
            coll = x.collection(cls_name, "Constraint")
            cm = x.add_membership(o["class_id"], o["object_id"], coll, x.cls("Constraint"), oid)
            x.add_data(cm, x.prop(coll, coef_prop), f"{coef:g}", [] if battery else [chain])
            x.pin_membership[name] = cm
            store.append((mid, output, label, obj_name))


def settlement_pins(x, scenario_id, source_model, prefix, files, category_id=None, v1g=False, overrides=None, absent=()):
    """Flexibility fixed scenario_id: the battery constraint and the EV constraints of the chain on (V1G: charging,
    V2G: stored energy) with source_model's files as RHS (files: existing data files by output), the SoC limits and
    power ratings of the pinned objects and the charging station's limits replaced, no simultaneous battery
    charge/discharge, Read Order above the other scenarios (its V2G discharge ratings override scenario V2G's and the
    sweep sizing scenarios'). overrides: {(object, rating): real value} of a sweep level whose sizing changes it.
    The discharging is pinned as well (battery; V2G EVs), which with the stored energy fixes the charging, and the
    pinned objects may charge and discharge in one hour (SETTLEMENT_SIMULTANEOUS): no binaries, the settlement is an LP.
    absent: vehicles with 0 Units in this model (fleet-mix ends), which PLEXOS drops: their pins stay off."""
    tpl = x.oid("Data File", "DA Market Purchases 1")
    coll = x.collection("System", "Constraint")
    pins = x.energy_constraints[:1] + x.discharge_constraints[:1]  # battery: SoC and discharging
    pins += (x.charge_constraints if v1g else x.energy_constraints[1:] + x.discharge_constraints[1:])
    for mid, output, label, obj_name in pins:
        if obj_name in absent:
            continue
        f = files.get(output) or x.add_datafile(tpl, f"{prefix} {label}", f"Model {source_model} Solution\\interval\\ST {output}.csv", category_id)
        x.add_data(mid, x.prop(coll, "Include in ST Schedule"), -1, [scenario_id])
        x.add_data(mid, x.prop(coll, "RHS"), 0, [scenario_id, f])
    v2g = x.oid("Scenario", "V2G")
    objects = [("Battery", "Stationary Battery")] + [("Vehicle", ev) for ev in EVS] + [("Charging Station", STATION)]  # absent: rows unused
    for cls_name, obj_name in objects:
        m = x.sys_membership(x.oid(cls_name, obj_name))
        if cls_name != "Charging Station":  # no binaries: the pins fix both flows
            x.add_data(m["membership_id"], x.prop(m["collection_id"], "Simultaneous Charge and Discharge"), SETTLEMENT_SIMULTANEOUS, [scenario_id])
        if cls_name != "Charging Station":  # a station stores nothing
            for prop, value in PINNED_LIMITS:
                x.add_data(m["membership_id"], x.prop(m["collection_id"], prop), value, [scenario_id])
        for prop in PINNED_RATINGS[cls_name]:
            if prop == "Max Discharge Rate" and v1g and cls_name == "Vehicle":
                continue  # a V1G vehicle does not discharge
            real = (overrides or {}).get((obj_name, prop))
            if real is None:
                real = rating(x, m, prop, v2g if (cls_name, prop) == ("Vehicle", "Max Discharge Rate") else None)
            x.add_data(m["membership_id"], x.prop(m["collection_id"], prop), num(RATING_FACTOR * real), [scenario_id])
    x.set_new_attribute(scenario_id, "Scenario", "Read Order", SETTLEMENT_READ_ORDER)


def rating(x, membership, prop, scenario_id=None):
    """The real rating: the one row of prop on membership, untagged or tagged with scenario_id only."""
    rows = [r for r in x.data(membership_id=membership["membership_id"], property_id=x.prop(membership["collection_id"], prop))
            if [t["object_id"] for t in x.tags(r["data_id"])] == ([str(scenario_id)] if scenario_id else [])]
    assert len(rows) == 1, f"{x.name_of(membership['child_object_id'])} {prop}: {len(rows)} rows"
    return float(rows[0]["value"])


def flexibility_pins(x, scenario_id):
    """The source model's SoC file pins of scenario_id: battery and EV Min/Max SoC rows read from a file."""
    members = {x.sys_membership(x.oid(c, n))["membership_id"] for c, n in [("Battery", "Stationary Battery")] + [("Vehicle", ev) for ev in EVS]}
    pins = [r for r in x.tagged(scenario_id) if r["membership_id"] in members
            and any(x.is_class(t["object_id"], "Data File") for t in x.tags(r["data_id"]))]
    props = {p["name"] for p in x.rows["t_property"] if p["property_id"] in {r["property_id"] for r in pins}}
    assert len(pins) == 2 + 2 * len(EVS) and props == {"Min SoC", "Max SoC"}, f"scenario {scenario_id}: SoC file pins {len(pins)} on {props}"
    return pins


def battery_soc_file(x, pins):
    bat = x.sys_membership(x.oid("Battery", "Stationary Battery"))["membership_id"]
    f = {t["object_id"] for r in pins if r["membership_id"] == bat for t in x.tags(r["data_id"]) if x.is_class(t["object_id"], "Data File")}
    assert len(f) == 1 and x.filename(next(iter(f))).endswith("ST Battery(1).SoC.csv"), f
    return f.pop()


def source_model(x, datafile_id):
    m = re.match(r"Model (.+) Solution\\", x.filename(datafile_id))
    return m.group(1) if m else None


def replace_flexibility_pins(x):
    """2025 settlement scenarios: SoC file pins -> the energy constraints. The battery keeps its SoC data file
    (now the RHS of its constraint); the EV SoC data files are deleted."""
    for scen in FLEX_FIXED:
        sid = x.oid("Scenario", scen)
        pins = flexibility_pins(x, sid)
        files = {t["object_id"] for r in pins for t in x.tags(r["data_id"]) if x.is_class(t["object_id"], "Data File")}
        sources = {source_model(x, f) for f in files}
        assert len(sources) == 1, f"{scen}: SoC pins read {sources}"
        bat_file = battery_soc_file(x, pins)
        for r in pins:
            x.remove_data(r["data_id"])
        for f in files - {bat_file}:
            x.remove_datafile(f)
        settlement_pins(x, sid, sources.pop(), scen.replace(" Flexibility fixed", ""), {"Battery(1).SoC": bat_file}, v1g=scen == V1G_PINS)


def settlement_grid(x):
    """Scenario SETTLEMENT_GRID (created once): a finite limit on the grid connection."""
    if not hasattr(x, "grid_scenario"):
        name, line, mw, users = SETTLEMENT_GRID
        x.grid_scenario = x.add_object(x.obj("Scenario", "Imbalance settlement"), name,
                                       description=f"Settlement runs ({users}): {line} limit {mw} MW instead of 2 MW, "
                                                   "so the imbalance market takes every deviation of the actual RES and load")
        lm = x.sys_membership(x.oid("Line", line))
        for prop, value in [("Max Flow", mw), ("Min Flow", -mw)]:
            x.add_data(lm["membership_id"], x.prop(lm["collection_id"], prop), value, [x.grid_scenario])
    return x.grid_scenario


def lean_report(x):
    """Report rows: the REPORT properties in the ST phase (interval + year flat files); every other row removed."""
    system = x.cls("System")
    want = {}
    for r in x.rows["t_property_report"]:
        c = next(cc for cc in x.rows["t_collection"] if cc["collection_id"] == r["collection_id"])
        child = next(k["name"] for k in x.rows["t_class"] if k["class_id"] == c["child_class_id"])
        if c["parent_class_id"] == system and r["name"] in REPORT.get(child, []):
            want[r["property_id"]] = f"{child} {r['name']}"
    assert len(want) == sum(map(len, REPORT.values())), sorted(want.values())
    kept = set()
    for b in re.findall(r"  <t_report>\r\n.*?  </t_report>\r\n", x.text, re.S):
        pid, phase = (re.search(rf"<{f}>(\d+)</{f}>", b).group(1) for f in ["property_id", "phase_id"])
        new = ""
        if pid in want and phase == "4":
            new = re.sub(r"<(report_period|report_summary|write_flat_files)>\w+</", r"<\1>true</", b)
            new = re.sub(r"<(report_statistics|report_samples)>\w+</", r"<\1>false</", new)
            kept.add(pid)
        x.text = x.text.replace(b, new, 1)
    assert kept == set(want), f"no ST report row for {[want[p] for p in set(want) - kept]}"


def move_2025_inputs(x):
    for r in x.rows["t_text"]:
        name = r["value"].replace("data_files/", "", 1)
        if r["value"].startswith("data_files/") and name in MOVED_2025:
            x.replace_in_block("t_text", "data_id", r["data_id"], f"<value>{r['value']}</value>", f"<value>data_files/2025/{name}</value>")


def input_datafiles(x):
    """{data file id: file name} of the year-dependent input files."""
    out = {}
    for r in x.rows["t_object"]:
        if r["class_id"] == x.cls("Data File"):
            path = x.filename(r["object_id"])
            if path.startswith("data_files/") and path[len("data_files/"):] in YEAR_INPUTS:
                out[r["object_id"]] = path[len("data_files/"):]
    assert sorted(out.values()) == sorted(YEAR_INPUTS), sorted(set(YEAR_INPUTS) - set(out.values()))
    return out


# ---------------------------------------------------------------- cloning
class Linker:
    """Clones scenarios for a prefix ('2023', 'S-EV50'): input files swapped via input_map, solution
    files re-pointed to the renamed source models (model_map), SoC file pins replaced by the energy
    constraints."""

    def __init__(self, x, prefix, model_map, input_map=None, df_category=None, overrides=None, absent=()):
        self.x, self.prefix, self.model_map, self.input_map, self.df_category = x, prefix, model_map, input_map or {}, df_category
        self.absent = set(absent)  # vehicles with 0 Units in this level (fleet-mix ends)
        self.overrides = overrides or {}  # real ratings changed by a sweep level's sizing, for the settlement x RATING_FACTOR
        self.cache = {}

    def datafile(self, df_id):
        if df_id in self.input_map:
            return self.input_map[df_id]
        src = source_model(self.x, df_id)
        if src is None:
            return df_id
        if df_id not in self.cache:
            path = self.x.filename(df_id).replace(f"Model {src} Solution", f"Model {self.model_map[src]} Solution", 1)
            self.cache[df_id] = self.x.add_datafile(df_id, f"{self.prefix} {self.x.name_of(df_id)}", path, self.df_category)
        return self.cache[df_id]

    def scenario(self, template_name, category_id, rows=None, new_name=None):
        x = self.x
        tpl = x.obj("Scenario", template_name)
        sid = x.add_object(tpl, new_name or f"{self.prefix} {template_name}", category_id)
        pins = flexibility_pins(x, tpl["object_id"]) if template_name in FLEX_FIXED else []
        for r in rows if rows is not None else x.tagged(tpl["object_id"]):
            if r in pins:
                continue
            tags = []
            for t in x.tags(r["data_id"]):
                if t["object_id"] == tpl["object_id"]:
                    continue
                o = self.datafile(t["object_id"]) if x.is_class(t["object_id"], "Data File") else t["object_id"]
                tags.append((o, t.get("action_id")))
            x.add_data(r["membership_id"], r["property_id"], r["value"], [sid] + tags)
        if pins:
            bat_file = battery_soc_file(x, pins)
            settlement_pins(x, sid, self.model_map[source_model(x, bat_file)], f"{self.prefix} {template_name.replace(' Flexibility fixed', '')}",
                            {"Battery(1).SoC": self.datafile(bat_file)}, self.df_category, v1g=template_name == V1G_PINS,
                            overrides=self.overrides, absent=self.absent)
        return sid


def clone_model(x, template_name, new_name, swaps, extra_scenarios, category_id):
    tpl = x.obj("Model", template_name)
    mid = x.add_object(tpl, new_name, category_id)
    x.set_new_attribute(mid, "Model", "Enabled", 0)
    for r in x.memberships(child_object_id=tpl["object_id"]):  # Project -> Model
        if r["parent_object_id"] != "1":
            x.add_membership(r["parent_class_id"], r["parent_object_id"], r["collection_id"], r["child_class_id"], mid)
    scen_coll = None
    for r in x.memberships(parent_object_id=tpl["object_id"]):  # Model -> Horizon, Scenarios, ...
        child = swaps.get(r["child_object_id"], r["child_object_id"])
        x.add_membership(r["parent_class_id"], mid, r["collection_id"], r["child_class_id"], child)
        if r["child_class_id"] == x.cls("Scenario"):
            scen_coll = r["collection_id"]
    for s in extra_scenarios:
        x.add_membership(x.cls("Model"), mid, scen_coll, x.cls("Scenario"), s)
    return mid


def clone_horizon(x, template_name, new_name, year, lookahead=None):
    hid = x.add_object(x.obj("Horizon", template_name), new_name)
    for a in ["Date From", "Chrono Date From"]:
        x.set_new_attribute(hid, "Horizon", a, excel_serial(year))
    x.set_new_attribute(hid, "Horizon", "Step Count", PLANNING_DAYS)
    if lookahead is not None:
        x.set_new_attribute(hid, "Horizon", "Look-ahead At a Time", lookahead)
    return hid


# ---------------------------------------------------------------- years
def add_year(x, year, inputs):
    cat_model, cat_scen = x.model_category, x.add_category("Scenario", f"{year}")
    cat_in, cat_sol = x.add_category("Data File", f"{year} inputs"), x.add_category("Data File", f"{year} Solution files")
    swaps = {x.oid("Horizon", OPT_HORIZON[0]): clone_horizon(x, OPT_HORIZON[0], f"{year} - 3d-LT-4dLA (121 steps)", year, lookahead=4),
             x.oid("Horizon", SETTL_HORIZON[0]): clone_horizon(x, SETTL_HORIZON[0], f"{year} - 3d-LT-NoLA (Imbalance-settl)", year)}

    input_map = {}
    for df_id, name in inputs.items():
        label = re.sub(r" DE-50Hz| Copy", "", x.name_of(df_id)).replace("2025", str(year))
        label = label if str(year) in label else f"{year} {label}"
        input_map[df_id] = x.add_datafile(df_id, label, f"data_files/{year}/{name.replace('2025', str(year))}", cat_in, solution=False)

    model_map = {m: f"{year}_{m}" for m in STAGES.values()}
    link = Linker(x, str(year), model_map, input_map, cat_sol)
    untagged = [r for r in x.rows["t_data"] if r["membership_id"] not in {x.sys_membership(d)["membership_id"] for d in inputs}
                and any(t["object_id"] in inputs for t in x.tags(r["data_id"]))
                and not any(x.is_class(t["object_id"], "Scenario") for t in x.tags(r["data_id"]))]
    year_inputs = link.scenario("Forecasted data", cat_scen, rows=untagged, new_name=f"{year} inputs")
    for s in ["Forecasted data", "Actual data"] + FIXED:
        swaps[x.oid("Scenario", s)] = link.scenario(s, cat_scen)
    for m in STAGES.values():
        grid = [settlement_grid(x)] if m in SETTL_MODELS else []
        clone_model(x, m, model_map[m], performance_swap(x, m, swaps), [year_inputs] + grid, cat_model)


# ---------------------------------------------------------------- sweeps
def add_level(x, level, spec, cats):
    """One sweep level: its sizing scenario (Read Order SIZING_READ_ORDER) and its B.1 -> C.1 -> C.2 chain. The real
    ratings the sizing changes are handed to the level's settlement scenario (x RATING_FACTOR)."""
    cat_model, cat_scen, cat_sol = cats
    sizing = x.add_object(x.obj("Scenario", "Day-Ahead market Fixed"), f"{level} sizing", cat_scen)
    x.set_new_attribute(sizing, "Scenario", "Read Order", SIZING_READ_ORDER)
    overrides = {}

    def base(cls_name, obj_name, prop, scenario=None):  # the real value of the base model
        return rating(x, x.sys_membership(x.oid(cls_name, obj_name)), prop, scenario)

    def put(cls_name, obj_name, prop, value, tags=()):
        m = x.sys_membership(x.oid(cls_name, obj_name))
        x.add_data(m["membership_id"], x.prop(m["collection_id"], prop), num(value), [sizing, *tags])
        return float(num(value))

    station = {"Max Charge Rate": 1.0, "Max Discharge Rate": 1.0}  # factors on the charging station's limits
    if "units" in spec:
        for ev, base_n, n in zip(EVS, BASE_UNITS, spec["units"]):
            m = x.sys_membership(x.oid("Vehicle", ev))
            units = x.data(membership_id=m["membership_id"], property_id=x.prop(m["collection_id"], "Units"))
            assert [float(r["value"]) for r in units] == [base_n] and not x.tags(units[0]["data_id"]), (ev, units)  # v11_base
            x.add_data(m["membership_id"], x.prop(m["collection_id"], "Units"), num(n), [sizing])
        station = {p: round(sum(spec["units"]) / sum(BASE_UNITS), 9) for p in station}  # float Units (S-MIX)
    if any(f != 1.0 for f in station.values()):
        for p, f in station.items():
            overrides[(STATION, p)] = put("Charging Station", STATION, p, base("Charging Station", STATION, p) * f)
        feeder = max(station.values())
        if feeder > 1.0:  # charging-station feeder (2 MW) grows with the station; grid connection stays 2 MW
            for p in ["Max Flow", "Min Flow"]:
                put("Line", "CS-DEMS", p, base("Line", "CS-DEMS", p) * feeder)
    if "bess" in spec:  # stationary battery, energy and power (1 C); its settlement pin coefficient = 100 / capacity
        capacity = put("Battery", "Stationary Battery", "Capacity", base("Battery", "Stationary Battery", "Capacity") * spec["bess"])
        for p in ["Max Power", "Max Load"]:
            overrides[("Stationary Battery", p)] = put("Battery", "Stationary Battery", p, base("Battery", "Stationary Battery", p) * spec["bess"])
        coll = x.collection("Battery", "Constraint")
        x.add_data(x.pin_membership[ENERGY_PINS[0][0]], x.prop(coll, "Energy Coefficient"), num(100 / capacity), [sizing])
    for key, variables in [("res", RES_VARIABLES), ("load", LOAD_VARIABLES)]:
        for var in variables if key in spec else []:
            m = x.sys_membership(x.oid("Variable", var))
            v = float(x.data(membership_id=m["membership_id"])[0]["value"])
            x.add_data(m["membership_id"], x.prop(m["collection_id"], "Profile"), f"{v * spec[key]:g}", [sizing])

    model_map = {STAGES[s]: f"{level}_{STAGES[s]}" for s in SWEEP_STAGES}
    absent = [ev for ev, n in zip(EVS, spec.get("units", BASE_UNITS)) if n == 0]  # absent cohorts
    link = Linker(x, level, model_map, df_category=cat_sol, overrides=overrides, absent=absent)
    swaps = {x.oid("Scenario", s): link.scenario(s, cat_scen) for s in SWEEP_FIXED}
    for s in SWEEP_STAGES:
        grid = [settlement_grid(x)] if STAGES[s] in SETTL_MODELS else []
        clone_model(x, STAGES[s], model_map[STAGES[s]], performance_swap(x, STAGES[s], swaps), [sizing] + grid, cat_model)


# ---------------------------------------------------------------- settings of every model
def v10_settings(x):
    """Region price bounds (REGION_PRICE_BOUNDS) and the solver diagnostics (DIAGNOSTIC_SETTINGS), for every model."""
    m = x.sys_membership(x.oid("Region", REGION))
    for prop, value in REGION_PRICE_BOUNDS:
        assert not x.data(membership_id=m["membership_id"], property_id=x.prop(m["collection_id"], prop)), f"{REGION} {prop} already set"
        x.add_data(m["membership_id"], x.prop(m["collection_id"], prop), value)
    name, settings = DIAGNOSTIC_SETTINGS  # empty: no per-step task size or solver summary
    d = x.oid("Diagnostic", name)
    for a in DIAGNOSTIC_REMOVED:
        assert not any(r["object_id"] == d and r["attribute_id"] == x.attr("Diagnostic", a) for r in x.rows["t_attribute_data"]), a
    for a, v in settings:
        assert not any(r["object_id"] == d and r["attribute_id"] == x.attr("Diagnostic", a) for r in x.rows["t_attribute_data"]), a
        x.set_new_attribute(d, "Diagnostic", a, v)


# ---------------------------------------------------------------- inputs and settings
def v11_base(x):
    """Edits of source rows, before any row is added: EV data files (EV_FILES), EV units (BASE_UNITS, no Variable),
    charge and discharge efficiencies of the EVs (EV_EFFICIENCY) and the battery (BESS_EFFICIENCY)."""
    for old, new in EV_FILES.items():
        hits = [r for r in x.rows["t_text"] if r["value"] == f"data_files/{old}"]
        assert len(hits) == 1, (old, len(hits))
        x.replace_in_block("t_text", "data_id", hits[0]["data_id"], f"<value>data_files/{old}</value>", f"<value>data_files/{new}</value>")
    for ev, n in zip(EVS, BASE_UNITS):
        m = x.sys_membership(x.oid("Vehicle", ev))
        rows = x.data(membership_id=m["membership_id"], property_id=x.prop(m["collection_id"], "Units"))
        assert len(rows) == 1 and rows[0]["value"] == "1", (ev, rows)
        tags = x.tags(rows[0]["data_id"])
        assert len(tags) == 1 and x.is_class(tags[0]["object_id"], "Variable"), (ev, tags)  # 30-Units-EV / 20-Units-EV Copy
        did = rows[0]["data_id"]
        x.text = re.sub(rf"  <t_tag>\r\n    <data_id>{did}</data_id>\r\n.*?  </t_tag>\r\n", "", x.text, count=1, flags=re.S)
        x.replace_in_block("t_data", "data_id", did, "<value>1</value>", f"<value>{n}</value>")
    for cls_name, objects, value in [("Vehicle", EVS, EV_EFFICIENCY), ("Battery", ["Stationary Battery"], BESS_EFFICIENCY)]:
        for o in objects:
            m = x.sys_membership(x.oid(cls_name, o))
            for p in ["Charge Efficiency", "Discharge Efficiency"]:
                rows = x.data(membership_id=m["membership_id"], property_id=x.prop(m["collection_id"], p))
                assert len(rows) == 1 and float(rows[0]["value"]) == SOURCE_EFFICIENCY and not x.tags(rows[0]["data_id"]), (o, p, rows)
                x.replace_in_block("t_data", "data_id", rows[0]["data_id"], f"<value>{rows[0]['value']}</value>", f"<value>{num(value)}</value>")
    # the ST phase's MIP Relative Gap (Performance object of the ST Schedule, used by every model)
    solver, gap = x.oid("Performance", ST_PERFORMANCE), x.attr("Performance", "MIP Relative Gap")
    old = f"  <t_attribute_data>{NL}    <object_id>{solver}</object_id>{NL}    <attribute_id>{gap}</attribute_id>{NL}    <value>{ST_MIP_GAP[0]:g}</value>{NL}"
    assert x.text.count(old) == 1, f"{ST_PERFORMANCE}: MIP Relative Gap {ST_MIP_GAP[0]} not found once"
    x.text = x.text.replace(old, old.replace(f"<value>{ST_MIP_GAP[0]:g}</value>", f"<value>{ST_MIP_GAP[1]:g}</value>"))
    start = x.attr("Performance", "MIP Start Solution")  # no warm start from the previous step
    old = f"  <t_attribute_data>{NL}    <object_id>{solver}</object_id>{NL}    <attribute_id>{start}</attribute_id>{NL}    <value>{ST_MIP_START[0]}</value>{NL}"
    assert x.text.count(old) == 1, f"{ST_PERFORMANCE}: MIP Start Solution {ST_MIP_START[0]} not found once"
    x.text = x.text.replace(old, old.replace(f"<value>{ST_MIP_START[0]}</value>", f"<value>{ST_MIP_START[1]}</value>"))
    x.parse()


def settlement_performance(x):
    """The settlement models' solver: SETTLEMENT_PERFORMANCE, a copy of the ST phase's Performance object ST_PERFORMANCE
    (after v11_base: MIP gap ST_MIP_GAP[1]) with presolve off and a feasibility tolerance of 1e-5, attached to SETTLEMENT_ST, a
    copy of the ST Schedule ST_SCHEDULE with the same Transmission and Production objects. The 2025 settlement models
    switch their ST Schedule and their model-level Performance object here, their clones through performance_swap()."""
    name, settings = SETTLEMENT_PERFORMANCE
    x.settlement_perf = x.add_object(x.obj("Performance", ST_PERFORMANCE), name,
                                     description="settlement runs: the ST solver settings with presolve off and feasibility tolerance 1e-5")
    for a, v in settings:
        x.set_new_attribute(x.settlement_perf, "Performance", a, f"{float(v):G}")  # as PLEXOS writes it: 0, 1E-05
    st = x.oid("ST Schedule", ST_SCHEDULE)
    x.settlement_st = x.add_object(x.obj("ST Schedule", ST_SCHEDULE), SETTLEMENT_ST, description="ST phase of the settlement runs")
    for r in x.memberships(parent_object_id=st):  # Transmission, Production, Performance
        child = x.settlement_perf if r["child_class_id"] == x.cls("Performance") else r["child_object_id"]
        x.add_membership(r["parent_class_id"], x.settlement_st, r["collection_id"], r["child_class_id"], child)
    for m in SETTL_MODELS:
        for coll, old, new in [(x.collection("Model", "Performance"), x.oid("Performance", PERFORMANCE), x.settlement_perf),
                               (x.collection("Model", "ST Schedule"), st, x.settlement_st)]:
            rows = x.memberships(parent_object_id=x.oid("Model", m), collection_id=coll)
            assert len(rows) == 1 and rows[0]["child_object_id"] == old, (m, rows)
            x.replace_in_block("t_membership", "membership_id", rows[0]["membership_id"], f"<child_object_id>{old}</child_object_id>",
                               f"<child_object_id>{new}</child_object_id>")


def performance_swap(x, template_name, swaps):
    """swaps of clone_model(), plus the settlement Performance object for a settlement model (x.rows still shows the
    source's membership to PERFORMANCE)."""
    if template_name in SETTL_MODELS:
        return {**swaps, x.oid("Performance", PERFORMANCE): x.settlement_perf, x.oid("ST Schedule", ST_SCHEDULE): x.settlement_st}
    return swaps


# ---------------------------------------------------------------- short model names
def short_names():
    """{builder model name: (short name, stage)}."""
    out = {}
    for stage, m in STAGES.items():
        out[m] = (f"2025_{CODES[stage]}", stage)
        out.update({f"{year}_{m}": (f"{year}_{CODES[stage]}", stage) for year in YEARS})
        if stage in SWEEP_STAGES:
            out.update({f"{level}_{m}": (f"{level}_{CODES[stage]}", stage) for level in LEVELS})
    return out


def rename_models(x, names):
    """Short model names and descriptions; solution-file paths follow the new names."""
    model_cls = x.cls("Model")
    text = lambda stage, old: escape(f"{stage} {STAGE_TEXT[stage]} (v01 name: {old})")
    for r in x.rows["t_object"]:
        if r["class_id"] == model_cls:
            new, stage = names[r["name"]]
            x.replace_in_block("t_object", "object_id", r["object_id"], f"<name>{r['name']}</name>", f"<name>{new}</name>")
            x.replace_in_block("t_object", "object_id", r["object_id"], f"<description>{r['description']}</description>",
                               f"<description>{text(stage, r['name'])}</description>")
    for i, b in enumerate(x.new["t_object"]):
        if f"<class_id>{model_cls}</class_id>" in b:
            old = re.search(r"<name>(.*?)</name>", b).group(1)
            new, stage = names[old]
            x.new["t_object"][i] = b.replace(f"<name>{old}</name>", f"<name>{new}</name>").replace(
                "<description />", f"<description>{text(stage, old)}</description>")
    for old, (new, _) in names.items():
        a, b = f"Model {old} Solution\\", f"Model {new} Solution\\"
        x.text = x.text.replace(a, b)
        x.new["t_text"] = [t.replace(a, b) for t in x.new["t_text"]]


def main():
    x = Xml(SRC)
    drop_models(x)
    swap_load_files(x)
    v11_base(x)
    set_res_vom(x)
    v10_settings(x)
    settlement_performance(x)
    inputs = input_datafiles(x)
    rename_horizons(x)
    add_settlement_constraints(x)
    replace_flexibility_pins(x)
    lean_report(x)
    move_2025_inputs(x)
    base_cat = x.model_category = x.add_category("Model", MODEL_CATEGORY)
    for m in STAGES.values():
        o = x.obj("Model", m)
        x.replace_in_block("t_object", "object_id", o["object_id"], f"<category_id>{o['category_id']}</category_id>", f"<category_id>{base_cat}</category_id>")
        if m in SETTL_MODELS:  # the 10 MW grid connection in every settlement model
            x.add_membership(x.cls("Model"), o["object_id"], x.collection("Model", "Scenario"), x.cls("Scenario"), settlement_grid(x))
    for year in YEARS:
        add_year(x, year, inputs)
    cats = (x.model_category, x.add_category("Scenario", SWEEP_CATEGORY),
            x.add_category("Data File", f"{SWEEP_CATEGORY} - Solution files"))
    for level, spec in LEVELS.items():
        add_level(x, level, spec, cats)
    rename_models(x, short_names())
    x.write(DST)
    print(f"wrote {DST.name}: " + ", ".join(f"+{len(v)} {k}" for k, v in x.new.items()))


if __name__ == "__main__":
    main()
