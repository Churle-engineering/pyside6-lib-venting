"""The single calculation engine behind the LIB Run button.

Every calculation method runs through the same pipeline (`run_venting_assessment`):

    1. resolve_composition   - {species: fraction of total off-gas} for the scenario
    2. build_module_release  - HOW one module releases its gas (the ONLY step that
                               differs between calculation methods - see table below)
    3. system_propagation    - staggered module-to-module initiation turns one module's
                               release into the whole system's flowrate signal
    4. resolve_lfl           - the assessment LFL (user-entered or Le Chatelier mixture,
                               optionally temperature adjusted)
    5. room_gas_balance      - perfectly-mixed room integration of every species
    6. ScenarioResult        - stored on the Scenario (`scenario.result`), consumed by
                               the summary strip, plot tabs and PDF export

Calculation method -> release model -> parameters used:

    Cell Volume UL9540A       CellByCellModuleRelease
                                cells inside a module initiate in staggered cohorts
                                (1 cell at t=0, then spec.cell_prop_number more every
                                spec.cell_prop_delay s, up to inputs.cells_per_module);
                                each cell releases spec.cell_volume litres - at a flat
                                rate over spec.cell_duration s, or along the empirical
                                rise/decay curve when spec.cell_duration is 0.
    Module Volume UL9540A     FlatModuleRelease
                                one module releases spec.module_volume litres at a
                                constant rate over spec.module_duration s.
    Module Capacity           FlatModuleRelease
                                volume = chemistry specific_capacity (L/kWh, keyed by
                                spec.cell_format) * spec.module_capacity (kWh), released
                                at a constant rate over spec.module_duration s.
    Module Variable Flowrate  MeasuredModuleRelease
                                one module replays the scenario's imported
                                FlowrateProfile dataset (which defines both the
                                flowrate and the release duration).

Module-to-module staggering is identical for every method: 1 module initiates at t=0,
then spec.mod_prop_number more every spec.mod_prop_delay seconds, until
inputs.modules_per_unit * inputs.units modules have started.
"""
from dataclasses import dataclass
import copy

import numpy as np
from scipy.signal import lfilter
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QMessageBox, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from scenario_model import GasResults, ScenarioResult
from information import (
    BATTERY_CHEMISTRY_DATA,
    CHEMICAL_PROPERTIES,
    CALC_METHOD_CELL_VOLUME_UL9540A,
    CALC_METHOD_MODULE_VOLUME_UL9540A,
    CALC_METHOD_MODULE_CAPACITY,
    CALC_METHOD_MODULE_VARIABLE_FLOWRATE,
)


# ---------------------------------------------------------------------------
# Single-cell release (used by the Cell Volume UL9540A method)
# ---------------------------------------------------------------------------

def _cell_curve_params(volume_l):
    """Derive one cell's curve shape parameters (h, tp, m1, tau, te) from its volume."""
    # -- define curve gradient conditions based on empirical venting data
    t_eps = 0.0001  # decay tail is cut off at this fraction of the peak flow
    t_tau = 4.0
    m1 = 1.6
    # -- -- -- -- -- - - -- - - - --- -- ---

    area = volume_l / 1000.0  # L -> m3, i.e. area under the flowrate(m3/s)-time(s) curve
    if area <= 0:
        raise ValueError("cell_vent_profile: volume must be positive")

    # peak flowrate forced by the area constraint (area = h^2/(2*m1) + h*tau)
    h = np.sqrt(m1**2 * t_tau**2 + 2 * m1 * area) - m1 * t_tau
    tp = h / m1
    te = tp + t_tau * np.log(1.0 / t_eps)
    return h, tp, m1, t_tau, te


@dataclass(slots=True)
class CellRelease:
    """One cell's release against its own local time, in m3/s.

    `curve` is empty for a flat release (a measured cell duration was entered) and holds
    the `_cell_curve_params` tuple when the shape is derived from the cell volume alone.
    """

    volume_m3: float
    duration: float
    curve: tuple = ()

    @property
    def is_flat(self):
        return not self.curve

    def cumulative_volume(self, t):
        """Exact volume (m3) this cell releases from its own t=0 up to local time t."""
        t = np.asarray(t, dtype=np.float64)
        if self.is_flat:
            return (self.volume_m3 / self.duration) * np.clip(t, 0.0, self.duration)

        h, tp, m1, tau, te = self.curve
        rise_volume = 0.5 * m1 * np.clip(t, 0.0, tp) ** 2
        decay_span = np.clip(t, tp, te) - tp
        return rise_volume + h * tau * (1.0 - np.exp(-decay_span / tau))

    def profile(self):
        """Sampled (time, flowrate) for one cell's release."""
        if self.is_flat:
            rate = self.volume_m3 / self.duration
            return np.array([0.0, self.duration]), np.array([rate, rate])

        h, tp, m1, tau, te = self.curve
        # tp is sampled exactly so the peak is never interpolated away when the rise is
        # much shorter than the decay
        time = np.unique(np.concatenate([np.linspace(0.0, tp, 50), np.linspace(tp, te, 100)]))
        return time, np.where(time <= tp, m1 * time, h * np.exp(-(time - tp) / tau))


