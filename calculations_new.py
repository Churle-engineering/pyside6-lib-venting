import re
from tkinter import messagebox
import warnings
import math
import numpy as np
import pandas as pd
from scipy.signal import lfilter
from PySide6.QtWidgets import QMessageBox
from information import (
    BATTERY_CHEMISTRY_DATA,
    MODULES_PER_DELAY,
    CHEMICAL_PROPERTIES,
    FLAMMABLE_GASES,
    COMBINED_INPUTS,
    TEXT_INPUT_KEYS,
    CALCULATION_METHODS,
    INPUT_SCHEMA,
    TARGET_FLAM_GAS,
    get_specific_capacity,
    CO_TEMPERATURE_LFL_PARAMETER_A,
    CO_TEMPERATURE_LFL_PARAMETER_B,
    H2_TEMPERATURE_LFL_PARAMETER_A,
    H2_TEMPERATURE_LFL_PARAMETER_B,
    THC_TEMPERATURE_LFL_PARAMETER_A,
    THC_TEMPERATURE_LFL_PARAMETER_B,
)

# ============================================================================
# SHARED HELPER FUNCTIONS
# ============================================================================

def strip_unit_suffix(name):
    """Strip unit suffix like _(%), _(s), _(ah), etc. from normalized name."""
    return re.sub(r'_\([^)]*\)$', '', name)

def is_string_field(label):
    label_l = str(label).lower()
    return any(kw in label_l for kw in ["description", "name", "location", "battery room", "manufacturer", "lib type"])

# ============================================================================
# covert input data to useable format
# ============================================================================

def is_missing(value):
    """
    Returns True for values that should be treated as missing input.
    Handles None, '', np.nan, and string 'nan'.
    """
    if value is None:
        return True

    if isinstance(value, str):
        return value.strip() == "" or value.strip().lower() == "nan"

    try:
        return bool(np.isnan(value))
    except TypeError:
        return False


def clean_string(value, default=""):
    """
    Cleans string/categorical inputs.
    """
    if is_missing(value):
        return default

    return str(value).strip()


def clean_float(value, default=np.nan):
    """
    Converts values to float.
    Handles strings, blanks, None and np.nan.
    """
    if is_missing(value):
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def scenario_rows_to_list(scenario_data):
    """
    Converts scenario_data into a normal list of rows.

    Works for:
    - normal ndarray object arrays
    - structured NumPy arrays
    - list of tuples
    """
    arr = np.asarray(scenario_data)

    if arr.dtype.names is not None:
        # Structured array case
        rows = []
        for row in arr:
            rows.append(tuple(row[name] for name in arr.dtype.names))
        return rows

    if arr.ndim == 1:
        # Often an array of tuples/records
        return list(arr)

    if arr.ndim == 2:
        return arr.tolist()

    raise ValueError(f"Unsupported scenario_data shape: {arr.shape}")


def scenario_data_to_records(
    scenario_data,
    combined_inputs,
    text_keys=None,
    default_lib_type="NMC",
):
    """
    Converts raw scenario_data rows into:

        names = ["scenario 1", "scenario 2", ...]
        inputs = [
            {"scenario_name": "scenario 1", "lib_type": "NMC", ...},
            {"scenario_name": "scenario 2", "lib_type": "LFP", ...},
        ]

    This is the bridge between QTableWidget/NumPy saved data and vectorised calculations.
    """
    if text_keys is None:
        text_keys = {"scenario_name", "lib_type"}

    rows = scenario_rows_to_list(scenario_data)

    records = []

    for row_idx, row in enumerate(rows):
        if len(row) != len(combined_inputs):
            raise ValueError(
                f"Row {row_idx} has {len(row)} values, but COMBINED_INPUTS has "
                f"{len(combined_inputs)} keys.\n"
                f"Row: {row}"
            )

        record = {}

        for key, value in zip(combined_inputs, row):
            if key in text_keys:
                record[key] = clean_string(value)
            else:
                record[key] = clean_float(value)

        # Fallbacks
        if not record.get("scenario_name"):
            record["scenario_name"] = f"scenario {row_idx + 1}"

        if not record.get("lib_type"):
            record["lib_type"] = default_lib_type

        records.append(record)

    names = [record["scenario_name"] for record in records]

    return names, records


