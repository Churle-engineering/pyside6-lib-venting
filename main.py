from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTabWidget, QToolBar,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QComboBox, QCheckBox, QGridLayout,
    QAbstractItemView, QMenu, QTableWidget, QTableWidgetItem, QHeaderView, QSpinBox)
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import (QFont, QDoubleValidator, QKeySequence, QShortcut,
    QActionGroup)
from information import (FIRE_PROPERTIES, POOL_SPREAD_DATA, LIB_TYPE, CELL_FORMAT, CALCULATION_METHODS, _THEMES,
                         POOL_PROPERTIES, CHEMICAL_PROPERTIES, COMPOSITION_METHODS, SPRINKLER_PROPERTIES,
                         FlowrateProfile, GasComposition, LIBInputs, LIBSpec,
                         CALC_METHOD_MODULE_VARIABLE_FLOWRATE)
import copy
import math
import os
from importlib import import_module
from dataclass_forms import build_tabbed_form, read_form
from lib_validation import input_problems
from scenario_model import ScenarioStore
from sprinkler import activation_time_Calc
from heat_flux_of_emitter import (heat_flux_of_emitter, temp_of_emitter,
                                  DEFAULT_INPUTS as DEFAULT_HEAT_FLUX_INPUTS)
from saveload import save_program_state, load_program_state
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

calculate_pool_assessment = import_module("spill_poolfire").calculate_pool_assessment

#export
#pyinstaller --clean --noconfirm --name LIBOffgasTool --onedir --icon ".\jeof_icon.ico" --add-data ".\arup_logo.png;." --hidden-import spill_poolfire ".\main.py"


# to do's:
# update le chateliers lfl calculation to use all gas and account for the non-flammable components
# variable flowrate calculation needs fixing and checking.
# stop auto normalsing the off gas composition. Should only happen upon user selection.
# something to notify the user if the composition changes or drops back to literature.
# add separate cumulative generated gas 
# implement battery charge relationship to stuff.


# need to decouple timestep from number of printed sheets
# make data tables optional for the pdf export
# add an input into the windows that specifies the project that is being run. Make it optional but helps to track what data is what.
# I want to make emergency ventilation not apart of the spreadhseet inputs but a separate tab to select or something
# add button to delete specifcally results data and not affect the spreadsheet.
# try to integrate a way to use the different calculation methods for different scenario rows as they may have different batteries that require different methods.
# add a safety factor to the ventillation as some decimal which could account for reducing the perfect mixing.
#add an option to toggle a 25% of LFL line to be put in the popup results plots.


# ---------------------------------------------------------------------------
# Theme definitions – applied globally via QApplication.setStyleSheet().
# Add QPushButton#clearAllButton entries to every theme so the button stays
# visually distinct regardless of the active colour scheme.
# ---------------------------------------------------------------------------
_current_theme = "Warm Slate"  # Default theme applied at startup


def app_settings() -> QSettings:
    """Persistent user preferences (theme, window geometry, splitter layout)."""
    return QSettings("Arup", "LIBOffgasTool")


# Main application window that hosts the page stack and shared state for the
# different calculation modules.
class BaseWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Charlie's Proprietary LIB Offgas Modelling Tool")
        saved_geometry = app_settings().value("window/geometry")
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        else:
            self.setGeometry(500, 500, 800, 600)
        self.page_stack = QStackedWidget()
        self.setCentralWidget(self.page_stack) #set as central widget of page
        self.page = {}  # store pages by name
        self.page_history = []  # store page history for back button functionality
        self.custom_lib_definitions = {}
        self.custom_composition_definitions = {}
        self.custom_flowrate_profiles = {}
        self._copied_scenario = None
        self.current_save_path = None

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
        openAction = fileMenu.addAction('Open...')
        openAction.setShortcut(QKeySequence.Open)
        openAction.triggered.connect(self.open_session)
        saveAction = fileMenu.addAction('Save')
        saveAction.setShortcut(QKeySequence.Save)
        saveAction.triggered.connect(lambda: self.save_session(use_current_path=True))
        saveAsAction = fileMenu.addAction('Save As...')
        saveAsAction.setShortcut(QKeySequence.SaveAs)
        saveAsAction.triggered.connect(lambda: self.save_session(use_current_path=False))
        fileMenu.addSeparator()
        exitAction = fileMenu.addAction('Exit')
        exitAction.triggered.connect(self.close)

        themeMenu = menubar.addMenu('Theme')
        self._theme_actions = {}
        theme_group = QActionGroup(self)
        for _theme_name in _THEMES:
            _action = themeMenu.addAction(_theme_name)
            _action.setCheckable(True)
            theme_group.addAction(_action)
            _action.triggered.connect(lambda checked=False, t=_theme_name: self.select_theme(t))
            self._theme_actions[_theme_name] = _action
        if _current_theme in self._theme_actions:
            self._theme_actions[_current_theme].setChecked(True)

    def select_theme(self, theme_name):
        """Apply a theme and keep the Theme menu's check mark in sync."""
        apply_theme(theme_name)
        action = self._theme_actions.get(theme_name)
        if action is not None:
            action.setChecked(True)

    def closeEvent(self, event):
        """Confirm exit (any close path) and persist user preferences."""
        reply = QMessageBox.question(
            self, 'Exit', 'Are you sure you want to exit?\nAny unsaved changes will be lost.',
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok)
        if reply != QMessageBox.StandardButton.Ok:
            event.ignore()
            return
        settings = app_settings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("theme", _current_theme)
        lib_page = self.page.get("LIBPage")
        if lib_page is not None:
            settings.setValue("libpage/middle_splitter", lib_page.middle_splitter.saveState())
            settings.setValue("libpage/body_splitter", lib_page.body_splitter.saveState())
        event.accept()

    def save_session(self, use_current_path=False):
        path = self.current_save_path if use_current_path else None
        if save_program_state(self, _current_theme, path=path):
            self.setWindowTitle(f"Charlie's Proprietary LIB Offgas Modelling Tool - {self.current_save_path}")

    def open_session(self):
        path, theme_name = load_program_state(self)
        if not path:
            return
        if theme_name in _THEMES:
            self.select_theme(theme_name)
        self.setWindowTitle(f"Charlie's Proprietary LIB Offgas Modelling Tool - {path}")

# Helper functions for shared UI behaviour such as theme switching and simple
# window actions used by multiple pages.
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


