#generate a pdf for the program
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate, SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
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

        flowables.append(Paragraph(f"Scenario Inputs: {html.escape(str(scenario_name))}", local_styles["Heading2"]))
        flowables.append(Spacer(1, 4 * mm))

        table_rows = [["Input Name", "Input Value"]]
        pairs = _input_pairs(input_values)
        if not pairs:
            table_rows.append(["No inputs provided", "-"])
        else:
            for input_name, input_value in pairs:
                table_rows.append([html.escape(input_name), html.escape(input_value)])

        inputs_table = Table(table_rows, colWidths=[70 * mm, None], repeatRows=1)
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

    # Match popup behaviour: Total Gas (ppm) is derived from v/v% columns if missing.
    peak_value_vv = 0.0
    if df_vv is not None and hasattr(df_vv, "columns") and hasattr(df_vv, "empty") and not df_vv.empty:
        if "Total Gas (ppm)" not in df_vv.columns:
            vv_cols = [col for col in list(df_vv.columns) if str(col).endswith("(v/v%)")]
            if vv_cols:
                df_vv["Total Gas (ppm)"] = df_vv[vv_cols].sum(axis=1)
            else:
                df_vv["Total Gas (ppm)"] = 0
        peak_value_vv = _as_float(df_vv["Total Gas (ppm)"].max(), 0.0)

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
        "Peak Total Gas (ppm)",
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


