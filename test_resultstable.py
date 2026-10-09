"""Regression checks for results-table defaults and copyable threshold text."""

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from resultstable import ResultsTableDialog


class ResultsTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        toxic_species = [
            SimpleNamespace(species=name, peak_ppm=ppm, percent_of_erpg_3=percent)
            for name, ppm, percent in (
                ("benzene", 100.0, 10.0), ("hf", 25.0, 50.0),
                ("hcn", 5.0, 20.0), ("co", 250.0, 50.0),
            )
        ]
        self.summary = SimpleNamespace(
            toxic_species=toxic_species,
            flammable_species=[SimpleNamespace(species="co", peak_ppm=12500.0, peak_vv=1.25)],
            peak_flammable_ppm=12500.0, peak_percent_of_lfl=25.0, lfl_percent=5.0,
        )
        self.dialog = ResultsTableDialog(
            None, [SimpleNamespace(name="Scenario", summary=self.summary)],
        )

    def tearDown(self):
        self.dialog.deleteLater()
        self.app.processEvents()

    def select_columns(self, keys):
        for row, column in enumerate(self.dialog._columns):
            self.dialog.column_list.item(row).setCheckState(
                Qt.Checked if column.key in keys else Qt.Unchecked,
            )

    def test_default_columns_and_toggle(self):
        self.assertEqual(
            [column.key for column in self.dialog._selected_columns()],
            ["tox:co:peak_ppm", "tox:hcn:peak_ppm", "tox:hf:peak_ppm", "tox:benzene:peak_ppm"],
        )
        self.assertFalse(self.dialog.include_threshold_text.isChecked())
        self.dialog.include_threshold_text.setChecked(True)
        self.assertEqual(
            [self.dialog.table.item(0, column).text() for column in range(4)],
            ["250.0 ppm 50.0% of ERPG3", "5.0 ppm 20.0% of ERPG3",
             "25.0 ppm 50.0% of ERPG3", "100.0 ppm 10.0% of ERPG3"],
        )
        self.dialog.include_threshold_text.setChecked(False)
        self.assertEqual(self.dialog.table.item(0, 0).text(), "250.0")

    def test_flammable_species_uses_own_lfl_and_total_uses_assessment_lfl(self):
        self.select_columns({"flam:co:peak_ppm", "peak_flam_ppm"})
        self.dialog.include_threshold_text.setChecked(True)
        self.assertEqual(self.dialog.table.item(0, 0).text(), "12500 ppm 25.0% of LFL")
        self.assertEqual(self.dialog.table.item(0, 1).text(), "12500 ppm 10.0% of LFL")

    def test_missing_species_and_thresholds(self):
        self.summary.toxic_species = [self.summary.toxic_species[-1]]
        self.summary.toxic_species[0].percent_of_erpg_3 = None
        self.dialog.include_threshold_text.setChecked(True)
        self.assertEqual(self.dialog.table.item(0, 0).text(), "250.0 ppm")
        self.assertEqual(self.dialog.table.item(0, 1).text(), "-")

    def test_non_peak_ppm_columns_are_not_annotated(self):
        self.summary.toxic_species[-1].erpg_3 = 500.0
        self.select_columns({"tox:co:erpg", "tox:co:percent_erpg"})
        self.dialog.include_threshold_text.setChecked(True)
        self.assertEqual(self.dialog.table.item(0, 0).text(), "500.000")
        self.assertEqual(self.dialog.table.item(0, 1).text(), "50.0")

    def test_clipboard_actions_preserve_annotations(self):
        self.dialog.include_threshold_text.setChecked(True)
        expected = "250.0 ppm 50.0% of ERPG3"
        self.dialog._copy_cell(0, 0)
        self.assertEqual(self.app.clipboard().text(), expected)
        self.dialog._copy_column(0)
        self.assertTrue(self.app.clipboard().text().endswith(expected))
        self.dialog._copy_row(0)
        self.assertIn(expected, self.app.clipboard().text())
        self.dialog._copy_table()
        self.assertIn(expected, self.app.clipboard().text())
        self.dialog.table.selectAll()
        self.dialog._copy_selection()
        self.assertIn(expected, self.app.clipboard().text())

    def test_copy_for_word_includes_structured_html_and_plain_text(self):
        self.dialog.table.setVerticalHeaderLabels(["<Study & Scenario>"])

        self.dialog._copy_table_for_word()

        mime_data = self.app.clipboard().mimeData()
        self.assertTrue(mime_data.hasHtml())
        self.assertTrue(mime_data.hasText())
        html = mime_data.html()
        self.assertIn("<table", html)
        self.assertEqual(html.count("<tr>"), 2)
        self.assertEqual(html.count("<th>"), 5)
        self.assertEqual(html.count("<td>"), 5)
        self.assertIn("&lt;Study &amp; Scenario&gt;", html)
        self.assertIn("<Study & Scenario>", mime_data.text())
        self.app.clipboard().clear()


if __name__ == "__main__":
    unittest.main()