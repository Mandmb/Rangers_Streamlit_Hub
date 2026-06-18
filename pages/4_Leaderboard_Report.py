import streamlit as st
import pandas as pd
from io import BytesIO

from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas


st.set_page_config(page_title="Leaderboard Report", layout="wide")

st.title("Player Leaderboard Report")

st.sidebar.header("Upload CSVs")

uploaded_files = st.sidebar.file_uploader(
    "Upload all CSVs at once",
    type="csv",
    accept_multiple_files=True
)

hitting_file = None
baserunning_file = None
infield_file = None
outfield_file = None
catching_file = None

if uploaded_files:
    for file in uploaded_files:
        name = file.name.lower()

        if "rate" in name:
            hitting_file = file
        elif "stolen" in name or "base" in name:
            baserunning_file = file
        elif "infield" in name:
            infield_file = file
        elif "outfield" in name:
            outfield_file = file
        elif "game review" in name or "catch" in name:
            catching_file = file

    st.sidebar.success("Files detected")
    st.sidebar.write("Hitting:", hitting_file.name if hitting_file else "Missing")
    st.sidebar.write("Baserunning:", baserunning_file.name if baserunning_file else "Missing")
    st.sidebar.write("Infield:", infield_file.name if infield_file else "Missing")
    st.sidebar.write("Outfield:", outfield_file.name if outfield_file else "Missing")
    st.sidebar.write("Catching:", catching_file.name if catching_file else "Missing")


def load_csv(file):
    if file is not None:
        return pd.read_csv(file)
    return None


def clean_df(df, rename_map, keep_cols):
    if df is None:
        return None

    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    if "Rank" in df.columns:
        df = df[~df["Rank"].astype(str).str.upper().isin(["TOTAL", "AVERAGE", "RANK"])]

    df = df.rename(columns=rename_map)

    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols]

    return df


def to_number(series):
    return pd.to_numeric(
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False),
        errors="coerce"
    )


def top_leaders_with_extra(df, stat_col, extra_col, n=5, ascending=False):
    if df is None or "Player" not in df.columns or stat_col not in df.columns or extra_col not in df.columns:
        return pd.DataFrame(columns=["Player", stat_col, extra_col])

    temp = df.copy()
    temp["_sort"] = to_number(temp[stat_col])
    temp = temp.dropna(subset=["_sort"])

    return temp.sort_values("_sort", ascending=ascending)[["Player", stat_col, extra_col]].head(n)


def top_leaders_with_context(df, stat_col, context_col, n=5, ascending=False):
    if df is None or "Player" not in df.columns or stat_col not in df.columns or context_col not in df.columns:
        return pd.DataFrame(columns=["Player", context_col, stat_col])

    temp = df.copy()
    temp["_sort"] = to_number(temp[stat_col])
    temp = temp.dropna(subset=["_sort"])

    return temp.sort_values("_sort", ascending=ascending)[["Player", context_col, stat_col]].head(n)


hitting_df = clean_df(
    load_csv(hitting_file),
    {"playerFullName": "Player", "BA": "AVG"},
    ["Player", "G", "PA", "AB", "AVG", "OBP", "SLG", "OPS", "K%", "BB%"]
)

baserunning_df = clean_df(
    load_csv(baserunning_file),
    {"playerFullName": "Player"},
    ["Player", "G", "SBA", "SB", "CS", "SB%"]
)

infield_df = clean_df(
    load_csv(infield_file),
    {"playerFullName": "Player", "IFErr": "E", "IFFld%": "FLD%"},
    ["Player", "InnIF", "IFChances", "IFPutout", "IFAst", "E", "FLD%"]
)

outfield_df = clean_df(
    load_csv(outfield_file),
    {"playerFullName": "Player", "OFErr": "E", "OFFld%": "FLD%"},
    ["Player", "InnOF", "OFChances", "OFPutout", "OFAst", "E", "FLD%"]
)

catching_df = clean_df(
    load_csv(catching_file),
    {"playerFullName": "Player"},
    ["Player", "CS%", "SBA", "SL+", "FrmdB50%+", "P", "StrkFrmd", "BallFrmd"]
)


def short_name(name, max_len=17):
    name = str(name)
    if len(name) <= max_len:
        return name
    return name[:max_len - 2] + ".."


def draw_centered_text(c, text, x, y, w, font="Helvetica", size=6.6):
    text = str(text)
    c.setFont(font, size)
    text_width = c.stringWidth(text, font, size)
    c.drawString(x + (w / 2) - (text_width / 2), y, text)


def draw_baseball_icon(c, x, y, size=12):
    c.setStrokeColor(colors.white)
    c.setFillColor(colors.white)
    c.circle(x, y, size / 2, stroke=1, fill=0)
    c.line(x - 3, y + 4, x - 1, y - 4)
    c.line(x + 3, y + 4, x + 1, y - 4)


