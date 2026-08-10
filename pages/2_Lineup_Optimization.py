
import streamlit as st
import pandas as pd
import numpy as np
import re
import html
import os
import tempfile
from datetime import date
from io import BytesIO

from PIL import Image
try:
    from pypdf import PdfReader
    PDF_READER_AVAILABLE = True
except ModuleNotFoundError:
    try:
        from PyPDF2 import PdfReader
        PDF_READER_AVAILABLE = True
    except ModuleNotFoundError:
        PdfReader = None
        PDF_READER_AVAILABLE = False
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

st.set_page_config(page_title="Lineup Optimization", layout="wide")

# ============================================================
# CONFIG
# ============================================================

BASE_STATS = ["AVG", "OBP", "SLG", "ISO", "SB"]
PITCH_GROUPS = ["FB", "SI", "CT", "SL", "CB", "CH"]

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

TERMINAL_KEYWORDS = (
    "single", "double", "triple", "home run", "walk", "hit by pitch",
    "strikeout", "ground out", "fly out", "line out", "pop out",
    "double play", "triple play", "fielder's choice", "reached on error",
    "sacrifice", "sac fly", "sac bunt", "field out", "force out",
    "interference"
)

# ============================================================
# GENERIC HELPERS
# ============================================================

def clean_columns(df):
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def find_column(df, candidates):
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in lookup:
            return lookup[key]
    return None


def normalize_hand(value):
    if pd.isna(value):
        return "R"
    value = str(value).strip().upper()
    if value.startswith("L"):
        return "L"
    if value.startswith("S") or value in {"B", "BOTH", "SWITCH"}:
        return "S"
    return "R"


def hitter_name_color(hand):
    hand = normalize_hand(hand)
    if hand == "L":
        return "#BA0C2F"
    if hand == "S":
        return "#0057B8"
    return "#111111"


def format_rate(value):
    try:
        return f"{float(value):.3f}".replace("0.", ".")
    except Exception:
        return ""


def format_cell(value, column):
    if pd.isna(value):
        return ""
    if column in {"AVG", "OBP", "SLG", "ISO"}:
        return format_rate(value)
    if column in {"PA", "SB", "Lineup Spot"}:
        try:
            return str(int(round(float(value))))
        except Exception:
            return str(value)
    if column in {"Overall Score", "Spot Fit Score", "Matchup Score"}:
        try:
            return f"{float(value):.4f}"
        except Exception:
            return str(value)
    return str(value)


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce").fillna(0)


def minmax(series):
    values = safe_numeric(series)
    lo, hi = values.min(), values.max()
    if hi == lo:
        return pd.Series(0.5, index=series.index)
    return (values - lo) / (hi - lo)


def rgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*[max(0, min(255, int(x))) for x in rgb])


def extract_team_colors(logo_file):
    default_primary = (0, 45, 114)
    default_accent = (186, 12, 47)
    if logo_file is None:
        return default_primary, default_accent

    try:
        logo_file.seek(0)
        image = Image.open(logo_file).convert("RGBA")
        image.thumbnail((180, 180))
        buckets = {}

        for r, g, b, a in image.getdata():
            if a < 120:
                continue
            if r > 238 and g > 238 and b > 238:
                continue
            if max(r, g, b) - min(r, g, b) < 16:
                continue
            key = (
                min(255, round(r / 32) * 32),
                min(255, round(g / 32) * 32),
                min(255, round(b / 32) * 32),
            )
            buckets[key] = buckets.get(key, 0) + 1

        ranked = [color for color, _ in sorted(buckets.items(), key=lambda item: item[1], reverse=True)]
        if not ranked:
            return default_primary, default_accent

        primary = ranked[0]
        accent = default_accent
        for candidate in ranked[1:]:
            distance = sum((candidate[i] - primary[i]) ** 2 for i in range(3)) ** 0.5
            if distance > 90:
                accent = candidate
                break
        return primary, accent
    except Exception:
        return default_primary, default_accent
    finally:
        try:
            logo_file.seek(0)
        except Exception:
            pass


def save_uploaded_temp(uploaded_file, suffix):
    if uploaded_file is None:
        return None
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    uploaded_file.seek(0)
    handle.write(uploaded_file.read())
    handle.close()
    uploaded_file.seek(0)
    return handle.name


# ============================================================
# PITCH-BY-PITCH STAT ENGINE
# ============================================================

def pitch_group(code, full_name=""):
    code = str(code).upper().strip()
    full_name = str(full_name).upper().strip()

    if code in {"FA", "FF"} or "FASTBALL" in full_name or "FOUR SEAM" in full_name:
        return "FB"
    if code in {"SI", "FT"} or "SINKER" in full_name or "TWO SEAM" in full_name:
        return "SI"
    if code in {"FC", "CT"} or "CUTTER" in full_name:
        return "CT"
    if code in {"SL", "ST"} or "SLIDER" in full_name or "SWEEPER" in full_name:
        return "SL"
    if code in {"CU", "CB", "KC", "CS"} or "CURVE" in full_name:
        return "CB"
    if code in {"CH", "FS", "OS"} or "CHANGE" in full_name or "SPLITTER" in full_name:
        return "CH"
    return "OTHER"


def is_terminal_result(result):
    text = str(result).strip().lower()
    return any(keyword in text for keyword in TERMINAL_KEYWORDS)


def outcome_flags(result):
    text = str(result).strip().lower()

    single = "single" in text
    double = "double" in text and "double play" not in text
    triple = "triple" in text and "triple play" not in text
    homer = "home run" in text or "homer" in text
    walk = text == "walk" or "intentional walk" in text
    hbp = "hit by pitch" in text
    sacrifice_fly = "sac fly" in text or "sacrifice fly" in text
    sacrifice_bunt = "sac bunt" in text or "sacrifice bunt" in text

    hit = single or double or triple or homer
    total_bases = int(single) + 2 * int(double) + 3 * int(triple) + 4 * int(homer)

    no_ab = walk or hbp or sacrifice_fly or sacrifice_bunt
    ab = int(not no_ab)
    obp_den = int(not sacrifice_bunt)
    reached = int(hit or walk or hbp)

    return {
        "PA": 1,
        "AB": ab,
        "H": int(hit),
        "TB": total_bases,
        "BB": int(walk),
        "HBP": int(hbp),
        "SF": int(sacrifice_fly),
        "OBP_DEN": obp_den,
        "REACHED": reached,
    }



