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
    * Libraries      - custom LIB (battery) definitions, gas compositions and
                       imported flowrate profiles held on ``BaseWindow``.
    * ``LIBPage``    - the full group/scenario study tree, every scenario's
                       ``LIBInputs`` and every stored ``ScenarioResult``
                       (including the arrays used to redraw the result plots).
    * Every page     - all ``QLineEdit`` / ``QComboBox`` / ``QCheckBox`` values
                       found on the page, captured generically so pages added
                       later (sprinkler, pool spill, receptor heat flux, ...)
                       are saved without touching this module.
    * The active theme.

Forwards / backwards compatibility:
    * The payload is a versioned dictionary of top-level, independent sections.
    * Every section is optional on load and dataclass fields the running build no
      longer has are dropped, so opening an older save in a newer build (or
      vice-versa) will not crash.

Note on coupling:
    This module intentionally avoids importing anything from ``main.py`` (that
    would create a circular import, since ``main.py`` imports the two public
    entry points below). Instead it accesses pages/widgets duck-typed, via
    ``getattr``/``hasattr``, so it keeps working even if a given page hasn't
    been created yet. The Qt-specific study-tree rebuild lives on ``LIBPage``
    itself (``tree_snapshot`` / ``restore_tree``).
"""

import json
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

from information import FlowrateProfile, GasComposition, LIBInputs, LIBSpec
from scenario_model import GasResults, Scenario, ScenarioResult

FORMAT_ID = "lib_offgas_save"
SAVE_VERSION = 4
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
# Scenario results and summaries are cheap to recompute (press Run), and the bound
# battery/composition/flowrate objects are re-bound by name from the libraries
# section on load, so persisting any of them would only bloat and duplicate.
_TRANSIENT_FIELDS = {
    "Scenario": {"result", "summary", "lib_spec", "gas_composition", "flowrate_profile"},
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
        names = {f.name for f in fields(cls)}
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
        entry = {"widgets": _capture_widgets(page)}
        if hasattr(page, "tree_snapshot"):
            entry["study_tree"] = _encode(page.tree_snapshot())
        page_state[name] = entry

    return {
        "format": FORMAT_ID,
        "version": SAVE_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "theme": theme_name,
        "libraries": {
            "lib_definitions": _encode(getattr(base_window, "custom_lib_definitions", {})),
            "compositions": _encode(getattr(base_window, "custom_composition_definitions", {})),
            "flowrate_profiles": _encode(getattr(base_window, "custom_flowrate_profiles", {})),
        },
        "pages": page_state,
    }


def apply_state(base_window, state):
    """Restore a payload produced by `collect_state`.

    Returns the theme name stored in the file (or None) so the caller can apply it.
    Libraries are restored before the pages so scenarios rebind to their battery,
    composition and flowrate definitions by name.
    """
    libraries = state.get("libraries") or {}
    base_window.custom_lib_definitions = _decode(libraries.get("lib_definitions")) or {}
    base_window.custom_composition_definitions = _decode(libraries.get("compositions")) or {}
    base_window.custom_flowrate_profiles = _decode(libraries.get("flowrate_profiles")) or {}

    pages = getattr(base_window, "page", {}) or {}
    for name, entry in (state.get("pages") or {}).items():
        page = pages.get(name)
        if page is None:
            continue
        _restore_widgets(page, entry.get("widgets"))
        if "study_tree" in entry and hasattr(page, "restore_tree"):
            page.restore_tree(_decode(entry["study_tree"]))

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

    try:
        payload = collect_state(base_window, theme_name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except (OSError, TypeError, ValueError) as exc:
        QMessageBox.critical(base_window, "Save Failed", f"Could not save the session:\n{exc}")
        return None

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
