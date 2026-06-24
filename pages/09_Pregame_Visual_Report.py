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
# ADVANCED PREGAME REPORT - VISUAL PDF VERSION
# No SimpleDocTemplate. PDF is drawn with reportlab canvas.
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
PITCH_ORDER = ["FA", "FF", "SI", "FC", "SL", "CU", "CH", "FS", "SW", "KN"]
PITCH_COLORS = {
    "FA": HexColor("#D9233F"), "FF": HexColor("#D9233F"), "SI": HexColor("#F28E2B"),
    "FC": HexColor("#59A14F"), "SL": HexColor("#2878D7"), "CU": HexColor("#7B4ABF"),
    "CH": HexColor("#22A7F0"), "FS": HexColor("#00A5A5"), "SW": HexColor("#8B5CF6"),
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
    return f"{x*100:.{digits}f}%"

def num(x, digits=3):
    if x is None or pd.isna(x) or np.isinf(x):
        return "-"
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
        "FASTBALL": "FA", "FOURSEAM": "FA", "4SEAM": "FA", "4-SEAM": "FA", "FF": "FA",
        "SINKER": "SI", "TWOSEAM": "SI", "2SEAM": "SI", "2-SEAM": "SI",
        "CUTTER": "FC", "SLIDER": "SL", "CURVE": "CU", "CURVEBALL": "CU",
        "CHANGEUP": "CH", "CHANGE": "CH", "SPLITTER": "FS", "SPLIT": "FS", "SWEEPER": "SW"
    }
    return aliases.get(p, p)

def outcome_is_swing(x):
    s = str(x).strip().lower().replace(" ", "")
    take_terms = {"ball", "ballcall", "calledball", "strikecalled", "calledstrike", "automaticball", "automaticstrike"}
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
        if "pregame hitting" in name:
            out["league_hitting"] = f
        elif "rate" in name:
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

    # PA stats - prefer PA result columns when available; fallback to row ending logic if possible
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
        # Estimate PA from final pitch of each plate appearance: batter changes or known terminal outcomes.
        tmp = df.copy()
        tmp["Player"] = tmp[player_col].astype(str) if player_col else "Unknown"
        terminal = tmp[play_col].astype(str).str.lower() if play_col else pd.Series([""] * len(tmp))
        is_pa = terminal.str.contains("single|double|triple|home|walk|strikeout|out|sac|error|hitbypitch|hbp|fielderschoice", regex=True)
        if not is_pa.any():
            is_pa = tmp["Player"].ne(tmp["Player"].shift(-1))
        pa_rows = tmp[is_pa].copy()
        val = pa_rows[play_col].astype(str).str.lower() if play_col else pd.Series([""] * len(pa_rows))
        pa_rows["BB"] = val.str.contains("walk|bb", regex=True).astype(int)
        pa_rows["K"] = val.str.contains("strikeout|strikeswinging|strikecalled", regex=True).astype(int)
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
    g = g.sort_values("OPS", ascending=False)

    team = {
        "OPS": safe_div(g["H"].sum() + g["BB"].sum(), g["AB"].sum() + g["BB"].sum()) + safe_div(g["TB"].sum(), g["AB"].sum()),
        "AVG": safe_div(g["H"].sum(), g["AB"].sum()),
        "Swing%": df["Swing"].mean() if len(df) else 0,
    }
    return team, swing_by_count, hitter_swing, g

