"""PDF report generation for the LIB off-gassing calculation results.

``export_lib_report_pdf`` is wired to the LIBPage "Export PDF Report" button. It
collects every scenario that has a stored calculation result, asks the user for
report metadata and which scenarios to include, then writes a report with:

1. an intro page (Arup logo top right, title, metadata, assumptions),
2. a contents page whose page numbers are resolved by reportlab's multi-pass
   ``TableOfContents`` build, so they stay accurate however long the report gets, and
3. for each scenario, in study-tree order: an inputs page, then for the flammable
   and (where present) toxic results a landscape plot page followed by a portrait
   summary-data page.

Figures are rebuilt offscreen with matplotlib's Agg backend straight from the same
``ResultSummary`` the on-screen plot tabs use, so the report matches the UI.
"""

import html
import os
from dataclasses import fields
from datetime import datetime
from io import BytesIO

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, Image,
    ListFlowable, ListItem, NextPageTemplate, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

from information import CHEMICAL_PROPERTIES


def _register_report_fonts():
    """Register Times New Roman (body/level-1 headings) and Arial (level-2 headings,
    table captions) from the Windows fonts folder, falling back to the built-in
    Times/Helvetica families if the TTFs cannot be loaded."""
    fonts_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")
    families = {
        "Times": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
        "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    }
    for family, files in families.items():
        try:
            paths = [os.path.join(fonts_dir, name) for name in files]
            if not all(os.path.exists(path) for path in paths):
                raise IOError(f"missing font files: {files}")
            regular, bold, italic, bold_italic = (f"{family}{suffix}" for suffix in
                                                  ("", "-Bold", "-Italic", "-BoldItalic"))
            for font_name, path in zip((regular, bold, italic, bold_italic), paths):
                pdfmetrics.registerFont(TTFont(font_name, path))
            pdfmetrics.registerFontFamily(family, normal=regular, bold=bold,
                                          italic=italic, boldItalic=bold_italic)
        except Exception:
            fallback = {"Times": "Times-Roman", "Arial": "Helvetica"}[family]
            globals()[f"FONT_{family.upper()}"] = fallback
            globals()[f"FONT_{family.upper()}_BOLD"] = (
                "Times-Bold" if family == "Times" else "Helvetica-Bold")
            globals()[f"FONT_{family.upper()}_ITALIC"] = (
                "Times-Italic" if family == "Times" else "Helvetica-Oblique")
        else:
            globals()[f"FONT_{family.upper()}"] = family
            globals()[f"FONT_{family.upper()}_BOLD"] = f"{family}-Bold"
            globals()[f"FONT_{family.upper()}_ITALIC"] = f"{family}-Italic"


_register_report_fonts()
FONT_BODY = FONT_TIMES
FONT_BODY_BOLD = FONT_TIMES_BOLD
FONT_BODY_ITALIC = FONT_TIMES_ITALIC
FONT_HEADING2 = FONT_ARIAL
FONT_HEADING2_BOLD = FONT_ARIAL_BOLD
FONT_CAPTION = FONT_ARIAL

_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arup_logo.png")

_MARGIN = 18 * mm
_ARUP_RED = colors.HexColor("#E61E28")   # sampled from arup_logo.png
_GRID = colors.black
_ROW_ALT = colors.HexColor("#f4e1e2")
_FOOTER_TEXT = colors.black

_ASSUMPTIONS = [
    "Off-gas volumes are determined from UL9540A cell or module test data, module "
    "capacity using literature specific-capacity values (L/kWh), or an imported "
    "measured module flowrate profile, according to each scenario's calculation method.",
    "Thermal runaway propagation between cells and between modules is represented by "
    "the user-specified propagation delays and propagation batch sizes; a single "
    "cell's release curve is derived from empirical venting data.",
    "The battery room is modelled as one well-mixed volume: released gas is assumed "
    "to distribute instantaneously and uniformly, and is diluted by the room "
    "ventilation rate.",
    "An optional emergency ventilation rate activates while the room's carbon "
    "monoxide concentration is at or above the user-specified percentage of CO's "
    "lower flammability limit. Both ventilation rates are specified per square "
    "metre of room floor area.",
    "Gas composition is taken from literature data, UL9540A flammability data, or a "
    "user-defined composition. Some species contribute to both the flammable and "
    "the toxic totals.",
    "Flammable results are assessed against the battery lower flammability limit "
    "(LFL); optionally a Le Chatelier mixture LFL is used, optionally adjusted for "
    "the venting temperature.",
    "Toxic species are assessed against their ERPG-3 values.",
    "Concentrations are reported in v/v %; mg/L values are derived from the species "
    "densities.",
]

_DISCLAIMER = (
    "These calculations are based on empirical correlations drawn from 60 "
    "peer-reviewed papers covering 470 LIB experiments. They are founded on certain "
    "assumptions and have inherent limitations. The results may or may not have "
    "reasonable predictive capabilities for a given situation and should only be "
    "interpreted by an informed user. There is no absolute guarantee of the accuracy "
    "of these calculations."
)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

_STYLES = getSampleStyleSheet()
_STYLES.add(ParagraphStyle(
    "ReportTitle", fontName=FONT_BODY_BOLD, fontSize=24, leading=30,
    textColor=_ARUP_RED, spaceAfter=4))
_STYLES.add(ParagraphStyle(
    "IntroSub", fontName=FONT_BODY, fontSize=11, leading=16,
    textColor=colors.HexColor("#333333")))
_STYLES.add(ParagraphStyle(
    "IntroHeading", fontName=FONT_BODY_BOLD, fontSize=13, leading=17,
    textColor=_ARUP_RED, spaceBefore=14, spaceAfter=6))
_STYLES.add(ParagraphStyle(
    "IntroBody", fontName=FONT_BODY, fontSize=10, leading=15))
_STYLES.add(ParagraphStyle(
    "ScenarioHeading", fontName=FONT_BODY_BOLD, fontSize=17, leading=21,
    textColor=_ARUP_RED, spaceAfter=4))
_STYLES.add(ParagraphStyle(
    "ScenarioMeta", fontName=FONT_BODY_ITALIC, fontSize=9, leading=12,
    textColor=_FOOTER_TEXT, spaceAfter=8))
_STYLES.add(ParagraphStyle(
    "SectionHeading", fontName=FONT_HEADING2_BOLD, fontSize=13.5, leading=17,
    textColor=_ARUP_RED, spaceAfter=8))
_STYLES.add(ParagraphStyle(
    "ContentsTitle", fontName=FONT_BODY_BOLD, fontSize=17, leading=21,
    textColor=_ARUP_RED, spaceAfter=10))
_STYLES.add(ParagraphStyle(
    "GroupMarker", fontName=FONT_BODY, fontSize=1, leading=1,
    textColor=colors.white))
_STYLES.add(ParagraphStyle(
    "TableSection", fontName=FONT_CAPTION, fontSize=10.5, leading=13,
    textColor=_ARUP_RED, spaceBefore=10, spaceAfter=4))
_STYLES.add(ParagraphStyle(
    "TableHeader", fontName=FONT_HEADING2_BOLD, fontSize=7.5, leading=9.5,
    textColor=colors.white))
_STYLES.add(ParagraphStyle(
    "Disclaimer", fontName=FONT_BODY_BOLD, fontSize=9, leading=13,
    textColor=_ARUP_RED))

# Paragraph style name -> TOC level. Only these styles register contents entries.
_TOC_LEVELS = {"GroupMarker": 0, "ScenarioHeading": 1, "SectionHeading": 2}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _fmt(value, digits=4):
    """Compact number formatting for table cells."""
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == 0:
        return "0"
    return f"{number:,.{digits}g}"


def _header_cell(text):
    return Paragraph(html.escape(text), _STYLES["TableHeader"])


def _table(rows, col_widths, header=True, font_size=7.5):
    """A black-gridded table with an Arup-red header row and alternating row shading."""
    table = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), FONT_BODY),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), _ARUP_RED),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
        ]
    table.setStyle(TableStyle(commands))
    return table


