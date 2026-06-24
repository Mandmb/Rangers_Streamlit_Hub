
import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, KeepTogether
    )
except Exception:
    colors = None


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Advanced Pregame Report",
    page_icon="⚾",
    layout="wide",
)

st.title("⚾ Advanced Pregame Report")
st.caption("Upload opponent CSVs + league average CSVs to build a game plan report.")


# ============================================================
# HELPERS
# ============================================================

COUNT_ORDER = [
    "0-0", "0-1", "0-2",
    "1-0", "1-1", "1-2",
    "2-0", "2-1", "2-2",
    "3-0", "3-1", "3-2",
]

TAKE_CALLS = {
    "ballcalled", "ball", "calledball",
    "strikecalled", "calledstrike",
    "automaticball", "automaticstrike",
}

SWING_CALL_KEYWORDS = [
    "inplay", "foul", "swing", "hit", "bunt",
]


def clean_col(c):
    return str(c).strip()


def normalize_col(c):
    return re.sub(r"[^a-z0-9]", "", str(c).lower())


def find_col(df, candidates):
    if df is None or df.empty:
        return None
    norm_map = {normalize_col(c): c for c in df.columns}
    for cand in candidates:
        key = normalize_col(cand)
        if key in norm_map:
            return norm_map[key]
    for c in df.columns:
        nc = normalize_col(c)
        for cand in candidates:
            if normalize_col(cand) in nc:
                return c
    return None


def read_csv_any(file):
    if file is None:
        return None
    try:
        return pd.read_csv(file)
    except UnicodeDecodeError:
        return pd.read_csv(file, encoding="latin-1")
    except Exception:
        return pd.read_csv(file, engine="python")


def pct(num, den):
    try:
        den = float(den)
        if den == 0:
            return 0.0
        return float(num) / den
    except Exception:
        return 0.0


def fmt_pct(x, decimals=1):
    if pd.isna(x):
        return "-"
    return f"{float(x) * 100:.{decimals}f}%"


def fmt_avg(x):
    if pd.isna(x):
        return "-"
    return f"{float(x):.3f}".replace("0.", ".")


def fmt_num(x):
    if pd.isna(x):
        return "-"
    try:
        return f"{int(x)}"
    except Exception:
        return str(x)


def get_count_series(df):
    count_col = find_col(df, ["Count", "Pitch Count", "count"])
    if count_col:
        return df[count_col].astype(str).str.strip()

    balls_col = find_col(df, ["Balls", "Ball"])
    strikes_col = find_col(df, ["Strikes", "Strike"])
    if balls_col and strikes_col:
        return (
            pd.to_numeric(df[balls_col], errors="coerce").fillna(0).astype(int).astype(str)
            + "-"
            + pd.to_numeric(df[strikes_col], errors="coerce").fillna(0).astype(int).astype(str)
        )

    # TrackMan-style R/S fallback
    r_col = find_col(df, ["R"])
    s_col = find_col(df, ["S"])
    if r_col and s_col:
        return (
            pd.to_numeric(df[r_col], errors="coerce").fillna(0).astype(int).astype(str)
            + "-"
            + pd.to_numeric(df[s_col], errors="coerce").fillna(0).astype(int).astype(str)
        )

    return pd.Series(["Unknown"] * len(df), index=df.index)


def is_swing_value(x):
    val = str(x).strip().lower().replace(" ", "")
    if val in TAKE_CALLS:
        return False
    return any(k in val for k in SWING_CALL_KEYWORDS) or val not in TAKE_CALLS


def style_table_vs_avg(df, stat_cols, avg_map=None, lower_is_better=None):
    lower_is_better = lower_is_better or set()
    avg_map = avg_map or {}

    def apply(row):
        styles = []
        for col in df.columns:
            if col in stat_cols and col in avg_map and pd.notna(row[col]):
                try:
                    player_val = float(row[col])
                    avg_val = float(avg_map[col])
                    good = player_val >= avg_val
                    if col in lower_is_better:
                        good = player_val <= avg_val
                    styles.append(
                        "background-color: #d8f3dc; color: #000;"
                        if good else
                        "background-color: #f8d7da; color: #000;"
                    )
                except Exception:
                    styles.append("")
            else:
                styles.append("")
        return styles

    return df.style.apply(apply, axis=1)