def build_pitching(standard):
    if standard is None or standard.empty:
        return {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
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

    # Estimate PA rows for BB/K leaders
    tmp = standard.copy()
    tmp["Pitcher"] = tmp[pitcher_col].astype(str) if pitcher_col else "Unknown"
    res = tmp[result_col].astype(str).str.lower() if result_col else pd.Series([""] * len(tmp))
    is_pa = res.str.contains("walk|bb|strikeout|single|double|triple|home|out|hbp|hitbypitch|sac|error", regex=True)
    if not is_pa.any():
        batter_col = find_col(tmp, ["batter", "batterFullName", "batterAbbrevName"])
        is_pa = tmp[batter_col].ne(tmp[batter_col].shift(-1)) if batter_col else pd.Series([False]*len(tmp))
    pa = tmp[is_pa].copy()
    res_pa = pa[result_col].astype(str).str.lower() if result_col else pd.Series([""] * len(pa))
    pa["BB"] = res_pa.str.contains("walk|bb", regex=True).astype(int)
    pa["K"] = res_pa.str.contains("strikeout|strikeswinging|strikecalled", regex=True).astype(int)
    leaders = pa.groupby("Pitcher").agg(PA=("Pitcher", "size"), BB=("BB", "sum"), K=("K", "sum")).reset_index()
    if leaders.empty and pitcher_col:
        leaders = df.groupby(pitcher_col).size().reset_index(name="Pitches").rename(columns={pitcher_col:"Pitcher"})
        leaders["PA"] = 0; leaders["BB"] = 0; leaders["K"] = 0
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
        # If outs increase on the next row, count as caught stealing.
        next_outs = df[outs_col].shift(-1)
        steal_rows["CS"] = (pd.to_numeric(next_outs.loc[steal_rows.index], errors="coerce") > pd.to_numeric(df.loc[steal_rows.index, outs_col], errors="coerce")).astype(int)
    else:
        cs_col = find_col(df, ["CS", "CaughtStealing"])
        steal_rows["CS"] = pd.to_numeric(steal_rows[cs_col], errors="coerce").fillna(0) if cs_col else 0
    steal_rows["SBA"] = 1
    g = steal_rows.groupby(catcher_col).agg(SBA=("SBA", "sum"), CS=("CS", "sum")).reset_index().rename(columns={catcher_col: "Catcher"})
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
                team_counts = df[[count_col, sba_col]].rename(columns={count_col:"Count", sba_col:"SBA"})
            else:
                team_counts = df.groupby(count_col).size().reset_index(name="SBA").rename(columns={count_col:"Count"})
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
            runners = runners[runners["Runner"].str.lower() != "playerfullname"].sort_values("SBA", ascending=False)
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
        "Swing%": pd.to_numeric(df[swing_col], errors="coerce").mean() if swing_col else None,
    }

def league_pitching_baseline(df):
    if df is None or df.empty:
        return {"BB%": None, "K%": None}
    bb_col = find_col(df, ["BB%", "BBPct", "Walk%"])
    k_col = find_col(df, ["K%", "KPct", "SO%"])
    def mean_pct(col):
        if not col:
            return None
        s = df[col].astype(str).str.replace("%", "", regex=False)
        v = pd.to_numeric(s, errors="coerce")
        if v.dropna().mean() and v.dropna().mean() > 1:
            v = v / 100
        return v.mean()
    return {"BB%": mean_pct(bb_col), "K%": mean_pct(k_col)}

# -----------------------------
# PDF drawing helpers
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
    c.setLineWidth(lw)
    c.setStrokeColor(stroke)
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, radius, stroke=1, fill=1)

def draw_header(c, title, opponent, page_num, logo_path="Rangers.png"):
    margin = 22
    if logo_path and os.path.exists(logo_path):
        try:
            c.drawImage(ImageReader(logo_path), margin, PAGE_H - 74, width=58, height=58, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass
    else:
        c.setFillColor(NAVY); c.circle(margin + 29, PAGE_H - 45, 28, fill=1); c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 28); c.drawCentredString(margin + 29, PAGE_H - 55, "T")
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 27)
    c.drawString(95, PAGE_H - 38, "ADVANCED PREGAME REPORT")
    c.setFillColor(RED)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(96, PAGE_H - 62, f"VS. {opponent.upper()}")
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(PAGE_W - 35, PAGE_H - 38, datetime.now().strftime("%b %d, %Y"))
    c.drawRightString(PAGE_W - 35, 25, f"PAGE {page_num}")
    c.setStrokeColor(RED); c.setLineWidth(2); c.line(22, PAGE_H - 82, PAGE_W - 22, PAGE_H - 82)

