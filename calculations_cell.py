#this file contains functions for determining cell profile venting and cell-to-cell/module propagation for the off gassing program.
#a separate calculation to the current calculations.py file.
#cell_propagation stages cell initiation (within a module) and module initiation (within the system) together.
#cell_venting_assessment_calc uses that combined release profile to determine the gas in the room.
#gas composition (Literature Data / UL9540A Flam Data / User Defined) reuses calculations.py's own
#resolution system so toxic and flammable species share one release signal but are still returned
#as separate flam_*/tox_* breakdowns, matching flammability_assessment_calc/toxicity_assessment_calc.
from dataclasses import dataclass

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QMessageBox

from calculations import (
    _coerce_scalar,
    _bool_state_value,
    _coerce_bool,
    _iter_scenarios,
    _parse_scenario_inputs,
    normalize_gas_key,
    resolve_flammable_gas_inputs,
    resolve_lfl_curve_labels,
    resolve_toxic_gas_densities,
    validate_densities,
    init_emergency_ventilation,
    maybe_activate_emergency_ventilation,
)
from information import (
    BATTERY_CHEMISTRY_DATA,
    CO_TEMPERATURE_LFL_PARAMETER_A,
    CO_TEMPERATURE_LFL_PARAMETER_B,
    H2_TEMPERATURE_LFL_PARAMETER_A,
    H2_TEMPERATURE_LFL_PARAMETER_B,
    THC_TEMPERATURE_LFL_PARAMETER_A,
    THC_TEMPERATURE_LFL_PARAMETER_B,
)

# Default staggered-initiation constants for this cell/module model. Scenarios can
# override these via Cell Propagation tab inputs in the UI.
CELL_PROP_DELAY = 60.0      # seconds between cell-initiation cohorts within a module
CELL_INIT_NUM = 2           # cells that initiate together, every CELL_PROP_DELAY seconds
MODULE_PROP_DELAY = 300.0   # seconds between module-initiation cohorts (5 minutes)
MODULE_INIT_NUM = 2         # additional modules that initiate together thereafter
MODULE_FIRST_INIT_NUM = 1   # modules already initiating at t=0


def _resolve_cell_propagation_controls(data):
    """Resolve optional per-scenario overrides for cohort timing/count controls."""
    data = data or {}
    return {
        "cell_prop_delay": max(0.0, _coerce_scalar(data.get("Cell Propagation Delay (s)"), CELL_PROP_DELAY)),
        "cell_init_num": max(1, int(round(_coerce_scalar(data.get("No. Cells Propagating"), CELL_INIT_NUM)))),
        "module_prop_delay": max(
            0.0,
            _coerce_scalar(
                data.get("Cell Model Module Propagation Delay (s)", data.get("Module Propagation Delay (s)")),
                MODULE_PROP_DELAY,
            ),
        ),
        "module_init_num": max(1, int(round(_coerce_scalar(data.get("No. Modules Propagating"), MODULE_INIT_NUM)))),
        "module_first_init_num": max(
            1,
            int(round(_coerce_scalar(data.get("Initially Propagating Modules"), MODULE_FIRST_INIT_NUM))),
        ),
    }


def _cell_curve_params(volume_l):
    """Derive one cell's curve shape parameters (h, tp, m1, tau, te) from its volume.

    Shared by `cell_vent_profile` (builds the plotted/sampled curve) and the exact
    closed-form integration `_cell_cumulative_volume` used by `cell_propagation`.
    """
    # -- define curve gradient conditions based on empirical venting data
    t_eps = 0.01
    t_tau = 5.0
    m1 = 2.0
    # -- -- -- -- -- - - -- - - - --- -- --- 

    area = volume_l / 1000.0  # L -> m3, i.e. area under the flowrate(m3/s)-time(s) curve
    if area <= 0:
        raise ValueError("cell_vent_profile: volume must be positive")

    # peak flowrate forced by the area constraint (area = h^2/(2*m1) + h*tau)
    h = np.sqrt(m1**2 * t_tau**2 + 2 * m1 * area) - m1 * t_tau
    tp = h / m1
    te = tp + t_tau * np.log(1.0 / t_eps)
    return h, tp, m1, t_tau, te


