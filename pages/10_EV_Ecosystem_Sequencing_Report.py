
import io
import re
import math
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.platypus import Table, TableStyle


# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="EV Ecosystem & Sequencing Report",
    page_icon="⚾",
    layout="wide",
)

# Rangers-style palette
BLUE = "#002D72"
RED = "#BA0C2F"
DARK = "#1F2937"
MID = "#6B7280"
LIGHT = "#F3F4F6"
GREEN = "#DFF2E1"
YELLOW = "#FFF2CC"
PINK = "#FCE8E6"
PURPLE = "#7C3AED"
TEAL = "#059669"

PITCH_COLORS = {
    "4-Seam": RED,
    "Fastball": RED,
    "Sinker": "#F59E0B",
    "Cutter": "#EC4899",
    "Slider": BLUE,
    "Sweeper": "#0EA5E9",
    "Curveball": TEAL,
    "Changeup": PURPLE,
    "Splitter": "#8B5CF6",
    "Other": MID,
}

st.markdown(
    f"""
    <style>
    .block-container {{padding-top: 1.25rem; padding-bottom: 3rem;}}
    h1, h2, h3 {{color: {BLUE};}}
    div[data-testid="stMetric"] {{
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        padding: 10px 12px;
        background: white;
    }}
    .ev-note {{
        background: #F8FAFC;
        border-left: 4px solid {BLUE};
        padding: 12px 14px;
        border-radius: 6px;
        margin: 8px 0 14px 0;
    }}
    .small-muted {{color:#6B7280; font-size:0.88rem;}}
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# COLUMN DETECTION
# =========================================================
COLUMN_ALIASES = {
    "pitcher": [
        "Pitcher", "PitcherName", "pitcher_name", "PlayerName",
        "player_name", "PitcherFullName", "Pitcher Full Name",
        "fullName", "pitcherAbbrevName"
    ],
    "pitch_type": [
        "PitchType", "TaggedPitchType", "AutoPitchType", "pitch_type",
        "Pitch Type", "Pitch_Type", "pitchType", "pitchTypeFull"
    ],
    "velo": [
        "RelSpeed", "Velocity", "release_speed", "PitchSpeed",
        "Pitch Velocity", "Velo", "ReleaseSpeed",
        "releaseVelocity", "Vel"
    ],
    "plate_x": [
        "PlateLocSide", "plate_x", "PlateX", "px", "Plate Loc Side",
        "PlateLocationSide"
    ],
    "plate_z": [
        "PlateLocHeight", "plate_z", "PlateZ", "pz", "Plate Loc Height",
        "PlateLocationHeight"
    ],
    "batter_side": [
        "BatterSide", "BatterSideCode", "Stand", "stand",
        "Batter Side", "BatterHand", "BatterHandedness",
        "batterHand"
    ],
    "pitcher_hand": [
        "PitcherThrows", "PitcherHand", "PitcherSide", "Throws",
        "Pitcher Hand", "pitcherHand"
    ],
    "game_date": [
        "Date", "GameDate", "game_date", "Game Date", "gameDate", "date"
    ],
    "game_id": [
        "GameID", "GameId", "game_pk", "Game", "Game ID", "gameId"
    ],
    "pa_id": [
        "PAofInning", "PA_ID", "PlateAppearance", "PlateAppearanceID",
        "AtBatNo", "AtBatNumber", "AB", "pa_id", "abNumInGame"
    ],
    "pitch_no": [
        "PitchofPA", "PitchNo", "PitchNumber", "Pitch #", "pitch_number",
        "PitchOfPA", "PitchNoInPA", "pitchNumInAB", "pitchNumInGame"
    ],
    "inning": [
        "Inning", "inning", "inn"
    ],
    "top_bottom": [
        "TopBottom", "InningHalf", "Top/Bottom", "inning_topbot"
    ],
    "release_x": [
        "RelSide", "release_pos_x", "ReleaseSide", "Release X", "ReleaseX", "RelSd"
    ],
    "release_z": [
        "RelHeight", "release_pos_z", "ReleaseHeight", "Release Z", "ReleaseZ"
    ],
    "horz_break": [
        "HorzBreak", "pfx_x", "HorizontalBreak", "Horizontal Break",
        "InducedHorzBreak", "Horizontal Movement"
    ],
    "vert_break": [
        "InducedVertBreak", "pfx_z", "VerticalBreak", "IVB",
        "Induced Vertical Break", "Vertical Movement"
    ],
}


def normalized_name(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def person_match_key(value):
    """
    Conservative pitcher-name matching across PDF and CSV sources.
    Examples:
      "Gabriel Ynoa" -> "gabrielynoa"
      "#19 Kelly Austin" -> "kellyaustin"
    """
    s = str(value).strip().lower()
    s = re.sub(r"^#?\d+\s+", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def detect_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    normalized = {normalized_name(c): c for c in df.columns}
    found = {}
    for key, aliases in COLUMN_ALIASES.items():
        match = None
        for alias in aliases:
            n = normalized_name(alias)
            if n in normalized:
                match = normalized[n]
                break
        found[key] = match
    return found


# =========================================================
# NORMALIZATION
# =========================================================
def normalize_pitch_type(v):
    s = str(v).strip().lower()
    if not s or s == "nan":
        return "Other"
    if any(k in s for k in ["4-seam", "4 seam", "four seam", "4s", "fastball (4"]):
        return "4-Seam"
    if "sinker" in s or "2-seam" in s or "2 seam" in s or "two seam" in s:
        return "Sinker"
    if "cutter" in s or s in {"ct"}:
        return "Cutter"
    if "sweeper" in s:
        return "Sweeper"
    if "slider" in s or s in {"sl"}:
        return "Slider"
    if "curve" in s or s in {"cb", "cu"}:
        return "Curveball"
    if "change" in s or s in {"ch"}:
        return "Changeup"
    if "split" in s or s in {"fs"}:
        return "Splitter"
    if "fastball" in s or s in {"fb"}:
        return "Fastball"
    return str(v).strip().title()


def normalize_side(v):
    s = str(v).strip().upper()
    if s.startswith("R"):
        return "R"
    if s.startswith("L"):
        return "L"
    return None


def safe_numeric(s):
    return pd.to_numeric(s, errors="coerce")


# =========================================================
# PITCH CHART PDF PARSER
# =========================================================
PITCHER_RE = re.compile(r"#\d+\s+(.+?)\s+\(([RL])\)(?:\s+.*)?$")


@dataclass
class PitchChartPitcher:
    name: str
    hand: str
    page_num: int
    pitch_counts_rhh: Dict[str, int]
    pitch_counts_lhh: Dict[str, int]


def _count_pitch_types_from_page_text(text: str) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    The standardized report prints the six RHH panels first, then the six LHH panels.
    PyMuPDF text extraction follows that layout closely enough to split the page around
    the second 'Fastball' block. This is intended as an inventory helper, not the source
    for EV/tunnel calculations.
    """
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    occurrences = [i for i, x in enumerate(lines) if x == "Fastball"]
    if len(occurrences) >= 2:
        left_lines = lines[occurrences[0]:occurrences[1]]
        right_lines = lines[occurrences[1]:]
    else:
        left_lines, right_lines = lines, []

    def parse_block(block):
        out = {}
        joined = "\n".join(block)
        patterns = [
            ("4-Seam", r"Fastball\s*\(4S\)\s*:\s*(\d+)"),
            ("Sinker", r"(?:Sinker|Fastball\s*\(2S\))\s*:\s*(\d+)"),
            ("Cutter", r"Cutter\s*:\s*(\d+)"),
            ("Slider", r"Slider\s*:\s*(\d+)"),
            ("Sweeper", r"Sweeper\s*:\s*(\d+)"),
            ("Curveball", r"Curveball\s*:\s*(\d+)"),
            ("Changeup", r"Change\s*:\s*(\d+)"),
            ("Splitter", r"Splitter\s*:\s*(\d+)"),
        ]
        for pt, pat in patterns:
            vals = [int(v) for v in re.findall(pat, joined, flags=re.I)]
            if vals:
                out[pt] = int(sum(vals))
        return out

    return parse_block(left_lines), parse_block(right_lines)


def parse_pitch_chart_pdf(pdf_bytes: bytes) -> List[PitchChartPitcher]:
    if fitz is None:
        return []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pitchers = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        name = None
        hand = None
        for line in lines[:8]:
            m = PITCHER_RE.search(line)
            if m:
                name = m.group(1).strip()
                hand = m.group(2)
                break
        if not name and lines:
            m = re.search(r"#\d+\s+(.+?)\s+\(([RL])\)", lines[0])
            if m:
                name = m.group(1).strip()
                hand = m.group(2)
        if name:
            rhh, lhh = _count_pitch_types_from_page_text(text)
            pitchers.append(
                PitchChartPitcher(
                    name=name,
                    hand=hand or "",
                    page_num=i + 1,
                    pitch_counts_rhh=rhh,
                    pitch_counts_lhh=lhh,
                )
            )
    return pitchers


# =========================================================
# ECOSYSTEM + PUBLIC EV ESTIMATE
# =========================================================
def kde_mode_xy(x: np.ndarray, z: np.ndarray) -> Tuple[float, float]:
    """
    Lightweight 2D Gaussian density mode. Avoids scipy so the page deploys easily.
    """
    x = np.asarray(x, dtype=float)
    z = np.asarray(z, dtype=float)
    mask = np.isfinite(x) & np.isfinite(z)
    x, z = x[mask], z[mask]
    if len(x) == 0:
        return np.nan, np.nan
    if len(x) < 4:
        return float(np.nanmedian(x)), float(np.nanmedian(z))

    gx = np.linspace(max(-2.5, np.nanmin(x)-0.2), min(2.5, np.nanmax(x)+0.2), 45)
    gz = np.linspace(max(0.0, np.nanmin(z)-0.2), min(5.5, np.nanmax(z)+0.2), 55)
    bw_x = max(0.18, min(0.40, np.nanstd(x) * 0.45))
    bw_z = max(0.20, min(0.45, np.nanstd(z) * 0.45))
    if not np.isfinite(bw_x): bw_x = 0.28
    if not np.isfinite(bw_z): bw_z = 0.30

    best = (float(np.nanmedian(x)), float(np.nanmedian(z)))
    best_score = -1.0
    for xx in gx:
        dx = ((x - xx) / bw_x) ** 2
        for zz in gz:
            score = float(np.exp(-0.5 * (dx + ((z - zz) / bw_z) ** 2)).sum())
            if score > best_score:
                best_score = score
                best = (float(xx), float(zz))
    return best


def public_ev_estimate(velo, plate_x, plate_z, batter_side):
    """
    Public approximation based on descriptions of Perry Husband's EV work:
    up/in plays faster, down/away plays slower, at roughly 2.75 mph per 6 inches
    along the EV diagonal.

    This is deliberately labeled an ESTIMATE because Husband's full proprietary
    model is more sophisticated than the public approximation.

    Statcast-style plate_x convention:
      +x = catcher's right; -x = catcher's left.
      For RHH, inside is negative x.
      For LHH, inside is positive x.
    """
    if any(pd.isna(v) for v in [velo, plate_x, plate_z]) or batter_side not in {"R", "L"}:
        return np.nan

    # Neutral reference: plate center, approximate vertical middle of zone.
    z0 = 2.50

    # Inside direction: RHH -> negative x, LHH -> positive x.
    inside = -float(plate_x) if batter_side == "R" else float(plate_x)
    up = float(plate_z) - z0

    # Project onto a 45-degree up/in <-> down/away axis.
    # Divide by sqrt(2) so a 6-inch diagonal move is treated as 6 inches of EV-axis travel.
    axis_feet = (inside + up) / math.sqrt(2.0)

    # 2.75 mph per 0.5 ft = 5.5 mph per foot.
    adjustment = 5.5 * axis_feet
    return float(velo) + adjustment


def ecosystem_radius(x, z, cx, cz):
    d = np.sqrt((x-cx)**2 + (z-cz)**2)
    d = d[np.isfinite(d)]
    if len(d) == 0:
        return 0.30
    # Circle containing roughly the inner half of the pitch cluster.
    return float(np.clip(np.nanquantile(d, 0.50), 0.20, 0.55))


def prepare_pitch_data(df: pd.DataFrame, cols: Dict[str, Optional[str]]) -> pd.DataFrame:
    d = df.copy()
    required = ["pitcher", "pitch_type", "velo", "plate_x", "plate_z", "batter_side"]
    missing = [k for k in required if not cols.get(k)]
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))

    d["_pitcher"] = d[cols["pitcher"]].astype(str).str.strip()
    d["_pitch_type"] = d[cols["pitch_type"]].map(normalize_pitch_type)
    d["_velo"] = safe_numeric(d[cols["velo"]])
    d["_x"] = safe_numeric(d[cols["plate_x"]])
    d["_z"] = safe_numeric(d[cols["plate_z"]])
    d["_bside"] = d[cols["batter_side"]].map(normalize_side)

    if cols.get("pitcher_hand"):
        d["_phand"] = d[cols["pitcher_hand"]].map(normalize_side)
    else:
        d["_phand"] = None

    d = d[
        d["_pitcher"].notna() &
        d["_velo"].notna() &
        d["_x"].notna() &
        d["_z"].notna() &
        d["_bside"].isin(["R", "L"])
    ].copy()

    d["_ev"] = [
        public_ev_estimate(v, x, z, side)
        for v, x, z, side in zip(d["_velo"], d["_x"], d["_z"], d["_bside"])
    ]
    return d


