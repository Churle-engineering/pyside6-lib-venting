import os
import sys
import zipfile
import csv
import numpy as np
from PySide6.QtWidgets import QMessageBox, QFileDialog
from information import COMBINED_INPUTS

def clear_all_scenarios(self):
    # 1. Confirm the action
    confirm = QMessageBox.question(None, "Clear All", "Are you sure you want to delete all scenarios and calculation results?", QMessageBox.Yes | QMessageBox.No)
    if confirm != QMessageBox.Yes:
        return

    self.blockSignals(True)  # Block signals to prevent triggering cellChanged events during clearing
    self.clearContents()  # Clear the QTableWidget contents
    self.data[:] = np.nan
    self.blockSignals(False)  # Unblock signals after clearing

    # 2. Clear the Treeview (The Visuals)
    for table in self.tables:
        table.setRowCount(0)  # Clear all rows in the current spreadsheet widget

    # 3. Clear the Input Data (The User Entries)
    self.scenario_data.clear()
    
    # Update status bar if available
    if hasattr(self, 'update_status'):
        self.update_status("All scenarios cleared", 0)

    # 4. Clear the Calculated Results (The "Sitting" Data)
    # We use hasattr/getattr checks to avoid crashing if calculations haven't run yet
    
    # Clear Flammability Results
    if hasattr(self, 'flam_scenario_results') and isinstance(self.flam_scenario_results, dict):
        self.flam_scenario_results.clear()
        
    # Clear Toxicity Results (assuming similar naming convention)
    if hasattr(self, 'tox_scenario_results') and isinstance(self.tox_scenario_results, dict):
        self.tox_scenario_results.clear()
        
        

def normalize_name(name):
    if '_normalize_cache' not in globals():
        global _normalize_cache
        _normalize_cache = {}
    if name not in _normalize_cache:
        _normalize_cache[name] = name.strip().lower().replace(" ", "_")
    return _normalize_cache[name]

def generate_input_template(state):
    from miscfunc import generate_input_template as _generate_input_template
    return _generate_input_template(state)
        
# import excel data for scenarios
def load_excel_data(self, file_path):
    if not os.path.exists(file_path):
        QMessageBox.critical(None, "File Not Found", f"The file {file_path} does not exist.")
        return

    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            # Assuming the first file in the zip is the CSV we want
            csv_files = [f for f in z.namelist() if f.endswith('.csv')]
            if not csv_files:
                QMessageBox.critical(None, "No CSV Found", "No CSV files found in the provided zip archive.")
                return
            
            with z.open(csv_files[0]) as csvfile:
                reader = csv.DictReader(line.decode('utf-8') for line in csvfile)
                self.scenario_data.clear()
                for row in reader:
                    self.scenario_data.append(row)
                
                # Update the table with the loaded data
                self.update_table_from_data()
                
    except Exception as e:
        QMessageBox.critical(None, "Error Loading Data", f"An error occurred while loading data: {str(e)}")
        
        
def data_submission(self):

    rows = self.table.rowCount()
    cols = self.table.columnCount()
    headers = [self.table.horizontalHeaderItem(c).text() for c in range(cols)]

    result = {h: [] for h in headers}
    for r in range(rows):
        for c, h in enumerate(headers):
            item = self.table.item(r, c)
            text = item.text().strip() if item else ""
            try:
                result[h].append(float(text))
            except ValueError:
                result[h].append(np.nan)

    return {h: np.array(v) for h, v in result.items()}
