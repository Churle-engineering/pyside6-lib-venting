"""
saveload.py

Save and restore the complete state of the LIB Off-gassing Modelling Tool
to/from a single session file so users can close the program and later pick
up exactly where they left off.

Chosen file format: JSON (stored with a ``.libsave`` extension).

Why JSON rather than CSV?
    A CSV can only represent a single flat table. The program's state is a rich,
    nested structure: several spreadsheet tabs, text-box inputs, dropdown
    selections, and calculated results that contain whole pandas DataFrames
    and numpy arrays (used to redraw the results plots). JSON captures all of
    this in one human-readable, self-describing file.

What gets saved:
    * ``LIBPage``      - every spreadsheet tab (headers + cell values), the
                          per-tab toxicity/flammability calculation results
                          (including the DataFrames used to draw the result
                          plots), and the toolbar option selections.
    * ``SprinklerPage`` - all input fields and the last computed activation
                          result.
    * ``PoolSpillPage`` - all input fields and checkbox/option state.
    * ``ReceptorHeatFluxPage`` - all input fields.
    * Global options    - selected calculation method, LFL options, target
                          flammable gas, and imported gas flowrate data.

Forwards / backwards compatibility:
    * The payload is a versioned dictionary of top-level, independent sections.
    * Every section is optional on load; missing keys are skipped gracefully, so
      opening an older save in a newer build (or vice-versa) will not crash.
    * Spreadsheet rows are stored together with their column headers and are
      re-aligned by header name on load, so adding, removing or reordering input
      columns in future versions will not corrupt previously saved data.

Note on coupling:
    This module intentionally avoids importing anything from ``main.py`` (that
    would create a circular import, since ``main.py`` imports the two public
    entry points below). Instead it accesses pages/widgets duck-typed, via
    ``getattr``/``hasattr``, so it keeps working even if a given page hasn't
    been created yet.
"""

import os
import json
from datetime import datetime

import pandas as pd
import numpy as np

from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QTableWidgetItem,
)

FORMAT_ID = "lib_offgas_save"
SAVE_VERSION = 1
DEFAULT_EXTENSION = ".libsave"
FILE_DIALOG_FILTER = "LIB Offgas Save (*.libsave);;JSON files (*.json);;All files (*.*)"
FILE_OPEN_FILTER = "LIB Offgas Save (*.libsave *.json);;All files (*.*)"


