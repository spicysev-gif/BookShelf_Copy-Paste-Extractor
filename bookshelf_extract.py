#!/usr/bin/env python3
"""
bookshelf-extract.py
====================
Extract clean, readable text and PDFs from VitalSource Bookshelf HTML dumps.

How it works:
  1. Walks character-by-character through the raw HTML.
     A boolean flips to False on '<' and back to True on '>'.
     Only text OUTSIDE tags is collected.
  2. A second pass tracks structural tags (<h1>-<h6>, <table>, <tr>, <td>,
     <strong>, etc.) to format output with bold headers, two-column Q&A
     tables, and proper paragraph breaks.

Supports two modes:
  • Single section  – one HTML file → one .txt and/or one .pdf
  • Multi section   – one HTML file containing multiple <section> blocks
                      → one .txt/.pdf per section, auto-named by topic

Usage:
    # Single section
    python bookshelf-extract.py chapter16.txt
    python bookshelf-extract.py chapter16.txt --pdf
    python bookshelf-extract.py chapter16.txt --txt -o my_notes

    # Multi section (auto-splits on <section> tags)
    python bookshelf-extract.py combined.txt --split
    python bookshelf-extract.py combined.txt --split --pdf -o output_dir/

Requirements:
    pip install reportlab      (for PDF output)
"""

import argparse
import re
import sys
import os
import textwrap


# ════════════════════════════════════════════════════════════════════════
#  TAG-LEVEL PARSER
# ════════════════════════════════════════════════════════════════════════

def parse_html(raw: str):
    """
    Walk through raw HTML character by character.
    Returns a list of events:
        ('text', string)
        ('open', tag_name, attrs_string)
        ('close', tag_name)
    """
    events = []
    i = 0
    n = len(raw)
    buf = []

    while i < n:
        ch = raw[i]
        if ch == '<':
            if buf:
                events.append(('text', ''.join(buf)))
                buf = []
            tag_buf = []
            i += 1
            while i < n and raw[i] != '>':
                tag_buf.append(raw[i])
                i += 1
            tag_str = ''.join(tag_buf).strip()
            if tag_str.startswith('!') or tag_str.startswith('?'):
                # comment or processing instruction — skip
                pass
            elif tag_str.startswith('/'):
                tag_name = tag_str[1:].split()[0].lower().rstrip('/')
                events.append(('close', tag_name))
            elif tag_str.endswith('/'):
                tag_name = tag_str.rstrip('/').split()[0].lower()
                events.append(('open', tag_name, tag_str))
                events.append(('close', tag_name))
            else:
                parts = tag_str.split(None, 1)
                tag_name = parts[0].lower() if parts else ''
                attrs = parts[1] if len(parts) > 1 else ''
                events.append(('open', tag_name, attrs))
            i += 1  # skip '>'
        else:
            buf.append(ch)
            i += 1

    if buf:
        events.append(('text', ''.join(buf)))

    return events


# ════════════════════════════════════════════════════════════════════════
#  STRUCTURAL FORMATTER
# ════════════════════════════════════════════════════════════════════════

HEADER_TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
SKIP_TAGS = {
    'script', 'style', 'iframe', 'noscript', 'svg',
    'mosaic-highlight-indicator', 'mosaic-plugin-image-tools',
    'template',
}
HEADER_CLASSES = {
    'unt2', 'untmt3', 'nbxmh1', 'nbxmh2', 'nbxmh3',
    'clinic-head2', 'clinic-head', 'h4', 'h5', 'h6',
    'video', 'box-title',
}


def _attrs_contain_header_class(attrs_str: str) -> bool:
    m = re.search(r'class\s*=\s*["\']([^"\']*)["\']', attrs_str, re.I)
    if not m:
        return False
    classes = m.group(1).lower().split()
    return bool(set(classes) & HEADER_CLASSES)


