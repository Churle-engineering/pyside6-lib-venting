#generate a pdf for the program
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate, SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from datetime import datetime
from PySide6.QtWidgets import QFileDialog, QMessageBox
import html
from io import BytesIO



def portrait_footer(fig, page_num, current_date):
    # Create a drawing for the footer
    footer = Drawing(fig.bbox.width, 50)
    
    # Add a rectangle for the footer background
    footer_bg = Rect(0, 0, fig.bbox.width, 50)
    footer_bg.fillColor = colors.lightgrey
    footer.add(footer_bg)
    
    # Add page number and date text
    footer.add(String(10, 30, f"Page {page_num}", fontName="Helvetica", fontSize=9))
    footer.add(String(10, 15, f"Generated on: {current_date}", fontName="Helvetica", fontSize=9))
    
    return footer

def landscape_footer(fig, page_num, current_date):
    # Create a drawing for the footer
    footer = Drawing(fig.bbox.width, 50)
    
    # Add a rectangle for the footer background
    footer_bg = Rect(0, 0, fig.bbox.width, 50)
    footer_bg.fillColor = colors.lightgrey
    footer.add(footer_bg)
    
    # Add page number and date text
    footer.add(String(10, 30, f"Page {page_num}", fontName="Helvetica", fontSize=9))
    footer.add(String(10, 15, f"Generated on: {current_date}", fontName="Helvetica", fontSize=9))
    
    return footer

def _has_entries(data):
    if data is None:
        return False
    if isinstance(data, str):
        return bool(data.strip())
    if isinstance(data, (list, tuple, set, dict)):
        return len(data) > 0
    return True


def _scenario_text(item, default_name):
    if isinstance(item, str):
        text = item.strip()
        return text if text else None

    if isinstance(item, dict):
        input_payload = item.get("input") if isinstance(item.get("input"), dict) else None
        if input_payload:
            for key in ("Scenario Description", "scenario_description", "description", "name", "title"):
                value = input_payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        preferred_keys = [
            "scenario_description",
            "description",
            "name",
            "title",
            "scenario",
        ]
        for key in preferred_keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        scalar_bits = []
        for key, value in item.items():
            if isinstance(value, (str, int, float)) and str(value).strip():
                scalar_bits.append(f"{key}: {value}")
            if len(scalar_bits) == 2:
                break
        if scalar_bits:
            return f"{default_name} ({'; '.join(scalar_bits)})"
        return str(default_name)

    return str(default_name)


def _extract_scenario_descriptions(results, scenario_type_label):
    descriptions = []

    if not _has_entries(results):
        return descriptions

    if isinstance(results, dict):
        items = list(results.items())
        for idx, (key, value) in enumerate(items, start=1):
            default_name = str(key) if str(key).strip() else f"Scenario {idx}"
            scenario_text = _scenario_text(value, default_name)
            if scenario_text:
                descriptions.append(f"{scenario_type_label}: {scenario_text}")
        return descriptions

    if isinstance(results, (list, tuple, set)):
        for idx, value in enumerate(results, start=1):
            scenario_text = _scenario_text(value, f"Scenario {idx}")
            if scenario_text:
                descriptions.append(f"{scenario_type_label}: {scenario_text}")
        return descriptions

    scenario_text = _scenario_text(results, "Scenario 1")
    if scenario_text:
        descriptions.append(f"{scenario_type_label}: {scenario_text}")
    return descriptions


def create_page_counter(start_page=1):
    start = max(1, int(start_page))
    return {
        "next_page": start,
        "contents": [],
    }


def register_page(counter, section_title=None, page_increment=1):
    if counter is None:
        return None

    page_number = counter.get("next_page", 1)

    if section_title:
        counter.setdefault("contents", []).append((str(section_title), int(page_number)))

    increment = max(1, int(page_increment))
    counter["next_page"] = int(page_number) + increment
    return int(page_number)


def get_total_pages(counter):
    if not counter:
        return 0
    return max(0, int(counter.get("next_page", 1)) - 1)


def get_contents_entries(counter):
    if not counter:
        return []
    return list(counter.get("contents", []))


def _iter_named_scenarios(scenarios):
    if scenarios is None:
        return []

    if isinstance(scenarios, dict):
        return [(str(k), v) for k, v in scenarios.items()]

    if isinstance(scenarios, (list, tuple, set)):
        items = []
        for idx, item in enumerate(scenarios, start=1):
            if isinstance(item, dict) and "name" in item and "inputs" in item:
                items.append((str(item.get("name") or f"Scenario {idx}"), item.get("inputs")))
            elif isinstance(item, tuple) and len(item) == 2:
                items.append((str(item[0]), item[1]))
            else:
                items.append((f"Scenario {idx}", item))
        return items

    return [("Scenario 1", scenarios)]


