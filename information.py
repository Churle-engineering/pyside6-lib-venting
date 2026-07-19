# aLL DATA TO DRAW FROM IN PROGRAM

TARGET_FLAM_GAS = ["CO", "H2", "Total Hydrocarbons"]
LIB_TYPE = ["NMC", "LFP", "LCO"]
REQ_LIB_INFO = ["Manufacturer name","Battery room","LFL (%)","Cell Duration (s)","Module Duration (s)","Venting Temperature (°C)","Cell Amp Hr (Ah)","Module Amp Hr (Ah)","Module Capacity (kWh)","Cell Volume (L)","Module Volume (L)","Battery Charge (%)","CO (%)","CO2 (%)","H2 (%)","Total Hydrocarbons (%)"]
USER_INPUTS = ["Scenario Description", "Room Area (m2)","Room Height (m)","Equipment Space (%)","Ventilation Rate (L/s/m2)","Module Propagation Delay (s)","Cells per","Modules per","Units","Calculation Duration (s)","Time Step (s)","LIB Type","Vent Switch Conc (%)","Emergency Vent Rate (L/s/m2)"]
CALCULATION_METHODS = ["Cell Volume UL9540A", "Module Volume UL9540A", "Module Capacity", "Module Variable Flowrate"]
UL_TEST_GASSES = ["CO","CO2","H2","Total Hydrocarbons"]
# COMBINED_INPUTS = USER_INPUTS + REQ_LIB_INFO

INPUT_SCHEMA = {
    # identification            metadata
    "scenario_description": ("Scenario Description",          str,   0),
    "manufacturer_name":    ("Manufacturer Name",             str,   0),
    "battery_room":         ("Battery Room",                  str,   0),
    "room_height":          ("Room Height (m)",              float, 0),
    "room_area":            ("Room Area (m2)",               float, 0),
    "equip_space":          ("Equipment Space (%)",          float, 0),
    "calc_duration":        ("Calculation Duration (s)",     lambda x: int(float(x)), 0),
    "time_step":            ("Time Step (s)",                lambda x: int(float(x)), 1),
    "ventilation_rate":     ("Ventilation Rate (L/s/m2)",    float, 0),
    "cell_volume":          ("cell_volume_(l)",              float, 0),
    "cell_duration":        ("cell_duration_(s)",            float, 0),
    "module_volume":        ("module_volume_(l)",            float, 0),
    "module_duration":      ("module_duration_(s)",          float, 0),
    "cells per":            ("Cells per module",             float, 0),
    "modules per":          ("Modules per unit",             float, 0),
    "units":                ("Units",                        float, 0),
    "lfl":                  ("LFL (%)",                       float, 0),
    "lib_type":             ("LIB Type",                     str,   0),
    "mod_prop_delay":       ("Module Propagation Delay (s)", float, 180),
    "mod_capacity":         ("module_capacity_(kwh)",        float, 0),
    "battery_charge":       ("Battery Charge (%)",           float, 100),
    "vent_switch_conc":     ("Vent Switch Conc (%)",         float, 0),
    "emergency_vent_rate":  ("Emergency Vent Rate (L/s/m2)", float, 0),
    "co":                   ("Carbon Monoxide (%)", float, 0),
    "co2":                  ("Carbon Dioxide (%)", float, 0),
    "h2":                   ("Hydrogen (%)", float, 0),
    "total_hydrocarbons":   ("Total Hydrocarbons (%)", float, 0),
}

COMBINED_INPUTS = [key for key, _, _ in INPUT_SCHEMA.values()]
TEXT_INPUT_KEYS = {key for key, _, _ in INPUT_SCHEMA.values()}

GAS_LABEL_FIX = {
    "hcl": "HCl",
    "hcn": "HCN",
    "hf": "HF",
    "h2": "H₂",
    "co2": "CO₂",
    "co": "CO",
    "benzene": "Benzene",
    "no2": "NO₂",
    "toluene": "Toluene",
    "Total Gas (ppm)": "Total Gas",
    "total_gas": "Total Gas",
    "total_hydrocarbons": "Total Hydrocarbons"
}

