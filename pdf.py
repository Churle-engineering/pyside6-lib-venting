#generate a pdf for the program
from turtle import pd
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, A4
from reportlab.platypus import Image, SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Frame, PageTemplate, FrameBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib.units import cm, mm
from datetime import datetime
from PySide6.QtWidgets import QFileDialog, QMessageBox
from information import GAS_LABEL_FIX
import math
import re
import time
import gc
import matplotlib.pyplot as plt
import numpy as np



def portrait_footer(fig, page_num, current_date):
    # Create a drawing for the footer
    footer = Drawing(fig.bbox.width, 50)
    
    # Add a rectangle for the footer background
    footer.add(Rect(0, 0, fig.bbox.width, 50, fillColor=colors.lightgrey))
    
    # Add page number and date text
    footer.add(Paragraph(f"Page {page_num}", getSampleStyleSheet()['Normal']))
    footer.add(Paragraph(f"Generated on: {current_date}", getSampleStyleSheet()['Normal']))
    page_counter[0] += 1  # Increment the page number for the next page
    step += 1  # count events for progress bar
    
    return footer

def landscape_footer(fig, page_num, current_date):
    # Create a drawing for the footer
    footer = Drawing(fig.bbox.width, 50)
    
    # Add a rectangle for the footer background
    footer.add(Rect(0, 0, fig.bbox.width, 50, fillColor=colors.lightgrey))
    
    # Add page number and date text
    footer.add(Paragraph(f"Page {page_num}", getSampleStyleSheet()['Normal']))
    footer.add(Paragraph(f"Generated on: {current_date}", getSampleStyleSheet()['Normal']))
    
    return footer

