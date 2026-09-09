# aLL DATA TO DRAW FROM IN PROGRAM
# -------- data classes ----------
from dataclasses import dataclass, field

# ----------- INPUTS --------------

@dataclass
class LIBInputs:
    
    scenario_description: str = field(
        default="Default Scenario Description",
        metadata={"label": "Scenario Description",
                  "units": 'string',
                  "tooltip": "A brief description of the scenario being analyzed."
                  }
    )
    manufacturer_name: str = field(
        default="Default Manufacturer",
        metadata={"label": "Manufacturer Name",
                  "units": 'string',
                  "tooltip": "The name of the battery manufacturer."
                  }
    )
    battery_room: str = field(
        default="Default Battery Room",
        metadata={"label": "Battery Room",
                  "units": 'string',
                  "tooltip": "The name or identifier of the battery room."
                  }
    )
    room_height: float = field(
        default=3.0,
        metadata={"label": "Room Height",
                  "units": 'm',
                  "tooltip": "The height of the battery room."
                  }
    )
    room_area: float = field(
        default=50.0,
        metadata={"label": "Room Area",
                  "units": 'm2',
                  "tooltip": "The floor area of the battery room."
                  }
    )
    equip_space: float = field(
        default=10.0,
        metadata={"label": "Equipment Space",
                  "units": '%',
                  "tooltip": "The percentage of the room occupied by equipment."
                  }
    )
    calc_duration: int = field(
        default=3600,
        metadata={"label": "Calculation Duration",
                  "units": 's',
                  "tooltip": "The duration of the calculation in seconds."
                  }
    )
    time_step: int = field(
        default=1,
        metadata={"label": "Time Step",
                  "units": 's',
                  "tooltip": "The simulation time step. Larger steps degrade accuracy of the gas balance."
                  }
    )
    ventilation_rate: float = field(
        default=5.0,
        metadata={"label": "Ventilation Rate",
                  "units": 'L/s/m2',
                  "tooltip": "The ventilation rate of the battery room."
                  }
    )
    cells_per_module: int = field(
        default=10,
        metadata={"label": "Cells per Module",
                  "units": 'count',
                  "tooltip": "The number of cells in a single module."
                  }
    )
    modules_per_unit: int = field(
        default=5,
        metadata={"label": "Modules per Unit",
                  "units": 'count',
                  "tooltip": "The number of modules in a single unit."
                  }
    )
    units: int = field(
        default=1,
        metadata={"label": "Units",
                  "units": 'count',
                  "tooltip": "The number of units in the battery system."
                  }
    )
    lib_spec: str = field(
        default="None",
        metadata={"label": "Battery (LIB)",
                  "units": 'string',
                  "tooltip": "Name of a user-defined battery whose specs this scenario uses."
                  }
    )
    calc_method: str = field(
        default="Cell Volume UL9540A",
        metadata={"label": "Calculation Method",
                  "units": 'string',
                  "tooltip": "The calculation method used to determine off-gas volumes for this scenario.\n"
                             "Cell Volume UL9540A: uses a pre-defined (empirical) cell release curve derived from the "
                             "cell volume when the Cell Duration is 0; if a measured Cell Duration is entered, the "
                             "cell instead releases its volume at a flat rate over that duration."
                  }
    )
    composition_method: str = field(
        default="Literature Data",
        metadata={"label": "Composition Method",
                  "units": 'string',
                  "tooltip": "Whether the gas composition is taken from literature data or a user-defined composition."
                  }
    )
    gas_composition: str = field(
        default="None",
        metadata={"label": "Gas Composition",
                  "units": 'string',
                  "tooltip": "Name of a user-defined gas composition to apply to this scenario."
                  }
    )
    flowrate_profile: str = field(
        default="None",
        metadata={"label": "Flowrate Dataset",
                  "units": 'string',
                  "tooltip": "Name of an imported measured flowrate dataset, used by the 'Module Variable Flowrate' calculation method."
                  }
    )
    emergency_vent_rate: float = field(
        default=0.0,
        metadata={"label": "Emergency Vent Rate",
                  "units": 'L/s/m2',
                  "tooltip": "Emergency ventilation rate per square metre of room floor area\n"
                             "(same basis as the standard Ventilation Rate), activated by the\n"
                             "Vent Switch Concentration. Set to 0 to disable emergency ventilation."
                  }
    )
    vent_switch_conc: float = field(
        default=0.0,
        metadata={"label": "Vent Switch Concentration",
                  "units": '% of CO LFL',
                    "tooltip": "Room CO concentration, as a percentage of CO's own LFL, at which\n"
                               "ventilation switches to the emergency rate (not latched: it returns\n"
                               "to the standard rate if CO falls back below the trigger).\n"
                               "Set to 0 to disable emergency ventilation."
                    } 
    )
    use_le_chatelier_lfl: bool = field(
        default=False,
        metadata={"label": "Use Le Chatelier LFL",
                  "units": 'bool',
                  "tooltip": "Blend the per-gas LFLs into a mixture LFL instead of using the entered LFL."
                  }
    )
    use_temp_dependent_lfl: bool = field(
        default=False,
        metadata={"label": "Use Temperature Dependent LFL",
                  "units": 'bool',
                  "tooltip": "Adjust CO, H2 and total hydrocarbon LFLs for the venting temperature."
                  }
    )

    # Derived values live here so every calculation module agrees on how they are
    # computed, rather than each re-deriving them from the raw fields.
    def room_volume(self) -> float:
        """Free room volume (m3) once the equipment-occupied share is removed."""
        return self.room_height * self.room_area * (1.0 - self.equip_space / 100.0)

    def total_modules(self) -> int:
        """Modules across the whole system."""
        return self.modules_per_unit * self.units

    def effective_time_step(self) -> float:
        return float(self.time_step) if self.time_step > 0 else 1.0