def cell_vent_profile(inputs, n=100):
    """Build a single cell's vent flowrate profile: linear rise then exponential decay.

    inputs['volume'] is the total gas volume released by the cell, in litres
    (matches the cell_volume_(l) convention used elsewhere). It is converted to
    m3 and used as the fixed area under the flowrate-time curve, so the
    resulting flowrate is in m3/s and integrates back to the input volume.
    """
    h, tp, m1, t_tau, te = _cell_curve_params(inputs['volume'])

    time = np.linspace(0, te, n)
    flowrate = np.where(time <= tp, m1 * time, h * np.exp(-(time - tp) / t_tau))
    return time, flowrate


def _cohort_schedule(total_count, batch_size, interval, first_batch_size=None):
    """Return [(start_time_s, count), ...] batches of `total_count` items starting
    together, beginning at t=0 and repeating every `interval` seconds until all items
    have started. `first_batch_size` lets the t=0 batch differ in size (e.g. modules
    start 1-then-2, cells start 2-then-2)."""
    total_count = int(total_count)
    if total_count <= 0:
        return []

    batch_size = max(1, int(batch_size))
    first_size = int(first_batch_size) if first_batch_size is not None else batch_size
    first_size = max(1, min(first_size, total_count))

    cohorts = [(0.0, first_size)]
    remaining = total_count - first_size
    wave = 1
    while remaining > 0:
        size = min(batch_size, remaining)
        cohorts.append((wave * float(interval), size))
        remaining -= size
        wave += 1
    return cohorts


def _cell_cumulative_volume(t, cell_params):
    """Exact closed-form volume (m3) one cell releases from its own t=0 up to local time t."""
    h, tp, m1, tau, te = cell_params
    t = np.asarray(t, dtype=np.float64)
    rise_volume = 0.5 * m1 * np.clip(t, 0.0, tp) ** 2
    decay_span = np.clip(t, tp, te) - tp
    return rise_volume + h * tau * (1.0 - np.exp(-decay_span / tau))


def _system_cumulative_volume(t_array, module_cohorts, cell_cohorts, cell_params):
    """Exact total volume (m3) released by every module/cell up to each system time.

    Differencing this at t and t+dt gives an exact, mass-conserving average flowrate for
    that step - a point-sampled instantaneous flowrate would undersample a cell's release
    whenever it is faster than the simulation's time step.
    """
    total = np.zeros(len(t_array), dtype=np.float64)
    for m_start, m_count in module_cohorts:
        if m_count <= 0:
            continue
        local = t_array - m_start
        module_volume = np.zeros(len(t_array), dtype=np.float64)
        for c_start, c_count in cell_cohorts:
            if c_count <= 0:
                continue
            module_volume += c_count * _cell_cumulative_volume(local - c_start, cell_params)
        total += m_count * module_volume
    return total


def _sum_cohort_active_count(time_array, cohorts, unit_duration):
    """Sum cohort counts still within their unit_duration window at each time."""
    total = np.zeros(len(time_array), dtype=np.float64)
    for start, count in cohorts:
        if count <= 0:
            continue
        local = time_array - start
        mask = (local >= 0) & (local <= unit_duration)
        total[mask] += count
    return total


def _cohort_start_for_index(cohorts, index):
    """Start time of the cohort containing the item at position `index` (0-based)."""
    if index < 0:
        return None
    running = 0
    for start, count in cohorts:
        if index < running + count:
            return start
        running += count
    return None


@dataclass(slots=True)
class CellPropagationResult:
    """Time-resolved cell/module release profile for one scenario.

    `module_cohorts`/`cell_cohorts` are lightweight (start_time, count) schedules, not
    dense per-cell arrays, so any individual cell's position in its own release profile
    can be recovered on demand via `cell_state_at` instead of being stored up front.
    """

    time: np.ndarray
    total_flowrate: np.ndarray        # m3/s, summed across every releasing cell
    active_cell_count: np.ndarray     # cells currently releasing, summed across all modules
    active_module_count: np.ndarray   # modules with at least one cell still releasing
    module_cohorts: list              # [(start_time_s, module_count), ...]
    cell_cohorts: list                # [(local_start_time_s, cell_count), ...] relative to a module's own start
    cell_profile_time: np.ndarray     # one cell's (time, flowrate) curve from cell_vent_profile
    cell_profile_flow: np.ndarray
    cell_duration: float              # te - time for one cell's release to finish
    module_duration: float            # time for one module's last cell cohort to finish


