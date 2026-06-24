import io
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# =====================================================
# ADVANCED PREGAME VISUAL REPORT
# Permanent page target: pages/07_Pregame_Visual_Report.py
# PDF engine: reportlab canvas only. No SimpleDocTemplate.
# =====================================================

st.set_page_config(page_title="Advanced Pregame Report", layout="wide")

NAVY = HexColor("#002D72")
RED = HexColor("#BA0C2F")
DARK = HexColor("#1F2937")
GRAY = HexColor("#F3F6FA")
BORDER = HexColor("#CBD5E1")
GREEN = HexColor("#147A36")
GREEN_BG = HexColor("#E8F5E9")
RED_BG = HexColor("#FDECEC")
LIGHT_BLUE = HexColor("#EAF2FF")
WHITE = colors.white
BLACK = colors.black

PAGE_W, PAGE_H = landscape(letter)
COUNTS = ["0-0", "1-0", "2-0", "3-0", "0-1", "1-1", "2-1", "3-1", "0-2", "1-2", "2-2", "3-2"]
PITCH_ORDER = ["FA", "SI", "FC", "SL", "CU", "CH", "FS", "SW", "KN"]
PITCH_COLORS = {
    "FA": HexColor("#D9233F"), "FF": HexColor("#D9233F"), "SI": HexColor("#F28E2B"),
    "FC": HexColor("#59A14F"), "SL": HexColor("#2878D7"), "CU": HexColor("#7B4ABF"),
    "CH": HexColor("#F5C542"), "FS": HexColor("#00A5A5"), "SW": HexColor("#8B5CF6"),
    "KN": HexColor("#999999"), "OTHER": HexColor("#A0AEC0")
}

# -----------------------------
# Utility helpers
# -----------------------------
def clean_col(c):
    return re.sub(r"[^a-z0-9]", "", str(c).strip().lower())

def find_col(df, candidates):
    if df is None or df.empty:
        return None
    lookup = {clean_col(c): c for c in df.columns}
    for cand in candidates:
        key = clean_col(cand)
        if key in lookup:
            return lookup[key]
    for c in df.columns:
        cc = clean_col(c)
        for cand in candidates:
            if clean_col(cand) in cc:
                return c
    return None

def pct(x, digits=1):
    if x is None or pd.isna(x) or np.isinf(x):
        return "-"
    return f"{float(x)*100:.{digits}f}%"

def pct_pts(x, digits=1):
    if x is None or pd.isna(x) or np.isinf(x):
        return "-"
    sign = "+" if float(x) >= 0 else ""
    return f"{sign}{float(x)*100:.{digits}f}%"

def num(x, digits=3):
    if x is None or pd.isna(x) or np.isinf(x):
        return "-"
    x = float(x)
    if 0 <= x < 1:
        return f"{x:.{digits}f}".replace("0.", ".")
    return f"{x:.{digits}f}"

def safe_div(a, b):
    try:
        return float(a) / float(b) if float(b) else 0.0
    except Exception:
        return 0.0

def norm_pitch(p):
    p = str(p).strip().upper()
    if p in ["UN", "", "NAN", "NONE"]:
        return None
    aliases = {
        "FASTBALL": "FA", "FOURSEAM": "FA", "FOUR-SEAM": "FA", "4SEAM": "FA", "4-SEAM": "FA", "FF": "FA",
        "SINKER": "SI", "TWOSEAM": "SI", "2SEAM": "SI", "2-SEAM": "SI",
        "CUTTER": "FC", "SLIDER": "SL", "CURVE": "CU", "CURVEBALL": "CU",
        "CHANGEUP": "CH", "CHANGE": "CH", "SPLITTER": "FS", "SPLIT": "FS", "SWEEPER": "SW"
    }
    return aliases.get(p, p)

def outcome_is_swing(x):
    s = str(x).strip().lower().replace(" ", "")
    take_terms = {
        "ball", "ballcall", "calledball", "strikecalled", "calledstrike",
        "automaticball", "automaticstrike", "intentball", "pitchout"
    }
    return s not in take_terms

def read_csv_file(uploaded):
    try:
        return pd.read_csv(uploaded)
    except Exception:
        uploaded.seek(0)
        return pd.read_csv(uploaded, encoding="latin1")

def detect_files(files):
    out = {}
    for f in files or []:
        name = f.name.lower()
        if "pitch usage" in name:
            out["league_pitch_usage"] = f
        elif "pregame hitting" in name:
            out["league_hitting"] = f
        elif re.search(r"(^|[^a-z])rate([^a-z]|$)", name):
            out["league_pitching"] = f
        elif "catching" in name:
            out["catching"] = f
        elif "sba count" in name:
            out["sba_count"] = f
        elif "stolen" in name:
            out["stolen_bases"] = f
        elif "standard" in name:
            out["standard"] = f
        elif "pregame" in name:
            out["pregame"] = f
    return out

def parse_pct_series(series):
    s = series.astype(str).str.replace("%", "", regex=False).str.strip()
    v = pd.to_numeric(s, errors="coerce")
    if v.dropna().mean() is not None and pd.notna(v.dropna().mean()) and v.dropna().mean() > 1:
        v = v / 100.0
    return v

def find_logo_path():
    for path in ["Rangers.png", "rangers.png", "assets/Rangers.png", "assets/rangers.png", "images/Rangers.png", "images/rangers.png"]:
        if os.path.exists(path):
            return path
    return None