# ============================================================================
# misc functions for parsing and normalizing scenario rows
# ============================================================================

# INSTEAD OF GETTING INPUTS MANUALLY IN FUNCTION

def get_float_array(records, key, default=np.nan):
    """
    Extracts one numeric column from records as a float NumPy array.
    """
    return np.array(
        [clean_float(record.get(key), default=default) for record in records],
        dtype=float,
    )


def get_string_array(records, key, default=""):
    """
    Extracts one string/categorical column from records.
    """
    return np.array(
        [clean_string(record.get(key), default=default) for record in records],
        dtype=object,
    )
    
    
def get_float_arrays(records, keys, default=np.nan):
    """
    Returns a dictionary of numeric arrays.

    Example:
        arrs = get_float_arrays(inputs, ["room_height", "room_area"])
        room_height = arrs["room_height"]
    """
    return {
        key: get_float_array(records, key, default=default)
        for key in keys
    }


def validate_required_numeric(arrays, required_keys):
    """
    Raises a clear error if any required numeric input contains nan.
    """
    errors = []

    for key in required_keys:
        values = arrays[key]
        bad_rows = np.where(np.isnan(values))[0]

        if len(bad_rows) > 0:
            scenario_nums = [int(i + 1) for i in bad_rows]
            errors.append(f"{key}: missing in scenario rows {scenario_nums}")

    if errors:
        raise ValueError(
            "Missing required numeric inputs:\n" + "\n".join(errors)
        )


def _value_from_row(row, column_name, default=None):
    """Fetch a value from a scenario row supporting dict/pandas/numpy record rows."""
    if row is None:
        return default

    if isinstance(row, dict):
        return row.get(column_name, default)

    if hasattr(row, "get"):
        try:
            return row.get(column_name, default)
        except Exception:
            pass

    if hasattr(row, "dtype") and getattr(row.dtype, "names", None):
        if column_name in row.dtype.names:
            return row[column_name]

    return default


def iter_scenarios(scenario_data):
    """Yield (scenario_name, inputs_dict) for every non-empty scenario.

    Accepts:
      - None                      -> yields nothing
      - dict                      -> single scenario ("Scenario 1")
      - numpy structured array    -> one scenario per row
      - list/tuple/ndarray of rows-> one scenario per row
    """
    if scenario_data is None:
        return

    # Single dict -> one scenario
    if isinstance(scenario_data, dict):
        if _row_has_any_input(scenario_data):
            yield "Scenario 1", _normalize_row(scenario_data)
        return

    # Iterable of rows
    for idx, row in enumerate(scenario_data, start=1):
        if not _row_has_any_input(row):
            continue

        inputs = _normalize_row(row)

        # Prefer a user-supplied name column if present, else auto-number
        name = inputs.get("scenario_name") or f"Scenario {idx}"
        yield name, inputs


# ---- helpers kept private so the public surface is just iter_scenarios ----

def _row_has_any_input(row):
    """True if at least one schema column has a non-missing value."""
    for _, (column_name, _, _) in INPUT_SCHEMA.items():
        if not _is_missing(_value_from_row(row, column_name, None)):
            return True
    return False


def _normalize_row(row):
    """Row -> canonical inputs dict, with casts, defaults, and legacy aliases."""
    inputs = {}
    for var_name, (column_name, cast, default) in INPUT_SCHEMA.items():
        raw = _value_from_row(row, column_name, default)
        if _is_missing(raw):
            inputs[var_name] = default
            continue
        try:
            inputs[var_name] = cast(raw)
        except (TypeError, ValueError):
            inputs[var_name] = default

    # Backward-compatible aliases
    inputs["total_duration"]    = inputs.get("calc_duration", 0)
    inputs["propagation_delay"] = inputs.get("mod_prop_delay", 0)
    inputs["total_modules"]     = inputs.get("modules", 0) * inputs.get("units", 0)
    inputs["cells_per"]         = inputs.get("cells", 0)
    inputs["module_capacity"]   = inputs.get("mod_capacity", 0)
    inputs["lib_type"]          = str(inputs.get("lib_type") or "NMC").upper()
    return inputs



