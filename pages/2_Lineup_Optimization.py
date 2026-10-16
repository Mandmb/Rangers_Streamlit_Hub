
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
from reportlab.lib.pagesizes import landscape, letter, A3
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

    # A large league-wide export can contain several different players with
    # the same full name. Use the highest-PA row for each name, and let the
    # user explicitly choose which additional names to import.
    df = df.sort_values("PA", ascending=False).drop_duplicates(
        subset=["playerFullName"], keep="first"
    )
    # The provided export uses newestTeamLevel as its league identifier.
    league_col = find_column(df, ["newestTeamLevel", "newestTeam", "currentTeamLevel"])
    df["League"] = df[league_col].fillna("UNKNOWN").astype(str).str.strip().str.upper() if league_col else "UNKNOWN"
    df["Last Team"] = df["newestTeamName"].fillna("").astype(str) if "newestTeamName" in df.columns else ""
    return df[
        ["playerFullName", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB", "League", "Last Team"]
    ].reset_index(drop=True)


def lidom_translate(df, benchmarks):
    """League-relative rate translation, using user-provided league means.

    For rate r, translated r = r * (LIDOM mean / source mean).
    SB is translated as steals per PA, then restored to the same sample PA.
    This is an environment adjustment, not a calibrated talent projection.
    """
    result = df.copy()
    if "League" not in result.columns:
        result["League"] = "UNKNOWN"
    lidom = benchmarks.get("WIN")
    if not lidom:
        return result
    for idx, row in result.iterrows():
        source = benchmarks.get(str(row["League"]).upper())
        if not source:
            continue
        for stat in ("AVG", "OBP", "SLG"):
            denom = source.get(stat, 0)
            if denom > 0 and lidom.get(stat, 0) > 0:
                result.at[idx, stat] = float(row[stat]) * lidom[stat] / denom
        result.at[idx, "AVG"] = min(1.0, max(0.0, result.at[idx, "AVG"]))
        result.at[idx, "OBP"] = min(1.0, max(result.at[idx, "AVG"], result.at[idx, "OBP"]))
        result.at[idx, "SLG"] = max(result.at[idx, "AVG"], result.at[idx, "SLG"])
        result.at[idx, "ISO"] = max(0.0, result.at[idx, "SLG"] - result.at[idx, "AVG"])
        if source.get("SB_PA", 0) > 0 and lidom.get("SB_PA", 0) > 0:
            result.at[idx, "SB"] = max(0.0, float(row["SB"]) * lidom["SB_PA"] / source["SB_PA"])
    return result


def projected_runs_nine(lineup, team_pa=38.0):
    """Bill James basic RC=(H+BB)*TB/(AB+BB), approximated from rate data.
    Assumes PA=AB+BB and OBP=(H+BB)/PA; ignores HBP, SF, CS, etc.
    """
    if lineup is None or lineup.empty:
        return 0.0
    total = 0.0
    for _, p in lineup.iterrows():
        avg = float(p["AVG"]); obp = float(p["OBP"]); slg = float(p["SLG"])
        if avg >= 0.999:
            continue
        ab_fraction = max(0.0, min(1.0, (1 - obp) / (1 - avg)))
        hits = avg * ab_fraction
        walks = 1 - ab_fraction
        tb = slg * ab_fraction
        rc_per_pa = ((hits + walks) * tb)  # AB+BB = 1 normalized PA
        total += max(0.0, rc_per_pa) * (team_pa / 9.0)
    return total


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



def combine_extra_hitters(existing, extra, replace_existing=False):
    """Append missing hitters without silently double counting existing players."""
    if extra is None or extra.empty:
        return existing.copy()
    result = existing.copy()
    keys = set(result["playerFullName"].astype(str).str.strip().str.casefold())
    additions = extra[
        ~extra["playerFullName"].astype(str).str.strip().str.casefold().isin(keys)
    ].copy()
    return pd.concat([result, additions], ignore_index=True)


def supplement_split(split, combined_overall, original_names):
    """Use overall stats as a clearly identified fallback for supplemental hitters."""
    extra = combined_overall[
        ~combined_overall["playerFullName"].isin(original_names)
    ].copy()
    return combine_extra_hitters(split, extra)


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


def build_stats_only_pitcher_lineup(overall_df, pitcher_info, weights, opponent_weight=0.25):
    """Opponent-adjusted proxy: hitter overall quality plus pitcher's observed
    results allowed to the batter's effective side. Does not claim pitch-type
    or hitter platoon splits that the stats-only CSV does not provide.
    """
    scored = overall_df.copy()
    scored["Overall Component"] = weighted_offense_score(scored, weights)

    def allowed_number(side, stat):
        try:
            raw = pitcher_info.get(f"stats_vs_{side}", {}).get(stat, "")
            return float(str(raw).strip().replace("%", ""))
        except (ValueError, TypeError):
            return float("nan")

    # Opponent allowed OBP and SLG by hitter side, scaled to a relative
    # multiplier. Switch hitters face the pitcher from the opposite side.
    allowed = {}
    for side in ("R", "L"):
        obp = allowed_number(side, "OBP")
        slg = allowed_number(side, "SLG")
        allowed[side] = (obp + slg) if pd.notna(obp) and pd.notna(slg) else float("nan")

    valid = [v for v in allowed.values() if pd.notna(v)]
    neutral = sum(valid) / len(valid) if valid else 1.0

    def effective_bats(hand):
        hand = normalize_hand(hand)
        if hand == "S":
            return "L" if pitcher_info["hand"] == "R" else "R"
        return hand

    def vulnerability(hand):
        val = allowed.get(effective_bats(hand), float("nan"))
        if pd.isna(val) or neutral <= 0:
            return 1.0
        return max(0.75, min(1.25, val / neutral))

    scored["Opponent Factor"] = scored["Bats"].apply(vulnerability)
    scored["Matchup Score"] = scored["Overall Component"] * (
        (1.0 - opponent_weight) + opponent_weight * scored["Opponent Factor"]
    )
    scored["Overall Score"] = scored["Matchup Score"]
    selected = scored.sort_values("Matchup Score", ascending=False).head(9).copy()
    lineup = optimize_batting_order(selected, weights, score_column="Matchup Score")
    return lineup, scored


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



def ten_priority_scenarios(base_weights):
    """Two transparent sensitivity levels per priority, preserving other weights."""
    for stat in BASE_STATS:
        for level, multiplier in (("Focused", 2.0), ("Strong", 4.0)):
            modified = dict(base_weights)
            modified[stat] = max(1.0, modified[stat]) * multiplier
            yield stat, level, modified


def generate_ten_lineups_pdf(scenarios, team_name, report_date, logo_file,
                             primary_rgb, accent_rgb, opponent_name=None):
    """One landscape A3 sheet: five priorities, two alternatives per priority."""
    output = BytesIO()
    w, h = landscape(A3)
    c = canvas.Canvas(output, pagesize=(w, h))
    deep = colors.Color(*(v / 255 for v in primary_rgb))
    bright = colors.Color(*(v / 255 for v in accent_rgb))
    c.setFillColor(deep)
    c.rect(0, h - 91, w, 91, fill=1, stroke=0)
    logo_path = save_uploaded_temp(logo_file, ".png") if logo_file else None
    if logo_path:
        draw_logo(c, logo_path, 28, h - 79, 64, 65)
    left = 106 if logo_path else 34
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 21)
    c.drawString(left, h - 41, "LEONES DEL ESCOGIDO")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(left, h - 65, "10 OPTIMIZED LINEUPS | STAT PRIORITIES")
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 29, h - 35, str(report_date))
    subtitle = "Opponent: " + str(opponent_name) if opponent_name else "Overall player statistics"
    c.drawRightString(w - 29, h - 54, subtitle[:64])
    c.setFillColor(bright)
    c.rect(0, h - 95, w, 4, fill=1, stroke=0)

    margin, gutter = 25, 15
    panel_w = (w - 2 * margin - gutter) / 2
    panel_h, row_gap = 129, 9
    top = h - 110

    for index, (stat, level, lineup, weights_used) in enumerate(scenarios):
        col, row = index % 2, index // 2
        x = margin + col * (panel_w + gutter)
        y = top - (row + 1) * panel_h - row * row_gap
        c.setStrokeColor(colors.HexColor("#D5D9DF"))
        c.setFillColor(colors.white)
        c.roundRect(x, y, panel_w, panel_h, 5, fill=1, stroke=1)
        band = deep if level == "Focused" else bright
        c.setFillColor(band)
        c.roundRect(x, y + panel_h - 25, panel_w, 25, 5, fill=1, stroke=0)
        c.rect(x, y + panel_h - 25, panel_w, 5, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 10, y + panel_h - 17, f"{stat} PRIORITY  |  {level.upper()}")
        c.setFont("Helvetica", 7.5)
        weight_pct = 100 * weights_used[stat] / max(sum(weights_used.values()), 1)
        c.drawRightString(x + panel_w - 10, y + panel_h - 16,
                          f"Est. RC/9: {projected_runs_nine(lineup):.1f}  |  {weight_pct:.0f}%")
        c.setFillColor(colors.HexColor("#555D69"))
        c.setFont("Helvetica-Bold", 7)
        for tx, title in [(11, "#"), (32, "PLAYER"), (panel_w - 197, "B"),
                          (panel_w - 173, "PA"), (panel_w - 139, "AVG"),
                          (panel_w - 103, "OBP"), (panel_w - 67, "SLG"),
                          (panel_w - 31, "SB")]:
            c.drawString(x + tx, y + panel_h - 37, title)
        for i, (_, player) in enumerate(lineup.iterrows()):
            yy = y + panel_h - 48 - i * 8.75
            if i % 2 == 0:
                c.setFillColor(colors.HexColor("#F5F6F8"))
                c.rect(x + 5, yy - 2, panel_w - 10, 9, fill=1, stroke=0)
            hand = str(player.get("Bats", "R")).upper()
            c.setFillColor(colors.HexColor("#BA0C2F") if hand == "L" else
                           colors.HexColor("#0057B8") if hand == "S" else
                           colors.HexColor("#1E2530"))
            c.setFont("Helvetica", 7.3)
            c.drawString(x + 11, yy, str(i + 1))
            name = str(player["playerFullName"])
            # Truncate to avoid overlapping the stats columns.
            while c.stringWidth(name, "Helvetica", 7.3) > panel_w - 245 and len(name) > 3:
                name = name[:-1]
            if name != str(player["playerFullName"]):
                name = name[:-1] + "..."
            c.drawString(x + 32, yy, name)
            c.drawString(x + panel_w - 197, yy, hand)
            c.drawString(x + panel_w - 173, yy, str(int(player["PA"])))
            for offset, key in [(-139, "AVG"), (-103, "OBP"), (-67, "SLG")]:
                c.drawString(x + panel_w + offset, yy, f'{float(player[key]):.3f}')
            c.drawString(x + panel_w - 31, yy, str(int(player["SB"])))
    c.setFillColor(deep)
    c.rect(0, 0, w, 29, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 8)
    c.drawString(27, 11, "LHH red  |  Switch blue  |  RHH black")
    c.drawRightString(w - 27, 11,
                      "RC/9 estimated via Bill James basic RC; 38 team PA, rate-derived BB/AB; no sequencing model")
    c.save()
    output.seek(0)
    return output


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
    team_name = "Leones del Escogido"
    st.text_input("Team Name", value=team_name, disabled=True,
                  help="This report is branded for Leones del Escogido.")
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

