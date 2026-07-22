"""
Builds a copy-paste friendly table of computed peak values from calculation
results. Rows are scenarios, columns are user-selected gas/unit species.

The table is placed on the clipboard as tab-separated values (TSV). When pasted
into Microsoft Word it is automatically converted into a table grid (or fills an
existing equal-sized table cell-by-cell), giving the user formatted results
without reading through graphs and reports.

This module is intentionally standalone (no imports from the main application)
to avoid circular imports.
"""

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

try:
    from information import CHEMICAL_PROPERTIES
except Exception:
    CHEMICAL_PROPERTIES = {}


def _metric_peak(df, col):
    return df[col].max()

def _metric_time_of_peak(df, col):
    if "Time (s)" not in df.columns:
        return ""
    return df.loc[df[col].idxmax(), "Time (s)"]


METRICS = {
    "Peak Value": _metric_peak,
    "Time of Peak (s)": _metric_time_of_peak,
}

# Which stored DataFrame to read for each (source, unit) combination.
DATA_SOURCES = {
    "Toxicity": {"dict": "tox_scenario_results", "df_keys": {"v/v%": "tox_vv_df", "mg/L": "tox_mgl_df"}},
    "Flammability": {"dict": "flam_scenario_results", "df_keys": {"v/v%": "flam_vv_df", "mg/L": "flam_mgl_df"}},
}

# Short tag shown in column headers so the user can tell tox CO from flam CO.
SOURCE_TAG = {"Toxicity": "Tox", "Flammability": "Flam"}

def _get_results_dict(state, source):
    """Return the scenario results dict for the given source, or {}."""
    attr = DATA_SOURCES[source]["dict"]
    return getattr(state, attr, {}) or {}


def _discover_columns(results_dict, df_keys):
    """Collect the unique set of data columns across all scenario DataFrames."""
    cols = set()
    for res in results_dict.values():
        for df_key in df_keys.values():
            df = res.get(df_key)
            if df is not None:
                cols.update(c for c in df.columns if c != "Time (s)")
    return sorted(cols)


def _discover_combined_columns(state):
    """
    Build the combined column list across both sources.

    Returns a list of specs: {"label", "source", "col"} where `label` is a
    source-tagged, user-facing header (e.g. "CO (v/v%) [Tox]").
    """
    specs = []
    for source, tag in SOURCE_TAG.items():
        results_dict = _get_results_dict(state, source)
        if not results_dict:
            continue
        df_keys = DATA_SOURCES[source]["df_keys"]
        for col in _discover_columns(results_dict, df_keys):
            if source == "Toxicity" and col.endswith(" (v/v%)"):
                gas = col[:-7]
                specs.append({"label": f"{gas} (ppm) [{tag}]", "source": source, "col": col, "special": "tox_ppm", "gas": gas})
            specs.append({"label": f"{col} [{tag}]", "source": source, "col": col})

    # Derived "% of LFL" column (peak Total Gas v/v% relative to the battery LFL).
    if _get_results_dict(state, "Flammability"):
        tag = SOURCE_TAG["Flammability"]
        specs.append({
            "label": f"% of LFL [{tag}]",
            "source": "Flammability",
            "col": "__pct_of_lfl__",
            "special": "pct_of_lfl",
        })
    return specs


def _union_scenarios(state):
    """Deduplicated list of scenario names present in either source."""
    names = []
    seen = set()
    for source in SOURCE_TAG:
        for name in _get_results_dict(state, source).keys():
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _find_df_for_column(res, df_keys, col):
    """Find the DataFrame within a scenario result that contains `col`."""
    for df_key in df_keys.values():
        df = res.get(df_key)
        if df is not None and col in df.columns:
            return df
    return None


def _compute_pct_of_lfl(res, decimals):
    """
    Peak Total Gas (v/v%) expressed as a percentage of the battery LFL.

    Returns a formatted string ending in "% of LFL", or "" if unavailable.
    """
    if res is None:
        return ""
    df = res.get("flam_vv_df")
    if df is None or "Total Gas (v/v%)" not in df.columns:
        return ""
    try:
        input_data = res.get("input", {}) or {}
        lfl_bat = float(input_data.get("lfl_(%)", input_data.get("LFL (%)", 0)))
        if lfl_bat <= 0:
            return ""
        peak_total = float(df["Total Gas (v/v%)"].max())
        pct = (peak_total / lfl_bat) * 100
        return f"{pct:.{decimals}f}% of LFL"
    except (ValueError, TypeError):
        return ""