# -----------------------------
# Data builders
# -----------------------------
def build_hitting(pregame):
    if pregame is None or pregame.empty:
        return {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    df = pregame.copy()
    hitter_col = find_col(df, ["batter", "hitter", "playerFullName", "batterFullName", "batterAbbrevName"])
    result_col = find_col(df, ["pitchCall", "pitchResult", "PitchCall", "PitchResult", "playResult", "result"])
    balls_col = find_col(df, ["balls", "Balls", "B"])
    strikes_col = find_col(df, ["strikes", "Strikes", "S"])

    if balls_col and strikes_col:
        df["Count"] = df[balls_col].astype(str).str.replace(".0", "", regex=False) + "-" + df[strikes_col].astype(str).str.replace(".0", "", regex=False)
    else:
        count_col = find_col(df, ["count", "Count"])
        df["Count"] = df[count_col].astype(str) if count_col else "0-0"

    df["Swing"] = df[result_col].apply(outcome_is_swing) if result_col else False
    swing_by_count = df.groupby("Count").agg(Pitches=("Swing", "size"), SwingPct=("Swing", "mean")).reset_index()
    swing_by_count = swing_by_count[swing_by_count["Count"].isin(COUNTS)]

    if hitter_col:
        hitter_swing = df.groupby(hitter_col).agg(Pitches=("Swing", "size"), SwingPct=("Swing", "mean")).reset_index()
        hitter_swing = hitter_swing.rename(columns={hitter_col: "Player"}).sort_values("Pitches", ascending=False)
    else:
        hitter_swing = pd.DataFrame(columns=["Player", "Pitches", "SwingPct"])

    player_col = hitter_col
    play_col = find_col(df, ["playResult", "PlayResult", "result", "Result", "KorBB", "PitchCall"])
    pa_col = find_col(df, ["PA", "pa"])
    ab_col = find_col(df, ["AB", "ab"])
    h_col = find_col(df, ["H", "hit", "hits"])
    bb_col = find_col(df, ["BB", "walk", "walks"])
    k_col = find_col(df, ["K", "SO", "strikeout", "strikeouts"])
    tb_col = find_col(df, ["TB", "totalBases", "TotalBases"])

    if all([player_col, pa_col, ab_col, h_col]):
        g = df.groupby(player_col).agg(
            PA=(pa_col, "sum"), AB=(ab_col, "sum"), H=(h_col, "sum"),
            BB=(bb_col, "sum") if bb_col else (pa_col, lambda x: 0),
            K=(k_col, "sum") if k_col else (pa_col, lambda x: 0),
            TB=(tb_col, "sum") if tb_col else (h_col, "sum")
        ).reset_index().rename(columns={player_col: "Player"})
    else:
        tmp = df.copy()
        tmp["Player"] = tmp[player_col].astype(str) if player_col else "Unknown"
        terminal = tmp[play_col].astype(str).str.lower() if play_col else pd.Series([""] * len(tmp))
        is_pa = terminal.str.contains("single|double|triple|home|walk|strikeout|out|sac|error|hitbypitch|hbp|fielderschoice", regex=True)
        if not is_pa.any():
            is_pa = tmp["Player"].ne(tmp["Player"].shift(-1))
        pa_rows = tmp[is_pa].copy()
        val = pa_rows[play_col].astype(str).str.lower() if play_col else pd.Series([""] * len(pa_rows))
        pa_rows["BB"] = val.str.contains("walk|bb", regex=True).astype(int)
        pa_rows["K"] = val.str.contains("strikeout", regex=True).astype(int)
        pa_rows["HBP"] = val.str.contains("hbp|hitbypitch", regex=True).astype(int)
        pa_rows["H"] = val.str.contains("single|double|triple|home", regex=True).astype(int)
        pa_rows["TB"] = np.select([
            val.str.contains("home", regex=True), val.str.contains("triple", regex=True),
            val.str.contains("double", regex=True), val.str.contains("single", regex=True)
        ], [4, 3, 2, 1], default=0)
        pa_rows["AB"] = (~((pa_rows["BB"] == 1) | (pa_rows["HBP"] == 1) | val.str.contains("sac", regex=True))).astype(int)
        g = pa_rows.groupby("Player").agg(PA=("Player", "size"), AB=("AB", "sum"), H=("H", "sum"), BB=("BB", "sum"), K=("K", "sum"), TB=("TB", "sum")).reset_index()

    for c in ["PA", "AB", "H", "BB", "K", "TB"]:
        if c not in g.columns:
            g[c] = 0
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    g["AVG"] = g.apply(lambda r: safe_div(r.H, r.AB), axis=1)
    g["OBP"] = g.apply(lambda r: safe_div(r.H + r.BB, r.AB + r.BB), axis=1)
    g["SLG"] = g.apply(lambda r: safe_div(r.TB, r.AB), axis=1)
    g["OPS"] = g["OBP"] + g["SLG"]
    g["BB%"] = g.apply(lambda r: safe_div(r.BB, r.PA), axis=1)
    g["K%"] = g.apply(lambda r: safe_div(r.K, r.PA), axis=1)
    g = g[g["Player"].astype(str).str.lower() != "playerfullname"]
    g = g[~g["Player"].astype(str).str.lower().isin(["nan", "none", "unknown"])]
    g = g.sort_values("OPS", ascending=False)

    team = {
        "OPS": safe_div(g["H"].sum() + g["BB"].sum(), g["AB"].sum() + g["BB"].sum()) + safe_div(g["TB"].sum(), g["AB"].sum()),
        "AVG": safe_div(g["H"].sum(), g["AB"].sum()),
        "Swing%": df["Swing"].mean() if len(df) else 0,
    }
    return team, swing_by_count, hitter_swing, g

def build_pitching(standard):
    if standard is None or standard.empty:
        return {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    df = standard.copy()
    pitcher_col = find_col(df, ["pitcher", "pitcherFullName", "pitcherAbbrevName", "Player"])
    pitch_col = find_col(df, ["pitchType", "TaggedPitchType", "AutoPitchType", "PitchType"])
    result_col = find_col(df, ["pitchCall", "pitchResult", "PlayResult", "KorBB", "Result"])
    balls_col = find_col(df, ["balls", "Balls", "B"])
    strikes_col = find_col(df, ["strikes", "Strikes", "S"])
    if balls_col and strikes_col:
        df["Count"] = df[balls_col].astype(str).str.replace(".0", "", regex=False) + "-" + df[strikes_col].astype(str).str.replace(".0", "", regex=False)
    else:
        count_col = find_col(df, ["count", "Count"])
        df["Count"] = df[count_col].astype(str) if count_col else "0-0"
    df["Pitch"] = df[pitch_col].apply(norm_pitch) if pitch_col else "OTHER"
    df = df[df["Pitch"].notna()].copy()

    usage_count = pd.crosstab(df["Count"], df["Pitch"], normalize="index").reset_index()
    usage_count = usage_count[usage_count["Count"].isin(COUNTS)]
    usage_overall = df["Pitch"].value_counts(normalize=True).rename_axis("Pitch").reset_index(name="Usage")

    if pitcher_col:
        pitcher_usage = pd.crosstab(df[pitcher_col], df["Pitch"], normalize="index") * 100
        pitcher_counts = df.groupby(pitcher_col).size().rename("Pitches")
        pitcher_usage = pitcher_usage.join(pitcher_counts).reset_index().rename(columns={pitcher_col: "Pitcher"})
        cols = ["Pitcher", "Pitches"] + [c for c in PITCH_ORDER if c in pitcher_usage.columns]
        pitcher_usage = pitcher_usage[cols].sort_values("Pitches", ascending=False)
    else:
        pitcher_usage = pd.DataFrame()

    tmp = standard.copy()
    tmp["Pitcher"] = tmp[pitcher_col].astype(str) if pitcher_col else "Unknown"
    res = tmp[result_col].astype(str).str.lower() if result_col else pd.Series([""] * len(tmp))
    is_pa = res.str.contains("walk|bb|strikeout|single|double|triple|home|out|hbp|hitbypitch|sac|error", regex=True)
    if not is_pa.any():
        batter_col = find_col(tmp, ["batter", "batterFullName", "batterAbbrevName"])
        is_pa = tmp[batter_col].ne(tmp[batter_col].shift(-1)) if batter_col else pd.Series([False] * len(tmp))
    pa = tmp[is_pa].copy()
    res_pa = pa[result_col].astype(str).str.lower() if result_col else pd.Series([""] * len(pa))
    pa["BB"] = res_pa.str.contains("walk|bb", regex=True).astype(int)
    pa["K"] = res_pa.str.contains("strikeout", regex=True).astype(int)
    leaders = pa.groupby("Pitcher").agg(PA=("Pitcher", "size"), BB=("BB", "sum"), K=("K", "sum")).reset_index()
    if leaders.empty and pitcher_col:
        leaders = df.groupby(pitcher_col).size().reset_index(name="Pitches").rename(columns={pitcher_col: "Pitcher"})
        leaders["PA"] = 0; leaders["BB"] = 0; leaders["K"] = 0
    leaders = leaders[~leaders["Pitcher"].astype(str).str.lower().isin(["nan", "none", "unknown", "playerfullname"])]
    leaders["BB%"] = leaders.apply(lambda r: safe_div(r.BB, r.PA), axis=1)
    leaders["K%"] = leaders.apply(lambda r: safe_div(r.K, r.PA), axis=1)

    team = {"BB%": safe_div(leaders["BB"].sum(), leaders["PA"].sum()), "K%": safe_div(leaders["K"].sum(), leaders["PA"].sum())}
    return team, usage_count, usage_overall, pitcher_usage, leaders

def build_catching(catching):
    if catching is None or catching.empty:
        return {}, pd.DataFrame()
    df = catching.copy()
    catcher_col = find_col(df, ["catcher", "Catcher"])
    sba_col = find_col(df, ["baseStealAtt", "BaseStealAtt", "basestealatt", "SBA"])
    outs_col = find_col(df, ["outs", "Outs"])
    if catcher_col is None:
        return {}, pd.DataFrame()
    if sba_col:
        att = df[sba_col].astype(str).str.lower().isin(["1", "true", "yes", "y", "sba", "steal", "attempt"])
        steal_rows = df[att].copy()
    else:
        steal_rows = df.copy()
    if outs_col and len(steal_rows):
        next_outs = df[outs_col].shift(-1)
        steal_rows["CS"] = (pd.to_numeric(next_outs.loc[steal_rows.index], errors="coerce") > pd.to_numeric(df.loc[steal_rows.index, outs_col], errors="coerce")).astype(int)
    else:
        cs_col = find_col(df, ["CS", "CaughtStealing"])
        steal_rows["CS"] = pd.to_numeric(steal_rows[cs_col], errors="coerce").fillna(0) if cs_col else 0
    steal_rows["SBA"] = 1
    g = steal_rows.groupby(catcher_col).agg(SBA=("SBA", "sum"), CS=("CS", "sum")).reset_index().rename(columns={catcher_col: "Catcher"})
    g = g[~g["Catcher"].astype(str).str.lower().isin(["nan", "none", "unknown"])]
    g["SB"] = g["SBA"] - g["CS"]
    g["CS%"] = g.apply(lambda r: safe_div(r.CS, r.SBA), axis=1)
    team = {"SBA": g["SBA"].sum(), "CS%": safe_div(g["CS"].sum(), g["SBA"].sum())}
    return team, g.sort_values("CS%", ascending=False)

def build_running(stolen_bases, sba_count):
    team_counts = pd.DataFrame(columns=["Count", "SBA"])
    runners = pd.DataFrame(columns=["Runner", "SBA", "SB", "SB%"])
    if stolen_bases is not None and not stolen_bases.empty:
        df = stolen_bases.copy()
        count_col = find_col(df, ["Count", "count"])
        sba_col = find_col(df, ["SBA", "SB Attempts", "Attempts", "basestealatt"])
        if count_col:
            if sba_col:
                team_counts = df[[count_col, sba_col]].rename(columns={count_col: "Count", sba_col: "SBA"})
            else:
                team_counts = df.groupby(count_col).size().reset_index(name="SBA").rename(columns={count_col: "Count"})
    if sba_count is not None and not sba_count.empty:
        df = sba_count.copy()
        runner_col = find_col(df, ["Runner", "playerFullName", "Player", "runner"])
        total_col = find_col(df, ["Total SBA", "SBA", "Attempts", "Total"])
        sb_col = find_col(df, ["SB", "StolenBase", "Successful"])
        if runner_col:
            runners["Runner"] = df[runner_col].astype(str)
            runners["SBA"] = pd.to_numeric(df[total_col], errors="coerce").fillna(0) if total_col else 0
            runners["SB"] = pd.to_numeric(df[sb_col], errors="coerce").fillna(runners["SBA"]) if sb_col else runners["SBA"]
            runners["SB%"] = runners.apply(lambda r: safe_div(r.SB, r.SBA), axis=1)
            runners = runners[~runners["Runner"].str.lower().isin(["playerfullname", "nan", "none", "unknown"])]
            runners = runners.sort_values("SBA", ascending=False)
    team = {"SBA": team_counts["SBA"].sum() if not team_counts.empty else runners["SBA"].sum(), "SB%": safe_div(runners["SB"].sum(), runners["SBA"].sum()) if not runners.empty else 0}
    return team, team_counts, runners

def league_hitting_baseline(df):
    if df is None or df.empty:
        return {"OPS": None, "AVG": None, "Swing%": None}
    ops_col = find_col(df, ["OPS", "ops"])
    avg_col = find_col(df, ["AVG", "BA", "avg"])
    swing_col = find_col(df, ["Swing%", "SwingPct", "swing"])
    return {
        "OPS": pd.to_numeric(df[ops_col], errors="coerce").mean() if ops_col else None,
        "AVG": pd.to_numeric(df[avg_col], errors="coerce").mean() if avg_col else None,
        "Swing%": parse_pct_series(df[swing_col]).mean() if swing_col else None,
    }

def league_pitching_baseline(df):
    if df is None or df.empty:
        return {"BB%": None, "K%": None}
    bb_col = find_col(df, ["BB%", "BBPct", "Walk%"])
    k_col = find_col(df, ["K%", "KPct", "SO%"])
    return {"BB%": parse_pct_series(df[bb_col]).mean() if bb_col else None, "K%": parse_pct_series(df[k_col]).mean() if k_col else None}

def league_pitch_usage_baseline(df):
    if df is None or df.empty:
        return {}
    pitch_col = find_col(df, ["Pitch", "Pitch Type", "pitchType", "TaggedPitchType", "AutoPitchType"])
    usage_col = find_col(df, ["Usage", "Usage%", "Pitch Usage", "Pitch%", "%", "Pct"])
    if pitch_col is None:
        return {}
    tmp = df.copy()
    tmp["Pitch"] = tmp[pitch_col].apply(norm_pitch)
    tmp = tmp[tmp["Pitch"].notna()]
    if usage_col:
        tmp["Usage"] = parse_pct_series(tmp[usage_col])
        return tmp.groupby("Pitch")["Usage"].mean().dropna().to_dict()
    total = len(tmp)
    return (tmp["Pitch"].value_counts() / total).to_dict() if total else {}

# -----------------------------
# Drawing helpers
# -----------------------------
def draw_wrapped(c, text, x, y, max_w, font="Helvetica", size=8, leading=10, color=BLACK, max_lines=4):
    c.setFillColor(color)
    c.setFont(font, size)
    words = str(text).split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if c.stringWidth(test, font, size) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    lines = lines[:max_lines]
    for i, ln in enumerate(lines):
        c.drawString(x, y - i * leading, ln)
    return y - len(lines) * leading

def round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=8, lw=1):
    c.setLineWidth(lw); c.setStrokeColor(stroke); c.setFillColor(fill)
    c.roundRect(x, y, w, h, radius, stroke=1, fill=1)

def draw_header(c, opponent, page_num, logo_path=None):
    margin = 22
    logo_path = logo_path or find_logo_path()
    if logo_path and os.path.exists(logo_path):
        try:
            c.drawImage(ImageReader(logo_path), margin, PAGE_H - 77, width=62, height=62, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass
    else:
        c.setFillColor(NAVY); c.circle(margin + 31, PAGE_H - 46, 30, fill=1); c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 28); c.drawCentredString(margin + 31, PAGE_H - 56, "T")
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 28); c.drawString(95, PAGE_H - 38, "ADVANCED PREGAME REPORT")
    c.setFillColor(RED); c.setFont("Helvetica-Bold", 15); c.drawString(96, PAGE_H - 63, f"VS. {opponent.upper()}")
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 9); c.drawRightString(PAGE_W - 35, PAGE_H - 38, datetime.now().strftime("%b %d, %Y"))
    c.drawRightString(PAGE_W - 35, 25, f"PAGE {page_num}")
    c.setStrokeColor(RED); c.setLineWidth(2); c.line(22, PAGE_H - 84, PAGE_W - 22, PAGE_H - 84)

