import re
from io import BytesIO
from datetime import date, timedelta

import fitz
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Spacer,
    Paragraph,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT


st.set_page_config(
    page_title="Escogido Pitch Report",
    page_icon="⚾",
    layout="wide"
)

# ---------- BRAND / PDF STYLING ----------
NAVY = colors.HexColor("#0D2E57")
RED = colors.HexColor("#C62839")
MID_BLUE = colors.HexColor("#1E4C7A")
LIGHT_BLUE = colors.HexColor("#EAF1F8")
VERY_LIGHT = colors.HexColor("#F7F9FC")
GRID = colors.HexColor("#D7DFEA")
TEXT = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#5B6777")
WHITE = colors.white

A3_LANDSCAPE = (16.54 * inch, 11.69 * inch)

styles = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle(
    "TitleStyle",
    parent=styles["Title"],
    fontName="Helvetica-Bold",
    fontSize=18,
    leading=20,
    textColor=NAVY,
    alignment=TA_LEFT,
    spaceAfter=4,
)
SUBTITLE_STYLE = ParagraphStyle(
    "SubtitleStyle",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=10,
    leading=12,
    textColor=MUTED,
    alignment=TA_LEFT,
    spaceAfter=6,
)
SECTION_STYLE = ParagraphStyle(
    "SectionStyle",
    parent=styles["Heading3"],
    fontName="Helvetica-Bold",
    fontSize=9,
    leading=11,
    textColor=WHITE,
    alignment=TA_LEFT,
)
FOOT_STYLE = ParagraphStyle(
    "FootStyle",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=7,
    textColor=MUTED,
    alignment=TA_RIGHT,
)

# ---------- SOURCE PDF TABLE REGIONS ----------
# Coordinates match the original TrackMan style export.
SECTIONS = [
    {
        "name": "Fastball in Zone",
        "type": "main",
        "rect": (68, 42, 392, 334),
    },
    {
        "name": "Fastball Chase % Below the Zone",
        "type": "chase",
        "rect": (430, 42, 566, 334),
    },
    {
        "name": "Fastballs Up & In vs Righties",
        "type": "main",
        "rect": (68, 382, 392, 565),
    },
    {
        "name": "All Pitches Chase % Below the Zone",
        "type": "chase",
        "rect": (430, 392, 566, 578),
    },
    {
        "name": "Fastballs Up & In vs Lefties",
        "type": "main",
        "rect": (68, 580, 392, 708),
    },
]

MAIN_COLS = [
    "Player","K","K Looking #","P","CallStrk#","CallStrike%","Miss#","Miss %",
    "Foul#","FoulP%","Total","Total%","BIP","BIP %","1B","2B","3B","HR","TB","BABIP","SLG"
]
CHASE_COLS = ["Player", "Chase%", "P", "Chase#"]

# ---------- HELPERS ----------
def norm_space(s):
    return re.sub(r"\s+", " ", s or "").strip()

def cluster_rows(words, y_threshold=3.5):
    """
    Group words into rows based on vertical position.
    """
    if not words:
        return []

    words_sorted = sorted(words, key=lambda w: (round(w[3], 1), w[0]))
    rows = []
    current = [words_sorted[0]]
    current_y = words_sorted[0][3]

    for w in words_sorted[1:]:
        y = w[3]
        if abs(y - current_y) <= y_threshold:
            current.append(w)
            current_y = (current_y + y) / 2
        else:
            rows.append(sorted(current, key=lambda x: x[0]))
            current = [w]
            current_y = y
    rows.append(sorted(current, key=lambda x: x[0]))
    return rows

def row_text(words_row):
    return " ".join(w[4] for w in words_row)

def split_player_and_numbers(text, expected_numeric_count):
    """
    Split a row into player name + expected numeric/stat tokens.
    Works even when player names have spaces/accents.
    """
    tokens = text.split()
    if len(tokens) <= expected_numeric_count:
        return None
    player = " ".join(tokens[:-expected_numeric_count])
    nums = tokens[-expected_numeric_count:]
    if not player:
        return None
    return [player] + nums

def extract_words_from_rect(page, rect):
    sx = page.rect.width / 612
    sy = page.rect.height / 792
    scaled = fitz.Rect(rect[0]*sx, rect[1]*sy, rect[2]*sx, rect[3]*sy)
    return page.get_text("words", clip=scaled)