def cell_vent_profile(volume_l, duration=0.0):
    """Build a single cell's vent flowrate profile.

    A non-zero `duration` releases `volume_l` at a flat flowrate over that many seconds;
    a zero duration falls back to the volume-derived linear rise then exponential decay.
    `volume_l` is the total gas volume the cell releases, in litres, so the resulting
    flowrate is in m3/s and integrates back to that volume.
    """
    if volume_l <= 0:
        raise ValueError("cell_vent_profile: volume must be positive")
    if duration > 0:
        return CellRelease(volume_m3=volume_l / 1000.0, duration=float(duration))

    params = _cell_curve_params(volume_l)
    return CellRelease(volume_m3=volume_l / 1000.0, duration=float(params[-1]), curve=params)


# ---------------------------------------------------------------------------
# Cohort scheduling (shared by cell-within-module and module-within-system staggering)
# ---------------------------------------------------------------------------

def _cohort_schedule(total_count, batch_size, interval, first_batch=None):
    """Return [(start_time_s, count), ...] initiation waves.

    The first wave holds `first_batch` items (defaults to `batch_size`) and starts at
    t=0; every later wave adds `batch_size` more items `interval` seconds after the
    previous one, until `total_count` items have started.
    """
    total_count = int(total_count)
    if total_count <= 0:
        return []

    batch_size = max(1, int(batch_size))
    first_size = batch_size if first_batch is None else max(1, int(first_batch))

    cohorts = []
    remaining = total_count
    wave = 0
    while remaining > 0:
        size = min(first_size if wave == 0 else batch_size, remaining)
        cohorts.append((wave * float(interval), size))
        remaining -= size
        wave += 1
    return cohorts


def _sum_cohort_active_count(time_array, cohorts, unit_duration):
    """Sum cohort counts still within their unit_duration window at each time."""
    total = np.zeros(len(time_array), dtype=np.float64)
    for start, count in cohorts:
        if count <= 0:
            continue
        local = time_array - start
        mask = (local >= 0) & (local <= unit_duration)
        total[mask] += count
    return total


# ---------------------------------------------------------------------------
# Module release models - one per calculation method (see the module docstring).
# Each exposes the same interface consumed by `system_propagation`:
#   duration            - seconds one module takes to finish releasing
#   volume_l            - total litres one module releases (diagnostic)
#   cumulative_volume(t) - exact m3 released by one module up to local time t
#   active_cells(t)     - cells releasing within one module at each local time
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CellByCellModuleRelease:
    """Cell Volume UL9540A: cells inside the module initiate in staggered cohorts."""

    cell_release: CellRelease
    cell_cohorts: list   # [(local_start_time_s, cell_count), ...] within one module

    @property
    def duration(self):
        return self.cell_cohorts[-1][0] + self.cell_release.duration

    @property
    def volume_l(self):
        cells = sum(count for _, count in self.cell_cohorts)
        return cells * self.cell_release.volume_m3 * 1000.0

    def cumulative_volume(self, t):
        t = np.asarray(t, dtype=np.float64)
        total = np.zeros(t.shape, dtype=np.float64)
        for start, count in self.cell_cohorts:
            if count > 0:
                total += count * self.cell_release.cumulative_volume(t - start)
        return total

    def active_cells(self, t):
        return _sum_cohort_active_count(t, self.cell_cohorts, self.cell_release.duration)


@dataclass(slots=True)
class FlatModuleRelease:
    """Module Volume UL9540A / Module Capacity: one constant rate for the whole module."""

    volume_m3: float
    duration: float
    cells_per_module: float   # all cells release together, only used for the diagnostic count

    @property
    def volume_l(self):
        return self.volume_m3 * 1000.0

    def cumulative_volume(self, t):
        t = np.asarray(t, dtype=np.float64)
        return (self.volume_m3 / self.duration) * np.clip(t, 0.0, self.duration)

    def active_cells(self, t):
        active = (t >= 0) & (t <= self.duration)
        return self.cells_per_module * active.astype(np.float64)


@dataclass(slots=True)
class MeasuredModuleRelease:
    """Module Variable Flowrate: one module replays an imported flowrate dataset.

    ``cumulative_m3`` is the trapezoidal integral of the dataset's flowrate up to each of
    its own sample times, so `cumulative_volume` can interpolate released volume directly
    instead of re-integrating a sampled flowrate on the simulation grid.
    """

    time: np.ndarray            # dataset sample times (s), rebased to start at 0
    flowrate: np.ndarray        # m3/s at each sample time
    cumulative_m3: np.ndarray   # volume released up to each sample time
    cells_per_module: float     # all cells release together, only used for the diagnostic count

    @property
    def duration(self):
        return float(self.time[-1])

    @property
    def volume_l(self):
        return float(self.cumulative_m3[-1]) * 1000.0

    def cumulative_volume(self, t):
        """Clamped at both ends: nothing before the dataset starts, and the module holds
        its total once the dataset has run out."""
        t = np.asarray(t, dtype=np.float64)
        return np.interp(t, self.time, self.cumulative_m3, left=0.0, right=float(self.cumulative_m3[-1]))

    def active_cells(self, t):
        active = (t >= 0) & (t <= self.duration)
        return self.cells_per_module * active.astype(np.float64)