def _print_cell_propagation_audit(result):
    """Print a compact time-resolved audit trail for cell/module propagation."""
    if result is None:
        return

    time_arr = np.asarray(result.time, dtype=float)
    active_cells = np.asarray(result.active_cell_count, dtype=float)
    active_modules = np.asarray(result.active_module_count, dtype=float)
    flowrates = np.asarray(result.total_flowrate, dtype=float)

    if time_arr.size == 0:
        return

    print("Cell/Module propagation audit")
    print("t(s) | active_cells | active_modules | flowrate(m3/s)")
    for t_val, active_cell_val, active_module_val, flowrate_val in zip(time_arr, active_cells, active_modules, flowrates):
        print(f"{t_val:8.2f} | {active_cell_val:12.2f} | {active_module_val:14.2f} | {flowrate_val:12.6e}")


def cell_propagation(inputs, time_array=None, controls=None):
    """Combine per-cell and per-module staggered initiation into a system-wide release profile.

    Cells initiate CELL_INIT_NUM at a time every CELL_PROP_DELAY seconds (starting at
    t=0) until `inputs.cells` cells in a module have all started, each following the
    shared `cell_vent_profile` curve. Modules initiate similarly (MODULE_FIRST_INIT_NUM
    at t=0, then MODULE_INIT_NUM every MODULE_PROP_DELAY) until `inputs.modules *
    inputs.units` modules have all started, each restarting its own cell-initiation
    sequence at its own start time.
    """

    cells_per_module = round(inputs.cells)
    total_modules = round(inputs.modules * inputs.units)
    dt = inputs.time_step if inputs.time_step > 0 else 1.0
    controls = controls or {}

    cell_prop_delay = float(controls.get("cell_prop_delay", CELL_PROP_DELAY))
    cell_init_num = int(controls.get("cell_init_num", CELL_INIT_NUM))
    module_prop_delay = float(controls.get("module_prop_delay", MODULE_PROP_DELAY))
    module_init_num = int(controls.get("module_init_num", MODULE_INIT_NUM))
    module_first_init_num = int(controls.get("module_first_init_num", MODULE_FIRST_INIT_NUM))

    if time_array is None:
        time_array = np.arange(0, inputs.total_duration + dt, dt)
    time_array = np.asarray(time_array, dtype=np.float64)

    if cells_per_module <= 0 or total_modules <= 0:
        zeros = np.zeros(len(time_array), dtype=np.float64)
        return CellPropagationResult(
            time=time_array,
            total_flowrate=zeros,
            active_cell_count=zeros.copy(),
            active_module_count=zeros.copy(),
            module_cohorts=[],
            cell_cohorts=[],
            cell_profile_time=np.array([0.0]),
            cell_profile_flow=np.array([0.0]),
            cell_duration=0.0,
            module_duration=0.0,
        )

    # one cell's exact curve parameters and sampled (time, flowrate) - every cell in
    # every module follows this same shape
    cell_params = _cell_curve_params(inputs.cell_volume)
    cell_duration = float(cell_params[-1])  # te
    cell_time, cell_flow = cell_vent_profile({"volume": inputs.cell_volume})

    # cells within a single module: wave size and delay are configurable per scenario
    cell_cohorts = _cohort_schedule(cells_per_module, cell_init_num, cell_prop_delay)
    module_duration = cell_cohorts[-1][0] + cell_duration

    # modules across the whole system: configurable first-wave/next-wave controls
    module_cohorts = _cohort_schedule(
        total_modules, module_init_num, module_prop_delay, first_batch_size=module_first_init_num
    )

    # Exact, mass-conserving average flowrate per step (see _system_cumulative_volume),
    # using the backward-looking window [t-dt, t] so total_flowrate[n] is the release
    # that brings the system up to time_array[n] - a forward window [t, t+dt] would
    # report each sample one dt later than its label (e.g. a nonzero release at t=0
    # before any cell has started). Both cumulative ends are evaluated in one
    # concatenated call to halve the cohort-loop overhead versus two separate calls.
    combined_times = np.concatenate([time_array - dt, time_array])
    combined_cumulative = _system_cumulative_volume(combined_times, module_cohorts, cell_cohorts, cell_params)
    cumulative_start, cumulative_end = np.split(combined_cumulative, 2)
    total_flowrate = (cumulative_end - cumulative_start) / dt

    # active counts are instantaneous snapshots (not integrals), so a direct presence
    # check at each queried time is already exact regardless of grid spacing
    active_cell_count = np.zeros(len(time_array), dtype=np.float64)
    for m_start, m_count in module_cohorts:
        local = time_array - m_start
        active_cell_count += m_count * _sum_cohort_active_count(local, cell_cohorts, cell_duration)
    active_module_count = _sum_cohort_active_count(time_array, module_cohorts, module_duration)

    return CellPropagationResult(
        time=time_array,
        total_flowrate=total_flowrate,
        active_cell_count=active_cell_count,
        active_module_count=active_module_count,
        module_cohorts=module_cohorts,
        cell_cohorts=cell_cohorts,
        cell_profile_time=cell_time,
        cell_profile_flow=cell_flow,
        cell_duration=cell_duration,
        module_duration=module_duration,
    )