def _clean(text: str) -> str:
    """Collapse whitespace, strip, decode common HTML entities."""
    text = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    for old, new in [
        ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
        ('&nbsp;', ' '), ('&#160;', ' '),
        ('&mdash;', '—'), ('&ndash;', '–'),
        ('&rsquo;', '\u2019'), ('&lsquo;', '\u2018'),
        ('&rdquo;', '\u201d'), ('&ldquo;', '\u201c'),
        ('&hellip;', '…'), ('&bull;', '•'),
        ('&times;', '×'), ('&rarr;', '→'),
    ]:
        text = text.replace(old, new)
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def build_lines(events):
    """
    Walk parsed events and produce structured output lines.
    Each line is a dict with keys:
        text       (str or None)
        bold       (bool)
        table_row  (bool)
        cells      (list[str] or None)
    """
    lines = []
    skip_depth = 0
    in_bold = False
    in_header = False
    in_table = False
    current_row_cells = None
    cell_buf = []
    text_buf = []
    header_via_class = False

    def flush_text():
        nonlocal text_buf
        t = _clean(' '.join(text_buf))
        text_buf = []
        if t:
            lines.append({
                'text': t,
                'bold': in_bold or in_header or header_via_class,
                'table_row': False,
                'cells': None,
            })

    def flush_cell():
        nonlocal cell_buf
        t = _clean(' '.join(cell_buf))
        cell_buf = []
        return t

    for ev in events:
        if ev[0] == 'open':
            tag = ev[1]
            attrs = ev[2] if len(ev) > 2 else ''

            if tag in SKIP_TAGS:
                skip_depth += 1
                continue
            if skip_depth > 0:
                continue

            if tag in HEADER_TAGS:
                flush_text()
                in_header = True
            elif tag in ('strong', 'b'):
                in_bold = True
            elif tag == 'table':
                flush_text()
                in_table = True
            elif tag == 'tr':
                current_row_cells = []
                cell_buf = []
            elif tag in ('td', 'th'):
                cell_buf = []
            elif tag == 'p':
                if _attrs_contain_header_class(attrs):
                    header_via_class = True
            elif tag == 'br':
                if in_table and current_row_cells is not None:
                    cell_buf.append(' ')
                else:
                    text_buf.append(' ')

        elif ev[0] == 'close':
            tag = ev[1]

            if tag in SKIP_TAGS:
                skip_depth = max(0, skip_depth - 1)
                continue
            if skip_depth > 0:
                continue

            if tag in HEADER_TAGS:
                flush_text()
                in_header = False
            elif tag in ('strong', 'b'):
                in_bold = False
            elif tag == 'table':
                in_table = False
            elif tag == 'tr':
                if current_row_cells is not None:
                    last = flush_cell()
                    if last:
                        current_row_cells.append(last)
                    if any(c for c in current_row_cells):
                        lines.append({
                            'text': None,
                            'bold': False,
                            'table_row': True,
                            'cells': current_row_cells,
                        })
                current_row_cells = None
            elif tag in ('td', 'th'):
                if current_row_cells is not None:
                    current_row_cells.append(flush_cell())
            elif tag == 'p':
                if in_table and current_row_cells is not None:
                    cell_buf.append(' ')
                else:
                    flush_text()
                header_via_class = False

        elif ev[0] == 'text':
            if skip_depth > 0:
                continue
            txt = ev[1]
            if in_table and current_row_cells is not None:
                cell_buf.append(txt)
            else:
                text_buf.append(txt)

    flush_text()
    return lines


# ════════════════════════════════════════════════════════════════════════
#  OUTPUT FORMATTERS
# ════════════════════════════════════════════════════════════════════════

