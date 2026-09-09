from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTabWidget, QToolBar,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QComboBox, QCheckBox, QGridLayout)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QDoubleValidator, QKeySequence, QShortcut
from information import (FIRE_PROPERTIES, POOL_SPREAD_DATA, LIB_TYPE, CELL_FORMAT, CALCULATION_METHODS, _THEMES,
                         POOL_PROPERTIES, CHEMICAL_PROPERTIES, COMPOSITION_METHODS,
                         FlowrateProfile, GasComposition, LIBInputs, LIBSpec,
                         CALC_METHOD_MODULE_VARIABLE_FLOWRATE)
import copy
import os
from dataclass_forms import build_tabbed_form, read_form
from scenario_model import ScenarioStore
from sprinkler import activation_time_Calc
from saveload import save_program_state, load_program_state



# to do's:
# add a calculation method to the input of the pdf report.
# make it so that 1 second timesteps are always used for the quick caluclations. Big time steps can mess it up
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

# Main application window that hosts the page stack and shared state for the
# different calculation modules.
class BaseWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Charlie's Proprietary LIB Offgas Modelling Tool")
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
        openAction = fileMenu.addAction('Open Session...')
        openAction.setShortcut(QKeySequence.Open)
        openAction.triggered.connect(self.open_session)
        saveAction = fileMenu.addAction('Save Session')
        saveAction.setShortcut(QKeySequence.Save)
        saveAction.triggered.connect(lambda: self.save_session(use_current_path=True))
        saveAsAction = fileMenu.addAction('Save Session As...')
        saveAsAction.setShortcut(QKeySequence.SaveAs)
        saveAsAction.triggered.connect(lambda: self.save_session(use_current_path=False))
        fileMenu.addSeparator()
        exitAction = fileMenu.addAction('Exit')
        exitAction.triggered.connect(lambda: ask_to_close(self))

        themeMenu = menubar.addMenu('Theme')
        for _theme_name in _THEMES:
            _action = themeMenu.addAction(_theme_name)
            _action.triggered.connect(lambda checked=False, t=_theme_name: apply_theme(t))

    def save_session(self, use_current_path=False):
        path = self.current_save_path if use_current_path else None
        if save_program_state(self, _current_theme, path=path):
            self.setWindowTitle(f"Charlie's Proprietary LIB Offgas Modelling Tool - {self.current_save_path}")

    def open_session(self):
        path, theme_name = load_program_state(self)
        if not path:
            return
        if theme_name in _THEMES:
            apply_theme(theme_name)
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


