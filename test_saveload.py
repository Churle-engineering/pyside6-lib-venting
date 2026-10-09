import json
import os
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QCheckBox

from information import CHEMICAL_PROPERTIES, FlowrateProfile, GasComposition, LIBInputs, LIBSpec
from main import BaseWindow, LIBPage, PoolSpillPage, ReceptorHeatFlux, SprinklerPage
from saveload import apply_state, collect_state, load_program_state, save_program_state
from scenario_model import GasResults, ScenarioResult
from venting_calculation import summarize_result


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.windows = []
        self.window = self.make_window()

    def make_window(self):
        window = BaseWindow()
        for name, page_type in (
            ("LIBPage", LIBPage), ("SprinklerPage", SprinklerPage),
            ("PoolSpillPage", PoolSpillPage), ("ReceptorHeatFluxPage", ReceptorHeatFlux),
        ):
            window.add_page(name, page_type(window))
        self.windows.append(window)
        return window

    def tearDown(self):
        for window in self.windows:
            window.deleteLater()
        self.app.processEvents()

    def populate(self):
        window = self.window
        spec = LIBSpec(name="Battery", cell_volume=27.5)
        window.custom_lib_definitions[spec.name] = spec
        composition = GasComposition("Blend", {"co": 60.0, "h2": 40.0})
        window.custom_composition_definitions[composition.name] = composition
        profile = FlowrateProfile("Measured", [0.0, 1.0, 2.0], [1.0, 2.0, 0.0])
        window.custom_flowrate_profiles[profile.name] = profile
        inputs = LIBInputs(
            scenario_description="Saved run", lib_spec=spec.name,
            gas_composition=composition.name, flowrate_profile=profile.name,
            emergency_vent_rate=12.5, vent_switch_conc=25.0, emergency_vent_delay=7.5,
            use_le_chatelier_lfl=True, use_temp_dependent_lfl=True,
        )
        page = window.page["LIBPage"]
        page.scenarios.add_group("Empty group")
        scenario = page.scenarios.add(inputs, "Study")
        page._apply_lib_spec(scenario)
        page._apply_composition(scenario)
        page._apply_flowrate_profile(scenario)
        result = ScenarioResult(
            scenario_name=scenario.name, calc_method=inputs.calc_method,
            inputs=LIBInputs(scenario_description=scenario.name),
            time=np.array([0., 1., 2.]), flowrate=np.array([1., 2., 0.]),
            total_gas_m3=np.array([0., 1., 2.]), total_gas_vv=np.array([0., 2., 4.]),
            flammable=GasResults(["co"], np.array([[0., 1., 2.]]),
                                 np.array([[0., 2., 4.]]), np.array([1.165])),
            toxic=GasResults(["co"], np.array([[0., 1., 2.]]),
                             np.array([[0., 2., 4.]]), np.array([1.165])),
            lfl_percent=12.5, lib_spec=LIBSpec(name="Battery", cell_volume=20.0),
        )
        scenario.result = result
        scenario.summary = summarize_result(result, CHEMICAL_PROPERTIES)
        # The latest inputs/library must not overwrite the historical run snapshot.
        scenario.inputs.room_area = 99.0
        page.restore_tree(page.tree_snapshot())
        return page.scenarios.get(scenario.node_id)

    def test_result_round_trip_rebuilds_plots_summary_and_bindings(self):
        original = self.populate()
        payload = json.loads(json.dumps(collect_state(self.window, "Warm Slate")))
        restored_window = self.make_window()
        self.assertEqual(apply_state(restored_window, payload), "Warm Slate")
        page = restored_window.page["LIBPage"]
        restored = page.scenarios.get(original.node_id)
        self.assertIsNotNone(restored.result)
        np.testing.assert_array_equal(restored.result.time, original.result.time)
        np.testing.assert_array_equal(restored.result.toxic.conc_vv, original.result.toxic.conc_vv)
        self.assertEqual(restored.result.lib_spec.cell_volume, 20.0)
        self.assertEqual(restored.lib_spec.cell_volume, 27.5)
        self.assertIs(restored.lib_spec, restored_window.custom_lib_definitions["Battery"])
        self.assertIs(restored.gas_composition, restored_window.custom_composition_definitions["Blend"])
        self.assertIs(restored.flowrate_profile, restored_window.custom_flowrate_profiles["Measured"])
        for field in fields(LIBInputs):
            self.assertEqual(getattr(restored.inputs, field.name), getattr(original.inputs, field.name))
        self.assertEqual(restored.summary.peak_flammable_vv, 4.0)
        self.assertEqual(page.result_tabs.count(), 1)
        self.assertEqual(page.summary_stack.currentWidget().rowCount(), 1)
        self.assertEqual(page.scenarios.group_names, ["Empty group", "Study"])

    def test_pool_inputs_and_optional_visibility_round_trip(self):
        page = self.window.page["PoolSpillPage"]
        page.ground_conditions.setCurrentText("Custom")
        for name, value in (
            ("pool_depth", "0.02"),
            ("operator_intervention_time", "10"),
        ):
            getattr(page, name).setText(value)
        page.oi_tickbox.setChecked(True)
        page.pool_fire_tickbox.setChecked(True)
        page.results_label.setText("Saved provisional pool result")
        target = self.make_window()
        apply_state(target, json.loads(json.dumps(collect_state(self.window))))
        restored = target.page["PoolSpillPage"]
        self.assertEqual(restored.pool_depth.text(), "0.02")
        self.assertEqual(restored.ground_conditions.currentText(), "Custom")
        self.assertFalse(restored.pool_depth.isReadOnly())
        self.assertFalse(hasattr(restored, "kinematic_viscosity"))
        self.assertTrue(restored.pool_fire_tickbox.isChecked())
        self.assertFalse(restored.optional_group.isHidden())
        self.assertEqual(restored.results_label.text(), page.results_label.text())
        page.ground_conditions.setCurrentText("rough")
        apply_state(target, json.loads(json.dumps(collect_state(self.window))))
        self.assertEqual(restored.ground_conditions.currentText(), "rough")
        self.assertEqual(restored.pool_depth.text(), "0.02")
        self.assertTrue(restored.pool_depth.isReadOnly())

    def test_sprinkler_result_and_navigation_round_trip(self):
        page = self.window.page["SprinklerPage"]
        page.ceiling_height.setText("3.5")
        page.last_activation_time_s = 123.45
        page.results_label.setText("Saved sprinkler result")
        page.copy_activation_button.setEnabled(True)
        self.window.show_page("SprinklerPage")
        target = self.make_window()
        apply_state(target, json.loads(json.dumps(collect_state(self.window))))
        restored = target.page["SprinklerPage"]
        self.assertEqual(restored.last_activation_time_s, 123.45)
        self.assertTrue(restored.copy_activation_button.isEnabled())
        self.assertEqual(restored.results_label.text(), "Saved sprinkler result")
        self.assertIs(target.current_page(), restored)
        self.assertEqual(target.page_history, [])

    def test_sprinkler_calculation_inputs_and_history_round_trip(self):
        page = self.window.page["SprinklerPage"]
        for name, value in (("sprinkler_id", "SPK-7"), ("sprinkler_rti", "50"),
                            ("activation_temperature", "68"), ("ceiling_height", "3"),
                            ("radial_distance", "2"), ("ambient_temperature", "20")):
            getattr(page, name).setText(value)
        page.fire_growth_rate.setCurrentIndex(page.fire_growth_rate.count() - 1)
        page.run_sprinkler_calc()
        page.run_sprinkler_calc()
        target = self.make_window()
        apply_state(target, json.loads(json.dumps(collect_state(self.window))))
        restored = target.page["SprinklerPage"]
        self.assertEqual(restored.result_history, page.result_history)
        self.assertIn("detector_temperature_c", restored.result_history[0])
        self.assertEqual(restored.last_activation_time_s, page.last_activation_time_s)
        self.assertEqual(restored.history_table.rowCount(), 2)
        self.assertEqual(restored.latest_value_label.text(), page.latest_value_label.text())
        self.assertEqual(restored.results_label.text(), page.results_label.text())
        self.assertEqual(restored.sprinkler_id.text(), "SPK-7")
        self.assertEqual(restored.fire_growth_rate.currentText(), page.fire_growth_rate.currentText())

    def test_receptor_heat_flux_inputs_units_and_history_round_trip(self):
        page = self.window.page["ReceptorHeatFluxPage"]
        page.input_mode.setCurrentText(page.MODE_TEMPERATURE)
        page.distance_mode.setCurrentText(page.DISTANCE_RANGE)
        page.receptor_id.setText("R-9")
        for name, value in (("emitter_temperature", "1000"), ("emissivity", "0.9"),
                            ("range_start", "1"), ("range_end", "3"), ("range_step", "1")):
            getattr(page, name).setText(value)
        page._set_units([("Unit A", "5", "2"), ("Unit B", "4", "1")])
        page.plot_height.setValue(500)
        page.plot_width.setValue(800)
        page.run_heat_flux_calc()
        self.assertEqual(len(page.result_history), 6)
        target = self.make_window()
        apply_state(target, json.loads(json.dumps(collect_state(self.window))))
        restored = target.page["ReceptorHeatFluxPage"]
        self.assertEqual(restored.result_history, page.result_history)
        self.assertEqual(restored._unit_rows(), [("Unit A", "5", "2"), ("Unit B", "4", "1")])
        self.assertEqual(restored.input_mode.currentText(), page.MODE_TEMPERATURE)
        self.assertEqual(restored.distance_mode.currentText(), page.DISTANCE_RANGE)
        self.assertEqual(restored.emitter_temperature.text(), "1000")
        self.assertEqual(restored.range_end.text(), "3")
        self.assertEqual((restored.plot_height.value(), restored.plot_width.value()), (500, 800))
        self.assertEqual(restored.history_table.rowCount(), 6)
        self.assertEqual(restored.latest_value_label.text(), page.latest_value_label.text())
        self.assertEqual(restored.results_label.text(), page.results_label.text())
        self.assertEqual(len(restored.axes.get_lines()), 2)
        restored.run_heat_flux_calc()
        self.assertEqual(restored._latest_run_number(), 2)

    def test_plot_visibility_tab_and_tree_selection_round_trip(self):
        scenario = self.populate()
        page = self.window.page["LIBPage"]
        page._refresh_tree(select_node_id=scenario.node_id)
        page.scenario_tree_inner.topLevelItem(0).setExpanded(False)
        plots = page._result_tab_widgets[scenario.node_id]
        plots.setCurrentIndex(1)
        box = next(box for box in plots.widget(0).findChildren(QCheckBox) if box.text() == "CO")
        box.setChecked(True)
        target = self.make_window()
        apply_state(target, json.loads(json.dumps(collect_state(self.window))))
        restored = target.page["LIBPage"]
        restored_plots = restored._result_tab_widgets[scenario.node_id]
        self.assertEqual(restored_plots.currentIndex(), 1)
        restored_box = next(
            box for box in restored_plots.widget(0).findChildren(QCheckBox) if box.text() == "CO"
        )
        self.assertTrue(restored_box.isChecked())
        self.assertFalse(restored.scenario_tree_inner.topLevelItem(0).isExpanded())
        self.assertEqual(restored._selected_scenario_node_ids(), {scenario.node_id})
        self.assertIs(restored.result_tabs.currentWidget(), restored_plots)

    def test_ungrouped_scenario_and_new_ids_are_preserved(self):
        page = self.window.page["LIBPage"]
        page.scenarios.add(LIBInputs(scenario_description="Ungrouped scenario"))
        page.scenarios.add(LIBInputs(scenario_description="Second"), "Named group")
        payload = json.loads(json.dumps(collect_state(self.window)))
        target = self.make_window()
        apply_state(target, payload)
        store = target.page["LIBPage"].scenarios
        self.assertEqual(store.get(1).group, "")
        self.assertEqual(store.group_names, ["Named group"])
        self.assertEqual(store.add(LIBInputs()).node_id, 3)

    def test_version_four_input_only_save_clears_stale_outputs(self):
        self.populate()
        payload = collect_state(self.window)
        payload["version"] = 4
        payload.pop("active_page")
        for entry in payload["pages"].values():
            entry.pop("session")
        for group in payload["pages"]["LIBPage"]["study_tree"]:
            for scenario in group["__dict__"]["scenarios"]:
                scenario["fields"].pop("result")
                # Removed and newly-added dataclass fields remain compatible.
                scenario["fields"]["inputs"]["fields"]["obsolete_field"] = 42
                scenario["fields"]["inputs"]["fields"].pop("use_temp_dependent_lfl")
        sprinkler = self.window.page["SprinklerPage"]
        sprinkler.last_activation_time_s = 99.0
        sprinkler.copy_activation_button.setEnabled(True)
        sprinkler.results_label.setText("Old output")
        self.window.page["PoolSpillPage"].results_label.setText("Old pool output")
        apply_state(self.window, json.loads(json.dumps(payload)))
        page = self.window.page["LIBPage"]
        self.assertIsNone(page.scenarios.get(1).result)
        self.assertIsNone(page.scenarios.get(1).summary)
        self.assertFalse(page.scenarios.get(1).inputs.use_temp_dependent_lfl)
        self.assertEqual(page.result_tabs.count(), 0)
        self.assertIsNone(sprinkler.last_activation_time_s)
        self.assertFalse(sprinkler.copy_activation_button.isEnabled())
        self.assertNotEqual(sprinkler.results_label.text(), "Old output")
        self.assertNotEqual(self.window.page["PoolSpillPage"].results_label.text(), "Old pool output")

    def test_save_and_open_public_entry_points(self):
        original = self.populate()
        target = self.make_window()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "session.libsave")
            self.assertEqual(save_program_state(self.window, "Warm Slate", path), path)
            self.assertEqual(load_program_state(target, path), (path, "Warm Slate"))
            self.assertEqual(target.current_save_path, path)
            restored = target.page["LIBPage"].scenarios.get(original.node_id)
            np.testing.assert_array_equal(restored.result.flowrate, original.result.flowrate)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["session.libsave"])

    def test_failed_save_does_not_truncate_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.libsave"
            path.write_text("previous session", encoding="utf-8")
            with patch("saveload.json.dump", side_effect=TypeError("Unsupported state")), \
                    patch("saveload.QMessageBox.critical") as error:
                self.assertIsNone(save_program_state(self.window, path=str(path)))
            error.assert_called_once()
            self.assertEqual(path.read_text(encoding="utf-8"), "previous session")
            self.assertIsNone(self.window.current_save_path)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["session.libsave"])

    def test_invalid_file_does_not_replace_live_state(self):
        original = self.populate()
        payload = collect_state(self.window)
        scenarios = payload["pages"]["LIBPage"]["study_tree"][1]["__dict__"]["scenarios"]
        scenarios[0]["fields"]["result"]["fields"]["time"] = "not an array"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.libsave"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("saveload.QMessageBox.critical") as error:
                self.assertEqual(load_program_state(self.window, str(path)), (None, None))
            error.assert_called_once()
        self.assertIs(self.window.page["LIBPage"].scenarios.get(original.node_id), original)
        self.assertIs(original.lib_spec, self.window.custom_lib_definitions["Battery"])
        self.assertIsNone(self.window.current_save_path)

    def test_empty_optional_sections_and_invalid_page_state(self):
        self.assertIsNone(apply_state(self.window, {}))
        for pages in (
            [], {"PoolSpillPage": {"widgets": []}},
            {"SprinklerPage": {"session": {"activation_time_s": "bad"}}},
            {"SprinklerPage": {"session": {"history": [{"rti": "fast"}]}}},
            {"ReceptorHeatFluxPage": {"session": {"history": [{"run": 1}]}}},
            {"ReceptorHeatFluxPage": {"session": {"units": [{"name": 5}]}}},
            {"ReceptorHeatFluxPage": {"session": {"plot_height": "tall"}}},
            {"LIBPage": {"session": {"plots": [{"node_id": []}]}}},
        ):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                apply_state(self.window, {"pages": pages})

    def test_real_calculation_can_be_loaded_and_run_again(self):
        spec = LIBSpec(name="Short run", cell_volume=10.0, cell_duration=2.0, lfl=5.0)
        self.window.custom_lib_definitions[spec.name] = spec
        page = self.window.page["LIBPage"]
        scenario = page.scenarios.add(LIBInputs(
            lib_spec=spec.name, calc_duration=10, cells_per_module=1,
            modules_per_unit=1, units=1,
        ), "Short study")
        page._apply_lib_spec(scenario)
        with patch("main.QMessageBox.warning") as warning:
            page.run_calc()
        warning.assert_not_called()
        self.assertIsNotNone(scenario.result)
        target = self.make_window()
        apply_state(target, json.loads(json.dumps(collect_state(self.window))))
        restored_page = target.page["LIBPage"]
        restored = restored_page.scenarios.get(scenario.node_id)
        np.testing.assert_array_equal(restored.result.total_gas_vv, scenario.result.total_gas_vv)
        np.testing.assert_array_equal(restored.result.active_cells, scenario.result.active_cells)
        from resultstable import ResultsTableDialog
        dialog = ResultsTableDialog(restored_page, [restored])
        self.assertIsNotNone(dialog)
        dialog.deleteLater()
        with patch("main.QMessageBox.warning") as warning:
            restored_page.run_calc()
        warning.assert_not_called()
        np.testing.assert_array_equal(restored.result.total_gas_vv, scenario.result.total_gas_vv)
        restored_page._on_result_tab_close_requested(0)
        payload = collect_state(target)
        apply_state(self.window, json.loads(json.dumps(payload)))
        self.assertIsNone(self.window.page["LIBPage"].scenarios.get(scenario.node_id).result)
        self.assertEqual(self.window.page["LIBPage"].result_tabs.count(), 0)


if __name__ == "__main__":
    unittest.main()