def section_bar(c, y, text):
    round_rect(c, 22, y, PAGE_W - 44, 28, fill=NAVY, stroke=NAVY, radius=5)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 15); c.drawString(35, y + 8, text)

def metric_card(c, x, y, w, h, title, value, subtitle="", lg=None, better=True, stat_label=None):
    round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=8)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 8.5); c.drawCentredString(x + w / 2, y + h - 17, title)
    val_y = y + h - 48 if stat_label else y + h - 38
    if stat_label:
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", 7.0); c.drawCentredString(x + w / 2, y + h - 31, stat_label)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 20); c.drawCentredString(x + w / 2, val_y, value)
    if subtitle:
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", 7); c.drawCentredString(x + w / 2, val_y - 13, subtitle)
    if lg is not None:
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", 7); c.drawCentredString(x + w / 2, y + 24, f"LG AVG {lg}")
    bg, col = (GREEN_BG, GREEN) if better else (RED_BG, RED)
    round_rect(c, x + 16, y + 6, w - 32, 16, fill=bg, stroke=bg, radius=4)
    c.setFillColor(col); c.setFont("Helvetica-Bold", 7.3); c.drawCentredString(x + w / 2, y + 10, "▲ BETTER" if better else "▼ BELOW AVG")

def draw_table(c, x, y, w, h, title, rows, headers, font_size=6.4, max_rows=6, highlight_diff=False):
    round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=7)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 8); c.drawCentredString(x + w/2, y + h - 15, title)
    rows = rows[:max_rows]
    top = y + h - 31
    row_h = min(16, (h - 38) / max(1, len(rows) + 1))
    c.setFillColor(GRAY); c.rect(x + 6, top - row_h, w - 12, row_h, stroke=0, fill=1)
    col_w = (w - 12) / len(headers)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", font_size)
    for i, head in enumerate(headers):
        c.drawCentredString(x + 6 + col_w * i + col_w / 2, top - row_h + 5, str(head)[:14])
    for r, row in enumerate(rows):
        yy = top - row_h * (r + 2)
        if r % 2 == 1:
            c.setFillColor(HexColor("#FAFBFD")); c.rect(x + 6, yy, w - 12, row_h, stroke=0, fill=1)
        for i, val in enumerate(row):
            cell_x = x + 6 + col_w * i
            text = str(val)
            if highlight_diff and i == len(headers) - 1 and text not in ["-", ""]:
                if text.startswith("+"):
                    c.setFillColor(GREEN_BG); c.rect(cell_x + 2, yy + 1.5, col_w - 4, row_h - 3, stroke=0, fill=1); c.setFillColor(GREEN)
                elif text.startswith("-"):
                    c.setFillColor(RED_BG); c.rect(cell_x + 2, yy + 1.5, col_w - 4, row_h - 3, stroke=0, fill=1); c.setFillColor(RED)
                else:
                    c.setFillColor(BLACK)
                c.setFont("Helvetica-Bold", font_size)
            else:
                c.setFillColor(BLACK); c.setFont("Helvetica", font_size)
            max_chars = 18 if i == 0 else 8
            if len(text) > max_chars:
                text = text[:max_chars - 1] + "…"
            c.drawCentredString(cell_x + col_w / 2, yy + 5, text)