def cell_state_at(result, global_time, module_index, cell_index_in_module):
    """Return (local_elapsed_s, flowrate_m3s) for one specific cell at `global_time`, or
    None if that cell has not started yet or has already finished releasing."""
    module_start = _cohort_start_for_index(result.module_cohorts, module_index)
    if module_start is None:
        return None
    cell_start = _cohort_start_for_index(result.cell_cohorts, cell_index_in_module)
    if cell_start is None:
        return None

    local_elapsed = global_time - module_start - cell_start
    if local_elapsed < 0 or local_elapsed > result.cell_duration:
        return None

    flow = float(np.interp(local_elapsed, result.cell_profile_time, result.cell_profile_flow))
    return local_elapsed, flow


def _resolve_cell_gas_composition(data, lib_type, gas_data):
    """Resolve every gas species as a fraction of the *total* released gas volume.

    Reuses calculations.py's Literature Data / UL9540A Flam Data / User Defined
    composition system verbatim - the same _tox_gas_composition_override /
    _percent_tox_override / _flam_percent_override scenario keys that
    toxicity_assessment_calc and flammability_assessment_calc already check -
    so this file combines that system rather than re-implementing it. Returns
    within-subset fractions (e.g. CO's share of just the toxic mix) alongside
    release-wide fractions (within-subset * percent_tox/percent_flam / 100) so
    callers can reproduce either calculation's own formulas exactly.
    """
    lib_type_upper = str(lib_type).upper()
    chemistry_data = BATTERY_CHEMISTRY_DATA.get(lib_type_upper, BATTERY_CHEMISTRY_DATA.get("NMC", {}))

    tox_comp_override = data.get("_tox_gas_composition_override")
    tox_gas_composition = tox_comp_override if tox_comp_override else chemistry_data.get("tox_gas_composition", {})
    if "_percent_tox_override" in data:
        percent_tox = float(data["_percent_tox_override"])
    else:
        percent_tox = chemistry_data.get("percent_tox", 100)

    tox_labels = []
    tox_within_fractions = np.array([], dtype=float)
    tox_fractions = np.array([], dtype=float)
    tox_densities = np.array([], dtype=float)
    tox_density_result = resolve_toxic_gas_densities(tox_gas_composition)
    if tox_density_result is not None:
        raw_labels, raw_percents, raw_densities = tox_density_result
        tox_labels = [normalize_gas_key(label) for label in raw_labels]
        tox_within_fractions = raw_percents
        tox_fractions = raw_percents * (percent_tox / 100.0)
        tox_densities = raw_densities

    if "_flam_percent_override" in data:
        percent_flam = float(data["_flam_percent_override"])
    else:
        percent_flam = chemistry_data.get("percent_flam", 100)

    flam_labels = []
    flam_within_fractions = np.array([], dtype=float)
    flam_fractions = np.array([], dtype=float)
    flam_densities = np.array([], dtype=float)
    gas_input_pairs = resolve_flammable_gas_inputs(data)
    if gas_input_pairs:
        raw_flam_labels = [label for label, _ in gas_input_pairs]
        raw_flam_percents = np.array([float(data.get(label, 0)) / 100.0 for label, _ in gas_input_pairs], dtype=float)
        flam_density_result = validate_densities(raw_flam_labels, raw_flam_percents, gas_data, normalize_fn=normalize_gas_key)
        if flam_density_result is not None:
            raw_labels, raw_percents, raw_densities = flam_density_result
            flam_labels = [normalize_gas_key(label) for label in raw_labels]
            flam_within_fractions = raw_percents
            flam_fractions = raw_percents * (percent_flam / 100.0)
            flam_densities = raw_densities

    return {
        "tox_labels": tox_labels,
        "tox_within_fractions": tox_within_fractions,
        "tox_fractions": tox_fractions,
        "tox_densities": tox_densities,
        "percent_tox": percent_tox,
        "flam_labels": flam_labels,
        "flam_within_fractions": flam_within_fractions,
        "flam_fractions": flam_fractions,
        "flam_densities": flam_densities,
        "percent_flam": percent_flam,
    }