def _compute_pct_of_erpg3(res, gas_name, decimals):
    """Peak toxic gas % of ERPG-3 based on matching mg/L concentration."""
    if res is None or not gas_name:
        return ""

    df_mgl = res.get("tox_mgl_df")
    mgl_col = f"{gas_name} (mg/L)"
    if df_mgl is None or mgl_col not in df_mgl.columns:
        return ""

    try:
        input_data = res.get("input", {}) or {}
        gas_data = input_data.get("gas_data", {}) or {}
        erpg3 = gas_data.get(gas_name, {}).get("erpg_3")
        if erpg3 is None:
            erpg3 = CHEMICAL_PROPERTIES.get(gas_name.lower(), {}).get("erpg_3")
        erpg3 = float(erpg3)
        if erpg3 <= 0:
            return ""

        peak_mgl = float(df_mgl[mgl_col].max())
        pct = (peak_mgl / erpg3) * 100
        return f"{pct:.{decimals}f}% of ERPG-3"
    except (ValueError, TypeError):
        return ""
    

def build_results_table(state, scenarios, column_specs, metric_name, decimals, include_erpg3_text=False):
    """
    Assemble a single combined table as a list of rows (first row is the header).

    Columns may come from either source; each spec carries its own source so
    toxic and flammable results sit side by side in one table.

    rows[0]      -> ["Scenario", label1, label2, ...]
    rows[1..n]   -> [scenario_name, value1, value2, ...]
    """
    metric_fn = METRICS[metric_name]

    header = ["Scenario"] + [spec["label"] for spec in column_specs]
    rows = [header]

    for name in scenarios:
        row = [name]
        for spec in column_specs:
            source = spec["source"]
            col = spec["col"]
            results_dict = _get_results_dict(state, source)
            df_keys = DATA_SOURCES[source]["df_keys"]
            res = results_dict.get(name)
            value = ""
            if spec.get("special") == "pct_of_lfl":
                value = _compute_pct_of_lfl(res, decimals)
            elif spec.get("special") == "tox_ppm":
                if res is not None:
                    df = _find_df_for_column(res, df_keys, col)
                    if df is not None:
                        try:
                            raw = metric_fn(df, col)
                            value = f"{float(raw):.{decimals}f}"
                        except (ValueError, TypeError):
                            value = str(raw)

                    if include_erpg3_text and metric_name == "Peak Value" and value:
                        pct_text = _compute_pct_of_erpg3(res, spec.get("gas", ""), decimals)
                        if pct_text:
                            value = f"{value} ({pct_text})"
            elif res is not None:
                df = _find_df_for_column(res, df_keys, col)
                if df is not None:
                    try:
                        raw = metric_fn(df, col)
                        value = f"{float(raw):.{decimals}f}"
                    except (ValueError, TypeError):
                        value = str(raw)
            row.append(value)
        rows.append(row)

    return rows


def copy_table_to_clipboard(rows, include_header=True):
    """Place the table on the clipboard as tab-separated values."""
    data = rows if include_header else rows[1:]
    tsv = "\n".join("\t".join(str(cell) for cell in r) for r in data)
    QApplication.clipboard().setText(tsv)


# --- UI here ---

