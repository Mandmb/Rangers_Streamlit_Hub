import streamlit as st
import pandas as pd
import numpy as np
import html
from io import BytesIO
from datetime import date

try:
    from PIL import Image
except Exception:
    Image = None

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
except Exception:
    colors = None
    landscape = None
    letter = None
    inch = 72
    ImageReader = None
    canvas = None

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

DEFAULT_PRIMARY = "#002D72"
DEFAULT_SECONDARY = "#BA0C2F"
HAND_RED = "#BA0C2F"
HAND_BLUE = "#002D72"
HAND_BLACK = "#111111"


# =====================================================
# GENERAL HELPERS
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
    side = side.replace("-", " ").replace("_", " ").strip()
    left_values = ["L", "LEFT", "LHH", "LH", "LEFT HANDED", "LEFT HAND", "LEFTY"]
    right_values = ["R", "RIGHT", "RHH", "RH", "RIGHT HANDED", "RIGHT HAND", "RIGHTY"]
    switch_values = ["S", "SW", "SWITCH", "BOTH", "SH", "SWITCH HITTER", "SWITCH HIT"]
    if side in left_values:
        return "L"
    if side in right_values:
        return "R"
    if side in switch_values:
        return "S"
    if side.startswith("L"):
        return "L"
    if side.startswith("S") or "SWITCH" in side:
        return "S"
    return "R"


def hitter_name_color(side):
    side = normalize_bats(side)
    if side == "L":
        return HAND_RED
    if side == "S":
        return HAND_BLUE
    return HAND_BLACK


def player_eligible_for_position(player_pos, required_pos):
    player_pos = normalize_position(player_pos)
    if required_pos == "DH":
        return True
    positions = [p.strip() for p in player_pos.replace(",", "/").split("/")]
    if required_pos == "OF":
        return "OF" in positions
    return required_pos in positions


def fmt_decimal(value, digits=3):
    try:
        x = float(value)
        return f"{x:.{digits}f}".replace("0.", ".")
    except Exception:
        return ""


def fmt_score(value):
    try:
        return f"{float(value):.2f}"
    except Exception:
        return ""


def hex_to_rgb(hex_color):
    hex_color = str(hex_color).strip().lstrip("#")
    if len(hex_color) != 6:
        return (0, 45, 114)
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v))) for v in rgb)


def darken(hex_color, factor=0.75):
    r, g, b = hex_to_rgb(hex_color)
    return rgb_to_hex((r * factor, g * factor, b * factor))


def lighten(hex_color, factor=0.88):
    r, g, b = hex_to_rgb(hex_color)
    return rgb_to_hex((255 - (255 - r) * factor, 255 - (255 - g) * factor, 255 - (255 - b) * factor))


def reportlab_color(hex_color):
    r, g, b = hex_to_rgb(hex_color)
    return colors.Color(r / 255, g / 255, b / 255)


# =====================================================
# LOGO / COLORS
# =====================================================