def ask_to_close(self):
    reply = QMessageBox.question(self, 'Exit', 'Are you sure you want to exit?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    if reply == QMessageBox.Yes:
        self.close()


# Landing page that presents the main tools available in the application.
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

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(name_form)
        layout.addWidget(scroll)
        layout.addWidget(self.total_label)
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
            return
        self.total_label.setText(f"Total: {total:.2f} %")

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
                           "emergency_vent_rate", "vent_switch_conc"]),
        ("Calculation", ["calc_duration", "time_step", "use_le_chatelier_lfl",
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
        if not user_defined:
            widgets["gas_composition"].setToolTip(
                "Only used when the Composition Method is 'User Defined'.")

        variable = widgets["calc_method"].currentText() == CALC_METHOD_MODULE_VARIABLE_FLOWRATE
        widgets["flowrate_profile"].setEnabled(variable)
        if not variable:
            widgets["flowrate_profile"].setToolTip(
                "Only used by the 'Module Variable Flowrate' calculation method.")

    def _validation_problems(self, inputs):
        """Configuration contradictions that would make the run fail later."""
        problems = []
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
        run_button.setToolTip("Run the selected calculation method for the current scenarios.")
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

        self.next_result_button = QPushButton("Next Result")
        self.next_result_button.setToolTip("Switch to the next results tab and show its linked summary.")
        self.next_result_button.clicked.connect(self.show_next_result)
        self.next_result_button.setEnabled(False)

        toolbarlayout.addWidget(libraries_button)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(run_button)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(clear_all)
        toolbarlayout.addWidget(export_to_pdf)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(results_table)
        toolbarlayout.addWidget(self.next_result_button)
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
        self.scenario_tree_inner.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
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
                item = QTreeWidgetItem([scenario.name])
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
        if item.data(0, NODE_TYPE_ROLE) == NODE_GROUP:
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
            return
        if item.data(0, NODE_TYPE_ROLE) != NODE_SCENARIO:
            item.setExpanded(not item.isExpanded())
            return

        node_id = item.data(0, NODE_ID_ROLE)
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

        Results are not saved to session files, so the results panel starts empty
        after a load - press Run to recompute them from the restored inputs.
        """
        self._clear_result_tabs()
        self._clear_summary_stack()
        self.scenarios = ScenarioStore()

        for group in groups or []:
            group_name = group.get("name") or "New Group"
            self.scenarios.add_group(group_name)
            for scenario in group.get("scenarios") or []:
                scenario.group = group_name
                self.scenarios.scenarios[scenario.node_id] = scenario
                self.scenarios._counter = max(self.scenarios._counter, scenario.node_id)
                self._apply_composition(scenario)
                self._apply_lib_spec(scenario)
                self._apply_flowrate_profile(scenario)

        self._refresh_tree()

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

    def _clear_summary_stack(self):
        while self.summary_stack.count() > 1:
            widget = self.summary_stack.widget(1)
            self.summary_stack.removeWidget(widget)
            widget.deleteLater()
        self.summary_stack.setCurrentWidget(self._summary_placeholder)

    def _show_result_summary(self, title):
        """Render the summary strip from every scenario's stored ResultSummary."""
        summaries = [s.summary for s in self._scenarios_in_tree_order() if s.summary is not None]
        if not summaries:
            self._show_summary(f"{title}: no results were produced.")
            return
        blocks = ["\n".join(summary.summary_lines()) for summary in summaries]
        self._show_summary("\n\n".join(blocks))

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

    def show_next_result(self):
        pass

    def open_library_manager(self):
        dialog = LibraryManagerDialog(self, self.base_window)
        dialog.exec()
        # library objects may have been renamed/deleted - rebind every scenario by name
        for scenario in self.scenarios:
            self._apply_composition(scenario)
            self._apply_lib_spec(scenario)
            self._apply_flowrate_profile(scenario)


# Page for calculating sprinkler activation times from the supplied inputs.
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
        toolbarcontents.setObjectName("toolbarContents")
        toolbarlayout = QHBoxLayout()
        toolbarlayout.setContentsMargins(0, 0, 0, 0)
        toolbarlayout.setSpacing(6)
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
                "icon": "🚀",
                "title": "Getting Started",
                "content": "Welcome to the Battery Off-gassing Calculation Tool! This application helps you assess toxicity and flammability risks from lithium-ion battery thermal runaway events.\nThe basic workflow is: define your batteries in Libraries, build scenarios in the study tree, press Run, then review the plots and summary before exporting a PDF report."
            },
            {
                "icon": "📚",
                "title": "Libraries",
                "content": "The 'Libraries' button manages the three kinds of named objects scenarios reference:\n• Batteries (LIB): the cell/module volumes, durations, LFL and propagation behaviour of one battery product\n• Gas Compositions: a named percentage split of the off-gas into chemical species\n• Flowrate Datasets: measured module flowrate curves imported from CSV\nDefine an object once, then any number of scenarios can select it by name. Editing a library object updates every scenario that references it."
            },
            {
                "icon": "📝",
                "title": "Creating Scenarios",
                "content": "1. Press '+ Group' to create a group (e.g. a design option or room)\n2. With the group selected, press '+' to add a scenario\n3. Fill in the scenario dialog: pick the battery, counts, room details and the Calculation Method\n4. Double-click a scenario to edit it, or a group to rename it\n5. Ctrl+C / Ctrl+V copies and pastes scenarios between groups"
            },
            {
                "icon": "🧪",
                "title": "Running Calculations",
                "content": "Press Run to calculate. The selection controls the scope: a selected scenario runs alone, a selected group runs its scenarios, and no selection runs everything.\nEvery scenario runs through the same pipeline; only its Calculation Method changes how one module releases gas:\n• Cell Volume UL9540A: cells inside each module initiate in staggered waves, each following an empirical release curve (or a flat rate if a measured Cell Duration is entered)\n• Module Volume UL9540A: each module releases its UL9540A test volume at a constant rate\n• Module Capacity: the volume comes from literature specific-capacity data (L/kWh) times the module capacity\n• Module Variable Flowrate: each module replays an imported measured flowrate dataset\nModules always initiate in staggered waves set by the battery's module propagation delay and number."
            },
            {
                "icon": "📊",
                "title": "Results",
                "content": "Each run adds one tab per scenario with a Flammable Gas and a Toxic Gas plot; checkboxes toggle individual species and their threshold lines (per-species LFLs, ERPG-3).\nThe strip along the bottom summarises every stored result: peak flammable concentration, the assessment LFL and when (or whether) it is reached, and each toxic species' peak.\nClosing a tab discards that scenario's stored result. 'Clear All' discards everything."
            },
            {
                "icon": "📄",
                "title": "Exporting Reports",
                "content": "Click 'Export PDF Report' to generate a document with an intro/assumptions page, a contents page, and per scenario: the exact inputs and battery specification the run used, landscape concentration plots, and summary tables of peaks against LFL and ERPG-3 thresholds.\nOnly scenarios with stored results can be exported, and you choose which to include."
            },
            {
                "icon": "💾",
                "title": "Saving Sessions",
                "content": "File > Save Session stores the whole program state - libraries, the study tree and every scenario's inputs - in a .libsave file. Calculation results are deliberately not saved: they are cheap to recompute, so simply press Run after opening a session."
            },
            {
                "icon": "🚨",
                "title": "Emergency Ventilation",
                "content": "Vent Switch Concentration and Emergency Vent Rate let one scenario use two ventilation rates. Set both to 0 to disable the system.\nVent Switch Concentration is the room's CO concentration, as a percentage of CO's own LFL, at which the ventilation switches to the emergency rate - e.g. 25 switches when CO reaches 25% of its LFL. The switch is not latched: if CO falls back below the trigger the standard rate resumes.\nBoth rates are entered in L/s per m2 of room floor area; the emergency rate is typically higher than the standard rate."
            },
            {
                "icon": "🔄",
                "title": "Variable Flowrates",
                "content": "Module level UL9540A test reports often provide flowrate data as graphs. Using WebPlotDigitizer you can extract the curve into a two-column CSV (time in seconds, flowrate in L/s) and import it under Libraries > Flowrate Datasets.\nThen select the 'Module Variable Flowrate' calculation method in a scenario and pick the dataset in its 'Flowrate Dataset' field - the dataset defines both one module's flowrate and its release duration, while the gas composition still comes from the scenario's Composition Method."
            },
            {
                "icon": "⚙️",
                "title": "Technical Notes",
                "content": "• The battery room is modelled as a single well-mixed volume diluted by the ventilation rate\n• Gas composition comes from literature data per chemistry, or a user-defined composition\n• Flammable results are assessed against the battery LFL, or optionally a Le Chatelier mixture LFL\n• Toxic species are assessed against their ERPG-3 values\n• All correlations are based on 60 peer reviewed papers containing data for a total of 470 LIB experiments"
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
        toolbarcontents.setObjectName("toolbarContents")
        toolbarlayout = QHBoxLayout()
        toolbarlayout.setContentsMargins(0, 0, 0, 0)
        toolbarlayout.setSpacing(6)
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


# Placeholder page for receptor heat flux calculations.
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