# Fixed Leones del Escogido branding: deep red, red accent, white text.
# Logo upload is retained for the PDF header/footer but does not change colors.
primary_rgb = (139, 0, 27)   # Escogido deep red
accent_rgb = (206, 17, 38)   # Escogido bright red

st.markdown("### LIDOM Offensive Environment Translation")
# Official 2025-26 LIDOM regular-season team totals (MLB winter leagues).
# Source: https://www.mlb.com/ligas-invernales/stats/team/team
# Do not mark the 3-season benchmark complete until 2023-24 and 2024-25
# are independently verified with matching AB/H/2B/3B/HR/R/BB/SB and
# complete HBP/SF/PA counts for exact OBP and SB/PA.
LIDOM_VERIFIED_SEASONS = {
    "2025-26": {"AB": 9998, "H": 2472, "2B": 485, "3B": 49,
                "HR": 195, "R": 1414, "BB": 1171, "SB": 372,
                "team_games": 298, "source": "MLB winter league team stats"},
    # "2024-25": { ... },  # Awaiting verification
    # "2023-24": { ... },  # Awaiting verification
}
REQUIRED_LIDOM_SEASONS = ("2023-24", "2024-25", "2025-26")

def calculate_lidom_baseline(seasons):
    """Combine counting stats first; never average displayed season rates."""
    if any(year not in seasons for year in REQUIRED_LIDOM_SEASONS):
        return None
    keys = ("AB", "H", "2B", "3B", "HR", "R", "BB", "SB", "team_games")
    totals = {key: sum(seasons[year][key] for year in REQUIRED_LIDOM_SEASONS)
              for key in keys}
    if not totals["AB"] or not totals["team_games"]:
        return None
    tb = totals["H"] + totals["2B"] + 2 * totals["3B"] + 3 * totals["HR"]
    avg = totals["H"] / totals["AB"]
    slg = tb / totals["AB"]
    result = {"AVG": avg, "SLG": slg, "ISO": slg - avg,
              "R_G": totals["R"] / totals["team_games"]}
    # Exact OBP and SB/PA require HBP, SF and PA, respectively.
    if all(all(k in seasons[y] for k in ("HBP", "SF", "PA"))
           for y in REQUIRED_LIDOM_SEASONS):
        hbp = sum(seasons[y]["HBP"] for y in REQUIRED_LIDOM_SEASONS)
        sf = sum(seasons[y]["SF"] for y in REQUIRED_LIDOM_SEASONS)
        pa = sum(seasons[y]["PA"] for y in REQUIRED_LIDOM_SEASONS)
        result["OBP"] = ((totals["H"] + totals["BB"] + hbp) /
                         (totals["AB"] + totals["BB"] + hbp + sf))
        result["SB_PA"] = totals["SB"] / pa if pa else 0
    return result