# Landing page that presents the main tools available in the application.
class IntroPage(QWidget):
    TOOLS = [
        ("LIB Modelling Tool",
         "Room off-gas concentrations assessed against LFL and ERPG-3 thresholds.",
         "LIBPage"),
        ("Sprinkler Activation Time",
         "Time for a sprinkler head to activate under a growing fire.",
         "SprinklerPage"),
        ("Pool Spill & Fire Duration",
         "Provisional spill pool size and pool fire duration estimates.",
         "PoolSpillPage"),
        ("Receptor Heat Flux",
         "Radiant heat flux received from a rectangular emitting panel (view factor method).",
         "ReceptorHeatFluxPage"),
    ]

    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window

        title = QLabel("LIB Off-gassing Calculation Tool")
        title_font = title.font()
        title_font.setPointSize(30)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)

        subtitle = QLabel("Choose a calculator below to get started.")
        subtitle.setObjectName("introSubtitle")
        subtitle_font = subtitle.font()
        subtitle_font.setPointSize(16)
        subtitle.setFont(subtitle_font)
        subtitle.setAlignment(Qt.AlignCenter)

        # 2 x 2 grid of card-style tool buttons
        btn_grid = QGridLayout()
        btn_grid.setSpacing(18)
        self._tool_grid = btn_grid
        self._tool_buttons = [
            self._tool_button(name, description, page_name)
            for name, description, page_name in self.TOOLS
        ]

        # Tutorial is a secondary action - full width but visually lighter
        tutorial_button = QPushButton("Tutorial - learn the modelling workflow")
        tutorial_button.setObjectName("tutorialButton")
        tutorial_button.setMinimumHeight(50)
        tutorial_font = tutorial_button.font()
        tutorial_font.setPointSize(14)
        tutorial_button.setFont(tutorial_font)
        tutorial_button.setToolTip("Step-by-step guide to libraries, scenarios, "
                                   "running calculations and exporting reports.")
        tutorial_button.clicked.connect(lambda: self.base_window.show_page("TutorialPage"))

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(18)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(10)
        layout.addLayout(btn_grid)
        layout.addWidget(tutorial_button)
        layout.addStretch(2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)
        self._layout_tool_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_tool_buttons()

    def _layout_tool_buttons(self):
        columns = 2 if self.width() >= 700 else 1
        if getattr(self, "_tool_columns", None) == columns:
            return
        self._tool_columns = columns
        while self._tool_grid.count():
            self._tool_grid.takeAt(0)
        self._tool_grid.setColumnStretch(0, 1)
        self._tool_grid.setColumnStretch(1, 1 if columns == 2 else 0)
        for index, button in enumerate(self._tool_buttons):
            self._tool_grid.addWidget(button, index // columns, index % columns)

    def _tool_button(self, name, description, page_name):
        """Card-style button: bold tool name over a smaller description line."""
        button = QPushButton()
        button.setMinimumSize(0, 128)
        button.setToolTip(f"Open the {name}.")
        button.clicked.connect(lambda: self.base_window.show_page(page_name))

        name_label = QLabel(name)
        name_font = name_label.font()
        name_font.setPointSize(17)
        name_font.setBold(True)
        name_label.setFont(name_font)

        desc_label = QLabel(description)
        desc_font = desc_label.font()
        desc_font.setPointSize(12)
        desc_label.setFont(desc_font)
        desc_label.setWordWrap(True)

        for label in (name_label, desc_label):
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            label.setStyleSheet("background: transparent; border: none;")

        button_layout = QVBoxLayout(button)
        button_layout.setContentsMargins(20, 14, 20, 14)
        button_layout.setSpacing(8)
        button_layout.addStretch()
        button_layout.addWidget(name_label)
        button_layout.addWidget(desc_label)
        button_layout.addStretch()
        return button


# Study tree node kinds. Stored on each item under NODE_TYPE_ROLE.
NODE_STUDY = "study"
NODE_GROUP = "group"
NODE_SCENARIO = "scenario"

NODE_TYPE_ROLE = Qt.UserRole + 1
NODE_ID_ROLE = Qt.UserRole + 2

# Combo entry meaning "no user-defined composition selected" for LIBInputs.gas_composition.
NO_COMPOSITION = "None"

# Combo entry meaning "no user-defined battery selected" for LIBInputs.lib_spec.
NO_LIB = "None"

# Combo entry meaning "no imported dataset selected" for LIBInputs.flowrate_profile.
NO_FLOWRATE = "None"


# Dialog that builds a named GasComposition from a percentage per CHEMICAL_PROPERTIES
# species. Only the percentages are captured here - density/LFL/factors stay in
# CHEMICAL_PROPERTIES and are looked up through the dataclass.
class GasCompositionDialog(QDialog):
    def __init__(self, parent, existing_names=(), composition=None):
        super().__init__(parent)
        self.setWindowTitle("Gas Composition" if composition is not None else "Add Gas Composition")
        self._existing_names = set(existing_names)
        if composition is not None:
            self._existing_names.discard(composition.name)
        self.result_composition = None

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. NMC UL9540A Test 3")
        self.name_edit.setToolTip("Name this composition appears under in the scenario dialog.")
        if composition is not None:
            self.name_edit.setText(composition.name)

        name_form = QFormLayout()
        name_form.addRow("Composition Name:", self.name_edit)

        gas_page = QWidget()
        gas_form = QFormLayout(gas_page)
        gas_form.setHorizontalSpacing(16)
        gas_form.setVerticalSpacing(6)

        self._gas_edits = {}
        for gas, properties in CHEMICAL_PROPERTIES.items():
            initial = composition.percentages.get(gas, 0) if composition is not None else 0
            edit = QLineEdit(str(initial))
            edit.setValidator(QDoubleValidator(0.0, 100.0, 6))
            edit.setToolTip(
                f"Share of the total off-gas that is {gas} (%).\n"
                f"Density: {properties['density']} g/L, LFL: {properties['lfl']}"
            )
            edit.textChanged.connect(self._update_total)
            gas_form.addRow(f"{gas.upper()} (%):", edit)
            self._gas_edits[gas] = edit

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(gas_page)

        self.total_label = QLabel()

        normalize_button = QPushButton("Normalize to 100%")
        normalize_button.setToolTip("Scale every entered percentage so the total is exactly 100%.")
        normalize_button.clicked.connect(self._normalize)

        total_row = QHBoxLayout()
        total_row.addWidget(self.total_label)
        total_row.addStretch()
        total_row.addWidget(normalize_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(name_form)
        layout.addWidget(scroll)
        layout.addLayout(total_row)
        layout.addWidget(buttons)
        self.resize(420, 620)
        self._update_total()

    def _percentages(self):
        values = {}
        for gas, edit in self._gas_edits.items():
            text = edit.text().strip().replace(",", ".")
            if not text:
                continue
            try:
                values[gas] = float(text)
            except ValueError as exc:
                raise ValueError(f"{gas.upper()} must be a valid percentage.") from exc
        return values

    def _update_total(self):
        try:
            total = sum(self._percentages().values())
        except ValueError:
            self.total_label.setText("Total: invalid entry")
            self.total_label.setStyleSheet("color: #c0392b; font-weight: bold;")
            return
        self.total_label.setText(f"Total: {total:.2f} %")
        off_target = abs(total - 100.0) > 0.01
        self.total_label.setStyleSheet(
            "color: #c0392b; font-weight: bold;" if off_target else "")

    def _normalize(self):
        try:
            values = self._percentages()
        except ValueError:
            return
        total = sum(values.values())
        if total <= 0:
            return
        for gas, edit in self._gas_edits.items():
            value = values.get(gas, 0.0)
            edit.setText(f"{value / total * 100.0:.6g}" if value else "0")

    def _on_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Input Error", "Enter a name for the composition.")
            return
        if name in self._existing_names or name == NO_COMPOSITION:
            QMessageBox.warning(self, "Input Error", f"A composition named '{name}' already exists.")
            return

        try:
            percentages = self._percentages()
        except ValueError as exc:
            QMessageBox.warning(self, "Input Error", str(exc))
            return

        if not any(value > 0 for value in percentages.values()):
            QMessageBox.warning(self, "Input Error", "Enter a percentage for at least one gas.")
            return

        self.result_composition = GasComposition(name=name, percentages=percentages)
        self.accept()


# Dialog that builds a named LIBSpec - the battery definition a scenario points at.
# Like ScenarioInputDialog it keeps no parallel copy of the field values; the form is
# generated from LIBSpec's field metadata and read straight back into a LIBSpec.
class BatteryDefinitionDialog(QDialog):
    # Every LIBSpec field must be assigned to a tab (build_tabbed_form enforces this).
    TAB_FIELDS = [
        ("General", ["name", "lib_type", "cell_format", "battery_charge", "venting_temperature", "lfl"]),
        ("Cell", ["cell_volume", "cell_duration", "cell_amphour", "cell_capacity"]),
        ("Module", ["module_volume", "module_duration", "module_amphour", "module_capacity"]),
        ("Propagation", ["cell_prop_delay", "cell_prop_number", "mod_prop_delay", "mod_prop_number"]),
    ]

    def __init__(self, parent, spec: LIBSpec | None = None, existing_names=()):
        super().__init__(parent)
        self.setWindowTitle("Battery Definition")
        self.result_spec = spec if spec is not None else LIBSpec()
        self._existing_names = set(existing_names) - {self.result_spec.name}

        form_tabs, self._field_widgets = build_tabbed_form(
            LIBSpec,
            self.TAB_FIELDS,
            instance=self.result_spec,
            choices={"lib_type": LIB_TYPE, "cell_format": CELL_FORMAT},
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(form_tabs)
        layout.addWidget(buttons)
        self.resize(520, 560)

    def _on_accept(self):
        try:
            spec = read_form(LIBSpec, self._field_widgets)
        except ValueError as exc:
            QMessageBox.warning(self, "Input Error", str(exc))
            return

        if not spec.name:
            QMessageBox.warning(self, "Input Error", "Enter a name for the battery.")
            return
        if spec.name in self._existing_names or spec.name == NO_LIB:
            QMessageBox.warning(self, "Input Error", f"A battery named '{spec.name}' already exists.")
            return

        self.result_spec = spec
        self.accept()


# Dialog that edits a single LIBInputs instance using an auto-generated form.
# LIBInputs is the single source of truth here: this dialog keeps no parallel
# copy of field values - it only reads/writes LIBInputs via dataclass_forms.
class ScenarioInputDialog(QDialog):
    # Every LIBInputs field must be assigned to a tab (build_tabbed_form enforces this).
    TAB_FIELDS = [
        ("General", ["scenario_description", "manufacturer_name", "battery_room",
                     "lib_spec", "cells_per_module", "modules_per_unit", "units",
                     "calc_method", "composition_method", "gas_composition",
                     "flowrate_profile"]),
        ("Room Details", ["room_height", "room_area", "equip_space", "ventilation_rate",
                           "emergency_vent_rate", "emergency_vent_delay", "vent_switch_conc"]),
        ("Calculation", ["calc_duration", "use_le_chatelier_lfl",
                          "use_temp_dependent_lfl"]),
    ]

    def __init__(self, parent, inputs: LIBInputs, composition_names=None, lib_names=None,
                 flowrate_names=None):
        super().__init__(parent)
        self.setWindowTitle("Scenario Inputs")
        self.result_inputs = inputs

        form_tabs, self._field_widgets = build_tabbed_form(
            LIBInputs,
            self.TAB_FIELDS,
            instance=inputs,
            choices={
                "calc_method": CALCULATION_METHODS,
                "composition_method": COMPOSITION_METHODS,
                "gas_composition": list(composition_names or [NO_COMPOSITION]),
                "lib_spec": list(lib_names or [NO_LIB]),
                "flowrate_profile": list(flowrate_names or [NO_FLOWRATE]),
            },
        )

        # only the fields the chosen methods actually consume stay enabled
        self._field_widgets["calc_method"].currentTextChanged.connect(self._update_dependent_fields)
        self._field_widgets["composition_method"].currentTextChanged.connect(self._update_dependent_fields)
        self._update_dependent_fields()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(form_tabs)
        layout.addWidget(buttons)
        self.resize(520, 620)

    def _update_dependent_fields(self, _text=None):
        widgets = self._field_widgets
        user_defined = widgets["composition_method"].currentText() == "User Defined"
        widgets["gas_composition"].setEnabled(user_defined)
        widgets["gas_composition"].parentWidget().layout().setRowVisible(
            widgets["gas_composition"], user_defined)
        if not user_defined:
            widgets["gas_composition"].setToolTip(
                "Only used when the Composition Method is 'User Defined'.")

        variable = widgets["calc_method"].currentText() == CALC_METHOD_MODULE_VARIABLE_FLOWRATE
        widgets["flowrate_profile"].setEnabled(variable)
        widgets["flowrate_profile"].parentWidget().layout().setRowVisible(
            widgets["flowrate_profile"], variable)
        if not variable:
            widgets["flowrate_profile"].setToolTip(
                "Only used by the 'Module Variable Flowrate' calculation method.")

    def _validation_problems(self, inputs):
        """Configuration contradictions that would make the run fail later."""
        problems = input_problems(inputs)
        if inputs.lib_spec == NO_LIB:
            problems.append("Select a battery ('Battery (LIB)') - create one with 'Add LIB' first.")
        if (inputs.calc_method == CALC_METHOD_MODULE_VARIABLE_FLOWRATE
                and inputs.flowrate_profile == NO_FLOWRATE):
            problems.append("The 'Module Variable Flowrate' method needs an imported "
                            "flowrate dataset ('Flowrate Dataset').")
        if (inputs.composition_method == "User Defined"
                and inputs.gas_composition == NO_COMPOSITION):
            problems.append("The 'User Defined' composition method needs a gas composition - "
                            "create one with 'Add Composition' first.")
        return problems

    def _on_accept(self):
        try:
            inputs = read_form(LIBInputs, self._field_widgets)
        except ValueError as exc:
            QMessageBox.warning(self, "Input Error", str(exc))
            return

        problems = self._validation_problems(inputs)
        if problems:
            QMessageBox.warning(self, "Scenario Configuration", "\n\n".join(problems))
            return

        self.result_inputs = inputs
        self.accept()


# One dialog to view, add, edit, delete and import every named library object the
# scenarios reference: batteries (LIBSpec), gas compositions (GasComposition) and
# measured flowrate datasets (FlowrateProfile). Scenarios store only the names;
# LIBPage rebinds the objects after the dialog closes.
class LibraryManagerDialog(QDialog):
    def __init__(self, parent, base_window):
        super().__init__(parent)
        self.base_window = base_window
        self.setWindowTitle("Libraries")

        tabs = QTabWidget()
        self._battery_list = self._make_tab(
            tabs, "Batteries (LIB)",
            add=self._add_battery, edit=self._edit_battery,
            delete=lambda: self._delete_item(self._battery_list,
                                             self.base_window.custom_lib_definitions, "battery"),
        )
        self._composition_list = self._make_tab(
            tabs, "Gas Compositions",
            add=self._add_composition, edit=self._edit_composition,
            delete=lambda: self._delete_item(self._composition_list,
                                             self.base_window.custom_composition_definitions,
                                             "composition"),
        )
        self._flowrate_list = self._make_tab(
            tabs, "Flowrate Datasets",
            add=self._import_flowrate, edit=None,
            delete=lambda: self._delete_item(self._flowrate_list,
                                             self.base_window.custom_flowrate_profiles, "dataset"),
            add_label="Import CSV...",
            hint=("A dataset is a two-column CSV (time in seconds, flowrate in L/s) describing "
                  "ONE module's total off-gas flowrate, e.g. extracted from a UL9540A test "
                  "report with WebPlotDigitizer. It is used by the 'Module Variable Flowrate' "
                  "calculation method."),
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        self.resize(520, 460)
        self._refresh_lists()

    def _make_tab(self, tabs, title, add, edit, delete, add_label="Add...", hint=None):
        page = QWidget()
        layout = QVBoxLayout(page)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)
        list_widget = QListWidget()
        layout.addWidget(list_widget)

        button_row = QHBoxLayout()
        add_button = QPushButton(add_label)
        add_button.clicked.connect(add)
        button_row.addWidget(add_button)
        if edit is not None:
            edit_button = QPushButton("Edit...")
            edit_button.clicked.connect(edit)
            button_row.addWidget(edit_button)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(delete)
        button_row.addWidget(delete_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        tabs.addTab(page, title)
        return list_widget

    def _refresh_lists(self):
        self._battery_list.clear()
        self._battery_list.addItems(list(self.base_window.custom_lib_definitions))
        self._composition_list.clear()
        self._composition_list.addItems(list(self.base_window.custom_composition_definitions))
        self._flowrate_list.clear()
        for name, profile in self.base_window.custom_flowrate_profiles.items():
            self._flowrate_list.addItem(f"{name}   ({profile.duration():.0f} s, "
                                        f"{profile.total_volume_l():.1f} l)")

    def _selected_name(self, list_widget):
        item = list_widget.currentItem()
        if item is None:
            return None
        return item.text().split("   (")[0]

    def _delete_item(self, list_widget, store, noun):
        name = self._selected_name(list_widget)
        if name is None or name not in store:
            return
        confirm = QMessageBox.question(
            self, "Delete",
            f"Delete {noun} '{name}'?\nScenarios referencing it will need a new selection "
            "before they can run.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        store.pop(name, None)
        self._refresh_lists()

    # -- batteries -----------------------------------------------------------

    def _add_battery(self):
        dialog = BatteryDefinitionDialog(self, existing_names=self.base_window.custom_lib_definitions)
        if dialog.exec() != QDialog.Accepted:
            return
        spec = dialog.result_spec
        self.base_window.custom_lib_definitions[spec.name] = spec
        self._refresh_lists()

    def _edit_battery(self):
        definitions = self.base_window.custom_lib_definitions
        name = self._selected_name(self._battery_list)
        if name is None or name not in definitions:
            return
        dialog = BatteryDefinitionDialog(self, copy.deepcopy(definitions[name]),
                                         existing_names=definitions)
        if dialog.exec() != QDialog.Accepted:
            return
        spec = dialog.result_spec
        if spec.name != name:
            definitions.pop(name, None)
        definitions[spec.name] = spec
        self._refresh_lists()

    # -- compositions ----------------------------------------------------------

    def _add_composition(self):
        dialog = GasCompositionDialog(self, self.base_window.custom_composition_definitions)
        if dialog.exec() != QDialog.Accepted:
            return
        composition = dialog.result_composition
        self.base_window.custom_composition_definitions[composition.name] = composition
        self._refresh_lists()

    def _edit_composition(self):
        definitions = self.base_window.custom_composition_definitions
        name = self._selected_name(self._composition_list)
        if name is None or name not in definitions:
            return
        dialog = GasCompositionDialog(self, definitions, composition=definitions[name])
        if dialog.exec() != QDialog.Accepted:
            return
        composition = dialog.result_composition
        if composition.name != name:
            definitions.pop(name, None)
        definitions[composition.name] = composition
        self._refresh_lists()

    # -- flowrate datasets -----------------------------------------------------

    def _import_flowrate(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Flowrate Dataset", "", "CSV files (*.csv);;All files (*.*)")
        if not path:
            return

        try:
            time_s, flowrate_lps = self._parse_flowrate_csv(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Import Flowrate Dataset", str(exc))
            return

        default_name = os.path.splitext(os.path.basename(path))[0]
        name, accepted = QInputDialog.getText(
            self, "Import Flowrate Dataset", "Dataset name:", text=default_name)
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.base_window.custom_flowrate_profiles or name == NO_FLOWRATE:
            QMessageBox.warning(self, "Import Flowrate Dataset",
                                f"A dataset named '{name}' already exists.")
            return

        self.base_window.custom_flowrate_profiles[name] = FlowrateProfile(
            name=name, time_s=time_s, flowrate_lps=flowrate_lps)
        self._refresh_lists()

    @staticmethod
    def _parse_flowrate_csv(path):
        """Read a two-column (time_s, flowrate_lps) CSV, tolerating a header row."""
        time_s, flowrate_lps = [], []
        with open(path, "r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                parts = [part.strip() for part in line.replace(";", ",").split(",")]
                try:
                    t, q = float(parts[0]), float(parts[1])
                except (ValueError, IndexError):
                    if line_number == 1:
                        continue   # header row
                    raise ValueError(
                        f"Line {line_number} is not 'time, flowrate': {line!r}") from None
                time_s.append(t)
                flowrate_lps.append(q)
        if len(time_s) < 2:
            raise ValueError("The file needs at least two 'time, flowrate' rows.")
        return time_s, flowrate_lps


# Main calculation page for LIB toxicity and flammability assessments.
class LIBPage(QWidget):
    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window
        self.scenarios = ScenarioStore()   # owns every Scenario; tree items hold only node ids
        self._copied_scenario = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Toolbar ---
        toolbar = QToolBar("LIB Offgassing Calculation Tool")
        toolbar.setMovable(False)
        toolbarcontents = QWidget()
        toolbarcontents.setObjectName("toolbarContents")
        toolbarlayout = QHBoxLayout()
        toolbarlayout.setContentsMargins(0, 0, 0, 0)
        toolbarlayout.setSpacing(6)
        toolbarcontents.setLayout(toolbarlayout)
        toolbar.addWidget(toolbarcontents)

        libraries_button = QPushButton("Libraries")
        libraries_button.setToolTip("Manage the named objects scenarios reference: batteries (LIBs), "
                                    "gas compositions and imported flowrate datasets.")
        libraries_button.clicked.connect(self.open_library_manager)

        run_button = QPushButton("Run")
        run_button.setObjectName("runButton")
        run_button.setToolTip("Run the calculation. Scope follows the tree selection:\n"
                              "a scenario runs alone, a group runs its scenarios,\n"
                              "no selection runs everything.")
        run_button.clicked.connect(self.run_calc)

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

        toolbarlayout.addWidget(libraries_button)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(run_button)
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

        # Middle: horizontal splitter (study tree | results plot)
        middle_splitter = QSplitter(Qt.Horizontal)
        middle_splitter.setChildrenCollapsible(False)
        body_splitter.addWidget(middle_splitter)

        self.scenario_tree = self._build_study_tree_panel()
        middle_splitter.addWidget(self.scenario_tree)
        middle_splitter.setStretchFactor(0, 0)

        self.plot_display = QWidget()
        self.plot_display.setObjectName("plotDisplay")
        self.plot_layout = QVBoxLayout(self.plot_display)
        self.plot_layout.setContentsMargins(16, 16, 16, 16)

        self.plot_placeholder = QLabel(
            "Plot display area\n\nGenerated calculation plots will appear here."
        )
        self.plot_placeholder.setObjectName("plotDisplayPlaceholder")
        self.plot_placeholder.setAlignment(Qt.AlignCenter)

        # one tab per scenario that has been run; tabs persist across runs
        self.result_tabs = QTabWidget()
        self.result_tabs.setTabsClosable(True)
        self.result_tabs.tabCloseRequested.connect(self._on_result_tab_close_requested)
        self._result_tab_widgets = {}   # node_id -> that scenario's plot widget

        self.plot_stack = QStackedWidget()
        self.plot_stack.addWidget(self.plot_placeholder)
        self.plot_stack.addWidget(self.result_tabs)
        self.plot_stack.setCurrentWidget(self.plot_placeholder)
        self.plot_layout.addWidget(self.plot_stack)

        middle_splitter.addWidget(self.plot_display)
        middle_splitter.setStretchFactor(1, 1)
        middle_splitter.setSizes([280, 900])

        # Bottom: scrollable summary strip
        self.summary_scroll = QScrollArea()
        self.summary_scroll.setObjectName("summaryResultsPanel")
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setMinimumHeight(130)
        self.summary_scroll.setMaximumHeight(220)
        self.summary_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.summary_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.summary_stack = QStackedWidget()
        self._summary_placeholder = self._summary_placeholder_label(
            "Summary results will appear here after running a calculation."
        )
        self.summary_stack.addWidget(self._summary_placeholder)
        self.summary_stack.setCurrentWidget(self._summary_placeholder)
        self.summary_scroll.setWidget(self.summary_stack)
        body_splitter.addWidget(self.summary_scroll)

        body_splitter.setSizes([10000, 160])
        body_splitter.setStretchFactor(0, 1)
        body_splitter.setStretchFactor(1, 0)

        # restore the user's last splitter layout (saved in BaseWindow.closeEvent)
        self.middle_splitter = middle_splitter
        self.body_splitter = body_splitter
        settings = app_settings()
        for splitter, key in ((middle_splitter, "libpage/middle_splitter"),
                              (body_splitter, "libpage/body_splitter")):
            state = settings.value(key)
            if state is not None:
                splitter.restoreState(state)

    # ------------------------------------------------------------------
    # Study tree — nodes hold no data of their own, only a NODE_ID_ROLE key
    # into self.scenarios (node id -> Scenario).
    # ------------------------------------------------------------------

    def _summary_placeholder_label(self, text):
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        return label

    def _build_study_tree_panel(self):
        panel = QWidget()
        panel.setObjectName("scenarioTreeWidget")
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("scenarioTreeHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(4)
        header_label = QLabel("Scenarios")
        header_label.setStyleSheet("font-weight: bold;")

        add_group_btn = QPushButton("+ Group")
        add_group_btn.setToolTip("Add a new scenario group to the study tree.")
        add_group_btn.clicked.connect(self._add_group_node)

        add_scenario_btn = QPushButton("+")
        add_scenario_btn.setToolTip("Add a new scenario, backed by a LIBInputs dataclass, under the selected group.")
        add_scenario_btn.clicked.connect(self._add_scenario_node)

        remove_btn = QPushButton("-")
        remove_btn.setToolTip("Remove the selected group or scenario from the study tree.")
        remove_btn.clicked.connect(self._remove_selected_node)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(add_group_btn, 1)
        button_layout.addWidget(add_scenario_btn, 1)
        button_layout.addWidget(remove_btn, 1)

        self.scenario_tree_inner = QTreeWidget()
        self.scenario_tree_inner.setObjectName("scenarioTreeInner")
        self.scenario_tree_inner.setHeaderHidden(True)
        self.scenario_tree_inner.setToolTip(
            "Double-click to edit, right-click for more options.\n"
            "Ctrl+C / Ctrl+V copies and pastes scenarios between groups.")
        self.scenario_tree_inner.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
        self.scenario_tree_inner.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scenario_tree_inner.customContextMenuRequested.connect(self._show_tree_context_menu)
        copy_shortcut = QShortcut(QKeySequence.Copy, self.scenario_tree_inner)
        copy_shortcut.activated.connect(self._copy_selected_scenario)
        paste_shortcut = QShortcut(QKeySequence.Paste, self.scenario_tree_inner)
        paste_shortcut.activated.connect(self._paste_copied_scenario)

        header_layout.addWidget(header_label)
        header_layout.addLayout(button_layout)
        layout.addWidget(header)
        layout.addWidget(self.scenario_tree_inner)
        return panel

    # ------------------------------------------------------------------
    # Study tree - pure presentation. Group names/order and scenario membership
    # live only on self.scenarios (ScenarioStore); every structural edit mutates
    # the store first and then redraws the tree from it, so the two can't drift.
    # ------------------------------------------------------------------

    def _refresh_tree(self, select_node_id=None, select_group=None):
        """Rebuild the QTreeWidget from the store, optionally restoring a selection."""
        self.scenario_tree_inner.clear()
        for group_name, scenarios in self.scenarios.groups().items():
            parent_item = QTreeWidgetItem([group_name or "Ungrouped"])
            parent_item.setData(0, NODE_TYPE_ROLE, NODE_GROUP)
            self.scenario_tree_inner.addTopLevelItem(parent_item)
            for scenario in scenarios:
                status = "R" if scenario.summary is not None else " "
                item = QTreeWidgetItem([f"[{status}] {scenario.name}"])
                item.setData(0, NODE_TYPE_ROLE, NODE_SCENARIO)
                item.setData(0, NODE_ID_ROLE, scenario.node_id)
                parent_item.addChild(item)
            parent_item.setExpanded(True)
            if select_group is not None and group_name == select_group:
                self.scenario_tree_inner.setCurrentItem(parent_item)
            elif select_node_id is not None:
                for child_index in range(parent_item.childCount()):
                    child = parent_item.child(child_index)
                    if child.data(0, NODE_ID_ROLE) == select_node_id:
                        self.scenario_tree_inner.setCurrentItem(child)

    def _refresh_tree_status(self):
        """Update each scenario label with whether a result is stored."""
        for group_index in range(self.scenario_tree_inner.topLevelItemCount()):
            group_item = self.scenario_tree_inner.topLevelItem(group_index)
            for child_index in range(group_item.childCount()):
                child = group_item.child(child_index)
                scenario = self.scenarios.get(child.data(0, NODE_ID_ROLE))
                if scenario is not None:
                    status = "R" if scenario.summary is not None else " "
                    child.setText(0, f"[{status}] {scenario.name}")

    def _show_tree_context_menu(self, pos):
        item = self.scenario_tree_inner.itemAt(pos)
        menu = QMenu(self)
        if item is None:
            menu.addAction("Add Group", self._add_group_node)
        else:
            self.scenario_tree_inner.setCurrentItem(item)
            if item.data(0, NODE_TYPE_ROLE) == NODE_SCENARIO:
                node_id = item.data(0, NODE_ID_ROLE)
                menu.addAction("Edit...", lambda: self._edit_scenario(node_id))
                menu.addAction("Duplicate", lambda: self._duplicate_scenario(node_id))
                menu.addAction("Run This Scenario", self.run_calc)
                menu.addSeparator()
                menu.addAction("Delete", self._remove_selected_node)
            else:
                menu.addAction("Add Scenario...", self._add_scenario_node)
                menu.addAction("Rename...", lambda: self._rename_group(item))
                menu.addAction("Run Group", self.run_calc)
                menu.addSeparator()
                menu.addAction("Delete Group", self._remove_selected_node)
        menu.exec(self.scenario_tree_inner.viewport().mapToGlobal(pos))

    def _add_group_node(self):
        base_name, count = "New Group", 1
        name = base_name
        while name in self.scenarios.group_names:
            count += 1
            name = f"{base_name} {count}"
        self.scenarios.add_group(name)
        self._refresh_tree(select_group=name)

    def _selected_group_name(self):
        item = self.scenario_tree_inner.currentItem()
        if item is None:
            return None
        if item.data(0, NODE_TYPE_ROLE) == NODE_GROUP:
            return item.text(0)
        parent = item.parent()
        if parent is not None and parent.data(0, NODE_TYPE_ROLE) == NODE_GROUP:
            return parent.text(0)
        return None

    def _add_scenario_node(self):
        group_name = self._selected_group_name()
        if group_name is None:
            QMessageBox.information(self, "Add Scenario", "Select (or create) a group to add the scenario to.")
            return

        dialog = ScenarioInputDialog(self, LIBInputs(), self._composition_names(), self._lib_names(),
                                     self._flowrate_names())
        if dialog.exec() != QDialog.Accepted:
            return

        scenario = self.scenarios.add(dialog.result_inputs, group=group_name)
        self._apply_composition(scenario)
        self._apply_lib_spec(scenario)
        self._apply_flowrate_profile(scenario)
        self._refresh_tree(select_node_id=scenario.node_id)

    def _on_tree_item_double_clicked(self, item, _column):
        node_type = item.data(0, NODE_TYPE_ROLE)
        if node_type == NODE_GROUP:
            self._rename_group(item)
        elif node_type == NODE_SCENARIO:
            self._edit_scenario(item.data(0, NODE_ID_ROLE))
        else:
            item.setExpanded(not item.isExpanded())

    def _rename_group(self, item):
        old_name = item.text(0)
        group_name, accepted = QInputDialog.getText(
            self, "Rename Group", "Group name:", text=old_name
        )
        group_name = group_name.strip()
        if not accepted or not group_name or group_name == old_name:
            return
        if not self.scenarios.rename_group(old_name, group_name):
            QMessageBox.warning(self, "Rename Group",
                                f"A group named '{group_name}' already exists.")
            return
        self._refresh_tree(select_group=group_name)

    def _edit_scenario(self, node_id):
        scenario = self.scenarios.get(node_id)
        if scenario is None:
            return

        dialog = ScenarioInputDialog(self, scenario.inputs, self._composition_names(), self._lib_names(),
                                     self._flowrate_names())
        if dialog.exec() != QDialog.Accepted:
            return

        self.scenarios.update_inputs(node_id, dialog.result_inputs)
        self._apply_composition(scenario)
        self._apply_lib_spec(scenario)
        self._apply_flowrate_profile(scenario)
        self._refresh_tree(select_node_id=node_id)
        self._refresh_result_watermarks()

    def _duplicate_scenario(self, node_id):
        scenario = self.scenarios.get(node_id)
        if scenario is None:
            return
        inputs = copy.deepcopy(scenario.inputs)
        inputs.scenario_description = f"Copy of {inputs.scenario_description}"
        duplicate = self.scenarios.add(inputs, group=scenario.group)
        self._apply_composition(duplicate)
        self._apply_lib_spec(duplicate)
        self._apply_flowrate_profile(duplicate)
        self._refresh_tree(select_node_id=duplicate.node_id)

    def _copy_selected_scenario(self):
        item = self.scenario_tree_inner.currentItem()
        if item is None or item.data(0, NODE_TYPE_ROLE) != NODE_SCENARIO:
            return
        scenario = self.scenarios.get(item.data(0, NODE_ID_ROLE))
        if scenario is not None:
            self._copied_scenario = copy.deepcopy(scenario)

    def _paste_copied_scenario(self):
        if self._copied_scenario is None:
            return
        group_name = self._selected_group_name()
        if group_name is None:
            QMessageBox.information(self, "Paste Scenario", "Select a group to paste the scenario into.")
            return

        inputs = copy.deepcopy(self._copied_scenario.inputs)
        inputs.scenario_description = f"Copy of {inputs.scenario_description}"
        scenario = self.scenarios.add(inputs, group=group_name)
        self._apply_composition(scenario)
        self._apply_lib_spec(scenario)
        self._apply_flowrate_profile(scenario)
        self._refresh_tree(select_node_id=scenario.node_id)

    def _remove_selected_node(self):
        item = self.scenario_tree_inner.currentItem()
        if item is None:
            return
        if item.data(0, NODE_TYPE_ROLE) == NODE_SCENARIO:
            node_id = item.data(0, NODE_ID_ROLE)
            self.scenarios.remove(node_id)
            self._remove_result_tab(node_id)
        elif item.data(0, NODE_TYPE_ROLE) == NODE_GROUP:
            for node_id in self.scenarios.remove_group(item.text(0)):
                self._remove_result_tab(node_id)
        self._refresh_tree()

    def _selected_scenario_node_ids(self):
        """Node ids to run: the selected scenario, every scenario in the selected
        group, or None (meaning "run everything") if nothing is selected."""
        item = self.scenario_tree_inner.currentItem()
        if item is None:
            return None
        node_type = item.data(0, NODE_TYPE_ROLE)
        if node_type == NODE_SCENARIO:
            return {item.data(0, NODE_ID_ROLE)}
        if node_type == NODE_GROUP:
            group_name = item.text(0)
            return {s.node_id for s in self.scenarios if s.group == group_name}
        return None

    def _scenarios_in_tree_order(self):
        """Every scenario in study-tree display order (group by group)."""
        return self.scenarios.scenarios_in_display_order()

    # ------------------------------------------------------------------
    # Session save / load — saveload.py handles the JSON, this side handles Qt.
    # ------------------------------------------------------------------

    def tree_snapshot(self):
        """[{'name': group, 'scenarios': [Scenario, ...]}, ...] in display order.

        Derived straight from the store - the tree widget holds no state of its own.
        """
        return [{"name": name, "scenarios": scenarios}
                for name, scenarios in self.scenarios.groups().items()]

    def restore_tree(self, groups):
        """Replace the scenario store from a snapshot and redraw the tree from it.

        Rebuild summaries and plots from saved results, not from current inputs.
        Older input-only sessions still start with an empty results panel.
        """
        from venting_calculation import build_result_plots, summarize_result

        self._clear_result_tabs()
        self._clear_summary_stack()
        self.scenarios = ScenarioStore()
        self._copied_scenario = None

        for group in groups or []:
            group_name = group.get("name", "")
            self.scenarios.add_group(group_name)
            for scenario in group.get("scenarios") or []:
                scenario.group = group_name
                self.scenarios.scenarios[scenario.node_id] = scenario
                self.scenarios._counter = max(self.scenarios._counter, scenario.node_id)
                self._apply_composition(scenario)
                self._apply_lib_spec(scenario)
                self._apply_flowrate_profile(scenario)
                scenario.summary = (
                    summarize_result(scenario.result, CHEMICAL_PROPERTIES)
                    if scenario.result is not None else None
                )
                if scenario.summary is not None:
                    self._set_result_tab(scenario.node_id, scenario.name,
                                         build_result_plots(scenario.summary))

        self._refresh_tree()
        if any(s.summary is not None for s in self.scenarios):
            self._show_result_summary("Saved Calculation Results")

    def session_snapshot(self):
        """Capture presentation choices separately from the scenario records."""
        tree = self.scenario_tree_inner
        selected = tree.currentItem()
        plots = []
        node_ids = {widget: node_id for node_id, widget in self._result_tab_widgets.items()}
        for index in range(self.result_tabs.count()):
            widget = self.result_tabs.widget(index)
            if not isinstance(widget, QTabWidget):
                raise TypeError("Scenario plots must be tab widgets.")
            checkboxes = []
            for tab in range(widget.count()):
                plot_tab = widget.widget(tab)
                assert plot_tab is not None
                checkboxes.append({
                    box.text(): box.isChecked() for box in plot_tab.findChildren(QCheckBox)
                })
            plots.append({
                "node_id": node_ids[widget],
                "active_tab": widget.currentIndex(),
                "checkboxes": checkboxes,
            })
        expanded_groups = {}
        for index in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(index)
            assert group is not None
            expanded_groups[group.text(0)] = group.isExpanded()
        return {
            "selected_node_id": (
                selected.data(0, NODE_ID_ROLE)
                if selected is not None and selected.data(0, NODE_TYPE_ROLE) == NODE_SCENARIO
                else None
            ),
            "selected_group": (
                selected.text(0)
                if selected is not None and selected.data(0, NODE_TYPE_ROLE) == NODE_GROUP
                else None
            ),
            "expanded_groups": expanded_groups,
            "plots": plots,
            "active_result": node_ids.get(self.result_tabs.currentWidget()),
        }

    def restore_session(self, state):
        tree = self.scenario_tree_inner
        for index in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(index)
            assert group is not None
            group.setExpanded(state.get("expanded_groups", {}).get(group.text(0), True))
            if group.text(0) == state.get("selected_group"):
                tree.setCurrentItem(group)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                assert child is not None
                if child.data(0, NODE_ID_ROLE) == state.get("selected_node_id"):
                    tree.setCurrentItem(child)

        for index, plot in enumerate(state.get("plots", [])):
            widget = self._result_tab_widgets.get(plot["node_id"])
            if widget is None:
                continue
            current_index = self.result_tabs.indexOf(widget)
            self.result_tabs.tabBar().moveTab(current_index, index)
            for tab, checkboxes in enumerate(plot.get("checkboxes", [])):
                if tab >= widget.count():
                    break
                for box in widget.widget(tab).findChildren(QCheckBox):
                    if box.text() in checkboxes:
                        box.setChecked(checkboxes[box.text()])
            widget.setCurrentIndex(plot.get("active_tab", 0))
        self._focus_result_tab(state.get("active_result"))

    # ------------------------------------------------------------------
    # Gas compositions
    # ------------------------------------------------------------------

    def _composition_names(self):
        return [NO_COMPOSITION] + list(self.base_window.custom_composition_definitions)

    def _apply_composition(self, scenario):
        """Bind the GasComposition named on the scenario's inputs to the Scenario."""
        scenario.gas_composition = self.base_window.custom_composition_definitions.get(
            scenario.inputs.gas_composition
        )

    # ------------------------------------------------------------------
    # Battery (LIB) definitions
    # ------------------------------------------------------------------

    def _lib_names(self):
        return [NO_LIB] + list(self.base_window.custom_lib_definitions)

    def _apply_lib_spec(self, scenario):
        """Bind the LIBSpec named on the scenario's inputs to the Scenario."""
        scenario.lib_spec = self.base_window.custom_lib_definitions.get(scenario.inputs.lib_spec)

    # ------------------------------------------------------------------
    # Flowrate datasets
    # ------------------------------------------------------------------

    def _flowrate_names(self):
        return [NO_FLOWRATE] + list(self.base_window.custom_flowrate_profiles)

    def _apply_flowrate_profile(self, scenario):
        """Bind the FlowrateProfile named on the scenario's inputs to the Scenario."""
        scenario.flowrate_profile = self.base_window.custom_flowrate_profiles.get(
            scenario.inputs.flowrate_profile
        )

    # ------------------------------------------------------------------
    # Results panel
    # ------------------------------------------------------------------

    def _show_summary(self, text):
        label = self._summary_placeholder_label(text)
        self.summary_stack.addWidget(label)
        self.summary_stack.setCurrentWidget(label)

    def clear_results(self):
        self.scenarios.clear_results()
        self._clear_summary_stack()
        self._clear_result_tabs()
        self._refresh_tree_status()

    def _clear_summary_stack(self):
        while self.summary_stack.count() > 1:
            widget = self.summary_stack.widget(1)
            self.summary_stack.removeWidget(widget)
            widget.deleteLater()
        self.summary_stack.setCurrentWidget(self._summary_placeholder)

    def _show_result_summary(self, title):
        """Render the summary strip as one table row per stored ResultSummary."""
        self._clear_summary_stack()
        rows = [(s.node_id, s.summary) for s in self._scenarios_in_tree_order()
                if s.summary is not None]
        if not rows:
            self._show_summary(f"{title}: no results were produced.")
            return

        headers = ["Scenario", "Method", "Peak Flam. (v/v%)", "Peak Time (s)",
               "Assessment LFL (v/v%)", "25% LFL Reached", "Worst Toxic (% of ERPG-3)",
               "Worst Toxic (mg/L)", "Worst Toxic (ppm)"]
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setToolTip("Click a row to show that scenario's plots.")

        for row, (_node_id, summary) in enumerate(rows):
            lfl_text = f"{summary.lfl_percent:.3f}" if summary.lfl_percent else "-"
            quarter_lfl_time = next(
                (time for time, percent in zip(summary.time, summary.percent_of_lfl_curve)
                 if percent >= 25.0),
                None,
            )
            if not summary.lfl_percent:
                quarter_lfl_text = "-"
            elif quarter_lfl_time is not None:
                quarter_lfl_text = f"t={quarter_lfl_time:.0f} s"
            else:
                quarter_lfl_text = "Not reached"

            worst = max((sp for sp in summary.toxic_species
                         if sp.percent_of_erpg_3 is not None),
                        key=lambda sp: sp.percent_of_erpg_3, default=None)
            worst_text = (f"{worst.species.upper()}: {worst.percent_of_erpg_3:.0f}%"
                          if worst is not None else "-")
            worst_mgl_text = f"{worst.peak_mgl:.3f}" if worst is not None else "-"
            worst_ppm_text = f"{worst.peak_ppm:.0f}" if worst is not None else "-"

            values = [summary.scenario_name, summary.calc_method,
                      f"{summary.peak_flammable_vv:.3f}",
                      f"{summary.peak_flammable_time:.0f}",
                      lfl_text, quarter_lfl_text, worst_text, worst_mgl_text, worst_ppm_text]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))

        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        node_ids = [node_id for node_id, _ in rows]
        table.cellClicked.connect(lambda row, _col: self._focus_result_tab(node_ids[row]))

        self.summary_stack.addWidget(table)
        self.summary_stack.setCurrentWidget(table)

    def _focus_result_tab(self, node_id):
        """Bring the scenario's plot tab to the front (from a summary row click)."""
        widget = self._result_tab_widgets.get(node_id)
        if widget is None:
            return
        index = self.result_tabs.indexOf(widget)
        if index != -1:
            self.result_tabs.setCurrentIndex(index)
            self.plot_stack.setCurrentWidget(self.result_tabs)

    def run_calc(self):
        from venting_calculation import run_venting_assessment, build_result_plots

        if not len(self.scenarios):
            QMessageBox.information(self, "Run", "Add at least one scenario first.")
            return
        node_ids = self._selected_scenario_node_ids()
        if node_ids is not None and not node_ids:
            QMessageBox.information(self, "Run", "The selected group has no scenarios.")
            return

        # One engine for every calculation method: each scenario's inputs.calc_method
        # selects its release model inside run_venting_assessment (see
        # venting_calculation.build_module_release). Scenarios outside node_ids keep
        # their stored results untouched.
        results = run_venting_assessment(self, self.scenarios, CHEMICAL_PROPERTIES,
                                         node_ids=node_ids)

        self._show_result_summary("Calculation Results")

        for node_id in results:
            scenario = self.scenarios.get(node_id)
            if scenario is not None and scenario.summary is not None:
                self._set_result_tab(node_id, scenario.name,
                                     build_result_plots(scenario.summary))

        for node_id in list(self._result_tab_widgets):
            scenario = self.scenarios.get(node_id)
            if scenario is None or scenario.result is None:
                self._remove_result_tab(node_id)
        self._refresh_result_watermarks()
        self._refresh_tree_status()

    def _refresh_result_watermarks(self):
        from venting_calculation import set_result_plots_out_of_date

        for node_id, widget in self._result_tab_widgets.items():
            scenario = self.scenarios.get(node_id)
            if scenario is not None:
                set_result_plots_out_of_date(widget, scenario.results_out_of_date)

    def _set_result_tab(self, node_id, label, widget):
        """Add the scenario's plot tab, replacing its previous one if it was run before."""
        previous = self._result_tab_widgets.pop(node_id, None)
        if previous is not None:
            index = self.result_tabs.indexOf(previous)
            if index != -1:
                self.result_tabs.removeTab(index)
            previous.deleteLater()

        self._result_tab_widgets[node_id] = widget
        self.result_tabs.setCurrentIndex(self.result_tabs.addTab(widget, label))
        self.plot_stack.setCurrentWidget(self.result_tabs)
        self._refresh_result_watermarks()

    def _clear_result_tabs(self):
        while self.result_tabs.count():
            widget = self.result_tabs.widget(0)
            self.result_tabs.removeTab(0)
            widget.deleteLater()
        self._result_tab_widgets.clear()
        self.plot_stack.setCurrentWidget(self.plot_placeholder)

    def _remove_result_tab(self, node_id):
        widget = self._result_tab_widgets.pop(node_id, None)
        if widget is None:
            return
        index = self.result_tabs.indexOf(widget)
        if index != -1:
            self.result_tabs.removeTab(index)
        widget.deleteLater()
        if not self.result_tabs.count():
            self.plot_stack.setCurrentWidget(self.plot_placeholder)

    def _on_result_tab_close_requested(self, index):
        """Close (x) on a result tab: drop the scenario's stored result so it
        stops appearing in the summary strip and is not included in any export."""
        widget = self.result_tabs.widget(index)
        node_id = next((nid for nid, w in self._result_tab_widgets.items() if w is widget), None)
        if node_id is None:
            return
        scenario = self.scenarios.get(node_id)
        if scenario is not None:
            scenario.result = None
            scenario.summary = None
        self._remove_result_tab(node_id)
        self._show_result_summary("Calculation Results")
        self._refresh_tree_status()


    def export_current_sheet_pdf(self):
        from pdf import export_lib_report_pdf
        export_lib_report_pdf(self, self._scenarios_in_tree_order())

    def open_results_table(self):
        from resultstable import open_results_table

        scenarios = [s for s in self._scenarios_in_tree_order() if s.summary is not None]
        if not scenarios:
            QMessageBox.information(self, "Results Table",
                                    "No scenarios have results yet - press Run first.")
            return
        open_results_table(self, scenarios)

    def open_library_manager(self):
        dialog = LibraryManagerDialog(self, self.base_window)
        dialog.exec()
        # library objects may have been renamed/deleted - rebind every scenario by name
        for scenario in self.scenarios:
            self._apply_composition(scenario)
            self._apply_lib_spec(scenario)
            self._apply_flowrate_profile(scenario)
        self._refresh_result_watermarks()


# Page for calculating sprinkler activation times from the supplied inputs.
class SprinklerPage(QWidget):
    """UI page for sprinkler activation time calculations."""
    PLACEHOLDER_TEXT = "Run a calculation to see the activation time here."
    CUSTOM_PRESET = "Custom"
    HISTORY_HEADERS = ["#", "Sprinkler ID", "Activation Time (s)", "Fire Growth",
                       "Ceiling Height (m)", "Radial Distance (m)", "RTI (m·s)^0.5",
                       "Activation Temp (°C)", "Ambient Temp (°C)", "HRR at Activation (kW)"]

    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window
        self.last_activation_time_s = None
        self.result_history = []

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # --- Toolbar ---
        toolbar = QToolBar("Sprinkler Activation Time Calculator")
        toolbar.setMovable(False)
        toolbarcontents = QWidget()
        toolbarcontents.setObjectName("toolbarContents")
        toolbarlayout = QHBoxLayout()
        toolbarlayout.setContentsMargins(0, 0, 0, 0)
        toolbarlayout.setSpacing(6)
        toolbarcontents.setLayout(toolbarlayout)
        toolbar.addWidget(toolbarcontents)

        run_button = QPushButton("Run")
        run_button.setObjectName("runButton")
        run_button.setShortcut(QKeySequence("Ctrl+Return"))
        run_button.setToolTip("Run the sprinkler activation time calculation (Ctrl+Enter).\n"
                              "Pressing Enter in any input field also runs it.")
        run_button.clicked.connect(self.run_sprinkler_calc)

        self.copy_activation_button = QPushButton("Copy Latest Result")
        self.copy_activation_button.setToolTip("Copy the latest activation time to the clipboard.")
        self.copy_activation_button.setEnabled(False)
        self.copy_activation_button.clicked.connect(self.copy_activation_duration)

        clear_inputs_button = QPushButton("Clear Inputs")
        clear_inputs_button.setToolTip("Clear all input fields. The results history is kept.")
        clear_inputs_button.clicked.connect(self.clear_inputs)

        clear_results_button = QPushButton("Clear Results")
        clear_results_button.setObjectName("clearAllButton")
        clear_results_button.setToolTip("Clear the latest result and the results history.")
        clear_results_button.clicked.connect(self.clear_results)

        toolbarlayout.addWidget(run_button)
        toolbarlayout.addWidget(self.copy_activation_button)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(clear_inputs_button)
        toolbarlayout.addWidget(clear_results_button)
        page_layout.addWidget(toolbar)

        # --- Body: inputs (left) | latest result + history (right) ---
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(20, 16, 20, 20)
        body_layout.setSpacing(20)
        page_layout.addLayout(body_layout, 1)

        input_panel = QWidget()
        input_panel.setMinimumWidth(360)
        input_panel.setMaximumWidth(460)
        input_column = QVBoxLayout(input_panel)
        input_column.setContentsMargins(0, 0, 0, 0)
        input_column.setSpacing(12)

        title = QLabel("Sprinkler Activation Time")
        title_font = title.font()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)

        subtitle = QLabel("t²-fire ceiling jet with an RTI detector response model "
                          "(SFPE Handbook, p. 1324).")
        subtitle.setWordWrap(True)

        # Sprinkler
        self.sprinkler_id = QLineEdit()
        self.sprinkler_id.setPlaceholderText("e.g. SPK-01 (optional)")
        self.sprinkler_id.setToolTip("Optional sprinkler identifier shown in the results history.")

        self.sprinkler_rti = QLineEdit()
        self.sprinkler_rti.setPlaceholderText("e.g. 80")
        self.sprinkler_rti.setToolTip("Sprinkler response time index (m·s)^0.5.")
        self.rti_preset = self._preset_combo(
            SPRINKLER_PROPERTIES["sprinkler response time index"], self.sprinkler_rti, "")
        self.rti_preset.setToolTip("Fill the RTI from a typical sprinkler type (AS 2118.1:2017).")

        self.activation_temperature = QLineEdit()
        self.activation_temperature.setPlaceholderText("e.g. 68")
        self.activation_temperature.setToolTip("Sprinkler activation temperature (°C).")
        self.activation_preset = self._preset_combo(
            SPRINKLER_PROPERTIES["activation temperatures"], self.activation_temperature, " °C")
        self.activation_preset.setToolTip("Fill the activation temperature from a bulb colour.")

        sprinkler_group, sprinkler_form = self._input_group("Sprinkler")
        sprinkler_form.addRow("Sprinkler ID:", self.sprinkler_id)
        sprinkler_form.addRow("RTI ((m·s)^0.5):", self._with_preset(self.sprinkler_rti, self.rti_preset))
        sprinkler_form.addRow("Activation Temp (°C):",
                              self._with_preset(self.activation_temperature, self.activation_preset))

        # Geometry
        self.ceiling_height = QLineEdit()
        self.ceiling_height.setPlaceholderText("e.g. 3.0")
        self.ceiling_height.setToolTip("Height of the ceiling above the fire source (m).")

        self.radial_distance = QLineEdit()
        self.radial_distance.setPlaceholderText("e.g. 2.0")
        self.radial_distance.setToolTip("Horizontal distance from the fire plume centreline to the sprinkler (m).")

        geometry_group, geometry_form = self._input_group("Geometry")
        geometry_form.addRow("Ceiling Height (m):", self.ceiling_height)
        geometry_form.addRow("Radial Distance (m):", self.radial_distance)

        # Fire & environment
        self.fire_growth_rate = QComboBox()
        for name, alpha in FIRE_PROPERTIES["fire growth rate"].items():
            self.fire_growth_rate.addItem(name)
            self.fire_growth_rate.setItemData(
                self.fire_growth_rate.count() - 1, f"α = {alpha} kW/s²", Qt.ToolTipRole)
        self.fire_growth_rate.setToolTip("t² fire growth rate category.")

        self.ambient_temperature = QLineEdit()
        self.ambient_temperature.setPlaceholderText("e.g. 20")
        self.ambient_temperature.setToolTip("Ambient room temperature (°C).")

        fire_group, fire_form = self._input_group("Fire && Environment")
        fire_form.addRow("Fire Growth Rate:", self.fire_growth_rate)
        fire_form.addRow("Ambient Temp (°C):", self.ambient_temperature)

        for edit in (self.sprinkler_id, self.sprinkler_rti, self.activation_temperature,
                     self.ceiling_height, self.radial_distance, self.ambient_temperature):
            edit.returnPressed.connect(self.run_sprinkler_calc)

        input_column.addWidget(title)
        input_column.addWidget(subtitle)
        input_column.addWidget(sprinkler_group)
        input_column.addWidget(geometry_group)
        input_column.addWidget(fire_group)
        input_column.addStretch()

        # Latest result card
        result_column = QVBoxLayout()
        result_column.setSpacing(12)

        latest_group = QGroupBox("Latest Result")
        latest_layout = QVBoxLayout(latest_group)
        latest_layout.setSpacing(4)
        self.latest_value_label = QLabel("—")
        value_font = self.latest_value_label.font()
        value_font.setPointSize(28)
        value_font.setBold(True)
        self.latest_value_label.setFont(value_font)
        self.latest_value_label.setAlignment(Qt.AlignCenter)
        self.latest_value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.results_label = QLabel(self.PLACEHOLDER_TEXT)
        self.results_label.setWordWrap(True)
        self.results_label.setAlignment(Qt.AlignCenter)
        self.results_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        latest_layout.addWidget(self.latest_value_label)
        latest_layout.addWidget(self.results_label)

        # History table
        history_group = QGroupBox("Results History")
        history_layout = QVBoxLayout(history_group)
        history_hint = QLabel("Every run is kept until Clear Results is pressed. "
                              "The newest result is listed first.")
        history_hint.setWordWrap(True)

        self.history_table = QTableWidget(0, len(self.HISTORY_HEADERS))
        self.history_table.setHorizontalHeaderLabels(self.HISTORY_HEADERS)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setStretchLastSection(True)

        history_layout.addWidget(history_hint)
        history_layout.addWidget(self.history_table)

        result_column.addWidget(latest_group)
        result_column.addWidget(history_group, 1)

        body_layout.addWidget(input_panel)
        body_layout.addLayout(result_column, 1)

    @staticmethod
    def _input_group(title):
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        return group, form

    @staticmethod
    def _with_preset(edit, combo):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(edit, 1)
        layout.addWidget(combo)
        return row

    def _preset_combo(self, presets, target, units):
        """Combo that fills `target` with a typical value; typing reverts it to Custom."""
        combo = QComboBox()
        combo.addItem(self.CUSTOM_PRESET, None)
        for name, value in presets.items():
            combo.addItem(f"{name.title()} ({value}{units})", value)
        def apply_preset(_index):
            if combo.currentData() is not None:
                target.setText(f"{combo.currentData():g}")

        combo.activated.connect(apply_preset)
        target.textEdited.connect(lambda _text: combo.setCurrentIndex(0))
        return combo

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
            data = self._get_sprinkler_inputs()
            result = activation_time_Calc(data)
        except ValueError as err:
            QMessageBox.warning(self, "Input Error", str(err))
            return
        except Exception as err:
            QMessageBox.critical(self, "Calculation Error", f"Failed to run calculation:\n{err}")
            return

        activation_time = result.get("activation_time_s")
        activated = activation_time is not None
        self.result_history.append({
            "sprinkler_id": data["sprinkler_id"],
            "fire_growth_rate": data["fire_growth_rate"],
            "ceiling_height": data["ceiling_height"],
            "radial_distance": data["radial_distance"],
            "rti": data["sprinkler_response_time_index"],
            "activation_temperature": data["sprinkler_activation_temperature"],
            "ambient_temperature": data["ambient_temperature"],
            "activation_time_s": activation_time,
            "heat_release_rate_kw": result["heat_release_rate_kw"] if activated else None,
            "detector_temperature_c": result["detector_temperature_c"],
            "ceiling_jet_temperature_c": result["ceiling_jet_temperature_c"],
            "jet_velocity_mps": result["jet_velocity_mps"],
        })

        self.last_activation_time_s = activation_time
        if activated:
            self.results_label.setText(
                f"Sprinkler {data['sprinkler_id']} · {data['fire_growth_rate']} fire\n"
                f"Detector temperature: {result['detector_temperature_c']:.1f} °C   ·   "
                f"Ceiling jet: {result['ceiling_jet_temperature_c']:.1f} °C at "
                f"{result['jet_velocity_mps']:.2f} m/s\n"
                f"Heat release rate at activation: {result['heat_release_rate_kw']:.0f} kW"
            )
        else:
            self.results_label.setText(
                f"Sprinkler {data['sprinkler_id']} did not activate within the maximum "
                "simulation time (10000 s)."
            )
        self._refresh_result_display()

    @staticmethod
    def _fmt(value, spec):
        return "-" if value is None else format(value, spec)

    def _refresh_result_display(self):
        """Redraw the latest-result value and the history table from stored state."""
        if self.last_activation_time_s is not None:
            self.latest_value_label.setText(f"{self.last_activation_time_s:.1f} s")
        elif self.result_history:
            self.latest_value_label.setText("No activation")
        else:
            self.latest_value_label.setText("—")
        self.copy_activation_button.setEnabled(self.last_activation_time_s is not None)

        table = self.history_table
        table.setRowCount(len(self.result_history))
        # newest first
        for row, (number, record) in enumerate(reversed(list(enumerate(self.result_history, 1)))):
            activation = record.get("activation_time_s")
            values = [
                str(number),
                str(record.get("sprinkler_id", "")),
                "No activation" if activation is None else f"{activation:.1f}",
                str(record.get("fire_growth_rate", "")),
                self._fmt(record.get("ceiling_height"), "g"),
                self._fmt(record.get("radial_distance"), "g"),
                self._fmt(record.get("rti"), "g"),
                self._fmt(record.get("activation_temperature"), "g"),
                self._fmt(record.get("ambient_temperature"), "g"),
                self._fmt(record.get("heat_release_rate_kw"), ".0f"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                if row == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                table.setItem(row, column, item)

    def copy_activation_duration(self):
        if self.last_activation_time_s is None:
            QMessageBox.warning(
                self,
                "No Activation Time",
                "The latest calculation has no activation time to copy.",
            )
            return

        QApplication.clipboard().setText(f"{self.last_activation_time_s:.1f} s")
        self.copy_activation_button.setText("Copied!")
        QTimer.singleShot(1500, lambda: self.copy_activation_button.setText("Copy Latest Result"))

    def session_snapshot(self):
        return {
            "activation_time_s": self.last_activation_time_s,
            "results_text": self.results_label.text(),
            "history": self.result_history,
        }

    def restore_session(self, state):
        self.last_activation_time_s = state.get("activation_time_s")
        self.result_history = list(state.get("history", []))
        self.results_label.setText(state.get("results_text", self.PLACEHOLDER_TEXT))
        self._refresh_result_display()

    def clear_inputs(self):
        for edit in (self.sprinkler_id, self.ceiling_height, self.radial_distance,
                     self.sprinkler_rti, self.activation_temperature, self.ambient_temperature):
            edit.clear()
        self.rti_preset.setCurrentIndex(0)
        self.activation_preset.setCurrentIndex(0)
        self.fire_growth_rate.setCurrentIndex(0)

    def clear_results(self):
        if self.result_history:
            reply = QMessageBox.question(
                self, "Clear Results", "Clear the latest result and the results history?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.result_history = []
        self.last_activation_time_s = None
        self.results_label.setText(self.PLACEHOLDER_TEXT)
        self._refresh_result_display()


# Tutorial page that explains how to use the modelling workflow.
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
                      "icon": "1.",
                      "title": "LIB Off-gassing: User Workflow",
                      "content": "Use the LIB Modelling Tool for a room-level estimate of off-gas concentrations from a lithium-ion battery thermal-runaway release. Work through the steps below: (1) define the battery and, if needed, gas composition and flowrate data in Libraries; (2) create a group and scenario; (3) enter the battery-system, room, ventilation and calculation inputs; (4) run the scenario or a selected group; and (5) review the plots and summaries, then export a PDF report if required. Check every input and assumption against the project-specific evidence before interpreting results."
            },
            {
                      "icon": "2.",
                      "title": "Prepare Libraries",
                      "content": "Open Libraries and define the objects your scenarios will use:\n• Batteries (LIB): enter the chemistry, cell format, state of charge, venting temperature, LFL, cell/module release data and propagation settings using the available project or test data.\n• Gas Compositions: choose Literature Data or create a User Defined percentage split of off-gas species. Confirm that the selected composition is appropriate for the battery and test basis.\n• Flowrate Datasets: import a two-column CSV (time in seconds, flowrate in L/s) describing ONE module. This is required only for the Module Variable Flowrate method; the dataset supplies the release profile and duration, while the scenario supplies composition.\nA named library object can be reused by multiple scenarios. Editing it affects scenarios that reference it, so review and rerun results after changing library data."
            },
            {
                      "icon": "3.",
                      "title": "Create and Configure Scenarios",
                      "content": "In the study tree, press '+ Group' to organise cases (for example by room or design option), select a group and press '+' to add a scenario. Enter the scenario description and manufacturer, select a Battery (LIB), and enter cells per module, modules per unit and number of units. Then set room height and floor area, the equipment-occupied percentage, standard ventilation rate and calculation duration. The off-gassing calculation uses a fixed 1-second time step. Use consistent units as shown beside each field. Room dimensions, free room volume and calculation duration must be positive; equipment occupancy must be at least 0% and less than 100%. Counts must be positive whole numbers. Ventilation rates and the emergency trigger must be non-negative: zero standard ventilation models a sealed room, and zero emergency ventilation or trigger disables emergency extraction. The engine repeats validation for loaded scenarios and reports invalid cases as skipped. Release volumes/capacities and module durations must be positive for the selected method; zero cell duration uses the empirical curve, and zero propagation delay is allowed. An entered or temperature-adjusted LFL must be finite, greater than 0% and no more than 100%. Double-click a scenario to edit it or a group to rename it; Ctrl+C / Ctrl+V copies scenarios between groups."
            },
            {
                      "icon": "4.",
                      "title": "Choose the Off-gas Release Method and Run",
                      "content": "Select a Composition Method and Calculation Method in the scenario. The release method describes one cell or module; module-to-module propagation then staggers the release across the system using the battery's propagation delay and number of modules initiated in each wave.\n• Cell Volume UL9540A: cells initiate in staggered cohorts. Each cell releases its entered volume along the empirical rise/decay curve when Cell Duration is 0, or at a constant rate over the entered duration when it is non-zero.\n• Module Volume UL9540A: one module's entered test volume is released at a constant rate over its entered duration.\n• Module Capacity: module capacity (kWh) is multiplied by the chemistry- and cell-format-specific literature value (L/kWh); this volume is released at a constant rate over the module duration.\n• Module Variable Flowrate: each module replays the selected measured dataset, which defines its flowrate and duration.\nPress Run to calculate. A selected scenario runs by itself, a selected group runs its scenarios, and with no selection all scenarios run."
            },
            {
                      "icon": "5.",
                      "title": "Review Results and Export",
                      "content": "Each completed scenario has flammable-gas and toxic-gas plots. Use the plot controls to inspect the available gas species and thresholds. A RESULTS OUT OF DATE watermark appears when scenario inputs or a referenced battery, user-defined composition or measured flowrate dataset differ from the stored run. Rerun the affected scenario to update its results and remove the watermark. Saved sessions retain this warning; older results without the required library snapshots also need a rerun. The results summary reports peak flammable concentration, the assessment LFL and whether/when it is reached, plus toxic-species peaks against ERPG-3 where available. Use Export PDF Report to select scenarios with stored results and include their inputs, battery specifications, plots and summary tables. Closing a result tab discards that scenario's stored result; Clear All removes all stored results."
            },
            {
                      "icon": "6.",
                      "title": "LIB Calculation Basis and Assumptions",
                      "content": "The LIB assessment is a simplified, transient, perfectly mixed room model. It calculates free room volume as room height × floor area × (1 − equipment-space percentage/100); gas is assumed to mix uniformly throughout that volume, so local concentrations and spatial stratification are not represented. Off-gas generation follows the selected release method and the entered or imported battery and propagation data. Ventilation is treated as a dilution/extraction rate: the entered L/s/m² is multiplied by room floor area. Emergency ventilation is optional; when enabled, the activation delay starts when room CO first reaches the entered percentage of CO's own LFL. Set Emergency Vent Activation Delay in Room Details to a non-negative number of seconds (default 0). The countdown continues even if CO drops below the trigger. Once the delay expires, the emergency rate applies while CO is at or above the trigger, and standard ventilation applies below it. Activation is evaluated at interval starts on the one-second calculation grid. A zero switch concentration disables this feature.\n                      Flammable concentrations are assessed against the battery LFL unless Use Le Chatelier LFL is selected to estimate a mixture LFL from the composition. The optional temperature-dependent adjustment applies to CO, H2 and total hydrocarbons. Toxic species are compared with their configured ERPG-3 values. The LIB off-gassing calculation uses a fixed 1-second time step; choose a duration that covers the release and assessment period."
            },
            {
                      "icon": "7.",
                      "title": "Interpretation and Limitations",
                      "content": "These outputs are estimates based on the supplied inputs, model assumptions, literature values and test data; they are not a substitute for a project-specific fire or hazard assessment. The well-mixed assumption cannot predict local peaks near a battery or poor mixing, and results are sensitive to release rates, composition, propagation, ventilation and selected thresholds. Verify data sources, units and applicability, and have the results reviewed by a suitably qualified person before using them for engineering decisions. A PDF records the model inputs and results; it does not independently validate them."
            },
            {
                      "icon": "8.",
                      "title": "Other Calculators: Sprinkler Activation",
                      "content": (
                          "Inputs: enter the ceiling height above the fire, horizontal radial distance from the plume centreline, "
                          "sprinkler response time index (RTI), activation temperature, ambient temperature and fire-growth category. "
                          "The RTI and bulb-colour presets fill typical values; check them against the actual sprinkler specification. "
                          "The sprinkler ID is optional.\n\n"
                          "Calculation process: the selected growth coefficient defines a t-squared fire, with heat release rate "
                          "Q = alpha x time squared. At each 0.1-second step, the code uses Alpert-type ceiling-jet correlations "
                          "to estimate the gas temperature and velocity at the sprinkler from Q, ceiling height and radial distance. "
                          "The sprinkler element starts at ambient temperature and heats towards the ceiling-jet temperature, "
                          "with response rate sqrt(jet velocity) / RTI. The thermal response is integrated over each step and "
                          "the threshold crossing is resolved within the step. Activation is the first time the element reaches "
                          "its activation temperature, not the time the gas reaches that temperature.\n\n"
                          "Outputs: press Run to display activation time, element and ceiling-jet temperatures, jet velocity and "
                          "heat release rate at activation. If the element does not activate within 10000 seconds, the result "
                          "reports no activation. Each run is retained in Results History; Copy Latest Result copies an available "
                          "activation time. Clear Inputs keeps the history, while Clear Results removes it.\n\n"
                          "Basis and limitations: this implementation was produced by Charlie Bibb using the SFPE Handbook "
                          "heat-detection method (p. 1324), not ArupCompute. It assumes the selected growing fire and a simplified "
                          "ceiling jet and RTI response; obstructions, sprinkler conduction losses and fire suppression after activation "
                          "are not modelled. Treat outputs as provisional and verify the method, inputs and applicability independently "
                          "before relying on them for design or safety decisions."
                      )
            },
            {
                      "icon": "9.",
                      "title": "Other Calculators: Pool Spill and Fire",
                      "content": (
                          "Inputs: select the fuel, surface material, surface weather and orifice condition. Enter ambient "
                          "temperature in kelvin, wind speed, bund area, volumetric flowrate, orifice diameter and pressure differential "
                          "in the displayed units. The orifice/pressure inputs and entered volumetric flowrate are used by different "
                          "spill correlations; check that they describe a consistent release.\n\n"
                          "Spill calculation: the code estimates an evaporation-limited area from the orifice discharge, fuel "
                          "properties, wind and temperature, and caps this area at the bund area (area_max). It separately estimates "
                          "an infiltration-limited area from volumetric flowrate, fuel viscosity and surface permeability "
                          "(area_permeability). The combined estimate is area_max x area_permeability / "
                          "(area_max + area_permeability), reported as area_combined. These are correlation-based estimates, "
                          "not a time-dependent simulation of pool spreading.\n\n"
                          "Operator Intervention: selecting this option requires an intervention time and pool depth. Choose a "
                          "ground-condition depth preset or Custom to enter a depth in metres. The code derives an evaporation "
                          "term from the existing fuel, wind and temperature inputs and applies the intervention correlation "
                          "to area_combined. The adjusted area is reported separately; the three baseline areas remain unchanged.\n\n"
                          "Pool Fire Calculation: selecting this option also requires pool depth. The fire uses area_combined, "
                          "or the intervention-adjusted area when intervention is selected. The code assumes a circular pool "
                          "to calculate diameter, and a uniform depth to calculate volume = area x depth. Heat release rate is "
                          "estimated from fuel mass burning rate, heat of combustion, pool area and a diameter-dependent correction. "
                          "Burn duration is volume / (area x liquid regression rate), where regression rate is mass burning rate / "
                          "liquid density. This represents depletion of the assumed pool inventory at a constant burning rate; "
                          "it does not model continued fuel supply during the fire. Heskestad and Thomas flame-height estimates "
                          "are reported separately.\n\n"
                          "Outputs and limitations: press Calculate to display the spill areas and selected intervention/fire "
                          "outputs; Copy Latest Result copies that assessment. The correlations (Brooks, Bozek and Barberio, "
                          "PCIC EUR25_03) and fuel-property data remain provisional, with some placeholder properties. "
                          "Verify property values, units, pool-depth assumptions and correlation applicability independently; "
                          "do not treat these outputs as validated design results."
                      )
            },
            {
                      "icon": "10.",
                      "title": "Other Calculators: Receptor Heat Flux",
                      "content": (
                          "Inputs: choose Emissive Power to enter the panel's radiant output in kW/m2, or Emitter Temperature "
                          "to enter surface temperature in kelvin and emissivity (greater than 0 and no more than 1). "
                          "Enter one or more emitter units, each with a unique name, panel length and panel width in metres. "
                          "All units share the emitter inputs and receptor distances. The receptor ID is optional.\n\n"
                          "Calculation process: for each unit and distance, the code calculates a dimensionless rectangular-panel "
                          "view factor using the implemented geometry from the ArupCompute view-factor documentation. "
                          "In Emissive Power mode, received heat flux = emissive power x view factor. In Emitter Temperature mode, "
                          "the panel's emissive power is calculated from emissivity x Stefan-Boltzmann constant x temperature "
                          "to the fourth power, then multiplied by the same view factor. Temperature must be absolute (kelvin), "
                          "and the constant is expressed in kW/m2/K4 so received heat flux is reported in kW/m2.\n\n"
                          "Distances and outputs: choose Single Point for one distance, or Range for start, end and step. "
                          "A range evaluates successive distances from the start; the end is included only when a step lands "
                          "on it. Up to 1000 distances are allowed. Press Run to calculate each unit independently and plot "
                          "its own curve; unit contributions are not summed. Latest Result shows the single result or the "
                          "largest result across the latest run. Results History records each unit/distance result, its view "
                          "factor and inputs. Plot height and width are adjustable; Copy Latest Result copies a single heat-flux "
                          "value or a distance-by-unit table for multiple results. Clear Inputs keeps history; Clear Results removes it.\n\n"
                          "Limitations: this is a radiation-only calculation for the implemented panel/receptor arrangement. "
                          "It does not model convection, atmospheric attenuation, shielding or a changing emitter temperature. "
                          "Verify that the geometry represents the actual arrangement and independently check the method, "
                          "inputs and units before relying on these provisional outputs for design."
                      )
            },
                  {
                      "icon": "11.",
                      "title": "Saving Sessions",
                      "content": "Use File > Save or Save As to store libraries, the study tree, scenario inputs and calculated results in a .libsave file. Reopening a session restores saved plots and summaries without rerunning the calculations. Rerun scenarios after changing relevant inputs or library definitions so the stored outputs correspond to the current setup."
                  },
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


# Page for pool spill and fire duration calculations.
class PoolSpillPage(QWidget):
    """Provisional spill and pool-fire calculator."""
    PLACEHOLDER_TEXT = "Run a calculation to see the pool spill areas here."

    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        toolbar = QToolBar("Pool Spill and Fire Calculator")
        toolbar.setMovable(False)
        toolbarcontents = QWidget()
        toolbarcontents.setObjectName("toolbarContents")
        toolbarlayout = QHBoxLayout(toolbarcontents)
        toolbarlayout.setContentsMargins(0, 0, 0, 0)
        toolbarlayout.setSpacing(6)
        toolbar.addWidget(toolbarcontents)

        calculate_button = QPushButton("Calculate")
        calculate_button.setObjectName("runButton")
        calculate_button.setShortcut(QKeySequence("Ctrl+Return"))
        calculate_button.setToolTip("Calculate the spill and selected fire outputs (Ctrl+Enter).")
        calculate_button.clicked.connect(self.run_pool_calculation)
        toolbarlayout.addWidget(calculate_button)

        self.copy_result_button = QPushButton("Copy Latest Result")
        self.copy_result_button.setToolTip("Copy the latest pool assessment to the clipboard.")
        self.copy_result_button.setEnabled(False)
        self.copy_result_button.clicked.connect(self.copy_latest_result)
        toolbarlayout.addWidget(self.copy_result_button)
        toolbarlayout.addWidget(_make_toolbar_separator())

        clear_inputs_button = QPushButton("Clear Inputs")
        clear_inputs_button.setToolTip("Clear numeric inputs, keeping the latest result.")
        clear_inputs_button.clicked.connect(self.clear_inputs)
        toolbarlayout.addWidget(clear_inputs_button)

        clear_results_button = QPushButton("Clear Results")
        clear_results_button.setObjectName("clearAllButton")
        clear_results_button.setToolTip("Clear the latest pool assessment.")
        clear_results_button.clicked.connect(self.clear_results)
        toolbarlayout.addWidget(clear_results_button)
        page_layout.addWidget(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        body_layout = QHBoxLayout(content)
        body_layout.setContentsMargins(20, 16, 20, 20)
        body_layout.setSpacing(20)
        scroll.setWidget(content)
        page_layout.addWidget(scroll, 1)

        input_panel = QWidget()
        input_panel.setMinimumWidth(360)
        input_panel.setMaximumWidth(460)
        input_column = QVBoxLayout(input_panel)
        input_column.setContentsMargins(0, 0, 0, 0)
        input_column.setSpacing(12)

        title = QLabel("Pool Spill & Fire")
        title_font = title.font()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        subtitle = QLabel("Spill spread correlations (Brooks, Bozek and Barberio, "
                          "PCIC EUR25_03), with optional pool-fire assessment.")
        subtitle.setWordWrap(True)
        input_column.addWidget(title)
        input_column.addWidget(subtitle)

        self.fuel_material = QComboBox()
        self.fuel_material.setToolTip("Select the fuel material for the pool spill.")
        self.fuel_material.addItems(list(POOL_SPREAD_DATA.keys()))
        self.fuel_material.setCurrentText("diesel")
        self.surface_weather = QComboBox()
        self.surface_weather.setToolTip("Select the surface weather condition for the pool spill.")
        self.surface_weather.addItems(list(POOL_PROPERTIES["relative_permeability"]))
        
        self.surface_material = QComboBox()
        self.surface_material.setToolTip("Select the surface material for the pool spill.\nFrom Table 1 of 'DETERMINATION OF FLAMMABLE LIQUID POOL SIZES AND THE RESULTANT HAZARDOUS DISTANCES'")
        self.surface_material.addItems(list(POOL_PROPERTIES["intrinsic_permeability"]))
        
        self.ground_conditions = QComboBox()
        self.ground_conditions.setToolTip("Select a typical pool depth from ground conditions, "
                          "or Custom to enter a depth in meters.")
        self.ground_conditions.addItems(list(POOL_PROPERTIES["average_pool_height"]))
        self.ground_conditions.addItem("Custom")
        
        self.orifice_condition = QComboBox()
        self.orifice_condition.setToolTip("Select the orifice condition for the pool spill.")
        self.orifice_condition.addItems(list(POOL_PROPERTIES["discharge_coefficients"]))
        
        #user inputs
        
        self.ambient_temperature = QLineEdit()
        self.ambient_temperature.setToolTip("Enter the ambient temperature in kelvin.")
        
        self.wind_speed = QLineEdit()
        self.wind_speed.setToolTip("Enter the surface wind speed in meters per second.")
        
        self.bund_size = QLineEdit()
        self.bund_size.setToolTip("Enter the maximum bunded pool area in square meters.")
        
        self.operator_intervention_time = QLineEdit()
        self.operator_intervention_time.setToolTip("Enter the operator intervention time in seconds.")
        
        self.orifice_diameter = QLineEdit()
        self.orifice_diameter.setToolTip("Enter the orifice diameter in meters.")
        
        self.delta_p = QLineEdit()
        self.delta_p.setToolTip("Enter the pressure differential in Pascals.")
        
        self.volumetric_flowrate = QLineEdit()
        self.volumetric_flowrate.setToolTip("Enter the volumetric flowrate in cubic meters per second.")

        self.pool_depth = QLineEdit()
        self.pool_depth.setToolTip("Assumed uniform pool depth in meters, used only for "
                       "operator intervention and pool-fire burn duration.")
        self.ground_conditions.currentTextChanged.connect(self._update_pool_depth)
        self.ground_conditions.setCurrentText("normal")
        self._update_pool_depth()

        fuel_group, fuel_form = SprinklerPage._input_group("Fuel && Environment")
        fuel_form.addRow("Fuel Material:", self.fuel_material)
        fuel_form.addRow("Ambient Temperature (K):", self.ambient_temperature)
        fuel_form.addRow("Wind Speed (m/s):", self.wind_speed)

        release_group, release_form = SprinklerPage._input_group("Release && Surface")
        release_form.addRow("Bund Area (m²):", self.bund_size)
        release_form.addRow("Volumetric Flowrate (m³/s):", self.volumetric_flowrate)
        release_form.addRow("Orifice Diameter (m):", self.orifice_diameter)
        release_form.addRow("Orifice Condition:", self.orifice_condition)
        release_form.addRow("Pressure Differential (Pa):", self.delta_p)
        release_form.addRow("Surface Material:", self.surface_material)
        release_form.addRow("Surface Weather:", self.surface_weather)

        self.pool_depth_group, depth_form = SprinklerPage._input_group("Pool Depth")
        depth_form.addRow("Pool Depth (m):",
                     SprinklerPage._with_preset(self.pool_depth, self.ground_conditions))

        self.oi_tickbox = QCheckBox("Operator Intervention")
        self.oi_tickbox.setToolTip("Apply the intervention correlation to the assessed area. "
                                 "The three baseline spill areas remain unchanged.")
        self.pool_fire_tickbox = QCheckBox("Pool Fire Calculation")
        self.pool_fire_tickbox.setToolTip("Calculate HRR, burn duration and flame heights "
                                        "for the assessed pool area and entered depth.")
        options_group = QGroupBox("Calculation Options")
        options_layout = QVBoxLayout(options_group)
        options_layout.addWidget(self.oi_tickbox)
        options_layout.addWidget(self.pool_fire_tickbox)

        self.optional_group, self.optional_layout = SprinklerPage._input_group("Operator Intervention")
        self.optional_layout.addRow("Operator Intervention Time (s):", self.operator_intervention_time)

        input_column.insertWidget(2, options_group)
        for group in (fuel_group, release_group, self.pool_depth_group, self.optional_group):
            input_column.addWidget(group)
        input_column.addStretch()

        self._numeric_inputs = (
            self.ambient_temperature, self.wind_speed, self.bund_size,
            self.operator_intervention_time, self.orifice_diameter, self.delta_p,
            self.volumetric_flowrate,
            self.pool_depth,
        )
        for edit in self._numeric_inputs:
            edit.returnPressed.connect(self.run_pool_calculation)

        results_panel = QWidget()
        results_panel.setMinimumWidth(300)
        result_column = QVBoxLayout(results_panel)
        result_column.setContentsMargins(0, 0, 0, 0)
        result_column.setSpacing(12)
        latest_group = QGroupBox("Latest Result")
        latest_layout = QVBoxLayout(latest_group)
        self.results_label = QLabel(self.PLACEHOLDER_TEXT)
        self.results_label.setTextFormat(Qt.PlainText)
        self.results_label.setWordWrap(True)
        self.results_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        result_font = self.results_label.font()
        result_font.setPointSize(12)
        self.results_label.setFont(result_font)
        latest_layout.addWidget(self.results_label)
        result_column.addWidget(latest_group)

        basis_label = QLabel(
            "Spill areas: area_max is the evaporation-limited area capped by the bund; "
            "area_permeability is the infiltration-limited area; area_combined combines "
            "the two limits. Operator intervention is a separate adjusted area. "
            "Its evaporation term is calculated from the existing fuel, wind and temperature inputs.\n\n"
            "Fire outputs use the assessed area (intervention-adjusted when selected). "
            "Flame heights are reported separately for Heskestad and Thomas."
        )
        basis_label.setWordWrap(True)
        result_column.addWidget(basis_label)
        warning_label = QLabel("PROVISIONAL - verify fuel properties, units, correlations "
                               "and applicability independently before using these results for design.")
        warning_label.setStyleSheet("color: red; font-weight: bold;")
        warning_label.setWordWrap(True)
        result_column.addWidget(warning_label)
        result_column.addStretch()
        body_layout.addWidget(input_panel)
        body_layout.addWidget(results_panel, 1)

        self.oi_tickbox.toggled.connect(self.toggle_optional_inputs)
        self.pool_fire_tickbox.toggled.connect(self.toggle_optional_inputs)
        self.toggle_optional_inputs()

    def toggle_optional_inputs(self):
        self.optional_group.setVisible(self.oi_tickbox.isChecked())
        self.pool_depth_group.setVisible(self.oi_tickbox.isChecked() or self.pool_fire_tickbox.isChecked())

    def _update_pool_depth(self, _text=None):
        depth = POOL_PROPERTIES["average_pool_height"].get(self.ground_conditions.currentText())
        self.pool_depth.setReadOnly(depth is not None)
        if depth is not None:
            self.pool_depth.setText(f"{depth:g}")

    def session_snapshot(self):
        return {"results_text": self.results_label.text()}

    def restore_session(self, state):
        selected_depth = POOL_PROPERTIES["average_pool_height"].get(self.ground_conditions.currentText())
        try:
            saved_depth = float(self.pool_depth.text())
        except ValueError:
            saved_depth = selected_depth
        if selected_depth is not None and saved_depth != selected_depth:
            self.ground_conditions.setCurrentText("Custom")
        self._update_pool_depth()
        self.toggle_optional_inputs()
        self.results_label.setText(state.get(
            "results_text", self.PLACEHOLDER_TEXT,
        ))
        self.copy_result_button.setEnabled(self.results_label.text().startswith("PROVISIONAL"))

    def copy_latest_result(self):
        if self.copy_result_button.isEnabled():
            QApplication.clipboard().setText(self.results_label.text())

    def clear_inputs(self):
        for edit in self._numeric_inputs:
            edit.clear()
        self.ground_conditions.setCurrentText("normal")
        self._update_pool_depth()

    def clear_results(self):
        self.results_label.setText(self.PLACEHOLDER_TEXT)
        self.copy_result_button.setEnabled(False)

    def _pool_number(self, widget, label, allow_zero=False):
        text = widget.text().strip()
        if not text:
            raise ValueError(f"{label} is required.")
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be a valid number.") from exc
        if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
            limit = "0 or greater" if allow_zero else "greater than 0"
            raise ValueError(f"{label} must be finite and {limit}.")
        return value

    def run_pool_calculation(self):
        try:
            result = calculate_pool_assessment(
                bund_area=self._pool_number(self.bund_size, "Bund area"),
                fuel=self.fuel_material.currentText(),
                wind_speed=self._pool_number(self.wind_speed, "Wind speed"),
                orifice_diameter=self._pool_number(self.orifice_diameter, "Orifice diameter"),
                delta_p=self._pool_number(self.delta_p, "Pressure differential"),
                ambient_temperature=self._pool_number(self.ambient_temperature, "Ambient temperature"),
                volumetric_flow_rate=self._pool_number(self.volumetric_flowrate, "Volumetric flow rate"),
                surface=self.surface_material.currentText(),
                weather=self.surface_weather.currentText(),
                orifice_condition=self.orifice_condition.currentText(),
                pool_depth=(self._pool_number(self.pool_depth, "Pool depth")
                            if self.oi_tickbox.isChecked() or self.pool_fire_tickbox.isChecked() else None),
                ground_description=self.ground_conditions.currentText(),
                intervention_time=(
                    self._pool_number(self.operator_intervention_time, "Operator intervention time", allow_zero=True)
                    if self.oi_tickbox.isChecked() else None
                ),
                include_fire=self.pool_fire_tickbox.isChecked(),
            )
        except (ValueError, KeyError, OverflowError, ZeroDivisionError) as exc:
            self.results_label.setText("Calculation not available for these inputs.")
            self.copy_result_button.setEnabled(False)
            QMessageBox.warning(self, "Pool Calculation Error", str(exc))
            return

        lines = [
            "PROVISIONAL - fuel properties and units must be verified before use.",
            f"Fuel: {self.fuel_material.currentText()}",
            "",
            "POOL SPILL",
            f"Maximum area (area_max, bund-capped): {result['area_max_m2']:.4g} m²",
            f"Permeability area (area_permeability): {result['area_permeability_m2']:.4g} m²",
            f"Combined area (area_combined): {result['area_combined_m2']:.4g} m²",
        ]
        if self.oi_tickbox.isChecked():
            lines.append(f"Operator intervention area: {result['area_intervention_m2']:.4g} m²")
        if self.pool_fire_tickbox.isChecked():
            lines.extend((
                "", "POOL FIRE",
                f"Pool depth: {result['pool_depth_m']:.4g} m",
                f"Pool diameter: {result['pool_diameter_m']:.4g} m",
                f"Pool volume: {result['pool_volume_m3']:.4g} m³",
                f"Heat release rate: {result['heat_release_rate']:.4g} kW",
                f"Burn duration: {result['burn_duration_s']:.4g} s",
                f"Flame height (Heskestad): {result['flame_height_heskestad_m']:.4g} m",
                f"Flame height (Thomas): {result['flame_height_thomas_m']:.4g} m",
            ))
        self.results_label.setText("\n".join(lines))
        self.copy_result_button.setEnabled(True)


# Page for radiant heat flux received from a rectangular emitting panel.
class ReceptorHeatFlux(QWidget):
    """UI page for the receptor heat flux (view factor) calculator."""
    PLACEHOLDER_TEXT = "Run a calculation to see the received heat flux here."
    HISTORY_HEADERS = ["Run", "Receptor ID", "Unit", "Input", "Distance to Receptor (m)",
                       "Received Heat Flux (kW/m²)", "View Factor",
                       "Emissive Power (kW/m²)", "Emitter Temp (K)", "Emissivity",
                       "Panel Length (m)", "Panel Width (m)"]
    UNIT_HEADERS = ["Unit", "Panel Length (m)", "Panel Width (m)"]
    DEFAULT_PLOT_HEIGHT = 360
    DISTANCE_POINT = "Single Point"
    DISTANCE_RANGE = "Range"
    MAX_RANGE_POINTS = 1000
    MODE_HEAT_FLUX = "Emissive Power"
    MODE_TEMPERATURE = "Emitter Temperature"
    # mode -> (calculation function, emitter field attributes it consumes)
    INPUT_MODES = {
        MODE_HEAT_FLUX: (heat_flux_of_emitter, ("emissive_power",)),
        MODE_TEMPERATURE: (temp_of_emitter, ("emitter_temperature", "emissivity")),
    }
    # (attribute, label, calculation keyword, tooltip)
    EMITTER_FIELDS = [
        ("emissive_power", "Emissive Power (kW/m²):", "emmissive_power",
         "Emissive power of the radiating panel (kW/m²)."),
        ("emitter_temperature", "Emitter Temperature (K):", "temp_of_emitter",
         "Surface temperature of the radiating panel (K)."),
        ("emissivity", "Emissivity (-):", "emissivity",
         "Emissivity of the radiating panel (0 - 1)."),
    ]
    POINT_FIELDS = [
        ("perp_distance_to_receptor", "Distance to Receptor (m):", "perp_distance_to_receptor",
         "Distance from the emitter to the receptor (m)."),
    ]
    RANGE_FIELDS = [
        ("range_start", "Range Start (m):", "range_start",
         "First receptor distance in the range (m)."),
        ("range_end", "Range End (m):", "range_end",
         "Last receptor distance in the range (m)."),
        ("range_step", "Range Step (m):", "range_step",
         "Spacing between the calculated distances (m)."),
    ]
    PANEL_FIELDS = [
        ("Panel Length (m)", "length_of_radiating_panel"),
        ("Panel Width (m)", "width_of_radiating_panel"),
    ]
    NUMERIC_FIELDS = EMITTER_FIELDS + POINT_FIELDS + RANGE_FIELDS
    FIELD_DEFAULTS = {**DEFAULT_HEAT_FLUX_INPUTS, "range_start": 1, "range_end": 20, "range_step": 1}

    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window
        self.result_history = []

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # --- Toolbar ---
        toolbar = QToolBar("Receptor Heat Flux Calculator")
        toolbar.setMovable(False)
        toolbarcontents = QWidget()
        toolbarcontents.setObjectName("toolbarContents")
        toolbarlayout = QHBoxLayout()
        toolbarlayout.setContentsMargins(0, 0, 0, 0)
        toolbarlayout.setSpacing(6)
        toolbarcontents.setLayout(toolbarlayout)
        toolbar.addWidget(toolbarcontents)

        run_button = QPushButton("Run")
        run_button.setObjectName("runButton")
        run_button.setShortcut(QKeySequence("Ctrl+Return"))
        run_button.setToolTip("Run the receptor heat flux calculation (Ctrl+Enter).\n"
                              "Pressing Enter in any input field also runs it.")
        run_button.clicked.connect(self.run_heat_flux_calc)

        self.copy_result_button = QPushButton("Copy Latest Result")
        self.copy_result_button.setToolTip("Copy the latest received heat flux to the clipboard.\n"
                                           "Range runs are copied as a distance / heat flux table.")
        self.copy_result_button.setEnabled(False)
        self.copy_result_button.clicked.connect(self.copy_latest_result)

        defaults_button = QPushButton("Load Example Inputs")
        defaults_button.setToolTip("Fill the inputs with the example values from the calculation module.")
        defaults_button.clicked.connect(self.load_example_inputs)

        clear_inputs_button = QPushButton("Clear Inputs")
        clear_inputs_button.setToolTip("Clear all input fields. The results history is kept.")
        clear_inputs_button.clicked.connect(self.clear_inputs)

        clear_results_button = QPushButton("Clear Results")
        clear_results_button.setObjectName("clearAllButton")
        clear_results_button.setToolTip("Clear the latest result and the results history.")
        clear_results_button.clicked.connect(self.clear_results)

        toolbarlayout.addWidget(run_button)
        toolbarlayout.addWidget(self.copy_result_button)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(defaults_button)
        toolbarlayout.addWidget(clear_inputs_button)
        toolbarlayout.addWidget(clear_results_button)
        page_layout.addWidget(toolbar)

        # --- Body: inputs (left) | latest result + history (right) ---
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(20, 16, 20, 20)
        body_layout.setSpacing(20)
        page_layout.addLayout(body_layout, 1)

        input_panel = QWidget()
        input_panel.setMinimumWidth(360)
        input_panel.setMaximumWidth(460)
        input_column = QVBoxLayout(input_panel)
        input_column.setContentsMargins(0, 0, 0, 0)
        input_column.setSpacing(12)

        title = QLabel("Receptor Heat Flux")
        title_font = title.font()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)

        subtitle = QLabel("Radiant heat flux received from a rectangular emitting panel, "
                          "using the view factor method (ArupCompute documentation). "
                          "Received heat flux = emissive power × view factor, or "
                          "ε σ T⁴ × view factor when the emitter temperature is entered.")
        subtitle.setWordWrap(True)

        self.input_mode = QComboBox()
        self.input_mode.addItems(list(self.INPUT_MODES))
        self.input_mode.setToolTip("Choose whether the emitter is defined by its emissive power "
                                   "or by its temperature and emissivity.\n"
                                   "Geometry inputs are shared by both methods.")

        self.receptor_id = QLineEdit()
        self.receptor_id.setPlaceholderText("e.g. R-01 (optional)")
        self.receptor_id.setToolTip("Optional receptor identifier shown in the results history.")
        self.receptor_id.returnPressed.connect(self.run_heat_flux_calc)

        receptor_group, receptor_form = SprinklerPage._input_group("Emitter && Receptor")
        receptor_form.addRow("Receptor ID:", self.receptor_id)
        receptor_form.addRow("Emitter Input:", self.input_mode)
        geometry_group, geometry_form = SprinklerPage._input_group("Geometry")
        self._emitter_form = receptor_form
        self._geometry_form = geometry_form

        self.distance_mode = QComboBox()
        self.distance_mode.addItems([self.DISTANCE_POINT, self.DISTANCE_RANGE])
        self.distance_mode.setToolTip("Calculate at a single receptor distance, or at every step "
                                      "across a range of distances and plot the result.")
        geometry_form.addRow("Distance Input:", self.distance_mode)

        for fields, form in ((self.EMITTER_FIELDS, receptor_form),
                             (self.POINT_FIELDS + self.RANGE_FIELDS, geometry_form)):
            for attribute, label, key, tooltip in fields:
                edit = QLineEdit()
                edit.setPlaceholderText(f"e.g. {self.FIELD_DEFAULTS[key]:g}")
                edit.setToolTip(f"{tooltip}\nMust be greater than 0.")
                edit.returnPressed.connect(self.run_heat_flux_calc)
                setattr(self, attribute, edit)
                form.addRow(label, edit)

        self.input_mode.currentTextChanged.connect(self._update_mode_fields)
        self.distance_mode.currentTextChanged.connect(self._update_mode_fields)
        self._update_mode_fields()

        units_group = QGroupBox("Emitter Units")
        units_layout = QVBoxLayout(units_group)
        units_hint = QLabel("Each unit uses the emitter and distance inputs above with its own "
                            "panel size, and is plotted as a separate curve.")
        units_hint.setWordWrap(True)
        self.units_table = QTableWidget(0, len(self.UNIT_HEADERS))
        self.units_table.setHorizontalHeaderLabels(self.UNIT_HEADERS)
        self.units_table.verticalHeader().setVisible(False)
        self.units_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.units_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.units_table.setMinimumHeight(140)
        self.units_table.setToolTip("Double-click a cell to edit it.\n"
                                    "Panel length and width must be greater than 0.")
        add_unit_button = QPushButton("+ Unit")
        add_unit_button.setToolTip("Add another unit geometry.")
        add_unit_button.clicked.connect(lambda: self._add_unit_row())
        remove_unit_button = QPushButton("- Unit")
        remove_unit_button.setToolTip("Remove the selected unit (or the last one).")
        remove_unit_button.clicked.connect(self._remove_unit_row)
        unit_buttons = QHBoxLayout()
        unit_buttons.addWidget(add_unit_button)
        unit_buttons.addWidget(remove_unit_button)
        unit_buttons.addStretch()
        units_layout.addWidget(units_hint)
        units_layout.addWidget(self.units_table)
        units_layout.addLayout(unit_buttons)
        self._add_unit_row()

        input_column.addWidget(title)
        input_column.addWidget(subtitle)
        input_column.addWidget(receptor_group)
        input_column.addWidget(geometry_group)
        input_column.addWidget(units_group)
        input_column.addStretch()

        # Scrollable results column: latest result, plot, then history table
        results_panel = QWidget()
        result_column = QVBoxLayout(results_panel)
        result_column.setContentsMargins(0, 0, 8, 0)
        result_column.setSpacing(12)

        latest_group = QGroupBox("Latest Result")
        latest_layout = QVBoxLayout(latest_group)
        latest_layout.setSpacing(4)
        self.latest_value_label = QLabel("—")
        value_font = self.latest_value_label.font()
        value_font.setPointSize(28)
        value_font.setBold(True)
        self.latest_value_label.setFont(value_font)
        self.latest_value_label.setAlignment(Qt.AlignCenter)
        self.latest_value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.results_label = QLabel(self.PLACEHOLDER_TEXT)
        self.results_label.setWordWrap(True)
        self.results_label.setAlignment(Qt.AlignCenter)
        self.results_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        latest_layout.addWidget(self.latest_value_label)
        latest_layout.addWidget(self.results_label)

        plot_group = QGroupBox("Heat Flux vs Distance")
        plot_layout = QVBoxLayout(plot_group)
        self.figure = Figure(figsize=(6, 3.6), layout="tight")
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.figure)

        self.plot_height = QSpinBox()
        self.plot_height.setRange(200, 2000)
        self.plot_height.setSingleStep(20)
        self.plot_height.setSuffix(" px")
        self.plot_height.setValue(self.DEFAULT_PLOT_HEIGHT)
        self.plot_height.setToolTip("Height of the plot.")
        self.plot_width = QSpinBox()
        self.plot_width.setRange(0, 4000)
        self.plot_width.setSingleStep(50)
        self.plot_width.setSuffix(" px")
        self.plot_width.setSpecialValueText("Auto")
        self.plot_width.setToolTip("Width of the plot. 'Auto' fits the available space; "
                                   "wider plots can be scrolled horizontally.")
        self.plot_height.valueChanged.connect(self._apply_plot_size)
        self.plot_width.valueChanged.connect(self._apply_plot_size)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Plot height:"))
        size_row.addWidget(self.plot_height)
        size_row.addSpacing(12)
        size_row.addWidget(QLabel("Plot width:"))
        size_row.addWidget(self.plot_width)
        size_row.addStretch()
        self._apply_plot_size()

        plot_layout.addLayout(size_row)
        plot_layout.addWidget(NavigationToolbar2QT(self.canvas, plot_group))
        plot_layout.addWidget(self.canvas)

        history_group = QGroupBox("Results History")
        history_layout = QVBoxLayout(history_group)
        history_hint = QLabel("Every run is kept until Clear Results is pressed. The newest run "
                              "is listed first; a range run adds one row per distance.")
        history_hint.setWordWrap(True)

        self.history_table = QTableWidget(0, len(self.HISTORY_HEADERS))
        self.history_table.setMinimumHeight(280)
        self.history_table.setHorizontalHeaderLabels(self.HISTORY_HEADERS)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setStretchLastSection(True)

        history_layout.addWidget(history_hint)
        history_layout.addWidget(self.history_table)

        warning_label = QLabel("Provisional calculator - verify the method, inputs and units "
                               "independently before relying on the results for design.")
        warning_label.setStyleSheet("color: red; font-weight: bold;")
        warning_label.setWordWrap(True)

        result_column.addWidget(latest_group)
        result_column.addWidget(plot_group)
        result_column.addWidget(history_group)
        result_column.addWidget(warning_label)

        results_scroll = QScrollArea()
        results_scroll.setWidgetResizable(True)
        results_scroll.setFrameShape(QFrame.NoFrame)
        results_scroll.setWidget(results_panel)

        body_layout.addWidget(input_panel)
        body_layout.addWidget(results_scroll, 1)
        self._draw_plot([])

    def _apply_plot_size(self, _value=None):
        self.canvas.setFixedHeight(self.plot_height.value())
        width = self.plot_width.value()
        if width:
            self.canvas.setFixedWidth(width)
        else:
            self.canvas.setMinimumWidth(0)
            self.canvas.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX

    def _add_unit_row(self, name=None, length="", width=""):
        row = self.units_table.rowCount()
        self.units_table.insertRow(row)
        for column, text in enumerate((name or f"Unit {row + 1}", length, width)):
            self.units_table.setItem(row, column, QTableWidgetItem(text))

    def _remove_unit_row(self):
        table = self.units_table
        if table.rowCount() <= 1:
            QMessageBox.information(self, "Remove Unit", "At least one unit is required.")
            return
        row = table.currentRow()
        table.removeRow(row if row >= 0 else table.rowCount() - 1)

    def _set_units(self, units):
        self.units_table.setRowCount(0)
        for name, length, width in units:
            self._add_unit_row(name, length, width)

    def _unit_rows(self):
        """Raw (name, length, width) text for every row of the units table."""
        rows = []
        for row in range(self.units_table.rowCount()):
            cells = [self.units_table.item(row, column) for column in range(len(self.UNIT_HEADERS))]
            rows.append(tuple(cell.text().strip() if cell is not None else "" for cell in cells))
        return rows

    def _read_units(self):
        """Validated [(unit name, panel geometry kwargs), ...] from the units table."""
        units = []
        for row, (name, *texts) in enumerate(self._unit_rows(), 1):
            name = name or f"Unit {row}"
            geometry = {key: self._parse_positive(f"{name} {label}", text, key)
                        for (label, key), text in zip(self.PANEL_FIELDS, texts)}
            units.append((name, geometry))
        if not units:
            raise ValueError("Add at least one unit.")
        names = [name for name, _geometry in units]
        if len(set(names)) != len(names):
            raise ValueError("Each unit needs a different name.")
        return units

    def _update_mode_fields(self, _text=None):
        """Show only the inputs the selected emitter and distance options consume."""
        _function, used = self.INPUT_MODES[self.input_mode.currentText()]
        for attribute, *_rest in self.EMITTER_FIELDS:
            self._emitter_form.setRowVisible(getattr(self, attribute), attribute in used)
        is_range = self.distance_mode.currentText() == self.DISTANCE_RANGE
        for attribute, *_rest in self.POINT_FIELDS:
            self._geometry_form.setRowVisible(getattr(self, attribute), not is_range)
        for attribute, *_rest in self.RANGE_FIELDS:
            self._geometry_form.setRowVisible(getattr(self, attribute), is_range)

    def _distances(self):
        """Receptor distances to calculate: the single point, or every step of the range."""
        if self.distance_mode.currentText() != self.DISTANCE_RANGE:
            return [self._read_fields(self.POINT_FIELDS)["perp_distance_to_receptor"]]
        values = self._read_fields(self.RANGE_FIELDS)
        start, end, step = values["range_start"], values["range_end"], values["range_step"]
        if end <= start:
            raise ValueError("Range End must be greater than Range Start.")
        count = int(math.floor((end - start) / step + 1e-9)) + 1
        if count > self.MAX_RANGE_POINTS:
            raise ValueError(f"The range gives {count} distances - increase the step so there "
                             f"are no more than {self.MAX_RANGE_POINTS}.")
        return [round(start + index * step, 10) for index in range(count)]

    def _read_fields(self, fields):
        """Collect and validate line-edit values as calculation keyword arguments."""
        return {key: self._parse_positive(label.rstrip(":"), getattr(self, attribute).text().strip(), key)
                for attribute, label, key, _tooltip in fields}

    @staticmethod
    def _parse_positive(name, text, key):
        if not text:
            raise ValueError(f"{name} is required.")
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError(f"{name} must be a valid number.") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and greater than 0.")
        if key == "emissivity" and value > 1:
            raise ValueError(f"{name} must not be greater than 1.")
        return value

    def run_heat_flux_calc(self):
        mode = self.input_mode.currentText()
        calculation, used = self.INPUT_MODES[mode]
        emitter_fields = [field for field in self.EMITTER_FIELDS if field[0] in used]
        try:
            inputs = self._read_fields(emitter_fields)
            units = self._read_units()
            distances = self._distances()
            results = [(name, geometry, distance,
                        calculation(**inputs, **geometry, perp_distance_to_receptor=distance))
                       for name, geometry in units for distance in distances]
        except ValueError as err:
            QMessageBox.warning(self, "Input Error", str(err))
            return
        except (OverflowError, ZeroDivisionError) as err:
            QMessageBox.critical(self, "Calculation Error", f"Failed to run calculation:\n{err}")
            return

        receptor_id = self.receptor_id.text().strip() or "Receptor-1"
        run = self._latest_run_number() + 1
        records = [{
            "run": run,
            "receptor_id": receptor_id,
            "unit_name": name,
            "input_mode": mode,
            "distance_mode": self.distance_mode.currentText(),
            "perp_distance_to_receptor": distance,
            "received_heat_flux": result["received_heat_flux"],
            "view_factor": result["view_factor"],
            **inputs,
            **geometry,
        } for name, geometry, distance, result in results]
        self.result_history.extend(records)

        if mode == self.MODE_TEMPERATURE:
            emitter_text = (f"Emitter {inputs['temp_of_emitter']:g} K, "
                            f"emissivity {inputs['emissivity']:g}")
        else:
            emitter_text = f"Emissive power {inputs['emmissive_power']:g} kW/m²"
        if len(records) == 1:
            record = records[0]
            self.results_label.setText(
                f"Receptor {receptor_id} · {record['unit_name']} · "
                f"view factor {record['view_factor']:.4f}\n{emitter_text} · panel "
                f"{record['length_of_radiating_panel']:g} m × "
                f"{record['width_of_radiating_panel']:g} m at {distances[0]:g} m"
            )
        else:
            peak = max(records, key=lambda record: record["received_heat_flux"])
            unit_text = units[0][0] if len(units) == 1 else f"{len(units)} units"
            distance_text = (f"{len(distances)} distances from {distances[0]:g} m to "
                             f"{distances[-1]:g} m" if len(distances) > 1
                             else f"at {distances[0]:g} m")
            self.results_label.setText(
                f"Receptor {receptor_id} · {unit_text} · {distance_text}\n{emitter_text} · "
                f"peak at {peak['perp_distance_to_receptor']:g} m ({peak['unit_name']})"
            )
        self._refresh_result_display()

    def _latest_run_number(self):
        return max((record.get("run", 0) for record in self.result_history), default=0)

    def _latest_run_records(self):
        if not self.result_history:
            return []
        run = self._latest_run_number()
        return [record for record in self.result_history if record.get("run") == run]

    def _draw_plot(self, records):
        axes = self.axes
        axes.clear()
        axes.set_xlabel("Distance to Receptor (m)")
        axes.set_ylabel("Received Heat Flux (kW/m²)")
        axes.grid(True, alpha=0.3)
        if records:
            curves = {}
            for record in records:
                curves.setdefault(record.get("unit_name", "Unit 1"), []).append(record)
            for name, unit_records in curves.items():
                axes.plot([record.get("perp_distance_to_receptor") for record in unit_records],
                          [record.get("received_heat_flux") for record in unit_records],
                          marker="o", markersize=4, label=name)
            if len(curves) > 1:
                axes.legend()
            axes.set_title(f"{records[0].get('receptor_id', '')} - "
                           f"{records[0].get('input_mode', self.MODE_HEAT_FLUX)}")
        else:
            axes.text(0.5, 0.5, "Run a calculation to plot heat flux against distance.",
                      transform=axes.transAxes, ha="center", va="center", color="gray")
        self.canvas.draw_idle()

    def _refresh_result_display(self):
        """Redraw the latest-result value, plot and history table from stored state."""
        latest = self._latest_run_records()
        if not latest:
            self.latest_value_label.setText("—")
        elif len(latest) == 1:
            self.latest_value_label.setText(f"{latest[0]['received_heat_flux']:.3f} kW/m²")
        else:
            peak = max(record["received_heat_flux"] for record in latest)
            self.latest_value_label.setText(f"Peak {peak:.3f} kW/m²")
        self.copy_result_button.setEnabled(bool(latest))
        self._draw_plot(latest)

        latest_run = self._latest_run_number()
        fmt = SprinklerPage._fmt
        table = self.history_table
        table.setRowCount(len(self.result_history))
        for row, record in enumerate(reversed(self.result_history)):
            values = [
                str(record.get("run", "")),
                str(record.get("receptor_id", "")),
                str(record.get("unit_name", "Unit 1")),
                str(record.get("input_mode", self.MODE_HEAT_FLUX)),
                fmt(record.get("perp_distance_to_receptor"), "g"),
                fmt(record.get("received_heat_flux"), ".3f"),
                fmt(record.get("view_factor"), ".4f"),
                fmt(record.get("emmissive_power"), "g"),
                fmt(record.get("temp_of_emitter"), "g"),
                fmt(record.get("emissivity"), "g"),
                fmt(record.get("length_of_radiating_panel"), "g"),
                fmt(record.get("width_of_radiating_panel"), "g"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                if record.get("run") == latest_run:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                table.setItem(row, column, item)

    def copy_latest_result(self):
        latest = self._latest_run_records()
        if not latest:
            return
        if len(latest) == 1:
            text = f"{latest[0]['received_heat_flux']:.3f} kW/m²"
        else:
            units = list(dict.fromkeys(record.get("unit_name", "Unit 1") for record in latest))
            distances = sorted({record["perp_distance_to_receptor"] for record in latest})
            flux = {(record.get("unit_name", "Unit 1"), record["perp_distance_to_receptor"]):
                    record["received_heat_flux"] for record in latest}
            text = "\n".join(
                ["Distance (m)\t" + "\t".join(f"{unit} (kW/m²)" for unit in units)] + [
                    f"{distance:g}\t" + "\t".join(
                        f"{flux[(unit, distance)]:.3f}" if (unit, distance) in flux else ""
                        for unit in units)
                    for distance in distances])
        QApplication.clipboard().setText(text)
        self.copy_result_button.setText("Copied!")
        QTimer.singleShot(1500, lambda: self.copy_result_button.setText("Copy Latest Result"))

    def load_example_inputs(self):
        for attribute, _label, key, _tooltip in self.NUMERIC_FIELDS:
            getattr(self, attribute).setText(f"{self.FIELD_DEFAULTS[key]:g}")
        self._set_units([("Unit 1", *(f"{self.FIELD_DEFAULTS[key]:g}" for _label, key in self.PANEL_FIELDS))])

    def clear_inputs(self):
        self.receptor_id.clear()
        for attribute, *_rest in self.NUMERIC_FIELDS:
            getattr(self, attribute).clear()
        self._set_units([("Unit 1", "", "")])

    def clear_results(self):
        if self.result_history:
            reply = QMessageBox.question(
                self, "Clear Results", "Clear the latest result and the results history?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.result_history = []
        self.results_label.setText(self.PLACEHOLDER_TEXT)
        self._refresh_result_display()

    def session_snapshot(self):
        return {
            "results_text": self.results_label.text(),
            "history": self.result_history,
            "units": [{"name": name, "length": length, "width": width}
                      for name, length, width in self._unit_rows()],
            "plot_height": self.plot_height.value(),
            "plot_width": self.plot_width.value(),
        }

    def restore_session(self, state):
        units = state.get("units")
        if isinstance(units, list) and units:
            self._set_units([(str(unit.get("name", "")), str(unit.get("length", "")),
                              str(unit.get("width", "")))
                             for unit in units if isinstance(unit, dict)])
        for spin_box, key in ((self.plot_height, "plot_height"), (self.plot_width, "plot_width")):
            if type(state.get(key)) is int:
                spin_box.setValue(state[key])
        self.result_history = list(state.get("history", []))
        for index, record in enumerate(self.result_history, 1):
            record.setdefault("run", index)  # saves made before range runs existed
        self.results_label.setText(state.get("results_text", self.PLACEHOLDER_TEXT))
        self._refresh_result_display()

               
if __name__ == "__main__": 
    app = QApplication([])
    saved_theme = app_settings().value("theme", _current_theme)
    apply_theme(saved_theme if saved_theme in _THEMES else _current_theme)
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
