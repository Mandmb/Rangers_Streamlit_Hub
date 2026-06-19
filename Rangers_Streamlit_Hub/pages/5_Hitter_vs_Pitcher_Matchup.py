import math
from io import BytesIO
from datetime import datetime
from functools import partial

import pandas as pd
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as canvas_module
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak,
    KeepTogether,
    Image,
)

# =====================================================
# STREAMLIT SETUP
# =====================================================

st.set_page_config(page_title="Hitter vs Pitcher Matchups", layout="wide")
st.title("⚾ Hitter vs Pitcher Matchup Tool")

REQUIRED_COLUMNS = [
    "pitcherAbbrevName",
    "pitcherHand",
    "batterAbbrevName",
    "batterHand",
    "pitchResult",
]

# Brand colors
BLUE = "#002B5C"
RED = "#C8102E"
DARK_RED = "#B00020"
GREEN = "#188038"
GRAY = "#8E8E8E"
LIGHT_GRAY = "#F4F6F8"
BORDER = "#C8D0D8"
BLACK = "#111111"
WHITE = "#FFFFFF"
LIGHT_BLUE = "#EAF3FF"
LIGHT_RED = "#FDECEA"
LIGHT_GREEN = "#E8F5E9"

# PDF constants
PAGE_W, PAGE_H = landscape(letter)
PDF_LEFT = 0.25 * inch
PDF_RIGHT = 0.25 * inch
PDF_TOP = 1.05 * inch
PDF_BOTTOM = 0.30 * inch
CONTENT_W = PAGE_W - PDF_LEFT - PDF_RIGHT

# Optional icon used inside executive summary / team snapshot cards.
# On your Mac, either upload baseball.png in the sidebar or keep a file named
# baseball.png in the same folder as app.py.
CARD_ICON_BYTES = None



# =====================================================
# FORMAT HELPERS
# =====================================================

def safe_div(n, d):
    return n / d if d else 0


def fmt_avg(x):
    try:
        return f"{float(x):.3f}".replace("0.", ".")
    except Exception:
        return ".000"


def fmt_pct(x):
    try:
        return f"{float(x) * 100:.1f}%"
    except Exception:
        return "0.0%"


def hand_label(hand):
    hand = str(hand).strip().upper()
    if hand == "R":
        return "RHP"
    if hand == "L":
        return "LHP"
    return hand


def ops_band_color(ops):
    """
    Pitcher perspective requested by user:
    Red = elite pitcher result, OPS allowed < .650
    Gray = average, .650-.800
    Green = damage, OPS allowed > .800
    """
    ops = float(ops or 0)
    if ops < 0.650:
        return DARK_RED
    if ops > 0.800:
        return GREEN
    return GRAY


def ops_light_fill(ops):
    ops = float(ops or 0)
    if ops < 0.650:
        return "#FFE3E3"
    if ops > 0.800:
        return "#DFF3E5"
    return "#EFEFEF"


def k_text_color(k):
    return GREEN if float(k or 0) >= 0.250 else BLUE


def bb_text_color(bb):
    return DARK_RED if float(bb or 0) >= 0.120 else GREEN


# =====================================================
# DATA LOGIC
# =====================================================

def classify_result(result):
    result = str(result).strip().lower()
    return {
        "Single": int(result.startswith("single")),
        "Double": int(result.startswith("double")),
        "Triple": int(result.startswith("triple")),
        "Homerun": int(result.startswith("home run")),
        "Walks": int(result.startswith("walk")),
        "HBP": int("hit by pitch" in result),
        "Strikeouts": int("strikeout" in result),
    }