def parse_main_section(page, rect):
    words = extract_words_from_rect(page, rect)
    rows = cluster_rows(words, y_threshold=3.2)
    parsed = []

    for r in rows:
        text = norm_space(row_text(r))
        low = text.lower()

        if not text:
            continue
        if low in {"calculations", "results"}:
            continue
        if low.startswith("player k"):
            continue
        if low.startswith("total ") or text == "TOTAL":
            split = split_player_and_numbers(text, 20)
            if split:
                parsed.append(split)
            continue

        candidate = split_player_and_numbers(text, 20)
        if candidate:
            parsed.append(candidate)

    # keep rows that look like real records
    clean = []
    for row in parsed:
        if len(row) == 21:
            clean.append(row)

    return clean

def parse_chase_section(page, rect):
    words = extract_words_from_rect(page, rect)
    rows = cluster_rows(words, y_threshold=3.0)
    parsed = []

    for r in rows:
        text = norm_space(row_text(r))
        low = text.lower()

        if not text:
            continue
        if low in {"calculations", "results"}:
            continue
        if low.startswith("player chase%") or low.startswith("player chase"):
            continue

        candidate = split_player_and_numbers(text, 3)
        if candidate and len(candidate) == 4:
            parsed.append(candidate)

    return parsed

def extract_report_data(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count == 0:
        raise ValueError("The uploaded PDF has no pages.")

    page = doc[0]
    source_text = page.get_text().lower()
    required = ["fastball in zone", "chase", "fastballs up"]
    if not all(key in source_text for key in required):
        raise ValueError("The uploaded PDF does not match the expected TrackMan report format.")

    output = {}
    for section in SECTIONS:
        if section["type"] == "main":
            rows = parse_main_section(page, section["rect"])
        else:
            rows = parse_chase_section(page, section["rect"])
        output[section["name"]] = rows

    doc.close()
    return output

# ---------- TABLE BUILDERS ----------
def make_section_banner(title, width):
    tbl = Table([[Paragraph(title.upper(), SECTION_STYLE)]], colWidths=[width])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, -1), WHITE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0, NAVY),
    ]))
    return tbl

def build_main_table(title, rows, table_width):
    header = MAIN_COLS
    data = [header] + rows

    col_widths = [
        table_width * 0.18,  # Player
        table_width * 0.035, table_width * 0.05, table_width * 0.04, table_width * 0.055,
        table_width * 0.06, table_width * 0.045, table_width * 0.05, table_width * 0.045,
        table_width * 0.055, table_width * 0.045, table_width * 0.055, table_width * 0.04,
        table_width * 0.05, table_width * 0.03, table_width * 0.03, table_width * 0.03,
        table_width * 0.03, table_width * 0.035, table_width * 0.05, table_width * 0.045
    ]

    tbl = Table(data, colWidths=col_widths, repeatRows=1)

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), MID_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 5.8),
        ("LEADING", (0, 0), (-1, 0), 6.6),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 5.8),
        ("LEADING", (0, 1), (-1, -1), 6.4),
        ("GRID", (0, 0), (-1, -1), 0.25, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
    ]

    # zebra stripes + total row styling
    for i, row in enumerate(data[1:], start=1):
        player = row[0].strip().upper()
        if player == "TOTAL":
            style.extend([
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#DCE7F5")),
                ("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, i), (-1, i), NAVY),
            ])
        elif i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), VERY_LIGHT))

    tbl.setStyle(TableStyle(style))

    return KeepTogether([
        make_section_banner(title, table_width),
        tbl
    ])

def build_chase_table(title, rows, table_width):
    data = [CHASE_COLS] + rows
    col_widths = [
        table_width * 0.60,
        table_width * 0.15,
        table_width * 0.10,
        table_width * 0.15,
    ]

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), MID_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.3, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    for i, row in enumerate(data[1:], start=1):
        player = row[0].strip().upper()
        if player == "TOTAL":
            style.extend([
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#DCE7F5")),
                ("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, i), (-1, i), NAVY),
            ])
        elif i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), VERY_LIGHT))

    tbl.setStyle(TableStyle(style))
    return KeepTogether([
        make_section_banner(title, table_width),
        tbl
    ])

