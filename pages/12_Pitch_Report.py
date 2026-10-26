import streamlit as st
import fitz
from datetime import date, timedelta
from io import BytesIO
import re

st.set_page_config(
    page_title="Escogido Pitch Report",
    page_icon="⚾",
    layout="wide"
)

BLUE = (0.055, 0.19, 0.36)
RED = (0.78, 0.12, 0.17)
GRAY = (0.42, 0.45, 0.50)

# Regions based on the supplied TrackMan PDF.
# Coordinates are proportions of the original page.
SECTIONS = [
    ("Fastball in Zone", (.105, .055, .635, .345), True),
    ("Fastball Chase % Below the Zone", (.695, .055, .940, .340), False),
    ("Fastballs Up & In vs Righties", (.105, .475, .635, .705), True),
    ("All Pitches Chase % Below the Zone", (.695, .475, .940, .765), False),
    ("Fastballs Up & In vs Lefties", (.105, .745, .635, .945), True),
]


def make_pdf(data, game_date, opponent):
    source = fitz.open(stream=data, filetype="pdf")
    if source.page_count == 0:
        raise ValueError("The PDF has no pages.")

    src = source[0]
    source_text = src.get_text().lower()

    required = [
        "fastball in zone",
        "fastballs up",
        "chase"
    ]
    if not all(x in source_text for x in required):
        raise ValueError(
            "The uploaded PDF does not match the "
            "expected TrackMan report."
        )

    # Single A3 portrait sheet.
    # The original PDF tables are kept as vector content.
    output = fitz.open()
    page = output.new_page(width=842, height=1191)

    w = page.rect.width
    h = page.rect.height

    # Main header
    page.draw_rect(
        fitz.Rect(0, 0, w, 11),
        color=RED, fill=RED
    )

    page.insert_text(
        (35, 47),
        "LEONES DEL ESCOGIDO - PITCH REPORT",
        fontname="hebo",
        fontsize=20,
        color=BLUE
    )

    page.insert_text(
        (35, 73),
        f"{game_date:%B %d, %Y}  |  vs. {opponent}",
        fontsize=12,
        color=GRAY
    )

    page.draw_line(
        (35, 89), (807, 89),
        color=RED, width=2
    )

    # Original PDF coordinates measured from
    # the October 25 TrackMan export.
    #
    # The first three tables occupy the left.
    # The two chase tables occupy the right.
    #
    # (name, source clipping rectangle,
    #  destination x, destination y, max width)

    panels = [
        (
            "Fastball in Zone",
            (68, 46, 385, 330),
            35, 115, 530
        ),
        (
            "Fastballs Up & In vs Righties",
            (68, 384, 385, 562),
            35, 607, 530
        ),
        (
            "Fastballs Up & In vs Lefties",
            (68, 585, 385, 704),
            35, 926, 530
        ),
        (
            "Fastball Chase Below Zone",
            (428, 46, 560, 230),
            584, 115, 223
        ),
        (
            "All Pitches Chase Below Zone",
            (428, 398, 560, 556),
            584, 464, 223
        )
    ]

    for name, rect, x, y, max_width in panels:
        clip = fitz.Rect(*rect)

        # Convert original PDF coordinates
        # if the export page dimensions differ.
        sx = src.rect.width / 612
        sy = src.rect.height / 792

        clip = fitz.Rect(
            clip.x0 * sx,
            clip.y0 * sy,
            clip.x1 * sx,
            clip.y1 * sy
        )

        scale = max_width / clip.width
        rendered_height = clip.height * scale

        target = fitz.Rect(
            x, y,
            x + max_width,
            y + rendered_height
        )

        # Copy original text and tables directly.
        # No statistics are recalculated or rounded.
        page.show_pdf_page(
            target,
            source,
            0,
            clip=clip,
            keep_proportion=True
        )

    # Subtle separation between columns
    page.draw_line(
        (574, 110),
        (574, 1124),
        color=(0.85, 0.87, 0.90),
        width=0.7
    )

    # Footer
    page.draw_line(
        (35, 1145), (807, 1145),
        color=(0.83, 0.85, 0.88),
        width=0.7
    )

    page.insert_text(
        (35, 1165),
        "LEONES DEL ESCOGIDO | ANALYTICS",
        fontsize=9,
        color=GRAY
    )

    page.insert_text(
        (747, 1165),
        "Page 1 of 1",
        fontsize=9,
        color=GRAY
    )

    result = output.tobytes(
        garbage=4,
        deflate=True
    )

    output.close()
    source.close()

    return result


st.title("⚾ Leones del Escogido - Pitch Report")
st.write(
    "Upload your TrackMan PDF and generate a cleaner, "
    "more readable report while preserving the original data."
)

st.divider()

uploaded = st.file_uploader(
    "Upload TrackMan PDF",
    type=["pdf"]
)

c1, c2 = st.columns(2)

with c1:
    game_date = st.date_input(
        "Game Date",
        value=date.today()-timedelta(days=1),
        format="MM/DD/YYYY"
    )

with c2:
    opponent = st.text_input(
        "Opponent",
        placeholder="Toros del Este"
    )

st.subheader("Report Sections")
for title, _, _ in SECTIONS:
    st.write("✓ " + title)

if "pitch_report_pdf" not in st.session_state:
    st.session_state.pitch_report_pdf = None
if "pitch_report_input" not in st.session_state:
    st.session_state.pitch_report_input = None

if st.button("Generate Pitch Report", type="primary"):
    if uploaded is None:
        st.warning("Please upload your PDF.")
    elif not opponent.strip():
        st.warning("Please enter the opponent.")
    else:
        try:
            with st.spinner("Building report..."):
                result = make_pdf(
                    uploaded.getvalue(),
                    game_date,
                    opponent.strip()
                )
            st.session_state.pitch_report_pdf = result
            st.session_state.pitch_report_input = (
                uploaded.getvalue(),
                game_date,
                opponent.strip()
            )
            st.success("Your one-page report is ready!")
        except Exception as e:
            st.error(str(e))

if st.session_state.pitch_report_pdf is not None:
    saved = st.session_state.pitch_report_input
    if (
        uploaded is not None
        and saved == (
            uploaded.getvalue(),
            game_date,
            opponent.strip()
        )
    ):
        safe_opponent = re.sub(
            r"[^a-zA-Z0-9_-]+", "_", opponent
        )
        st.download_button(
            "⬇️ Download Pitch Report PDF",
            data=st.session_state.pitch_report_pdf,
            file_name=(
                f"Escogido_Pitch_Report_"
                f"{game_date:%Y-%m-%d}_"
                f"{safe_opponent}.pdf"
            ),
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