def _clean_text(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _first_present_value(source, keys):
    if not isinstance(source, dict):
        return None
    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        if value is not None:
            return value
    return None


def _summarize_flowrate_data(flowrate_data):
    if not isinstance(flowrate_data, dict) or not flowrate_data:
        return ""

    series = 0
    max_points = 0
    for value in flowrate_data.values():
        if isinstance(value, (list, tuple)):
            series += 1
            max_points = max(max_points, len(value))

    if series == 0:
        return "Imported variable flowrate data"
    return f"{series} gas series, {max_points} timesteps"


def _resolve_scenario_display_name(scenario_key, scenario_data):
    input_data = scenario_data.get("input") if isinstance(scenario_data, dict) else None
    if isinstance(input_data, dict):
        explicit_name = _first_present_value(
            input_data,
            [
                "Scenario Description",
                "scenario_description",
                "description",
                "name",
                "title",
            ],
        )
        if explicit_name is not None:
            return _clean_text(explicit_name, str(scenario_key))

    key_text = str(scenario_key)
    # Result tabs store keys like "flam:3:Scenario Name".
    if ":" in key_text:
        parts = key_text.split(":")
        if len(parts) >= 3 and _clean_text(parts[-1]):
            return _clean_text(parts[-1], key_text)
    return _clean_text(key_text, "Scenario")


def _select_plot_figure(scenario_data, preferred_key):
    if not isinstance(scenario_data, dict):
        return None

    for key in (preferred_key, "plot_fig", "figure", "fig", "flam_plot_fig", "tox_plot_fig"):
        fig = scenario_data.get(key)
        if fig is not None:
            return fig

    for key, value in scenario_data.items():
        if key.endswith("_plot_fig") and value is not None:
            return value
    return None


def _collect_pdf_input_rows(input_values, scenario_meta=None):
    rows = []
    data = input_values if isinstance(input_values, dict) else {}
    metadata = scenario_meta if isinstance(scenario_meta, dict) else {}

    custom_lib = data.get("_custom_lib_data")
    if not isinstance(custom_lib, dict):
        custom_lib = metadata.get("custom_lib") if isinstance(metadata.get("custom_lib"), dict) else {}

    alias_groups = [
        ("Scenario", "Scenario Description", ["Scenario Description"]),
        ("Scenario", "Scenario Type", ["scenario_type"]),
        ("Scenario", "LIB Type", ["LIB Type", "Generated LIB"]),
        ("Scenario", "Composition Method", ["Composition Method"]),
        ("Scenario", "Gas Composition", ["Gas Composition"]),
        ("Scenario", "Calculation Method", ["Calculation Method", "calc_method"]),
        ("Scenario", "Use Le Chatelier LFL", ["Use Le Chatelier LFL"]),
        ("Scenario", "Use Temperature Dependent LFL", ["Use Temperature Dependent LFL"]),
        ("Scenario", "Units", ["Units"]),
        ("Scenario", "Cells per module", ["Cells per module", "Cells per"]),
        ("Scenario", "Modules per unit", ["Modules per unit", "Modules per"]),
        ("Scenario", "Module Propagation Delay (s)", ["Module Propagation Delay (s)"]),
        ("Scenario", "Calculation Duration (s)", ["Calculation Duration (s)"]),
        ("Room", "Battery Room", ["Battery Room", "battery_room"]),
        ("Room", "Room Area (m2)", ["Room Area (m2)"]),
        ("Room", "Room Height (m)", ["Room Height (m)"]),
        ("Room", "Equipment Space (%)", ["Equipment Space (%)"]),
        ("Room", "Ventilation Rate (L/s/m2)", ["Ventilation Rate (L/s/m2)"]),
        ("Room", "Vent Switch Conc (%)", ["Vent Switch Conc (%)"]),
        ("Room", "Emergency Vent Rate (L/s/m2)", ["Emergency Vent Rate (L/s/m2)"]),
        ("Battery", "Manufacturer Name", ["Manufacturer Name", "manufacturer_name"]),
        ("Battery", "Battery Chemistry", ["Battery Chemistry"]),
        ("Battery", "LFL (%)", ["LFL (%)", "lfl_(%)"]),
        ("Battery", "Venting Temperature (°C)", ["Venting Temperature (°C)", "venting_temperature_(°C)"]),
        ("Battery", "Battery Charge (%)", ["Battery Charge (%)"]),
        ("Battery", "Cell Volume (L)", ["Cell Volume (L)", "cell_volume_(l)"]),
        ("Battery", "Cell Duration (s)", ["Cell Duration (s)", "cell_duration_(s)"]),
        ("Battery", "Module Volume (L)", ["Module Volume (L)", "module_volume_(l)"]),
        ("Battery", "Module Duration (s)", ["Module Duration (s)", "module_duration_(s)"]),
        ("Battery", "Module Capacity (kWh)", ["Module Capacity (kWh)", "module_capacity_(kwh)"]),
        ("Battery", "CO (%)", ["CO (%)", "co_(%)", "Carbon Monoxide (%)"]),
        ("Battery", "CO2 (%)", ["CO2 (%)", "co2_(%)", "Carbon Dioxide (%)"]),
        ("Battery", "H2 (%)", ["H2 (%)", "h2_(%)", "Hydrogen (%)"]),
        ("Battery", "Total Hydrocarbons (%)", ["Total Hydrocarbons (%)", "total_hydrocarbons_(%)"]),
    ]

    used_keys = set()

    def _append_row(category, label, value, key_refs=None):
        if isinstance(value, str):
            if not value.strip():
                return
            text = value.strip()
        elif value is None:
            return
        else:
            text = str(value)

        rows.append((category, label, text))
        if key_refs:
            for key in key_refs:
                used_keys.add(key)

    _append_row("Scenario", "Scenario Name", metadata.get("scenario_name"))

    metadata_only_keys = {"scenario_type", "calc_method"}
    for category, label, keys in alias_groups:
        lookup_source = metadata if keys and (keys[0].startswith("__") or keys[0] in metadata_only_keys) else data
        value = _first_present_value(lookup_source, keys)
        _append_row(category, label, value, key_refs=keys)

    if isinstance(custom_lib, dict):
        for lib_key in [
            "Manufacturer name",
            "Battery room",
            "Battery Chemistry",
            "LFL (%)",
            "Cell Duration (s)",
            "Module Duration (s)",
            "Venting Temperature (°C)",
            "Cell Amp Hr (Ah)",
            "Module Amp Hr (Ah)",
            "Module Capacity (kWh)",
            "Cell Volume (L)",
            "Module Volume (L)",
            "Battery Charge (%)",
            "CO (%)",
            "CO2 (%)",
            "H2 (%)",
            "Total Hydrocarbons (%)",
        ]:
            _append_row("Generated LIB", lib_key, custom_lib.get(lib_key), key_refs=[lib_key])

        flowrate_summary = _summarize_flowrate_data(custom_lib.get("_flowrate_data"))
        if flowrate_summary:
            _append_row("Generated LIB", "Variable Flowrate Data", flowrate_summary, key_refs=["_flowrate_data"])

    lib_flowrate_summary = _summarize_flowrate_data(data.get("_lib_flowrate_data"))
    if lib_flowrate_summary:
        _append_row("Generated LIB", "Scenario Flowrate Data", lib_flowrate_summary, key_refs=["_lib_flowrate_data"])

    skip_keys = {
        "_custom_lib_data",
        "_composition_data",
        "_tox_gas_composition_override",
        "_percent_tox_override",
        "_flam_percent_override",
        "_lib_flowrate_data",
    }
    for key in sorted(data.keys()):
        if key in used_keys or key in skip_keys or str(key).startswith("_"):
            continue
        value = data.get(key)
        if isinstance(value, dict):
            continue
        _append_row("Additional", str(key), value)

    return rows


def _input_pairs(input_values):
    if input_values is None:
        return []

    if isinstance(input_values, dict):
        return [(str(k), "" if v is None else str(v)) for k, v in input_values.items()]

    if isinstance(input_values, (list, tuple, set)):
        pairs = []
        for idx, item in enumerate(input_values, start=1):
            if isinstance(item, tuple) and len(item) == 2:
                pairs.append((str(item[0]), "" if item[1] is None else str(item[1])))
            elif isinstance(item, dict):
                key = item.get("name", f"Input {idx}")
                value = item.get("value", "")
                pairs.append((str(key), "" if value is None else str(value)))
            else:
                pairs.append((f"Input {idx}", str(item)))
        return pairs

    return [("Value", str(input_values))]


def build_scenario_input_pages(scenarios, page_counter=None, include_title=False, styles=None):
    scenario_items = _iter_named_scenarios(scenarios)
    if not scenario_items:
        return []

    local_styles = styles or getSampleStyleSheet()
    flowables = []

    for idx, (scenario_name, input_values) in enumerate(scenario_items):
        if include_title or idx > 0:
            flowables.append(PageBreak())

        register_page(page_counter, f"Scenario Inputs - {scenario_name}")

        scenario_data = input_values
        scenario_meta = {}
        if isinstance(input_values, dict) and "__pdf_meta__" in input_values:
            meta_candidate = input_values.get("__pdf_meta__")
            scenario_meta = meta_candidate if isinstance(meta_candidate, dict) else {}
            scenario_data = scenario_meta.get("input", {}) if isinstance(scenario_meta, dict) else {}
            if not isinstance(scenario_data, dict):
                scenario_data = {}

        flowables.append(Paragraph(f"Scenario Inputs: {html.escape(str(scenario_name))}", local_styles["Heading2"]))
        flowables.append(Spacer(1, 4 * mm))

        table_rows = [["Category", "Input Name", "Input Value"]]
        rows = _collect_pdf_input_rows(scenario_data, scenario_meta)
        if not rows:
            table_rows.append(["Scenario", "No inputs provided", "-"])
        else:
            for category, input_name, input_value in rows:
                table_rows.append([html.escape(category), html.escape(input_name), html.escape(input_value)])

        inputs_table = Table(table_rows, colWidths=[28 * mm, 64 * mm, None], repeatRows=1)
        inputs_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6E6E6")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        inputs_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F5F5F5")),
                ]
            )
        )
        flowables.append(inputs_table)

    return flowables


