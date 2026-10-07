"""
saveload.py

Save and restore the complete state of the LIB Off-gassing Modelling Tool
to/from a single session file so users can close the program and later pick
up exactly where they left off.

Chosen file format: JSON (stored with a ``.libsave`` extension).

Why JSON rather than CSV?
    A CSV can only represent a single flat table. The program's state is a rich,
    nested structure: hierarchical scenario tree data, text-box inputs,
    dropdown selections, and calculated results containing numpy arrays
    (used to redraw the results plots). JSON
    captures all of this in one human-readable, self-describing file.

What gets saved:
    * Libraries      - custom LIB (battery) definitions, gas compositions and
                       imported flowrate profiles held on ``BaseWindow``.
    * ``LIBPage``    - the full group/scenario study tree, every scenario's
                       ``LIBInputs`` and every stored ``ScenarioResult``
                       (including the arrays used to redraw the result plots).
    * Every page     - all ``QLineEdit`` / ``QComboBox`` / ``QCheckBox`` values
                       found on the page, captured generically so pages added
                       later (sprinkler, pool spill, receptor heat flux, ...)
                       are saved without touching this module.
    * Calculator outputs, LIB plot visibility/tab selections and tree selection.
    * The active theme and page (window geometry remains a user preference).

Forwards / backwards compatibility:
    * The payload is a versioned dictionary of top-level, independent sections.
    * Every section is optional on load and dataclass fields the running build no
      longer has are dropped, so opening an older save in a newer build (or
      vice-versa) can retain the fields that build understands. Input-only saves
      open with empty results; saved results are not recalculated on load.

Note on coupling:
    This module intentionally avoids importing anything from ``main.py`` (that
    would create a circular import, since ``main.py`` imports the two public
    entry points below). Instead it accesses pages/widgets duck-typed, via
    ``getattr``/``hasattr``, so it keeps working even if a given page hasn't
    been created yet. The Qt-specific study-tree rebuild lives on ``LIBPage``
    itself (``tree_snapshot`` / ``restore_tree``).
"""

import json
import math
import os
import tempfile
from dataclasses import fields, is_dataclass
from datetime import datetime

import numpy as np

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QMessageBox,
)

from information import CHEMICAL_PROPERTIES, FlowrateProfile, GasComposition, LIBInputs, LIBSpec
from scenario_model import GasResults, Scenario, ScenarioResult

FORMAT_ID = "lib_offgas_save"
SAVE_VERSION = 5
DEFAULT_EXTENSION = ".libsave"
FILE_SAVE_FILTER = "LIB Offgas Save (*.libsave);;JSON files (*.json);;All files (*.*)"
FILE_OPEN_FILTER = "LIB Offgas Save (*.libsave *.json);;All files (*.*)"

# A dataclass must be listed here to be written out, so a new one cannot silently
# be dropped from a save file.
_DATACLASS_TYPES = {
    cls.__name__: cls
    for cls in (LIBInputs, LIBSpec, GasComposition, FlowrateProfile,
                Scenario, ScenarioResult, GasResults)
}

# Per-run/session-only dataclass fields that are never written to a save file.
# Summaries are derived from the saved raw results. Bound library objects are
# re-bound by name; ScenarioResult battery, composition and flowrate snapshots are saved.
_TRANSIENT_FIELDS = {
    "Scenario": {"summary", "lib_spec", "gas_composition", "flowrate_profile"},
}


# ---------------------------------------------------------------------------
# Generic encode / decode helpers (dataclasses and numpy arrays - which hold the
# calculated curves used to redraw the result plots - to/from plain JSON types).
# ---------------------------------------------------------------------------