TOOLTIPS = {
    "Room Area (m2)": "Total internal floor area of the room",
    "Room Height (m)": "Ceiling height of the room",
    "Equipment Space (%)": "Percentage of room occupied by equipment",
    "Ventilation Rate (L/s/m2)": "Air changes per unit area",
    "Module Propagation Delay (s)": "Duration for spread to two additional modules",
    "Cells per": "Number of cells per module",
    "Modules per": "Number of modules per unit",
    "Units": "Number of LIB units",
    "Calculation Duration (s)": "Total simulation time",
    "Time Step (s)": "Calculation time increment",
    "LIB Type": "Lithium-ion battery chemistry type",
    "Vent Switch Conc (%)": "Total gas concentration (%) at which ventilation switches to emergency rate. Set to 0 to disable.",
    "Emergency Vent Rate (L/s/m2)": "Ventilation rate to switch to when concentration threshold is reached. Set to 0 to disable."
}

"""
Battery Chemistry Literature Data
==================================
This module stores literature-based data for different battery chemistry types.
Data sourced from: DNV.GL Technical Reference for Li-ion Battery Explosion Risk and Fire Suppression

Each chemistry type contains:
- percent_tox: Percentage of toxic gas composition
- percent_flam: Percentage of flammable gas composition  
- tox_gas_composition: Dictionary of toxic gases and their composition percentages
- gas_volume_factor: L/Ah - gas volume per amp-hour (for toxicity calculations)
- specific_capacity: L/kWh - specific capacity for module-level calculations (for flammability calculations)

Chemistry types supported: NMC, LFP, LCO
"""


# ============================================================================
# CENTRALIZED BATTERY CHEMISTRY DATA STRUCTURE
# ============================================================================
BATTERY_CHEMISTRY_DATA = {
    'NMC': {
        'percent_tox': 30.66753,      # Percentage toxic gases (literature-based)
        'percent_flam': 100,     # Percentage flammable gases (literature-based) add back 84.68538
        'specific_capacity': 458.266894,  # L/kWh - specific capacity for module calculations
        'tox_gas_composition': {
            'co': 38.1,               # Carbon monoxide
            'no2': 9.7,               # Nitrogen dioxide
            'hcl': 9.7,               # Hydrogen chloride
            'hf': 3.7,                # Hydrogen fluoride
            'hcn': 0.7,               # Hydrogen cyanide
            'benzene': 13.6,          # Benzene
            'toluene': 4.1,
            'so2': 3,
            'c2h5f': 1,
            'methanol':1,
            'dec': 2.4,
            'dmc': 2.5,
            'propane': 1.5,
            'no':4,
            'h2o':5
        },
        'description': 'Nickel Manganese Cobalt Oxide (NMC) - High energy density cathode material',
        'reference': 'DNV.GL Technical Reference for Li-ion Battery Explosion Risk and Fire Suppression + additional data'
    },
    'LFP': {
        'percent_tox': 34.6478,      # Percentage toxic gases (literature-based)
        'percent_flam': 70.39466,     # Percentage flammable gases (literature-based)
        'specific_capacity': 77.23544682,  # L/kWh - specific capacity for module calculations
        'tox_gas_composition': {
            'co': 38.1,               # Carbon monoxide
            'no2': 9.7,               # Nitrogen dioxide
            'hcl': 9.7,               # Hydrogen chloride
            'hf': 3.7,                # Hydrogen fluoride
            'hcn': 0.7,               # Hydrogen cyanide
            'benzene': 12.6,          # Benzene
            'toluene': 4.1,           # Toluene
            'so2': 10.7,
            'c2h5f': 4.6,
            'methanol':0.5,
            'emc': 0.6,
            'dmc': 3,
            'propane': 0.5,
            'no':1,
            'pf3':0.5
        },
        'description': 'Lithium Iron Phosphate (LFP) - Safer, more stable cathode material',
        'reference': 'DNV.GL Technical Reference for Li-ion Battery Explosion Risk and Fire Suppression'
    },
    'LCO': {
        'percent_tox': 23.40185,      # Percentage toxic gases (literature-based)
        'percent_flam': 93.92602,     # Percentage flammable gases (literature-based)
        'specific_capacity': 378.135, # L/kWh - specific capacity for module calculations
        'tox_gas_composition': {
            'co': 45.5742,               # Carbon monoxide
            'no2': 11.6029,               # Nitrogen dioxide
            'hcl': 11.6029,               # Hydrogen chloride
            'hf': 4.42584,                # Hydrogen fluoride
            'hcn': 0.83732,               # Hydrogen cyanide
            'benzene': 16.2679,           # Benzene
            'toluene': 4.90431,           # Toluene
            'dec': 1.19617,
            'dmc': 1.19617,
            'propane': 1.19617,
            'xylene': 1.19617
        },
        'description': 'Lithium Cobalt Oxide (LCO) - High energy density, consumer electronics',
        'reference': 'DNV.GL Technical Reference for Li-ion Battery Explosion Risk and Fire Suppression'
    }
}

