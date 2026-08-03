from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTabWidget, QToolBar,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QComboBox, QCheckBox,
    QGridLayout)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QShortcut, QKeySequence
from information import (FIRE_PROPERTIES, COMBINED_INPUTS, POOL_SPREAD_DATA,
    REQ_LIB_INFO, TOOLTIPS, LIB_TYPE, CALCULATION_METHODS, _THEMES,
    POOL_PROPERTIES, BATTERY_CHEMISTRY_DATA, CHEMICAL_PROPERTIES, FLAMMABLE_GASES,
    LIB_TYPE_SPECIFIC_CAPACITY, GAS_LABEL_FIX, COMPOSITION_METHODS)
from pdf import pdf_generation
import numpy as np
import copy
from types import SimpleNamespace
from miscfunc import load_file, import_gas_flowrate_data, generate_input_template
import display_popup as display_popup_module
from resulttable import open_results_table_window
from saveload import save_program_state, load_program_state
from calculations import (
    is_string_field,
    toxicity_assessment_calc,
    flammability_assessment_calc,
    flammability_assessment_calc_graphical_method,
)
from sprinkler import activation_time_Calc


# to do's:
# add a calculation method to the input of the pdf report.
# the result table builder needs ppm and % of the toxixity threshold
# make it so that 1 second timesteps are always used for the quick caluclations. Big time steps can mess it up
# need to decouple timestep from number of printed sheets
# make data tables optional for the pdf export
# add an input into the windows that specifies the project that is being run. Make it optional but helps to track what data is what.
# I want to make emergency ventilation not apart of the spreadhseet inputs but a separate tab to select or something
# add button to delete specifcally results data and not affect the spreadsheet.
# try to integrate a way to use the different calculation methods for different scenario rows as they may have different batteries that require different methods.
# add a safety factor to the ventillation as some decimal which could account for reducing the perfect mixing.
#add an option to toggle a 25% of LFL line to be put in the popup results plots.
# add a way to add command + s shortcut to save current state.


# ---------------------------------------------------------------------------
# Theme definitions – applied globally via QApplication.setStyleSheet().
# Add QPushButton#clearAllButton entries to every theme so the button stays
# visually distinct regardless of the active colour scheme.
# ---------------------------------------------------------------------------
_current_theme = "Warm Slate"  # Default theme applied at startup

# helper functions

def apply_theme(theme_name: str) -> None:
    """Apply a named theme to the whole application by setting the QSS."""
    global _current_theme
    _current_theme = theme_name
    app = QApplication.instance()
    if app:
        app.setStyleSheet(_THEMES.get(theme_name, ""))


def _make_toolbar_separator() -> QFrame:
    """Vertical line widget for visually separating toolbar groups."""
    sep = QFrame()
    sep.setFrameShape(QFrame.VLine)
    sep.setFrameShadow(QFrame.Sunken)
    sep.setFixedWidth(2)
    sep.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    return sep

def return_to_intro_page(current_window):
    current_window.close()
    intro_page = IntroPage()
    intro_page.show()
    return intro_page  # Return the new window instance for further use if needed

def save_file(self):
    save_program_state(self)

def open_file(self):
    load_program_state(self)

def ask_to_close(self):
    reply = QMessageBox.question(self, 'Exit', 'Are you sure you want to exit?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    if reply == QMessageBox.Yes:
        self.close()


def display_toxicity_result_popup(results, tree, gas_labels, gas_data):
    if not results:
        QMessageBox.information(None, "Toxicity Results", "No toxicity results were generated.")
        return

    scenario_names = ", ".join(results.keys())
    QMessageBox.information(
        None,
        "Toxicity Results",
        f"Toxicity assessment completed for {len(results)} scenario(s):\n\n{scenario_names}",
    )


def display_flammability_result_popup(results, tree, gas_data, bat_data, parent=None):
    if not results:
        QMessageBox.information(parent or None, "Flammability Results", "No flammability results were generated.")
        return

    scenario_names = ", ".join(results.keys())
    QMessageBox.information(
        parent or None,
        "Flammability Results",
        f"Flammability assessment completed for {len(results)} scenario(s):\n\n{scenario_names}",
    )

# Override the simple stubs with the richer PySide6 popup implementations
try:
    display_toxicity_result_popup = display_popup_module.display_toxicity_result_popup
    display_flammability_result_popup = display_popup_module.display_flammability_result_popup
except Exception:
    # If import fails, keep the simple QMessageBox-based stubs above
    pass


class BaseWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Charlie's Proprietary LIB Offgas Modelling Tool")
        self.setGeometry(500, 500, 800, 600)
        self.page_stack = QStackedWidget()
        self.setCentralWidget(self.page_stack) #set as central widget of page
        self.page = {}  # store pages by name
        self.page_history = []  # store page history for back button functionality
        self.tox_scenario_results = {}
        self.flam_scenario_results = {}
        self.selected_calc_method = CALCULATION_METHODS[0]
        self.use_le_chatelier_lfl = False
        self.use_temp_dependent_lfl = False
        self.selected_target_flam_gas = "CO"
        self.gas_flowrate_data = None
        self.custom_lib_definitions = {}
        self.custom_composition_definitions = {}
        
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self) # Add Command+S shortcut to save current state
        save_shortcut.activated.connect(lambda: save_file(self))
        
        print_shortcut = QShortcut(QKeySequence("Ctrl+P"), self) # add command+p shortcut to export current sheet to pdf
        print_shortcut.activated.connect(lambda: self.current_page().export_current_sheet_pdf() if hasattr(self.current_page(), 'export_current_sheet_pdf') else None)
        
        self.create_menus()
        
        
    def add_page(self, page_name, page):
        """Register a page with the main window."""

        self.page[page_name] = page
        self.page_stack.addWidget(page)

    def show_page(self, page_name, remember_current=True):
        """Display one of the registered pages."""

        if page_name not in self.page:
            raise ValueError(f"Page '{page_name}' has not been registered.")

        current_page = self.page_stack.currentWidget()
        new_page = self.page[page_name]

        if (
            remember_current
            and current_page is not None
            and current_page is not new_page
        ):
            self.page_history.append(current_page)

        self.page_stack.setCurrentWidget(new_page)

        # Optional page update method
        if hasattr(new_page, "page_shown"):
            new_page.page_shown()

    def go_back(self):
        """Return to the previously displayed page."""

        if self.page_history:
            previous_page = self.page_history.pop()
            self.page_stack.setCurrentWidget(previous_page)
        else:
            self.show_page("IntroPage", remember_current=False)

    def current_page(self):
        """Return the page that is currently displayed."""

        return self.page_stack.currentWidget()

    def create_menus(self):
        menubar = self.menuBar() #menu bar
        backButton = menubar.addAction('Back')# back button
        backButton.triggered.connect(lambda: self.show_page("IntroPage"))
        fileMenu = menubar.addMenu('File')
        dataMenu = menubar.addMenu('Data')
        import_scenarios = dataMenu.addAction('Import Scenarios')
        import_scenarios.triggered.connect(lambda: load_file(self, "battery_data/scenarios.zip"))
        generate_template = dataMenu.addAction('Generate Template')
        generate_template.triggered.connect(lambda checked=False: generate_input_template(self))
        openFile = fileMenu.addAction('Open')
        openFile.triggered.connect(lambda: open_file(self))
        saveFile = fileMenu.addAction('Save')
        saveFile.triggered.connect(lambda: save_file(self))
        exitAction = fileMenu.addAction('Exit')
        exitAction.triggered.connect(lambda: ask_to_close(self))

        themeMenu = menubar.addMenu('Theme')
        for _theme_name in _THEMES:
            _action = themeMenu.addAction(_theme_name)
            _action.triggered.connect(lambda checked=False, t=_theme_name: apply_theme(t))
        
        
class IntroPage(QWidget):
    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window

        # Create a label
        label = QLabel("Welcome to the LIB Off-gassing Calculation Tool.\nPlease choose an option below to proceed.")
        font = label.font()
        font.setPointSize(26)
        font.setBold(True)
        label.setFont(font)
        label.setAlignment(Qt.AlignCenter)

        # button to open main window
        button = QPushButton("LIB Modelling Tool")
        button.setToolTip("Click here to open the LIB Off-gassing Calculation Tool.")
        button.clicked.connect(lambda: self.base_window.show_page("LIBPage"))
        
        # button to open to tutorial window
        button2 = QPushButton("Tutorial")
        button2.setToolTip("Click here to view the tutorial for using the LIB Off-gassing Calculation Tool.")
        button2.clicked.connect(lambda: self.base_window.show_page("TutorialPage"))
        
        #button to open pool spill size and pool fire duration calculator window
        button3 = QPushButton("Pool Spill & Fire Duration Calculator")
        button3.setToolTip("Click here to open the Pool Spill & Fire Duration Calculator.")
        button3.clicked.connect(lambda: self.base_window.show_page("PoolSpillPage"))
        
        button4 = QPushButton("Sprinkler Activation Time")
        button4.setToolTip("Click here to open the Sprinkler Activation Time Calculator.")
        button4.clicked.connect(lambda: self.base_window.show_page("SprinklerPage"))
        
        receptor = QPushButton("Receptor Heat Flux")
        receptor.setToolTip("Click here to open the Receptor Heat Flux Calculator.")
        receptor.clicked.connect(lambda: self.base_window.show_page("ReceptorHeatFluxPage"))

        # Uniform font and size for all four action buttons
        btn_font = QFont()
        btn_font.setPointSize(13)
        btn_font.setBold(True)
        for btn in (button, button2, button3, button4, receptor):
            btn.setMinimumSize(300, 110)
            btn.setFont(btn_font)

        # 2 × 2 grid so the buttons sit together at a consistent size
        btn_grid = QGridLayout()
        btn_grid.setSpacing(16)
        btn_grid.addWidget(button,  0, 0)   # LIB Modelling Tool
        btn_grid.addWidget(button4, 0, 1)   # Sprinkler Activation Time
        btn_grid.addWidget(button3, 1, 0)   # Pool Spill & Fire
        btn_grid.addWidget(button2, 2, 0, 1, 2)   # Tutorial
        btn_grid.addWidget(receptor, 1, 1)  # Receptor Heat Flux (spans two columns)

        # Outer layout: title + button grid
        layout = QVBoxLayout(self)
        layout.setSpacing(28)
        layout.setContentsMargins(50, 36, 50, 36)
        layout.addWidget(label)
        layout.addLayout(btn_grid)
        layout.addStretch()


