
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
from urllib.parse import urlparse, urljoin, parse_qs
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


MLB_TEAM_OPTIONS = {
    "Arizona Diamondbacks": "ARI",
    "Athletics": "ATH",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CHW",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KCR",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SDP",
    "San Francisco Giants": "SFG",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TBR",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSN",
}


MLB_TEAM_IDS_BY_BREF_ABBR = {
    "ARI": 109,
    "ATH": 133,
    "ATL": 144,
    "BAL": 110,
    "BOS": 111,
    "CHC": 112,
    "CHW": 145,
    "CIN": 113,
    "CLE": 114,
    "COL": 115,
    "DET": 116,
    "HOU": 117,
    "KCR": 118,
    "LAA": 108,
    "LAD": 119,
    "MIA": 146,
    "MIL": 158,
    "MIN": 142,
    "NYM": 121,
    "NYY": 147,
    "PHI": 143,
    "PIT": 134,
    "SDP": 135,
    "SFG": 137,
    "SEA": 136,
    "STL": 138,
    "TBR": 139,
    "TEX": 140,
    "TOR": 141,
    "WSN": 120,
}


def build_baseball_reference_url(team_abbr, season):
    return (
        f"https://www.baseball-reference.com/teams/"
        f"{team_abbr}/{int(season)}-batting-orders.shtml"
    )


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



def get_mlb_pitcher_hand(feed, side_key, probable_pitcher_id=None):
    players = feed.get("gameData", {}).get("players", {})

    if probable_pitcher_id:
        player_data = players.get(f"ID{probable_pitcher_id}", {})
        hand = player_data.get("pitchHand", {}).get("code")
        if hand:
            return str(hand).upper()

    team_box = (
        feed.get("liveData", {})
        .get("boxscore", {})
        .get("teams", {})
        .get(side_key, {})
    )
    pitcher_ids = team_box.get("pitchers", [])
    if pitcher_ids:
        player_data = players.get(f"ID{pitcher_ids[0]}", {})
        hand = player_data.get("pitchHand", {}).get("code")
        if hand:
            return str(hand).upper()

    return "Unknown"


def extract_mlb_daily_lineup(feed, team_id, game_date):
    game_data = feed.get("gameData", {})
    teams = game_data.get("teams", {})
    home_id = teams.get("home", {}).get("id")
    away_id = teams.get("away", {}).get("id")

    if team_id == home_id:
        team_side, opponent_side = "home", "away"
    elif team_id == away_id:
        team_side, opponent_side = "away", "home"
    else:
        return []

    live_data = feed.get("liveData", {})
    boxscore = live_data.get("boxscore", {})
    team_box = boxscore.get("teams", {}).get(team_side, {})
    batting_order = team_box.get("battingOrder", [])

    if len(batting_order) < 9:
        return []

    players = game_data.get("players", {})
    probable_pitcher = (
        game_data.get("probablePitchers", {}).get(opponent_side, {})
    )
    pitcher_id = probable_pitcher.get("id")
    pitcher_hand = get_mlb_pitcher_hand(
        feed,
        opponent_side,
        pitcher_id,
    )

    opponent_name = teams.get(opponent_side, {}).get("name", "")
    game_pk = game_data.get("game", {}).get("pk", "")
    venue = game_data.get("venue", {}).get("name", "")

    linescore = live_data.get("linescore", {})
    home_runs = linescore.get("teams", {}).get("home", {}).get("runs")
    away_runs = linescore.get("teams", {}).get("away", {}).get("runs")

    if home_runs is not None and away_runs is not None:
        team_runs = home_runs if team_side == "home" else away_runs
        opponent_runs = away_runs if team_side == "home" else home_runs
        result = "W" if team_runs > opponent_runs else "L" if team_runs < opponent_runs else "T"
        result = f"{result} {team_runs}-{opponent_runs}"
    else:
        result = ""

    rows = []
    for spot, player_id in enumerate(batting_order[:9], start=1):
        player_data = players.get(f"ID{player_id}", {})
        box_player = team_box.get("players", {}).get(f"ID{player_id}", {})

        position = (
            box_player.get("position", {}).get("abbreviation")
            or player_data.get("primaryPosition", {}).get("abbreviation")
            or ""
        )
        bats = player_data.get("batSide", {}).get("code", "")

        rows.append({
            "Date": pd.to_datetime(game_date).date(),
            "GamePk": game_pk,
            "Team": teams.get(team_side, {}).get("name", ""),
            "Opponent": opponent_name,
            "Result": result,
            "HomeAway": "Home" if team_side == "home" else "Away",
            "Venue": venue,
            "OpposingStarter": probable_pitcher.get("fullName", ""),
            "OpposingPitcherHand": pitcher_hand,
            "LineupSpot": spot,
            "PlayerID": player_id,
            "Player": player_data.get(
                "fullName",
                box_player.get("person", {}).get("fullName", ""),
            ),
            "Bats": bats,
            "Position": position,
            "Source": "MLB Official Game Feed",
        })

    return rows


@st.cache_data(ttl=1800, show_spinner=False)
def load_official_mlb_lineups(team_abbr, season):
    team_id = MLB_TEAM_IDS_BY_BREF_ABBR.get(team_abbr)
    if not team_id:
        raise ValueError(f"Could not find MLB team ID for {team_abbr}.")

    schedule_url = (
        "https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&teamId={team_id}"
        f"&startDate={int(season)}-01-01"
        f"&endDate={int(season)}-12-31"
    )
    schedule = fetch_json(schedule_url)

    rows = []
    for date_block in schedule.get("dates", []):
        game_date = date_block.get("date")
        for game in date_block.get("games", []):
            status = game.get("status", {}).get("abstractGameState", "")
            if status not in {"Final", "Live"}:
                continue

            game_pk = game.get("gamePk")
            if not game_pk:
                continue

            try:
                feed = fetch_json(
                    f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
                )
                rows.extend(
                    extract_mlb_daily_lineup(
                        feed,
                        team_id=team_id,
                        game_date=game_date,
                    )
                )
            except Exception:
                continue

    if not rows:
        raise ValueError(
            "No completed daily lineups were found for the selected team and season."
        )

    result = pd.DataFrame(rows)
    result = result.drop_duplicates(
        subset=["GamePk", "LineupSpot", "PlayerID"]
    )
    result = result.sort_values(
        ["Date", "GamePk", "LineupSpot"]
    ).reset_index(drop=True)
    return result


def baseball_reference_data_is_daily(lineups_df, season):
    if lineups_df is None or lineups_df.empty:
        return False

    dates = pd.to_datetime(lineups_df.get("Date"), errors="coerce")
    valid_dates = dates.notna().sum()
    unique_dates = dates.dropna().dt.date.nunique()

    if valid_dates < min(10, len(lineups_df) * 0.50):
        return False

    if unique_dates < 5:
        return False

    year_matches = (dates.dropna().dt.year == int(season)).mean()
    if year_matches < 0.80:
        return False

    names = lineups_df.get("Player", pd.Series(dtype=str)).astype(str)
    bad_name_ratio = names.str.contains(
        r"\bPlayers?\b|-\d+$|-(?:C|1B|2B|3B|SS|LF|CF|RF|OF|DH)$",
        regex=True,
        case=False,
        na=False,
    ).mean()

    return bad_name_ratio < 0.20


@st.cache_data(ttl=1800, show_spinner=False)
def load_historical_lineups_with_fallback(url, team_abbr, season):
    source_note = ""

    try:
        bref_df, _, _ = load_baseball_reference_lineups(url)
        if baseball_reference_data_is_daily(bref_df, season):
            source_note = "Baseball Reference daily batting-order table"
            return bref_df, source_note
    except Exception:
        pass

    mlb_df = load_official_mlb_lineups(team_abbr, season)
    source_note = (
        "MLB official game feeds were used because the Baseball Reference page "
        "returned a summary table rather than true daily lineups."
    )
    return mlb_df, source_note


def build_baseball_reference_team_stats_url(team_abbr, season):
    return (
        f"https://www.baseball-reference.com/teams/"
        f"{team_abbr}/{int(season)}.shtml"
    )


def detect_baseball_reference_batting_table(tables):
    candidates = []

    for index, table in enumerate(tables):
        frame = flatten_html_columns(table)
        columns = [str(col).strip() for col in frame.columns]
        lower_columns = [col.lower() for col in columns]

        name_score = int(
            any(
                col in {
                    "player", "name", "player name",
                    "standard batting player",
                }
                or col.endswith(" player")
                for col in lower_columns
            )
        )

        expected_stats = {
            "pa", "ab", "r", "h", "2b", "3b", "hr",
            "rbi", "sb", "cs", "bb", "so", "ba", "avg",
            "obp", "slg", "ops", "ops+",
        }
        stat_score = sum(col in expected_stats for col in lower_columns)

        # Standard team batting tables generally contain many of these columns.
        score = name_score * 20 + stat_score

        if len(frame) >= 5:
            score += 2
        if len(frame.columns) >= 12:
            score += 3

        candidates.append((score, index, frame))

    candidates.sort(reverse=True, key=lambda item: item[0])

    if not candidates or candidates[0][0] < 28:
        headers = [
            ", ".join(map(str, flatten_html_columns(table).columns[:15]))
            for table in tables[:10]
        ]
        raise ValueError(
            "Could not identify the Baseball Reference standard batting table. "
            "Detected table headers: " + " | ".join(headers)
        )

    return candidates[0][2]