def detect_files(uploaded_files):
    detected = {
        "pregame": None,
        "standard": None,
        "catching": None,
        "stolen_bases": None,
        "sba_count": None,
        "league_hitting": None,
        "league_pitching": None,
    }

    for f in uploaded_files:
        name = f.name.lower()

        if "pregame hitting" in name:
            detected["league_hitting"] = f
        elif "rate" in name:
            detected["league_pitching"] = f
        elif "catching" in name:
            detected["catching"] = f
        elif "sba count" in name:
            detected["sba_count"] = f
        elif "stolen" in name and "base" in name:
            detected["stolen_bases"] = f
        elif "standard" in name:
            detected["standard"] = f
        elif "pregame" in name:
            detected["pregame"] = f

    return detected


# ============================================================
# BASEBALL CALCULATIONS
# ============================================================

def add_pa_id(df, batter_col):
    out = df.copy()
    if batter_col is None:
        out["_pa_id"] = range(len(out))
        return out

    game_col = find_col(out, ["GameID", "GameUID", "game_id", "Date"])
    inning_col = find_col(out, ["Inning", "InningNo"])
    top_col = find_col(out, ["Top/Bottom", "TopBottom", "Home/Away"])
    pa_col = find_col(out, ["PA", "PAofInning", "PlateAppearanceID", "PitcherBatterSequence"])

    if pa_col:
        out["_pa_id"] = out[pa_col].astype(str)
        return out

    keys = []
    if game_col:
        keys.append(out[game_col].astype(str))
    if inning_col:
        keys.append(out[inning_col].astype(str))
    if top_col:
        keys.append(out[top_col].astype(str))

    batter_change = out[batter_col].astype(str).ne(out[batter_col].astype(str).shift()).cumsum().astype(str)
    if keys:
        out["_pa_id"] = pd.concat(keys + [batter_change], axis=1).agg("_".join, axis=1)
    else:
        out["_pa_id"] = batter_change
    return out


def calculate_batting_stats(df, player_col=None):
    if df is None or df.empty:
        return pd.DataFrame()

    batter_col = player_col or find_col(df, ["Batter", "batter", "batterAbbrevName", "batterFullName", "playerFullName"])
    result_col = find_col(df, ["PlayResult", "playResult", "Result", "KorBB", "PitchCall", "pitchResult", "PitchResult"])
    pitch_call_col = find_col(df, ["PitchCall", "pitchResult", "PitchResult"])
    pa_df = add_pa_id(df, batter_col)

    rows = []
    group_cols = [batter_col] if batter_col else [None]
    grouped = pa_df.groupby(batter_col, dropna=False) if batter_col else [("Team", pa_df)]

    for name, g in grouped:
        pa_rows = g.groupby("_pa_id").tail(1)
        pa = len(pa_rows)

        vals = pd.Series([""] * len(pa_rows), index=pa_rows.index)
        if result_col:
            vals = pa_rows[result_col].astype(str).str.lower()
        calls = pd.Series([""] * len(pa_rows), index=pa_rows.index)
        if pitch_call_col:
            calls = pa_rows[pitch_call_col].astype(str).str.lower()

        singles = vals.str.contains("single|1b", regex=True, na=False).sum()
        doubles = vals.str.contains("double|2b", regex=True, na=False).sum()
        triples = vals.str.contains("triple|3b", regex=True, na=False).sum()
        hrs = vals.str.contains("home|homerun|hr", regex=True, na=False).sum()
        hits = singles + doubles + triples + hrs

        bb = vals.str.contains("walk|bb", regex=True, na=False).sum()
        if bb == 0:
            bb = calls.str.contains("walk|bb", regex=True, na=False).sum()

        hbp = vals.str.contains("hitbypitch|hbp", regex=True, na=False).sum()
        k = vals.str.contains("strikeout|k", regex=True, na=False).sum()
        if k == 0:
            k = calls.str.contains("strikeout|strikeswinging|strikecalled", regex=True, na=False).sum()

        sac = vals.str.contains("sacrifice|sac", regex=True, na=False).sum()

        ab = max(pa - bb - hbp - sac, 0)
        tb = singles + 2 * doubles + 3 * triples + 4 * hrs

        rows.append({
            "Player": name,
            "PA": pa,
            "AB": ab,
            "H": hits,
            "BB": bb,
            "K": k,
            "AVG": pct(hits, ab),
            "OBP": pct(hits + bb + hbp, ab + bb + hbp + sac),
            "SLG": pct(tb, ab),
            "OPS": pct(hits + bb + hbp, ab + bb + hbp + sac) + pct(tb, ab),
            "BB%": pct(bb, pa),
            "K%": pct(k, pa),
        })

    return pd.DataFrame(rows).sort_values("PA", ascending=False)


