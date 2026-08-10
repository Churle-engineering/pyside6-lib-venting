import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import lfilter
from PySide6.QtWidgets import QMessageBox

from information import (
    BATTERY_CHEMISTRY_DATA,
    CHEMICAL_PROPERTIES,
    MODULES_PER_DELAY,
    COMBINED_INPUTS,
    get_specific_capacity,
    CO_TEMPERATURE_LFL_PARAMETER_A,
    CO_TEMPERATURE_LFL_PARAMETER_B,
    H2_TEMPERATURE_LFL_PARAMETER_A,
    H2_TEMPERATURE_LFL_PARAMETER_B,
    THC_TEMPERATURE_LFL_PARAMETER_A,
    THC_TEMPERATURE_LFL_PARAMETER_B,
)

# Helper utilities that normalise gas labels and convert scenario rows into a
# consistent shape before the main simulation routines run.
def strip_unit_suffix(name):
    """Remove unit suffixes such as _(%), _(s), _(ah), etc."""
    return re.sub(r"_\([^)]*\)$", "", name)


def normalize_gas_key(label):
    """Normalize gas labels from UI/scenario data to the canonical keys used in CHEMICAL_PROPERTIES."""
    text = strip_unit_suffix(str(label).strip().lower())
    text = text.replace("%", "")
    text = re.sub(r"[()\s]+", "_", text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if text.endswith("_ppm"):
        text = text[:-4]
    if text.endswith("_mg_l"):
        text = text[:-5]
    if text.endswith("_v_v"):
        text = text[:-4]

    aliases = {
        "carbon_monoxide": "co",
        "carbon_monoxide_gas": "co",
        "hydrogen": "h2",
        "hydrogen_gas": "h2",
        "carbon_dioxide": "co2",
        "co2": "co2",
        "thc": "total_hydrocarbons",
        "total_hc": "total_hydrocarbons",
        "total_hydrocarbon": "total_hydrocarbons",
        "total_hydrocarbons": "total_hydrocarbons",
        "hydrocarbons_total": "total_hydrocarbons",
    }
    return aliases.get(text, text)


def resolve_flammable_gas_inputs(data):
    """Return scenario gas labels mapped to canonical flammable gas keys in a stable order."""
    desired_order = ["co", "h2", "total_hydrocarbons"]
    resolved = []
    for canonical in desired_order:
        for label in data:
            if normalize_gas_key(label) == canonical:
                resolved.append((label, canonical))
                break
    return resolved


def resolve_lfl_curve_labels(labels):
    """Return canonical flammable-gas labels and their source row indices."""
    index_by_gas = {}
    for index, label in enumerate(labels):
        index_by_gas.setdefault(normalize_gas_key(label), index)

    names = [
        gas
        for gas in ("co", "h2", "total_hydrocarbons")
        if gas in index_by_gas
    ]
    return names, [index_by_gas[gas] for gas in names]


def is_string_field(label):
    label_l = str(label).lower()
    return any(
        kw in label_l
        for kw in ["description", "name", "location", "room", "manufacturer", "lib type"]
    )


def _coerce_scalar(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        if text == "" or text.lower() in {"nan", "none"}:
            return default
        try:
            return float(text)
        except ValueError:
            return default
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.integer, int)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_state_value(obj, attr, default=None):
    if obj is None:
        return default

    value = getattr(obj, attr, default)
    if hasattr(value, "currentText"):
        return value.currentText()
    if hasattr(value, "get"):
        try:
            return value.get()
        except Exception:
            pass
    if isinstance(value, bool):
        return value
    return value


def _bool_state_value(obj, attr, default=False):
    value = _resolve_state_value(obj, attr, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return bool(value)


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
        return default
    return bool(value)


def _row_has_any_input(row):
    if isinstance(row, dict):
        return any(value not in (None, "", np.nan) for value in row.values())

    if hasattr(row, "dtype") and getattr(row.dtype, "names", None):
        for value in row:
            if value not in (None, "", np.nan):
                return True
        return False

    if isinstance(row, (list, tuple)):
        return any(value not in (None, "", np.nan) for value in row)

    return False


def _iter_scenarios(state, scenario_data=None):
    """Yield (scenario_name, input_dict) rows from the current spreadsheet data."""
    if scenario_data is None:
        if hasattr(state, "scenario_data") and state.scenario_data is not None:
            scenario_data = state.scenario_data
        elif hasattr(state, "current_scenario_data"):
            scenario_data = state.current_scenario_data()

    if scenario_data is None:
        return []

    if isinstance(scenario_data, dict):
        if _row_has_any_input(scenario_data):
            return [("Scenario 1", scenario_data)]
        return []

    if isinstance(scenario_data, np.ndarray) and scenario_data.dtype.names is not None:
        rows = []
        for idx, row in enumerate(scenario_data):
            if not _row_has_any_input(row):
                continue
            data = {}
            for name in scenario_data.dtype.names:
                value = row[name]
                if isinstance(value, float) and np.isnan(value):
                    value = "" if is_string_field(name) else 0
                elif isinstance(value, np.bytes_):
                    value = value.decode("utf-8")
                data[name] = value
            rows.append((f"Scenario {idx + 1}", data))
        return rows

    if isinstance(scenario_data, (list, tuple)):
        rows = []
        for idx, row in enumerate(scenario_data):
            if not _row_has_any_input(row):
                continue
            if isinstance(row, dict):
                data = row
                name = str(data.get("Scenario Description", "") or "").strip() or f"Scenario {idx + 1}"
            elif isinstance(row, (list, tuple)):
                data = {
                    header: row[i]
                    for i, header in enumerate(COMBINED_INPUTS[: len(row)])
                }
                name = f"Scenario {idx + 1}"
            else:
                data = {"value": row}
                name = f"Scenario {idx + 1}"
            rows.append((name, data))
        return rows

    return []


# Lightweight dataclass that stores the parsed scenario inputs using named
# attributes instead of string-based dictionary lookups.
@dataclass(slots=True)
class ScenarioInputs:
    """Typed, attribute-accessed view of one parsed scenario row.

    Replaces the previous dict-based ``inputs`` structure so downstream
    calculation code uses attribute access (``inputs.room_area``) instead of
    string-keyed lookups (``inputs["room_area"]``). This catches key typos
    at edit time (via IDE/type checking) instead of at runtime, and
    ``slots=True`` avoids the per-instance ``__dict__`` a plain dict/object
    would need, which keeps memory use low even across many scenarios.
    """

    total_duration: int = 0
    time_step: int = 1
    ventilation_rate: float = 0.0
    room_height: float = 0.0
    room_area: float = 0.0
    equip_space: float = 0.0
    cell_volume: float = 0.0
    cell_duration: float = 0.0
    module_volume: float = 0.0
    module_duration: float = 0.0
    cells: float = 0.0
    modules: float = 0.0
    units: float = 0.0
    lfl_percent: float = 0.0
    propagation_delay: float = 0.0
    module_capacity: float = 0.0
    vent_switch_conc: float = 0.0
    emergency_vent_rate: float = 0.0
    co2_percent: float = 0.0
    venting_temperature: float = 0.0
    lib_type: str = "NMC"

    def to_input_array(self):
        """Return the numeric fields as one contiguous float64 numpy array.

        Handy when a batch of scenarios needs identical arithmetic applied
        at once (e.g. stacking several scenarios' arrays with ``np.vstack``
        for a vectorised calculation) instead of scalar attribute access.
        """
        return np.array(
            [
                self.total_duration,
                self.time_step,
                self.ventilation_rate,
                self.room_height,
                self.room_area,
                self.equip_space,
                self.cell_volume,
                self.cell_duration,
                self.module_volume,
                self.module_duration,
                self.cells,
                self.modules,
                self.units,
                self.lfl_percent,
                self.propagation_delay,
                self.module_capacity,
                self.vent_switch_conc,
                self.emergency_vent_rate,
                self.co2_percent,
                self.venting_temperature,
            ],
            dtype=np.float64,
        )


# Convert a scenario row from the UI or spreadsheet into the shared numeric
# input object used by all of the calculation routines.
def _parse_scenario_inputs(data, propagation_delay_default=0.0):
    """Convert one spreadsheet row into the shared calculation input shape."""
    def number(column, *aliases, default=0.0):
        for label in (column, *aliases):
            if label in data:
                return _coerce_scalar(data[label], default)
        return default

    return ScenarioInputs(
        total_duration=int(number("Calculation Duration (s)")),
        time_step=1,
        ventilation_rate=number("Ventilation Rate (L/s/m2)"),
        room_height=number("Room Height (m)"),
        room_area=number("Room Area (m2)"),
        equip_space=number("Equipment Space (%)"),
        # Accept both internal keys and UI labels from scenario edit/popups.
        cell_volume=number("cell_volume_(l)", "Cell Volume (L)"),
        cell_duration=number("cell_duration_(s)", "Cell Duration (s)"),
        module_volume=number("module_volume_(l)", "Module Volume (L)"),
        module_duration=number("module_duration_(s)", "Module Duration (s)"),
        cells=number("Cells per module", "Cells per"),
        modules=number("Modules per unit", "Modules per"),
        units=number("Units"),
        lfl_percent=number("LFL (%)", "lfl_(%)"),
        propagation_delay=number("Module Propagation Delay (s)", default=propagation_delay_default),
        module_capacity=number("module_capacity_(kwh)", "Module Capacity (kWh)"),
        vent_switch_conc=number("Vent Switch Conc (%)"),
        emergency_vent_rate=number("Emergency Vent Rate (L/s/m2)"),
        co2_percent=number("co2_(%)", "CO2 (%)") / 100.0,
        venting_temperature=number(
            "venting_temperature_(°c)",
            "Venting Temperature (°C)",
            "Venting Temperature (C)",
        ),
        lib_type=str(data.get("LIB Type", "NMC") or "NMC"),
    )


# Build the time-varying list of active modules so the release profile can be
# staggered across the simulation period.
def calc_active_modules_array(time_array, total_mods, propagation_delay, mod_duration, modules_per_delay=MODULES_PER_DELAY):
    """Vectorized module activity profile for the simulation."""
    active = np.zeros(len(time_array), dtype=np.float64)
    mask = time_array > 0
    t_pos = time_array[mask]

    if propagation_delay > 0:
        # First delayed group starts one full delay after the initial module start.
        intervals_passed = (t_pos // propagation_delay).astype(np.int64)
        intervals_passed = np.maximum(intervals_passed, 0)
        started = np.minimum(total_mods, 1 + intervals_passed * modules_per_delay)
    else:
        started = np.full(len(t_pos), total_mods, dtype=np.float64)

    if propagation_delay == 0:
        finished = np.where(t_pos >= mod_duration, total_mods, 0)
    else:
        past_duration = t_pos >= mod_duration
        finished_intervals = ((t_pos - mod_duration) // propagation_delay).astype(np.int64) * modules_per_delay
        finished = np.where(past_duration, np.minimum(total_mods, 1 + finished_intervals), 0)

    active[mask] = np.maximum(0, started - finished)
    return active


# Choose which release calculation pathway should be used for the scenario.
def determine_calc_method(mod_capacity, user_selected_method):
    if user_selected_method == "Module Variable Flowrate":
        return "Module Variable Flowrate", False
    if user_selected_method == "Module Volume UL9540A":
        return "Module Volume UL9540A", False
    if mod_capacity > 1:
        was_overridden = user_selected_method == "Module Capacity"
        return "Cell Volume UL9540A", was_overridden
    return user_selected_method, False


# Convert the selected calculation method into a module release volume in cubic metres.
def calc_module_volume(calc_method, lib_type, mod_capacity, cells, cell_volume, module_volume=0.0):
    if calc_method == "Module Volume UL9540A":
        return module_volume / 1000.0
    if calc_method == "Module Capacity":
        specific_capacity = get_specific_capacity(lib_type)
        return (specific_capacity * mod_capacity) / 1000.0
    return cells * cell_volume / 1000.0


# Resolve the release volume and duration for the chosen method so the engine
# can keep a consistent interface regardless of the input source.
def resolve_release_parameters_for_calc_method(calc_method, inputs):
    """Resolve per-module release volume and release duration used by calculations.

    Returns a dict with explicit source metadata so each method's inputs are clear.
    """
    if calc_method == "Module Variable Flowrate":
        return {
            "route": "graphical_flowrate",
            "total_release_volume_m3": None,
            "release_duration_s": None,
            "volume_source": "flowrate dataset (_lib_flowrate_data)",
            "duration_source": "flowrate profile length",
            "specific_capacity_ah_per_kwh": None,
        }

    if calc_method == "Module Volume UL9540A":
        return {
            "route": "scalar_release",
            "total_release_volume_m3": inputs.module_volume / 1000.0,
            "release_duration_s": inputs.module_duration,
            "volume_source": "module_volume_(l)",
            "duration_source": "module_duration_(s)",
            "specific_capacity_ah_per_kwh": None,
        }

    if calc_method == "Module Capacity":
        specific_capacity = get_specific_capacity(inputs.lib_type)
        return {
            "route": "scalar_release",
            "total_release_volume_m3": (specific_capacity * inputs.module_capacity) / 1000.0,
            "release_duration_s": inputs.module_duration,
            "volume_source": "specific_capacity(lib_type) * module_capacity_(kwh)",
            "duration_source": "module_duration_(s)",
            "specific_capacity_ah_per_kwh": specific_capacity,
        }

    return {
        "route": "scalar_release",
        "total_release_volume_m3": (inputs.cells * inputs.cell_volume) / 1000.0,
        "release_duration_s": inputs.cell_duration,
        "volume_source": "cells_per_module * cell_volume_(l)",
        "duration_source": "cell_duration_(s)",
        "specific_capacity_ah_per_kwh": None,
    }


def validate_densities(gas_labels, gas_percents, gas_data, normalize_fn=None):
    densities = []
    valid_labels = []
    valid_percents = []

    for idx, label in enumerate(gas_labels):
        normalized = normalize_fn(label) if normalize_fn else normalize_gas_key(label)
        density = gas_data.get(normalized, {}).get("density")
        if density is not None and density > 0:
            densities.append(density)
            valid_labels.append(label)
            valid_percents.append(gas_percents[idx])

    if not valid_labels:
        return None

    return valid_labels, np.array(valid_percents, dtype=float), np.array(densities, dtype=float)


def resolve_toxic_gas_densities(tox_gas_composition):
    """Return toxic components that have usable canonical density data."""
    gas_labels = []
    gas_percents = []
    densities = []

    for label, percent in tox_gas_composition.items():
        gas_key = normalize_gas_key(label)
        density = CHEMICAL_PROPERTIES.get(gas_key, {}).get("density")
        if density is not None and density > 0:
            gas_labels.append(label)
            gas_percents.append(float(percent) / 100.0)
            densities.append(float(density))

    if not gas_labels:
        return None

    percents = np.array(gas_percents, dtype=float)
    if float(np.sum(percents)) <= 0:
        return None

    # Return raw fractions (value/100) so each gas volume = total_volume * percent_tox * gas_fraction.
    # Gases without density data are excluded but their share is not redistributed.
    return (
        gas_labels,
        percents,
        np.array(densities, dtype=float),
    )


def resolve_toxic_trigger_gas(valid_gas_labels):
    """Return (label, index, erpg_3_threshold) for CO, the fixed toxicity emergency-vent trigger gas."""
    for idx, label in enumerate(valid_gas_labels):
        if normalize_gas_key(label) == "co":
            erpg_3 = CHEMICAL_PROPERTIES.get("co", {}).get("erpg_3")
            if erpg_3 is not None and erpg_3 > 0:
                return label, idx, erpg_3
            return label, idx, None
    return None, None, None


# Create the emergency ventilation controller state used by both toxicity and
# flammability calculations when a trigger concentration is exceeded.
def init_emergency_ventilation(ventilation_rate, emergency_vent_rate, room_area, room_vol, vent_switch_conc, trigger_threshold=None):
    """Create shared emergency-ventilation controller state for toxicity and flammability calcs.

    `vent_switch_conc` is the user-entered value that (alongside `emergency_vent_rate`) must be
    provided to enable emergency ventilation. `trigger_threshold` is the concentration the
    monitored gas must exceed to activate; defaults to `vent_switch_conc` (flammable gas case).
    """
    if trigger_threshold is None:
        trigger_threshold = vent_switch_conc

    base_vent_rate = (ventilation_rate / 1000.0) * room_area if ventilation_rate > 0 else 0.0
    requested_emergency_rate = (emergency_vent_rate / 1000.0) * room_area if emergency_vent_rate > 0 else 0.0
    emergency_vent_rate_effective = max(base_vent_rate, requested_emergency_rate)

    base_outflow = base_vent_rate / room_vol if room_vol > 0 else 0.0
    emergency_outflow = emergency_vent_rate_effective / room_vol if room_vol > 0 else 0.0
    enabled = (
        vent_switch_conc > 0
        and requested_emergency_rate > base_vent_rate
        and room_vol > 0
        and trigger_threshold is not None
    )

    print(
        f"DEBUG: init_emergency_ventilation -> enabled={enabled}, "
        f"base_outflow={base_outflow:.6f}/s, emergency_outflow={emergency_outflow:.6f}/s, "
        f"trigger_threshold={trigger_threshold}, vent_switch_conc={vent_switch_conc}, "
        f"emergency_vent_rate={emergency_vent_rate}"
    )

    return {
        "trigger_threshold": trigger_threshold,
        "enabled": enabled,
        "activated": False,
        "base_outflow": base_outflow,
        "emergency_outflow": emergency_outflow,
        "current_outflow": base_outflow,
    }


def resolve_trigger_concentration(current_conc, target_gas_index):
    if target_gas_index is None:
        return float(np.sum(current_conc))
    if target_gas_index < 0 or target_gas_index >= len(current_conc):
        return float(np.sum(current_conc))
    return float(current_conc[target_gas_index])


def maybe_activate_emergency_ventilation(vent_state, trigger_conc, time_s, target_gas_name):
    if not vent_state["enabled"] or vent_state["activated"]:
        return vent_state["current_outflow"]

    if trigger_conc > vent_state["trigger_threshold"]:
        old_outflow = vent_state["current_outflow"]
        vent_state["activated"] = True
        vent_state["current_outflow"] = vent_state["emergency_outflow"]
        print(f"⚠️ Emergency ventilation ACTIVATED at t={time_s}s ({target_gas_name}: {trigger_conc:.4f}%)")
        print(f"DEBUG: outflow changed from {old_outflow:.6f}/s to {vent_state['current_outflow']:.6f}/s")

    return vent_state["current_outflow"]


def _search_modules_required_for_threshold(peak_fn, threshold_value, max_modules_limit=100000):
    """Return the minimum failing modules needed to reach the criterion threshold."""
    if threshold_value <= 0:
        return 0

    low = 1
    high = 1
    while high <= max_modules_limit and peak_fn(high) < threshold_value:
        low = high + 1
        high *= 2

    if low > max_modules_limit:
        return None

    high = min(high, max_modules_limit)
    if low > high:
        return None

    result = None
    while low <= high:
        mid = (low + high) // 2
        if peak_fn(mid) >= threshold_value:
            result = mid
            high = mid - 1
        else:
            low = mid + 1
    return result


# Determine the number of modules required to reach a threshold using a
# constant-per-module release profile and a simple room mixing model.
def modules_required_constant_flow(
    total_duration,
    time_step,
    propagation_delay,
    mod_duration,
    per_module_flowrate,
    room_vol,
    adj_ventilation_rate,
    threshold_value,
    modules_per_delay=MODULES_PER_DELAY,
    max_modules_limit=100000,
):
    """Minimum failed modules needed to reach threshold for constant per-module release."""
    if threshold_value <= 0:
        return 0

    if (
        room_vol <= 0
        or time_step <= 0
        or total_duration <= 0
        or mod_duration <= 0
        or per_module_flowrate <= 0
    ):
        return None

    vent_coeff = adj_ventilation_rate / room_vol if room_vol > 0 else 0.0
    alpha = 1.0 - vent_coeff * time_step
    time_array = np.arange(0, total_duration + 1, time_step)
    peak_cache = {}

    def peak_with_modules(module_count):
        cached = peak_cache.get(module_count)
        if cached is not None:
            return cached
        active_array = calc_active_modules_array(
            time_array,
            module_count,
            propagation_delay,
            mod_duration,
            modules_per_delay,
        )
        inflow_signal = active_array * per_module_flowrate * time_step
        gas_array = lfilter([1.0], [1.0, -alpha], inflow_signal)
        gas_array = np.maximum(gas_array, 0.0)
        peak_value = float(np.max(gas_array)) if gas_array.size else 0.0
        peak_cache[module_count] = peak_value
        return peak_value

    return _search_modules_required_for_threshold(
        peak_with_modules,
        threshold_value,
        max_modules_limit=max_modules_limit,
    )


# Determine the number of modules required to reach a threshold using a
# time-varying flowrate profile imported from the custom LIB data.
def modules_required_flow_profile(
    total_duration,
    time_step,
    propagation_delay,
    flowrate_profile,
    room_vol,
    adj_ventilation_rate,
    threshold_value,
    modules_per_delay=MODULES_PER_DELAY,
    max_modules_limit=100000,
):
    """Minimum failed modules needed to reach threshold for a per-module flow profile."""
    if threshold_value <= 0:
        return 0

    if room_vol <= 0 or time_step <= 0 or total_duration <= 0:
        return None

    profile = np.asarray(flowrate_profile, dtype=float)
    if profile.size == 0 or not np.any(profile > 0):
        return None

    mod_duration = int(profile.size)
    time_array = np.arange(0, total_duration + 1, time_step)
    num_steps = len(time_array)
    vent_coeff = adj_ventilation_rate / room_vol if room_vol > 0 else 0.0
    alpha = 1.0 - vent_coeff * time_step
    peak_cache = {}

    def peak_with_modules(total_mods):
        cached = peak_cache.get(total_mods)
        if cached is not None:
            return cached

        inflow_signal = np.zeros(num_steps, dtype=float)
        if total_mods > 0:
            if propagation_delay <= 0:
                module_groups = [(1, int(total_mods))]
            else:
                module_groups = []
                remaining = int(total_mods)
                module_groups.append((1, 1))
                remaining -= 1
                delay_count = 1
                while remaining > 0:
                    start_time = int(1 + delay_count * propagation_delay)
                    count = min(modules_per_delay, remaining)
                    module_groups.append((start_time, count))
                    remaining -= count
                    delay_count += 1

            for group_start, group_count in module_groups:
                valid_mask = (time_array >= group_start) & ((time_array - group_start) < mod_duration)
                if not np.any(valid_mask):
                    continue
                local_times = (time_array[valid_mask] - group_start).astype(np.intp)
                inflow_signal[valid_mask] += group_count * profile[local_times] * time_step

        gas_array = lfilter([1.0], [1.0, -alpha], inflow_signal)
        gas_array = np.maximum(gas_array, 0.0)
        peak_value = float(np.max(gas_array)) if gas_array.size else 0.0
        peak_cache[total_mods] = peak_value
        return peak_value

    return _search_modules_required_for_threshold(
        peak_with_modules,
        threshold_value,
        max_modules_limit=max_modules_limit,
    )


def max_modules_before_threshold(modules_required, max_modules_limit=100000):
    """Convert a modules-required value into maximum modules that can fail before criterion is met."""
    if modules_required is None:
        return max_modules_limit
    return max(0, int(modules_required) - 1)


# --- Calculations ---


# Run the toxicity assessment across the selected scenarios and store the
# resulting concentration DataFrames for later display.
def toxicity_assessment_calc(parent, state, display_toxicity_result_popup, gas_data, scenario_data=None, clear_existing=True):
    tox_scenario_results = getattr(state, "tox_scenario_results", None)
    if tox_scenario_results is None:
        tox_scenario_results = {}
        state.tox_scenario_results = tox_scenario_results
    if clear_existing:
        tox_scenario_results.clear()

    scenarios = _iter_scenarios(state, scenario_data)
    if not scenarios:
        display_toxicity_result_popup(tox_scenario_results, None, [], gas_data)
        return

    for scenario_name, data in scenarios:
        try:
            inputs = _parse_scenario_inputs(data, propagation_delay_default=180.0)
            total_duration = inputs.total_duration
            time_step = inputs.time_step
            ventilation_rate = inputs.ventilation_rate
            room_height = inputs.room_height
            room_area = inputs.room_area
            equip_space = inputs.equip_space
            modules = inputs.modules
            units = inputs.units
            lib_type = inputs.lib_type
            propagation_delay = inputs.propagation_delay
            mod_capacity = inputs.module_capacity
            vent_switch_conc = inputs.vent_switch_conc
            emergency_vent_rate = inputs.emergency_vent_rate

            user_selected_method = str(data.get("Calculation Method",_resolve_state_value(state, "selected_calc_method", "Cell Volume UL9540A"),) or "Cell Volume UL9540A")
            if user_selected_method == "Module Variable Flowrate":
                # Toxicity does not support the graphical flowrate route.
                # Fall back to module-level scalar toxicity calculations.
                print(
                    f"Toxicity - Scenario '{scenario_name}' selected Module Variable Flowrate; "
                    "defaulting to Module Volume UL9540A for toxicity."
                )
                user_selected_method = "Module Volume UL9540A"
            calc_method, _ = determine_calc_method(mod_capacity, user_selected_method)
            print(f"Toxicity - Using calculation method: {calc_method}")

            release_params = resolve_release_parameters_for_calc_method(calc_method, inputs)
            if release_params["route"] == "graphical_flowrate":
                raise ValueError(
                    "Module Variable Flowrate is not supported for toxicity calculations. "
                    "Use Module Volume UL9540A, Module Capacity, Cell Volume UL9540A, or Cell Propagation."
                )

            if room_height == 0 or room_area == 0:
                raise ValueError("Room Height (m) and Room Area (m2) are required")

            if release_params["release_duration_s"] is None or release_params["release_duration_s"] <= 0:
                raise ValueError(
                    f"{calc_method} requires positive release duration from {release_params['duration_source']}"
                )
            if release_params["total_release_volume_m3"] is None or release_params["total_release_volume_m3"] <= 0:
                raise ValueError(
                    f"{calc_method} requires positive total release volume from {release_params['volume_source']}"
                )

            mod_vol = float(release_params["total_release_volume_m3"])
            mod_duration = float(release_params["release_duration_s"])
            print(
                "Toxicity - Release source: "
                f"volume={mod_vol:.8f} m3 ({release_params['volume_source']}), "
                f"duration={mod_duration:.4f} s ({release_params['duration_source']})"
            )
            if release_params["specific_capacity_ah_per_kwh"] is not None:
                print(
                    "Toxicity - Module Capacity conversion: "
                    f"specific_capacity={release_params['specific_capacity_ah_per_kwh']:.6f} Ah/kWh, "
                    f"module_capacity={inputs.module_capacity:.6f} kWh"
                )

            lib_type_upper = str(lib_type).upper()
            chemistry_data = BATTERY_CHEMISTRY_DATA.get(lib_type_upper, BATTERY_CHEMISTRY_DATA.get("NMC", {}))

            # User Defined composition can supply an override for tox gas composition
            tox_comp_override = data.get("_tox_gas_composition_override")
            if tox_comp_override:
                lib_tox_gas_composition = tox_comp_override
            else:
                lib_tox_gas_composition = chemistry_data.get("tox_gas_composition", {})

            density_result = resolve_toxic_gas_densities(lib_tox_gas_composition)
            if density_result is None:
                raise ValueError("No toxic gases with valid density data were found")

            valid_gas_labels, gas_percents, densities = density_result
            num_gases = len(valid_gas_labels)
            num_steps = (total_duration // time_step) + 1
            concentrations = np.zeros((num_gases, num_steps), dtype=float)
            mgl_concentrations = np.zeros((num_gases, num_steps), dtype=float)
            gases = np.zeros(num_gases, dtype=float)
            prev_gas = np.zeros(num_gases, dtype=float)
            time = np.arange(0, total_duration + 1, time_step)

            adj_ventilation_rate = (ventilation_rate / 1000.0) * room_area

            room_vol = room_height * room_area * (1 - (equip_space / 100.0))
            total_mods = modules * units

            if "_percent_tox_override" in data:
                percent_tox = float(data["_percent_tox_override"])
            else:
                percent_tox = chemistry_data.get("percent_tox", 100)
            tox_mod_vol = mod_vol * (percent_tox / 100.0)
            mod_flowrate = tox_mod_vol / mod_duration if mod_duration > 0 else 0

            target_gas_name, target_gas_index, co_erpg_3 = resolve_toxic_trigger_gas(valid_gas_labels)
            emergency_vent_state = init_emergency_ventilation(
                ventilation_rate,
                emergency_vent_rate,
                room_area,
                room_vol,
                vent_switch_conc,
                trigger_threshold=co_erpg_3,
            )
            total_vent_outflow = emergency_vent_state["current_outflow"]
            active_modules_arr = calc_active_modules_array(time, total_mods, propagation_delay, mod_duration)

            for step_idx in range(num_steps):
                current_total_bat_flow = active_modules_arr[step_idx] * mod_flowrate
                inflows = current_total_bat_flow * gas_percents
                outflows = total_vent_outflow * prev_gas
                gases += (inflows - outflows) * time_step
                gases = np.maximum(gases, 0.0)
                prev_gas[:] = gases

                current_conc = (gases / room_vol) * 100.0 if room_vol > 0 else np.zeros_like(gases)
                concentrations[:, step_idx] = current_conc * 10000  # ppm (v/v% * 10000)
                mgl_concentrations[:, step_idx] = (current_conc / 100.0) * densities * 1000.0

                trigger_conc = resolve_trigger_concentration(current_conc, target_gas_index)
                total_vent_outflow = maybe_activate_emergency_ventilation(
                    emergency_vent_state,
                    trigger_conc,
                    time[step_idx],
                    target_gas_name or "CO",
                )

            mgl_data = {"Time (s)": time}
            vv_data = {"Time (s)": time}
            for idx, label in enumerate(valid_gas_labels):
                mgl_data[f"{label} (mg/L)"] = mgl_concentrations[idx, :]
                vv_data[f"{label} (v/v%)"] = concentrations[idx, :]

            tox_result_mgl_df = pd.DataFrame(mgl_data)
            tox_result_vv_df = pd.DataFrame(vv_data)
            tox_result_mgl_df["Total Gas (mg/L)"] = tox_result_mgl_df[[c for c in tox_result_mgl_df.columns if c != "Time (s)" and c != "Total Gas (mg/L)"]].sum(axis=1)
            tox_result_vv_df["Total Gas (v/v%)"] = tox_result_vv_df[[c for c in tox_result_vv_df.columns if c != "Time (s)" and c != "Total Gas (v/v%)"]].sum(axis=1)

            tox_max_mods = {}
            for idx, label in enumerate(valid_gas_labels):
                gas_percent = gas_percents[idx]
                if gas_percent <= 0:
                    tox_max_mods[label] = "NA - No Gas Fraction"
                    continue

                threshold_value = (gas_percent * room_vol) / 100.0
                modules_required = modules_required_constant_flow(
                    total_duration,
                    time_step,
                    propagation_delay,
                    mod_duration,
                    mod_flowrate * gas_percent,
                    room_vol,
                    adj_ventilation_rate,
                    threshold_value,
                )
                max_modules = max_modules_before_threshold(modules_required)
                tox_max_mods[label] = max_modules if modules_required is not None else "NA - Exceeds Calc Limit"

            tox_scenario_results[scenario_name] = {
                "tox_vv_df": tox_result_vv_df,
                "tox_mgl_df": tox_result_mgl_df,
                "tox_max_mod": tox_max_mods,
                "calc_method": calc_method,
                "input": data,
            }
        except ZeroDivisionError:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed: Division by zero encountered.\nPlease check the input values.")
            return
        except Exception as exc:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed with an unexpected error:\n{exc}")
            return

    if tox_scenario_results:
        first_scenario = next(iter(tox_scenario_results.values()))
        result_gas_labels = [
            col.replace(" (mg/L)", "")
            for col in first_scenario["tox_mgl_df"].columns
            if col not in ["Time (s)", "Total Gas (mg/L)"]
        ]
        display_toxicity_result_popup(tox_scenario_results, None, result_gas_labels, gas_data)
    else:
        display_toxicity_result_popup(tox_scenario_results, None, [], gas_data)


# Run the main flammability assessment using the selected release method and
# build DataFrames of vapour concentration versus time.
def flammability_assessment_calc(parent, state, display_flammability_result_popup, gas_data, bat_data, flam_gasses_labels, scenario_data=None, clear_existing=True):
    print("\n=== DEBUG: flammability_assessment_calc START ===")
    print(f"DEBUG: clear_existing={clear_existing}, scenario_data_type={type(scenario_data).__name__ if scenario_data is not None else 'None'}")
    flam_scenario_results = getattr(state, "flam_scenario_results", None)
    if flam_scenario_results is None:
        flam_scenario_results = {}
        state.flam_scenario_results = flam_scenario_results
    if clear_existing:
        flam_scenario_results.clear()

    scenarios = _iter_scenarios(state, scenario_data)
    print(f"DEBUG: scenarios_found={len(scenarios)}")
    if not scenarios:
        print("DEBUG: No scenarios found; showing empty flammability popup")
        display_flammability_result_popup(flam_scenario_results, None, gas_data, bat_data, parent=parent)
        return

    module_capacity_overrides = []

    for scenario_name, data in scenarios:
        try:
            print("\n--- DEBUG: Scenario START ---")
            print(f"DEBUG: scenario_name={scenario_name}")
            print(f"DEBUG: scenario_keys={list(data.keys())}")

            inputs = _parse_scenario_inputs(data)
            print(
                "DEBUG: parsed_inputs="
                f"total_duration={inputs.total_duration}, time_step={inputs.time_step}, "
                f"ventilation_rate={inputs.ventilation_rate}, room_height={inputs.room_height}, room_area={inputs.room_area}, "
                f"equip_space={inputs.equip_space}, cell_volume={inputs.cell_volume}, cell_duration={inputs.cell_duration}, "
                f"module_volume={inputs.module_volume}, module_duration={inputs.module_duration}, cells={inputs.cells}, "
                f"modules={inputs.modules}, units={inputs.units}, lfl_percent={inputs.lfl_percent}, "
                f"propagation_delay={inputs.propagation_delay}, module_capacity={inputs.module_capacity}, "
                f"vent_switch_conc={inputs.vent_switch_conc}, emergency_vent_rate={inputs.emergency_vent_rate}, "
                f"co2_percent={inputs.co2_percent}, venting_temperature={inputs.venting_temperature}, lib_type={inputs.lib_type}"
            )

            # --- Calculation method ---
            user_selected_method = str(
                data.get("Calculation Method", _resolve_state_value(state, "selected_calc_method", "Cell Volume UL9540A"))
                or "Cell Volume UL9540A"
            )
            calc_method, _ = determine_calc_method(inputs.module_capacity, user_selected_method)
            print(
                f"DEBUG: calc_method_selection user_selected_method='{user_selected_method}', "
                f"resolved_calc_method='{calc_method}', module_capacity={inputs.module_capacity}"
            )
            if user_selected_method == "Module Capacity" and inputs.module_capacity > 1:
                module_capacity_overrides.append(f"{scenario_name} ({inputs.module_capacity:g} kWh)")
                print("DEBUG: module_capacity_override_applied=True")

            # --- Room geometry ---
            room_vol = inputs.room_height * inputs.room_area * (1 - inputs.equip_space / 100.0)
            adj_ventilation_rate = (inputs.ventilation_rate / 1000.0) * inputs.room_area
            print(
                f"DEBUG: geometry room_vol={room_vol:.6f} m3, adj_ventilation_rate={adj_ventilation_rate:.6f} m3/s"
            )

            # --- Gas volume source: depends on calc_method ---
            #     Module Volume UL9540A  -> inputs.module_volume (m3 direct)
            #     Module Capacity        -> specific capacity * kWh (via get_specific_capacity)
            #     Cell Volume UL9540A    -> inputs.cell_volume * inputs.cells
            mod_vol = calc_module_volume(
                calc_method, inputs.lib_type, inputs.module_capacity,
                inputs.cells, inputs.cell_volume, inputs.module_volume,
            )
            if calc_method == "Module Volume UL9540A":
                if inputs.room_height == 0 or inputs.room_area == 0 or inputs.module_duration == 0:
                    raise ValueError("Module Volume UL9540A requires room dimensions and module duration")
                if inputs.module_volume == 0:
                    raise ValueError("Module volume is zero")
                mod_duration = inputs.module_duration
            else:
                if inputs.room_height == 0 or inputs.room_area == 0 or inputs.cell_duration == 0:
                    raise ValueError("Cell-based methods require room dimensions and cell duration")
                if calc_method == "Module Capacity" and inputs.module_capacity == 0:
                    raise ValueError("Module capacity is zero")
                if calc_method != "Module Capacity" and inputs.cell_volume == 0:
                    raise ValueError("Cell volume is zero")
                mod_duration = inputs.cell_duration
            if mod_duration <= 0:
                mod_duration = 1
            print(
                f"DEBUG: module_source mod_vol={mod_vol:.8f} m3, mod_duration={mod_duration:.4f} s"
            )

            # Flammable fraction of module volume: from chemistry data or scenario override
            if "_flam_percent_override" in data:
                flam_percentage = float(data["_flam_percent_override"]) / 100.0
                print(f"DEBUG: flam_percentage_source=scenario_override ({flam_percentage * 100:.4f}%)")
            else:
                flam_percentage = BATTERY_CHEMISTRY_DATA.get(str(inputs.lib_type).upper(), {}).get("percent_flam", 100) / 100.0
                print(f"DEBUG: flam_percentage_source=chemistry_default ({flam_percentage * 100:.4f}%)")
            mod_flowrate = (mod_vol * flam_percentage) / mod_duration
            print(f"DEBUG: mod_flowrate={mod_flowrate:.10f} m3/s")

            # --- Gas composition source: scenario gas% columns (co, h2, total_hydrocarbons) ---
            gas_input_pairs = resolve_flammable_gas_inputs(data)
            valid_gas_labels = [label for label, _ in gas_input_pairs]
            gas_percents = np.array([float(data.get(label, 0)) / 100.0 for label, _ in gas_input_pairs], dtype=float)
            print(f"DEBUG: gas_input_pairs={gas_input_pairs}")
            print(f"DEBUG: gas_percents_raw={np.array2string(gas_percents, precision=8)} sum={float(np.sum(gas_percents)):.8f}")
            density_result = validate_densities(valid_gas_labels, gas_percents, gas_data, normalize_fn=normalize_gas_key)
            if density_result is None:
                raise ValueError("No flammable gases with valid density data were found")
            valid_gas_labels, gas_percents, densities = density_result
            print(f"DEBUG: valid_gas_labels={valid_gas_labels}")
            print(f"DEBUG: gas_percents_valid={np.array2string(gas_percents, precision=8)} sum={float(np.sum(gas_percents)):.8f}")
            print(f"DEBUG: densities_kgm3={np.array2string(densities, precision=8)}")

            # --- LFL thresholds ---
            use_le_chatelier = _coerce_bool(
                data.get("Use Le Chatelier LFL"),
                _bool_state_value(state, "use_le_chatelier_lfl", False),
            )
            use_temp_dependent_lfl = _coerce_bool(
                data.get("Use Temperature Dependent LFL"),
                _bool_state_value(state, "use_temp_dependent_lfl", False),
            )
            # Base LFLs from gas_data; overridden by temperature-linear model when both options active
            individual_lfls = np.array(
                [gas_data.get(g, {}).get("lfl", 0) or 0 for g in ("co", "h2", "total_hydrocarbons")],
                dtype=float,
            )
            print(
                f"DEBUG: lfl_flags use_le_chatelier={use_le_chatelier}, "
                f"use_temp_dependent_lfl={use_temp_dependent_lfl}, venting_temperature={inputs.venting_temperature}"
            )
            print(f"DEBUG: individual_lfls_initial={np.array2string(individual_lfls, precision=8)}")
            if use_le_chatelier and use_temp_dependent_lfl and inputs.venting_temperature > 0:
                t = inputs.venting_temperature
                temp_lfls = [
                    CO_TEMPERATURE_LFL_PARAMETER_A * t + CO_TEMPERATURE_LFL_PARAMETER_B,
                    H2_TEMPERATURE_LFL_PARAMETER_A * t + H2_TEMPERATURE_LFL_PARAMETER_B,
                    THC_TEMPERATURE_LFL_PARAMETER_A * t + THC_TEMPERATURE_LFL_PARAMETER_B,
                ]
                for idx, temp_lfl in enumerate(temp_lfls):
                    if temp_lfl > 0:
                        individual_lfls[idx] = temp_lfl
                print(f"DEBUG: temp_lfls_applied={np.array2string(np.array(temp_lfls, dtype=float), precision=8)}")
            print(f"DEBUG: individual_lfls_final={np.array2string(individual_lfls, precision=8)}")

            # --- Simulation ---
            total_mods = inputs.modules * inputs.units
            time = np.arange(0, inputs.total_duration + 1, 1)
            num_steps = len(time)
            num_gases = len(valid_gas_labels)
            print(
                f"DEBUG: simulation_setup total_mods={total_mods}, num_steps={num_steps}, num_gases={num_gases}, "
                f"time_start={time[0] if num_steps else 'NA'}, time_end={time[-1] if num_steps else 'NA'}"
            )

            vv_concentrations = np.zeros((num_gases, num_steps), dtype=float)
            mgl_concentrations = np.zeros((num_gases, num_steps), dtype=float)
            gases = np.zeros(num_gases, dtype=float)
            prev_gas = np.zeros(num_gases, dtype=float)

            # CO2 is inert (not summed into flammable gas totals) but dilutes the mixture,
            # so its own concentration trace is tracked for the Le Chatelier LFL correction.
            k_co2 = 1.5
            co2_conc_arr = np.zeros(num_steps, dtype=float)
            co2_gas = 0.0
            co2_prev = 0.0

            emergency_vent_state = init_emergency_ventilation(
                inputs.ventilation_rate, inputs.emergency_vent_rate,
                inputs.room_area, room_vol, inputs.vent_switch_conc,
            )
            total_vent_outflow = emergency_vent_state["current_outflow"]
            active_modules_arr = calc_active_modules_array(time, total_mods, inputs.propagation_delay, mod_duration)
            print(
                f"DEBUG: active_modules_arr stats min={float(np.min(active_modules_arr)):.4f}, "
                f"max={float(np.max(active_modules_arr)):.4f}, final={float(active_modules_arr[-1]) if len(active_modules_arr) else 0.0:.4f}"
            )
            if len(active_modules_arr) > 0:
                preview_count = min(15, len(active_modules_arr))
                print(f"DEBUG: active_modules_arr_first_{preview_count}={np.array2string(active_modules_arr[:preview_count], precision=4)}")

            peak_total_vv = -1.0
            peak_total_vv_time = 0
            peak_total_gas_volume = -1.0
            peak_total_gas_volume_time = 0

            for step_idx in range(num_steps):
                inflows = active_modules_arr[step_idx] * mod_flowrate * gas_percents
                outflows = total_vent_outflow * prev_gas
                gases += (inflows - outflows) * inputs.time_step
                gases = np.maximum(gases, 0.0)
                prev_gas[:] = gases

                current_conc = (gases / room_vol) * 100.0 if room_vol > 0 else np.zeros_like(gases)
                vv_concentrations[:, step_idx] = current_conc
                mgl_concentrations[:, step_idx] = (current_conc / 100.0) * densities * 1000.0

                co2_inflow = active_modules_arr[step_idx] * mod_flowrate * inputs.co2_percent
                co2_outflow = total_vent_outflow * co2_prev
                co2_gas = max(co2_gas + (co2_inflow - co2_outflow) * inputs.time_step, 0.0)
                co2_prev = co2_gas
                co2_conc_arr[step_idx] = (co2_gas / room_vol) * 100.0 if room_vol > 0 else 0.0

                total_vv_now = float(np.sum(current_conc))
                total_gas_volume_now = float(np.sum(gases))
                if total_vv_now > peak_total_vv:
                    peak_total_vv = total_vv_now
                    peak_total_vv_time = int(time[step_idx])
                    # print(
                    #     f"DEBUG: NEW_PEAK total_vv={peak_total_vv:.8f}% at t={peak_total_vv_time}s, "
                    #     f"total_gas_volume={total_gas_volume_now:.8f} m3"
                    # )
                if total_gas_volume_now > peak_total_gas_volume:
                    peak_total_gas_volume = total_gas_volume_now
                    peak_total_gas_volume_time = int(time[step_idx])

                should_print_step = (
                    step_idx < 5
                    or step_idx == num_steps - 1
                    or (step_idx % 60 == 0)
                )
                if should_print_step:
                    print(
                        # f"DEBUG: step={step_idx}, t={int(time[step_idx])}s, active_mods={active_modules_arr[step_idx]:.4f}, "
                        # f"inflows={np.array2string(inflows, precision=8)}, outflows={np.array2string(outflows, precision=8)}, "
                        # f"gases_m3={np.array2string(gases, precision=8)}, conc_vv={np.array2string(current_conc, precision=8)}, "
                        # f"total_vv={total_vv_now:.8f}%"
                    )

                total_vent_outflow = maybe_activate_emergency_ventilation(
                    emergency_vent_state, float(np.sum(current_conc)), time[step_idx], "Total Flammable Gas",
                )

            print(
                f"DEBUG: simulation_peaks peak_total_vv={peak_total_vv:.8f}% at t={peak_total_vv_time}s, "
                f"peak_total_gas_volume={peak_total_gas_volume:.8f} m3 at t={peak_total_gas_volume_time}s"
            )
            if num_gases > 0:
                per_gas_peak_vv = np.max(vv_concentrations, axis=1)
                per_gas_peak_mgl = np.max(mgl_concentrations, axis=1)
                print(f"DEBUG: per_gas_peak_vv={dict(zip(valid_gas_labels, per_gas_peak_vv.tolist()))}")
                print(f"DEBUG: per_gas_peak_mgl={dict(zip(valid_gas_labels, per_gas_peak_mgl.tolist()))}")

            # --- Result DataFrames ---
            flam_result_vv_df = pd.DataFrame({"Time (s)": time})
            flam_result_mgl_df = pd.DataFrame({"Time (s)": time})
            for idx, label in enumerate(valid_gas_labels):
                base_label = strip_unit_suffix(label)
                flam_result_vv_df[f"{base_label} (v/v%)"] = vv_concentrations[idx, :]
                flam_result_mgl_df[f"{base_label} (mg/L)"] = mgl_concentrations[idx, :]

            total_cols_vv = ["co (v/v%)", "h2 (v/v%)", "total_hydrocarbons (v/v%)"]
            total_cols_mgl = ["co (mg/L)", "h2 (mg/L)", "total_hydrocarbons (mg/L)"]
            if all(c in flam_result_vv_df.columns for c in total_cols_vv):
                flam_result_vv_df["Total Gas (v/v%)"] = flam_result_vv_df[total_cols_vv].sum(axis=1)
            if all(c in flam_result_mgl_df.columns for c in total_cols_mgl):
                flam_result_mgl_df["Total Gas (mg/L)"] = flam_result_mgl_df[total_cols_mgl].sum(axis=1)
            print(f"DEBUG: vv_columns={list(flam_result_vv_df.columns)}")
            print(f"DEBUG: mgl_columns={list(flam_result_mgl_df.columns)}")
            if "Total Gas (v/v%)" in flam_result_vv_df.columns:
                vv_peak_idx = int(flam_result_vv_df["Total Gas (v/v%)"].idxmax())
                print(
                    f"DEBUG: dataframe_peak_total_vv={float(flam_result_vv_df['Total Gas (v/v%)'].iloc[vv_peak_idx]):.8f}% "
                    f"at t={int(flam_result_vv_df['Time (s)'].iloc[vv_peak_idx])}s"
                )
            if "Total Gas (mg/L)" in flam_result_mgl_df.columns:
                mgl_peak_idx = int(flam_result_mgl_df["Total Gas (mg/L)"].idxmax())
                print(
                    f"DEBUG: dataframe_peak_total_mgl={float(flam_result_mgl_df['Total Gas (mg/L)'].iloc[mgl_peak_idx]):.8f} "
                    f"at t={int(flam_result_mgl_df['Time (s)'].iloc[mgl_peak_idx])}s"
                )

            # --- Le Chatelier LFL curve (optional) ---
            adjusted_le_chatelier_lfl = None
            lfl_curve_label = None
            if use_le_chatelier:
                names, rows = resolve_lfl_curve_labels(valid_gas_labels)
                if names:
                    conc_flam = vv_concentrations[rows, :]
                    total_flam_conc = conc_flam.sum(axis=0)
                    lfl_lookup = {"co": individual_lfls[0], "h2": individual_lfls[1], "total_hydrocarbons": individual_lfls[2]}
                    used_lfls = np.array([lfl_lookup[name] for name in names], dtype=float)
                    adjusted_le_chatelier_lfl = np.full(num_steps, np.nan)
                    active_mask = total_flam_conc > 0
                    if np.any(active_mask):
                        fracs = conc_flam[:, active_mask] / total_flam_conc[active_mask]
                        inv_lfls = np.where(used_lfls > 0, 1.0 / used_lfls, 0.0)
                        denominator = inv_lfls @ fracs
                        valid_denom = denominator > 0
                        active_indices = np.where(active_mask)[0]
                        valid_indices = active_indices[valid_denom]
                        lfl_mix = 1.0 / denominator[valid_denom]

                        # Dilute the mixture LFL when CO2 is present alongside the flammable gases.
                        total_offgas = total_flam_conc[valid_indices] + co2_conc_arr[valid_indices]
                        co2_frac = np.where(total_offgas > 0, co2_conc_arr[valid_indices] / total_offgas, 0.0)
                        needs_correction = (co2_frac > 0) & (co2_frac < 1.0)
                        inert_ratio = np.where(needs_correction, co2_frac / (1.0 - co2_frac), 0.0)
                        adjusted_lfl = lfl_mix * (100.0 - lfl_mix - (1.0 - k_co2) * inert_ratio * lfl_mix) / (100.0 - lfl_mix)
                        adjusted_lfl = np.where(needs_correction, adjusted_lfl, lfl_mix)
                        adjusted_le_chatelier_lfl[valid_indices] = adjusted_lfl
                    lfl_curve_label = "Temperature-adjusted Le Chatelier LFL" if use_temp_dependent_lfl else "Le Chatelier LFL"
                    print(f"DEBUG: le_chatelier_names={names}")
                    print(f"DEBUG: le_chatelier_used_lfls={np.array2string(used_lfls, precision=8)}")
                if adjusted_le_chatelier_lfl is not None:
                    flam_result_vv_df["Le Chatelier LFL (v/v%)"] = adjusted_le_chatelier_lfl
                    finite_lfl = adjusted_le_chatelier_lfl[np.isfinite(adjusted_le_chatelier_lfl)]
                    if finite_lfl.size > 0:
                        print(
                            f"DEBUG: le_chatelier_curve_stats min={float(np.min(finite_lfl)):.8f}, "
                            f"max={float(np.max(finite_lfl)):.8f}, mean={float(np.mean(finite_lfl)):.8f}"
                        )
                    else:
                        print("DEBUG: le_chatelier_curve_stats no finite values")

            # --- Max failing modules before LFL threshold ---
            combined_gas_percent = sum(float(data.get(label, 0)) / 100.0 for label in ["co_(%)", "h2_(%)", "total_hydrocarbons_(%)"])
            lfl_value = (inputs.lfl_percent * room_vol) / 100.0 if room_vol > 0 else 0
            print(
                f"DEBUG: threshold_inputs combined_gas_percent={combined_gas_percent:.8f}, "
                f"lfl_value_m3={lfl_value:.8f}, threshold_lfl_percent={inputs.lfl_percent}"
            )
            modules_required = modules_required_constant_flow(
                inputs.total_duration, inputs.time_step, inputs.propagation_delay, mod_duration,
                mod_flowrate * combined_gas_percent, room_vol, adj_ventilation_rate, lfl_value,
            )
            max_modules = max_modules_before_threshold(modules_required)
            print(
                f"DEBUG: module_threshold_result modules_required={modules_required}, "
                f"max_modules_before_threshold={max_modules}"
            )

            flam_scenario_results[scenario_name] = {
                "flam_vv_df": flam_result_vv_df,
                "flam_mgl_df": flam_result_mgl_df,
                "flam_max_mod": {"total_gas": max_modules if modules_required is not None else "NA - Exceeds Calc Limit"},
                "calc_method": calc_method,
                "input": data,
                "use_le_chatelier": use_le_chatelier,
                "use_temp_dependent_lfl": use_temp_dependent_lfl,
                "le_chatelier_lfl_array": adjusted_le_chatelier_lfl if use_le_chatelier else None,
                "lfl_curve_array": adjusted_le_chatelier_lfl if use_le_chatelier else None,
                "lfl_curve_label": lfl_curve_label,
            }
            print(
                f"DEBUG: scenario_result_saved scenario={scenario_name}, "
                f"flam_max_mod={flam_scenario_results[scenario_name]['flam_max_mod']}"
            )
            print("--- DEBUG: Scenario END ---")
        except ZeroDivisionError:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed: Division by zero encountered.\nPlease check the input values.")
            return
        except Exception as exc:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed with an unexpected error:\n{exc}")
            return

    if module_capacity_overrides:
        print(f"DEBUG: module_capacity_overrides={module_capacity_overrides}")
        override_list = "\n".join(f"• {item}" for item in module_capacity_overrides)
        QMessageBox.warning(
            parent,
            "Module Capacity Limited",
            "Module Capacity is limited to modules at or below 1 kWh.\n"
            "The following scenario(s) exceeded that limit and were calculated using Cell Volume UL9540A instead:\n\n"
            f"{override_list}",
        )

    print(f"DEBUG: total_scenarios_saved={len(flam_scenario_results)}")
    print("=== DEBUG: flammability_assessment_calc END ===\n")
    display_flammability_result_popup(flam_scenario_results, None, gas_data, bat_data, parent=parent)


# Run the graphical flowrate-based flammability model for LIB datasets that
# provide a time-series release profile rather than a single scalar release.
def flammability_assessment_calc_graphical_method(parent, state, display_flammability_result_popup, gas_data, bat_data, flam_gasses_labels, scenario_data=None, clear_existing=True):
    """Fallback implementation for the graphical flowrate method."""
    """
    Flammability calculation using time-varying flowrate data from imported Excel file.
    Uses per-second flowrate arrays instead of constant module volume method.
    """
    gas_labels = ["co", "h2", "total_hydrocarbons", "co2"]
    num_gases = len(gas_labels)
    default_flowrate_data = getattr(state, "gas_flowrate_data", None)

    flam_scenario_results = getattr(state, "flam_scenario_results", None)
    if flam_scenario_results is None:
        flam_scenario_results = {}
        state.flam_scenario_results = flam_scenario_results
    if clear_existing:
        flam_scenario_results.clear()

    scenarios = _iter_scenarios(state, scenario_data)
    has_any_flowrate_data = bool(default_flowrate_data) or any(
        isinstance(data, dict) and isinstance(data.get("_lib_flowrate_data"), dict)
        for _, data in scenarios
    )
    if not has_any_flowrate_data:
        QMessageBox.critical(
            parent,
            "Missing Data",
            "Gas flowrate data has not been imported for any selected LIB.\n"
            "Open 'Add LIB' and use 'Import Flowrate Data' to attach a dataset.",
        )
        return

    for scenario_name, data in scenarios:
        try:
            scenario_flowrate_data = data.get("_lib_flowrate_data") if isinstance(data, dict) else None
            if not isinstance(scenario_flowrate_data, dict):
                scenario_flowrate_data = default_flowrate_data
            if not isinstance(scenario_flowrate_data, dict):
                QMessageBox.critical(
                    parent,
                    "Missing Data",
                    f"{scenario_name} is set to 'Module Variable Flowrate' but has no flowrate dataset attached to its LIB.",
                )
                return

            missing_labels = [label for label in gas_labels if label not in scenario_flowrate_data]
            if missing_labels:
                QMessageBox.critical(
                    parent,
                    "Invalid Flowrate Data",
                    f"{scenario_name} is missing required flowrate gas columns: {', '.join(missing_labels)}.",
                )
                return

            flowrate_matrix = np.array([scenario_flowrate_data[label] for label in gas_labels], dtype=float)
            if flowrate_matrix.ndim != 2 or flowrate_matrix.shape[1] == 0:
                QMessageBox.critical(
                    parent,
                    "Invalid Flowrate Data",
                    f"{scenario_name} has empty or invalid flowrate data.",
                )
                return
            mod_duration = flowrate_matrix.shape[1]
            combined_flam_flowrates = flowrate_matrix[0] + flowrate_matrix[1] + flowrate_matrix[2]

            inputs = _parse_scenario_inputs(data)
            total_duration = inputs.total_duration
            time_step = inputs.time_step
            ventilation_rate = inputs.ventilation_rate
            room_height = inputs.room_height
            room_area = inputs.room_area
            modules = inputs.modules
            equip_space = inputs.equip_space
            units = inputs.units
            lfl_percent = inputs.lfl_percent
            propagation_delay = inputs.propagation_delay
            vent_switch_conc = inputs.vent_switch_conc
            emergency_vent_rate = inputs.emergency_vent_rate
            k_co2 = 1.5

            # Le Chatelier's LFL option
            use_le_chatelier = _coerce_bool(
                data.get("Use Le Chatelier LFL"),
                _bool_state_value(state, "use_le_chatelier_lfl", False),
            )
            use_temp_dependent_lfl = _coerce_bool(
                data.get("Use Temperature Dependent LFL"),
                _bool_state_value(state, "use_temp_dependent_lfl", False),
            )

            # Individual LFL values (% v/v)
            individual_lfls = np.zeros(3)
            for idx, flam_label in enumerate(["co", "h2", "total_hydrocarbons"]):
                lfl_val = gas_data.get(flam_label, {}).get("lfl", 0)
                individual_lfls[idx] = lfl_val if lfl_val and lfl_val > 0 else 0

            # Temperature-dependent LFL adjustment
            if use_le_chatelier and use_temp_dependent_lfl:
                venting_temp = inputs.venting_temperature
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
            emergency_vent_state = init_emergency_ventilation(
                ventilation_rate,
                emergency_vent_rate,
                room_area,
                room_vol,
                vent_switch_conc,
            )
            total_vent_outflow = emergency_vent_state["current_outflow"]

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
                        start_time = int(1 + delay_count * propagation_delay)
                        count = min(MODULES_PER_DELAY, remaining)
                        module_groups.append((start_time, count))
                        remaining -= count
                        delay_count += 1

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

                trigger_conc = float(np.sum(current_conc[:3]))
                total_vent_outflow = maybe_activate_emergency_ventilation(
                    emergency_vent_state,
                    trigger_conc,
                    time[step_idx],
                    "Total Flammable Gas",
                )

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
            lfl_curve_label = None
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

                lfl_curve_label = "Temperature-adjusted Le Chatelier LFL" if use_temp_dependent_lfl else "Le Chatelier LFL"
                flam_result_vv_df["Le Chatelier LFL (v/v%)"] = adjusted_le_chatelier_lfl
                print(f"Le Chatelier's LFL range: {np.nanmin(adjusted_le_chatelier_lfl):.4f}% - {np.nanmax(adjusted_le_chatelier_lfl):.4f}%")
            elif use_temp_dependent_lfl:
                print("Temperature-dependent LFL is enabled without Le Chatelier; standard user LFL threshold remains unchanged.")

    # === Max module calculation using shared threshold solver ===
            lfl_value = (lfl_percent * room_vol) / 100
            modules_required = modules_required_flow_profile(
                total_duration,
                time_step,
                propagation_delay,
                combined_flam_flowrates,
                room_vol,
                adj_ventilation_rate,
                lfl_value,
            )
            flam_max_mods_val = (
                max_modules_before_threshold(modules_required)
                if modules_required is not None
                else 'NA - Exceeds Calc Limit'
            )
            flam_max_mods = {"total_gas": flam_max_mods_val}

            # === Save results ===
            flam_scenario_results[scenario_name] = {
                "flam_vv_df": flam_result_vv_df,
                "flam_mgl_df": flam_result_mgl_df,
                "flam_max_mod": flam_max_mods,
                "input": data,
                "use_le_chatelier": use_le_chatelier,
                "use_temp_dependent_lfl": use_temp_dependent_lfl,
                "le_chatelier_lfl_array": adjusted_le_chatelier_lfl if use_le_chatelier else None,
                "lfl_curve_array": adjusted_le_chatelier_lfl if use_le_chatelier else None,
                "lfl_curve_label": lfl_curve_label,
            }
        except ZeroDivisionError:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed: Division by zero encountered.\nPlease check the input values.")
            return
        except Exception as e:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed with an unexpected error:\n{e}")
            return

    # Display results
    display_flammability_result_popup(flam_scenario_results, None, gas_data, bat_data, parent=parent)