# ============================================================================
# GAS LABELS AND SETS
# ============================================================================

# Target gases for combined flammability calculations
FLAMMABLE_GASES = {'co_(%)','h2_(%)','total_hydrocarbons_(%)'}

# ============================================================================
# PROPAGATION CONSTANTS
# ============================================================================
# Number of modules that start failing each propagation interval
MODULES_PER_DELAY = 2

# Data for the linear relationship equation between temperature and LFL
CO_TEMPERATURE_LFL_PARAMETER_A = -0.0108
CO_TEMPERATURE_LFL_PARAMETER_B = 12.456

H2_TEMPERATURE_LFL_PARAMETER_A = -0.0120
H2_TEMPERATURE_LFL_PARAMETER_B = 7.2884

THC_TEMPERATURE_LFL_PARAMETER_A = -0.0040
THC_TEMPERATURE_LFL_PARAMETER_B = 5.0990

# ============================================================================
# LEGACY CONSTANTS (for backward compatibility)
# ============================================================================
# Specific capacity by lib type (L/kWh) - used in flammability calculations
LIB_TYPE_SPECIFIC_CAPACITY = {
    'NMC': 458.266894,
    'LFP': 77.23544682,
    'LCO': 378.135
}



# Data sourced from "Chem property data txt" folder text files.
# density: g/L (or kg/m3 as provided in source data, e.g. water in kg/m3)
# erpg_3: ERPG-3 value (ppm, or ppm/percent depending on gas - see source file). None if N/A.
# lfl: Lower Flammable Limit (%). None if N/A / not flammable.
# molecular_weight: g/mol. None if N/A.
CHEMICAL_PROPERTIES = {
    'benzene': {'density': 3.313, 'erpg_3': 3.313, 'lfl': 1.4, 'molecular_weight': 78.11, 'toxicity_factor': 1.0},
    'toluene': {'density': 3.755, 'erpg_3': 3.755, 'lfl': 1.3, 'molecular_weight': 92.13842, 'toxicity_factor': 0.5},
    'co': {'density': 0.967, 'erpg_3': 0.484, 'lfl': 12.5, 'molecular_weight': 28.0101, 'toxicity_factor': 1.0},
    'co2': {'density': 1.830, 'erpg_3': 0.000, 'lfl': None, 'molecular_weight': 44.0095, 'toxicity_factor': 1.0},
    'no2': {'density': 1.890, 'erpg_3': 0.057, 'lfl': None, 'molecular_weight': 46.01, 'toxicity_factor': 1.0},
    'hcl': {'density': 1.517, 'erpg_3': 0.227, 'lfl': None, 'molecular_weight': 36.46, 'toxicity_factor': 1.0},
    'hf': {'density': 0.825, 'erpg_3': 0.041, 'lfl': None, 'molecular_weight': 20.01, 'toxicity_factor': 1.0},
    'hcn': {'density': 1.078, 'erpg_3': 0.027, 'lfl': 5.6, 'molecular_weight': 27.0253, 'toxicity_factor': 1.0},
    'so2': {'molecular_weight': 64.07, 'toxicity_factor': 1.0},
    'c2h5f': {'density': 2.14, 'erpg_3': 260000, 'lfl': 2.6, 'molecular_weight': 48.0601, 'toxicity_factor': 1.0},
    'methanol': {'density': 1.11, 'erpg_3': 145000, 'lfl': 6, 'molecular_weight': 32.042, 'toxicity_factor': 1.0},
    'emc': {'molecular_weight': 88.06, 'toxicity_factor': 1.0},
    'dmc': {'density': 3.1, 'erpg_3': 140, 'lfl': 4.2, 'molecular_weight': 90.08, 'toxicity_factor': 1.0},
    'dec': {'density': 4.1, 'erpg_3': 21, 'lfl': 4.2, 'molecular_weight': 118.13, 'toxicity_factor': 1.0},
    'propane': {'density': 0.86, 'erpg_3': 180000, 'lfl': 2.1, 'molecular_weight': 44.10, 'toxicity_factor': 1.0},
    'xylene': {'density': 3.7, 'erpg_3': 2500, 'lfl': 1.7, 'molecular_weight': 106.17, 'toxicity_factor': 1.0},
    'h2': {'density': 0.084, 'erpg_3': None, 'lfl': 4.0, 'molecular_weight': 2.01588, 'toxicity_factor': 1.0},
    'h2o': {'density': 996.86, 'erpg_3': None, 'lfl': None, 'molecular_weight': 18.015, 'toxicity_factor': 1.0},
    'pf3': {'density': 3.907, 'erpg_3': 10, 'lfl': None, 'molecular_weight': 87.97, 'toxicity_factor': 1.0},
    'ch4': {'density': 0.664, 'erpg_3': None, 'lfl': 4.4, 'molecular_weight': 16.04, 'toxicity_factor': 1.0},
    'total_hydrocarbons': {'density': 3.708, 'erpg_3': 0.000, 'lfl': 6.5, 'molecular_weight': None, 'toxicity_factor': 1.0},
}