BUILTIN_LEAGUE_BENCHMARKS = {
    # Populate verified 3-season league benchmarks for MLB/AAA/AAX/AFA/MEX.
    # A LIDOM reference is calculated automatically once all three seasons
    # above have complete, verified counting totals.
}
benchmarks = BUILTIN_LEAGUE_BENCHMARKS.copy()
lidom_baseline = calculate_lidom_baseline(LIDOM_VERIFIED_SEASONS)
if lidom_baseline and all(k in lidom_baseline for k in ("AVG", "OBP", "SLG", "SB_PA")):
    benchmarks["WIN"] = lidom_baseline

verified = LIDOM_VERIFIED_SEASONS["2025-26"]
with st.expander("Verified LIDOM reference data and model status", expanded=False):
    st.write("**Target seasons:** 2023-24, 2024-25, 2025-26 (regular season only)")
    st.write("**Verified so far:** " + ", ".join(LIDOM_VERIFIED_SEASONS))
    st.write("**2025-26:** AVG .247 | SLG .364 | ISO .117 | Runs/team game 4.74")
    st.caption("2025-26 MLB team totals: 9,998 AB, 2,472 H, 485 2B, "
               "49 3B, 195 HR, 1,414 R, 1,171 BB, 372 SB, 298 team games. "
               "Exact OBP requires HBP and SF; SB/PA requires PA.")
    st.markdown("[Source: MLB Winter Leagues team batting](https://www.mlb.com/ligas-invernales/stats/team/team)")