def setup_emergency_ventilation(vent_switch_conc, emergency_vent_rate, room_area):
    """Return adjusted emergency ventilation rate and activation flag."""
    adj_emergency_vent_rate = (emergency_vent_rate / 1000) * room_area if emergency_vent_rate > 0 else 0
    emergency_vent_enabled = (vent_switch_conc > 0 and emergency_vent_rate > 0)
    return adj_emergency_vent_rate, emergency_vent_enabled

def determine_calc_method(state, user_selected_method=None):
    """Return the selected calculation method in a UI-agnostic way."""
    if user_selected_method is not None:
        return user_selected_method

    method_combo = getattr(state, "method_combo", None)
    if method_combo is not None and hasattr(method_combo, "currentText"):
        return method_combo.currentText()

    return CALCULATION_METHODS[0]


def active_modules_arr(scenario_data, modules_per_step=2, initial_active=1):
    """
    Number of modules actively venting at each time step.

    Ramp rule
    ---------
    - At t = 0, `initial_active` module(s) begin venting (the initiating module).
    - Every `propagation_delay` seconds after t = 0, an additional
      `modules_per_step` modules join the venting cascade.
    - The count is clipped at `total_modules` once all modules are venting.

    Parameters
    ----------
    scenario_data : dict
        Canonical inputs dict from `_normalize_row`. Must provide
        `total_modules` (or `modules` * `units`), `propagation_delay`,
        `time_step`, and `total_duration`.
    modules_per_step : int, default 2
        Number of modules that join venting at each propagation interval.
    initial_active : int, default 1
        Number of modules already venting at t = 0.

    Returns
    -------
    np.ndarray, shape (num_steps,)
        Active module count at each simulated time step.
    """
    total_modules     = int(scenario_data["total_modules"])
    propagation_delay = float(scenario_data["propagation_delay"])
    time_step         = float(scenario_data["time_step"])
    total_duration    = float(scenario_data["total_duration"])

    if total_modules <= 0 or time_step <= 0:
        return np.zeros(1, dtype=int)

    num_steps = int(total_duration // time_step) + 1
    time = np.arange(num_steps) * time_step                    # shape (num_steps,)

    # Degenerate case: no propagation delay -> all modules venting immediately
    if propagation_delay <= 0:
        return np.full(num_steps, total_modules, dtype=int)

    # Number of completed propagation intervals elapsed at each step
    intervals_elapsed = np.floor(time / propagation_delay).astype(int)

    # Ramp: initial + per-interval addition, clipped at total
    active = initial_active + intervals_elapsed * modules_per_step
    active = np.clip(active, 0, total_modules)

    return active.astype(int)


def resolve_target_gas_index(gas_labels, state):
    """
    Map the user-selected trigger gas to its index in `gas_labels`.

    Parameters
    ----------
    gas_labels : list[str]
        Ordered gas labels used by the calculation (per-scenario valid_gas_labels
        or the batched union axis).
    state : object
        Calc state carrying the UI widgets. Expected to expose
        `state.target_gas_combo` (QComboBox) with the user's selection.

    Returns
    -------
    (name, index) : tuple[str, int]
        name  : canonical label used for logging / print statements
        index : position in `gas_labels`, or `TARGET_TOTAL` (-1) meaning
                "sum all gases for the trigger check"
    """
    # 1. Read the user's selection (defensive against missing widget)
    selected = ""
    combo = getattr(state, "target_gas_combo", None)
    if combo is not None:
        selected = combo.currentText().strip()

    # 2. Empty selection or explicit "Total" -> use summed concentration
    if not selected or selected.lower() in {"total", "all", "sum"}:
        return "Total", -1 #target total

    # 3. Try exact match first (fast path)
    if selected in gas_labels:
        return selected, gas_labels.index(selected)

    # 4. Fall back to normalized match ("Carbon Monoxide" == "carbon_monoxide" == "CO"
    #    if you map aliases in CHEMICAL_PROPERTIES)
    target_key = _normalize_key(selected)
    for i, lbl in enumerate(gas_labels):
        if _normalize_key(lbl) == target_key:
            return lbl, i

    # 5. Optional alias resolution via CHEMICAL_PROPERTIES
    #    e.g. selected = "Carbon Monoxide" -> CHEMICAL_PROPERTIES["co"]["aliases"] contains it
    for i, lbl in enumerate(gas_labels):
        aliases = CHEMICAL_PROPERTIES.get(_normalize_key(lbl), {}).get("aliases", [])
        if target_key in {_normalize_key(a) for a in aliases}:
            return lbl, i

    # 6. Not found in this scenario's gas list -> fall back to total
    #    (calc code already handles -1 as "sum all gases")
    return "Total", -1


def calc_mod_vol(scenario_data):
    """
    Calculate the total volume of active modules based on the number of modules and their individual volumes.
    """
    
    
    total_modules = scenario_data.get("total_modules", scenario_data.get("modules", 0) * scenario_data.get("units", 0))
    cell_volume = scenario_data.get("cell_volume", 0)
    module_volume = scenario_data.get("module_volume", 0)
    
    if scenario_data.get("calc_method") == "Cell Volume UL9540A":
        total_volume = total_modules * cell_volume
    else:
        total_volume = total_modules * module_volume
    return total_volume

def density(scenario_data):
# i want to get a numpy array of densities for each gas used in a given calculation.
    densities = []
    chemistry = BATTERY_CHEMISTRY_DATA.get(str(scenario_data.get("lib_type", "")).upper(), {})
    tox_comp = chemistry.get("tox_gas_composition", {})
    for gas in tox_comp.keys():
        gas_props = CHEMICAL_PROPERTIES.get(str(gas).lower(), {})
        if "density" in gas_props:
            densities.append(gas_props["density"])

    flammable_comp = chemistry.get("flammable_gas_composition", {})
    for gas in flammable_comp.keys():
        gas_props = CHEMICAL_PROPERTIES.get(str(gas).lower(), {})
        if "density" in gas_props:
            densities.append(gas_props["density"])

    for gas, properties in scenario_data.get("gases", {}).items():
        if "density" in properties:
            densities.append(properties["density"])
    return np.array(densities)


def _normalize_key(label: str) -> str:
    """Normalize a gas label to match CHEMICAL_PROPERTIES keys."""
    return label.strip().lower().replace(" ", "_")

# ============================================================================
# Calculations
# ============================================================================

def toxic_calc(state, scenario_data):
    # --- clear existing resutls
    tox_scenario_results = state.tox_scenario_results
    tox_scenario_results.clear()

    
    names, inputs = scenario_data_to_records(
        scenario_data=scenario_data,
        combined_inputs=COMBINED_INPUTS,
        text_keys=TEXT_INPUT_KEYS,
    )

    if not inputs:
        return

    S = len(inputs)

    # ---- build the union gas axis ------
    union_labels = []
    
    for i in inputs:
        chem = BATTERY_CHEMISTRY_DATA.get(i["lib_type"], BATTERY_CHEMISTRY_DATA["NMC"])
        for lbl in chem["tox_gas_composition"]:
            key = _normalize_key(lbl)
            if (key in CHEMICAL_PROPERTIES
                    and CHEMICAL_PROPERTIES[key].get("erpg-3", 0)
                    and lbl not in union_labels):
                union_labels.append(lbl)
    G = len(union_labels)

    # densities: shape (G,)
    densities = np.array(
        [CHEMICAL_PROPERTIES[_normalize_key(lbl)].get("density", 0) or 0
         for lbl in union_labels],
        dtype=float,
    )

    # gas_percents: shape (S, G)  — 0 where a scenario's chemistry lacks that gas
    gas_percents = np.zeros((S, G))
    for s_idx, i in enumerate(inputs):
        chem = BATTERY_CHEMISTRY_DATA.get(i["lib_type"], BATTERY_CHEMISTRY_DATA["NMC"])
        comp = chem["tox_gas_composition"]
        for g_idx, lbl in enumerate(union_labels):
            if lbl in comp:
                gas_percents[s_idx, g_idx] = float(comp[lbl]) / 100.0

    # ---------- 2. Per-scenario scalars as (S,) arrays ----------
    method_text = state.method_combo.currentText()

    def _pick(inputs, key_cell, key_mod, key_capacity):
        # Returns (vol_arr, bat_duration_arr) based on global method
        vols = np.array([i[key_cell] if key_cell else i[key_capacity]
                         for i in inputs], dtype=float)
        durs = np.array([i[key_mod] for i in inputs], dtype=float)
        return vols, durs

    if method_text == CALCULATION_METHODS["Cell Volume UL9540A"]:
        vol = np.array([i["cell_volume"] * i["cells_per"] for i in inputs], dtype=float)
        bat_duration = np.array([i["cell_duration"] for i in inputs], dtype=float)
        calc_method = "Cell Volume UL9540A"
    elif method_text == CALCULATION_METHODS["Module Volume UL9540A"]:
        vol = np.array([i["module_volume"] for i in inputs], dtype=float)
        bat_duration = np.array([i["module_duration"] for i in inputs], dtype=float)
        calc_method = "Module Volume UL9540A"
    elif method_text == CALCULATION_METHODS["Module Capacity"]:
        vol = np.array([i["module_capacity"] for i in inputs], dtype=float)
        bat_duration = np.array([i["module_duration"] for i in inputs], dtype=float)
        calc_method = "Module Capacity"
    else:
        raise ValueError(f"Unknown calculation method: {method_text}")

    # get input data and convert to numpy arrays for vectorized calculations
    numeric_keys = TEXT_INPUT_KEYS - {"scenario_description", "lib_type"}
    arrays = get_float_arrays(inputs, numeric_keys)

    room_height  = arrays["room_height"]
    room_area    = arrays["room_area"]
    equip_space  = arrays["equip_space"]
    modules      = arrays["modules"]
    units        = arrays["units"]
    vent_rate    = arrays["ventilation_rate"]
    prop_delay   = arrays["propagation_delay"]
    vent_switch  = arrays["vent_switch_conc"]
    emerg_rate   = arrays["emergency_vent_rate"]

    room_vol     = room_height * room_area * (1 - equip_space / 100.0)   # (S,)
    total_mods   = modules * units                                       # (S,)
    mod_flowrate = vol / bat_duration                                    # (S,)
    k_vent       = (vent_rate / 1000.0)                                  # (S,) — per-vol rate
    k_vent_emerg = (emerg_rate / 1000.0)                                 # (S,)

    # ---------- 3. Time grid (assumes shared dt/duration) ----------
    dt = float(inputs[0]["time_step"])
    T  = int(inputs[0]["total_duration"] // dt) + 1
    time = np.arange(0, T) * dt

    # active_modules: shape (S, T)  — vectorize your existing helper
    active_modules = np.stack(
        [active_modules_arr({
            "total_modules": total_mods[s],
            "propagation_delay": prop_delay[s],
            "time_step": dt,
            "total_duration": inputs[0]["total_duration"]
        })
         for s in range(S)],
        axis=0,
    )

    # ---------- 4. Batched recurrence ----------
    gases          = np.zeros((S, G))                # running mass
    concentrations = np.zeros((S, G, T))             # v/v % * 100 (i.e. filled at end)
    k_vent_now     = k_vent.copy()                   # (S,) — flips on emergency
    emerg_active   = np.zeros(S, dtype=bool)
    emerg_enabled  = (emerg_rate > 0) & (vent_switch > 0)

    # per-scenario target gas index into the UNION axis
    target_idx = np.array(
        [resolve_target_gas_index(union_labels, state)[1] for _ in range(S)]
    )   # or compute properly if it varies per scenario

    for t in range(T):
        inflow_total = active_modules[:, t] * mod_flowrate            # (S,)
        inflows  = inflow_total[:, None] * gas_percents               # (S, G)
        outflows = k_vent_now[:, None] * gases                        # (S, G)

        gases = np.maximum(gases + (inflows - outflows) * dt, 0.0)

        current_conc = (gases / room_vol[:, None]) * 100.0            # (S, G) v/v %
        concentrations[:, :, t] = current_conc

        # Emergency vent: vectorized state flip
        if np.any(emerg_enabled & ~emerg_active):
            trigger = current_conc[np.arange(S), target_idx]          # (S,)
            newly_active = emerg_enabled & ~emerg_active & (trigger > vent_switch)
            if np.any(newly_active):
                emerg_active |= newly_active
                k_vent_now[newly_active] = k_vent_emerg[newly_active]

    # ---------- 5. Build result DataFrames per scenario ----------
    ppm_all = concentrations * 10_000                                 # v/v% -> ppm
    mgl_all = (concentrations / 100.0) * densities[None, :, None] * 1000.0

    for s_idx, name in enumerate(names):
        vv_data  = {"Time (s)": time}
        mgl_data = {"Time (s)": time}
        for g_idx, lbl in enumerate(union_labels):
            if gas_percents[s_idx, g_idx] == 0:
                continue                                              # skip gases not in this chem
            vv_data[f"{lbl} (v/v%)"]  = concentrations[s_idx, g_idx, :]
            mgl_data[f"{lbl} (mg/L)"] = mgl_all[s_idx, g_idx, :]

        vv_df  = pd.DataFrame(vv_data)
        mgl_df = pd.DataFrame(mgl_data)
        vv_df["Total Gas (ppm)"]  = vv_df.iloc[:, 1:].sum(axis=1) * 10_000 / 100  # or sum ppm columns
        mgl_df["Total Gas (mg/L)"] = mgl_df.iloc[:, 1:].sum(axis=1)

        tox_scenario_results[name] = {
            "tox_vv_df":  vv_df,
            "tox_mgl_df": mgl_df,
            "tox_max_mod": int(np.max(active_modules[s_idx])),
            "calc_method": calc_method,
            "input": inputs[s_idx],
        }












def std_flam_calc(state, scenario_data):
    # Placeholder for standard flammability calculation logic
    # Implement the actual calculation based on state
    pass

def vari_flowrate_flam_calc(state, scenario_data):
    # Placeholder for variable flowrate flammability calculation logic
    # Implement the actual calculation based on state
    
    if not hasattr(state, 'gas_flowrate_data') or state.gas_flowrate_data is None:
        QMessageBox.warning(None, "Missing Data", "Gas flowrate data has not been imported.\nPlease use the 'Import Flowrate Data' button first.")
        return
    
    # --- setup pre loop ---
    flam_gas_labels = ["co", "h2", "thc"]
    num_gases = len(flam_gas_labels)
    flowrate_matrix = np.array([state.gas_flowrate_data[label] for label in flam_gas_labels])
    mod_duration = flowrate_matrix.shape[1]
    combined_flam_flowrates = flowrate_matrix.sum(axis=0)
    flam_scenario_results = state.flam_scenario_results
    flam_scenario_results.clear()
    
    scenarios = parse_scenario_rows(state)
    
    for scenario_name, data in scenarios:
        try:
            #insert method for retieveing scenario data from scenario_data state object
                        # Le Chatelier's LFL option
            use_le_chatelier = state.use_le_chatelier_lfl.get() if hasattr(state, 'use_le_chatelier_lfl') else False
            use_temp_dependent_lfl = state.use_temp_dependent_lfl.get() if hasattr(state, 'use_temp_dependent_lfl') else False
            
                        # Individual LFL values (% v/v)
            individual_lfls = np.zeros(3)
            for idx, flam_label in enumerate(["co", "h2", "total_hydrocarbons"]):
                lfl_val = CHEMICAL_PROPERTIES.get(flam_label, {}).get("lfl", 0)
                individual_lfls[idx] = lfl_val if lfl_val and lfl_val > 0 else 0
    
            # Temperature-dependent LFL adjustment
            if use_temp_dependent_lfl and use_le_chatelier:
                venting_temp = float(data.get("venting_temperature_(°c)", 0))
                if venting_temp > 0:
                    temp_lfls = [
                        CO_TEMPERATURE_LFL_PARAMETER_A * venting_temp + CO_TEMPERATURE_LFL_PARAMETER_B,
                        H2_TEMPERATURE_LFL_PARAMETER_A * venting_temp + H2_TEMPERATURE_LFL_PARAMETER_B,
                        THC_TEMPERATURE_LFL_PARAMETER_A * venting_temp + THC_TEMPERATURE_LFL_PARAMETER_B,
                    ]
                    for idx, temp_lfl in enumerate(temp_lfls):
                        if temp_lfl > 0:
                            individual_lfls[idx] = temp_lfl
                    print(f"Temperature-dependent LFL (T={venting_temp}°C): CO={individual_lfls[0]:.4f}%, H2={individual_lfls[1]:.4f}%, THC={individual_lfls[2]:.4f}%")

            if use_le_chatelier:
                print(f"Le Chatelier's LFL enabled. Individual LFLs: CO={individual_lfls[0]}, H2={individual_lfls[1]}, THC={individual_lfls[2]}")

            # Validate critical inputs
            if room_height == 0 or room_area == 0:
                print(f"An input is zero when it shouldn't be. RH:{room_height} m, RA:{room_area} m2")
                return pd.DataFrame(), pd.DataFrame(), {}
            
                        # Pre-allocate arrays
            num_steps = (total_duration // time_step) + 1
            vv_concentrations = np.zeros((num_gases, num_steps))
            mgl_concentrations = np.zeros((num_gases, num_steps))
            gases = np.zeros(num_gases)
            prev_gas = np.zeros(num_gases)
            time = np.arange(0, total_duration + 1, time_step)

            # Derived parameters
            room_vol = (room_height * room_area) * (1 - (equip_space / 100))
            total_mods = int(modules * units)
            adj_ventilation_rate = (ventilation_rate / 1000) * room_area
            adj_emergency_vent_rate, emergency_vent_enabled = setup_emergency_ventilation(vent_switch_conc, emergency_vent_rate, room_area)
            emergency_vent_activated = False
            total_vent_outflow = adj_ventilation_rate / room_vol

            # Cache gas densities
            densities = np.array([gas_data.get(label, {}).get("density", 0) or 0 for label in gas_labels])
            
                        # Pre-compute module group start times for staggered propagation
            module_groups = []
            if total_mods > 0:
                if propagation_delay == 0:
                    module_groups.append((1, total_mods))
                else:
                    remaining = total_mods
                    module_groups.append((1, 1))
                    remaining -= 1
                    delay_count = 1
                    while remaining > 0:
                        start_time = int(delay_count * propagation_delay)
                        count = min(MODULES_PER_DELAY, remaining)
                        module_groups.append((start_time, count))
                        remaining -= count
                        delay_count += 1

            # Resolve target gas for emergency ventilation
            target_gas_map = {"CO": 0, "H2": 1, "Total Hydrocarbons": 2}
            selected_target = state.selected_target_flam_gas.get() if hasattr(state, 'selected_target_flam_gas') else "CO"
            target_gas_index = target_gas_map.get(selected_target, 0)

            # === Pre-compute total inflow matrix for all timesteps (vectorized per group) ===
            total_inflows_matrix = np.zeros((num_gases, num_steps))
            for group_start, group_count in module_groups:
                valid_mask = (time >= group_start) & ((time - group_start) < mod_duration)
                local_times = (time[valid_mask] - group_start).astype(np.intp)
                total_inflows_matrix[:, valid_mask] += group_count * flowrate_matrix[:, local_times]

            # === Calculation loop using pre-computed inflows ===
            for step_idx in range(num_steps):
                inflows = total_inflows_matrix[:, step_idx]
                outflows = total_vent_outflow * prev_gas

                gases += (inflows - outflows) * time_step
                gases = np.maximum(gases, 0)
                prev_gas[:] = gases

                current_conc = (gases / room_vol) * 100
                vv_concentrations[:, step_idx] = current_conc
                mgl_concentrations[:, step_idx] = (current_conc / 100) * densities * 1000

                # Emergency ventilation check
                if emergency_vent_enabled and not emergency_vent_activated:
                    if current_conc[target_gas_index] >= vent_switch_conc:
                        emergency_vent_activated = True
                        total_vent_outflow = adj_emergency_vent_rate / room_vol
                        print(f"⚠️ Emergency ventilation ACTIVATED at t={time[step_idx]}s ({current_conc[target_gas_index]:.4f}% >= {vent_switch_conc}%)")

            # === Build result DataFrames ===
            flam_result_vv_df = pd.DataFrame({"Time (s)": time})
            flam_result_mgl_df = pd.DataFrame({"Time (s)": time})
            for i, label in enumerate(gas_labels):
                flam_result_vv_df[f"{label} (v/v%)"] = vv_concentrations[i, :]
                flam_result_mgl_df[f"{label} (mg/L)"] = mgl_concentrations[i, :]

            flam_result_vv_df["Total Gas (v/v%)"] = vv_concentrations[0, :] + vv_concentrations[1, :] + vv_concentrations[2, :]
            flam_result_mgl_df["Total Gas (mg/L)"] = mgl_concentrations[0, :] + mgl_concentrations[1, :] + mgl_concentrations[2, :]

    # === Le Chatelier's LFL calculation (vectorized) ===
            adjusted_le_chatelier_lfl = None
            if use_le_chatelier:
                conc_flam = vv_concentrations[:3, :]
                total_flam_conc = conc_flam.sum(axis=0)
                conc_co2 = vv_concentrations[3, :]

                adjusted_le_chatelier_lfl = np.full(num_steps, np.nan)
                active_mask = total_flam_conc > 0

                if np.any(active_mask):
                    fracs = conc_flam[:, active_mask] / total_flam_conc[active_mask]

                    # Vectorized denominator: sum(frac_i / lfl_i) for valid LFLs
                    inv_lfls = np.where(individual_lfls > 0, 1.0 / individual_lfls, 0.0)  # shape (3,)
                    denominator = inv_lfls @ fracs  # (3,) @ (3, N) -> (N,)

                    valid_denom = denominator > 0
                    active_indices = np.where(active_mask)[0]
                    valid_indices = active_indices[valid_denom]

                    lfl_mix = 1.0 / denominator[valid_denom]

                    # CO2 inert gas correction
                    total_offgas = total_flam_conc[valid_indices] + conc_co2[valid_indices]
                    co2_frac = np.where(total_offgas > 0, conc_co2[valid_indices] / total_offgas, 0.0)
                    needs_correction = (co2_frac > 0) & (co2_frac < 1.0)
                    inert_ratio = np.where(needs_correction, co2_frac / (1.0 - co2_frac), 0.0)
                    adjusted_lfl = lfl_mix * (100.0 - lfl_mix - (1.0 - k_co2) * inert_ratio * lfl_mix) / (100.0 - lfl_mix)
                    adjusted_lfl = np.where(needs_correction, adjusted_lfl, lfl_mix)
                    adjusted_le_chatelier_lfl[valid_indices] = adjusted_lfl

                flam_result_vv_df["Le Chatelier LFL (v/v%)"] = adjusted_le_chatelier_lfl
                print(f"Le Chatelier's LFL range: {np.nanmin(adjusted_le_chatelier_lfl):.4f}% - {np.nanmax(adjusted_le_chatelier_lfl):.4f}%")


            # === Save results ===
            flam_scenario_results[scenario_name] = {
                "flam_vv_df": flam_result_vv_df,
                "flam_mgl_df": flam_result_mgl_df,
                "flam_max_mod": flam_max_mods,
                "input": data,
                "use_le_chatelier": use_le_chatelier,
                "le_chatelier_lfl_array": adjusted_le_chatelier_lfl if use_le_chatelier else None
            }

        except ZeroDivisionError:
            QMessageBox.warning(None, "Calculation Error", f"{scenario_name} failed: Division by zero encountered.\nPlease check the input values.")
            return
        except Exception as e:
            QMessageBox.warning(None, "Calculation Error", f"{scenario_name} failed with an unexpected error:\n{e}")
            return
        
            # Display results
    # display_flammability_result_popup(flam_scenario_results, state.tree, gas_data, bat_data)
    pass

