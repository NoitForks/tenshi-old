#!/usr/bin/env python

from __future__ import print_function
import eagle_util_funcs
import os
import os.path
import subprocess
import sys
import shutil

try:
    import csv
    from reportlab.lib.pagesizes import LETTER, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, Table, TableStyle
    from reportlab.platypus import SimpleDocTemplate
    import reportlab.lib.colors

    reportlab_available = True
except ImportError:
    reportlab_available = False


def hint_word_wrap(dat):
    """
    If the BOM sheets are generated without word-wrapping cells, they would be
    wider than a page.

    By default, reportlab only word wraps around spaces. However, some fields
    use underscores or dashes as separators. (e.g. WIRE_WITH_HOLE)

    This hack inserts spaces throughout the fields to force them to word wrap.
    """
    segments = dat.split(" ")
    i = 0
    while i < len(segments):
        seg = segments[i]
        if len(seg) < 15:
            i += 1
            continue

        try:
            before, after = seg.split("-", 1)
            if len(before) < 15:
                segments[i] = before + "-"
                segments.insert(i + 1, after)
                i += 1
                continue
        except ValueError:
            pass

        try:
            before, after = seg.split("_", 1)
            if len(before) < 15:
                segments[i] = before + "_"
                segments.insert(i + 1, after)
                i += 1
                continue
        except ValueError:
            pass

        i += 1

    return " ".join(segments)


def get_table_data(csv_name):
    """
    Read a CSV file, and convert it to an array of reportlab Paragraphs.
    The Paragraphs make sure the cells can word wrap.
    """

    with open(csv_name, "r") as csvfile:
        reader = csv.reader(csvfile)
        data = list(reader)

    # Small fonts are required for the table width to not exceed the page width
    styles = getSampleStyleSheet()
    text_style = styles["Normal"]
    text_style.fontSize = 6

    header_row = [[Paragraph("<b><u>" + x + "</u></b>", text_style)
                   for x in data[0]]]
    other_rows = [[Paragraph(hint_word_wrap(x), text_style) for x in y]
                  for y in data[1:]]

    return header_row + other_rows


def gen_bom_pdf(csv_name, pdf_name):
    """
    Render a CSV file to PDF
    """
    doc = SimpleDocTemplate(pdf_name,
                            pagesize=landscape(LETTER),
                            # Use minimum printable margins
                            rightMargin=4,
                            leftMargin=4,
                            topMargin=4,
                            bottomMargin=4)
    data = get_table_data(csv_name)
    table_style = TableStyle([
        # Shade alternating rows with a light grey background
        ['ROWBACKGROUNDS', (0, 0), (-1, -1), [reportlab.lib.colors.lightgrey,
                                              reportlab.lib.colors.white]]
    ])
    # Render and write the PDF file to disk
    doc.build([Table(data, style=table_style)])


def run_script(file_name, script_name):
    ret = eagle_util_funcs.run_eagle([
        file_name,
        '-S' + script_name,
        ]
        )

    if ret != 0:
        print("Eagle returned error!")
        sys.exit(ret)


def copy_and_replace(src, dst, pattern, replacement):
    with open(src) as src_file:
        with open(dst, "w") as dst_file:
            dst_file.write(src_file.read().replace(pattern, replacement))


def compile_pdf(inputs, output):
    ret = subprocess.call(["pdftk"] + inputs + [
        "cat",
        "output",
        output
        ]
        )

    if ret != 0:
        print("pdftk returned error!")
        sys.exit(ret)


def main():
    # TODO(kzentner): accept four arguments
    if len(sys.argv) < 3:
        # TODO(kzentner): change signature ta have CSV as last arg
        print("Usage: %s in.sch|in.brd out.pdf" % (sys.argv[0]))
        sys.exit(1)

    scr_dir = os.path.abspath(os.path.dirname(sys.argv[0]))

    base_name = os.path.splitext(os.path.abspath(sys.argv[1]))[0]
    out_name = os.path.join(os.getcwd(), os.path.abspath(sys.argv[2]))

    sch_name = os.path.join(os.getcwd(), base_name + ".sch")
    brd_name = os.path.join(os.getcwd(), base_name + ".brd")

    if reportlab_available:
        # TODO(kzentner): accept the csv path as an argument instead
        csv_name = os.path.join(
            os.path.abspath("../../build/artifacts/boards"),
            base_name.split("/")[-1] + ".csv")
        have_csv = os.path.isfile(csv_name)
    else:
        have_csv = False

    have_sch = os.path.isfile(sch_name)
    have_brd = os.path.isfile(brd_name)

    # Start xvfb
    xvfb, display_num = eagle_util_funcs.start_xvfb()

    # Create temporary directory
    tmp_dir = eagle_util_funcs.setup_tmp_dir()

    # Copy scripts to the temporary directory
    # Eagle's default location for saving exported images is unrelated to the
    # current working directory, so the scripts must be modified to hardcode
    # the output file paths
    copy_and_replace(os.path.join(scr_dir, "docu-packet-schematic.scr"),
                     os.path.join(tmp_dir, "schematic.scr"),
                     "%PATH%",
                     tmp_dir)
    copy_and_replace(os.path.join(scr_dir, "docu-packet-board.scr"),
                     os.path.join(tmp_dir, "board.scr"),
                     "%PATH%",
                     tmp_dir)

    inputs = []

    # Generate schematic image
    if have_sch:
        dst_sch_name = os.path.join(tmp_dir, "file.sch")
        shutil.copy(sch_name, dst_sch_name)
        run_script(dst_sch_name, "schematic.scr")
        os.remove(dst_sch_name)
        inputs.append(os.path.join(tmp_dir, "schematic.pdf"))

    # Generate board images
    if have_brd:
        dst_brd_name = os.path.join(tmp_dir, "file.brd")
        shutil.copy(brd_name, dst_brd_name)
        run_script(dst_brd_name, "board.scr")
        os.remove(dst_brd_name)
        inputs.append(os.path.join(tmp_dir, "top.pdf"))
        inputs.append(os.path.join(tmp_dir, "bottom.pdf"))

    # Generate bill of materials
    if have_csv:
        gen_bom_pdf(csv_name, os.path.join(tmp_dir, "bom.pdf"))
        inputs.append(os.path.join(tmp_dir, "bom.pdf"))

    # Compile final pdf
    compile_pdf(inputs, out_name)

    # Clean up
    eagle_util_funcs.remove_tmp_dir(tmp_dir)
    eagle_util_funcs.kill_xvfb(xvfb)

if __name__ == '__main__':
    main()