def section_bar(c, y, text):
    round_rect(c, 22, y, PAGE_W - 44, 28, fill=NAVY, stroke=NAVY, radius=5)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 15); c.drawString(35, y + 8, text)

def metric_card(c, x, y, w, h, title, value, subtitle="", lg=None, better=True, stat_label=None):
    round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=8)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 8.5); c.drawCentredString(x + w/2, y + h - 18, title)
    if stat_label:
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", 7.2); c.drawCentredString(x + w/2, y + h - 31, stat_label)
        val_y = y + h - 54
    else:
        val_y = y + h - 43
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 20); c.drawCentredString(x + w/2, val_y, value)
    if subtitle:
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", 7); c.drawCentredString(x + w/2, val_y - 14, subtitle)
    if lg is not None:
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", 7); c.drawCentredString(x + w/2, y + 25, f"LG AVG {lg}")
    bg = GREEN_BG if better else RED_BG
    col = GREEN if better else RED
    round_rect(c, x + 16, y + 6, w - 32, 16, fill=bg, stroke=bg, radius=4)
    c.setFillColor(col); c.setFont("Helvetica-Bold", 7.3); c.drawCentredString(x + w/2, y + 10, ("▲ BETTER" if better else "▼ BELOW AVG"))

def draw_table(c, x, y, w, h, title, rows, headers, font_size=6.4, max_rows=6):
    round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=7)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 8); c.drawCentredString(x + w/2, y + h - 15, title)
    rows = rows[:max_rows]
    top = y + h - 31
    row_h = min(16, (h - 38) / max(1, len(rows) + 1))
    c.setFillColor(GRAY); c.rect(x + 6, top - row_h, w - 12, row_h, stroke=0, fill=1)
    col_w = (w - 12) / len(headers)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", font_size)
    for i, head in enumerate(headers):
        c.drawCentredString(x + 6 + col_w*i + col_w/2, top - row_h + 5, str(head)[:14])
    c.setFont("Helvetica", font_size)
    for r, row in enumerate(rows):
        yy = top - row_h * (r + 2)
        if r % 2 == 1:
            c.setFillColor(HexColor("#FAFBFD")); c.rect(x + 6, yy, w - 12, row_h, stroke=0, fill=1)
        c.setFillColor(BLACK)
        for i, val in enumerate(row):
            text = str(val)
            max_chars = 18 if i == 0 else 8
            if len(text) > max_chars:
                text = text[:max_chars-1] + "…"
            c.drawCentredString(x + 6 + col_w*i + col_w/2, yy + 5, text)

def draw_key_box(c, x, y, w, h, title, text, icon="◎"):
    round_rect(c, x, y, w, h, fill=LIGHT_BLUE, stroke=BORDER, radius=8)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 23); c.drawCentredString(x + 36, y + h/2 - 8, icon)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 9); c.drawString(x + 72, y + h - 25, title)
    draw_wrapped(c, text, x + 72, y + h - 42, w - 84, font="Helvetica-Bold", size=8.2, leading=11, max_lines=4)

def draw_pitch_usage_chart(c, x, y, w, h, usage_count):
    round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=7)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 8); c.drawCentredString(x + w/2, y + h - 15, "PITCH USAGE BY COUNT")
    if usage_count is None or usage_count.empty:
        return
    data = usage_count.set_index("Count")
    pitches = [p for p in PITCH_ORDER if p in data.columns]
    if not pitches:
        pitches = [p for p in data.columns if p != "Count"][:7]
    chart_x = x + 42
    chart_y = y + 30
    chart_w = w - 70
    row_h = (h - 65) / len(COUNTS)
    for idx, cnt in enumerate(COUNTS):
        yy = chart_y + (len(COUNTS)-1-idx) * row_h
        c.setFillColor(DARK); c.setFont("Helvetica", 6.6); c.drawRightString(chart_x - 8, yy + 2, cnt)
        c.setFillColor(HexColor("#EDF2F7")); c.rect(chart_x, yy, chart_w, 6, stroke=0, fill=1)
        if cnt in data.index:
            start = chart_x
            for p in pitches:
                val = float(data.loc[cnt, p]) if p in data.columns and pd.notna(data.loc[cnt, p]) else 0
                seg_w = chart_w * val
                if seg_w > 0.3:
                    c.setFillColor(PITCH_COLORS.get(p, PITCH_COLORS["OTHER"]))
                    c.rect(start, yy, seg_w, 6, stroke=0, fill=1)
                start += seg_w
    # compact legend, no overflow
    lx = chart_x
    ly = y + 13
    for p in pitches[:8]:
        c.setFillColor(PITCH_COLORS.get(p, PITCH_COLORS["OTHER"])); c.circle(lx, ly + 2, 3, fill=1, stroke=0)
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", 6.2); c.drawString(lx + 6, ly, p)
        lx += 39
        if lx > x + w - 34:
            break