@dataclass
class LIBSpec:
    """A named battery definition: everything that describes the LIB itself.

    These fields used to live on ``LIBInputs``. They are separated so one battery can
    be defined once and reused by any number of scenarios, each of which stores only
    the battery's ``name`` in ``LIBInputs.lib_spec``.
    """

    name: str = field(
        default="New Battery",
        metadata={"label": "Battery Name",
                  "units": 'string',
                  "tooltip": "Name this battery appears under in the scenario dialog."
                  }
    )
    lib_type: str = field(
        default="nmc",
        metadata={"label": "LIB Type",
                  "units": 'string',
                  "tooltip": "The type of lithium-ion battery."
                  }
    )
    cell_format: str = field(
        default="prismatic",
        metadata={"label": "Cell Format",
                  "units": 'string',
                  "tooltip": "The physical cell format, used to select the specific capacity (L/kWh) for the Module Capacity calculation method."
                  }
    )
    battery_charge: float = field(
        default=100.0,
        metadata={"label": "Battery Charge",
                  "units": '%',
                  "tooltip": "The state of charge of the battery."
                  }
    )
    venting_temperature: float = field(
        default=60.0,
        metadata={"label": "Venting Temperature",
                  "units": '°C',
                  "tooltip": "The venting temperature of the battery."
                  }
    )
    lfl: float = field(
        default=0.0,
        metadata={"label": "LFL",
                  "units": '%',
                  "tooltip": "The lower flammability limit of the battery off-gas mixture (v/v%).\n"
                             "Must be entered (> 0) unless the scenario enables 'Use Le Chatelier LFL',\n"
                             "which computes a mixture LFL from the gas composition instead."
                  }
    )
    cell_volume: float = field(
        default=0.5,
        metadata={"label": "Cell Volume",
                  "units": 'l',
                  "tooltip": "The volume of a single battery cell."
                  }
    )
    cell_duration: float = field(
        default=0,
        metadata={"label": "Cell Duration",
                  "units": 's',
                  "tooltip": "Measured venting duration of a single cell. Set to 0 to derive the release curve from the cell volume instead."
                  }
    )
    cell_amphour: float = field(
        default=2.0,
        metadata={"label": "Cell Amp Hour",
                  "units": 'Ah',
                  "tooltip": "The amp-hour rating of the cell."
                  }
    )
    cell_capacity: float = field(
        default=0.5,
        metadata={"label": "Cell Capacity",
                  "units": 'kWh',
                  "tooltip": "The energy capacity of the cell."
                  }
    )
    module_volume: float = field(
        default=5.0,
        metadata={"label": "Module Volume",
                  "units": 'l',
                  "tooltip": "The volume of a single battery module."
                  }
    )
    module_duration: float = field(
        default=3600,
        metadata={"label": "Module Duration",
                  "units": 's',
                  "tooltip": "The duration of a single battery module."
                  }
    )
    module_amphour: float = field(
        default=20.0,
        metadata={"label": "Module Amp Hour",
                  "units": 'Ah',
                  "tooltip": "The amp-hour rating of the module."
                  }
    )
    module_capacity: float = field(
        default=5.0,
        metadata={"label": "Module Capacity",
                  "units": 'kWh',
                  "tooltip": "The energy capacity of the module."
                  }
    )
    cell_prop_delay: float = field(
        default=60.0,
        metadata={"label": "Cell Propagation Delay",
                  "units": 's',
                  "tooltip": "The propagation delay of the cell."
                  }
    )
    cell_prop_number: int = field(
        default=3,
        metadata={"label": "Cell Propagation Number",
                  "units": 'count',
                  "tooltip": "The number of cells involved in propagation."
                  }
    )
    mod_prop_delay: float = field(
        default=180.0,
        metadata={"label": "Module Propagation Delay",
                  "units": 's',
                  "tooltip": "The propagation delay of the module."
                  }
    )
    mod_prop_number: int = field(
        default=2,
        metadata={"label": "Module Propagation Number",
                  "units": 'count',
                  "tooltip": "The number of modules involved in propagation."
                  }
    )


# ------------- DATA FOR GUI ----------------

"""
Battery Chemistry Literature Data

"""

LIB_TYPE = ["nmc", "lfp", "lco"]

CELL_FORMAT = ["prismatic", "cylindrical", "pouch"]

# Canonical calculation-method identifiers. Every consumer (UI dropdown, engine router,
# release-param branching, PDF/summary labels) references these constants so a wording
# change is made once here and can't drift into a typo mismatch across files.
CALC_METHOD_CELL_VOLUME_UL9540A = "Cell Volume UL9540A"
CALC_METHOD_MODULE_VOLUME_UL9540A = "Module Volume UL9540A"
CALC_METHOD_MODULE_CAPACITY = "Module Capacity"
CALC_METHOD_MODULE_VARIABLE_FLOWRATE = "Module Variable Flowrate"