def _build_measured_release(profile, cells_per_module):
    """Validate a `FlowrateProfile` dataset and turn it into a `MeasuredModuleRelease`."""
    if profile is None:
        raise ValueError(
            "the 'Module Variable Flowrate' method needs a flowrate dataset; "
            "select one in the scenario's 'Flowrate Dataset' field"
        )

    time = np.asarray(profile.time_s, dtype=np.float64)
    flowrate = np.asarray(profile.flowrate_lps, dtype=np.float64)
    if time.size != flowrate.size:
        raise ValueError(
            f"flowrate dataset '{profile.name}' has {time.size} times but "
            f"{flowrate.size} flowrates"
        )
    if time.size < 2:
        raise ValueError(f"flowrate dataset '{profile.name}' needs at least two samples")
    if not np.all(np.isfinite(time)) or not np.all(np.isfinite(flowrate)):
        raise ValueError(f"flowrate dataset '{profile.name}' contains non-numeric samples")

    order = np.argsort(time)
    time = time[order] - time[order][0]
    flowrate = np.clip(flowrate[order], 0.0, None) / 1000.0  # l/s -> m3/s
    if time[-1] <= 0:
        raise ValueError(f"flowrate dataset '{profile.name}' has no duration")

    steps = np.diff(time)
    cumulative = np.concatenate([[0.0], np.cumsum(0.5 * steps * (flowrate[1:] + flowrate[:-1]))])
    if cumulative[-1] <= 0:
        raise ValueError(f"flowrate dataset '{profile.name}' releases no gas")

    return MeasuredModuleRelease(time=time, flowrate=flowrate, cumulative_m3=cumulative,
                                 cells_per_module=cells_per_module)


def build_module_release(scenario):
    """Resolve a scenario's `inputs.calc_method` into one module's release model.

    This is the ONLY place the calculation methods differ - everything upstream
    (composition, LFL) and downstream (module staggering, room balance) is shared.
    Raises ValueError with a user-facing message when the method's inputs are unusable.
    """
    inputs = scenario.inputs
    spec = scenario.lib_spec
    method = inputs.calc_method

    if method == CALC_METHOD_CELL_VOLUME_UL9540A:
        cell_release = cell_vent_profile(spec.cell_volume, spec.cell_duration)
        cell_cohorts = _cohort_schedule(inputs.cells_per_module, spec.cell_prop_number,
                                        spec.cell_prop_delay, first_batch=1)
        if not cell_cohorts:
            raise ValueError("'Cells per Module' must be at least 1 for the Cell Volume method")
        return CellByCellModuleRelease(cell_release=cell_release, cell_cohorts=cell_cohorts)

    if method == CALC_METHOD_MODULE_VOLUME_UL9540A:
        volume_l, duration = spec.module_volume, spec.module_duration
    elif method == CALC_METHOD_MODULE_CAPACITY:
        chemistry = BATTERY_CHEMISTRY_DATA[spec.lib_type.upper()]
        volume_l = chemistry['specific_capacity'][spec.cell_format] * spec.module_capacity
        duration = spec.module_duration
    elif method == CALC_METHOD_MODULE_VARIABLE_FLOWRATE:
        return _build_measured_release(scenario.flowrate_profile, inputs.cells_per_module)
    else:
        raise ValueError(f"unsupported calculation method {method!r}")

    if volume_l <= 0 or duration <= 0:
        raise ValueError(
            f"'{method}' needs a positive release volume and duration "
            f"(got {volume_l} l over {duration} s)"
        )
    return FlatModuleRelease(volume_m3=volume_l / 1000.0, duration=float(duration),
                             cells_per_module=inputs.cells_per_module)


# ---------------------------------------------------------------------------
# System propagation - module-to-module staggering, shared by every method
# ---------------------------------------------------------------------------

def _system_cumulative_volume(t_array, module_cohorts, release):
    """Exact total volume (m3) released by every module up to each system time.

    Differencing this at t-dt and t gives an exact, mass-conserving average flowrate for
    that step - a point-sampled instantaneous flowrate would undersample any release
    feature faster than the simulation's time step.

    For the cell-by-cell model the module and cell cohort schedules are pre-merged into
    one flat {system_offset: cell_count} table, so each unique start offset costs one
    curve evaluation instead of module_cohorts x cell_cohorts evaluations (regular
    delays make many offsets coincide).
    """
    if isinstance(release, CellByCellModuleRelease):
        merged = {}
        for m_start, m_count in module_cohorts:
            if m_count <= 0:
                continue
            for c_start, c_count in release.cell_cohorts:
                if c_count <= 0:
                    continue
                offset = m_start + c_start
                merged[offset] = merged.get(offset, 0.0) + m_count * c_count
        total = np.zeros(len(t_array), dtype=np.float64)
        for offset, count in merged.items():
            total += count * release.cell_release.cumulative_volume(t_array - offset)
        return total

    total = np.zeros(len(t_array), dtype=np.float64)
    for start, count in module_cohorts:
        if count <= 0:
            continue
        total += count * release.cumulative_volume(t_array - start)
    return total