def get_chemistry_data(chemistry_type):
    """
    Retrieve data for a specific battery chemistry type.
    
    Parameters:
    -----------
    chemistry_type : str
        Battery chemistry type ('NMC', 'LFP', or 'LCO')
    
    Returns:
    --------
    dict : Dictionary containing percent_tox, percent_flam, and tox_gas_composition
    
    Raises:
    -------
    ValueError : If chemistry_type is not recognized
    """
    chemistry_upper = chemistry_type.upper()
    if chemistry_upper not in BATTERY_CHEMISTRY_DATA:
        raise ValueError(f"Unknown chemistry type: {chemistry_type}. "
                        f"Available types: {list(BATTERY_CHEMISTRY_DATA.keys())}")
    return BATTERY_CHEMISTRY_DATA[chemistry_upper]


def get_percent_tox(chemistry_type):
    """Get the toxic gas percentage for a specific chemistry type."""
    return get_chemistry_data(chemistry_type)['percent_tox']


def get_percent_flam(chemistry_type):
    """Get the flammable gas percentage for a specific chemistry type."""
    return get_chemistry_data(chemistry_type)['percent_flam']


def get_tox_composition(chemistry_type):
    """Get the toxic gas composition dictionary for a specific chemistry type."""
    return get_chemistry_data(chemistry_type)['tox_gas_composition']


def list_available_chemistries():
    """Return a list of all available battery chemistry types."""
    return list(BATTERY_CHEMISTRY_DATA.keys())


