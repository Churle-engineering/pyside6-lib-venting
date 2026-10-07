"""Activation timing, scenario form and persistence regressions."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QTabWidget

from dataclass_forms import read_form
from information import CHEMICAL_PROPERTIES, LIBInputs
from main import ScenarioInputDialog
from pdf import _dataclass_rows
from saveload import _decode, _encode
from venting_calculation import room_gas_balance


class EmergencyVentDelayTests(unittest.TestCase):
    def inputs(self, **overrides):
        values = dict(room_height=1.0, room_area=1.0, equip_space=0.0,
                      ventilation_rate=0.0, emergency_vent_rate=1000.0,
                      vent_switch_conc=1.0)
        values.update(overrides)
        return LIBInputs(**values)

    def solve(self, inputs, release, fractions=None):
        time = np.arange(len(release), dtype=float)
        _, volume, _ = room_gas_balance(inputs, time, release,
                                        fractions or {"co": 1.0})
        return volume.sum(axis=0)

    def test_delay_starts_at_trigger_not_at_simulation_start(self):
        release = np.array([0., 0., 0., .1, .1, .1, .1, .1])
        for delay in (2.0, 1.5):
            with self.subTest(delay=delay):
                actual = self.solve(self.inputs(emergency_vent_delay=delay), release)
                r = np.exp(-1.0)
                expected = np.array([0., 0., 0., .1, .2, .3,
                                     .3 * r + .1 * (1 - r),
                                     (.3 * r + .1 * (1 - r)) * r + .1 * (1 - r)])
                np.testing.assert_allclose(actual, expected)

    def test_zero_delay_preserves_immediate_nonlatched_control(self):
        release = np.array([0., 1., 0., 0., 1., 0., 0.])
        trigger = 50.0
        inputs = self.inputs(ventilation_rate=1000.0, emergency_vent_rate=2000.0,
                             vent_switch_conc=trigger * 100 / CHEMICAL_PROPERTIES["co"]["lfl"])
        expected = [0.]
        for inflow in release[1:]:
            q = 2.0 if expected[-1] * 100 >= trigger else 1.0
            r = np.exp(-q)
            expected.append(expected[-1] * r + inflow * (1 - r) / q)
        self.assertEqual(inputs.emergency_vent_delay, 0.0)
        np.testing.assert_allclose(self.solve(inputs, release), expected)

    def test_countdown_survives_co_dropping_below_trigger(self):
        release = np.array([0., 1., 0., 0., 1., 0., 0.])
        inputs = self.inputs(
            ventilation_rate=1000.0, emergency_vent_rate=2000.0,
            vent_switch_conc=50 * 100 / CHEMICAL_PROPERTIES["co"]["lfl"],
            emergency_vent_delay=3.0)
        r = np.exp(-1.0)
        g = 1 - r
        at_four = g * r**3 + g
        at_five = at_four * np.exp(-2.0)
        expected = [0., g, g * r, g * r**2, at_four, at_five, at_five * r]
        np.testing.assert_allclose(self.solve(inputs, release), expected)

    def test_delay_beyond_run_never_activates_emergency_rate(self):
        release = np.full(10, .1)
        actual = self.solve(self.inputs(emergency_vent_delay=20.0), release)
        np.testing.assert_allclose(actual, np.arange(10) * .1)

    def test_disabled_triggers_ignore_delay(self):
        release = np.full(10, .1)
        for overrides, fractions in (
            ({"vent_switch_conc": 0.0}, {"co": 1.0}),
            ({"emergency_vent_rate": 0.0}, {"co": 1.0}),
            ({}, {"h2": 1.0}),
        ):
            with self.subTest(overrides=overrides, fractions=fractions):
                inputs = self.inputs(emergency_vent_delay=2.0, **overrides)
                np.testing.assert_allclose(self.solve(inputs, release, fractions),
                                           np.arange(10) * .1)


class EmergencyVentDelaySurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scenario_form_places_delay_beside_emergency_rate_and_reads_it(self):
        dialog = ScenarioInputDialog(None, LIBInputs())
        try:
            tabs = dialog.findChild(QTabWidget)
            room = tabs.widget(1)
            form = room.layout()
            rate = dialog._field_widgets["emergency_vent_rate"]
            delay = dialog._field_widgets["emergency_vent_delay"]
            self.assertEqual(tabs.tabText(1), "Room Details")
            self.assertEqual(form.getWidgetPosition(delay)[0],
                             form.getWidgetPosition(rate)[0] + 1)
            self.assertEqual(delay.text(), "0.0")
            delay.setText("7.5")
            self.assertEqual(read_form(LIBInputs, dialog._field_widgets).emergency_vent_delay, 7.5)
            edited = ScenarioInputDialog(None, LIBInputs(emergency_vent_delay=7.5))
            try:
                self.assertEqual(edited._field_widgets["emergency_vent_delay"].text(), "7.5")
            finally:
                edited.deleteLater()
        finally:
            dialog.deleteLater()
            self.app.processEvents()

    def test_save_round_trip_and_older_save_default(self):
        encoded = _encode(LIBInputs(emergency_vent_delay=7.5))
        self.assertEqual(_decode(encoded).emergency_vent_delay, 7.5)
        del encoded["fields"]["emergency_vent_delay"]
        self.assertEqual(_decode(encoded).emergency_vent_delay, 0.0)

    def test_report_includes_delay_value_and_units(self):
        rows = _dataclass_rows(LIBInputs(emergency_vent_delay=7.5))
        self.assertIn(["Emergency Vent Activation Delay", "7.5", "s"], rows)


if __name__ == "__main__":
    unittest.main()