def _plot_legend_entries(fig):
    entries = []
    if fig is None:
        return entries

    for ax in fig.get_axes():
        handles, labels = ax.get_legend_handles_labels()
        for handle, label in zip(handles, labels):
            label_text = str(label).strip()
            if not label_text or label_text.startswith("_"):
                continue

            color = None
            get_color = getattr(handle, "get_color", None)
            if callable(get_color):
                try:
                    color = get_color()
                except Exception:
                    color = None

            entries.append((label_text, color))

    # Preserve order while deduplicating labels.
    deduped = []
    seen = set()
    for label_text, color in entries:
        if label_text in seen:
            continue
        seen.add(label_text)
        deduped.append((label_text, color))
    return deduped


def _color_to_hex(color):
    if color is None:
        return None
    try:
        from matplotlib.colors import to_hex

        return to_hex(color)
    except Exception:
        return None


def _figure_to_rl_image(fig, max_width, max_height, dpi=170):
    if fig is None:
        return None

    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    buffer.seek(0)

    fig_width = max(1.0, float(fig.get_figwidth()) * float(dpi))
    fig_height = max(1.0, float(fig.get_figheight()) * float(dpi))
    scale = min(float(max_width) / fig_width, float(max_height) / fig_height)

    img = Image(buffer)
    img.drawWidth = fig_width * scale
    img.drawHeight = fig_height * scale
    img.hAlign = "CENTER"
    return img


def _build_logo_flowable(logo_path, max_width=35 * mm, max_height=18 * mm):
    try:
        image_reader = ImageReader(logo_path)
        image_width, image_height = image_reader.getSize()
        scale = min(float(max_width) / float(image_width), float(max_height) / float(image_height))
        logo = Image(logo_path, width=image_width * scale, height=image_height * scale)
        logo.hAlign = "RIGHT"
        return logo
    except Exception:
        return Paragraph("ARUP", getSampleStyleSheet()["Heading3"])


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _popup_style_flam_summary_row(scenario_name, result_data):
    if not isinstance(result_data, dict):
        return [], []

    vv_df = result_data.get("flam_vv_df")
    mgl_df = result_data.get("flam_mgl_df")
    input_data = result_data.get("input", {}) if isinstance(result_data.get("input"), dict) else {}
    max_mods = result_data.get("flam_max_mod")
    if not isinstance(max_mods, dict):
        max_mods = {}

    headers = [
        "Scenario",
        "Description",
        "Manufacturer name",
        "Battery room",
        "Modules",
        "Units",
        "Peak Total Conc. (v/v%)",
        "Peak Total Gas (mg/L)",
        "(%) of LFL",
        "Max Modules Before LFL",
    ]

    vv_max_total_value = 0.0
    mgl_max_total_value = 0.0
    if vv_df is not None and hasattr(vv_df, "columns"):
        if "Total Gas (v/v%)" in vv_df.columns and hasattr(vv_df, "empty") and not vv_df.empty:
            vv_max_total_value = _as_float(vv_df["Total Gas (v/v%)"].max(), 0.0)
    if mgl_df is not None and hasattr(mgl_df, "columns"):
        if "Total Gas (mg/L)" in mgl_df.columns and hasattr(mgl_df, "empty") and not mgl_df.empty:
            mgl_max_total_value = _as_float(mgl_df["Total Gas (mg/L)"].max(), 0.0)

    lfl_bat = _as_float(input_data.get("LFL (%)", input_data.get("lfl_(%)", 0.0)), 0.0)
    mods = _as_float(input_data.get("Modules per", input_data.get("Modules per unit", 0.0)), 0.0)
    units = _as_float(input_data.get("Units", 0.0), 0.0)

    row_data = [
        scenario_name,
        input_data.get("Scenario Description"),
        input_data.get("manufacturer_name"),
        input_data.get("battery_room"),
        mods,
        units,
        f"{vv_max_total_value:.4f}",
        f"{mgl_max_total_value:.4f}",
        f"{(vv_max_total_value / lfl_bat) * 100 if lfl_bat else 0:.3f}",
        max_mods.get("total_gas", "N/A"),
    ]

    return headers, row_data


def _infer_tox_labels_from_df(df_mgl):
    if df_mgl is None or not hasattr(df_mgl, "columns"):
        return []
    labels = []
    for col in list(df_mgl.columns):
        if col.endswith(" (mg/L)") and col != "Total Gas (mg/L)":
            labels.append(col[: -len(" (mg/L)")])
    return labels


