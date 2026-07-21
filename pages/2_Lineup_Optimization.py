
import streamlit as st
from ui_styles import apply_page_style
apply_page_style()
import pandas as pd
import numpy as np
import html
from html import unescape
from datetime import date
from io import BytesIO, StringIO
import tempfile
import os
import re
import json
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse
from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor
from urllib.error import URLError, HTTPError
import http.cookiejar
from datetime import timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.units import inch
from reportlab.platypus import Table, TableStyle
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image

st.set_page_config(page_title="Lineup Optimization", layout="wide")

REQUIRED_STATS = ["AVG", "OBP", "SLG", "ISO", "SB"]

POSITION_REQUIREMENTS = {
    "C": 1,
    "1B": 1,
    "2B": 1,
    "3B": 1,
    "SS": 1,
    "OF": 3,
    "DH": 1,
}

LINEUP_SPOT_WEIGHTS = {
    1: {"AVG": 0.15, "OBP": 0.45, "SLG": 0.15, "ISO": 0.05, "SB": 0.20},
    2: {"AVG": 0.20, "OBP": 0.35, "SLG": 0.25, "ISO": 0.10, "SB": 0.10},
    3: {"AVG": 0.20, "OBP": 0.25, "SLG": 0.30, "ISO": 0.20, "SB": 0.05},
    4: {"AVG": 0.10, "OBP": 0.20, "SLG": 0.35, "ISO": 0.30, "SB": 0.05},
    5: {"AVG": 0.15, "OBP": 0.20, "SLG": 0.35, "ISO": 0.25, "SB": 0.05},
    6: {"AVG": 0.20, "OBP": 0.25, "SLG": 0.25, "ISO": 0.15, "SB": 0.15},
    7: {"AVG": 0.20, "OBP": 0.25, "SLG": 0.20, "ISO": 0.10, "SB": 0.25},
    8: {"AVG": 0.20, "OBP": 0.25, "SLG": 0.20, "ISO": 0.10, "SB": 0.25},
    9: {"AVG": 0.15, "OBP": 0.30, "SLG": 0.15, "ISO": 0.05, "SB": 0.35},
}


# =====================================================
# BASIC HELPERS
# =====================================================

