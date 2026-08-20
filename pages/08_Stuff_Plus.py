import io
import math
import numpy as np
import pandas as pd
import streamlit as st

# ============================================================
# STUFF PLUS
# Physical pitch-quality baseline for aggregated pitch CSVs
# ============================================================

st.set_page_config(page_title="Stuff Plus", page_icon="⚾", layout="wide")

# -----------------------------
# Styling
# -----------------------------
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1450px;}
    h1, h2, h3 {letter-spacing: -0.02em;}
    .sp-card {
        border: 1px solid rgba(49,51,63,.16);
        border-radius: 14px;
        padding: 16px 18px;
        background: rgba(255,255,255,.02);
        margin-bottom: 12px;
    }
    .sp-small {font-size: .88rem; opacity: .78;}
    div[data-testid="stMetric"] {
        border: 1px solid rgba(49,51,63,.14);
        border-radius: 12px;
        padding: 10px 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Stuff Plus")
st.caption(
    "Physical pitch-quality model. Upload one CSV per pitch type; scores are normalized so 100 = the uploaded peer-group average. Version: 3-Page PDF Leaderboards."
)

# ============================================================
# Configuration
# ============================================================

PITCH_TYPES = [
    "Fastball",
    "Sinker",
    "Cutter",
    "Slider",
    "Sweeper",
    "Curveball",
    "Changeup",
    "Splitter",
]

# Flexible aliases so the app can accept slightly different TrackMan/Hawkeye exports.
ALIASES = {
    "player_id": ["playerId", "PitcherId", "pitcherId", "PlayerId"],
    "name": ["playerFullName", "Pitcher", "pitcherFullName", "player", "Name"],
    "short_name": ["abbrevName", "PitcherAbbrev", "playerAbbrevName"],
    "hand": ["throwsHand", "PitcherThrows", "pitcherHand", "Hand", "Pitcher Handness", "Pitcher Handedness"],
    "pitches": ["P", "Pitches", "PitchCount", "pitchCount"],
    "velo": ["Vel", "Velocity", "Velo", "RelSpeed", "releaseSpeed"],
    "ivb": ["VertBrk", "IVB", "InducedVertBreak", "Vertical Break", "VerticalBreak"],
    "hb": ["HorzBrk", "HB", "Horizontal Break", "HorizontalBreak"],
    "rel_height": ["Rel. Height", "RelHeight", "Release Height", "ReleaseHeight"],
    "rel_side": ["RSd", "RelSide", "Release Side", "ReleaseSide"],
    "extension": ["Extension", "Ext"],
    "spin": ["Spin Rate", "SpinRate", "spinRate", "Spin"],
    "vaa": ["VertApprAngle", "VAA", "Vertical Approach Angle", "VerticalApproachAngle"],
    "haa": ["HorzApprAngle", "HAA", "Horizontal Approach Angle", "HorizontalApproachAngle"],
}

# These are deliberately transparent, editable baseline weights.
# They are NOT represented as MLB-calibrated empirical coefficients.
# The model is intended as a physical baseline until an outcome-trained model is supplied.
WEIGHTS = {
    "Fastball":  {"velo": .34, "shape": .30, "extension": .10, "vaa": .16, "spin": .10},
    "Sinker":    {"velo": .30, "shape": .38, "extension": .10, "vaa": .12, "spin": .10},
    "Cutter":    {"velo": .32, "shape": .35, "extension": .08, "vaa": .15, "spin": .10},
    "Slider":    {"velo": .34, "shape": .38, "extension": .06, "vaa": .12, "spin": .10},
    "Sweeper":   {"velo": .25, "shape": .50, "extension": .05, "vaa": .10, "spin": .10},
    "Curveball": {"velo": .20, "shape": .50, "extension": .05, "vaa": .15, "spin": .10},
    "Changeup":  {"velo": .18, "shape": .40, "extension": .06, "vaa": .10, "spin": .06, "fb_sep": .20},
    "Splitter":  {"velo": .20, "shape": .42, "extension": .06, "vaa": .10, "spin": .02, "fb_sep": .20},
}


# ============================================================
# Helpers
# ============================================================

def first_existing_column(df, aliases):
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        key = alias.strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def numeric(series):
    return pd.to_numeric(series.replace("-", np.nan), errors="coerce")


def safe_z(series):
    s = pd.to_numeric(series, errors="coerce")
    mu = s.mean()
    sd = s.std(ddof=0)
    if pd.isna(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def winsorize(series, lower=.02, upper=.98):
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if len(valid) < 8:
        return s
    lo, hi = valid.quantile([lower, upper])
    return s.clip(lo, hi)


def normalize_hand(series):
    s = series.astype(str).str.upper().str.strip()
    s = s.replace({
        "RIGHT": "R", "RIGHT-HANDED": "R", "RH": "R",
        "LEFT": "L", "LEFT-HANDED": "L", "LH": "L",
    })
    return s


@st.cache_data(show_spinner=False)
def standardize_file(df, pitch_type):
    out = pd.DataFrame(index=df.index)

    for key, aliases in ALIASES.items():
        col = first_existing_column(df, aliases)
        if col is not None:
            out[key] = df[col]

    if "name" not in out.columns:
        if "short_name" in out.columns:
            out["name"] = out["short_name"]
        else:
            raise ValueError("Could not find a pitcher-name column.")

    if "hand" not in out.columns:
        out["hand"] = "R"
    out["hand"] = normalize_hand(out["hand"])

    for key in ["pitches", "velo", "ivb", "hb", "rel_height", "rel_side", "extension", "spin", "vaa", "haa"]:
        if key in out.columns:
            out[key] = numeric(out[key])
        else:
            out[key] = np.nan

    if "player_id" not in out.columns:
        out["player_id"] = out["name"].astype(str)

    out["pitch_type"] = pitch_type
    out = out[out["name"].notna()].copy()
    out = out[out["velo"].notna() | out["ivb"].notna() | out["hb"].notna()].copy()

    return out.reset_index(drop=True)


def residualize(y, X):
    """Return residuals of y ~ intercept + X using only complete rows."""
    y = pd.to_numeric(y, errors="coerce")
    X = X.apply(pd.to_numeric, errors="coerce")
    valid = y.notna() & X.notna().all(axis=1)

    result = pd.Series(np.nan, index=y.index, dtype=float)
    if valid.sum() < max(8, X.shape[1] + 3):
        result.loc[valid] = y.loc[valid] - y.loc[valid].mean()
        return result

    xv = np.column_stack([np.ones(valid.sum()), X.loc[valid].values])
    yv = y.loc[valid].values.astype(float)
    beta, *_ = np.linalg.lstsq(xv, yv, rcond=None)
    pred = xv @ beta
    result.loc[valid] = yv - pred
    return result


def arm_side_break(df):
    # Convert HB so positive = arm-side movement for both RHP/LHP.
    sign = np.where(df["hand"].eq("R"), 1.0, -1.0)
    return df["hb"] * sign


def glove_side_break(df):
    # Positive = glove-side movement magnitude.
    return -arm_side_break(df)


def build_fastball_reference(fastball_df):
    if fastball_df is None or fastball_df.empty:
        return None

    cols = [
        "player_id", "name", "velo", "ivb", "hb",
        "rel_height", "rel_side", "extension", "vaa", "haa"
    ]
    fb = fastball_df[cols].copy()

    # Guarantee ONE fastball reference row per pitcher. This prevents
    # many-to-many merges from exploding in size on Streamlit Cloud.
    fb = (
        fb.sort_values("player_id")
          .drop_duplicates(subset=["player_id"], keep="first")
          .reset_index(drop=True)
    )

    rename = {
        c: f"fb_{c}" for c in cols
        if c not in ["player_id", "name"]
    }
    return fb.rename(columns=rename)


def add_physical_features(df, pitch_type, fb_reference=None):
    x = df.copy()

    # Release-contextualized movement: reward movement that is unusual for the release geometry.
    release_x = x[["rel_height", "rel_side"]].copy()
    x["ivb_release_resid"] = residualize(x["ivb"], release_x)
    x["hb_release_resid"] = residualize(arm_side_break(x), release_x)

    x["arm_hb"] = arm_side_break(x)
    x["glove_hb"] = glove_side_break(x)

    if pitch_type in {"Fastball"}:
        # Ride-oriented four-seam baseline.
        x["shape_raw"] = 0.68 * safe_z(winsorize(x["ivb_release_resid"])) + 0.32 * safe_z(winsorize(-x["arm_hb"].abs()))
    elif pitch_type == "Sinker":
        # Arm-side run + lower IVB.
        x["shape_raw"] = 0.62 * safe_z(winsorize(x["arm_hb"])) + 0.38 * safe_z(winsorize(-x["ivb"]))
    elif pitch_type == "Cutter":
        # Glove-side/cutting action while retaining some vertical shape.
        x["shape_raw"] = 0.65 * safe_z(winsorize(x["glove_hb"])) + 0.35 * safe_z(winsorize(x["ivb"]))
    elif pitch_type == "Slider":
        x["shape_raw"] = 0.62 * safe_z(winsorize(x["glove_hb"])) + 0.38 * safe_z(winsorize(-x["ivb"]))
    elif pitch_type == "Sweeper":
        x["shape_raw"] = 0.82 * safe_z(winsorize(x["glove_hb"])) + 0.18 * safe_z(winsorize(-x["ivb"]))
    elif pitch_type == "Curveball":
        x["shape_raw"] = 0.72 * safe_z(winsorize(-x["ivb"])) + 0.28 * safe_z(winsorize(x["glove_hb"].abs()))
    elif pitch_type in {"Changeup", "Splitter"}:
        x["shape_raw"] = 0.55 * safe_z(winsorize(x["arm_hb"])) + 0.45 * safe_z(winsorize(-x["ivb"]))
    else:
        x["shape_raw"] = 0.5 * safe_z(winsorize(x["ivb"])) + 0.5 * safe_z(winsorize(x["hb"].abs()))

    # VAA preference varies by family. A flatter VAA is useful for riding fastballs;
    # more negative VAA is generally desirable for depth-based secondaries.
    if pitch_type in {"Fastball", "Sinker", "Cutter"}:
        x["vaa_component"] = safe_z(winsorize(x["vaa"]))
    else:
        x["vaa_component"] = safe_z(winsorize(-x["vaa"]))

    x["velo_component"] = safe_z(winsorize(x["velo"]))
    x["extension_component"] = safe_z(winsorize(x["extension"]))
    x["spin_component"] = safe_z(winsorize(x["spin"])).fillna(0.0)
    x["shape_component"] = safe_z(winsorize(x["shape_raw"]))

    # Fastball-relative characteristics for secondaries.
    # Use Series.map instead of dataframe merges. This is much faster and,
    # importantly, cannot create a many-to-many row explosion.
    x["fb_sep_component"] = 0.0
    if fb_reference is not None and pitch_type not in {"Fastball", "Sinker"}:
        ref = fb_reference.drop_duplicates("player_id").set_index("player_id")

        fb_velo = x["player_id"].map(ref["fb_velo"])
        fb_ivb = x["player_id"].map(ref["fb_ivb"])
        fb_hb = x["player_id"].map(ref["fb_hb"])
        fb_rel_height = x["player_id"].map(ref["fb_rel_height"])
        fb_rel_side = x["player_id"].map(ref["fb_rel_side"])

        # Fallback by player name when an ID is unavailable or mismatched.
        if fb_velo.isna().any():
            name_ref = fb_reference.drop_duplicates("name").set_index("name")
            miss = fb_velo.isna()
            fb_velo.loc[miss] = x.loc[miss, "name"].map(name_ref["fb_velo"])
            fb_ivb.loc[miss] = x.loc[miss, "name"].map(name_ref["fb_ivb"])
            fb_hb.loc[miss] = x.loc[miss, "name"].map(name_ref["fb_hb"])
            fb_rel_height.loc[miss] = x.loc[miss, "name"].map(name_ref["fb_rel_height"])
            fb_rel_side.loc[miss] = x.loc[miss, "name"].map(name_ref["fb_rel_side"])

        velo_sep = fb_velo - x["velo"]
        ivb_sep = (fb_ivb - x["ivb"]).abs()
        hb_sep = (fb_hb - x["hb"]).abs()
        release_match = -np.sqrt(
            (fb_rel_height - x["rel_height"]) ** 2 +
            (fb_rel_side - x["rel_side"]) ** 2
        )

        sep = (
            0.40 * safe_z(winsorize(velo_sep)) +
            0.25 * safe_z(winsorize(ivb_sep)) +
            0.25 * safe_z(winsorize(hb_sep)) +
            0.10 * safe_z(winsorize(release_match))
        )
        x["fb_sep_component"] = sep.fillna(0.0)

    return x


def score_pitch_type(df, pitch_type, fb_reference=None):
    x = add_physical_features(df, pitch_type, fb_reference)
    w = WEIGHTS[pitch_type]

    # Reallocate optional-spin weight when spin is unavailable.
    effective = dict(w)
    if x["spin"].notna().sum() < 3 and "spin" in effective:
        spin_w = effective.pop("spin")
        effective["shape"] = effective.get("shape", 0) + spin_w * 0.65
        effective["velo"] = effective.get("velo", 0) + spin_w * 0.35

    components = {
        "velo": x["velo_component"].fillna(0),
        "shape": x["shape_component"].fillna(0),
        "extension": x["extension_component"].fillna(0),
        "vaa": x["vaa_component"].fillna(0),
        "spin": x["spin_component"].fillna(0),
        "fb_sep": x["fb_sep_component"].fillna(0),
    }

    raw = pd.Series(0.0, index=x.index)
    used_weight = 0.0
    for key, weight in effective.items():
        raw += weight * components[key]
        used_weight += weight

    if used_weight:
        raw /= used_weight

    # Re-standardize the composite so 100 is peer average, 10 points = 1 SD.
    x["Stuff+"] = 100 + 10 * safe_z(raw)
    x["Stuff+"] = x["Stuff+"].clip(60, 140).round(1)

    x["Velo+"] = (100 + 10 * safe_z(x["velo"])).round(1)
    x["Shape+"] = (100 + 10 * safe_z(x["shape_raw"])).round(1)
    x["Extension+"] = (100 + 10 * safe_z(x["extension"])).round(1)

    return x


def grade(score):
    if pd.isna(score):
        return ""
    if score >= 130: return "Elite"
    if score >= 120: return "Plus"
    if score >= 110: return "Above Avg"
    if score >= 90: return "Average"
    if score >= 80: return "Below Avg"
    return "Poor"


def format_table(df):
    cols = [
        "name", "hand", "pitches", "Stuff+", "Velo+", "Shape+",
        "velo", "ivb", "hb", "rel_height", "rel_side", "extension", "spin", "vaa", "haa"
    ]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out = out.rename(columns={
        "name": "Pitcher",
        "hand": "Hand",
        "pitches": "P",
        "velo": "Velo",
        "ivb": "IVB",
        "hb": "HB",
        "rel_height": "Rel Ht",
        "rel_side": "Rel Side",
        "extension": "Ext",
        "spin": "Spin",
        "vaa": "VAA",
        "haa": "HAA",
    })
    out.insert(min(4, len(out.columns)), "Grade", df["Stuff+"].apply(grade).values)
    return out


# ============================================================
# PDF export
# ============================================================

def _pdf_text(value):
    if pd.isna(value):
        return "-"
    return str(value)


def build_stuff_plus_pdf(combined_df, pitch_order):
    """Create a three-page landscape PDF containing Stuff+ results."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    page_size = landscape(letter)
    page_w, page_h = page_size
    c = canvas.Canvas(buffer, pagesize=page_size)

    NAVY = colors.HexColor("#003278")
    RED = colors.HexColor("#C0111F")
    LIGHT_BLUE = colors.HexColor("#EAF1F8")
    GRID = colors.HexColor("#B8C2CC")
    TEXT = colors.HexColor("#1F2937")
    MUTED = colors.HexColor("#667085")
    WHITE = colors.white
    HIGHLIGHT_YELLOW = colors.HexColor("#FFF4C2")
    HIGHLIGHT_BLUE = colors.HexColor("#DDEEFF")
    HIGHLIGHT_GREEN = colors.HexColor("#DFF3DF")
    HIGHLIGHT_PURPLE = colors.HexColor("#EADDF7")

    title_style = ParagraphStyle(
        "pdf_title",
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=NAVY,
        leading=20,
    )
    subtitle_style = ParagraphStyle(
        "pdf_subtitle",
        fontName="Helvetica",
        fontSize=8,
        textColor=MUTED,
        leading=10,
    )
    cell_left = ParagraphStyle(
        "cell_left",
        fontName="Helvetica",
        fontSize=7,
        textColor=TEXT,
        alignment=TA_LEFT,
        leading=8,
    )
    cell_center = ParagraphStyle(
        "cell_center",
        fontName="Helvetica",
        fontSize=7,
        textColor=TEXT,
        alignment=TA_CENTER,
        leading=8,
    )

    def draw_header(page_title, subtitle):
        c.setFillColor(NAVY)
        c.rect(0, page_h - 42, page_w, 42, stroke=0, fill=1)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(30, page_h - 27, page_title)
        c.setFillColor(colors.HexColor("#DCE7F5"))
        c.setFont("Helvetica", 7.5)
        c.drawRightString(page_w - 30, page_h - 26, subtitle)

    def draw_footer(page_num):
        c.setStrokeColor(colors.HexColor("#D0D5DD"))
        c.line(30, 22, page_w - 30, 22)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawString(30, 10, "Stuff+ | 100 = uploaded peer-group average")
        c.drawRightString(page_w - 30, 10, f"Page {page_num} of 3")

    # --------------------------------------------------------
    # PAGE 1 — Pitcher-by-pitch Stuff+ matrix
    # --------------------------------------------------------
    draw_header("Stuff Plus Results", "Pitcher-by-pitch Stuff+ overview")

    active_pitches = [p for p in pitch_order if p in combined_df["pitch_type"].unique()]
    pivot = (
        combined_df.pivot_table(
            index="name",
            columns="pitch_type",
            values="Stuff+",
            aggfunc="mean",
        )
        .reindex(columns=active_pitches)
        .reset_index()
    )

    # Sort by the average Stuff+ of each pitcher's available arsenal.
    numeric_cols = [p for p in active_pitches if p in pivot.columns]
    pivot["_avg"] = pivot[numeric_cols].mean(axis=1, skipna=True)
    pivot = pivot.sort_values(["_avg", "name"], ascending=[False, True]).drop(columns="_avg")

    headers = ["Pitcher"] + active_pitches
    data = [headers]
    for _, row in pivot.iterrows():
        vals = [row["name"]]
        for pitch in active_pitches:
            v = row.get(pitch, np.nan)
            vals.append("-" if pd.isna(v) else f"{v:.1f}")
        data.append(vals)

    left = 30
    right = 30
    # Reserve a little extra room under the title for the highlight legend.
    top_y = page_h - 78
    bottom_y = 34
    avail_w = page_w - left - right
    avail_h = top_y - bottom_y

    # Highlight legend: number of pitches with Stuff+ > 100.
    legend_y = page_h - 59
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 6.7)
    c.drawString(left, legend_y, "Above-average pitches:")
    legend_items = [
        ("1", HIGHLIGHT_YELLOW),
        ("2", HIGHLIGHT_BLUE),
        ("3", HIGHLIGHT_GREEN),
        ("4+", HIGHLIGHT_PURPLE),
    ]
    lx = left + 83
    for label, fill in legend_items:
        c.setFillColor(fill)
        c.roundRect(lx, legend_y - 4, 18, 10, 2, stroke=0, fill=1)
        c.setFillColor(TEXT)
        c.setFont("Helvetica-Bold", 6.2)
        c.drawCentredString(lx + 9, legend_y - 1, label)
        lx += 27

    n_rows = max(1, len(data))
    n_pitch_cols = max(1, len(active_pitches))
    pitcher_w = max(120, min(190, avail_w * 0.27))
    stat_w = (avail_w - pitcher_w) / n_pitch_cols
    col_widths = [pitcher_w] + [stat_w] * n_pitch_cols

    row_h = min(20, avail_h / n_rows)
    font_size = max(5.0, min(8.0, row_h * 0.42))

    page1_table = Table(data, colWidths=col_widths, rowHeights=[row_h] * n_rows)
    page1_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#F8FAFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]

    # Apply a full-row highlight based on the number of available pitches
    # that are above the peer average (Stuff+ > 100).
    for table_row, (_, prow) in enumerate(pivot.iterrows(), start=1):
        above_avg = sum(
            1 for pitch in active_pitches
            if pd.notna(prow.get(pitch, np.nan)) and float(prow.get(pitch)) > 100.0
        )
        fill = None
        if above_avg == 1:
            fill = HIGHLIGHT_YELLOW
        elif above_avg == 2:
            fill = HIGHLIGHT_BLUE
        elif above_avg == 3:
            fill = HIGHLIGHT_GREEN
        elif above_avg >= 4:
            fill = HIGHLIGHT_PURPLE
        if fill is not None:
            page1_style.append(("BACKGROUND", (0, table_row), (-1, table_row), fill))

    page1_table.setStyle(TableStyle(page1_style))

    tw, th = page1_table.wrapOn(c, avail_w, avail_h)
    page1_table.drawOn(c, left, top_y - th)
    draw_footer(1)
    c.showPage()

    # --------------------------------------------------------
    # PAGES 2-3 — Ranked leaderboard tables by pitch group
    # --------------------------------------------------------
    def draw_leaderboard_page(page_num, page_title, requested_pitches, grid_cols):
        draw_header(page_title, "Ranked highest to lowest by Stuff+")

        page_pitches = [p for p in requested_pitches if p in active_pitches]
        pitch_tables = []
        for pitch in page_pitches:
            dfp = combined_df[combined_df["pitch_type"] == pitch].copy()
            dfp = dfp.sort_values(
                ["Stuff+", "pitches", "name"],
                ascending=[False, False, True],
                na_position="last",
            )
            pitch_tables.append((pitch, dfp))

        if not pitch_tables:
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 11)
            c.drawCentredString(page_w / 2, page_h / 2, "No uploaded pitch types for this page.")
            draw_footer(page_num)
            c.showPage()
            return

        grid_cols = max(1, min(grid_cols, len(pitch_tables)))
        grid_rows = int(math.ceil(len(pitch_tables) / grid_cols))

        margin_x = 30
        gap_x = 22
        gap_y = 18
        content_top = page_h - 64
        content_bottom = 36
        total_w = page_w - 2 * margin_x
        total_h = content_top - content_bottom
        box_w = (total_w - gap_x * (grid_cols - 1)) / grid_cols
        box_h = (total_h - gap_y * (grid_rows - 1)) / grid_rows

        for i, (pitch, dfp) in enumerate(pitch_tables):
            gr = i // grid_cols
            gc = i % grid_cols
            x = margin_x + gc * (box_w + gap_x)
            y_top = content_top - gr * (box_h + gap_y)

            c.setFillColor(colors.HexColor("#F8FAFC"))
            c.roundRect(x, y_top - box_h, box_w, box_h, 7, stroke=0, fill=1)

            title_h = 27
            c.setFillColor(NAVY)
            c.roundRect(x, y_top - title_h, box_w, title_h, 7, stroke=0, fill=1)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", 11)
            c.drawString(x + 10, y_top - 18, pitch)
            c.setFont("Helvetica", 7.3)
            c.drawRightString(x + box_w - 10, y_top - 18, f"{len(dfp)} pitchers")

            table_data = [["Pitcher", "P", "Stuff+"]]
            for _, row in dfp.iterrows():
                pitches_txt = "-" if pd.isna(row.get("pitches")) else f"{int(round(row['pitches']))}"
                stuff_txt = "-" if pd.isna(row.get("Stuff+")) else f"{row['Stuff+']:.1f}"
                table_data.append([str(row["name"]), pitches_txt, stuff_txt])

            available_table_h = box_h - title_h - 10
            ntr = max(1, len(table_data))
            table_row_h = min(22, available_table_h / ntr)
            table_font = max(5.5, min(9.0, table_row_h * 0.45))

            name_w = box_w * 0.66
            p_w = box_w * 0.14
            stuff_w = box_w - name_w - p_w
            tbl = Table(
                table_data,
                colWidths=[name_w, p_w, stuff_w],
                rowHeights=[table_row_h] * ntr,
            )
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), table_font),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8DEE7")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#FBFCFE")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))

            tw, th = tbl.wrapOn(c, box_w, available_table_h)
            tbl.drawOn(c, x, y_top - title_h - th - 6)

        draw_footer(page_num)
        c.showPage()

    # Page 2: three primary pitch leaderboards, one tall column each.
    draw_leaderboard_page(
        2,
        "Stuff Plus Leaderboards - Fastball / Slider / Changeup",
        ["Fastball", "Slider", "Changeup"],
        grid_cols=3,
    )

    # Page 3: remaining four pitch leaderboards in a spacious 2 x 2 grid.
    draw_leaderboard_page(
        3,
        "Stuff Plus Leaderboards - Other Pitches",
        ["Sinker", "Cutter", "Sweeper", "Curveball"],
        grid_cols=2,
    )

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


# ============================================================
# Upload section
# ============================================================

st.subheader("1. Upload pitch files")
st.write(
    "Upload one CSV for each pitch type you want to evaluate. Files can contain multiple pitchers."
)

uploaded = {}
cols = st.columns(4)
for i, pitch_type in enumerate(PITCH_TYPES):
    with cols[i % 4]:
        uploaded[pitch_type] = st.file_uploader(
            pitch_type,
            type=["csv"],
            key=f"upload_{pitch_type}",
        )

if not any(uploaded.values()):
    st.info("Upload at least one pitch-type CSV to begin.")
    st.stop()

parsed = {}
errors = []

for pitch_type, file in uploaded.items():
    if file is None:
        continue
    try:
        file.seek(0)
        raw = pd.read_csv(io.BytesIO(file.getvalue()))
        parsed[pitch_type] = standardize_file(raw, pitch_type)
    except Exception as exc:
        errors.append(f"{pitch_type}: {exc}")

if errors:
    for err in errors:
        st.error(err)

if not parsed:
    st.stop()

# ============================================================
# Filters / model controls
# ============================================================

st.subheader("2. Model controls")
c1, c2, c3 = st.columns(3)

with c1:
    min_pitches = st.number_input(
        "Minimum pitches (P)",
        min_value=0,
        max_value=5000,
        value=10,
        step=5,
        help="Applied separately within each pitch-type file.",
    )

all_hands = sorted(
    set(
        h
        for df in parsed.values()
        for h in df["hand"].dropna().astype(str).unique().tolist()
        if h not in {"", "NAN"}
    )
)
with c2:
    hand_filter = st.multiselect(
        "Pitcher hand",
        options=all_hands,
        default=all_hands,
    )

with c3:
    selected_pitch_types = st.multiselect(
        "Pitch types to display",
        options=list(parsed.keys()),
        default=list(parsed.keys()),
    )

# Use Fastball as the primary FB reference; fall back to Sinker if needed.
fb_source = parsed.get("Fastball")
if fb_source is None:
    fb_source = parsed.get("Sinker")
fb_reference = build_fastball_reference(fb_source) if fb_source is not None else None

scored = {}
for pitch_type, df in parsed.items():
    work = df.copy()

    if min_pitches > 0 and work["pitches"].notna().any():
        work = work[(work["pitches"].fillna(0) >= min_pitches)].copy()

    if hand_filter:
        work = work[work["hand"].isin(hand_filter)].copy()

    if len(work) >= 3:
        scored[pitch_type] = score_pitch_type(work, pitch_type, fb_reference)

# ============================================================
# Summary
# ============================================================

if not scored:
    st.warning("No pitch type has enough pitchers after the current filters to calculate a peer-normalized Stuff+ score.")
    st.stop()

combined = pd.concat(scored.values(), ignore_index=True)
combined = combined[combined["pitch_type"].isin(selected_pitch_types)].copy()

st.subheader("3. Stuff+ results")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Pitchers", combined["name"].nunique())
m2.metric("Pitch Types", combined["pitch_type"].nunique())
m3.metric("Pitch Rows", len(combined))
if not combined.empty:
    best = combined.loc[combined["Stuff+"].idxmax()]
    m4.metric("Top Pitch", f'{best["Stuff+"]:.1f}', f'{best["name"]} · {best["pitch_type"]}')

st.caption(
    "Current version is a transparent physical baseline, not an MLB outcome-trained Stuff+ model. "
    "100 = average within the uploaded peer group for that pitch type; ~10 points = one standard deviation."
)

# ============================================================
# Leaderboard + pitch tabs
# ============================================================

leaderboard = combined.sort_values(["Stuff+", "pitches"], ascending=[False, False], na_position="last").copy()
leaderboard_display = leaderboard[
    ["name", "pitch_type", "hand", "pitches", "Stuff+", "velo", "ivb", "hb", "extension", "vaa"]
].rename(columns={
    "name": "Pitcher",
    "pitch_type": "Pitch",
    "hand": "Hand",
    "pitches": "P",
    "velo": "Velo",
    "ivb": "IVB",
    "hb": "HB",
    "extension": "Ext",
    "vaa": "VAA",
})

st.markdown("#### Overall pitch leaderboard")
st.dataframe(
    leaderboard_display,
    width="stretch",
    hide_index=True,
    column_config={
        "Stuff+": st.column_config.NumberColumn(format="%.1f"),
        "Velo": st.column_config.NumberColumn(format="%.1f"),
        "IVB": st.column_config.NumberColumn(format="%.1f"),
        "HB": st.column_config.NumberColumn(format="%.1f"),
        "Ext": st.column_config.NumberColumn(format="%.2f"),
        "VAA": st.column_config.NumberColumn(format="%.2f"),
    },
)

tabs = st.tabs([pt for pt in selected_pitch_types if pt in scored])
for tab, pitch_type in zip(tabs, [pt for pt in selected_pitch_types if pt in scored]):
    with tab:
        df = scored[pitch_type].sort_values("Stuff+", ascending=False).copy()

        left, right = st.columns([1.55, 1])

        with left:
            st.markdown(f"##### {pitch_type} leaderboard")
            st.dataframe(
                format_table(df),
                width="stretch",
                hide_index=True,
                column_config={
                    "Stuff+": st.column_config.NumberColumn(format="%.1f"),
                    "Velo+": st.column_config.NumberColumn(format="%.1f"),
                    "Shape+": st.column_config.NumberColumn(format="%.1f"),
                    "Velo": st.column_config.NumberColumn(format="%.1f"),
                    "IVB": st.column_config.NumberColumn(format="%.1f"),
                    "HB": st.column_config.NumberColumn(format="%.1f"),
                    "Rel Ht": st.column_config.NumberColumn(format="%.2f"),
                    "Rel Side": st.column_config.NumberColumn(format="%.2f"),
                    "Ext": st.column_config.NumberColumn(format="%.2f"),
                    "Spin": st.column_config.NumberColumn(format="%.0f"),
                    "VAA": st.column_config.NumberColumn(format="%.2f"),
                    "HAA": st.column_config.NumberColumn(format="%.2f"),
                },
            )

        with right:
            st.markdown("##### Pitcher detail")
            names = df["name"].tolist()
            selected_name = st.selectbox(
                f"Select {pitch_type} pitcher",
                names,
                key=f"detail_{pitch_type}",
                label_visibility="collapsed",
            )
            row = df[df["name"] == selected_name].iloc[0]

            a, b, c = st.columns(3)
            a.metric("Stuff+", f'{row["Stuff+"]:.1f}')
            b.metric("Velo+", f'{row["Velo+"]:.1f}')
            c.metric("Shape+", f'{row["Shape+"]:.1f}')

            detail = {
                "Velocity": row.get("velo"),
                "IVB": row.get("ivb"),
                "HB": row.get("hb"),
                "Release Height": row.get("rel_height"),
                "Release Side": row.get("rel_side"),
                "Extension": row.get("extension"),
                "Spin Rate": row.get("spin"),
                "VAA": row.get("vaa"),
                "HAA": row.get("haa"),
            }
            detail_df = pd.DataFrame(
                [{"Metric": k, "Value": v} for k, v in detail.items() if pd.notna(v)]
            )
            st.dataframe(detail_df, width="stretch", hide_index=True)

            if pitch_type not in {"Fastball", "Sinker"} and fb_reference is not None:
                st.caption(
                    "Secondary-pitch score includes fastball-relative velocity, movement separation, "
                    "and release-point similarity when a matching fastball is available."
                )

# ============================================================
# Player arsenal view
# ============================================================

st.subheader("4. Pitcher arsenal")
pitcher_names = sorted(combined["name"].dropna().unique().tolist())
selected_pitcher = st.selectbox("Select pitcher", pitcher_names, key="arsenal_pitcher")

arsenal = combined[combined["name"] == selected_pitcher].sort_values("Stuff+", ascending=False).copy()

if not arsenal.empty:
    cols = st.columns(min(4, len(arsenal)))
    for i, (_, row) in enumerate(arsenal.iterrows()):
        with cols[i % len(cols)]:
            st.metric(row["pitch_type"], f'{row["Stuff+"]:.1f}', grade(row["Stuff+"]))

    arsenal_table = arsenal[
        ["pitch_type", "pitches", "Stuff+", "Velo+", "Shape+", "velo", "ivb", "hb", "extension", "vaa"]
    ].rename(columns={
        "pitch_type": "Pitch",
        "pitches": "P",
        "velo": "Velo",
        "ivb": "IVB",
        "hb": "HB",
        "extension": "Ext",
        "vaa": "VAA",
    })
    st.dataframe(arsenal_table, width="stretch", hide_index=True)

# ============================================================
# Download
# ============================================================

st.subheader("5. Export")
download_cols = [
    "player_id", "name", "hand", "pitch_type", "pitches",
    "Stuff+", "Velo+", "Shape+",
    "velo", "ivb", "hb", "rel_height", "rel_side", "extension", "spin", "vaa", "haa"
]
download_cols = [c for c in download_cols if c in combined.columns]
csv_bytes = combined[download_cols].sort_values(
    ["name", "Stuff+"], ascending=[True, False]
).to_csv(index=False).encode("utf-8")

export_col1, export_col2 = st.columns(2)

with export_col1:
    st.download_button(
        "Download Stuff+ Results CSV",
        data=csv_bytes,
        file_name="stuff_plus_results.csv",
        mime="text/csv",
        width="stretch",
    )

with export_col2:
    try:
        pdf_bytes = build_stuff_plus_pdf(combined, PITCH_TYPES)
        st.download_button(
            "Download Stuff+ Results PDF",
            data=pdf_bytes,
            file_name="stuff_plus_results.pdf",
            mime="application/pdf",
            width="stretch",
        )
    except ImportError:
        st.error("PDF export requires ReportLab. Add `reportlab` to requirements.txt.")
    except Exception as exc:
        st.error(f"Could not build PDF: {exc}")

# ============================================================
# Methodology
# ============================================================

with st.expander("How this version calculates Stuff+"):
    st.markdown(
        """
        **This is a physical baseline model designed for your aggregated CSV format.**

        - Each pitch type is evaluated separately.
        - 100 is the average of the uploaded peer group for that pitch type.
        - Approximately 10 Stuff+ points equals one standard deviation.
        - Velocity, movement shape, extension, VAA, and Spin Rate (when available) are evaluated.
        - Movement is partially contextualized by release height and release side.
        - Horizontal break is interpreted relative to pitcher handedness.
        - Secondary pitches can receive a fastball-separation component using velocity, IVB, HB,
          and release-point similarity.
        - Missing Spin Rate does not prevent scoring; its weight is redistributed.
        - Location is deliberately excluded.

        **Important:** This is not yet an outcome-trained MLB Stuff+ model. The strongest future
        version would train pitch-level XGBoost/CatBoost models on expected run value or outcome
        probabilities, then use these same physical features as inputs. This page is structured
        so the scoring function can later be replaced by that trained model without changing the
        upload workflow.
        """
    )