def _popup_style_tox_summary_row(scenario_name, result_data, tox_gas_labels=None, gas_data=None):
    if not isinstance(result_data, dict):
        return [], []

    df_vv = result_data.get("tox_vv_df")
    df_mgl = result_data.get("tox_mgl_df")
    input_data = result_data.get("input", {}) if isinstance(result_data.get("input"), dict) else {}
    max_mods = result_data.get("tox_max_mod", {})
    if not isinstance(max_mods, dict):
        max_mods = {}
    gas_data = gas_data if isinstance(gas_data, dict) else {}

    if not tox_gas_labels:
        tox_gas_labels = _infer_tox_labels_from_df(df_mgl)

    valid_gas_labels = []
    if df_mgl is not None and hasattr(df_mgl, "columns"):
        valid_gas_labels = [label for label in tox_gas_labels if f"{label} (mg/L)" in df_mgl.columns]

    # Match popup behaviour: Total Gas (v/v%) is derived from v/v% columns if missing.
    peak_value_vv = 0.0
    if df_vv is not None and hasattr(df_vv, "columns") and hasattr(df_vv, "empty") and not df_vv.empty:
        if "Total Gas (v/v%)" not in df_vv.columns:
            vv_cols = [col for col in list(df_vv.columns) if str(col).endswith("(v/v%)")]
            if vv_cols:
                df_vv["Total Gas (v/v%)"] = df_vv[vv_cols].sum(axis=1)
            else:
                df_vv["Total Gas (v/v%)"] = 0
        peak_value_vv = _as_float(df_vv["Total Gas (v/v%)"].max(), 0.0)

    peak_value_mgl = 0.0
    if df_mgl is not None and hasattr(df_mgl, "columns") and hasattr(df_mgl, "empty") and not df_mgl.empty:
        if "Total Gas (mg/L)" not in df_mgl.columns:
            mg_cols = [f"{gas} (mg/L)" for gas in valid_gas_labels if f"{gas} (mg/L)" in df_mgl.columns]
            if mg_cols:
                df_mgl["Total Gas (mg/L)"] = df_mgl[mg_cols].sum(axis=1)
            else:
                df_mgl["Total Gas (mg/L)"] = 0
        peak_value_mgl = _as_float(df_mgl["Total Gas (mg/L)"].max(), 0.0)

    total_mods = _as_float(input_data.get("Modules per", 0.0), 0.0) * _as_float(input_data.get("Units", 0.0), 0.0)

    headers = [
        "Scenario",
        "Scenario Description",
        "Manufacturer",
        "Battery Room",
        "Modules",
        "Peak Total Gas (v/v%)",
        "Peak Total Gas (mg/L)",
    ]
    row_data = [
        scenario_name,
        input_data.get("Scenario Description", ""),
        input_data.get("manufacturer_name", ""),
        input_data.get("battery_room", ""),
        total_mods,
        f"{peak_value_vv:.4f}",
        f"{peak_value_mgl:.4f}",
    ]

    for gas in valid_gas_labels:
        vv_col = f"{gas} (v/v%)"
        mgl_col = f"{gas} (mg/L)"
        erpg3 = _as_float(gas_data.get(gas, {}).get("erpg_3", 0.0), 0.0)
        max_vv = 0.0
        max_mgl = 0.0
        if df_vv is not None and hasattr(df_vv, "columns") and vv_col in df_vv.columns:
            max_vv = _as_float(df_vv[vv_col].max(), 0.0)
        if df_mgl is not None and hasattr(df_mgl, "columns") and mgl_col in df_mgl.columns:
            max_mgl = _as_float(df_mgl[mgl_col].max(), 0.0)

        percent_erpg3 = (max_mgl / erpg3) * 100 if erpg3 else 0

        headers.extend([f"{gas} (ppm)", f"{gas} (mg/L)", f"{gas} % of ERPG-3"])
        row_data.extend([f"{max_vv:.4f}", f"{max_mgl:.4f}", f"{percent_erpg3:.2f}"])

    if valid_gas_labels:
        for gas in valid_gas_labels:
            mod = max_mods.get(gas, 0)
            headers.append(f"{gas} Max Mod")
            try:
                row_data.append(f"{float(mod):.1f}")
            except (TypeError, ValueError):
                row_data.append(str(mod))

    return headers, row_data


def _summary_table_flowable(headers, row_data, table_width):
    if not headers:
        return Paragraph("No summary data available.", getSampleStyleSheet()["BodyText"])

    styles = getSampleStyleSheet()
    body_style = styles["BodyText"]
    header_style = styles["BodyText"].clone("SummaryHeader")
    header_style.fontName = "Helvetica-Bold"
    header_style.wordWrap = "CJK"
    body_style.wordWrap = "CJK"

    normalized_row_data = ["" if val is None else str(val) for val in row_data]

    def desired_width(header_text, value_text):
        text_length = max(len(str(header_text)), len(str(value_text)))
        return min(65 * mm, max(28 * mm, text_length * 1.45 * mm))

    grouped_columns = []
    current_group = []
    current_width = 0.0
    gutter = 4 * mm

    for header_text, value_text in zip(headers, normalized_row_data):
        proposed_width = desired_width(header_text, value_text)
        extra_width = proposed_width if not current_group else proposed_width + gutter
        if current_group and current_width + extra_width > table_width:
            grouped_columns.append(current_group)
            current_group = []
            current_width = 0.0

        current_group.append((str(header_text), str(value_text), proposed_width))
        current_width += proposed_width if len(current_group) == 1 else proposed_width + gutter

    if current_group:
        grouped_columns.append(current_group)

    flow_table_rows = []
    row_heights = []
    col_widths = []

    for group in grouped_columns:
        group_desired_total = sum(item[2] for item in group)
        if group_desired_total <= 0:
            group_widths = [table_width / len(group)] * len(group)
        else:
            scale = table_width / group_desired_total
            group_widths = [item[2] * scale for item in group]

        header_row = []
        value_row = []
        for (header_text, value_text, _), group_width in zip(group, group_widths):
            header_row.append(Paragraph(html.escape(header_text), header_style))
            value_row.append(Paragraph(html.escape(value_text), body_style))
            col_widths.append(group_width)

        flow_table_rows.append(header_row)
        flow_table_rows.append(value_row)
        row_heights.extend([None, None])

    summary_table = Table(flow_table_rows, colWidths=col_widths[: max(len(row) for row in flow_table_rows)], repeatRows=0, splitByRow=1)
    summary_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    for row_index in range(0, len(flow_table_rows), 2):
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#E6E6E6")),
                    ("FONTNAME", (0, row_index), (-1, row_index), "Helvetica-Bold"),
                    ("TEXTCOLOR", (0, row_index), (-1, row_index), colors.black),
                ]
            )
        )

    return summary_table