def _build_legend_table(legend_entries, available_width, styles):
    if not legend_entries:
        return None, 0

    local_styles = styles or getSampleStyleSheet()
    legend_count = len(legend_entries)
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

        for scenario_idx, (scenario_name, scenario_data) in enumerate(scenario_dict.items(), start=1):
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
                flowables.append(Spacer(1, 6 * mm))
            else:
                flowables.append(plot_image)

            legend_entries = _plot_legend_entries(fig)
            if legend_entries:
                legend_table, legend_height = _build_legend_table(legend_entries, usable_width, local_styles)
                current_plot_height = plot_image.drawHeight if plot_image is not None else 0
                text_block_height = 18 * mm
                spacer_height = max(4 * mm, content_height - text_block_height - current_plot_height - legend_height - (4 * mm))
                flowables.append(Spacer(1, spacer_height))
                flowables.append(Paragraph("Legend", local_styles["Heading3"]))
                flowables.append(legend_table)
            else:
                flowables.append(Spacer(1, max(4 * mm, content_height - (plot_image.drawHeight if plot_image is not None else 0) - (26 * mm))))

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

    story.append(Paragraph("Scenario Types Calculated", styles["Heading3"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"&bull; {html.escape(scenario_type_text)}", styles["BodyText"]))
    story.append(Spacer(1, 7 * mm))

    story.append(Paragraph("Title Contents", styles["Heading3"]))
    story.append(Spacer(1, 2 * mm))

    if contents_entries is None and page_counter is not None:
        contents_entries = get_contents_entries(page_counter)

    resolved_contents = []
    if contents_entries:
        for entry in contents_entries:
            if isinstance(entry, tuple) and len(entry) >= 2:
                entry_title = str(entry[0]).strip() or "Untitled"
                entry_page = entry[1]
                resolved_contents.append(f"{entry_title} .... {entry_page}")
            elif isinstance(entry, dict):
                entry_title = str(entry.get("title") or entry.get("name") or "Untitled")
                entry_page = entry.get("page")
                if entry_page is None:
                    resolved_contents.append(entry_title)
                else:
                    resolved_contents.append(f"{entry_title} .... {entry_page}")
            else:
                resolved_contents.append(str(entry))

    if resolved_contents:
        scenario_descriptions = resolved_contents

    if not scenario_descriptions:
        story.append(Paragraph("&bull; No scenarios were calculated.", styles["BodyText"]))
    else:
        if len(scenario_descriptions) > 24:
            columns = 3
        elif len(scenario_descriptions) > 12:
            columns = 2
        else:
            columns = 1

        col_values = [[] for _ in range(columns)]
        for idx, entry in enumerate(scenario_descriptions):
            col_values[idx % columns].append(entry)

        column_flowables = []
        for entries in col_values:
            flowables = []
            for entry in entries:
                flowables.append(Paragraph(f"&bull; {html.escape(entry)}", styles["BodyText"]))
                flowables.append(Spacer(1, 1.5 * mm))
            if not flowables:
                flowables.append(Paragraph(" ", styles["BodyText"]))
            column_flowables.append(flowables)

        col_width = doc.width / columns
        scenario_table = Table([column_flowables], colWidths=[col_width] * columns)
        scenario_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(scenario_table)

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

    story.append(Paragraph("Scenario Types Calculated", styles["Heading3"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"&bull; {html.escape(scenario_type_text)}", styles["BodyText"]))
    story.append(Spacer(1, 7 * mm))

    story.append(Paragraph("Title Contents", styles["Heading3"]))
    story.append(Spacer(1, 2 * mm))

    resolved_contents = []
    if contents_entries:
        for entry in contents_entries:
            if isinstance(entry, tuple) and len(entry) >= 2:
                entry_title = str(entry[0]).strip() or "Untitled"
                entry_page = entry[1]
                resolved_contents.append(f"{entry_title} .... {entry_page}")
            elif isinstance(entry, dict):
                entry_title = str(entry.get("title") or entry.get("name") or "Untitled")
                entry_page = entry.get("page")
                if entry_page is None:
                    resolved_contents.append(entry_title)
                else:
                    resolved_contents.append(f"{entry_title} .... {entry_page}")
            else:
                resolved_contents.append(str(entry))

    if resolved_contents:
        scenario_descriptions = resolved_contents

    if not scenario_descriptions:
        story.append(Paragraph("&bull; No scenarios were calculated.", styles["BodyText"]))
        return story

    if len(scenario_descriptions) > 24:
        columns = 3
    elif len(scenario_descriptions) > 12:
        columns = 2
    else:
        columns = 1

    col_values = [[] for _ in range(columns)]
    for idx, entry in enumerate(scenario_descriptions):
        col_values[idx % columns].append(entry)

    column_flowables = []
    for entries in col_values:
        flowables = []
        for entry in entries:
            flowables.append(Paragraph(f"&bull; {html.escape(entry)}", styles["BodyText"]))
            flowables.append(Spacer(1, 1.5 * mm))
        if not flowables:
            flowables.append(Paragraph(" ", styles["BodyText"]))
        column_flowables.append(flowables)

    # SimpleDocTemplate and BaseDocTemplate share the same width semantics.
    page_width = A4[0] - (20 * mm) - (20 * mm)
    col_width = page_width / columns
    scenario_table = Table([column_flowables], colWidths=[col_width] * columns)
    scenario_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(scenario_table)
    return story


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
    """Generate the final report: title page, scenario input pages, then plot+summary pages."""
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

    # Build page-count metadata for all pages after the title page.
    page_counter = create_page_counter(start_page=2)

    input_scenarios = {}
    if isinstance(flam_scenario_results, dict):
        for scenario_name, data in flam_scenario_results.items():
            scenario_input = data.get("input") if isinstance(data, dict) else data
            if isinstance(scenario_input, dict):
                scenario_input = dict(scenario_input)
                calc_method = data.get("calc_method") if isinstance(data, dict) else None
                if calc_method:
                    scenario_input["Calculation Method"] = calc_method
            input_scenarios[f"Flam - {scenario_name}"] = scenario_input
    if isinstance(tox_scenario_results, dict):
        for scenario_name, data in tox_scenario_results.items():
            scenario_input = data.get("input") if isinstance(data, dict) else data
            if isinstance(scenario_input, dict):
                scenario_input = dict(scenario_input)
                calc_method = data.get("calc_method") if isinstance(data, dict) else None
                if calc_method:
                    scenario_input["Calculation Method"] = calc_method
            input_scenarios[f"Tox - {scenario_name}"] = scenario_input

    input_pages_story = build_scenario_input_pages(
        input_scenarios,
        page_counter=page_counter,
        include_title=False,
        styles=styles,
    )

    plot_summary_story = build_landscape_plot_and_summary_pages(
        flam_scenario_results=flam_scenario_results,
        tox_scenario_results=tox_scenario_results,
        tox_gas_labels=tox_gas_labels,
        gas_data=gas_data,
        page_counter=page_counter,
        styles=styles,
        landscape_template_name="landscape",
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
    landscape_left_margin = 20 * mm
    landscape_right_margin = 20 * mm
    landscape_top_margin = 20 * mm
    landscape_bottom_margin = 20 * mm
    landscape_frame = Frame(
        landscape_left_margin,
        landscape_bottom_margin,
        landscape_width - landscape_left_margin - landscape_right_margin,
        landscape_height - landscape_top_margin - landscape_bottom_margin,
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

    final_story = []
    final_story.extend(title_story)

    has_more_pages = bool(input_pages_story or plot_summary_story)
    if has_more_pages:
        final_story.append(NextPageTemplate("portrait"))
        final_story.append(PageBreak())

    final_story.extend(input_pages_story)

    if plot_summary_story:
        if input_pages_story:
            final_story.append(NextPageTemplate("landscape"))
            final_story.append(PageBreak())
        else:
            # No input pages; switch directly from title to landscape for first scenario page.
            if has_more_pages:
                # Replace the template switch inserted before the first post-title page.
                if len(final_story) >= 2 and isinstance(final_story[-2], NextPageTemplate) and isinstance(final_story[-1], PageBreak):
                    final_story[-2] = NextPageTemplate("landscape")
            else:
                final_story.append(NextPageTemplate("landscape"))
        final_story.extend(plot_summary_story)

    doc.build(final_story)
    return file_path
                                  
