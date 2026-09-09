r"""Hand-calculation verification cases for venting_calculation.py.

Run with:
    .venv\Scripts\python.exe test_hand_verification.py -v

Unlike test_venting_calculation.py (which pins code behaviour: dispatch, error paths,
edge cases), every assertion here is checked against a value you can reproduce on
paper. Each test docstring shows the full hand calculation.

To verify a calculation method you must specify, per case:
    LIBInputs   - room geometry (room_height, room_area, equip_space), ventilation
                  (ventilation_rate, emergency_vent_rate, vent_switch_conc), the grid
                  (calc_duration, time_step), the system size (cells_per_module,
                  modules_per_unit, units), calc_method, and the composition source.
    LIBSpec     - the release parameters the chosen method reads (cell_volume /
                  cell_duration, module_volume / module_duration, module_capacity +
                  cell_format + lib_type), the staggering (cell/mod_prop_number,
                  cell/mod_prop_delay), and lfl (or enable use_le_chatelier_lfl).
    Composition - a User Defined composition with round fractions (50/50 H2-CO here)
                  so every split is trivial on paper. Literature compositions have
                  many species and are better verified by the normalisation tests in
                  test_venting_calculation.py.

Keep every hand case deliberately simple: 1 module (or a tiny staggered set), flat
releases, ventilation off (or a single constant rate), equip_space=0, round volumes.
The physics is then linear algebra you can do by hand; the empirical cell curve is
verified through its closed-form invariants instead of point values.
"""

from types import SimpleNamespace
import copy
import unittest

import numpy as np

from venting_calculation import (
    _cell_curve_params,
    _gas_results,
    build_module_release,
    resolve_composition,
    resolve_lfl,
    room_gas_balance,
    split_species,
    summarize_result,
    system_propagation,
)
from scenario_model import ScenarioResult
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


# 50% H2 / 50% CO: both flammable, only CO toxic, so every split is trivial on paper.
# H2:  lfl 4.0 v/v%, density 0.084 g/L        CO: lfl 12.5 v/v%, density 0.967 g/L
HALF_H2_HALF_CO = SimpleNamespace(percentages={"h2": 50.0, "co": 50.0})


def _base_inputs(**overrides):
    """100 m3 free room (2 m x 50 m2, no equipment), no ventilation, 1 module, dt=1 s."""
    values = dict(
        room_height=2.0, room_area=50.0, equip_space=0.0,
        ventilation_rate=0.0, emergency_vent_rate=0.0, vent_switch_conc=0.0,
        calc_duration=200, time_step=1,
        cells_per_module=1, modules_per_unit=1, units=1,
        composition_method="User Defined",
    )
    values.update(overrides)
    return LIBInputs(**values)


def _scenario(inputs, spec, gas_composition=HALF_H2_HALF_CO, flowrate_profile=None):
    return SimpleNamespace(name="hand-calc", inputs=inputs, lib_spec=spec,
                           gas_composition=gas_composition, flowrate_profile=flowrate_profile)


def _run_pipeline(scenario):
    """Mirror run_venting_assessment for ONE scenario, without any Qt widgets.

    Returns (ScenarioResult, ResultSummary, PropagationResult) so tests can check the
    raw flowrate signal, the room balance and the derived summary figures.
    """
    inputs = scenario.inputs
    fractions = resolve_composition(scenario)
    release = build_module_release(scenario)
    prop = system_propagation(inputs, scenario.lib_spec, release)
    lfl, lfl_label = resolve_lfl(inputs, scenario.lib_spec, fractions)
    species, volume_m3, conc_vv = room_gas_balance(
        inputs, prop.time, prop.total_flowrate, fractions)
    flammable, toxic = split_species(species)
    total_gas_m3 = volume_m3.sum(axis=0)

    result = ScenarioResult(
        scenario_name=scenario.name,
        calc_method=inputs.calc_method,
        inputs=copy.deepcopy(inputs),
        time=prop.time,
        flowrate=prop.total_flowrate,
        total_gas_m3=total_gas_m3,
        total_gas_vv=(total_gas_m3 / inputs.room_volume()) * 100.0,
        flammable=_gas_results(species, flammable, volume_m3, conc_vv),
        toxic=_gas_results(species, toxic, volume_m3, conc_vv),
        active_cells=prop.active_cell_count,
        active_modules=prop.active_module_count,
        lfl_percent=lfl,
        lfl_label=lfl_label,
        lib_spec=copy.deepcopy(scenario.lib_spec),
    )
    return result, summarize_result(result, CHEMICAL_PROPERTIES), prop


