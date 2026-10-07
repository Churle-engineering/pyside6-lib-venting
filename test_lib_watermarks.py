"""Regression checks for stale LIB result plots and saved run snapshots."""

import copy
import json
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog

from information import (
    CALC_METHOD_MODULE_VARIABLE_FLOWRATE, CHEMICAL_PROPERTIES,
    FlowrateProfile, GasComposition, LIBInputs, LIBSpec,
)
from main import BaseWindow, LIBPage
from saveload import apply_state, collect_state
from venting_calculation import build_result_plots, run_venting_assessment


class ResultWatermarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = BaseWindow()
        self.page = LIBPage(self.window)
        self.window.add_page("LIBPage", self.page)
        self.window.custom_lib_definitions["Battery"] = LIBSpec(name="Battery", lfl=10.0)
        self.window.custom_lib_definitions["Unrelated"] = LIBSpec(name="Unrelated", lfl=10.0)
        self.window.custom_composition_definitions["Blend"] = GasComposition(
            "Blend", {"co": 60.0, "h2": 40.0},
        )
        self.window.custom_flowrate_profiles["Measured"] = FlowrateProfile(
            "Measured", [0.0, 1.0, 2.0], [0.0, 2.0, 0.0],
        )

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()

    def add_run(self, **overrides):
        inputs = LIBInputs(lib_spec="Battery", calc_duration=20)
        scenario = self.page.scenarios.add(replace(inputs, **overrides), "Study")
        self.page._apply_lib_spec(scenario)
        self.page._apply_composition(scenario)
        self.page._apply_flowrate_profile(scenario)
        with patch("venting_calculation.QMessageBox.warning") as warning:
            results = run_venting_assessment(
                self.page, self.page.scenarios, CHEMICAL_PROPERTIES, node_ids={scenario.node_id},
            )
        self.assertEqual(warning.call_count, 0, warning.call_args)
        self.assertIn(scenario.node_id, results)
        self.page._set_result_tab(
            scenario.node_id, scenario.name, build_result_plots(scenario.summary),
        )
        return scenario

    def assert_watermarks(self, scenario, visible):
        widget = self.page._result_tab_widgets[scenario.node_id]
        canvases = widget.findChildren(FigureCanvasQTAgg)
        self.assertEqual(len(canvases), 2)
        for canvas in canvases:
            canvas.draw()
            texts = [
                text for axes in canvas.figure.axes for text in axes.texts
                if text.get_gid() == "results-out-of-date"
            ]
            self.assertEqual(len(texts), 1)
            self.assertEqual(texts[0].get_visible(), visible)
            self.assertIn("RESULTS OUT OF DATE", texts[0].get_text())
            if visible:
                bounds = texts[0].get_window_extent(canvas.get_renderer())
                self.assertTrue(bounds.overlaps(canvas.figure.axes[0].get_window_extent()))

    def edit_scenario(self, scenario, inputs, accepted=True):
        with patch("main.ScenarioInputDialog") as dialog_type:
            dialog_type.return_value.exec.return_value = (
                QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
            )
            dialog_type.return_value.result_inputs = inputs
            self.page._edit_scenario(scenario.node_id)

    def edit_library(self, change):
        with patch("main.LibraryManagerDialog") as dialog_type:
            dialog_type.return_value.exec.side_effect = change
            self.page.open_library_manager()

    def test_scenario_edit_marks_both_plots_and_preserves_controls(self):
        scenario = self.add_run()
        other = self.add_run(lib_spec="Unrelated")
        self.assert_watermarks(scenario, False)
        widget = self.page._result_tab_widgets[scenario.node_id]
        checkbox = widget.findChildren(QCheckBox)[0]
        checkbox.setChecked(False)
        self.edit_scenario(scenario, replace(scenario.inputs, room_area=75.0))
        self.assert_watermarks(scenario, True)
        self.assert_watermarks(other, False)
        self.assertIs(widget, self.page._result_tab_widgets[scenario.node_id])
        self.assertFalse(checkbox.isChecked())
        widget.setCurrentIndex(1)
        self.assert_watermarks(scenario, True)

    def test_cancel_and_unchanged_edits_do_not_mark_results(self):
        scenario = self.add_run()
        self.edit_scenario(scenario, replace(scenario.inputs, room_area=75.0), accepted=False)
        self.assert_watermarks(scenario, False)
        self.edit_scenario(scenario, copy.deepcopy(scenario.inputs))
        self.assert_watermarks(scenario, False)
        self.edit_library(lambda: None)
        self.assert_watermarks(scenario, False)

    def test_shared_battery_change_only_marks_affected_scenarios(self):
        scenarios = [self.add_run(), self.add_run(), self.add_run(lib_spec="Unrelated")]
        self.edit_library(lambda: self.window.custom_lib_definitions.update({
            "Battery": replace(self.window.custom_lib_definitions["Battery"], cell_volume=30.0),
        }))
        for scenario, visible in zip(scenarios, [True, True, False]):
            self.assert_watermarks(scenario, visible)

    def test_deleted_or_renamed_battery_marks_results(self):
        scenario = self.add_run()
        self.edit_library(lambda: self.window.custom_lib_definitions.update({
            "Renamed": self.window.custom_lib_definitions.pop("Battery"),
        }))
        self.assertIsNone(scenario.lib_spec)
        self.assert_watermarks(scenario, True)

    def test_only_used_composition_and_flowrate_changes_mark_results(self):
        literature = self.add_run(gas_composition="Blend", flowrate_profile="Measured")
        custom = self.add_run(composition_method="User Defined", gas_composition="Blend")
        measured = self.add_run(
            calc_method=CALC_METHOD_MODULE_VARIABLE_FLOWRATE, flowrate_profile="Measured",
        )
        self.edit_library(lambda: self.window.custom_composition_definitions["Blend"]
                          .percentages.update({"co": 50.0, "h2": 50.0}))
        self.assert_watermarks(literature, False)
        self.assert_watermarks(custom, True)
        self.assert_watermarks(measured, False)
        self.edit_library(lambda: self.window.custom_flowrate_profiles["Measured"]
                          .flowrate_lps.__setitem__(1, 3.0))
        self.assert_watermarks(measured, True)
        self.assert_watermarks(literature, False)
        self.assertEqual(measured.result.flowrate_profile.flowrate_lps[1], 2.0)

    def test_rerun_only_clears_selected_scenarios_watermarks(self):
        first, second = self.add_run(), self.add_run()
        for scenario in (first, second):
            self.edit_scenario(scenario, replace(scenario.inputs, ventilation_rate=8.0))
        with patch.object(self.page, "_selected_scenario_node_ids", return_value={first.node_id}):
            self.page.run_calc()
        self.assert_watermarks(first, False)
        self.assert_watermarks(second, True)

    def test_failed_rerun_removes_old_plot(self):
        scenario = self.add_run()
        self.edit_scenario(scenario, replace(scenario.inputs, room_area=0.0))
        with patch.object(self.page, "_selected_scenario_node_ids",
                          return_value={scenario.node_id}), patch("venting_calculation.QMessageBox.warning"):
            self.page.run_calc()
        self.assertIsNone(scenario.result)
        self.assertNotIn(scenario.node_id, self.page._result_tab_widgets)
        self.assertEqual(self.page.result_tabs.count(), 0)

    def test_reverting_to_run_inputs_removes_warning(self):
        scenario = self.add_run()
        original = copy.deepcopy(scenario.inputs)
        self.edit_scenario(scenario, replace(original, room_area=75.0))
        self.assert_watermarks(scenario, True)
        self.edit_scenario(scenario, original)
        self.assert_watermarks(scenario, False)

    def test_deleted_used_libraries_mark_results(self):
        custom = self.add_run(composition_method="User Defined", gas_composition="Blend")
        measured = self.add_run(
            calc_method=CALC_METHOD_MODULE_VARIABLE_FLOWRATE, flowrate_profile="Measured",
        )
        self.edit_library(lambda: self.window.custom_composition_definitions.pop("Blend"))
        self.edit_library(lambda: self.window.custom_flowrate_profiles.pop("Measured"))
        self.assert_watermarks(custom, True)
        self.assert_watermarks(measured, True)

    def test_clear_and_close_discard_stale_plots(self):
        scenario = self.add_run()
        self.edit_scenario(scenario, replace(scenario.inputs, room_area=75.0))
        self.page._on_result_tab_close_requested(0)
        self.assertFalse(scenario.results_out_of_date)
        self.assertEqual(self.page.result_tabs.count(), 0)
        self.add_run()
        self.page.clear_results()
        self.assertEqual(self.page.result_tabs.count(), 0)
        self.assertFalse(self.page._result_tab_widgets)

    def test_save_load_restores_current_and_stale_watermarks(self):
        current = self.add_run(
            composition_method="User Defined", gas_composition="Blend",
            calc_method=CALC_METHOD_MODULE_VARIABLE_FLOWRATE, flowrate_profile="Measured",
        )
        stale = self.add_run()
        self.edit_scenario(stale, replace(stale.inputs, room_area=75.0))
        payload = json.loads(json.dumps(collect_state(self.window, "Warm Slate")))
        apply_state(self.window, payload)
        current = self.page.scenarios.get(current.node_id)
        stale = self.page.scenarios.get(stale.node_id)
        self.assert_watermarks(current, False)
        self.assert_watermarks(stale, True)
        self.assertEqual(current.result.flowrate_profile.flowrate_lps, [0.0, 2.0, 0.0])

    def test_older_result_without_required_snapshot_needs_rerun(self):
        scenario = self.add_run(
            calc_method=CALC_METHOD_MODULE_VARIABLE_FLOWRATE, flowrate_profile="Measured",
        )
        scenario.result.flowrate_profile = None
        self.page.restore_tree(self.page.tree_snapshot())
        self.assert_watermarks(scenario, True)


if __name__ == "__main__":
    unittest.main()