@dataclass(slots=True)
class PropagationResult:
    """Time-resolved whole-system release profile for one scenario."""

    time: np.ndarray
    total_flowrate: np.ndarray        # m3/s, summed across every releasing module
    active_cell_count: np.ndarray     # cells currently releasing, summed across all modules
    active_module_count: np.ndarray   # modules still within their release window
    module_cohorts: list              # [(start_time_s, module_count), ...]
    release: object                   # the per-module release model that drove this run


def system_propagation(inputs, spec, release, time_array=None):
    """Turn one module's release model into the whole system's flowrate signal.

    One module initiates at t=0, then `spec.mod_prop_number` more join every
    `spec.mod_prop_delay` seconds until every module
    (`inputs.modules_per_unit * inputs.units`) has started; each replays `release`
    from its own start time.
    """
    total_modules = inputs.total_modules()
    if total_modules <= 0:
        raise ValueError("the scenario has no modules ('Modules per Unit' x 'Units' is 0)")

    dt = inputs.effective_time_step()
    if time_array is None:
        time_array = np.arange(0, inputs.calc_duration + dt, dt)
    time_array = np.asarray(time_array, dtype=np.float64)

    module_cohorts = _cohort_schedule(total_modules, spec.mod_prop_number, spec.mod_prop_delay,
                                      first_batch=1)

    # Exact, mass-conserving average flowrate per step (see _system_cumulative_volume),
    # using the backward-looking window [t-dt, t] so total_flowrate[n] is the release
    # that brings the system up to time_array[n] - a forward window [t, t+dt] would
    # report each sample one dt later than its label (e.g. a nonzero release at t=0
    # before anything has started). Both cumulative ends are evaluated in one
    # concatenated call to halve the cohort-loop overhead versus two separate calls.
    combined_times = np.concatenate([time_array - dt, time_array])
    combined_cumulative = _system_cumulative_volume(combined_times, module_cohorts, release)
    cumulative_start, cumulative_end = np.split(combined_cumulative, 2)
    total_flowrate = (cumulative_end - cumulative_start) / dt

    # active counts are instantaneous snapshots (not integrals), so a direct presence
    # check at each queried time is already exact regardless of grid spacing
    active_module_count = _sum_cohort_active_count(time_array, module_cohorts, release.duration)
    active_cell_count = np.zeros(len(time_array), dtype=np.float64)
    for m_start, m_count in module_cohorts:
        if m_count > 0:
            active_cell_count += m_count * release.active_cells(time_array - m_start)

    return PropagationResult(
        time=time_array,
        total_flowrate=total_flowrate,
        active_cell_count=active_cell_count,
        active_module_count=active_module_count,
        module_cohorts=module_cohorts,
        release=release,
    )


# ---------------------------------------------------------------------------
# Composition resolution
# ---------------------------------------------------------------------------

def resolve_composition(scenario):
    """Return {species: fraction of total off-gas} for one scenario.

    ``User Defined`` uses the scenario's own ``GasComposition``; anything else falls
    back to the literature composition for the battery's chemistry. Fractions are
    normalised so they sum to 1, and species with no CHEMICAL_PROPERTIES entry are
    dropped (no density/LFL data means nothing downstream can use them).
    """
    inputs = scenario.inputs

    if inputs.composition_method == "User Defined" and scenario.gas_composition is not None:
        percentages = scenario.gas_composition.percentages
    else:
        chemistry = BATTERY_CHEMISTRY_DATA[scenario.lib_spec.lib_type.upper()]
        percentages = chemistry['composition']

    raw = {}
    for species, percent in percentages.items():
        if species not in CHEMICAL_PROPERTIES or percent <= 0:
            continue
        raw[species] = raw.get(species, 0.0) + float(percent)

    total = sum(raw.values())
    if total <= 0:
        raise ValueError("resolve_composition: composition has no usable species")
    return {species: value / total for species, value in raw.items()}


def split_species(species):
    """Split the resolved species list into (flammable, toxic) sub-lists."""
    flammable = [s for s in species if CHEMICAL_PROPERTIES[s].get('flammability_factor')]
    toxic = [s for s in species
             if CHEMICAL_PROPERTIES[s].get('toxicity_factor')
             and CHEMICAL_PROPERTIES[s].get('erpg_3') is not None]
    return flammable, toxic


# ---------------------------------------------------------------------------
# LFL resolution
# ---------------------------------------------------------------------------

def le_chatelier_lfl(fractions):
    """Mixture LFL (v/v%) from one fixed composition {species: fraction}.

    Fractions are renormalised onto the flammable species subset only, then
    combined with Le Chatelier's equation. Returns None when no flammable
    species with an LFL are present.
    """
    usable = [(species, fraction) for species, fraction in fractions.items()
              if fraction > 0 and CHEMICAL_PROPERTIES[species].get('lfl')]
    total = sum(fraction for _, fraction in usable)
    if total <= 0:
        return None

    denominator = sum(
        (fraction / total) / CHEMICAL_PROPERTIES[species]['lfl']
        for species, fraction in usable
    )
    return 1.0 / denominator if denominator > 0 else None