def open_results_table_window(parent, state):
    """Open the interactive table builder window."""
    has_tox = bool(getattr(state, "tox_scenario_results", {}))
    has_flam = bool(getattr(state, "flam_scenario_results", {}))
    if not has_tox and not has_flam:
        QMessageBox.warning(
            None,
            "No Results",
            "No calculation results are available yet.\n"
            "Run a Toxicity or Explosive calculation first, then build the table.",
        )
        return

    win = QDialog(parent)
    win.setWindowTitle("Build Results Table")
    win.resize(900, 650)
    win.setWindowModality(Qt.WindowModality.WindowModal)
    win.setStyleSheet("background-color: #f5f7f9;")

    layout = QVBoxLayout(win)
    layout.setContentsMargins(20, 20, 20, 15)
    layout.setSpacing(12)

    header = QFrame(win)
    header.setStyleSheet("background-color: white; border-radius: 8px;")
    header_layout = QVBoxLayout(header)
    header_layout.setContentsMargins(20, 15, 20, 15)
    title = QLabel("📋 Build Results Table")
    title.setStyleSheet("font-family: Segoe UI; font-size: 16px; font-weight: 700; color: #2c3e50;")
    header_layout.addWidget(title)
    layout.addWidget(header)

    separator = QFrame(win)
    separator.setFixedHeight(3)
    separator.setStyleSheet("background-color: #8e44ad;")
    layout.addWidget(separator)

    controls = QFrame(win)
    controls.setStyleSheet("background-color: #f5f7f9;")
    controls_layout = QHBoxLayout(controls)
    controls_layout.setContentsMargins(0, 0, 0, 0)
    controls_layout.setSpacing(10)

    metric_label = QLabel("Metric:")
    metric_label.setStyleSheet("font-family: Segoe UI; font-size: 10pt; font-weight: 700; color: #2c3e50;")
    controls_layout.addWidget(metric_label)

    metric_combo = QComboBox()
    metric_combo.addItems(list(METRICS.keys()))
    metric_combo.setCurrentIndex(0)
    metric_combo.setMinimumWidth(180)
    controls_layout.addWidget(metric_combo)

    decimals_label = QLabel("Decimals:")
    decimals_label.setStyleSheet("font-family: Segoe UI; font-size: 10pt; font-weight: 700; color: #2c3e50;")
    controls_layout.addWidget(decimals_label)

    decimals_spin = QSpinBox()
    decimals_spin.setRange(0, 8)
    decimals_spin.setValue(2)
    decimals_spin.setFixedWidth(70)
    controls_layout.addWidget(decimals_spin)

    include_header_var = QCheckBox("Include header row")
    include_header_var.setChecked(True)
    include_header_var.setStyleSheet("font-family: Segoe UI; font-size: 9pt; color: #2c3e50;")
    controls_layout.addWidget(include_header_var)

    include_erpg3_btn = QPushButton("ERPG-3 text: OFF")
    include_erpg3_btn.setCheckable(True)
    include_erpg3_btn.setStyleSheet(
        "QPushButton { border: 1px solid #d9e2ec; border-radius: 6px; padding: 4px 10px; "
        "font-family: Segoe UI; font-size: 9pt; color: #2c3e50; background-color: white; }"
        "QPushButton:checked { background-color: #e8f4ff; border-color: #5dade2; color: #1b4f72; }"
    )
    controls_layout.addWidget(include_erpg3_btn)
    controls_layout.addStretch(1)
    layout.addWidget(controls)

    def make_selection_panel(title_text):
        box = QGroupBox(title_text)
        box.setStyleSheet(
            "QGroupBox { background-color: white; border: 1px solid #d9e2ec; border-radius: 8px; margin-top: 10px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #2c3e50; font-family: Segoe UI; font-weight: 700; }"
        )
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(12, 18, 12, 12)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(4)
        inner_layout.addStretch(1)
        area.setWidget(inner)

        box_layout.addWidget(area)
        return box, inner_layout

    panels = QWidget(win)
    panels_layout = QHBoxLayout(panels)
    panels_layout.setContentsMargins(0, 0, 0, 0)
    panels_layout.setSpacing(12)
    scen_box, scen_layout = make_selection_panel("Scenarios (rows)")
    col_box, col_layout = make_selection_panel("Gas Species / Units (columns) - [Tox] / [Flam]")
    panels_layout.addWidget(scen_box)
    panels_layout.addWidget(col_box)
    layout.addWidget(panels)

    scenario_vars = {}
    column_vars = {}   # label -> {"var": QCheckBox, "spec": {...}}

    preview_frame = QFrame(win)
    preview_frame.setStyleSheet("background-color: white; border: 1px solid #d9e2ec; border-radius: 8px;")
    preview_layout = QVBoxLayout(preview_frame)
    preview_layout.setContentsMargins(10, 10, 10, 10)

    preview_tree = QTableWidget()
    preview_tree.setAlternatingRowColors(True)
    preview_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    preview_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    preview_tree.setWordWrap(False)
    preview_tree.setStyleSheet(
        "QTableWidget { background-color: white; alternate-background-color: #f9f9f9; gridline-color: #e6e6e6; }"
        "QHeaderView::section { background-color: #eef2f7; color: #2c3e50; font-family: Segoe UI; font-weight: 700; padding: 6px; border: none; }"
    )
    preview_layout.addWidget(preview_tree)
    layout.addWidget(preview_frame, 1)

    def current_rows():
        scenarios = [name for name, checkbox in scenario_vars.items() if checkbox.isChecked()]
        column_specs = [entry["spec"] for entry in column_vars.values() if entry["var"].isChecked()]
        if not scenarios or not column_specs:
            return None
        return build_results_table(
            state,
            scenarios,
            column_specs,
            metric_combo.currentText(),
            decimals_spin.value(),
            include_erpg3_text=include_erpg3_btn.isChecked(),
        )

    def refresh_preview(*_):
        rows = current_rows()
        preview_tree.clear()
        if not rows:
            preview_tree.setRowCount(0)
            preview_tree.setColumnCount(0)
            return

        header, *body = rows
        preview_tree.setColumnCount(len(header))
        preview_tree.setRowCount(len(body))
        preview_tree.setHorizontalHeaderLabels(header)
        header_view = preview_tree.horizontalHeader()
        for column_index in range(len(header)):
            header_view.setSectionResizeMode(column_index, QHeaderView.ResizeMode.ResizeToContents)

        for row_index, row_values in enumerate(body):
            for column_index, cell in enumerate(row_values):
                item = QTableWidgetItem(str(cell))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                preview_tree.setItem(row_index, column_index, item)

    def clear_layout(layout_obj):
        while layout_obj.count():
            item = layout_obj.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def rebuild_selectors(*_):
        clear_layout(scen_layout)
        clear_layout(col_layout)
        scenario_vars.clear()
        column_vars.clear()

        for name in _union_scenarios(state):
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)
            checkbox.setStyleSheet("font-family: Segoe UI; font-size: 9pt; color: #2c3e50;")
            checkbox.stateChanged.connect(refresh_preview)
            scenario_vars[name] = checkbox
            scen_layout.insertWidget(scen_layout.count(), checkbox)

        scen_layout.insertStretch(scen_layout.count(), 1)

        for spec in _discover_combined_columns(state):
            checkbox = QCheckBox(spec["label"])
            checkbox.setChecked(False)
            checkbox.setStyleSheet("font-family: Segoe UI; font-size: 9pt; color: #2c3e50;")
            checkbox.stateChanged.connect(refresh_preview)
            column_vars[spec["label"]] = {"var": checkbox, "spec": spec}
            col_layout.insertWidget(col_layout.count(), checkbox)

        col_layout.insertStretch(col_layout.count(), 1)
        refresh_preview()

    def do_copy():
        rows = current_rows()
        if not rows:
            QMessageBox.warning(win, "Nothing to Copy", "Select at least one scenario and one column.")
            return
        copy_table_to_clipboard(rows, include_header=include_header_var.isChecked())
        QMessageBox.information(
            win,
            "Copied",
            "Table copied to clipboard as tab-separated values.\n\n"
            "Paste directly into a Word table (or into the document to create one).",
        )

    metric_combo.currentIndexChanged.connect(refresh_preview)
    decimals_spin.valueChanged.connect(refresh_preview)
    include_header_var.stateChanged.connect(refresh_preview)
    include_erpg3_btn.toggled.connect(lambda checked: include_erpg3_btn.setText(f"ERPG-3 text: {'ON' if checked else 'OFF'}"))
    include_erpg3_btn.toggled.connect(refresh_preview)

    buttons = QHBoxLayout()
    buttons.setContentsMargins(0, 0, 0, 0)
    buttons.setSpacing(10)

    def styled_btn(text, command, color):
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: white; border: none; border-radius: 6px; padding: 8px 14px; font-family: Segoe UI; font-size: 10pt; font-weight: 700; }}"
            f"QPushButton:hover {{ background-color: {color}; }}"
        )
        button.clicked.connect(command)
        buttons.addWidget(button)
        return button

    styled_btn("📋 Copy to Clipboard", do_copy, "#8e44ad")
    styled_btn("Close", win.reject, "#7f8c8d")
    buttons.addStretch(1)
    layout.addLayout(buttons)

    rebuild_selectors()
    refresh_preview()
    win.exec()


