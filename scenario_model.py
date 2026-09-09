"""Scenario and result object model shared by the LIBPage UI and the calculation modules.

Three dataclass layers, each with one job:

1. ``LIBInputs`` (information.py) - one GUI-editable record per scenario. Its field
   metadata drives dataclass_forms, and its field values are fed straight into the
   calculations, so there is no second hand-maintained input schema to keep in sync.
2. ``Scenario`` - binds a ``LIBInputs`` to its identity in the study tree and to the
   results produced from it. The tree stores only ``node_id``; ``ScenarioStore`` owns
   the objects.
3. ``ScenarioResult`` / ``GasResults`` - the numeric output of one calculation run.
   These hold numpy arrays rather than DataFrames because the calculations produce
   arrays and the plots consume arrays; DataFrames are built on demand for export.
"""

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from information import FlowrateProfile, GasComposition, LIBInputs, LIBSpec


def _empty_2d():
    return np.zeros((0, 0), dtype=float)


def _empty_1d():
    return np.zeros(0, dtype=float)


@dataclass(slots=True)
class GasResults:
    """Per-species arrays for one subset of the release (flammable or toxic).

    ``volume_m3`` and ``conc_vv`` are shaped ``(n_species, n_steps)`` and share the
    parent ``ScenarioResult`` time axis, so a species is addressed by its row index
    in ``labels``. Concentrations are stored in v/v% only; mg/L is derived on demand
    from ``densities`` so the two can never drift apart.
    """

    labels: list = field(default_factory=list)
    volume_m3: np.ndarray = field(default_factory=_empty_2d)
    conc_vv: np.ndarray = field(default_factory=_empty_2d)
    densities: np.ndarray = field(default_factory=_empty_1d)

    def __len__(self):
        return len(self.labels)

    def conc_mgl(self):
        """Concentrations in mg/L, derived from v/v% and each species' density (g/L)."""
        if not self.labels:
            return _empty_2d()
        return (self.conc_vv / 100.0) * self.densities[:, None] * 1000.0

    def total_vv(self):
        """Summed concentration across every species at each time step."""
        if not self.labels:
            return np.zeros(self.conc_vv.shape[-1], dtype=float)
        return self.conc_vv.sum(axis=0)


@dataclass(slots=True)
class ScenarioResult:
    """The raw arrays one calculation run produced for one scenario.

    Everything derived from these (peaks, % of LFL, summary lines, plot curves) lives
    in ``venting_calculation.ResultSummary``, computed once per run and stored on the
    scenario alongside this object. ``inputs`` and ``lib_spec`` are deep-copied
    snapshots of what the run actually used, so a stored result stays interpretable
    (and exportable) even after the user edits the scenario or battery afterwards.
    """

    scenario_name: str
    calc_method: str
    inputs: LIBInputs
    time: np.ndarray
    flowrate: np.ndarray
    total_gas_m3: np.ndarray
    total_gas_vv: np.ndarray
    flammable: GasResults = field(default_factory=GasResults)
    toxic: GasResults = field(default_factory=GasResults)
    active_cells: np.ndarray = field(default_factory=_empty_1d)
    active_modules: np.ndarray = field(default_factory=_empty_1d)
    lfl_percent: Optional[float] = None
    lfl_label: str = "LFL"
    lib_spec: Optional[LIBSpec] = None


