"""Shared physical-input validation for LIB dialogs and the calculation engine.

Zero ventilation, zero propagation delays and a zero cell duration are supported.
Release checks are method-specific: unused release fields do not block a run.
Validators return all applicable errors; engine entry points raise ValueError so
invalid scenarios use the existing skipped-scenario notification path.
"""

import math
from numbers import Real

from information import (
    CALCULATION_METHODS,
    CALC_METHOD_CELL_VOLUME_UL9540A,
    CALC_METHOD_MODULE_CAPACITY,
    CALC_METHOD_MODULE_VOLUME_UL9540A,
    LIBInputs,
    LIBSpec,
    MAX_CALC_DURATION_S,
)


def number_problems(value: object, label: str, *, positive: bool = False,
                    integer: bool = False, maximum: float | None = None) -> list[str]:
    """Check a finite numeric value without coercing strings, booleans or counts."""
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        return [f"{label} must be a finite number."]
    if integer and value % 1 != 0:
        return [f"{label} must be a whole number."]
    if value < 0 or (positive and value == 0):
        return [f"{label} must be {'greater than zero' if positive else 'zero or greater'}."]
    if maximum is not None and value > maximum:
        return [f"{label} must not exceed {maximum:g}."]
    return []


def require_valid(problems: list[str]) -> None:
    if problems:
        raise ValueError("\n".join(problems))


def input_problems(inputs: LIBInputs) -> list[str]:
    """Validate room geometry, ventilation, system counts and simulation timing."""
    problems = []
    for field_name in ("room_height", "room_area"):
        label = LIBInputs.__dataclass_fields__[field_name].metadata["label"]
        problems.extend(number_problems(getattr(inputs, field_name), label, positive=True))
    occupancy = number_problems(inputs.equip_space, "Equipment Space", maximum=100)
    if not occupancy and inputs.equip_space == 100:
        occupancy.append("Equipment Space must be less than 100%.")
    problems.extend(occupancy)
    if not problems:
        problems.extend(number_problems(inputs.room_volume(), "Free Room Volume", positive=True))

    for field_name in ("ventilation_rate", "emergency_vent_rate", "vent_switch_conc",
                       "emergency_vent_delay"):
        label = LIBInputs.__dataclass_fields__[field_name].metadata["label"]
        problems.extend(number_problems(getattr(inputs, field_name), label))
    if not problems:
        for rate in (inputs.ventilation_rate, inputs.emergency_vent_rate):
            problems.extend(number_problems(rate / 1000 * inputs.room_area,
                                            "Room Ventilation Flowrate"))
    for field_name in ("cells_per_module", "modules_per_unit", "units"):
        label = LIBInputs.__dataclass_fields__[field_name].metadata["label"]
        problems.extend(number_problems(getattr(inputs, field_name), label,
                                        positive=True, integer=True))
    problems.extend(number_problems(inputs.calc_duration, "Calculation Duration",
                                    positive=True, maximum=MAX_CALC_DURATION_S))
    if inputs.calc_method not in CALCULATION_METHODS:
        problems.append(f"Unsupported calculation method {inputs.calc_method!r}.")
    return problems


def release_problems(inputs: LIBInputs, spec: LIBSpec) -> list[str]:
    """Validate only battery parameters used by the selected release method."""
    problems = []
    checks = [("mod_prop_delay", False, False), ("mod_prop_number", True, True)]
    if inputs.calc_method == CALC_METHOD_CELL_VOLUME_UL9540A:
        checks.extend([
            ("cell_volume", True, False), ("cell_duration", False, False),
            ("cell_prop_delay", False, False), ("cell_prop_number", True, True),
        ])
    elif inputs.calc_method == CALC_METHOD_MODULE_VOLUME_UL9540A:
        checks.extend([("module_volume", True, False), ("module_duration", True, False)])
    elif inputs.calc_method == CALC_METHOD_MODULE_CAPACITY:
        checks.extend([("module_capacity", True, False), ("module_duration", True, False)])
    for field_name, positive, integer in checks:
        label = LIBSpec.__dataclass_fields__[field_name].metadata["label"]
        problems.extend(number_problems(getattr(spec, field_name), label,
                                        positive=positive, integer=integer))
    return problems


def lfl_input_problems(inputs: LIBInputs, spec: LIBSpec) -> list[str]:
    problems = []
    if not inputs.use_le_chatelier_lfl:
        problems.extend(number_problems(spec.lfl, "LFL", positive=True, maximum=100))
    if inputs.use_temp_dependent_lfl:
        temperature = spec.venting_temperature
        if (isinstance(temperature, bool) or not isinstance(temperature, Real)
                or not math.isfinite(temperature) or temperature <= -273.15):
            problems.append("Venting Temperature must be finite and above -273.15 C.")
    return problems
