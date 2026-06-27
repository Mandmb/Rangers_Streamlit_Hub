
import streamlit as st
import pandas as pd
import numpy as np
import html
from datetime import date
from io import BytesIO
import tempfile
import os

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
# APP UI
# =====================================================

st.title("Lineup Optimization")
st.caption("Upload CSV files and optimize lineups overall, vs right-handed pitchers, and vs left-handed pitchers.")

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
    - Use the sidebar to choose between Overall, Vs RHP, and Vs LHP.
    - Upload all three CSVs to activate the PDF export.
    - The PDF uses your uploaded team logo and automatically detects team colors for the report theme.
    - Batting hand colors stay fixed: LHH red, switch hitters blue, RHH black.
    - Position requirements are optional.
    - The batting order uses both your selected stat weights and spot-specific logic.
    """
)
