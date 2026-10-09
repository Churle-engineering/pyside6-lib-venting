"""Regression tests for shared LIB validation and its engine/UI entry points."""

from dataclasses import dataclass
from unittest.mock import Mock, patch
import unittest

import numpy as np

from dataclass_forms import read_form
from information import (
    CALC_METHOD_CELL_VOLUME_UL9540A,
    CALC_METHOD_MODULE_CAPACITY,
    CALC_METHOD_MODULE_VARIABLE_FLOWRATE,
    CALC_METHOD_MODULE_VOLUME_UL9540A,
    CHEMICAL_PROPERTIES, FlowrateProfile, LIBInputs, LIBSpec, MAX_CALC_DURATION_S,
)
from lib_validation import input_problems, release_problems
from main import ScenarioInputDialog
from scenario_model import Scenario, ScenarioStore
from venting_calculation import (
    build_module_release, cell_vent_profile, resolve_lfl, room_gas_balance,
    run_venting_assessment, system_propagation,
)


class InputValidationTests(unittest.TestCase):
    def test_calculation_duration_is_bounded_to_three_days(self):
        self.assertEqual(input_problems(LIBInputs(calc_duration=MAX_CALC_DURATION_S)), [])
        problems = input_problems(LIBInputs(calc_duration=MAX_CALC_DURATION_S + 1))
        self.assertIn(
            f"Calculation Duration must not exceed {MAX_CALC_DURATION_S:g}.", problems,
        )

    def test_default_and_zero_ventilation_inputs_are_valid(self):
        self.assertEqual(input_problems(LIBInputs()), [])
        self.assertEqual(input_problems(LIBInputs(
            ventilation_rate=0, emergency_vent_rate=0, vent_switch_conc=0,
        )), [])

    def test_invalid_scalar_inputs_are_reported(self):
        cases = {
            "room_height": (0, -1, np.nan, np.inf, "3", True),
            "room_area": (0, -1, np.nan, np.inf),
            "equip_space": (-1, 100, 110, np.nan, np.inf),
            "ventilation_rate": (-1, np.nan, np.inf),
            "emergency_vent_rate": (-1, np.nan, np.inf),
            "emergency_vent_delay": (-1, np.nan, np.inf, "3", True),
            "vent_switch_conc": (-1, np.nan, np.inf),
            "calc_duration": (0, -1, np.nan, np.inf),
            "cells_per_module": (0, -1, 1.5, np.nan, np.inf, True),
            "modules_per_unit": (0, -1, 1.5, np.nan, np.inf),
            "units": (0, -1, 1.5, np.nan, np.inf),
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    inputs = LIBInputs(**{name: value})
                    errors = input_problems(inputs)
                    self.assertTrue(errors)
                    label = LIBInputs.__dataclass_fields__[name].metadata["label"]
                    self.assertTrue(any(label in error for error in errors))

    def test_derived_room_volume_must_be_finite_and_positive(self):
        for value in (1e308, 1e-300):
            with self.subTest(value=value):
                errors = input_problems(LIBInputs(room_area=value, room_height=value))
                self.assertTrue(any("Free Room Volume" in error for error in errors))

    def test_multiple_errors_are_collected(self):
        errors = input_problems(LIBInputs(room_height=0, ventilation_rate=-1, units=0))
        self.assertEqual(len(errors), 3)

    def test_scenario_dialog_uses_same_input_rules(self):
        inputs = LIBInputs(lib_spec="battery", room_height=0, ventilation_rate=-1)
        self.assertEqual(ScenarioInputDialog._validation_problems(None, inputs),
                         input_problems(inputs))

    def test_room_balance_rejects_invalid_inputs_before_division(self):
        for occupancy in (100, 110):
            with self.subTest(occupancy=occupancy):
                with self.assertRaisesRegex(ValueError, "Equipment Space"):
                    room_gas_balance(LIBInputs(equip_space=occupancy),
                                     np.array([0., 1.]), np.array([0., 0.1]), {"co": 1})

    def test_propagation_rejects_fractional_system_counts(self):
        inputs = LIBInputs(units=1.5)
        spec = LIBSpec()
        release = build_module_release(Scenario(1, inputs, lib_spec=spec))
        with self.assertRaisesRegex(ValueError, "Units must be a whole number"):
            system_propagation(inputs, spec, release)

    def test_propagation_rejects_duration_above_limit_before_allocation(self):
        inputs = LIBInputs(calc_duration=MAX_CALC_DURATION_S + 1)
        spec = LIBSpec()
        release = build_module_release(Scenario(1, inputs, lib_spec=spec))
        with self.assertRaisesRegex(ValueError, "Calculation Duration"):
            system_propagation(inputs, spec, release)


class ReleaseValidationTests(unittest.TestCase):
    def test_method_specific_fields(self):
        cases = {
            CALC_METHOD_CELL_VOLUME_UL9540A: {
                "cell_volume": (0, -1, np.nan, np.inf),
                "cell_duration": (-1, np.nan, np.inf),
                "cell_prop_delay": (-1, np.nan, np.inf),
                "cell_prop_number": (0, -1, 1.5, np.nan, np.inf),
            },
            CALC_METHOD_MODULE_VOLUME_UL9540A: {
                "module_volume": (0, -1, np.nan, np.inf),
                "module_duration": (0, -1, np.nan, np.inf),
            },
            CALC_METHOD_MODULE_CAPACITY: {
                "module_capacity": (0, -1, np.nan, np.inf),
                "module_duration": (0, -1, np.nan, np.inf),
            },
        }
        for method, fields in cases.items():
            for name, values in fields.items():
                for value in values:
                    with self.subTest(method=method, name=name, value=value):
                        scenario = Scenario(1, LIBInputs(calc_method=method),
                                            lib_spec=LIBSpec(**{name: value}))
                        with self.assertRaises(ValueError):
                            build_module_release(scenario)

    def test_module_propagation_fields_are_validated_for_all_methods(self):
        for method in (CALC_METHOD_CELL_VOLUME_UL9540A, CALC_METHOD_MODULE_CAPACITY,
                       CALC_METHOD_MODULE_VOLUME_UL9540A,
                       CALC_METHOD_MODULE_VARIABLE_FLOWRATE):
            for name, value in (("mod_prop_delay", -1), ("mod_prop_delay", np.nan),
                                ("mod_prop_number", 0), ("mod_prop_number", 1.5)):
                with self.subTest(method=method, name=name, value=value):
                    self.assertTrue(release_problems(
                        LIBInputs(calc_method=method), LIBSpec(**{name: value})))

    def test_unused_fields_do_not_block_other_methods(self):
        inputs = LIBInputs(calc_method=CALC_METHOD_MODULE_VOLUME_UL9540A)
        spec = LIBSpec(cell_volume=-1, cell_duration=-1, cell_prop_number=0,
                       cell_prop_delay=-1, module_capacity=-1)
        self.assertEqual(release_problems(inputs, spec), [])
        build_module_release(Scenario(1, inputs, lib_spec=spec))

    def test_zero_duration_and_propagation_delay_remain_valid(self):
        inputs = LIBInputs()
        spec = LIBSpec(cell_duration=0, cell_prop_delay=0, mod_prop_delay=0)
        self.assertEqual(release_problems(inputs, spec), [])
        build_module_release(Scenario(1, inputs, lib_spec=spec))

    def test_direct_cell_release_rejects_invalid_values(self):
        for volume, duration in ((np.nan, 0), (1, -1), (1, np.inf)):
            with self.subTest(volume=volume, duration=duration):
                with self.assertRaises(ValueError):
                    cell_vent_profile(volume, duration)

    def test_invalid_datasets_are_rejected(self):
        cases = (
            ([0, 1], [1, -1]),
            ([0, 0, 1], [1, 1, 1]),
            ([0, np.inf], [1, 1]),
            ([0, 1], [1, np.nan]),
            ([[0, 1]], [[1, 1]]),
        )
        for times, flows in cases:
            with self.subTest(times=times, flows=flows):
                scenario = Scenario(
                    1, LIBInputs(calc_method=CALC_METHOD_MODULE_VARIABLE_FLOWRATE),
                    lib_spec=LIBSpec(),
                    flowrate_profile=FlowrateProfile(name="test", time_s=times,
                                                    flowrate_lps=flows),
                )
                with self.assertRaises(ValueError):
                    build_module_release(scenario)

    def test_unsorted_offset_dataset_remains_supported(self):
        scenario = Scenario(
            1, LIBInputs(calc_method=CALC_METHOD_MODULE_VARIABLE_FLOWRATE),
            lib_spec=LIBSpec(),
            flowrate_profile=FlowrateProfile(name="offset", time_s=[12, 10, 11],
                                            flowrate_lps=[0, 0, 2]),
        )
        release = build_module_release(scenario)
        self.assertAlmostEqual(release.volume_l, 2)


class LflValidationTests(unittest.TestCase):
    def test_entered_lfl_must_be_finite_positive_percentage(self):
        for value in (None, 0, -1, np.nan, np.inf, 101, True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "LFL"):
                    resolve_lfl(LIBInputs(), LIBSpec(lfl=value), {"co": 1})

    def test_le_chatelier_does_not_validate_unused_entered_lfl(self):
        lfl, _ = resolve_lfl(LIBInputs(use_le_chatelier_lfl=True),
                             LIBSpec(lfl=np.nan), {"co": 1})
        self.assertEqual(lfl, CHEMICAL_PROPERTIES["co"]["lfl"])

    def test_temperature_must_be_finite_and_above_absolute_zero_when_used(self):
        for value in (-273.15, -300, np.nan, np.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Venting Temperature"):
                    resolve_lfl(LIBInputs(use_temp_dependent_lfl=True),
                                LIBSpec(lfl=5, venting_temperature=value), {"co": 1})

    def test_zero_adjusted_lfl_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "Assessment LFL"):
            resolve_lfl(LIBInputs(use_temp_dependent_lfl=True),
                        LIBSpec(lfl=0.01, venting_temperature=1000), {"co": 1})

    def test_nonflammable_composition_can_have_no_computed_lfl(self):
        lfl, _ = resolve_lfl(LIBInputs(use_le_chatelier_lfl=True),
                             LIBSpec(), {"co2": 1})
        self.assertIsNone(lfl)


class RunValidationTests(unittest.TestCase):
    def test_invalid_runs_clear_old_results_report_all_errors_and_continue(self):
        store = ScenarioStore()
        bad = store.add(LIBInputs(room_height=0, ventilation_rate=-1))
        bad.lib_spec = LIBSpec(lfl=5)
        bad.result = Mock()
        bad.summary = Mock()
        good = store.add(LIBInputs(calc_duration=2, ventilation_rate=0))
        good.lib_spec = LIBSpec(lfl=5)
        with patch("venting_calculation.QMessageBox.warning") as warning:
            results = run_venting_assessment(None, store, CHEMICAL_PROPERTIES)
        self.assertEqual(set(results), {good.node_id})
        self.assertIsNone(bad.result)
        self.assertIsNone(bad.summary)
        self.assertTrue(np.all(np.isfinite(good.result.total_gas_vv)))
        warning.assert_called_once()
        message = warning.call_args.args[2]
        self.assertIn("Room Height", message)
        self.assertIn("Ventilation Rate", message)

    def test_unselected_scenario_keeps_its_result(self):
        store = ScenarioStore()
        scenario = store.add(LIBInputs(room_height=0))
        old_result = scenario.result = Mock()
        with patch("venting_calculation.QMessageBox.warning") as warning:
            self.assertEqual(run_venting_assessment(None, store, CHEMICAL_PROPERTIES,
                                                    node_ids=[]), {})
        self.assertIs(scenario.result, old_result)
        warning.assert_not_called()


class FormIntegerValidationTests(unittest.TestCase):
    def test_integer_fields_are_not_silently_truncated(self):
        @dataclass
        class Count:
            count: int = 1

        widget = Mock()
        for value in ("1.5", "nan", "inf"):
            with self.subTest(value=value):
                widget.text.return_value = value
                with self.assertRaises(ValueError):
                    read_form(Count, {"count": widget})
        widget.text.return_value = "2.0"
        self.assertEqual(read_form(Count, {"count": widget}).count, 2)


if __name__ == "__main__":
    unittest.main()