CALCULATION_METHODS = [
    CALC_METHOD_CELL_VOLUME_UL9540A,
    CALC_METHOD_MODULE_VOLUME_UL9540A,
    CALC_METHOD_MODULE_CAPACITY,
    CALC_METHOD_MODULE_VARIABLE_FLOWRATE,
]

COMPOSITION_METHODS = ["Literature Data", "User Defined"]

# ============================================================================
# CENTRALIZED BATTERY CHEMISTRY DATA STRUCTURE
# ============================================================================
BATTERY_CHEMISTRY_DATA = {
    'NMC': {
        'default_lfl': 8.5,  # Default Lower Flammable Limit (%)
        'litre_per_ah': 0.07723544682,  # L/Ah - gas volume per amp-hour (for toxicity calculations)
        'specific_capacity': {#data taken from Peter's paper Figure 5. in L/KWh. Uses the median value from literature review data set.
            'prismatic': 585,
            'cylindrical': 203,
            'pouch': 530
            },
        # TODO: replace with source-verified shares. The raw literature values summed to
        # 141.9%, so every species below was scaled by 100/141.9 to total 100%.
        'composition': {
            'co': 42.29,  # Carbon monoxide
            'h2': 7.05,       # Hydrogen
            'thc': 7.05,  # Total hydrocarbons
            'no2': 6.84,               # Nitrogen dioxide
            'hcl': 6.84,               # Hydrogen chloride
            'hf': 2.61,                # Hydrogen fluoride
            'hcn': 0.49,               # Hydrogen cyanide
            'benzene': 9.58,          # Benzene
            'toluene': 2.89,
            'so2': 2.11,
            'c2h5f': 0.70,
            'methanol': 0.70,
            'dec': 1.69,
            'dmc': 1.76,
            'propane': 1.06,
            'no': 2.82,
            'h2o': 3.52
        },
        'description': 'Nickel Manganese Cobalt Oxide (NMC) - High energy density cathode material',
        'reference': 'Peter Literature Data'
    },
    'LFP': {
        'default_lfl': 5.5,  # Default LFL value for LFP chemistry
        'litre_per_ah': 0.07723544682,  # L/Ah - gas volume per amp-hour (for toxicity calculations)
        'specific_capacity':{#data taken from Peter's paper Figure 5. in L/KWh. Uses the median value from literature review data set.
            'prismatic': 373, 
            'cylindrical': 168,
            'pouch': 131
        }, 
        # TODO: replace with source-verified shares. The raw literature values summed to
        # 161.9%, so every species below was scaled by 100/161.9 to total 100%.
        'composition': {
            'co': 49.41,  # Carbon monoxide
            'h2': 6.18,       # Hydrogen
            'thc': 6.18,  # Total hydrocarbons
            'no2': 5.99,               # Nitrogen dioxide
            'hcl': 5.99,               # Hydrogen chloride
            'hf': 2.29,                # Hydrogen fluoride
            'hcn': 0.43,               # Hydrogen cyanide
            'benzene': 8.40,          # Benzene
            'toluene': 2.53,
            'so2': 1.85,
            'c2h5f': 0.62,
            'methanol': 0.62,
            'dec': 1.48,
            'dmc': 1.54,
            'propane': 0.93,
            'no': 2.47,
            'h2o': 3.09
        },
        'description': 'Lithium Iron Phosphate (LFP) - Safer, more stable cathode material',
        'reference': 'DNV.GL Technical Reference for Li-ion Battery Explosion Risk and Fire Suppression'
    },
    'LCO': {
        'default_lfl': 7.5,  # Default Lower Flammable Limit for LCO chemistry
        'litre_per_ah': 0.07723544682,  # L/Ah - gas volume per amp-hour (for toxicity calculations)
        'specific_capacity':{#data taken from Peter's paper Figure 5. in L/KWh. Uses the median value from literature review data set.
            'prismatic': 891, 
            'cylindrical': 305, 
            'pouch': 384
            },  # L/kWh - specific capacity for module calculations
        # TODO: replace with source-verified shares. The raw literature values summed to
        # 161.9%, so every species below was scaled by 100/161.9 to total 100%.
        'composition': {
            'co': 49.41,  # Carbon monoxide
            'h2': 6.18,       # Hydrogen
            'thc': 6.18,  # Total hydrocarbons
            'no2': 5.99,               # Nitrogen dioxide
            'hcl': 5.99,               # Hydrogen chloride
            'hf': 2.29,                # Hydrogen fluoride
            'hcn': 0.43,               # Hydrogen cyanide
            'benzene': 8.40,          # Benzene
            'toluene': 2.53,
            'so2': 1.85,
            'c2h5f': 0.62,
            'methanol': 0.62,
            'dec': 1.48,
            'dmc': 1.54,
            'propane': 0.93,
            'no': 2.47,
            'h2o': 3.09
        },
        'description': 'Lithium Cobalt Oxide (LCO) - High energy density, consumer electronics',
        'reference': 'DNV.GL Technical Reference for Li-ion Battery Explosion Risk and Fire Suppression'
    }
}

# ============================================================================
# TEMPERATURE CONSTANTS
# ============================================================================