def clean_colnames(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def find_column(df, possible_names):
    lower_map = {c.lower(): c for c in df.columns}
    for name in possible_names:
        if name.lower() in lower_map:
            return lower_map[name.lower()]
    return None


def normalize_position(pos):
    if pd.isna(pos):
        return ""
    pos = str(pos).upper().strip()
    pos = pos.replace("LF", "OF").replace("CF", "OF").replace("RF", "OF")
    return pos


def normalize_bats(value):
    if pd.isna(value):
        return "R"
    side = str(value).strip().upper()
    left_values = ["L", "LEFT", "LHH", "LH", "LEFT-HANDED", "LEFT HANDED"]
    right_values = ["R", "RIGHT", "RHH", "RH", "RIGHT-HANDED", "RIGHT HANDED"]
    switch_values = ["S", "SW", "SWITCH", "BOTH", "SH", "SWITCH-HITTER", "SWITCH HITTER"]
    if side in left_values:
        return "L"
    if side in right_values:
        return "R"
    if side in switch_values:
        return "S"
    return side


def hitter_name_color(side):
    side = normalize_bats(side)
    if side == "L":
        return "#BA0C2F"
    if side == "S":
        return "#002D72"
    return "#111111"


def player_eligible_for_position(player_pos, required_pos):
    player_pos = normalize_position(player_pos)
    if required_pos == "DH":
        return True
    positions = [p.strip() for p in player_pos.replace(",", "/").split("/")]
    if required_pos == "OF":
        return "OF" in positions
    return required_pos in positions


def normalize_stats(df, stat_cols):
    df = df.copy()
    for col in stat_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    normalized = pd.DataFrame(index=df.index)
    for col in stat_cols:
        min_val = df[col].min()
        max_val = df[col].max()
        if max_val == min_val:
            normalized[col] = 0.5
        else:
            normalized[col] = (df[col] - min_val) / (max_val - min_val)
    return normalized


def calculate_overall_score(df, weights):
    total_weight = sum(weights.values()) or 1
    normalized = normalize_stats(df, REQUIRED_STATS)
    score = np.zeros(len(df))
    for stat, weight in weights.items():
        score += normalized[stat] * (weight / total_weight)
    return score


def calculate_spot_fit_score(row, spot, normalized_df, user_weights):
    spot_weights = LINEUP_SPOT_WEIGHTS[spot]
    user_total = max(sum(user_weights.values()), 1)
    combined_weights = {}
    for stat in REQUIRED_STATS:
        combined_weights[stat] = (spot_weights[stat] * 0.60) + (
            user_weights[stat] / user_total * 0.40
        )

    score = 0
    for stat in REQUIRED_STATS:
        score += normalized_df.loc[row.name, stat] * combined_weights[stat]
    return score


def select_best_9_no_positions(df):
    return df.sort_values("Overall Score", ascending=False).head(9).copy()


def select_best_9_with_positions(df, position_col):
    selected_rows = []
    used_indexes = set()

    for required_pos, count_needed in POSITION_REQUIREMENTS.items():
        eligible = df[
            (~df.index.isin(used_indexes))
            & (df[position_col].apply(lambda p: player_eligible_for_position(p, required_pos)))
        ].sort_values("Overall Score", ascending=False)

        if len(eligible) < count_needed:
            st.warning(
                f"Not enough eligible players for {required_pos}. Needed {count_needed}, found {len(eligible)}."
            )
            continue

        chosen = eligible.head(count_needed)
        selected_rows.append(chosen)
        used_indexes.update(chosen.index.tolist())

    if not selected_rows:
        return pd.DataFrame()

    selected = pd.concat(selected_rows)

    if len(selected) < 9:
        remaining = df[~df.index.isin(selected.index)].sort_values("Overall Score", ascending=False)
        selected = pd.concat([selected, remaining.head(9 - len(selected))])

    return selected.head(9).copy()


def optimize_order(selected_df, user_weights):
    selected_df = selected_df.copy()
    normalized = normalize_stats(selected_df, REQUIRED_STATS)
    remaining = selected_df.copy()
    lineup_rows = []

    for spot in range(1, 10):
        scores = []
        for idx, row in remaining.iterrows():
            spot_score = calculate_spot_fit_score(row, spot, normalized, user_weights)
            scores.append((idx, spot_score))

        best_idx, best_score = max(scores, key=lambda x: x[1])
        best_row = remaining.loc[best_idx].copy()
        best_row["Lineup Spot"] = spot
        best_row["Spot Fit Score"] = round(best_score, 4)
        lineup_rows.append(best_row)
        remaining = remaining.drop(best_idx)

    lineup = pd.DataFrame(lineup_rows)
    display_cols = ["Lineup Spot", "playerFullName"]

    # Keep Position available internally for optional defensive requirements,
    # but do not display it in optimized lineup tables.
    if "Bats" in lineup.columns:
        display_cols.append("Bats")
    if "PA" in lineup.columns:
        display_cols.append("PA")

    display_cols += REQUIRED_STATS + ["Overall Score", "Spot Fit Score"]
    return lineup[display_cols]


def format_decimal(value):
    try:
        return f"{float(value):.3f}".replace("0.", ".")
    except Exception:
        return str(value)


def format_cell(value, col):
    if pd.isna(value):
        return ""
    if col in ["AVG", "OBP", "SLG", "ISO"]:
        return format_decimal(value)
    if col in ["Overall Score", "Spot Fit Score"]:
        try:
            return f"{float(value):.4f}"
        except Exception:
            return str(value)
    if col in ["SB", "PA"]:
        try:
            return f"{int(float(value))}"
        except Exception:
            return str(value)
    return str(value)


# =====================================================
# DATA PREP
# =====================================================

def prepare_dataframe(uploaded_file, label):
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Could not read {label} CSV: {e}")
        return None

    df = clean_colnames(df)

    name_col = find_column(df, ["playerFullName", "PlayerFullName", "player_name", "playerName", "Name", "Player"])
    if name_col is None:
        st.error(f"Could not find a player name column in {label}. The app expects `playerFullName`.")
        return None

    df["playerFullName"] = df[name_col].astype(str).str.strip()
    bad_names = ["", "none", "nan", "null", "unknown"]
    df = df[~df["playerFullName"].str.lower().isin(bad_names)].copy()

    missing_stats = [stat for stat in REQUIRED_STATS if stat not in df.columns]
    if missing_stats:
        st.error(f"Missing required stat columns in {label}: {missing_stats}")
        st.write("Your CSV must include:", REQUIRED_STATS)
        return None

    for stat in REQUIRED_STATS:
        df[stat] = pd.to_numeric(df[stat], errors="coerce").fillna(0)

    pa_col = find_column(df, ["PA", "pa", "PlateAppearances", "plateAppearances", "Plate Appearances"])
    if pa_col:
        df["PA"] = pd.to_numeric(df[pa_col], errors="coerce").fillna(0).astype(int)
    else:
        df["PA"] = 0

    position_col = find_column(df, ["Position", "position", "POS", "pos", "PrimaryPosition", "primaryPosition"])
    if position_col:
        df["Position"] = df[position_col].apply(normalize_position)

    bats_col = find_column(
        df,
        [
            "batsHand", "BatsHand", "batshand", "BATS HAND", "Bats Hand",
            "Bats", "bats", "BatSide", "batSide", "BatterSide", "batterSide",
            "HitterSide", "hitterSide", "Side", "side", "battingSide", "BattingSide",
            "BatterHand", "batterHand", "HitterHand", "hitterHand", "BatHand", "batHand",
            "Bats/Throws", "BatsThrows",
        ],
    )
    if bats_col:
        df["Bats"] = df[bats_col].apply(normalize_bats)
    else:
        df["Bats"] = "R"

    return df


def build_lineup(df, weights, enforce_positions, label):
    df = df.copy()
    df["Overall Score"] = calculate_overall_score(df, weights)
    df["Overall Score"] = df["Overall Score"].round(4)

    if len(df) < 9:
        st.error(f"{label}: You need at least 9 players in the CSV.")
        return None, df

    can_enforce = enforce_positions and "Position" in df.columns
    if enforce_positions and not can_enforce:
        st.warning(f"{label}: No position column found. Position requirements were ignored.")

    if can_enforce:
        selected = select_best_9_with_positions(df, "Position")
    else:
        selected = select_best_9_no_positions(df)

    if len(selected) < 9:
        st.error(f"{label}: Could not select 9 players. Check player pool and positions.")
        return None, df

    lineup = optimize_order(selected, weights)
    return lineup, df


def lineup_summary(lineup):
    if lineup is None or lineup.empty:
        return {"AVG": 0, "OBP": 0, "SLG": 0, "ISO": 0, "SB": 0, "PA": 0, "Score": 0}

    summary = {}
    total_pa = float(pd.to_numeric(lineup.get("PA", pd.Series([0] * len(lineup))), errors="coerce").fillna(0).sum())
    weights_pa = pd.to_numeric(lineup.get("PA", pd.Series([0] * len(lineup))), errors="coerce").fillna(0)

    for stat in ["AVG", "OBP", "SLG", "ISO"]:
        vals = pd.to_numeric(lineup[stat], errors="coerce").fillna(0)
        if total_pa > 0:
            summary[stat] = float((vals * weights_pa).sum() / total_pa)
        else:
            summary[stat] = float(vals.mean())

    summary["SB"] = int(pd.to_numeric(lineup["SB"], errors="coerce").fillna(0).sum())
    summary["PA"] = int(total_pa)
    summary["Score"] = float(pd.to_numeric(lineup["Spot Fit Score"], errors="coerce").fillna(0).sum())
    return summary


def total_avg_row(lineup):
    s = lineup_summary(lineup)
    return [
        "",
        "TOTAL/AVG",
        "—",
        str(s["PA"]),
        format_decimal(s["AVG"]),
        format_decimal(s["OBP"]),
        format_decimal(s["SLG"]),
        format_decimal(s["ISO"]),
        str(s["SB"]),
    ]


# =====================================================
# WEBSITE TABLE
# =====================================================

def render_lineup_table(lineup):
    cols = [c for c in lineup.columns if c not in ["Overall Score", "Spot Fit Score"]]
    table_html = """
    <style>
    .lineup-table {width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 15px;}
    .lineup-table th {background-color: #002D72; color: white; text-align: center; padding: 10px; border: 1px solid #d9d9d9; font-weight: 700;}
    .lineup-table td {padding: 9px; border: 1px solid #e1e1e1; text-align: center;}
    .lineup-table tr:nth-child(even) {background-color: #f7f7f7;}
    .lineup-table tr:nth-child(odd) {background-color: #ffffff;}
    .player-name-cell {text-align: left !important; font-weight: 800;}
    .total-row td {background-color: #E8EEF8 !important; color: #002D72; font-weight: 900;}
    </style>
    <table class="lineup-table"><thead><tr>
    """
    pretty_cols = {"Lineup Spot": "#", "playerFullName": "Player", "Bats": "B"}
    for col in cols:
        table_html += f"<th>{html.escape(pretty_cols.get(str(col), str(col)))}</th>"
    table_html += "</tr></thead><tbody>"

    for _, row in lineup.iterrows():
        table_html += "<tr>"
        bats = row["Bats"] if "Bats" in lineup.columns else "R"
        name_color = hitter_name_color(bats)
        for col in cols:
            value = format_cell(row[col], col)
            safe_value = html.escape(value)
            if col == "playerFullName":
                table_html += f'<td class="player-name-cell" style="color:{name_color};">{safe_value}</td>'
            else:
                table_html += f"<td>{safe_value}</td>"
        table_html += "</tr>"

    # Total / average row
    s = lineup_summary(lineup)
    total_values = {
        "Lineup Spot": "",
        "playerFullName": "TOTAL/AVG",
        "Bats": "—",
        "PA": s["PA"],
        "AVG": s["AVG"],
        "OBP": s["OBP"],
        "SLG": s["SLG"],
        "ISO": s["ISO"],
        "SB": s["SB"],
    }
    table_html += '<tr class="total-row">'
    for col in cols:
        table_html += f"<td>{html.escape(format_cell(total_values.get(col, ''), col))}</td>"
    table_html += "</tr>"

    table_html += "</tbody></table>"
    st.markdown(table_html, unsafe_allow_html=True)


def show_player_pool(df):
    preview_cols = ["playerFullName"]
    if "Position" in df.columns:
        preview_cols.append("Position")
    preview_cols.append("Bats")
    if "PA" in df.columns:
        preview_cols.append("PA")
    preview_cols += REQUIRED_STATS + ["Overall Score"]
    st.dataframe(
        df[preview_cols].sort_values("Overall Score", ascending=False),
        use_container_width=True,
        hide_index=True,
    )


# =====================================================
# BRANDING / COLORS
# =====================================================

def clamp(v):
    return max(0, min(255, int(v)))


def rgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(clamp(rgb[0]), clamp(rgb[1]), clamp(rgb[2]))


def luminance(rgb):
    r, g, b = [x / 255 for x in rgb]
    return 0.299 * r + 0.587 * g + 0.114 * b


def darken(rgb, factor=0.55):
    return tuple(clamp(x * factor) for x in rgb)


def extract_team_colors(logo_file):
    default_primary = (0, 45, 114)
    default_accent = (186, 12, 47)

    if logo_file is None:
        return default_primary, default_accent

    try:
        logo_file.seek(0)
        img = Image.open(logo_file).convert("RGBA")
        img.thumbnail((180, 180))

        pixels = []
        for r, g, b, a in img.getdata():
            if a < 120:
                continue
            # Skip nearly white / gray background
            if r > 235 and g > 235 and b > 235:
                continue
            if abs(r - g) < 12 and abs(g - b) < 12 and abs(r - b) < 12:
                continue
            pixels.append((r, g, b))

        if not pixels:
            return default_primary, default_accent

        # Quantize by color buckets
        buckets = {}
        for r, g, b in pixels:
            key = (round(r / 32) * 32, round(g / 32) * 32, round(b / 32) * 32)
            buckets[key] = buckets.get(key, 0) + 1

        ranked = sorted(buckets.items(), key=lambda x: x[1], reverse=True)
        colors_found = [c for c, _ in ranked]

        primary = colors_found[0]
        accent = default_accent

        for c in colors_found[1:]:
            # Select a second color that is visually different
            dist = sum((c[i] - primary[i]) ** 2 for i in range(3)) ** 0.5
            if dist > 90:
                accent = c
                break

        if luminance(primary) > 0.55:
            primary = darken(primary, 0.55)
        if luminance(accent) > 0.65:
            accent = darken(accent, 0.65)

        return primary, accent
    except Exception:
        return default_primary, default_accent


def save_logo_temp(logo_file):
    if logo_file is None:
        return None
    try:
        suffix = os.path.splitext(logo_file.name)[1] or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        logo_file.seek(0)
        tmp.write(logo_file.read())
        tmp.close()
        logo_file.seek(0)
        return tmp.name
    except Exception:
        return None


# =====================================================
# PDF EXPORT
# =====================================================

def draw_rounded_rect(c, x, y, w, h, radius=6, fill=colors.white, stroke=colors.HexColor("#DDDDDD"), stroke_width=1):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(stroke_width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def draw_metric_block(c, x, y, w, h, label, value, label_color, value_color, label_size=7.0, value_size=15.0):
    c.setStrokeColor(colors.HexColor("#E2E2E2"))
    c.setLineWidth(0.6)
    c.line(x + w, y + 5, x + w, y + h - 5)

    c.setFillColor(label_color)
    c.setFont("Helvetica-Bold", label_size)
    c.drawCentredString(x + w / 2, y + h - 15, label)

    c.setFillColor(value_color)
    c.setFont("Helvetica-Bold", value_size)
    c.drawCentredString(x + w / 2, y + 9, value)


def draw_logo(c, logo_path, x, y, max_w, max_h):
    if not logo_path:
        return
    try:
        img = ImageReader(logo_path)
        iw, ih = img.getSize()
        scale = min(max_w / iw, max_h / ih)
        w = iw * scale
        h = ih * scale
        c.drawImage(img, x + (max_w - w) / 2, y + (max_h - h) / 2, width=w, height=h, mask="auto")
    except Exception:
        pass


def pdf_table_data(lineup):
    rows = [["#", "PLAYER", "B", "PA", "AVG", "OBP", "SLG", "ISO", "SB"]]
    for _, row in lineup.iterrows():
        rows.append([
            format_cell(row.get("Lineup Spot", ""), "Lineup Spot"),
            str(row.get("playerFullName", "")),
            str(row.get("Bats", "")),
            format_cell(row.get("PA", 0), "PA"),
            format_cell(row.get("AVG", 0), "AVG"),
            format_cell(row.get("OBP", 0), "OBP"),
            format_cell(row.get("SLG", 0), "SLG"),
            format_cell(row.get("ISO", 0), "ISO"),
            format_cell(row.get("SB", 0), "SB"),
        ])

    rows.append(total_avg_row(lineup))
    return rows


def draw_lineup_panel(c, lineup, x, y, w, h, title, header_color):
    header_h = 30
    metrics_h = 39
    table_top_gap = 2

    # Outer panel
    draw_rounded_rect(c, x, y, w, h, radius=6, fill=colors.white, stroke=colors.HexColor("#D7D7D7"))

    # Big panel header
    c.setFillColor(header_color)
    c.roundRect(x, y + h - header_h, w, header_h, 6, fill=1, stroke=0)
    # Square off bottom of rounded header
    c.rect(x, y + h - header_h, w, 7, fill=1, stroke=0)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(x + w / 2, y + h - 20, title)

    # Metrics row
    s = lineup_summary(lineup)
    metric_y = y + h - header_h - metrics_h
    metric_w = w / 4

    metric_labels = ["Team AVG", "Team OBP", "Team SLG", "Projected Score"]
    metric_vals = [
        format_decimal(s["AVG"]),
        format_decimal(s["OBP"]),
        format_decimal(s["SLG"]),
        f"{s['Score']:.2f}",
    ]

    c.setFillColor(colors.white)
    c.rect(x, metric_y, w, metrics_h, fill=1, stroke=0)

    for i, (lab, val) in enumerate(zip(metric_labels, metric_vals)):
        value_color = colors.HexColor("#BA0C2F") if i == 3 else header_color
        draw_metric_block(
            c,
            x + i * metric_w,
            metric_y,
            metric_w,
            metrics_h,
            lab,
            val,
            colors.HexColor("#111111"),
            value_color,
            label_size=6.2,
            value_size=13.0,
        )

    # Table
    rows = pdf_table_data(lineup)
    col_widths = [
        w * 0.055,  # #
        w * 0.390,  # Player
        w * 0.070,  # Bats
        w * 0.085,  # PA
        w * 0.085,  # AVG
        w * 0.085,  # OBP
        w * 0.085,  # SLG
        w * 0.085,  # ISO
        w * 0.060,  # SB
    ]

    table_h = h - header_h - metrics_h - table_top_gap - 8
    row_h = table_h / len(rows)
    table = Table(rows, colWidths=col_widths, rowHeights=[row_h] * len(rows))

    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 6.0),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -2), "LEFT"),
        ("FONTNAME", (0, 1), (-1, -2), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -2), 5.7),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E1E1E1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF0FA")),
        ("TEXTCOLOR", (0, -1), (-1, -1), header_color),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 5.8),
    ])

    for r in range(1, len(rows) - 1):
        if r % 2 == 0:
            style.add("BACKGROUND", (0, r), (-1, r), colors.HexColor("#F7F8FB"))
        else:
            style.add("BACKGROUND", (0, r), (-1, r), colors.white)

        bats = rows[r][2]
        if bats == "L":
            style.add("TEXTCOLOR", (1, r), (1, r), colors.HexColor("#BA0C2F"))
            style.add("FONTNAME", (1, r), (1, r), "Helvetica-Bold")
        elif bats == "S":
            style.add("TEXTCOLOR", (1, r), (1, r), colors.HexColor("#002D72"))
            style.add("FONTNAME", (1, r), (1, r), "Helvetica-Bold")
        else:
            style.add("TEXTCOLOR", (1, r), (1, r), colors.HexColor("#111111"))

    table.setStyle(style)
    table.wrapOn(c, w, table_h)
    table.drawOn(c, x, y + 6)