def update_chemistry_data(chemistry_type, percent_tox=None, percent_flam=None, tox_gas_composition=None):
    """
    Update data for a specific chemistry type.
    
    Parameters:
    -----------
    chemistry_type : str
        Battery chemistry type to update
    percent_tox : float, optional
        New toxic gas percentage
    percent_flam : float, optional
        New flammable gas percentage
    tox_gas_composition : dict, optional
        New toxic gas composition dictionary
    """
    chemistry_upper = chemistry_type.upper()
    if chemistry_upper not in BATTERY_CHEMISTRY_DATA:
        raise ValueError(f"Unknown chemistry type: {chemistry_type}")
    
    if percent_tox is not None:
        BATTERY_CHEMISTRY_DATA[chemistry_upper]['percent_tox'] = percent_tox
    if percent_flam is not None:
        BATTERY_CHEMISTRY_DATA[chemistry_upper]['percent_flam'] = percent_flam
    if tox_gas_composition is not None:
        BATTERY_CHEMISTRY_DATA[chemistry_upper]['tox_gas_composition'] = tox_gas_composition


def get_specific_capacity(chemistry_type):
    """
    Get the specific capacity (L/kWh) for a specific chemistry type.
    Used in flammability calculations.
    """
    chemistry_upper = chemistry_type.upper()
    return LIB_TYPE_SPECIFIC_CAPACITY.get(chemistry_upper, 0)


# Example usage:
if __name__ == "__main__":
    # Print all available chemistries
    print("Available battery chemistries:", list_available_chemistries())
    
    # Access NMC data
    nmc_data = get_chemistry_data('NMC')
    print("\nNMC Data:")
    print(f"  Toxic %: {nmc_data['percent_tox']}")
    print(f"  Flammable %: {nmc_data['percent_flam']}")
    print(f"  Specific Capacity: {nmc_data['specific_capacity']} L/kWh")
    print(f"  Toxic composition: {nmc_data['tox_gas_composition']}")
    
    # Access specific values using helper functions
    print(f"\nLFP toxic percentage: {get_percent_tox('LFP')}")
    print(f"LCO flammable percentage: {get_percent_flam('LCO')}")
    print(f"LFP specific capacity: {get_specific_capacity('LFP')} L/kWh")
    
    