def draw_crossed_bats(c, x, y):
    c.setStrokeColor(colors.HexColor("#001F45"))
    c.setLineWidth(4)
    c.line(x - 18, y - 18, x + 18, y + 18)
    c.line(x - 18, y + 18, x + 18, y - 18)

    c.setFillColor(colors.white)
    c.circle(x, y, 12, stroke=1, fill=1)

    c.setStrokeColor(colors.HexColor("#001F45"))
    c.setLineWidth(1)
    c.circle(x, y, 12, stroke=1, fill=0)
    c.line(x - 5, y + 8, x - 2, y - 8)
    c.line(x + 5, y + 8, x + 2, y - 8)


def draw_section_banner(c, text, x, y, w, h=18):
    red = colors.HexColor("#C0111F")
    c.setFillColor(red)
    c.roundRect(x, y, w, h, 4, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + w / 2, y + 5, text)


def draw_table(c, title, df, x, y, w, col_weights):
    navy = colors.HexColor("#002B5C")
    light = colors.HexColor("#EAF0F6")
    grid = colors.HexColor("#C8C8C8")

    title_h = 17
    header_h = 14
    row_h = 15
    h = title_h + header_h + row_h * 5

    c.setStrokeColor(colors.HexColor("#D6D6D6"))
    c.setFillColor(colors.white)
    c.roundRect(x, y - h, w, h, 3, stroke=1, fill=1)

    c.setFillColor(navy)
    c.roundRect(x, y - title_h, w, title_h, 3, stroke=0, fill=1)

    draw_baseball_icon(c, x + 13, y - 8.5, 10)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x + w / 2, y - 11.5, title)

    if df is None or df.empty:
        cols = ["#", "PLAYER", ""]
        rows = []
    else:
        cols = ["#"] + [str(cn).upper() for cn in df.columns]
        rows = df.fillna("").astype(str).values.tolist()

    total_weight = sum(col_weights)
    col_widths = [w * cw / total_weight for cw in col_weights]

    header_y = y - title_h - header_h

    c.setFillColor(light)
    c.rect(x, header_y, w, header_h, stroke=0, fill=1)

    current_x = x
    for i, col in enumerate(cols):
        cw = col_widths[i] if i < len(col_widths) else col_widths[-1]

        c.setStrokeColor(grid)
        c.setLineWidth(0.4)
        c.line(current_x, y - title_h, current_x, y - h)

        c.setFillColor(colors.HexColor("#0B1628"))
        draw_centered_text(c, col, current_x, header_y + 4, cw, "Helvetica-Bold", 6.2)

        current_x += cw

    c.line(x + w, y - title_h, x + w, y - h)

    for r in range(5):
        row_top = header_y - r * row_h
        row_bottom = row_top - row_h

        if r % 2 == 1:
            c.setFillColor(colors.HexColor("#F7F7F7"))
            c.rect(x, row_bottom, w, row_h, stroke=0, fill=1)

        c.setStrokeColor(grid)
        c.line(x, row_bottom, x + w, row_bottom)

        c.setFillColor(colors.black)
        draw_centered_text(
            c,
            str(r + 1),
            x,
            row_bottom + 4,
            col_widths[0],
            "Helvetica-Bold",
            6.7
        )

        if r < len(rows):
            values = rows[r]
            current_x = x + col_widths[0]

            for i, val in enumerate(values):
                cw = col_widths[i + 1] if i + 1 < len(col_widths) else col_widths[-1]

                if i == 0:
                    text = short_name(val, 15)
                else:
                    text = short_name(val, 8)

                c.setFillColor(colors.black)
                draw_centered_text(
                    c,
                    text,
                    current_x,
                    row_bottom + 4,
                    cw,
                    "Helvetica",
                    6.6
                )

                current_x += cw

    c.setStrokeColor(grid)
    c.rect(x, y - h, w, h, stroke=1, fill=0)