def generate_all_lineups_pdf(lineups, report_title, team_name, report_date, logo_file, primary_rgb, accent_rgb):
    buffer = BytesIO()
    page_w, page_h = landscape(letter)
    c = canvas.Canvas(buffer, pagesize=landscape(letter))

    primary = colors.HexColor(rgb_to_hex(primary_rgb))
    accent = colors.HexColor(rgb_to_hex(accent_rgb))
    navy = primary
    red = accent
    gray_text = colors.HexColor("#6D7480")

    logo_path = save_logo_temp(logo_file)

    # Margins
    left = 24
    right = 24
    top = 22
    bottom = 24

    # Header logo
    draw_logo(c, logo_path, left, page_h - 80, 70, 56)

    # Header title
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(page_w / 2, page_h - 41, report_title.upper())

    # Date
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(page_w - right, page_h - 38, report_date.strftime("%b %d, %Y"))

    # Subtitle with shorter lines so text never gets cut off
    subtitle = "OPTIMIZED LINEUPS FOR EVERY SITUATION"
    subtitle_y = page_h - 64
    c.setFillColor(gray_text)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawCentredString(page_w / 2, subtitle_y, subtitle)

    text_width = c.stringWidth(subtitle, "Helvetica-Bold", 9.5)
    gap = 15
    line_y = subtitle_y + 2
    line_h = 2.3
    line_left_start = left + 75
    line_left_end = page_w / 2 - text_width / 2 - gap
    line_right_start = page_w / 2 + text_width / 2 + gap
    line_right_end = page_w - right - 22

    c.setFillColor(red)
    if line_left_end > line_left_start:
        c.rect(line_left_start, line_y, line_left_end - line_left_start, line_h, fill=1, stroke=0)
    if line_right_end > line_right_start:
        c.rect(line_right_start, line_y, line_right_end - line_right_start, line_h, fill=1, stroke=0)

    # Team summary moved taller/wider
    summary_y = page_h - 150
    summary_h = 56
    summary_x = left
    summary_w = page_w - left - right - 140
    legend_x = summary_x + summary_w + 14
    legend_w = page_w - right - legend_x

    draw_rounded_rect(c, summary_x, summary_y, summary_w, summary_h, radius=2, fill=colors.white, stroke=colors.HexColor("#D1D1D1"))

    # Team summary label block
    label_w = 112
    c.setFillColor(navy)
    c.rect(summary_x, summary_y, label_w, summary_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(summary_x + label_w / 2, summary_y + 32, "TEAM")
    c.drawCentredString(summary_x + label_w / 2, summary_y + 15, "SUMMARY")

    overall_summary = lineup_summary(lineups["Overall"])
    summary_metrics = [
        ("Team AVG", format_decimal(overall_summary["AVG"])),
        ("Team OBP", format_decimal(overall_summary["OBP"])),
        ("Team SLG", format_decimal(overall_summary["SLG"])),
        ("Projected Lineup Score", f"{overall_summary['Score']:.2f}"),
    ]

    metric_area_x = summary_x + label_w
    metric_area_w = summary_w - label_w
    metric_w = metric_area_w / 4
    for i, (lab, val) in enumerate(summary_metrics):
        value_color = red if i == 3 else navy
        draw_metric_block(c, metric_area_x + i * metric_w, summary_y + 5, metric_w, summary_h - 10, lab, val, colors.black, value_color, label_size=7.0, value_size=15.0)

    # Larger legend box
    draw_rounded_rect(c, legend_x, summary_y, legend_w, summary_h, radius=2, fill=colors.white, stroke=colors.HexColor("#D1D1D1"))
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 8.3)
    c.drawString(legend_x + 10, summary_y + summary_h - 16, "BATTING HAND LEGEND")

    c.setFont("Helvetica-Bold", 6.6)
    c.setFillColor(colors.HexColor("#111111"))
    c.drawString(legend_x + 10, summary_y + 31, "R = Right-Handed")
    c.setFillColor(colors.HexColor("#BA0C2F"))
    c.drawString(legend_x + 10, summary_y + 20, "L = Left-Handed")
    c.setFillColor(colors.HexColor("#002D72"))
    c.drawString(legend_x + 10, summary_y + 9, "S = Switch-Hitter")

    # Lineup panels: moved down to use white space and give top boxes room
    panel_y = 92
    panel_h = 322
    panel_gap = 14
    panel_w = (page_w - left - right - (panel_gap * 2)) / 3

    header_colors = {
        "Overall": navy,
        "Vs RHP": red,
        "Vs LHP": navy,
    }
    titles = {
        "Overall": "OVERALL OPTIMAL LINEUP",
        "Vs RHP": "VS RIGHT-HANDED PITCHER",
        "Vs LHP": "VS LEFT-HANDED PITCHER",
    }

    for i, key in enumerate(["Overall", "Vs RHP", "Vs LHP"]):
        draw_lineup_panel(
            c,
            lineups[key],
            left + i * (panel_w + panel_gap),
            panel_y,
            panel_w,
            panel_h,
            titles[key],
            header_colors[key],
        )

    # Footer
    footer_h = 40
    footer_y = 24
    c.setFillColor(navy)
    c.rect(left, footer_y, page_w - left - right, footer_h, fill=1, stroke=0)

    # accent diagonal stripes
    c.setFillColor(red)
    c.saveState()
    p = c.beginPath()
    p.moveTo(page_w - 88, footer_y)
    p.lineTo(page_w - 77, footer_y)
    p.lineTo(page_w - 52, footer_y + footer_h)
    p.lineTo(page_w - 63, footer_y + footer_h)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    c.restoreState()

    draw_logo(c, logo_path, left + 10, footer_y + 5, 40, 30)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left + 58, footer_y + 24, team_name.upper())
    c.setFont("Helvetica", 7.5)
    c.drawString(left + 58, footer_y + 12, "BASEBALL OPERATIONS")

    c.setFont("Helvetica-Bold", 9.5)
    c.drawRightString(page_w - right - 75, footer_y + 16, "Data-Driven Decisions. Better Results.")

    c.showPage()
    c.save()

    if logo_path and os.path.exists(logo_path):
        try:
            os.remove(logo_path)
        except Exception:
            pass

    buffer.seek(0)
    return buffer