def draw_swing_grid(c, x, y, w, h, swing_by_count):
    round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=7)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 8); c.drawCentredString(x + w/2, y + h - 15, "SWING RATE BY COUNT")
    lookup = {}
    if swing_by_count is not None and not swing_by_count.empty:
        lookup = dict(zip(swing_by_count["Count"], swing_by_count["SwingPct"]))
    cols, rows = 4, 3
    cell_w = (w - 24) / cols
    cell_h = (h - 40) / rows
    for i, cnt in enumerate(COUNTS):
        col, row = i % cols, i // cols
        cx = x + 12 + col * cell_w
        cy = y + h - 34 - (row + 1) * cell_h
        round_rect(c, cx, cy, cell_w - 6, cell_h - 5, fill=GRAY, stroke=HexColor("#E2E8F0"), radius=4)
        c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 7); c.drawCentredString(cx + (cell_w-6)/2, cy + cell_h - 18, cnt)
        c.setFont("Helvetica-Bold", 10); c.drawCentredString(cx + (cell_w-6)/2, cy + 8, pct(lookup.get(cnt, 0)))

def draw_sba_grid(c, x, y, w, h, team_counts):
    round_rect(c, x, y, w, h, fill=WHITE, stroke=BORDER, radius=7)
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 8); c.drawCentredString(x + w/2, y + h - 15, "SBA BY COUNT (ATTEMPTS)")
    lookup = {}
    if team_counts is not None and not team_counts.empty:
        team_counts["Count"] = team_counts["Count"].astype(str)
        lookup = dict(zip(team_counts["Count"], pd.to_numeric(team_counts["SBA"], errors="coerce").fillna(0)))
    cols, rows = 4, 3
    cell_w = (w - 24) / cols
    cell_h = (h - 40) / rows
    for i, cnt in enumerate(COUNTS):
        col, row = i % cols, i // cols
        cx = x + 12 + col * cell_w
        cy = y + h - 34 - (row + 1) * cell_h
        round_rect(c, cx, cy, cell_w - 6, cell_h - 5, fill=GRAY, stroke=HexColor("#E2E8F0"), radius=4)
        c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 7); c.drawCentredString(cx + (cell_w-6)/2, cy + cell_h - 18, cnt)
        c.setFont("Helvetica-Bold", 12); c.drawCentredString(cx + (cell_w-6)/2, cy + 8, str(int(lookup.get(cnt, 0))))

def concise(text, max_words=11):
    words = str(text).split()
    return " ".join(words[:max_words]) + ("." if len(words) > max_words else "")

def build_insights(pitch_team, usage_overall, swing_by_count, run_counts, hitters):
    insights = []
    if usage_overall is not None and not usage_overall.empty:
        top = usage_overall.iloc[0]
        insights.append(f"High {top['Pitch']} usage ({pct(top['Usage'])}); be ready in leverage counts.")
    if swing_by_count is not None and not swing_by_count.empty:
        top = swing_by_count.sort_values("SwingPct", ascending=False).iloc[0]
        insights.append(f"Most aggressive in {top['Count']} counts ({pct(top['SwingPct'])}).")
    if run_counts is not None and not run_counts.empty:
        rc = run_counts.copy(); rc["SBA"] = pd.to_numeric(rc["SBA"], errors="coerce").fillna(0)
        top = rc.sort_values("SBA", ascending=False).iloc[0]
        insights.append(f"Running game peaks in {top['Count']} counts ({int(top['SBA'])} SBA).")
    if hitters is not None and not hitters.empty:
        top = hitters.sort_values("OPS", ascending=False).iloc[0]
        insights.append(f"Circle {top['Player']} as top OPS threat ({num(top['OPS'])}).")
    return [concise(i, 12) for i in insights[:3]]

