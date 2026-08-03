import json
import os
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from main import (
    BaseWindow,
    IntroPage,
    LIBPage,
    SprinklerPage,
    PoolSpillPage,
    ReceptorHeatFlux,
)
from saveload import collect_program_state, restore_program_state

_APP = QApplication.instance() or QApplication([])


def _build_window():
    window = BaseWindow()
    window.add_page("IntroPage", IntroPage(window))
    window.add_page("LIBPage", LIBPage(window))
    window.add_page("SprinklerPage", SprinklerPage(window))
    window.add_page("PoolSpillPage", PoolSpillPage(window))
    window.add_page("ReceptorHeatFluxPage", ReceptorHeatFlux(window))
    return window


class SaveLoadRoundTripTests(unittest.TestCase):
    def test_roundtrip_preserves_inputs_and_results(self):
        window = _build_window()

        lib_page = window.page["LIBPage"]

        # Build a deterministic scenario tree: Project -> Type -> Scenario.
        tree_widget = lib_page.scenario_tree
        tree_widget.tree.clear()
        globals_map = tree_widget._add_project.__globals__
        project_cls = globals_map["ProjectTreeItem"]
        type_cls = globals_map["ScenarioTypeTreeItem"]
        scenario_cls = globals_map["ScenarioTreeItem"]

        project = project_cls("Project A")
        tree_widget.tree.addTopLevelItem(project)
        scenario_type = type_cls("Type A")
        project.addChild(scenario_type)
        scenario_payload = {
            "Scenario Description": "Scenario 1",
            "LIB Type": "Custom-LIB-1",
            "Calculation Duration (s)": "600",
            "Ventilation Rate (L/s/m2)": "5",
        }
        scenario_item = scenario_cls("Scenario 1", data=scenario_payload)
        scenario_type.addChild(scenario_item)

        window.custom_lib_definitions["Custom-LIB-1"] = {
            "LFL (%)": "4.0",
            "Battery Charge (%)": "100",
            "CO (%)": "5",
            "CO2 (%)": "10",
            "H2 (%)": "25",
            "Total Hydrocarbons (%)": "60",
        }
        window.custom_composition_definitions["Comp-1"] = {
            "co": 5.0,
            "co2": 10.0,
            "h2": 25.0,
            "total_hydrocarbons": 60.0,
        }

        window.tox_scenario_results["Scenario 1"] = {
            "tox_vv_df": pd.DataFrame({"Time (s)": [0.0, 1.0], "CO (ppm)": [0.0, 50.0]}),
            "tox_summary_headers": ["Scenario"],
            "tox_summary_row_data": ["Scenario 1"],
        }
        window.flam_scenario_results["Scenario 1"] = {
            "flam_vv_df": pd.DataFrame({"Time (s)": [0.0, 1.0], "% LFL": [0.0, 15.0]}),
            "flam_summary_headers": ["Scenario"],
            "flam_summary_row_data": ["Scenario 1"],
        }

        sprinkler_page = window.page["SprinklerPage"]
        sprinkler_page.sprinkler_id.setText("SPK-42")
        sprinkler_page.ceiling_height.setText("3.5")
        sprinkler_page.last_activation_time_s = 123.4

        pool_page = window.page["PoolSpillPage"]
        pool_page.ambient_temperature.setText("300")
        pool_page.oi_tickbox.setChecked(True)

        payload = collect_program_state(window)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".libsave", delete=False, encoding="utf-8") as f:
            json.dump(payload, f)
            path = f.name

        try:
            with open(path, "r", encoding="utf-8") as f:
                reloaded_payload = json.load(f)

            new_window = _build_window()
            restore_program_state(new_window, reloaded_payload)

            new_lib_page = new_window.page["LIBPage"]
            root = new_lib_page.scenario_tree.tree.invisibleRootItem()
            self.assertEqual(root.childCount(), 1)
            self.assertEqual(root.child(0).project_name, "Project A")
            self.assertEqual(root.child(0).childCount(), 1)
            self.assertEqual(root.child(0).child(0).type_name, "Type A")
            self.assertEqual(root.child(0).child(0).childCount(), 1)
            restored_scenario = root.child(0).child(0).child(0)
            self.assertEqual(restored_scenario.scenario_name, "Scenario 1")
            self.assertEqual(restored_scenario.scenario_data["LIB Type"], "Custom-LIB-1")

            self.assertIn("Scenario 1", new_window.tox_scenario_results)
            self.assertIn("Scenario 1", new_window.flam_scenario_results)
            tox_df = new_window.tox_scenario_results["Scenario 1"]["tox_vv_df"]
            flam_df = new_window.flam_scenario_results["Scenario 1"]["flam_vv_df"]
            self.assertEqual(float(tox_df["CO (ppm)"].iloc[-1]), 50.0)
            self.assertEqual(float(flam_df["% LFL"].iloc[-1]), 15.0)
            self.assertIn("Custom-LIB-1", new_window.custom_lib_definitions)
            self.assertIn("Comp-1", new_window.custom_composition_definitions)

            new_sprinkler_page = new_window.page["SprinklerPage"]
            self.assertEqual(new_sprinkler_page.sprinkler_id.text(), "SPK-42")
            self.assertEqual(new_sprinkler_page.ceiling_height.text(), "3.5")
            self.assertEqual(new_sprinkler_page.last_activation_time_s, 123.4)

            new_pool_page = new_window.page["PoolSpillPage"]
            self.assertEqual(new_pool_page.ambient_temperature.text(), "300")
            self.assertTrue(new_pool_page.oi_tickbox.isChecked())
        finally:
            os.remove(path)

    def test_user_defined_composition_uses_direct_total_volume_percentages(self):
        window = _build_window()
        lib_page = window.page["LIBPage"]

        window.custom_composition_definitions["Comp-Direct"] = {
            "co": 10.0,
            "h2": 5.0,
            "total_hydrocarbons": 5.0,
            "co2": 20.0,
        }

        scenario = {
            "Scenario Description": "User Comp Scenario",
            "Composition Method": "User Defined",
            "Gas Composition": "Comp-Direct",
            "LIB Type": "NMC",
        }

        merged = lib_page._apply_composition_to_scenario(scenario)

        # Toxic share should be the sum of toxic composition percentages.
        self.assertAlmostEqual(float(merged.get("_percent_tox_override", -1)), 40.0)

        # Flammable share should be absolute % of total volume,
        # while per-gas flammable fields are normalized to a 100% split.
        self.assertAlmostEqual(float(merged.get("_flam_percent_override", -1)), 20.0)
        self.assertAlmostEqual(float(merged.get("co_(%)", -1)), 50.0)
        self.assertAlmostEqual(float(merged.get("h2_(%)", -1)), 25.0)
        self.assertAlmostEqual(float(merged.get("total_hydrocarbons_(%)", -1)), 25.0)


if __name__ == "__main__":
    unittest.main()