class ModuleVolumeHandCalcTests(unittest.TestCase):
    """Module Volume UL9540A: 1 module, 1000 L over 100 s, sealed 100 m3 room.

    Hand calculation:
        flowrate       = 1000 L / 100 s = 10 L/s = 0.01 m3/s   (t = 1..100 s)
        released total = 1.0 m3
        final conc     = 1.0 m3 / 100 m3 * 100 = 1.0 v/v%   (both species flammable)
        H2 = CO conc   = 0.5 v/v% each = 5000 ppm each
        peak mg/L      = 0.5/100*0.084*1000 + 0.5/100*0.967*1000 = 0.42 + 4.835 = 5.255
        LFL 0.5 v/v%   -> crossed when released volume > 0.5 m3, i.e. first step AFTER
                          t = 50 s (t=50 is exactly 0.5 m3, the comparison is strict) -> 51 s
    """

    def _run(self):
        inputs = _base_inputs(calc_method=CALC_METHOD_MODULE_VOLUME_UL9540A)
        spec = LIBSpec(module_volume=1000.0, module_duration=100.0, lfl=0.5)
        return _run_pipeline(_scenario(inputs, spec))

    def test_flowrate_is_the_flat_hand_calculated_rate(self):
        result, _, prop = self._run()
        self.assertEqual(prop.total_flowrate[0], 0.0)
        np.testing.assert_allclose(prop.total_flowrate[1:101], 0.01)
        np.testing.assert_allclose(prop.total_flowrate[101:], 0.0, atol=1e-15)
        self.assertAlmostEqual(float(prop.total_flowrate.sum() * 1.0), 1.0)

    def test_sealed_room_concentrations_match_hand_values(self):
        result, _, _ = self._run()
        self.assertAlmostEqual(float(result.total_gas_vv[-1]), 1.0)
        co_row = result.toxic.labels.index("co")
        self.assertAlmostEqual(float(result.toxic.conc_vv[co_row, -1]), 0.5)

    def test_summary_peaks_and_lfl_crossing_match_hand_values(self):
        _, summary, _ = self._run()
        self.assertAlmostEqual(summary.peak_flammable_vv, 1.0)
        self.assertAlmostEqual(summary.peak_flammable_ppm, 10000.0)
        self.assertAlmostEqual(summary.peak_flammable_mgl, 5.255)
        self.assertEqual(summary.lfl_crossing_time, 51.0)
        co = next(s for s in summary.toxic_species if s.species == "co")
        self.assertAlmostEqual(co.peak_vv, 0.5)
        self.assertAlmostEqual(co.peak_ppm, 5000.0)


class ModuleStaggerHandCalcTests(unittest.TestCase):
    """3 modules, 1 more every 50 s, each 1000 L over 100 s, sealed room.

    Hand calculation (module cohorts start at t = 0, 50, 100):
        t in ( 0,  50]: 1 module active  -> 0.01 m3/s
        t in (50, 100]: 2 modules active -> 0.02 m3/s
        t in (100,150]: modules 2+3      -> 0.02 m3/s
        t in (150,200]: module 3 only    -> 0.01 m3/s
        total released = 3 x 1.0 m3 -> final conc = 3/100*100 = 3.0 v/v%
    """

    def test_overlapping_modules_sum_and_conserve_volume(self):
        inputs = _base_inputs(calc_method=CALC_METHOD_MODULE_VOLUME_UL9540A,
                              modules_per_unit=3, calc_duration=300)
        spec = LIBSpec(module_volume=1000.0, module_duration=100.0, lfl=0.5,
                       mod_prop_number=1, mod_prop_delay=50.0)
        result, _, prop = _run_pipeline(_scenario(inputs, spec))

        self.assertEqual(prop.module_cohorts, [(0.0, 1), (50.0, 1), (100.0, 1)])
        self.assertAlmostEqual(float(prop.total_flowrate[25]), 0.01)
        self.assertAlmostEqual(float(prop.total_flowrate[75]), 0.02)
        self.assertAlmostEqual(float(prop.total_flowrate[175]), 0.01)
        self.assertAlmostEqual(float(result.total_gas_vv[-1]), 3.0)