def temperature_adjusted_lfl(base_lfl, temperature_c):
    """Placeholder temperature correction: scale an LFL by a single temporary factor.

    Kept deliberately trivial until the real temperature relationship is specified;
    every caller goes through here so only this body needs replacing later.
    """
    if base_lfl is None:
        return None
    temporary_factor = 1.0
    return base_lfl * temporary_factor


def resolve_lfl(inputs, spec, fractions):
    """Pick one scenario-level assessment LFL (v/v%) and a display label.

    Le Chatelier (when enabled) is calculated once from the scenario's resolved
    composition fractions; otherwise the battery's entered LFL is used, and it must
    have been entered (> 0) - there is deliberately no built-in default, so a
    forgotten value fails loudly instead of silently steering the assessment.
    Temperature adjustment is then applied to the single selected value.
    """
    if inputs.use_le_chatelier_lfl:
        lfl = le_chatelier_lfl(fractions)
        label = "Le Chatelier LFL"
    else:
        if spec.lfl is None or spec.lfl <= 0:
            raise ValueError(
                f"battery '{spec.name}' has no LFL entered; set a positive LFL in the "
                "battery definition or enable 'Use Le Chatelier LFL' on the scenario"
            )
        lfl = spec.lfl
        label = "LFL"

    if inputs.use_temp_dependent_lfl:
        lfl = temperature_adjusted_lfl(lfl, spec.venting_temperature)
        label = f"Temperature-adjusted {label}"

    return lfl, label


# ---------------------------------------------------------------------------
# Room gas balance
# ---------------------------------------------------------------------------

def _step_coefficients(extract_rate, room_volume, dt):
    """(retained, inflow_factor) of the exact one-step solution of
    dV/dt = inflow - (extract_rate/room_volume)*V, so a large Q*dt/V_room can never
    extract more gas than the room actually holds."""
    decay_rate = extract_rate / room_volume
    if decay_rate <= 0:
        return 1.0, dt
    return np.exp(-decay_rate * dt), -np.expm1(-decay_rate * dt) / decay_rate


def room_gas_balance(inputs, time, release_flowrate, fractions):
    """Integrate every species' volume in the room over the whole time array.

    Perfect mixing: the extract carries the room's own composition, so each species is
    removed in proportion to its share of the room pool. Because every species shares
    the same extraction rate, only ONE unsplit pool is integrated over time; each
    species' volume is exactly its composition fraction times that pool (the per-step
    recurrence preserves proportionality), which removes the whole per-species
    dimension from the time loop.

    Ventilation: the standard rate applies until the room's CO concentration reaches
    `inputs.vent_switch_conc` percent of CO's own LFL, then the emergency rate applies
    (not latched - the standard rate resumes if CO falls back below the trigger).
    Both rates are entered in L/s per m2 of room floor area.

    Returns (species, volume_m3, conc_vv) where the two arrays are shaped
    (n_species, n_steps).
    """
    species = list(fractions)
    fraction_arr = np.array([fractions[s] for s in species], dtype=np.float64)
    room_volume = inputs.room_volume()
    dt = inputs.effective_time_step()

    base_rate = (inputs.ventilation_rate / 1000.0) * inputs.room_area
    emergency_rate = max(base_rate, (inputs.emergency_vent_rate / 1000.0) * inputs.room_area)
    co_fraction = fractions.get('co', 0.0)
    trigger_enabled = (inputs.vent_switch_conc > 0 and co_fraction > 0
                       and emergency_rate > base_rate)

    pool = np.zeros(len(time), dtype=np.float64)   # unsplit total gas volume (m3)
    base_retained, base_inflow_factor = _step_coefficients(base_rate, room_volume, dt)

    if not trigger_enabled:
        # constant extraction: the per-step recurrence pool[n] = r*pool[n-1] + g*q[n]
        # is a linear filter, solved for the whole array in one vectorized pass
        inflow = np.asarray(release_flowrate, dtype=np.float64).copy()
        inflow[0] = 0.0
        pool = lfilter([base_inflow_factor], [1.0, -base_retained], inflow)
    else:
        # the emergency-vent switch re-evaluates every step (not latched), so the rate
        # depends on the evolving CO concentration - but only the scalar unsplit pool
        # is stepped; both candidate step coefficients are precomputed
        emergency_retained, emergency_inflow_factor = _step_coefficients(
            emergency_rate, room_volume, dt)
        trigger = CHEMICAL_PROPERTIES['co']['lfl'] * inputs.vent_switch_conc / 100.0
        current = 0.0
        for step in range(1, len(time)):
            co_conc = co_fraction * (current / room_volume) * 100.0
            if co_conc >= trigger:
                retained, inflow_factor = emergency_retained, emergency_inflow_factor
            else:
                retained, inflow_factor = base_retained, base_inflow_factor
            current = current * retained + release_flowrate[step] * inflow_factor
            pool[step] = current

    volume_m3 = fraction_arr[:, None] * pool[None, :]
    conc_vv = (volume_m3 / room_volume) * 100.0
    return species, volume_m3, conc_vv