def draw_key_box(c, x, y, w, h, title, bullets):
    round_rect(c, x, y, w, h, fill=LIGHT_BLUE, stroke=BORDER, radius=8)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 9); c.drawString(x + 16, y + h - 22, title)
    yy = y + h - 40
    for b in bullets[:5]:
        c.setFillColor(NAVY); c.circle(x + 18, yy + 4, 2.2, fill=1, stroke=0)
        yy = draw_wrapped(c, b, x + 28, yy + 8, w - 44, font="Helvetica-Bold", size=7.8, leading=10, max_lines=2) - 7

def draw_pitch_usage_chart(c, x, y, w, h, usage_count):
    round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=7)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 8); c.drawCentredString(x + w/2, y + h - 15, "PITCH USAGE BY COUNT")
    if usage_count is None or usage_count.empty:
        return
    data = usage_count.set_index("Count")
    pitches = [p for p in PITCH_ORDER if p in data.columns]
    if not pitches:
        pitches = [p for p in data.columns if p != "Count"][:7]
    chart_x = x + 42; chart_y = y + 40; chart_w = w - 78
    row_h = (h - 82) / len(COUNTS)
    # X axis/grid
    c.setFont("Helvetica", 6.5); c.setFillColor(DARK); c.setStrokeColor(HexColor("#E2E8F0")); c.setLineWidth(0.5)
    for v, lab in [(0, "0%"), (.25, "25%"), (.5, "50%"), (.75, "75%"), (1, "100%")]:
        xx = chart_x + chart_w * v
        c.line(xx, chart_y - 3, xx, chart_y + row_h * len(COUNTS) + 2)
        c.drawCentredString(xx, chart_y + row_h * len(COUNTS) + 8, lab)
    for idx, cnt in enumerate(COUNTS):
        yy = chart_y + (len(COUNTS) - 1 - idx) * row_h
        c.setFillColor(DARK); c.setFont("Helvetica", 6.6); c.drawRightString(chart_x - 8, yy + 2, cnt)
        c.setFillColor(HexColor("#EDF2F7")); c.rect(chart_x, yy, chart_w, 6, stroke=0, fill=1)
        if cnt in data.index:
            start = chart_x
            for p in pitches:
                val = float(data.loc[cnt, p]) if p in data.columns and pd.notna(data.loc[cnt, p]) else 0
                seg_w = chart_w * val
                if seg_w > 0.3:
                    c.setFillColor(PITCH_COLORS.get(p, PITCH_COLORS["OTHER"])); c.rect(start, yy, seg_w, 6, stroke=0, fill=1)
                start += seg_w
    lx, ly = chart_x, y + 17
    for p in pitches[:8]:
        c.setFillColor(PITCH_COLORS.get(p, PITCH_COLORS["OTHER"])); c.circle(lx, ly + 2, 3, fill=1, stroke=0)
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", 6.2); c.drawString(lx + 6, ly, p)
        lx += 42
        if lx > x + w - 34:
            break

