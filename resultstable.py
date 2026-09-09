"""Results table builder: a cross-scenario comparison table.

The user picks scenarios (rows) and result types (columns) from the two lists at the
top; the table below is rebuilt from every selected scenario's ``ResultSummary``.
Everything is read-only and derived - no result data is stored here.

Clicking any cell copies its text to the clipboard; clicking a header copies that
whole column/row, and "Copy Table" copies the whole thing as tab-separated text
(pastes straight into Excel/Word).
"""

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence


NOT_AVAILABLE = "-"


@dataclass(slots=True)
class ColumnSpec:
    """One selectable table column: how it is labelled and how it reads a summary."""

    key: str
    header: str
    value: Callable
    fmt: str = "{:.3f}"


def _format(value, fmt):
    if value is None:
        return NOT_AVAILABLE
    if isinstance(value, str):
        return value
    try:
        return fmt.format(value)
    except (TypeError, ValueError):
        return str(value)


def _crossing_time(summary):
    return summary.lfl_crossing_time if summary.lfl_crossing_time is not None else "Not reached"


# Columns every result has, independent of which species its composition contains.
GENERAL_COLUMNS = [
    ColumnSpec("calc_method", "Calculation Method", lambda s: s.calc_method, "{}"),
    ColumnSpec("peak_flam_vv", "Peak Flammable Gas (v/v%)", lambda s: s.peak_flammable_vv),
    ColumnSpec("peak_flam_ppm", "Peak Flammable Gas (ppm)", lambda s: s.peak_flammable_ppm, "{:.0f}"),
    ColumnSpec("peak_flam_mgl", "Peak Flammable Gas (mg/L)", lambda s: s.peak_flammable_mgl),
    ColumnSpec("peak_flam_time", "Time of Peak Flammable Gas (s)", lambda s: s.peak_flammable_time, "{:.0f}"),
    ColumnSpec("lfl_label", "LFL Basis", lambda s: s.lfl_label, "{}"),
    ColumnSpec("lfl_percent", "Assessment LFL (v/v%)", lambda s: s.lfl_percent),
    ColumnSpec("peak_percent_lfl", "Peak % of LFL", lambda s: s.peak_percent_of_lfl, "{:.1f}"),
    ColumnSpec("lfl_crossing", "Time LFL Reached (s)", _crossing_time, "{:.0f}"),
]


def _species_getter(attribute, species, toxic):
    """Read one species' figure out of a summary, or None if it has no such species."""
    def getter(summary):
        block = summary.toxic_species if toxic else summary.flammable_species
        for species_summary in block:
            if species_summary.species == species:
                return getattr(species_summary, attribute)
        return None
    return getter


def _species_columns(summaries):
    """Per-species columns for every species present in the given summaries."""
    columns = []
    seen = set()

    for summary in summaries:
        for species in summary.toxic_species:
            if ("tox", species.species) in seen:
                continue
            seen.add(("tox", species.species))
            name = species.species.upper()
            columns.extend([
                ColumnSpec(f"tox:{species.species}:peak_ppm", f"{name} Peak (ppm)",
                           _species_getter("peak_ppm", species.species, True), "{:.1f}"),
                ColumnSpec(f"tox:{species.species}:peak_vv", f"{name} Peak (v/v%)",
                           _species_getter("peak_vv", species.species, True), "{:.4f}"),
                ColumnSpec(f"tox:{species.species}:peak_mgl", f"{name} Peak (mg/L)",
                           _species_getter("peak_mgl", species.species, True), "{:.4f}"),
                ColumnSpec(f"tox:{species.species}:peak_time", f"{name} Time of Peak (s)",
                           _species_getter("peak_time", species.species, True), "{:.0f}"),
                ColumnSpec(f"tox:{species.species}:erpg", f"{name} ERPG-3 (ppm)",
                           _species_getter("erpg_3", species.species, True), "{:.3f}"),
                ColumnSpec(f"tox:{species.species}:percent_erpg", f"{name} % of ERPG-3",
                           _species_getter("percent_of_erpg_3", species.species, True), "{:.1f}"),
            ])

    for summary in summaries:
        for species in summary.flammable_species:
            if ("flam", species.species) in seen:
                continue
            seen.add(("flam", species.species))
            # a species can be both flammable and toxic, so the headers must differ
            name = f"{species.species.upper()} (Flammable)"
            columns.extend([
                ColumnSpec(f"flam:{species.species}:peak_vv", f"{name} Peak (v/v%)",
                           _species_getter("peak_vv", species.species, False), "{:.4f}"),
                ColumnSpec(f"flam:{species.species}:peak_ppm", f"{name} Peak (ppm)",
                           _species_getter("peak_ppm", species.species, False), "{:.0f}"),
                ColumnSpec(f"flam:{species.species}:peak_mgl", f"{name} Peak (mg/L)",
                           _species_getter("peak_mgl", species.species, False), "{:.4f}"),
                ColumnSpec(f"flam:{species.species}:peak_time", f"{name} Time of Peak (s)",
                           _species_getter("peak_time", species.species, False), "{:.0f}"),
            ])

    return columns


def build_columns(summaries):
    """Every column that can be offered for the given set of summaries."""
    return GENERAL_COLUMNS + _species_columns(summaries)


