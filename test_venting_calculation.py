r"""Focused verification checks for venting_calculation.py.

Run with:
    .venv\Scripts\python.exe test_venting_calculation.py -v

Expected failures document calculation defects found during review. They should be
converted to normal tests when the corresponding production behavior is corrected.
"""

from types import SimpleNamespace
import unittest

import numpy as np

from venting_calculation import (
    CellByCellModuleRelease,
    FlatModuleRelease,
    MeasuredModuleRelease,
    _cell_curve_params,
    _cohort_schedule,
    build_module_release,
    cell_vent_profile,
    resolve_composition,
    resolve_lfl,
    room_gas_balance,
    system_propagation,
    temperature_adjusted_lfl,
)
from information import (
    BATTERY_CHEMISTRY_DATA,
    CHEMICAL_PROPERTIES,
    CALC_METHOD_CELL_VOLUME_UL9540A,
    CALC_METHOD_MODULE_CAPACITY,
    CALC_METHOD_MODULE_VARIABLE_FLOWRATE,
    CALC_METHOD_MODULE_VOLUME_UL9540A,
    FlowrateProfile,
    LIBInputs,
    LIBSpec,
)
from main import BatteryDefinitionDialog


def _scenario(inputs, spec, flowrate_profile=None):
    """Minimal stand-in for a Scenario, as consumed by the engine's resolvers."""
    return SimpleNamespace(inputs=inputs, lib_spec=spec, gas_composition=None,
                           flowrate_profile=flowrate_profile)


def _run_propagation(inputs, spec, flowrate_profile=None):
    """build_module_release + system_propagation, the way run_venting_assessment does."""
    release = build_module_release(_scenario(inputs, spec, flowrate_profile))
    return system_propagation(inputs, spec, release)


class ReleaseModelDispatchTests(unittest.TestCase):
    """inputs.calc_method is the single switch that selects the release model."""

    def test_each_method_maps_to_its_release_model(self):
        cases = {
            CALC_METHOD_CELL_VOLUME_UL9540A: CellByCellModuleRelease,
            CALC_METHOD_MODULE_VOLUME_UL9540A: FlatModuleRelease,
            CALC_METHOD_MODULE_CAPACITY: FlatModuleRelease,
        }
        for method, expected_model in cases.items():
            with self.subTest(method=method):
                release = build_module_release(
                    _scenario(LIBInputs(calc_method=method), LIBSpec())
                )
                self.assertIsInstance(release, expected_model)

    def test_variable_flowrate_replays_the_imported_dataset(self):
        profile = FlowrateProfile(name="test", time_s=[0.0, 1.0, 2.0],
                                  flowrate_lps=[0.0, 2.0, 0.0])
        release = build_module_release(
            _scenario(LIBInputs(calc_method=CALC_METHOD_MODULE_VARIABLE_FLOWRATE),
                      LIBSpec(), flowrate_profile=profile)
        )
        self.assertIsInstance(release, MeasuredModuleRelease)
        self.assertEqual(release.duration, 2.0)
        # trapezoidal volume of the triangle profile: 2 l/s peak over 2 s -> 2 l
        self.assertAlmostEqual(release.volume_l, 2.0)

    def test_variable_flowrate_without_a_dataset_raises(self):
        with self.assertRaises(ValueError):
            build_module_release(
                _scenario(LIBInputs(calc_method=CALC_METHOD_MODULE_VARIABLE_FLOWRATE),
                          LIBSpec(), flowrate_profile=None)
            )

    def test_unknown_method_raises(self):
        with self.assertRaises(ValueError):
            build_module_release(_scenario(LIBInputs(calc_method="Nonsense"), LIBSpec()))

    def test_module_capacity_uses_the_chemistry_specific_capacity(self):
        spec = LIBSpec(lib_type="nmc", cell_format="prismatic", module_capacity=5.0)
        release = build_module_release(
            _scenario(LIBInputs(calc_method=CALC_METHOD_MODULE_CAPACITY), spec)
        )
        expected_l = (BATTERY_CHEMISTRY_DATA["NMC"]["specific_capacity"]["prismatic"]
                      * spec.module_capacity)
        self.assertAlmostEqual(release.volume_l, expected_l)


