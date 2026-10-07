import math
import os
import unittest
from importlib import import_module
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from information import POOL_SPREAD_DATA
from main import PoolSpillPage

pool = import_module("spill&poolfire")


class PoolCalculationTests(unittest.TestCase):
    def setUp(self):
        self.inputs = dict(
            bund_area=12.0, fuel="methanol", wind_speed=2.0,
            orifice_diameter=0.01, delta_p=1000.0,
            ambient_temperature=293.0, volumetric_flow_rate=0.001,
            surface="finished concrete", weather="dry",
            orifice_condition="sharp", kinematic_viscosity=1e-6,
            ground_description="normal",
        )

    def test_spill_uses_orifice_condition_and_caps_area_by_bund(self):
        result = pool.calculate_pool_assessment(**self.inputs)
        fuel = POOL_SPREAD_DATA["methanol"]
        raw_area = (
            0.61 * math.pi * (0.01 / 2) ** 2 * pool.R * 293
            * math.sqrt(2 * fuel["density"] * 1000)
            / (18.3e-3 * 2 ** 0.78
               * fuel["liquid vapour pressure"] * fuel["molar mass"])
        )
        area_max = min(raw_area, 12)
        permeability_area = 1.7715 * 0.001 * 1e-6 / (9.81 * 1e-18)
        self.assertAlmostEqual(result["area_max_m2"], area_max)
        self.assertAlmostEqual(result["area_permeability_m2"], permeability_area)
        self.assertAlmostEqual(
            result["pool_area_m2"],
            area_max * permeability_area / (area_max + permeability_area),
        )
        self.assertNotIn("burn_duration_s", result)
        capped = pool.calculate_pool_assessment(**{**self.inputs, "bund_area": 0.01})
        self.assertAlmostEqual(capped["area_max_m2"], 0.01)

    def test_intervention_and_fire_use_final_area_and_depth(self):
        result = pool.calculate_pool_assessment(
            **self.inputs, intervention_time=10, evaporation_rate=0.001,
            include_fire=True, pool_depth=0.02,
        )
        adjusted = result["area_combined_m2"] * (
            1 - 0.5 ** (10 * 0.001 / (result["area_max_m2"] * 0.01))
        )
        self.assertAlmostEqual(result["pool_area_m2"], adjusted)
        diameter = math.sqrt(4 * adjusted / math.pi)
        self.assertAlmostEqual(result["pool_diameter_m"], diameter)
        self.assertAlmostEqual(result["pool_volume_m3"], adjusted * 0.02)
        fuel = POOL_SPREAD_DATA["methanol"]
        self.assertAlmostEqual(
            result["heat_release_rate"],
            fuel["mass burning rate"] * fuel["heat of combustion"]
            * (1 - math.exp(-fuel["empirical constant"] * diameter)) * adjusted,
        )
        self.assertAlmostEqual(
            result["burn_duration_s"], 0.02 * fuel["density"] / fuel["mass burning rate"]
        )
        self.assertAlmostEqual(
            result["flame_height_thomas_m"],
            42 * diameter * (
                fuel["mass burning rate"] / (1.18 * math.sqrt(9.81 * diameter))
            ) ** 0.61,
        )

    def test_bad_inputs_are_rejected(self):
        for changes in (
            {"wind_speed": 0},
            {"bund_area": float("nan")},
            {"weather": "saturated"},
            {"kinematic_viscosity": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                pool.calculate_pool_assessment(**{**self.inputs, **changes})
        with self.assertRaisesRegex(ValueError, "Pool depth"):
            pool.calculate_pool_assessment(**self.inputs, include_fire=True)
        with self.assertRaisesRegex(ValueError, "evaporation rate"):
            pool.calculate_pool_assessment(**self.inputs, intervention_time=5)
        with self.assertRaisesRegex(ValueError, "positive pool area"):
            pool.calculate_pool_assessment(
                **self.inputs, intervention_time=0, evaporation_rate=0.001,
                include_fire=True, pool_depth=0.02,
            )


class PoolPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = PoolSpillPage(None)
        for field, value in (
            ("bund_size", "12"), ("wind_speed", "2"),
            ("orifice_diameter", "0.01"), ("delta_p", "1000"),
            ("ambient_temperature", "293"), ("volumetric_flowrate", "0.001"),
            ("kinematic_viscosity", "0.000001"),
        ):
            getattr(self.page, field).setText(value)

    def tearDown(self):
        self.page.close()

    def test_run_spill_and_optional_fire_from_ui(self):
        calculate = next(
            button for button in self.page.findChildren(QPushButton)
            if button.text() == "Calculate"
        )
        calculate.click()
        self.assertIn("Combined spill area:", self.page.results_label.text())
        self.assertNotIn("Burn duration:", self.page.results_label.text())
        self.page.pool_fire_tickbox.setChecked(True)
        self.page.pool_depth.setText("0.02")
        self.page.oi_tickbox.setChecked(True)
        self.page.operator_intervention_time.setText("10")
        self.page.average_evaporation_rate.setText("0.001")
        calculate.click()
        self.assertIn("Intervention-adjusted area:", self.page.results_label.text())
        self.assertIn("Burn duration:", self.page.results_label.text())
        self.assertIn("Flame height (Thomas):", self.page.results_label.text())

    def test_invalid_input_clears_stale_result(self):
        self.page.run_pool_calculation()
        self.page.wind_speed.setText("0")
        with patch("main.QMessageBox.warning") as warning:
            self.page.run_pool_calculation()
        warning.assert_called_once()
        self.assertEqual(
            self.page.results_label.text(), "Calculation not available for these inputs."
        )


if __name__ == "__main__":
    unittest.main()