if "WIN" not in benchmarks or not any(k in benchmarks for k in ("MLB", "AAA", "AAX", "AFA", "MEX")):
    st.info("Three-season LIDOM translation is not fully calibrated yet. "
            "The app continues using original statistics; it does NOT label "
            "them LIDOM-equivalent. No additional CSV upload is required.")

st.markdown("### Data Source")
csv_source = st.radio(
    "CSV Source",
    ["Pregame Pitch-by-Pitch", "Lineup Optimizer Stats", "Additional Stats Only"],
    horizontal=True,
    help=(
        "Pregame Pitch-by-Pitch enables Overall, vs RHP, vs LHP, and opponent-specific lineups. "
        "Lineup Optimizer Stats uses the already-calculated PA/AVG/OBP/SLG/ISO/SB values for the Overall lineup."
    ),
)

col1, col2 = st.columns(2)
with col1:
    if csv_source == "Additional Stats Only":
        hitter_file = None
        st.info("Upload your player stats in the Additional Players Stats CSV field below. No Pregame CSV is needed.")
    elif csv_source == "Pregame Pitch-by-Pitch":
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
        help="Works with either pitch-by-pitch data or the additional stats CSV. Stats-only matchups use the pitcher's allowed splits.",
    )

extra_file = st.file_uploader(
    "Additional Players Stats CSV (can be used alone)",
    type=["csv"],
    key="extra_players_csv",
    help="Add players absent from the main file. Required: playerFullName, PA, AVG, OBP, SLG, ISO, SB. Optional: batsHand.",
)
extra_stats = prepare_lineup_optimizer_csv(extra_file) if extra_file is not None else None
if extra_stats is not None and "WIN" in benchmarks:
    extra_stats = lidom_translate(extra_stats, benchmarks)
if extra_file is not None and extra_stats is None:
    st.stop()