def count_balls_in_pa(pa):
    ball_results = ["ball", "ball in the dirt"]
    return (
        pa["pitchResult"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(ball_results)
        .sum()
    )


def add_rate_stats(grouped):
    grouped = grouped.copy()
    grouped["Total Bases"] = (
        grouped["Single"]
        + grouped["Double"] * 2
        + grouped["Triple"] * 3
        + grouped["Homerun"] * 4
    )

    grouped["BA_num"] = grouped.apply(lambda r: safe_div(r["Hits"], r["PA"]), axis=1)
    grouped["OBP_num"] = grouped.apply(lambda r: safe_div(r["Hits"] + r["Walks"] + r["HBP"], r["PA"]), axis=1)
    grouped["SLG_num"] = grouped.apply(lambda r: safe_div(r["Total Bases"], r["PA"]), axis=1)
    grouped["OPS_num"] = grouped["OBP_num"] + grouped["SLG_num"]
    grouped["BB_pct_num"] = grouped.apply(lambda r: safe_div(r["Walks"], r["PA"]), axis=1)
    grouped["K_pct_num"] = grouped.apply(lambda r: safe_div(r["Strikeouts"], r["PA"]), axis=1)

    grouped["BA"] = grouped["BA_num"].apply(fmt_avg)
    grouped["OBP"] = grouped["OBP_num"].apply(fmt_avg)
    grouped["SLG"] = grouped["SLG_num"].apply(fmt_avg)
    grouped["OPS"] = grouped["OPS_num"].apply(fmt_avg)
    grouped["BB%"] = grouped["BB_pct_num"].apply(fmt_pct)
    grouped["K%"] = grouped["K_pct_num"].apply(fmt_pct)
    return grouped


def build_matchups(df):
    df = df[REQUIRED_COLUMNS].copy()
    df = df.dropna(subset=["pitcherAbbrevName", "batterAbbrevName"])
    df = df.reset_index(drop=True)

    df["new_pa"] = (
        (df["batterAbbrevName"] != df["batterAbbrevName"].shift())
        | (df["pitcherAbbrevName"] != df["pitcherAbbrevName"].shift())
    )
    df["pa_id"] = df["new_pa"].cumsum()

    pa_rows = []
    for _, pa in df.groupby("pa_id", sort=False):
        first = pa.iloc[0]
        last = pa.iloc[-1]
        stats = classify_result(last["pitchResult"])

        if stats["Walks"] == 0 and count_balls_in_pa(pa) >= 4:
            stats["Walks"] = 1

        stats["Hits"] = stats["Single"] + stats["Double"] + stats["Triple"] + stats["Homerun"]

        pa_rows.append({
            "pitcherAbbrevName": first["pitcherAbbrevName"],
            "pitcherHand": first["pitcherHand"],
            "batterAbbrevName": first["batterAbbrevName"],
            "batterHand": first["batterHand"],
            "PA": 1,
            **stats,
        })

    pa_df = pd.DataFrame(pa_rows)
    if pa_df.empty:
        return pd.DataFrame()

    grouped = pa_df.groupby(
        ["pitcherAbbrevName", "pitcherHand", "batterAbbrevName", "batterHand"],
        as_index=False,
    ).sum(numeric_only=True)

    grouped = add_rate_stats(grouped)

    final_cols = [
        "pitcherAbbrevName", "pitcherHand", "batterAbbrevName", "batterHand",
        "PA", "Hits", "Single", "Double", "Triple", "Homerun", "Walks", "HBP",
        "Strikeouts", "Total Bases", "BA", "OBP", "SLG", "OPS", "BB%", "K%",
        "BA_num", "OBP_num", "SLG_num", "OPS_num", "BB_pct_num", "K_pct_num",
    ]

    return grouped[final_cols].sort_values(
        by=["pitcherAbbrevName", "PA", "OPS_num"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def aggregate_rows(df, group_cols):
    if df.empty:
        return pd.DataFrame()

    numeric_cols = [
        "PA", "Hits", "Single", "Double", "Triple", "Homerun",
        "Walks", "HBP", "Strikeouts"
    ]
    grouped = df.groupby(group_cols, as_index=False)[numeric_cols].sum()
    return add_rate_stats(grouped)


def team_total_row(df):
    numeric_cols = ["PA", "Hits", "Single", "Double", "Triple", "Homerun", "Walks", "HBP", "Strikeouts"]
    values = {col: int(df[col].sum()) for col in numeric_cols}
    temp = pd.DataFrame([values])
    temp = add_rate_stats(temp)
    return temp.iloc[0]


def pitcher_score(ops, k_pct, bb_pct):
    """
    Higher score is better for pitcher.
    60% lower OPS allowed, 25% higher K%, 15% lower BB%.
    """
    ops_component = max(0, min(1, (1.200 - float(ops)) / 1.200)) * 60
    k_component = max(0, min(1, float(k_pct) / 0.350)) * 25
    bb_component = max(0, min(1, (0.180 - float(bb_pct)) / 0.180)) * 15
    return int(round(ops_component + k_component + bb_component))


def build_pitcher_summary(df):
    ps = aggregate_rows(df, ["pitcherAbbrevName", "pitcherHand"])
    if ps.empty:
        return ps

    ps["Pitcher Score"] = ps.apply(
        lambda r: pitcher_score(r["OPS_num"], r["K_pct_num"], r["BB_pct_num"]),
        axis=1,
    )
    ps = ps.sort_values(
        by=["Pitcher Score", "OPS_num", "K_pct_num"],
        ascending=[False, True, False],
    ).reset_index(drop=True)
    ps["Rank"] = range(1, len(ps) + 1)
    return ps


def build_split_rows_for_pitcher(pitcher_df):
    rows = []

    def make_row(label, subdf):
        if subdf.empty:
            return None
        r = team_total_row(subdf)
        return {
            "Split": label,
            "PA": int(r["PA"]),
            "OPS": r["OPS"],
            "OPS_num": r["OPS_num"],
        }

    for label, subdf in [
        ("TOTAL", pitcher_df),
        ("vs RHH", pitcher_df[pitcher_df["batterHand"].astype(str).str.upper() == "R"]),
        ("vs LHH", pitcher_df[pitcher_df["batterHand"].astype(str).str.upper() == "L"]),
    ]:
        row = make_row(label, subdf)
        if row:
            rows.append(row)

    return pd.DataFrame(rows)


# =====================================================
# REPORTLAB STYLES
# =====================================================

def p(text, style):
    return Paragraph(str(text), style)


def get_pdf_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleBig", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=24, leading=27, textColor=colors.HexColor(BLUE), alignment=0,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontSize=8.5,
            textColor=colors.HexColor("#333333"), leading=10,
        ),
        "section": ParagraphStyle(
            "Section", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=13, textColor=colors.HexColor(BLUE),
        ),
        "small": ParagraphStyle(
            "Small", parent=base["Normal"], fontSize=7, leading=8,
            textColor=colors.HexColor("#333333"),
        ),
        "small_white": ParagraphStyle(
            "SmallWhite", parent=base["Normal"], fontSize=7, leading=8,
            textColor=colors.white, alignment=1,
        ),
        "card_label": ParagraphStyle(
            "CardLabel", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=6.6, leading=7.5, textColor=colors.HexColor(BLUE), alignment=1,
        ),
        "card_value": ParagraphStyle(
            "CardValue", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=14, leading=15, textColor=colors.HexColor(BLACK), alignment=1,
        ),
        "card_sub": ParagraphStyle(
            "CardSub", parent=base["Normal"], fontSize=7, leading=8,
            textColor=colors.HexColor(BLACK), alignment=1,
        ),
        "note": ParagraphStyle(
            "Note", parent=base["Italic"], fontSize=7, leading=8,
            textColor=colors.HexColor("#444444"),
        ),
    }


class NumberedCanvas(canvas_module.Canvas):
    def __init__(self, *args, logo_bytes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.logo_bytes = logo_bytes

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_header(page_count)
            super().showPage()
        super().save()

    def draw_page_header(self, page_count):
        page_num = self._pageNumber
        width, height = PAGE_W, PAGE_H

        self.saveState()

        # Blue top strip and red underline
        self.setFillColor(colors.HexColor(BLUE))
        self.rect(0, height - 0.32 * inch, width, 0.32 * inch, fill=1, stroke=0)
        self.setFillColor(colors.HexColor(RED))
        self.rect(0, height - 0.36 * inch, width, 0.04 * inch, fill=1, stroke=0)

        # Logo box
        logo_x = 0.25 * inch
        logo_y = height - 0.88 * inch
        logo_size = 0.62 * inch

        if self.logo_bytes:
            try:
                img = ImageReader(BytesIO(self.logo_bytes))
                self.drawImage(img, logo_x, logo_y, width=logo_size, height=logo_size, preserveAspectRatio=True, mask="auto")
            except Exception:
                self._draw_default_logo(logo_x, logo_y, logo_size)
        else:
            self._draw_default_logo(logo_x, logo_y, logo_size)

        # Big title
        self.setFillColor(colors.HexColor(BLUE))
        self.setFont("Helvetica-Bold", 20)
        self.drawString(1.05 * inch, height - 0.57 * inch, "HITTER VS PITCHER")
        self.drawString(1.05 * inch, height - 0.83 * inch, "MATCHUP REPORT")

        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#333333"))
        self.drawString(1.05 * inch, height - 0.98 * inch, f"Generated on {datetime.now().strftime('%B %d, %Y')}")

        # Page label top right
        self.setFillColor(colors.white)
        self.setFont("Helvetica-Bold", 8.5)
        self.drawRightString(width - 0.25 * inch, height - 0.205 * inch, f"PAGE {page_num} OF {page_count}")

        self.restoreState()

    def _draw_default_logo(self, x, y, size):
        self.setFillColor(colors.HexColor(BLUE))
        self.rect(x, y, size, size, fill=1, stroke=0)
        self.setFillColor(colors.white)
        self.setFont("Helvetica-Bold", 26)
        self.drawCentredString(x + size / 2, y + size * 0.25, "T")


# =====================================================
# PDF COMPONENTS
# =====================================================

def section_header(title, styles):
    title_tbl = Table(
        [[p(title, styles["section"]), ""]],
        colWidths=[2.35 * inch, CONTENT_W - 2.35 * inch],
    )
    title_tbl.setStyle(TableStyle([
        ("LINEBELOW", (1, 0), (1, 0), 1.0, colors.HexColor(RED)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
    ]))
    return title_tbl


def legend_box(styles):
    data = [[
        p("<b>LEGEND</b><br/><font size='6'>(Based on OPS Allowed)</font>", styles["small"]),
        p("<font color='#B00020'>●</font> Elite (OPS &lt; .650)", styles["small"]),
        p("<font color='#8E8E8E'>●</font> Average (.650 - .800)", styles["small"]),
        p("<font color='#188038'>●</font> Damage (OPS &gt; .800)", styles["small"]),
    ]]
    tbl = Table(data, colWidths=[1.35 * inch, 1.55 * inch, 1.75 * inch, 1.75 * inch])
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAFBFC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def icon_card(label, value, subtext, badge, badge_color, styles, width=1.95 * inch):
    """Small summary card. If CARD_ICON_BYTES is available, use baseball.png instead of text badges."""
    global CARD_ICON_BYTES

    badge_style = ParagraphStyle(
        "Badge", parent=styles["card_label"], textColor=colors.white,
        fontSize=10, leading=11, alignment=1,
    )

    if CARD_ICON_BYTES:
        try:
            badge_cell = Image(BytesIO(CARD_ICON_BYTES), width=0.22 * inch, height=0.22 * inch)
        except Exception:
            badge_cell = p(badge, badge_style)
    else:
        badge_cell = p(badge, badge_style)

    data = [[
        badge_cell,
        p(f"<b>{label}</b>", styles["card_label"]),
    ], [
        "",
        p(value, styles["card_value"]),
    ], [
        "",
        p(subtext, styles["card_sub"]),
    ]]

    tbl = Table(data, colWidths=[0.36 * inch, width - 0.36 * inch], rowHeights=[0.25 * inch, 0.31 * inch, 0.22 * inch])
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor(BORDER)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(badge_color)),
        ("SPAN", (0, 1), (0, 2)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tbl


def executive_summary_cards(df, styles):
    min3 = df[df["PA"] >= 3].copy()
    if min3.empty:
        min3 = df.copy()

    best_ops = min3.sort_values(["OPS_num", "PA"], ascending=[False, False]).iloc[0]
    worst_ops = min3.sort_values(["OPS_num", "PA"], ascending=[True, False]).iloc[0]
    highest_pa = df.sort_values(["PA", "OPS_num"], ascending=[False, False]).iloc[0]
    highest_k = min3.sort_values(["K_pct_num", "PA"], ascending=[False, False]).iloc[0]
    highest_bb = min3.sort_values(["BB_pct_num", "PA"], ascending=[False, False]).iloc[0]

    def matchup(row):
        return f"{row['pitcherAbbrevName']} vs {row['batterAbbrevName']}"

    cards = [
        icon_card("BEST OPS MATCHUP", matchup(best_ops), f"{best_ops['OPS']} OPS | PA: {int(best_ops['PA'])}", "OPS", RED, styles),
        icon_card("WORST OPS MATCHUP", matchup(worst_ops), f"{worst_ops['OPS']} OPS | PA: {int(worst_ops['PA'])}", "LOW", GREEN, styles),
        icon_card("HIGHEST PA MATCHUP", matchup(highest_pa), f"PA: {int(highest_pa['PA'])} | {highest_pa['OPS']} OPS", "PA", BLUE, styles),
        icon_card("HIGHEST K% MATCHUP", matchup(highest_k), f"{highest_k['K%']} K% | PA: {int(highest_k['PA'])}", "K", BLUE, styles),
        icon_card("HIGHEST BB% MATCHUP", matchup(highest_bb), f"{highest_bb['BB%']} BB% | PA: {int(highest_bb['PA'])}", "BB", BLUE, styles),
    ]
    tbl = Table([cards], colWidths=[CONTENT_W / 5] * 5)
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl


def team_snapshot_cards(df, pitcher_summary, styles):
    team = team_total_row(df)
    pitchers_used = df["pitcherAbbrevName"].nunique()
    min3_pitchers = pitcher_summary[pitcher_summary["PA"] >= 3]

    ops_rank = "-"
    k_rank = "-"
    bb_rank = "-"
    if not pitcher_summary.empty:
        ops_sorted = pitcher_summary.sort_values("OPS_num", ascending=True).reset_index(drop=True)
        k_sorted = pitcher_summary.sort_values("K_pct_num", ascending=False).reset_index(drop=True)
        bb_sorted = pitcher_summary.sort_values("BB_pct_num", ascending=True).reset_index(drop=True)
        team_ops = team["OPS_num"]
        team_k = team["K_pct_num"]
        team_bb = team["BB_pct_num"]
        ops_rank = f"Team total"
        k_rank = f"Team total"
        bb_rank = f"Team total"

    cards = [
        icon_card("TEAM OPS ALLOWED", team["OPS"], ops_rank, "OPS", ops_band_color(team["OPS_num"]), styles),
        icon_card("TEAM K%", team["K%"], k_rank, "K", GREEN, styles),
        icon_card("TEAM BB%", team["BB%"], bb_rank, "BB", RED, styles),
        icon_card("TOTAL PA", f"{int(team['PA']):,}", "Across all matchups", "PA", BLUE, styles),
        icon_card("PITCHERS USED", f"{pitchers_used}", f"{len(min3_pitchers)} with 3+ PA", "P", BLUE, styles),
    ]
    tbl = Table([cards], colWidths=[CONTENT_W / 5] * 5)
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl


def staff_leaderboard_table(pitcher_summary, styles, max_rows=10):
    """
    Compact leaderboard requested by user:
    - Rows 1-6: best 6 pitchers by Pitcher Score
    - Row 7: divider row "..."
    - Rows 8-10: bottom 3 pitchers by Pitcher Score
    """
    ps = pitcher_summary.copy().reset_index(drop=True)

    headers = ["RANK", "PITCHER", "THROWS", "PA", "OPS ALLOWED", "K%", "BB%", "PITCHER SCORE"]
    data = [headers]
    row_meta = []

    if len(ps) <= 10:
        display_rows = [("data", r) for _, r in ps.iterrows()]
    else:
        best = [("data", r) for _, r in ps.head(6).iterrows()]
        divider = [("divider", None)]
        bottom = [("data", r) for _, r in ps.tail(3).iterrows()]
        display_rows = best + divider + bottom

    for row_type, r in display_rows:
        if row_type == "divider":
            data.append(["...", "...", "...", "...", "...", "...", "...", "..."])
            row_meta.append(("divider", None))
            continue

        bar_count = max(1, min(12, int(round(r["Pitcher Score"] / 8))))
        bar = "█" * bar_count
        data.append([
            int(r["Rank"]),
            r["pitcherAbbrevName"],
            hand_label(r["pitcherHand"]),
            int(r["PA"]),
            r["OPS"],
            r["K%"],
            r["BB%"],
            f"{int(r['Pitcher Score'])}  {bar}",
        ])
        row_meta.append(("data", r))

    col_widths = [0.50 * inch, 1.55 * inch, 0.75 * inch, 0.50 * inch, 1.05 * inch, 0.75 * inch, 0.75 * inch, 2.10 * inch]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BLUE)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(BORDER)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(LIGHT_GRAY)]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]

    for table_row_idx, (row_type, r) in enumerate(row_meta, start=1):
        if row_type == "divider":
            style += [
                ("SPAN", (0, table_row_idx), (-1, table_row_idx)),
                ("BACKGROUND", (0, table_row_idx), (-1, table_row_idx), colors.HexColor("#E6EAF0")),
                ("TEXTCOLOR", (0, table_row_idx), (-1, table_row_idx), colors.HexColor(BLUE)),
                ("FONTNAME", (0, table_row_idx), (-1, table_row_idx), "Helvetica-Bold"),
                ("ALIGN", (0, table_row_idx), (-1, table_row_idx), "CENTER"),
            ]
            continue

        style.append(("BACKGROUND", (4, table_row_idx), (4, table_row_idx), colors.HexColor(ops_band_color(r["OPS_num"]))))
        style.append(("TEXTCOLOR", (4, table_row_idx), (4, table_row_idx), colors.white))
        style.append(("FONTNAME", (4, table_row_idx), (4, table_row_idx), "Helvetica-Bold"))
        style.append(("TEXTCOLOR", (7, table_row_idx), (7, table_row_idx), colors.HexColor(BLUE)))
        style.append(("FONTNAME", (7, table_row_idx), (7, table_row_idx), "Helvetica-Bold"))

    tbl.setStyle(TableStyle(style))
    return tbl