def format_txt(lines, col_width=80):
    """Produce a plain-text string from parsed lines."""
    out = []
    for line in lines:
        if line['table_row']:
            cells = line['cells']
            if len(cells) == 1:
                out.append('')
                out.append(f"** {cells[0]} **")
                out.append('')
            elif len(cells) == 2:
                left, right = cells[0], cells[1]
                lw = col_width // 2 - 2
                left_lines = textwrap.wrap(left, width=lw) or ['']
                right_lines = textwrap.wrap(right, width=lw) or ['']
                max_h = max(len(left_lines), len(right_lines))
                left_lines += [''] * (max_h - len(left_lines))
                right_lines += [''] * (max_h - len(right_lines))
                for ll, rl in zip(left_lines, right_lines):
                    out.append(f"  {ll:<{lw}}  |  {rl}")
                out.append('-' * col_width)
            else:
                out.append('  |  '.join(c for c in cells))
                out.append('-' * col_width)
        else:
            text = line['text']
            if line['bold']:
                out.append('')
                out.append(f"** {text} **")
                out.append('')
            else:
                out.append(textwrap.fill(text, width=col_width))

    result = '\n'.join(out)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip() + '\n'


def format_pdf(lines, output_path):
    """Produce a formatted PDF from parsed lines using ReportLab."""
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    bold_style = ParagraphStyle(
        'BoldHeader', parent=styles['Heading3'],
        spaceAfter=4, spaceBefore=10,
    )
    body_style = ParagraphStyle(
        'BodyText2', parent=styles['Normal'],
        spaceAfter=4, fontSize=9, leading=12,
    )
    cell_style = ParagraphStyle(
        'CellText', parent=styles['Normal'],
        fontSize=8, leading=10, spaceAfter=2,
    )

    story = []
    table_buf = []

    def flush_table():
        nonlocal table_buf
        if not table_buf:
            return
        page_width = letter[0] - 1.5 * inch
        ncols = max(len(row) for row in table_buf)
        col_widths = [page_width / ncols] * ncols

        data = []
        for row_cells in table_buf:
            if len(row_cells) == 1:
                data.append(
                    [Paragraph(f'<b>{row_cells[0]}</b>', cell_style)]
                    + [''] * (ncols - 1)
                )
            else:
                padded = row_cells + [''] * (ncols - len(row_cells))
                data.append([Paragraph(c, cell_style) for c in padded[:ncols]])

        t = Table(data, colWidths=col_widths, repeatRows=0)
        cmds = [
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]
        for ri, row_cells in enumerate(table_buf):
            if len(row_cells) == 1:
                cmds.append(('SPAN', (0, ri), (ncols - 1, ri)))
                cmds.append(('BACKGROUND', (0, ri), (-1, ri),
                             colors.Color(0.92, 0.92, 0.92)))
        t.setStyle(TableStyle(cmds))
        story.append(t)
        story.append(Spacer(1, 8))
        table_buf = []

    for line in lines:
        if line['table_row']:
            table_buf.append(line['cells'])
        else:
            flush_table()
            text = line['text']
            if line['bold']:
                story.append(Paragraph(f'<b>{text}</b>', bold_style))
            else:
                story.append(Paragraph(text, body_style))

    flush_table()
    doc.build(story)


# ════════════════════════════════════════════════════════════════════════
#  SECTION SPLITTER
# ════════════════════════════════════════════════════════════════════════

def _guess_section_name(html: str, index: int) -> str:
    """Try to derive a filename-friendly name from the first heading or paragraph."""
    # Try <h4> or <h5> text
    m = re.search(r'<h[45][^>]*>([^<]+)</h[45]>', html[:2000])
    if m:
        name = m.group(1).strip()
    else:
        # Fall back to first meaningful paragraph text
        m = re.search(r'<p[^>]*>([^<]{10,80})', html[:3000])
        name = m.group(1).strip() if m else f"section_{index}"

    # Identify the body system from surrounding text
    sample = html[:5000].lower()
    system = ""
    for keyword, label in [
        ('musculoskeletal', 'Musculoskeletal'),
        ('neurologic', 'Neurologic'),
        ('female genitali', 'Female_Genitalia'),
        ('male genitali', 'Male_Genitalia'),
        ('heart', 'Heart'),
        ('lung', 'Lung'),
        ('abdomen', 'Abdomen'),
        ('skin', 'Skin'),
        ('head and neck', 'Head_Neck'),
        ('breast', 'Breast'),
        ('ear', 'Ear'),
        ('eye', 'Eye'),
        ('nose', 'Nose'),
        ('peripheral vascular', 'Peripheral_Vascular'),
    ]:
        if keyword in sample:
            system = label
            break

    # Build filename
    if 'analyzing data' in name.lower() or 'clinical judgment' in name.lower():
        suffix = 'Clinical_Judgments'
    elif 'health assessment' in name.lower():
        suffix = 'Health_Assessment'
    else:
        suffix = re.sub(r'[^\w\s-]', '', name)
        suffix = re.sub(r'\s+', '_', suffix)[:50]

    if system:
        return f"{system}_{suffix}"
    return suffix or f"section_{index}"