def calculate_pitcher_stats(df):
    if df is None or df.empty:
        return pd.DataFrame()

    pitcher_col = find_col(df, ["Pitcher", "pitcher", "pitcherAbbrevName", "pitcherFullName", "playerFullName"])
    result_col = find_col(df, ["PlayResult", "playResult", "Result", "KorBB", "PitchCall", "pitchResult", "PitchResult"])
    pitch_call_col = find_col(df, ["PitchCall", "pitchResult", "PitchResult"])

    pa_df = add_pa_id(df, find_col(df, ["Batter", "batter", "batterAbbrevName", "batterFullName"]))
    rows = []
    grouped = pa_df.groupby(pitcher_col, dropna=False) if pitcher_col else [("Team", pa_df)]

    for name, g in grouped:
        pa_rows = g.groupby("_pa_id").tail(1)
        pa = len(pa_rows)

        vals = pd.Series([""] * len(pa_rows), index=pa_rows.index)
        if result_col:
            vals = pa_rows[result_col].astype(str).str.lower()
        calls = pd.Series([""] * len(pa_rows), index=pa_rows.index)
        if pitch_call_col:
            calls = pa_rows[pitch_call_col].astype(str).str.lower()

        bb = vals.str.contains("walk|bb", regex=True, na=False).sum()
        if bb == 0:
            bb = calls.str.contains("walk|bb", regex=True, na=False).sum()

        k = vals.str.contains("strikeout|k", regex=True, na=False).sum()
        if k == 0:
            k = calls.str.contains("strikeout", regex=True, na=False).sum()

        rows.append({
            "Pitcher": name,
            "PA": pa,
            "BB": bb,
            "K": k,
            "BB%": pct(bb, pa),
            "K%": pct(k, pa),
        })

    return pd.DataFrame(rows).sort_values("PA", ascending=False)


def pitch_usage_by_count(df):
    if df is None or df.empty:
        return pd.DataFrame()

    pitch_col = find_col(df, ["PitchType", "TaggedPitchType", "AutoPitchType", "pitchType"])
    if pitch_col is None:
        return pd.DataFrame()

    work = df.copy()
    work["_Count"] = get_count_series(work)
    work["_PitchType"] = work[pitch_col].astype(str).str.strip()
    work = work[~work["_PitchType"].str.upper().eq("UN")]

    pivot = pd.crosstab(work["_Count"], work["_PitchType"], normalize="index")
    pivot = pivot.reindex([c for c in COUNT_ORDER if c in pivot.index])
    return pivot.reset_index().rename(columns={"_Count": "Count"})


def pitcher_pitch_usage(df):
    if df is None or df.empty:
        return pd.DataFrame()

    pitcher_col = find_col(df, ["Pitcher", "pitcher", "pitcherAbbrevName", "pitcherFullName", "playerFullName"])
    pitch_col = find_col(df, ["PitchType", "TaggedPitchType", "AutoPitchType", "pitchType"])
    if pitcher_col is None or pitch_col is None:
        return pd.DataFrame()

    work = df.copy()
    work["_PitchType"] = work[pitch_col].astype(str).str.strip()
    work = work[~work["_PitchType"].str.upper().eq("UN")]

    pivot = pd.crosstab(work[pitcher_col], work["_PitchType"], normalize="index")
    counts = work.groupby(pitcher_col).size().rename("Pitches")
    out = pivot.join(counts).reset_index().rename(columns={pitcher_col: "Pitcher"})
    cols = ["Pitcher", "Pitches"] + [c for c in out.columns if c not in ["Pitcher", "Pitches"]]
    return out[cols].sort_values("Pitches", ascending=False)