class CellVolumeHandCalcTests(unittest.TestCase):
    """Cell Volume UL9540A - flat mode (measured cell_duration) is hand-calculable
    step by step; curve mode (cell_duration=0) is verified via closed-form invariants."""

    def test_flat_cell_staggering_matches_hand_steps(self):
        """3 cells of 30 L over 10 s each; 1 starts at t=0, 2 more at t=5.

        Hand calculation (per cell rate = 0.03 m3 / 10 s = 0.003 m3/s):
            t in ( 0,  5]: 1 cell  -> 0.003 m3/s
            t in ( 5, 10]: 3 cells -> 0.009 m3/s
            t in (10, 15]: 2 cells -> 0.006 m3/s
            total = 3 x 0.03 = 0.09 m3
        """
        inputs = _base_inputs(calc_method=CALC_METHOD_CELL_VOLUME_UL9540A,
                              cells_per_module=3, calc_duration=60)
        spec = LIBSpec(cell_volume=30.0, cell_duration=10.0,
                       cell_prop_number=2, cell_prop_delay=5.0, lfl=0.5)
        _, _, prop = _run_pipeline(_scenario(inputs, spec))

        self.assertEqual(prop.release.cell_cohorts, [(0.0, 1), (5.0, 2)])
        np.testing.assert_allclose(prop.total_flowrate[1:6], 0.003)
        np.testing.assert_allclose(prop.total_flowrate[6:11], 0.009)
        np.testing.assert_allclose(prop.total_flowrate[11:16], 0.006)
        self.assertAlmostEqual(float(prop.total_flowrate.sum() * 1.0), 0.09)

    def test_curve_mode_satisfies_its_closed_form_invariants(self):
        """cell_volume = 1000 L (area A = 1 m3), constants m1=1.6, tau=4.

        Hand calculation (from _cell_curve_params' area constraint):
            h  = sqrt(m1^2 tau^2 + 2 m1 A) - m1 tau
               = sqrt(2.56*16 + 3.2) - 6.4 = sqrt(44.16) - 6.4 = 0.245299...
            check: h^2/(2 m1) + h tau must equal A = 1.0 exactly
            released volume = A - h*tau*eps (decay tail cut at eps = 0.01% of peak)
                            = 1.0 - 0.245299*4*1e-4 = 0.99990188 m3
        """
        h, tp, m1, tau, te = _cell_curve_params(1000.0)
        self.assertAlmostEqual(h, np.sqrt(44.16) - 6.4, places=12)
        self.assertAlmostEqual(h**2 / (2 * m1) + h * tau, 1.0, places=12)

        inputs = _base_inputs(calc_method=CALC_METHOD_CELL_VOLUME_UL9540A,
                              calc_duration=int(te) + 10)
        spec = LIBSpec(cell_volume=1000.0, cell_duration=0.0, lfl=0.5)
        _, _, prop = _run_pipeline(_scenario(inputs, spec))
        self.assertAlmostEqual(float(prop.total_flowrate.sum() * 1.0),
                               1.0 - h * tau * 1e-4, places=9)


class ModuleCapacityHandCalcTests(unittest.TestCase):
    def test_release_volume_is_specific_capacity_times_module_kwh(self):
        """NMC prismatic: 585 L/kWh (BATTERY_CHEMISTRY_DATA / Peter's paper Fig. 5).

        Hand calculation: 585 L/kWh x 10 kWh = 5850 L over 100 s = 0.0585 m3/s.
        NOTE: 585 is pinned as a literal on purpose - if the chemistry table changes,
        this test fails and the new value must be re-verified against the source paper.
        """
        self.assertEqual(BATTERY_CHEMISTRY_DATA["NMC"]["specific_capacity"]["prismatic"], 585)

        inputs = _base_inputs(calc_method=CALC_METHOD_MODULE_CAPACITY)
        spec = LIBSpec(lib_type="nmc", cell_format="prismatic",
                       module_capacity=10.0, module_duration=100.0, lfl=0.5)
        _, _, prop = _run_pipeline(_scenario(inputs, spec))

        self.assertAlmostEqual(prop.release.volume_l, 5850.0)
        np.testing.assert_allclose(prop.total_flowrate[1:101], 5.85 / 100.0)


class MeasuredFlowrateHandCalcTests(unittest.TestCase):
    def test_trapezoid_dataset_volume_and_plateau_rate(self):
        """Trapezoid: 0 -> 5 -> 5 -> 0 L/s at t = 0, 10, 20, 30 s.

        Hand calculation (trapezoidal areas):
            ramp up   0.5*10*5 = 25 L
            plateau       10*5 = 50 L
            ramp down 0.5*10*5 = 25 L      total = 100 L = 0.1 m3
            plateau flowrate = 5 L/s = 0.005 m3/s
        """
        profile = FlowrateProfile(name="trapezoid", time_s=[0.0, 10.0, 20.0, 30.0],
                                  flowrate_lps=[0.0, 5.0, 5.0, 0.0])
        inputs = _base_inputs(calc_method=CALC_METHOD_MODULE_VARIABLE_FLOWRATE,
                              calc_duration=60)
        spec = LIBSpec(lfl=0.5)
        result, _, prop = _run_pipeline(_scenario(inputs, spec, flowrate_profile=profile))

        self.assertAlmostEqual(prop.release.volume_l, 100.0)
        np.testing.assert_allclose(prop.total_flowrate[11:21], 0.005)
        self.assertAlmostEqual(float(result.total_gas_vv[-1]), 0.1)  # 0.1 m3 / 100 m3