class LIBDefinitionDialog(QDialog):
    """Dialog for creating a custom LIB type from required LIB input fields."""

    _DEFAULTS = {
        "LFL (%)": "4.0",
        "Battery Charge (%)": "100",
        "CO (%)": "0",
        "CO2 (%)": "0",
        "H2 (%)": "0",
        "Total Hydrocarbons (%)": "0",
    }

    def __init__(self, parent=None, prefill=None):
        super().__init__(parent)
        self._prefill = prefill or {}
        edit_mode = bool(prefill)
        self.setWindowTitle("Edit LIB" if edit_mode else "Add LIB")
        self.setMinimumSize(560, 620)
        self.resize(620, 700)
        self._field_widgets = {}
        self._flowrate_data = self._prefill.get("_flowrate_data")

        root_layout = QVBoxLayout(self)

        title = QLabel("Edit Custom LIB Type" if edit_mode else "Create Custom LIB Type")
        title_font = title.font()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        root_layout.addWidget(title)

        type_form = QFormLayout()
        self.lib_type_name = QLineEdit()
        self.lib_type_name.setPlaceholderText("e.g. VendorX 280Ah")
        self.lib_type_name.setToolTip("Name of the custom LIB type shown in scenario selection")
        if self._prefill.get("lib_type_name"):
            self.lib_type_name.setText(self._prefill["lib_type_name"])
            self.lib_type_name.setReadOnly(True)
        type_form.addRow("LIB Type Name:", self.lib_type_name)
        self.import_flowrate_btn = QPushButton("Import Flowrate Data")
        self.import_flowrate_btn.setToolTip(
            "Import module variable flowrate data to be associated with this custom LIB."
        )
        self.import_flowrate_btn.clicked.connect(self._import_flowrate_data)
        _flowrate_count = len(next(iter(self._flowrate_data.values()), [])) if isinstance(self._flowrate_data, dict) else 0
        self.flowrate_status_label = QLabel(
            f"Flowrate data imported ({_flowrate_count} seconds)." if _flowrate_count else "No flowrate data imported (optional)."
        )
        self.flowrate_status_label.setWordWrap(True)
        type_form.addRow("Variable Flowrate:", self.import_flowrate_btn)
        type_form.addRow("", self.flowrate_status_label)
        self.battery_chemistry_combo = QComboBox()
        self.battery_chemistry_combo.addItems(["NMC", "LFP", "LCO"])
        self.battery_chemistry_combo.setToolTip(
            "Battery chemistry type associated with this LIB."
        )
        prefill_chem = str(self._prefill.get("Battery Chemistry", "NMC") or "NMC").upper()
        idx = self.battery_chemistry_combo.findText(prefill_chem)
        if idx >= 0:
            self.battery_chemistry_combo.setCurrentIndex(idx)
        type_form.addRow("Battery Chemistry:", self.battery_chemistry_combo)
        root_layout.addLayout(type_form)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        form_layout.setHorizontalSpacing(16)
        form_layout.setVerticalSpacing(9)
        form_layout.setContentsMargins(8, 8, 8, 8)

        prefill_inputs = self._prefill.get("inputs", {})
        for label in REQ_LIB_INFO:
            widget = QLineEdit()
            if label in prefill_inputs:
                widget.setText(str(prefill_inputs[label]))
            elif label in self._DEFAULTS:
                widget.setText(self._DEFAULTS[label])
            if label in TOOLTIPS:
                widget.setToolTip(TOOLTIPS[label])
            self._field_widgets[label] = widget
            form_layout.addRow(f"{label}:", widget)

        scroll.setWidget(form_container)
        root_layout.addWidget(scroll, 1)

        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        root_layout.addWidget(btn_box)

    def _import_flowrate_data(self):
        data = import_gas_flowrate_data(self, store_attr=None)
        if data is None:
            return
        self._flowrate_data = data
        sample_count = len(next(iter(data.values()), []))
        self.flowrate_status_label.setText(
            f"Flowrate data imported for this LIB ({sample_count} seconds)."
        )

    def get_payload(self):
        """Return custom LIB name and raw input values from the form."""
        return {
            "lib_type_name": self.lib_type_name.text().strip(),
            "inputs": {k: w.text().strip() for k, w in self._field_widgets.items()},
            "flowrate_data": self._flowrate_data,
            "battery_chemistry": self.battery_chemistry_combo.currentText(),
        }


# ---------------------------------------------------------------------------
# Composition definition dialog
# ---------------------------------------------------------------------------