def extract_logo_colors(logo_bytes):
    if not logo_bytes or Image is None:
        return DEFAULT_PRIMARY, DEFAULT_SECONDARY
    try:
        img = Image.open(BytesIO(logo_bytes)).convert("RGBA")
        img.thumbnail((180, 180))
        arr = np.array(img)
        rgb = arr[:, :, :3]
        alpha = arr[:, :, 3]
        mask = alpha > 40
        if not mask.any():
            return DEFAULT_PRIMARY, DEFAULT_SECONDARY
        pixels = rgb[mask]
        # Remove near-white and near-black so logos do not choose background/outline first.
        brightness = pixels.mean(axis=1)
        saturation = pixels.max(axis=1) - pixels.min(axis=1)
        keep = (brightness < 245) & (brightness > 25) & (saturation > 18)
        pixels = pixels[keep] if keep.any() else pixels
        # Quantize by rounding to reduce noise.
        rounded = (pixels // 24) * 24
        unique, counts = np.unique(rounded, axis=0, return_counts=True)
        order = np.argsort(counts)[::-1]
        chosen = []
        for idx in order:
            c = unique[idx]
            if not chosen:
                chosen.append(c)
                continue
            dist = np.linalg.norm(c.astype(float) - chosen[0].astype(float))
            if dist > 85:
                chosen.append(c)
                break
        if not chosen:
            return DEFAULT_PRIMARY, DEFAULT_SECONDARY
        primary = rgb_to_hex(chosen[0])
        secondary = rgb_to_hex(chosen[1]) if len(chosen) > 1 else DEFAULT_SECONDARY
        return darken(primary, 0.78), darken(secondary, 0.86)
    except Exception:
        return DEFAULT_PRIMARY, DEFAULT_SECONDARY


# =====================================================
# LINEUP OPTIMIZATION
# =====================================================

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
        combined_weights[stat] = (spot_weights[stat] * 0.60) + (user_weights[stat] / user_total * 0.40)
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
            st.warning(f"Not enough eligible players for {required_pos}. Needed {count_needed}, found {len(eligible)}.")
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
    if "Position" in lineup.columns:
        display_cols.append("Position")
    if "Bats" in lineup.columns:
        display_cols.append("Bats")
    if "PA" in lineup.columns:
        display_cols.append("PA")
    display_cols += REQUIRED_STATS + ["Overall Score", "Spot Fit Score"]
    return lineup[display_cols]


def prepare_dataframe(uploaded_file, label):
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Could not read {label} CSV: {e}")
        return None
    df = clean_colnames(df)
    name_col = find_column(df, ["playerFullName", "PlayerFullName", "player_name", "playerName", "Name", "Player", "FullName", "fullName"])
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
    pa_col = find_column(df, ["PA", "pa", "PlateAppearances", "plateAppearances", "Plate Appearances", "plate appearances"])
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
    selected = select_best_9_with_positions(df, "Position") if can_enforce else select_best_9_no_positions(df)
    if len(selected) < 9:
        st.error(f"{label}: Could not select 9 players. Check player pool and positions.")
        return None, df
    lineup = optimize_order(selected, weights)
    return lineup, df


# =====================================================
# METRICS / TABLE DISPLAY
# =====================================================

def weighted_metric(lineup, col):
    if lineup is None or lineup.empty or col not in lineup.columns:
        return 0
    if "PA" in lineup.columns and lineup["PA"].sum() > 0:
        return float(np.average(pd.to_numeric(lineup[col], errors="coerce").fillna(0), weights=pd.to_numeric(lineup["PA"], errors="coerce").fillna(0)))
    return float(pd.to_numeric(lineup[col], errors="coerce").fillna(0).mean())


def lineup_summary(lineup):
    if lineup is None or lineup.empty:
        return {"AVG": 0, "OBP": 0, "SLG": 0, "ISO": 0, "SB": 0, "PA": 0, "Score": 0}
    return {
        "AVG": weighted_metric(lineup, "AVG"),
        "OBP": weighted_metric(lineup, "OBP"),
        "SLG": weighted_metric(lineup, "SLG"),
        "ISO": weighted_metric(lineup, "ISO"),
        "SB": int(pd.to_numeric(lineup["SB"], errors="coerce").fillna(0).sum()) if "SB" in lineup.columns else 0,
        "PA": int(pd.to_numeric(lineup["PA"], errors="coerce").fillna(0).sum()) if "PA" in lineup.columns else 0,
        "Score": float(pd.to_numeric(lineup["Spot Fit Score"], errors="coerce").fillna(0).sum()) if "Spot Fit Score" in lineup.columns else 0,
    }


def format_cell(value, col):
    if pd.isna(value):
        return ""
    if col in ["AVG", "OBP", "SLG", "ISO"]:
        return fmt_decimal(value, 3)
    if col in ["Overall Score", "Spot Fit Score"]:
        return f"{float(value):.4f}"
    if col in ["SB", "PA", "Lineup Spot"]:
        try:
            return f"{int(float(value))}"
        except Exception:
            return str(value)
    return str(value)


def render_lineup_table(lineup):
    cols = lineup.columns.tolist()
    table_html = """
    <style>
    .lineup-table {width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 15px;}
    .lineup-table th {background-color: #002D72; color: white; text-align: center; padding: 10px; border: 1px solid #d9d9d9; font-weight: 700;}
    .lineup-table td {padding: 9px; border: 1px solid #e1e1e1; text-align: center;}
    .lineup-table tr:nth-child(even) {background-color: #f7f7f7;}
    .lineup-table tr:nth-child(odd) {background-color: #ffffff;}
    .player-name-cell {text-align: left !important; font-weight: 800;}
    </style>
    <table class="lineup-table"><thead><tr>
    """
    for col in cols:
        table_html += f"<th>{html.escape(str(col))}</th>"
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
    table_html += "</tbody></table>"
    st.markdown(table_html, unsafe_allow_html=True)


def show_player_pool(df):
    preview_cols = ["playerFullName"]
    if "Position" in df.columns:
        preview_cols.append("Position")
    preview_cols += ["Bats", "PA"]
    preview_cols += REQUIRED_STATS + ["Overall Score"]
    st.dataframe(df[preview_cols].sort_values("Overall Score", ascending=False), use_container_width=True, hide_index=True)


# =====================================================
# PROFESSIONAL PDF EXPORT
# =====================================================

def draw_centered_text(c, text, x, y, font="Helvetica-Bold", size=12, color_hex="#000000"):
    c.setFillColor(reportlab_color(color_hex))
    c.setFont(font, size)
    c.drawCentredString(x, y, text)


def draw_right_text(c, text, x, y, font="Helvetica", size=10, color_hex="#000000"):
    c.setFillColor(reportlab_color(color_hex))
    c.setFont(font, size)
    c.drawRightString(x, y, text)


def draw_logo(c, logo_bytes, x, y, w, h):
    if not logo_bytes or ImageReader is None:
        return
    try:
        c.drawImage(ImageReader(BytesIO(logo_bytes)), x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
    except Exception:
        pass


def draw_metric_box(c, x, y, w, h, label, value, value_color):
    c.setStrokeColor(reportlab_color("#D6DAE2"))
    c.setLineWidth(0.6)
    c.rect(x, y, w, h, stroke=1, fill=0)
    draw_centered_text(c, label, x + w / 2, y + h - 13, "Helvetica-Bold", 6.2, "#111111")
    draw_centered_text(c, value, x + w / 2, y + 9, "Helvetica-Bold", 12, value_color)


def draw_summary_strip(c, x, y, w, h, primary, secondary, overall_summary):
    label_w = 1.48 * inch
    c.setFillColor(reportlab_color(primary))
    c.roundRect(x, y, label_w, h, 4, fill=1, stroke=0)
    draw_centered_text(c, "TEAM", x + label_w / 2, y + h / 2 + 8, "Helvetica-Bold", 11, "#FFFFFF")
    draw_centered_text(c, "SUMMARY", x + label_w / 2, y + h / 2 - 7, "Helvetica-Bold", 11, "#FFFFFF")

    metric_w = (w - label_w) / 4
    labels = ["Team AVG", "Team OBP", "Team SLG", "Projected Lineup Score"]
    values = [fmt_decimal(overall_summary["AVG"]), fmt_decimal(overall_summary["OBP"]), fmt_decimal(overall_summary["SLG"]), fmt_score(overall_summary["Score"])]
    value_colors = [primary, primary, primary, secondary]
    for i, (lab, val, col) in enumerate(zip(labels, values, value_colors)):
        draw_metric_box(c, x + label_w + i * metric_w, y, metric_w, h, lab, val, col)


def draw_hand_legend(c, x, y, w, h):
    c.setStrokeColor(reportlab_color("#C7CAD1"))
    c.setLineWidth(0.8)
    c.rect(x, y, w, h, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(reportlab_color(DEFAULT_PRIMARY))
    c.drawString(x + 10, y + h - 14, "BATTING HAND LEGEND")
    c.setFont("Helvetica-Bold", 6.4)
    c.setFillColor(reportlab_color(HAND_BLACK))
    c.drawString(x + 10, y + h - 29, "R = Right-Handed")
    c.setFillColor(reportlab_color(HAND_RED))
    c.drawString(x + 10, y + h - 42, "L = Left-Handed")
    c.setFillColor(reportlab_color(HAND_BLUE))
    c.drawString(x + 10, y + h - 55, "S = Switch-Hitter")


def draw_lineup_panel(c, lineup, title, x, y, w, h, panel_color, accent_color):
    summary = lineup_summary(lineup)
    c.setFillColor(reportlab_color(panel_color))
    c.roundRect(x, y + h - 28, w, 28, 5, fill=1, stroke=0)
    draw_centered_text(c, title, x + w / 2, y + h - 18, "Helvetica-Bold", 9.2, "#FFFFFF")

    metric_h = 34
    metric_y = y + h - 28 - metric_h
    metric_w = w / 4
    metrics = [
        ("Team AVG", fmt_decimal(summary["AVG"]), panel_color),
        ("Team OBP", fmt_decimal(summary["OBP"]), panel_color),
        ("Team SLG", fmt_decimal(summary["SLG"]), panel_color),
        ("Projected Score", fmt_score(summary["Score"]), accent_color),
    ]
    for i, (lab, val, val_color) in enumerate(metrics):
        draw_metric_box(c, x + i * metric_w, metric_y, metric_w, metric_h, lab, val, val_color)

    header_y = metric_y - 18
    row_h = 18
    columns = [
        ("#", 0.06), ("PLAYER", 0.29), ("POS", 0.08), ("BATS", 0.08), ("PA", 0.08),
        ("AVG", 0.085), ("OBP", 0.085), ("SLG", 0.085), ("ISO", 0.075), ("SB", 0.075),
    ]
    total_ratio = sum(r for _, r in columns)
    widths = [w * r / total_ratio for _, r in columns]

    c.setFillColor(reportlab_color(panel_color))
    c.rect(x, header_y, w, row_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 5.8)
    cx = x
    for (lab, _), cw in zip(columns, widths):
        c.drawCentredString(cx + cw / 2, header_y + 6, lab)
        cx += cw

    data_y = header_y - row_h
    c.setFont("Helvetica", 5.9)
    for i, (_, row) in enumerate(lineup.iterrows(), start=1):
        fill = "#FFFFFF" if i % 2 else "#F4F6FA"
        c.setFillColor(reportlab_color(fill))
        c.rect(x, data_y, w, row_h, fill=1, stroke=0)
        vals = [
            str(i),
            str(row.get("playerFullName", "")),
            str(row.get("Position", "")),
            str(row.get("Bats", "")),
            str(int(float(row.get("PA", 0)))) if str(row.get("PA", "")).strip() != "" else "",
            fmt_decimal(row.get("AVG", 0)),
            fmt_decimal(row.get("OBP", 0)),
            fmt_decimal(row.get("SLG", 0)),
            fmt_decimal(row.get("ISO", 0)),
            str(int(float(row.get("SB", 0)))) if str(row.get("SB", "")).strip() != "" else "",
        ]
        cx = x
        for j, (val, cw) in enumerate(zip(vals, widths)):
            if j == 1:
                c.setFillColor(reportlab_color(hitter_name_color(row.get("Bats", "R"))))
                c.setFont("Helvetica-Bold", 5.8)
                c.drawString(cx + 3, data_y + 6, val[:24])
                c.setFont("Helvetica", 5.9)
            elif j == 3:
                c.setFillColor(reportlab_color(hitter_name_color(row.get("Bats", "R"))))
                c.setFont("Helvetica-Bold", 5.8)
                c.drawCentredString(cx + cw / 2, data_y + 6, val)
                c.setFont("Helvetica", 5.9)
            else:
                c.setFillColor(reportlab_color("#111111"))
                c.drawCentredString(cx + cw / 2, data_y + 6, val)
            cx += cw
        data_y -= row_h

    # Total / average row
    total_y = data_y
    c.setFillColor(reportlab_color(lighten(panel_color, 0.92)))
    c.rect(x, total_y, w, row_h + 2, fill=1, stroke=0)
    total_vals = ["", "TOTAL/AVG", "—", "—", str(summary["PA"]), fmt_decimal(summary["AVG"]), fmt_decimal(summary["OBP"]), fmt_decimal(summary["SLG"]), fmt_decimal(summary["ISO"]), str(summary["SB"])]
    c.setFont("Helvetica-Bold", 5.7)
    c.setFillColor(reportlab_color(panel_color))
    cx = x
    for val, cw in zip(total_vals, widths):
        if val == "TOTAL/AVG":
            c.drawString(cx + 3, total_y + 7, val)
        else:
            c.drawCentredString(cx + cw / 2, total_y + 7, val)
        cx += cw

    # Panel border
    c.setStrokeColor(reportlab_color("#D7DCE5"))
    c.setLineWidth(0.7)
    c.roundRect(x, total_y, w, h - (total_y - y), 5, fill=0, stroke=1)


def create_professional_pdf(lineups, logo_bytes, report_title, report_date, team_name, primary, secondary):
    if canvas is None:
        raise RuntimeError("ReportLab is not installed. Add `reportlab` to requirements.txt.")

    buffer = BytesIO()
    page_w, page_h = landscape(letter)
    c = canvas.Canvas(buffer, pagesize=landscape(letter))

    margin = 0.25 * inch
    top = page_h - margin
    logo_w = 0.72 * inch
    logo_h = 0.72 * inch

    # Header
    draw_logo(c, logo_bytes, margin, top - logo_h + 0.02 * inch, logo_w, logo_h)
    draw_centered_text(c, report_title.upper(), page_w / 2, top - 0.15 * inch, "Helvetica-Bold", 21, primary)
    draw_right_text(c, report_date.strftime("%b %d, %Y"), page_w - margin, top - 0.14 * inch, "Helvetica-Bold", 8.5, primary)

    line_y = top - 0.48 * inch
    c.setStrokeColor(reportlab_color(secondary))
    c.setLineWidth(2.2)
    c.line(margin + 0.9 * inch, line_y, page_w / 2 - 1.05 * inch, line_y)
    c.line(page_w / 2 + 1.05 * inch, line_y, page_w - margin, line_y)
    draw_centered_text(c, "OPTIMIZED LINEUPS FOR EVERY SITUATION", page_w / 2, line_y - 3, "Helvetica-Bold", 8.5, "#808895")

    overall_summary = lineup_summary(lineups["Overall"])
    summary_y = top - 1.20 * inch
    summary_h = 0.56 * inch
    summary_w = page_w - (2 * margin) - 1.95 * inch
    draw_summary_strip(c, margin, summary_y, summary_w, summary_h, primary, secondary, overall_summary)
    draw_hand_legend(c, margin + summary_w + 0.18 * inch, summary_y, 1.77 * inch, summary_h)

    # Three side-by-side panels
    panel_top = summary_y - 0.16 * inch
    panel_h = 4.50 * inch
    gap = 0.16 * inch
    panel_w = (page_w - 2 * margin - 2 * gap) / 3
    panel_y = panel_top - panel_h

    overall_color = primary
    vs_rhp_color = secondary
    vs_lhp_color = darken(primary, 0.90)
    draw_lineup_panel(c, lineups["Overall"], "OVERALL OPTIMAL LINEUP", margin, panel_y, panel_w, panel_h, overall_color, secondary)
    draw_lineup_panel(c, lineups["Vs RHP"], "VS RIGHT-HANDED PITCHER", margin + panel_w + gap, panel_y, panel_w, panel_h, vs_rhp_color, secondary)
    draw_lineup_panel(c, lineups["Vs LHP"], "VS LEFT-HANDED PITCHER", margin + 2 * (panel_w + gap), panel_y, panel_w, panel_h, vs_lhp_color, secondary)

    # Footer
    footer_h = 0.50 * inch
    footer_y = margin - 0.05 * inch
    c.setFillColor(reportlab_color(primary))
    c.rect(margin, footer_y, page_w - 2 * margin, footer_h, fill=1, stroke=0)
    draw_logo(c, logo_bytes, margin + 0.10 * inch, footer_y + 0.08 * inch, 0.34 * inch, 0.34 * inch)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin + 0.55 * inch, footer_y + 0.28 * inch, team_name.upper() if team_name else "BASEBALL OPERATIONS")
    c.setFont("Helvetica", 6.8)
    c.drawString(margin + 0.55 * inch, footer_y + 0.15 * inch, "BASEBALL OPERATIONS")
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(page_w - margin - 0.35 * inch, footer_y + 0.22 * inch, "Data-Driven Decisions. Better Results.")
    c.setStrokeColor(reportlab_color(secondary))
    c.setLineWidth(3)
    c.line(page_w - margin - 0.20 * inch, footer_y, page_w - margin - 0.02 * inch, footer_y + footer_h)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


# =====================================================
# APP UI
# =====================================================

st.title("Lineup Optimization")
st.caption("Upload CSV files and optimize lineups overall, vs right-handed pitchers, and vs left-handed pitchers.")

st.sidebar.header("Report Branding")
team_logo_file = st.sidebar.file_uploader("Team Logo", type=["png", "jpg", "jpeg"], help="Optional. The PDF will use this logo and pull team colors from it.")
team_name = st.sidebar.text_input("Team Name", value="Texas Rangers")
report_title = st.sidebar.text_input("Report Title", value="Lineup Optimization Report")
report_date = st.sidebar.date_input("Report Date", value=date.today())
logo_bytes = team_logo_file.getvalue() if team_logo_file else None
primary_color, secondary_color = extract_logo_colors(logo_bytes)
st.sidebar.caption(f"Detected colors: {primary_color} / {secondary_color}")

st.markdown(
    """
    **Bats color key:**  
    <span style="color:#BA0C2F;font-weight:800;">Left-handed hitters</span> = red &nbsp; | &nbsp;
    <span style="color:#002D72;font-weight:800;">Switch hitters</span> = blue &nbsp; | &nbsp;
    <span style="color:#111111;font-weight:800;">Right-handed hitters</span> = black
    """,
    unsafe_allow_html=True,
)

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
    help="Choose which uploaded CSV to show on screen.",
)

col1, col2, col3 = st.columns(3)
with col1:
    overall_file = st.file_uploader("Overall CSV", type=["csv"], key="overall_csv")
with col2:
    vs_rhp_file = st.file_uploader("Vs RHP CSV", type=["csv"], key="vs_rhp_csv")
with col3:
    vs_lhp_file = st.file_uploader("Vs LHP CSV", type=["csv"], key="vs_lhp_csv")

files = {"Overall": overall_file, "Vs RHP": vs_rhp_file, "Vs LHP": vs_lhp_file}

prepared = {}
scored = {}
lineups = {}
for label, file in files.items():
    if file is not None:
        df = prepare_dataframe(file, label)
        if df is not None:
            lineup, scored_df = build_lineup(df, weights, enforce_positions, label)
            if lineup is not None:
                prepared[label] = df
                scored[label] = scored_df
                lineups[label] = lineup

selected_file = files[lineup_mode]
if selected_file is None:
    st.info(f"Upload the {lineup_mode} CSV to generate that lineup.")
else:
    if lineup_mode in lineups:
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
st.subheader("PDF Export")
missing_for_pdf = [label for label in ["Overall", "Vs RHP", "Vs LHP"] if label not in lineups]
if missing_for_pdf:
    st.info("Upload all three CSVs to export the full one-page PDF: " + ", ".join(missing_for_pdf))
else:
    try:
        pdf_bytes = create_professional_pdf(lineups, logo_bytes, report_title, report_date, team_name, primary_color, secondary_color)
        st.download_button(
            label="Export All 3 Lineups as PDF",
            data=pdf_bytes,
            file_name="lineup_optimization_report.pdf",
            mime="application/pdf",
            type="primary",
        )
    except Exception as e:
        st.error(f"Could not generate PDF: {e}")
        st.caption("If this says ReportLab is missing, add `reportlab` to requirements.txt and push again.")

st.markdown("### Lineup Notes")
st.write(
    """
    - Use the sidebar to choose which lineup appears on screen.
    - Upload all three CSVs to export the full PDF with Overall, Vs RHP, and Vs LHP on one page.
    - The PDF uses your uploaded logo and automatically pulls team colors from it.
    - Batting hand colors stay fixed: LHH red, switch hitters blue, RHH black.
    - Position requirements are optional.
    """
)