def draw_count_grid(c, x, y, w, h, title, values, is_pct=True):
    round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=7)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 8); c.drawCentredString(x + w/2, y + h - 15, title)
    cols, rows = 4, 3
    cell_w = (w - 24) / cols; cell_h = (h - 42) / rows
    for i, cnt in enumerate(COUNTS):
        col, row = i % cols, i // cols
        cx = x + 12 + col * cell_w; cy = y + h - 36 - (row + 1) * cell_h
        round_rect(c, cx, cy, cell_w - 6, cell_h - 5, fill=GRAY, stroke=HexColor("#E2E8F0"), radius=4)
        c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(cx + (cell_w - 6) / 2, cy + cell_h - 15, cnt)
        c.setFont("Helvetica-Bold", 10.5 if is_pct else 13)
        val = values.get(cnt, 0)
        text = pct(val) if is_pct else str(int(val))
        c.drawCentredString(cx + (cell_w - 6) / 2, cy + 9, text)

# -----------------------------
# Insights
# -----------------------------
def pitch_usage_rows(usage_overall, lg_usage):
    rows = []
    if usage_overall is None or usage_overall.empty:
        return rows
    for _, r in usage_overall.head(7).iterrows():
        p = r["Pitch"]; u = float(r["Usage"])
        lg = lg_usage.get(p) if isinstance(lg_usage, dict) else None
        diff = None if lg is None or pd.isna(lg) else u - float(lg)
        rows.append([p, pct(u), pct(lg) if lg is not None else "-", pct_pts(diff) if diff is not None else "-"])
    return rows

def build_pitching_insights(usage_overall, lg_usage, pitch_team, lg_pitch, pitch_leaders, min_pitcher_pa):
    out = []
    if usage_overall is not None and not usage_overall.empty:
        top = usage_overall.iloc[0]
        p, u = top["Pitch"], float(top["Usage"])
        lg = lg_usage.get(p) if isinstance(lg_usage, dict) else None
        if lg is not None:
            out.append(f"{p} usage is {pct(u)} ({pct_pts(u-lg)} vs league); plan around when it appears by count.")
        else:
            out.append(f"{p} is their primary pitch at {pct(u)}; expect it in leverage counts.")
        elevated = []
        for _, r in usage_overall.head(6).iterrows():
            lg2 = lg_usage.get(r["Pitch"]) if isinstance(lg_usage, dict) else None
            if lg2 is not None and float(r["Usage"]) - float(lg2) >= 0.04:
                elevated.append((r["Pitch"], float(r["Usage"]) - float(lg2)))
        if len(elevated) > 1:
            out.append(f"Secondary usage is elevated with {elevated[1][0]} ({pct_pts(elevated[1][1])} vs league); prepare for it after fastball counts.")
    bb, bb_lg = pitch_team.get("BB%", 0), lg_pitch.get("BB%")
    if bb_lg is not None:
        out.append(f"Staff BB% is {pct(bb)} vs {pct(bb_lg)} league average; force them into the zone before expanding.")
    k, k_lg = pitch_team.get("K%", 0), lg_pitch.get("K%")
    if k_lg is not None:
        out.append(f"Staff K% is {pct(k)} vs {pct(k_lg)} league average; contact opportunities are there if we control counts.")
    q = pitch_leaders[pitch_leaders["PA"] >= min_pitcher_pa] if pitch_leaders is not None and not pitch_leaders.empty else pd.DataFrame()
    if not q.empty:
        wild = q.sort_values("BB%", ascending=False).head(1).iloc[0]
        out.append(f"{wild.Pitcher} has the highest qualified BB% ({pct(wild['BB%'])}); extend at-bats and make him prove strike command.")
    return out[:5]

def build_hitting_insights(swing_by_count, hit_team, lg_hit, hitters, min_pa):
    out = []
    if swing_by_count is not None and not swing_by_count.empty:
        top = swing_by_count.sort_values("SwingPct", ascending=False).iloc[0]
        low = swing_by_count.sort_values("SwingPct", ascending=True).iloc[0]
        out.append(f"Most aggressive count is {top['Count']} ({pct(top['SwingPct'])}); use that count to expand or change speeds.")
        out.append(f"Most passive count is {low['Count']} ({pct(low['SwingPct'])}); steal strikes there when possible.")
    ops, lg_ops = hit_team.get("OPS", 0), lg_hit.get("OPS")
    if lg_ops is not None:
        out.append(f"Team OPS is {num(ops)} vs {num(lg_ops)} league average; overall run production grades below league.")
    q = hitters[hitters["PA"] >= min_pa] if hitters is not None and not hitters.empty else pd.DataFrame()
    if not q.empty:
        top2 = q.sort_values("OPS", ascending=False).head(2)["Player"].tolist()
        out.append(f"Primary threats are {', '.join(top2)}; avoid giving them free traffic ahead of damage counts.")
        bottom = q.sort_values("OPS", ascending=True).head(1).iloc[0]
        out.append(f"Attack the lower OPS pocket around {bottom.Player}; challenge early and avoid unnecessary walks.")
    return out[:5]