def _dataclass_rows(instance):
    """[Parameter, Value, Units] rows straight from a dataclass's field metadata."""
    rows = [[_header_cell("Parameter"), _header_cell("Value"), _header_cell("Units")]]
    for f in fields(instance):
        meta = f.metadata or {}
        label = meta.get("label", f.name)
        units = meta.get("units", "")
        value = getattr(instance, f.name)
        if isinstance(value, bool):
            text, units = ("Yes" if value else "No"), ""
        elif isinstance(value, float):
            text = _fmt(value)
        else:
            text = str(value)
        if units in ("string", "bool"):
            units = ""
        rows.append([label, text, units])
    return rows


def _species_col_widths(n_cols, total_width, first=70):
    rest = (total_width - first) / (n_cols - 1)
    return [first] + [rest] * (n_cols - 1)


# ---------------------------------------------------------------------------
# Figures (offscreen Agg renderings mirroring the on-screen result tabs)
# ---------------------------------------------------------------------------

def _new_figure(title):
    fig = Figure(figsize=(11.4, 6.2))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.set_title(title)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Concentration (v/v %)")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    return fig, ax


def _set_ylim_from_curves(ax, curves):
    """Scale the y-axis to the largest actual data curve, ignoring flat threshold
    lines so small curves stay visible even when a threshold value is much bigger."""
    finite_values = [np.asarray(curve, dtype=float) for curve in curves]
    finite_values = [values[np.isfinite(values)] for values in finite_values]
    finite_values = [values for values in finite_values if values.size]
    y_max = max((float(values.max()) for values in finite_values), default=0.0)
    ax.set_ylim(0.0, y_max * 1.05 if y_max > 0 else 1.0)