# =====================================================
# HISTORICAL LINEUP ANALYSIS
# =====================================================

MLB_TEAM_IDS = {
    "athletics": 133, "orioles": 110, "red-sox": 111, "yankees": 147,
    "rays": 139, "blue-jays": 141, "white-sox": 145, "guardians": 114,
    "tigers": 116, "royals": 118, "twins": 142, "astros": 117,
    "angels": 108, "mariners": 136, "rangers": 140, "braves": 144,
    "marlins": 146, "mets": 121, "phillies": 143, "nationals": 120,
    "cubs": 112, "reds": 113, "brewers": 158, "pirates": 134,
    "cardinals": 138, "diamondbacks": 109, "rockies": 115,
    "dodgers": 119, "padres": 135, "giants": 137,
}

MLB_TEAM_ABBR = {
    133: "ATH", 110: "BAL", 111: "BOS", 147: "NYY", 139: "TB",
    141: "TOR", 145: "CWS", 114: "CLE", 116: "DET", 118: "KC",
    142: "MIN", 117: "HOU", 108: "LAA", 136: "SEA", 140: "TEX",
    144: "ATL", 146: "MIA", 121: "NYM", 143: "PHI", 120: "WSH",
    112: "CHC", 113: "CIN", 158: "MIL", 134: "PIT", 138: "STL",
    109: "ARI", 115: "COL", 119: "LAD", 135: "SD", 137: "SF",
}


def normalize_player_key(value):
    if pd.isna(value):
        return ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9 ]", " ", value)
    value = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", value)
    return re.sub(r"\s+", " ", value).strip()


def fetch_json(url, timeout=20):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Lineup-Construction-Analyzer/1.0",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_baseball_reference_url(url):
    parsed = urlparse(str(url).strip())
    if "baseball-reference.com" not in parsed.netloc.lower():
        raise ValueError("Please enter a Baseball Reference team batting-orders URL.")

    match = re.search(
        r"/teams/([A-Z0-9]{2,3})/(\d{4})-batting-orders\.shtml$",
        parsed.path,
        flags=re.I,
    )
    if not match:
        raise ValueError(
            "Use a Baseball Reference URL such as "
            "https://www.baseball-reference.com/teams/LAD/2025-batting-orders.shtml"
        )

    team_abbr = match.group(1).upper()
    season = int(match.group(2))
    return team_abbr, season


def baseball_reference_request(url, timeout=30):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def uncomment_baseball_reference_tables(page_html):
    # Baseball Reference often wraps data tables inside HTML comments.
    comment_blocks = re.findall(r"<!--(.*?)-->", page_html, flags=re.S)
    useful = [block for block in comment_blocks if "<table" in block.lower()]
    if useful:
        page_html = page_html + "\n" + "\n".join(useful)
    return unescape(page_html)


def flatten_html_columns(df):
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        flattened = []
        for parts in df.columns:
            clean_parts = [
                str(part).strip()
                for part in parts
                if str(part).strip() and not str(part).startswith("Unnamed")
            ]
            flattened.append(" ".join(dict.fromkeys(clean_parts)).strip())
        df.columns = flattened
    else:
        df.columns = [str(col).strip() for col in df.columns]
    return df


def clean_bref_player_name(value):
    if pd.isna(value):
        return ""
    value = str(value).strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^\d+[\.\)]\s*", "", value)
    value = re.sub(r"\s+\*+$", "", value)
    return value.strip()