def _build_legend_table(legend_entries, available_width, styles, target_max_height=None):
    if not legend_entries:
        return None, 0

    local_styles = styles or getSampleStyleSheet()
    legend_count = len(legend_entries)
    row_height_estimate = 7 * mm
    if target_max_height is not None and target_max_height > row_height_estimate:
        max_rows = max(1, int(target_max_height / row_height_estimate))
        column_count = max(2, min(8, (legend_count + max_rows - 1) // max_rows))
    else:
        column_count = min(4, max(2, legend_count))
    row_count = (legend_count + column_count - 1) // column_count
    entry_width = available_width / column_count

    grid_rows = []
    for row_index in range(row_count):
        row = []
        for column_index in range(column_count):
            entry_index = row_index + (column_index * row_count)
            if entry_index >= legend_count:
                row.append(Paragraph(" ", local_styles["BodyText"]))
                continue

            label_text, color = legend_entries[entry_index]
            color_hex = _color_to_hex(color) or "#444444"
            row.append(
                Paragraph(
                    f"<font color='{color_hex}'>&#9632;</font> {html.escape(label_text)}",
                    local_styles["BodyText"],
                )
            )
        grid_rows.append(row)

    legend_table = Table(grid_rows, colWidths=[entry_width] * column_count)
    legend_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    estimated_height = max(10 * mm, row_count * 7 * mm)
    return legend_table, estimated_height


def build_landscape_plot_and_summary_pages(
    flam_scenario_results=None,
    tox_scenario_results=None,
    tox_gas_labels=None,
    gas_data=None,
    page_counter=None,
    styles=None,
    landscape_template_name="landscape",
):
    """Build separate landscape plot and summary pages for each scenario."""
    local_styles = styles or getSampleStyleSheet()
    flowables = []

    page_width, page_height = landscape(A4)
    usable_width = page_width - (20 * mm) - (20 * mm)
    usable_plot_height = page_height - (20 * mm) - (20 * mm) - (35 * mm)
    content_height = page_height - (20 * mm) - (20 * mm)

    scenario_groups = [
        ("Flam", flam_scenario_results or {}, "flam_plot_fig", "flam"),
        ("Tox", tox_scenario_results or {}, "tox_plot_fig", "tox"),
    ]

    first_page = True
    for scenario_type, scenario_dict, fig_key, summary_kind in scenario_groups:
        if not isinstance(scenario_dict, dict):
            continue

        for scenario_idx, (scenario_key, scenario_data) in enumerate(scenario_dict.items(), start=1):
            scenario_name = _resolve_scenario_display_name(scenario_key, scenario_data)
            if first_page:
                first_page = False
            else:
                if landscape_template_name:
                    flowables.append(NextPageTemplate(landscape_template_name))
                flowables.append(PageBreak())

            if landscape_template_name:
                flowables.append(NextPageTemplate(landscape_template_name))

            plot_page_title = f"{scenario_type} Scenario {scenario_idx} Plot"
            register_page(page_counter, plot_page_title)

            flowables.append(Paragraph(plot_page_title, local_styles["Heading2"]))
            flowables.append(Spacer(1, 2 * mm))
            flowables.append(Paragraph(f"Scenario Name: {html.escape(str(scenario_name))}", local_styles["BodyText"]))
            flowables.append(Spacer(1, 3 * mm))

            fig = _select_plot_figure(scenario_data, fig_key)

            plot_image = _figure_to_rl_image(fig, usable_width, usable_plot_height)
            if plot_image is None:
                flowables.append(
                    Paragraph(
                        "Plot is unavailable. Open the scenario popup first so the plot can be generated.",
                        local_styles["BodyText"],
                    )
                )
                flowables.append(Spacer(1, 6 * mm))
            else:
                flowables.append(plot_image)

            legend_entries = _plot_legend_entries(fig)
            current_plot_height = plot_image.drawHeight if plot_image is not None else 0
            text_block_height = 18 * mm
            if legend_entries:
                available_for_legend = max(10 * mm, content_height - text_block_height - current_plot_height - (10 * mm))
                legend_table, legend_height = _build_legend_table(legend_entries, usable_width, local_styles, target_max_height=available_for_legend)
                spacer_height = max(4 * mm, content_height - text_block_height - current_plot_height - legend_height - (4 * mm))
                flowables.append(Spacer(1, spacer_height))
                flowables.append(Paragraph("Legend", local_styles["Heading3"]))
                flowables.append(legend_table)
            else:
                flowables.append(Spacer(1, max(4 * mm, content_height - current_plot_height - (26 * mm))))

            if landscape_template_name:
                flowables.append(NextPageTemplate(landscape_template_name))
            flowables.append(PageBreak())

            summary_page_title = f"{scenario_type} Scenario {scenario_idx} Results Summary"
            register_page(page_counter, summary_page_title)
            flowables.append(Paragraph(summary_page_title, local_styles["Heading2"]))
            flowables.append(Spacer(1, 2 * mm))
            flowables.append(Paragraph(f"Scenario Name: {html.escape(str(scenario_name))}", local_styles["BodyText"]))
            flowables.append(Spacer(1, 4 * mm))

            headers = []
            row_data = []
            if isinstance(scenario_data, dict):
                if summary_kind == "flam":
                    headers = scenario_data.get("flam_summary_headers", [])
                    row_data = scenario_data.get("flam_summary_row_data", [])
                    if not headers or not row_data:
                        headers, row_data = _popup_style_flam_summary_row(scenario_name, scenario_data)
                else:
                    headers = scenario_data.get("tox_summary_headers", [])
                    row_data = scenario_data.get("tox_summary_row_data", [])
                    if not headers or not row_data:
                        headers, row_data = _popup_style_tox_summary_row(
                            scenario_name,
                            scenario_data,
                            tox_gas_labels=tox_gas_labels,
                            gas_data=gas_data,
                        )

            flowables.append(Paragraph("Result Summary", local_styles["Heading3"]))
            flowables.append(_summary_table_flowable(headers, row_data, usable_width))

    return flowables


def build_landscape_scenario_plot_pages(
    flam_scenario_results=None,
    tox_scenario_results=None,
    page_counter=None,
    styles=None,
    landscape_template_name="landscape",
):
    """Create one landscape plot page per scenario using popup-generated figures.

    Expects each scenario result dict to carry `flam_plot_fig` or `tox_plot_fig`,
    as populated by display_popup.py after the popup has rendered.
    """
    local_styles = styles or getSampleStyleSheet()
    flowables = []

    page_width, page_height = landscape(A4)
    usable_width = page_width - (20 * mm) - (20 * mm)
    usable_plot_height = page_height - (20 * mm) - (30 * mm) - (45 * mm)

    scenario_groups = [
        ("Flam", flam_scenario_results or {}, "flam_plot_fig"),
        ("Tox", tox_scenario_results or {}, "tox_plot_fig"),
    ]

    first_page = True
    for scenario_type, scenario_dict, fig_key in scenario_groups:
        if not isinstance(scenario_dict, dict):
            continue

        for scenario_idx, (scenario_name, scenario_data) in enumerate(scenario_dict.items(), start=1):
            if first_page:
                first_page = False
            else:
                if landscape_template_name:
                    flowables.append(NextPageTemplate(landscape_template_name))
                flowables.append(PageBreak())

            if landscape_template_name:
                flowables.append(NextPageTemplate(landscape_template_name))

            page_title = f"{scenario_type} Scenario {scenario_idx} Plot"
            register_page(page_counter, page_title)

            flowables.append(Paragraph(page_title, local_styles["Heading2"]))
            flowables.append(Spacer(1, 2 * mm))
            flowables.append(Paragraph(f"Scenario Name: {html.escape(str(scenario_name))}", local_styles["BodyText"]))
            flowables.append(Spacer(1, 3 * mm))

            fig = None
            if isinstance(scenario_data, dict):
                fig = scenario_data.get(fig_key)

            plot_image = _figure_to_rl_image(fig, usable_width, usable_plot_height)
            if plot_image is None:
                flowables.append(
                    Paragraph(
                        "Plot is unavailable. Open the scenario popup first so the plot can be generated.",
                        local_styles["BodyText"],
                    )
                )
                flowables.append(Spacer(1, 4 * mm))
            else:
                flowables.append(plot_image)
                flowables.append(Spacer(1, 4 * mm))

            flowables.append(Paragraph("Legend", local_styles["Heading3"]))
            legend_entries = _plot_legend_entries(fig)
            if not legend_entries:
                flowables.append(Paragraph("No legend entries available.", local_styles["BodyText"]))
                continue

            legend_rows = []
            for label_text, color in legend_entries:
                color_hex = _color_to_hex(color) or "#444444"
                marker = f"<font color='{color_hex}'>&#9632;</font>"
                legend_rows.append([Paragraph(marker, local_styles["BodyText"]), Paragraph(html.escape(label_text), local_styles["BodyText"])])

            legend_table = Table(legend_rows, colWidths=[8 * mm, usable_width - (8 * mm)])
            legend_table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 2),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                        ("TOPPADDING", (0, 0), (-1, -1), 1),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                    ]
                )
            )
            flowables.append(legend_table)

    return flowables