def _flammable_figure(summary):
    fig, ax = _new_figure(f"{summary.scenario_name}: Flammable Gas Concentration")
    curves = [summary.flammable_total_vv]
    ax.plot(summary.time, summary.flammable_total_vv,
            color="black", linewidth=2, label="Total Flammable")
    ax.plot(summary.time, summary.lfl_curve,
            color="darkred", linestyle=":", linewidth=1.5, label="Assessment LFL")
    for species in summary.flammable_species:
        (line,) = ax.plot(summary.time, species.conc_vv, label=species.species.upper())
        curves.append(species.conc_vv)
        lfl = CHEMICAL_PROPERTIES[species.species].get("lfl")
        if lfl is not None:
            ax.plot([summary.time[0], summary.time[-1]], [lfl, lfl],
                    color=line.get_color(), linestyle="--", linewidth=1,
                    label=f"{species.species.upper()} LFL")
    _set_ylim_from_curves(ax, curves)
    ax.legend(loc="upper right", fontsize=7, ncol=2)
    fig.tight_layout()
    return fig


def _toxic_figure(summary):
    fig, ax = _new_figure(f"{summary.scenario_name}: Toxic Gas Concentration")
    curves = []
    for species in summary.toxic_species:
        (line,) = ax.plot(summary.time, species.conc_vv, label=species.species.upper())
        curves.append(species.conc_vv)
        if species.erpg_3:
            ax.plot([summary.time[0], summary.time[-1]],
                    [species.erpg_3 / 10000.0, species.erpg_3 / 10000.0],
                    color=line.get_color(), linestyle="--", linewidth=1,
                    label=f"{species.species.upper()} ERPG-3")
    _set_ylim_from_curves(ax, curves)
    ax.legend(loc="upper right", fontsize=7, ncol=2)
    fig.tight_layout()
    return fig


def _figure_image(fig, max_width, max_height):
    """Render a Figure to a reportlab Image scaled to fit the given box."""
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=200)
    buffer.seek(0)
    pixel_w, pixel_h = ImageReader(buffer).getSize()
    scale = min(max_width / pixel_w, max_height / pixel_h)
    buffer.seek(0)
    return Image(buffer, width=pixel_w * scale, height=pixel_h * scale)


# ---------------------------------------------------------------------------
# Document template: intro / portrait / landscape pages + TOC notification
# ---------------------------------------------------------------------------