def _encode(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return {"__ndarray__": obj.tolist(), "dtype": str(obj.dtype), "shape": list(obj.shape)}
    if is_dataclass(obj) and not isinstance(obj, type):
        name = type(obj).__name__
        if name not in _DATACLASS_TYPES:
            raise TypeError(f"Cannot save unregistered dataclass {name!r}")
        skip = _TRANSIENT_FIELDS.get(name, ())
        return {
            "__dataclass__": name,
            "fields": {f.name: _encode(getattr(obj, f.name)) for f in fields(obj)
                       if f.name not in skip},
        }
    if isinstance(obj, dict):
        if all(isinstance(key, str) for key in obj):
            return {"__dict__": {key: _encode(value) for key, value in obj.items()}}
        return {"__items__": [[_encode(key), _encode(value)] for key, value in obj.items()]}
    if isinstance(obj, (list, tuple, set)):
        return [_encode(value) for value in obj]
    raise TypeError(f"Cannot save value of type {type(obj).__name__}")


def _decode(obj):
    if isinstance(obj, list):
        return [_decode(value) for value in obj]
    if not isinstance(obj, dict):
        return obj
    if "__ndarray__" in obj:
        array = np.array(obj["__ndarray__"], dtype=obj.get("dtype") or None)
        shape = obj.get("shape")
        return array.reshape(shape) if shape is not None else array
    if "__dataclass__" in obj:
        cls = _DATACLASS_TYPES.get(obj["__dataclass__"])
        if cls is None:
            raise ValueError(f"Unknown saved type {obj['__dataclass__']!r}")
        # Fields the running build no longer has are dropped, so older saves still load.
        names = {f.name for f in fields(cls)} - _TRANSIENT_FIELDS.get(cls.__name__, set())
        values = {k: _decode(v) for k, v in (obj.get("fields") or {}).items() if k in names}
        return cls(**values)
    if "__dict__" in obj:
        return {key: _decode(value) for key, value in obj["__dict__"].items()}
    if "__items__" in obj:
        return {_decode(key): _decode(value) for key, value in obj["__items__"]}
    return obj


# ---------------------------------------------------------------------------
# Widget capture / restore - generic, so pages added later are covered with no
# changes here.
# ---------------------------------------------------------------------------

def _capture_widgets(page):
    state = {}
    for name, widget in vars(page).items():
        if isinstance(widget, QLineEdit):
            state[name] = widget.text()
        elif isinstance(widget, QComboBox):
            state[name] = widget.currentText()
        elif isinstance(widget, QCheckBox):
            state[name] = widget.isChecked()
    return state


def _restore_widgets(page, state):
    for name, value in (state or {}).items():
        widget = getattr(page, name, None)
        if isinstance(widget, QLineEdit):
            widget.setText("" if value is None else str(value))
        elif isinstance(widget, QComboBox):
            index = widget.findText("" if value is None else str(value))
            if index >= 0:
                widget.setCurrentIndex(index)
            elif widget.isEditable():
                widget.setEditText("" if value is None else str(value))
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))


# ---------------------------------------------------------------------------
# Whole-program state
# ---------------------------------------------------------------------------

def collect_state(base_window, theme_name=None):
    """Build the JSON-ready payload describing the whole program state."""
    pages = getattr(base_window, "page", {}) or {}

    page_state = {}
    for name, page in pages.items():
        entry: dict[str, object] = {"widgets": _capture_widgets(page)}
        if hasattr(page, "tree_snapshot"):
            entry["study_tree"] = _encode(page.tree_snapshot())
        if hasattr(page, "session_snapshot"):
            entry["session"] = _encode(page.session_snapshot())
        page_state[name] = entry

    return {
        "format": FORMAT_ID,
        "version": SAVE_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "theme": theme_name,
        "active_page": next(
            (name for name, page in pages.items()
             if page is base_window.current_page()), None
        ),
        "libraries": {
            "lib_definitions": _encode(getattr(base_window, "custom_lib_definitions", {})),
            "compositions": _encode(getattr(base_window, "custom_composition_definitions", {})),
            "flowrate_profiles": _encode(getattr(base_window, "custom_flowrate_profiles", {})),
        },
        "pages": page_state,
    }


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def _result_array(array, shape):
    if (not isinstance(array, np.ndarray) or array.shape != shape
            or array.dtype.kind not in "biuf"):
        raise ValueError("Saved result arrays must be numeric and match their axes.")