def build_pdf():
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(letter))

    width, height = landscape(letter)

    navy = colors.HexColor("#001F45")
    red = colors.HexColor("#C0111F")

    c.setFillColor(colors.white)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    draw_crossed_bats(c, 70, 562)
    draw_crossed_bats(c, width - 70, 562)

    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(width / 2, 555, "PLAYER LEADERBOARD REPORT")

    c.setStrokeColor(red)
    c.setLineWidth(1.4)
    c.line(90, 530, 335, 530)
    c.line(457, 530, 702, 530)

    c.setFillColor(red)
    c.setFont("Helvetica-Bold", 15)
    for sx in [350, 373, 396, 419, 442]:
        c.drawCentredString(sx, 523, "★")

    draw_section_banner(c, "HITTING", 265, 490, 262)

    hitting_tables = [
        ("AVG", top_leaders_with_context(hitting_df, "AVG", "PA")),
        ("OBP", top_leaders_with_context(hitting_df, "OBP", "PA")),
        ("SLG", top_leaders_with_context(hitting_df, "SLG", "PA")),
        ("OPS", top_leaders_with_context(hitting_df, "OPS", "PA")),
        ("BB%", top_leaders_with_context(hitting_df, "BB%", "PA")),
        ("K%", top_leaders_with_context(hitting_df, "K%", "PA", ascending=True)),
    ]

    start_x = 16
    table_w = 120
    gap = 12
    y = 474

    for i, (title, df) in enumerate(hitting_tables):
        draw_table(
            c,
            title,
            df,
            start_x + i * (table_w + gap),
            y,
            table_w,
            [0.14, 0.48, 0.18, 0.20]
        )

    draw_section_banner(c, "BASERUNNING / DEFENSE", 245, 342, 302)

    middle_tables = [
        ("SB LEADERS", top_leaders_with_extra(baserunning_df, "SB", "SB%"), 145, [0.14, 0.48, 0.18, 0.20]),
        ("INF ERRORS", top_leaders_with_context(infield_df, "E", "InnIF", ascending=True), 145, [0.14, 0.46, 0.22, 0.18]),
        ("INF FLD%", top_leaders_with_context(infield_df, "FLD%", "InnIF"), 145, [0.14, 0.46, 0.22, 0.18]),
        ("OF ERRORS", top_leaders_with_context(outfield_df, "E", "InnOF", ascending=True), 145, [0.14, 0.46, 0.22, 0.18]),
        ("OF FLD%", top_leaders_with_context(outfield_df, "FLD%", "InnOF"), 145, [0.14, 0.46, 0.22, 0.18]),
    ]

    start_x = 16
    gap = 12
    y = 326

    current_x = start_x
    for title, df, tw, weights in middle_tables:
        draw_table(c, title, df, current_x, y, tw, weights)
        current_x += tw + gap

    draw_section_banner(c, "CATCHING", 315, 194, 162)

    catching_tables = [
        ("SL+", top_leaders_with_context(catching_df, "SL+", "P"), 215, [0.14, 0.50, 0.18, 0.18]),
        ("CS% / SBA", top_leaders_with_extra(catching_df, "CS%", "SBA"), 245, [0.14, 0.48, 0.19, 0.19]),
    ]

    y = 178
    draw_table(c, catching_tables[0][0], catching_tables[0][1], 164, y, catching_tables[0][2], catching_tables[0][3])
    draw_table(c, catching_tables[1][0], catching_tables[1][1], 400, y, catching_tables[1][2], catching_tables[1][3])

    c.setStrokeColor(navy)
    c.setLineWidth(1)
    c.line(25, 25, 330, 25)
    c.line(462, 25, 767, 25)

    c.setFillColor(red)
    c.setFont("Helvetica-Bold", 14)
    for sx in [350, 373, 419, 442]:
        c.drawCentredString(sx, 19, "★")

    c.setFillColor(navy)
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(25, 12, "TOP 5 PLAYERS PER STATISTIC")
    c.drawRightString(767, 12, "GENERATED FROM UPLOADED CSV FILES")

    c.showPage()
    c.save()

    buffer.seek(0)
    return buffer


st.header("Cleaned CSV Preview")

tabs = st.tabs(["Hitting", "Baserunning", "Infield Defense", "Outfield Defense", "Catching"])

with tabs[0]:
    if hitting_df is not None:
        st.dataframe(hitting_df, hide_index=True)
    else:
        st.info("Upload Hitting CSV")

with tabs[1]:
    if baserunning_df is not None:
        st.dataframe(baserunning_df, hide_index=True)
    else:
        st.info("Upload Baserunning CSV")

with tabs[2]:
    if infield_df is not None:
        st.dataframe(infield_df, hide_index=True)
    else:
        st.info("Upload Infield Defense CSV")

with tabs[3]:
    if outfield_df is not None:
        st.dataframe(outfield_df, hide_index=True)
    else:
        st.info("Upload Outfield Defense CSV")

with tabs[4]:
    if catching_df is not None:
        st.dataframe(catching_df, hide_index=True)
    else:
        st.info("Upload Catching CSV")


all_uploaded = all([
    hitting_df is not None,
    baserunning_df is not None,
    infield_df is not None,
    outfield_df is not None,
    catching_df is not None
])

if all_uploaded:
    pdf = build_pdf()

    st.download_button(
        label="Download Beautiful PDF Report",
        data=pdf,
        file_name="player_leaderboard_report.pdf",
        mime="application/pdf"
    )
else:
    st.info("Upload all 5 CSVs to enable PDF export.")