def pdf_results(tox_scenario_results=None, flam_scenario_results=None,title ="Battery Off-gas Assessment Results"):
    
    current_date = datetime.now().strftime(" %d %B %Y ")
    #create variable filename
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"{now_str} Offgas_Assessment_Report.pdf"
    page_counter = [1]  # mutable container to track page numbers
    file_path = QFileDialog.getSaveFileName(None, "Save PDF Report", filename, "PDF Files (*.pdf)")[0]
    if not file_path:
        QMessageBox.warning(None, "Save PDF Report", "No file selected. PDF report was not saved.")
        return  # User cancelled the save dialog
    
    with open(file_path, 'wb') as f:
        # --- generate title page ---
        portrait_doc = SimpleDocTemplate(f, pagesize=A4, rightMargin=72*mm, leftMargin=72*mm, topMargin=72*mm, bottomMargin=72*mm)
        styles = getSampleStyleSheet()
        page_w, page_h = A4
        margin = 2 * cm
        
        usable_w = page_w - 2 * margin
        half_h = (page_h - 2 * margin) / 2  # each frame gets half the usable height

        top_frame = Frame(margin, margin + half_h, usable_w, half_h, id='top_frame', showBoundary=0)
        bottom_frame = Frame(margin, margin, usable_w, half_h, id='bottom_frame', showBoundary=0)
        
        arup_logo_path = "arup_logo.png"  # Ensure this path is correct
        try:
            logo = Image(arup_logo_path, width=100, height=50)  # Adjust size as needed
        except:
            logo = Paragraph("ARUP ", styles['Normal'])
        title_paragraph = Paragraph(title, styles['Title'])
        portrait_doc.build([logo, Spacer(1, 12), title_paragraph], onFirstPage=lambda canvas, doc: canvas.setPageTemplates([PageTemplate(id='TwoCol', frames=[top_frame, bottom_frame])]))
        
        contents = []
        
        # build trhe story
        story = []
        
        # top frame
        
        if contents:
            story.append(Paragraph("Report Contents", styles['Heading2']))
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph("<br/>".join(contents), styles['Normal']))
        else:
            story.append(Paragraph("No results available to display.", styles['Normal']))
                                                                              
        story.append(FrameBreak())
                                  
                                  
        # bottom frame: list of scenarios

        scenarios = set()
        if tox_scenario_results:
            scenarios.update(tox_scenario_results.keys())
        if flam_scenario_results:
            scenarios.update(flam_scenario_results.keys())

        scenario_list = sorted(scenarios)

        if scenario_list:
            story.append(Paragraph("Scenarios to be included in the report:", styles['Heading2']))
            story.append(Spacer(1, 0.4 * cm))

            # Split into two balanced columns (col 1 fills first, col 2 gets the remainder)
            n = len(scenario_list)
            half = (n + 1) // 2
            col1 = scenario_list[:half]
            col2 = scenario_list[half:]
            while len(col2) < len(col1):
                col2.append("")

            rows = [
                [Paragraph(f"• {a}", styles['Normal']),
                Paragraph(f"• {b}" if b else "", styles['Normal'])]
                for a, b in zip(col1, col2)
            ]

            col_w = usable_w / 2
            table = Table(rows, colWidths=[col_w, col_w])
            table.setStyle(TableStyle([
                ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
                ('TOPPADDING',    (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                # ('GRID', (0,0), (-1,-1), 0.25, colors.grey),  # debug
            ]))
            story.append(table)

        portrait_doc.build(story)
        export_input_data_pages(flam_scenario_results, tox_scenario_results, pdf, page_counter, current_date)

        # tox tables
        if tox_scenario_results:
            for scenario_name in scenario_list(tox_scenario_results.keys()):
                result = tox_scenario_results.get(scenario_name)
                if not result:
                    continue  # Skip if no result for this scenario
                
            fig = result.get("tox_plot_fig")
            if fig:
                # Save the figure to a temporary file
                temp_fig_path = f"temp_tox_plot_{scenario_name}.png"
                fig.savefig(temp_fig_path, bbox_inches='tight')
                plt.close(fig)  # Close the figure to free memory

                # Add the figure to the PDF
                pdf.drawImage(temp_fig_path, x=50, y=400, width=500, height=300)  # Adjust position and size as needed
                pdf.showPage()  # Move to the next page
        
            tox_vv_df = result.get("tox_vv_df")
            headers = result.get("tox_summary_headers", [])
            row_data = result.get("tox_summary_row_data", [])
            input_data = result.get("input", {})
            scenario_desc = input_data.get("Scenario Description", "")
            
            if headers and row_data:
                export_summary_table_to_pdf(
                headers, row_data,
                f"Toxicity Summary {scenario_name}: {scenario_desc}",
                pdf, page_counter, current_date
            )
                
            if isinstance(tox_vv_df, pd.DataFrame) and not tox_vv_df.empty:
                export_dataframe_table(
                    tox_vv_df,
                    f"Toxicity (ppm) {scenario_name}: {scenario_desc}",
                    pdf, page_counter, current_date
                )
        #  flammability tables
        if flam_scenario_results:
            for scenario_name in scenario_list(flam_scenario_results.keys()):
                result = flam_scenario_results.get(scenario_name)
                if not result:
                    continue  # Skip if no result for this scenario
                
                fig = result.get("flam_plot_fig")
                if fig:
                    # Save the figure to a temporary file
                    temp_fig_path = f"temp_flam_plot_{scenario_name}.png"
                    fig.savefig(temp_fig_path, bbox_inches='tight')
                    plt.close(fig)  # Close the figure to free memory

                    # Add the figure to the PDF
                    pdf.drawImage(temp_fig_path, x=50, y=400, width=500, height=300)  # Adjust position and size as needed
                    pdf.showPage()  # Move to the next page
                
                flam_vv_df = result.get("flam_vv_df")
                headers = result.get("flam_summary_headers", [])
                row_data = result.get("flam_summary_row_data", [])
                input_data = result.get("input", {})
                scenario_desc = input_data.get("Scenario Description", "")
                
                if headers and row_data:
                    export_summary_table_to_pdf(
                        headers, row_data,
                        f"Flammability Summary {scenario_name}: {scenario_desc}",
                        pdf, page_counter, current_date
                    )
                
                if isinstance(flam_vv_df, pd.DataFrame) and not flam_vv_df.empty:
                    export_dataframe_table(
                        flam_vv_df,
                        f"Flammability (ppm) {scenario_name}: {scenario_desc}",
                        pdf, page_counter, current_date
                    )
                
        QMessageBox.information(None, "PDF Report Generated", f"PDF report has been successfully generated and saved to:\n{file_path}")
        
def export_input_data_pages(flam_scenario_results, tox_scenario_results, pdf, page_counter, current_date):
    
    scenarios = set()
    if tox_scenario_results:
        scenarios.update(tox_scenario_results.keys())
    if flam_scenario_results:
        scenarios.update(flam_scenario_results.keys())
    
    for scenario_name in sorted(scenarios):
        
        result = None
        if tox_scenario_results and scenario_name in tox_scenario_results:
            result = tox_scenario_results[scenario_name]
        elif flam_scenario_results and scenario_name in flam_scenario_results:
            result = flam_scenario_results[scenario_name]
        
        if not result:
            continue  # Skip if no result for this scenario
        
        input_data = result.get("input", {})
        scenario_desc = input_data.get("Scenario Description", "")
        items = input_data.items()
        
        table_data = []
        for key, value in items:
            key_norm = key.lower().replace("_", " ").title().capitalize()
            heading = GAS_LABEL_FIX.get(key_norm, key_norm)
            
            if isinstance(value, str) and "\n" in value:
                lines = value.split("\n")
                value = lines[0] + "\n" + "\n".join("    " + line for line in lines[1:])
            table_data.append([heading, str(value)])

        # Replace underscores in column headings
        col_headers = ["Input", "Value"]

        # Create figure
        fig, ax = plt.subplots(figsize=(8, 11))  # A4 portrait
        ax.axis('off')
        fig.suptitle(f"Input Data for {scenario_name}: {scenario_desc}", fontsize=14, fontname='Arial', weight='bold', y=0.94)

        # Build table
        table = Table(table_data, colWidths=[3.5 * cm, 3.5 * cm], hAlign='LEFT')

        # Table formatting            
        table.auto_set_font_size(False)
        table.setFont(QFont("Arial", 8))
        table.scale(1, 1)

        for (row, col), cell in table.get_celld().items():
            if row == 0:
                cell.set_text_props(weight='bold')
                cell.set_facecolor("#D3D3D3")  # Light grey
            else:
                cell.set_facecolor("white")
            cell.set_height(0.05)
            cell.set_edgecolor('grey')
            
        portrait_page_footer(fig, page_counter[0], current_date)
        # Save to PDF
        pdf.savefig(fig)
        plt.close(fig)

    gc.collect()
                

            
def export_dataframe_table(df, title, pdf, page_counter, current_date, rows_per_page=29):

    total_rows = df.shape[0]
    total_pages = (total_rows // rows_per_page) + int(total_rows % rows_per_page != 0)

    for i in range(total_pages):
        chunk_start = i * rows_per_page
        chunk_end = (i + 1) * rows_per_page
        chunk = df.iloc[chunk_start:chunk_end].copy()  # Explicit copy for safety

        # Format the 'time' column (case-insensitive) to show integers - in place
        time_cols = [col for col in chunk.columns if col.strip().lower() == "time (s)"]
        if time_cols:
            chunk[time_cols[0]] = chunk[time_cols[0]].astype(int)

        fig, ax = plt.subplots(figsize=(10.5, 11), dpi=100)
        fig.subplots_adjust(top=0.94, bottom=0.06)
        ax.axis("off")
        ax.set_title(f"{title} (Page {i+1} of {total_pages})", fontsize=15, weight='bold', pad=12)

        min_col_width = 12
        
        # Optimized column width calculation using vectorization
        col_lens = chunk.astype(str).apply(lambda x: x.str.len().max(), axis=0).values
        header_lens = np.array([len(str(col)) for col in chunk.columns])
        col_widths = np.maximum(np.maximum(col_lens, header_lens), min_col_width)
        
        # Give extra width to "Total Gas (ppm)" column to fit header text
        for idx, col in enumerate(chunk.columns):
            if "Total Gas" in col and "ppm" in col:
                col_widths[idx] = col_widths[idx] * 1.35  # 35% wider
        
        col_widths = col_widths / col_widths.sum()  # Normalize

        # Create table with improved sizing
        table = ax.table(
            cellText=chunk.round(4).values,
            colLabels=[GAS_LABEL_FIX.get(col.lower().replace(' ', '\n').replace('(v/v%)', '').replace(' (ppm)', '').replace('(mg/L)', '').strip(),col) 
            for col in df.columns],
            loc='center',
            cellLoc='center',
            bbox=[0.0, 0.01, 1.0, 0.99],
            colWidths=col_widths.tolist()
            )

        table.auto_set_font_size(False)
        table.set_fontsize(9)  # Increased from 8
        table.scale(2, 2.4)  # Increased scaling for better fit

        # Style header cells with larger font
        for col_idx in range(len(df.columns)):
            cell = table[(0, col_idx)]
            cell.set_fontsize(10)  # Larger header font
            cell.set_text_props(weight='bold', wrap=True)
            cell.set_facecolor("#D3D3D3")
        
        # Ensure all data cells have proper height
        for row_idx in range(1, len(chunk) + 1):
            for col_idx in range(len(df.columns)):
                cell = table[(row_idx, col_idx)]
                cell.set_height(0.06)  # Increased cell height

        add_footer(fig, page_counter[0], current_date)
        pdf.savefig(fig)
        plt.close(fig)
        page_counter[0] += 1
        if page_counter[0] % 20 == 0:  # Reduced gc frequency
            gc.collect()

def export_summary_table_to_pdf(headers, values, title, pdf, page_counter, current_date, max_columns_per_chunk=8, chunks_per_row=1, chunks_per_col=6):

    total_columns = len(headers)
    total_chunks = math.ceil(total_columns / max_columns_per_chunk)
    chunks_per_page = chunks_per_row * chunks_per_col
    total_pages = math.ceil(total_chunks / chunks_per_page)

    chunk_index = 0

    for page in range(total_pages):
        fig, axes = plt.subplots(chunks_per_col, chunks_per_row, figsize=(11, 8.5))
        fig.subplots_adjust(top=0.88)  # Match title spacing
        fig.suptitle(f"{title} (Page {page+1} of {total_pages})", fontsize=14, weight='bold')

        # Normalize axes to 2D
        if chunks_per_col == 1:
            axes = [axes]
        if chunks_per_row == 1:
            axes = [[ax] for ax in axes]

        for r in range(chunks_per_col):
            for c in range(chunks_per_row):
                if chunk_index >= total_chunks:
                    axes[r][c].axis("off")
                    continue

                col_start = chunk_index * max_columns_per_chunk
                col_end = min((chunk_index + 1) * max_columns_per_chunk, total_columns)

                sub_headers = headers[col_start:col_end]
                sub_values = values[col_start:col_end]

                ax = axes[r][c]
                ax.axis("off")

                col_widths = [len(str(header)) for header in sub_headers]
                total = sum(col_widths)
                col_widths = [w / total for w in col_widths]

                table = ax.table(
                    cellText=[sub_values],
                    colLabels=sub_headers,
                    loc="center",
                    cellLoc="center",
                    bbox=[0.02, 0.02, 0.95, 0.95],
                    colWidths=col_widths
                )
                table.auto_set_font_size(False)
                table.set_fontsize(8)
                table.scale(1.2, 1.8)

                # Style header row
                for col_idx in range(len(sub_headers)):
                    cell = table[(0, col_idx)]  # header cell
                    cell.set_fontsize(8)
                    cell.set_text_props(weight='bold')
                    cell.set_facecolor("#D3D3D3")

                chunk_index += 1

        plt.tight_layout(rect=[0, 0, 1, 0.96])
        landscape_footer(fig, page_counter[0], current_date)
        pdf.savefig(fig)
        plt.close(fig)
        page_counter[0] += 1
        if page_counter[0] % 20 == 0:  # Reduced gc frequency
            gc.collect()            
        
        
        