class LIBReportDoc(BaseDocTemplate):
    """Draws the page furniture and notifies the TOC whenever a heading is laid out."""

    def __init__(self, filename, metadata, logo_path=_LOGO_PATH):
        super().__init__(
            filename, pagesize=A4,
            leftMargin=_MARGIN, rightMargin=_MARGIN,
            topMargin=_MARGIN, bottomMargin=_MARGIN,
            title="LIB Off-gassing Assessment Report",
            author=metadata.get("author") or "",
        )
        self.metadata = metadata
        self.logo_path = logo_path

        portrait_frame = Frame(
            _MARGIN, _MARGIN, A4[0] - 2 * _MARGIN, A4[1] - 2 * _MARGIN, id="portrait")
        intro_frame = Frame(
            _MARGIN, _MARGIN, A4[0] - 2 * _MARGIN, A4[1] - 2 * _MARGIN - 24 * mm,
            id="intro")
        landscape_frame = Frame(
            _MARGIN, _MARGIN, landscape(A4)[0] - 2 * _MARGIN,
            landscape(A4)[1] - 2 * _MARGIN, id="landscape")

        self.addPageTemplates([
            PageTemplate(id="Intro", frames=[intro_frame], pagesize=A4,
                         onPage=self._on_intro_page),
            PageTemplate(id="Portrait", frames=[portrait_frame], pagesize=A4,
                         onPage=self._on_content_page),
            PageTemplate(id="Landscape", frames=[landscape_frame],
                         pagesize=landscape(A4), onPage=self._on_content_page),
        ])

    def afterFlowable(self, flowable):
        """Register TOC entries for the heading styles as they are laid out."""
        if not isinstance(flowable, Paragraph):
            return
        level = _TOC_LEVELS.get(flowable.style.name)
        if level is None:
            return
        text = getattr(flowable, "_toc_text", None) or flowable.getPlainText()
        self.notify("TOCEntry", (level, text, self.page))

    # -- page furniture -----------------------------------------------------

    def _draw_logo(self, canvas):
        if not self.logo_path or not os.path.exists(self.logo_path):
            return
        image = ImageReader(self.logo_path)
        img_w, img_h = image.getSize()
        height = 11.2 * mm
        width = img_w * (height / img_h)
        canvas.drawImage(image, A4[0] - _MARGIN - width, A4[1] - 12 * mm - height,
                         width=width, height=height, mask="auto")

    def _on_intro_page(self, canvas, doc):
        canvas.saveState()
        self._draw_logo(canvas)
        canvas.restoreState()

    def _on_content_page(self, canvas, doc):
        width, _height = self.pageTemplate.pagesize or self.pagesize
        canvas.saveState()
        canvas.setFont(FONT_BODY, 8)
        canvas.setFillColor(_FOOTER_TEXT)
        left = "  |  ".join(part for part in (
            self.metadata.get("project"),
            f"Job {self.metadata['job']}" if self.metadata.get("job") else "",
            self.metadata.get("author"),
            datetime.now().strftime("%d %b %Y"),
        ) if part)
        canvas.drawString(_MARGIN, _MARGIN - 7.5 * mm, left)
        canvas.drawRightString(width - _MARGIN, _MARGIN - 7.5 * mm, f"Page {doc.page}")
        canvas.restoreState()


# ---------------------------------------------------------------------------
# Story construction
# ---------------------------------------------------------------------------

def _make_toc():
    toc = TableOfContents()
    toc.dotsMinLevel = 0
    toc.levelStyles = [
        ParagraphStyle("TOCGroup", fontName=FONT_HEADING2_BOLD, fontSize=11,
                       leading=15, spaceBefore=8, leftIndent=0, firstLineIndent=0),
        ParagraphStyle("TOCScenario", fontName=FONT_BODY_BOLD, fontSize=10,
                       leading=13, spaceBefore=4, leftIndent=14, firstLineIndent=0),
        ParagraphStyle("TOCSection", fontName=FONT_BODY, fontSize=9.5,
                       leading=12, leftIndent=28, firstLineIndent=0),
    ]
    return toc


def _toc_heading(text, style_name, toc_text=None):
    paragraph = Paragraph(html.escape(text), _STYLES[style_name])
    if toc_text is not None:
        paragraph._toc_text = toc_text
    return paragraph


def _group_marker(group_name):
    """Invisible 1pt paragraph that only exists to register a group in the TOC."""
    return _toc_heading("&nbsp;", "GroupMarker", toc_text=group_name)