def build_ecosystem_summary(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (pitcher, side, pitch_type), g in d.groupby(["_pitcher", "_bside", "_pitch_type"]):
        if len(g) < 2:
            continue
        cx, cz = kde_mode_xy(g["_x"].to_numpy(), g["_z"].to_numpy())
        r = ecosystem_radius(g["_x"].to_numpy(), g["_z"].to_numpy(), cx, cz)
        dist = np.sqrt((g["_x"] - cx)**2 + (g["_z"] - cz)**2)
        in_eco = dist <= r
        # Estimate the EV at ecosystem using median velocity + ecosystem center location.
        avg_v = float(g["_velo"].median())
        eco_ev = public_ev_estimate(avg_v, cx, cz, side)
        rows.append({
            "Pitcher": pitcher,
            "BatterSide": side,
            "PitchType": pitch_type,
            "Pitches": int(len(g)),
            "UsagePct": np.nan,
            "AvgVelo": float(g["_velo"].mean()),
            "MedianVelo": avg_v,
            "EcoX": cx,
            "EcoZ": cz,
            "EcoRadius": r,
            "EcoEV": eco_ev,
            "InEcoPct": float(in_eco.mean() * 100),
            "AvgPitchEV": float(g["_ev"].mean()),
        })
    out = pd.DataFrame(rows)
    if len(out):
        totals = out.groupby(["Pitcher", "BatterSide"])["Pitches"].transform("sum")
        out["UsagePct"] = out["Pitches"] / totals * 100
    return out


# =========================================================
# SEQUENCE ANALYSIS
# =========================================================
def sequence_sort_columns(cols):
    sort_cols = []
    for key in ["game_date", "game_id", "inning", "top_bottom", "pa_id", "pitch_no"]:
        if cols.get(key):
            sort_cols.append(cols[key])
    return sort_cols


def build_sequences(raw_df, prepared_df, cols):
    """
    Uses source row order if a complete PA/pitch ordering is not available.
    Best results require game + PA + pitch number columns.
    """
    d = prepared_df.copy()
    sort_cols = sequence_sort_columns(cols)

    # Preserve original index for merging source sequencing fields.
    if sort_cols:
        for c in sort_cols:
            d[f"_sort_{c}"] = raw_df.loc[d.index, c]
        mapped_sort = [f"_sort_{c}" for c in sort_cols]
        d = d.sort_values(["_pitcher"] + mapped_sort + [d.index.name] if d.index.name else ["_pitcher"] + mapped_sort, kind="stable")
    else:
        d = d.sort_index()

    pa_group_cols = ["_pitcher"]
    for key in ["game_date", "game_id", "inning", "top_bottom", "pa_id"]:
        c = cols.get(key)
        if c:
            d[f"_grp_{key}"] = raw_df.loc[d.index, c].astype(str)
            pa_group_cols.append(f"_grp_{key}")

    if len(pa_group_cols) == 1:
        # Without PA identifiers, only form consecutive pairs within pitcher and side.
        pa_group_cols.append("_bside")

    pieces = []
    for _, g in d.groupby(pa_group_cols, sort=False, dropna=False):
        g = g.copy()
        if len(g) < 2:
            continue
        g["_prev_pitch"] = g["_pitch_type"].shift(1)
        g["_prev_ev"] = g["_ev"].shift(1)
        g["_prev_x"] = g["_x"].shift(1)
        g["_prev_z"] = g["_z"].shift(1)
        g["_prev_side"] = g["_bside"].shift(1)
        g = g[g["_prev_pitch"].notna() & (g["_prev_side"] == g["_bside"])].copy()
        if len(g):
            g["_ev_gap"] = (g["_ev"] - g["_prev_ev"]).abs()
            g["_from_to"] = g["_prev_pitch"] + " → " + g["_pitch_type"]
            pieces.append(g)
    if not pieces:
        return pd.DataFrame()
    return pd.concat(pieces, ignore_index=True)


def sequence_summary(seq: pd.DataFrame) -> pd.DataFrame:
    if seq.empty:
        return pd.DataFrame()
    rows = []
    for (pitcher, side, pair), g in seq.groupby(["_pitcher", "_bside", "_from_to"]):
        rows.append({
            "Pitcher": pitcher,
            "BatterSide": side,
            "Sequence": pair,
            "N": len(g),
            "AvgEVGap": float(g["_ev_gap"].mean()),
            "PctInside6": float((g["_ev_gap"] < 6.0).mean() * 100),
            "PctOutside6": float((g["_ev_gap"] >= 6.0).mean() * 100),
        })
    return pd.DataFrame(rows)


# =========================================================
# OPTIONAL TUNNEL PROXY
# =========================================================
def can_make_tunnel_proxy(cols):
    return all(cols.get(k) for k in ["release_x", "release_z", "horz_break", "vert_break"])


def add_tunnel_proxy(seq: pd.DataFrame, raw_df: pd.DataFrame, cols):
    """
    A transparent proxy, NOT Perry Husband's proprietary tunnel model.
    Lower score = more similar release/shape between pitch 1 and pitch 2.
    """
    if seq.empty or not can_make_tunnel_proxy(cols):
        return seq

    # Since seq is reset-indexed, source indices are no longer straightforward.
    # Keep this feature conservative: recompute from the current and prior rows only
    # when original source columns can be brought forward in future versions.
    return seq


# =========================================================
# PDF DRAWING HELPERS
# =========================================================
RL_BLUE = HexColor(BLUE)
RL_RED = HexColor(RED)
RL_DARK = HexColor(DARK)
RL_MID = HexColor(MID)
RL_LIGHT = HexColor(LIGHT)
RL_GREEN = HexColor(GREEN)
RL_YELLOW = HexColor(YELLOW)
RL_PINK = HexColor(PINK)
W, H = letter


def rl_hex(hex_string):
    return HexColor(hex_string)


def pdf_header(c, title, subtitle, page_no, total_pages):
    c.setFillColor(RL_BLUE)
    c.rect(0, H-54, W, 54, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16.5)
    c.drawString(28, H-34, title)
    c.setFont("Helvetica", 8)
    c.drawRightString(W-28, H-33, subtitle)
    c.setStrokeColor(HexColor("#D1D5DB"))
    c.line(28, 30, W-28, 30)
    c.setFillColor(RL_MID)
    c.setFont("Helvetica", 6.7)
    c.drawString(28, 18, "Public EV estimate based on published descriptions of Perry Husband's framework; not a proprietary EV calculation.")
    c.drawRightString(W-28, 18, f"Page {page_no} of {total_pages}")


def pdf_table(c, data, widths, x, y_top, font_size=7.0, row_colors=None):
    t = Table(data, colWidths=widths)
    style = [
        ("BACKGROUND",(0,0),(-1,0),RL_BLUE),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTNAME",(0,1),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),font_size),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("GRID",(0,0),(-1,-1),0.45,HexColor("#CBD5E1")),
        ("LEFTPADDING",(0,0),(-1,-1),3),
        ("RIGHTPADDING",(0,0),(-1,-1),3),
        ("TOPPADDING",(0,0),(-1,-1),4),
        ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]
    if row_colors is None:
        style.append(("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, HexColor("#F8FAFC")]))
    else:
        for i, bg in enumerate(row_colors, start=1):
            style.append(("BACKGROUND",(0,i),(-1,i),bg))
    t.setStyle(TableStyle(style))
    tw, th = t.wrapOn(c, sum(widths), 700)
    t.drawOn(c, x, y_top-th)
    return th


def draw_strike_zone(c, x, y, w, h, title, ecosystems):
    c.setStrokeColor(RL_DARK)
    c.setLineWidth(1.0)
    c.rect(x, y, w, h, fill=0, stroke=1)

    zx = x + w*0.27
    zy = y + h*0.15
    zw = w*0.46
    zh = h*0.66

    c.setStrokeColor(colors.black)
    c.setLineWidth(1.2)
    c.rect(zx, zy, zw, zh, fill=0, stroke=1)
    c.setStrokeColor(HexColor("#D1D5DB"))
    c.setLineWidth(0.5)
    for i in [1,2]:
        c.line(zx + zw*i/3, zy, zx + zw*i/3, zy+zh)
        c.line(zx, zy + zh*i/3, zx+zw, zy+zh*i/3)

    c.setFillColor(HexColor("#E5E7EB"))
    c.roundRect(x+8, y+h-24, w-16, 16, 4, fill=1, stroke=0)
    c.setFillColor(RL_DARK)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawCentredString(x+w/2, y+h-19, title)

    # plot x range approx -2.0 to +2.0, z 0.5 to 4.5
    for eco in ecosystems:
        px = float(eco["EcoX"])
        pz = float(eco["EcoZ"])
        pt = str(eco["PitchType"])
        radius_ft = float(eco["EcoRadius"])
        nx = (px + 2.0) / 4.0
        nz = (pz - 0.5) / 4.0
        cx = x + np.clip(nx, 0.02, 0.98) * w
        cy = y + np.clip(nz, 0.02, 0.98) * h
        rr = max(8.0, min(22.0, radius_ft / 4.0 * w))
        col = rl_hex(PITCH_COLORS.get(pt, MID))
        c.setStrokeColor(col)
        c.setLineWidth(2.2)
        c.circle(cx, cy, rr, fill=0, stroke=1)
        c.setFillColor(col)
        c.setFont("Helvetica-Bold", 6.6)
        label = {
            "4-Seam":"4S","Fastball":"FB","Sinker":"SI","Cutter":"CT",
            "Slider":"SL","Sweeper":"SW","Curveball":"CB","Changeup":"CH",
            "Splitter":"FS"
        }.get(pt, pt[:2].upper())
        c.drawCentredString(cx, cy-2.4, label)


def color_for_gap(gap):
    if pd.isna(gap):
        return RL_LIGHT
    if gap < 6:
        return RL_PINK
    if gap < 10:
        return RL_YELLOW
    return RL_GREEN


def build_pdf_report(prepared, eco, seqsum, pitch_chart_pitchers=None):
    pitchers = list(dict.fromkeys(prepared["_pitcher"].tolist()))
    total_pages = len(pitchers) * 3
    bio = io.BytesIO()
    c = canvas.Canvas(bio, pagesize=letter)
    c.setTitle("EV Ecosystem & Sequencing Report")

    chart_map = {}
    if pitch_chart_pitchers:
        chart_map = {p.name.lower(): p for p in pitch_chart_pitchers}

    pg = 0
    for pitcher in pitchers:
        pdat = prepared[prepared["_pitcher"] == pitcher].copy()
        peco = eco[eco["Pitcher"] == pitcher].copy()
        pseq = seqsum[seqsum["Pitcher"] == pitcher].copy() if len(seqsum) else pd.DataFrame()

        phand = ""
        if "_phand" in pdat.columns and pdat["_phand"].notna().any():
            phand = str(pdat["_phand"].dropna().iloc[0])
        elif pitcher.lower() in chart_map:
            phand = chart_map[pitcher.lower()].hand

        # PAGE 1
        pg += 1
        pdf_header(c, "Pitcher EV Ecosystem Report", f"{pitcher} • {phand}HP" if phand else pitcher, pg, total_pages)

        c.setFillColor(RL_DARK)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(28, H-79, pitcher)
        c.setFont("Helvetica", 7.7)
        c.setFillColor(RL_MID)
        c.drawString(28, H-92, "Density-based pitch ecosystems shown separately from the hitter's RHH and LHH perspective.")

        rhh = peco[peco["BatterSide"] == "R"].to_dict("records")
        lhh = peco[peco["BatterSide"] == "L"].to_dict("records")
        draw_strike_zone(c, 34, 392, 250, 238, "vs RIGHT-HANDED HITTER", rhh)
        draw_strike_zone(c, 328, 392, 250, 238, "vs LEFT-HANDED HITTER", lhh)

        # table, one row per pitch/side
        rows = [["Side","Pitch","N","Usage","Avg Velo","Eco EV","In Eco"]]
        for _, r in peco.sort_values(["BatterSide","UsagePct"], ascending=[True,False]).iterrows():
            rows.append([
                "RHH" if r["BatterSide"]=="R" else "LHH",
                r["PitchType"], int(r["Pitches"]), f'{r["UsagePct"]:.0f}%',
                f'{r["AvgVelo"]:.1f}', f'{r["EcoEV"]:.1f}', f'{r["InEcoPct"]:.0f}%'
            ])
        rows = rows[:15]
        th = pdf_table(c, rows, [44,76,38,48,68,62,62], 56, 366, font_size=6.7)

        c.setFillColor(RL_LIGHT)
        yb = max(66, 350-th-82)
        c.roundRect(34, yb, 544, 62, 7, fill=1, stroke=0)
        c.setFillColor(RL_DARK)
        c.setFont("Helvetica-Bold", 8.4)
        c.drawString(45, yb+44, "How to read this page")
        c.setFont("Helvetica", 7.2)
        c.drawString(45, yb+29, "The circle marks the densest landing area for that pitch. 'Eco EV' estimates reactionary speed at the ecosystem center.")
        c.drawString(45, yb+15, "The same pitch can have a different ecosystem and different reactionary-speed effect vs RHH and LHH.")
        c.showPage()

        # PAGE 2
        pg += 1
        pdf_header(c, "EV Differential Matrix", f"{pitcher} • Sequence timing", pg, total_pages)
        c.setFillColor(RL_DARK)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(28, H-80, "Actual consecutive pitch pairs")
        c.setFont("Helvetica", 7.6)
        c.setFillColor(RL_MID)
        c.drawString(28, H-94, "Green = average EV gap ≥10; yellow = 6–9.9; red = <6 EvMPH. Tunnel quality is intentionally kept separate.")

        if not pseq.empty:
            top = pseq.sort_values(["N","AvgEVGap"], ascending=[False,False]).head(16)
            rows = [["Side","Sequence","N","Avg EV Gap","Inside 6","Timing"]]
            colors_rows = []
            for _, r in top.iterrows():
                gap = r["AvgEVGap"]
                timing = "At Risk" if gap < 6 else ("Separated" if gap < 10 else "Strong Sep.")
                rows.append([
                    "RHH" if r["BatterSide"]=="R" else "LHH",
                    r["Sequence"], int(r["N"]), f"{gap:.1f}",
                    f'{r["PctInside6"]:.0f}%', timing
                ])
                colors_rows.append(color_for_gap(gap))
            th = pdf_table(c, rows, [48,130,38,74,70,90], 80, H-122, font_size=7.0, row_colors=colors_rows)
        else:
            c.setFillColor(HexColor("#F8FAFC"))
            c.roundRect(54, 490, 504, 100, 8, fill=1, stroke=0)
            c.setFillColor(RL_DARK)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(72, 558, "Sequence ordering was not available.")
            c.setFont("Helvetica", 8)
            c.drawString(72, 540, "Include game / plate appearance / pitch-number fields in the raw CSV")
            c.drawString(72, 526, "to calculate true consecutive-pitch EV differentials.")

        c.setFillColor(RL_LIGHT)
        c.roundRect(46, 104, 520, 126, 8, fill=1, stroke=0)
        c.setFillColor(RL_DARK)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(60, 207, "Important: EV separation ≠ tunneling")
        c.setFont("Helvetica", 7.5)
        c.drawString(60, 190, "Perry Husband's public work treats tunnels as a deception / pitch-identification problem.")
        c.drawString(60, 176, "This report does not call a pair a 'good tunnel' from plate location alone.")
        c.drawString(60, 155, "For a true tunnel section, upload trajectory-capable data (release + pitch flight fields).")
        c.drawString(60, 141, "The current timing analysis asks a separate question: did consecutive pitches create")
        c.drawString(60, 127, "enough reactionary-speed separation to move outside the hitter's timing window?")
        c.showPage()

        # PAGE 3
        pg += 1
        pdf_header(c, "Sequencing Plan", f"{pitcher} • Actionable summary", pg, total_pages)
        c.setFillColor(RL_DARK)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(28, H-80, "Most-used sequence relationships")

        if not pseq.empty:
            used = pseq.sort_values("N", ascending=False).head(12).copy()
            rows = [["Side","Sequence","N","EV Gap","<6 EV","Classification"]]
            row_bgs = []
            for _, r in used.iterrows():
                gap = r["AvgEVGap"]
                cls = "AT RISK" if gap < 6 else ("CAUTION" if gap < 10 else "SEPARATED")
                rows.append([
                    "RHH" if r["BatterSide"]=="R" else "LHH",
                    r["Sequence"], int(r["N"]), f"{gap:.1f}",
                    f'{r["PctInside6"]:.0f}%', cls
                ])
                row_bgs.append(color_for_gap(gap))
            th = pdf_table(c, rows, [46,132,38,62,62,92], 80, H-108, font_size=7.0, row_colors=row_bgs)

            # Best / caution / risk boxes
            best = pseq[pseq["AvgEVGap"] >= 10].sort_values(["N","AvgEVGap"], ascending=False).head(4)
            caution = pseq[(pseq["AvgEVGap"] >= 6) & (pseq["AvgEVGap"] < 10)].sort_values("N", ascending=False).head(4)
            risk = pseq[pseq["AvgEVGap"] < 6].sort_values("N", ascending=False).head(4)

            sections = [
                ("STRONG SEPARATION", best, RL_GREEN),
                ("CAUTION", caution, RL_YELLOW),
                ("AT RISK", risk, RL_PINK),
            ]
            xs = [28, 213, 398]
            for (title, frame, bg), x in zip(sections, xs):
                y = 174
                c.setFillColor(bg)
                c.roundRect(x, y, 164, 154, 7, fill=1, stroke=0)
                c.setFillColor(RL_DARK)
                c.setFont("Helvetica-Bold", 8.5)
                c.drawCentredString(x+82, y+132, title)
                c.setFont("Helvetica", 6.8)
                yy = y+111
                if frame.empty:
                    c.drawCentredString(x+82, yy, "No qualifying pairs")
                else:
                    for _, r in frame.iterrows():
                        label = f'{r["Sequence"]} • {r["AvgEVGap"]:.1f} EV'
                        if len(label) > 27:
                            label = label[:27]
                        c.drawString(x+10, yy, "• " + label)
                        yy -= 22
        else:
            c.setFillColor(RL_LIGHT)
            c.roundRect(50, 475, 512, 110, 8, fill=1, stroke=0)
            c.setFillColor(RL_DARK)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(68, 550, "No sequence table available")
            c.setFont("Helvetica", 8)
            c.drawString(68, 530, "The ecosystem pages are still valid. Add sequencing identifiers to the CSV")
            c.drawString(68, 515, "to unlock pitch-to-pitch timing analysis.")

        c.setFillColor(HexColor("#EEF2F7"))
        c.roundRect(34, 65, 544, 82, 7, fill=1, stroke=0)
        c.setFillColor(RL_DARK)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(46, 126, "Method note")
        c.setFont("Helvetica", 6.9)
        c.drawString(46, 110, "This page uses the public approximation of Effective Velocity, not Perry Husband's proprietary calculation.")
        c.drawString(46, 97, "Public descriptions: up/in plays faster, down/away plays slower; ~2.75 mph per six inches along the EV axis.")
        c.drawString(46, 84, "The full EV Ecosystem also includes deception, predictability, pitch tunnels, hitter side and scientific sequencing.")
        c.showPage()

    c.save()
    bio.seek(0)
    return bio.getvalue()


# =========================================================
# UI
# =========================================================
st.title("⚾ EV Ecosystem & Sequencing Report")
st.markdown(
    """
    <div class="ev-note">
    <b>Goal:</b> upload a Pitch Chart report like your example and, when available,
    the matching pitch-by-pitch CSV. The page builds a multi-pitcher PDF with
    pitch ecosystems, public Effective Velocity estimates, and sequencing analysis.
    </div>
    """,
    unsafe_allow_html=True,
)

st.info(
    "A Pitch Chart PDF by itself does not contain the raw velocity or full pitch-flight data needed "
    "to calculate true Effective Velocity and tunneling. The PDF is used to identify the pitchers "
    "and their pitch inventory. For the full report, upload the raw pitch-level CSV as well."
)

left, right = st.columns(2)

with left:
    pitch_chart_file = st.file_uploader(
        "1) Pitch Chart Report PDF",
        type=["pdf"],
        help="Use the standardized multi-page Pitch Chart report. One pitcher per page is ideal.",
    )

with right:
    raw_csv_files = st.file_uploader(
        "2) Pitch-by-Pitch CSVs",
        type=["csv"],
        accept_multiple_files=True,
        help="Upload one or many pitcher Pitch Info CSVs. Only pitchers found in BOTH the Pitch Chart PDF and the CSV uploads will be included.",
    )

chart_pitchers = []
if pitch_chart_file is not None:
    pdf_bytes = pitch_chart_file.getvalue()
    if fitz is None:
        st.warning("PyMuPDF is not installed, so PDF parsing is unavailable. Add `pymupdf` to requirements.txt.")
    else:
        try:
            chart_pitchers = parse_pitch_chart_pdf(pdf_bytes)
            st.success(f"Pitch Chart loaded: {len(chart_pitchers)} pitcher pages detected.")
            if chart_pitchers:
                preview = []
                for p in chart_pitchers:
                    pitch_names = sorted(set(p.pitch_counts_rhh) | set(p.pitch_counts_lhh))
                    preview.append({
                        "Pitcher": p.name,
                        "Throws": p.hand,
                        "Page": p.page_num,
                        "Pitch Types Found": ", ".join(pitch_names) if pitch_names else "—",
                    })
                st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Could not parse Pitch Chart PDF: {e}")

if raw_csv_files:
    frames = []
    load_errors = []

    for uploaded_csv in raw_csv_files:
        try:
            try:
                temp_df = pd.read_csv(uploaded_csv)
            except UnicodeDecodeError:
                uploaded_csv.seek(0)
                temp_df = pd.read_csv(uploaded_csv, encoding="latin-1")

            temp_df["_source_file"] = uploaded_csv.name
            frames.append(temp_df)
        except Exception as e:
            load_errors.append(f"{uploaded_csv.name}: {e}")

    if load_errors:
        st.error("Some CSV files could not be read:\n\n" + "\n".join(load_errors))

    if not frames:
        st.stop()

    # Combine all uploaded pitcher files. Union of columns is allowed.
    raw_df = pd.concat(frames, ignore_index=True, sort=False)

    st.success(
        f"{len(frames)} CSV file(s) loaded • {len(raw_df):,} pitch rows combined."
    )

    st.subheader("CSV field detection")
    detected = detect_columns(raw_df)

    # Allow user to correct auto-detection.
    options = ["—"] + list(raw_df.columns)

    required_keys = ["pitcher", "pitch_type", "velo", "plate_x", "plate_z", "batter_side"]
    optional_keys = ["pitcher_hand", "game_date", "game_id", "inning", "top_bottom", "pa_id", "pitch_no",
                     "release_x", "release_z", "horz_break", "vert_break"]

    with st.expander("Review / correct detected columns", expanded=False):
        cols1, cols2 = st.columns(2)
        corrected = {}
        for i, key in enumerate(required_keys + optional_keys):
            target_col = cols1 if i % 2 == 0 else cols2
            current = detected.get(key)
            idx = options.index(current) if current in options else 0
            label = key.replace("_", " ").title()
            selected = target_col.selectbox(label, options, index=idx, key=f"map_{key}")
            corrected[key] = None if selected == "—" else selected
        detected = corrected

    # ---- Match pitchers BEFORE report generation ----
    pdf_names = []
    if chart_pitchers:
        pdf_names = [p.name for p in chart_pitchers]

    csv_pitcher_col = detected.get("pitcher")
    if not csv_pitcher_col:
        st.error("Could not identify the pitcher-name column in the uploaded CSV files.")
        st.stop()

    csv_names = (
        raw_df[csv_pitcher_col]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: s.ne("")]
        .drop_duplicates()
        .tolist()
    )

    pdf_key_to_name = {person_match_key(n): n for n in pdf_names}
    csv_key_to_name = {person_match_key(n): n for n in csv_names}

    matching_keys = sorted(set(pdf_key_to_name) & set(csv_key_to_name))

    # If there is no parsed PDF yet, do not produce a report packet.
    if pitch_chart_file is None:
        st.warning("Upload the Pitch Chart PDF too. Reports are generated only for pitchers present in both sources.")
        st.stop()

    if fitz is None:
        st.warning("The PDF cannot be parsed until PyMuPDF is installed.")
        st.stop()

    if not chart_pitchers:
        st.warning("No pitcher names were detected in the Pitch Chart PDF.")
        st.stop()

    matched_rows = []
    for key in matching_keys:
        matched_rows.append({
            "Pitcher in PDF": pdf_key_to_name[key],
            "Pitcher in CSV": csv_key_to_name[key],
        })

    st.subheader("Matched pitchers")
    if matched_rows:
        st.success(
            f"{len(matched_rows)} pitcher(s) found in BOTH the Pitch Chart PDF and the uploaded CSV files."
        )
        st.dataframe(pd.DataFrame(matched_rows), use_container_width=True, hide_index=True)
    else:
        st.error("No pitcher names match between the Pitch Chart PDF and the uploaded CSV files.")
        st.stop()

    # Filter the combined raw data to matched pitchers only.
    raw_df["_pitcher_match_key"] = raw_df[csv_pitcher_col].map(person_match_key)
    matched_raw_df = raw_df[raw_df["_pitcher_match_key"].isin(matching_keys)].copy()

    # Convert the CSV pitcher name to the PDF name so the generated PDF uses one consistent name.
    canonical_pdf_name = {k: pdf_key_to_name[k] for k in matching_keys}
    matched_raw_df[csv_pitcher_col] = matched_raw_df["_pitcher_match_key"].map(canonical_pdf_name)

    # Filter chart_pitchers to matched pitchers only.
    matched_chart_pitchers = [
        p for p in chart_pitchers
        if person_match_key(p.name) in matching_keys
    ]

    # Helpful source audit.
    if "_source_file" in matched_raw_df.columns:
        audit = (
            matched_raw_df.groupby([csv_pitcher_col, "_source_file"])
            .size()
            .reset_index(name="Pitch Rows")
            .rename(columns={csv_pitcher_col: "Pitcher", "_source_file": "CSV File"})
        )
        with st.expander("Matched CSV files", expanded=False):
            st.dataframe(audit, use_container_width=True, hide_index=True)

    missing = [k for k in required_keys if not detected.get(k)]
    if missing:
        st.error(
            "The matched CSV data is missing required fields for ecosystem calculations: "
            + ", ".join(missing)
        )
        st.caption(
            "The attached Pitch Info format has pitcher, pitch type, velocity, handedness and sequence fields, "
            "but the app still needs true plate-location X/Z fields to calculate the ecosystem circles."
        )
        st.stop()

    try:
        prepared = prepare_pitch_data(matched_raw_df, detected)
    except Exception as e:
        st.error(str(e))
        st.stop()

    if prepared.empty:
        st.error("No usable pitch rows were found for the matched pitchers after cleaning the CSVs.")
        st.stop()

    # Guard against placeholder location columns (for example x=0 on every row).
    x_unique = prepared["_x"].dropna().nunique()
    z_unique = prepared["_z"].dropna().nunique()
    if x_unique <= 2 or z_unique <= 2:
        st.error(
            "The selected plate-location columns do not contain usable pitch locations. "
            "Choose the real horizontal and vertical plate-location fields in the field-mapping section."
        )
        st.stop()

    eco = build_ecosystem_summary(prepared)
    seq = build_sequences(matched_raw_df, prepared, detected)
    seqsum = sequence_summary(seq)

    # Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Matched Pitchers", prepared["_pitcher"].nunique())
    m2.metric("Matched Pitches", f"{len(prepared):,}")
    m3.metric("Pitch Types", prepared["_pitch_type"].nunique())
    if not seq.empty:
        m4.metric("Consecutive Pairs", f"{len(seq):,}")
    else:
        m4.metric("Consecutive Pairs", "Not available")

    st.subheader("Ecosystem preview")
    pitcher_options = list(prepared["_pitcher"].drop_duplicates())
    selected_pitcher = st.selectbox("Pitcher", pitcher_options)

    p_eco = eco[eco["Pitcher"] == selected_pitcher].copy()
    if len(p_eco):
        view = p_eco[
            ["BatterSide","PitchType","Pitches","UsagePct","AvgVelo","EcoX","EcoZ","EcoRadius","EcoEV","InEcoPct"]
        ].copy()
        view["BatterSide"] = view["BatterSide"].map({"R":"RHH","L":"LHH"})
        for c in ["UsagePct","AvgVelo","EcoX","EcoZ","EcoRadius","EcoEV","InEcoPct"]:
            view[c] = view[c].round(1)
        st.dataframe(view, use_container_width=True, hide_index=True)

    st.subheader("Generate matched-pitcher report packet")
    st.caption(
        "Only pitchers present in BOTH the Pitch Chart PDF and the uploaded CSV files are included. "
        "Each matched pitcher receives 3 pages: EV Ecosystem, EV Differential Matrix, and Sequencing Plan."
    )

    if st.button("Generate Matched Pitchers PDF", type="primary", use_container_width=True):
        with st.spinner("Building matched pitcher reports..."):
            pdf_output = build_pdf_report(prepared, eco, seqsum, matched_chart_pitchers)
        st.session_state["ev_pdf_output"] = pdf_output
        st.success(f"Report created for {prepared['_pitcher'].nunique()} matched pitcher(s).")

    if "ev_pdf_output" in st.session_state:
        st.download_button(
            "⬇️ Download Matched EV Ecosystem & Sequencing Report",
            data=st.session_state["ev_pdf_output"],
            file_name="Matched_EV_Ecosystem_Sequencing_Report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    with st.expander("Methodology / important limitations"):
        st.markdown(
            """
            - **Pitcher inclusion:** only pitchers present in both the uploaded Pitch Chart PDF and at least one uploaded CSV.
            - **Pitch ecosystem:** density-mode of plate location for each pitch type, separated vs RHH/LHH.
            - **Public EV estimate:** uses the published up/in ↔ down/away reactionary-speed concept and
              approximately **2.75 mph per six inches** along the EV axis.
            - **6 EvMPH band:** used as a sequencing reference because Husband's public material discusses
              hitters performing best within roughly a 6 EvMPH speed bubble.
            - **True pitch tunneling is not inferred from landing location alone.** Genuine tunnel analysis needs
              pitch-flight / trajectory information.
            - Perry Husband's full Effective Velocity system is more sophisticated than this public approximation.
            """
        )

else:
    st.markdown("---")
    if pitch_chart_file is not None and fitz is None:
        st.warning(
            "The PDF was uploaded, but it has NOT been parsed because PyMuPDF is not installed. "
            "Add `pymupdf` to requirements.txt, redeploy, then upload the report again."
        )
    elif pitch_chart_file is not None and chart_pitchers:
        st.warning(
            "The Pitch Chart was parsed successfully. Upload the matching pitch-by-pitch CSV to calculate "
            "velocity, ecosystem centers, EvMPH and sequence relationships for every pitcher."
        )
    elif pitch_chart_file is not None:
        st.warning(
            "The PDF was uploaded, but no pitcher pages were detected. Make sure this is the standardized "
            "Pitch Chart report format."
        )
    else:
        st.caption("Start by uploading the Pitch Chart report and the matching pitch-level CSV.")
