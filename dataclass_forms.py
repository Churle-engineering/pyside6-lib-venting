# Reusable helpers for building/reading Qt forms directly from dataclass fields.
# Dataclasses (e.g. LIBInputs) are the single source of truth for scenario data:
# widget labels/units/tooltips come from each field's `metadata`, and values are
# read back straight into a dataclass instance - there is no separate hand-typed
# UI schema to keep in sync.
from dataclasses import fields

from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLineEdit, QTabWidget, QWidget


def _make_field_widget(f, choices):
    """Create the appropriate widget (QComboBox/QCheckBox/QLineEdit) for one dataclass field."""
    meta = f.metadata or {}
    label_text = meta.get("label", f.name)
    units = meta.get("units")
    if units and units not in ("string", "count", "bool"):
        label_text = f"{label_text} ({units}):"
    else:
        label_text = f"{label_text}:"

    if f.name in choices:
        widget = QComboBox()
        widget.addItems([str(option) for option in choices[f.name]])
    elif f.type is bool:
        widget = QCheckBox()
    else:
        widget = QLineEdit()
        if f.type in (float, int):
            widget.setValidator(QDoubleValidator())

    if meta.get("tooltip"):
        widget.setToolTip(meta["tooltip"])

    return label_text, widget


def build_form(dataclass_type, instance=None, choices=None):
    """Build a QFormLayout from a dataclass type's fields.

    `choices` is an optional {field_name: [options]} map for fields that should be
    rendered as a QComboBox instead of a QLineEdit (e.g. lib_type -> LIB_TYPE).
    Returns (QWidget container, {field_name: widget}).
    """
    choices = choices or {}
    container = QWidget()
    layout = QFormLayout(container)
    layout.setHorizontalSpacing(16)
    layout.setVerticalSpacing(8)

    widgets = {}
    for f in fields(dataclass_type):
        label_text, widget = _make_field_widget(f, choices)
        layout.addRow(label_text, widget)
        widgets[f.name] = widget

    populate_form(instance if instance is not None else dataclass_type(), widgets)
    return container, widgets


def build_tabbed_form(dataclass_type, tab_field_names, instance=None, choices=None):
    """Build a QTabWidget, one tab per (tab_name, [field_names]) group.

    `tab_field_names` is an ordered list of (tab_name, [field_names]) tuples and must
    assign EVERY field of the dataclass to a tab - a new field that has not been
    placed raises immediately, so it cannot silently land on the wrong tab. Returns
    (QTabWidget, {field_name: widget}).
    """
    choices = choices or {}
    field_map = {f.name: f for f in fields(dataclass_type)}

    listed_names = [name for _, names in tab_field_names for name in names]
    unknown = [name for name in listed_names if name not in field_map]
    missing = [name for name in field_map if name not in listed_names]
    if unknown:
        raise ValueError(f"build_tabbed_form: unknown fields listed: {unknown}")
    if missing:
        raise ValueError(
            f"build_tabbed_form: fields of {dataclass_type.__name__} not assigned "
            f"to any tab: {missing}"
        )

    tabs = QTabWidget()
    widgets = {}
    for tab_name, field_names in tab_field_names:
        page = QWidget()
        layout = QFormLayout(page)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(8)

        for name in field_names:
            label_text, widget = _make_field_widget(field_map[name], choices)
            layout.addRow(label_text, widget)
            widgets[name] = widget

        tabs.addTab(page, tab_name)

    populate_form(instance if instance is not None else dataclass_type(), widgets)
    return tabs, widgets


def populate_form(instance, widgets):
    """Set each widget's displayed value from a dataclass instance's fields."""
    for name, widget in widgets.items():
        value = getattr(instance, name)
        if isinstance(widget, QComboBox):
            index = widget.findText(str(value))
            widget.setCurrentIndex(index if index >= 0 else 0)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        else:
            widget.setText(str(value))


def read_form(dataclass_type, widgets):
    """Read widget values back into a new dataclass instance, coercing types.

    Raises ValueError naming the offending field's label if a numeric field can't
    be parsed, so callers can surface it directly to the user.
    """
    values = {}
    for f in fields(dataclass_type):
        widget = widgets[f.name]
        if isinstance(widget, QCheckBox):
            values[f.name] = widget.isChecked()
            continue

        raw = widget.currentText() if isinstance(widget, QComboBox) else widget.text().strip()
        try:
            if f.type is float:
                values[f.name] = float(raw)
            elif f.type is int:
                values[f.name] = int(float(raw))
            else:
                values[f.name] = raw
        except ValueError as exc:
            label = (f.metadata or {}).get("label", f.name)
            raise ValueError(f"{label} must be a valid {f.type.__name__}.") from exc
    return dataclass_type(**values)