def build_running_insights(run_counts, run_team, runners, catch_team, catchers):
    out = []
    if run_counts is not None and not run_counts.empty:
        rc = run_counts.copy(); rc["SBA"] = pd.to_numeric(rc["SBA"], errors="coerce").fillna(0)
        top = rc.sort_values("SBA", ascending=False).iloc[0]
        out.append(f"SBA volume peaks in {top['Count']} counts ({int(top['SBA'])} attempts); control tempo in that count.")
    out.append(f"Team SB success is {pct(run_team.get('SB%', 0))}; prioritize holds, looks, and slide-step timing.")
    if runners is not None and not runners.empty:
        vols = runners.head(2)["Runner"].tolist()
        vol_names = [str(v).strip() for v in vols if pd.notna(v) and str(v).strip()]
        if vol_names:
            out.append(f"Highest-volume runners: {', '.join(vol_names)}; have the battery plan ready before they reach.")
    out.append(f"Team CS% is {pct(catch_team.get('CS%', 0))}; catcher exchange and pitcher time to plate both matter here.")
    if catchers is not None and not catchers.empty:
        top_c = catchers.sort_values("CS%", ascending=False).iloc[0]
        out.append(f"{top_c.Catcher} leads the group in CS% ({pct(top_c['CS%'])}); adjust risk by catcher on the field.")
    return out[:5]

def executive_paragraph(hit_team, lg_hit, pitch_team, lg_pitch, run_team, catch_team, hitters, usage_overall):
    top_pitch = usage_overall.iloc[0]["Pitch"] if usage_overall is not None and not usage_overall.empty else "primary pitch"
    top_hitter = hitters.sort_values("OPS", ascending=False).iloc[0]["Player"] if hitters is not None and not hitters.empty else "their top bat"
    return (f"Opponent profiles with {num(hit_team.get('OPS',0))} team OPS and a {pct(run_team.get('SB%',0))} SB success rate. "
            f"Their staff leans on {top_pitch} and carries a {pct(pitch_team.get('BB%',0))} BB%, so the offensive plan should prioritize count control and forcing strikes. "
            f"Manage the running game aggressively, especially with their top runners aboard, and treat {top_hitter} as the primary matchup bat.")