# Data for the linear relationship equation between temperature and LFL

TEMPERATURE_DEPENDENT_LFL_PARAMETERS = {"co": {"a": -0.0108, "b": 12.456},
                                        "h2": {"a": -0.0120, "b": 7.2884},
                                        "thc": {"a": -0.0040, "b": 5.0990}}


# Data sourced from "Chem property data txt" folder text files.
# density: g/L (or kg/m3 as provided in source data, e.g. water in kg/m3)
# erpg_3: ERPG-3 value (ppm, or ppm/percent depending on gas - see source file). None if N/A.
# lfl: Lower Flammable Limit (%). None if N/A / not flammable.
# molecular_weight: g/mol. None if N/A.
CHEMICAL_PROPERTIES = {
    'benzene':      {'density': 3.313, 'erpg_3': 3.313, 'lfl': 1.4,  'molecular_weight': 78.11,    'toxicity_factor': 1, 'flammability_factor': 1},
    'toluene':      {'density': 3.755, 'erpg_3': 3.755, 'lfl': 1.3,  'molecular_weight': 92.13842, 'toxicity_factor': 1, 'flammability_factor': 1},
    'co':           {'density': 0.967, 'erpg_3': 0.484, 'lfl': 12.5, 'molecular_weight': 28.0101,  'toxicity_factor': 1, 'flammability_factor': 1},
    'co2':          {'density': 1.830, 'erpg_3': 0.000, 'lfl': None, 'molecular_weight': 44.0095,  'toxicity_factor': 0, 'flammability_factor': 0},
    'no2':          {'density': 1.890, 'erpg_3': 0.057, 'lfl': None, 'molecular_weight': 46.01,    'toxicity_factor': 1, 'flammability_factor': 0},
    'hcl':          {'density': 1.517, 'erpg_3': 0.227, 'lfl': None, 'molecular_weight': 36.46,    'toxicity_factor': 1, 'flammability_factor': 0},
    'hf':           {'density': 0.825, 'erpg_3': 0.041, 'lfl': None, 'molecular_weight': 20.01,    'toxicity_factor': 1, 'flammability_factor': 0},
    'hcn':          {'density': 1.078, 'erpg_3': 0.027, 'lfl': 5.6,  'molecular_weight': 27.0253,  'toxicity_factor': 1, 'flammability_factor': 1},
    'so2':          {'density': 1.078, 'erpg_3': 25,    'lfl': None, 'molecular_weight': 64.07,    'toxicity_factor': 1, 'flammability_factor': 0},
    'c2h5f':        {'density': 2.14,  'erpg_3': 260000,'lfl': 2.6,  'molecular_weight': 48.0601,  'toxicity_factor': 1, 'flammability_factor': 1},
    'methanol':     {'density': 1.11,  'erpg_3': 145000,'lfl': 6,    'molecular_weight': 32.042,   'toxicity_factor': 1, 'flammability_factor': 1},
    'dmc':          {'density': 3.1,   'erpg_3': 140,   'lfl': 4.2,  'molecular_weight': 90.08,    'toxicity_factor': 1, 'flammability_factor': 1},
    'dec':          {'density': 4.1,   'erpg_3': 21,    'lfl': 4.2,  'molecular_weight': 118.13,   'toxicity_factor': 1, 'flammability_factor': 1},
    'propane':      {'density': 0.86,  'erpg_3': 180000,'lfl': 2.1,  'molecular_weight': 44.10,    'toxicity_factor': 1, 'flammability_factor': 1},
    'xylene':       {'density': 3.7,   'erpg_3': 2500,  'lfl': 1.7,  'molecular_weight': 106.17,   'toxicity_factor': 1, 'flammability_factor': 1},
    'h2':           {'density': 0.084, 'erpg_3': None,  'lfl': 4.0,  'molecular_weight': 2.01588,  'toxicity_factor': 1, 'flammability_factor': 1},
    'h2o':          {'density': 996.86,'erpg_3': None,  'lfl': None, 'molecular_weight': 18.015,   'toxicity_factor': 0, 'flammability_factor': 0},
    'pf3':          {'density': 3.907, 'erpg_3': 10,    'lfl': None, 'molecular_weight': 87.97,    'toxicity_factor': 0, 'flammability_factor': 0},
    'methane':      {'density': 0.664, 'erpg_3': None,  'lfl': 4.4,  'molecular_weight': 16.04,    'toxicity_factor': 0, 'flammability_factor': 1},
    'thc':          {'density': 3.708, 'erpg_3': None, 'lfl': 6.5,   'molecular_weight': None,     'toxicity_factor': 0, 'flammability_factor': 1},
    'ethanol':      {'density': 0.668, 'erpg_3': None,  'lfl': 5.0,  'molecular_weight': 46.08,    'toxicity_factor': 0, 'flammability_factor': 1},
    'no':           {'density': 1.34,  'erpg_3': None,  'lfl': None, 'molecular_weight': 30.01,    'toxicity_factor': 0, 'flammability_factor': 0},
}


