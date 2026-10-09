import math
import os
import unittest
from importlib import import_module
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from information import POOL_PROPERTIES, POOL_SPREAD_DATA
from main import PoolSpillPage

pool = import_module("spill_poolfire")


class PoolCalculationTests(unittest.TestCase):
    def setUp(self):
        self.inputs = dict(
            bund_area=12.0, fuel="benzene", wind_speed=2.0,
            orifice_diameter=0.01, delta_p=1000.0,
            ambient_temperature=293.0, volumetric_flow_rate=0.001,
            surface="finished concrete", weather="dry",
            orifice_condition="sharp",
            ground_description="normal",
        )

    def test_spill_uses_orifice_condition_and_caps_area_by_bund(self):
        result = pool.calculate_pool_assessment(**self.inputs)
        fuel = POOL_SPREAD_DATA["benzene"]
        raw_area = (
            0.61 * math.pi * (0.01 / 2) ** 2 * pool.R * 293
            * math.sqrt(2 * fuel["density"] * 1000)
            / (18.3e-3 * 2 ** 0.78
                    * fuel["liquid vapour pressure"] * fuel["molar mass"] ** 0.667)
        )
        area_max = min(raw_area, 12)
        permeability_area = (
            1.7715 * 0.001 * fuel["kinematic_viscosity"] / (9.81 * 1e-18)
        )
        self.assertAlmostEqual(result["area_max_m2"], area_max)
        self.assertAlmostEqual(result["area_permeability_m2"], permeability_area)
        self.assertAlmostEqual(
            result["pool_area_m2"],
            area_max * permeability_area / (area_max + permeability_area),
        )
        self.assertNotIn("burn_duration_s", result)
        self.assertNotIn("uninterrupted_duration_s", result)
        self.assertNotIn("area_intervention_m2", result)
        alternate_fuel = pool.calculate_pool_assessment(
            **{**self.inputs, "fuel": "hexane"},
        )
        expected_alternate_area = (
            1.7715 * 0.001 * POOL_SPREAD_DATA["hexane"]["kinematic_viscosity"]
            / (9.81 * 1e-18)
        )
        self.assertAlmostEqual(alternate_fuel["area_permeability_m2"], expected_alternate_area)
        capped = pool.calculate_pool_assessment(**{**self.inputs, "bund_area": 0.01})
        self.assertAlmostEqual(capped["area_max_m2"], 0.01)

    def test_intervention_and_fire_use_final_area_and_depth(self):
        result = pool.calculate_pool_assessment(
            **self.inputs, intervention_time=10,
            include_fire=True, pool_depth=0.02,
        )
        fuel = POOL_SPREAD_DATA["benzene"]
        expected_hrr_kw = (
            fuel["mass burning rate"] * fuel["heat of combustion"]
            * (1 - math.exp(-fuel["empirical constant"] * result["pool_diameter_m"]))
            * result["pool_area_m2"]
        )
        self.assertAlmostEqual(result["heat_release_rate"], expected_hrr_kw)

    def test_bad_inputs_are_rejected(self):
        for changes in (
            {"wind_speed": 0},
            {"bund_area": float("nan")},
            {"weather": "saturated"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                pool.calculate_pool_assessment(**{**self.inputs, **changes})
        with self.assertRaisesRegex(ValueError, "missing verified property data: kinematic_viscosity"):
            pool.calculate_pool_assessment(**{**self.inputs, "fuel": "methanol"})
        with self.assertRaisesRegex(ValueError, "Pool depth"):
            pool.calculate_pool_assessment(**self.inputs, include_fire=True, pool_depth=0)
        with self.assertRaisesRegex(ValueError, "positive pool area"):
            pool.calculate_pool_assessment(
                **self.inputs, intervention_time=0,
                include_fire=True, pool_depth=0.02,
            )

    def test_plain_spill_does_not_require_pool_depth_or_evaporation(self):
        result = pool.calculate_pool_assessment(
            **{**self.inputs, "ground_description": "Custom"},
        )
        self.assertEqual(set(result), {
            "area_max_m2", "area_permeability_m2", "area_combined_m2", "pool_area_m2",
        })
        self.assertEqual(result["pool_area_m2"], result["area_combined_m2"])

    def test_presets_and_calculated_evaporation_need_no_rate_input(self):
        fuel = POOL_SPREAD_DATA["benzene"]
        evaporation_per_area = (
            18.3e-3 * 2 ** 0.78 * fuel["liquid vapour pressure"] * fuel["molar mass"] ** 0.667
            / (pool.R * 293 * fuel["density"])
        )
        for ground, depth in POOL_PROPERTIES["average_pool_height"].items():
            with self.subTest(ground=ground):
                result = pool.calculate_pool_assessment(
                    **{**self.inputs, "ground_description": ground},
                    include_fire=True, intervention_time=10,
                )
                self.assertEqual(result["pool_depth_m"], depth)
                self.assertAlmostEqual(result["pool_volume_m3"], result["pool_area_m2"] * depth)
                self.assertAlmostEqual(result["burn_duration_s"], depth * fuel["density"] / fuel["mass burning rate"])
                self.assertAlmostEqual(
                    result["area_intervention_m2"],
                    result["area_combined_m2"] * (1 - 0.5 ** (10 * evaporation_per_area * 5400 / depth)),
                )
                self.assertEqual(result["pool_area_m2"], result["area_intervention_m2"])


class PoolPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = PoolSpillPage(None)
        self.assertEqual(self.page.fuel_material.currentText(), "diesel")
        self.page.ground_conditions.setCurrentText("Custom")
        for field, value in (
            ("bund_size", "12"), ("wind_speed", "2"),
            ("orifice_diameter", "0.01"), ("delta_p", "1000"),
            ("ambient_temperature", "293"), ("volumetric_flowrate", "0.001"),
            ("pool_depth", "0.02"),
        ):
            getattr(self.page, field).setText(value)

    def tearDown(self):
        self.page.close()

    def test_run_spill_and_fire_with_table_coefficient(self):
        calculate = next(
            button for button in self.page.findChildren(QPushButton)
            if button.text() == "Calculate"
        )
        calculate.click()
        for name in ("area_max", "area_permeability", "area_combined"):
            self.assertIn(name, self.page.results_label.text())
        self.assertNotIn("Uninterrupted pool duration", self.page.results_label.text())
        self.assertNotIn("Burn duration:", self.page.results_label.text())
        self.page.pool_fire_tickbox.setChecked(True)
        self.page.pool_depth.setText("0.02")
        self.page.oi_tickbox.setChecked(True)
        self.page.operator_intervention_time.setText("10")
        with patch("main.QMessageBox.warning") as warning:
            calculate.click()
        warning.assert_not_called()
        self.assertIn("Burn duration:", self.page.results_label.text())
        self.assertIn("Heat release rate:", self.page.results_label.text())
        self.assertIn(" kW", self.page.results_label.text())
        self.assertIn("Flame height (Heskestad):", self.page.results_label.text())
        self.assertIn("Flame height (Thomas):", self.page.results_label.text())

    def test_invalid_input_clears_stale_result(self):
        self.page.run_pool_calculation()
        self.page.wind_speed.setText("0")
        with patch("main.QMessageBox.warning") as warning:
            self.page.run_pool_calculation()
        warning.assert_called_once()
        self.assertFalse(self.page.copy_result_button.isEnabled())
        self.assertEqual(
            self.page.results_label.text(), "Calculation not available for these inputs."
        )

    def test_toggle_combinations_only_consume_enabled_optional_inputs(self):
        for intervention in (False, True):
            for fire in (False, True):
                with self.subTest(intervention=intervention, fire=fire):
                    self.page.oi_tickbox.setChecked(intervention)
                    self.page.pool_fire_tickbox.setChecked(fire)
                    self.page.operator_intervention_time.setText("10" if intervention else "invalid")
                    self.page.pool_depth.setText("0.02" if intervention or fire else "invalid")
                    self.assertEqual(self.page.optional_group.isHidden(), not intervention)
                    self.assertEqual(self.page.pool_depth_group.isHidden(), not (intervention or fire))
                    with patch("main.QMessageBox.warning") as warning:
                        self.page.run_pool_calculation()
                    warning.assert_not_called()
                    text = self.page.results_label.text()
                    for name in ("area_max", "area_permeability", "area_combined"):
                        self.assertIn(name, text)
                    self.assertNotIn("Uninterrupted pool duration", text)
                    self.assertEqual("Operator intervention area:" in text, intervention)
                    self.assertEqual("Burn duration:" in text, fire)

    def test_copy_clear_and_restore_results(self):
        self.page.run_pool_calculation()
        state = self.page.session_snapshot()
        self.page.copy_latest_result()
        self.assertEqual(QApplication.clipboard().text(), state["results_text"])
        self.page.clear_inputs()
        self.assertTrue(all(not edit.text() for edit in self.page._numeric_inputs
                    if edit is not self.page.pool_depth))
        self.assertEqual(self.page.pool_depth.text(), "0.01")
        self.assertEqual(self.page.results_label.text(), state["results_text"])
        self.page.clear_results()
        self.assertEqual(self.page.results_label.text(), self.page.PLACEHOLDER_TEXT)
        self.assertFalse(self.page.copy_result_button.isEnabled())
        self.page.restore_session(state)
        self.assertEqual(self.page.results_label.text(), state["results_text"])
        self.assertTrue(self.page.copy_result_button.isEnabled())

    def test_custom_depth_is_required(self):
        self.page.pool_fire_tickbox.setChecked(True)
        self.page.pool_depth.clear()
        with patch("main.QMessageBox.warning") as warning:
            self.page.run_pool_calculation()
        warning.assert_called_once()
        self.assertFalse(self.page.copy_result_button.isEnabled())

    def test_depth_presets_and_custom_without_evaporation_input(self):
        self.assertFalse(hasattr(self.page, "average_evaporation_rate"))
        self.page.pool_fire_tickbox.setChecked(True)
        for ground, depth in POOL_PROPERTIES["average_pool_height"].items():
            with self.subTest(ground=ground):
                self.page.ground_conditions.setCurrentText(ground)
                self.assertTrue(self.page.pool_depth.isReadOnly())
                self.assertEqual(float(self.page.pool_depth.text()), depth)
                with patch("main.QMessageBox.warning") as warning:
                    self.page.run_pool_calculation()
                warning.assert_not_called()
                self.assertIn(f"Pool depth: {depth:g} m", self.page.results_label.text())
        self.page.ground_conditions.setCurrentText("Custom")
        self.assertFalse(self.page.pool_depth.isReadOnly())
        self.page.pool_depth.setText("0.03")
        with patch("main.QMessageBox.warning") as warning:
            self.page.run_pool_calculation()
        warning.assert_not_called()
        self.assertIn("Pool depth: 0.03 m", self.page.results_label.text())

    def test_legacy_saved_manual_depth_is_restored_as_custom(self):
        self.page.ground_conditions.setCurrentText("normal")
        self.page.pool_depth.setText("0.017")
        self.page.restore_session({})
        self.assertEqual(self.page.ground_conditions.currentText(), "Custom")
        self.assertFalse(self.page.pool_depth.isReadOnly())
        self.assertEqual(self.page.pool_depth.text(), "0.017")


if __name__ == "__main__":
    unittest.main()