# -----------------------------
# PDF builder
# -----------------------------
def build_visual_pdf(context):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(letter))
    opponent = context.get("opponent", "Opponent")
    logo_path = context.get("logo_path")
    hit_team = context["hit_team"]; pitch_team = context["pitch_team"]; catch_team = context["catch_team"]; run_team = context["run_team"]
    lg_hit = context["lg_hit"]; lg_pitch = context["lg_pitch"]; lg_usage = context.get("lg_usage", {})
    usage_count = context["usage_count"]; usage_overall = context["usage_overall"]; pitcher_usage = context["pitcher_usage"]; pitch_leaders = context["pitch_leaders"]
    swing_by_count = context["swing_by_count"]; hitters = context["hitters"]
    catchers = context["catchers"]; run_counts = context["run_counts"]; runners = context["runners"]
    min_pa = context.get("min_pa", 30); min_pitcher_pa = context.get("min_pitcher_pa", 20)

    pitch_insights = build_pitching_insights(usage_overall, lg_usage, pitch_team, lg_pitch, pitch_leaders, min_pitcher_pa)
    hitting_insights = build_hitting_insights(swing_by_count, hit_team, lg_hit, hitters, min_pa)
    running_insights = build_running_insights(run_counts, run_team, runners, catch_team, catchers)

    # Page 1
    draw_header(c, opponent, 1, logo_path)
    section_bar(c, PAGE_H - 122, "EXECUTIVE SUMMARY")
    y = PAGE_H - 218; card_w = 180; gap = 10; x0 = 22
    hit_lg = lg_hit.get("OPS")
    metric_card(c, x0, y, card_w, 82, "TEAM HITTING", num(hit_team.get("OPS", 0)), "OPS", num(hit_lg) if hit_lg is not None else None, hit_team.get("OPS", 0) >= (hit_lg or 0), "Team OPS")
    bb_lg = lg_pitch.get("BB%")
    metric_card(c, x0 + (card_w + gap), y, card_w, 82, "TEAM PITCHING", pct(pitch_team.get("BB%", 0)), "BB% Allowed", pct(bb_lg) if bb_lg is not None else None, pitch_team.get("BB%", 0) <= (bb_lg or 1), "Opponent BB%")
    metric_card(c, x0 + 2 * (card_w + gap), y, card_w, 82, "TEAM BASERUNNING", pct(run_team.get("SB%", 0)), "SB Success", None, True, "SB%")
    metric_card(c, x0 + 3 * (card_w + gap), y, card_w, 82, "TEAM CATCHING", pct(catch_team.get("CS%", 0)), "Caught Stealing", None, True, "CS%")

    tx_y = 75; box_h = 220
    round_rect(c, 22, tx_y, 345, box_h, fill=WHITE, stroke=BORDER, radius=8)
    round_rect(c, 22, tx_y + box_h - 28, 345, 28, fill=NAVY, stroke=NAVY, radius=8)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 13); c.drawCentredString(194, tx_y + box_h - 19, "KEY TAKEAWAYS")
    summary = executive_paragraph(hit_team, lg_hit, pitch_team, lg_pitch, run_team, catch_team, hitters, usage_overall)
    draw_wrapped(c, summary, 45, tx_y + box_h - 58, 292, font="Helvetica-Bold", size=9.0, leading=13, max_lines=8)

    round_rect(c, 382, tx_y, PAGE_W - 404, box_h, fill=WHITE, stroke=BORDER, radius=8)
    round_rect(c, 382, tx_y + box_h - 28, PAGE_W - 404, 28, fill=NAVY, stroke=NAVY, radius=8)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 13); c.drawCentredString(585, tx_y + box_h - 19, "GAME PLAN")
    plan = [
        ("PITCHING APPROACH", hitting_insights[0] if hitting_insights else "Attack early, then expand when counts favor us."),
        ("DEFENSIVE APPROACH", running_insights[0] if running_insights else "Control steal counts with tempo and varied looks."),
        ("OFFENSIVE APPROACH", pitch_insights[2] if len(pitch_insights) > 2 else "Force their staff into the zone; target high-BB arms."),
        ("KEY MATCHUPS", f"Circle {hitters.iloc[0]['Player'] if hitters is not None and not hitters.empty else 'top OPS bat'} as primary threat."),
        ("BOTTOM LINE", "Win counts, control the running game, and execute the matchup plan."),
    ]
    yy = tx_y + box_h - 55
    for title, text in plan:
        c.setFillColor(RED); c.setFont("Helvetica-Bold", 8.5); c.drawString(410, yy, title)
        draw_wrapped(c, text, 410, yy - 12, 320, size=8.3, leading=10, max_lines=2)
        yy -= 34
    c.showPage()

    # Page 2
    draw_header(c, opponent, 2, logo_path)
    section_bar(c, PAGE_H - 122, "PITCHING SUMMARY")
    draw_pitch_usage_chart(c, 22, PAGE_H - 333, 375, 198, usage_count)
    draw_table(c, 415, PAGE_H - 333, 245, 198, "PITCH USAGE (OVERALL)", pitch_usage_rows(usage_overall, lg_usage), ["Pitch", "Usage", "LG", "Diff"], font_size=6.8, max_rows=7, highlight_diff=True)
    metric_card(c, 680, PAGE_H - 222, 105, 87, "TEAM BB%", pct(pitch_team.get("BB%", 0)), "", pct(bb_lg) if bb_lg is not None else None, pitch_team.get("BB%", 0) <= (bb_lg or 1), "BB%")
    k_lg = lg_pitch.get("K%")
    metric_card(c, 680, PAGE_H - 333, 105, 87, "TEAM K%", pct(pitch_team.get("K%", 0)), "", pct(k_lg) if k_lg is not None else None, pitch_team.get("K%", 0) >= (k_lg or 0), "K%")

    qualified_pitch = pitch_leaders[pitch_leaders["PA"] >= min_pitcher_pa] if pitch_leaders is not None and not pitch_leaders.empty else pd.DataFrame()
    hi_bb = qualified_pitch.sort_values("BB%", ascending=False).head(3) if not qualified_pitch.empty else pd.DataFrame()
    hi_k = qualified_pitch.sort_values("K%", ascending=False).head(3) if not qualified_pitch.empty else pd.DataFrame()
    bb_rows = [[r.Pitcher, int(r.PA), pct(r["BB%"]), pct(r["K%"]) ] for _, r in hi_bb.iterrows()]
    k_rows = [[r.Pitcher, int(r.PA), pct(r["K%"]), pct(r["BB%"]) ] for _, r in hi_k.iterrows()]
    mid_y = 155
    draw_table(c, 22, mid_y, 245, 112, f"HIGHEST BB% PITCHERS (MIN {min_pitcher_pa} PA)", bb_rows, ["Pitcher", "PA", "BB%", "K%"], max_rows=3)
    draw_table(c, 287, mid_y, 245, 112, f"HIGHEST K% PITCHERS (MIN {min_pitcher_pa} PA)", k_rows, ["Pitcher", "PA", "K%", "BB%"], max_rows=3)
    snap_rows = []
    if pitcher_usage is not None and not pitcher_usage.empty:
        cols = [c2 for c2 in ["CH", "CU", "FA", "FC", "FS", "SI", "SL"] if c2 in pitcher_usage.columns]
        for _, r in pitcher_usage.head(5).iterrows():
            snap_rows.append([r["Pitcher"], int(r["Pitches"])] + [f"{r[c2]:.0f}" for c2 in cols[:5]])
        draw_table(c, 552, mid_y, 233, 112, "PITCHER USAGE SNAPSHOT", snap_rows, ["Pitcher", "P"] + cols[:5], font_size=5.5, max_rows=5)
    draw_key_box(c, 22, 55, PAGE_W - 44, 78, "KEY INSIGHT", pitch_insights)
    c.showPage()

    # Page 3
    draw_header(c, opponent, 3, logo_path)
    section_bar(c, PAGE_H - 122, "HITTING SUMMARY")
    swing_lookup = dict(zip(swing_by_count["Count"], swing_by_count["SwingPct"])) if swing_by_count is not None and not swing_by_count.empty else {}
    draw_count_grid(c, 22, PAGE_H - 276, 340, 140, "SWING RATE BY COUNT", swing_lookup, is_pct=True)
    metric_card(c, 378, PAGE_H - 276, 120, 140, "HITTER SWING%", pct(hit_team.get("Swing%", 0)), "Overall", pct(lg_hit.get("Swing%")) if lg_hit.get("Swing%") is not None else None, True, "Swing Rate")
    draw_key_box(c, 514, PAGE_H - 276, 266, 140, "KEY INSIGHT", hitting_insights)

    qualified_hitters = hitters[hitters["PA"] >= min_pa] if hitters is not None and not hitters.empty else pd.DataFrame()
    top3 = qualified_hitters.sort_values("OPS", ascending=False).head(3) if not qualified_hitters.empty else pd.DataFrame()
    bot3 = qualified_hitters.sort_values("OPS", ascending=True).head(3) if not qualified_hitters.empty else pd.DataFrame()
    top_rows = [[r.Player, int(r.PA), num(r.AVG), num(r.OBP), num(r.SLG), num(r.OPS), pct(r["BB%"]), pct(r["K%"]) ] for _, r in top3.iterrows()]
    bot_rows = [[r.Player, int(r.PA), num(r.AVG), num(r.OBP), num(r.SLG), num(r.OPS), pct(r["BB%"]), pct(r["K%"]) ] for _, r in bot3.iterrows()]
    draw_table(c, 22, 265, 370, 115, f"TOP 3 HITTERS BY OPS (MIN {min_pa} PA)", top_rows, ["Player", "PA", "AVG", "OBP", "SLG", "OPS", "BB%", "K%"], font_size=5.8, max_rows=3)
    draw_table(c, 410, 265, 370, 115, f"BOTTOM 3 HITTERS BY OPS (MIN {min_pa} PA)", bot_rows, ["Player", "PA", "AVG", "OBP", "SLG", "OPS", "BB%", "K%"], font_size=5.8, max_rows=3)

    leader_specs = [("BEST AVG", "AVG", False), ("BEST OBP", "OBP", False), ("BEST SLG", "SLG", False), ("BEST OPS", "OPS", False), ("BEST BB%", "BB%", False), ("LOWEST K%", "K%", True)]
    box_w, box_h = 116, 74
    for i, (title, stat, asc) in enumerate(leader_specs):
        xx = 22 + (i % 6) * (box_w + 12)
        yy = 80
        df = qualified_hitters.sort_values(stat, ascending=asc).head(3) if not qualified_hitters.empty else pd.DataFrame()
        rows = [[r.Player, pct(r[stat]) if "%" in stat else num(r[stat]), int(r.PA)] for _, r in df.iterrows()]
        draw_table(c, xx, yy, box_w, box_h, f"{title}", rows, ["Player", stat, "PA"], font_size=5.3, max_rows=3)
    c.showPage()

    # Page 4
    draw_header(c, opponent, 4, logo_path)
    section_bar(c, PAGE_H - 122, "CATCHING & RUNNING GAME")
    metric_card(c, 22, PAGE_H - 215, 240, 82, "TEAM CS%", pct(catch_team.get("CS%", 0)), "Caught Stealing", None, True, "Catcher CS%")
    metric_card(c, 280, PAGE_H - 215, 240, 82, "TEAM SB SUCCESS %", pct(run_team.get("SB%", 0)), "Baserunning", None, True, "SB%")
    draw_key_box(c, 540, PAGE_H - 215, 240, 82, "KEY INSIGHT", running_insights[:3])
    run_lookup = {}
    if run_counts is not None and not run_counts.empty:
        rc = run_counts.copy(); rc["Count"] = rc["Count"].astype(str); rc["SBA"] = pd.to_numeric(rc["SBA"], errors="coerce").fillna(0)
        run_lookup = dict(zip(rc["Count"], rc["SBA"]))
    draw_count_grid(c, 22, PAGE_H - 380, 360, 145, "SBA BY COUNT (ATTEMPTS)", run_lookup, is_pct=False)
    c_rows = [[r.Catcher, int(r.SBA), int(r.CS), int(r.SB), pct(r["CS%"])] for _, r in catchers.head(5).iterrows()] if catchers is not None and not catchers.empty else []
    draw_table(c, 405, PAGE_H - 380, 375, 145, "CATCHER LEADERBOARD (BY CS%)", c_rows, ["Catcher", "SBA", "CS", "SB", "CS%"], font_size=6.2, max_rows=5)
    r_rows = [[r.Runner, int(r.SBA), int(r.SB), pct(r["SB%"])] for _, r in runners.head(7).iterrows()] if runners is not None and not runners.empty else []
    draw_table(c, 22, 80, 758, 135, "INDIVIDUAL RUNNER TENDENCIES (SB%)", r_rows, ["Runner", "SBA", "SB", "SB%"], font_size=6.5, max_rows=7)
    c.showPage(); c.save(); buffer.seek(0)
    return buffer.getvalue()

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("Advanced Pregame Report")
st.caption("Upload all opponent and league CSVs at once. The app auto-detects files by filename.")