@dataclass
class GasComposition:
    """A named split of the total off-gas into individual species.

    ``percentages`` maps a CHEMICAL_PROPERTIES key to that species' share (%) of the
    total released gas. No per-species physical data is copied here: density, LFL and
    the flammable/toxic factors are always looked up from CHEMICAL_PROPERTIES.
    """

    name: str
    percentages: dict = field(default_factory=dict)

    def species(self) -> list:
        """Species with a non-zero share, in CHEMICAL_PROPERTIES order."""
        return [gas for gas in CHEMICAL_PROPERTIES if self.percentages.get(gas, 0.0) > 0.0]

    def total_percent(self) -> float:
        return float(sum(self.percentages.get(gas, 0.0) for gas in self.species()))

    def fractions(self) -> dict:
        """{species: fraction of the total gas} for every non-zero species."""
        return {gas: self.percentages[gas] / 100.0 for gas in self.species()}

    def properties(self, gas: str) -> dict:
        return CHEMICAL_PROPERTIES[gas]

    def flammable_species(self) -> list:
        return [g for g in self.species() if CHEMICAL_PROPERTIES[g].get('flammability_factor')]

    def toxic_species(self) -> list:
        return [g for g in self.species()
                if CHEMICAL_PROPERTIES[g].get('toxicity_factor') and CHEMICAL_PROPERTIES[g].get('erpg_3') is not None]

    def densities(self, species=None) -> list:
        return [CHEMICAL_PROPERTIES[g]['density'] for g in (species or self.species())]


@dataclass
class FlowrateProfile:
    """A named measured release profile: one module's total off-gas flowrate over time.

    ``flowrate_lps[i]`` is the flowrate (L/s) at ``time_s[i]``, nominally on a one
    second grid. Only the total flowrate is held here - the split into species still
    comes from the scenario's gas composition, exactly as it does for every other
    calculation method - so an importer only has to produce these two columns.
    """

    name: str
    time_s: list = field(default_factory=list)
    flowrate_lps: list = field(default_factory=list)

    def duration(self) -> float:
        """Length of the dataset (s); this is what sets one module's release duration."""
        return float(self.time_s[-1]) if self.time_s else 0.0

    def total_volume_l(self) -> float:
        """Volume (l) the dataset releases, by trapezoidal integration."""
        total = 0.0
        for index in range(1, len(self.time_s)):
            step = float(self.time_s[index]) - float(self.time_s[index - 1])
            total += 0.5 * step * (float(self.flowrate_lps[index]) + float(self.flowrate_lps[index - 1]))
        return total

    def peak_flowrate_lps(self) -> float:
        return max((float(value) for value in self.flowrate_lps), default=0.0)

    def lfls(self, species=None) -> list:
        return [CHEMICAL_PROPERTIES[g]['lfl'] for g in (species or self.species())]