def swing_take_by_count(df):
    if df is None or df.empty:
        return pd.DataFrame()

    call_col = find_col(df, ["PitchCall", "pitchResult", "PitchResult", "pitchCall"])
    if call_col is None:
        return pd.DataFrame()

    work = df.copy()
    work["_Count"] = get_count_series(work)
    work["_Swing"] = work[call_col].apply(is_swing_value)

    rows = []
    for count, g in work.groupby("_Count"):
        total = len(g)
        swings = int(g["_Swing"].sum())
        takes = total - swings
        rows.append({
            "Count": count,
            "Pitches": total,
            "Swing%": pct(swings, total),
            "Take%": pct(takes, total),
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_order"] = out["Count"].apply(lambda x: COUNT_ORDER.index(x) if x in COUNT_ORDER else 99)
    return out.sort_values("_order").drop(columns="_order")


def hitter_swing_by_count(df):
    if df is None or df.empty:
        return pd.DataFrame()

    hitter_col = find_col(df, ["Batter", "batter", "batterAbbrevName", "batterFullName", "playerFullName"])
    call_col = find_col(df, ["PitchCall", "pitchResult", "PitchResult", "pitchCall"])
    if hitter_col is None or call_col is None:
        return pd.DataFrame()

    work = df.copy()
    work["_Count"] = get_count_series(work)
    work["_Swing"] = work[call_col].apply(is_swing_value)

    pivot = pd.pivot_table(
        work,
        values="_Swing",
        index=hitter_col,
        columns="_Count",
        aggfunc="mean",
        fill_value=0,
    )
    counts = work.groupby(hitter_col).size().rename("Pitches")
    out = pivot.join(counts).reset_index().rename(columns={hitter_col: "Hitter"})
    count_cols = [c for c in COUNT_ORDER if c in out.columns]
    return out[["Hitter", "Pitches"] + count_cols].sort_values("Pitches", ascending=False)


def calculate_catching(df):
    if df is None or df.empty:
        return pd.DataFrame(), {}

    catcher_col = find_col(df, ["Catcher", "catcher"])
    sba_col = find_col(df, ["BaseStealAtt", "basestealatt", "BaseStealAttempt"])
    outs_col = find_col(df, ["Outs", "outs", "Out"])

    if catcher_col is None or sba_col is None:
        return pd.DataFrame(), {}

    work = df.copy()
    work["_SBA"] = work[sba_col].astype(str).str.lower().isin(["1", "true", "yes", "y", "sba", "steal", "attempt"])

    if outs_col:
        outs = pd.to_numeric(work[outs_col], errors="coerce")
        work["_NextOuts"] = outs.shift(-1)
        work["_CS"] = work["_SBA"] & (work["_NextOuts"] > outs)
    else:
        result_col = find_col(work, ["Result", "PlayResult", "playResult", "Event"])
        if result_col:
            work["_CS"] = work["_SBA"] & work[result_col].astype(str).str.lower().str.contains("caught|cs|out", regex=True, na=False)
        else:
            work["_CS"] = False

    rows = []
    for catcher, g in work.groupby(catcher_col, dropna=False):
        sba = int(g["_SBA"].sum())
        cs = int(g["_CS"].sum())
        rows.append({
            "Catcher": catcher,
            "SBA": sba,
            "CS": cs,
            "SB": max(sba - cs, 0),
            "CS%": pct(cs, sba),
        })

    team_sba = int(work["_SBA"].sum())
    team_cs = int(work["_CS"].sum())
    team = {
        "SBA": team_sba,
        "CS": team_cs,
        "SB": max(team_sba - team_cs, 0),
        "CS%": pct(team_cs, team_sba),
    }

    return pd.DataFrame(rows).sort_values("SBA", ascending=False), team


def sba_by_count_from_file(df):
    if df is None or df.empty:
        return pd.DataFrame()

    count_col = find_col(df, ["Count", "count"])
    runner_col = find_col(df, ["Runner", "runner", "playerFullName", "Player", "Baserunner"])
    sba_col = find_col(df, ["SBA", "SB_Att", "Attempts", "BaseStealAtt", "basestealatt"])

    if count_col is None:
        count_series = get_count_series(df)
    else:
        count_series = df[count_col].astype(str)

    work = df.copy()
    work["_Count"] = count_series

    if sba_col:
        work["_SBA"] = pd.to_numeric(work[sba_col], errors="coerce").fillna(0)
    else:
        work["_SBA"] = 1

    if runner_col:
        pivot = pd.pivot_table(
            work,
            values="_SBA",
            index=runner_col,
            columns="_Count",
            aggfunc="sum",
            fill_value=0,
        )
        total = work.groupby(runner_col)["_SBA"].sum().rename("Total SBA")
        out = pivot.join(total).reset_index().rename(columns={runner_col: "Runner"})
        count_cols = [c for c in COUNT_ORDER if c in out.columns]
        other_cols = [c for c in out.columns if c not in ["Runner", "Total SBA"] + count_cols]
        return out[["Runner", "Total SBA"] + count_cols + other_cols].sort_values("Total SBA", ascending=False)

    out = work.groupby("_Count", as_index=False)["_SBA"].sum().rename(columns={"_Count": "Count", "_SBA": "SBA"})
    out["_order"] = out["Count"].apply(lambda x: COUNT_ORDER.index(x) if x in COUNT_ORDER else 99)
    return out.sort_values("_order").drop(columns="_order")


def league_pitching_averages(rate_df):
    if rate_df is None or rate_df.empty:
        return {}

    avg_map = {}
    bb_col = find_col(rate_df, ["BB%", "BB Rate", "Walk%", "Walk Rate"])
    k_col = find_col(rate_df, ["K%", "SO%", "Strikeout%", "K Rate"])
    pa_col = find_col(rate_df, ["PA", "BF", "Batters Faced"])

    for label, col in [("BB%", bb_col), ("K%", k_col)]:
        if col:
            vals = pd.to_numeric(rate_df[col].astype(str).str.replace("%", "", regex=False), errors="coerce")
            if vals.dropna().median() > 1:
                vals = vals / 100
            if pa_col:
                weights = pd.to_numeric(rate_df[pa_col], errors="coerce").fillna(0)
                avg_map[label] = (vals.fillna(0) * weights).sum() / weights.sum() if weights.sum() else vals.mean()
            else:
                avg_map[label] = vals.mean()

    return avg_map


def league_hitting_averages(hitting_df):
    if hitting_df is None or hitting_df.empty:
        return {}

    avg_map = {}
    stat_names = ["AVG", "OBP", "SLG", "OPS", "BB%", "K%"]
    pa_col = find_col(hitting_df, ["PA", "Plate Appearances"])

    for stat in stat_names:
        col = find_col(hitting_df, [stat])
        if not col:
            continue
        vals = pd.to_numeric(hitting_df[col].astype(str).str.replace("%", "", regex=False), errors="coerce")
        if stat.endswith("%") and vals.dropna().median() > 1:
            vals = vals / 100
        if pa_col:
            weights = pd.to_numeric(hitting_df[pa_col], errors="coerce").fillna(0)
            avg_map[stat] = (vals.fillna(0) * weights).sum() / weights.sum() if weights.sum() else vals.mean()
        else:
            avg_map[stat] = vals.mean()

    return avg_map


# ============================================================
# PDF
# ============================================================

def df_for_pdf(df, percent_cols=None, avg_cols=None):
    if df is None or df.empty:
        return [["No data"]]
    percent_cols = percent_cols or []
    avg_cols = avg_cols or []
    display = df.copy()
    for c in display.columns:
        if c in percent_cols:
            display[c] = display[c].apply(fmt_pct)
        elif c in avg_cols:
            display[c] = display[c].apply(fmt_avg)
        elif pd.api.types.is_numeric_dtype(display[c]):
            if display[c].between(0, 1).all() and c not in ["PA", "AB", "H", "BB", "K", "Pitches", "SBA", "CS", "SB", "Total SBA"]:
                display[c] = display[c].apply(fmt_pct)
            else:
                display[c] = display[c].apply(fmt_num)
    return [display.columns.tolist()] + display.astype(str).values.tolist()


def add_table(story, data, title=None, small=False):
    if colors is None:
        return

    styles = getSampleStyleSheet()
    if title:
        story.append(Paragraph(title, styles["Heading2"]))
        story.append(Spacer(1, 0.08 * inch))

    if not data or len(data) == 0:
        data = [["No data"]]

    table = Table(data, repeatRows=1)
    font_size = 6 if small else 8

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#002D72")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))

    story.append(table)
    story.append(Spacer(1, 0.18 * inch))


def build_pdf(
    opponent_name,
    pitcher_stats,
    team_pitch_usage,
    pitcher_usage,
    swing_take,
    hitter_swing,
    hitting_stats,
    catching_df,
    catching_team,
    team_sba,
    runner_sba,
    league_hit_avg,
    league_pitch_avg,
):
    if colors is None:
        raise RuntimeError("ReportLab is not installed. Add reportlab to requirements.txt.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=0.35 * inch,
        leftMargin=0.35 * inch,
        topMargin=0.35 * inch,
        bottomMargin=0.35 * inch,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="CoverTitle",
        parent=styles["Title"],
        fontSize=28,
        textColor=colors.HexColor("#002D72"),
        spaceAfter=18,
    ))
    styles.add(ParagraphStyle(
        name="Sub",
        parent=styles["Normal"],
        fontSize=12,
        textColor=colors.HexColor("#444444"),
        spaceAfter=12,
    ))

    story = []

    story.append(Paragraph("ADVANCED PREGAME REPORT", styles["CoverTitle"]))
    story.append(Paragraph(f"Opponent: <b>{opponent_name}</b>", styles["Sub"]))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%b %d, %Y')}", styles["Sub"]))
    story.append(Spacer(1, 0.25 * inch))

    pitch_team_pa = int(pitcher_stats["PA"].sum()) if not pitcher_stats.empty and "PA" in pitcher_stats else 0
    pitch_bb = pitcher_stats["BB"].sum() if not pitcher_stats.empty and "BB" in pitcher_stats else 0
    pitch_k = pitcher_stats["K"].sum() if not pitcher_stats.empty and "K" in pitcher_stats else 0
    hit_pa = int(hitting_stats["PA"].sum()) if not hitting_stats.empty and "PA" in hitting_stats else 0

    summary_data = [
        ["Area", "Metric", "Value"],
        ["Pitching", "Opponent BB%", fmt_pct(pct(pitch_bb, pitch_team_pa))],
        ["Pitching", "Opponent K%", fmt_pct(pct(pitch_k, pitch_team_pa))],
        ["Hitting", "Hitter PA in file", fmt_num(hit_pa)],
        ["Catching", "Team SBA", fmt_num(catching_team.get("SBA", 0))],
        ["Catching", "Team CS%", fmt_pct(catching_team.get("CS%", 0))],
    ]
    add_table(story, summary_data, "Executive Summary")

    story.append(PageBreak())

    story.append(Paragraph("Pitching Plan", styles["Title"]))
    add_table(story, df_for_pdf(pitcher_stats.sort_values("BB%", ascending=False).head(3), ["BB%", "K%"]), "Highest BB% Pitchers")
    add_table(story, df_for_pdf(pitcher_stats.sort_values("BB%", ascending=True).head(3), ["BB%", "K%"]), "Lowest BB% Pitchers")
    add_table(story, df_for_pdf(pitcher_stats.sort_values("K%", ascending=False).head(3), ["BB%", "K%"]), "Highest K% Pitchers")
    add_table(story, df_for_pdf(pitcher_stats.sort_values("K%", ascending=True).head(3), ["BB%", "K%"]), "Lowest K% Pitchers")
    add_table(story, df_for_pdf(team_pitch_usage), "Team Pitch Usage by Count", small=True)

    story.append(PageBreak())

    story.append(Paragraph("Pitcher Usage Table", styles["Title"]))
    add_table(story, df_for_pdf(pitcher_usage), "Pitch Usage by Pitcher", small=True)

    story.append(PageBreak())

    story.append(Paragraph("Hitting Plan", styles["Title"]))
    add_table(story, df_for_pdf(swing_take, ["Swing%", "Take%"]), "Team Swing/Take by Count")
    for stat in ["AVG", "OBP", "SLG", "OPS", "BB%", "K%"]:
        if stat in hitting_stats:
            pct_cols = ["BB%", "K%"]
            avg_cols = ["AVG", "OBP", "SLG", "OPS"]
            ascending = stat == "K%"
            add_table(
                story,
                df_for_pdf(hitting_stats.sort_values(stat, ascending=ascending).head(3), pct_cols, avg_cols),
                f"Top 3 Hitters - {stat}",
            )
            add_table(
                story,
                df_for_pdf(hitting_stats.sort_values(stat, ascending=not ascending).head(3), pct_cols, avg_cols),
                f"Bottom 3 Hitters - {stat}",
            )

    story.append(PageBreak())

    story.append(Paragraph("Hitter Swing Table", styles["Title"]))
    add_table(story, df_for_pdf(hitter_swing), "Swing% by Hitter and Count", small=True)

    story.append(PageBreak())

    story.append(Paragraph("Catching & Running Game", styles["Title"]))
    add_table(story, df_for_pdf(catching_df, ["CS%"]), "Catcher Running Game")
    add_table(story, df_for_pdf(team_sba), "Team SBA by Count")
    add_table(story, df_for_pdf(runner_sba), "Runner SBA by Count", small=True)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ============================================================
# SIDEBAR UPLOADS
# ============================================================

st.sidebar.header("Upload CSVs")

uploaded_files = st.sidebar.file_uploader(
    "Upload all CSVs at once",
    type=["csv"],
    accept_multiple_files=True,
    help="Upload Pregame, Copy of Standard, Catching PreGame, Stolen Bases, SBA Count, Pregame Hitting, and Rate together.",
)

opponent_name = st.sidebar.text_input("Opponent Name", value="Opponent")

detected = detect_files(uploaded_files or [])

with st.sidebar.expander("Detected Files", expanded=True):
    for key, f in detected.items():
        label = key.replace("_", " ").title()
        st.write(f"✅ {label}: {f.name}" if f else f"❌ {label}: Missing")

with st.sidebar.expander("Optional Manual Overrides"):
    pregame_file = st.file_uploader("Opponent Pregame.csv", type=["csv"], key="pregame_manual")
    standard_file = st.file_uploader("Opponent Copy of Standard.csv", type=["csv"], key="standard_manual")
    catching_file = st.file_uploader("Opponent Catching PreGame.csv", type=["csv"], key="catching_manual")
    stolen_file = st.file_uploader("Opponent Stolen Bases.csv", type=["csv"], key="stolen_manual")
    sba_count_file = st.file_uploader("Opponent SBA Count.csv", type=["csv"], key="sba_manual")
    league_hit_file = st.file_uploader("League Pregame Hitting.csv", type=["csv"], key="league_hit_manual")
    league_pitch_file = st.file_uploader("League Rate.csv", type=["csv"], key="league_pitch_manual")

pregame_file = pregame_file or detected["pregame"]
standard_file = standard_file or detected["standard"]
catching_file = catching_file or detected["catching"]
stolen_file = stolen_file or detected["stolen_bases"]
sba_count_file = sba_count_file or detected["sba_count"]
league_hit_file = league_hit_file or detected["league_hitting"]
league_pitch_file = league_pitch_file or detected["league_pitching"]


if not uploaded_files and not any([pregame_file, standard_file, catching_file, stolen_file, sba_count_file]):
    st.info("Upload the CSV files in the sidebar to generate the report.")
    st.stop()


# ============================================================
# READ DATA
# ============================================================

pregame_df = read_csv_any(pregame_file)
standard_df = read_csv_any(standard_file)
catching_df_raw = read_csv_any(catching_file)
stolen_df = read_csv_any(stolen_file)
sba_count_df = read_csv_any(sba_count_file)
league_hit_df = read_csv_any(league_hit_file)
league_pitch_df = read_csv_any(league_pitch_file)

league_hit_avg = league_hitting_averages(league_hit_df)
league_pitch_avg = league_pitching_averages(league_pitch_df)


# ============================================================
# BUILD TABLES
# ============================================================

pitcher_stats = calculate_pitcher_stats(standard_df)
team_pitch_usage = pitch_usage_by_count(standard_df)
pitcher_usage = pitcher_pitch_usage(standard_df)

hitting_stats = calculate_batting_stats(pregame_df)
swing_take = swing_take_by_count(pregame_df)
hitter_swing = hitter_swing_by_count(pregame_df)

catcher_table, catcher_team = calculate_catching(catching_df_raw)
team_sba_table = sba_by_count_from_file(stolen_df)
runner_sba_table = sba_by_count_from_file(sba_count_df)


# ============================================================
# APP DISPLAY
# ============================================================

st.success("Files loaded. Report sections generated.")

if league_hit_avg or league_pitch_avg:
    st.subheader("League Average Benchmarks")
    col1, col2 = st.columns(2)
    with col1:
        st.write("**Hitting League Averages**")
        st.dataframe(pd.DataFrame([league_hit_avg]), use_container_width=True)
    with col2:
        st.write("**Pitching League Averages**")
        st.dataframe(pd.DataFrame([league_pitch_avg]), use_container_width=True)
else:
    st.warning("League average files not detected yet. Highlighting will be limited.")


tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "PDF Export",
    "Pitching",
    "Hitting",
    "Catching",
    "Baserunning",
])