class CellPropagationTests(unittest.TestCase):
    def test_cohort_schedules_start_at_zero_and_cap_final_wave(self):
        self.assertEqual(
            _cohort_schedule(total_count=8, batch_size=3, interval=10),
            [(0.0, 3), (10.0, 3), (20.0, 2)],
        )

    def test_cohort_schedule_can_start_with_a_single_item(self):
        self.assertEqual(
            _cohort_schedule(total_count=8, batch_size=3, interval=10, first_batch=1),
            [(0.0, 1), (10.0, 3), (20.0, 3), (30.0, 1)],
        )

    def test_cell_and_module_cohorts_combine_at_expected_times(self):
        inputs = LIBInputs(
            cells_per_module=5,
            modules_per_unit=3,
            units=1,
            calc_duration=60,
            time_step=1,
        )
        spec = LIBSpec(
            cell_volume=100.0,
            cell_prop_number=2,
            cell_prop_delay=5.0,
            mod_prop_number=2,
            mod_prop_delay=20.0,
        )

        result = _run_propagation(inputs, spec)

        self.assertEqual(result.release.cell_cohorts, [(0.0, 1), (5.0, 2), (10.0, 2)])
        self.assertEqual(result.module_cohorts, [(0.0, 1), (20.0, 2)])
        self.assertEqual(result.total_flowrate[0], 0.0)
        self.assertEqual(result.active_cell_count[0], 1.0)
        self.assertEqual(result.active_module_count[0], 1.0)

    def test_completed_propagation_releases_entered_cell_volume(self):
        inputs = LIBInputs(
            cells_per_module=1,
            modules_per_unit=1,
            units=1,
            calc_duration=120,
            time_step=0.25,
        )
        spec = LIBSpec(
            cell_volume=100.0,
            cell_duration=0.0,
            cell_prop_number=1,
            cell_prop_delay=1.0,
            mod_prop_number=1,
            mod_prop_delay=1.0,
        )

        result = _run_propagation(inputs, spec)
        released_m3 = float(result.total_flowrate.sum() * inputs.effective_time_step())

        # the decay tail is cut off at 0.01% of the peak flow
        self.assertAlmostEqual(released_m3 / (spec.cell_volume / 1000.0), 1.0, places=3)

    def test_cell_duration_gives_a_flat_release_of_the_entered_volume(self):
        inputs = LIBInputs(
            cells_per_module=1,
            modules_per_unit=1,
            units=1,
            calc_duration=60,
            time_step=1,
        )
        spec = LIBSpec(cell_volume=100.0, cell_duration=20.0)

        result = _run_propagation(inputs, spec)

        self.assertEqual(result.release.cell_release.duration, 20.0)
        expected_rate = (spec.cell_volume / 1000.0) / spec.cell_duration
        np.testing.assert_allclose(result.total_flowrate[1:21], expected_rate)
        np.testing.assert_allclose(result.total_flowrate[21:], 0.0, atol=1e-15)
        self.assertAlmostEqual(
            float(result.total_flowrate.sum() * inputs.effective_time_step()),
            spec.cell_volume / 1000.0,
        )

    def test_cell_profile_samples_the_analytic_peak_flow(self):
        peak_flow, peak_time = _cell_curve_params(0.5)[:2]

        time, flow = cell_vent_profile(0.5).profile()

        self.assertAlmostEqual(float(np.interp(peak_time, time, flow)), peak_flow, places=12)

    def test_cell_duration_input_controls_release_duration(self):
        inputs = LIBInputs(
            cells_per_module=1,
            modules_per_unit=1,
            units=1,
            calc_duration=4000,
            time_step=1,
        )
        short_spec = LIBSpec(cell_volume=0.5, cell_duration=30.0)
        long_spec = LIBSpec(cell_volume=0.5, cell_duration=3600.0)

        short_result = _run_propagation(inputs, short_spec)
        long_result = _run_propagation(inputs, long_spec)

        self.assertEqual(short_result.release.cell_release.duration, 30.0)
        self.assertEqual(long_result.release.cell_release.duration, 3600.0)

    def test_zero_cell_duration_falls_back_to_the_volume_derived_curve(self):
        inputs = LIBInputs(
            cells_per_module=1,
            modules_per_unit=1,
            units=1,
            calc_duration=100,
            time_step=1,
        )
        spec = LIBSpec(cell_volume=0.5, cell_duration=0.0)

        result = _run_propagation(inputs, spec)

        self.assertAlmostEqual(result.release.cell_release.duration,
                               _cell_curve_params(spec.cell_volume)[-1])


