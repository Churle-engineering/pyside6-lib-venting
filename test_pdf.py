"""Regression checks for per-scenario PDF gas composition input summaries."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph, Table

from information import CHEMICAL_PROPERTIES, GasComposition, LIBInputs, LIBSpec
from pdf import _MARGIN, _add_inputs_page, build_lib_report
from saveload import _decode, _encode
from scenario_model import ScenarioStore
from venting_calculation import run_venting_assessment, summarize_result


class GasCompositionReportTests(unittest.TestCase):
    def setUp(self):
        self.store = ScenarioStore()

    def run_scenario(self, name, composition, method="User Defined"):
        scenario = self.store.add(LIBInputs(
            scenario_description=name, composition_method=method,
            gas_composition=composition.name, calc_duration=2,
            cells_per_module=1, modules_per_unit=1, units=1,
            ventilation_rate=0,
        ))
        scenario.lib_spec = LIBSpec(lfl=5)
        scenario.gas_composition = composition
        with patch("venting_calculation.QMessageBox.warning") as warning:
            results = run_venting_assessment(
                None, self.store, CHEMICAL_PROPERTIES, node_ids=[scenario.node_id])
        warning.assert_not_called()
        self.assertIn(scenario.node_id, results)
        return scenario

    def input_story(self, scenario):
        story = []
        _add_inputs_page(story, scenario, scenario.result, A4[0] - 2 * _MARGIN)
        return story

    def composition_rows(self, story):
        return [
            item._cellvalues for item in story
            if isinstance(item, Table)
            and isinstance(item._cellvalues[0][0], Paragraph)
            and item._cellvalues[0][0].getPlainText() == "Species"
        ]

    def test_each_scenario_reports_its_own_composition_snapshot(self):
        first = self.run_scenario(
            "First", GasComposition("Blend <A>", {"h2": 40.0, "co": 60.0, "co2": 0.0}))
        second = self.run_scenario(
            "Second", GasComposition("Blend B", {"h2": 25.0, "co2": 75.0}))
        self.assertIsNot(first.result.gas_composition, first.gas_composition)
        self.assertIsNot(first.result.gas_composition.percentages, first.gas_composition.percentages)
        first.gas_composition.percentages["h2"] = 99.0
        first.gas_composition.name = "Edited blend"
        first.inputs.composition_method = "Literature Data"
        first.inputs.gas_composition = "Edited blend"

        for scenario, name, expected in (
            (first, "Blend <A>", [["H2", "40"], ["CO", "60"]]),
            (second, "Blend B", [["H2", "25"], ["CO2", "75"]]),
        ):
            with self.subTest(scenario=scenario.name):
                story = self.input_story(scenario)
                tables = self.composition_rows(story)
                self.assertEqual(len(tables), 1)
                self.assertEqual(tables[0][1:], expected)
                headings = [item.getPlainText() for item in story if isinstance(item, Paragraph)]
                self.assertIn(f"Gas Composition: {name}", headings)

    def test_literature_run_does_not_report_unused_custom_composition(self):
        scenario = self.run_scenario(
            "Literature", GasComposition("Unused", {"h2": 100.0}), "Literature Data")
        self.assertIsNone(scenario.result.gas_composition)
        scenario.inputs.composition_method = "User Defined"
        self.assertEqual(self.composition_rows(self.input_story(scenario)), [])

    def test_snapshot_survives_save_round_trip_and_library_removal(self):
        scenario = self.run_scenario("Saved", GasComposition("Original", {"h2": 100.0}))
        scenario.result = _decode(json.loads(json.dumps(_encode(scenario.result))))
        scenario.gas_composition = None
        self.assertEqual(scenario.result.gas_composition, GasComposition("Original", {"h2": 100.0}))
        self.assertEqual(self.composition_rows(self.input_story(scenario))[0][1:], [["H2", "100"]])

    def test_legacy_result_uses_only_matching_library_and_labels_fallback(self):
        scenario = self.run_scenario("Legacy", GasComposition("Original", {"h2": 100.0}))
        encoded = _encode(scenario.result)
        del encoded["fields"]["gas_composition"]
        scenario.result = _decode(encoded)
        story = self.input_story(scenario)
        self.assertEqual(self.composition_rows(story)[0][1:], [["H2", "100"]])
        self.assertTrue(any(
            "no run-time composition snapshot" in item.getPlainText()
            for item in story if isinstance(item, Paragraph)))
        scenario.gas_composition = GasComposition("Replacement", {"co": 100.0})
        self.assertEqual(self.composition_rows(self.input_story(scenario)), [])

    def test_multi_scenario_pdf_builds_with_composition_tables(self):
        scenarios = [
            self.run_scenario("First", GasComposition("Blend A", {"h2": 40.0, "co": 60.0})),
            self.run_scenario("Second", GasComposition("Blend B", {"h2": 25.0, "co2": 75.0})),
        ]
        entries = [(scenario, scenario.result, summarize_result(scenario.result, CHEMICAL_PROPERTIES))
                   for scenario in scenarios]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.pdf"
            with patch("pdf._add_inputs_page", wraps=_add_inputs_page) as add_inputs:
                build_lib_report(str(path), entries, {"project": "Composition check"}, logo_path="")
            self.assertEqual(add_inputs.call_count, 2)
            self.assertEqual(path.read_bytes()[:5], b"%PDF-")


if __name__ == "__main__":
    unittest.main()
