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

    if not all(x in source_text for x in [
        "fastball in zone", "chase", "fastballs up"
    ]):
        raise ValueError(
            "The PDF does not match the expected "
            "TrackMan report format."
        )

    output = fitz.open()
    page_count = len(SECTIONS)

    for number, (title, coords, wide) in enumerate(SECTIONS, 1):
        if wide:
            page = output.new_page(width=842, height=595)
        else:
            page = output.new_page(width=595, height=842)

        w, h = page.rect.width, page.rect.height

        # Top accent
        page.draw_rect(
            fitz.Rect(0, 0, w, 9),
            color=RED, fill=RED
        )

        # Main title
        page.insert_text(
            (35, 42),
            "LEONES DEL ESCOGIDO - PITCH REPORT",
            fontsize=17,
            fontname="hebo",
            color=BLUE
        )

        page.insert_text(
            (35, 64),
            f"{game_date.strftime('%B %d, %Y')} | vs. {opponent}",
            fontsize=11,
            color=GRAY
        )

        # Section heading
        page.draw_rect(
            fitz.Rect(35, 83, w-35, 118),
            color=BLUE, fill=BLUE
        )
        page.insert_text(
            (47, 105),
            title.upper(),
            fontsize=12,
            fontname="hebo",
            color=(1, 1, 1)
        )

        # Convert normalized coordinates to source PDF units
        clip = fitz.Rect(
            coords[0] * src.rect.width,
            coords[1] * src.rect.height,
            coords[2] * src.rect.width,
            coords[3] * src.rect.height,
        )

        # Fit original vector content into the new page.
        # This avoids changing any player statistics.
        available = fitz.Rect(35, 135, w-35, h-58)
        scale = min(
            available.width / clip.width,
            available.height / clip.height
        )

        content_w = clip.width * scale
        content_h = clip.height * scale

        target = fitz.Rect(
            (w-content_w)/2,
            140,
            (w+content_w)/2,
            140+content_h
        )

        page.show_pdf_page(
            target,
            source,
            0,
            clip=clip,
            keep_proportion=True
        )

        # Footer
        page.draw_line(
            (35, h-43),
            (w-35, h-43),
            color=(.83, .85, .88)
        )
        page.insert_text(
            (35, h-27),
            "LEONES DEL ESCOGIDO | ANALYTICS",
            fontsize=8,
            color=GRAY
        )
        page.insert_text(
            (w-100, h-27),
            f"Page {number} of {page_count}",
            fontsize=8,
            color=GRAY
        )

    pdf = output.tobytes(garbage=4, deflate=True)
    output.close()
    source.close()
    return pdf


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
            st.success("Your report is ready!")
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
