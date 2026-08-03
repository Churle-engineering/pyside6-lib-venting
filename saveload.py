"""
saveload.py

Save and restore the complete state of the LIB Off-gassing Modelling Tool
to/from a single session file so users can close the program and later pick
up exactly where they left off.

Chosen file format: JSON (stored with a ``.libsave`` extension).

Why JSON rather than CSV?
    A CSV can only represent a single flat table. The program's state is a rich,
    nested structure: hierarchical scenario tree data, text-box inputs,
    dropdown selections, and calculated results that contain whole pandas
    DataFrames and numpy arrays (used to redraw the results plots). JSON
    captures all of this in one human-readable, self-describing file.

What gets saved:
    * ``LIBPage``      - the full project/type/scenario hierarchy from the
                          scenario tree and toxicity/flammability calculation
                          results (including the DataFrames used to draw the
                          result plots).
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
        * Scenario rows are stored as independent dictionaries, so adding/removing
            optional input fields in future versions will not corrupt older save files.

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
)

FORMAT_ID = "lib_offgas_save"
SAVE_VERSION = 2
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
# LIBPage - scenario tree + shared calculation results
# ---------------------------------------------------------------------------
def _resolve_tree_item_classes(scenario_tree_widget):
    """Return (ProjectTreeItem, ScenarioTypeTreeItem, ScenarioTreeItem) classes.

    Classes are resolved from the bound method globals to avoid importing
    ``main.py`` and creating a circular dependency.
    """
    globals_map = getattr(getattr(scenario_tree_widget, "_add_project", None), "__globals__", {}) or {}
    return (
        globals_map.get("ProjectTreeItem"),
        globals_map.get("ScenarioTypeTreeItem"),
        globals_map.get("ScenarioTreeItem"),
    )


def _collect_scenario_tree(scenario_tree_widget):
    """Capture the full Project -> Type -> Scenario hierarchy."""
    tree = getattr(scenario_tree_widget, "tree", None)
    if tree is None:
        return {"projects": []}

    projects = []
    root = tree.invisibleRootItem()
    for i in range(root.childCount()):
        project_item = root.child(i)
        project_payload = {
            "name": getattr(project_item, "project_name", project_item.text(0).strip()),
            "expanded": bool(project_item.isExpanded()),
            "types": [],
        }

        for j in range(project_item.childCount()):
            type_item = project_item.child(j)
            type_payload = {
                "name": getattr(type_item, "type_name", type_item.text(0).strip()),
                "expanded": bool(type_item.isExpanded()),
                "scenarios": [],
            }

            for k in range(type_item.childCount()):
                scenario_item = type_item.child(k)
                type_payload["scenarios"].append(
                    {
                        "name": getattr(scenario_item, "scenario_name", scenario_item.text(0).strip()),
                        "expanded": bool(scenario_item.isExpanded()),
                        "data": _encode(getattr(scenario_item, "scenario_data", {}) or {}),
                    }
                )

            project_payload["types"].append(type_payload)

        projects.append(project_payload)

    return {"projects": projects}


def _restore_scenario_tree(scenario_tree_widget, payload):
    """Rebuild scenario tree hierarchy from payload."""
    tree = getattr(scenario_tree_widget, "tree", None)
    if tree is None:
        return

    projects = (payload or {}).get("projects", []) or []
    if not projects:
        return

    project_cls, type_cls, scenario_cls = _resolve_tree_item_classes(scenario_tree_widget)
    if project_cls is None or type_cls is None or scenario_cls is None:
        raise RuntimeError("Scenario tree item classes are unavailable; cannot restore scenario hierarchy.")

    tree.clear()
    for project_payload in projects:
        project_name = str(project_payload.get("name", "My Project") or "My Project")
        project_item = project_cls(project_name)
        tree.addTopLevelItem(project_item)

        for type_payload in (project_payload.get("types", []) or []):
            type_name = str(type_payload.get("name", "New Type") or "New Type")
            type_item = type_cls(type_name)
            project_item.addChild(type_item)

            for scenario_payload in (type_payload.get("scenarios", []) or []):
                scenario_name = str(scenario_payload.get("name", "New Scenario") or "New Scenario")
                scenario_data = _decode(scenario_payload.get("data", {}) or {})
                if not isinstance(scenario_data, dict):
                    scenario_data = {}
                scenario_item = scenario_cls(scenario_name, data=scenario_data)
                type_item.addChild(scenario_item)
                scenario_item.setExpanded(bool(scenario_payload.get("expanded", False)))

            type_item.setExpanded(bool(type_payload.get("expanded", True)))

        project_item.setExpanded(bool(project_payload.get("expanded", True)))


def _collect_lib_page(lib_page):
    base_window = getattr(lib_page, "base_window", None)
    active_result_type = None
    if isinstance(getattr(base_window, "flam_scenario_results", None), dict) and base_window.flam_scenario_results:
        active_result_type = "flam"
    elif isinstance(getattr(base_window, "tox_scenario_results", None), dict) and base_window.tox_scenario_results:
        active_result_type = "tox"

    return {
        "scenario_tree": _collect_scenario_tree(getattr(lib_page, "scenario_tree", None)),
        "results": {
            "tox_scenario_results": _encode(getattr(base_window, "tox_scenario_results", {}) or {}),
            "flam_scenario_results": _encode(getattr(base_window, "flam_scenario_results", {}) or {}),
            "active_result_type": active_result_type,
            "active_results_tab_index": getattr(getattr(lib_page, "results_tabs", None), "currentIndex", lambda: 0)(),
        },
    }


def _restore_lib_page(lib_page, payload):
    scenario_tree_payload = (payload or {}).get("scenario_tree", {}) or {}
    _restore_scenario_tree(getattr(lib_page, "scenario_tree", None), scenario_tree_payload)

    base_window = getattr(lib_page, "base_window", None)
    results_payload = (payload or {}).get("results", {}) or {}
    if base_window is not None:
        tox_results = _decode(results_payload.get("tox_scenario_results", {}))
        if isinstance(tox_results, dict):
            base_window.tox_scenario_results = tox_results

        flam_results = _decode(results_payload.get("flam_scenario_results", {}))
        if isinstance(flam_results, dict):
            base_window.flam_scenario_results = flam_results

    active_result_type = results_payload.get("active_result_type")
    if not active_result_type:
        if getattr(base_window, "flam_scenario_results", None):
            active_result_type = "flam"
        elif getattr(base_window, "tox_scenario_results", None):
            active_result_type = "tox"

    if active_result_type in {"flam", "tox"} and hasattr(lib_page, "_update_results_display"):
        lib_page._update_results_display(active_result_type)
        desired_index = int(results_payload.get("active_results_tab_index", 0) or 0)
        if hasattr(lib_page, "results_tabs") and 0 <= desired_index < lib_page.results_tabs.count():
            lib_page.results_tabs.setCurrentIndex(desired_index)


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
        "custom_lib_definitions": _encode(getattr(base_window, "custom_lib_definitions", {}) or {}),
        "custom_composition_definitions": _encode(getattr(base_window, "custom_composition_definitions", {}) or {}),
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
    restored_custom_libs = _decode(payload.get("custom_lib_definitions", {}))
    if isinstance(restored_custom_libs, dict):
        base_window.custom_lib_definitions = restored_custom_libs

    restored_compositions = _decode(payload.get("custom_composition_definitions", {}))
    if isinstance(restored_compositions, dict):
        base_window.custom_composition_definitions = restored_compositions

    lib_page = pages.get("LIBPage")
    if lib_page is not None and "lib_page" in payload:
        _restore_lib_page(lib_page, payload["lib_page"])
    if lib_page is not None and hasattr(lib_page, "sync_custom_lib_registry"):
        lib_page.sync_custom_lib_registry()

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