def _gas_results(species, subset, volume_m3, conc_vv):
    """Pack one subset (flammable or toxic) of the solved species into a GasResults."""
    rows = [species.index(s) for s in subset]
    return GasResults(
        labels=list(subset),
        volume_m3=volume_m3[rows],
        conc_vv=conc_vv[rows],
        densities=np.array([CHEMICAL_PROPERTIES[s]['density'] for s in subset], dtype=float),
    )


# ---------------------------------------------------------------------------
# The pipeline - one entry point for every calculation method
# ---------------------------------------------------------------------------

def run_venting_assessment(parent, store, gas_data, node_ids=None):
    """Run every selected scenario through the shared pipeline (see module docstring).

    ``node_ids`` limits the run to those scenarios (None runs the whole store). Each
    scenario's outcome is stored on the scenario itself - ``scenario.result`` (the raw
    arrays) and ``scenario.summary`` (the derived ``ResultSummary`` every display path
    reads) - and the results are also returned as {node_id: ScenarioResult}. A scenario
    that fails validation is skipped and loses any previously stored result, so a stale
    result can never be mistaken for the outcome of this run; every skip reason is
    collected and reported in ONE message box after the run instead of one popup per
    scenario.
    """
    results = {}
    problems = []

    for scenario in store:
        if node_ids is not None and scenario.node_id not in node_ids:
            continue
        scenario.result = None
        scenario.summary = None

        inputs = scenario.inputs
        if scenario.lib_spec is None:
            problems.append(f"{scenario.name}: no battery definition is assigned to this scenario.")
            continue

        try:
            fractions = resolve_composition(scenario)
            release = build_module_release(scenario)
            prop = system_propagation(inputs, scenario.lib_spec, release)
            assessment_lfl, lfl_label = resolve_lfl(inputs, scenario.lib_spec, fractions)
        except (KeyError, ValueError) as exc:
            problems.append(f"{scenario.name}: {exc}")
            continue

        species, volume_m3, conc_vv = room_gas_balance(
            inputs, prop.time, prop.total_flowrate, fractions
        )
        flammable, toxic = split_species(species)

        total_gas_m3 = volume_m3.sum(axis=0)

        result = ScenarioResult(
            scenario_name=scenario.name,
            calc_method=inputs.calc_method,
            inputs=copy.deepcopy(inputs),
            time=prop.time,
            flowrate=prop.total_flowrate,
            total_gas_m3=total_gas_m3,
            total_gas_vv=(total_gas_m3 / inputs.room_volume()) * 100.0,
            flammable=_gas_results(species, flammable, volume_m3, conc_vv),
            toxic=_gas_results(species, toxic, volume_m3, conc_vv),
            active_cells=prop.active_cell_count,
            active_modules=prop.active_module_count,
            lfl_percent=assessment_lfl,
            lfl_label=lfl_label,
            lib_spec=copy.deepcopy(scenario.lib_spec),
        )

        scenario.result = result
        scenario.summary = summarize_result(result, gas_data)
        results[scenario.node_id] = result

    if problems:
        QMessageBox.warning(
            parent, "Run - Skipped Scenarios",
            "The following scenarios were skipped:\n\n" + "\n\n".join(problems),
        )

    return results


# ---------------------------------------------------------------------------
# Result processing
# ---------------------------------------------------------------------------

def _to_mgl(conc_vv, density):
    """v/v% -> mg/L for one species (density in g/L, numerically identical to kg/m3)."""
    return (conc_vv / 100.0) * density * 1000.0


def _to_ppm(conc_vv):
    return conc_vv * 10000.0


@dataclass(slots=True)
class SpeciesSummary:
    """One species' concentration curve plus its peak figures for the result table."""

    species: str
    conc_vv: np.ndarray
    conc_ppm: np.ndarray
    peak_vv: float
    peak_mgl: float
    peak_ppm: float
    peak_time: float
    erpg_3: float = None
    percent_of_erpg_3: float = None


@dataclass(slots=True)
class ResultSummary:
    """Everything derived from one run: summary-strip lines, plot curves and
    result-table figures. Computed once per run (`summarize_result`) and stored on the
    scenario, so the summary strip, plot tabs and PDF export all read the same object."""

    scenario_name: str
    calc_method: str
    time: np.ndarray
    flammable_total_vv: np.ndarray     # summed flammable concentration at each step
    flammable_total_mgl: np.ndarray
    lfl_curve: np.ndarray              # per-step LFL used for the % of LFL comparison
    percent_of_lfl_curve: np.ndarray
    lfl_percent: float                 # the scalar assessment LFL (None when unresolved)
    lfl_label: str
    lfl_crossing_time: float           # first time total flammable exceeds it (None = never)
    peak_flammable_vv: float
    peak_flammable_mgl: float
    peak_flammable_ppm: float
    peak_flammable_time: float
    peak_percent_of_lfl: float
    flammable_species: list            # [SpeciesSummary, ...]
    toxic_species: list                # [SpeciesSummary, ...]

    def summary_lines(self):
        """Short human-readable lines for the LIBPage summary strip."""
        lines = [
            f"{self.scenario_name} ({self.calc_method})",
            f"Peak flammable gas: {self.peak_flammable_vv:.3f} v/v% at t={self.peak_flammable_time:.0f} s",
        ]
        if self.lfl_percent:
            reached = (f"reached at t={self.lfl_crossing_time:.0f} s"
                       if self.lfl_crossing_time is not None else "not reached")
            lines.append(f"{self.lfl_label}: {self.lfl_percent:.3f} v/v% ({reached})")
        for species in self.toxic_species:
            lines.append(f"Peak {species.species}: {species.peak_vv:.4f} v/v% "
                         f"at t={species.peak_time:.0f} s")
        return lines