class ResultsTableDialog(QDialog):
    """Scenario x result-type comparison table built from stored ResultSummaries."""

    DEFAULT_COLUMN_KEYS = ("peak_flam_vv", "peak_flam_time", "lfl_percent",
                           "peak_percent_lfl", "lfl_crossing")

    def __init__(self, parent, scenarios):
        super().__init__(parent)
        self.setWindowTitle("Results Table")

        self._scenarios = [s for s in scenarios if s.summary is not None]
        self._columns = build_columns([s.summary for s in self._scenarios])

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Tick the scenarios (rows) and result types (columns) to compare. "
            "Click a cell to copy it, or a header to copy that column/row."))

        self.scenario_list = self._make_list([s.name for s in self._scenarios], check_all=True)
        self.column_list = self._make_list(
            [c.header for c in self._columns],
            checked_rows={row for row, column in enumerate(self._columns)
                          if column.key in self.DEFAULT_COLUMN_KEYS},
        )

        lists_row = QHBoxLayout()
        lists_row.addWidget(self._titled("Scenarios", self.scenario_list))
        lists_row.addWidget(self._titled("Result Types", self.column_list))
        layout.addLayout(lists_row)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.cellClicked.connect(self._copy_cell)
        self.table.horizontalHeader().sectionClicked.connect(self._copy_column)
        self.table.verticalHeader().sectionClicked.connect(self._copy_row)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        copy_table_button = QPushButton("Copy Table")
        copy_table_button.setToolTip("Copy the whole table to the clipboard as tab-separated text.")
        copy_table_button.clicked.connect(self._copy_table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.addButton(copy_table_button, QDialogButtonBox.ActionRole)
        layout.addWidget(buttons)

        self.scenario_list.itemChanged.connect(self._rebuild_table)
        self.column_list.itemChanged.connect(self._rebuild_table)

        self.resize(1000, 700)
        self._rebuild_table()

    # -- construction helpers -------------------------------------------------

    def _make_list(self, labels, check_all=False, checked_rows=()):
        widget = QListWidget()
        widget.setSelectionMode(QAbstractItemView.NoSelection)
        widget.setMaximumHeight(180)
        for row, label in enumerate(labels):
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if check_all or row in checked_rows else Qt.Unchecked)
            widget.addItem(item)
        return widget

    @staticmethod
    def _titled(title, widget):
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setStyleSheet("font-weight: bold;")
        box.addWidget(label)
        box.addWidget(widget)
        return container

    # -- table ----------------------------------------------------------------

    @staticmethod
    def _checked_rows(list_widget):
        return [row for row in range(list_widget.count())
                if list_widget.item(row).checkState() == Qt.Checked]

    def _selected_scenarios(self):
        return [self._scenarios[row] for row in self._checked_rows(self.scenario_list)]

    def _selected_columns(self):
        return [self._columns[row] for row in self._checked_rows(self.column_list)]

    def _rebuild_table(self):
        scenarios = self._selected_scenarios()
        columns = self._selected_columns()

        self.table.clear()
        self.table.setRowCount(len(scenarios))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([c.header for c in columns])
        self.table.setVerticalHeaderLabels([s.name for s in scenarios])

        for row, scenario in enumerate(scenarios):
            for column_index, column in enumerate(columns):
                text = _format(column.value(scenario.summary), column.fmt)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, column_index, item)

        self.table.resizeColumnsToContents()
        if not self._scenarios:
            self.status_label.setText("No scenarios have results yet - press Run first.")
        else:
            self.status_label.setText(
                f"{len(scenarios)} scenario(s) x {len(columns)} result type(s).")

    # -- clipboard ------------------------------------------------------------

    def _set_clipboard(self, text, message):
        QApplication.clipboard().setText(text)
        self.status_label.setText(message)

    def _copy_cell(self, row, column):
        item = self.table.item(row, column)
        if item is not None:
            self._set_clipboard(item.text(), f"Copied '{item.text()}' to the clipboard.")

    def _copy_column(self, column):
        header = self.table.horizontalHeaderItem(column)
        values = [header.text() if header else ""]
        values += [self.table.item(row, column).text() for row in range(self.table.rowCount())]
        self._set_clipboard("\n".join(values), "Copied column to the clipboard.")

    def _copy_row(self, row):
        header = self.table.verticalHeaderItem(row)
        values = [header.text() if header else ""]
        values += [self.table.item(row, col).text() for col in range(self.table.columnCount())]
        self._set_clipboard("\t".join(values), "Copied row to the clipboard.")

    def _copy_table(self):
        headers = [""] + [self.table.horizontalHeaderItem(col).text()
                          for col in range(self.table.columnCount())]
        lines = ["\t".join(headers)]
        for row in range(self.table.rowCount()):
            name = self.table.verticalHeaderItem(row)
            cells = [name.text() if name else ""]
            cells += [self.table.item(row, col).text()
                      for col in range(self.table.columnCount())]
            lines.append("\t".join(cells))
        self._set_clipboard("\n".join(lines), "Copied the whole table to the clipboard.")

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy) and self.table.hasFocus():
            self._copy_selection()
            return
        super().keyPressEvent(event)

    def _copy_selection(self):
        ranges = self.table.selectedRanges()
        if not ranges:
            return
        selection = ranges[0]
        lines = []
        for row in range(selection.topRow(), selection.bottomRow() + 1):
            lines.append("\t".join(
                self.table.item(row, col).text()
                for col in range(selection.leftColumn(), selection.rightColumn() + 1)))
        self._set_clipboard("\n".join(lines), "Copied selection to the clipboard.")


def open_results_table(parent, scenarios):
    """Show the results table for every scenario that has a stored result."""
    ResultsTableDialog(parent, scenarios).exec()
