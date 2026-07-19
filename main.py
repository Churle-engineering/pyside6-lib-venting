from PySide6.QtWidgets import QApplication, QFormLayout, QFrame, QGroupBox, QLineEdit, QStackedWidget, QHeaderView, QCheckBox, QHBoxLayout, QInputDialog, QMainWindow, QDockWidget, QPushButton, QScrollArea, QSizePolicy, QTabBar, QTabWidget, QMessageBox, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget, QLabel, QVBoxLayout, QGridLayout, QTextEdit, QSlider, QProgressBar, QComboBox, QListWidget, QRadioButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QAction
from information import FIRE_PROPERTIES, COMBINED_INPUTS, POOL_SPREAD_DATA, REQ_LIB_INFO, USER_INPUTS, CALCULATION_METHODS, _THEMES, POOL_PROPERTIES, BATTERY_CHEMISTRY_DATA, CHEMICAL_PROPERTIES, FLAMMABLE_GASES
from pdf import pdf_results
import sys
import numpy as np
from buttons import clear_all_scenarios, data_submission, load_excel_data
from miscfunc import load_file, import_gas_flowrate_data, generate_input_template
import display_popup as display_popup_module
from resulttable import open_results_table_window
from calculations import (
    is_string_field,
    toxicity_assessment_calc,
    flammability_assessment_calc,
    flammability_assessment_calc_graphical_method,
    determine_calc_method,
)
from sprinkler import activation_time_Calc

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
    page = self.frames.get("LIBPages")
    if page is None:
        QMessageBox.warning(self, "Error", "Main window page not found.")
        return
    save_program_state(self)
    # to be saving a json file later, for now just a placeholder
    QMessageBox.information(self, "Save File", "File saved successfully!")
    
def open_file(self):
    # to be opening a json file later, for now just a placeholder
    QMessageBox.information(self, "Open File", "File opened successfully!")

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
        import_flowrate = dataMenu.addAction('Import Flowrate Data')
        import_flowrate.triggered.connect(lambda: import_gas_flowrate_data(self))
        import_scenarios = dataMenu.addAction('Import Scenarios')
        import_scenarios.triggered.connect(lambda: load_file(self, "battery_data/scenarios.zip"))
        generate_template = dataMenu.addAction('Generate Template')
        generate_template.triggered.connect(lambda checked=False: generate_input_template(self))
        openFile = fileMenu.addAction('Open')
        # openFile.triggered.connect(self.open_file) 
        saveFile = fileMenu.addAction('Save')
        # saveFile.triggered.connect(lambda: save_file(self))
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