def detect_bref_batting_order_table(tables):
    scored = []

    for idx, table in enumerate(tables):
        frame = flatten_html_columns(table)
        cols = [str(c).strip() for c in frame.columns]
        lower_cols = [c.lower() for c in cols]

        spot_count = 0
        for col in lower_cols:
            if re.fullmatch(r"(?:batting order\s*)?[1-9]", col):
                spot_count += 1
            elif re.fullmatch(r"[1-9](?:st|nd|rd|th)", col):
                spot_count += 1

        has_date = any("date" == c or c.endswith(" date") for c in lower_cols)
        has_game = any(c in {"g", "game", "game number", "gm"} for c in lower_cols)
        has_opponent = any("opp" in c or "opponent" in c for c in lower_cols)

        # Some Baseball Reference tables use generic labels and put the lineup
        # in nine consecutive columns. Give larger tables a secondary score.
        score = spot_count * 10 + int(has_date) * 4 + int(has_game) * 2 + int(has_opponent) * 3
        if len(frame.columns) >= 10:
            score += 2
        if len(frame) >= 10:
            score += 2

        scored.append((score, idx, frame))

    scored.sort(reverse=True, key=lambda item: item[0])

    if not scored or scored[0][0] < 15:
        detected = [
            ", ".join(map(str, flatten_html_columns(t).columns[:12]))
            for t in tables[:8]
        ]
        raise ValueError(
            "Could not identify the Baseball Reference batting-order table. "
            "Detected table headers: " + " | ".join(detected)
        )

    return scored[0][2]


def map_bref_columns(df):
    cols = list(df.columns)
    lower_map = {str(c).lower().strip(): c for c in cols}

    date_col = next(
        (col for key, col in lower_map.items() if key == "date" or key.endswith(" date")),
        None,
    )
    game_col = next(
        (col for key, col in lower_map.items() if key in {"g", "game", "game number", "gm"}),
        None,
    )
    opponent_col = next(
        (col for key, col in lower_map.items() if "opp" in key or "opponent" in key),
        None,
    )
    result_col = next(
        (col for key, col in lower_map.items() if key in {"result", "w/l", "wl", "res"}),
        None,
    )

    spot_cols = {}
    for col in cols:
        cleaned = str(col).strip().lower()
        match = re.fullmatch(r"(?:batting order\s*)?([1-9])", cleaned)
        if match:
            spot_cols[int(match.group(1))] = col
            continue

        match = re.fullmatch(r"([1-9])(?:st|nd|rd|th)", cleaned)
        if match:
            spot_cols[int(match.group(1))] = col
            continue

        match = re.fullmatch(r"(?:spot|order|lineup)\s*([1-9])", cleaned)
        if match:
            spot_cols[int(match.group(1))] = col

    if len(spot_cols) < 9:
        # Fallback: identify nine player-like columns after metadata columns.
        excluded = {c for c in [date_col, game_col, opponent_col, result_col] if c is not None}
        candidates = [c for c in cols if c not in excluded]

        player_like = []
        for col in candidates:
            sample = df[col].dropna().astype(str).head(20)
            if sample.empty:
                continue
            text_ratio = sample.str.contains(r"[A-Za-z]", regex=True).mean()
            numeric_ratio = pd.to_numeric(sample, errors="coerce").notna().mean()
            if text_ratio >= 0.6 and numeric_ratio < 0.5:
                player_like.append(col)

        if len(player_like) >= 9:
            spot_cols = {spot: player_like[spot - 1] for spot in range(1, 10)}

    if len(spot_cols) < 9:
        raise ValueError(
            "The Baseball Reference table was found, but lineup spots 1 through 9 "
            "could not be identified."
        )

    return date_col, game_col, opponent_col, result_col, spot_cols


def parse_baseball_reference_table(df, team_abbr, season):
    df = flatten_html_columns(df)
    date_col, game_col, opponent_col, result_col, spot_cols = map_bref_columns(df)

    rows = []
    game_counter = 0

    for row_index, source_row in df.iterrows():
        lineup_names = [
            clean_bref_player_name(source_row.get(spot_cols[spot], ""))
            for spot in range(1, 10)
        ]

        valid_names = [
            name for name in lineup_names
            if name and name.lower() not in {"nan", "none", "-", "n/a", "did not play"}
        ]
        if len(valid_names) < 7:
            continue

        raw_date = source_row.get(date_col, "") if date_col else ""
        parsed_date = pd.to_datetime(raw_date, errors="coerce")

        if pd.isna(parsed_date):
            # Baseball Reference sometimes omits the year in date labels.
            parsed_date = pd.to_datetime(
                f"{raw_date} {season}",
                errors="coerce",
            )

        game_date = parsed_date.date() if pd.notna(parsed_date) else None
        raw_game = source_row.get(game_col, "") if game_col else ""
        opponent = str(source_row.get(opponent_col, "") if opponent_col else "").strip()
        result = str(source_row.get(result_col, "") if result_col else "").strip()

        game_counter += 1
        game_id = (
            f"BR-{team_abbr}-{game_date.isoformat()}-{raw_game or game_counter}"
            if game_date
            else f"BR-{team_abbr}-{season}-{raw_game or game_counter}"
        )

        for spot in range(1, 10):
            player_name = clean_bref_player_name(source_row.get(spot_cols[spot], ""))
            if not player_name or player_name.lower() in {
                "nan", "none", "-", "n/a", "did not play"
            }:
                continue

            rows.append({
                "Date": game_date,
                "GamePk": game_id,
                "Team": team_abbr,
                "Opponent": opponent,
                "Result": result,
                "HomeAway": "Away" if opponent.startswith("@") else "Home",
                "Venue": "",
                "OpposingStarter": "",
                "OpposingPitcherHand": "Unknown",
                "LineupSpot": spot,
                "PlayerID": "",
                "Player": player_name,
                "Bats": "",
                "Position": "",
                "Source": "Baseball Reference",
            })

    if not rows:
        raise ValueError("No completed historical batting orders were found on the page.")

    result_df = pd.DataFrame(rows)
    result_df = result_df.drop_duplicates(subset=["GamePk", "LineupSpot", "Player"])
    result_df = result_df.sort_values(
        ["Date", "GamePk", "LineupSpot"],
        na_position="last",
    ).reset_index(drop=True)
    return result_df


@st.cache_data(ttl=1800, show_spinner=False)
def load_baseball_reference_lineups(url):
    team_abbr, season = parse_baseball_reference_url(url)
    page_html = baseball_reference_request(url)
    page_html = uncomment_baseball_reference_tables(page_html)

    try:
        tables = pd.read_html(StringIO(page_html))
    except ValueError:
        raise ValueError("Baseball Reference returned no readable tables.")

    batting_order_table = detect_bref_batting_order_table(tables)
    lineups_df = parse_baseball_reference_table(
        batting_order_table,
        team_abbr,
        season,
    )
    return lineups_df, team_abbr, season


def calculate_expected_spots(merged_df, numeric_cols):
    work = merged_df.copy()

    usable = []
    for col in numeric_cols:
        vals = pd.to_numeric(work[col], errors="coerce")
        if vals.notna().sum() >= 6 and vals.nunique(dropna=True) >= 2:
            usable.append(col)

    if not usable:
        return pd.DataFrame()

    # Use the most complete metrics, capped to avoid overfitting small samples.
    completeness = {
        col: pd.to_numeric(work[col], errors="coerce").notna().mean()
        for col in usable
    }
    model_cols = sorted(
        usable,
        key=lambda col: completeness[col],
        reverse=True,
    )[:12]

    player_profiles = (
        work.groupby("Player")[model_cols + ["LineupSpot"]]
        .mean(numeric_only=True)
        .reset_index()
    )

    if len(player_profiles) < 3:
        return pd.DataFrame()

    X = player_profiles[model_cols].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median(numeric_only=True)).fillna(0)

    std = X.std(ddof=0).replace(0, 1)
    X_scaled = (X - X.mean()) / std

    y = player_profiles["LineupSpot"].astype(float)
    design = np.column_stack([np.ones(len(X_scaled)), X_scaled.values])

    try:
        coefficients, *_ = np.linalg.lstsq(design, y.values, rcond=None)
        predicted = design @ coefficients
    except Exception:
        return pd.DataFrame()

    predicted = np.clip(predicted, 1, 9)
    player_profiles["ActualAverageSpot"] = y.round(2)
    player_profiles["ExpectedSpot"] = np.round(predicted, 2)
    player_profiles["ActualMinusExpected"] = (
        player_profiles["ActualAverageSpot"] - player_profiles["ExpectedSpot"]
    ).round(2)
    player_profiles["Interpretation"] = np.where(
        player_profiles["ActualMinusExpected"] < -0.50,
        "Used earlier than profile",
        np.where(
            player_profiles["ActualMinusExpected"] > 0.50,
            "Used later than profile",
            "Close to expected",
        ),
    )

    return player_profiles[
        [
            "Player",
            "ActualAverageSpot",
            "ExpectedSpot",
            "ActualMinusExpected",
            "Interpretation",
        ]
    ].sort_values("ActualMinusExpected").reset_index(drop=True)


