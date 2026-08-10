"""Standalone audit harness for the cell propagation venting calculation.

This script builds one fixed scenario, runs cell_venting_assessment_calc,
and prints key audit outputs:
- cell/module initiation cohort arrays,
- number of new and active venting cells each second,
- resulting room and gas concentration timelines.
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd

from calculations import _parse_scenario_inputs
from calculations_cell import (
	_resolve_cell_propagation_controls,
	cell_propagation,
	cell_venting_assessment_calc,
)
from information import CHEMICAL_PROPERTIES


def _build_audit_scenario():
	"""Return one deterministic scenario row compatible with _parse_scenario_inputs."""
	return {
		"Scenario Description": "Audit Scenario - Cell Propagation",
		"Calculation Duration (s)": 500,
		"Room Height (m)": 3.0,
		"Room Area (m2)": 12.0,
		"Equipment Space (%)": 15.0,
		"Ventilation Rate (L/s/m2)": 2.0,
		"Vent Switch Conc (%)": 1.0,
		"Emergency Vent Rate (L/s/m2)": 12.0,
		"Cell Volume (L)": 6.0,
		"Cells per module": 28,
		"Modules per unit": 6,
		"Units": 2,
		"LIB Type": "NMC",
		"LFL (%)": 6.0,
		"CO2 (%)": 5.0,
		"Venting Temperature (C)": 25.0,
		"CO (%)": 80.0,
		"H2 (%)": 10.0,
		"Total Hydrocarbons (%)": 10.0,
		"Cell Propagation Delay (s)": 40.0,
		"No. Cells Propagating": 2,
		"Cell Model Module Propagation Delay (s)": 45.0,
		"No. Modules Propagating": 2,
		"Initially Propagating Modules": 1,
		"Use Le Chatelier LFL": True,
		"Use Temperature Dependent LFL": True,
	}


def _count_new_cells_started_at_time(module_cohorts, cell_cohorts, time_s):
	"""Count cells that start venting exactly at time_s across all modules."""
	total = 0
	for module_start, module_count in module_cohorts:
		for cell_start, cell_count in cell_cohorts:
			if np.isclose(module_start + cell_start, time_s):
				total += int(module_count) * int(cell_count)
	return total


def _print_input_summary(scenario):
	print("=" * 88)
	print("AUDIT INPUT SCENARIO")
	print("=" * 88)
	for key in sorted(scenario.keys()):
		print(f"{key:40s}: {scenario[key]}")
	print()


def _print_cohort_schedules(prop):
	print("=" * 88)
	print("COHORT INITIATION ARRAYS")
	print("=" * 88)

	print("Cell cohorts within one module: (local_start_s, cell_count)")
	for local_start_s, count in prop.cell_cohorts:
		print(f"  ({local_start_s:8.2f}, {int(count):3d})")
	print()

	print("Module cohorts across the room: (global_start_s, module_count)")
	for global_start_s, count in prop.module_cohorts:
		print(f"  ({global_start_s:8.2f}, {int(count):3d})")
	print()


def _print_per_second_propagation_audit(prop):
	print("=" * 88)
	print("PER-SECOND PROPAGATION AUDIT")
	print("=" * 88)
	print("Columns: time_s | new_cells_starting | active_cells | active_modules | flowrate_m3_s")

	for idx, time_s in enumerate(prop.time):
		new_cells = _count_new_cells_started_at_time(prop.module_cohorts, prop.cell_cohorts, time_s)
		active_cells = round(float(prop.active_cell_count[idx]))
		active_modules = round(float(prop.active_module_count[idx]))
		flowrate = float(prop.total_flowrate[idx])
		print(
			f"{time_s:7.1f} | {new_cells:18d} | {active_cells:12d} | "
			f"{active_modules:14d} | {flowrate:12.6e}"
		)
	print()


def _print_result_tables(result_data):
	print("=" * 88)
	print("ROOM AND GAS RESULTS")
	print("=" * 88)

	cell_df = result_data["cell_gas_df"].copy()
	flam_df = result_data["flam_vv_df"].copy()
	tox_df = result_data["tox_vv_df"].copy()

	merged = cell_df[[
		"Time (s)",
		"Total Gas (m3)",
		"Total Gas (v/v%)",
		"Active Cells",
		"Active Modules",
		"Flowrate (m3/s)",
	]].rename(columns={"Total Gas (v/v%)": "Room Total Gas (v/v%)"})

	if "Total Gas (v/v%)" in flam_df.columns:
		merged = merged.merge(
			flam_df[["Time (s)", "Total Gas (v/v%)"]].rename(columns={"Total Gas (v/v%)": "Flammable Gas (v/v%)"}),
			on="Time (s)",
			how="left",
		)

	if "Total Gas (v/v%)" in tox_df.columns:
		merged = merged.merge(
			tox_df[["Time (s)", "Total Gas (v/v%)"]].rename(columns={"Total Gas (v/v%)": "Toxic Gas (v/v%)"}),
			on="Time (s)",
			how="left",
		)

	if "Le Chatelier LFL (v/v%)" in flam_df.columns:
		merged = merged.merge(flam_df[["Time (s)", "Le Chatelier LFL (v/v%)"]], on="Time (s)", how="left")

	pd.set_option("display.max_rows", None)
	pd.set_option("display.max_columns", None)
	pd.set_option("display.width", 160)

	print("Per-second integrated gas balance and concentrations:")
	print(
		merged.to_string(
			index=False,
			float_format=lambda x: f"{x:.6f}",
		)
	)
	print()


def run_audit():
	scenario = _build_audit_scenario()
	_print_input_summary(scenario)

	parsed_inputs = _parse_scenario_inputs(scenario)
	controls = _resolve_cell_propagation_controls(scenario)
	prop = cell_propagation(parsed_inputs, controls=controls)

	_print_cohort_schedules(prop)
	_print_per_second_propagation_audit(prop)

	state = SimpleNamespace(
		cell_scenario_results={},
		use_le_chatelier_lfl=True,
		use_temp_dependent_lfl=True,
	)

	cell_venting_assessment_calc(
		parent=None,
		state=state,
		gas_data=CHEMICAL_PROPERTIES,
		scenario_data=[scenario],
		clear_existing=True,
	)

	scenario_name = scenario.get("Scenario Description", "Scenario 1")
	result_data = state.cell_scenario_results.get(scenario_name)
	if result_data is None:
		print("No result returned for expected scenario name.")
		print(f"Available result keys: {list(state.cell_scenario_results.keys())}")
		return

	_print_result_tables(result_data)

	print("=" * 88)
	print("AUDIT COMPLETE")
	print("=" * 88)
	print(f"Scenario processed: {scenario_name}")
	print(f"Rows in time series: {len(result_data['cell_gas_df'])}")
	print(f"Peak active cells: {int(np.max(prop.active_cell_count))}")
	print(f"Peak active modules: {int(np.max(prop.active_module_count))}")
	print(f"Peak room gas (v/v%): {float(result_data['cell_gas_df']['Total Gas (v/v%)'].max()):.6f}")


if __name__ == "__main__":
	run_audit()