def title_page(
    tox_scenario_results=None,
    flam_scenario_results=None,
    title="Battery Off-gas Assessment Results",
    subtitle="Result Export Report",
    contents_entries=None,
    page_counter=None,
    body_text=(
        "This report summarises the analysed venting scenarios for the current "
        "project configuration."
    ),
):
    current_date = datetime.now().strftime("%d %B %Y")
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"{now_str} Offgas_Assessment_Report.pdf"

    file_path = QFileDialog.getSaveFileName(
        None,
        "Save PDF Report",
        filename,
        "PDF Files (*.pdf)",
    )[0]
    if not file_path:
        QMessageBox.warning(
            None,
            "Save PDF Report",
            "No file selected. PDF report was not saved.",
        )
        return None

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        file_path,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=25 * mm,
    )

    def draw_title_page_footer(canv, document):
        canv.saveState()
        footer_y = 14 * mm
        canv.setStrokeColor(colors.lightgrey)
        canv.line(document.leftMargin, footer_y + 5 * mm, A4[0] - document.rightMargin, footer_y + 5 * mm)
        canv.setFont("Helvetica", 9)
        canv.setFillColor(colors.grey)
        canv.drawRightString(A4[0] - document.rightMargin, footer_y, f"Generated on: {current_date}")
        canv.restoreState()

    scenario_descriptions = []
    scenario_descriptions.extend(_extract_scenario_descriptions(flam_scenario_results, "Flam"))
    scenario_descriptions.extend(_extract_scenario_descriptions(tox_scenario_results, "Tox"))

    # Preserve order while removing duplicates.
    scenario_descriptions = list(dict.fromkeys(scenario_descriptions))

    story = []

    logo_path = "arup_logo.png"
    story.append(_build_logo_flowable(logo_path))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(subtitle, styles["Heading2"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(body_text, styles["BodyText"]))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("Contents", styles["Heading3"]))
    story.append(Spacer(1, 2 * mm))

    if contents_entries is None and page_counter is not None:
        contents_entries = get_contents_entries(page_counter)

    toc_pairs = []
    if contents_entries:
        for entry in contents_entries:
            if isinstance(entry, tuple) and len(entry) >= 2:
                toc_pairs.append((str(entry[0]).strip() or "Untitled", entry[1]))
            elif isinstance(entry, dict):
                entry_title = str(entry.get("title") or entry.get("name") or "Untitled")
                toc_pairs.append((entry_title, entry.get("page")))
            else:
                toc_pairs.append((str(entry), None))
    elif scenario_descriptions:
        for desc in scenario_descriptions:
            toc_pairs.append((desc, None))

    if not toc_pairs:
        story.append(Paragraph("&bull; No scenarios were calculated.", styles["BodyText"]))
    else:
        content_width = A4[0] - 40 * mm
        title_col_w = 110 * mm
        page_col_w = 12 * mm
        dots_col_w = content_width - title_col_w - page_col_w
        # Helvetica "." glyph width = 278/1000 em; compute how many fit in one line
        dots_count = max(10, int((dots_col_w - 2) / (9 * 278 / 1000)))
        dots_style = ParagraphStyle(
            "TOCDotLeader",
            parent=styles["BodyText"],
            fontSize=9,
            textColor=colors.Color(0.65, 0.65, 0.65),
        )
        toc_rows = [
            [
                Paragraph(f"&bull; {html.escape(t)}", styles["BodyText"]),
                Paragraph("." * dots_count, dots_style),
                str(p) if p is not None else "",
            ]
            for t, p in toc_pairs
        ]
        toc_table = Table(toc_rows, colWidths=[title_col_w, dots_col_w, page_col_w])
        toc_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(toc_table)

    doc.build(story, onFirstPage=draw_title_page_footer)
    return file_path