def _species_summaries(gas_results, time, gas_data, include_erpg=False):
    """Build a SpeciesSummary per species in one GasResults block."""
    summaries = []
    for row, species in enumerate(gas_results.labels):
        properties = gas_data[species]
        conc_vv = gas_results.conc_vv[row]
        conc_ppm = _to_ppm(conc_vv)
        peak_index = int(conc_vv.argmax())
        peak_vv = float(conc_vv[peak_index])
        peak_ppm = _to_ppm(peak_vv)

        erpg_3 = properties.get('erpg_3') if include_erpg else None
        percent_of_erpg_3 = peak_ppm / erpg_3 * 100.0 if erpg_3 else None

        summaries.append(SpeciesSummary(
            species=species,
            conc_vv=conc_vv,
            conc_ppm=conc_ppm,
            peak_vv=peak_vv,
            peak_mgl=_to_mgl(peak_vv, properties['density']),
            peak_ppm=peak_ppm,
            peak_time=float(time[peak_index]),
            erpg_3=erpg_3,
            percent_of_erpg_3=percent_of_erpg_3,
        ))
    return summaries


def summarize_result(result, gas_data):
    """Derive one scenario's `ResultSummary` from its `ScenarioResult`.

    Flammable species are summed at each step into one flammable-gas curve, which is
    compared against that step's LFL to give a % of LFL curve. Toxic species stay
    individual so each can be reported against its own ERPG-3.
    """
    flammable_total_vv = result.flammable.total_vv()
    # mixture mg/L is the sum of each species' own mg/L, not a single density
    flammable_total_mgl = result.flammable.conc_mgl().sum(axis=0)

    # the assessment LFL is a single scalar; the plot curve is just that value repeated
    lfl_value = result.lfl_percent if result.lfl_percent else np.nan
    lfl_curve = np.full(len(result.time), lfl_value, dtype=float)
    percent_of_lfl_curve = np.divide(
        flammable_total_vv * 100.0, lfl_curve,
        out=np.zeros_like(flammable_total_vv), where=lfl_curve > 0,
    )

    lfl_crossing_time = None
    if result.lfl_percent and result.lfl_percent > 0:
        exceed = np.flatnonzero(flammable_total_vv > result.lfl_percent)
        if exceed.size:
            lfl_crossing_time = float(result.time[exceed[0]])

    peak_index = int(flammable_total_vv.argmax()) if flammable_total_vv.size else 0
    peak_flammable_vv = float(flammable_total_vv[peak_index]) if flammable_total_vv.size else 0.0

    return ResultSummary(
        scenario_name=result.scenario_name,
        calc_method=result.calc_method,
        time=result.time,
        flammable_total_vv=flammable_total_vv,
        flammable_total_mgl=flammable_total_mgl,
        lfl_curve=lfl_curve,
        percent_of_lfl_curve=percent_of_lfl_curve,
        lfl_percent=result.lfl_percent,
        lfl_label=result.lfl_label,
        lfl_crossing_time=lfl_crossing_time,
        peak_flammable_vv=peak_flammable_vv,
        peak_flammable_mgl=float(flammable_total_mgl[peak_index]) if flammable_total_mgl.size else 0.0,
        peak_flammable_ppm=_to_ppm(peak_flammable_vv),
        peak_flammable_time=float(result.time[peak_index]),
        peak_percent_of_lfl=float(percent_of_lfl_curve[peak_index]) if percent_of_lfl_curve.size else 0.0,
        flammable_species=_species_summaries(result.flammable, result.time, gas_data),
        toxic_species=_species_summaries(result.toxic, result.time, gas_data, include_erpg=True),
    )


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def _make_plot_tab(x_label, y_label, title):
    """Bare figure/canvas/toolbar/checkbox-row scaffold shared by both gas plot tabs."""
    figure = Figure(figsize=(6, 4))
    axes = figure.add_subplot(111)
    axes.set_xlabel(x_label)
    axes.set_ylabel(y_label)
    axes.set_title(title)
    axes.grid(True, alpha=0.3)

    canvas = FigureCanvasQTAgg(figure)
    toolbar = NavigationToolbar2QT(canvas)

    checkbox_row = QWidget()
    checkbox_layout = QHBoxLayout(checkbox_row)
    checkbox_layout.setContentsMargins(4, 2, 4, 2)

    checkbox_scroll = QScrollArea()
    checkbox_scroll.setWidgetResizable(True)
    checkbox_scroll.setWidget(checkbox_row)
    checkbox_scroll.setMaximumHeight(50)

    tab = QWidget()
    tab_layout = QVBoxLayout(tab)
    tab_layout.addWidget(toolbar)
    tab_layout.addWidget(canvas)
    tab_layout.addWidget(checkbox_scroll)
    return tab, figure, axes, canvas, checkbox_layout


