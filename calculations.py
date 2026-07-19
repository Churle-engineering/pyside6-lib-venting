import re
import numpy as np
import math
import pandas as pd
from scipy.signal import lfilter
from PySide6.QtWidgets import QMessageBox

from information import (
    BATTERY_CHEMISTRY_DATA,
    CHEMICAL_PROPERTIES,
    MODULES_PER_DELAY,
    CALCULATION_METHODS,
    COMBINED_INPUTS,
    FIRE_PROPERTIES,
    get_specific_capacity,
    CO_TEMPERATURE_LFL_PARAMETER_A,
    CO_TEMPERATURE_LFL_PARAMETER_B,
    H2_TEMPERATURE_LFL_PARAMETER_A,
    H2_TEMPERATURE_LFL_PARAMETER_B,
    THC_TEMPERATURE_LFL_PARAMETER_A,
    THC_TEMPERATURE_LFL_PARAMETER_B,
)


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

    aliases = {
        "carbon_monoxide": "co",
        "hydrogen": "h2",
        "carbon_dioxide": "co2",
        "co2": "co2",
        "total_hydrocarbon": "total_hydrocarbons",
        "total_hydrocarbons": "total_hydrocarbons",
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

    if isinstance(scenario_data, np.ndarray):
        if scenario_data.dtype.names is not None:
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
            elif isinstance(row, (list, tuple)):
                data = {
                    header: row[i]
                    for i, header in enumerate(COMBINED_INPUTS[: len(row)])
                }
            else:
                data = {"value": row}
            rows.append((f"Scenario {idx + 1}", data))
        return rows

    return []


def _parse_scenario_inputs(data, propagation_delay_default=0.0):
    """Convert one spreadsheet row into the shared calculation input shape."""
    def number(column, *aliases, default=0.0):
        for label in (column, *aliases):
            if label in data:
                return _coerce_scalar(data[label], default)
        return default

    return {
        "total_duration": int(number("Calculation Duration (s)")),
        "time_step": int(number("Time Step (s)", default=1.0)),
        "ventilation_rate": number("Ventilation Rate (L/s/m2)"),
        "room_height": number("Room Height (m)"),
        "room_area": number("Room Area (m2)"),
        "equip_space": number("Equipment Space (%)"),
        "cell_volume": number("cell_volume_(l)"),
        "cell_duration": number("cell_duration_(s)"),
        "module_volume": number("module_volume_(l)"),
        "module_duration": number("module_duration_(s)"),
        "cells": number("Cells per module", "Cells per"),
        "modules": number("Modules per unit", "Modules per"),
        "units": number("Units"),
        "lfl_percent": number("LFL (%)", "lfl_(%)"),
        "propagation_delay": number(
            "Module Propagation Delay (s)", default=propagation_delay_default
        ),
        "module_capacity": number("module_capacity_(kwh)"),
        "vent_switch_conc": number("Vent Switch Conc (%)"),
        "emergency_vent_rate": number("Emergency Vent Rate (L/s/m2)"),
        "co2_percent": number("co2_(%)", "CO2 (%)") / 100.0,
        "venting_temperature": number("venting_temperature_(°c)"),
        "lib_type": str(data.get("LIB Type", "NMC") or "NMC"),
    }


def calc_active_modules_array(time_array, total_mods, propagation_delay, mod_duration, modules_per_delay=MODULES_PER_DELAY):
    """Vectorized module activity profile for the simulation."""
    active = np.zeros(len(time_array), dtype=np.float64)
    mask = time_array > 0
    t_pos = time_array[mask]

    if propagation_delay > 0:
        intervals_passed = (t_pos // propagation_delay).astype(np.int64)
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


def determine_calc_method(mod_capacity, user_selected_method):
    if user_selected_method == "Module Variable Flowrate":
        return "Module Variable Flowrate", False
    if user_selected_method == "Module Volume UL9540A":
        return "Module Volume UL9540A", False
    if mod_capacity > 1:
        was_overridden = user_selected_method == "Module Capacity"
        return "Cell Volume UL9540A", was_overridden
    return user_selected_method, False


def calc_module_volume(calc_method, lib_type, mod_capacity, cells, cell_volume, module_volume=0):
    if calc_method == "Module Volume UL9540A":
        return module_volume / 1000.0
    if calc_method == "Module Capacity":
        specific_capacity = get_specific_capacity(lib_type)
        return (specific_capacity * mod_capacity) / 1000.0
    return cells * cell_volume / 1000.0


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

    return (
        gas_labels,
        np.array(gas_percents, dtype=float),
        np.array(densities, dtype=float),
    )


def resolve_target_gas_index(valid_gas_labels, state):
    target_gas_map = {"CO": "co", "H2": "h2", "Total Hydrocarbons": "total_hydrocarbons"}
    selected_target = _resolve_state_value(state, "selected_target_flam_gas", "CO")
    if selected_target is None:
        selected_target = "CO"

    target_gas_key = target_gas_map.get(str(selected_target), "co")
    for idx, label in enumerate(valid_gas_labels):
        if normalize_gas_key(label) == target_gas_key:
            return selected_target, idx

    return selected_target, None


def setup_emergency_ventilation(vent_switch_conc, emergency_vent_rate, room_area):
    adj_emergency_vent_rate = (emergency_vent_rate / 1000.0) * room_area if emergency_vent_rate > 0 else 0
    emergency_vent_enabled = vent_switch_conc > 0 and emergency_vent_rate > 0
    return adj_emergency_vent_rate, emergency_vent_enabled


def run_max_modules_binary_search(total_duration, time_step, propagation_delay, mod_duration, mod_flowrate, gas_percent, room_vol, adj_ventilation_rate, threshold_value, modules_per_delay=MODULES_PER_DELAY):
    vent_coeff = adj_ventilation_rate / room_vol if room_vol > 0 else 0
    alpha = 1.0 - vent_coeff * time_step
    time_array = np.arange(0, total_duration + 1, time_step)

    low = 1
    high = 100000
    max_modules = None

    while low <= high:
        mid = (low + high + 1) // 2
        active_array = calc_active_modules_array(time_array, mid, propagation_delay, mod_duration, modules_per_delay)
        inflow_signal = active_array * mod_flowrate * gas_percent * time_step
        gas_array = lfilter([1.0], [1.0, -alpha], inflow_signal)
        gas_array = np.maximum(gas_array, 0.0)

        if np.any(gas_array >= threshold_value):
            high = mid - 1
        else:
            max_modules = mid
            low = mid + 1

    return max_modules


def toxicity_assessment_calc(parent, state, display_toxicity_result_popup, gas_data, scenario_data=None):
    tox_scenario_results = getattr(state, "tox_scenario_results", None)
    if tox_scenario_results is None:
        tox_scenario_results = {}
        setattr(state, "tox_scenario_results", tox_scenario_results)
    tox_scenario_results.clear()

    scenarios = _iter_scenarios(state, scenario_data)
    if not scenarios:
        display_toxicity_result_popup(tox_scenario_results, None, [], gas_data)
        return

    for scenario_name, data in scenarios:
        try:
            inputs = _parse_scenario_inputs(data, propagation_delay_default=180.0)
            total_duration = inputs["total_duration"]
            time_step = inputs["time_step"]
            ventilation_rate = inputs["ventilation_rate"]
            room_height = inputs["room_height"]
            room_area = inputs["room_area"]
            equip_space = inputs["equip_space"]
            vol_battery = inputs["cell_volume"]
            cell_duration = inputs["cell_duration"]
            module_volume = inputs["module_volume"]
            module_duration = inputs["module_duration"]
            cells = inputs["cells"]
            modules = inputs["modules"]
            units = inputs["units"]
            lib_type = inputs["lib_type"]
            propagation_delay = inputs["propagation_delay"]
            mod_capacity = inputs["module_capacity"]
            vent_switch_conc = inputs["vent_switch_conc"]
            emergency_vent_rate = inputs["emergency_vent_rate"]

            user_selected_method = _resolve_state_value(state, "selected_calc_method", "Cell Volume UL9540A")
            calc_method, was_overridden = determine_calc_method(mod_capacity, user_selected_method)
            print(f"Toxicity - Using calculation method: {calc_method}")

            mod_vol = calc_module_volume(calc_method, lib_type, mod_capacity, cells, vol_battery, module_volume)
            if calc_method == "Module Volume UL9540A":
                if room_height == 0 or room_area == 0 or module_duration == 0:
                    raise ValueError("Module Volume UL9540A requires room dimensions and module duration")
                if module_volume == 0:
                    raise ValueError("Module volume is zero")
            else:
                if room_height == 0 or room_area == 0 or cell_duration == 0:
                    raise ValueError("Cell-based methods require room dimensions and cell duration")
                if calc_method == "Module Capacity" and mod_capacity == 0:
                    raise ValueError("Module capacity is zero")
                if calc_method != "Module Capacity" and vol_battery == 0:
                    raise ValueError("Cell volume is zero")

            lib_type_upper = str(lib_type).upper() if isinstance(lib_type, str) else str(lib_type).upper()
            chemistry_data = BATTERY_CHEMISTRY_DATA.get(lib_type_upper, BATTERY_CHEMISTRY_DATA.get("NMC", {}))
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
            adj_emergency_vent_rate, emergency_vent_enabled = setup_emergency_ventilation(vent_switch_conc, emergency_vent_rate, room_area)
            emergency_vent_activated = False

            if calc_method == "Module Volume UL9540A":
                battery_duration = module_duration
            else:
                battery_duration = cell_duration
            if battery_duration <= 0:
                battery_duration = 1

            room_vol = room_height * room_area * (1 - (equip_space / 100.0))
            total_mods = modules * units
            mod_duration = battery_duration
            total_vent_outflow = adj_ventilation_rate / room_vol if room_vol > 0 else 0

            percent_tox = chemistry_data.get("percent_tox", 100)
            tox_mod_vol = mod_vol * (percent_tox / 100.0)
            mod_flowrate = tox_mod_vol / mod_duration if mod_duration > 0 else 0

            target_gas_name, target_gas_index = resolve_target_gas_index(valid_gas_labels, state)
            active_modules_arr = calc_active_modules_array(time, total_mods, propagation_delay, mod_duration)

            for step_idx in range(num_steps):
                current_total_bat_flow = active_modules_arr[step_idx] * mod_flowrate
                inflows = current_total_bat_flow * gas_percents
                outflows = total_vent_outflow * prev_gas
                gases += (inflows - outflows) * time_step
                gases = np.maximum(gases, 0.0)
                prev_gas[:] = gases

                current_conc = (gases / room_vol) * 100.0 if room_vol > 0 else np.zeros_like(gases)
                concentrations[:, step_idx] = current_conc
                mgl_concentrations[:, step_idx] = (current_conc / 100.0) * densities * 1000.0

                if emergency_vent_enabled and not emergency_vent_activated:
                    trigger_conc = current_conc[target_gas_index] if target_gas_index is not None else np.sum(current_conc)
                    if trigger_conc >= vent_switch_conc:
                        emergency_vent_activated = True
                        total_vent_outflow = adj_emergency_vent_rate / room_vol if room_vol > 0 else 0
                        print(f"Emergency ventilation activated at t={time[step_idx]}s ({target_gas_name}: {trigger_conc:.4f}%)")

            mgl_data = {"Time (s)": time}
            vv_data = {"Time (s)": time}
            for idx, label in enumerate(valid_gas_labels):
                mgl_data[f"{label} (mg/L)"] = mgl_concentrations[idx, :]
                vv_data[f"{label} (v/v%)"] = concentrations[idx, :]

            tox_result_mgl_df = pd.DataFrame(mgl_data)
            tox_result_vv_df = pd.DataFrame(vv_data)
            tox_result_mgl_df["Total Gas (mg/L)"] = tox_result_mgl_df[[c for c in tox_result_mgl_df.columns if c != "Time (s)" and c != "Total Gas (mg/L)"]].sum(axis=1)
            tox_result_vv_df["Total Gas (ppm)"] = tox_result_vv_df[[c for c in tox_result_vv_df.columns if c != "Time (s)" and c != "Total Gas (ppm)"]].sum(axis=1)

            tox_max_mods = {}
            for idx, label in enumerate(valid_gas_labels):
                gas_percent = gas_percents[idx]
                threshold_value = (gas_percent * room_vol) / 100.0
                max_modules = run_max_modules_binary_search(
                    total_duration,
                    time_step,
                    propagation_delay,
                    mod_duration,
                    mod_flowrate,
                    gas_percent,
                    room_vol,
                    adj_ventilation_rate,
                    threshold_value,
                )
                tox_max_mods[label] = max_modules if max_modules is not None else "NA - Exceeds Calc Limit"

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


def flammability_assessment_calc(parent, state, display_flammability_result_popup, gas_data, bat_data, flam_gasses_labels, scenario_data=None):
    print("DEBUG: Entered flammability_assessment_calc")
    flam_scenario_results = getattr(state, "flam_scenario_results", None)
    if flam_scenario_results is None:
        flam_scenario_results = {}
        setattr(state, "flam_scenario_results", flam_scenario_results)
    flam_scenario_results.clear()

    scenarios = _iter_scenarios(state, scenario_data)
    print(f"DEBUG: Found {len(scenarios)} flammability scenario(s)")
    if not scenarios:
        print("DEBUG: No flammability scenarios available; calling popup with empty results")
        display_flammability_result_popup(flam_scenario_results, None, gas_data, bat_data, parent=parent)
        return

    for scenario_name, data in scenarios:
        try:
            inputs = _parse_scenario_inputs(data)
            total_duration = inputs["total_duration"]
            time_step = inputs["time_step"]
            ventilation_rate = inputs["ventilation_rate"]
            room_height = inputs["room_height"]
            room_area = inputs["room_area"]
            cell_vol_battery = inputs["cell_volume"]
            cell_duration = inputs["cell_duration"]
            module_volume = inputs["module_volume"]
            module_duration = inputs["module_duration"]
            modules = inputs["modules"]
            equip_space = inputs["equip_space"]
            units = inputs["units"]
            cells = inputs["cells"]
            lfl_percent = inputs["lfl_percent"]
            propagation_delay = inputs["propagation_delay"]
            lib_type = inputs["lib_type"]
            mod_capacity = inputs["module_capacity"]
            vent_switch_conc = inputs["vent_switch_conc"]
            emergency_vent_rate = inputs["emergency_vent_rate"]
            co2_percent = inputs["co2_percent"]

            user_selected_method = _resolve_state_value(state, "selected_calc_method", "Cell Volume UL9540A")
            calc_method, _ = determine_calc_method(mod_capacity, user_selected_method)
            use_le_chatelier = _bool_state_value(state, "use_le_chatelier_lfl", False)
            use_temp_dependent_lfl = _bool_state_value(state, "use_temp_dependent_lfl", False)
            print(f"DEBUG: LFL options enabled -> le_chatelier={use_le_chatelier}, temp_dependent={use_temp_dependent_lfl}")

            individual_lfls = np.zeros(3, dtype=float)
            for idx, flam_label in enumerate(["co", "h2", "total_hydrocarbons"]):
                lfl_val = gas_data.get(flam_label, {}).get("lfl", 0)
                individual_lfls[idx] = lfl_val if lfl_val and lfl_val > 0 else 0

            if use_temp_dependent_lfl:
                venting_temp = inputs["venting_temperature"]
                if venting_temp > 0:
                    temp_lfls = [
                        CO_TEMPERATURE_LFL_PARAMETER_A * venting_temp + CO_TEMPERATURE_LFL_PARAMETER_B,
                        H2_TEMPERATURE_LFL_PARAMETER_A * venting_temp + H2_TEMPERATURE_LFL_PARAMETER_B,
                        THC_TEMPERATURE_LFL_PARAMETER_A * venting_temp + THC_TEMPERATURE_LFL_PARAMETER_B,
                    ]
                    for idx, temp_lfl in enumerate(temp_lfls):
                        if temp_lfl > 0:
                            individual_lfls[idx] = temp_lfl

            mod_vol = calc_module_volume(calc_method, lib_type, mod_capacity, cells, cell_vol_battery, module_volume)
            if calc_method == "Module Volume UL9540A":
                if room_height == 0 or room_area == 0 or module_duration == 0:
                    raise ValueError("Module Volume UL9540A requires room dimensions and module duration")
                if module_volume == 0:
                    raise ValueError("Module volume is zero")
            else:
                if room_height == 0 or room_area == 0 or cell_duration == 0:
                    raise ValueError("Cell-based methods require room dimensions and cell duration")
                if calc_method == "Module Capacity" and mod_capacity == 0:
                    raise ValueError("Module capacity is zero")
                if calc_method != "Module Capacity" and cell_vol_battery == 0:
                    raise ValueError("Cell volume is zero")

            gas_input_pairs = resolve_flammable_gas_inputs(data)
            valid_gas_labels = [label for label, _ in gas_input_pairs]
            gas_percents = np.array([float(data.get(label, 0)) / 100.0 for label, _ in gas_input_pairs], dtype=float)
            density_result = validate_densities(
                valid_gas_labels,
                gas_percents,
                gas_data,
                normalize_fn=normalize_gas_key,
            )
            if density_result is None:
                raise ValueError("No flammable gases with valid density data were found")
            valid_gas_labels, gas_percents, densities = density_result
            num_gases = len(valid_gas_labels)

            num_steps = (total_duration // time_step) + 1
            vv_concentrations = np.zeros((num_gases, num_steps), dtype=float)
            mgl_concentrations = np.zeros((num_gases, num_steps), dtype=float)
            gases = np.zeros(num_gases, dtype=float)
            prev_gas = np.zeros(num_gases, dtype=float)
            time = np.arange(0, total_duration + 1, time_step)

            co2_conc_arr = np.zeros(num_steps, dtype=float)
            co2_gas = 0.0
            co2_prev = 0.0

            if calc_method == "Module Volume UL9540A":
                mod_duration = module_duration
            else:
                mod_duration = cell_duration
            if mod_duration <= 0:
                mod_duration = 1

            room_vol = room_height * room_area * (1 - (equip_space / 100.0))
            flam_percentage = BATTERY_CHEMISTRY_DATA.get(str(lib_type).upper(), {}).get("percent_flam", 100) / 100.0
            flam_mod_vol = mod_vol * flam_percentage
            mod_flowrate = flam_mod_vol / mod_duration if mod_duration > 0 else 0
            total_mods = modules * units
            adj_ventilation_rate = (ventilation_rate / 1000.0) * room_area
            adj_emergency_vent_rate, emergency_vent_enabled = setup_emergency_ventilation(vent_switch_conc, emergency_vent_rate, room_area)
            emergency_vent_activated = False
            total_vent_outflow = adj_ventilation_rate / room_vol if room_vol > 0 else 0

            target_gas_name, target_gas_index = resolve_target_gas_index(valid_gas_labels, state)
            active_modules_arr = calc_active_modules_array(time, total_mods, propagation_delay, mod_duration)

            for step_idx in range(num_steps):
                current_total_bat_flow = active_modules_arr[step_idx] * mod_flowrate
                inflows = current_total_bat_flow * gas_percents
                outflows = total_vent_outflow * prev_gas
                gases += (inflows - outflows) * time_step
                gases = np.maximum(gases, 0.0)
                prev_gas[:] = gases

                current_conc = (gases / room_vol) * 100.0 if room_vol > 0 else np.zeros_like(gases)
                vv_concentrations[:, step_idx] = current_conc
                mgl_concentrations[:, step_idx] = (current_conc / 100.0) * densities * 1000.0

                co2_inflow = current_total_bat_flow * co2_percent
                co2_outflow = total_vent_outflow * co2_prev
                co2_gas = max(co2_gas + (co2_inflow - co2_outflow) * time_step, 0.0)
                co2_prev = co2_gas
                co2_conc_arr[step_idx] = (co2_gas / room_vol) * 1.0 if room_vol > 0 else 0.0

                if emergency_vent_enabled and not emergency_vent_activated:
                    trigger_conc = current_conc[target_gas_index] if target_gas_index is not None else np.sum(current_conc)
                    if trigger_conc >= vent_switch_conc:
                        emergency_vent_activated = True
                        total_vent_outflow = adj_emergency_vent_rate / room_vol if room_vol > 0 else 0
                        print(f"Emergency ventilation activated at t={time[step_idx]}s ({target_gas_name}: {trigger_conc:.4f}%)")

            flam_result_vv_df = pd.DataFrame({"Time (s)": time})
            flam_result_mgl_df = pd.DataFrame({"Time (s)": time})
            for idx, label in enumerate(valid_gas_labels):
                base_label = strip_unit_suffix(label)
                flam_result_vv_df[f"{base_label} (v/v%)"] = vv_concentrations[idx, :]
                flam_result_mgl_df[f"{base_label} (mg/L)"] = mgl_concentrations[idx, :]

            if all(col in flam_result_vv_df.columns for col in ["co (v/v%)", "h2 (v/v%)", "total_hydrocarbons (v/v%)"]):
                flam_result_vv_df["Total Gas (v/v%)"] = flam_result_vv_df[["co (v/v%)", "h2 (v/v%)", "total_hydrocarbons (v/v%)"]].sum(axis=1)
            if all(col in flam_result_mgl_df.columns for col in ["co (mg/L)", "h2 (mg/L)", "total_hydrocarbons (mg/L)"]):
                flam_result_mgl_df["Total Gas (mg/L)"] = flam_result_mgl_df[["co (mg/L)", "h2 (mg/L)", "total_hydrocarbons (mg/L)"]].sum(axis=1)

            adjusted_le_chatelier_lfl = None
            lfl_curve_label = None
            if use_le_chatelier or use_temp_dependent_lfl:
                if use_le_chatelier:
                    names, rows = resolve_lfl_curve_labels(valid_gas_labels)
                    if names:
                        conc_flam = vv_concentrations[rows, :]
                        total_flam_conc = conc_flam.sum(axis=0)
                        lfl_lookup = {
                            "co": individual_lfls[0],
                            "h2": individual_lfls[1],
                            "total_hydrocarbons": individual_lfls[2],
                        }
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
                            adjusted_le_chatelier_lfl[valid_indices] = lfl_mix
                        lfl_curve_label = "Temperature-adjusted LFL" if use_temp_dependent_lfl else "Le Chatelier LFL"
                        print(f"DEBUG: LFL curve generated; finite points={np.isfinite(adjusted_le_chatelier_lfl).sum()} label={lfl_curve_label}")
                elif use_temp_dependent_lfl:
                    adjusted_le_chatelier_lfl = np.full(num_steps, float(lfl_percent), dtype=float)
                    lfl_curve_label = "Temperature-adjusted LFL"

                if adjusted_le_chatelier_lfl is not None:
                    flam_result_vv_df["Le Chatelier LFL (v/v%)"] = adjusted_le_chatelier_lfl

            combined_gas_percent = sum(float(data.get(label, 0)) / 100.0 for label in ["co_(%)", "h2_(%)", "total_hydrocarbons_(%)"])
            lfl_value = (lfl_percent * room_vol) / 100.0 if room_vol > 0 else 0
            max_modules = run_max_modules_binary_search(
                total_duration,
                time_step,
                propagation_delay,
                mod_duration,
                mod_flowrate,
                combined_gas_percent,
                room_vol,
                adj_ventilation_rate,
                lfl_value,
            )

            flam_max_mods = {"total_gas": max_modules if max_modules is not None else "NA - Exceeds Calc Limit"}
            flam_scenario_results[scenario_name] = {
                "flam_vv_df": flam_result_vv_df,
                "flam_mgl_df": flam_result_mgl_df,
                "flam_max_mod": flam_max_mods,
                "calc_method": calc_method,
                "input": data,
                "use_le_chatelier": use_le_chatelier,
                "use_temp_dependent_lfl": use_temp_dependent_lfl,
                "le_chatelier_lfl_array": adjusted_le_chatelier_lfl if (use_le_chatelier or use_temp_dependent_lfl) else None,
                "lfl_curve_array": adjusted_le_chatelier_lfl if (use_le_chatelier or use_temp_dependent_lfl) else None,
                "lfl_curve_label": lfl_curve_label,
            }
        except ZeroDivisionError:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed: Division by zero encountered.\nPlease check the input values.")
            return
        except Exception as exc:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed with an unexpected error:\n{exc}")
            return

    display_flammability_result_popup(flam_scenario_results, None, gas_data, bat_data, parent=parent)


def flammability_assessment_calc_graphical_method(parent, state, display_flammability_result_popup, gas_data, bat_data, flam_gasses_labels, scenario_data=None):
    """Fallback implementation for the graphical flowrate method."""
    """
    Flammability calculation using time-varying flowrate data from imported Excel file.
    Uses per-second flowrate arrays instead of constant module volume method.
    """
    if not hasattr(state, 'gas_flowrate_data') or state.gas_flowrate_data is None:
        QMessageBox.critical(parent, "Missing Data", "Gas flowrate data has not been imported.\nPlease use the 'Import Flowrate Data' button first.")
        return

    # Setup flowrate data
    gas_labels = ["co", "h2", "total_hydrocarbons", "co2"]
    num_gases = len(gas_labels)
    flowrate_matrix = np.array([state.gas_flowrate_data[label] for label in gas_labels])
    mod_duration = flowrate_matrix.shape[1]
    combined_flam_flowrates = flowrate_matrix[0] + flowrate_matrix[1] + flowrate_matrix[2]

    flam_scenario_results = getattr(state, "flam_scenario_results", None)
    if flam_scenario_results is None:
        flam_scenario_results = {}
        setattr(state, "flam_scenario_results", flam_scenario_results)
    flam_scenario_results.clear()

    scenarios = _iter_scenarios(state, scenario_data)

    for scenario_name, data in scenarios:
        try:
            inputs = _parse_scenario_inputs(data)
            total_duration = inputs["total_duration"]
            time_step = inputs["time_step"]
            ventilation_rate = inputs["ventilation_rate"]
            room_height = inputs["room_height"]
            room_area = inputs["room_area"]
            modules = inputs["modules"]
            equip_space = inputs["equip_space"]
            units = inputs["units"]
            lfl_percent = inputs["lfl_percent"]
            propagation_delay = inputs["propagation_delay"]
            vent_switch_conc = inputs["vent_switch_conc"]
            emergency_vent_rate = inputs["emergency_vent_rate"]
            k_co2 = 1.5

            # Le Chatelier's LFL option
            use_le_chatelier = _bool_state_value(state, "use_le_chatelier_lfl", False)
            use_temp_dependent_lfl = _bool_state_value(state, "use_temp_dependent_lfl", False)

            # Individual LFL values (% v/v)
            individual_lfls = np.zeros(3)
            for idx, flam_label in enumerate(["co", "h2", "total_hydrocarbons"]):
                lfl_val = gas_data.get(flam_label, {}).get("lfl", 0)
                individual_lfls[idx] = lfl_val if lfl_val and lfl_val > 0 else 0

            # Temperature-dependent LFL adjustment
            if use_temp_dependent_lfl:
                venting_temp = inputs["venting_temperature"]
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
            selected_target = _resolve_state_value(state, "selected_target_flam_gas", "CO")
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

                lfl_curve_label = "Temperature-adjusted LFL" if use_temp_dependent_lfl else "Le Chatelier LFL"
                flam_result_vv_df["Le Chatelier LFL (v/v%)"] = adjusted_le_chatelier_lfl
                print(f"Le Chatelier's LFL range: {np.nanmin(adjusted_le_chatelier_lfl):.4f}% - {np.nanmax(adjusted_le_chatelier_lfl):.4f}%")
            elif use_temp_dependent_lfl:
                adjusted_le_chatelier_lfl = np.full(num_steps, float(lfl_percent), dtype=float)
                lfl_curve_label = "Temperature-adjusted LFL"
                flam_result_vv_df["Le Chatelier LFL (v/v%)"] = adjusted_le_chatelier_lfl
                print(f"Temperature-adjusted LFL set to user input threshold: {lfl_percent:.4f}%")

    # === Max module calculation (optimized using linearity of lfilter) ===
            lfl_value = (lfl_percent * room_vol) / 100
            vent_coeff = adj_ventilation_rate / room_vol
            alpha = 1.0 - vent_coeff * time_step

            if propagation_delay == 0:
                time_arr_bs = np.arange(0, total_duration + 1, time_step)
                num_steps_bs = len(time_arr_bs)

                # All modules start simultaneously at t=1 — response is linear in module count
                inflow_unit = np.zeros(num_steps_bs)
                valid_mask = (time_arr_bs >= 1) & ((time_arr_bs - 1) < mod_duration)
                local_times = (time_arr_bs[valid_mask] - 1).astype(np.intp)
                inflow_unit[valid_mask] = combined_flam_flowrates[local_times] * time_step
                response_unit = lfilter([1.0], [1.0, -alpha], inflow_unit)
                peak_response = np.max(response_unit)

                if peak_response > 0:
                    max_modules = int(lfl_value / peak_response)
                    # Verify boundary for floating point precision
                    if max_modules > 0 and max_modules * peak_response >= lfl_value:
                        max_modules -= 1
                else:
                    max_modules = 100000
            else:
                # Extend simulation to cover the ventilation decay time constant.
                # The steady-state peak requires enough groups for the exponential
                # decay tail to converge (5 time constants gives 99.3% convergence).
                decay_time_constant = room_vol / adj_ventilation_rate if adj_ventilation_rate > 0 else total_duration
                convergence_duration = int(5 * decay_time_constant)
                # Also ensure we cover the module overlap window
                overlap_duration = int(math.ceil(mod_duration / propagation_delay) + 1) * int(propagation_delay) + mod_duration
                bs_duration = max(total_duration, convergence_duration, overlap_duration)
                time_arr_bs = np.arange(0, bs_duration + 1, time_step)
                num_steps_bs = len(time_arr_bs)
                shift_samples = max(1, int(propagation_delay / time_step))

                # Compute response for group 0 (1 module starting at t=1)
                inflow_0 = np.zeros(num_steps_bs)
                valid_mask = (time_arr_bs >= 1) & ((time_arr_bs - 1) < mod_duration)
                if np.any(valid_mask):
                    local_times = (time_arr_bs[valid_mask] - 1).astype(np.intp)
                    inflow_0[valid_mask] = combined_flam_flowrates[local_times] * time_step
                response_0 = lfilter([1.0], [1.0, -alpha], inflow_0)

                # Compute base response for group 1 (1 module starting at t=propagation_delay)
                # By LTI time-shift property, response for group k is response_1
                # shifted right by (k-1)*shift_samples — no need for repeated lfilter calls
                start_time_1 = int(propagation_delay)
                inflow_1 = np.zeros(num_steps_bs)
                valid_mask = (time_arr_bs >= start_time_1) & ((time_arr_bs - start_time_1) < mod_duration)
                if np.any(valid_mask):
                    local_times = (time_arr_bs[valid_mask] - start_time_1).astype(np.intp)
                    inflow_1[valid_mask] = combined_flam_flowrates[local_times] * time_step
                response_1 = lfilter([1.0], [1.0, -alpha], inflow_1)

                # Determine total number of contributing groups
                # A group at offset >= num_steps_bs cannot contribute to the simulation
                max_groups = min(
                    int(bs_duration / propagation_delay),
                    (num_steps_bs - 1) // shift_samples
                )

                # Build cumulative shifted sum incrementally and record peak at each step.
                # running_cum[n] = sum_{j=0}^{g-1} response_1[n - j*shift_samples]
                # This correctly accounts for ALL overlapping group contributions.
                running_cum = np.zeros(num_steps_bs)
                # peak_full[g] = peak gas with g full delay groups (each MODULES_PER_DELAY modules)
                # peak_partial[g] = peak gas with g full groups + 1 extra module at next position
                peak_full = [np.max(response_0)]  # g=0: only group 0
                peak_partial = []

                for g in range(max_groups):
                    offset = g * shift_samples
                    if offset >= num_steps_bs:
                        break

                    # Shifted response_1 for this group position
                    end_idx = num_steps_bs - offset
                    shifted_slice = response_1[:end_idx]

                    # peak_partial[g]: g full groups + 1 partial module at this position
                    # Must check all timesteps (earlier ones have accumulated running_cum)
                    full_partial_gas = response_0.copy()
                    full_partial_gas += MODULES_PER_DELAY * running_cum
                    full_partial_gas[offset:] += shifted_slice
                    peak_partial.append(np.max(full_partial_gas))

                    # Add this group's contribution to running cumulative
                    running_cum[offset:] += shifted_slice

                    # peak_full[g+1]: g+1 full groups
                    peak_full.append(np.max(response_0 + MODULES_PER_DELAY * running_cum))

                num_computed_groups = len(peak_full) - 1

                # Steady-state check: if the fully converged peak doesn't exceed LFL
                if peak_full[-1] < lfl_value and (not peak_partial or peak_partial[-1] < lfl_value):
                    max_modules = 100000
                else:
                    # Binary search using precomputed peaks (monotonically non-decreasing)
                    max_searchable = 1 + num_computed_groups * MODULES_PER_DELAY + (MODULES_PER_DELAY - 1)
                    low = 1
                    high = min(100000, max_searchable)
                    max_modules = None

                    while low <= high:
                        mid = (low + high + 1) // 2
                        remaining = mid - 1

                        if remaining == 0:
                            peak = peak_full[0]
                        else:
                            num_full_groups = remaining // MODULES_PER_DELAY
                            partial = remaining % MODULES_PER_DELAY

                            # Cap at computed range
                            effective_full = min(num_full_groups, num_computed_groups)

                            if partial == 0:
                                peak = peak_full[effective_full]
                            else:
                                # Use peak_partial which includes the extra module
                                if effective_full < len(peak_partial):
                                    peak = peak_partial[effective_full]
                                else:
                                    # Beyond computed range — use last known full peak
                                    peak = peak_full[-1]

                        if peak >= lfl_value:
                            high = mid - 1
                        else:
                            max_modules = mid
                            low = mid + 1

            flam_max_mods_val = max_modules if max_modules else 'NA - Exceeds Calc Limit'
            flam_max_mods = {"total_gas": flam_max_mods_val}

            # === Save results ===
            flam_scenario_results[scenario_name] = {
                "flam_vv_df": flam_result_vv_df,
                "flam_mgl_df": flam_result_mgl_df,
                "flam_max_mod": flam_max_mods,
                "input": data,
                "use_le_chatelier": use_le_chatelier,
                "le_chatelier_lfl_array": adjusted_le_chatelier_lfl if (use_le_chatelier or use_temp_dependent_lfl) else None,
                "lfl_curve_array": adjusted_le_chatelier_lfl if (use_le_chatelier or use_temp_dependent_lfl) else None,
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