def _validate_tree(groups):
    if not isinstance(groups, list):
        raise ValueError("Study tree must be a list.")
    node_ids = set()
    for group in groups:
        _mapping(group, "Study group")
        if not isinstance(group.get("name", ""), str):
            raise ValueError("Study group name must be text.")
        scenarios = group.get("scenarios", [])
        if not isinstance(scenarios, list):
            raise ValueError("Study scenarios must be a list.")
        for scenario in scenarios:
            if not isinstance(scenario, Scenario) or not isinstance(scenario.inputs, LIBInputs):
                raise ValueError("Study scenarios must contain Scenario and LIBInputs records.")
            if (type(scenario.node_id) is not int or scenario.node_id <= 0
                    or scenario.node_id in node_ids):
                raise ValueError("Scenario IDs must be unique positive integers.")
            node_ids.add(scenario.node_id)
            result = scenario.result
            if result is None:
                continue
            if not isinstance(result, ScenarioResult) or not isinstance(result.inputs, LIBInputs):
                raise ValueError("Invalid saved scenario result.")
            if result.lib_spec is not None and not isinstance(result.lib_spec, LIBSpec):
                raise ValueError("Invalid saved result battery snapshot.")
            if result.flowrate_profile is not None and not isinstance(result.flowrate_profile, FlowrateProfile):
                raise ValueError("Invalid saved result flowrate snapshot.")
            if not isinstance(result.time, np.ndarray) or result.time.ndim != 1 or not result.time.size:
                raise ValueError("Saved result time must be a non-empty array.")
            _result_array(result.time, result.time.shape)
            if result.lfl_percent is not None and (
                type(result.lfl_percent) not in (int, float) or not math.isfinite(result.lfl_percent)
            ):
                raise ValueError("Saved result LFL must be a finite number.")
            for array in (result.flowrate, result.total_gas_m3, result.total_gas_vv):
                _result_array(array, result.time.shape)
            for array in (result.active_cells, result.active_modules):
                if not isinstance(array, np.ndarray):
                    raise ValueError("Saved active counts must be arrays.")
                _result_array(array, (0,) if array.size == 0 else result.time.shape)
            for gases in (result.flammable, result.toxic):
                if not isinstance(gases, GasResults) or not isinstance(gases.labels, list):
                    raise ValueError("Invalid saved species results.")
                if any(label not in CHEMICAL_PROPERTIES for label in gases.labels):
                    raise ValueError("Saved results contain an unknown gas species.")
                shape = (len(gases.labels), len(result.time))
                for name in ("volume_m3", "conc_vv"):
                    array = getattr(gases, name)
                    # Older saves can use the empty GasResults default.
                    if isinstance(array, np.ndarray) and not gases.labels and array.shape == (0, 0):
                        array = np.zeros(shape)
                        setattr(gases, name, array)
                    _result_array(array, shape)
                _result_array(gases.densities, (len(gases.labels),))


def _validate_session(session):
    if "results_text" in session and not isinstance(session["results_text"], str):
        raise ValueError("Saved calculator output must be text.")
    activation = session.get("activation_time_s")
    if activation is not None and (
        type(activation) not in (int, float) or not math.isfinite(activation) or activation < 0
    ):
        raise ValueError("Saved sprinkler activation time must be a finite non-negative number.")
    for name in ("selected_node_id", "active_result"):
        if session.get(name) is not None and type(session[name]) is not int:
            raise ValueError(f"{name} must be a scenario ID.")
    if session.get("selected_group") is not None and not isinstance(session["selected_group"], str):
        raise ValueError("Selected group must be text.")
    expanded = _mapping(session.get("expanded_groups", {}), "Expanded groups")
    if any(type(value) is not bool for value in expanded.values()):
        raise ValueError("Group expansion values must be booleans.")
    plots = session.get("plots", [])
    if not isinstance(plots, list):
        raise ValueError("Saved plot settings must be a list.")
    for plot in plots:
        _mapping(plot, "Plot settings")
        if type(plot.get("node_id")) is not int or type(plot.get("active_tab", 0)) is not int:
            raise ValueError("Plot settings must specify integer scenario and tab IDs.")
        checkboxes = plot.get("checkboxes", [])
        if not isinstance(checkboxes, list):
            raise ValueError("Saved plot checkboxes must be a list.")
        for tab in checkboxes:
            _mapping(tab, "Plot checkboxes")
            if any(type(value) is not bool for value in tab.values()):
                raise ValueError("Plot checkbox values must be booleans.")