if extra_stats is not None:
    if hitter_file is None:
        # Standalone mode: automatically import every valid hitter in the CSV.
        # Roster selection below is the single place to exclude players.
        st.caption(f"Loaded {len(extra_stats)} hitters from the Additional Players Stats CSV. Use Eligible Players below to exclude anyone.")
    else:
        st.caption("Select supplemental hitters to import. Duplicate names use the highest-PA record.")
        extra_choices = st.multiselect(
            "Additional players to import",
            options=sorted(extra_stats["playerFullName"].tolist(), key=str.casefold),
            default=[],
            key="additional_player_names",
        )
        extra_stats = extra_stats[extra_stats["playerFullName"].isin(extra_choices)].copy()

# The optional stats upload can also serve as a standalone data source.
# This preserves the usual Pregame + supplemental workflow when both exist.
stats_only_from_additional = hitter_file is None and extra_stats is not None and not extra_stats.empty
if hitter_file is None and not stats_only_from_additional:
    if extra_file is not None and extra_stats is not None and extra_stats.empty:
        st.info("No valid hitters were found in the uploaded additional stats CSV.")
    else:
        st.info("Upload an Additional Players Stats CSV to build a standalone lineup, or upload a main CSV.")
    st.stop()
if stats_only_from_additional:
    st.success("Stats-only mode: building the optimized lineup from your Additional Players Stats CSV.")
    csv_source = "Lineup Optimizer Stats"

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

    original_names = set(overall_df_all["playerFullName"])
    if extra_stats is not None:
        original_count = len(overall_df_all)
        overall_df_all = combine_extra_hitters(overall_df_all, extra_stats)
        st.caption(f"Added {len(overall_df_all) - original_count} additional hitters not present in the main CSV.")
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
    # Supplemental hitters have only overall statistics, so use those as
    # provisional split estimates rather than falsely assigning zero production.
    for split_frame in (vs_rhp_df, vs_lhp_df):
        missing = ~split_frame["playerFullName"].isin(original_names)
        if missing.any():
            lookup = (eligible_overall.sort_values("PA", ascending=False)
                      .drop_duplicates("playerFullName")
                      .set_index("playerFullName"))
            for stat in ["PA", "AVG", "OBP", "SLG", "ISO", "SB"]:
                split_frame.loc[missing, stat] = split_frame.loc[missing, "playerFullName"].map(lookup[stat]).values

    all_names = sorted(overall_df["playerFullName"].astype(str).unique().tolist(), key=str.casefold)
    chosen = st.multiselect(
        "Eligible Players — select or deselect",
        options=all_names,
        default=all_names,
        key="eligible_player_selection",
        help="Deselected players are removed from every lineup and the exported report.",
    )
    if len(chosen) < 9:
        st.warning(f"Select at least 9 players to build a complete lineup ({len(chosen)} currently selected).")
        st.stop()
    overall_df = overall_df[overall_df["playerFullName"].isin(chosen)].copy()
    overall_lineup, overall_pool = build_standard_lineup(overall_df, weights)
    vs_rhp_df = vs_rhp_df[vs_rhp_df["playerFullName"].isin(chosen)].copy()
    vs_lhp_df = vs_lhp_df[vs_lhp_df["playerFullName"].isin(chosen)].copy()
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
    if stats_only_from_additional:
        overall_df_all = extra_stats.copy()
        # Already selected in the optional uploader; don't merge it a second time.
        extra_stats = None
    else:
        overall_df_all = prepare_lineup_optimizer_csv(hitter_file)
        if overall_df_all is None:
            st.stop()
        if "WIN" in benchmarks:
            overall_df_all = lidom_translate(overall_df_all, benchmarks)

    if extra_stats is not None:
        original_count = len(overall_df_all)
        overall_df_all = combine_extra_hitters(overall_df_all, extra_stats)
        st.caption(f"Added {len(overall_df_all) - original_count} additional hitters not present in the main CSV.")
    overall_df = overall_df_all[
        overall_df_all["PA"] >= minimum_pa
    ].copy()

    all_names = sorted(overall_df["playerFullName"].astype(str).unique().tolist(), key=str.casefold)
    chosen = st.multiselect(
        "Eligible Players — select or deselect",
        options=all_names,
        default=all_names,
        key="eligible_player_selection",
        help="Deselected players are removed from every lineup and the exported report.",
    )
    if len(chosen) < 9:
        st.warning(f"Select at least 9 players to build a complete lineup ({len(chosen)} currently selected).")
        st.stop()
    overall_df = overall_df[overall_df["playerFullName"].isin(chosen)].copy()
    overall_lineup, overall_pool = build_standard_lineup(overall_df, weights)
    rhp_lineup = rhp_pool = None
    lhp_lineup = lhp_pool = None

    available_modes = ["Overall"]
    if pitcher_pdf is not None:
        pitcher_info = parse_pitcher_pdf(pitcher_pdf)
        if pitcher_info is not None:
            pitcher_lineup, pitcher_pool = build_stats_only_pitcher_lineup(
                overall_df, pitcher_info, weights
            )
            available_modes.append("Vs Uploaded Pitcher")
            st.caption(
                "Opponent-specific lineup uses overall hitter stats plus the pitcher's "
                "OBP/SLG allowed to each batting side. No hitter pitch-type or platoon "
                "splits are inferred."
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
elif csv_source == "Pregame Pitch-by-Pitch":
    display_map["Vs Uploaded Pitcher"] = (
        None, None, rgb_to_hex(accent_rgb)
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

if extra_stats is not None and csv_source == "Pregame Pitch-by-Pitch":
    st.caption("Additional hitters use overall stats as provisional vs-RHP/vs-LHP estimates; pitch-type matchup defaults to neutral without pitch-level data.")
st.subheader(f"Optimized Lineup — {lineup_mode}")
st.caption(f"Eligibility filter: {int(minimum_pa)}+ total PA across all pitcher hands.")
render_lineup_table(selected_lineup, header_color)

with st.expander("Player Pool and Calculated Statistics"):
    pool_columns = [
        column for column in
        ["playerFullName", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB",
         "League", "Last Team", "Overall Score", "Matchup Score", "Pitch Matchup Coverage"]
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

st.divider()
st.subheader("10-Lineup Priority Comparison")
st.caption("Projected RC/9 uses Bill James's basic Runs Created, estimated from AVG/OBP/SLG and 38 team PA. It is a lineup-level rate estimate, not a batting-order simulation. League normalization is applied only where benchmark data are supplied.")
st.caption(
    "Two scenarios for each of AVG, OBP, SLG, ISO and SB. Focused = 2× "
    "that statistic's current weight; Strong = 4×. All other weights stay "
    "unchanged. The report fits all 10 lineups on one landscape A3 page."
)
compare_opponent = st.checkbox(
    "Optimize the 10 lineups against the uploaded opposing pitcher",
    value=pitcher_info is not None,
    disabled=pitcher_info is None,
)
if st.button("Prepare 10-Lineup PDF", type="primary"):
    try:
        comparison = []
        for priority, level, scenario_weights in ten_priority_scenarios(weights):
            if compare_opponent and pitcher_info is not None:
                if csv_source == "Pregame Pitch-by-Pitch":
                    pitcher_split = vs_rhp_df if pitcher_info["hand"] == "R" else vs_lhp_df
                    scenario_pitches = build_pitch_type_tables(
                        terminal_df, hitter_hand_context=pitcher_info["hand"]
                    )
                    lineup_variant, _ = build_pitcher_specific_lineup(
                        overall_df, pitcher_split, scenario_pitches,
                        pitcher_info, scenario_weights, regression_pa
                    )
                else:
                    lineup_variant, _ = build_stats_only_pitcher_lineup(
                        overall_df, pitcher_info, scenario_weights
                    )
            else:
                lineup_variant, _ = build_standard_lineup(overall_df, scenario_weights)
            comparison.append((priority, level, lineup_variant, scenario_weights))
        pdf_ten = generate_ten_lineups_pdf(
            comparison, team_name, report_date, team_logo,
            primary_rgb, accent_rgb,
            opponent_name=pitcher_info.get("name", "Uploaded pitcher")
            if compare_opponent and pitcher_info else None
        )
        st.session_state["ten_lineup_pdf"] = pdf_ten.getvalue()
    except Exception as exc:
        st.error(f"Could not generate the comparison PDF: {exc}")
if "ten_lineup_pdf" in st.session_state:
    st.download_button(
        "Download 10 Optimized Lineups (One-Page PDF)",
        data=st.session_state["ten_lineup_pdf"],
        file_name="escogido_10_optimized_lineups.pdf",
        mime="application/pdf",
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
            "Stats-only mode can optimize Overall and vs Uploaded Pitcher. "
            "The four-lineup PDF requires pitch-by-pitch data for true hitter splits."
        )

st.info(
    "SB is credited when the play description explicitly identifies a successful base stealer. "
    "`BaseStealAtt` alone identifies the attempt but frequently belongs to the current batter rather than the runner."
)
