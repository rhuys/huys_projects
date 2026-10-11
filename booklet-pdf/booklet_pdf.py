#!/usr/bin/env python
"""
booklet-pdf.py:   simple file helper tools

** https://github.com/rhuys/pyhuys.git - Created by Roeland Huys, 2026 **

Create a booklet PDF from the input PDF, reordering pages for saddle stitching

USAGE:
    booklet-pdf.py [-h] input_pdf [margin_mm] [gutter_mm] [crop_mm]
    
    example:   python reorder_pdf.py <input_pdf> [margin_mm] [gutter_mm] [crop_mm]

ARGS
    -h    :  print help
    crop_mm   :  the amount to crop around each page (default: 0 mm)
    margin_mm :  the margin to apply around the output landscape pages (default: 1.0 mm)
    gutter_mm :  the inner space between the two pages on the output landscape pages (default: 0 mm)

OUTPUT
    Output filename will be <input_pdf>-formatted.pdf

DETAILS

input format: pdf with pages in normal order (1, 2, 3, 4, ...)
output format: pdf with pages in saddle stitch order (4, 1, 2, 3, 8, 5, 6, 7, ...)
after this, print the output PDF double-sided, flipping on the short edge
rotated pages will be rotated to portrait orientation, and cropped if needed.  The output PDF will be in A4 landscape format, with two portrait pages per landscape page.

"""

import sys
import pymupdf  # pip install pymupdf

mm = 72 / 25.4 # Conversion factor from mm to points (1 mm = 2.83465 points)

A4_width, A4_height = pymupdf.paper_size("A4")  # Get A4 dimensions in points

def reorder_for_saddle_stitch(doc):
    """Reorders pages for saddle stitching (e.g., 4-1-2-3, 8-5-6-7) directly on a fitz document."""
    total_pages = len(doc)
    reordered_doc = pymupdf.open()

    # Ensure the total pages are a multiple of 4
    remainder = total_pages % 4
    if remainder != 0:
        blank_pages_needed = 4 - remainder
        for _ in range(blank_pages_needed):
            reordered_doc.insert_pdf(doc, from_page=-1, to_page=-1)  # Add blank pages

    # Reorder pages: 4-1-2-3, 8-5-6-7, etc.
    reordered_indices = []
    for i in range(0, total_pages, 4):
        group = list(range(i, min(i + 4, total_pages)))
        if len(group) == 4:
            reordered_indices.extend([group[3], group[0], group[1], group[2]])
        else:
            reordered_indices.extend(group)  # Handle incomplete groups

    # Reorder the document
    for idx in reordered_indices:
        reordered_doc.insert_pdf(doc, from_page=idx, to_page=idx)

    return reordered_doc

def apply_crop(doc, crop_mm=0):
    """makes sure all pages are A4 portrait and applies cropping if needed"""
    output_doc = pymupdf.open()

    for i in range(len(doc)):
        page = doc[i]
        new_page = output_doc.new_page(width=A4_width, height=A4_height)  # Create a new A4 portrait page

        page.set_rotation(0)  # Reset rotation to 0 for consistent cropping

        rotate = -90 if page.rect.width > page.rect.height else 0

        clip_rect = pymupdf.Rect(
            page.rect[0] + crop_mm * mm, 
            page.rect[1] + crop_mm * mm, 
            page.rect[2] - crop_mm * mm, 
            page.rect[3] - crop_mm * mm)  # Crop the page if needed

        # Draw the original page content onto the new page with rotation
        new_page.show_pdf_page(
            pymupdf.Rect(0, 0, A4_width, A4_height),  # Destination rectangle (A4 portrait)
            docsrc = doc,
            pno = i,
            rotate = rotate,
            clip  = clip_rect
        )

    return output_doc

def compose_landscape_page(new_page, doc, left_page_index, right_page_index, margin_mm=0, gutter_mm=0):
    """Composes a new landscape page with two portrait pages side by side, applying margins and gutter."""

    # Calculate the rectangles for the left and right pages
    left_rect = pymupdf.Rect(
        margin_mm * mm,
        margin_mm * mm,
        new_page.rect.width / 2 - gutter_mm/2 * mm,
        new_page.rect.height - margin_mm * mm
    )
    right_rect = pymupdf.Rect(
        new_page.rect.width / 2  + gutter_mm/2 * mm,
        margin_mm * mm,
        new_page.rect.width  - margin_mm * mm,
        new_page.rect.height - margin_mm * mm
    )

    # Show the left page
    if left_page_index < len(doc):
        new_page.show_pdf_page(left_rect, doc, left_page_index)

    # Show the right page
    if right_page_index < len(doc):
        new_page.show_pdf_page(right_rect, doc, right_page_index)

def make_saddle_stitch(doc, margin_mm=0, gutter_mm=0):
    """Reorders pages for saddle stitching and applies zoom and gutter to a pymupdf document while preserving vector format."""

    output_doc = pymupdf.open()
    for i in range(0, len(doc), 4):  # page numbers

        # Create a new landscape page (A4 landscape) for the front side
        new_page = output_doc.new_page(width=A4_height, height=A4_width)
        compose_landscape_page(new_page, doc, i+3, i, margin_mm, gutter_mm)

        # Create a new landscape page (A4 landscape) for the rear side
        new_page = output_doc.new_page(width=A4_height, height=A4_width)
        compose_landscape_page(new_page, doc, i+1, i+2, margin_mm, gutter_mm)

    return output_doc
    

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_pdf = sys.argv[1]
    margin_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    gutter_mm = float(sys.argv[3]) if len(sys.argv) > 3 else 0
    crop_mm = float(sys.argv[4]) if len(sys.argv) > 4 else 0

    # Open the input PDF
    doc = pymupdf.open(input_pdf)

    # Step 1: Apply crop
    output_doc = apply_crop(doc, crop_mm)

    # Step 2: Reorder pages for saddle stitching
    output_doc = make_saddle_stitch(output_doc, margin_mm, gutter_mm)

    # Step 3: Apply zoom and gutter to the reordered PDF
   #soutput_doc = apply_margin_and_gutter(output_doc, margin_mm, gutter_mm)

    # Save the output PDF
    output_pdf = input_pdf.replace(".pdf", "-formatted.pdf")
    output_doc.save(output_pdf)
    print(f"Formatted PDF saved to {output_pdf}")