def find_bref_stat_column(df, possible_names):
    normalized = {
        re.sub(r"\s+", " ", str(col)).strip().lower(): col
        for col in df.columns
    }

    for name in possible_names:
        key = re.sub(r"\s+", " ", str(name)).strip().lower()
        if key in normalized:
            return normalized[key]

    for normalized_name, original in normalized.items():
        for name in possible_names:
            key = str(name).strip().lower()
            if normalized_name.endswith(f" {key}"):
                return original

    return None


def clean_baseball_reference_stats_table(df):
    df = flatten_html_columns(df).copy()

    name_col = find_bref_stat_column(
        df,
        ["Player", "Name", "Player Name"],
    )
    if name_col is None:
        raise ValueError(
            "The Baseball Reference batting table did not contain a player-name column."
        )

    df["Player"] = (
        df[name_col]
        .astype(str)
        .str.replace(r"\*+$", "", regex=True)
        .str.replace(r"^\s*\d+\.\s*", "", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    excluded_name_patterns = [
        r"^team totals?$",
        r"^team total$",
        r"^rank in",
        r"^league average",
        r"^lg average",
        r"^average$",
        r"^player$",
        r"^nan$",
        r"^$",
    ]

    invalid_mask = pd.Series(False, index=df.index)
    for pattern in excluded_name_patterns:
        invalid_mask |= df["Player"].str.match(
            pattern,
            case=False,
            na=False,
        )

    df = df[~invalid_mask].copy()

    column_aliases = {
        "Age": ["Age"],
        "G": ["G", "Games"],
        "PA": ["PA", "Plate Appearances"],
        "AB": ["AB", "At Bats"],
        "R": ["R", "Runs"],
        "H": ["H", "Hits"],
        "2B": ["2B", "Doubles"],
        "3B": ["3B", "Triples"],
        "HR": ["HR", "Home Runs"],
        "RBI": ["RBI"],
        "SB": ["SB", "Stolen Bases"],
        "CS": ["CS", "Caught Stealing"],
        "BB": ["BB", "Walks"],
        "SO": ["SO", "Strikeouts"],
        "AVG": ["BA", "AVG", "Batting Average"],
        "OBP": ["OBP"],
        "SLG": ["SLG"],
        "OPS": ["OPS"],
        "OPS+": ["OPS+"],
        "TB": ["TB", "Total Bases"],
        "GDP": ["GDP", "GIDP"],
        "HBP": ["HBP"],
        "SF": ["SF"],
        "Pos": ["Pos", "Position", "Pos Summary"],
    }

    output = pd.DataFrame()
    output["Player"] = df["Player"]

    for standardized_name, aliases in column_aliases.items():
        source_col = find_bref_stat_column(df, aliases)
        if source_col is not None:
            output[standardized_name] = df[source_col]

    # Convert available statistical columns to numeric.
    non_numeric = {"Player", "Pos"}
    for col in output.columns:
        if col in non_numeric:
            continue

        output[col] = pd.to_numeric(
            output[col]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False)
            .str.strip(),
            errors="coerce",
        )

    # Drop rows without real playing time.
    if "PA" in output.columns:
        output = output[
            output["PA"].fillna(0) > 0
        ].copy()
    elif "G" in output.columns:
        output = output[
            output["G"].fillna(0) > 0
        ].copy()

    # Derived traits that improve the lineup-construction analysis.
    if "SLG" in output.columns and "AVG" in output.columns:
        output["ISO"] = output["SLG"] - output["AVG"]

    if "BB" in output.columns and "PA" in output.columns:
        output["BB%"] = np.where(
            output["PA"] > 0,
            output["BB"] / output["PA"] * 100,
            np.nan,
        )

    if "SO" in output.columns and "PA" in output.columns:
        output["K%"] = np.where(
            output["PA"] > 0,
            output["SO"] / output["PA"] * 100,
            np.nan,
        )

    if "SB" in output.columns and "CS" in output.columns:
        attempts = output["SB"].fillna(0) + output["CS"].fillna(0)
        output["SB%"] = np.where(
            attempts > 0,
            output["SB"].fillna(0) / attempts * 100,
            np.nan,
        )

    output["_name_key"] = output["Player"].apply(normalize_player_key)

    def build_name_keys(player_name):
        key = normalize_player_key(player_name)
        keys = {key} if key else set()
        parts = key.split()

        if len(parts) >= 2:
            keys.add(parts[-1])
            keys.add(f"{parts[0][0]} {parts[-1]}")

        return sorted(keys)

    output["_all_name_keys"] = output["Player"].apply(build_name_keys)
    output = output.drop_duplicates("_name_key", keep="first")

    numeric_cols = [
        col for col in output.columns
        if col not in {
            "Player", "Pos", "_name_key", "_all_name_keys"
        }
        and pd.api.types.is_numeric_dtype(output[col])
        and output[col].notna().sum() >= 3
        and output[col].nunique(dropna=True) >= 2
    ]

    if not numeric_cols:
        raise ValueError(
            "No usable player statistics were found in the Baseball Reference batting table."
        )

    return output.reset_index(drop=True), numeric_cols


@st.cache_data(ttl=1800, show_spinner=False)
def load_baseball_reference_team_stats(team_abbr, season):
    stats_url = build_baseball_reference_team_stats_url(
        team_abbr,
        season,
    )
    page_html = baseball_reference_request(stats_url)
    page_html = uncomment_baseball_reference_tables(page_html)

    try:
        tables = pd.read_html(StringIO(page_html))
    except ValueError:
        raise ValueError(
            "Baseball Reference returned no readable team-stat tables."
        )

    batting_table = detect_baseball_reference_batting_table(tables)
    stats_df, numeric_cols = clean_baseball_reference_stats_table(
        batting_table
    )

    return stats_df, numeric_cols, stats_url


def clean_mlb_api_player_name(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip(),
    )


@st.cache_data(ttl=1800, show_spinner=False)
def load_official_mlb_team_stats(team_abbr, season):
    team_id = MLB_TEAM_IDS_BY_BREF_ABBR.get(team_abbr)
    if not team_id:
        raise ValueError(
            f"Could not find an MLB team ID for {team_abbr}."
        )

    url = (
        "https://statsapi.mlb.com/api/v1/stats"
        "?stats=season"
        "&group=hitting"
        "&sportIds=1"
        f"&teamId={team_id}"
        f"&season={int(season)}"
        "&playerPool=ALL"
        "&limit=500"
        "&hydrate=person"
    )

    payload = fetch_json(url)
    splits = []

    for stats_group in payload.get("stats", []):
        splits.extend(stats_group.get("splits", []))

    rows = []
    for split in splits:
        player = split.get("player", {})
        stat = split.get("stat", {})

        player_name = clean_mlb_api_player_name(
            player.get("fullName", "")
        )
        if not player_name:
            continue

        row = {
            "Player": player_name,
            "Age": player.get("currentAge"),
            "G": stat.get("gamesPlayed"),
            "PA": stat.get("plateAppearances"),
            "AB": stat.get("atBats"),
            "R": stat.get("runs"),
            "H": stat.get("hits"),
            "2B": stat.get("doubles"),
            "3B": stat.get("triples"),
            "HR": stat.get("homeRuns"),
            "RBI": stat.get("rbi"),
            "SB": stat.get("stolenBases"),
            "CS": stat.get("caughtStealing"),
            "BB": stat.get("baseOnBalls"),
            "SO": stat.get("strikeOuts"),
            "AVG": stat.get("avg"),
            "OBP": stat.get("obp"),
            "SLG": stat.get("slg"),
            "OPS": stat.get("ops"),
            "TB": stat.get("totalBases"),
            "HBP": stat.get("hitByPitch"),
            "SF": stat.get("sacFlies"),
        }
        rows.append(row)

    if not rows:
        raise ValueError(
            "No official MLB batting statistics were returned for the selected team and season."
        )

    stats_df = pd.DataFrame(rows)

    for col in stats_df.columns:
        if col == "Player":
            continue
        stats_df[col] = pd.to_numeric(
            stats_df[col],
            errors="coerce",
        )

    stats_df = stats_df[
        stats_df.get("PA", pd.Series(0, index=stats_df.index))
        .fillna(0) > 0
    ].copy()

    if "SLG" in stats_df.columns and "AVG" in stats_df.columns:
        stats_df["ISO"] = stats_df["SLG"] - stats_df["AVG"]

    if "BB" in stats_df.columns and "PA" in stats_df.columns:
        stats_df["BB%"] = np.where(
            stats_df["PA"] > 0,
            stats_df["BB"] / stats_df["PA"] * 100,
            np.nan,
        )

    if "SO" in stats_df.columns and "PA" in stats_df.columns:
        stats_df["K%"] = np.where(
            stats_df["PA"] > 0,
            stats_df["SO"] / stats_df["PA"] * 100,
            np.nan,
        )

    if "SB" in stats_df.columns and "CS" in stats_df.columns:
        attempts = (
            stats_df["SB"].fillna(0)
            + stats_df["CS"].fillna(0)
        )
        stats_df["SB%"] = np.where(
            attempts > 0,
            stats_df["SB"].fillna(0) / attempts * 100,
            np.nan,
        )

    stats_df["_name_key"] = stats_df["Player"].apply(
        normalize_player_key
    )

    def player_keys(player_name):
        key = normalize_player_key(player_name)
        keys = {key} if key else set()
        parts = key.split()

        if len(parts) >= 2:
            keys.add(parts[-1])
            keys.add(f"{parts[0][0]} {parts[-1]}")

        return sorted(keys)

    stats_df["_all_name_keys"] = stats_df["Player"].apply(
        player_keys
    )
    stats_df = stats_df.drop_duplicates(
        "_name_key",
        keep="first",
    )

    numeric_cols = [
        col for col in stats_df.columns
        if col not in {
            "Player", "_name_key", "_all_name_keys"
        }
        and pd.api.types.is_numeric_dtype(stats_df[col])
        and stats_df[col].notna().sum() >= 3
        and stats_df[col].nunique(dropna=True) >= 2
    ]

    return stats_df.reset_index(drop=True), numeric_cols


@st.cache_data(ttl=1800, show_spinner=False)
def load_team_stats_with_fallback(team_abbr, season):
    try:
        stats_df, numeric_cols, stats_url = (
            load_baseball_reference_team_stats(
                team_abbr,
                season,
            )
        )
        source_note = (
            "Baseball Reference standard batting table"
        )
        return (
            stats_df,
            numeric_cols,
            source_note,
            stats_url,
        )
    except Exception:
        stats_df, numeric_cols = load_official_mlb_team_stats(
            team_abbr,
            season,
        )
        stats_url = build_baseball_reference_team_stats_url(
            team_abbr,
            season,
        )
        source_note = (
            "Official MLB season batting statistics were used because "
            "the Baseball Reference batting table could not be read."
        )
        return (
            stats_df,
            numeric_cols,
            source_note,
            stats_url,
        )

def read_historical_stats_csv(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as exc:
        raise ValueError(f"Could not read season stats CSV: {exc}")

    df = clean_colnames(df)

    candidate_name_columns = [
        col for col in [
            find_column(df, ["playerFullName", "PlayerFullName", "Full Name"]),
            find_column(df, ["Player", "Name", "playerName", "player_name"]),
            find_column(df, ["abbrevName", "AbbrevName", "Abbreviated Name"]),
            find_column(df, ["player", "Last Name", "lastName"]),
        ]
        if col is not None
    ]
    candidate_name_columns = list(dict.fromkeys(candidate_name_columns))

    if not candidate_name_columns:
        raise ValueError(
            "Could not find a player-name column in the season stats CSV."
        )

    primary_name_col = (
        find_column(df, ["playerFullName", "PlayerFullName", "Full Name"])
        or candidate_name_columns[0]
    )

    df["Player"] = df[primary_name_col].astype(str).str.strip()

    # Remove total rows, repeated header rows, and blank-name rows.
    invalid_names = {
        "", "nan", "none", "null", "total",
        "playerfullname", "player", "name",
    }
    df = df[
        ~df["Player"].str.lower().str.strip().isin(invalid_names)
    ].copy()

    # Build multiple normalized keys for each player.
    def row_name_keys(row):
        keys = set()
        for col in candidate_name_columns:
            value = row.get(col)
            key = normalize_player_key(value)
            if key and key not in invalid_names:
                keys.add(key)

                parts = key.split()
                if len(parts) >= 2:
                    keys.add(parts[-1])
                    keys.add(f"{parts[0][0]} {parts[-1]}")
        return sorted(keys)

    df["_all_name_keys"] = df.apply(row_name_keys, axis=1)
    df["_name_key"] = df["Player"].apply(normalize_player_key)

    excluded = {
        primary_name_col.lower(),
        "player", "_name_key", "_all_name_keys",
        "playerid", "player id", "id",
        "team", "level", "position", "pos",
        "bats", "batshand",
    }

    numeric_cols = []
    for col in df.columns:
        if str(col).lower().strip() in excluded:
            continue
        if col in candidate_name_columns:
            continue

        converted = pd.to_numeric(
            df[col]
            .astype(str)
            .str.replace("%", "", regex=False)
            .str.replace(",", "", regex=False),
            errors="coerce",
        )
        if converted.notna().sum() >= max(3, int(len(df) * 0.25)):
            df[col] = converted
            numeric_cols.append(col)

    if not numeric_cols:
        raise ValueError(
            "No usable numeric stat columns were detected in the season stats CSV."
        )

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

    key_to_index = {}
    for idx, row in stats_unique.iterrows():
        keys = row.get("_all_name_keys", [])
        if not isinstance(keys, list):
            keys = []
        keys = set(keys)
        keys.add(row.get("_name_key", ""))

        for key in keys:
            if key:
                key_to_index.setdefault(key, idx)

    available_keys = set(key_to_index.keys())

    matched_indexes = []
    match_scores = []
    match_methods = []

    for lineup_name, lineup_key in zip(
        lineups["Player"],
        lineups["_name_key"],
    ):
        matched_index = None
        score = 0.0
        method = "Unmatched"

        if lineup_key in key_to_index:
            matched_index = key_to_index[lineup_key]
            score = 1.0
            method = "Exact"
        else:
            name_parts = lineup_key.split()
            last_name = name_parts[-1] if name_parts else ""

            last_name_candidates = [
                key for key in available_keys
                if key.split() and key.split()[-1] == last_name
            ]

            candidate_pool = (
                last_name_candidates
                if last_name_candidates
                else list(available_keys)
            )

            best_key = ""
            best_score = 0.0
            for candidate in candidate_pool:
                candidate_score = SequenceMatcher(
                    None,
                    lineup_key,
                    candidate,
                ).ratio()

                candidate_parts = candidate.split()
                if (
                    name_parts
                    and candidate_parts
                    and name_parts[-1] == candidate_parts[-1]
                ):
                    candidate_score += 0.10

                if candidate_score > best_score:
                    best_key = candidate
                    best_score = candidate_score

            if best_key and best_score >= 0.80:
                matched_index = key_to_index[best_key]
                score = min(best_score, 1.0)
                method = "Fuzzy"

        matched_indexes.append(matched_index)
        match_scores.append(score)
        match_methods.append(method)

    lineups["_stats_index"] = matched_indexes
    lineups["NameMatchScore"] = match_scores
    lineups["NameMatchMethod"] = match_methods

    stats_for_merge = stats_unique.copy()
    stats_for_merge["_stats_index"] = stats_for_merge.index

    merged = lineups.merge(
        stats_for_merge.drop(columns=["Player"], errors="ignore"),
        how="left",
        on="_stats_index",
        suffixes=("", "_stats"),
    )

    unmatched = (
        lineups[lineups["_stats_index"].isna()]["Player"]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    matched_players = (
        lineups[lineups["_stats_index"].notna()]["Player"]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    return merged, unmatched, matched_players



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

    def draw_simple_table(
        dataframe,
        x,
        y_top,
        width,
        title,
        max_rows=10,
        row_height=15,
        title_gap=22,
    ):
        c.setFillColor(navy)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y_top, title)

        if dataframe is None or dataframe.empty:
            c.setFont("Helvetica", 8)
            c.drawString(x, y_top - 18, "Not enough data.")
            return y_top - 18

        view = dataframe.head(max_rows).copy()
        three_decimal_stats = {"AVG", "OBP", "SLG", "OPS", "ISO"}

        for col in view.columns:
            if pd.api.types.is_float_dtype(view[col]):
                if str(col).strip().upper() in three_decimal_stats:
                    view[col] = view[col].map(
                        lambda v: f"{v:.3f}" if pd.notna(v) else ""
                    )
                else:
                    view[col] = view[col].map(
                        lambda v: f"{v:.2f}" if pd.notna(v) else ""
                    )

        rows = [list(view.columns)] + view.astype(str).values.tolist()
        col_width = width / len(view.columns)
        table_height = row_height * len(rows)
        table_bottom = y_top - title_gap - table_height

        table = Table(
            rows,
            colWidths=[col_width] * len(view.columns),
            rowHeights=[row_height] * len(rows),
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 5.9),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9DEE7")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ]))
        table.wrapOn(c, width, table_height)
        table.drawOn(c, x, table_bottom)
        return table_bottom

    imp_view = (
        importance_df[["Trait", "ImportanceScore", "Direction"]].copy()
        if not importance_df.empty
        else importance_df
    )
    usage_view = (
        usage_df[["Player", "Starts", "StartRate", "AverageSpot"]].copy()
        if not usage_df.empty
        else usage_df
    )

    # Compact upper tables and preserve a clear visual gap before
    # the lineup-spot profile section.
    upper_title_y = page_h - 180
    upper_left_bottom = draw_simple_table(
        imp_view,
        30,
        upper_title_y,
        350,
        "MOST EMPHASIZED TRAITS",
        max_rows=10,
        row_height=15,
        title_gap=22,
    )
    upper_right_bottom = draw_simple_table(
        usage_view,
        410,
        upper_title_y,
        350,
        "PLAYER USAGE",
        max_rows=10,
        row_height=15,
        title_gap=22,
    )

    upper_tables_bottom = min(
        upper_left_bottom,
        upper_right_bottom,
    )

    # Keep at least 18 points between the upper tables and this heading.
    profile_title_y = min(213, upper_tables_bottom - 18)
    profile_view = profiles_df.copy()
    draw_simple_table(
        profile_view,
        30,
        profile_title_y,
        page_w - 60,
        "AVERAGE PROFILE BY LINEUP SPOT",
        max_rows=9,
        row_height=15,
        title_gap=22,
    )

    c.setFillColor(red)
    c.rect(30, 28, page_w - 60, 4, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#666666"))
    c.setFont("Helvetica", 6.5)
    c.drawString(30, 16, "Observed lineup associations; results should be interpreted with sample size and data timing in mind.")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer



LIDOM_TEAM_OPTIONS = {
    "Águilas Cibaeñas": "AC",
    "Estrellas Orientales": "EO",
    "Gigantes del Cibao": "GC",
    "Leones del Escogido": "LE",
    "Tigres del Licey": "TL",
    "Toros del Este": "TE",
}


def lidom_season_options():
    current_year = date.today().year
    return [
        f"{year}-{str(year + 1)[-2:]}"
        for year in range(current_year, 1999, -1)
    ]


def standardize_lidom_lineups(uploaded_file, team_name, season_label):
    try:
        raw = pd.read_csv(uploaded_file)
    except Exception as exc:
        raise ValueError(f"Could not read the LIDOM lineup CSV: {exc}")

    raw = clean_colnames(raw)

    date_col = find_column(
        raw,
        ["Date", "GameDate", "Game Date", "Fecha", "game_date"],
    )
    player_col = find_column(
        raw,
        [
            "Player", "playerFullName", "PlayerFullName",
            "Name", "playerName", "Jugador",
        ],
    )
    spot_col = find_column(
        raw,
        [
            "LineupSpot", "Lineup Spot", "BattingOrder",
            "Batting Order", "Order", "Spot", "Turno",
        ],
    )

    opponent_col = find_column(
        raw,
        ["Opponent", "Opp", "Oponente", "Rival"],
    )
    result_col = find_column(
        raw,
        ["Result", "Resultado", "W/L", "WL"],
    )
    home_away_col = find_column(
        raw,
        ["HomeAway", "Home/Away", "LocalVisitante", "H/A"],
    )
    pitcher_col = find_column(
        raw,
        [
            "OpposingStarter", "Opposing Starter",
            "Opp Pitcher", "Pitcher", "Abridor Rival",
        ],
    )
    pitcher_hand_col = find_column(
        raw,
        [
            "OpposingPitcherHand", "Opposing Pitcher Hand",
            "PitcherHand", "Pitcher Hand", "Hand",
        ],
    )
    bats_col = find_column(
        raw,
        ["Bats", "batsHand", "BatSide", "Batea"],
    )
    position_col = find_column(
        raw,
        ["Position", "POS", "Pos", "Posición"],
    )
    game_id_col = find_column(
        raw,
        ["GamePk", "GameID", "Game ID", "game_id", "JuegoID"],
    )

    # Long format: one row per player per game.
    if player_col and spot_col:
        result = pd.DataFrame()
        result["Date"] = pd.to_datetime(
            raw[date_col] if date_col else pd.NaT,
            errors="coerce",
        ).dt.date
        result["Player"] = raw[player_col].astype(str).str.strip()
        result["LineupSpot"] = pd.to_numeric(
            raw[spot_col],
            errors="coerce",
        )
        result["Opponent"] = (
            raw[opponent_col].astype(str).str.strip()
            if opponent_col else ""
        )
        result["Result"] = (
            raw[result_col].astype(str).str.strip()
            if result_col else ""
        )
        result["HomeAway"] = (
            raw[home_away_col].astype(str).str.strip()
            if home_away_col else ""
        )
        result["OpposingStarter"] = (
            raw[pitcher_col].astype(str).str.strip()
            if pitcher_col else ""
        )
        result["OpposingPitcherHand"] = (
            raw[pitcher_hand_col].astype(str).str.upper().str.strip()
            if pitcher_hand_col else "Unknown"
        )
        result["Bats"] = (
            raw[bats_col].apply(normalize_bats)
            if bats_col else ""
        )
        result["Position"] = (
            raw[position_col].apply(normalize_position)
            if position_col else ""
        )

        if game_id_col:
            result["GamePk"] = raw[game_id_col].astype(str)
        else:
            result["GamePk"] = [
                f"LIDOM-{season_label}-{d or 'NA'}-{i // 9 + 1}"
                for i, d in enumerate(result["Date"])
            ]

    else:
        # Wide format: one row per game with lineup columns 1 through 9.
        spot_columns = {}
        for col in raw.columns:
            cleaned = str(col).strip().lower()
            match = re.fullmatch(
                r"(?:spot|lineup|order|batting order|turno)?\s*([1-9])",
                cleaned,
            )
            if match:
                spot_columns[int(match.group(1))] = col

        if len(spot_columns) < 9:
            raise ValueError(
                "The LIDOM lineup CSV must either contain Player and LineupSpot "
                "columns, or nine lineup columns labeled 1 through 9."
            )

        rows = []
        for row_index, row in raw.iterrows():
            parsed_date = pd.to_datetime(
                row.get(date_col, "") if date_col else "",
                errors="coerce",
            )
            game_date = parsed_date.date() if pd.notna(parsed_date) else None
            game_id = (
                str(row.get(game_id_col))
                if game_id_col
                else f"LIDOM-{season_label}-{game_date or row_index}-{row_index}"
            )

            for spot in range(1, 10):
                player_name = str(
                    row.get(spot_columns[spot], "")
                ).strip()
                if not player_name or player_name.lower() in {
                    "nan", "none", "-", "n/a",
                }:
                    continue

                rows.append({
                    "Date": game_date,
                    "GamePk": game_id,
                    "Player": player_name,
                    "LineupSpot": spot,
                    "Opponent": (
                        str(row.get(opponent_col, "")).strip()
                        if opponent_col else ""
                    ),
                    "Result": (
                        str(row.get(result_col, "")).strip()
                        if result_col else ""
                    ),
                    "HomeAway": (
                        str(row.get(home_away_col, "")).strip()
                        if home_away_col else ""
                    ),
                    "OpposingStarter": (
                        str(row.get(pitcher_col, "")).strip()
                        if pitcher_col else ""
                    ),
                    "OpposingPitcherHand": (
                        str(row.get(pitcher_hand_col, "Unknown")).upper().strip()
                        if pitcher_hand_col else "Unknown"
                    ),
                    "Bats": "",
                    "Position": "",
                })

        result = pd.DataFrame(rows)

    if result.empty:
        raise ValueError("No usable LIDOM lineup rows were found.")

    result["LineupSpot"] = pd.to_numeric(
        result["LineupSpot"],
        errors="coerce",
    )
    result = result[
        result["LineupSpot"].between(1, 9)
        & result["Player"].astype(str).str.strip().ne("")
    ].copy()

    result["Team"] = team_name
    result["Venue"] = ""
    result["PlayerID"] = ""
    result["Source"] = "Uploaded LIDOM historical lineups"

    # Normalize hand labels.
    result["OpposingPitcherHand"] = (
        result["OpposingPitcherHand"]
        .replace({
            "RHP": "R", "RIGHT": "R", "D": "R",
            "LHP": "L", "LEFT": "L", "Z": "L",
        })
        .fillna("Unknown")
    )

    result = result.drop_duplicates(
        subset=["GamePk", "LineupSpot", "Player"],
    ).sort_values(
        ["Date", "GamePk", "LineupSpot"],
        na_position="last",
    ).reset_index(drop=True)

    return result


def lidom_lineup_template():
    columns = [
        "Date", "GameID", "Opponent", "Result", "HomeAway",
        "OpposingStarter", "OpposingPitcherHand",
        "LineupSpot", "Player", "Bats", "Position",
    ]
    sample_rows = []
    for spot in range(1, 10):
        sample_rows.append({
            "Date": "2025-10-15",
            "GameID": "LE-2025-10-15-1",
            "Opponent": "Tigres del Licey",
            "Result": "W 4-2",
            "HomeAway": "Home",
            "OpposingStarter": "Pitcher Name",
            "OpposingPitcherHand": "R",
            "LineupSpot": spot,
            "Player": f"Player {spot}",
            "Bats": "R",
            "Position": "",
        })
    return pd.DataFrame(sample_rows, columns=columns)


def lidom_stats_template():
    return pd.DataFrame(
        columns=[
            "playerFullName", "PA", "AVG", "OBP", "SLG",
            "OPS", "HR", "BB", "SO", "SB", "CS",
        ]
    )


LIDOM_DIGIMETRICS_BASE = "https://estadisticas.lidom.com"

LIDOM_TEAM_NAME_ALIASES = {
    "Águilas Cibaeñas": [
        "aguilas cibaeñas", "aguilas cibaeñas", "aguilas",
    ],
    "Estrellas Orientales": [
        "estrellas orientales", "estrellas",
    ],
    "Gigantes del Cibao": [
        "gigantes del cibao", "gigantes",
    ],
    "Leones del Escogido": [
        "leones del escogido", "escogido", "leones",
    ],
    "Tigres del Licey": [
        "tigres del licey", "licey", "tigres",
    ],
    "Toros del Este": [
        "toros del este", "toros",
    ],
}


def normalize_lidom_text(value):
    if pd.isna(value):
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(
        ch for ch in normalized
        if not unicodedata.combining(ch)
    )
    normalized = normalized.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def lidom_request(url, timeout=30):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "es-DO,es;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_lidom_game_links(page_html, base_url=LIDOM_DIGIMETRICS_BASE):
    links = set()

    for href in re.findall(
        r'href=["\']([^"\']+)["\']',
        page_html,
        flags=re.I,
    ):
        absolute = urljoin(base_url, unescape(href))
        if re.search(
            r"/Partido/Detalle\?idPartido=\d+",
            absolute,
            flags=re.I,
        ):
            links.add(absolute)

    # Some pages expose game IDs inside JavaScript rather than anchor tags.
    for game_id in re.findall(
        r"idPartido\s*[=:]\s*['\"]?(\d+)",
        page_html,
        flags=re.I,
    ):
        links.add(
            f"{LIDOM_DIGIMETRICS_BASE}/Partido/Detalle"
            f"?idPartido={game_id}"
        )

    return sorted(links)


def parse_lidom_season_start_year(season_label):
    match = re.match(r"(\d{4})", str(season_label))
    if not match:
        raise ValueError(
            f"Could not interpret LIDOM season: {season_label}"
        )
    return int(match.group(1))


def lidom_date_matches_season(game_date, season_label):
    if game_date is None or pd.isna(game_date):
        return True

    start_year = parse_lidom_season_start_year(season_label)
    allowed_years = {start_year, start_year + 1}
    return pd.Timestamp(game_date).year in allowed_years


def find_date_in_lidom_page(page_html):
    text_only = re.sub(r"<[^>]+>", " ", page_html)
    text_only = unescape(text_only)

    date_patterns = [
        r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\d{1,2}-\d{1,2}-\d{4})\b",
    ]

    for pattern in date_patterns:
        match = re.search(pattern, text_only)
        if match:
            parsed = pd.to_datetime(
                match.group(1),
                dayfirst=True,
                errors="coerce",
            )
            if pd.notna(parsed):
                return parsed.date()

    return None


def identify_lidom_team_from_text(value):
    normalized = normalize_lidom_text(value)

    for team_name, aliases in LIDOM_TEAM_NAME_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return team_name

    return ""


def flatten_lidom_table_columns(df):
    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        flattened = []
        for parts in df.columns:
            clean_parts = [
                str(part).strip()
                for part in parts
                if str(part).strip()
                and not str(part).startswith("Unnamed")
            ]
            flattened.append(
                " ".join(dict.fromkeys(clean_parts)).strip()
            )
        df.columns = flattened
    else:
        df.columns = [
            str(col).strip()
            for col in df.columns
        ]

    return df


def detect_lidom_batting_tables(tables):
    detected = []

    for table_index, table in enumerate(tables):
        frame = flatten_lidom_table_columns(table)
        lower_cols = [
            normalize_lidom_text(col)
            for col in frame.columns
        ]

        has_batter = any(
            col in {
                "bateador", "jugador", "player", "nombre",
            }
            or "bateador" in col
            for col in lower_cols
        )
        has_ab = any(
            col == "ab" or "turnos" in col
            for col in lower_cols
        )
        has_hits = any(col == "h" for col in lower_cols)
        has_runs = any(col == "r" for col in lower_cols)

        score = (
            int(has_batter) * 10
            + int(has_ab) * 4
            + int(has_hits) * 3
            + int(has_runs) * 2
        )

        if score >= 14 and len(frame) >= 5:
            detected.append(
                {
                    "index": table_index,
                    "score": score,
                    "frame": frame,
                }
            )

    return detected


def find_lidom_col(df, aliases):
    normalized_map = {
        normalize_lidom_text(col): col
        for col in df.columns
    }

    for alias in aliases:
        normalized_alias = normalize_lidom_text(alias)
        if normalized_alias in normalized_map:
            return normalized_map[normalized_alias]

    for normalized_col, original_col in normalized_map.items():
        for alias in aliases:
            normalized_alias = normalize_lidom_text(alias)
            if normalized_alias in normalized_col:
                return original_col

    return None


def clean_lidom_batter_name(value):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    value = unescape(value)
    value = re.sub(r"\s+", " ", value).strip()

    # Remove common substitution/order markers while keeping the actual name.
    value = re.sub(r"^\d+[\.\-\)]\s*", "", value)
    value = re.sub(r"^[a-z]\-\s*", "", value, flags=re.I)
    value = re.sub(r"\s+\((?:PH|PR|DR|C|1B|2B|3B|SS|LF|CF|RF|OF|DH)\)$", "", value, flags=re.I)
    value = re.sub(r"\s+(?:PH|PR|DR)$", "", value, flags=re.I)

    return value.strip()


def infer_team_for_batting_table(
    frame,
    table_index,
    batting_tables,
    page_text,
):
    # Often the table immediately follows a team heading. Search text around
    # the first player name and use the closest recognized team name.
    first_col = frame.columns[0] if len(frame.columns) else None
    sample_name = ""
    if first_col is not None and not frame.empty:
        sample_name = clean_lidom_batter_name(
            frame.iloc[0][first_col]
        )

    normalized_page = normalize_lidom_text(page_text)
    sample_key = normalize_lidom_text(sample_name)

    if sample_key:
        position = normalized_page.find(sample_key)
        if position >= 0:
            nearby = normalized_page[
                max(0, position - 700): position + 200
            ]
            team = identify_lidom_team_from_text(nearby)
            if team:
                return team

    # Fallback: preserve page order. Official box scores normally list
    # visiting batting table first and home batting table second.
    known_teams = []
    for team_name in LIDOM_TEAM_OPTIONS:
        if any(
            alias in normalized_page
            for alias in LIDOM_TEAM_NAME_ALIASES[team_name]
        ):
            known_teams.append(team_name)

    if len(known_teams) >= 2:
        relative_index = [
            item["index"]
            for item in batting_tables
        ].index(table_index)
        return known_teams[
            min(relative_index, len(known_teams) - 1)
        ]

    return ""


def parse_lidom_batting_table(
    frame,
    team_name,
    game_id,
    game_date,
    opponent,
):
    frame = flatten_lidom_table_columns(frame)

    player_col = find_lidom_col(
        frame,
        ["Bateador", "Jugador", "Player", "Nombre"],
    )
    if player_col is None:
        player_col = frame.columns[0]

    aliases = {
        "AB": ["AB", "Turnos"],
        "R": ["R", "Carreras"],
        "H": ["H", "Hits"],
        "2B": ["2B"],
        "3B": ["3B"],
        "HR": ["HR"],
        "RBI": ["RBI", "CE"],
        "BB": ["BB", "Boletos"],
        "SO": ["SO", "K", "Ponches"],
        "AVG": ["AVG", "AVGA"],
        "OBP": ["OBP"],
        "SLG": ["SLG"],
        "SB": ["SB", "BR"],
        "CS": ["CS"],
    }

    mapped_cols = {
        standard: find_lidom_col(frame, candidates)
        for standard, candidates in aliases.items()
    }

    parsed_rows = []
    lineup_candidates = []

    for source_index, source_row in frame.iterrows():
        player_name = clean_lidom_batter_name(
            source_row.get(player_col, "")
        )

        if not player_name:
            continue

        normalized_name = normalize_lidom_text(player_name)
        if normalized_name in {
            "totales", "total", "team totals",
            "bateador", "jugador",
        }:
            continue

        row = {
            "Date": game_date,
            "GamePk": game_id,
            "Team": team_name,
            "Opponent": opponent,
            "Player": player_name,
            "PlayerID": "",
            "Bats": "",
            "Position": "",
            "Source": "LIDOM Digimetrics",
        }

        for standard, source_col in mapped_cols.items():
            if source_col is not None:
                row[standard] = pd.to_numeric(
                    source_row.get(source_col),
                    errors="coerce",
                )

        parsed_rows.append(row)

        # The first nine non-substitution rows in official batting order
        # tables represent the starters. Indented or prefixed rows are
        # generally substitutions.
        raw_name = str(source_row.get(player_col, ""))
        is_substitute = bool(
            re.match(r"^\s{2,}", raw_name)
            or re.match(r"^[a-z]\-", raw_name, flags=re.I)
            or re.search(
                r"\b(?:PH|PR|DR)\b",
                raw_name,
                flags=re.I,
            )
        )

        if not is_substitute and player_name not in lineup_candidates:
            lineup_candidates.append(player_name)

    lineup_candidates = lineup_candidates[:9]

    lineup_rows = []
    for spot, player_name in enumerate(
        lineup_candidates,
        start=1,
    ):
        lineup_rows.append({
            "Date": game_date,
            "GamePk": game_id,
            "Team": team_name,
            "Opponent": opponent,
            "Result": "",
            "HomeAway": "",
            "Venue": "",
            "OpposingStarter": "",
            "OpposingPitcherHand": "Unknown",
            "LineupSpot": spot,
            "PlayerID": "",
            "Player": player_name,
            "Bats": "",
            "Position": "",
            "Source": "LIDOM Digimetrics",
        })

    return lineup_rows, parsed_rows


def aggregate_lidom_batting_stats(boxscore_rows):
    if not boxscore_rows:
        raise ValueError(
            "No LIDOM batting box-score rows were available to aggregate."
        )

    df = pd.DataFrame(boxscore_rows)

    count_stats = [
        col for col in [
            "AB", "R", "H", "2B", "3B", "HR",
            "RBI", "BB", "SO", "SB", "CS",
        ]
        if col in df.columns
    ]

    for col in count_stats:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        ).fillna(0)

    grouped = (
        df.groupby("Player", as_index=False)[count_stats]
        .sum()
    )

    games = (
        df.groupby("Player")["GamePk"]
        .nunique()
        .rename("G")
        .reset_index()
    )
    grouped = grouped.merge(
        games,
        on="Player",
        how="left",
    )

    # Approximate PA from official countable outcomes available in the
    # box score. HBP/SF may not always be exposed, so PA is conservative.
    grouped["PA"] = (
        grouped.get("AB", 0)
        + grouped.get("BB", 0)
    )

    grouped["AVG"] = np.where(
        grouped.get("AB", 0) > 0,
        grouped.get("H", 0) / grouped.get("AB", 0),
        np.nan,
    )

    total_bases = (
        grouped.get("H", 0)
        + grouped.get("2B", 0)
        + 2 * grouped.get("3B", 0)
        + 3 * grouped.get("HR", 0)
    )
    grouped["TB"] = total_bases

    grouped["SLG"] = np.where(
        grouped.get("AB", 0) > 0,
        total_bases / grouped.get("AB", 0),
        np.nan,
    )

    grouped["OBP"] = np.where(
        grouped["PA"] > 0,
        (
            grouped.get("H", 0)
            + grouped.get("BB", 0)
        ) / grouped["PA"],
        np.nan,
    )
    grouped["OPS"] = grouped["OBP"] + grouped["SLG"]
    grouped["ISO"] = grouped["SLG"] - grouped["AVG"]

    grouped["BB%"] = np.where(
        grouped["PA"] > 0,
        grouped.get("BB", 0) / grouped["PA"] * 100,
        np.nan,
    )
    grouped["K%"] = np.where(
        grouped["PA"] > 0,
        grouped.get("SO", 0) / grouped["PA"] * 100,
        np.nan,
    )

    attempts = (
        grouped.get("SB", 0)
        + grouped.get("CS", 0)
    )
    grouped["SB%"] = np.where(
        attempts > 0,
        grouped.get("SB", 0) / attempts * 100,
        np.nan,
    )

    grouped["_name_key"] = grouped["Player"].apply(
        normalize_player_key
    )

    def player_keys(player_name):
        key = normalize_player_key(player_name)
        keys = {key} if key else set()
        parts = key.split()
        if len(parts) >= 2:
            keys.add(parts[-1])
            keys.add(f"{parts[0][0]} {parts[-1]}")
        return sorted(keys)

    grouped["_all_name_keys"] = grouped["Player"].apply(
        player_keys
    )

    numeric_cols = [
        col for col in grouped.columns
        if col not in {
            "Player", "_name_key", "_all_name_keys",
        }
        and pd.api.types.is_numeric_dtype(grouped[col])
        and grouped[col].notna().sum() >= 3
        and grouped[col].nunique(dropna=True) >= 2
    ]

    return grouped, numeric_cols


@st.cache_data(ttl=3600, show_spinner=False)
def load_lidom_digimetrics_data(
    selected_team_name,
    selected_season,
):
    seed_urls = [
        f"{LIDOM_DIGIMETRICS_BASE}/",
        f"{LIDOM_DIGIMETRICS_BASE}/PlayByPlay",
        f"{LIDOM_DIGIMETRICS_BASE}/Partido",
        f"{LIDOM_DIGIMETRICS_BASE}/Partido/Index",
    ]

    game_links = set()
    seed_errors = []

    for seed_url in seed_urls:
        try:
            seed_html = lidom_request(seed_url)
            game_links.update(
                extract_lidom_game_links(
                    seed_html,
                    seed_url,
                )
            )
        except Exception as exc:
            seed_errors.append(
                f"{seed_url}: {exc}"
            )

    if not game_links:
        raise ValueError(
            "Digimetrics did not expose any game-detail links. "
            "The site may be temporarily blocking automated access."
        )

    lineup_rows = []
    target_boxscore_rows = []
    games_checked = 0
    games_used = 0

    for game_url in sorted(game_links):
        try:
            page_html = lidom_request(game_url)
            game_date = find_date_in_lidom_page(page_html)

            if not lidom_date_matches_season(
                game_date,
                selected_season,
            ):
                continue

            page_text = unescape(
                re.sub(r"<[^>]+>", " ", page_html)
            )
            normalized_page = normalize_lidom_text(
                page_text
            )

            target_aliases = LIDOM_TEAM_NAME_ALIASES[
                selected_team_name
            ]
            if not any(
                alias in normalized_page
                for alias in target_aliases
            ):
                continue

            game_id_match = re.search(
                r"idPartido=(\d+)",
                game_url,
                flags=re.I,
            )
            game_id = (
                f"LIDOM-{game_id_match.group(1)}"
                if game_id_match
                else game_url
            )

            tables = pd.read_html(
                StringIO(page_html)
            )
            batting_tables = detect_lidom_batting_tables(
                tables
            )
            if len(batting_tables) < 2:
                continue

            team_tables = []
            for batting_item in batting_tables:
                team_name = infer_team_for_batting_table(
                    batting_item["frame"],
                    batting_item["index"],
                    batting_tables,
                    page_text,
                )
                team_tables.append(
                    (
                        team_name,
                        batting_item["frame"],
                    )
                )

            present_teams = [
                team_name
                for team_name, _ in team_tables
                if team_name
            ]
            opponent = next(
                (
                    team
                    for team in present_teams
                    if team != selected_team_name
                ),
                "",
            )

            games_checked += 1

            for team_name, batting_frame in team_tables:
                if team_name != selected_team_name:
                    continue

                game_lineup, game_box_rows = (
                    parse_lidom_batting_table(
                        batting_frame,
                        team_name=selected_team_name,
                        game_id=game_id,
                        game_date=game_date,
                        opponent=opponent,
                    )
                )

                if len(game_lineup) >= 7:
                    lineup_rows.extend(game_lineup)
                    target_boxscore_rows.extend(
                        game_box_rows
                    )
                    games_used += 1
                    break

        except Exception:
            continue

    if not lineup_rows:
        raise ValueError(
            "No usable Digimetrics lineups were found for "
            f"{selected_team_name}, {selected_season}. "
            "The selected season may not be available from the site's "
            "current game index."
        )

    lineups_df = pd.DataFrame(lineup_rows)
    lineups_df = lineups_df.drop_duplicates(
        subset=["GamePk", "LineupSpot", "Player"],
    ).sort_values(
        ["Date", "GamePk", "LineupSpot"],
        na_position="last",
    ).reset_index(drop=True)

    stats_df, numeric_cols = (
        aggregate_lidom_batting_stats(
            target_boxscore_rows
        )
    )

    source_note = (
        "LIDOM Digimetrics official game box scores "
        f"({games_used} games imported)"
    )

    return (
        lineups_df,
        stats_df,
        numeric_cols,
        source_note,
    )


MLB_WINTER_SPORT_ID = 17

LIDOM_MLB_NAME_ALIASES = {
    "Águilas Cibaeñas": [
        "aguilas cibaeñas", "aguilas cibaeñas", "aguilas",
    ],
    "Estrellas Orientales": [
        "estrellas orientales", "estrellas",
    ],
    "Gigantes del Cibao": [
        "gigantes del cibao", "gigantes",
    ],
    "Leones del Escogido": [
        "leones del escogido", "escogido", "leones",
    ],
    "Tigres del Licey": [
        "tigres del licey", "licey", "tigres",
    ],
    "Toros del Este": [
        "toros del este", "toros",
    ],
}


def normalize_winter_name(value):
    if pd.isna(value):
        return ""

    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(
        character
        for character in value
        if not unicodedata.combining(character)
    )
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9 ]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def winter_season_date_range(season_label):
    match = re.match(r"(\d{4})", str(season_label))
    if not match:
        raise ValueError(
            f"Could not interpret winter season: {season_label}"
        )

    start_year = int(match.group(1))
    start_date = f"{start_year}-09-01"
    end_date = f"{start_year + 1}-02-28"
    return start_year, start_date, end_date


@st.cache_data(ttl=86400, show_spinner=False)
def discover_lidom_team_id(selected_team_name, season_label):
    start_year, _, _ = winter_season_date_range(season_label)

    possible_urls = [
        (
            "https://statsapi.mlb.com/api/v1/teams"
            f"?sportId={MLB_WINTER_SPORT_ID}"
            f"&season={start_year}"
        ),
        (
            "https://statsapi.mlb.com/api/v1/teams"
            f"?sportIds={MLB_WINTER_SPORT_ID}"
            f"&season={start_year}"
        ),
    ]

    teams = []
    last_error = None

    for teams_url in possible_urls:
        try:
            payload = fetch_json(teams_url)
            teams = payload.get("teams", [])
            if teams:
                break
        except Exception as exc:
            last_error = exc

    if not teams:
        raise ValueError(
            "MLB Winter Leagues did not return a team directory"
            + (f": {last_error}" if last_error else ".")
        )

    selected_aliases = [
        normalize_winter_name(alias)
        for alias in LIDOM_MLB_NAME_ALIASES[selected_team_name]
    ]

    candidates = []

    for team in teams:
        searchable_values = [
            team.get("name", ""),
            team.get("teamName", ""),
            team.get("clubName", ""),
            team.get("shortName", ""),
            team.get("locationName", ""),
            team.get("franchiseName", ""),
            team.get("abbreviation", ""),
        ]
        searchable_text = normalize_winter_name(
            " ".join(
                str(value)
                for value in searchable_values
                if value
            )
        )

        score = 0
        for alias in selected_aliases:
            if alias == searchable_text:
                score = max(score, 100)
            elif alias in searchable_text:
                score = max(score, 80)
            elif searchable_text and searchable_text in alias:
                score = max(score, 60)

        league_name = normalize_winter_name(
            team.get("league", {}).get("name", "")
        )
        if "dominican" in league_name:
            score += 20

        if score > 0:
            candidates.append(
                (
                    score,
                    team.get("id"),
                    team.get("name", selected_team_name),
                )
            )

    if not candidates:
        available = ", ".join(
            sorted(
                {
                    str(team.get("name", ""))
                    for team in teams
                    if team.get("name")
                }
            )
        )
        raise ValueError(
            f"Could not identify {selected_team_name} in MLB Winter Leagues. "
            f"Available teams included: {available[:800]}"
        )

    candidates.sort(reverse=True)
    _, team_id, official_team_name = candidates[0]

    return int(team_id), official_team_name


def extract_winter_boxscore_batting_rows(
    feed,
    team_id,
    game_date,
):
    game_data = feed.get("gameData", {})
    teams = game_data.get("teams", {})
    home_id = teams.get("home", {}).get("id")
    away_id = teams.get("away", {}).get("id")

    if team_id == home_id:
        team_side = "home"
    elif team_id == away_id:
        team_side = "away"
    else:
        return []

    team_box = (
        feed.get("liveData", {})
        .get("boxscore", {})
        .get("teams", {})
        .get(team_side, {})
    )

    game_pk = game_data.get("game", {}).get("pk", "")
    players_data = game_data.get("players", {})
    box_players = team_box.get("players", {})

    batting_order_ids = set(team_box.get("battingOrder", []))
    rows = []

    for player_key, player_box in box_players.items():
        person = player_box.get("person", {})
        player_id = person.get("id")

        batting = (
            player_box.get("stats", {})
            .get("batting", {})
        )

        if not batting:
            continue

        at_bats = pd.to_numeric(
            batting.get("atBats"),
            errors="coerce",
        )
        plate_appearances = pd.to_numeric(
            batting.get("plateAppearances"),
            errors="coerce",
        )

        if (
            (pd.isna(at_bats) or at_bats == 0)
            and (
                pd.isna(plate_appearances)
                or plate_appearances == 0
            )
            and player_id not in batting_order_ids
        ):
            continue

        player_data = players_data.get(
            f"ID{player_id}",
            {},
        )

        rows.append({
            "Date": pd.to_datetime(game_date).date(),
            "GamePk": game_pk,
            "PlayerID": player_id,
            "Player": (
                player_data.get("fullName")
                or person.get("fullName")
                or ""
            ),
            "G": 1,
            "PA": batting.get("plateAppearances", 0),
            "AB": batting.get("atBats", 0),
            "R": batting.get("runs", 0),
            "H": batting.get("hits", 0),
            "2B": batting.get("doubles", 0),
            "3B": batting.get("triples", 0),
            "HR": batting.get("homeRuns", 0),
            "RBI": batting.get("rbi", 0),
            "BB": batting.get("baseOnBalls", 0),
            "SO": batting.get("strikeOuts", 0),
            "SB": batting.get("stolenBases", 0),
            "CS": batting.get("caughtStealing", 0),
            "HBP": batting.get("hitByPitch", 0),
            "SF": batting.get("sacFlies", 0),
        })

    return rows


def aggregate_winter_game_stats(game_stat_rows):
    if not game_stat_rows:
        raise ValueError(
            "No player batting statistics were found in the "
            "MLB Winter Leagues game feeds."
        )

    raw = pd.DataFrame(game_stat_rows)

    numeric_count_columns = [
        "PA", "AB", "R", "H", "2B", "3B", "HR",
        "RBI", "BB", "SO", "SB", "CS", "HBP", "SF",
    ]

    for column in numeric_count_columns:
        if column not in raw.columns:
            raw[column] = 0
        raw[column] = pd.to_numeric(
            raw[column],
            errors="coerce",
        ).fillna(0)

    grouped = (
        raw.groupby(
            ["PlayerID", "Player"],
            as_index=False,
        )[numeric_count_columns]
        .sum()
    )

    games = (
        raw.groupby(
            ["PlayerID", "Player"],
            as_index=False,
        )["GamePk"]
        .nunique()
        .rename(columns={"GamePk": "G"})
    )

    grouped = grouped.merge(
        games,
        on=["PlayerID", "Player"],
        how="left",
    )

    grouped["AVG"] = np.where(
        grouped["AB"] > 0,
        grouped["H"] / grouped["AB"],
        np.nan,
    )

    total_bases = (
        grouped["H"]
        + grouped["2B"]
        + 2 * grouped["3B"]
        + 3 * grouped["HR"]
    )
    grouped["TB"] = total_bases

    grouped["SLG"] = np.where(
        grouped["AB"] > 0,
        grouped["TB"] / grouped["AB"],
        np.nan,
    )

    obp_denominator = (
        grouped["AB"]
        + grouped["BB"]
        + grouped["HBP"]
        + grouped["SF"]
    )
    grouped["OBP"] = np.where(
        obp_denominator > 0,
        (
            grouped["H"]
            + grouped["BB"]
            + grouped["HBP"]
        ) / obp_denominator,
        np.nan,
    )

    grouped["OPS"] = grouped["OBP"] + grouped["SLG"]
    grouped["ISO"] = grouped["SLG"] - grouped["AVG"]

    grouped["BB%"] = np.where(
        grouped["PA"] > 0,
        grouped["BB"] / grouped["PA"] * 100,
        np.nan,
    )
    grouped["K%"] = np.where(
        grouped["PA"] > 0,
        grouped["SO"] / grouped["PA"] * 100,
        np.nan,
    )

    stolen_base_attempts = (
        grouped["SB"] + grouped["CS"]
    )
    grouped["SB%"] = np.where(
        stolen_base_attempts > 0,
        grouped["SB"] / stolen_base_attempts * 100,
        np.nan,
    )

    grouped["_name_key"] = grouped["Player"].apply(
        normalize_player_key
    )

    def winter_player_keys(player_name):
        key = normalize_player_key(player_name)
        keys = {key} if key else set()
        parts = key.split()

        if len(parts) >= 2:
            keys.add(parts[-1])
            keys.add(f"{parts[0][0]} {parts[-1]}")

        return sorted(keys)

    grouped["_all_name_keys"] = grouped["Player"].apply(
        winter_player_keys
    )

    numeric_cols = [
        column
        for column in grouped.columns
        if column not in {
            "PlayerID",
            "Player",
            "_name_key",
            "_all_name_keys",
        }
        and pd.api.types.is_numeric_dtype(
            grouped[column]
        )
        and grouped[column].notna().sum() >= 3
        and grouped[column].nunique(dropna=True) >= 2
    ]

    return grouped, numeric_cols


@st.cache_data(ttl=3600, show_spinner=False)
def load_lidom_from_mlb_winter_leagues(
    selected_team_name,
    selected_season,
):
    team_id, official_team_name = discover_lidom_team_id(
        selected_team_name,
        selected_season,
    )

    (
        start_year,
        start_date,
        end_date,
    ) = winter_season_date_range(selected_season)

    schedule_urls = [
        (
            "https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId={MLB_WINTER_SPORT_ID}"
            f"&teamId={team_id}"
            f"&startDate={start_date}"
            f"&endDate={end_date}"
        ),
        (
            "https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId={MLB_WINTER_SPORT_ID}"
            f"&teamIds={team_id}"
            f"&startDate={start_date}"
            f"&endDate={end_date}"
        ),
    ]

    schedule = None
    schedule_error = None

    for schedule_url in schedule_urls:
        try:
            candidate = fetch_json(schedule_url)
            if candidate.get("dates"):
                schedule = candidate
                break
        except Exception as exc:
            schedule_error = exc

    if not schedule:
        raise ValueError(
            "MLB Winter Leagues returned no LIDOM schedule"
            + (
                f": {schedule_error}"
                if schedule_error
                else "."
            )
        )

    lineup_rows = []
    game_stat_rows = []
    completed_games = 0
    skipped_games = 0

    for date_block in schedule.get("dates", []):
        game_date = date_block.get("date")

        for game in date_block.get("games", []):
            abstract_state = (
                game.get("status", {})
                .get("abstractGameState", "")
            )

            if abstract_state not in {"Final", "Live"}:
                continue

            game_pk = game.get("gamePk")
            if not game_pk:
                continue

            try:
                feed = fetch_json(
                    "https://statsapi.mlb.com/api/v1.1/"
                    f"game/{game_pk}/feed/live"
                )

                game_lineup = extract_mlb_daily_lineup(
                    feed,
                    team_id=team_id,
                    game_date=game_date,
                )

                if len(game_lineup) >= 7:
                    for row in game_lineup:
                        row["Source"] = (
                            "MLB Winter Leagues official game feed"
                        )
                    lineup_rows.extend(game_lineup)

                    game_stat_rows.extend(
                        extract_winter_boxscore_batting_rows(
                            feed,
                            team_id=team_id,
                            game_date=game_date,
                        )
                    )
                    completed_games += 1
                else:
                    skipped_games += 1

            except Exception:
                skipped_games += 1
                continue

    if not lineup_rows:
        raise ValueError(
            "MLB Winter Leagues found the selected team and schedule, "
            "but no completed batting orders were available."
        )

    lineups_df = pd.DataFrame(lineup_rows)
    lineups_df = lineups_df.drop_duplicates(
        subset=["GamePk", "LineupSpot", "PlayerID"],
    ).sort_values(
        ["Date", "GamePk", "LineupSpot"],
        na_position="last",
    ).reset_index(drop=True)

    stats_df, numeric_cols = aggregate_winter_game_stats(
        game_stat_rows
    )

    source_note = (
        "MLB Winter Leagues official game feeds "
        f"({completed_games} completed games imported"
    )
    if skipped_games:
        source_note += (
            f", {skipped_games} games skipped"
        )
    source_note += ")"

    return (
        lineups_df,
        stats_df,
        numeric_cols,
        source_note,
        official_team_name,
    )

def render_historical_analysis():
    st.subheader("Historical Lineup Construction Analysis")

    selected_league = st.segmented_control(
        "Select League",
        options=["MLB", "LIDOM"],
        default="MLB",
        key="historical_league_selector",
    )

    if selected_league == "MLB":
        st.caption(
            "Select an MLB team and season. The app automatically loads daily lineups "
            "and team season batting statistics."
        )

        selector_col1, selector_col2 = st.columns(2)

        with selector_col1:
            selected_team_name = st.selectbox(
                "Select MLB Team",
                options=list(MLB_TEAM_OPTIONS.keys()),
                index=list(MLB_TEAM_OPTIONS.keys()).index("Texas Rangers"),
                key="historical_mlb_team_selector",
            )

        with selector_col2:
            current_year = date.today().year
            available_years = list(range(current_year, 2000, -1))
            selected_season = st.selectbox(
                "Select Season",
                options=available_years,
                index=0,
                key="historical_mlb_season_selector",
            )

        selected_team_abbr = MLB_TEAM_OPTIONS[selected_team_name]
        url_text = build_baseball_reference_url(
            selected_team_abbr,
            selected_season,
        )
        stats_url_text = build_baseball_reference_team_stats_url(
            selected_team_abbr,
            selected_season,
        )

        source_col1, source_col2 = st.columns(2)
        with source_col1:
            st.caption(f"Lineup source: {url_text}")
        with source_col2:
            st.caption(f"Team stats source: {stats_url_text}")

        lineup_file = None
        stats_file = None

    else:
        st.caption(
            "Select a LIDOM team and winter season. The app automatically "
            "loads official MLB Winter Leagues games, daily batting orders, "
            "opposing starters, and player batting statistics."
        )

        selector_col1, selector_col2 = st.columns(2)

        with selector_col1:
            selected_team_name = st.selectbox(
                "Select LIDOM Team",
                options=list(LIDOM_TEAM_OPTIONS.keys()),
                index=list(LIDOM_TEAM_OPTIONS.keys()).index(
                    "Leones del Escogido"
                ),
                key="historical_lidom_team_selector",
            )

        with selector_col2:
            selected_season = st.selectbox(
                "Select Winter Season",
                options=lidom_season_options(),
                index=0,
                key="historical_lidom_season_selector",
            )

        selected_team_abbr = LIDOM_TEAM_OPTIONS[
            selected_team_name
        ]
        lineup_file = None
        stats_file = None

        st.caption(
            "Official source: MLB Winter Leagues / MLB Stats API"
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

    try:
        with st.spinner("Loading and analyzing historical lineup data..."):
            team_abbr = selected_team_abbr
            season = selected_season
            team_slug = team_abbr.lower()

            if selected_league == "MLB":
                lineups_df, lineup_source_note = (
                    load_historical_lineups_with_fallback(
                        url_text,
                        team_abbr,
                        season,
                    )
                )
                (
                    stats_df,
                    numeric_cols,
                    stats_source_note,
                    stats_source_url,
                ) = load_team_stats_with_fallback(
                    team_abbr,
                    season,
                )
            else:
                (
                    lineups_df,
                    stats_df,
                    numeric_cols,
                    winter_source_note,
                    official_team_name,
                ) = load_lidom_from_mlb_winter_leagues(
                    selected_team_name,
                    selected_season,
                )
                lineup_source_note = winter_source_note
                stats_source_note = (
                    "Aggregated from official MLB Winter "
                    "Leagues game box scores"
                )
                stats_source_url = (
                    "https://www.mlb.com/ligas-invernales/"
                )

            merged_df, unmatched, matched_players = merge_lineups_with_stats(
                lineups_df,
                stats_df,
            )

    except (
        ValueError,
        HTTPError,
        URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        st.error(f"Could not complete the historical analysis: {exc}")
        return
    except Exception as exc:
        st.error(f"Unexpected historical-analysis error: {exc}")
        return

    matched_rows = merged_df["_stats_index"].notna().sum()
    total_rows = len(merged_df)
    games = lineups_df["GamePk"].nunique()
    match_pct = matched_rows / max(total_rows, 1) * 100

    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("Games", games)
    metric2.metric("Lineup Entries", total_rows)
    metric3.metric(
        "Players Matched",
        f"{len(matched_players)} / {lineups_df['Player'].nunique()}",
        help=f"{match_pct:.1f}% of lineup entries matched to team stats.",
    )
    metric4.metric(
        "Date Range",
        f"{lineups_df['Date'].min()} to {lineups_df['Date'].max()}",
    )

    st.caption(f"Historical lineup source: {lineup_source_note}")
    st.caption(f"Season-stat source: {stats_source_note}")

    if unmatched:
        preview_unmatched = unmatched[:20]
        unmatched_text = ", ".join(preview_unmatched)
        if len(unmatched) > 20:
            unmatched_text += f", and {len(unmatched) - 20} more"
        st.warning(
            f"{len(unmatched)} unmatched player(s) were excluded: "
            + unmatched_text
        )
    else:
        st.success(
            f"All {len(matched_players)} lineup players were matched "
            "to the team season statistics."
        )

    analysis_df = merged_df[
        merged_df["_stats_index"].notna()
    ].copy()

    if analysis_df.empty:
        st.error(
            "No lineup names could be matched to the team season statistics."
        )
        return

    importance = calculate_trait_importance(
        analysis_df,
        numeric_cols,
    )
    profiles = calculate_spot_profiles(
        analysis_df,
        numeric_cols,
    )
    usage = calculate_usage_table(analysis_df)
    archetypes = build_lineup_archetypes(
        analysis_df,
        numeric_cols,
    )
    expected_spots = calculate_expected_spots(
        analysis_df,
        numeric_cols,
    )
    consistency = calculate_lineup_consistency(analysis_df)
    philosophy = build_philosophy_summary(
        importance,
        analysis_df,
        consistency,
    )

    st.markdown("### Team Philosophy")
    st.write(philosophy)

    st.markdown("### Team Season Stats")
    preferred_stat_columns = [
        col for col in [
            "Player", "Age", "G", "PA", "AVG", "OBP", "SLG",
            "OPS", "OPS+", "ISO", "BB%", "K%", "HR", "SB", "SB%",
        ]
        if col in stats_df.columns
    ]
    st.dataframe(
        stats_df[preferred_stat_columns],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Most Emphasized Traits")
    if importance.empty:
        st.info(
            "The sample is too small or the uploaded metrics do not vary enough."
        )
    else:
        chart_df = importance.head(12).set_index("Trait")[
            ["ImportanceScore"]
        ]
        st.bar_chart(chart_df, horizontal=True)
        st.dataframe(
            importance[
                [
                    "Trait", "ImportanceScore", "Relationship",
                    "Direction", "Observations",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("### Average Profile by Lineup Spot")
    st.dataframe(
        profiles,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Player Usage")
    st.dataframe(
        usage,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Lineup Archetypes")
    if archetypes.empty:
        st.info(
            "Not enough compatible metrics were available "
            "to create lineup archetypes."
        )
    else:
        st.dataframe(
            archetypes,
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("### Actual vs Expected Lineup Spot")
    if expected_spots.empty:
        st.info(
            "Not enough matched player profiles were available "
            "to estimate expected lineup spots."
        )
    else:
        st.dataframe(
            expected_spots,
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("### Imported Historical Lineups")
    display_cols = [
        col for col in [
            "Date", "Opponent", "Result", "HomeAway",
            "OpposingStarter", "OpposingPitcherHand",
            "LineupSpot", "Player", "Bats", "Position",
        ]
        if col in lineups_df.columns
    ]
    st.dataframe(
        lineups_df[display_cols],
        use_container_width=True,
        hide_index=True,
    )

    team_name_display = (
        lineups_df["Team"].dropna().iloc[0]
        if not lineups_df.empty
        else selected_team_name
    )
    date_range = (
        f"{lineups_df['Date'].min()} – "
        f"{lineups_df['Date'].max()}"
    )
    season_filename = str(season).replace("/", "-")

    export1, export2, export3 = st.columns(3)

    with export1:
        st.download_button(
            "Download Imported Lineups CSV",
            data=lineups_df.to_csv(index=False).encode("utf-8"),
            file_name=(
                f"{team_abbr.lower()}_{season_filename}_"
                "historical_lineups.csv"
            ),
            mime="text/csv",
            use_container_width=True,
        )

    with export2:
        st.download_button(
            "Download Analysis CSV",
            data=importance.to_csv(index=False).encode("utf-8"),
            file_name=(
                f"{team_abbr.lower()}_{season_filename}_"
                "lineup_trait_importance.csv"
            ),
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
            file_name=(
                f"{team_abbr.lower()}_{season_filename}_"
                "lineup_construction_analysis.pdf"
            ),
            mime="application/pdf",
            use_container_width=True,
        )

    st.caption(
        "Interpretation note: importance scores measure association with "
        "earlier or later lineup placement. They do not prove causation "
        "or fully explain starter selection because bench availability "
        "is not included."
    )


# =====================================================
# APP UI
# =====================================================

st.title("Lineup Optimization & Construction Intelligence")
st.caption(
    "Optimize future lineups or reverse-engineer lineup construction across MLB and LIDOM."
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
    - Historical analysis only requires MLB team and season selections.
    - Team batting statistics and historical daily lineups are loaded automatically, with official MLB data used as a fallback.
    - The historical mode reports observed relationships; it does not claim causal intent.
    - The PDF uses your uploaded team logo and automatically detects team colors for the optimizer theme.
    - Batting hand colors stay fixed: LHH red, switch hitters blue, RHH black.
    - Position requirements are optional.
    """
)