# --- Reusable spreadsheet page ---
class SpreadsheetWidget(QWidget):
    def __init__(self, headers=COMBINED_INPUTS, rows=30, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(rows, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)  # Stretch columns to fill the available space
        self.table.horizontalHeader().setStretchLastSection(True)


        # Structured NumPy array — one row per scenario.
        # Descriptive/string columns (e.g. "Scenario Description", "LIB Type",
        # "Manufacturer name", "Battery room") are stored as unicode strings;
        # everything else is stored as a float so it can be fed straight into
        # calculations.py.
        self.headers = headers
        self.dtype = [(h, 'U100') if is_string_field(h) else (h, 'f8') for h in headers]

        # Full-size buffer backing the table (one slot per table row). This is
        # never shrunk/grown by anything other than the table's own row count,
        # so it always has a slot to write into regardless of which row is
        # edited.
        self._full_scenario_data = np.zeros(rows, dtype=self.dtype)
        for h in headers:
            if not is_string_field(h):
                self._full_scenario_data[h] = np.nan

        # Public view: only the rows up to (and including) the highest row
        # index that has any input. Starts empty since no rows have data yet.
        self.scenario_data = self._full_scenario_data[:0]

        # Connect the signal - automatically submits data on every cell edit
        self.table.cellChanged.connect(self.on_cell_changed)

        layout.addWidget(self.table)

    def _row_has_data(self, row):
        """Return True if any column in this row of the full buffer holds a value."""
        for h in self.headers:
            value = self._full_scenario_data[h][row]
            if is_string_field(h):
                if value != "":
                    return True
            elif not np.isnan(value):
                return True
        return False

    def _refresh_scenario_data_view(self):
        """Trim self.scenario_data to only include rows up to the highest
        row index that currently has an input."""
        last_used_row = -1
        for row in range(self._full_scenario_data.shape[0]):
            if self._row_has_data(row):
                last_used_row = row
        self.scenario_data = self._full_scenario_data[:last_used_row + 1]

    def on_cell_changed(self, row, col):
        self.table.blockSignals(True)  # Prevent recursive calls to on_cell_changed
        item = self.table.item(row, col)
        header = self.headers[col]
        text = item.text().strip() if item is not None else ""

        if is_string_field(header):
            # Descriptive fields are stored as-is (empty string if blank)
            self._full_scenario_data[header][row] = text
        elif text == "":
            self._full_scenario_data[header][row] = np.nan
        else:
            try:
                self._full_scenario_data[header][row] = float(text)
                item.setData(Qt.BackgroundRole, None)
            except ValueError:
                # Invalid input — reset to NaN and flag it visually
                self._full_scenario_data[header][row] = np.nan
                item.setBackground(Qt.red)

        self._refresh_scenario_data_view()
        self.table.blockSignals(False)  # Prevent recursive calls to on_cell_changed
        print(f"start {self.scenario_data}")

# --- Custom tab bar that renames on double-click ---
class RenamableTabBar(QTabBar):
    def mouseDoubleClickEvent(self, event):
        index = self.tabAt(event.pos())
        if index >= 0:
            current = self.tabText(index)
            new_name, ok = QInputDialog.getText(
                self, "Rename Sheet", "Sheet name:", text=current
            )
            if ok and new_name.strip():
                self.setTabText(index, new_name.strip())
        super().mouseDoubleClickEvent(event)


class LIBPage(QWidget):
    def __init__(self, base_window):
        # Initialize. Set Size and Title
        super().__init__()
        self.base_window = base_window


        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        
     
        # dock area for tools, settings, and other widgets
        toolbar = QToolBar("LIB Offgassing Calculation Tool")
        toolbar.setMovable(False)  # optional: prevent the toolbar from being dragged
        toolbarcontents = QWidget()
        toolbarlayout = QHBoxLayout()
        toolbarcontents.setLayout(toolbarlayout)
        toolbar.addWidget(toolbarcontents)
        
        # --- define widget functions ---
        
        # dropdown menu for calculation function to be used
        self.calc_function = QComboBox()
        self.calc_function.setToolTip("Select the calculation function to be used for the current scenarios.")
        self.calc_function.addItems(CALCULATION_METHODS)
        self.calc_function.currentTextChanged.connect(lambda text: setattr(self.base_window, "selected_calc_method", text))
        #le chatelier option
        self.le_chatelier_check = QCheckBox('Le Chatelier LFL')
        self.le_chatelier_check.addAction(QAction("Le Chatelier LFL", self))
        self.le_chatelier_check.setToolTip("Check this box to use the Le Chatelier method for calculating the lower flammability limit (LFL) of the gas mixture.")
        self.le_chatelier_check.stateChanged.connect(lambda state: setattr(self.base_window, "use_le_chatelier_lfl", bool(state)))
        #opt to use a temperature dependent lfl calculation
        self.temp_dependent_lfl = QCheckBox('Temperature Dependent LFL')
        self.temp_dependent_lfl.addAction(QAction("Temperature Dependent LFL", self))
        self.temp_dependent_lfl.setToolTip("Check this box to use the temperature dependent lower flammability limit (LFL) for the gas mixture. This option is only applicable for the 'Module Variable Flowrate' calculation function.")
        self.temp_dependent_lfl.stateChanged.connect(lambda state: setattr(self.base_window, "use_temp_dependent_lfl", bool(state)))
        # flam calc button
        flam_calc = QPushButton("Flam Calc")
        flam_calc.setToolTip("Click here to calculate the flammability assessment for the current scenarios.")
        flam_calc.clicked.connect(self.run_flam_calc)
        # tox calc button
        tox_calc = QPushButton("Tox Calc")
        tox_calc.setToolTip("Click here to calculate the toxicity assessment for the current scenarios.")
        tox_calc.clicked.connect(self.run_tox_calc)
        # clear all button
        clear_all = QPushButton("Clear All")
        clear_all.setObjectName("clearAllButton")  # targeted by QPushButton#clearAllButton in every theme
        clear_all.setToolTip("Click here to clear all scenarios and calculation results.")
        clear_all.clicked.connect(self.clear_current_sheet)
        # export to pdf button
        export_to_pdf = QPushButton("Export PDF Report")
        export_to_pdf.setToolTip("Click here to export a PDF report of the current scenarios and results.")
        export_to_pdf.clicked.connect(lambda: pdf_results(tox_scenario_results=self.base_window.tox_scenario_results, flam_scenario_results=self.base_window.flam_scenario_results, title="Battery Off-gas Assessment Results"))

        # results table button
        results_table = QPushButton("Results Table")
        results_table.setToolTip("Open the results table builder for the current calculation results.")
        results_table.clicked.connect(lambda: open_results_table_window(self.base_window, self.base_window))
        
        # --- add your widgets, with vertical separators between logical groups ---
        # Group 1: calculation method selector
        toolbarlayout.addWidget(self.calc_function)
        toolbarlayout.addWidget(_make_toolbar_separator())
        # Group 2: LFL options
        toolbarlayout.addWidget(self.le_chatelier_check)
        toolbarlayout.addWidget(self.temp_dependent_lfl)
        toolbarlayout.addWidget(_make_toolbar_separator())
        # Group 3: run calculations
        toolbarlayout.addWidget(flam_calc)
        toolbarlayout.addWidget(tox_calc)
        toolbarlayout.addWidget(_make_toolbar_separator())
        # Group 4: utility / destructive actions
        toolbarlayout.addWidget(clear_all)
        toolbarlayout.addWidget(export_to_pdf)
        toolbarlayout.addWidget(_make_toolbar_separator())
        toolbarlayout.addWidget(results_table)
        # add dock widget to left side
        main_layout.addWidget(toolbar)
        
        # create spreadsheet area for data input and output
        self.tabs = QTabWidget()
        self.tabs.setTabBar(RenamableTabBar())
        self.tabs.setTabsClosable(True)              # optional: X to close
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.setMovable(True)                    # optional: drag to reorder

        # "+" button in the corner of the tab bar
        self.add_btn = QPushButton("+") #define the add button
        self.add_btn.setFixedSize(25, 25) #set the size of the add button
        self.add_btn.clicked.connect(self.add_sheet)
        self.tabs.setCornerWidget(self.add_btn, Qt.TopRightCorner) #add button to corner of tab bar


        # Add tabs to the page layout
        main_layout.addWidget(self.tabs)


        self.sheet_counter = 0
        self.add_sheet()   # start with one sheet
        
        
    def current_spreadsheet(self):
        """Return the SpreadsheetWidget in the currently selected tab."""
        page = self.tabs.currentWidget()

        if isinstance(page, SpreadsheetWidget):
            return page

        return None
    
    def current_scenario_data(self):
        """Return scenario data from the currently selected spreadsheet."""
        spreadsheet = self.current_spreadsheet()

        if spreadsheet is None:
            return np.zeros(0, dtype=[])

        return spreadsheet.scenario_data

    def run_tox_calc(self):
        scenario_data = self.current_scenario_data()
        toxicity_assessment_calc(
            self.base_window,
            state=self.base_window,
            display_toxicity_result_popup=display_toxicity_result_popup,
            gas_data=CHEMICAL_PROPERTIES,
            scenario_data=scenario_data,
        )

    def run_flam_calc(self):
        print("DEBUG: Flam Calc button clicked")
        scenario_data = self.current_scenario_data()
        print(f"DEBUG: Current scenario data type={type(scenario_data).__name__}, rows={getattr(scenario_data, 'shape', (None,))[0] if hasattr(scenario_data, 'shape') else 'n/a'}")
        selected_method = self.calc_function.currentText()
        self.base_window.selected_calc_method = selected_method
        print(f"DEBUG: Selected calc method={selected_method}")

        if selected_method == "Module Variable Flowrate":
            print("DEBUG: Calling graphical-method flammability calculation")
            flammability_assessment_calc_graphical_method(
                self.base_window,
                state=self.base_window,
                display_flammability_result_popup=display_flammability_result_popup,
                gas_data=CHEMICAL_PROPERTIES,
                bat_data=BATTERY_CHEMISTRY_DATA,
                flam_gasses_labels=list(FLAMMABLE_GASES),
                scenario_data=scenario_data,
            )
        else:
            print("DEBUG: Calling standard flammability calculation")
            flammability_assessment_calc(
                self.base_window,
                state=self.base_window,
                display_flammability_result_popup=display_flammability_result_popup,
                gas_data=CHEMICAL_PROPERTIES,
                bat_data=BATTERY_CHEMISTRY_DATA,
                flam_gasses_labels=list(FLAMMABLE_GASES),
                scenario_data=scenario_data,
            )

    def clear_current_sheet(self):
        spreadsheet = self.current_spreadsheet()
        if spreadsheet is None:
            return

        spreadsheet.table.blockSignals(True)
        spreadsheet.table.clearContents()
        spreadsheet.table.setRowCount(0)
        spreadsheet.table.setRowCount(30)
        spreadsheet._full_scenario_data = np.zeros(30, dtype=spreadsheet.dtype)
        for h in spreadsheet.headers:
            if not is_string_field(h):
                spreadsheet._full_scenario_data[h] = np.nan
        spreadsheet.scenario_data = spreadsheet._full_scenario_data[:0]
        spreadsheet.table.blockSignals(False)
        self.base_window.tox_scenario_results.clear()
        self.base_window.flam_scenario_results.clear()

    def add_sheet(self):
        self.sheet_counter += 1
        page = SpreadsheetWidget()
        index = self.tabs.addTab(page, f"Sheet {self.sheet_counter}")
        self.tabs.setCurrentIndex(index)

    def close_tab(self, index):
        if self.tabs.count() > 1:      # keep at least one sheet
            self.tabs.removeTab(index)


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
        
        pool_fire_tickbox = QCheckBox('Pool Fire Duration')
        pool_fire_tickbox.setToolTip("Check this box to calculate the pool fire duration, flame height, and heat release rate")
        toolbarlayout.addWidget(pool_fire_tickbox)
        
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
        

        #drop boxes
        fuel_material = QComboBox()
        fuel_material.setToolTip("Select the fuel material for the pool spill.")
        fuel_material.addItems(list(POOL_SPREAD_DATA.keys()))
        surface_weather = QComboBox()
        surface_weather.setToolTip("Select the surface weather condition for the pool spill.")
        surface_weather.addItems(list(POOL_PROPERTIES["relative_permeability"]))
        
        surface_material = QComboBox()
        surface_material.setToolTip("Select the surface material for the pool spill.")
        surface_material.addItems(list(POOL_PROPERTIES["intrinsic_permeability"]))
        
        ground_conditions = QComboBox()
        ground_conditions.setToolTip("Select the ground conditions for the pool spill.")
        ground_conditions.addItems(list(POOL_PROPERTIES["average_pool_height"]))
        
        orifice_condition = QComboBox()
        orifice_condition.setToolTip("Select the orifice condition for the pool spill.")
        orifice_condition.addItems(list(POOL_PROPERTIES["discharge_coefficients"]))
        
        #user inputs
        
        ambient_temperature = QLineEdit()
        ambient_temperature.setToolTip("Enter the ambient temperature in kelvin.")
        
        wind_speed = QLineEdit()
        wind_speed.setToolTip("Enter the surface wind speed in meters per second.")
        
        bund_size = QLineEdit()
        bund_size.setToolTip("Enter the bund size in meters.")
        
        self.operator_intervention_time = QLineEdit()
        self.operator_intervention_time.setToolTip("Enter the operator intervention time in seconds.")
        
        self.orifice_diameter = QLineEdit()
        self.orifice_diameter.setToolTip("Enter the orifice diameter in meters.")
        
        self.delta_p = QLineEdit()
        self.delta_p.setToolTip("Enter the pressure differential in Pascals.")
        
        volumetric_flowrate = QLineEdit()
        volumetric_flowrate.setToolTip("Enter the volumetric flowrate in cubic meters per second.")
        
        
                # Input group
        input_group = QGroupBox("Pool Spill Inputs")
        
        input_group.setMaximumWidth(500)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(15)
        form_layout.setVerticalSpacing(10)
        form_layout2 = QFormLayout()
        form_layout2.setHorizontalSpacing(15)
        form_layout2.setVerticalSpacing(10)

        form_layout.addRow("Fuel Material:", fuel_material)
        form_layout.addRow("Surface Weather:", surface_weather)
        form_layout.addRow("Surface Material:", surface_material)
        form_layout.addRow("Ground Conditions:", ground_conditions)
        form_layout.addRow("Orifice Condition:", orifice_condition)
        form_layout2.addRow("Ambient Temperature (K):",ambient_temperature)
        form_layout2.addRow("Wind Speed (m/s):",wind_speed)
        form_layout2.addRow("Bund Size (m):",bund_size)
        form_layout2.addRow("Volumetric Flowrate (m³/s):",volumetric_flowrate)

        
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

        self.oi_tickbox.toggled.connect(self.toggle_optional_inputs)
        self.toggle_optional_inputs()

    def toggle_optional_inputs(self):
        self.optional_group.setVisible(self.oi_tickbox.isChecked())


class ReceptorHeatFlux(QWidget):
    """Placeholder window for the Receptor Heat Flux calculator."""
    def __init__(self, base_window):
        super().__init__()
        self.base_window = base_window
        
        emissive_power = QLineEdit()
        emissive_power.setToolTip("Enter the emissive power in kW/m².\nMust be greater than 0.")
        
        perpendicular_distance = QLineEdit()
        perpendicular_distance.setToolTip("Enter the perpendicular distance from the fire source to the receptor in meters.\nMust be greater than 0.")
        
        

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
