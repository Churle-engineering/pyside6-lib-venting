import json
import os
import sys
import tempfile
import unittest

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
        spreadsheet = lib_page.current_spreadsheet()
        spreadsheet.table.setItem(0, 0, __import__("PySide6.QtWidgets", fromlist=["QTableWidgetItem"]).QTableWidgetItem("Test Scenario"))
        spreadsheet.on_cell_changed(0, 0)
        lib_page._sheet_results[id(spreadsheet)]["tox"]["Scenario 1"] = {
            "tox_max_mod": {"co": 3},
            "calc_method": "Module Volume UL9540A",
            "input": {"foo": 1.0},
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
            new_spreadsheet = new_lib_page.current_spreadsheet()
            self.assertEqual(new_spreadsheet.table.item(0, 0).text(), "Test Scenario")
            new_store = new_lib_page._sheet_results[id(new_spreadsheet)]
            self.assertIn("Scenario 1", new_store["tox"])
            self.assertEqual(new_store["tox"]["Scenario 1"]["tox_max_mod"]["co"], 3)

            new_sprinkler_page = new_window.page["SprinklerPage"]
            self.assertEqual(new_sprinkler_page.sprinkler_id.text(), "SPK-42")
            self.assertEqual(new_sprinkler_page.ceiling_height.text(), "3.5")
            self.assertEqual(new_sprinkler_page.last_activation_time_s, 123.4)

            new_pool_page = new_window.page["PoolSpillPage"]
            self.assertEqual(new_pool_page.ambient_temperature.text(), "300")
            self.assertTrue(new_pool_page.oi_tickbox.isChecked())
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