def build_visual_pdf(context):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(letter))
    opponent = context.get("opponent", "Opponent")
    logo_path = context.get("logo_path", "Rangers.png")
    hit_team = context["hit_team"]; pitch_team = context["pitch_team"]; catch_team = context["catch_team"]; run_team = context["run_team"]
    lg_hit = context["lg_hit"]; lg_pitch = context["lg_pitch"]
    usage_count = context["usage_count"]; usage_overall = context["usage_overall"]; pitcher_usage = context["pitcher_usage"]; pitch_leaders = context["pitch_leaders"]
    swing_by_count = context["swing_by_count"]; hitters = context["hitters"]
    catchers = context["catchers"]; run_counts = context["run_counts"]; runners = context["runners"]
    insights = build_insights(pitch_team, usage_overall, swing_by_count, run_counts, hitters)

    # PAGE 1
    draw_header(c, "ADVANCED PREGAME REPORT", opponent, 1, logo_path)
    section_bar(c, PAGE_H - 122, "EXECUTIVE SUMMARY")
    y = PAGE_H - 218
    card_w = 180; gap = 10; x0 = 22
    hit_lg = lg_hit.get("OPS")
    metric_card(c, x0, y, card_w, 82, "TEAM HITTING", num(hit_team.get("OPS", 0)), "OPS", num(hit_lg) if hit_lg is not None else None, hit_team.get("OPS",0) >= (hit_lg or 0), "Team OPS")
    bb_lg = lg_pitch.get("BB%")
    metric_card(c, x0 + (card_w+gap), y, card_w, 82, "TEAM PITCHING", pct(pitch_team.get("BB%", 0)), "BB% Allowed", pct(bb_lg) if bb_lg is not None else None, pitch_team.get("BB%",0) <= (bb_lg or 1), "Opponent BB%")
    metric_card(c, x0 + 2*(card_w+gap), y, card_w, 82, "TEAM BASERUNNING", pct(run_team.get("SB%",0)), "SB Success", None, True, "SB%")
    metric_card(c, x0 + 3*(card_w+gap), y, card_w, 82, "TEAM CATCHING", pct(catch_team.get("CS%",0)), "Caught Stealing", None, True, "CS%")

    # Takeaways and Game plan, balanced with fixed line limits
    tx_y = 75; box_h = 220
    round_rect(c, 22, tx_y, 345, box_h, fill=WHITE, stroke=BORDER, radius=8)
    round_rect(c, 22, tx_y + box_h - 28, 345, 28, fill=NAVY, stroke=NAVY, radius=8)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 13); c.drawCentredString(194, tx_y + box_h - 19, "KEY TAKEAWAYS")
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 28); c.drawString(45, tx_y + 124, "▣")
    yy = tx_y + box_h - 65
    for item in insights:
        c.setFillColor(RED); c.circle(70, yy + 4, 2.2, fill=1, stroke=0)
        yy = draw_wrapped(c, item, 86, yy + 8, 240, font="Helvetica-Bold", size=9, leading=13, max_lines=2) - 16

    round_rect(c, 382, tx_y, PAGE_W - 404, box_h, fill=WHITE, stroke=BORDER, radius=8)
    round_rect(c, 382, tx_y + box_h - 28, PAGE_W - 404, 28, fill=NAVY, stroke=NAVY, radius=8)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 13); c.drawCentredString(585, tx_y + box_h - 19, "GAME PLAN")
    plan = [
        ("PITCHING APPROACH", "Attack early, then expand when counts favor us."),
        ("DEFENSIVE APPROACH", "Control steal counts with tempo, holds, and quick exchanges."),
        ("OFFENSIVE APPROACH", "Force their staff into the zone; target high-BB arms."),
        ("KEY MATCHUPS", f"Circle {hitters.iloc[0]['Player'] if not hitters.empty else 'top OPS bat'} as primary threat."),
        ("BOTTOM LINE", "Win counts, control the running game, execute the plan."),
    ]
    yy = tx_y + box_h - 55
    for title, text in plan:
        c.setFillColor(RED); c.setFont("Helvetica-Bold", 8.5); c.drawString(410, yy, title)
        draw_wrapped(c, text, 410, yy - 12, 320, size=8.5, leading=10, max_lines=2)
        yy -= 34
    c.showPage()

    # PAGE 2 Pitching
    draw_header(c, "ADVANCED PREGAME REPORT", opponent, 2, logo_path)
    section_bar(c, PAGE_H - 122, "PITCHING PLAN")
    metric_card(c, 525, PAGE_H - 205, 120, 74, "TEAM BB%", pct(pitch_team.get("BB%",0)), "Walk Rate", pct(bb_lg) if bb_lg is not None else None, pitch_team.get("BB%",0) <= (bb_lg or 1), "BB%")
    k_lg = lg_pitch.get("K%")
    metric_card(c, 660, PAGE_H - 205, 120, 74, "TEAM K%", pct(pitch_team.get("K%",0)), "Strikeout Rate", pct(k_lg) if k_lg is not None else None, pitch_team.get("K%",0) >= (k_lg or 0), "K%")
    draw_pitch_usage_chart(c, 22, PAGE_H - 355, 355, 220, usage_count)

    rows = []
    if usage_overall is not None and not usage_overall.empty:
        for _, r in usage_overall.head(7).iterrows():
            rows.append([r["Pitch"], pct(r["Usage"]), "-", "-"])
    draw_table(c, 390, PAGE_H - 355, 245, 220, "PITCH USAGE (OVERALL)", rows, ["Pitch", "Usage", "LG", "Diff"], font_size=6.8, max_rows=7)
    top_pitch = usage_overall.iloc[0] if usage_overall is not None and not usage_overall.empty else None
    key = f"Highest pitch usage is {top_pitch['Pitch']} ({pct(top_pitch['Usage'])}). Prepare for it in leverage counts." if top_pitch is not None else "Identify primary pitch patterns by count."
    draw_key_box(c, 650, PAGE_H - 355, 130, 110, "KEY INSIGHT", key, icon="◎")

    hi_bb = pitch_leaders[pitch_leaders["PA"] > 0].sort_values("BB%", ascending=False).head(3) if pitch_leaders is not None and not pitch_leaders.empty else pd.DataFrame()
    hi_k = pitch_leaders[pitch_leaders["PA"] > 0].sort_values("K%", ascending=False).head(3) if pitch_leaders is not None and not pitch_leaders.empty else pd.DataFrame()
    bb_rows = [[r.Pitcher, int(r.PA), pct(r["BB%"]), pct(r["K%"]) ] for _, r in hi_bb.iterrows()]
    k_rows = [[r.Pitcher, int(r.PA), pct(r["K%"]), pct(r["BB%"]) ] for _, r in hi_k.iterrows()]
    draw_table(c, 22, 78, 235, 130, "HIGHEST BB% PITCHERS", bb_rows, ["Pitcher", "PA", "BB%", "K%"], max_rows=3)
    draw_table(c, 275, 78, 235, 130, "HIGHEST K% PITCHERS", k_rows, ["Pitcher", "PA", "K%", "BB%"], max_rows=3)
    snap_rows = []
    if pitcher_usage is not None and not pitcher_usage.empty:
        cols = [c for c in ["CH", "CU", "FA", "FC", "FS", "SI", "SL"] if c in pitcher_usage.columns]
        for _, r in pitcher_usage.head(5).iterrows():
            snap_rows.append([r["Pitcher"], int(r["Pitches"])] + [f"{r[c]:.0f}" for c in cols[:5]])
        draw_table(c, 528, 78, 252, 130, "PITCHER USAGE SNAPSHOT", snap_rows, ["Pitcher", "P"] + cols[:5], font_size=5.8, max_rows=5)
    c.showPage()

    # PAGE 3 Hitting
    draw_header(c, "ADVANCED PREGAME REPORT", opponent, 3, logo_path)
    section_bar(c, PAGE_H - 122, "HITTING PLAN")
    draw_swing_grid(c, 22, PAGE_H - 276, 340, 140, swing_by_count)
    metric_card(c, 378, PAGE_H - 276, 120, 140, "HITTER SWING%", pct(hit_team.get("Swing%",0)), "Overall", pct(lg_hit.get("Swing%")) if lg_hit.get("Swing%") is not None else None, True, "Swing Rate")
    sw_top = swing_by_count.sort_values("SwingPct", ascending=False).iloc[0] if swing_by_count is not None and not swing_by_count.empty else None
    key = f"They swing most in {sw_top['Count']} counts ({pct(sw_top['SwingPct'])}). Use that count to expand." if sw_top is not None else "Use swing/take tendencies to shape attack zones."
    draw_key_box(c, 514, PAGE_H - 276, 266, 140, "KEY INSIGHT", key, icon="◎")

    top3 = hitters.sort_values("OPS", ascending=False).head(3) if hitters is not None and not hitters.empty else pd.DataFrame()
    bot3 = hitters[hitters["PA"] > 0].sort_values("OPS", ascending=True).head(3) if hitters is not None and not hitters.empty else pd.DataFrame()
    top_rows = [[r.Player, int(r.PA), num(r.AVG), num(r.OBP), num(r.SLG), num(r.OPS), pct(r["BB%"]), pct(r["K%"]) ] for _, r in top3.iterrows()]
    bot_rows = [[r.Player, int(r.PA), num(r.AVG), num(r.OBP), num(r.SLG), num(r.OPS), pct(r["BB%"]), pct(r["K%"]) ] for _, r in bot3.iterrows()]
    draw_table(c, 22, 265, 370, 115, "TOP 3 HITTERS (BY OPS)", top_rows, ["Player", "PA", "AVG", "OBP", "SLG", "OPS", "BB%", "K%"], font_size=5.8, max_rows=3)
    draw_table(c, 410, 265, 370, 115, "BOTTOM 3 HITTERS (BY OPS)", bot_rows, ["Player", "PA", "AVG", "OBP", "SLG", "OPS", "BB%", "K%"], font_size=5.8, max_rows=3)

    leader_specs = [("BEST AVG", "AVG", False), ("BEST OBP", "OBP", False), ("BEST SLG", "SLG", False), ("BEST OPS", "OPS", False), ("BEST BB%", "BB%", False), ("LOWEST K%", "K%", True)]
    start_x, start_y = 22, 80
    box_w, box_h = 120, 76
    for i, (title, stat, asc) in enumerate(leader_specs):
        xx = start_x + (i % 6) * (box_w + 12)
        yy = start_y
        df = hitters[hitters["PA"] > 0].sort_values(stat, ascending=asc).head(3) if hitters is not None and not hitters.empty else pd.DataFrame()
        rows = [[r.Player, pct(r[stat]) if "%" in stat else num(r[stat]), int(r.PA)] for _, r in df.iterrows()]
        draw_table(c, xx, yy, box_w, box_h, title, rows, ["Player", stat, "PA"], font_size=5.6, max_rows=3)
    c.showPage()

    # PAGE 4 Catching & Running
    draw_header(c, "ADVANCED PREGAME REPORT", opponent, 4, logo_path)
    section_bar(c, PAGE_H - 122, "CATCHING & RUNNING GAME")
    metric_card(c, 22, PAGE_H - 215, 240, 82, "TEAM CS%", pct(catch_team.get("CS%",0)), "Caught Stealing", None, True, "Catcher CS%")
    metric_card(c, 280, PAGE_H - 215, 240, 82, "TEAM SB SUCCESS %", pct(run_team.get("SB%",0)), "Baserunning", None, True, "SB%")
    draw_key_box(c, 540, PAGE_H - 215, 240, 82, "KEY INSIGHT", insights[2] if len(insights) > 2 else "Control tempo and prevent free 90s.", icon="◎")
    draw_sba_grid(c, 22, PAGE_H - 380, 360, 145, run_counts)
    c_rows = [[r.Catcher, int(r.SBA), int(r.CS), int(r.SB), pct(r["CS%"])] for _, r in catchers.head(5).iterrows()] if catchers is not None and not catchers.empty else []
    draw_table(c, 405, PAGE_H - 380, 375, 145, "CATCHER LEADERBOARD (BY CS%)", c_rows, ["Catcher", "SBA", "CS", "SB", "CS%"], font_size=6.2, max_rows=5)
    r_rows = [[r.Runner, int(r.SBA), int(r.SB), pct(r["SB%"])] for _, r in runners.head(7).iterrows()] if runners is not None and not runners.empty else []
    draw_table(c, 22, 80, 758, 135, "INDIVIDUAL RUNNER TENDENCIES (SB%)", r_rows, ["Runner", "SBA", "SB", "SB%"], font_size=6.5, max_rows=7)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("Advanced Pregame Report")