with st.sidebar:
    st.header("Report Setup")
    opponent = st.text_input("Opponent name", value="Opponent")
    min_pa = st.number_input("Minimum Hitter PA", min_value=0, value=30, step=5)
    min_pitcher_pa = st.number_input("Minimum Pitcher PA Faced", min_value=0, value=20, step=5)
    uploaded_files = st.file_uploader("Upload all CSVs", type=["csv"], accept_multiple_files=True)
    st.caption("Expected: Pregame, Copy of Standard, Catching PreGame, Stolen Bases, SBA Count, Pregame Hitting, Rate, Pitch Usage")

files = detect_files(uploaded_files)
if uploaded_files:
    st.success(f"Uploaded {len(uploaded_files)} file(s). Detected: {', '.join(files.keys())}")
else:
    st.info("Upload your CSV files to generate the report.")
    st.stop()

pregame = read_csv_file(files["pregame"]) if "pregame" in files else pd.DataFrame()
standard = read_csv_file(files["standard"]) if "standard" in files else pd.DataFrame()
catching = read_csv_file(files["catching"]) if "catching" in files else pd.DataFrame()
stolen = read_csv_file(files["stolen_bases"]) if "stolen_bases" in files else pd.DataFrame()
sba_count = read_csv_file(files["sba_count"]) if "sba_count" in files else pd.DataFrame()
league_hitting = read_csv_file(files["league_hitting"]) if "league_hitting" in files else pd.DataFrame()
league_pitching = read_csv_file(files["league_pitching"]) if "league_pitching" in files else pd.DataFrame()
league_pitch_usage = read_csv_file(files["league_pitch_usage"]) if "league_pitch_usage" in files else pd.DataFrame()

hit_team, swing_by_count, hitter_swing, hitters = build_hitting(pregame)
pitch_team, usage_count, usage_overall, pitcher_usage, pitch_leaders = build_pitching(standard)
catch_team, catchers = build_catching(catching)
run_team, run_counts, runners = build_running(stolen, sba_count)
lg_hit = league_hitting_baseline(league_hitting)
lg_pitch = league_pitching_baseline(league_pitching)
lg_usage = league_pitch_usage_baseline(league_pitch_usage)

context = dict(
    opponent=opponent,
    logo_path=find_logo_path(),
    hit_team=hit_team,
    swing_by_count=swing_by_count,
    hitter_swing=hitter_swing,
    hitters=hitters,
    pitch_team=pitch_team,
    usage_count=usage_count,
    usage_overall=usage_overall,
    pitcher_usage=pitcher_usage,
    pitch_leaders=pitch_leaders,
    catch_team=catch_team,
    catchers=catchers,
    run_team=run_team,
    run_counts=run_counts,
    runners=runners,
    lg_hit=lg_hit,
    lg_pitch=lg_pitch,
    lg_usage=lg_usage,
    min_pa=min_pa,
    min_pitcher_pa=min_pitcher_pa,
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Team OPS", num(hit_team.get("OPS", 0)))
c2.metric("Opponent BB%", pct(pitch_team.get("BB%", 0)))
c3.metric("SB Success", pct(run_team.get("SB%", 0)))
c4.metric("Catcher CS%", pct(catch_team.get("CS%", 0)))

tabs = st.tabs(["Pitching", "Hitting", "Catching & Running", "PDF"])
with tabs[0]:
    st.subheader("Pitching Summary")
    st.write(f"Pitcher leaderboards filtered to minimum **{min_pitcher_pa} PA faced**.")
    st.dataframe(usage_overall, use_container_width=True)
    st.dataframe(pitcher_usage, use_container_width=True)
with tabs[1]:
    st.subheader("Hitting Summary")
    st.write(f"Hitter leaderboards filtered to minimum **{min_pa} PA**.")
    st.dataframe(swing_by_count, use_container_width=True)
    st.dataframe(hitters, use_container_width=True)
with tabs[2]:
    st.subheader("Catching & Running")
    st.dataframe(catchers, use_container_width=True)
    st.dataframe(runners, use_container_width=True)
with tabs[3]:
    st.subheader("Export PDF")
    pdf_bytes = build_visual_pdf(context)
    fname = f"{opponent.replace(' ', '_')}_advanced_pregame_report.pdf"
    st.download_button("Download Beautiful PDF", data=pdf_bytes, file_name=fname, mime="application/pdf", use_container_width=True)