# ---------------------------------------------------------------------------
# Generic encode / decode helpers (handle pandas + numpy objects so the
# calculation result dictionaries - which hold whole DataFrames used to draw
# the result plots - can be written to/read from plain JSON).
# ---------------------------------------------------------------------------
def _encode(obj):
    """Recursively convert an object graph into JSON-serialisable primitives."""
    if isinstance(obj, pd.DataFrame):
        return {"__type__": "DataFrame", "value": obj.to_dict(orient="split")}
    if isinstance(obj, pd.Series):
        return {"__type__": "Series", "value": obj.to_dict()}
    if isinstance(obj, dict):
        return {str(k): _encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _encode(obj.tolist())
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj


def _decode(obj):
    """Reverse :func:`_encode`, rebuilding pandas objects where tagged."""
    if isinstance(obj, dict):
        kind = obj.get("__type__")
        if kind == "DataFrame":
            v = obj.get("value", {})
            return pd.DataFrame(
                data=v.get("data", []),
                index=v.get("index"),
                columns=v.get("columns"),
            )
        if kind == "Series":
            return pd.Series(obj.get("value", {}))
        return {k: _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    return obj


def _json_default(o):
    """Fallback for any stray numpy scalar that slips through ``_encode``."""
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ---------------------------------------------------------------------------
# LIBPage - spreadsheet tabs + per-tab calculation results
# ---------------------------------------------------------------------------
def _collect_spreadsheet(spreadsheet):
    """Capture the raw cell text of a ``SpreadsheetWidget`` (one sheet tab)."""
    table = spreadsheet.table
    rows = []
    for row in range(table.rowCount()):
        row_values = []
        for col in range(table.columnCount()):
            item = table.item(row, col)
            row_values.append(item.text() if item is not None else "")
        rows.append(row_values)

    return {
        "headers": list(spreadsheet.headers),
        "row_count": table.rowCount(),
        "rows": rows,
    }


def _restore_spreadsheet(spreadsheet, sheet_payload):
    """Replay saved cell text into a ``SpreadsheetWidget``, re-triggering the
    same cell-changed parsing logic the user's own typing would trigger so the
    structured ``scenario_data`` array is rebuilt correctly."""
    table = spreadsheet.table
    saved_headers = sheet_payload.get("headers", []) or []
    rows = sheet_payload.get("rows", []) or []
    row_count = sheet_payload.get("row_count", len(rows))

    if row_count > table.rowCount():
        table.setRowCount(row_count)

    # Map saved column index -> current column index by header name, so
    # reordered/added/removed columns in a newer build don't corrupt data.
    col_map = {
        saved_idx: spreadsheet.headers.index(header)
        for saved_idx, header in enumerate(saved_headers)
        if header in spreadsheet.headers
    }

    table.blockSignals(True)
    for row, row_values in enumerate(rows):
        for saved_idx, text in enumerate(row_values):
            if not text:
                continue
            target_col = col_map.get(saved_idx)
            if target_col is None:
                continue
            item = table.item(row, target_col)
            if item is None:
                item = QTableWidgetItem()
                table.setItem(row, target_col, item)
            item.setText(text)
    table.blockSignals(False)

    # Re-run the parser (unblocked) for every cell we just populated so the
    # underlying numpy scenario_data buffer is filled exactly as it would be
    # from live user input.
    for row, row_values in enumerate(rows):
        for saved_idx, text in enumerate(row_values):
            if not text:
                continue
            target_col = col_map.get(saved_idx)
            if target_col is not None:
                spreadsheet.on_cell_changed(row, target_col)


def _collect_lib_page(lib_page):
    sheets = []
    for index in range(lib_page.tabs.count()):
        spreadsheet = lib_page.tabs.widget(index)
        if not hasattr(spreadsheet, "table") or not hasattr(spreadsheet, "headers"):
            continue

        sheet_payload = _collect_spreadsheet(spreadsheet)
        sheet_payload["name"] = lib_page.tabs.tabText(index)

        store = lib_page._result_store_for_sheet(spreadsheet)
        sheet_payload["results"] = {
            "tox": _encode(store.get("tox", {}) or {}),
            "flam": _encode(store.get("flam", {}) or {}),
        }
        sheets.append(sheet_payload)

    return {
        "sheets": sheets,
        "active_sheet_index": lib_page.tabs.currentIndex(),
        "sheet_counter": getattr(lib_page, "sheet_counter", len(sheets)),
    }


def _restore_lib_page(lib_page, payload):
    sheets = payload.get("sheets", []) or []
    tabs = lib_page.tabs

    if sheets:
        # Trim down to a single sheet, then add new sheets as needed so the
        # number of tabs matches the save file exactly.
        while tabs.count() > 1:
            lib_page.close_tab(0)

        for index, sheet_payload in enumerate(sheets):
            if index == 0:
                spreadsheet = tabs.widget(0)
            else:
                lib_page.add_sheet()
                spreadsheet = tabs.widget(tabs.count() - 1)

            tabs.setTabText(index, sheet_payload.get("name", tabs.tabText(index)))
            _restore_spreadsheet(spreadsheet, sheet_payload)

            results_payload = sheet_payload.get("results", {}) or {}
            store = lib_page._result_store_for_sheet(spreadsheet)
            store["tox"] = _decode(results_payload.get("tox", {}) or {})
            store["flam"] = _decode(results_payload.get("flam", {}) or {})

        active_index = payload.get("active_sheet_index", 0)
        if 0 <= active_index < tabs.count():
            tabs.setCurrentIndex(active_index)
        lib_page._sync_base_results_to_active_sheet()
        lib_page.sheet_counter = payload.get("sheet_counter", tabs.count())

    # Sync the toolbar option widgets to whatever was restored onto the base
    # window (options are restored onto base_window before this is called).
    base_window = getattr(lib_page, "base_window", None)
    if base_window is not None:
        if hasattr(lib_page, "calc_function"):
            selected_method = getattr(base_window, "selected_calc_method", None)
            if selected_method:
                found_index = lib_page.calc_function.findText(selected_method)
                if found_index >= 0:
                    lib_page.calc_function.setCurrentIndex(found_index)
        if hasattr(lib_page, "le_chatelier_check"):
            lib_page.le_chatelier_check.setChecked(bool(getattr(base_window, "use_le_chatelier_lfl", False)))
        if hasattr(lib_page, "temp_dependent_lfl"):
            lib_page.temp_dependent_lfl.setChecked(bool(getattr(base_window, "use_temp_dependent_lfl", False)))


# ---------------------------------------------------------------------------
# SprinklerPage
# ---------------------------------------------------------------------------
_SPRINKLER_LINE_EDITS = [
    "sprinkler_id",
    "ceiling_height",
    "radial_distance",
    "sprinkler_rti",
    "activation_temperature",
    "ambient_temperature",
]


def _collect_sprinkler_page(page):
    inputs = {
        name: getattr(page, name).text()
        for name in _SPRINKLER_LINE_EDITS
        if hasattr(page, name)
    }
    if hasattr(page, "fire_growth_rate"):
        inputs["fire_growth_rate"] = page.fire_growth_rate.currentText()

    return {
        "inputs": inputs,
        "last_activation_time_s": getattr(page, "last_activation_time_s", None),
        "results_label_text": page.results_label.text() if hasattr(page, "results_label") else None,
    }


def _restore_sprinkler_page(page, payload):
    inputs = payload.get("inputs", {}) or {}

    for name in _SPRINKLER_LINE_EDITS:
        widget = getattr(page, name, None)
        if widget is not None and name in inputs:
            widget.setText(str(inputs[name]))

    if hasattr(page, "fire_growth_rate") and inputs.get("fire_growth_rate"):
        found_index = page.fire_growth_rate.findText(inputs["fire_growth_rate"])
        if found_index >= 0:
            page.fire_growth_rate.setCurrentIndex(found_index)

    page.last_activation_time_s = payload.get("last_activation_time_s")

    results_label_text = payload.get("results_label_text")
    if hasattr(page, "results_label") and results_label_text:
        page.results_label.setText(results_label_text)

    if hasattr(page, "copy_activation_button"):
        page.copy_activation_button.setEnabled(page.last_activation_time_s is not None)


# ---------------------------------------------------------------------------
# PoolSpillPage
# ---------------------------------------------------------------------------
_POOL_SPILL_COMBOS = [
    "fuel_material",
    "surface_weather",
    "surface_material",
    "ground_conditions",
    "orifice_condition",
]
_POOL_SPILL_LINE_EDITS = [
    "ambient_temperature",
    "wind_speed",
    "bund_size",
    "volumetric_flowrate",
    "orifice_diameter",
    "delta_p",
    "operator_intervention_time",
]
_POOL_SPILL_CHECKBOXES = ["oi_tickbox", "pool_fire_tickbox"]


def _collect_pool_spill_page(page):
    inputs = {}
    for name in _POOL_SPILL_COMBOS:
        widget = getattr(page, name, None)
        if widget is not None:
            inputs[name] = widget.currentText()
    for name in _POOL_SPILL_LINE_EDITS:
        widget = getattr(page, name, None)
        if widget is not None:
            inputs[name] = widget.text()

    checkboxes = {
        name: getattr(page, name).isChecked()
        for name in _POOL_SPILL_CHECKBOXES
        if hasattr(page, name)
    }

    return {"inputs": inputs, "checkboxes": checkboxes}


def _restore_pool_spill_page(page, payload):
    inputs = payload.get("inputs", {}) or {}

    for name in _POOL_SPILL_COMBOS:
        widget = getattr(page, name, None)
        if widget is not None and name in inputs:
            found_index = widget.findText(str(inputs[name]))
            if found_index >= 0:
                widget.setCurrentIndex(found_index)

    for name in _POOL_SPILL_LINE_EDITS:
        widget = getattr(page, name, None)
        if widget is not None and name in inputs:
            widget.setText(str(inputs[name]))

    checkboxes = payload.get("checkboxes", {}) or {}
    for name in _POOL_SPILL_CHECKBOXES:
        widget = getattr(page, name, None)
        if widget is not None and name in checkboxes:
            widget.setChecked(bool(checkboxes[name]))


# ---------------------------------------------------------------------------
# ReceptorHeatFluxPage
# ---------------------------------------------------------------------------
_RECEPTOR_LINE_EDITS = ["emissive_power", "perpendicular_distance"]


def _collect_receptor_heat_flux_page(page):
    return {
        name: getattr(page, name).text()
        for name in _RECEPTOR_LINE_EDITS
        if hasattr(page, name)
    }


def _restore_receptor_heat_flux_page(page, payload):
    for name in _RECEPTOR_LINE_EDITS:
        widget = getattr(page, name, None)
        if widget is not None and name in (payload or {}):
            widget.setText(str(payload[name]))


# ---------------------------------------------------------------------------
# Collect / restore the whole application state
# ---------------------------------------------------------------------------
def collect_program_state(base_window):
    """Build a JSON-serialisable dict describing the entire program state."""
    pages = getattr(base_window, "page", {}) or {}

    payload = {
        "format": FORMAT_ID,
        "version": SAVE_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "options": {
            "selected_calc_method": getattr(base_window, "selected_calc_method", None),
            "use_le_chatelier_lfl": getattr(base_window, "use_le_chatelier_lfl", None),
            "use_temp_dependent_lfl": getattr(base_window, "use_temp_dependent_lfl", None),
            "selected_target_flam_gas": getattr(base_window, "selected_target_flam_gas", None),
        },
        "gas_flowrate_data": _encode(getattr(base_window, "gas_flowrate_data", None)),
    }

    lib_page = pages.get("LIBPage")
    if lib_page is not None:
        payload["lib_page"] = _collect_lib_page(lib_page)

    sprinkler_page = pages.get("SprinklerPage")
    if sprinkler_page is not None:
        payload["sprinkler_page"] = _collect_sprinkler_page(sprinkler_page)

    pool_spill_page = pages.get("PoolSpillPage")
    if pool_spill_page is not None:
        payload["pool_spill_page"] = _collect_pool_spill_page(pool_spill_page)

    receptor_page = pages.get("ReceptorHeatFluxPage")
    if receptor_page is not None:
        payload["receptor_heat_flux_page"] = _collect_receptor_heat_flux_page(receptor_page)

    return payload


def restore_program_state(base_window, payload):
    """Apply a payload produced by :func:`collect_program_state` onto a live
    ``BaseWindow`` instance, restoring every page's inputs, options and
    calculated results."""
    pages = getattr(base_window, "page", {}) or {}

    options = payload.get("options", {}) or {}
    for attr in (
        "selected_calc_method",
        "use_le_chatelier_lfl",
        "use_temp_dependent_lfl",
        "selected_target_flam_gas",
    ):
        if options.get(attr) is not None:
            setattr(base_window, attr, options[attr])

    base_window.gas_flowrate_data = _decode(payload.get("gas_flowrate_data"))

    lib_page = pages.get("LIBPage")
    if lib_page is not None and "lib_page" in payload:
        _restore_lib_page(lib_page, payload["lib_page"])

    sprinkler_page = pages.get("SprinklerPage")
    if sprinkler_page is not None and "sprinkler_page" in payload:
        _restore_sprinkler_page(sprinkler_page, payload["sprinkler_page"])

    pool_spill_page = pages.get("PoolSpillPage")
    if pool_spill_page is not None and "pool_spill_page" in payload:
        _restore_pool_spill_page(pool_spill_page, payload["pool_spill_page"])

    receptor_page = pages.get("ReceptorHeatFluxPage")
    if receptor_page is not None and "receptor_heat_flux_page" in payload:
        _restore_receptor_heat_flux_page(receptor_page, payload["receptor_heat_flux_page"])


# ---------------------------------------------------------------------------
# Public entry points (wired to the File menu in main.py)
# ---------------------------------------------------------------------------
def save_program_state(base_window, file_path=None, parent=None):
    """Prompt for a location (unless ``file_path`` is given) and write the
    current session - every page's inputs, options and calculated results -
    to a ``.libsave`` file. Returns ``True`` on success."""
    parent = parent or base_window

    if file_path is None:
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            parent, "Save Session", "", FILE_DIALOG_FILTER
        )
        if not file_path:
            return False

    if not os.path.splitext(file_path)[1]:
        file_path += DEFAULT_EXTENSION

    try:
        payload = collect_program_state(base_window)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=_json_default)
    except Exception as exc:
        QMessageBox.critical(parent, "Save Error", f"Failed to save session:\n{exc}")
        return False

    QMessageBox.information(
        parent, "Save Session", f"Session saved successfully to:\n{os.path.basename(file_path)}"
    )
    return True


def load_program_state(base_window, file_path=None, parent=None):
    """Prompt for a save file (unless ``file_path`` is given) and restore the
    full session from it. Returns ``True`` on success."""
    parent = parent or base_window

    if file_path is None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            parent, "Open Save File", "", FILE_OPEN_FILTER
        )
        if not file_path:
            return False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        QMessageBox.critical(parent, "Open Error", f"Failed to read file:\n{exc}")
        return False

    if not isinstance(payload, dict) or payload.get("format") != FORMAT_ID:
        reply = QMessageBox.question(
            parent,
            "Unrecognized File",
            "This file does not look like a LIB Offgas save file.\nTry to load it anyway?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return False

    try:
        restore_program_state(base_window, payload)
    except Exception as exc:
        QMessageBox.critical(parent, "Load Error", f"Failed to load session:\n{exc}")
        return False

    QMessageBox.information(parent, "Open Save File", "Session loaded successfully.")
    return True