def _build_title_page_story(
    styles,
    title,
    subtitle,
    body_text,
    current_date,
    scenario_type_text,
    scenario_descriptions,
    contents_entries,
):
    story = []

    logo_path = "arup_logo.png"
    story.append(_build_logo_flowable(logo_path))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(subtitle, styles["Heading2"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(body_text, styles["BodyText"]))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("Title Contents", styles["Heading3"]))
    story.append(Spacer(1, 2 * mm))

    toc_pairs = []
    if contents_entries:
        for entry in contents_entries:
            if isinstance(entry, tuple) and len(entry) >= 2:
                toc_pairs.append((str(entry[0]).strip() or "Untitled", entry[1]))
            elif isinstance(entry, dict):
                entry_title = str(entry.get("title") or entry.get("name") or "Untitled")
                toc_pairs.append((entry_title, entry.get("page")))
            else:
                toc_pairs.append((str(entry), None))
    elif scenario_descriptions:
        for desc in scenario_descriptions:
            toc_pairs.append((desc, None))

    if not toc_pairs:
        story.append(Paragraph("&bull; No scenarios were calculated.", styles["BodyText"]))
        return story

    content_width = A4[0] - 40 * mm
    title_col_w = 110 * mm
    page_col_w = 12 * mm
    dots_col_w = content_width - title_col_w - page_col_w
    dots_count = max(10, int((dots_col_w - 2) / (9 * 278 / 1000)))
    dots_style = ParagraphStyle(
        "TOCDotLeader",
        parent=styles["BodyText"],
        fontSize=9,
        textColor=colors.Color(0.65, 0.65, 0.65),
    )
    toc_rows = [
        [
            Paragraph(f"&bull; {html.escape(t)}", styles["BodyText"]),
            Paragraph("." * dots_count, dots_style),
            str(p) if p is not None else "",
        ]
        for t, p in toc_pairs
    ]
    toc_table = Table(toc_rows, colWidths=[title_col_w, dots_col_w, page_col_w])
    toc_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(toc_table)
    return story


def _build_single_scenario_result_pages(
    scenario_type,
    scenario_idx,
    scenario_key,
    scenario_data,
    fig_key,
    summary_kind,
    page_counter=None,
    styles=None,
    tox_gas_labels=None,
    gas_data=None,
    landscape_template_name="landscape",
):
    """Return flowables for one scenario: a plot page followed by a results summary page.

    No leading PageBreak — the caller inserts one before this block.
    """
    local_styles = styles or getSampleStyleSheet()
    flowables = []

    page_width, page_height = landscape(A4)
    usable_width = page_width - 40 * mm
    content_height = page_height - 40 * mm

    scenario_name = _resolve_scenario_display_name(scenario_key, scenario_data)

    # ---- Plot page ----
    plot_page_title = f"{scenario_type} Scenario {scenario_idx} Plot"
    register_page(page_counter, plot_page_title)

    header_height = 20 * mm
    legend_reserve = 22 * mm
    usable_plot_height = content_height - header_height - legend_reserve

    flowables.append(Paragraph(plot_page_title, local_styles["Heading2"]))
    flowables.append(Spacer(1, 2 * mm))
    flowables.append(Paragraph(f"Scenario Name: {html.escape(str(scenario_name))}", local_styles["BodyText"]))
    flowables.append(Spacer(1, 3 * mm))

    fig = _select_plot_figure(scenario_data, fig_key)
    plot_image = _figure_to_rl_image(fig, usable_width, usable_plot_height)

    if plot_image is None:
        flowables.append(
            Paragraph(
                "Plot is unavailable. Open the scenario popup first so the plot can be generated.",
                local_styles["BodyText"],
            )
        )
        actual_plot_height = 0.0
    else:
        flowables.append(plot_image)
        actual_plot_height = float(plot_image.drawHeight)

    legend_entries = _plot_legend_entries(fig)
    if legend_entries:
        flowables.append(Spacer(1, 4 * mm))
        flowables.append(Paragraph("Legend", local_styles["Heading3"]))
        available_for_legend = max(10 * mm, content_height - header_height - actual_plot_height - (10 * mm))
        legend_table, _ = _build_legend_table(
            legend_entries, usable_width, local_styles, target_max_height=available_for_legend
        )
        flowables.append(legend_table)

    # ---- Summary page ----
    if landscape_template_name:
        flowables.append(NextPageTemplate(landscape_template_name))
    flowables.append(PageBreak())

    summary_page_title = f"{scenario_type} Scenario {scenario_idx} Results Summary"
    register_page(page_counter, summary_page_title)

    flowables.append(Paragraph(summary_page_title, local_styles["Heading2"]))
    flowables.append(Spacer(1, 2 * mm))
    flowables.append(Paragraph(f"Scenario Name: {html.escape(str(scenario_name))}", local_styles["BodyText"]))
    flowables.append(Spacer(1, 4 * mm))

    headers = []
    row_data = []
    if isinstance(scenario_data, dict):
        if summary_kind == "flam":
            headers = scenario_data.get("flam_summary_headers", [])
            row_data = scenario_data.get("flam_summary_row_data", [])
            if not headers or not row_data:
                headers, row_data = _popup_style_flam_summary_row(scenario_name, scenario_data)
        else:
            headers = scenario_data.get("tox_summary_headers", [])
            row_data = scenario_data.get("tox_summary_row_data", [])
            if not headers or not row_data:
                headers, row_data = _popup_style_tox_summary_row(
                    scenario_name, scenario_data, tox_gas_labels=tox_gas_labels, gas_data=gas_data
                )

    flowables.append(Paragraph("Result Summary", local_styles["Heading3"]))
    flowables.append(_summary_table_flowable(headers, row_data, usable_width))

    return flowables