def split_table(split_df, styles, width):
    data = [["SPLIT", "PA", "OPS"]]
    for _, r in split_df.iterrows():
        data.append([r["Split"], int(r["PA"]), r["OPS"]])

    tbl = Table(data, colWidths=[width * 0.48, width * 0.22, width * 0.30])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BLUE)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 5.6),
        ("FONTSIZE", (0, 1), (-1, -1), 5.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.20, colors.HexColor(BORDER)),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for i, (_, r) in enumerate(split_df.iterrows(), start=1):
        style.append(("BACKGROUND", (2, i), (2, i), colors.HexColor(ops_light_fill(r["OPS_num"]))))
        style.append(("TEXTCOLOR", (2, i), (2, i), colors.HexColor(ops_band_color(r["OPS_num"]))))
        style.append(("FONTNAME", (2, i), (2, i), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return tbl


def threats_table(pitcher_df, styles, width, max_threats=3):
    threats = pitcher_df.sort_values(["OPS_num", "PA"], ascending=[False, False]).head(max_threats)
    data = [["BIGGEST THREATS", "PA", "OPS"]]
    for i, (_, r) in enumerate(threats.iterrows(), start=1):
        data.append([f"{i}. {r['batterAbbrevName']}", int(r["PA"]), r["OPS"]])

    tbl = Table(data, colWidths=[width * 0.58, width * 0.17, width * 0.25])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BLUE)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 5.6),
        ("FONTSIZE", (0, 1), (-1, -1), 5.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.20, colors.HexColor(BORDER)),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for i, (_, r) in enumerate(threats.iterrows(), start=1):
        style.append(("TEXTCOLOR", (2, i), (2, i), colors.HexColor(ops_band_color(r["OPS_num"]))))
        style.append(("FONTNAME", (2, i), (2, i), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return tbl


def kpi_tiles(total_row, styles, width):
    ops_color = ops_band_color(total_row["OPS_num"])
    k_color = k_text_color(total_row["K_pct_num"])
    bb_color = bb_text_color(total_row["BB_pct_num"])

    label_style = ParagraphStyle("KPIlabel", parent=styles["small"], fontName="Helvetica-Bold", fontSize=5.4, leading=6, textColor=colors.HexColor(BLUE), alignment=1)
    value_style = ParagraphStyle("KPIvalue", parent=styles["small"], fontName="Helvetica-Bold", fontSize=11, leading=12, alignment=1)

    data = [[
        p("OPS ALLOWED", label_style),
        p("K%", label_style),
        p("BB%", label_style),
    ], [
        p(f"<font color='{ops_color}'>{total_row['OPS']}</font>", value_style),
        p(f"<font color='{k_color}'>{total_row['K%']}</font>", value_style),
        p(f"<font color='{bb_color}'>{total_row['BB%']}</font>", value_style),
    ]]
    tbl = Table(data, colWidths=[width / 3] * 3, rowHeights=[0.18 * inch, 0.30 * inch])
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor(BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.20, colors.HexColor(BORDER)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return tbl


def pitcher_card(pitcher_name, pitcher_df, styles, card_w, max_threats=3):
    total = team_total_row(pitcher_df)
    header_color = ops_band_color(total["OPS_num"])

    header_style = ParagraphStyle("CardHeader", parent=styles["small"], fontName="Helvetica-Bold", fontSize=7.5, leading=8.5, textColor=colors.white, alignment=0)
    header_right_style = ParagraphStyle("CardHeaderRight", parent=styles["small"], fontName="Helvetica-Bold", fontSize=7.5, leading=8.5, textColor=colors.white, alignment=2)

    p_hand = hand_label(pitcher_df["pitcherHand"].iloc[0])
    header = Table(
        [[p(f"{pitcher_name} ({p_hand})", header_style), p(f"{int(total['PA'])} PA", header_right_style)]],
        colWidths=[card_w * 0.70, card_w * 0.30],
        rowHeights=[0.26 * inch],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(header_color)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))

    split_df = build_split_rows_for_pitcher(pitcher_df)

    body = [
        [header],
        [kpi_tiles(total, styles, card_w)],
        [split_table(split_df, styles, card_w)],
        [threats_table(pitcher_df, styles, card_w, max_threats=max_threats)],
    ]
    tbl = Table(body, colWidths=[card_w])
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.05, colors.HexColor("#4A5568")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


def pitcher_cards_pages(df, styles, max_threats=3):
    elements = []
    pitchers = list(df.groupby("pitcherAbbrevName", sort=True))
    card_w = (CONTENT_W - 0.42 * inch) / 3

    for page_start in range(0, len(pitchers), 6):
        chunk = pitchers[page_start:page_start + 6]

        if page_start == 0:
            elements.append(section_header("PITCHER MATCHUP OVERVIEW  (6 PER PAGE)", styles))
            elements.append(Spacer(1, 6))

        rows = []
        for row_start in range(0, len(chunk), 3):
            card_row = []
            for name, pdf in chunk[row_start:row_start + 3]:
                card_row.append(pitcher_card(name, pdf, styles, card_w, max_threats=max_threats))
            while len(card_row) < 3:
                card_row.append("")
            rows.append(card_row)

        grid = Table(rows, colWidths=[card_w] * 3, rowHeights=[2.82 * inch] * len(rows))
        grid.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        elements.append(grid)

        if page_start + 6 < len(pitchers):
            elements.append(PageBreak())
            elements.append(section_header("PITCHER MATCHUP OVERVIEW  (6 PER PAGE)", styles))
            elements.append(Spacer(1, 6))

    return elements


# =====================================================
# PDF CREATION
# =====================================================

def create_front_office_pdf(df, logo_bytes=None, card_icon_bytes=None, max_threats=3, min_pa_for_cards=1, leaderboard_rows=10):
    global CARD_ICON_BYTES
    CARD_ICON_BYTES = card_icon_bytes

    buffer = BytesIO()
    styles = get_pdf_styles()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=PDF_RIGHT,
        leftMargin=PDF_LEFT,
        topMargin=PDF_TOP,
        bottomMargin=PDF_BOTTOM,
    )

    story = []
    working = df.copy()
    if min_pa_for_cards > 1:
        working = working[working["PA"] >= min_pa_for_cards].copy()

    pitcher_summary = build_pitcher_summary(working)

    # Top right legend directly under header
    legend = Table([["", legend_box(styles)]], colWidths=[CONTENT_W - 6.45 * inch, 6.45 * inch])
    legend.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(legend)
    story.append(Spacer(1, 8))

    story.append(section_header("EXECUTIVE SUMMARY", styles))
    story.append(Spacer(1, 6))
    story.append(executive_summary_cards(working, styles))
    story.append(Spacer(1, 8))

    story.append(section_header("TEAM PITCHING SNAPSHOT", styles))
    story.append(Spacer(1, 6))
    story.append(team_snapshot_cards(working, pitcher_summary, styles))
    story.append(Spacer(1, 8))

    story.append(section_header("STAFF LEADERBOARD  (MINIMUM SELECTED PA)", styles))
    story.append(Spacer(1, 6))
    story.append(staff_leaderboard_table(pitcher_summary, styles, max_rows=leaderboard_rows))
    story.append(Spacer(1, 8))

    # No forced page break here. This prevents a nearly blank second page when
    # the leaderboard note/footer alone spills over. ReportLab will naturally
    # start the pitcher overview on the next page if needed.
    story.extend(pitcher_cards_pages(working, styles, max_threats=max_threats))
    story.append(Spacer(1, 6))
    story.append(p("Note: Pitcher cards show selected PA filters. Biggest Threats are sorted by OPS, then PA.", styles["note"]))

    canvas_factory = partial(NumberedCanvas, logo_bytes=logo_bytes)
    doc.build(story, canvasmaker=canvas_factory)

    buffer.seek(0)
    return buffer


# =====================================================
# DISPLAY HELPERS
# =====================================================

def rename_for_display(df):
    return df.rename(columns={
        "pitcherAbbrevName": "Pitcher",
        "pitcherHand": "P/T",
        "batterAbbrevName": "Hitter",
        "batterHand": "B/T",
        "Hits": "H",
        "Single": "1B",
        "Double": "2B",
        "Triple": "3B",
        "Homerun": "HR",
    })


# =====================================================
# LOCAL ASSET HELPERS
# =====================================================

def load_local_baseball_icon():
    """Try to use baseball.png from the same folder as app.py when no upload is provided."""
    for path in ["baseball.png", "./baseball.png"]:
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            pass
    return None


# =====================================================
# APP UI
# =====================================================

uploaded_file = st.file_uploader("Upload pitch-by-pitch CSV", type=["csv"])

if not uploaded_file:
    st.info("Upload your CSV to generate matchup data.")
    st.stop()

try:
    raw_df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

missing = [c for c in REQUIRED_COLUMNS if c not in raw_df.columns]
if missing:
    st.error(f"Missing columns: {missing}")
    st.stop()

matchup_df = build_matchups(raw_df)
if matchup_df.empty:
    st.warning("No matchup rows were created from this CSV.")
    st.stop()

st.sidebar.header("Filters")
pitchers = sorted(matchup_df["pitcherAbbrevName"].dropna().unique())
hitters = sorted(matchup_df["batterAbbrevName"].dropna().unique())

selected_pitcher = st.sidebar.multiselect("Pitcher", pitchers)
selected_hitter = st.sidebar.multiselect("Hitter", hitters)
selected_pitcher_hand = st.sidebar.multiselect("Pitcher Hand", sorted(matchup_df["pitcherHand"].dropna().unique()))
selected_batter_hand = st.sidebar.multiselect("Batter Hand", sorted(matchup_df["batterHand"].dropna().unique()))
min_pa = st.sidebar.number_input("Minimum PA", min_value=1, value=1)

view = matchup_df.copy()
if selected_pitcher:
    view = view[view["pitcherAbbrevName"].isin(selected_pitcher)]
if selected_hitter:
    view = view[view["batterAbbrevName"].isin(selected_hitter)]
if selected_pitcher_hand:
    view = view[view["pitcherHand"].isin(selected_pitcher_hand)]
if selected_batter_hand:
    view = view[view["batterHand"].isin(selected_batter_hand)]
view = view[view["PA"] >= min_pa]

st.subheader("Matchup Table")
display_view = rename_for_display(
    view.drop(columns=[
        "BA_num", "OBP_num", "SLG_num", "OPS_num", "BB_pct_num", "K_pct_num",
        "Walks", "HBP", "Strikeouts", "Total Bases",
    ], errors="ignore")
)
st.dataframe(display_view, use_container_width=True, hide_index=True)

st.sidebar.divider()
st.sidebar.header("PDF Export")
team_logo = st.sidebar.file_uploader("Upload team logo for PDF header", type=["png", "jpg", "jpeg"])
card_icon_file = st.sidebar.file_uploader("Upload baseball.png for summary/snapshot icons", type=["png"])
pdf_min_pa = st.sidebar.number_input("PDF minimum PA", min_value=1, value=3)
max_threats = st.sidebar.slider("Threats per pitcher card", min_value=2, max_value=5, value=3)
leaderboard_rows = 10

pdf_scope = st.sidebar.selectbox(
    "PDF Scope",
    ["Current filtered table", "Full report", "Only selected pitcher", "Only selected hitter"],
)
pdf_pitcher = st.sidebar.selectbox("PDF selected pitcher", [""] + pitchers)
pdf_hitter = st.sidebar.selectbox("PDF selected hitter", [""] + hitters)

if pdf_scope == "Current filtered table":
    pdf_df = view.copy()
elif pdf_scope == "Full report":
    pdf_df = matchup_df.copy()
elif pdf_scope == "Only selected pitcher":
    pdf_df = matchup_df[matchup_df["pitcherAbbrevName"] == pdf_pitcher].copy() if pdf_pitcher else view.copy()
elif pdf_scope == "Only selected hitter":
    pdf_df = matchup_df[matchup_df["batterAbbrevName"] == pdf_hitter].copy() if pdf_hitter else view.copy()
else:
    pdf_df = view.copy()

pdf_df = pdf_df[pdf_df["PA"] >= pdf_min_pa].copy()

csv = display_view.to_csv(index=False).encode("utf-8")
col1, col2 = st.columns([1, 1])

with col1:
    st.download_button(
        "Download CSV",
        csv,
        "hitter_pitcher_matchups.csv",
        "text/csv",
    )

with col2:
    if pdf_df.empty:
        st.warning("No rows available for the selected PDF options.")
    else:
        logo_bytes = team_logo.getvalue() if team_logo is not None else None
        card_icon_bytes = card_icon_file.getvalue() if card_icon_file is not None else load_local_baseball_icon()
        pdf_file = create_front_office_pdf(
            pdf_df,
            logo_bytes=logo_bytes,
            card_icon_bytes=card_icon_bytes,
            max_threats=max_threats,
            min_pa_for_cards=1,
            leaderboard_rows=leaderboard_rows,
        )
        st.download_button(
            "📄 Export Front Office PDF",
            data=pdf_file,
            file_name="hitter_pitcher_matchup_report.pdf",
            mime="application/pdf",
        )