with tab1:
    st.subheader("Beautiful PDF Export")

    if st.button("Generate Beautiful Pregame PDF", type="primary"):
        try:
            pdf_bytes = build_pdf(
                opponent_name,
                pitcher_stats,
                team_pitch_usage,
                pitcher_usage,
                swing_take,
                hitter_swing,
                hitting_stats,
                catcher_table,
                catcher_team,
                team_sba_table,
                runner_sba_table,
                league_hit_avg,
                league_pitch_avg,
            )
            st.download_button(
                "Download Pregame PDF",
                data=pdf_bytes,
                file_name=f"{opponent_name.replace(' ', '_')}_advanced_pregame_report.pdf",
                mime="application/pdf",
            )
        except Exception as e:
            st.error(f"Could not generate PDF: {e}")

with tab2:
    st.header("Pitching")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Top 3 BB%")
        st.dataframe(
            style_table_vs_avg(
                pitcher_stats.sort_values("BB%", ascending=False).head(3),
                ["BB%", "K%"],
                league_pitch_avg,
                lower_is_better={"BB%"},
            ),
            use_container_width=True,
        )
    with c2:
        st.subheader("Bottom 3 BB%")
        st.dataframe(
            style_table_vs_avg(
                pitcher_stats.sort_values("BB%", ascending=True).head(3),
                ["BB%", "K%"],
                league_pitch_avg,
                lower_is_better={"BB%"},
            ),
            use_container_width=True,
        )

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("Top 3 K%")
        st.dataframe(
            style_table_vs_avg(
                pitcher_stats.sort_values("K%", ascending=False).head(3),
                ["BB%", "K%"],
                league_pitch_avg,
                lower_is_better={"BB%"},
            ),
            use_container_width=True,
        )
    with c4:
        st.subheader("Bottom 3 K%")
        st.dataframe(
            style_table_vs_avg(
                pitcher_stats.sort_values("K%", ascending=True).head(3),
                ["BB%", "K%"],
                league_pitch_avg,
                lower_is_better={"BB%"},
            ),
            use_container_width=True,
        )

    st.subheader("Team Pitch Usage by Count")
    st.dataframe(team_pitch_usage.style.format({c: "{:.1%}" for c in team_pitch_usage.columns if c != "Count"}), use_container_width=True)

    st.subheader("Pitch Usage by Pitcher")
    fmt_cols = {c: "{:.1%}" for c in pitcher_usage.columns if c not in ["Pitcher", "Pitches"]}
    st.dataframe(pitcher_usage.style.format(fmt_cols), use_container_width=True)