class CompositionDefinitionDialog(QDialog):
    """Dialog for defining a named gas composition from all tracked chemicals."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Composition")
        self.setMinimumSize(480, 560)
        self.resize(520, 640)
        self._field_widgets = {}

        root_layout = QVBoxLayout(self)

        title = QLabel("Create Gas Composition")
        title_font = title.font()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        root_layout.addWidget(title)

        name_form = QFormLayout()
        self.composition_title = QLineEdit()
        self.composition_title.setPlaceholderText("e.g. NMC Standard Mix")
        self.composition_title.setToolTip("Name of the composition shown in scenario selection")
        name_form.addRow("Composition Title:", self.composition_title)
        root_layout.addLayout(name_form)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        form_layout.setHorizontalSpacing(16)
        form_layout.setVerticalSpacing(9)
        form_layout.setContentsMargins(8, 8, 8, 8)

        for chem_key in CHEMICAL_PROPERTIES:
            label = GAS_LABEL_FIX.get(chem_key, chem_key.replace("_", " ").title())
            widget = QLineEdit()
            widget.setPlaceholderText("0.0")
            widget.setToolTip(f"Percentage of {label} in the vented gas composition (%)")
            self._field_widgets[chem_key] = widget
            form_layout.addRow(f"{label} (%):", widget)

        scroll.setWidget(form_container)
        root_layout.addWidget(scroll, 1)

        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        root_layout.addWidget(btn_box)

    def get_payload(self):
        """Return composition title and chemical percentages."""
        return {
            "composition_title": self.composition_title.text().strip(),
            "chemicals": {k: w.text().strip() for k, w in self._field_widgets.items()},
        }


# ---------------------------------------------------------------------------
# Scenario input dialog
# ---------------------------------------------------------------------------

class ScenarioInputDialog(QDialog):
    """Tabbed form for editing all inputs of a single scenario."""

    _DISPLAY_NAMES = {
        "cell_volume_(l)":       "Cell Volume (L)",
        "cell_duration_(s)":     "Cell Duration (s)",
        "module_volume_(l)":     "Module Volume (L)",
        "module_duration_(s)":   "Module Duration (s)",
        "module_capacity_(kwh)": "Module Capacity (kWh)",
    }

    _EXTRA_TOOLTIPS = {
        "Cells per module":      "Number of cells per module",
        "Modules per unit":      "Number of modules per unit",
        "Calculation Method":    "Calculation pathway used for this scenario.",
        "Use Le Chatelier LFL":  "Use Le Chatelier blending for flammable LFL thresholding.",
        "Use Temperature Dependent LFL": "Adjust gas LFL values using venting temperature.",
        "cell_volume_(l)":       "Volume of a single cell (litres)",
        "cell_duration_(s)":     "Duration of a single cell venting event (s)",
        "module_volume_(l)":     "Volume of a single module (litres)",
        "module_duration_(s)":   "Duration of a single module venting event (s)",
        "module_capacity_(kwh)": "Capacity of a single module (kWh)",
        "LFL (%)": "Lower Flammability Limit of the battery gas mixture (%)",
        "Venting Temperature (°C)": "Temperature of the venting gases (°C) — required for temperature-dependent LFL",
        "Battery Charge (%)":    "State of charge of the battery at start of event",
        "Carbon Monoxide (%)":   "Carbon monoxide fraction of total released gas (%)",
        "Carbon Dioxide (%)":    "Carbon dioxide fraction of total released gas (%)",
        "Hydrogen (%)":          "Hydrogen fraction of total released gas (%)",
        "Total Hydrocarbons (%)":"Total hydrocarbon fraction of total released gas (%)",
        "Manufacturer Name":     "Battery manufacturer name",
        "Battery Room":          "Name or ID of the battery room",
        "Scenario Description":    "Short description of the scenario for identification",
        "Composition Method":       "Method used to determine the gas composition for this scenario",
    }

    _TAB_FIELDS = [
        ("Scenario Info", [
            "Scenario Description",
            "Battery Room",
            "Generated LIB",
            "Composition Method",
            "Gas Composition",
            "Cells per module",
            "Modules per unit",
            "Units",
            "Module Propagation Delay (s)",
            "Calculation Method",
            "Use Le Chatelier LFL",
            "Use Temperature Dependent LFL",
        ]),
        ("Room & Ventilation", [
            "Room Area (m2)",
            "Room Height (m)",
            "Equipment Space (%)",
            "Ventilation Rate (L/s/m2)",
            "Vent Switch Conc (%)",
            "Emergency Vent Rate (L/s/m2)",
            "Calculation Duration (s)",
        ]),
    ]

    _DEFAULTS = {
        "Module Propagation Delay (s)": "180",
        "Battery Charge (%)":           "100",
        "Calculation Duration (s)":     "3600",
        "Calculation Method":           CALCULATION_METHODS[0],
        "Composition Method":           COMPOSITION_METHODS[0],
    }

    def __init__(self, scenario_name: str = "New Scenario", data: dict = None, lib_types=None, lib_definitions=None, composition_options=None, composition_definitions=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Scenario — {scenario_name}")
        self.setMinimumSize(500, 460)
        self.resize(540, 580)
        self._field_widgets: dict = {}
        self._form_labels: dict = {}
        self._lib_types = list(lib_types) if lib_types else list(LIB_TYPE)
        self._lib_definitions = dict(lib_definitions) if lib_definitions else {}
        self._composition_options = list(composition_options) if composition_options else []
        self._composition_definitions = dict(composition_definitions) if composition_definitions else {}

        tabs = QTabWidget()

        for tab_title, fields in self._TAB_FIELDS:
            tab_w = QWidget()
            form = QFormLayout(tab_w)
            form.setHorizontalSpacing(16)
            form.setVerticalSpacing(9)
            form.setContentsMargins(14, 12, 14, 12)

            for field in fields:
                display = self._DISPLAY_NAMES.get(field, field)
                tooltip = (
                    self._EXTRA_TOOLTIPS.get(field)
                    or TOOLTIPS.get(field)
                    or TOOLTIPS.get(field.rstrip(")").rsplit(" (", 1)[0])
                    or ""
                )

                if field == "Generated LIB":
                    w = QComboBox()
                    w.addItem("Missing LIB")
                    if self._lib_types:
                        w.addItems(self._lib_types)
                elif field == "Composition Method":
                    w = QComboBox()
                    w.addItems(COMPOSITION_METHODS)
                    default_method = self._DEFAULTS.get("Composition Method")
                    if default_method:
                        idx = w.findText(default_method)
                        if idx >= 0:
                            w.setCurrentIndex(idx)
                elif field == "Gas Composition":
                    w = QComboBox()
                    w.addItem("None")
                    if self._composition_options:
                        w.addItems(self._composition_options)
                    w.setToolTip("Named composition created via Add Composition (used when Composition Method is 'User Defined').")
                elif field == "Calculation Method":
                    w = QComboBox()
                    w.addItems(CALCULATION_METHODS)
                    default_method = self._DEFAULTS.get("Calculation Method")
                    if default_method:
                        default_index = w.findText(default_method)
                        if default_index >= 0:
                            w.setCurrentIndex(default_index)
                elif field in ("Use Le Chatelier LFL", "Use Temperature Dependent LFL"):
                    w = QCheckBox()
                else:
                    w = QLineEdit()
                    if not is_string_field(field):
                        w.setPlaceholderText("0.0")
                    # Apply default only for new scenarios without loaded data
                    if data is None and field in self._DEFAULTS:
                        w.setText(self._DEFAULTS[field])

                if tooltip:
                    w.setToolTip(tooltip)
                self._field_widgets[field] = w
                form.addRow(display + ":", w)
                # Track the label widget for dynamic show/hide
                row_num = form.rowCount() - 1
                label_item = form.itemAt(row_num, QFormLayout.LabelRole)
                if label_item and label_item.widget():
                    self._form_labels[field] = label_item.widget()

            tabs.addTab(tab_w, tab_title)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(btn_box)

        if data:
            self._load_data(data)

        # Connect Composition Method to Gas Composition row visibility
        comp_method_w = self._field_widgets.get("Composition Method")
        if isinstance(comp_method_w, QComboBox):
            comp_method_w.currentTextChanged.connect(self._update_composition_visibility)
        self._update_composition_visibility(
            comp_method_w.currentText() if isinstance(comp_method_w, QComboBox) else ""
        )

    def _update_composition_visibility(self, method_text: str = ""):
        """Show Gas Composition row only when Composition Method is 'User Defined'."""
        show = (method_text == "User Defined")
        for key in ("Gas Composition",):
            w = self._field_widgets.get(key)
            lbl = self._form_labels.get(key)
            if w:
                w.setVisible(show)
            if lbl:
                lbl.setVisible(show)

    def _load_data(self, data: dict):
        for field, w in self._field_widgets.items():
            if field == "Generated LIB":
                val = data.get("Generated LIB", data.get("LIB Type", ""))
            else:
                val = data.get(field, "")
            if isinstance(w, QComboBox):
                idx = w.findText(str(val) if val else "")
                if idx >= 0:
                    w.setCurrentIndex(idx)
            elif isinstance(w, QCheckBox):
                if isinstance(val, str):
                    w.setChecked(val.strip().lower() in {"1", "true", "yes", "on"})
                else:
                    w.setChecked(bool(val))
            else:
                w.setText("" if (val is None or val == "") else str(val))

    def accept(self):
        super().accept()

    def get_data(self) -> dict:
        """Return {COMBINED_INPUTS field label: raw string value}."""
        result = {}
        for field, w in self._field_widgets.items():
            if isinstance(w, QComboBox):
                result[field] = w.currentText()
            elif isinstance(w, QCheckBox):
                result[field] = bool(w.isChecked())
            else:
                result[field] = w.text().strip()

        selected_generated_lib = str(result.get("Generated LIB", "") or "").strip()
        if selected_generated_lib == "No custom LIBs added":
            selected_generated_lib = "Missing LIB"
        result["LIB Type"] = selected_generated_lib

        selected_lib = selected_generated_lib
        custom_lib = self._lib_definitions.get(selected_lib)
        if custom_lib:
            result["_custom_lib_data"] = dict(custom_lib)

        selected_composition = str(result.get("Gas Composition", "") or "").strip()
        if selected_composition and selected_composition != "None":
            comp_data = self._composition_definitions.get(selected_composition)
            if comp_data:
                result["_composition_data"] = dict(comp_data)
        return result


# ---------------------------------------------------------------------------
# Scenario tree — three-level hierarchy: Project → Type → Scenario
# ---------------------------------------------------------------------------

class ProjectTreeItem(QTreeWidgetItem):
    """Top-level project node."""

    def __init__(self, name: str = "My Project"):
        super().__init__()
        self.project_name = name
        self._refresh()

    def _refresh(self):
        self.setText(0, f"\u25b6  {self.project_name}")

    def rename(self, new_name: str):
        self.project_name = new_name
        self._refresh()


class ScenarioTypeTreeItem(QTreeWidgetItem):
    """Mid-level scenario-type / category node."""

    def __init__(self, name: str = "New Type"):
        super().__init__()
        self.type_name = name
        self._refresh()

    def _refresh(self):
        self.setText(0, f"    \u25b7  {self.type_name}")

    def rename(self, new_name: str):
        self.type_name = new_name
        self._refresh()


class ScenarioTreeItem(QTreeWidgetItem):
    """Leaf node: one runnable scenario with its full input data dict."""

    def __init__(self, name: str = "New Scenario", data: dict = None):
        super().__init__()
        self.scenario_name = name
        self.scenario_data: dict = data if data is not None else {}
        self._refresh()

    def _refresh(self):
        self.setText(0, f"        \u2014  {self.scenario_name}")

    def rename(self, new_name: str):
        self.scenario_name = new_name
        self._refresh()


class ScenarioTreeWidget(QWidget):
    """Left-panel hierarchy tree: Project → Scenario Type → Scenario."""

    def __init__(self, lib_type_provider=None, lib_definition_provider=None, composition_provider=None, composition_definition_provider=None, parent=None):
        super().__init__(parent)
        self._lib_type_provider = lib_type_provider
        self._composition_provider = composition_provider
        self._composition_definition_provider = composition_definition_provider
        self._lib_definition_provider = lib_definition_provider
        self._clipboard_scenario: dict = None  # Clipboard for copy/paste
        self._clipboard_scenario_name: str = None  # Store the original scenario name
        self.setObjectName("scenarioTreeWidget")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumWidth(220)
        self.setMaximumWidth(420)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setObjectName("scenarioTreeHeader")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 5, 8, 5)
        h_layout.setSpacing(4)
        title_lbl = QLabel("Scenarios")
        _f = title_lbl.font()
        _f.setBold(True)
        _f.setPointSize(10)
        title_lbl.setFont(_f)
        add_proj_btn = QPushButton("Add Project")
        add_proj_btn.setFixedHeight(24)
        add_proj_btn.setToolTip("Add a new top-level project")
        add_proj_btn.clicked.connect(lambda: self._add_project())
        add_sub_section = QPushButton("+")
        add_sub_section.setFixedHeight(24)
        add_sub_section.setToolTip("Add a sub-section")
        add_sub_section.clicked.connect(lambda: self._add_sub_section())
        h_layout.addWidget(title_lbl)
        h_layout.addStretch()
        h_layout.addWidget(add_proj_btn)
        h_layout.addWidget(add_sub_section)
        root_layout.addWidget(header)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setObjectName("scenarioTreeInner")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setFocusPolicy(Qt.StrongFocus)
        root_layout.addWidget(self.tree)

        # Keyboard shortcuts
        QShortcut(QKeySequence.Copy, self.tree, self._copy_scenario)
        QShortcut(QKeySequence.Paste, self.tree, self._paste_scenario)

        self._add_project("My Project")

    # ------------------------------------------------------------------
    # Tree-building actions
    # ------------------------------------------------------------------

    def _add_project(self, name: str = None):
        if name is None:
            name, ok = QInputDialog.getText(self, "New Project", "Project name:")
            if not ok or not name.strip():
                return
            name = name.strip()
        item = ProjectTreeItem(name)
        self.tree.addTopLevelItem(item)
        item.setExpanded(True)

    def _add_scenario_type(self, project_item: ProjectTreeItem): #this lets the user add a scenario types such as the room to separate scenarios per project.
        name, ok = QInputDialog.getText(self, "New Scenario Type", "Scenario type name:")
        if not ok or not name.strip():
            return
        child = ScenarioTypeTreeItem(name.strip())
        project_item.addChild(child)
        project_item.setExpanded(True)
        child.setExpanded(True)

    def _add_scenario(self, type_item: ScenarioTypeTreeItem): #lets the user add a scenario to the selected scenario type
        name, ok = QInputDialog.getText(self, "New Scenario", "Scenario name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        leaf = ScenarioTreeItem(name, data={"Scenario Description": name})
        type_item.addChild(leaf)
        type_item.setExpanded(True)
        self._edit_scenario(leaf)

    def _add_sub_section(self): # this lets the user add either a subsection or scenario depending on which item level is selected.
        item = self.tree.currentItem()
        if isinstance(item, ProjectTreeItem):
            self._add_scenario_type(item)
        elif isinstance(item, ScenarioTypeTreeItem):
            self._add_scenario(item)
        else:
            QMessageBox.information(self, "Add Sub-section", "Select a project or scenario type to add a sub-section.")

    def _edit_scenario(self, item: ScenarioTreeItem):
        dlg = ScenarioInputDialog(
            scenario_name=item.scenario_name,
            data=item.scenario_data,
            lib_types=self.get_available_lib_types(),
            lib_definitions=self.get_custom_lib_definitions(),
            composition_options=self.get_available_compositions(),
            composition_definitions=self.get_composition_definitions(),
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            item.scenario_data = dlg.get_data()
            desc = item.scenario_data.get("Scenario Description", "").strip()
            if desc:
                item.scenario_name = desc
                item._refresh()

    def _rename_item(self, item):
        if isinstance(item, ProjectTreeItem):
            current = item.project_name
        elif isinstance(item, ScenarioTypeTreeItem):
            current = item.type_name
        elif isinstance(item, ScenarioTreeItem):
            current = item.scenario_name
        else:
            return
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=current)
        if ok and new_name.strip():
            item.rename(new_name.strip())

    def _delete_item(self, item):
        reply = QMessageBox.question(
            self, "Delete", f"Delete '{item.text(0).strip()}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            parent = item.parent()
            if parent is None:
                idx = self.tree.indexOfTopLevelItem(item)
                self.tree.takeTopLevelItem(idx)
            else:
                parent.removeChild(item)

    def _duplicate_scenario(self, item: ScenarioTreeItem):
        import copy
        new_item = ScenarioTreeItem(
            f"{item.scenario_name} (copy)",
            data=copy.deepcopy(item.scenario_data),
        )
        parent = item.parent()
        if parent:
            parent.addChild(new_item)

    def _copy_scenario(self):
        """Copy the selected scenario to the clipboard."""
        item = self.tree.currentItem()
        if isinstance(item, ScenarioTreeItem):
            self._clipboard_scenario = copy.deepcopy(item.scenario_data)
            self._clipboard_scenario_name = item.scenario_name

    def _paste_scenario(self):
        """Paste the scenario from clipboard to the selected scenario type."""
          
        item = self.tree.currentItem()
        if isinstance(item, ScenarioTypeTreeItem):
            # Paste into the selected scenario type
            new_name, ok = QInputDialog.getText(
                self, 
                "Paste Scenario", 
                "Enter name for pasted scenario:",
                text=f"{self._clipboard_scenario_name}"
            )
            if ok and new_name.strip():
                new_name = new_name.strip()
                new_item = ScenarioTreeItem(
                    new_name,
                    data=copy.deepcopy(self._clipboard_scenario)
                )
                # Update the Scenario Description to match the new name
                new_item.scenario_data["Scenario Description"] = new_name
                item.addChild(new_item)
                item.setExpanded(True)

        elif isinstance(item, ScenarioTreeItem):
            # If a scenario is selected, use its parent type
            parent = item.parent()
            if isinstance(parent, ScenarioTypeTreeItem):
                new_name, ok = QInputDialog.getText(
                    self, 
                    "Paste Scenario", 
                    "Enter name for pasted scenario:",
                    text=f"{self._clipboard_scenario_name}"
                )
                if ok and new_name.strip():
                    new_name = new_name.strip()
                    new_item = ScenarioTreeItem(
                        new_name,
                        data=copy.deepcopy(self._clipboard_scenario)
                    )
                    # Update the Scenario Description to match the new name
                    new_item.scenario_data["Scenario Description"] = new_name
                    parent.addChild(new_item)
                    parent.setExpanded(True)

        else:
            QMessageBox.warning(
                self, 
                "Cannot Paste", 
                "Please select a scenario type to paste into."
            )

    # ------------------------------------------------------------------
    # Context menu and double-click
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)

        if item is None:
            menu.addAction("Add Project", lambda: self._add_project())
        elif isinstance(item, ProjectTreeItem):
            menu.addAction("Add Scenario Type", lambda: self._add_scenario_type(item))
            menu.addSeparator()
            menu.addAction("Rename", lambda: self._rename_item(item))
            menu.addAction("Delete Project", lambda: self._delete_item(item))
        elif isinstance(item, ScenarioTypeTreeItem):
            menu.addAction("Add Scenario", lambda: self._add_scenario(item))
            menu.addSeparator()
            if self._clipboard_scenario is not None:
                menu.addAction("Paste Scenario (Ctrl+V)", lambda: self._paste_scenario())
                menu.addSeparator()
            menu.addAction("Rename", lambda: self._rename_item(item))
            menu.addAction("Delete Type", lambda: self._delete_item(item))
        elif isinstance(item, ScenarioTreeItem):
            menu.addAction("Edit Inputs", lambda: self._edit_scenario(item))
            menu.addAction("Duplicate", lambda: self._duplicate_scenario(item))
            menu.addSeparator()
            menu.addAction("Copy Scenario (Ctrl+C)", lambda: self._copy_scenario())
            if self._clipboard_scenario is not None:
                menu.addAction("Paste Scenario (Ctrl+V)", lambda: self._paste_scenario())
            menu.addSeparator()
            menu.addAction("Rename", lambda: self._rename_item(item))
            menu.addAction("Delete Scenario", lambda: self._delete_item(item))

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_double_click(self, item, _column):
        if isinstance(item, ScenarioTreeItem):
            self._edit_scenario(item)
        else:
            self._rename_item(item)

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    def collect_all_scenarios(self) -> list:
        """Return list of data dicts for every ScenarioTreeItem leaf."""
        scenarios = []
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            proj = root.child(i)
            for j in range(proj.childCount()):
                stype = proj.child(j)
                for k in range(stype.childCount()):
                    leaf = stype.child(k)
                    if isinstance(leaf, ScenarioTreeItem):
                        scenarios.append(leaf.scenario_data)
        return scenarios

    def _collect_scenarios_under_item(self, item) -> list:
        """Return all ScenarioTreeItem data found under *item* (inclusive)."""
        if item is None:
            return []
        if isinstance(item, ScenarioTreeItem):
            return [item.scenario_data]

        scenarios = []
        for child_index in range(item.childCount()):
            child_item = item.child(child_index)
            scenarios.extend(self._collect_scenarios_under_item(child_item))
        return scenarios

    def collect_selected_scenarios(self) -> list:
        """Return scenarios based on current tree selection.

        Selection behavior:
        - Scenario leaf selected: run only that scenario.
        - Scenario type selected: run all scenarios within that type.
        - Project selected: run all scenarios in that project.
        - Nothing selected: run all scenarios across all projects.
        """
        selected_item = self.tree.currentItem()
        if selected_item is None:
            return self.collect_all_scenarios()

        selected_scenarios = self._collect_scenarios_under_item(selected_item)
        if selected_scenarios:
            return selected_scenarios
        return self.collect_all_scenarios()

    def get_available_lib_types(self):
        """Return current LIB type options for scenario dialogs."""
        if callable(self._lib_type_provider):
            try:
                values = list(self._lib_type_provider())
                if values:
                    return values
            except Exception:
                pass
        return list(LIB_TYPE)

    def get_custom_lib_definitions(self):
        """Return custom LIB definitions keyed by LIB Type name."""
        if callable(self._lib_definition_provider):
            try:
                data = self._lib_definition_provider()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def get_available_compositions(self):
        """Return current composition names for scenario dialogs."""
        if callable(self._composition_provider):
            try:
                values = list(self._composition_provider())
                if values:
                    return values
            except Exception:
                pass
        return []

    def get_composition_definitions(self):
        """Return composition definitions keyed by composition title."""
        if callable(self._composition_definition_provider):
            try:
                data = self._composition_definition_provider()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}


class LIBPage(QWidget):
    _CUSTOM_LIB_SCENARIO_KEY_MAP = {
        "Manufacturer name": ["manufacturer_name", "Manufacturer Name"],
        "Battery room": ["battery_room", "Battery Room"],
        "LFL (%)": ["LFL (%)", "lfl_(%)"],
        "Cell Duration (s)": ["cell_duration_(s)"],
        "Module Duration (s)": ["module_duration_(s)"],
        "Venting Temperature (°C)": ["Venting Temperature (°C)", "venting_temperature_(°C)"],
        "Module Capacity (kWh)": ["module_capacity_(kwh)"],
        "Cell Volume (L)": ["cell_volume_(l)"],
        "Module Volume (L)": ["module_volume_(l)"],
        "Battery Charge (%)": ["Battery Charge (%)"],
        "CO (%)": ["co_(%)", "Carbon Monoxide (%)"],
        "CO2 (%)": ["co2_(%)", "Carbon Dioxide (%)", "CO2 (%)"],
        "H2 (%)": ["h2_(%)", "Hydrogen (%)"],
        "Total Hydrocarbons (%)": ["total_hydrocarbons_(%)", "Total Hydrocarbons (%)"],
    }

    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window
        self._results_summary_widgets: dict = {}
        self._result_tab_meta: dict = {}
        self._result_entry_counter = 0

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Toolbar ---
        toolbar = QToolBar("LIB Offgassing Calculation Tool")
        toolbar.setMovable(False)
        toolbarcontents = QWidget()
        toolbarlayout = QHBoxLayout()
        toolbarcontents.setLayout(toolbarlayout)
        toolbar.addWidget(toolbarcontents)

        add_lib = QPushButton("Add LIB")
        add_lib.setToolTip("Create a custom LIB type from required LIB inputs.")
        add_lib.clicked.connect(self.open_add_lib_dialog)

        edit_lib = QPushButton("Edit LIB")
        edit_lib.setToolTip("Edit an existing user-defined custom LIB type.")
        edit_lib.clicked.connect(self.open_edit_lib_dialog)

        add_composition = QPushButton("Add Composition")
        add_composition.setToolTip("Create a named gas composition from chemical percentages.")
        add_composition.clicked.connect(self.open_add_composition_dialog)

        flam_calc = QPushButton("Flam Calc")
        flam_calc.setToolTip("Calculate the flammability assessment for the current scenarios.")
        flam_calc.clicked.connect(self.run_flam_calc)

        tox_calc = QPushButton("Tox Calc")
        tox_calc.setToolTip("Calculate the toxicity assessment for the current scenarios.")
        tox_calc.clicked.connect(self.run_tox_calc)

        clear_all = QPushButton("Clear All")
        clear_all.setObjectName("clearAllButton")
        clear_all.setToolTip("Clear all calculation results.")
        clear_all.clicked.connect(self.clear_results)

        export_to_pdf = QPushButton("Export PDF Report")
        export_to_pdf.setToolTip("Export a PDF report of the current scenarios and results.")
        export_to_pdf.clicked.connect(self.export_current_sheet_pdf)

        results_table = QPushButton("Results Table")
        results_table.setToolTip("Open the results table builder for the current calculation results.")
        results_table.clicked.connect(self.open_results_table)

        toolbarlayout.addWidget(add_lib)
        toolbarlayout.addWidget(edit_lib)
        toolbarlayout.addWidget(add_composition)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(flam_calc)
        toolbarlayout.addWidget(tox_calc)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(clear_all)
        toolbarlayout.addWidget(export_to_pdf)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(results_table)
        main_layout.addWidget(toolbar)

        # --- Body: vertical splitter (middle | bottom summary strip) ---
        body_splitter = QSplitter(Qt.Vertical)
        body_splitter.setChildrenCollapsible(False)
        main_layout.addWidget(body_splitter)

        # Middle: horizontal splitter (scenario tree | results plot)
        middle_splitter = QSplitter(Qt.Horizontal)
        middle_splitter.setChildrenCollapsible(False)
        body_splitter.addWidget(middle_splitter)

        self.scenario_tree = ScenarioTreeWidget(
            lib_type_provider=self.get_available_lib_types,
            lib_definition_provider=self.get_custom_lib_definitions,
            composition_provider=self.get_available_compositions,
            composition_definition_provider=self.get_composition_definitions,
        )
        middle_splitter.addWidget(self.scenario_tree)
        middle_splitter.setStretchFactor(0, 0)

        self.results_tabs = QTabWidget()
        self.results_tabs.setTabPosition(QTabWidget.North)
        self.results_tabs.setTabsClosable(True)
        self.results_tabs.currentChanged.connect(self._on_results_tab_changed)
        self.results_tabs.tabBarClicked.connect(self._on_results_tab_clicked)
        self.results_tabs.tabCloseRequested.connect(self._close_result_tab)
        _ph = QLabel("Run a calculation to view results here.")
        _ph.setAlignment(Qt.AlignCenter)
        self.results_tabs.addTab(_ph, "Results")
        middle_splitter.addWidget(self.results_tabs)
        middle_splitter.setStretchFactor(1, 1)
        middle_splitter.setSizes([280, 900])

        # Bottom: scrollable summary strip
        self.summary_scroll = QScrollArea()
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setMinimumHeight(130)
        self.summary_scroll.setMaximumHeight(220)
        self.summary_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.summary_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        _sph = QLabel("Summary results will appear here after running a calculation.")
        _sph.setAlignment(Qt.AlignCenter)
        self.summary_scroll.setWidget(_sph)
        body_splitter.addWidget(self.summary_scroll)

        body_splitter.setSizes([10000, 160])
        body_splitter.setStretchFactor(0, 1)
        body_splitter.setStretchFactor(1, 0)

    # ------------------------------------------------------------------
    # Scenario data — collected from the tree at calc time
    # ------------------------------------------------------------------

    def get_available_lib_types(self):
        """Return user-generated LIB type names in stable order."""
        names = []
        seen = set()
        for name in list(self.base_window.custom_lib_definitions.keys()):
            if name and name not in seen:
                names.append(name)
                seen.add(name)
        return names

    def get_custom_lib_definitions(self):
        """Return all custom LIB definitions keyed by LIB Type name."""
        return dict(getattr(self.base_window, "custom_lib_definitions", {}) or {})

    def get_available_compositions(self):
        """Return user-created composition names in stable order."""
        names = []
        seen = set()
        for name in list(getattr(self.base_window, "custom_composition_definitions", {}).keys()):
            if name and name not in seen:
                names.append(name)
                seen.add(name)
        return names

    def get_composition_definitions(self):
        """Return all composition definitions keyed by composition title."""
        return dict(getattr(self.base_window, "custom_composition_definitions", {}) or {})

    def _apply_custom_lib_to_scenario(self, scenario):
        """Overlay scenario values from selected custom LIB definition."""
        if not isinstance(scenario, dict):
            return scenario

        output = dict(scenario)
        selected_lib = str(output.get("LIB Type", "") or "").strip()
        custom_lib = self.base_window.custom_lib_definitions.get(selected_lib)
        if not custom_lib:
            custom_lib = output.get("_custom_lib_data")
        if not isinstance(custom_lib, dict):
            return output

        for src_key, target_keys in self._CUSTOM_LIB_SCENARIO_KEY_MAP.items():
            value = custom_lib.get(src_key)
            if value in (None, ""):
                continue
            for target_key in target_keys:
                output[target_key] = value

        lib_flowrate_data = custom_lib.get("_flowrate_data")
        if isinstance(lib_flowrate_data, dict):
            output["_lib_flowrate_data"] = lib_flowrate_data
        return output

    def _calculation_scenarios(self):
        """Return selection-scoped scenarios with custom LIB/composition data merged in."""
        scenarios = self.scenario_tree.collect_selected_scenarios()
        merged = [self._apply_custom_lib_to_scenario(s) for s in scenarios]
        return [self._apply_composition_to_scenario(s) for s in merged]

    def _apply_composition_to_scenario(self, scenario):
        """Apply gas composition based on the selected Composition Method."""
        if not isinstance(scenario, dict):
            return scenario

        output = dict(scenario)
        composition_method = str(output.get("Composition Method", "") or "").strip()
        lib_type = str(output.get("LIB Type", "") or "").strip().upper()

        if composition_method == "Literature Data":
            # Resolve the base chemistry (NMC/LFP/LCO) for custom LIBs so that
            # both flam and tox data come from BATTERY_CHEMISTRY_DATA, not the
            # custom LIB entry (which stores flam gases as tox_gas_composition).
            selected_lib_name = str(output.get("LIB Type", "") or "").strip()
            custom_lib_def = self.base_window.custom_lib_definitions.get(selected_lib_name) or {}
            base_chemistry = str(custom_lib_def.get("Battery Chemistry", selected_lib_name) or selected_lib_name).upper()
            base_chem_data = BATTERY_CHEMISTRY_DATA.get(base_chemistry, BATTERY_CHEMISTRY_DATA.get("NMC", {}))
            flam_comp = base_chem_data.get("flam_gas_composition", {})
            output.update(flam_comp)
            output["_flam_percent_override"] = base_chem_data.get("percent_flam", 100.0)
            output["_tox_gas_composition_override"] = base_chem_data.get("tox_gas_composition", {})
            output["_percent_tox_override"] = base_chem_data.get("percent_tox", 100.0)

        elif composition_method == "UL9540A Flam Data":
            # Flam: CO/H2/THC already merged from LIB definition via _apply_custom_lib_to_scenario.
            # Tox: resolve from base chemistry (NMC/LFP/LCO) so the correct toxic gases are used.
            selected_lib_name = str(output.get("LIB Type", "") or "").strip()
            custom_lib_def = self.base_window.custom_lib_definitions.get(selected_lib_name) or {}
            base_chemistry = str(custom_lib_def.get("Battery Chemistry", selected_lib_name) or selected_lib_name).upper()
            base_chem_data = BATTERY_CHEMISTRY_DATA.get(base_chemistry, BATTERY_CHEMISTRY_DATA.get("NMC", {}))
            output["_tox_gas_composition_override"] = base_chem_data.get("tox_gas_composition", {})
            output["_percent_tox_override"] = base_chem_data.get("percent_tox", 100.0)

            # Flam volumes = total_volume * percent_flam (from chemistry data) * user_gas_percent.
            # User CO/H2/THC percentages are used directly — not normalised — so each gas
            # volume is: mod_vol * chemistry_flam_fraction * (user_percent / 100).
            chemistry_flam_percent = self._to_float(base_chem_data.get("percent_flam"), 0.0)
            if chemistry_flam_percent > 0:
                output["_flam_percent_override"] = chemistry_flam_percent

        elif composition_method == "User Defined":
            selected_comp = str(output.get("Gas Composition", "") or "").strip()
            comp_data = None
            if selected_comp and selected_comp != "None":
                comp_data = getattr(self.base_window, "custom_composition_definitions", {}).get(selected_comp)
                if not comp_data:
                    comp_data = output.get("_composition_data")

            if isinstance(comp_data, dict):
                tox_comp = {}
                flam_comp = {}
                for chem_key, val in comp_data.items():
                    if val in (None, "") or str(val).strip() == "":
                        continue
                    try:
                        float_val = float(str(val))
                    except (ValueError, TypeError):
                        continue
                    if float_val == 0:
                        continue
                    chem_props = CHEMICAL_PROPERTIES.get(chem_key, {})
                    if chem_props.get("toxicity_factor", 0) == 1:
                        tox_comp[chem_key] = float_val
                    if chem_props.get("flammability_factor", 0) == 1:
                        flam_comp[chem_key] = float_val

                if tox_comp:
                    output["_tox_gas_composition_override"] = tox_comp
                    # percent_tox = 100 so tox_mod_vol = mod_vol; each gas fraction
                    # (tox_i/100) then gives volume = total_volume * tox_i/100 directly.
                    output["_percent_tox_override"] = 100

                if flam_comp:
                    total_flam_percent = sum(flam_comp.values())
                    output["_flam_percent_override"] = total_flam_percent
                    _FLAM_KEY_MAP = {
                        "co":                 ("co_(%)", "Carbon Monoxide (%)"),
                        "h2":                 ("h2_(%)", "Hydrogen (%)"),
                        "total_hydrocarbons": ("total_hydrocarbons_(%)", "Total Hydrocarbons (%)"),
                    }
                    if total_flam_percent > 0:
                        for chem_key, target_keys in _FLAM_KEY_MAP.items():
                            if chem_key in flam_comp:
                                split_percent = (flam_comp[chem_key] / total_flam_percent) * 100.0
                                for t in target_keys:
                                    output[t] = split_percent

                output["_composition_data"] = comp_data

        else:
            # Fallback: apply Gas Composition selection (backward compatibility)
            selected_comp = str(output.get("Gas Composition", "") or "").strip()
            if selected_comp and selected_comp != "None":
                comp_data = getattr(self.base_window, "custom_composition_definitions", {}).get(selected_comp)
                if not comp_data:
                    comp_data = output.get("_composition_data")
                if isinstance(comp_data, dict):
                    _COMP_MAP = {
                        "co":                 ["Carbon Monoxide (%)", "co_(%)"],
                        "co2":                ["Carbon Dioxide (%)",  "co2_(%)"],
                        "h2":                 ["Hydrogen (%)",        "h2_(%)"],
                        "total_hydrocarbons": ["Total Hydrocarbons (%)", "total_hydrocarbons_(%)"],
                    }
                    for chem_key, target_keys in _COMP_MAP.items():
                        value = comp_data.get(chem_key)
                        if value in (None, ""):
                            continue
                        for target_key in target_keys:
                            output[target_key] = value
                    output["_composition_data"] = comp_data

        return output

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _build_custom_chemistry(self, lib_type_name, raw_inputs):
        """Convert popup inputs into chemistry data used by calculations."""
        co = self._to_float(raw_inputs.get("CO (%)"), 0.0)
        co2 = self._to_float(raw_inputs.get("CO2 (%)"), 0.0)
        h2 = self._to_float(raw_inputs.get("H2 (%)"), 0.0)
        thc = self._to_float(raw_inputs.get("Total Hydrocarbons (%)"), 0.0)
        battery_chemistry = str(raw_inputs.get("Battery Chemistry", "NMC") or "NMC").upper()

        percent_flam = max(0.0, co + h2 + thc)
        if percent_flam == 0.0:
            percent_flam = 100.0

        return {
            "percent_tox": 100.0,
            "percent_flam": percent_flam,
            "specific_capacity": LIB_TYPE_SPECIFIC_CAPACITY.get(battery_chemistry, LIB_TYPE_SPECIFIC_CAPACITY.get("NMC", 458.266894)),
            "tox_gas_composition": {
                "co": co,
                "co2": co2,
                "h2": h2,
                "total_hydrocarbons": thc,
            },
            "description": f"Custom LIB definition: {lib_type_name}",
            "reference": "User-defined via Add LIB dialog",
        }

    def _register_custom_lib(self, lib_type_name, raw_inputs):
        """Register one custom LIB across UI selection and calculation registries."""
        if lib_type_name not in LIB_TYPE:
            LIB_TYPE.append(lib_type_name)

        battery_chemistry = str(raw_inputs.get("Battery Chemistry", "NMC") or "NMC").upper()
        BATTERY_CHEMISTRY_DATA[lib_type_name.upper()] = self._build_custom_chemistry(lib_type_name, raw_inputs)
        LIB_TYPE_SPECIFIC_CAPACITY[lib_type_name.upper()] = LIB_TYPE_SPECIFIC_CAPACITY.get(battery_chemistry, LIB_TYPE_SPECIFIC_CAPACITY.get("NMC", 458.266894))

    def sync_custom_lib_registry(self):
        """Synchronize in-memory custom LIB definitions into runtime registries."""
        custom_libs = getattr(self.base_window, "custom_lib_definitions", {}) or {}
        if not isinstance(custom_libs, dict):
            return

        for lib_type_name, raw_inputs in custom_libs.items():
            if not lib_type_name or not isinstance(raw_inputs, dict):
                continue
            self._register_custom_lib(lib_type_name, raw_inputs)

    def open_edit_lib_dialog(self):
        """Select a user-defined LIB then edit it via a prefilled LIBDefinitionDialog."""
        custom_libs = self.base_window.custom_lib_definitions
        if not custom_libs:
            QMessageBox.information(self, "Edit LIB", "No custom LIBs have been added yet.")
            return

        dlg_select = QDialog(self)
        dlg_select.setWindowTitle("Select LIB to Edit")
        dlg_select.setMinimumWidth(360)
        layout = QVBoxLayout(dlg_select)
        layout.addWidget(QLabel("Select a custom LIB to edit:"))
        combo = QComboBox()
        combo.addItems(sorted(custom_libs.keys()))
        layout.addWidget(combo)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dlg_select.accept)
        btn_box.rejected.connect(dlg_select.reject)
        layout.addWidget(btn_box)

        if dlg_select.exec() != QDialog.Accepted:
            return

        selected_name = combo.currentText()
        raw_inputs = custom_libs.get(selected_name, {})

        prefill = {
            "lib_type_name": selected_name,
            "inputs": {k: v for k, v in raw_inputs.items() if not k.startswith("_") and k != "Battery Chemistry"},
            "Battery Chemistry": raw_inputs.get("Battery Chemistry", "NMC"),
            "_flowrate_data": raw_inputs.get("_flowrate_data"),
        }

        dlg = LIBDefinitionDialog(self, prefill=prefill)
        if dlg.exec() != QDialog.Accepted:
            return

        payload = dlg.get_payload()
        new_inputs = dict(payload.get("inputs", {}))
        new_inputs["Battery Chemistry"] = payload.get("battery_chemistry", "NMC")
        flowrate_data = payload.get("flowrate_data")
        if isinstance(flowrate_data, dict):
            new_inputs["_flowrate_data"] = flowrate_data
        elif isinstance(raw_inputs.get("_flowrate_data"), dict):
            new_inputs["_flowrate_data"] = raw_inputs["_flowrate_data"]

        self.base_window.custom_lib_definitions[selected_name] = new_inputs
        self._register_custom_lib(selected_name, new_inputs)

        QMessageBox.information(
            self,
            "Edit LIB",
            f"Custom LIB '{selected_name}' updated.",
        )

    def open_add_lib_dialog(self):
        """Collect custom LIB inputs and register a selectable LIB type."""
        dlg = LIBDefinitionDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return

        payload = dlg.get_payload()
        lib_type_name = payload.get("lib_type_name", "").strip()
        raw_inputs = payload.get("inputs", {})
        flowrate_data = payload.get("flowrate_data")
        battery_chemistry = payload.get("battery_chemistry", "NMC")

        if not lib_type_name:
            QMessageBox.warning(self, "Add LIB", "LIB Type Name is required.")
            return

        if lib_type_name in self.base_window.custom_lib_definitions or lib_type_name in LIB_TYPE:
            QMessageBox.warning(self, "Add LIB", f"'{lib_type_name}' already exists.")
            return

        raw_inputs = dict(raw_inputs)
        raw_inputs["Battery Chemistry"] = battery_chemistry
        if isinstance(flowrate_data, dict):
            raw_inputs["_flowrate_data"] = flowrate_data

        self.base_window.custom_lib_definitions[lib_type_name] = raw_inputs
        self._register_custom_lib(lib_type_name, raw_inputs)

        QMessageBox.information(
            self,
            "Add LIB",
            f"Custom LIB '{lib_type_name}' saved. It is now available in scenario LIB Type selection.",
        )

    def open_add_composition_dialog(self):
        """Collect gas composition inputs and store a named composition."""
        dlg = CompositionDefinitionDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return

        payload = dlg.get_payload()
        comp_title = payload.get("composition_title", "").strip()
        chemicals = payload.get("chemicals", {})

        if not comp_title:
            QMessageBox.warning(self, "Add Composition", "Composition Title is required.")
            return

        existing = getattr(self.base_window, "custom_composition_definitions", {})
        if comp_title in existing:
            QMessageBox.warning(self, "Add Composition", f"'{comp_title}' already exists.")
            return

        self.base_window.custom_composition_definitions[comp_title] = chemicals

        QMessageBox.information(
            self,
            "Add Composition",
            f"Composition '{comp_title}' saved. It is now available in scenario Gas Composition selection.",
        )

    @staticmethod
    def _scenario_dtype():
        return np.dtype([(h, 'U100') if is_string_field(h) else (h, 'f8') for h in COMBINED_INPUTS])

    def current_scenario_data(self):
        """Build a numpy structured array from all ScenarioTreeItem leaves."""
        dicts = self.scenario_tree.collect_all_scenarios()
        if not dicts:
            return np.zeros(0, dtype=self._scenario_dtype())

        dtype = self._scenario_dtype()
        result = np.zeros(len(dicts), dtype=dtype)
        for i, data in enumerate(dicts):
            for field in COMBINED_INPUTS:
                val = data.get(field, "")
                if is_string_field(field):
                    result[field][i] = str(val) if val else ""
                else:
                    try:
                        result[field][i] = float(val) if val not in ("", None) else np.nan
                    except (ValueError, TypeError):
                        result[field][i] = np.nan
        return result

    # ------------------------------------------------------------------
    # Results panel
    # ------------------------------------------------------------------

    @staticmethod
    def _summary_placeholder_label(text: str):
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        return label

    def _show_summary_placeholder(self, text: str):
        if not hasattr(self, "summary_scroll"):
            return
        self.summary_scroll.setWidget(self._summary_placeholder_label(text))

    def _on_results_tab_clicked(self, index: int):
        self._on_results_tab_changed(index)

    def _on_results_tab_changed(self, index: int):
        if not hasattr(self, "summary_scroll"):
            return
        tab_widget = self.results_tabs.widget(index) if index >= 0 else None
        summary_w = self._results_summary_widgets.get(tab_widget)
        if summary_w is not None:
            self.summary_scroll.setWidget(summary_w)
        else:
            self._show_summary_placeholder("Summary results will appear here after running a calculation.")

    def _ensure_results_placeholder(self):
        if self.results_tabs.count() > 0:
            return
        ph = QLabel("Run a calculation to view results here.")
        ph.setAlignment(Qt.AlignCenter)
        self.results_tabs.addTab(ph, "Results")
        self._show_summary_placeholder("Summary results will appear here after running a calculation.")

    def _remove_results_placeholder(self):
        if self.results_tabs.count() != 1:
            return
        placeholder = self.results_tabs.widget(0)
        if placeholder is None:
            return
        if placeholder in self._result_tab_meta:
            return
        self.results_tabs.removeTab(0)
        placeholder.deleteLater()

    def _build_result_tab_title(self, scenario_name: str, result_type: str) -> str:
        suffix = "tox" if result_type == "tox" else "flam"
        return f"{scenario_name} ({suffix})"

    def _add_result_tab(self, result_type: str, scenario_name: str, result_data: dict):
        import display_popup as _dp

        if result_type == "tox":
            df = result_data.get("tox_vv_df")
        else:
            df = result_data.get("flam_vv_df")
        if df is None or df.empty:
            return

        self._remove_results_placeholder()

        tab_scroll = QScrollArea()
        tab_scroll.setWidgetResizable(True)
        tab_inner = QWidget()
        QVBoxLayout(tab_inner)
        tab_scroll.setWidget(tab_inner)

        if result_type == "flam":
            _dp.render_flam_scenario_into(tab_inner, scenario_name, result_data, CHEMICAL_PROPERTIES)
            headers = result_data.get("flam_summary_headers", [])
            row_data = result_data.get("flam_summary_row_data", [])
            groups = result_data.get("flam_summary_groups", [("Scenario Info", 6), ("Peak Results", 4)])
        else:
            _tox_mgl_df = result_data.get("tox_mgl_df")
            if _tox_mgl_df is not None:
                tox_gas_labels = [
                    col.replace(" (mg/L)", "")
                    for col in _tox_mgl_df.columns
                    if col not in ("Time (s)", "Total Gas (mg/L)")
                ]
            else:
                tox_gas_labels = list(CHEMICAL_PROPERTIES.keys())
            _dp.render_tox_scenario_into(tab_inner, scenario_name, result_data, tox_gas_labels, CHEMICAL_PROPERTIES)
            headers = result_data.get("tox_summary_headers", [])
            row_data = result_data.get("tox_summary_row_data", [])
            groups = result_data.get("tox_summary_groups", [("Scenario Info", 5), ("Peak Totals", 2)])

        summary_w = (
            _dp._build_summary_table(headers, row_data, groups)
            if headers and row_data
            else QLabel(f"Summary for {scenario_name}")
        )

        self._result_entry_counter += 1
        result_key = f"{result_type}:{self._result_entry_counter}:{scenario_name}"
        target_dict_name = "tox_scenario_results" if result_type == "tox" else "flam_scenario_results"
        target_dict = getattr(self.base_window, target_dict_name)
        target_dict[result_key] = result_data

        tab_title = self._build_result_tab_title(scenario_name, result_type)
        self.results_tabs.addTab(tab_scroll, tab_title)
        self._results_summary_widgets[tab_scroll] = summary_w
        self._result_tab_meta[tab_scroll] = {
            "result_type": result_type,
            "result_key": result_key,
            "scenario_name": scenario_name,
        }
        self.results_tabs.setCurrentWidget(tab_scroll)
        self._on_results_tab_changed(self.results_tabs.currentIndex())

    def _close_result_tab(self, index: int):
        tab_widget = self.results_tabs.widget(index)
        if tab_widget is None:
            return

        tab_meta = self._result_tab_meta.pop(tab_widget, None)
        if tab_meta is None:
            return

        summary_w = self._results_summary_widgets.pop(tab_widget, None)
        result_type = tab_meta.get("result_type")
        result_key = tab_meta.get("result_key")
        if result_type == "tox":
            self.base_window.tox_scenario_results.pop(result_key, None)
        elif result_type == "flam":
            self.base_window.flam_scenario_results.pop(result_key, None)

        self.results_tabs.removeTab(index)
        tab_widget.deleteLater()
        if summary_w is not None:
            summary_w.deleteLater()

        self._ensure_results_placeholder()
        self._on_results_tab_changed(self.results_tabs.currentIndex())

    def _update_results_display(self, result_type: str):
        import display_popup as _dp

        while self.results_tabs.count() > 0:
            w = self.results_tabs.widget(0)
            self.results_tabs.removeTab(0)
            if w:
                w.deleteLater()
        self._results_summary_widgets.clear()
        self._result_tab_meta.clear()

        all_entries = []
        for key, result_data in (self.base_window.tox_scenario_results or {}).items():
            if isinstance(result_data, dict):
                scenario_name = str(result_data.get("input", {}).get("Scenario Description") or key)
                all_entries.append(("tox", key, scenario_name, result_data))
        for key, result_data in (self.base_window.flam_scenario_results or {}).items():
            if isinstance(result_data, dict):
                scenario_name = str(result_data.get("input", {}).get("Scenario Description") or key)
                all_entries.append(("flam", key, scenario_name, result_data))

        for result_type_name, result_key, scenario_name, result_data in all_entries:
            tab_scroll = QScrollArea()
            tab_scroll.setWidgetResizable(True)
            tab_inner = QWidget()
            QVBoxLayout(tab_inner)
            tab_scroll.setWidget(tab_inner)

            if result_type_name == "tox":
                _dp.render_tox_scenario_into(tab_inner, scenario_name, result_data,
                                             list(CHEMICAL_PROPERTIES.keys()), CHEMICAL_PROPERTIES)
                hdrs = result_data.get("tox_summary_headers", [])
                rdata = result_data.get("tox_summary_row_data", [])
                grps = result_data.get("tox_summary_groups", [("Scenario Info", 5), ("Peak Totals", 2)])
            else:
                _dp.render_flam_scenario_into(tab_inner, scenario_name, result_data, CHEMICAL_PROPERTIES)
                hdrs = result_data.get("flam_summary_headers", [])
                rdata = result_data.get("flam_summary_row_data", [])
                grps = result_data.get("flam_summary_groups", [("Scenario Info", 6), ("Peak Results", 4)])

            self.results_tabs.addTab(tab_scroll, self._build_result_tab_title(scenario_name, result_type_name))
            self._results_summary_widgets[tab_scroll] = (
                _dp._build_summary_table(hdrs, rdata, grps) if hdrs and rdata
                else QLabel(f"Summary for {scenario_name}")
            )
            self._result_tab_meta[tab_scroll] = {
                "result_type": result_type_name,
                "result_key": result_key,
                "scenario_name": scenario_name,
            }

        self._ensure_results_placeholder()
        self._on_results_tab_changed(self.results_tabs.currentIndex())

    # ------------------------------------------------------------------
    # Calculations
    # ------------------------------------------------------------------

    def run_tox_calc(self):
        scenario_data = self._calculation_scenarios()
        missing = [s.get("Scenario Description", "(unnamed)") for s in scenario_data if str(s.get("LIB Type", "")).strip() == "Missing LIB"]
        if missing:
            QMessageBox.warning(self, "Missing LIB", "The following scenarios have no LIB assigned:\n" + "\n".join(f"  • {n}" for n in missing) + "\n\nAssign a LIB via Edit Scenario before running calculations.")
            return

        temp_state = SimpleNamespace(
            tox_scenario_results={},
            selected_calc_method=self.base_window.selected_calc_method,
            use_le_chatelier_lfl=self.base_window.use_le_chatelier_lfl,
            use_temp_dependent_lfl=self.base_window.use_temp_dependent_lfl,
        )
        _noop = lambda *a, **kw: None
        toxicity_assessment_calc(
            self.base_window,
            state=temp_state,
            display_toxicity_result_popup=_noop,
            gas_data=CHEMICAL_PROPERTIES,
            scenario_data=scenario_data,
            clear_existing=True,
        )
        for scenario_name, result_data in temp_state.tox_scenario_results.items():
            self._add_result_tab("tox", scenario_name, result_data)

    def run_flam_calc(self):
        scenario_data = self._calculation_scenarios()
        missing = [s.get("Scenario Description", "(unnamed)") for s in scenario_data if str(s.get("LIB Type", "")).strip() == "Missing LIB"]
        if missing:
            QMessageBox.warning(self, "Missing LIB", "The following scenarios have no LIB assigned:\n" + "\n".join(f"  • {n}" for n in missing) + "\n\nAssign a LIB via Edit Scenario before running calculations.")
            return
        standard_scenarios = []
        flowrate_scenarios = []
        default_method = CALCULATION_METHODS[0]
        for scenario in scenario_data:
            selected_method = str(scenario.get("Calculation Method", default_method) or default_method)
            if selected_method == "Module Variable Flowrate":
                flowrate_scenarios.append(scenario)
            else:
                standard_scenarios.append(scenario)

        temp_state = SimpleNamespace(
            flam_scenario_results={},
            selected_calc_method=self.base_window.selected_calc_method,
            use_le_chatelier_lfl=self.base_window.use_le_chatelier_lfl,
            use_temp_dependent_lfl=self.base_window.use_temp_dependent_lfl,
            gas_flowrate_data=self.base_window.gas_flowrate_data,
        )
        _noop = lambda *a, **kw: None

        if standard_scenarios:
            flammability_assessment_calc(
                self.base_window,
                state=temp_state,
                display_flammability_result_popup=_noop,
                gas_data=CHEMICAL_PROPERTIES,
                bat_data=BATTERY_CHEMISTRY_DATA,
                flam_gasses_labels=list(FLAMMABLE_GASES),
                scenario_data=standard_scenarios,
                clear_existing=True,
            )

        if flowrate_scenarios:
            flammability_assessment_calc_graphical_method(
                self.base_window,
                state=temp_state,
                display_flammability_result_popup=_noop,
                gas_data=CHEMICAL_PROPERTIES,
                bat_data=BATTERY_CHEMISTRY_DATA,
                flam_gasses_labels=list(FLAMMABLE_GASES),
                scenario_data=flowrate_scenarios,
                clear_existing=False,
            )
        for scenario_name, result_data in temp_state.flam_scenario_results.items():
            self._add_result_tab("flam", scenario_name, result_data)

    # ------------------------------------------------------------------
    # Other toolbar actions
    # ------------------------------------------------------------------

    def clear_results(self):
        self.base_window.tox_scenario_results.clear()
        self.base_window.flam_scenario_results.clear()
        while self.results_tabs.count() > 0:
            tab_widget = self.results_tabs.widget(0)
            self.results_tabs.removeTab(0)
            if tab_widget:
                tab_widget.deleteLater()
        self._results_summary_widgets.clear()
        self._result_tab_meta.clear()
        self._ensure_results_placeholder()

    def export_current_sheet_pdf(self):
        exported_path = pdf_generation(
            tox_scenario_results=self.base_window.tox_scenario_results,
            flam_scenario_results=self.base_window.flam_scenario_results,
            title="Battery Off-gas Assessment Results",
            gas_data=CHEMICAL_PROPERTIES,
        )
        if exported_path:
            QMessageBox.information(self, "PDF Export Complete",
                                    f"PDF report exported successfully:\n{exported_path}")

    def open_results_table(self):
        open_results_table_window(self.base_window, self.base_window)


class SprinklerPage(QWidget):
    """UI page for sprinkler activation time calculations."""
    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window
        self.last_activation_time_s = None

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        toolbar = QToolBar("Sprinkler Activation Time Calculator")
        toolbar.setMovable(False)
        toolbarcontents = QWidget()
        toolbarlayout = QHBoxLayout()
        toolbarlayout.setContentsMargins(8, 4, 8, 4)
        toolbarlayout.setSpacing(8)
        toolbarcontents.setLayout(toolbarlayout)
        toolbar.addWidget(toolbarcontents)

        run_button = QPushButton("Run")
        run_button.setToolTip("Run sprinkler activation time calculation with the current inputs.")
        run_button.clicked.connect(self.run_sprinkler_calc)

        clear_button = QPushButton("Clear")
        clear_button.setToolTip("Clear all sprinkler input fields.")
        clear_button.clicked.connect(self.clear_inputs)

        self.copy_activation_button = QPushButton("Copy Activation Duration")
        self.copy_activation_button.setToolTip("Copy the computed sprinkler activation duration to the clipboard.")
        self.copy_activation_button.setEnabled(False)
        self.copy_activation_button.clicked.connect(self.copy_activation_duration)

        toolbarlayout.addWidget(run_button)
        toolbarlayout.addWidget(clear_button)
        toolbarlayout.addWidget(self.copy_activation_button)
        toolbarlayout.addWidget(_make_toolbar_separator())

        page_layout.addWidget(toolbar)

        center_layout = QHBoxLayout()
        center_layout.setContentsMargins(24, 20, 24, 24)
        center_layout.addStretch()

        panel = QWidget()
        panel.setMaximumWidth(760)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(14)

        title = QLabel("Sprinkler Activation Time Calculator")
        title_font = title.font()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel(
            "Enter the sprinkler and fire parameters below, then click Run to compute activation time."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignCenter)

        input_group = QGroupBox("Inputs")
        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(16)
        form_layout.setVerticalSpacing(10)

        self.sprinkler_id = QLineEdit()
        self.sprinkler_id.setPlaceholderText("e.g. SPK-01")
        self.sprinkler_id.setToolTip("Optional sprinkler identifier.")

        self.ceiling_height = QLineEdit()
        self.ceiling_height.setPlaceholderText("e.g. 3.0")
        self.ceiling_height.setToolTip("Ceiling height in meters.")

        self.radial_distance = QLineEdit()
        self.radial_distance.setPlaceholderText("e.g. 2.0")
        self.radial_distance.setToolTip("Radial distance from fire plume centerline to sprinkler in meters.")

        self.sprinkler_rti = QLineEdit()
        self.sprinkler_rti.setPlaceholderText("e.g. 80")
        self.sprinkler_rti.setToolTip("Sprinkler response time index (m*s)^0.5.")

        self.activation_temperature = QLineEdit()
        self.activation_temperature.setPlaceholderText("e.g. 68")
        self.activation_temperature.setToolTip("Sprinkler activation temperature in degC.\n Typical inputs are 'red': 68, 'yellow': 79, 'green': 93")

        self.ambient_temperature = QLineEdit()
        self.ambient_temperature.setPlaceholderText("e.g. 20")
        self.ambient_temperature.setToolTip("Ambient temperature in degC.")

        self.fire_growth_rate = QComboBox()
        self.fire_growth_rate.addItems(list(FIRE_PROPERTIES["fire growth rate"].keys()))
        self.fire_growth_rate.setToolTip("Select the fire growth rate category.")

        form_layout.addRow("Sprinkler ID:", self.sprinkler_id)
        form_layout.addRow("Ceiling Height (m):", self.ceiling_height)
        form_layout.addRow("Radial Distance (m):", self.radial_distance)
        form_layout.addRow("Response Time Index (m*s)^0.5:", self.sprinkler_rti)
        form_layout.addRow("Activation Temperature (degC):", self.activation_temperature)
        form_layout.addRow("Ambient Temperature (degC):", self.ambient_temperature)
        form_layout.addRow("Fire Growth Rate:", self.fire_growth_rate)
        input_group.setLayout(form_layout)

        self.results_label = QLabel("Results will appear here after running the calculation.")
        self.results_label.setWordWrap(True)
        self.results_label.setAlignment(Qt.AlignCenter)

        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)
        panel_layout.addWidget(input_group)
        panel_layout.addWidget(self.results_label)

        center_layout.addWidget(panel)
        center_layout.addStretch()

        page_layout.addLayout(center_layout)

    def _get_sprinkler_inputs(self):
        """Collect and validate user input for sprinkler calculations."""
        numeric_fields = [
            ("Ceiling Height", self.ceiling_height, True),
            ("Radial Distance", self.radial_distance, True),
            ("Response Time Index", self.sprinkler_rti, True),
            ("Activation Temperature", self.activation_temperature, False),
            ("Ambient Temperature", self.ambient_temperature, False),
        ]

        values = {}
        for label, widget, must_be_positive in numeric_fields:
            text = widget.text().strip()
            if not text:
                raise ValueError(f"{label} is required.")

            try:
                value = float(text)
            except ValueError as exc:
                raise ValueError(f"{label} must be a valid number.") from exc

            if must_be_positive and value <= 0:
                raise ValueError(f"{label} must be greater than 0.")

            values[label] = value

        return {
            "sprinkler_id": self.sprinkler_id.text().strip() or "Sprinkler-1",
            "ceiling_height": values["Ceiling Height"],
            "radial_distance": values["Radial Distance"],
            "sprinkler_response_time_index": values["Response Time Index"],
            "sprinkler_activation_temperature": values["Activation Temperature"],
            "ambient_temperature": values["Ambient Temperature"],
            "fire_growth_rate": self.fire_growth_rate.currentText(),
        }

    def run_sprinkler_calc(self):
        """Run sprinkler activation time calculation from current UI inputs."""
        try:
            sprinkler_data = self._get_sprinkler_inputs()
            result = activation_time_Calc(sprinkler_data)
        except ValueError as err:
            QMessageBox.warning(self, "Input Error", str(err))
            return
        except Exception as err:
            QMessageBox.critical(self, "Calculation Error", f"Failed to run calculation:\n{err}")
            return

        activation_time = result.get("activation_time_s")
        if activation_time is None:
            self.last_activation_time_s = None
            self.copy_activation_button.setEnabled(False)
            self.results_label.setText(
                "No activation occurred within the maximum simulation time (10000 s)."
            )
            QMessageBox.information(
                self,
                "Sprinkler Result",
                "No activation occurred within the maximum simulation time (10000 s).",
            )
            return

        summary = (
            f"Sprinkler {sprinkler_data['sprinkler_id']} activation time: {activation_time:.1f} s\n"
            f"Detector temperature at activation check: {result['detector_temperature_c']:.1f} degC"
        )
        self.last_activation_time_s = activation_time
        self.copy_activation_button.setEnabled(True)
        self.results_label.setText(summary)
        QMessageBox.information(self, "Sprinkler Result", summary)

    def copy_activation_duration(self):
        if self.last_activation_time_s is None:
            QMessageBox.warning(
                self,
                "No Activation Duration",
                "Run a successful sprinkler calculation first to copy the activation duration.",
            )
            return

        activation_duration_text = f"{self.last_activation_time_s:.1f} s"
        QApplication.clipboard().setText(activation_duration_text)

    def clear_inputs(self):
        self.sprinkler_id.clear()
        self.ceiling_height.clear()
        self.radial_distance.clear()
        self.sprinkler_rti.clear()
        self.activation_temperature.clear()
        self.ambient_temperature.clear()
        self.fire_growth_rate.setCurrentIndex(0)
        self.last_activation_time_s = None
        self.copy_activation_button.setEnabled(False)
        self.results_label.setText("Results will appear here after running the calculation.")


class TutorialPage(QWidget):
    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window
        
        # Main page layout belonging to TutorialPage
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(20, 20, 20, 20)
        page_layout.setSpacing(15)

        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        label = QLabel("Tutorial for the LIB Off-gassing Calculation Tool")
        label.setFont(title_font)
        label.setAlignment(Qt.AlignCenter)

        page_layout.addWidget(label)

        
              # Tutorial sections
        sections = [
            {
                "icon": "🚀",
                "title": "Getting Started",
                "content": "Welcome to the Battery Off-gassing Calculation Tool! This application helps you assess toxicity and flammability risks from lithium-ion battery thermal runaway events."
            },
            {
                "icon": "📝",
                "title": "Creating Scenarios",
                "content": "1. Fill in the input parameters in the text boxes\n2. Select a battery type from the dropdown menu\n3. Press 'Enter Scenario' to add it to the queue\n4. Battery types are NMC, LFP1, and LFP2\n5. Cell temperatures and cell volumes are not used in calculations\nTip: Use presets for quick setup of common scenarios."
            },
            {
                "icon": "📁",
                "title": "Batch Import",
                "content": "For multiple scenarios:\n1. Click 'Generate Template' to create an Excel file\n2. Fill in your scenarios in the template\n3. Use 'Load Data File' to import all scenarios at once\n\nNote: Ensure a battery type is selected before loading."
            },
            {
                "icon": "🧪",
                "title": "Running Calculations",
                "content": "Choose your assessment type:\n\n• Calc Toxicity: Analyzes toxic gas concentrations (CO, NO₂, HCl, HF, HCN, Benzene, Toluene)\n• Calc Explosive: Evaluates flammable gas mixtures (CO, H₂, Hydrocarbons)\n\nResults appear in a popup window with graphs and summary tables."
            },
            {
                "icon": "📊",
                "title": "Exporting Results",
                "content": "Click 'Export PDF Report' to generate a comprehensive document including:\n• Input parameters for all scenarios\n• Concentration graphs over time\n• Summary tables and peak values\n• Maximum allowable units calculations"
            },
            {
                "icon": "⚙️",
                "title": "Technical Notes",
                "content": "• All parameters are based on module-level test data\n• Toxic gas composition: From DNV-GL empirical data\n• Flammable gas data: Specified in battery data files\n• Battery data stored in zip files in the battery_data folder\n• Results consider thermal propagation between modules"
            },
            {
                "icon": "🧹",
                "title": "Managing Scenarios",
                "content": "• Clear Form: Resets input fields\n• Delete Selected: Removes chosen scenarios from queue\n• Clear All: Removes all scenarios and calculation results"
            },
            {
                "icon": "💡",
                "title": "Tips",
                "content": "This program can either determine the volume off gassing through the UL9540A test results or the module capacity with a L/kWh value based on literature data.\nIf the capacity of a module is greater than 1, the model deviates too much so we default to using UL9540A cell volumes.\nA total volume is calculated and a percentage of that is used as either the flammable or toxic gas volume based on literature data. e.g. 80 percent flammable gas and 30 percent toxic gas as some gasses are counted as both flammable and toxic.\nAll correlations are based on 60 peer reviewed papers containing data for a total of 470 LIB experiments"
            },
            {
                "icon": "🚨",
                "title": "Emergency Ventilation",
                "content": "Vent Switch Conc and Emergency Vent Rate are inputs that allow users to use two ventilation rates in one scenario. To deactivate this system, input 0 for both inputs.\nVent Switch Conc is the percentage of the room that must be reached to activate the emergency ventliation. i.e. if LEL is 4% then activate emergency vent at 4%.\nEmergency vent is typically higher than the standard ventilation rate."
            },
            {
                "icon": "🔄",
                "title": "Variable Flowrates",
                "content": "Module level UL9540A test reports often provide flowrate data in graphs. Using WebPlotDigitizer you can extract the flowrate data into a csv file ascending in the x asis and import it to this program to use. \nYou need to select from the drop down menu the correct calculation function (module variable flowrate), opt to use a calculated LFL if you want, import the data, then import the scenarios from excel and run the calc. This is still a WIP."
            }
        ]

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)


        header_font = QFont()
        header_font.setPointSize(16)
        header_font.setBold(True)
        body_font = QFont()
        body_font.setPointSize(12)

        for section in sections:
            
            section_label = QLabel(f"{section['icon']} {section['title']}")
            section_label.setTextFormat(Qt.RichText)
            section_label.setAlignment(Qt.AlignLeft)
            section_label.setFont(header_font)

            section_content = QLabel(section['content'])
            section_content.setWordWrap(True)
            section_content.setAlignment(Qt.AlignLeft)
            section_content.setFont(body_font)

            main_layout.addWidget(section_label)
            main_layout.addWidget(section_content)



        # Keep all tutorial sections towards the top
        main_layout.addStretch()

        # --- Put it all in a scrollable container ---
        inner = QWidget()
        inner.setLayout(main_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)

        # This was missing: add scroll area to TutorialPage's layout
        page_layout.addWidget(scroll)


class PoolSpillPage(QWidget):
    """Placeholder window for the Pool Spill & Fire Duration calculator."""
    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window

        label = QLabel("Pool Spill & Fire Duration Calculator\n\nThis feature is not yet implemented.")
        font = label.font()
        font.setPointSize(18)
        font.setBold(True)
        label.setFont(font)
        label.setAlignment(Qt.AlignCenter)

        # dock area for tools, settings, and other widgets
        toolbar = QToolBar("LIB Offgassing Calculation Tool")
        toolbar.setMovable(False)  # optional: prevent the toolbar from being dragged
        toolbarcontents = QWidget()
        toolbarlayout = QHBoxLayout()
        toolbarcontents.setLayout(toolbarlayout)
        toolbar.addWidget(toolbarcontents)
        
        
        self.oi_tickbox = QCheckBox('Operator Intervention')
        self.oi_tickbox.setToolTip("Check this box to input the operator intervention time for the pool spill calculation. If unchecked, the volumetric flowrate will be used instead.")
        toolbarlayout.addWidget(self.oi_tickbox)
        
        self.pool_fire_tickbox = QCheckBox('Pool Fire Duration')
        self.pool_fire_tickbox.setToolTip("Check this box to calculate the pool fire duration, flame height, and heat release rate")
        toolbarlayout.addWidget(self.pool_fire_tickbox)
        
        calculate_button = QPushButton("Calculate")
        calculate_button.setToolTip("Click here to calculate the pool spill size and pool fire duration based on the input parameters.")
        # calculate_button.clicked.connect(lambda: data_submission(self.base_window, oi_tickbox.isChecked(), pool_fire_tickbox.isChecked()))
        toolbarlayout.addWidget(calculate_button)
        
        export_to_pdf = QPushButton("Export PDF Report")
        export_to_pdf.setToolTip("Click here to export a PDF report of the pool spill and pool fire duration results.")
        # export_to_pdf.clicked.connect(lambda: pdf_results(pool_spill_results=self.base_window.pool_spill_results, pool_fire_results=self.base_window.pool_fire_results, title="Pool Spill & Fire Duration Results"))
        toolbarlayout.addWidget(export_to_pdf)
        
        body_layout = QVBoxLayout(self)
        body_layout.addWidget(toolbar)
        
        main_layout = QHBoxLayout()
        main_layout.addStretch()
        
        pool_source_label = QLabel("Pool size is determined based on the methodology provided in DETERMINATION OF FLAMMABLE LIQUID POOL SIZES AND THE RESULTANT HAZARDOUS DISTANCES - Paper No. PCIC energy EUR25_03\nby Doug Brooks, Allan Bozek, and Angelo Barberio")
        fire_source_label = QLabel("Pool fire duration is determined based on the methodology provided in the two pool fire correlations using SFPE info\nMethod of Heskestad and Method of Thomas")
        pool_source_label.setWordWrap(True)
        fire_source_label.setWordWrap(True)
        body_layout.addWidget(pool_source_label)
        body_layout.addWidget(fire_source_label)
        
        warning_label = QLabel("The above calculations are based on principles developed in the Structural Design for Fire Safety, 2001. Calculations are based on certain assumptions and have inherent limitations. The results of such calculations may or may not have reasonable predictive capabilities for a given situation and should only be interpreted by an informed user. There is no absolute guarantee of the accuracy of these calculations.")
        warning_label.setStyleSheet("color: red; font-weight: bold;")
        warning_label.setWordWrap(True)

        #drop boxes
        self.fuel_material = QComboBox()
        self.fuel_material.setToolTip("Select the fuel material for the pool spill.")
        self.fuel_material.addItems(list(POOL_SPREAD_DATA.keys()))
        self.surface_weather = QComboBox()
        self.surface_weather.setToolTip("Select the surface weather condition for the pool spill.")
        self.surface_weather.addItems(list(POOL_PROPERTIES["relative_permeability"]))
        
        self.surface_material = QComboBox()
        self.surface_material.setToolTip("Select the surface material for the pool spill.\nFrom Table 1 of 'DETERMINATION OF FLAMMABLE LIQUID POOL SIZES AND THE RESULTANT HAZARDOUS DISTANCES'")
        self.surface_material.addItems(list(POOL_PROPERTIES["intrinsic_permeability"]))
        
        self.ground_conditions = QComboBox()
        self.ground_conditions.setToolTip("Select the ground conditions for the pool spill.")
        self.ground_conditions.addItems(list(POOL_PROPERTIES["average_pool_height"]))
        
        self.orifice_condition = QComboBox()
        self.orifice_condition.setToolTip("Select the orifice condition for the pool spill.")
        self.orifice_condition.addItems(list(POOL_PROPERTIES["discharge_coefficients"]))
        
        #user inputs
        
        self.ambient_temperature = QLineEdit()
        self.ambient_temperature.setToolTip("Enter the ambient temperature in kelvin.")
        
        self.wind_speed = QLineEdit()
        self.wind_speed.setToolTip("Enter the surface wind speed in meters per second.")
        
        self.bund_size = QLineEdit()
        self.bund_size.setToolTip("Enter the bund size in meters.")
        
        self.operator_intervention_time = QLineEdit()
        self.operator_intervention_time.setToolTip("Enter the operator intervention time in seconds.")
        
        self.orifice_diameter = QLineEdit()
        self.orifice_diameter.setToolTip("Enter the orifice diameter in meters.")
        
        self.delta_p = QLineEdit()
        self.delta_p.setToolTip("Enter the pressure differential in Pascals.")
        
        self.volumetric_flowrate = QLineEdit()
        self.volumetric_flowrate.setToolTip("Enter the volumetric flowrate in cubic meters per second.")
        
        
                # Input group
        input_group = QGroupBox("Pool Spill Inputs")
        
        input_group.setMaximumWidth(500)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(15)
        form_layout.setVerticalSpacing(10)
        form_layout2 = QFormLayout()
        form_layout2.setHorizontalSpacing(15)
        form_layout2.setVerticalSpacing(10)

        form_layout.addRow("Fuel Material:", self.fuel_material)
        form_layout.addRow("Surface Weather:", self.surface_weather)
        form_layout.addRow("Surface Material:", self.surface_material)
        form_layout.addRow("Ground Conditions:", self.ground_conditions)
        form_layout.addRow("Orifice Condition:", self.orifice_condition)
        form_layout2.addRow("Ambient Temperature (K):",self.ambient_temperature)
        form_layout2.addRow("Wind Speed (m/s):",self.wind_speed)
        form_layout2.addRow("Bund Size (m):",self.bund_size)
        form_layout2.addRow("Volumetric Flowrate (m³/s):",self.volumetric_flowrate)

        
        input_group.setLayout(form_layout)
        input_group2 = QGroupBox("Pool Spill Inputs")
        input_group2.setMaximumWidth(500)
        input_group2.setLayout(form_layout2)
        main_layout.addWidget(input_group2)

        main_layout.addWidget(input_group)

        # Right spacer
        main_layout.addStretch()

        body_layout.addLayout(main_layout)

        self.optional_group = QGroupBox("Operator Intervention Inputs")
        self.optional_group.setMaximumWidth(500)
        self.optional_group.setVisible(False)
        self.optional_layout = QFormLayout(self.optional_group)
        self.optional_layout.setHorizontalSpacing(15)
        self.optional_layout.setVerticalSpacing(10)

        self.optional_layout.addRow("Orifice Diameter (m):", self.orifice_diameter)
        self.optional_layout.addRow("Pressure Differential (Pa):", self.delta_p)
        self.optional_layout.addRow("Operator Intervention Time (s):", self.operator_intervention_time)

        main_layout.addWidget(self.optional_group)
        body_layout.addWidget(warning_label)

        self.oi_tickbox.toggled.connect(self.toggle_optional_inputs)
        self.toggle_optional_inputs()

    def toggle_optional_inputs(self):
        self.optional_group.setVisible(self.oi_tickbox.isChecked())


class ReceptorHeatFlux(QWidget):
    """Placeholder window for the Receptor Heat Flux calculator."""
    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window
        
        self.emissive_power = QLineEdit()
        self.emissive_power.setToolTip("Enter the emissive power in kW/m².\nMust be greater than 0.")
        
        self.perpendicular_distance = QLineEdit()
        self.perpendicular_distance.setToolTip("Enter the perpendicular distance from the fire source to the receptor in meters.\nMust be greater than 0.")
        
        

        label = QLabel("Receptor Heat Flux Calculator\n\nThis feature is not yet implemented.")
        font = label.font()
        font.setPointSize(18)
        font.setBold(True)
        label.setFont(font)
        label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addWidget(label)

               
if __name__ == "__main__": 
    app = QApplication([])
    apply_theme(_current_theme)
    window = BaseWindow()

    # Create pages
    intro_page = IntroPage(window)
    lib_page = LIBPage(window)
    tutorial_page = TutorialPage(window)
    sprinkler_page = SprinklerPage(window)
    pool_spill_page = PoolSpillPage(window)
    receptor_heat_flux_page = ReceptorHeatFlux(window)

    # Register pages
    window.add_page("IntroPage", intro_page)
    window.add_page("LIBPage", lib_page)
    window.add_page("TutorialPage", tutorial_page)
    window.add_page("SprinklerPage", sprinkler_page)
    window.add_page("PoolSpillPage", pool_spill_page)
    window.add_page("ReceptorHeatFluxPage", receptor_heat_flux_page)

    # Initially display the intro page
    window.show_page(
        "IntroPage",
        remember_current=False
    )

    window.show()

    app.exec()