_THEMES: dict = {
    "Default Light": """
        QWidget            { background-color: #f0f4f8; color: #1a2733; font-size: 13px; }
        QMainWindow        { background-color: #f0f4f8; }
        QMenuBar           { background-color: #dde6f0; color: #1a2733; border-bottom: 1px solid #b0c4d8; }
        QMenuBar::item:selected { background-color: #b8cfea; }
        QMenu              { background-color: #ffffff; border: 1px solid #b0c4d8; color: #1a2733; }
        QMenu::item:selected   { background-color: #b8cfea; }
        QToolBar           { background-color: #dde6f0; border-bottom: 2px solid #b0c4d8; spacing: 6px; padding: 4px; }
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
        QTableWidget       { background-color: #ffffff; gridline-color: #c8d8e8; }
        QHeaderView::section { background-color: #dde6f0; border: 1px solid #b0c4d8; padding: 5px; font-weight: bold; }
        QScrollBar:vertical { background: #e8eef5; width: 12px; }
        QScrollBar::handle:vertical { background: #7aabdb; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #7aabdb; }
    """,
    "Dark": """
        QWidget            { background-color: #1e1e2e; color: #cdd6f4; font-size: 13px; }
        QMainWindow        { background-color: #1e1e2e; }
        QMenuBar           { background-color: #181825; color: #cdd6f4; border-bottom: 1px solid #313244; }
        QMenuBar::item:selected { background-color: #313244; }
        QMenu              { background-color: #181825; border: 1px solid #313244; color: #cdd6f4; }
        QMenu::item:selected   { background-color: #313244; }
        QToolBar           { background-color: #181825; border-bottom: 2px solid #313244; spacing: 6px; padding: 4px; }
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
        QTableWidget       { background-color: #1e1e2e; color: #cdd6f4; gridline-color: #313244; }
        QHeaderView::section { background-color: #313244; border: 1px solid #45475a; padding: 5px; color: #cdd6f4; font-weight: bold; }
        QScrollBar:vertical { background: #181825; width: 12px; }
        QScrollBar::handle:vertical { background: #585b70; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #585b70; }
        QLabel             { color: #cdd6f4; }
    """,
    "Arup Red": """
        QWidget            { background-color: #fafafa; color: #1a1a1a; font-size: 13px; }
        QMainWindow        { background-color: #fafafa; }
        QMenuBar           { background-color: #e8001c; color: #ffffff; border-bottom: 2px solid #b30016; }
        QMenuBar::item:selected { background-color: #b30016; }
        QMenu              { background-color: #ffffff; border: 1px solid #e8001c; color: #1a1a1a; }
        QMenu::item:selected   { background-color: #ffd6d9; }
        QToolBar           { background-color: #f2f2f2; border-bottom: 2px solid #e8001c; spacing: 6px; padding: 4px; }
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
        QTableWidget       { background-color: #ffffff; gridline-color: #f5c6c9; }
        QHeaderView::section { background-color: #ffd6d9; border: 1px solid #e8001c; padding: 5px; font-weight: bold; }
        QScrollBar:vertical { background: #f5f5f5; width: 12px; }
        QScrollBar::handle:vertical { background: #e8001c; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #e8001c; }
    """,
    "High Contrast": """
        QWidget            { background-color: #000000; color: #ffffff; font-size: 13px; }
        QMainWindow        { background-color: #000000; }
        QMenuBar           { background-color: #000000; color: #ffffff; border-bottom: 2px solid #ffffff; }
        QMenuBar::item:selected { background-color: #ffffff; color: #000000; }
        QMenu              { background-color: #000000; border: 2px solid #ffffff; color: #ffffff; }
        QMenu::item:selected   { background-color: #ffffff; color: #000000; }
        QToolBar           { background-color: #000000; border-bottom: 2px solid #ffffff; spacing: 6px; padding: 4px; }
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
        QTableWidget       { background-color: #000000; color: #ffffff; gridline-color: #ffffff; }
        QHeaderView::section { background-color: #333333; border: 1px solid #ffffff; padding: 5px; color: #ffffff; font-weight: bold; }
        QScrollBar:vertical { background: #000000; width: 12px; }
        QScrollBar::handle:vertical { background: #ffffff; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #ffffff; }
        QLabel             { color: #ffffff; }
    """,
    "Warm Slate": """
        QWidget            { background-color: #f5f0eb; color: #2c1f14; font-size: 13px; }
        QMainWindow        { background-color: #f5f0eb; }
        QMenuBar           { background-color: #e8ddd2; color: #2c1f14; border-bottom: 1px solid #c4a882; }
        QMenuBar::item:selected { background-color: #d4bfa0; }
        QMenu              { background-color: #fff8f2; border: 1px solid #c4a882; color: #2c1f14; }
        QMenu::item:selected   { background-color: #e8d5bc; }
        QToolBar           { background-color: #ede4d8; border-bottom: 2px solid #c4a882; spacing: 6px; padding: 4px; }
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
        QTableWidget       { background-color: #fff8f2; gridline-color: #d4bfa0; }
        QHeaderView::section { background-color: #e8ddd2; border: 1px solid #c4a882; padding: 5px; font-weight: bold; }
        QScrollBar:vertical { background: #ede4d8; width: 12px; }
        QScrollBar::handle:vertical { background: #c4a882; border-radius: 5px; min-height: 20px; }
        QFrame[frameShape="5"] { color: #c4a882; }
    """,
}


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

# note that sprinkler RTI is selected in accordance with AS 2118.1:2017.
#see section 1.3.4 of AS2118.1:2017 for more information on sprinkler RTI selection.  
SPRINKLER_PROPERTIES = {
    'sprinkler response time index': {'exposed quick': 50, 'exposed standard': 80, 'concealed quick': 150, 'concealed standard': 234},
    'liquid colour code': {'red': 37, 'yellow': 48, 'green': 62},
    'activation temperatures': {'red': 68, 'yellow': 79, 'green': 93}

}