def pdf_generation(
    tox_scenario_results=None,
    flam_scenario_results=None,
    title="Battery Off-gas Assessment Results",
    subtitle="Result Export Report",
    body_text=(
        "This report summarises the analysed venting scenarios for the current "
        "project configuration."
    ),
    tox_gas_labels=None,
    gas_data=None,
):
    """Generate the final report: title page then per-scenario inputs, plots, and summaries."""
    current_date = datetime.now().strftime("%d %B %Y")
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"{now_str} Offgas_Assessment_Report.pdf"

    file_path = QFileDialog.getSaveFileName(
        None,
        "Save PDF Report",
        filename,
        "PDF Files (*.pdf)",
    )[0]
    if not file_path:
        QMessageBox.warning(
            None,
            "Save PDF Report",
            "No file selected. PDF report was not saved.",
        )
        return None

    styles = getSampleStyleSheet()

    flam_present = _has_entries(flam_scenario_results)
    tox_present = _has_entries(tox_scenario_results)
    if flam_present and tox_present:
        scenario_type_text = "Both flam and tox scenarios are calculated."
    elif flam_present:
        scenario_type_text = "Flam scenarios are calculated."
    elif tox_present:
        scenario_type_text = "Tox scenarios are calculated."
    else:
        scenario_type_text = "Neither flam nor tox scenarios are calculated."

    flam_items = list(flam_scenario_results.items()) if isinstance(flam_scenario_results, dict) else []
    tox_items = list(tox_scenario_results.items()) if isinstance(tox_scenario_results, dict) else []
    max_scenarios = max(len(flam_items), len(tox_items)) if (flam_items or tox_items) else 0

    page_counter = create_page_counter(start_page=2)
    body_story = []

    for i in range(max_scenarios):
        # --- Inputs (portrait) - one combined page per scenario ---
        pkey, pdata = flam_items[i] if i < len(flam_items) else tox_items[i]
        scenario_name_input = _resolve_scenario_display_name(pkey, pdata)
        scenario_input = pdata.get("input") if isinstance(pdata, dict) else pdata
        if isinstance(scenario_input, dict):
            scenario_input = dict(scenario_input)
            calc_method = pdata.get("calc_method") if isinstance(pdata, dict) else None
            if calc_method:
                scenario_input["Calculation Method"] = calc_method
        input_scenarios_single = {
            scenario_name_input: {
                "__pdf_meta__": {
                    "scenario_name": scenario_name_input,
                    "scenario_type": "Scenario",
                    "calc_method": pdata.get("calc_method", "") if isinstance(pdata, dict) else "",
                    "input": scenario_input if isinstance(scenario_input, dict) else {},
                    "custom_lib": (scenario_input.get("_custom_lib_data") if isinstance(scenario_input, dict) else {}),
                }
            }
        }

        body_story.append(NextPageTemplate("portrait"))
        body_story.append(PageBreak())
        body_story.extend(
            build_scenario_input_pages(
                input_scenarios_single,
                page_counter=page_counter,
                include_title=False,
                styles=styles,
            )
        )

        # --- Flam results (landscape) ---
        if i < len(flam_items):
            fkey, fdata = flam_items[i]
            body_story.append(NextPageTemplate("landscape"))
            body_story.append(PageBreak())
            body_story.extend(
                _build_single_scenario_result_pages(
                    "Flam", i + 1, fkey, fdata, "flam_plot_fig", "flam",
                    page_counter, styles, tox_gas_labels, gas_data,
                )
            )

        # --- Tox results (landscape) ---
        if i < len(tox_items):
            tkey, tdata = tox_items[i]
            body_story.append(NextPageTemplate("landscape"))
            body_story.append(PageBreak())
            body_story.extend(
                _build_single_scenario_result_pages(
                    "Tox", i + 1, tkey, tdata, "tox_plot_fig", "tox",
                    page_counter, styles, tox_gas_labels, gas_data,
                )
            )

    contents_entries = get_contents_entries(page_counter)
    scenario_descriptions = []
    scenario_descriptions.extend(_extract_scenario_descriptions(flam_scenario_results, "Flam"))
    scenario_descriptions.extend(_extract_scenario_descriptions(tox_scenario_results, "Tox"))
    scenario_descriptions = list(dict.fromkeys(scenario_descriptions))

    title_story = _build_title_page_story(
        styles=styles,
        title=title,
        subtitle=subtitle,
        body_text=body_text,
        current_date=current_date,
        scenario_type_text=scenario_type_text,
        scenario_descriptions=scenario_descriptions,
        contents_entries=contents_entries,
    )

    doc = BaseDocTemplate(
        file_path,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    portrait_frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="portrait_frame",
    )

    landscape_width, landscape_height = landscape(A4)
    landscape_frame = Frame(
        20 * mm,
        20 * mm,
        landscape_width - 40 * mm,
        landscape_height - 40 * mm,
        id="landscape_frame",
    )

    def draw_title_page_footer(canv, _doc):
        canv.saveState()
        footer_y = 14 * mm
        canv.setStrokeColor(colors.lightgrey)
        canv.line(doc.leftMargin, footer_y + 5 * mm, A4[0] - doc.rightMargin, footer_y + 5 * mm)
        canv.setFont("Helvetica", 9)
        canv.setFillColor(colors.grey)
        canv.drawRightString(A4[0] - doc.rightMargin, footer_y, f"Generated on: {current_date}")
        canv.restoreState()

    def draw_shared_header_footer(canv, _doc):
        canv.saveState()
        page_w, page_h = canv._pagesize
        left_margin = 20 * mm
        right_margin = 20 * mm
        top_y = page_h - 12 * mm
        bottom_y = 12 * mm

        canv.setStrokeColor(colors.lightgrey)
        canv.line(left_margin, top_y, page_w - right_margin, top_y)
        canv.line(left_margin, bottom_y + 5 * mm, page_w - right_margin, bottom_y + 5 * mm)

        canv.setFont("Helvetica", 9)
        canv.setFillColor(colors.grey)
        canv.drawString(left_margin, top_y + 2 * mm, title)
        canv.drawRightString(page_w - right_margin, bottom_y, f"Page {canv.getPageNumber()}")
        canv.drawString(left_margin, bottom_y, f"Generated on: {current_date}")
        canv.restoreState()

    doc.addPageTemplates(
        [
            PageTemplate(id="title", frames=[portrait_frame], pagesize=A4, onPage=draw_title_page_footer),
            PageTemplate(id="portrait", frames=[portrait_frame], pagesize=A4, onPage=draw_shared_header_footer),
            PageTemplate(id="landscape", frames=[landscape_frame], pagesize=landscape(A4), onPage=draw_shared_header_footer),
        ]
    )

    final_story = list(title_story)
    if body_story:
        final_story.extend(body_story)

    doc.build(final_story)
    return file_path
                                  