def _add_intro(story, metadata):
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("LIB Off-gassing Assessment Report", _STYLES["ReportTitle"]))
    story.append(Paragraph(
        "Lithium-ion battery thermal runaway off-gassing: room gas dispersion, "
        "flammability and toxicity assessment", _STYLES["IntroSub"]))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=_ARUP_RED))
    story.append(Spacer(1, 5 * mm))

    meta_rows = []
    if metadata.get("project"):
        meta_rows.append(["Project", metadata["project"]])
    if metadata.get("job"):
        meta_rows.append(["Job Number", metadata["job"]])
    if metadata.get("author"):
        meta_rows.append(["Author", metadata["author"]])
    meta_rows.append(["Date", datetime.now().strftime("%d %B %Y")])
    meta_rows.append(["Generated By", "LIB Off-gassing Calculation Tool"])
    story.append(_table(meta_rows, [110, 260], header=False, font_size=9.5))

    story.append(Paragraph("Methodology and Assumptions", _STYLES["IntroHeading"]))
    story.append(Paragraph(
        "This report presents the inputs and results of lithium-ion battery (LIB) "
        "thermal runaway off-gassing calculations. For each scenario the released "
        "gas is tracked in the room over time and the resulting flammable and toxic "
        "concentrations are compared with their respective assessment criteria. "
        "The following assumptions apply to every scenario in this report:",
        _STYLES["IntroBody"]))
    story.append(Spacer(1, 2 * mm))
    story.append(ListFlowable(
        [ListItem(Paragraph(html.escape(item), _STYLES["IntroBody"]), leftIndent=14)
         for item in _ASSUMPTIONS],
        bulletType="bullet", bulletFontSize=7))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(html.escape(_DISCLAIMER), _STYLES["Disclaimer"]))


def _add_inputs_page(story, scenario, result, portrait_w):
    group = (scenario.group or "").strip()
    if group:
        story.append(_group_marker(group))
    story.append(_toc_heading(result.scenario_name or scenario.name, "ScenarioHeading"))
    story.append(Paragraph(
        f"Group: {html.escape(group) or '-'} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Calculation method: {html.escape(result.calc_method)}",
        _STYLES["ScenarioMeta"]))
    story.append(Paragraph("Scenario Inputs", _STYLES["TableSection"]))
    story.append(_table(_dataclass_rows(result.inputs), [200, 160, portrait_w - 360]))

    # the battery spec snapshotted at run time, so the report matches what was computed
    spec = result.lib_spec if result.lib_spec is not None else scenario.lib_spec
    if spec is not None:
        story.append(Paragraph("Battery (LIB) Specification", _STYLES["TableSection"]))
        story.append(_table(_dataclass_rows(spec),
                            [200, 160, portrait_w - 360]))

    composition = scenario.gas_composition
    if composition is not None and composition.percentages:
        rows = [[_header_cell("Species"), _header_cell("Share of Off-gas (%)")]]
        for species, share in composition.percentages.items():
            if share and share > 0:
                rows.append([species.upper(), _fmt(share)])
        if len(rows) > 1:
            story.append(Paragraph(html.escape(f"Gas Composition: {composition.name}"),
                                   _STYLES["TableSection"]))
            story.append(_table(rows, [200, 160]))


def _flammable_key_rows(result, summary):
    rows = [[_header_cell("Metric"), _header_cell("Value")]]
    rows.append(["Peak total flammable concentration",
                 f"{_fmt(summary.peak_flammable_vv)} v/v%  "
                 f"({_fmt(summary.peak_flammable_mgl)} mg/L, "
                 f"{_fmt(summary.peak_flammable_ppm)} ppm)"])
    rows.append(["Time of peak", f"{_fmt(summary.peak_flammable_time)} s"])
    if summary.lfl_percent:
        rows.append([f"Assessment LFL ({summary.lfl_label})",
                     f"{_fmt(summary.lfl_percent)} v/v%"])
        rows.append(["Peak as % of LFL", f"{_fmt(summary.peak_percent_of_lfl)} %"])
        crossing = summary.lfl_crossing_time
        rows.append(["Time to reach LFL",
                     f"{crossing:.0f} s" if crossing is not None else "Not reached"])
    if result.total_gas_m3.size:
        rows.append(["Total gas released", f"{_fmt(float(result.total_gas_m3[-1]))} m3"])
    if result.active_cells.size:
        rows.append(["Cells vented (final)", _fmt(float(result.active_cells[-1]))])
    if result.active_modules.size:
        rows.append(["Modules vented (final)", _fmt(float(result.active_modules[-1]))])
    return rows