def apply_state(base_window, state):
    """Restore a payload produced by `collect_state`.

    Returns the theme name stored in the file (or None) so the caller can apply it.
    Libraries are restored before the pages so scenarios rebind to their battery,
    composition and flowrate definitions by name.
    """
    _mapping(state, "Session")
    if state.get("active_page") is not None and not isinstance(state["active_page"], str):
        raise ValueError("Active page must be a page name.")
    libraries = _mapping(state.get("libraries", {}), "Libraries")
    decoded_libraries = {}
    for name, cls in (("lib_definitions", LIBSpec), ("compositions", GasComposition),
                      ("flowrate_profiles", FlowrateProfile)):
        definitions = _mapping(_decode(libraries.get(name, {})), name)
        if any(not isinstance(key, str) or not isinstance(value, cls)
               for key, value in definitions.items()):
            raise ValueError(f"Invalid records in {name}.")
        decoded_libraries[name] = definitions

    # Decode and check every section before replacing any live inputs or libraries.
    decoded_pages = {}
    for name, entry in _mapping(state.get("pages", {}), "Pages").items():
        _mapping(entry, f"Page {name}")
        widgets = _mapping(entry.get("widgets", {}), f"Widgets for {name}")
        if any(value is not None and not isinstance(value, (str, int, float, bool))
               for value in widgets.values()):
            raise ValueError(f"Invalid widget values for {name}.")
        session = _mapping(_decode(entry.get("session", {})), f"Session for {name}")
        _validate_session(session)
        if "study_tree" in entry:
            groups = _decode(entry["study_tree"])
            _validate_tree(groups)
        else:
            groups = None
        decoded_pages[name] = (widgets, groups, session)

    base_window.custom_lib_definitions = decoded_libraries["lib_definitions"]
    base_window.custom_composition_definitions = decoded_libraries["compositions"]
    base_window.custom_flowrate_profiles = decoded_libraries["flowrate_profiles"]
    pages = getattr(base_window, "page", {}) or {}
    for name, (widgets, groups, session) in decoded_pages.items():
        page = pages.get(name)
        if page is None:
            continue
        _restore_widgets(page, widgets)
        if groups is not None and hasattr(page, "restore_tree"):
            page.restore_tree(groups)
        if hasattr(page, "restore_session"):
            page.restore_session(session)

    base_window.page_history.clear()
    base_window._copied_scenario = None
    active_page = state.get("active_page")
    if active_page in pages:
        base_window.show_page(active_page, remember_current=False)

    return state.get("theme")


# ---------------------------------------------------------------------------
# Public entry points (used by the File menu)
# ---------------------------------------------------------------------------

def save_program_state(base_window, theme_name=None, path=None):
    """Write the whole program state to a JSON session file. Returns the path used."""
    if not path:
        path, _ = QFileDialog.getSaveFileName(
            base_window, "Save Session", "session" + DEFAULT_EXTENSION, FILE_SAVE_FILTER
        )
        if not path:
            return None

    temporary_path = None
    try:
        payload = collect_state(base_window, theme_name)
        directory = os.path.dirname(os.path.abspath(path))
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False
        ) as handle:
            temporary_path = handle.name
            json.dump(payload, handle, indent=2)
        os.replace(temporary_path, path)
        temporary_path = None
    except (OSError, TypeError, ValueError) as exc:
        QMessageBox.critical(base_window, "Save Failed", f"Could not save the session:\n{exc}")
        return None
    finally:
        if temporary_path is not None:
            os.unlink(temporary_path)

    base_window.current_save_path = path
    return path


def load_program_state(base_window, path=None):
    """Read a session file and restore it. Returns (path, theme_name), or (None, None)."""
    if not path:
        path, _ = QFileDialog.getOpenFileName(base_window, "Open Session", "", FILE_OPEN_FILTER)
        if not path:
            return None, None

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or payload.get("format") != FORMAT_ID:
            raise ValueError("This file is not a LIB Off-gassing session file.")
        theme_name = apply_state(base_window, payload)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        QMessageBox.critical(base_window, "Open Failed", f"Could not open the session:\n{exc}")
        return None, None

    base_window.current_save_path = path
    return path, theme_name