def _add_checkboxes(checkbox_layout, axes, canvas, entries, scale_lines=None):
    """Add one checkbox per ``(label, [line, ...], visible)`` entry."""

    def _rescale_y_axis():
        visible_values = [
            np.asarray(line.get_ydata(), dtype=float)
            for line in (scale_lines or axes.lines) if line.get_visible()
        ]
        finite_values = [values[np.isfinite(values)] for values in visible_values]
        finite_values = [values for values in finite_values if values.size]
        y_max = max((float(values.max()) for values in finite_values), default=0.0)
        axes.set_ylim(0.0, y_max * 1.05 if y_max > 0 else 1.0)

    def _refresh_legend():
        legend = axes.get_legend()
        if legend is not None:
            legend.remove()
        visible_lines = [line for line in axes.lines if line.get_visible()]
        if visible_lines:
            axes.legend(visible_lines, [line.get_label() for line in visible_lines],
                        loc="upper right", fontsize=8)

    def _toggled(checked, lines):
        for line in lines:
            line.set_visible(checked)
        _rescale_y_axis()
        _refresh_legend()
        canvas.draw_idle()

    checkbox_layout.addStretch()
    for label, lines, visible in entries:
        checkbox = QCheckBox(label)
        for line in lines:
            line.set_visible(visible)
        checkbox.setChecked(visible)
        checkbox.toggled.connect(lambda checked, lines=lines: _toggled(checked, lines))
        checkbox_layout.addWidget(checkbox)
    checkbox_layout.addStretch()
    _rescale_y_axis()
    _refresh_legend()


def _species_entry(axes, summary, species_summary, threshold, threshold_label, visible):
    """Plot one species' concentration plus its own threshold line, as a checkbox entry."""
    name = species_summary.species.upper()
    (line,) = axes.plot(summary.time, species_summary.conc_vv, label=name)
    lines = [line]
    if threshold is not None:
        (threshold_line,) = axes.plot(
            [summary.time[0], summary.time[-1]], [threshold, threshold],
            color=line.get_color(), linestyle="--", linewidth=1,
            label=f"{name} {threshold_label}",
        )
        lines.append(threshold_line)
    return name, lines, visible


def _build_flammable_tab(summary):
    tab, figure, axes, canvas, checkbox_layout = _make_plot_tab(
        "Time (s)", "Concentration (v/v %)", f"{summary.scenario_name}: Flammable Gas Concentration",
    )

    entries = []
    (total_line,) = axes.plot(
        summary.time, summary.flammable_total_vv, label="Total Flammable", color="black", linewidth=2,
    )
    entries.append(("Total Flammable", [total_line], True))
    gas_lines = [total_line]

    (assessment_lfl_line,) = axes.plot(
        summary.time, summary.lfl_curve, label="Assessment LFL", color="darkred", linestyle=":", linewidth=1.5,
    )
    entries.append(("Assessment LFL", [assessment_lfl_line], True))

    for species_summary in summary.flammable_species:
        species_entry = _species_entry(
            axes, summary, species_summary,
            CHEMICAL_PROPERTIES[species_summary.species].get("lfl"), "LFL", False,
        )
        entries.append(species_entry)
        gas_lines.append(species_entry[1][0])

    figure.tight_layout()
    _add_checkboxes(checkbox_layout, axes, canvas, entries, scale_lines=gas_lines)
    return tab


def _build_toxic_tab(summary):
    tab, figure, axes, canvas, checkbox_layout = _make_plot_tab(
        "Time (s)", "Concentration (v/v %)", f"{summary.scenario_name}: Toxic Gas Concentration",
    )

    entries = []
    default_visible_species = {"co", "hcl", "hf", "hcn", "benzene"}
    if not summary.toxic_species:
        axes.text(0.5, 0.5, "No toxic species in this scenario's composition.",
                  ha="center", va="center", transform=axes.transAxes)

    for species_summary in summary.toxic_species:
        threshold = species_summary.erpg_3 / 10000.0 if species_summary.erpg_3 is not None else None  # ppm -> v/v%
        entries.append(_species_entry(
            axes, summary, species_summary, threshold, "ERPG-3",
            species_summary.species.lower() in default_visible_species,
        ))

    figure.tight_layout()
    _add_checkboxes(checkbox_layout, axes, canvas, entries)
    return tab


def build_result_plots(summary):
    """Build the flammable/toxic gas plot widget for one scenario's ResultSummary.

    Returns a QTabWidget with a "Flammable Gas" and a "Toxic Gas" tab. Each tab plots
    every individual species concentration over time plus its own threshold curve
    (individual LFL curves for flammables, each species' own ERPG-3 line for toxics).
    The flammable tab initially shows only the total-gas and assessment-LFL curves.
    """
    tabs = QTabWidget()
    tabs.addTab(_build_flammable_tab(summary), "Flammable Gas")
    tabs.addTab(_build_toxic_tab(summary), "Toxic Gas")
    return tabs