def parse_successful_steals(raw_df):
    """
    Infer the runner credited with each successful steal.

    `BaseStealAtt` identifies the destination base, but the hitter listed on
    that pitch is usually the batter at the plate, not the runner. The CSV also
    commonly leaves `atbatDesc` blank on steal pitches. We therefore process
    each game and half-inning chronologically, maintain a basic base-state,
    and credit the runner occupying the source base:

        2B   -> runner from first base
        3B   -> runner from second base
        Home -> runner from third base

    If the expected base is empty because an earlier advancement was not fully
    described by the feed, the most recent known baserunner in that half-inning
    is used as a fallback.
    """
    required = {
        "gameId", "inn", "pitchNumInGame", "batterAbbrevName",
        "pitchResult", "BaseStealAtt"
    }
    if not required.issubset(raw_df.columns):
        return {}

    steals = {}

    for (_, _), inning_df in raw_df.groupby(["gameId", "inn"], sort=False):
        inning_df = inning_df.sort_values("pitchNumInGame")

        bases = {1: None, 2: None, 3: None}
        recent_runners = []

        for _, row in inning_df.iterrows():
            batter = str(row["batterAbbrevName"]).strip()

            # Process the steal before processing the result of the current pitch.
            if pd.notna(row["BaseStealAtt"]):
                destination = str(row["BaseStealAtt"]).strip()
                target_base = {"2B": 2, "3B": 3, "Home": 4}.get(destination)
                source_base = target_base - 1 if target_base else None

                runner = bases.get(source_base) if source_base else None

                # Fallback for feeds that do not fully describe prior advances.
                if not runner and recent_runners:
                    runner = recent_runners[-1]

                if runner:
                    steals[runner] = steals.get(runner, 0) + 1

                    if source_base in bases and bases[source_base] == runner:
                        bases[source_base] = None

                    if target_base in bases:
                        bases[target_base] = runner

            result = str(row["pitchResult"]).strip().lower()

            if not is_terminal_result(result):
                continue

            if "home run" in result or "homer" in result:
                bases = {1: None, 2: None, 3: None}

            elif "triple" in result and "triple play" not in result:
                bases = {1: None, 2: None, 3: batter}
                recent_runners.append(batter)

            elif "double" in result and "double play" not in result:
                bases = {1: None, 2: batter, 3: None}
                recent_runners.append(batter)

            elif (
                "single" in result
                or "walk" in result
                or "hit by pitch" in result
                or "reached on error" in result
                or "fielder's choice" in result
            ):
                # Apply only the forced movement we can infer safely.
                if bases[2] and bases[1]:
                    bases[3] = bases[2]

                if bases[1]:
                    bases[2] = bases[1]

                bases[1] = batter
                recent_runners.append(batter)

            elif "double play" in result:
                bases[1] = None

    return steals


def assign_sb_to_players(player_names, successful_steals):
    """
    Match the inferred abbreviated runner names to the player names used by
    the batting tables.
    """
    normalized_success = {
        re.sub(r"[^a-z]", "", str(name).lower()): count
        for name, count in successful_steals.items()
    }

    assigned = {}

    for player in player_names:
        player_key = re.sub(r"[^a-z]", "", str(player).lower())
        total = 0

        for runner_key, count in normalized_success.items():
            if (
                player_key == runner_key
                or player_key in runner_key
                or runner_key in player_key
            ):
                total += count

        assigned[player] = total

    return assigned


def prepare_pitch_by_pitch(uploaded_csv):
    try:
        raw = pd.read_csv(uploaded_csv)
    except Exception as exc:
        st.error(f"Could not read Pregame CSV: {exc}")
        return None, None

    raw = clean_columns(raw)

    required = ["pitchResult", "pitchType", "batterHand", "pitcherHand"]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        st.error(f"Missing required columns: {missing}")
        return None, None

    name_col = find_column(raw, ["playerFullName", "batterFullName", "batterAbbrevName", "batterName"])
    if name_col is None:
        st.error("Could not find a hitter name column. Expected `batterAbbrevName` or a full-name equivalent.")
        return None, None

    raw["Player"] = raw[name_col].astype(str).str.strip()
    raw = raw[~raw["Player"].str.lower().isin(["", "nan", "none", "null"])].copy()

    if "pitchTypeFull" not in raw.columns:
        raw["pitchTypeFull"] = ""
    raw["PitchGroup"] = [
        pitch_group(code, full)
        for code, full in zip(raw["pitchType"], raw["pitchTypeFull"])
    ]
    raw["Bats"] = raw["batterHand"].apply(normalize_hand)
    raw["PitcherHand"] = raw["pitcherHand"].apply(normalize_hand)

    # Use explicit terminal PA results. If duplicate terminal records exist,
    # preserve only the final row for each plate appearance key.
    terminal = raw[raw["pitchResult"].apply(is_terminal_result)].copy()

    pa_key_options = [
        ["gameId", "abNumInGame", "Player"],
        ["gameString", "abNumInGame", "Player"],
        ["gameId", "pitchNumInAB", "Player"],
    ]
    pa_key = next((keys for keys in pa_key_options if all(k in terminal.columns for k in keys)), None)

    if pa_key:
        sort_cols = [c for c in ["gameDate", "gameId", "abNumInGame", "pitchNumInAB", "pitchNumInGame"] if c in terminal.columns]
        if sort_cols:
            terminal = terminal.sort_values(sort_cols)
        terminal = terminal.drop_duplicates(pa_key, keep="last")

    if terminal.empty:
        st.error("No completed plate appearances were detected from `pitchResult`.")
        return None, None

    flags = terminal["pitchResult"].apply(outcome_flags).apply(pd.Series)
    terminal = pd.concat([terminal.reset_index(drop=True), flags.reset_index(drop=True)], axis=1)

    successful_steals = parse_successful_steals(raw)
    sb_map = assign_sb_to_players(terminal["Player"].unique(), successful_steals)

    return raw, terminal.assign(SB=terminal["Player"].map(sb_map).fillna(0))