def build_lineup_archetypes(merged_df, numeric_cols):
    preferred = [
        c for c in [
            "AVG", "OBP", "SLG", "OPS", "ISO", "BB%", "K%",
            "Contact%", "Chase%", "SB", "wOBA", "wRC+",
        ]
        if c in numeric_cols
    ]
    metrics = preferred[:8] if preferred else numeric_cols[:8]
    if not metrics:
        return pd.DataFrame()

    work = merged_df.copy()
    work["LineupGroup"] = pd.cut(
        pd.to_numeric(work["LineupSpot"], errors="coerce"),
        bins=[0, 2, 5, 9],
        labels=["Table Setters (1-2)", "Run Producers (3-5)", "Bottom Order (6-9)"],
    )

    grouped = (
        work.groupby("LineupGroup", observed=False)[metrics]
        .mean(numeric_only=True)
        .reset_index()
    )

    overall = work[metrics].mean(numeric_only=True)
    std = work[metrics].std(numeric_only=True).replace(0, np.nan)

    descriptions = []
    for _, row in grouped.iterrows():
        strengths = []
        weaknesses = []

        for metric in metrics:
            if pd.isna(row.get(metric)) or pd.isna(std.get(metric)):
                continue
            z = (row[metric] - overall[metric]) / std[metric]
            inverse = metric.upper() in {"K%", "CHASE%", "GB%"}

            if (z >= 0.30 and not inverse) or (z <= -0.30 and inverse):
                strengths.append(metric)
            elif (z <= -0.30 and not inverse) or (z >= 0.30 and inverse):
                weaknesses.append(metric)

        strength_text = ", ".join(strengths[:3]) if strengths else "Balanced profile"
        weakness_text = ", ".join(weaknesses[:2]) if weaknesses else "No major weakness"
        descriptions.append(
            f"Emphasizes {strength_text}; lower emphasis on {weakness_text}."
        )

    grouped["ArchetypeSummary"] = descriptions
    return grouped


def read_historical_stats_csv(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as exc:
        raise ValueError(f"Could not read season stats CSV: {exc}")

    df = clean_colnames(df)
    name_col = find_column(
        df,
        ["playerFullName", "PlayerFullName", "Player", "Name", "playerName", "player_name"],
    )
    if not name_col:
        raise ValueError("Could not find a player-name column in the season stats CSV.")

    df["Player"] = df[name_col].astype(str).str.strip()
    df["_name_key"] = df["Player"].apply(normalize_player_key)

    excluded = {
        name_col, "Player", "_name_key", "playerid", "player id", "id",
        "team", "level", "position", "pos", "bats", "batshand",
    }

    numeric_cols = []
    for col in df.columns:
        if str(col).lower().strip() in excluded:
            continue
        converted = pd.to_numeric(
            df[col].astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False),
            errors="coerce",
        )
        if converted.notna().sum() >= max(3, int(len(df) * 0.25)):
            df[col] = converted
            numeric_cols.append(col)

    if not numeric_cols:
        raise ValueError("No usable numeric stat columns were detected in the season stats CSV.")

    return df, numeric_cols


def best_name_match(name_key, stats_keys, threshold=0.84):
    if name_key in stats_keys:
        return name_key, 1.0

    best_key, best_score = "", 0.0
    name_parts = name_key.split()
    for candidate in stats_keys:
        score = SequenceMatcher(None, name_key, candidate).ratio()
        candidate_parts = candidate.split()
        if name_parts and candidate_parts and name_parts[-1] == candidate_parts[-1]:
            score += 0.08
        if score > best_score:
            best_key, best_score = candidate, score
    return (best_key, min(best_score, 1.0)) if best_score >= threshold else ("", best_score)


