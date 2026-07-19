from information import COMBINED_INPUTS


def _build_summary_table(headers, row_data, groups):
    """Build a scrollable, sectioned summary table widget.

    ``groups`` is a list of ``(section_title, column_span)`` tuples used to
    render a super-header row above the column headers so related columns are
    visually grouped (e.g. "Scenario Info", a gas name, "Max Modules"...).
    Spans of 0 are skipped automatically.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget, QLabel, QGridLayout, QScrollArea, QFrame
    from PySide6.QtGui import QFont

    section_colors = ["#3a5f8a", "#4d7a4d", "#8a5f3a", "#5f3a8a"]
    header_bg = "#2b2b2b"
    row_bg = "#f2f2f2"

    section_font = QFont("DefaultFont", 9)
    section_font.setBold(True)
    header_font = QFont("DefaultFont", 9)
    header_font.setBold(True)
    data_font = QFont("DefaultFont", 9)

    table_widget = QWidget()
    table_layout = QGridLayout(table_widget)
    table_layout.setHorizontalSpacing(0)
    table_layout.setVerticalSpacing(0)
    table_layout.setContentsMargins(0, 0, 0, 0)

    col = 0
    color_idx = 0
    for title, span in groups:
        if span <= 0:
            continue
        lbl = QLabel(title)
        lbl.setFont(section_font)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        color = section_colors[color_idx % len(section_colors)]
        color_idx += 1
        lbl.setStyleSheet(
            f"background-color: {color}; color: white; padding: 4px; border: 1px solid #222;"
        )
        table_layout.addWidget(lbl, 0, col, 1, span)
        col += span

    for col_idx, header in enumerate(headers):
        h = QLabel(header)
        h.setFont(header_font)
        h.setWordWrap(True)
        h.setAlignment(Qt.AlignCenter)
        h.setStyleSheet(
            f"background-color: {header_bg}; color: white; padding: 3px; border: 1px solid #444;"
        )
        table_layout.addWidget(h, 1, col_idx)

        d = QLabel(str(row_data[col_idx]))
        d.setFont(data_font)
        d.setAlignment(Qt.AlignCenter)
        d.setWordWrap(True)
        d.setMinimumWidth(95)
        d.setStyleSheet(
            f"background-color: {row_bg}; padding: 3px; border: 1px solid #ccc;"
        )
        table_layout.addWidget(d, 2, col_idx)

    table_area = QScrollArea()
    table_area.setWidget(table_widget)
    table_area.setWidgetResizable(True)
    table_area.setFrameShape(QFrame.NoFrame)
    table_area.setMinimumHeight(120)
    table_area.setMaximumHeight(190)
    return table_area


def display_flammability_result_popup(flam_scenario_results, tree, gas_data, bat_data, parent=None):
    print("DEBUG: Entered display_flammability_result_popup")
    print(f"DEBUG: flamm_scenario_results count={len(flam_scenario_results) if flam_scenario_results else 0}")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication, QMessageBox, QDialog, QWidget, QFrame, QLabel, QPushButton,
        QVBoxLayout, QHBoxLayout, QScrollArea, QScrollBar, QTabWidget
    )
    from PySide6.QtGui import QFont

    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvasQTAgg
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar2QT

    def render_scenario_content(container, scenario_name, result_data):
        vv_df = result_data.get("flam_vv_df")
        mgl_df = result_data.get("flam_mgl_df")
        max_mods = result_data.get("flam_max_mod")
        input_data = result_data.get("input", {})

        manufacturer_name = input_data.get("manufacturer_name")
        scenario_description = input_data.get("Scenario Description")
        battery_room = result_data.get('input', {}).get('battery_room')
        lfl_bat = float(input_data.get("LFL (%)", input_data.get("lfl_(%)", 0)))
        mods = float(input_data.get("Modules per", input_data.get("Modules per unit", 0)))
        units = float(input_data.get("Units", 0))

        fig = Figure(figsize=(7.5, 4.8), dpi=100)
        ax = fig.add_subplot(111)

        if "Total Gas (v/v%)" not in vv_df.columns:
            expected_vv_cols = ["co (v/v%)", "h2 (v/v%)", "total_hydrocarbons (v/v%)"]
            present_vv_cols = [c for c in expected_vv_cols if c in vv_df.columns]
            if not present_vv_cols:
                present_vv_cols = [col for col in vv_df.columns if col.endswith("(v/v%)") and col != "Total Gas (v/v%)"]
            if present_vv_cols:
                vv_df["Total Gas (v/v%)"] = vv_df[present_vv_cols].sum(axis=1)
            else:
                vv_df["Total Gas (v/v%)"] = 0
        if "Total Gas (mg/L)" not in mgl_df.columns:
            expected_mgl_cols = ["co (mg/L)", "h2 (mg/L)", "total_hydrocarbons (mg/L)"]
            present_mgl_cols = [c for c in expected_mgl_cols if c in mgl_df.columns]
            if not present_mgl_cols:
                present_mgl_cols = [col for col in mgl_df.columns if col.endswith("(mg/L)") and col != "Total Gas (mg/L)"]
            if present_mgl_cols:
                mgl_df["Total Gas (mg/L)"] = mgl_df[present_mgl_cols].sum(axis=1)
            else:
                mgl_df["Total Gas (mg/L)"] = 0

        vv_max_total_value = vv_df.loc[vv_df["Total Gas (v/v%)"].idxmax(), "Total Gas (v/v%)"]
        mgl_max_total_value = mgl_df.loc[mgl_df["Total Gas (mg/L)"].idxmax(), "Total Gas (mg/L)"]

        ax.plot(vv_df["Time (s)"], vv_df["Total Gas (v/v%)"], label="Total Gas (v/v%)", linestyle='-', linewidth=2.5, color='black')

        import numpy as np
        lfl_curve_array = result_data.get("lfl_curve_array")
        lfl_curve_label = result_data.get("lfl_curve_label") or "LFL"
        if lfl_curve_array is not None:
            finite_mask = np.isfinite(lfl_curve_array)
            if np.any(finite_mask):
                ax.plot(vv_df["Time (s)"], lfl_curve_array, label=lfl_curve_label, linestyle='--', linewidth=2, color='darkorange')
                y_top = max(vv_max_total_value, lfl_bat if lfl_bat else 0) * 1.15
            else:
                if lfl_bat:
                    ax.axhline(y=lfl_bat, color='crimson', linestyle=':', linewidth=2, label=f"LFL ({lfl_bat}%)")
                y_top = max(vv_max_total_value, lfl_bat if lfl_bat else 0) * 1.15
        else:
            if lfl_bat:
                ax.axhline(y=lfl_bat, color='crimson', linestyle=':', linewidth=2, label=f"LFL ({lfl_bat}%)")
            y_top = max(vv_max_total_value, lfl_bat if lfl_bat else 0) * 1.15

        ax.set_ylim(bottom=0, top=y_top if y_top else 1)
        ax.set_title(f"{scenario_name} — Gas Concentration Over Time", fontsize=12, fontweight='bold')
        ax.set_xlabel("Time (s)", fontsize=10)
        ax.set_ylabel("Concentration (v/v%)", fontsize=10)
        ax.tick_params(labelsize=9)
        ax.legend(fontsize=9, loc='best', framealpha=0.9)
        ax.grid(True, linestyle='--', alpha=0.5)
        fig.tight_layout()

        canvas = FigureCanvasQTAgg(fig)
        canvas.setMinimumHeight(340)

        layout = container.layout()
        if layout is None:
            layout = QVBoxLayout(container)
            container.setLayout(layout)
        layout.addWidget(canvas, 1)
        toolbar = NavigationToolbar2QT(canvas, container)
        layout.addWidget(toolbar)

        result_data["flam_plot_fig"] = fig

        headers = ["Scenario","Description","Manufacturer name","Battery room","Modules","Units",
                   "Peak Total Conc. (v/v%)", "Peak Total Gas (mg/L)", "(%) of LFL", "Max Modules Before LFL"]

        flam_row_data = [
            scenario_name, scenario_description, manufacturer_name, battery_room, mods, units,
            f"{vv_max_total_value:.4f}",
            f"{mgl_max_total_value:.4f}",
            f"{(vv_max_total_value / lfl_bat) * 100 if lfl_bat else 0:.3f}",
            max_mods.get("total_gas", "N/A")
        ]

        groups = [("Scenario Info", 6), ("Peak Results", 4)]
        table_area = _build_summary_table(headers, flam_row_data, groups)
        layout.addWidget(table_area, 0)

        method_label = QLabel(f"Calculation Method: {result_data.get('calc_method', 'Unknown')}")
        method_label.setFont(QFont("DefaultFont", 9))
        layout.addWidget(method_label)

        result_data["flam_summary_headers"] = headers
        result_data["flam_summary_row_data"] = flam_row_data

    def perform_pop_out(notebook, original_tab, scenario_name, result_data):
        new_dialog = QDialog()
        new_dialog.setWindowTitle(f"{scenario_name} (Pop Out)")
        new_dialog.resize(1150, 800)
        render_scenario_content(new_dialog, scenario_name, result_data)
        notebook.removeTab(notebook.indexOf(original_tab))
        new_dialog.show()
        new_dialog.raise_()

    if not flam_scenario_results:
        QMessageBox.warning(None, "No Results", "No results available to show.")
        return

    owner = parent or (QApplication.instance().activeWindow() if QApplication.instance() is not None else None)
    popup = QDialog(owner)
    popup.setAttribute(Qt.WA_DeleteOnClose, False)
    popup.setWindowModality(Qt.NonModal)
    popup.setWindowTitle("Flammability Calculation Results")
    popup.resize(1150, 800)
    popup.setMinimumSize(950, 680)
    if owner is not None:
        setattr(owner, "_active_flam_popup", popup)
    else:
        app = QApplication.instance()
        if app is not None:
            setattr(app, "_active_flam_popup", popup)
    notebook = QTabWidget(popup)
    main_layout = QVBoxLayout(popup)
    main_layout.addWidget(notebook)

    if tree is None:
        # No tree provided: iterate over results dict directly
        for scenario_name, result_data in flam_scenario_results.items():
            vv_df = result_data.get("flam_vv_df")
            mgl_df = result_data.get("flam_mgl_df")
            if vv_df is None or vv_df.empty or mgl_df is None or mgl_df.empty:
                print(f"Data missing or empty for scenario: {scenario_name}")
                continue

            frame = QWidget()
            notebook.addTab(frame, scenario_name)
            frame_layout = QVBoxLayout(frame)
            top_layout = QHBoxLayout()
            frame_layout.addLayout(top_layout)
            pop_btn = QPushButton("⇱ Pop Out Window")
            pop_btn.clicked.connect(lambda checked=False, f=frame, n=scenario_name, d=result_data: perform_pop_out(notebook, f, n, d))
            top_layout.addWidget(pop_btn, alignment=Qt.AlignRight)
            render_scenario_content(frame, scenario_name, result_data)
    else:
        for row_id in tree.get_children():
            row_values = tree.item(row_id, "values")
            if not row_values:
                continue

            scenario_name = row_values[0]
            result_data = flam_scenario_results.get(scenario_name)
            if result_data is None:
                continue

            vv_df = result_data.get("flam_vv_df")
            mgl_df = result_data.get("flam_mgl_df")
            if vv_df is None or vv_df.empty or mgl_df is None or mgl_df.empty:
                print(f"Data missing or empty for scenario: {scenario_name}")
                continue

            frame = QWidget()
            notebook.addTab(frame, scenario_name)
            frame_layout = QVBoxLayout(frame)
            top_layout = QHBoxLayout()
            frame_layout.addLayout(top_layout)
            pop_btn = QPushButton("⇱ Pop Out Window")
            pop_btn.clicked.connect(lambda checked=False, f=frame, n=scenario_name, d=result_data: perform_pop_out(notebook, f, n, d))
            top_layout.addWidget(pop_btn, alignment=Qt.AlignRight)
            render_scenario_content(frame, scenario_name, result_data)

    print("DEBUG: Showing flammability popup")
    popup.show()
    popup.raise_()
    popup.activateWindow()
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    return popup

def display_toxicity_result_popup(tox_scenario_results, tree, tox_gas_labels, gas_data):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication, QMessageBox, QDialog, QWidget, QLabel, QPushButton,
        QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QTabWidget, QCheckBox
    )
    import matplotlib.cm as cm
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvasQTAgg
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar2QT

    def render_toxicity_content(container, scenario_name, result_data, tox_gas_labels, gas_data):
        df_vv = result_data.get("tox_vv_df")
        df_mgl = result_data.get("tox_mgl_df")
        max_mods = result_data.get("tox_max_mod", {})
        input_data = result_data.get("input", {})
        from typing import Any, cast

        manufacturer_name = input_data.get("manufacturer_name", "")
        scenario_description = input_data.get("Scenario Description", "")
        battery_room = input_data.get("battery_room", "")
        total_mods = float(input_data.get("Modules per", 0)) * float(input_data.get("Units", 0))

        fig = Figure(figsize=(7.5, 4.8), dpi=100)
        ax = fig.add_subplot(111)

        valid_gas_labels = [label for label in tox_gas_labels if f"{label} (mg/L)" in df_mgl.columns]
        color_count = len(valid_gas_labels) if valid_gas_labels else 1
        get_cmap_fn = getattr(cm, "get_cmap", None)
        if callable(get_cmap_fn):
            colors = cast(Any, get_cmap_fn('tab10', color_count))
        else:
            # Matplotlib >= 3.9 removed cm.get_cmap; use the colormaps API.
            import matplotlib
            colors = cast(Any, matplotlib.colormaps.get_cmap('tab10').resampled(color_count))

        gas_colors = {gas: colors(idx) for idx, gas in enumerate(valid_gas_labels)}
        gas_checkboxes = {}

        controls_widget = QWidget(container)
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        toggle_gas_options = QCheckBox("Show gas visibility options", controls_widget)
        controls_layout.addWidget(toggle_gas_options)

        gas_options_area = QScrollArea(controls_widget)
        gas_options_area.setWidgetResizable(True)
        gas_options_area.setVisible(False)
        gas_options_area.setMaximumHeight(170)

        gas_options_widget = QWidget()
        gas_options_layout = QGridLayout(gas_options_widget)
        gas_options_layout.setContentsMargins(0, 0, 0, 0)

        def update_toxicity_plot():
            ax.clear()

            selected_gases = [gas for gas in valid_gas_labels if gas_checkboxes.get(gas) and gas_checkboxes[gas].isChecked()]
            y_values = []
            erpg_values = []

            for gas in selected_gases:
                gas_col = f"{gas} (mg/L)"
                y = df_mgl[gas_col]
                y_values.extend(y.tolist())
                ax.plot(df_mgl["Time (s)"], y, label=gas, linewidth=2.5, color=gas_colors[gas])

            for gas in selected_gases:
                erpg3 = gas_data.get(gas, {}).get("erpg_3", None)
                if erpg3 is not None and erpg3 > 0:
                    erpg_values.append(erpg3)
                    ax.axhline(y=erpg3, color=gas_colors[gas], linestyle=':', linewidth=1.8, label=f"{gas} ERPG-3")

            if y_values or erpg_values:
                y_top = max(y_values + erpg_values) * 1.1
                ax.set_ylim(bottom=0, top=y_top)
            else:
                ax.set_ylim(bottom=0, top=1)
                ax.text(0.5, 0.5, "No toxic gas species selected", transform=ax.transAxes,
                        ha="center", va="center", fontsize=11)

            ax.set_title(f"{scenario_name} — Toxic Gas Concentrations", fontsize=12, fontweight='bold')
            ax.set_xlabel("Time (s)", fontsize=10)
            ax.set_ylabel("Concentration (mg/L)", fontsize=10)
            ax.tick_params(labelsize=9)
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
            ax.grid(True, linestyle='--', alpha=0.5)
            fig.tight_layout()
            canvas.draw_idle()

        default_deselected_gases = {"methanol", "dmc", "c2h5f"}
        for idx, gas in enumerate(valid_gas_labels):
            gas_checkbox = QCheckBox(gas, gas_options_widget)
            gas_checkbox.setChecked(gas not in default_deselected_gases)
            gas_checkboxes[gas] = gas_checkbox
            gas_checkbox.stateChanged.connect(lambda _state: update_toxicity_plot())
            gas_options_layout.addWidget(gas_checkbox, idx // 2, idx % 2)

        gas_options_area.setWidget(gas_options_widget)
        controls_layout.addWidget(gas_options_area)
        toggle_gas_options.toggled.connect(gas_options_area.setVisible)

        if "Total Gas (ppm)" not in df_vv.columns:
            df_vv["Total Gas (ppm)"] = df_vv[[col for col in df_vv.columns if col.endswith("(v/v%)")]].sum(axis=1)

        peak_idx_vv = df_vv["Total Gas (ppm)"].idxmax()
        peak_value_vv = df_vv.loc[peak_idx_vv, "Total Gas (ppm)"]

        canvas = FigureCanvasQTAgg(fig)
        canvas.setMinimumHeight(340)
        layout = container.layout()
        if layout is None:
            layout = QVBoxLayout(container)
            container.setLayout(layout)
        layout.addWidget(controls_widget)
        layout.addWidget(canvas, 1)
        toolbar = NavigationToolbar2QT(canvas, container)
        layout.addWidget(toolbar)

        update_toxicity_plot()

        result_data["tox_plot_fig"] = fig

        if "Total Gas (mg/L)" not in df_mgl.columns:
            mg_cols = [f"{gas} (mg/L)" for gas in valid_gas_labels if f"{gas} (mg/L)" in df_mgl.columns]
            df_mgl["Total Gas (mg/L)"] = df_mgl[mg_cols].sum(axis=1)

        peak_idx_mgl = df_mgl["Total Gas (mg/L)"].idxmax()
        peak_value_mgl = df_mgl.loc[peak_idx_mgl, "Total Gas (mg/L)"]

        headers = ["Scenario", "Scenario Description", "Manufacturer", "Battery Room", "Modules", "Peak Total Gas (ppm)", "Peak Total Gas (mg/L)"]
        row_data = [scenario_name, scenario_description, manufacturer_name, battery_room, total_mods, f"{peak_value_vv:.4f}", f"{peak_value_mgl:.4f}"]
        groups = [("Scenario Info", 5), ("Peak Totals", 2)]

        for gas in valid_gas_labels:
            vv_col = f"{gas} (v/v%)"
            mgl_col = f"{gas} (mg/L)"
            erpg3 = gas_data.get(gas, {}).get("erpg_3", 0)
            max_vv = df_vv[vv_col].max() if vv_col in df_vv.columns else 0
            max_mgl = df_mgl[mgl_col].max() if mgl_col in df_mgl.columns else 0
            percent_erpg3 = (max_mgl / erpg3) * 100 if erpg3 else 0

            headers.extend([f"{gas} (ppm)", f"{gas} (mg/L)", f"{gas} % of ERPG-3"])
            row_data.extend([f"{max_vv:.4f}", f"{max_mgl:.4f}", f"{percent_erpg3:.2f}"])
            groups.append((gas, 3))

        if valid_gas_labels:
            for gas in valid_gas_labels:
                mod = max_mods.get(gas, 0)
                headers.append(f"{gas} Max Mod")
                try:
                    row_data.append(f"{float(mod):.1f}")
                except (TypeError, ValueError):
                    row_data.append(str(mod))
            groups.append(("Max Modules Before ERPG-3", len(valid_gas_labels)))

        table_area = _build_summary_table(headers, row_data, groups)
        layout.addWidget(table_area, 0)

        method_label = QLabel(f"Calculation Method: {result_data.get('calc_method', 'Unknown')}")
        layout.addWidget(method_label)

        result_data["tox_summary_headers"] = headers
        result_data["tox_summary_row_data"] = row_data

    def perform_pop_out(notebook, original_tab, scenario_name, result_data, tox_gas_labels, gas_data):
        new_dialog = QDialog()
        new_dialog.setWindowTitle(f"{scenario_name} (Pop Out)")
        new_dialog.resize(1150, 800)
        render_toxicity_content(new_dialog, scenario_name, result_data, tox_gas_labels, gas_data)
        notebook.removeTab(notebook.indexOf(original_tab))
        new_dialog.show()
        new_dialog.raise_()
        dialogs = getattr(notebook, "_tox_popout_dialogs", None)
        if dialogs is None:
            dialogs = []
            setattr(notebook, "_tox_popout_dialogs", dialogs)
        dialogs.append(new_dialog)

    if not tox_scenario_results:
        QMessageBox.warning(None, "No Results", "No toxicity results available to show.")
        return

    app = QApplication.instance()
    owner = app.activeWindow() if app is not None and hasattr(app, "activeWindow") else None

    popup = QDialog(owner)
    popup.setAttribute(Qt.WA_DeleteOnClose, False)
    popup.setWindowModality(Qt.NonModal)
    popup.setWindowTitle("Toxicity Assessment Results")
    popup.resize(1150, 800)
    popup.setMinimumSize(950, 680)

    if owner is not None:
        setattr(owner, "_active_tox_popup", popup)
    elif app is not None:
        setattr(app, "_active_tox_popup", popup)

    notebook = QTabWidget(popup)
    main_layout = QVBoxLayout(popup)
    main_layout.addWidget(notebook)

    if tree is None:
        for scenario_name, result_data in tox_scenario_results.items():
            if result_data is None:
                continue
            df_vv = result_data.get("tox_vv_df")
            df_mgl = result_data.get("tox_mgl_df")
            if df_vv is None or df_vv.empty or df_mgl is None or df_mgl.empty:
                print(f"Data missing or empty for scenario: {scenario_name}")
                continue

            frame = QWidget()
            notebook.addTab(frame, scenario_name)
            frame_layout = QVBoxLayout(frame)
            top_layout = QHBoxLayout()
            frame_layout.addLayout(top_layout)
            pop_btn = QPushButton("⇱ Pop Out Window")
            pop_btn.clicked.connect(lambda checked=False, f=frame, n=scenario_name, r=result_data, t=tox_gas_labels, g=gas_data: perform_pop_out(notebook, f, n, r, t, g))
            top_layout.addWidget(pop_btn, alignment=Qt.AlignRight)
            render_toxicity_content(frame, scenario_name, result_data, tox_gas_labels, gas_data)

    else:
        for row_id in tree.get_children():
            row_values = tree.item(row_id, "values")
            if not row_values:
                continue

            scenario_name = row_values[0]
            result_data = tox_scenario_results.get(scenario_name)
            if result_data is None:
                continue

            df_vv = result_data.get("tox_vv_df")
            df_mgl = result_data.get("tox_mgl_df")
            if df_vv is None or df_vv.empty or df_mgl is None or df_mgl.empty:
                print(f"Data missing or empty for scenario: {scenario_name}")
                continue

            frame = QWidget()
            notebook.addTab(frame, scenario_name)
            frame_layout = QVBoxLayout(frame)
            top_layout = QHBoxLayout()
            frame_layout.addLayout(top_layout)
            pop_btn = QPushButton("⇱ Pop Out Window")
            pop_btn.clicked.connect(lambda checked=False, f=frame, n=scenario_name, r=result_data, t=tox_gas_labels, g=gas_data: perform_pop_out(notebook, f, n, r, t, g))
            top_layout.addWidget(pop_btn, alignment=Qt.AlignRight)
            render_toxicity_content(frame, scenario_name, result_data, tox_gas_labels, gas_data)

    print("DEBUG: Showing toxicity popup")
    popup.show()
    popup.raise_()
    popup.activateWindow()
    if app is not None:
        app.processEvents()
    return popup