st.caption("Upload all opponent and league CSVs at once. The app auto-detects files by filename.")

with st.sidebar:
    st.header("Report Setup")
    opponent = st.text_input("Opponent name", value="Opponent")
    uploaded_files = st.file_uploader("Upload all CSVs", type=["csv"], accept_multiple_files=True)
    st.caption("Expected: Pregame, Copy of Standard, Catching PreGame, Stolen Bases, SBA Count, Pregame Hitting, Rate")

files = detect_files(uploaded_files)
if uploaded_files:
    st.success(f"Uploaded {len(uploaded_files)} file(s). Detected: {', '.join(files.keys())}")
else:
    st.info("Upload your CSV files to generate the report.")
    st.stop()

# Read files
pregame = read_csv_file(files["pregame"]) if "pregame" in files else pd.DataFrame()
standard = read_csv_file(files["standard"]) if "standard" in files else pd.DataFrame()
catching = read_csv_file(files["catching"]) if "catching" in files else pd.DataFrame()
stolen = read_csv_file(files["stolen_bases"]) if "stolen_bases" in files else pd.DataFrame()
sba_count = read_csv_file(files["sba_count"]) if "sba_count" in files else pd.DataFrame()
league_hitting = read_csv_file(files["league_hitting"]) if "league_hitting" in files else pd.DataFrame()
league_pitching = read_csv_file(files["league_pitching"]) if "league_pitching" in files else pd.DataFrame()