_THEMES: dict = {
    "Default Light": """
        QWidget            { background-color: #f0f4f8; color: #1a2733; font-size: 13px; }
        QMainWindow        { background-color: #f0f4f8; }
        QMenuBar           { background-color: #dde6f0; color: #1a2733; border-bottom: 1px solid #b0c4d8; }
        QMenuBar::item:selected { background-color: #b8cfea; }
        QMenu              { background-color: #ffffff; border: 1px solid #b0c4d8; color: #1a2733; }
        QMenu::item:selected   { background-color: #b8cfea; }
        QToolBar           { background-color: #dde6f0; border-bottom: 2px solid #b0c4d8; spacing: 6px; padding: 4px; }
        QWidget#toolbarContents { background-color: #dde6f0; }
        QPushButton        { background-color: #c5dcf5; border: 1px solid #7aabdb; border-radius: 5px;
                             padding: 6px 14px; color: #1a2733; font-weight: bold; }
        QPushButton:hover  { background-color: #9dc4ef; }
        QPushButton:pressed { background-color: #6faae6; }
        QPushButton#clearAllButton       { background-color: #d9534f; border-color: #c9302c; color: #ffffff; }
        QPushButton#clearAllButton:hover { background-color: #c9302c; }
        QComboBox          { background-color: #ffffff; border: 1px solid #7aabdb; border-radius: 4px; padding: 4px 8px; }
        QComboBox QAbstractItemView { background-color: #ffffff; selection-background-color: #b8cfea; }
        QCheckBox          { spacing: 6px; }
        QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #7aabdb; border-radius: 3px; background: #ffffff; }
        QCheckBox::indicator:checked { background-color: #4a90d9; }
        QTabWidget::pane   { border: 1px solid #b0c4d8; background: #ffffff; }
        QTabBar::tab       { background: #dde6f0; border: 1px solid #b0c4d8; padding: 6px 16px; border-radius: 4px 4px 0 0; }
        QTabBar::tab:selected { background: #ffffff; border-bottom-color: #ffffff; font-weight: bold; }
        QTabBar::close-button { subcontrol-position: right; margin: 2px; border-radius: 3px; }
        QTabBar::close-button:hover { background: #b8cfea; }
        QTableWidget       { background-color: #ffffff; gridline-color: #c8d8e8; }
        QHeaderView::section { background-color: #dde6f0; border: 1px solid #b0c4d8; padding: 5px; font-weight: bold; }
        QScrollBar:vertical { background: #e8eef5; width: 12px; }
        QScrollBar::handle:vertical { background: #7aabdb; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #7aabdb; }
        QWidget#scenarioTreeWidget { border: 1px solid #8ba9c7; border-radius: 6px; background-color: #eef4fb; }
        QWidget#scenarioTreeHeader { background-color: #eef4fb; border-bottom: 1px solid #8ba9c7; }
        QWidget#scenarioTreeHeader QLabel { background-color: transparent; color: #1a2733; }
        QTreeWidget#scenarioTreeInner { background-color: #eef4fb; border: none; padding: 2px; }
    """,
    "Dark": """
        QWidget            { background-color: #1e1e2e; color: #cdd6f4; font-size: 13px; }
        QMainWindow        { background-color: #1e1e2e; }
        QMenuBar           { background-color: #181825; color: #cdd6f4; border-bottom: 1px solid #313244; }
        QMenuBar::item:selected { background-color: #313244; }
        QMenu              { background-color: #181825; border: 1px solid #313244; color: #cdd6f4; }
        QMenu::item:selected   { background-color: #313244; }
        QToolBar           { background-color: #181825; border-bottom: 2px solid #313244; spacing: 6px; padding: 4px; }
        QWidget#toolbarContents { background-color: #181825; }
        QPushButton        { background-color: #313244; border: 1px solid #585b70; border-radius: 5px;
                             padding: 6px 14px; color: #cdd6f4; font-weight: bold; }
        QPushButton:hover  { background-color: #45475a; }
        QPushButton:pressed { background-color: #585b70; }
        QPushButton#clearAllButton       { background-color: #f38ba8; border-color: #e06c75; color: #1e1e2e; }
        QPushButton#clearAllButton:hover { background-color: #e06c75; color: #ffffff; }
        QComboBox          { background-color: #313244; border: 1px solid #585b70; border-radius: 4px; padding: 4px 8px; color: #cdd6f4; }
        QComboBox QAbstractItemView { background-color: #313244; color: #cdd6f4; selection-background-color: #45475a; }
        QCheckBox          { spacing: 6px; color: #cdd6f4; }
        QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #585b70; border-radius: 3px; background: #313244; }
        QCheckBox::indicator:checked { background-color: #89b4fa; border-color: #89b4fa; }
        QTabWidget::pane   { border: 1px solid #313244; background: #1e1e2e; }
        QTabBar::tab       { background: #181825; border: 1px solid #313244; padding: 6px 16px;
                             color: #cdd6f4; border-radius: 4px 4px 0 0; }
        QTabBar::tab:selected { background: #1e1e2e; font-weight: bold; }
        QTabBar::close-button { subcontrol-position: right; margin: 2px; border-radius: 3px; }
        QTabBar::close-button:hover { background: #45475a; }
        QTableWidget       { background-color: #1e1e2e; color: #cdd6f4; gridline-color: #313244; }
        QHeaderView::section { background-color: #313244; border: 1px solid #45475a; padding: 5px; color: #cdd6f4; font-weight: bold; }
        QScrollBar:vertical { background: #181825; width: 12px; }
        QScrollBar::handle:vertical { background: #585b70; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #585b70; }
        QLabel             { color: #cdd6f4; }
        QWidget#scenarioTreeWidget { border: 1px solid #4c5064; border-radius: 6px; background-color: #25273a; }
        QWidget#scenarioTreeHeader { background-color: #25273a; border-bottom: 1px solid #4c5064; }
        QWidget#scenarioTreeHeader QLabel { background-color: transparent; color: #cdd6f4; }
        QTreeWidget#scenarioTreeInner { background-color: #25273a; border: none; padding: 2px; }
    """,
    "Arup Red": """
        QWidget            { background-color: #fafafa; color: #1a1a1a; font-size: 13px; }
        QMainWindow        { background-color: #fafafa; }
        QMenuBar           { background-color: #e8001c; color: #ffffff; border-bottom: 2px solid #b30016; }
        QMenuBar::item:selected { background-color: #b30016; }
        QMenu              { background-color: #ffffff; border: 1px solid #e8001c; color: #1a1a1a; }
        QMenu::item:selected   { background-color: #ffd6d9; }
        QToolBar           { background-color: #f2f2f2; border-bottom: 2px solid #e8001c; spacing: 6px; padding: 4px; }
        QWidget#toolbarContents { background-color: #f2f2f2; }
        QPushButton        { background-color: #f5f5f5; border: 2px solid #e8001c; border-radius: 5px;
                             padding: 6px 14px; color: #1a1a1a; font-weight: bold; }
        QPushButton:hover  { background-color: #ffd6d9; border-color: #b30016; }
        QPushButton:pressed { background-color: #ffb3b8; }
        QPushButton#clearAllButton       { background-color: #e8001c; border-color: #b30016; color: #ffffff; }
        QPushButton#clearAllButton:hover { background-color: #b30016; }
        QComboBox          { background-color: #ffffff; border: 2px solid #e8001c; border-radius: 4px; padding: 4px 8px; }
        QComboBox QAbstractItemView { background-color: #ffffff; selection-background-color: #ffd6d9; }
        QCheckBox          { spacing: 6px; }
        QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid #e8001c; border-radius: 3px; background: #ffffff; }
        QCheckBox::indicator:checked { background-color: #e8001c; }
        QTabWidget::pane   { border: 2px solid #e8001c; background: #ffffff; }
        QTabBar::tab       { background: #f5f5f5; border: 1px solid #e8001c; padding: 6px 16px; border-radius: 4px 4px 0 0; }
        QTabBar::tab:selected { background: #ffffff; font-weight: bold; border-bottom-color: #ffffff; }
        QTabBar::close-button { subcontrol-position: right; margin: 2px; border-radius: 3px; }
        QTabBar::close-button:hover { background: #ffd6d9; }
        QTableWidget       { background-color: #ffffff; gridline-color: #f5c6c9; }
        QHeaderView::section { background-color: #ffd6d9; border: 1px solid #e8001c; padding: 5px; font-weight: bold; }
        QScrollBar:vertical { background: #f5f5f5; width: 12px; }
        QScrollBar::handle:vertical { background: #e8001c; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #e8001c; }
        QWidget#scenarioTreeWidget { border: 2px solid #cf102a; border-radius: 6px; background-color: #fff6f7; }
        QWidget#scenarioTreeHeader { background-color: #fff6f7; border-bottom: 1px solid #cf102a; }
        QWidget#scenarioTreeHeader QLabel { background-color: transparent; color: #1a1a1a; }
        QTreeWidget#scenarioTreeInner { background-color: #fff6f7; border: none; padding: 2px; }
    """,
    "High Contrast": """
        QWidget            { background-color: #000000; color: #ffffff; font-size: 13px; }
        QMainWindow        { background-color: #000000; }
        QMenuBar           { background-color: #000000; color: #ffffff; border-bottom: 2px solid #ffffff; }
        QMenuBar::item:selected { background-color: #ffffff; color: #000000; }
        QMenu              { background-color: #000000; border: 2px solid #ffffff; color: #ffffff; }
        QMenu::item:selected   { background-color: #ffffff; color: #000000; }
        QToolBar           { background-color: #000000; border-bottom: 2px solid #ffffff; spacing: 6px; padding: 4px; }
        QWidget#toolbarContents { background-color: #000000; }
        QPushButton        { background-color: #000000; border: 2px solid #ffffff; border-radius: 4px;
                             padding: 6px 14px; color: #ffffff; font-weight: bold; }
        QPushButton:hover  { background-color: #333333; }
        QPushButton:pressed { background-color: #555555; }
        QPushButton#clearAllButton       { background-color: #ffff00; border-color: #ffffff; color: #000000; }
        QPushButton#clearAllButton:hover { background-color: #ffcc00; }
        QComboBox          { background-color: #000000; border: 2px solid #ffffff; border-radius: 4px; padding: 4px 8px; color: #ffffff; }
        QComboBox QAbstractItemView { background-color: #000000; color: #ffffff;
                                      selection-background-color: #ffffff; selection-color: #000000; }
        QCheckBox          { spacing: 6px; color: #ffffff; }
        QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid #ffffff; border-radius: 2px; background: #000000; }
        QCheckBox::indicator:checked { background-color: #ffffff; }
        QTabWidget::pane   { border: 2px solid #ffffff; background: #000000; }
        QTabBar::tab       { background: #000000; border: 2px solid #ffffff; padding: 6px 16px;
                             color: #ffffff; border-radius: 4px 4px 0 0; }
        QTabBar::tab:selected { background: #333333; font-weight: bold; }
        QTabBar::close-button { subcontrol-position: right; margin: 2px; border-radius: 3px; }
        QTabBar::close-button:hover { background: #ffffff; }
        QTableWidget       { background-color: #000000; color: #ffffff; gridline-color: #ffffff; }
        QHeaderView::section { background-color: #333333; border: 1px solid #ffffff; padding: 5px; color: #ffffff; font-weight: bold; }
        QScrollBar:vertical { background: #000000; width: 12px; }
        QScrollBar::handle:vertical { background: #ffffff; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #ffffff; }
        QLabel             { color: #ffffff; }
        QWidget#scenarioTreeWidget { border: 2px solid #ffffff; border-radius: 6px; background-color: #1a1a1a; }
        QWidget#scenarioTreeHeader { background-color: #1a1a1a; border-bottom: 1px solid #ffffff; }
        QWidget#scenarioTreeHeader QLabel { background-color: transparent; color: #ffffff; }
        QTreeWidget#scenarioTreeInner { background-color: #1a1a1a; border: none; padding: 2px; }
    """,
    "Warm Slate": """
        QWidget            { background-color: #f5f0eb; color: #2c1f14; font-size: 13px; }
        QMainWindow        { background-color: #f5f0eb; }
        QMenuBar           { background-color: #e8ddd2; color: #2c1f14; border-bottom: 1px solid #c4a882; }
        QMenuBar::item:selected { background-color: #d4bfa0; }
        QMenu              { background-color: #fff8f2; border: 1px solid #c4a882; color: #2c1f14; }
        QMenu::item:selected   { background-color: #e8d5bc; }
        QToolBar           { background-color: #ede4d8; border-bottom: 2px solid #c4a882; spacing: 6px; padding: 4px; }
        QWidget#toolbarContents { background-color: #ede4d8; }
        QPushButton        { background-color: #d4bfa0; border: 1px solid #a87d5a; border-radius: 5px;
                             padding: 6px 14px; color: #2c1f14; font-weight: bold; }
        QPushButton:hover  { background-color: #c4a882; }
        QPushButton:pressed { background-color: #a87d5a; color: #ffffff; }
        QPushButton#clearAllButton       { background-color: #c0392b; border-color: #922b21; color: #ffffff; }
        QPushButton#clearAllButton:hover { background-color: #922b21; }
        QComboBox          { background-color: #fff8f2; border: 1px solid #a87d5a; border-radius: 4px; padding: 4px 8px; }
        QComboBox QAbstractItemView { background-color: #fff8f2; selection-background-color: #e8d5bc; }
        QCheckBox          { spacing: 6px; }
        QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #a87d5a; border-radius: 3px; background: #fff8f2; }
        QCheckBox::indicator:checked { background-color: #a87d5a; }
        QTabWidget::pane   { border: 1px solid #c4a882; background: #fff8f2; }
        QTabBar::tab       { background: #e8ddd2; border: 1px solid #c4a882; padding: 6px 16px; border-radius: 4px 4px 0 0; }
        QTabBar::tab:selected { background: #fff8f2; font-weight: bold; }
        QTabBar::close-button { subcontrol-position: right; margin: 2px; border-radius: 3px; }
        QTabBar::close-button:hover { background: #e8d5bc; }
        QTableWidget       { background-color: #fff8f2; gridline-color: #d4bfa0; }
        QHeaderView::section { background-color: #e8ddd2; border: 1px solid #c4a882; padding: 5px; font-weight: bold; }
        QScrollBar:vertical { background: #ede4d8; width: 12px; }
        QScrollBar::handle:vertical { background: #c4a882; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #c4a882; }
        QWidget#scenarioTreeWidget { border: 1px solid #ad8c66; border-radius: 6px; background-color: #fbf4ec; }
        QWidget#scenarioTreeHeader { background-color: #fbf4ec; border-bottom: 1px solid #ad8c66; }
        QWidget#scenarioTreeHeader QLabel { background-color: transparent; color: #2c1f14; }
        QTreeWidget#scenarioTreeInner { background-color: #fbf4ec; border: none; padding: 2px; }
    """,
}