# ---------- PDF RENDER ----------
def build_pdf(report_data, game_date, opponent):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A3_LANDSCAPE,
        leftMargin=20,
        rightMargin=20,
        topMargin=20,
        bottomMargin=18,
    )

    story = []

    title = Paragraph("LEONES DEL ESCOGIDO - PITCH REPORT", TITLE_STYLE)
    subtitle = Paragraph(
        f"{game_date.strftime('%B %d, %Y')} &nbsp;&nbsp;|&nbsp;&nbsp; vs. {opponent}",
        SUBTITLE_STYLE
    )

    story.append(title)
    story.append(subtitle)
    story.append(Spacer(1, 6))

    usable_width = A3_LANDSCAPE[0] - doc.leftMargin - doc.rightMargin
    left_w = usable_width * 0.76
    right_w = usable_width * 0.22

    main_tables = [
        build_main_table("Fastball in Zone", report_data["Fastball in Zone"], left_w),
        build_main_table("Fastballs Up & In vs Righties", report_data["Fastballs Up & In vs Righties"], left_w),
        build_main_table("Fastballs Up & In vs Lefties", report_data["Fastballs Up & In vs Lefties"], left_w),
    ]

    chase_tables = [
        build_chase_table("Fastball Chase % Below the Zone", report_data["Fastball Chase % Below the Zone"], right_w),
        build_chase_table("All Pitches Chase % Below the Zone", report_data["All Pitches Chase % Below the Zone"], right_w),
    ]

    left_stack = []
    for i, t in enumerate(main_tables):
        left_stack.append(t)
        if i < len(main_tables) - 1:
            left_stack.append(Spacer(1, 6))

    right_stack = []
    for i, t in enumerate(chase_tables):
        right_stack.append(t)
        if i < len(chase_tables) - 1:
            right_stack.append(Spacer(1, 16))

    layout = Table(
        [[left_stack, right_stack]],
        colWidths=[left_w, right_w],
        rowHeights=None
    )

    layout.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEBEFORE", (1, 0), (1, 0), 0.6, GRID),
    ]))

    story.append(layout)

    def draw_page(canvas, doc):
        w, h = A3_LANDSCAPE

        # top accent bar
        canvas.setFillColor(RED)
        canvas.rect(0, h - 8, w, 8, stroke=0, fill=1)

        # footer
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 16, w - doc.rightMargin, 16)

        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(doc.leftMargin, 8, "LEONES DEL ESCOGIDO | ANALYTICS")
        canvas.drawRightString(w - doc.rightMargin, 8, "Page 1 of 1")

    doc.build(story, onFirstPage=draw_page)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

# ---------- STREAMLIT PAGE ----------
st.title("⚾ Leones del Escogido - Pitch Report")
st.write(
    "Upload your original TrackMan PDF and generate a clean, one-page report "
    "with the same data in a redesigned layout."
)

st.divider()

uploaded = st.file_uploader("Upload TrackMan PDF", type=["pdf"])

c1, c2 = st.columns(2)
with c1:
    game_date = st.date_input(
        "Game Date",
        value=date.today() - timedelta(days=1),
        format="MM/DD/YYYY"
    )
with c2:
    opponent = st.text_input("Opponent", placeholder="Toros del Este")

st.caption(
    "This version rebuilds the report tables into a designed one-page PDF "
    "instead of just rearranging screenshots of the original PDF."
)

if "pitch_report_pdf" not in st.session_state:
    st.session_state.pitch_report_pdf = None
if "pitch_report_input" not in st.session_state:
    st.session_state.pitch_report_input = None

if st.button("Generate Pitch Report", type="primary", use_container_width=True):
    if uploaded is None:
        st.warning("Please upload your PDF.")
    elif not opponent.strip():
        st.warning("Please enter the opponent.")
    else:
        try:
            with st.spinner("Rebuilding professional one-page report..."):
                report_data = extract_report_data(uploaded.getvalue())
                pdf = build_pdf(report_data, game_date, opponent.strip())

            st.session_state.pitch_report_pdf = pdf
            st.session_state.pitch_report_input = (
                uploaded.getvalue(),
                str(game_date),
                opponent.strip()
            )
            st.success("Your clean one-page report is ready!")
        except Exception as e:
            st.error(f"Could not generate report: {e}")

if st.session_state.pitch_report_pdf is not None and uploaded is not None:
    if st.session_state.pitch_report_input == (
        uploaded.getvalue(),
        str(game_date),
        opponent.strip()
    ):
        safe_opp = re.sub(r"[^A-Za-z0-9_-]+", "_", opponent.strip()) or "Opponent"
        st.download_button(
            "⬇️ Download Pitch Report PDF",
            data=st.session_state.pitch_report_pdf,
            file_name=f"Escogido_Pitch_Report_{game_date:%Y-%m-%d}_{safe_opp}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