def split_sections(raw: str):
    """Split an HTML file on <section> boundaries. Returns list of (name, html)."""
    parts = re.split(r'(?=<section[^>]*>)', raw)
    parts = [p for p in parts if p.strip()]

    # First part is often a <body> preamble with no real content
    if parts and not re.match(r'\s*<section', parts[0]):
        preamble = parts.pop(0)
        # If preamble has real content (tables, paragraphs), keep it
        if '<td' in preamble or '<p ' in preamble:
            parts.insert(0, preamble)

    sections = []
    for i, part in enumerate(parts):
        name = _guess_section_name(part, i + 1)
        sections.append((name, part))

    return sections


# ════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════

def process_one(html: str, base: str, do_txt: bool, do_pdf: bool):
    """Parse and write output for a single chunk of HTML."""
    events = parse_html(html)
    lines = build_lines(events)

    results = []
    if do_txt:
        txt_path = base + '.txt'
        txt = format_txt(lines)
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(txt)
        results.append(('txt', txt_path, len(txt)))

    if do_pdf:
        pdf_path = base + '.pdf'
        format_pdf(lines, pdf_path)
        results.append(('pdf', pdf_path, os.path.getsize(pdf_path)))

    return len(lines), results


def main():
    parser = argparse.ArgumentParser(
        description='Extract clean text/PDF from VitalSource Bookshelf HTML dumps')
    parser.add_argument('input', help='Path to the HTML/text file')
    parser.add_argument('-o', '--output',
                        help='Output base name (single mode) or directory (split mode)')
    parser.add_argument('--txt', action='store_true', help='Output .txt only')
    parser.add_argument('--pdf', action='store_true', help='Output .pdf only')
    parser.add_argument('--split', action='store_true',
                        help='Split on <section> tags and produce one output per section')

    args = parser.parse_args()
    input_path = args.input

    do_txt = True
    do_pdf = True
    if args.txt and not args.pdf:
        do_pdf = False
    if args.pdf and not args.txt:
        do_txt = False

    with open(input_path, 'r', encoding='utf-8-sig') as f:
        raw = f.read()

    if args.split:
        # ── Multi-section mode ──
        out_dir = args.output or os.path.splitext(input_path)[0] + '_sections'
        os.makedirs(out_dir, exist_ok=True)

        sections = split_sections(raw)
        print(f"Found {len(sections)} section(s) in {input_path}\n")

        for name, html in sections:
            base = os.path.join(out_dir, name)
            n_blocks, results = process_one(html, base, do_txt, do_pdf)
            for fmt, path, size in results:
                print(f"  [{fmt}] {os.path.basename(path)}  "
                      f"({n_blocks} blocks, {size:,} {'chars' if fmt == 'txt' else 'bytes'})")
        print(f"\nAll outputs in: {out_dir}/")

    else:
        # ── Single-section mode ──
        base = args.output or os.path.splitext(input_path)[0]
        n_blocks, results = process_one(raw, base, do_txt, do_pdf)
        print(f"Parsed {n_blocks} content blocks from {input_path}")
        for fmt, path, size in results:
            print(f"  Wrote {path}  "
                  f"({size:,} {'chars' if fmt == 'txt' else 'bytes'})")


if __name__ == '__main__':
    main()