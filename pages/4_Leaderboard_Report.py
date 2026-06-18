import os
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date

from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


st.set_page_config(page_title="Leaderboard Report", layout="wide")

st.title("Player Leaderboard Report")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CURRENT_DIR = os.getcwd()


def find_icon(filename):
    """Find icon in common local locations so Streamlit can draw it in the PDF."""
    possible_paths = [
        os.path.join(SCRIPT_DIR, filename),
        os.path.join(CURRENT_DIR, filename),
        os.path.join(SCRIPT_DIR, "assets", filename),
        os.path.join(CURRENT_DIR, "assets", filename),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None


HITTING_ICON = find_icon("Hitting.png")
BASERUNNING_ICON = find_icon("Baserunning.png") or find_icon("baserunning.png")
DEFENSE_ICON = find_icon("Defense.png")
CATCHING_ICON = find_icon("Catching.png")

st.sidebar.header("Upload CSVs")

uploaded_files = st.sidebar.file_uploader(
    "Upload all CSVs at once",
    type="csv",
    accept_multiple_files=True
)

st.sidebar.header("Report Info")
team_name = st.sidebar.text_input("Team / Group", "DSL Rangers")
report_date = st.sidebar.date_input("Report Date", date.today())

st.sidebar.header("Minimum Qualifiers")
min_pa = st.sidebar.number_input("Minimum PA for hitters", min_value=0, value=40)
min_inn_if = st.sidebar.number_input("Minimum InnIF", min_value=0, value=40)
min_inn_of = st.sidebar.number_input("Minimum InnOF", min_value=0, value=40)
min_catcher_p = st.sidebar.number_input("Minimum Catcher P", min_value=0, value=100)
min_sba = st.sidebar.number_input("Minimum SBA for CS%", min_value=0, value=5)

st.sidebar.header("PDF Icons")
st.sidebar.write("Hitting:", "Found" if HITTING_ICON else "Missing Hitting.png")
st.sidebar.write("Baserunning:", "Found" if BASERUNNING_ICON else "Missing Baserunning.png / baserunning.png")
st.sidebar.write("Defense:", "Found" if DEFENSE_ICON else "Missing Defense.png")
st.sidebar.write("Catching:", "Found" if CATCHING_ICON else "Missing Catching.png")

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


def top_leaders_with_extra(df, stat_col, extra_col, n=5, ascending=False, min_col=None, minimum=0):
    if df is None or "Player" not in df.columns or stat_col not in df.columns or extra_col not in df.columns:
        return pd.DataFrame(columns=["Player", stat_col, extra_col])

    temp = df.copy()

    if min_col and min_col in temp.columns:
        temp["_qualifier"] = to_number(temp[min_col])
        temp = temp[temp["_qualifier"] >= minimum]

    temp["_sort"] = to_number(temp[stat_col])
    temp = temp.dropna(subset=["_sort"])

    return temp.sort_values("_sort", ascending=ascending)[["Player", stat_col, extra_col]].head(n)


def top_leaders_with_context(df, stat_col, context_col, n=5, ascending=False, min_col=None, minimum=0):
    if df is None or "Player" not in df.columns or stat_col not in df.columns or context_col not in df.columns:
        return pd.DataFrame(columns=["Player", context_col, stat_col])

    temp = df.copy()

    if min_col and min_col in temp.columns:
        temp["_qualifier"] = to_number(temp[min_col])
        temp = temp[temp["_qualifier"] >= minimum]

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


def short_name(name, max_len=18):
    name = str(name)
    if len(name) <= max_len:
        return name
    return name[:max_len - 2] + ".."


def draw_centered_text(c, text, x, y, w, font="Helvetica", size=6.3):
    text = str(text)
    c.setFont(font, size)
    text_width = c.stringWidth(text, font, size)
    c.drawString(x + (w / 2) - (text_width / 2), y, text)


def draw_fallback_icon(c, x, y, size=14):
    c.setStrokeColor(colors.white)
    c.setLineWidth(1.1)
    c.circle(x, y, size / 2, stroke=1, fill=0)
    c.line(x - 3, y + 4, x - 1, y - 4)
    c.line(x + 3, y + 4, x + 1, y - 4)


def draw_image_icon(c, icon_path, x, y, size=18):
    if icon_path and os.path.exists(icon_path):
        try:
            img = ImageReader(icon_path)
            c.drawImage(
                img,
                x - size / 2,
                y - size / 2,
                width=size,
                height=size,
                mask="auto"
            )
            return
        except Exception:
            pass

    draw_fallback_icon(c, x, y, size=size)


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


def draw_table(c, title, df, x, y, w, col_weights, icon_path):
    header_blue = colors.HexColor("#4F8EF7")
    light = colors.HexColor("#EAF0F6")
    gold = colors.HexColor("#FFF2CC")
    grid = colors.HexColor("#C8C8C8")

    title_h = 18
    header_h = 14
    row_h = 15
    h = title_h + header_h + row_h * 5

    c.setStrokeColor(colors.HexColor("#D6D6D6"))
    c.setFillColor(colors.white)
    c.roundRect(x, y - h, w, h, 4, stroke=1, fill=1)

    c.setFillColor(header_blue)
    c.roundRect(x, y - title_h, w, title_h, 4, stroke=0, fill=1)

    draw_image_icon(c, icon_path, x + 14, y - 9, size=18)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x + (w / 2) + 5, y - 12, title)

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
        draw_centered_text(c, col, current_x, header_y + 4, cw, "Helvetica-Bold", 5.8)

        current_x += cw

    c.line(x + w, y - title_h, x + w, y - h)

    for r in range(5):
        row_top = header_y - r * row_h
        row_bottom = row_top - row_h

        if r == 0:
            c.setFillColor(gold)
            c.rect(x, row_bottom, w, row_h, stroke=0, fill=1)
        elif r % 2 == 1:
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
            6.2
        )

        if r < len(rows):
            values = rows[r]
            current_x = x + col_widths[0]

            for i, val in enumerate(values):
                cw = col_widths[i + 1] if i + 1 < len(col_widths) else col_widths[-1]

                if i == 0:
                    text = short_name(val, 18)
                    size = 6.1
                else:
                    text = short_name(val, 12)
                    size = 6.0

                draw_centered_text(
                    c,
                    text,
                    current_x,
                    row_bottom + 4,
                    cw,
                    "Helvetica-Bold" if r == 0 else "Helvetica",
                    size
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
    panel = colors.HexColor("#F4F6F9")

    c.setFillColor(colors.white)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    draw_crossed_bats(c, 70, 562)
    draw_crossed_bats(c, width - 70, 562)

    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(width / 2, 555, "PLAYER LEADERBOARD REPORT")

    c.setFillColor(colors.HexColor("#334155"))
    c.setFont("Helvetica", 9)
    subtitle = f"{team_name} | Through {report_date.strftime('%B %d, %Y')} | Top 5 by Category"
    c.drawCentredString(width / 2, 538, subtitle)

    c.setStrokeColor(red)
    c.setLineWidth(1.4)
    c.line(90, 524, 335, 524)
    c.line(457, 524, 702, 524)

    c.setFillColor(red)
    c.setFont("Helvetica-Bold", 14)
    center_x = width / 2
    star_spacing = 23
    for i in range(-2, 3):
        c.drawCentredString(center_x + (i * star_spacing), 517, "★")

    c.setFillColor(panel)
    c.roundRect(10, 377, width - 20, 123, 6, stroke=0, fill=1)
    draw_section_banner(c, "HITTING", (width - 262) / 2, 488, 262)

    hitting_tables = [
        ("AVG", top_leaders_with_context(hitting_df, "AVG", "PA", min_col="PA", minimum=min_pa)),
        ("OBP", top_leaders_with_context(hitting_df, "OBP", "PA", min_col="PA", minimum=min_pa)),
        ("SLG", top_leaders_with_context(hitting_df, "SLG", "PA", min_col="PA", minimum=min_pa)),
        ("OPS", top_leaders_with_context(hitting_df, "OPS", "PA", min_col="PA", minimum=min_pa)),
        ("BB%", top_leaders_with_context(hitting_df, "BB%", "PA", min_col="PA", minimum=min_pa)),
        ("K%", top_leaders_with_context(hitting_df, "K%", "PA", ascending=True, min_col="PA", minimum=min_pa)),
    ]

    hitting_table_w = 114
    hitting_gap = 8
    hitting_total_w = (6 * hitting_table_w) + (5 * hitting_gap)
    hitting_start_x = (width - hitting_total_w) / 2
    hitting_y = 472

    for i, (title, df) in enumerate(hitting_tables):
        draw_table(
            c,
            title,
            df,
            hitting_start_x + i * (hitting_table_w + hitting_gap),
            hitting_y,
            hitting_table_w,
            [0.12, 0.51, 0.17, 0.20],
            HITTING_ICON
        )

    c.setFillColor(panel)
    c.roundRect(10, 229, width - 20, 123, 6, stroke=0, fill=1)
    draw_section_banner(c, "BASERUNNING / DEFENSE", (width - 302) / 2, 340, 302)

    middle_tables = [
        ("SB LEADERS", top_leaders_with_extra(baserunning_df, "SB", "SB%"), 140, [0.12, 0.50, 0.16, 0.22], BASERUNNING_ICON),
        ("INF ERRORS", top_leaders_with_context(infield_df, "E", "InnIF", ascending=True, min_col="InnIF", minimum=min_inn_if), 140, [0.12, 0.50, 0.24, 0.14], DEFENSE_ICON),
        ("INF FLD%", top_leaders_with_context(infield_df, "FLD%", "InnIF", min_col="InnIF", minimum=min_inn_if), 140, [0.12, 0.48, 0.22, 0.18], DEFENSE_ICON),
        ("OF ERRORS", top_leaders_with_context(outfield_df, "E", "InnOF", ascending=True, min_col="InnOF", minimum=min_inn_of), 140, [0.12, 0.50, 0.24, 0.14], DEFENSE_ICON),
        ("OF FLD%", top_leaders_with_context(outfield_df, "FLD%", "InnOF", min_col="InnOF", minimum=min_inn_of), 140, [0.12, 0.44, 0.22, 0.22], DEFENSE_ICON),
    ]

    middle_gap = 8
    middle_total_w = sum(t[2] for t in middle_tables) + (len(middle_tables) - 1) * middle_gap
    middle_start_x = (width - middle_total_w) / 2
    middle_y = 324

    current_x = middle_start_x
    for title, df, tw, weights, icon in middle_tables:
        draw_table(c, title, df, current_x, middle_y, tw, weights, icon)
        current_x += tw + middle_gap

    catch_left_w = 230
    catch_right_w = 260
    catch_gap = 20
    catch_total_w = catch_left_w + catch_right_w + catch_gap
    catch_start_x = (width - catch_total_w) / 2
    catch_panel_x = catch_start_x - 15
    catch_panel_w = catch_total_w + 30

    c.setFillColor(panel)
    c.roundRect(catch_panel_x, 82, catch_panel_w, 122, 6, stroke=0, fill=1)
    draw_section_banner(c, "CATCHING", (width - 162) / 2, 192, 162)

    catching_tables = [
        ("SL+", top_leaders_with_context(catching_df, "SL+", "P", min_col="P", minimum=min_catcher_p), catch_left_w, [0.12, 0.55, 0.15, 0.18], CATCHING_ICON),
        ("CS% / SBA", top_leaders_with_extra(catching_df, "CS%", "SBA", min_col="SBA", minimum=min_sba), catch_right_w, [0.12, 0.52, 0.18, 0.18], CATCHING_ICON),
    ]

    catch_y = 176

    draw_table(
        c,
        catching_tables[0][0],
        catching_tables[0][1],
        catch_start_x,
        catch_y,
        catching_tables[0][2],
        catching_tables[0][3],
        catching_tables[0][4]
    )

    draw_table(
        c,
        catching_tables[1][0],
        catching_tables[1][1],
        catch_start_x + catch_left_w + catch_gap,
        catch_y,
        catching_tables[1][2],
        catching_tables[1][3],
        catching_tables[1][4]
    )

    c.setStrokeColor(navy)
    c.setLineWidth(1)

    footer_left_line_start = 25
    footer_left_line_end = (width / 2) - 66
    footer_right_line_start = (width / 2) + 66
    footer_right_line_end = width - 25

    c.line(footer_left_line_start, 25, footer_left_line_end, 25)
    c.line(footer_right_line_start, 25, footer_right_line_end, 25)

    c.setFillColor(red)
    c.setFont("Helvetica-Bold", 14)
    for i in [-2, -1, 1, 2]:
        c.drawCentredString(center_x + (i * star_spacing), 19, "★")

    c.setFillColor(navy)
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(25, 12, f"MIN PA {min_pa} | MIN INF {min_inn_if} | MIN OF {min_inn_of} | MIN C P {min_catcher_p}")
    c.drawRightString(width - 25, 12, "GENERATED FROM UPLOADED CSV FILES")

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