def merge_lineups_with_stats(lineups_df, stats_df):
    lineups = lineups_df.copy()
    lineups["_name_key"] = lineups["Player"].apply(normalize_player_key)

    stats_unique = stats_df.drop_duplicates("_name_key", keep="first").copy()
    stats_keys = set(stats_unique["_name_key"])

    matches = []
    scores = []
    for key in lineups["_name_key"]:
        matched, score = best_name_match(key, stats_keys)
        matches.append(matched)
        scores.append(score)

    lineups["_matched_key"] = matches
    lineups["NameMatchScore"] = scores

    merged = lineups.merge(
        stats_unique.drop(columns=["Player"], errors="ignore"),
        how="left",
        left_on="_matched_key",
        right_on="_name_key",
        suffixes=("", "_stats"),
    )

    unmatched = (
        lineups[lineups["_matched_key"].eq("")]["Player"]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    return merged, unmatched


def calculate_trait_importance(merged_df, numeric_cols, min_rows=6):
    records = []
    work = merged_df.copy()
    work["EarlierLineupValue"] = 10 - pd.to_numeric(work["LineupSpot"], errors="coerce")

    for col in numeric_cols:
        values = pd.to_numeric(work[col], errors="coerce")
        valid = values.notna() & work["EarlierLineupValue"].notna()
        n = int(valid.sum())
        if n < min_rows or values[valid].nunique() < 2:
            continue

        # Calculate Spearman correlation without SciPy.
        # Spearman is simply Pearson correlation applied to ranked values.
        ranked_trait = values.loc[valid].rank(method="average")
        ranked_lineup = work.loc[valid, "EarlierLineupValue"].rank(method="average")
        corr = ranked_trait.corr(ranked_lineup, method="pearson")
        if pd.isna(corr):
            continue
        records.append({
            "Trait": col,
            "Relationship": float(corr),
            "AbsoluteStrength": abs(float(corr)),
            "Direction": "Higher values appear earlier" if corr > 0 else "Higher values appear later",
            "Observations": n,
        })

    result = pd.DataFrame(records)
    if result.empty:
        return result

    max_strength = result["AbsoluteStrength"].max()
    result["ImportanceScore"] = (
        result["AbsoluteStrength"] / max_strength * 100 if max_strength > 0 else 0
    ).round(1)
    return result.sort_values(["ImportanceScore", "Trait"], ascending=[False, True]).reset_index(drop=True)


def calculate_spot_profiles(merged_df, numeric_cols):
    preferred = [
        c for c in ["AVG", "OBP", "SLG", "OPS", "ISO", "BB%", "K%", "SB", "wOBA", "wRC+"]
        if c in numeric_cols
    ]
    metrics = preferred[:8] if preferred else numeric_cols[:8]
    if not metrics:
        return pd.DataFrame()

    profiles = (
        merged_df.groupby("LineupSpot")[metrics]
        .mean(numeric_only=True)
        .reset_index()
        .sort_values("LineupSpot")
    )
    return profiles


def calculate_usage_table(merged_df):
    games = max(merged_df["GamePk"].nunique(), 1)
    usage = (
        merged_df.groupby("Player")
        .agg(
            Starts=("GamePk", "nunique"),
            AverageSpot=("LineupSpot", "mean"),
            EarliestSpot=("LineupSpot", "min"),
            LatestSpot=("LineupSpot", "max"),
            VsRHP=("OpposingPitcherHand", lambda s: int((s == "R").sum())),
            VsLHP=("OpposingPitcherHand", lambda s: int((s == "L").sum())),
        )
        .reset_index()
    )
    usage["StartRate"] = (usage["Starts"] / games * 100).round(1)
    usage["AverageSpot"] = usage["AverageSpot"].round(2)
    return usage.sort_values(["Starts", "AverageSpot"], ascending=[False, True]).reset_index(drop=True)


def calculate_lineup_consistency(merged_df):
    game_lineups = []
    for game_pk, group in merged_df.groupby("GamePk"):
        ordered = tuple(group.sort_values("LineupSpot")["Player"].tolist())
        game_lineups.append((game_pk, ordered))

    if len(game_lineups) < 2:
        return 100.0

    similarities = []
    for i in range(1, len(game_lineups)):
        previous = game_lineups[i - 1][1]
        current = game_lineups[i][1]
        same_spot = sum(a == b for a, b in zip(previous, current)) / 9
        same_players = len(set(previous) & set(current)) / 9
        similarities.append((same_spot * 0.60) + (same_players * 0.40))
    return round(float(np.mean(similarities) * 100), 1)


def build_philosophy_summary(importance_df, merged_df, consistency):
    if importance_df.empty:
        lead = "The available sample is too small to rank lineup traits reliably."
    else:
        top = importance_df.head(3)
        phrases = []
        for _, row in top.iterrows():
            direction = "earlier" if row["Relationship"] > 0 else "later"
            phrases.append(f"{row['Trait']} ({direction} in the order)")
        lead = "The strongest observed lineup-placement relationships are " + ", ".join(phrases) + "."

    hand_counts = merged_df.get(
        "OpposingPitcherHand",
        pd.Series(dtype=str),
    ).value_counts()
    rhp_games = int(hand_counts.get("R", 0)) // 9
    lhp_games = int(hand_counts.get("L", 0)) // 9
    if rhp_games or lhp_games:
        hand_text = (
            f"The sample includes {rhp_games} games versus right-handed starters "
            f"and {lhp_games} versus left-handed starters."
        )
    else:
        hand_text = (
            f"The sample includes {merged_df['GamePk'].nunique()} historical lineups. "
            "Opposing pitcher handedness is not supplied by this Baseball Reference table."
        )
    consistency_text = (
        f"Lineup consistency is {consistency:.1f}%, combining repeated starters and repeated batting-order spots."
    )
    caveat = (
        "These results describe observed associations, not proof of the manager's intent. "
        "Using season-to-date stats from each game date would make the conclusions stronger."
    )
    return f"{lead} {hand_text} {consistency_text} {caveat}"


def historical_analysis_pdf(team_name, date_range, summary_text, importance_df, usage_df, profiles_df):
    buffer = BytesIO()
    page_w, page_h = landscape(letter)
    c = canvas.Canvas(buffer, pagesize=landscape(letter))
    navy = colors.HexColor("#002D72")
    red = colors.HexColor("#BA0C2F")
    light = colors.HexColor("#F3F6FA")

    c.setFillColor(navy)
    c.rect(0, page_h - 72, page_w, 72, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(30, page_h - 42, "LINEUP CONSTRUCTION ANALYSIS")
    c.setFont("Helvetica", 9)
    c.drawRightString(page_w - 30, page_h - 40, f"{team_name} | {date_range}")

    c.setFillColor(light)
    c.roundRect(30, page_h - 150, page_w - 60, 58, 7, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#20242A"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(42, page_h - 112, "TEAM PHILOSOPHY SUMMARY")
    text_obj = c.beginText(42, page_h - 127)
    text_obj.setFont("Helvetica", 7.5)
    words = summary_text.split()
    line = ""
    for word in words:
        test = f"{line} {word}".strip()
        if c.stringWidth(test, "Helvetica", 7.5) > page_w - 90:
            text_obj.textLine(line)
            line = word
        else:
            line = test
    if line:
        text_obj.textLine(line)
    c.drawText(text_obj)

    def draw_simple_table(dataframe, x, y_top, width, title, max_rows=10):
        c.setFillColor(navy)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y_top, title)
        if dataframe is None or dataframe.empty:
            c.setFont("Helvetica", 8)
            c.drawString(x, y_top - 18, "Not enough data.")
            return

        view = dataframe.head(max_rows).copy()
        for col in view.columns:
            if pd.api.types.is_float_dtype(view[col]):
                view[col] = view[col].map(lambda v: f"{v:.2f}" if pd.notna(v) else "")
        rows = [list(view.columns)] + view.astype(str).values.tolist()
        col_width = width / len(view.columns)
        table = Table(rows, colWidths=[col_width] * len(view.columns), rowHeights=18)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 6.2),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9DEE7")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ]))
        table.wrapOn(c, width, 300)
        table.drawOn(c, x, y_top - 24 - 18 * len(rows))

    imp_view = importance_df[["Trait", "ImportanceScore", "Direction"]].copy() if not importance_df.empty else importance_df
    usage_view = usage_df[["Player", "Starts", "StartRate", "AverageSpot"]].copy() if not usage_df.empty else usage_df
    draw_simple_table(imp_view, 30, page_h - 180, 350, "MOST EMPHASIZED TRAITS", 10)
    draw_simple_table(usage_view, 410, page_h - 180, 350, "PLAYER USAGE", 10)

    profile_view = profiles_df.copy()
    draw_simple_table(profile_view, 30, 245, page_w - 60, "AVERAGE PROFILE BY LINEUP SPOT", 9)

    c.setFillColor(red)
    c.rect(30, 28, page_w - 60, 4, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#666666"))
    c.setFont("Helvetica", 6.5)
    c.drawString(30, 16, "Observed lineup associations; results should be interpreted with sample size and data timing in mind.")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def render_historical_analysis():
    st.subheader("Historical Lineup Construction Analysis")
    st.caption(
        "Paste a Baseball Reference team batting-orders URL and upload a season-stat CSV. "
        "The app imports the full-season batting-order table and matches those lineups to player traits."
    )

    st.info(
        "Baseball Reference provides a season-long batting-order history from one team URL. "
        "The app reads the full batting-order table directly from that page."
    )

    url_text = st.text_input(
        "Baseball Reference Team Batting-Orders URL",
        placeholder="https://www.baseball-reference.com/teams/LAD/2025-batting-orders.shtml",
        key="historical_baseball_reference_url",
    )
    season_stats_file = st.file_uploader(
        "Season Stats CSV",
        type=["csv"],
        key="historical_stats_csv",
    )

    analyze = st.button(
        "Analyze Lineup Construction",
        type="primary",
        use_container_width=True,
    )

    if not analyze:
        st.markdown(
            """
            **The analysis will show:**
            - Trait importance for batting-order placement
            - Average player profile by lineup spot
            - Player start frequency and average lineup position
            - Table-setter, run-producer, and bottom-order archetypes
            - Actual versus expected lineup placement
            - Lineup consistency and an automated philosophy summary
            """
        )
        return

    if not url_text.strip() or season_stats_file is None:
        st.error("Add a Baseball Reference batting-orders URL and upload the season stats CSV.")
        return

    try:
        with st.spinner("Loading Baseball Reference season batting orders and matching season statistics..."):
            lineups_df, team_abbr, season = load_baseball_reference_lineups(url_text)
            team_slug = team_abbr.lower()
            stats_df, numeric_cols = read_historical_stats_csv(season_stats_file)
            merged_df, unmatched = merge_lineups_with_stats(lineups_df, stats_df)
    except (ValueError, HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        st.error(f"Could not complete the historical analysis: {exc}")
        return
    except Exception as exc:
        st.error(f"Unexpected historical-analysis error: {exc}")
        return

    matched_rows = merged_df["_matched_key"].ne("").sum()
    total_rows = len(merged_df)
    games = lineups_df["GamePk"].nunique()
    match_pct = matched_rows / max(total_rows, 1) * 100

    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("Games", games)
    metric2.metric("Lineup Entries", total_rows)
    metric3.metric("Players Matched", f"{match_pct:.1f}%")
    metric4.metric("Date Range", f"{lineups_df['Date'].min()} to {lineups_df['Date'].max()}")

    if unmatched:
        st.warning(
            "Unmatched players were excluded from trait calculations: "
            + ", ".join(unmatched)
        )

    analysis_df = merged_df[merged_df["_matched_key"].ne("")].copy()
    if analysis_df.empty:
        st.error("No lineup names could be matched to the season stats CSV.")
        return

    importance = calculate_trait_importance(analysis_df, numeric_cols)
    profiles = calculate_spot_profiles(analysis_df, numeric_cols)
    usage = calculate_usage_table(analysis_df)
    archetypes = build_lineup_archetypes(analysis_df, numeric_cols)
    expected_spots = calculate_expected_spots(analysis_df, numeric_cols)
    consistency = calculate_lineup_consistency(analysis_df)
    philosophy = build_philosophy_summary(importance, analysis_df, consistency)

    st.markdown("### Team Philosophy")
    st.write(philosophy)

    st.markdown("### Most Emphasized Traits")
    if importance.empty:
        st.info("The sample is too small or the uploaded metrics do not vary enough.")
    else:
        chart_df = importance.head(12).set_index("Trait")[["ImportanceScore"]]
        st.bar_chart(chart_df, horizontal=True)
        st.dataframe(
            importance[["Trait", "ImportanceScore", "Relationship", "Direction", "Observations"]],
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("### Average Profile by Lineup Spot")
    st.dataframe(profiles, use_container_width=True, hide_index=True)

    st.markdown("### Player Usage")
    st.dataframe(usage, use_container_width=True, hide_index=True)

    st.markdown("### Lineup Archetypes")
    if archetypes.empty:
        st.info("Not enough compatible metrics were available to create lineup archetypes.")
    else:
        st.dataframe(archetypes, use_container_width=True, hide_index=True)

    st.markdown("### Actual vs Expected Lineup Spot")
    if expected_spots.empty:
        st.info("Not enough matched player profiles were available to estimate expected lineup spots.")
    else:
        st.dataframe(expected_spots, use_container_width=True, hide_index=True)

    st.markdown("### Imported Historical Lineups")
    display_cols = [
        "Date", "Opponent", "Result", "HomeAway",
        "LineupSpot", "Player",
    ]
    st.dataframe(
        lineups_df[display_cols],
        use_container_width=True,
        hide_index=True,
    )

    team_name_display = lineups_df["Team"].dropna().iloc[0] if not lineups_df.empty else team_slug.title()
    date_range = f"{lineups_df['Date'].min()} – {lineups_df['Date'].max()}"

    export1, export2, export3 = st.columns(3)
    with export1:
        st.download_button(
            "Download Imported Lineups CSV",
            data=lineups_df.to_csv(index=False).encode("utf-8"),
            file_name=f"{team_abbr.lower()}_{season}_historical_lineups.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with export2:
        st.download_button(
            "Download Analysis CSV",
            data=importance.to_csv(index=False).encode("utf-8"),
            file_name=f"{team_abbr.lower()}_{season}_lineup_trait_importance.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with export3:
        pdf = historical_analysis_pdf(
            team_name_display,
            date_range,
            philosophy,
            importance,
            usage,
            profiles,
        )
        st.download_button(
            "Export Analysis PDF",
            data=pdf,
            file_name=f"{team_abbr.lower()}_{season}_lineup_construction_analysis.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    st.caption(
        "Interpretation note: importance scores measure association with earlier or later lineup placement. "
        "They do not prove causation or fully explain starter selection because bench availability is not included."
    )


# =====================================================
# APP UI
# =====================================================

st.title("Lineup Optimization & Construction Intelligence")
st.caption(
    "Optimize future lineups or reverse-engineer how a team has constructed its recent batting orders."
)

analysis_mode = st.segmented_control(
    "Select Analysis Mode",
    options=["Optimize Lineup", "Analyze Historical Lineups"],
    default="Optimize Lineup",
    key="analysis_mode_selector",
)

if analysis_mode == "Analyze Historical Lineups":
    render_historical_analysis()
    st.stop()

# ------------------------------
# ORIGINAL LINEUP OPTIMIZER
# ------------------------------

st.sidebar.header("Report Branding")
team_name = st.sidebar.text_input("Team Name", value="Texas Rangers")
report_title = st.sidebar.text_input("Report Title", value="Lineup Optimization Report")
report_date = st.sidebar.date_input("Report Date", value=date.today())
team_logo = st.sidebar.file_uploader("Team Logo", type=["png", "jpg", "jpeg"], key="team_logo")

primary_rgb, accent_rgb = extract_team_colors(team_logo)
st.sidebar.caption(f"Detected primary color: {rgb_to_hex(primary_rgb)}")
st.sidebar.caption(f"Detected accent color: {rgb_to_hex(accent_rgb)}")

st.sidebar.divider()
st.sidebar.header("Stat Weights")
avg_weight = st.sidebar.slider("AVG Weight", 0.0, 5.0, 1.0, 0.1)
obp_weight = st.sidebar.slider("OBP Weight", 0.0, 5.0, 2.0, 0.1)
slg_weight = st.sidebar.slider("SLG Weight", 0.0, 5.0, 2.0, 0.1)
iso_weight = st.sidebar.slider("ISO Weight", 0.0, 5.0, 1.5, 0.1)
sb_weight = st.sidebar.slider("SB Weight", 0.0, 5.0, 0.8, 0.1)
weights = {"AVG": avg_weight, "OBP": obp_weight, "SLG": slg_weight, "ISO": iso_weight, "SB": sb_weight}

st.sidebar.divider()
enforce_positions = st.sidebar.checkbox(
    "Use position requirements",
    value=False,
    help="Optional. If checked, the app will try to include C, 1B, 2B, 3B, SS, 3 OF, and DH.",
)

st.sidebar.divider()
lineup_mode = st.sidebar.radio(
    "Lineup Type",
    ["Overall", "Vs RHP", "Vs LHP"],
    help="Choose which uploaded CSV to use for the optimized lineup.",
)

st.markdown(
    """
    **Bats color key:**  
    <span style="color:#BA0C2F;font-weight:800;">Left-handed hitters</span> = red &nbsp; | &nbsp;
    <span style="color:#002D72;font-weight:800;">Switch hitters</span> = blue &nbsp; | &nbsp;
    <span style="color:#111111;font-weight:800;">Right-handed hitters</span> = black
    """,
    unsafe_allow_html=True,
)

col1, col2, col3 = st.columns(3)
with col1:
    overall_file = st.file_uploader("Overall CSV", type=["csv"], key="overall_csv")
with col2:
    vs_rhp_file = st.file_uploader("Vs RHP CSV", type=["csv"], key="vs_rhp_csv")
with col3:
    vs_lhp_file = st.file_uploader("Vs LHP CSV", type=["csv"], key="vs_lhp_csv")

files = {
    "Overall": overall_file,
    "Vs RHP": vs_rhp_file,
    "Vs LHP": vs_lhp_file,
}

prepared = {}
lineups = {}
scored = {}

for key, file in files.items():
    if file is not None:
        df = prepare_dataframe(file, key)
        if df is not None:
            lineup, scored_df = build_lineup(df, weights, enforce_positions, key)
            if lineup is not None:
                prepared[key] = df
                lineups[key] = lineup
                scored[key] = scored_df

selected_file = files[lineup_mode]
if selected_file is None:
    st.info(f"Upload the {lineup_mode} CSV to generate that lineup.")
    st.stop()

if lineup_mode not in lineups:
    st.stop()

st.subheader(f"Uploaded Player Pool — {lineup_mode}")
show_player_pool(scored[lineup_mode])

st.subheader(f"Optimized Lineup — {lineup_mode}")
render_lineup_table(lineups[lineup_mode])

csv = lineups[lineup_mode].to_csv(index=False).encode("utf-8")
st.download_button(
    label=f"Download {lineup_mode} Optimized Lineup CSV",
    data=csv,
    file_name=f"optimized_lineup_{lineup_mode.lower().replace(' ', '_')}.csv",
    mime="text/csv",
)

st.divider()

if all(k in lineups for k in ["Overall", "Vs RHP", "Vs LHP"]):
    pdf_buffer = generate_all_lineups_pdf(
        lineups=lineups,
        report_title=report_title,
        team_name=team_name,
        report_date=report_date,
        logo_file=team_logo,
        primary_rgb=primary_rgb,
        accent_rgb=accent_rgb,
    )

    st.download_button(
        label="Export All 3 Lineups as PDF",
        data=pdf_buffer,
        file_name="lineup_optimization_report.pdf",
        mime="application/pdf",
        type="primary",
    )
else:
    st.info("Upload all 3 CSVs to export the one-page PDF with Overall, Vs RHP, and Vs LHP.")

st.markdown("### Lineup Notes")
st.write(
    """
    - Use the analysis-mode selector to switch between optimization and historical analysis.
    - Upload all three optimizer CSVs to activate the optimization PDF export.
    - Historical analysis accepts a Baseball Reference team batting-orders URL and a season-stat CSV.
    - The importer reads the full-season batting-order table directly from Baseball Reference.
    - The historical mode reports observed relationships; it does not claim causal intent.
    - The PDF uses your uploaded team logo and automatically detects team colors for the optimizer theme.
    - Batting hand colors stay fixed: LHH red, switch hitters blue, RHH black.
    - Position requirements are optional.
    """
)