def cell_venting_assessment_calc(parent, state, gas_data, scenario_data=None, clear_existing=True):
    """Room gas balance driven by the cell/module propagation profile.

    One shared release signal (prop.total_flowrate, filtered through the room's
    constant-ventilation model) is rescaled by calculations.py's composition
    system - once for toxic species (tox_gas_composition x percent_tox) and once
    for flammable species (CO/H2/THC x percent_flam) - instead of running two
    independent simulations. The room balance is linear/time-invariant at
    constant ventilation, so filtering the *unsplit* signal once and rescaling
    per-gas is exact, not an approximation.

    Each scenario's result carries both a flam_* breakdown (total flammable gas
    + optional Le Chatelier LFL curve) and a tox_* breakdown (individual toxic
    components), matching the shapes flammability_assessment_calc and
    toxicity_assessment_calc would each produce on their own.
    """
    cell_scenario_results = getattr(state, "cell_scenario_results", None)
    if cell_scenario_results is None:
        cell_scenario_results = {}
        state.cell_scenario_results = cell_scenario_results
    if clear_existing:
        cell_scenario_results.clear()

    scenarios = _iter_scenarios(state, scenario_data)
    if not scenarios:
        return cell_scenario_results

    for scenario_name, data in scenarios:
        try:
            inputs = _parse_scenario_inputs(data)
            if inputs.room_height <= 0 or inputs.room_area <= 0:
                raise ValueError("Room Height (m) and Room Area (m2) are required")

            room_vol = inputs.room_height * inputs.room_area * (1 - inputs.equip_space / 100.0)
            if room_vol <= 0:
                raise ValueError("Room volume must be positive")

            controls = _resolve_cell_propagation_controls(data)
            prop = cell_propagation(inputs, controls=controls)
            _print_cell_propagation_audit(prop)
            dt = inputs.time_step if inputs.time_step > 0 else 1.0

            # Build room-balance signal for total off-gas volume. When emergency
            # ventilation is configured, outflow can change in time so this path
            # must be integrated step-by-step (not fixed-coefficient lfilter).
            emergency_vent_state = init_emergency_ventilation(
                inputs.ventilation_rate,
                inputs.emergency_vent_rate,
                inputs.room_area,
                room_vol,
                inputs.vent_switch_conc,
            )
            total_vent_outflow = emergency_vent_state["current_outflow"]

            composition = _resolve_cell_gas_composition(data, inputs.lib_type, gas_data)
            flam_fraction_total = float(np.sum(composition["flam_fractions"])) if len(composition["flam_fractions"]) else 0.0

            base_gas_vol_arr = np.zeros(len(prop.time), dtype=float)
            gas_total = 0.0
            for step_idx, release_flow in enumerate(prop.total_flowrate):
                inflow = float(release_flow)
                outflow = total_vent_outflow * gas_total
                gas_total = max(gas_total + (inflow - outflow) * dt, 0.0)
                base_gas_vol_arr[step_idx] = gas_total

                total_offgas_conc = (gas_total / room_vol) * 100.0 if room_vol > 0 else 0.0
                trigger_conc = total_offgas_conc * flam_fraction_total
                total_vent_outflow = maybe_activate_emergency_ventilation(
                    emergency_vent_state,
                    trigger_conc,
                    prop.time[step_idx],
                    "Total Flammable Gas",
                )

            gas_conc_vv = (base_gas_vol_arr / room_vol) * 100.0

            result_df = pd.DataFrame({
                "Time (s)": prop.time,
                "Total Gas (m3)": base_gas_vol_arr,
                "Total Gas (v/v%)": gas_conc_vv,
                "Active Cells": prop.active_cell_count,
                "Active Modules": prop.active_module_count,
                "Flowrate (m3/s)": prop.total_flowrate,
            })

            # Note: max-modules-before-threshold (as in toxicity_assessment_calc /
            # flammability_assessment_calc) is intentionally not computed here. That
            # search re-runs the release calculation for many hypothetical module
            # counts; the coarse per-module model does that in O(1) per count via
            # calc_active_modules_array, but cell_propagation's cohort loops scale with
            # module count, which makes the same search prohibitively slow at the
            # module counts a real scenario can require.

            # --- Toxic species: individual concentrations -------------------------------
            tox_result_vv_df = pd.DataFrame({"Time (s)": prop.time})
            tox_result_mgl_df = pd.DataFrame({"Time (s)": prop.time})
            tox_max_mods = {}
            tox_labels = composition["tox_labels"]
            for label, fraction, within_fraction, density in zip(
                tox_labels, composition["tox_fractions"], composition["tox_within_fractions"], composition["tox_densities"]
            ):
                conc_vv = (fraction * base_gas_vol_arr / room_vol) * 100.0
                tox_result_vv_df[f"{label} (v/v%)"] = conc_vv
                tox_result_mgl_df[f"{label} (mg/L)"] = (conc_vv / 100.0) * density * 1000.0
                tox_max_mods[label] = "NA - No Gas Fraction" if within_fraction <= 0 else "Not Calculated for Cell Model"

            tox_vv_cols = [f"{label} (v/v%)" for label in tox_labels]
            tox_mgl_cols = [f"{label} (mg/L)" for label in tox_labels]
            tox_result_vv_df["Total Gas (v/v%)"] = tox_result_vv_df[tox_vv_cols].sum(axis=1) if tox_vv_cols else 0.0
            tox_result_mgl_df["Total Gas (mg/L)"] = tox_result_mgl_df[tox_mgl_cols].sum(axis=1) if tox_mgl_cols else 0.0

            # --- Flammable species: total flammable gas + optional Le Chatelier LFL -----
            flam_result_vv_df = pd.DataFrame({"Time (s)": prop.time})
            flam_result_mgl_df = pd.DataFrame({"Time (s)": prop.time})
            flam_vv_by_label = {}
            flam_labels = composition["flam_labels"]
            for label, fraction, density in zip(flam_labels, composition["flam_fractions"], composition["flam_densities"]):
                conc_vv = (fraction * base_gas_vol_arr / room_vol) * 100.0
                flam_result_vv_df[f"{label} (v/v%)"] = conc_vv
                flam_result_mgl_df[f"{label} (mg/L)"] = (conc_vv / 100.0) * density * 1000.0
                flam_vv_by_label[label] = conc_vv

            flam_vv_cols = [f"{label} (v/v%)" for label in flam_labels]
            flam_mgl_cols = [f"{label} (mg/L)" for label in flam_labels]
            flam_result_vv_df["Total Gas (v/v%)"] = flam_result_vv_df[flam_vv_cols].sum(axis=1) if flam_vv_cols else 0.0
            flam_result_mgl_df["Total Gas (mg/L)"] = flam_result_mgl_df[flam_mgl_cols].sum(axis=1) if flam_mgl_cols else 0.0

            # Max modules before the user's overall LFL (%) threshold is not computed
            # here - see the note above tox_max_mods for why.
            flam_max_mod_value = "Not Calculated for Cell Model"

            # --- Le Chatelier LFL curve (optional), CO2-diluted like flammability_assessment_calc ---
            use_le_chatelier = _coerce_bool(
                data.get("Use Le Chatelier LFL"), _bool_state_value(state, "use_le_chatelier_lfl", False)
            )
            use_temp_dependent_lfl = _coerce_bool(
                data.get("Use Temperature Dependent LFL"), _bool_state_value(state, "use_temp_dependent_lfl", False)
            )
            individual_lfls = np.array(
                [gas_data.get(g, {}).get("lfl", 0) or 0 for g in ("co", "h2", "total_hydrocarbons")], dtype=float
            )
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

            adjusted_le_chatelier_lfl = None
            lfl_curve_label = None
            if use_le_chatelier:
                names, _rows = resolve_lfl_curve_labels(flam_labels)
                if names:
                    conc_flam = np.vstack([flam_vv_by_label[name] for name in names])
                    total_flam_conc = conc_flam.sum(axis=0)
                    lfl_lookup = {"co": individual_lfls[0], "h2": individual_lfls[1], "total_hydrocarbons": individual_lfls[2]}
                    used_lfls = np.array([lfl_lookup[name] for name in names], dtype=float)

                    # CO2 dilutes the flammable mixture (k_co2 correction) but is not itself
                    # flammable - it shares the flam_percentage scaling, as in flammability_assessment_calc.
                    co2_fraction = (composition["percent_flam"] / 100.0) * inputs.co2_percent
                    co2_conc_arr = (co2_fraction * base_gas_vol_arr / room_vol) * 100.0
                    k_co2 = 1.5

                    adjusted_le_chatelier_lfl = np.full(len(prop.time), np.nan)
                    active_mask = total_flam_conc > 0
                    if np.any(active_mask):
                        fracs = conc_flam[:, active_mask] / total_flam_conc[active_mask]
                        inv_lfls = np.where(used_lfls > 0, 1.0 / used_lfls, 0.0)
                        denominator = inv_lfls @ fracs
                        valid_denom = denominator > 0
                        active_indices = np.where(active_mask)[0]
                        valid_indices = active_indices[valid_denom]
                        lfl_mix = 1.0 / denominator[valid_denom]

                        total_offgas = total_flam_conc[valid_indices] + co2_conc_arr[valid_indices]
                        co2_frac = np.where(total_offgas > 0, co2_conc_arr[valid_indices] / total_offgas, 0.0)
                        needs_correction = (co2_frac > 0) & (co2_frac < 1.0)
                        inert_ratio = np.where(needs_correction, co2_frac / (1.0 - co2_frac), 0.0)
                        adjusted_lfl = lfl_mix * (100.0 - lfl_mix - (1.0 - k_co2) * inert_ratio * lfl_mix) / (100.0 - lfl_mix)
                        adjusted_lfl = np.where(needs_correction, adjusted_lfl, lfl_mix)
                        adjusted_le_chatelier_lfl[valid_indices] = adjusted_lfl
                    lfl_curve_label = "Temperature-adjusted Le Chatelier LFL" if use_temp_dependent_lfl else "Le Chatelier LFL"
                if adjusted_le_chatelier_lfl is not None:
                    flam_result_vv_df["Le Chatelier LFL (v/v%)"] = adjusted_le_chatelier_lfl

            cell_scenario_results[scenario_name] = {
                # Not "propagation": prop (a CellPropagationResult dataclass) - it isn't
                # JSON-serializable for save/load and every value it holds is already
                # duplicated in cell_gas_df's columns (Time/Active Cells/Active Modules/Flowrate).
                "cell_gas_df": result_df,
                "flam_vv_df": flam_result_vv_df,
                "flam_mgl_df": flam_result_mgl_df,
                "flam_max_mod": {"total_gas": flam_max_mod_value},
                "tox_vv_df": tox_result_vv_df,
                "tox_mgl_df": tox_result_mgl_df,
                "tox_max_mod": tox_max_mods,
                "calc_method": "Cell/Module Propagation",
                "input": data,
                "use_le_chatelier": use_le_chatelier,
                "use_temp_dependent_lfl": use_temp_dependent_lfl,
                "le_chatelier_lfl_array": adjusted_le_chatelier_lfl if use_le_chatelier else None,
                "lfl_curve_array": adjusted_le_chatelier_lfl if use_le_chatelier else None,
                "lfl_curve_label": lfl_curve_label,
            }
        except ZeroDivisionError:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed: Division by zero encountered.\nPlease check the input values.")
            return cell_scenario_results
        except Exception as exc:
            QMessageBox.critical(parent, "Calculation Error", f"{scenario_name} failed with an unexpected error:\n{exc}")
            return cell_scenario_results

    return cell_scenario_results