@dataclass(slots=True)
class Scenario:
    """One study-tree scenario: its inputs, and the result calculated from them.

    ``result`` and ``summary`` are the outcome of the scenario's most recent run - a
    scenario has exactly one of each, produced by its own ``inputs.calc_method``, or
    None if it has not been run this session (or its last run failed). Neither is
    saved to session files: results are cheap to recompute, so Run is the only source
    of them. ``gas_composition`` is the named ``GasComposition`` the user picked in the
    scenario dialog (``LIBInputs.gas_composition`` stores only its name). ``lib_spec``
    is the named ``LIBSpec`` picked the same way (``LIBInputs.lib_spec`` stores only
    its name), and ``flowrate_profile`` the named ``FlowrateProfile``
    (``LIBInputs.flowrate_profile``).
    """

    node_id: int
    inputs: LIBInputs
    group: str = ""
    gas_composition: Optional[GasComposition] = None
    lib_spec: Optional[LIBSpec] = None
    flowrate_profile: Optional[FlowrateProfile] = None
    result: Optional[ScenarioResult] = None
    summary: Optional[object] = None   # venting_calculation.ResultSummary

    @property
    def name(self):
        return self.inputs.scenario_description


@dataclass
class ScenarioStore:
    """Owns every ``Scenario`` on a page - and the group structure they sit in.

    The study tree (a QTreeWidget) is pure presentation, rebuilt from this store after
    every structural change, so group names/order live in exactly one place and the
    calculation modules can iterate scenarios without any knowledge of Qt.
    ``group_names`` preserves display order and keeps empty groups alive.
    """

    scenarios: dict = field(default_factory=dict)
    group_names: list = field(default_factory=list)
    _counter: int = 0

    def __iter__(self):
        return iter(self.scenarios.values())

    def __len__(self):
        return len(self.scenarios)

    def add(self, inputs, group=""):
        self._counter += 1
        scenario = Scenario(node_id=self._counter, inputs=inputs, group=group)
        self.scenarios[scenario.node_id] = scenario
        if group:
            self.add_group(group)
        return scenario

    def get(self, node_id):
        return self.scenarios.get(node_id)

    def remove(self, node_id):
        return self.scenarios.pop(node_id, None)

    def update_inputs(self, node_id, inputs):
        scenario = self.scenarios.get(node_id)
        if scenario is not None:
            scenario.inputs = inputs
        return scenario

    # -- groups --------------------------------------------------------------

    def add_group(self, name):
        if name and name not in self.group_names:
            self.group_names.append(name)
        return name

    def rename_group(self, old_name, new_name):
        if new_name in self.group_names and new_name != old_name:
            return False   # collapse of two groups must be an explicit user action
        self.group_names = [new_name if g == old_name else g for g in self.group_names]
        for scenario in self.scenarios.values():
            if scenario.group == old_name:
                scenario.group = new_name
        return True

    def remove_group(self, name):
        """Drop a group and every scenario in it; returns the removed node ids."""
        removed = [nid for nid, s in self.scenarios.items() if s.group == name]
        for nid in removed:
            self.scenarios.pop(nid, None)
        self.group_names = [g for g in self.group_names if g != name]
        return removed

    def groups(self):
        """Ordered {group_name: [Scenario, ...]} covering every scenario.

        Groups appear in ``group_names`` order; a scenario whose group is not listed
        (e.g. from an older save) gets its group appended rather than lost.
        """
        for scenario in self.scenarios.values():
            if scenario.group and scenario.group not in self.group_names:
                self.group_names.append(scenario.group)
        ordered = {name: [] for name in self.group_names}
        for scenario in self.scenarios.values():
            ordered.setdefault(scenario.group or "", []).append(scenario)
        return ordered

    def scenarios_in_display_order(self):
        """Every scenario, group by group, in display order."""
        return [s for members in self.groups().values() for s in members]

    # -- results -------------------------------------------------------------

    def store_result(self, node_id, result, summary=None):
        """Attach a ``ScenarioResult`` (and its ``ResultSummary``) to its scenario."""
        scenario = self.scenarios.get(node_id)
        if scenario is not None:
            scenario.result = result
            scenario.summary = summary

    def results(self):
        """{node_id: ScenarioResult} for every scenario that has been run."""
        return {s.node_id: s.result for s in self.scenarios.values() if s.result is not None}

    def clear_results(self):
        for scenario in self.scenarios.values():
            scenario.result = None
            scenario.summary = None