hit_team, swing_by_count, hitter_swing, hitters = build_hitting(pregame)
pitch_team, usage_count, usage_overall, pitcher_usage, pitch_leaders = build_pitching(standard)
catch_team, catchers = build_catching(catching)
run_team, run_counts, runners = build_running(stolen, sba_count)
lg_hit = league_hitting_baseline(league_hitting)
lg_pitch = league_pitching_baseline(league_pitching)

logo_path = "Rangers.png"
context = dict(
    opponent=opponent,
    logo_path=logo_path,
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
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Team OPS", num(hit_team.get("OPS", 0)))
c2.metric("Opponent BB%", pct(pitch_team.get("BB%", 0)))
c3.metric("SB Success", pct(run_team.get("SB%", 0)))
c4.metric("Catcher CS%", pct(catch_team.get("CS%", 0)))

tabs = st.tabs(["Pitching", "Hitting", "Catching & Running", "PDF"])
with tabs[0]:
    st.subheader("Pitching")
    st.dataframe(usage_overall, use_container_width=True)
    st.dataframe(pitcher_usage, use_container_width=True)
with tabs[1]:
    st.subheader("Hitting")
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
    st.download_button(
        "Download Beautiful PDF",
        data=pdf_bytes,
        file_name=fname,
        mime="application/pdf",
        use_container_width=True,
    )