class VentilationHandCalcTests(unittest.TestCase):
    """room_gas_balance solves dV/dt = q - (Q/V_room) V exactly per step, so its
    analytic steady state and decay are exact hand checks (not approximations)."""

    def test_constant_inflow_reaches_the_analytic_steady_state(self):
        """q = 0.01 m3/s in, Q = 2 L/s/m2 * 50 m2 = 0.1 m3/s out, V_room = 100 m3.

        Hand calculation: steady state V = q*V_room/Q = 0.01*100/0.1 = 10 m3,
        i.e. 10 v/v%. Time constant V_room/Q = 1000 s, so by t = 8000 s (8 time
        constants) the pool is within e^-8 = 0.03% of 10 m3.
        """
        inputs = _base_inputs(ventilation_rate=2.0)
        time = np.arange(0.0, 8001.0, 1.0)
        release = np.full(len(time), 0.01)

        _, volume_m3, conc_vv = room_gas_balance(inputs, time, release, {"co": 1.0})

        self.assertAlmostEqual(float(volume_m3[0, -1]), 10.0, delta=0.01)
        self.assertAlmostEqual(float(conc_vv[0, -1]), 10.0, delta=0.01)

    def test_decay_after_release_stops_is_exactly_exponential(self):
        """Same Q/V_room = 0.001 1/s. After inflow stops, V(t0+n) = V(t0)*e^(-0.001 n),
        so exactly 1000 s later the pool must be V(t0)/e."""
        inputs = _base_inputs(ventilation_rate=2.0, calc_duration=2000)
        time = np.arange(0.0, 2001.0, 1.0)
        release = np.zeros(len(time))
        release[1:101] = 0.01

        _, volume_m3, _ = room_gas_balance(inputs, time, release, {"co": 1.0})

        self.assertAlmostEqual(float(volume_m3[0, 1100] / volume_m3[0, 100]),
                               float(np.exp(-1.0)), places=10)

    def test_emergency_vent_triggers_at_the_hand_calculated_time(self):
        """No base ventilation, q = 0.01 m3/s, 50% CO, trigger at 8% of CO's LFL.

        Hand calculation:
            trigger conc = 12.5 * 8/100 = 1.0 v/v% CO
            CO conc(t)   = 0.5 * (0.01 t / 100) * 100 = 0.005 t  v/v%
            -> reaches 1.0 v/v% when the pool holds 2.0 m3, at t = 200 s.
        The pool must grow at exactly 0.01 m3/step up to t = 200 s (2.0 m3), then the
        emergency rate (25 L/s/m2 * 50 m2 = 1.25 m3/s) pulls it back down.
        """
        inputs = _base_inputs(ventilation_rate=0.0, emergency_vent_rate=25.0,
                              vent_switch_conc=8.0, calc_duration=400)
        time = np.arange(0.0, 401.0, 1.0)
        release = np.full(len(time), 0.01)

        _, volume_m3, _ = room_gas_balance(inputs, time, release,
                                           {"co": 0.5, "h2": 0.5})
        pool = volume_m3.sum(axis=0)

        self.assertAlmostEqual(float(pool[100]), 1.0)
        self.assertAlmostEqual(float(pool[200]), 2.0)
        self.assertLess(float(pool[201]), 2.0)


class LflHandCalcTests(unittest.TestCase):
    def test_le_chatelier_for_the_half_and_half_mixture(self):
        """Hand calculation: LFL = 1 / (0.5/4.0 + 0.5/12.5) = 1/0.165 = 6.0606... v/v%"""
        lfl, label = resolve_lfl(LIBInputs(use_le_chatelier_lfl=True), LIBSpec(),
                                 {"h2": 0.5, "co": 0.5})
        self.assertEqual(label, "Le Chatelier LFL")
        self.assertAlmostEqual(lfl, 1.0 / (0.5 / 4.0 + 0.5 / 12.5), places=12)
        self.assertAlmostEqual(lfl, 6.060606, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