# --------------------- POOL FIRE SPREAD DATA ---------------------

@dataclass
class PoolFireInputs:
    """Class for storing pool fire input parameters."""
    fuel_type: str
    pool_diameter: float  # in meters
    wind_speed: float     # in m/s
    ambient_temperature: float  # in Celsius
    pool_depth: float     # in meters
    surface_area: float   # in square meters


POOL_SPREAD_DATA = { #reference is SPFE Handbook of fire protection engineering, 3rd edition 2002, page 3-26
    'methanol':           {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 32.04},
    'ethanol':        {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 46.07},
    'butane':           {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 58.12},
    'benzene':        {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'hexane':           {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 86.18},
    'heptane':         {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 100.21},
    'xylene':            {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 106.16},
    'acetone':           {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 58.08},
    'dioxane':           {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 88.11},
    'diethyl ether':       {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 74.12},
    'benzine':           {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'gasoline':         {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'kerosine':        {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'diesel':             {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'jp-4':              {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'jp-5':             {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'transformer oil':    {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    '561 silicon transformer fluid': {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'fuel oil':          {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'crude oil':          {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
    'lube oil':         {'mass burning rate': 3.313, 'heat of combustion': 3.313, 'density': 1.4, 'empirical constant': 78.11, 'liquid vapour pressure': 0.13, 'molar mass': 78.11},
}

POOL_PROPERTIES = {
    'intrinsic_permeability':     {'metallic': 1*10**-20, 'finished concrete': 1*10**-18, 'rough concrete': 1*10**-16, 'asphalt': 1*10**-15, 'clay': 1*10**-15, 'clay/silt': 1*10**-14, 'silt': 1*10**-13, 'silt/sand': 1*10**-12, 'sand': 1*10**-11, 'sand/gravel': 1*10**-10, 'gravel': 1*10**-8},
    'relative_permeability':      {'dry': 1.0, 'slightly wet': 0.9, 'wet': 0.5, 'very wet': 0.3, 'saturated': float('nan')},
    'discharge_coefficients':     {'sharp': 0.61, 'rounded': 0.97},
    'average_pool_height':        {'flat': 0.005, 'normal': 0.01, 'rough': 0.02, 'very rough': 0.025}  
}



FIRE_PROPERTIES = {
    'fire growth rate': {'slow': 0.00293, 'medium': 0.01172, 'fast': 0.04688, 'ultra fast': 0.1875},
}

# --------------------- SPRINKLER PROPERTIES ---------------------

@dataclass
class SprinklerInputs:
    sprinkler_type: str
    liquid_colour_code: str
    activation_temperature: str


# note that sprinkler RTI is selected in accordance with AS 2118.1:2017.
#see section 1.3.4 of AS2118.1:2017 for more information on sprinkler RTI selection.  
SPRINKLER_PROPERTIES = {
    'sprinkler response time index': {'exposed quick': 50, 'exposed standard': 80, 'concealed quick': 150, 'concealed standard': 234},
    'liquid colour code': {'red': 37, 'yellow': 48, 'green': 62},
    'activation temperatures': {'red': 68, 'yellow': 79, 'green': 93}

}


MXC_VALUES = {
    'argon': 6.15, 'neon': 9.20, 'nitrogen': 9.90, 'helium': 11.86, 'tetrafluoroethane': 11.98, 'carbon_dioxide':22.45, 'carbon_tetrafluoride': 33.43, 'sulfur_hexafluoride': 50.40
}