def aggregate_stats(terminal_df, pitcher_hand=None, pitch_group_filter=None):
    subset = terminal_df.copy()

    if pitcher_hand:
        subset = subset[subset["PitcherHand"] == pitcher_hand]
    if pitch_group_filter:
        subset = subset[subset["PitchGroup"] == pitch_group_filter]

    if subset.empty:
        return pd.DataFrame(columns=["playerFullName", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB"])

    grouped = subset.groupby("Player", as_index=False).agg(
        Bats=("Bats", lambda values: values.mode().iloc[0] if not values.mode().empty else "R"),
        PA=("PA", "sum"),
        AB=("AB", "sum"),
        H=("H", "sum"),
        TB=("TB", "sum"),
        BB=("BB", "sum"),
        HBP=("HBP", "sum"),
        SF=("SF", "sum"),
        SB=("SB", "max"),
    )

    grouped["AVG"] = np.where(grouped["AB"] > 0, grouped["H"] / grouped["AB"], 0.0)
    grouped["OBP_DEN"] = grouped["AB"] + grouped["BB"] + grouped["HBP"] + grouped["SF"]
    grouped["OBP"] = np.where(
        grouped["OBP_DEN"] > 0,
        (grouped["H"] + grouped["BB"] + grouped["HBP"]) / grouped["OBP_DEN"],
        0.0,
    )
    grouped["SLG"] = np.where(grouped["AB"] > 0, grouped["TB"] / grouped["AB"], 0.0)
    grouped["ISO"] = grouped["SLG"] - grouped["AVG"]
    grouped = grouped.rename(columns={"Player": "playerFullName"})

    return grouped[["playerFullName", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB"]]


def build_pitch_type_tables(terminal_df, hitter_hand_context=None):
    tables = {}
    for group in PITCH_GROUPS:
        subset = terminal_df.copy()
        if hitter_hand_context:
            subset = subset[subset["PitcherHand"] == hitter_hand_context]
        tables[group] = aggregate_stats(subset, pitch_group_filter=group)
    return tables



# ============================================================
# PRE-CALCULATED LINEUP OPTIMIZER CSV
# ============================================================

def prepare_lineup_optimizer_csv(uploaded_csv):
    """
    Read the pre-calculated Lineup Optimization CSV.

    Expected fields:
      playerFullName, batsHand, PA, AVG, OBP, SLG, ISO, SB

    The export may contain a TOTAL row and may also repeat the CSV header as
    a data row. Both are removed automatically.
    """
    try:
        df = pd.read_csv(uploaded_csv)
    except Exception as exc:
        st.error(f"Could not read Lineup Optimizer CSV: {exc}")
        return None

    df = clean_columns(df)

    required = ["playerFullName", "PA", "AVG", "OBP", "SLG", "ISO", "SB"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        st.error(
            "This does not look like a Lineup Optimizer CSV. "
            f"Missing columns: {missing}"
        )
        return None

    bats_col = find_column(df, ["batsHand", "BatsHand", "bats", "Bats"])
    if bats_col is None:
        df["Bats"] = "R"
    else:
        df["Bats"] = df[bats_col].apply(normalize_hand)

    # Remove the summary TOTAL row, blank-name rows, and repeated header rows.
    df["playerFullName"] = df["playerFullName"].astype(str).str.strip()

    if "playerId" in df.columns:
        player_id_text = df["playerId"].astype(str).str.strip().str.lower()
        df = df[player_id_text != "total"].copy()

    bad_names = {
        "", "nan", "none", "null", "playerfullname", "player full name"
    }
    df = df[~df["playerFullName"].str.lower().isin(bad_names)].copy()

    for column in ["PA", "AVG", "OBP", "SLG", "ISO", "SB"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df[df["PA"].notna()].copy()

    for column in ["PA", "AVG", "OBP", "SLG", "ISO", "SB"]:
        df[column] = df[column].fillna(0)

    # If ISO is missing/blank for an otherwise valid row, reconstruct it.
    iso_recalc = df["SLG"] - df["AVG"]
    df["ISO"] = df["ISO"].where(df["ISO"].notna(), iso_recalc)

    return df[
        ["playerFullName", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB"]
    ].reset_index(drop=True)


def detect_csv_source(uploaded_csv):
    """
    Auto-detect whether an uploaded CSV is pitch-by-pitch Pregame data or a
    pre-calculated Lineup Optimizer export.
    """
    try:
        uploaded_csv.seek(0)
        sample = pd.read_csv(uploaded_csv, nrows=5)
        uploaded_csv.seek(0)
    except Exception:
        try:
            uploaded_csv.seek(0)
        except Exception:
            pass
        return None

    columns = {str(column).strip().lower() for column in sample.columns}

    pregame_markers = {"pitchresult", "pitchtype", "batterhand", "pitcherhand"}
    optimizer_markers = {"playerfullname", "pa", "avg", "obp", "slg", "iso", "sb"}

    if pregame_markers.issubset(columns):
        return "Pregame Pitch-by-Pitch"
    if optimizer_markers.issubset(columns):
        return "Lineup Optimizer Stats"
    return None


# ============================================================
# PITCHER PDF PARSER
# ============================================================

def extract_pdf_text(uploaded_pdf):
    if not PDF_READER_AVAILABLE or PdfReader is None:
        raise RuntimeError(
            "PDF reading dependency is missing. Add `pypdf` to requirements.txt and redeploy."
        )

    uploaded_pdf.seek(0)
    reader = PdfReader(uploaded_pdf)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    uploaded_pdf.seek(0)
    return text


def section_between(text, start, ends):
    start_match = re.search(re.escape(start), text, re.IGNORECASE)
    if not start_match:
        return ""
    tail = text[start_match.end():]
    end_positions = []
    for end in ends:
        match = re.search(re.escape(end), tail, re.IGNORECASE)
        if match:
            end_positions.append(match.start())
    end_index = min(end_positions) if end_positions else len(tail)
    return tail[:end_index]


def parse_usage_section(section):
    usage = {}
    for code in ["FB", "SI", "CT", "SL", "CB", "OS"]:
        match = re.search(rf"\b{code}\s+([0-9]+(?:\.[0-9]+)?)%", section, re.IGNORECASE)
        if match:
            mapped = "CH" if code == "OS" else code
            usage[mapped] = float(match.group(1)) / 100.0
    return usage


def parse_pitcher_pdf(uploaded_pdf):
    try:
        text = extract_pdf_text(uploaded_pdf)
    except Exception as exc:
        st.error(f"Could not read opponent pitcher PDF: {exc}")
        return None

    header_match = re.search(r"#?\d*\s*([A-ZÁÉÍÓÚÑÜ][^\n\(]{2,60})\s*\(([RLS])\)", text)
    pitcher_name = header_match.group(1).strip() if header_match else "Uploaded Pitcher"
    pitcher_hand = normalize_hand(header_match.group(2)) if header_match else "R"

    rhh_section = section_between(text, "Usage% vs RHH", ["Usage% vs LHH", "Velocity", "Stats vs RHH"])
    lhh_section = section_between(text, "Usage% vs LHH", ["Velocity", "Stats vs RHH"])

    usage_rhh = parse_usage_section(rhh_section)
    usage_lhh = parse_usage_section(lhh_section)

    def stat_from_section(section_name, following_names, stat):
        sec = section_between(text, section_name, following_names)
        match = re.search(rf"\b{re.escape(stat)}\s+([.]?\d+(?:\.\d+)?%?)", sec, re.IGNORECASE)
        return match.group(1) if match else "—"

    stats_rhh = {
        "AVG": stat_from_section("Stats vs RHH", ["Stats vs LHH", "Total"], "AVG"),
        "OBP": stat_from_section("Stats vs RHH", ["Stats vs LHH", "Total"], "OBP"),
        "SLG": stat_from_section("Stats vs RHH", ["Stats vs LHH", "Total"], "SLG"),
        "OPS": stat_from_section("Stats vs RHH", ["Stats vs LHH", "Total"], "OPS"),
        "K%": stat_from_section("Stats vs RHH", ["Stats vs LHH", "Total"], "K%"),
        "BB%": stat_from_section("Stats vs RHH", ["Stats vs LHH", "Total"], "BB%"),
        "wOBA": stat_from_section("Stats vs RHH", ["Stats vs LHH", "Total"], "wOBA"),
    }
    stats_lhh = {
        "AVG": stat_from_section("Stats vs LHH", ["Total", "PitchType"], "AVG"),
        "OBP": stat_from_section("Stats vs LHH", ["Total", "PitchType"], "OBP"),
        "SLG": stat_from_section("Stats vs LHH", ["Total", "PitchType"], "SLG"),
        "OPS": stat_from_section("Stats vs LHH", ["Total", "PitchType"], "OPS"),
        "K%": stat_from_section("Stats vs LHH", ["Total", "PitchType"], "K%"),
        "BB%": stat_from_section("Stats vs LHH", ["Total", "PitchType"], "BB%"),
        "wOBA": stat_from_section("Stats vs LHH", ["Total", "PitchType"], "wOBA"),
    }

    return {
        "name": pitcher_name,
        "hand": pitcher_hand,
        "usage_vs_R": usage_rhh,
        "usage_vs_L": usage_lhh,
        "stats_vs_R": stats_rhh,
        "stats_vs_L": stats_lhh,
        "raw_text": text,
    }


# ============================================================
# LINEUP SCORING
# ============================================================

def weighted_offense_score(df, weights):
    total = sum(weights.values()) or 1.0
    score = pd.Series(0.0, index=df.index)
    for stat, weight in weights.items():
        score += minmax(df[stat]) * (weight / total)
    return score


def calculate_pitch_matchup_score(overall_df, pitch_tables, pitcher_info, weights, regression_pa):
    result = overall_df[["playerFullName", "Bats"]].copy()
    result["Pitch Matchup Score"] = 0.0
    result["Pitch Matchup Coverage"] = 0.0

    non_sb_weights = {key: value for key, value in weights.items() if key != "SB"}
    player_index = {name: idx for idx, name in enumerate(result["playerFullName"])}

    pitch_scores = {}
    for group, table in pitch_tables.items():
        if table.empty:
            continue
        table = table.copy()
        table["RawPitchScore"] = weighted_offense_score(table, non_sb_weights)
        team_mean = table["RawPitchScore"].mean()
        pa = safe_numeric(table["PA"])
        shrink = pa / (pa + max(regression_pa, 1))
        table["RegressedPitchScore"] = shrink * table["RawPitchScore"] + (1 - shrink) * team_mean
        pitch_scores[group] = dict(zip(table["playerFullName"], table["RegressedPitchScore"]))

    for row_idx, row in result.iterrows():
        bats = normalize_hand(row["Bats"])
        effective_side = bats
        if bats == "S":
            effective_side = "L" if pitcher_info["hand"] == "R" else "R"

        usage = pitcher_info["usage_vs_L"] if effective_side == "L" else pitcher_info["usage_vs_R"]
        weighted_sum = 0.0
        coverage = 0.0

        for group, fraction in usage.items():
            player_score = pitch_scores.get(group, {}).get(row["playerFullName"])
            if player_score is not None:
                weighted_sum += fraction * player_score
                coverage += fraction

        result.at[row_idx, "Pitch Matchup Score"] = weighted_sum / coverage if coverage > 0 else 0.5
        result.at[row_idx, "Pitch Matchup Coverage"] = coverage

    return result


def merge_split_scores(overall_df, split_df, weights):
    overall = overall_df.copy()
    split = split_df.copy()

    overall["Overall Component"] = weighted_offense_score(overall, weights)
    split["Platoon Component"] = weighted_offense_score(split, weights)

    merged = overall.merge(
        split[["playerFullName", "PA", "AVG", "OBP", "SLG", "ISO", "SB", "Platoon Component"]],
        on="playerFullName",
        how="left",
        suffixes=("", "_Split"),
    )

    merged["Platoon Component"] = merged["Platoon Component"].fillna(0.5)
    return merged


def build_standard_lineup(df, weights):
    scored = df.copy()
    scored["Overall Score"] = weighted_offense_score(scored, weights)
    selected = scored.sort_values("Overall Score", ascending=False).head(9).copy()
    return optimize_batting_order(selected, weights, score_column="Overall Score"), scored


def build_pitcher_specific_lineup(overall_df, split_df, pitch_tables, pitcher_info, weights, regression_pa):
    merged = merge_split_scores(overall_df, split_df, weights)
    pitch_scores = calculate_pitch_matchup_score(overall_df, pitch_tables, pitcher_info, weights, regression_pa)
    merged = merged.merge(
        pitch_scores[["playerFullName", "Pitch Matchup Score", "Pitch Matchup Coverage"]],
        on="playerFullName",
        how="left",
    )

    merged["Pitch Matchup Score"] = merged["Pitch Matchup Score"].fillna(0.5)
    merged["Matchup Score"] = (
        0.60 * merged["Overall Component"]
        + 0.25 * merged["Platoon Component"]
        + 0.15 * merged["Pitch Matchup Score"]
    )
    merged["Overall Score"] = merged["Matchup Score"]

    # Display the split-line stats that correspond to the pitcher's throwing hand.
    for stat in ["PA", "AVG", "OBP", "SLG", "ISO", "SB"]:
        split_col = f"{stat}_Split"
        if split_col in merged.columns:
            merged[stat] = merged[split_col].where(merged[split_col].notna(), merged[stat])

    selected = merged.sort_values("Matchup Score", ascending=False).head(9).copy()
    lineup = optimize_batting_order(selected, weights, score_column="Matchup Score")
    return lineup, merged


def calculate_spot_fit(row, spot, normalized, user_weights):
    spot_weights = LINEUP_SPOT_WEIGHTS[spot]
    user_total = max(sum(user_weights.values()), 1.0)
    score = 0.0
    for stat in BASE_STATS:
        combined = 0.60 * spot_weights[stat] + 0.40 * (user_weights[stat] / user_total)
        score += normalized.loc[row.name, stat] * combined
    return score


def optimize_batting_order(selected_df, weights, score_column):
    selected = selected_df.copy()
    normalized = pd.DataFrame({stat: minmax(selected[stat]) for stat in BASE_STATS}, index=selected.index)
    remaining = selected.copy()
    rows = []

    for spot in range(1, 10):
        candidates = []
        for idx, row in remaining.iterrows():
            fit = calculate_spot_fit(row, spot, normalized, weights)
            # Slightly retain the player-selection score in the ordering.
            selection_score = float(row.get(score_column, 0))
            candidates.append((idx, 0.80 * fit + 0.20 * selection_score))

        best_idx, best_fit = max(candidates, key=lambda item: item[1])
        best = remaining.loc[best_idx].copy()
        best["Lineup Spot"] = spot
        best["Spot Fit Score"] = best_fit
        rows.append(best)
        remaining = remaining.drop(best_idx)

    lineup = pd.DataFrame(rows)
    columns = ["Lineup Spot", "playerFullName", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB"]
    if "Matchup Score" in lineup.columns:
        columns.append("Matchup Score")
    columns += ["Overall Score", "Spot Fit Score"]
    return lineup[[column for column in columns if column in lineup.columns]]


def lineup_summary(lineup):
    pa = safe_numeric(lineup["PA"])
    total_pa = pa.sum()
    summary = {"PA": int(total_pa), "SB": int(safe_numeric(lineup["SB"]).sum())}
    for stat in ["AVG", "OBP", "SLG", "ISO"]:
        values = safe_numeric(lineup[stat])
        summary[stat] = float((values * pa).sum() / total_pa) if total_pa > 0 else float(values.mean())
    summary["Score"] = float(safe_numeric(lineup["Spot Fit Score"]).sum())
    return summary


# ============================================================
# WEBSITE TABLES
# ============================================================

def render_lineup_table(lineup, header_color="#002D72"):
    columns = ["Lineup Spot", "playerFullName", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB"]
    summary = lineup_summary(lineup)

    pretty = {
        "Lineup Spot": "#",
        "playerFullName": "Player",
        "Bats": "B",
    }

    table = f"""
    <style>
    .matchup-table {{width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:14px;}}
    .matchup-table th {{background:{header_color}; color:white; padding:9px 6px; border:1px solid #ddd;}}
    .matchup-table td {{padding:8px 6px; border:1px solid #e4e4e4; text-align:center;}}
    .matchup-table td.name {{text-align:left; font-weight:800;}}
    .matchup-table tr:nth-child(even) {{background:#f7f8fb;}}
    .matchup-table tr.total td {{background:#eaf0fa; color:{header_color}; font-weight:900;}}
    </style>
    <table class="matchup-table"><thead><tr>
    """
    table += "".join(f"<th>{pretty.get(column, column)}</th>" for column in columns)
    table += "</tr></thead><tbody>"

    for _, row in lineup.iterrows():
        table += "<tr>"
        for column in columns:
            value = format_cell(row[column], column)
            if column == "playerFullName":
                color = hitter_name_color(row["Bats"])
                table += f'<td class="name" style="color:{color}">{html.escape(value)}</td>'
            else:
                table += f"<td>{html.escape(value)}</td>"
        table += "</tr>"

    totals = {
        "Lineup Spot": "",
        "playerFullName": "TOTAL/AVG",
        "Bats": "—",
        "PA": summary["PA"],
        "AVG": summary["AVG"],
        "OBP": summary["OBP"],
        "SLG": summary["SLG"],
        "ISO": summary["ISO"],
        "SB": summary["SB"],
    }
    table += '<tr class="total">'
    table += "".join(f"<td>{html.escape(format_cell(totals[column], column))}</td>" for column in columns)
    table += "</tr></tbody></table>"
    st.markdown(table, unsafe_allow_html=True)


def render_pitcher_card(info):
    st.markdown(f"### Opponent: {info['name']} ({info['hand']})")
    col1, col2 = st.columns(2)

    def usage_text(usage):
        return " · ".join(f"{pitch} {value:.1%}" for pitch, value in sorted(usage.items(), key=lambda item: item[1], reverse=True))

    with col1:
        st.markdown("**Usage vs RHH**")
        st.write(usage_text(info["usage_vs_R"]) or "Usage could not be parsed.")
        st.markdown("**Results vs RHH**")
        st.write(" · ".join(f"{key} {value}" for key, value in info["stats_vs_R"].items()))

    with col2:
        st.markdown("**Usage vs LHH**")
        st.write(usage_text(info["usage_vs_L"]) or "Usage could not be parsed.")
        st.markdown("**Results vs LHH**")
        st.write(" · ".join(f"{key} {value}" for key, value in info["stats_vs_L"].items()))


# ============================================================
# PDF EXPORT
# ============================================================

def draw_logo(c, path, x, y, max_w, max_h):
    if not path:
        return
    try:
        image = ImageReader(path)
        iw, ih = image.getSize()
        scale = min(max_w / iw, max_h / ih)
        w, h = iw * scale, ih * scale
        c.drawImage(image, x + (max_w - w) / 2, y + (max_h - h) / 2, w, h, mask="auto")
    except Exception:
        pass


def pdf_rows(lineup):
    rows = [["#", "PLAYER", "B", "PA", "AVG", "OBP", "SLG", "ISO", "SB"]]
    for _, row in lineup.iterrows():
        rows.append([
            format_cell(row["Lineup Spot"], "Lineup Spot"),
            str(row["playerFullName"]),
            str(row["Bats"]),
            format_cell(row["PA"], "PA"),
            format_cell(row["AVG"], "AVG"),
            format_cell(row["OBP"], "OBP"),
            format_cell(row["SLG"], "SLG"),
            format_cell(row["ISO"], "ISO"),
            format_cell(row["SB"], "SB"),
        ])

    summary = lineup_summary(lineup)
    rows.append([
        "", "TOTAL/AVG", "—", str(summary["PA"]),
        format_rate(summary["AVG"]), format_rate(summary["OBP"]),
        format_rate(summary["SLG"]), format_rate(summary["ISO"]),
        str(summary["SB"]),
    ])
    return rows


def draw_lineup_panel(c, lineup, x, y, w, h, title, header_color):
    c.setStrokeColor(colors.HexColor("#D7D7D7"))
    c.setFillColor(colors.white)
    c.roundRect(x, y, w, h, 6, fill=1, stroke=1)

    header_h = 28
    metric_h = 35
    c.setFillColor(header_color)
    c.roundRect(x, y + h - header_h, w, header_h, 6, fill=1, stroke=0)
    c.rect(x, y + h - header_h, w, 6, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawCentredString(x + w / 2, y + h - 18, title)

    summary = lineup_summary(lineup)
    labels = ["Team AVG", "Team OBP", "Team SLG", "Projected Score"]
    values = [
        format_rate(summary["AVG"]),
        format_rate(summary["OBP"]),
        format_rate(summary["SLG"]),
        f"{summary['Score']:.2f}",
    ]

    metric_y = y + h - header_h - metric_h
    metric_w = w / 4
    for i, (label, value) in enumerate(zip(labels, values)):
        c.setFillColor(colors.HexColor("#20242B"))
        c.setFont("Helvetica-Bold", 5.5)
        c.drawCentredString(x + metric_w * (i + 0.5), metric_y + 22, label)
        c.setFillColor(colors.HexColor("#BA0C2F") if i == 3 else header_color)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(x + metric_w * (i + 0.5), metric_y + 8, value)

    rows = pdf_rows(lineup)
    col_widths = [w*.05, w*.39, w*.065, w*.08, w*.083, w*.083, w*.083, w*.083, w*.083]
    table_h = h - header_h - metric_h - 7
    row_h = table_h / len(rows)
    table = Table(rows, colWidths=col_widths, rowHeights=[row_h] * len(rows))

    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 5.6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#E2E2E2")),
        ("FONTSIZE", (0, 1), (-1, -2), 5.25),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF0FA")),
        ("TEXTCOLOR", (0, -1), (-1, -1), header_color),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 5.2),
    ])

    for row_index in range(1, len(rows) - 1):
        style.add("BACKGROUND", (0, row_index), (-1, row_index),
                  colors.white if row_index % 2 else colors.HexColor("#F7F8FB"))
        hand = rows[row_index][2]
        if hand == "L":
            style.add("TEXTCOLOR", (1, row_index), (1, row_index), colors.HexColor("#BA0C2F"))
            style.add("FONTNAME", (1, row_index), (1, row_index), "Helvetica-Bold")
        elif hand == "S":
            style.add("TEXTCOLOR", (1, row_index), (1, row_index), colors.HexColor("#0057B8"))
            style.add("FONTNAME", (1, row_index), (1, row_index), "Helvetica-Bold")

    table.setStyle(style)
    table.wrapOn(c, w, table_h)
    table.drawOn(c, x, y + 4)


def draw_report_header(c, page_w, page_h, logo_path, report_title, report_date, primary, accent):
    draw_logo(c, logo_path, 24, page_h - 80, 65, 54)
    c.setFillColor(primary)
    c.setFont("Helvetica-Bold", 23)
    c.drawCentredString(page_w / 2, page_h - 40, report_title.upper())
    c.setFont("Helvetica-Bold", 8.5)
    c.drawRightString(page_w - 24, page_h - 38, report_date.strftime("%b %d, %Y"))

    subtitle = "OPTIMIZED LINEUPS FOR EVERY SITUATION"
    c.setFillColor(colors.HexColor("#747A84"))
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(page_w / 2, page_h - 63, subtitle)
    text_w = c.stringWidth(subtitle, "Helvetica-Bold", 9)
    c.setFillColor(accent)
    c.rect(110, page_h - 61, page_w / 2 - text_w / 2 - 125, 2, fill=1, stroke=0)
    c.rect(page_w / 2 + text_w / 2 + 15, page_h - 61,
           page_w - 24 - (page_w / 2 + text_w / 2 + 15), 2, fill=1, stroke=0)


def draw_footer(c, page_w, logo_path, team_name, primary, accent):
    y, h = 24, 38
    c.setFillColor(primary)
    c.rect(24, y, page_w - 48, h, fill=1, stroke=0)
    draw_logo(c, logo_path, 32, y + 4, 35, 30)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(74, y + 22, team_name.upper())
    c.setFont("Helvetica", 7)
    c.drawString(74, y + 10, "BASEBALL OPERATIONS")
    c.setFont("Helvetica-Bold", 8.5)
    c.drawRightString(page_w - 55, y + 14, "Data-Driven Decisions. Better Results.")
    c.setFillColor(accent)
    c.rect(page_w - 48, y, 6, h, fill=1, stroke=0)


def generate_pdf(lineups, pitcher_info, team_name, report_title, report_date, logo_file, primary_rgb, accent_rgb):
    buffer = BytesIO()
    page_w, page_h = landscape(letter)
    c = canvas.Canvas(buffer, pagesize=landscape(letter))
    primary = colors.HexColor(rgb_to_hex(primary_rgb))
    accent = colors.HexColor(rgb_to_hex(accent_rgb))
    logo_path = save_uploaded_temp(logo_file, ".png") if logo_file else None

    # Page 1: the three general lineups.
    draw_report_header(c, page_w, page_h, logo_path, report_title, report_date, primary, accent)

    panel_y, panel_h, gap = 88, 415, 13
    panel_w = (page_w - 48 - 2 * gap) / 3
    headers = [primary, accent, primary]
    titles = ["OVERALL OPTIMAL LINEUP", "VS RIGHT-HANDED PITCHER", "VS LEFT-HANDED PITCHER"]
    keys = ["Overall", "Vs RHP", "Vs LHP"]

    for i, key in enumerate(keys):
        draw_lineup_panel(c, lineups[key], 24 + i * (panel_w + gap), panel_y, panel_w, panel_h, titles[i], headers[i])

    draw_footer(c, page_w, logo_path, team_name, primary, accent)
    c.showPage()

    # Page 2: pitcher-specific matchup.
    draw_report_header(c, page_w, page_h, logo_path, report_title, report_date, primary, accent)

    c.setFillColor(primary)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(30, page_h - 102, f"OPPONENT: {pitcher_info['name'].upper()} ({pitcher_info['hand']})")

    def usage_line(usage):
        return "   ".join(f"{key} {value:.1%}" for key, value in sorted(usage.items(), key=lambda x: x[1], reverse=True))

    c.setFillColor(colors.HexColor("#333333"))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(30, page_h - 121, "Usage vs RHH:")
    c.setFont("Helvetica", 8)
    c.drawString(98, page_h - 121, usage_line(pitcher_info["usage_vs_R"]))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(30, page_h - 136, "Usage vs LHH:")
    c.setFont("Helvetica", 8)
    c.drawString(98, page_h - 136, usage_line(pitcher_info["usage_vs_L"]))

    draw_lineup_panel(
        c, lineups["Vs Pitcher"], 90, 95, page_w - 180, 350,
        f"OPTIMAL LINEUP VS {pitcher_info['name'].upper()}", accent
    )

    c.setFillColor(colors.HexColor("#555555"))
    c.setFont("Helvetica", 7.5)
    c.drawCentredString(
        page_w / 2, 76,
        "Pitcher-specific selection: 60% overall production · 25% platoon split · 15% pitch-type matchup"
    )
    draw_footer(c, page_w, logo_path, team_name, primary, accent)
    c.showPage()
    c.save()

    if logo_path and os.path.exists(logo_path):
        try:
            os.remove(logo_path)
        except Exception:
            pass

    buffer.seek(0)
    return buffer


# ============================================================
# APP UI
# ============================================================

st.title("Lineup Optimization")
st.caption(
    "Upload one pitch-by-pitch Pregame CSV. The app calculates Overall, vs RHP, "
    "vs LHP, pitch-type splits, and an opponent-specific lineup."
)

with st.sidebar:
    st.header("Report Branding")
    team_name = st.text_input("Team Name", value="Texas Rangers")
    report_title = st.text_input("Report Title", value="Lineup Optimization Report")
    report_date = st.date_input("Report Date", value=date.today())
    team_logo = st.file_uploader("Team Logo", type=["png", "jpg", "jpeg"])

    st.divider()
    st.header("Stat Weights")
    weights = {
        "AVG": st.slider("AVG Weight", 0.0, 5.0, 1.0, 0.1),
        "OBP": st.slider("OBP Weight", 0.0, 5.0, 2.0, 0.1),
        "SLG": st.slider("SLG Weight", 0.0, 5.0, 2.0, 0.1),
        "ISO": st.slider("ISO Weight", 0.0, 5.0, 1.5, 0.1),
        "SB": st.slider("SB Weight", 0.0, 5.0, 0.8, 0.1),
    }

    st.divider()
    regression_pa = st.slider(
        "Pitch-type regression PA",
        1, 40, 12,
        help="Small pitch-type samples are pulled toward team average. Higher values apply more regression."
    )

    minimum_pa = st.number_input(
        "Minimum PA",
        min_value=0,
        max_value=1000,
        value=0,
        step=5,
        help=(
            "Eligibility is based on TOTAL plate appearances. "
            "Example: 50 means only hitters with 50+ total PA are eligible."
        ),
    )

primary_rgb, accent_rgb = extract_team_colors(team_logo)

st.markdown("### Data Source")
csv_source = st.radio(
    "CSV Source",
    ["Pregame Pitch-by-Pitch", "Lineup Optimizer Stats"],
    horizontal=True,
    help=(
        "Pregame Pitch-by-Pitch enables Overall, vs RHP, vs LHP, and opponent-specific lineups. "
        "Lineup Optimizer Stats uses the already-calculated PA/AVG/OBP/SLG/ISO/SB values for the Overall lineup."
    ),
)

col1, col2 = st.columns(2)
with col1:
    if csv_source == "Pregame Pitch-by-Pitch":
        hitter_file = st.file_uploader(
            "Pregame Pitch-by-Pitch CSV",
            type=["csv"],
            key="pregame_source_csv",
            help=(
                "Expected fields include batterAbbrevName, batterHand, pitcherHand, "
                "pitchType, pitchResult and BaseStealAtt."
            ),
        )
    else:
        hitter_file = st.file_uploader(
            "Lineup Optimizer CSV",
            type=["csv"],
            key="optimizer_source_csv",
            help=(
                "Expected fields include playerFullName, batsHand, PA, AVG, OBP, "
                "SLG, ISO and SB."
            ),
        )

with col2:
    pitcher_pdf = st.file_uploader(
        "Opponent Pitcher PDF",
        type=["pdf"],
        help="Used with the Pregame Pitch-by-Pitch source for the opponent-specific lineup.",
    )

if hitter_file is None:
    st.info(f"Upload the {csv_source} CSV to begin.")
    st.stop()

pitcher_info = None
pitcher_lineup = None
pitcher_pool = None
raw_df = None
terminal_df = None

if csv_source == "Pregame Pitch-by-Pitch":
    raw_df, terminal_df = prepare_pitch_by_pitch(hitter_file)
    if terminal_df is None:
        st.stop()

    overall_df_all = aggregate_stats(terminal_df)
    vs_rhp_df_all = aggregate_stats(terminal_df, pitcher_hand="R")
    vs_lhp_df_all = aggregate_stats(terminal_df, pitcher_hand="L")

    # Minimum PA qualification is based on TOTAL PA only.
    eligible_overall = overall_df_all[
        overall_df_all["PA"] >= minimum_pa
    ].copy()

    overall_df = eligible_overall.copy()

    def build_eligible_split(split_df, eligible_df):
        """
        Every player who qualifies by total PA stays eligible in each split.
        The split statistics themselves still reflect only that pitcher hand.
        """
        base = eligible_df[["playerFullName", "Bats"]].copy()
        split_columns = [
            "playerFullName", "PA", "AVG", "OBP", "SLG", "ISO", "SB"
        ]
        available = [
            column for column in split_columns if column in split_df.columns
        ]

        merged = base.merge(
            split_df[available],
            on="playerFullName",
            how="left",
        )

        for column in ["PA", "AVG", "OBP", "SLG", "ISO", "SB"]:
            if column not in merged.columns:
                merged[column] = 0
            merged[column] = pd.to_numeric(
                merged[column], errors="coerce"
            ).fillna(0)

        return merged[
            ["playerFullName", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB"]
        ]

    vs_rhp_df = build_eligible_split(vs_rhp_df_all, eligible_overall)
    vs_lhp_df = build_eligible_split(vs_lhp_df_all, eligible_overall)

    if len(overall_df) < 9:
        st.error(
            f"Only {len(overall_df)} hitters have {int(minimum_pa)}+ total PA. "
            "At least 9 qualified hitters are required to build a complete lineup."
        )
        st.stop()

    overall_lineup, overall_pool = build_standard_lineup(overall_df, weights)
    rhp_lineup, rhp_pool = build_standard_lineup(vs_rhp_df, weights)
    lhp_lineup, lhp_pool = build_standard_lineup(vs_lhp_df, weights)

    if pitcher_pdf is not None:
        pitcher_info = parse_pitcher_pdf(pitcher_pdf)
        if pitcher_info:
            split_df = (
                vs_rhp_df if pitcher_info["hand"] == "R" else vs_lhp_df
            )
            pitch_tables = build_pitch_type_tables(
                terminal_df,
                hitter_hand_context=pitcher_info["hand"],
            )
            pitcher_lineup, pitcher_pool = build_pitcher_specific_lineup(
                overall_df,
                split_df,
                pitch_tables,
                pitcher_info,
                weights,
                regression_pa,
            )

    available_modes = ["Overall", "Vs RHP", "Vs LHP", "Vs Uploaded Pitcher"]

else:
    overall_df_all = prepare_lineup_optimizer_csv(hitter_file)
    if overall_df_all is None:
        st.stop()

    overall_df = overall_df_all[
        overall_df_all["PA"] >= minimum_pa
    ].copy()

    if len(overall_df) < 9:
        st.error(
            f"Only {len(overall_df)} hitters have {int(minimum_pa)}+ total PA. "
            "At least 9 qualified hitters are required to build a complete lineup."
        )
        st.stop()

    overall_lineup, overall_pool = build_standard_lineup(overall_df, weights)
    rhp_lineup = rhp_pool = None
    lhp_lineup = lhp_pool = None

    available_modes = ["Overall"]

    if pitcher_pdf is not None:
        st.info(
            "The Lineup Optimizer Stats CSV contains overall statistics only. "
            "Use the Pregame Pitch-by-Pitch source to create vs RHP, vs LHP, "
            "or opponent-specific lineups."
        )

# Override the sidebar mode selector with modes supported by the selected data source.
lineup_mode = st.radio(
    "Lineup Type",
    available_modes,
    horizontal=True,
    key="supported_lineup_mode",
)

lineups = {"Overall": overall_lineup}

display_map = {
    "Overall": (
        overall_lineup,
        overall_pool,
        rgb_to_hex(primary_rgb),
    )
}

if csv_source == "Pregame Pitch-by-Pitch":
    lineups["Vs RHP"] = rhp_lineup
    lineups["Vs LHP"] = lhp_lineup

    display_map["Vs RHP"] = (
        rhp_lineup,
        rhp_pool,
        rgb_to_hex(accent_rgb),
    )
    display_map["Vs LHP"] = (
        lhp_lineup,
        lhp_pool,
        rgb_to_hex(primary_rgb),
    )

    if pitcher_lineup is not None:
        lineups["Vs Pitcher"] = pitcher_lineup
        display_map["Vs Uploaded Pitcher"] = (
            pitcher_lineup,
            pitcher_pool,
            rgb_to_hex(accent_rgb),
        )
    else:
        display_map["Vs Uploaded Pitcher"] = (
            None,
            None,
            rgb_to_hex(accent_rgb),
        )

selected_lineup, selected_pool, header_color = display_map[lineup_mode]

if lineup_mode == "Vs Uploaded Pitcher":
    if pitcher_pdf is None:
        st.info(
            "Upload the opponent pitcher PDF to create the pitcher-specific lineup."
        )
        st.stop()

    if pitcher_info is None or pitcher_lineup is None:
        st.error(
            "The opponent report could not be parsed well enough to create a lineup."
        )
        st.stop()

    render_pitcher_card(pitcher_info)

st.subheader(f"Optimized Lineup — {lineup_mode}")
st.caption(f"Eligibility filter: {int(minimum_pa)}+ total PA across all pitcher hands.")
render_lineup_table(selected_lineup, header_color)

with st.expander("Player Pool and Calculated Statistics"):
    pool_columns = [
        column for column in
        ["playerFullName", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB",
         "Overall Score", "Matchup Score", "Pitch Matchup Coverage"]
        if column in selected_pool.columns
    ]
    st.dataframe(
        selected_pool[pool_columns].sort_values(
            "Matchup Score" if "Matchup Score" in selected_pool.columns else "Overall Score",
            ascending=False,
        ),
        use_container_width=True,
        hide_index=True,
    )

st.markdown(
    """
    **Batting-hand legend:**  
    <span style="color:#BA0C2F;font-weight:800;">L = Left-handed</span> &nbsp; | &nbsp;
    <span style="color:#0057B8;font-weight:800;">S = Switch hitter</span> &nbsp; | &nbsp;
    <span style="color:#111111;font-weight:800;">R = Right-handed</span>
    """,
    unsafe_allow_html=True,
)

if (
    csv_source == "Pregame Pitch-by-Pitch"
    and pitcher_info
    and all(key in lineups for key in ["Overall", "Vs RHP", "Vs LHP", "Vs Pitcher"])
):
    pdf_buffer = generate_pdf(
        lineups=lineups,
        pitcher_info=pitcher_info,
        team_name=team_name,
        report_title=report_title,
        report_date=report_date,
        logo_file=team_logo,
        primary_rgb=primary_rgb,
        accent_rgb=accent_rgb,
    )
    st.download_button(
        "Export All 4 Lineups as PDF",
        data=pdf_buffer,
        file_name="lineup_optimization_report.pdf",
        mime="application/pdf",
        type="primary",
    )
else:
    if csv_source == "Pregame Pitch-by-Pitch":
        st.caption(
            "Upload an opponent pitcher PDF to enable the four-lineup PDF export."
        )
    else:
        st.caption(
            "Four-lineup PDF export requires the Pregame Pitch-by-Pitch source "
            "because the pre-calculated CSV does not contain pitcher-hand or pitch-type splits."
        )

st.info(
    "SB is credited when the play description explicitly identifies a successful base stealer. "
    "`BaseStealAtt` alone identifies the attempt but frequently belongs to the current batter rather than the runner."
)