with tab3:
    st.header("Hitting")

    st.subheader("Team Swing / Take by Count")
    if not swing_take.empty:
        st.dataframe(swing_take.style.format({"Swing%": "{:.1%}", "Take%": "{:.1%}"}), use_container_width=True)
    else:
        st.warning("No swing/take table available.")

    st.subheader("Top / Bottom Hitters")
    stat = st.selectbox("Stat", ["AVG", "OBP", "SLG", "OPS", "BB%", "K%"])
    ascending_top = stat == "K%"

    c1, c2 = st.columns(2)
    with c1:
        st.write(f"**Top 3 {stat}**")
        st.dataframe(
            style_table_vs_avg(
                hitting_stats.sort_values(stat, ascending=ascending_top).head(3),
                ["AVG", "OBP", "SLG", "OPS", "BB%", "K%"],
                league_hit_avg,
                lower_is_better={"K%"},
            ),
            use_container_width=True,
        )
    with c2:
        st.write(f"**Bottom 3 {stat}**")
        st.dataframe(
            style_table_vs_avg(
                hitting_stats.sort_values(stat, ascending=not ascending_top).head(3),
                ["AVG", "OBP", "SLG", "OPS", "BB%", "K%"],
                league_hit_avg,
                lower_is_better={"K%"},
            ),
            use_container_width=True,
        )

    st.subheader("Hitter Swing% by Count")
    if not hitter_swing.empty:
        st.dataframe(hitter_swing.style.format({c: "{:.1%}" for c in hitter_swing.columns if c in COUNT_ORDER}), use_container_width=True)
    else:
        st.warning("No hitter swing-by-count table available.")

with tab4:
    st.header("Catching")

    m1, m2, m3 = st.columns(3)
    m1.metric("Team SBA", catcher_team.get("SBA", 0))
    m2.metric("Team CS", catcher_team.get("CS", 0))
    m3.metric("Team CS%", fmt_pct(catcher_team.get("CS%", 0)))

    st.subheader("Catcher Running Game")
    if not catcher_table.empty:
        st.dataframe(catcher_table.style.format({"CS%": "{:.1%}"}), use_container_width=True)
    else:
        st.warning("No catcher table available.")

with tab5:
    st.header("Baserunning")

    st.subheader("Team SBA by Count")
    st.dataframe(team_sba_table, use_container_width=True)

    st.subheader("Individual Runner SBA by Count")
    st.dataframe(runner_sba_table, use_container_width=True)
# redeploy