def _flammable_species_rows(summary):
    rows = [[_header_cell(text) for text in
             ("Species", "Peak (v/v%)", "Peak (mg/L)", "Peak (ppm)",
              "Time of Peak (s)", "LFL (v/v%)")]]
    for species in summary.flammable_species:
        lfl = CHEMICAL_PROPERTIES[species.species].get("lfl")
        rows.append([species.species.upper(), _fmt(species.peak_vv),
                     _fmt(species.peak_mgl), _fmt(species.peak_ppm),
                     _fmt(species.peak_time), _fmt(lfl)])
    return rows


def _toxic_species_rows(summary):
    rows = [[_header_cell(text) for text in
             ("Species", "Peak (v/v%)", "Peak (mg/L)", "Peak (ppm)",
              "Time of Peak (s)", "ERPG-3 (ppm)", "% of ERPG-3")]]
    for species in summary.toxic_species:
        rows.append([species.species.upper(), _fmt(species.peak_vv),
                     _fmt(species.peak_mgl), _fmt(species.peak_ppm),
                     _fmt(species.peak_time), _fmt(species.erpg_3),
                     _fmt(species.percent_of_erpg_3)])
    return rows


def build_lib_report(path, entries, metadata, logo_path=_LOGO_PATH):
    """Write the PDF report to ``path``.

    ``entries`` is a list of ``(scenario, ScenarioResult, ResultSummary)`` triples in
    report order; ``metadata`` holds the optional project/job/author strings for the
    intro page and footer. Page numbers in the contents are resolved by ``multiBuild``.
    """
    doc = LIBReportDoc(path, metadata, logo_path)
    portrait_w = A4[0] - 2 * _MARGIN
    landscape_w = landscape(A4)[0] - 2 * _MARGIN
    landscape_h = landscape(A4)[1] - 2 * _MARGIN

    story = []
    _add_intro(story, metadata)
    story.append(NextPageTemplate("Portrait"))
    story.append(PageBreak())
    story.append(Paragraph("Contents", _STYLES["ContentsTitle"]))
    story.append(_make_toc())

    for scenario, result, summary in entries:
        name = result.scenario_name or scenario.name

        # Inputs page (portrait)
        story.append(NextPageTemplate("Portrait"))
        story.append(PageBreak())
        _add_inputs_page(story, scenario, result, portrait_w)

        # Flammable plot page (landscape) then summary page (portrait)
        story.append(NextPageTemplate("Landscape"))
        story.append(PageBreak())
        story.append(_toc_heading(f"{name} — Flammable Gas Concentration",
                                  "SectionHeading", toc_text="Flammable gas — plot"))
        story.append(_figure_image(_flammable_figure(summary),
                                   landscape_w, landscape_h - 40))
        story.append(NextPageTemplate("Portrait"))
        story.append(PageBreak())
        story.append(_toc_heading(f"{name} — Flammable Results Summary",
                                  "SectionHeading",
                                  toc_text="Flammable gas — results summary"))
        story.append(_table(_flammable_key_rows(result, summary),
                            [220, portrait_w - 220]))
        if summary.flammable_species:
            story.append(Spacer(1, 8))
            story.append(_table(_flammable_species_rows(summary),
                                _species_col_widths(6, portrait_w)))

        # Toxic plot page (landscape) then summary page (portrait)
        if summary.toxic_species:
            story.append(NextPageTemplate("Landscape"))
            story.append(PageBreak())
            story.append(_toc_heading(f"{name} — Toxic Gas Concentration",
                                      "SectionHeading", toc_text="Toxic gas — plot"))
            story.append(_figure_image(_toxic_figure(summary),
                                       landscape_w, landscape_h - 40))
            story.append(NextPageTemplate("Portrait"))
            story.append(PageBreak())
            story.append(_toc_heading(f"{name} — Toxic Results Summary",
                                      "SectionHeading",
                                      toc_text="Toxic gas — results summary"))
            story.append(_table(_toxic_species_rows(summary),
                                _species_col_widths(7, portrait_w)))

    doc.multiBuild(story)
    return path