class GasAccumulationTests(unittest.TestCase):
    def test_no_ventilation_accumulates_all_released_gas(self):
        inputs = LIBInputs(
            room_height=2.0,
            room_area=5.0,
            equip_space=0.0,
            time_step=1,
            ventilation_rate=0.0,
            emergency_vent_rate=0.0,
            vent_switch_conc=0.0,
        )
        time = np.arange(0.0, 6.0, 1.0)
        release_flow = np.array([0.0, 0.10, 0.20, 0.0, 0.05, 0.0])

        _, volume_m3, conc_vv = room_gas_balance(
            inputs,
            time,
            release_flow,
            {"co": 0.25, "co2": 0.75},
        )

        expected_total = np.cumsum(release_flow) * inputs.effective_time_step()
        np.testing.assert_allclose(volume_m3.sum(axis=0), expected_total)
        np.testing.assert_allclose(
            conc_vv.sum(axis=0),
            expected_total / inputs.room_volume() * 100.0,
        )

    def test_high_extraction_step_does_not_remove_more_than_available(self):
        inputs = LIBInputs(
            room_height=1.0,
            room_area=1.0,
            equip_space=0.0,
            time_step=2,
            ventilation_rate=1000.0,
            emergency_vent_rate=0.0,
            vent_switch_conc=0.0,
        )
        time = np.array([0.0, 2.0, 4.0, 6.0])
        release_flow = np.array([0.0, 0.1, 0.1, 0.1])

        _, volume_m3, _ = room_gas_balance(
            inputs,
            time,
            release_flow,
            {"co": 1.0},
        )

        self.assertGreater(volume_m3[0, 2], 0.0)


class CompositionTests(unittest.TestCase):
    def test_literature_compositions_sum_to_one_hundred_percent(self):
        for chemistry, data in BATTERY_CHEMISTRY_DATA.items():
            with self.subTest(chemistry=chemistry):
                self.assertAlmostEqual(sum(data["composition"].values()), 100.0, places=6)

    def test_literature_composition_is_normalized_and_uses_known_species(self):
        scenario = SimpleNamespace(
            inputs=LIBInputs(composition_method="Literature Data"),
            lib_spec=LIBSpec(lib_type="nmc"),
            gas_composition=None,
        )

        fractions = resolve_composition(scenario)

        self.assertAlmostEqual(sum(fractions.values()), 1.0)
        self.assertTrue(set(fractions).issubset(CHEMICAL_PROPERTIES))
        expected_species = {
            species
            for species, percent in BATTERY_CHEMISTRY_DATA["NMC"]["composition"].items()
            if percent > 0 and species in CHEMICAL_PROPERTIES
        }
        self.assertEqual(set(fractions), expected_species)

    def test_battery_definition_does_not_expose_a_separate_co2_field(self):
        self.assertNotIn("co2_percent", BatteryDefinitionDialog.TAB_FIELDS[0][1])


class LflTests(unittest.TestCase):
    def test_missing_user_lfl_raises(self):
        with self.assertRaises(ValueError):
            resolve_lfl(LIBInputs(use_le_chatelier_lfl=False), LIBSpec(lfl=0.0), {"h2": 1.0})

    def test_le_chatelier_does_not_need_a_user_lfl(self):
        lfl, label = resolve_lfl(LIBInputs(use_le_chatelier_lfl=True), LIBSpec(lfl=0.0),
                                 {"h2": 1.0})
        self.assertEqual(label, "Le Chatelier LFL")
        self.assertAlmostEqual(lfl, CHEMICAL_PROPERTIES["h2"]["lfl"])

    @unittest.expectedFailure
    def test_temperature_adjustment_changes_lfl(self):
        """Known defect: temperature_adjusted_lfl currently multiplies by 1.0."""
        self.assertNotEqual(temperature_adjusted_lfl(5.0, 200.0), 5.0)


class EmergencyVentilationTests(unittest.TestCase):
    def test_co_trigger_switches_to_the_higher_per_m2_rate(self):
        common = dict(room_height=3.0, room_area=10.0, equip_space=0.0, time_step=1)
        time = np.arange(0.0, 600.0, 1.0)
        release = np.full(len(time), 0.05)
        release[0] = 0.0
        fractions = {"co": 0.5, "h2": 0.5}

        no_switch = LIBInputs(ventilation_rate=1.0, vent_switch_conc=0.0,
                              emergency_vent_rate=50.0, **common)
        switched = LIBInputs(ventilation_rate=1.0, vent_switch_conc=0.001,
                             emergency_vent_rate=50.0, **common)

        _, vol_no_switch, _ = room_gas_balance(no_switch, time, release, fractions)
        _, vol_switched, _ = room_gas_balance(switched, time, release, fractions)

        # the CO trigger fires almost immediately, so the emergency (per-m2) rate
        # must extract far more gas than the untriggered run
        self.assertLess(vol_switched.sum(axis=0)[-1], 0.5 * vol_no_switch.sum(axis=0)[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
