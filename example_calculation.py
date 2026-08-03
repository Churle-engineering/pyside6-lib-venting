#note air changes per hour is ACPH = (3.6 * volumetric flow rate (L/s)) / room volume (m3)

import re
import warnings
import math
import numpy as np
import pandas as pd
from scipy.signal import lfilter
from ui_bridge import messagebox
from battery_chemistry_data import (
    BATTERY_CHEMISTRY_DATA,
    MODULES_PER_DELAY,
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
    return any(kw in label.lower() for kw in ["description", "name", "location", "room", "manufacturer", "lib type"])

def parse_scenario_rows(state):
    """
    Parse all scenario rows from the treeview into a list of (scenario_name, data_dict) tuples.
    Shared by toxicity, flammability, and graphical method calculations.
    """
    textbox_keys = list(state.entries.keys())
    try:
        battery_keys = list(next(iter(state.bat_data.values())).keys())
    except StopIteration:
        battery_keys = []

    all_keys = textbox_keys + battery_keys
    scenarios = []

    for item in state.tree.get_children():
        values = state.tree.item(item, 'values')
        scenario_name = values[0]
        data = {}

        for i, key in enumerate(all_keys):
            raw_value = values[i + 1] if i + 1 < len(values) else ""

            if raw_value is None or str(raw_value).strip().lower() in {"", "none", "nan"}:
                value = "" if is_string_field(key) else 0
            else:
                if is_string_field(key):
                    value = raw_value
                else:
                    try:
                        value = float(raw_value)
                    except ValueError:
                        warnings.warn(f"Invalid input '{raw_value}' for key '{key}'. Defaulting to 0.")
                        value = 0

            data[key] = value

        scenarios.append((scenario_name, data))

    return scenarios

def calc_active_modules(t, total_mods, propagation_delay, mod_duration, modules_per_delay=MODULES_PER_DELAY):
    """
    Calculate the number of active (currently off-gassing) modules at time t.
    Shared by all calculation loops and binary search simulations.
    
    Returns: number of active modules (int)
    """
    if t == 0:
        return 0

    # Modules that have STARTED failing by time t
    if propagation_delay > 0:
        intervals_passed = int(t // propagation_delay)
        started = min(total_mods, 1 + (intervals_passed * modules_per_delay))
    else:
        started = total_mods

    # Modules that have FINISHED off-gassing by time t
    if propagation_delay == 0:
        finished = total_mods if t >= mod_duration else 0
    elif t >= mod_duration:
        finished_intervals = int((t - mod_duration) // propagation_delay) * modules_per_delay
        finished = min(total_mods, 1 + finished_intervals)
    else:
        finished = 0

    return max(0, started - finished)


def calc_active_modules_array(time_array, total_mods, propagation_delay, mod_duration, modules_per_delay=MODULES_PER_DELAY):
    """
    Vectorized: compute active modules for all timesteps at once.
    Returns a numpy array of active module counts.
    """
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
    """
    Determine calculation method based on module capacity threshold.
    Returns (calc_method, was_overridden).
    """
    if user_selected_method == "Module Volume UL9540A":
        return "Module Volume UL9540A", False
    if mod_capacity > 1:
        was_overridden = (user_selected_method == "Module Capacity")
        return "Cell Volume UL9540A", was_overridden
    return user_selected_method, False


def calc_module_volume(calc_method, lib_type, mod_capacity, cells, cell_volume, module_volume=0):
    """
    Calculate module volume (m³) based on the selected calculation method.
    """
    if calc_method == "Module Volume UL9540A":
        return module_volume / 1000
    elif calc_method == "Module Capacity":
        specific_capacity = get_specific_capacity(lib_type)
        return (specific_capacity * mod_capacity) / 1000
    else:
        return cells * cell_volume / 1000


def validate_densities(gas_labels, gas_percents, gas_data, normalize_fn=None):
    """
    Filter gas labels to only those with valid density data.
    Returns (valid_labels, valid_percents_array, densities_array) or None if no valid gases.
    """
    densities = []
    valid_labels = []
    valid_percents = []

    for i, label in enumerate(gas_labels):
        normalized = normalize_fn(label) if normalize_fn else label.strip().lower().replace(' ', '_')
        density = gas_data.get(normalized, {}).get("density")
        if density is not None and density > 0:
            densities.append(density)
            valid_labels.append(label)
            valid_percents.append(gas_percents[i])

    if not valid_labels:
        return None

    return valid_labels, np.array(valid_percents), np.array(densities)


def resolve_target_gas_index(valid_gas_labels, state):
    """
    Find the index of the target flammable gas for emergency ventilation activation.
    Returns (target_gas_name, target_gas_index_or_None).
    """
    target_gas_map = {"CO": "co_(%)", "H2": "h2_(%)", "Total Hydrocarbons": "total_hydrocarbons_(%)"}
    selected_target = state.selected_target_flam_gas.get() if hasattr(state, 'selected_target_flam_gas') else "CO"
    target_gas_key = target_gas_map.get(selected_target, "co_(%)")

    for i, label in enumerate(valid_gas_labels):
        if label.strip().lower() == target_gas_key:
            return selected_target, i

    return selected_target, None


def setup_emergency_ventilation(vent_switch_conc, emergency_vent_rate, room_area):
    """
    Calculate emergency ventilation parameters.
    Returns (adj_emergency_vent_rate, emergency_vent_enabled).
    """
    adj_emergency_vent_rate = (emergency_vent_rate / 1000) * room_area if emergency_vent_rate > 0 else 0
    emergency_vent_enabled = (vent_switch_conc > 0 and emergency_vent_rate > 0)
    return adj_emergency_vent_rate, emergency_vent_enabled


def run_max_modules_binary_search(total_duration, time_step, propagation_delay, mod_duration,
                                  mod_flowrate, gas_percent, room_vol, adj_ventilation_rate,
                                  threshold_value, modules_per_delay=MODULES_PER_DELAY):
    """
    Binary search to find maximum number of modules before a concentration threshold is reached.
    Used by both toxicity (per-gas ERPG-3) and flammability (LFL) max module calculations.
    
    Parameters:
        threshold_value: The gas volume (m³) threshold that must not be exceeded.
        gas_percent: The fraction of total flow that is this specific gas (or combined fraction).
        mod_flowrate: Flow rate per module (m³/s).
    
    Returns: max_modules (int or None if limit not found)
    """
    vent_coeff = adj_ventilation_rate / room_vol
    alpha = 1.0 - vent_coeff * time_step
    time_array = np.arange(0, total_duration + 1, time_step)

    low = 1
    high = 100000
    max_modules = None

    while low <= high:
        mid = (low + high + 1) // 2

        # Vectorized: compute active modules and inflow for all timesteps
        active_array = calc_active_modules_array(time_array, mid, propagation_delay, mod_duration, modules_per_delay)
        inflow_signal = active_array * mod_flowrate * gas_percent * time_step

        # Solve recurrence gas[n] = alpha * gas[n-1] + inflow_signal[n] via lfilter
        # This is equivalent to the scalar loop but runs in compiled C code
        gas_array = lfilter([1.0], [1.0, -alpha], inflow_signal)
        gas_array = np.maximum(gas_array, 0.0)

        if np.any(gas_array >= threshold_value):
            high = mid - 1
        else:
            max_modules = mid
            low = mid + 1

    return max_modules

# ============================================================================
# CALCULATION FUNCTIONS
# ============================================================================

def toxicity_assessment_calc(parent, state, display_toxicity_result_popup, gas_data):
    """
    Calculate toxicity assessment for battery off-gassing scenarios.
    Uses battery-type-specific toxic gas composition from BATTERY_CHEMISTRY_DATA.
    """
    tox_scenario_results = state.tox_scenario_results
    tox_scenario_results.clear()
    overridden_scenarios = []

    scenarios = parse_scenario_rows(state)

    for scenario_name, data in scenarios:
        try:
            total_duration = int(float(data.get("Calculation Duration (s)", 0)))
            time_step = int(float(data.get("Time Step (s)", 1)))
            ventilation_rate = float(data.get("Ventilation Rate (L/s/m2)", 0))
            room_height = float(data.get("Room Height (m)", 0))
            room_area = float(data.get("Room Area (m2)", 0))
            equip_space = float(data.get("Equipment Space (%)", 0))
            vol_battery = float(data.get("cell_volume_(l)", 0))
            cell_duration = float(data.get("cell_duration_(s)", 0))
            module_volume = float(data.get("module_volume_(l)", 0))
            module_duration = float(data.get("module_duration_(s)", 0))
            cells = float(data.get("Cells per", 0))
            modules = float(data.get("Modules per", 0))
            units = float(data.get("Units", 0))
            lib_type = data.get("LIB Type", 0)
            propagation_delay = float(data.get("Module Propagation Delay (s)", 180))
            mod_capacity = float(data.get("module_capacity_(kwh)", 0))
            vent_switch_conc = float(data.get("Vent Switch Conc (%)", 0))
            emergency_vent_rate = float(data.get("Emergency Vent Rate (L/s/m2)", 0))

            # Determine calculation method
            user_selected_method = state.selected_calc_method.get() if hasattr(state, 'selected_calc_method') else "Cell Volume UL9540A"
            calc_method, was_overridden = determine_calc_method(mod_capacity, user_selected_method)
            if was_overridden:
                overridden_scenarios.append((scenario_name, mod_capacity))
            print(f"Toxicity - Using calculation method: {calc_method}")

            # Calculate module volume
            mod_vol = calc_module_volume(calc_method, lib_type, mod_capacity, cells, vol_battery, module_volume)

            # Validate critical inputs
            if calc_method == "Module Volume UL9540A":
                if room_height == 0 or room_area == 0 or module_duration == 0:
                    print(f"An input is zero when it shouldn't be. Either RH:{room_height} m, RA:{room_area} m2, ModDur:{module_duration} s")
                    return pd.DataFrame(), pd.DataFrame(), {}
                if module_volume == 0:
                    print("Module volume is zero when using Module Volume UL9540A Method")
                    return pd.DataFrame(), pd.DataFrame(), {}
            else:
                if room_height == 0 or room_area == 0 or cell_duration == 0:
                    print(f"An input is zero when it shouldn't be. Either RH:{room_height} m, RA:{room_area} m2, CD:{cell_duration} s")
                    return pd.DataFrame(), pd.DataFrame(), {}
                if calc_method == "Module Capacity" and mod_capacity == 0:
                    print("Module capacity is zero when using Module Capacity Method")
                    return pd.DataFrame(), pd.DataFrame(), {}
                elif calc_method != "Module Capacity" and vol_battery == 0:
                    print("Cell volume is zero when using Cell Volume Method")
                    return pd.DataFrame(), pd.DataFrame(), {}

            # Get toxic gas composition from centralized data
            lib_type_upper = lib_type.upper() if isinstance(lib_type, str) else str(lib_type).upper()
            chemistry_data = BATTERY_CHEMISTRY_DATA.get(lib_type_upper, BATTERY_CHEMISTRY_DATA.get('NMC', {}))
            lib_tox_gas_composition = chemistry_data.get('tox_gas_composition', {})

            # Filter to chemicals that have data in gas_data and a valid (non-zero) ERPG-3 value
            valid_gas_labels = [label for label in lib_tox_gas_composition.keys()
                                if label.strip().lower().replace(" ", "_") in gas_data
                                and gas_data[label.strip().lower().replace(" ", "_")].get("erpg-3", 0)]
            gas_percents = np.array([float(lib_tox_gas_composition.get(label, 0)) / 100 for label in valid_gas_labels])
            print(f"Lib type: {lib_type_upper}, Valid gases: {valid_gas_labels}")

            # Validate densities
            density_result = validate_densities(valid_gas_labels, gas_percents, gas_data)
            if density_result is None:
                print("Error: No gases with valid density data found.")
                return pd.DataFrame(), pd.DataFrame(), {}
            valid_gas_labels, gas_percents, densities = density_result
            num_gases = len(valid_gas_labels)

            # Pre-allocate arrays
            num_steps = (total_duration // time_step) + 1
            concentrations = np.zeros((num_gases, num_steps))
            mgl_concentrations = np.zeros((num_gases, num_steps))
            gases = np.zeros(num_gases)
            prev_gas = np.zeros(num_gases)
            time = np.arange(0, total_duration + 1, time_step)

            # Derived parameters
            adj_ventilation_rate = (ventilation_rate / 1000) * room_area
            adj_emergency_vent_rate, emergency_vent_enabled = setup_emergency_ventilation(vent_switch_conc, emergency_vent_rate, room_area)
            emergency_vent_activated = False

            # Use module_duration directly for Module Volume UL9540A, otherwise use cell_duration
            if calc_method == "Module Volume UL9540A":
                battery_duration = module_duration
            else:
                battery_duration = cell_duration
            if battery_duration <= 0:
                battery_duration = 1

            room_vol = (room_height * room_area) * (1 - (equip_space / 100))
            total_mods = modules * units
            mod_duration = battery_duration
            total_vent_outflow = adj_ventilation_rate / room_vol

            # Adjust for toxic percentage
            percent_tox = chemistry_data.get("percent_tox", 100)
            tox_mod_vol = mod_vol * (percent_tox / 100)
            mod_flowrate = tox_mod_vol / mod_duration
            print(f"Mod volume: {mod_vol} m3, toxic%: {percent_tox}%, flowrate: {mod_flowrate} m³/s/module")

            # Resolve emergency vent trigger gas
            target_gas_name, target_gas_index = resolve_target_gas_index(valid_gas_labels, state)

            # === Main calculation loop (pre-compute active modules array) ===
            active_modules_arr = calc_active_modules_array(time, total_mods, propagation_delay, mod_duration)

            for step_idx in range(num_steps):
                current_total_bat_flow = active_modules_arr[step_idx] * mod_flowrate

                inflows = current_total_bat_flow * gas_percents
                outflows = total_vent_outflow * prev_gas

                gases += (inflows - outflows) * time_step
                gases = np.maximum(gases, 0)
                prev_gas[:] = gases

                current_conc = (gases / room_vol) * 100
                concentrations[:, step_idx] = current_conc * 10000  # ppm
                mgl_concentrations[:, step_idx] = (current_conc / 100) * densities * 1000

                # Emergency ventilation check
                if emergency_vent_enabled and not emergency_vent_activated:
                    trigger_conc = current_conc[target_gas_index] if target_gas_index is not None else np.sum(current_conc)
                    if trigger_conc > vent_switch_conc:
                        emergency_vent_activated = True
                        total_vent_outflow = adj_emergency_vent_rate / room_vol
                        print(f"⚠️ Emergency ventilation ACTIVATED at t={time[step_idx]}s ({target_gas_name}: {trigger_conc:.4f}%)")

            # === Build result DataFrames ===
            mgl_data = {"Time (s)": time}
            vv_data = {"Time (s)": time}
            for i, label in enumerate(valid_gas_labels):
                mgl_data[f"{label} (mg/L)"] = mgl_concentrations[i, :]
                vv_data[f"{label} (v/v%)"] = concentrations[i, :]
            tox_result_mgl_df = pd.DataFrame(mgl_data)
            tox_result_vv_df = pd.DataFrame(vv_data)

            tox_result_mgl_df["Total Gas (mg/L)"] = tox_result_mgl_df[[f"{g} (mg/L)" for g in valid_gas_labels]].sum(axis=1)
            tox_result_vv_df["Total Gas (ppm)"] = tox_result_vv_df[[f"{g} (v/v%)" for g in valid_gas_labels]].sum(axis=1)

            # === Max module calculation (binary search per gas) ===
            tox_max_mods = {}
            for i, label in enumerate(valid_gas_labels):
                normalized_label = label.strip().lower().replace(' ', '_')
                if normalized_label not in gas_data:
                    continue
                gas_percent = gas_percents[i]
                density = densities[i]
                erpg3_value = gas_data[normalized_label].get("erpg-3", 0)

                if not erpg3_value or gas_percent <= 0 or density <= 0:
                    tox_max_mods[label] = 0
                    continue

                # Threshold: ERPG-3 in mg/L -> convert to equivalent gas volume in m³
                # conc_mgl = (gas / room_vol) * density * 1000 => gas = erpg3 * room_vol / (density * 1000)
                threshold_volume = erpg3_value * room_vol / (density * 1000)

                max_batteries = run_max_modules_binary_search(
                    total_duration, time_step, propagation_delay, mod_duration,
                    mod_flowrate, gas_percent, room_vol, adj_ventilation_rate, threshold_volume
                )

                if max_batteries is not None:
                    max_units = math.floor(max_batteries / modules)
                    print(f"✅ ERPG-3 limit for '{label}' reached at {max_units} Units")
                    tox_max_mods[label] = max_units
                else:
                    print(f"❌ ERPG-3 limit for '{label}' not reached within tested range")
                    tox_max_mods[label] = 0

            tox_scenario_results[scenario_name] = {
                "tox_vv_df": tox_result_vv_df,
                "tox_mgl_df": tox_result_mgl_df,
                "tox_max_mod": tox_max_mods,
                "calc_method": calc_method,
                "input": data
            }

        except ZeroDivisionError:
            messagebox.showerror("Calculation Error", f"{scenario_name} failed: Division by zero encountered.\nPlease check the input values.")
            return
        except Exception as e:
            messagebox.showerror("Calculation Error", f"{scenario_name} failed with an unexpected error:\n{e}")
            return

    # Show override notification
    if overridden_scenarios:
        override_msg = "The following scenarios have module capacity > 1 kWh.\n"
        override_msg += "The Cell Volume Method has been used instead of Module Capacity Method:\n\n"
        for name, capacity in overridden_scenarios:
            override_msg += f"  • {name} ({capacity:.2f} kWh)\n"
        messagebox.showinfo("Calculation Method Override", override_msg)

    # Show results
    if tox_scenario_results:
        first_scenario = next(iter(tox_scenario_results.values()))
        result_gas_labels = [col.replace(' (mg/L)', '') for col in first_scenario['tox_mgl_df'].columns if col not in ['Time (s)', 'Total Gas (mg/L)']]
        display_toxicity_result_popup(tox_scenario_results, state.tree, result_gas_labels, gas_data)
    else:
        display_toxicity_result_popup(tox_scenario_results, state.tree, [], gas_data)

def flammability_assessment_calc(parent, state, display_flammability_result_popup, gas_data, bat_data, flam_gasses_labels):
    """
    Calculate flammability assessment for battery off-gassing scenarios.
    """
    flam_scenario_results = state.flam_scenario_results
    flam_scenario_results.clear()
    overridden_scenarios = []

    scenarios = parse_scenario_rows(state)

    for scenario_name, data in scenarios:
        try:
            total_duration = int(float(data.get("Calculation Duration (s)", 0)))
            time_step = int(float(data.get("Time Step (s)", 1)))
            ventilation_rate = float(data.get("Ventilation Rate (L/s/m2)", 0))
            room_height = float(data.get("Room Height (m)", 0))
            room_area = float(data.get("Room Area (m2)", 0))
            cell_vol_battery = float(data.get("cell_volume_(l)", 0))
            cell_duration = float(data.get("cell_duration_(s)", 0))
            module_volume = float(data.get("module_volume_(l)", 0))
            module_duration = float(data.get("module_duration_(s)", 0))
            modules = float(data.get("Modules per", 0))
            equip_space = float(data.get("Equipment Space (%)", 0))
            units = float(data.get("Units", 0))
            cells = float(data.get("Cells per", 0))
            lfl_percent = float(data.get("lfl_(%)", 0))
            propagation_delay = float(data.get("Module Propagation Delay (s)", 0))
            lib_type = data.get("LIB Type", 0)
            mod_capacity = float(data.get("module_capacity_(kwh)", 0))
            vent_switch_conc = float(data.get("Vent Switch Conc (%)", 0))
            emergency_vent_rate = float(data.get("Emergency Vent Rate (L/s/m2)", 0))
            k_co2 = 1.5
            co2_percent = float(data.get("co2_(%)", 0)) / 100
            


            # Determine calculation method
            user_selected_method = state.selected_calc_method.get() if hasattr(state, 'selected_calc_method') else "Cell Volume UL9540A"
            calc_method, was_overridden = determine_calc_method(mod_capacity, user_selected_method)
            if was_overridden:
                overridden_scenarios.append((scenario_name, mod_capacity))
            print(f"Flammability - Using calculation method: {calc_method}")
            
            # Le Chatelier's LFL option
            use_le_chatelier = state.use_le_chatelier_lfl.get() if hasattr(state, 'use_le_chatelier_lfl') else False
            use_temp_dependent_lfl = state.use_temp_dependent_lfl.get() if hasattr(state, 'use_temp_dependent_lfl') else False

            # Individual LFL values (% v/v)
            individual_lfls = np.zeros(3)
            for idx, flam_label in enumerate(["co", "h2", "total_hydrocarbons"]):
                lfl_val = gas_data.get(flam_label, {}).get("lfl", 0)
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

            # Calculate module volume
            mod_vol = calc_module_volume(calc_method, lib_type, mod_capacity, cells, cell_vol_battery, module_volume)

            # Validate critical inputs
            if calc_method == "Module Volume UL9540A":
                if room_height == 0 or room_area == 0 or module_duration == 0:
                    print(f"An input is zero when it shouldn't be. Either RH:{room_height}, RA:{room_area}, ModDur:{module_duration}")
                    return pd.DataFrame(), pd.DataFrame(), {}
                if module_volume == 0:
                    print("Module volume is zero when using Module Volume UL9540A Method")
                    return pd.DataFrame(), pd.DataFrame(), {}
            else:
                if room_height == 0 or room_area == 0 or cell_duration == 0:
                    print(f"An input is zero when it shouldn't be. Either RH:{room_height}, RA:{room_area}, CD:{cell_duration}")
                    return pd.DataFrame(), pd.DataFrame(), {}
                if calc_method == "Module Capacity" and mod_capacity == 0:
                    print("Module capacity is zero when using Module Capacity Method")
                    return pd.DataFrame(), pd.DataFrame(), {}
                elif calc_method != "Module Capacity" and cell_vol_battery == 0:
                    print("Cell volume is zero when using Cell Volume Method")
                    return pd.DataFrame(), pd.DataFrame(), {}

            # Identify valid flammable gases from battery data
            valid_gas_labels = [label for label in data if label in flam_gasses_labels]
            gas_percents = np.array([float(data.get(label, 0)) / 100 for label in valid_gas_labels])
            num_gases = len(valid_gas_labels)

            # Pre-allocate arrays
            num_steps = (total_duration // time_step) + 1
            vv_concentrations = np.zeros((num_gases, num_steps))
            mgl_concentrations = np.zeros((num_gases, num_steps))
            gases = np.zeros(num_gases)
            prev_gas = np.zeros(num_gases)
            time = np.arange(0, total_duration + 1, time_step)

            # Pre-allocate a CO2 concentration trace
            co2_conc_arr = np.zeros(num_steps)
            co2_gas = 0.0
            co2_prev = 0.0


            # Derived parameters - use module_duration directly for Module Volume UL9540A
            if calc_method == "Module Volume UL9540A":
                mod_duration = module_duration
            else:
                mod_duration = cell_duration
            if mod_duration <= 0:
                mod_duration = 1

            room_vol = (room_height * room_area) * (1 - (equip_space / 100))

            # Adjust for flammable percentage
            flam_percentage = BATTERY_CHEMISTRY_DATA.get(lib_type, {}).get("percent_flam", 100) / 100
            flam_mod_vol = mod_vol * flam_percentage
            print(f"Flammable percentage for {lib_type}: {flam_percentage * 100}%, flam_mod_vol: {flam_mod_vol} m³")

            mod_flowrate = flam_mod_vol / mod_duration
            total_mods = modules * units
            adj_ventilation_rate = (ventilation_rate / 1000) * room_area

            # Emergency ventilation
            adj_emergency_vent_rate, emergency_vent_enabled = setup_emergency_ventilation(vent_switch_conc, emergency_vent_rate, room_area)
            emergency_vent_activated = False
            total_vent_outflow = adj_ventilation_rate / room_vol

            # Validate densities
            density_result = validate_densities(valid_gas_labels, gas_percents, gas_data,
                                                normalize_fn=lambda s: strip_unit_suffix(s.strip().lower()))
            if density_result is None:
                print("Error: No gases with valid density data found.")
                return pd.DataFrame(), pd.DataFrame(), {}
            valid_gas_labels, gas_percents, densities = density_result
            num_gases = len(valid_gas_labels)

            # Resolve emergency vent trigger gas
            target_gas_name, target_gas_index = resolve_target_gas_index(valid_gas_labels, state)

            # === Main calculation loop (pre-compute active modules array) ===
            active_modules_arr = calc_active_modules_array(time, total_mods, propagation_delay, mod_duration)

            for step_idx in range(num_steps):
                current_total_bat_flow = active_modules_arr[step_idx] * mod_flowrate

                inflows = current_total_bat_flow * gas_percents
                outflows = total_vent_outflow * prev_gas

                gases += (inflows - outflows) * time_step
                gases = np.maximum(gases, 0)
                prev_gas[:] = gases

                current_conc = (gases / room_vol) * 100
                vv_concentrations[:, step_idx] = current_conc
                mgl_concentrations[:, step_idx] = (current_conc / 100) * densities * 1000
                
                # --- CO2 (new) ---
                co2_inflow = current_total_bat_flow * co2_percent
                co2_outflow = total_vent_outflow * co2_prev
                co2_gas = max(co2_gas + (co2_inflow - co2_outflow) * time_step, 0.0)
                co2_prev = co2_gas
                co2_conc_arr[step_idx] = (co2_gas / room_vol) * 1

                # Emergency ventilation check
                if emergency_vent_enabled and not emergency_vent_activated:
                    trigger_conc = current_conc[target_gas_index] if target_gas_index is not None else np.sum(current_conc)
                    if trigger_conc >= vent_switch_conc:
                        emergency_vent_activated = True
                        total_vent_outflow = adj_emergency_vent_rate / room_vol
                        print(f"⚠️ Emergency ventilation ACTIVATED at t={time[step_idx]}s ({target_gas_name}: {trigger_conc:.4f}%)")

            # === Build result DataFrames ===
            flam_result_vv_df = pd.DataFrame({"Time (s)": time})
            flam_result_mgl_df = pd.DataFrame({"Time (s)": time})
            for i, label in enumerate(valid_gas_labels):
                base_label = strip_unit_suffix(label)
                flam_result_vv_df[f"{base_label} (v/v%)"] = vv_concentrations[i, :]
                flam_result_mgl_df[f"{base_label} (mg/L)"] = mgl_concentrations[i, :]


            # Total Gas columns
            flam_cols_vv = ["co (v/v%)", "h2 (v/v%)", "total_hydrocarbons (v/v%)"]
            flam_cols_mgl = ["co (mg/L)", "h2 (mg/L)", "total_hydrocarbons (mg/L)"]
            if all(c in flam_result_vv_df.columns for c in flam_cols_vv):
                flam_result_vv_df["Total Gas (v/v%)"] = flam_result_vv_df[flam_cols_vv].sum(axis=1)
            if all(c in flam_result_mgl_df.columns for c in flam_cols_mgl):
                flam_result_mgl_df["Total Gas (mg/L)"] = flam_result_mgl_df[flam_cols_mgl].sum(axis=1)
                
            print("Row order in vv_concentrations:", valid_gas_labels)
            print("num_gases:", num_gases)

                
                        # === Le Chatelier's LFL calculation (vectorized) ===
            adjusted_le_chatelier_lfl = None
            if use_le_chatelier:
                norm_labels = [strip_unit_suffix(l.strip().lower()) for l in valid_gas_labels]

                # Map "co"/"h2"/"total_hydrocarbons" -> row index in vv_concentrations
                name_to_row = {n: i for i, n in enumerate(norm_labels)}
                flam_names = ["co", "h2", "total_hydrocarbons"]
                used = [(n, name_to_row[n]) for n in flam_names if n in name_to_row]

                if not used:
                    print("Le Chatelier skipped: no flammable gases present.")
                else:
                    rows = [i for _, i in used]
                    conc_flam = vv_concentrations[rows, :]
                    total_flam_conc = conc_flam.sum(axis=0)
                    conc_co2 = co2_conc_arr   # <-- from the separate trace

                    # Align LFLs to the rows actually used
                    lfl_lookup = {
                        "co": individual_lfls[0],
                        "h2": individual_lfls[1],
                        "total_hydrocarbons": individual_lfls[2],
                    }
                    used_lfls = np.array([lfl_lookup[n] for n, _ in used])

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

                        total_offgas = total_flam_conc[valid_indices] + conc_co2[valid_indices]
                        co2_frac = np.where(total_offgas > 0, conc_co2[valid_indices] / total_offgas, 0.0)
                        needs_correction = (co2_frac > 0) & (co2_frac < 1.0)
                        inert_ratio = np.where(needs_correction, co2_frac / (1.0 - co2_frac), 0.0)
                        adjusted_lfl = lfl_mix * (100.0 - lfl_mix - (1.0 - k_co2) * inert_ratio * lfl_mix) / (100.0 - lfl_mix)
                        adjusted_lfl = np.where(needs_correction, adjusted_lfl, lfl_mix)
                        adjusted_le_chatelier_lfl[valid_indices] = adjusted_lfl

                    flam_result_vv_df["Le Chatelier LFL (v/v%)"] = adjusted_le_chatelier_lfl
                    print(f"Le Chatelier's LFL range: {np.nanmin(adjusted_le_chatelier_lfl):.4f}% - {np.nanmax(adjusted_le_chatelier_lfl):.4f}%")


            # === Max module calculation (binary search) ===
            target_gases = {"co_(%)", "h2_(%)", "total_hydrocarbons_(%)"}
            combined_gas_percent = sum(float(data.get(label, 0)) / 100 for label in target_gases)
            lfl_value = (lfl_percent * room_vol) / 100
            print(f"Combined flammable gas percent: {combined_gas_percent}, LFL threshold: {lfl_value} m³")

            max_modules = run_max_modules_binary_search(
                total_duration, time_step, propagation_delay, mod_duration,
                mod_flowrate, combined_gas_percent, room_vol, adj_ventilation_rate, lfl_value
            )

            flam_max_mods = {"total_gas": max_modules if max_modules else 'NA - Exceeds Calc Limit'}

            # === Save results ===
            flam_scenario_results[scenario_name] = {
                "flam_vv_df": flam_result_vv_df,
                "flam_mgl_df": flam_result_mgl_df,
                "flam_max_mod": flam_max_mods,
                "calc_method": calc_method,
                "input": data,
                "use_le_chatelier": use_le_chatelier,
                "le_chatelier_lfl_array": adjusted_le_chatelier_lfl if use_le_chatelier else None
            }
        except ZeroDivisionError:
            messagebox.showerror("Calculation Error", f"{scenario_name} failed: Division by zero encountered.\nPlease check the input values.")
            return
        except Exception as e:
            import traceback; traceback.print_exc() # print to console for debugging
            messagebox.showerror("Calculation Error", f"{scenario_name} failed with an unexpected error:\n{e}")
            return

    # Show override notification
    if overridden_scenarios:
        override_msg = "The following scenarios have module capacity > 1 kWh.\n"
        override_msg += "The Cell Volume Method has been used instead of Module Capacity Method:\n\n"
        for name, capacity in overridden_scenarios:
            override_msg += f"  • {name} ({capacity:.2f} kWh)\n"
        messagebox.showinfo("Calculation Method Override", override_msg)

    # Display results
    display_flammability_result_popup(flam_scenario_results, state.tree, gas_data, bat_data)


def flammability_assessment_calc_graphical_method(parent, state, display_flammability_result_popup, gas_data, bat_data, flam_gasses_labels):
    """
    Flammability calculation using time-varying flowrate data from imported Excel file.
    Uses per-second flowrate arrays instead of constant module volume method.
    """
    if not hasattr(state, 'gas_flowrate_data') or state.gas_flowrate_data is None:
        messagebox.showerror("Missing Data", "Gas flowrate data has not been imported.\nPlease use the 'Import Flowrate Data' button first.")
        return

    # Setup flowrate data
    gas_labels = ["co", "h2", "total_hydrocarbons", "co2"]
    num_gases = len(gas_labels)
    flowrate_matrix = np.array([state.gas_flowrate_data[label] for label in gas_labels])
    mod_duration = flowrate_matrix.shape[1]
    combined_flam_flowrates = flowrate_matrix[0] + flowrate_matrix[1] + flowrate_matrix[2]

    flam_scenario_results = state.flam_scenario_results
    flam_scenario_results.clear()

    scenarios = parse_scenario_rows(state)

    for scenario_name, data in scenarios:
        try:
            total_duration = int(float(data.get("Calculation Duration (s)", 0)))
            time_step = int(float(data.get("Time Step (s)", 1)))
            ventilation_rate = float(data.get("Ventilation Rate (L/s/m2)", 0))
            room_height = float(data.get("Room Height (m)", 0))
            room_area = float(data.get("Room Area (m2)", 0))
            modules = float(data.get("Modules per", 0))
            equip_space = float(data.get("Equipment Space (%)", 0))
            units = float(data.get("Units", 0))
            lfl_percent = float(data.get("lfl_(%)", 0))
            propagation_delay = float(data.get("Module Propagation Delay (s)", 0))
            vent_switch_conc = float(data.get("Vent Switch Conc (%)", 0))
            emergency_vent_rate = float(data.get("Emergency Vent Rate (L/s/m2)", 0))
            k_co2 = 1.5

            # Le Chatelier's LFL option
            use_le_chatelier = state.use_le_chatelier_lfl.get() if hasattr(state, 'use_le_chatelier_lfl') else False
            use_temp_dependent_lfl = state.use_temp_dependent_lfl.get() if hasattr(state, 'use_temp_dependent_lfl') else False

            # Individual LFL values (% v/v)
            individual_lfls = np.zeros(3)
            for idx, flam_label in enumerate(["co", "h2", "total_hydrocarbons"]):
                lfl_val = gas_data.get(flam_label, {}).get("lfl", 0)
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
                "le_chatelier_lfl_array": adjusted_le_chatelier_lfl if use_le_chatelier else None
            }
        except ZeroDivisionError:
            messagebox.showerror("Calculation Error", f"{scenario_name} failed: Division by zero encountered.\nPlease check the input values.")
            return
        except Exception as e:
            messagebox.showerror("Calculation Error", f"{scenario_name} failed with an unexpected error:\n{e}")
            return

    # Display results
    display_flammability_result_popup(flam_scenario_results, state.tree, gas_data, bat_data)