# ---------------------------------------------------------------------------
# Export dialog + entry point wired to the LIBPage button
# ---------------------------------------------------------------------------

class ReportExportDialog(QDialog):
    """Collects optional report metadata and which scenarios to include."""

    def __init__(self, parent, entries):
        super().__init__(parent)
        self.setWindowTitle("Export PDF Report")
        layout = QVBoxLayout(self)

        meta_group = QGroupBox("Report Metadata (optional)")
        form = QFormLayout(meta_group)
        self.project_edit = QLineEdit()
        self.job_edit = QLineEdit()
        self.author_edit = QLineEdit()
        form.addRow("Project Name:", self.project_edit)
        form.addRow("Job Number:", self.job_edit)
        form.addRow("Author:", self.author_edit)
        layout.addWidget(meta_group)

        scenario_group = QGroupBox("Scenarios to Include")
        scenario_layout = QVBoxLayout(scenario_group)
        select_row = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_none = QPushButton("Select None")
        select_all.clicked.connect(lambda: self._set_all(True))
        select_none.clicked.connect(lambda: self._set_all(False))
        select_row.addWidget(select_all)
        select_row.addWidget(select_none)
        select_row.addStretch()
        scenario_layout.addLayout(select_row)

        check_container = QWidget()
        check_layout = QVBoxLayout(check_container)
        check_layout.setContentsMargins(0, 0, 0, 0)
        self._checks = []
        for scenario, result, _summary in entries:
            name = result.scenario_name or scenario.name
            checkbox = QCheckBox(f"{name}   ({result.calc_method})")
            checkbox.setChecked(True)
            check_layout.addWidget(checkbox)
            self._checks.append((scenario.node_id, checkbox))
        check_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(check_container)
        scroll.setMaximumHeight(180)
        scenario_layout.addWidget(scroll)
        layout.addWidget(scenario_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(460, 400)

    def _set_all(self, checked):
        for _, checkbox in self._checks:
            checkbox.setChecked(checked)

    def _on_accept(self):
        if not self.selected_node_ids():
            QMessageBox.information(self, "Export PDF Report",
                                    "Select at least one scenario to include.")
            return
        self.accept()

    def selected_node_ids(self):
        return {node_id for node_id, checkbox in self._checks if checkbox.isChecked()}

    def metadata(self):
        return {
            "project": self.project_edit.text().strip(),
            "job": self.job_edit.text().strip(),
            "author": self.author_edit.text().strip(),
        }


def export_lib_report_pdf(lib_page, ordered_scenarios):
    """Handler for the LIBPage "Export PDF Report" button.

    ``ordered_scenarios`` is the store's scenarios in study-tree order (supplied by
    the page, which owns the tree); only those with stored results are offered.
    """
    entries = []
    for scenario in ordered_scenarios:
        if scenario.result is not None and scenario.summary is not None:
            entries.append((scenario, scenario.result, scenario.summary))

    if not entries:
        QMessageBox.information(lib_page, "Export PDF Report",
                                "No calculation results to export. Run a calculation first.")
        return

    dialog = ReportExportDialog(lib_page, entries)
    if dialog.exec() != QDialog.Accepted:
        return

    selected_ids = dialog.selected_node_ids()
    selected_entries = [entry for entry in entries if entry[0].node_id in selected_ids]

    default_name = f"LIB_Offgassing_Report_{datetime.now():%Y%m%d}.pdf"
    path, _ = QFileDialog.getSaveFileName(
        lib_page, "Save PDF Report", default_name, "PDF Files (*.pdf)")
    if not path:
        return

    try:
        build_lib_report(path, selected_entries, dialog.metadata())
    except Exception as exc:
        QMessageBox.critical(lib_page, "Export PDF Report",
                             f"Failed to generate the report:\n{exc}")
        return
    QMessageBox.information(lib_page, "Export PDF Report",
                            f"Report written to:\n{path}")


