import math
import re
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

REQUIRED_STATS = ["AVG", "OBP", "SLG", "ISO", "SB"]
REQUIRED_ROLES = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH"]
POSITION_ROLE_DISPLAY = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH"]

# Based on common lineup-optimization principles inspired by The Book:
# #1 OBP/speed, #2 best overall bat, #3 strong bat, #4 power, #5 run producer,
# #6-#9 descending quality with small speed/OBP preferences.
SPOT_PROFILES: Dict[int, Dict[str, float]] = {
    1: {"AVG": 0.15, "OBP": 0.45, "SLG": 0.10, "ISO": 0.05, "SB": 0.25},
    2: {"AVG": 0.15, "OBP": 0.35, "SLG": 0.25, "ISO": 0.15, "SB": 0.10},
    3: {"AVG": 0.20, "OBP": 0.25, "SLG": 0.25, "ISO": 0.20, "SB": 0.10},
    4: {"AVG": 0.10, "OBP": 0.20, "SLG": 0.35, "ISO": 0.30, "SB": 0.05},
    5: {"AVG": 0.15, "OBP": 0.20, "SLG": 0.30, "ISO": 0.25, "SB": 0.10},
    6: {"AVG": 0.20, "OBP": 0.25, "SLG": 0.25, "ISO": 0.15, "SB": 0.15},
    7: {"AVG": 0.20, "OBP": 0.25, "SLG": 0.20, "ISO": 0.15, "SB": 0.20},
    8: {"AVG": 0.20, "OBP": 0.25, "SLG": 0.20, "ISO": 0.10, "SB": 0.25},
    9: {"AVG": 0.15, "OBP": 0.30, "SLG": 0.15, "ISO": 0.05, "SB": 0.35},
}


def find_player_column(df: pd.DataFrame) -> str:
    candidates = ["playerFullName", "PlayerFullName", "Player Full Name", "Player", "Name", "Player Name", "Hitter", "Batter"]
    lower_map = {c.lower().strip(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    return df.columns[0]


def find_position_column(df: pd.DataFrame) -> str | None:
    candidates = [
        "Position", "position", "POS", "Pos", "playerPosition", "Player Position",
        "Primary Position", "primaryPosition", "DefensivePosition", "defensivePosition"
    ]
    lower_map = {c.lower().strip(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower().strip() in lower_map:
            return lower_map[candidate.lower().strip()]
    return None


def is_bad_name_value(value) -> bool:
    if pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"none", "nan", "null", "na", "n/a", "#n/a"}


def build_player_display_name(df: pd.DataFrame, preferred_col: str) -> Tuple[pd.DataFrame, str]:
    """Create a clean display name column.

    Uses playerFullName first, but if a row has None/blank there, it falls back
    to other common name columns or combines first/last name columns.
    """
    df = df.copy()
    cols_by_lower = {str(c).lower().strip(): c for c in df.columns}

    display = df[preferred_col] if preferred_col in df.columns else pd.Series([pd.NA] * len(df), index=df.index)

    first_candidates = ["playerfirstname", "firstname", "first name", "first", "namefirst"]
    last_candidates = ["playerlastname", "lastname", "last name", "last", "namelast"]
    first_col = next((cols_by_lower[c] for c in first_candidates if c in cols_by_lower), None)
    last_col = next((cols_by_lower[c] for c in last_candidates if c in cols_by_lower), None)
    if first_col and last_col:
        combined = (df[first_col].fillna("").astype(str).str.strip() + " " + df[last_col].fillna("").astype(str).str.strip()).str.strip()
        display = display.where(~display.apply(is_bad_name_value), combined)

    fallback_cols = [
        "playerFullName", "PlayerFullName", "Player Full Name", "fullName", "FullName", "Full Name",
        "playerName", "PlayerName", "Player Name", "Player", "Name", "Hitter", "Batter"
    ]
    for col in fallback_cols:
        actual = cols_by_lower.get(col.lower().strip())
        if actual and actual in df.columns:
            display = display.where(~display.apply(is_bad_name_value), df[actual])

    df["Player Name"] = display.astype(str).str.strip()
    df = df[~df["Player Name"].apply(is_bad_name_value)]
    return df, "Player Name"


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def validate_data(df: pd.DataFrame, position_col: str | None) -> Tuple[bool, List[str]]:
    missing = [stat for stat in REQUIRED_STATS if stat not in df.columns]
    if position_col is None or position_col not in df.columns:
        missing.append("Position column")
    return len(missing) == 0, missing


def min_max_scale(series: pd.Series) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce")
    if series.isna().all():
        return pd.Series([0.0] * len(series), index=series.index)
    series = series.fillna(series.median())
    min_val = series.min()
    max_val = series.max()
    if math.isclose(max_val, min_val):
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - min_val) / (max_val - min_val)


def prepare_scores(df: pd.DataFrame, user_weights: Dict[str, float]) -> pd.DataFrame:
    scored = df.copy()
    for stat in REQUIRED_STATS:
        scored[f"{stat}_scaled"] = min_max_scale(scored[stat])

    total_weight = sum(user_weights.values()) or 1
    normalized_user_weights = {k: v / total_weight for k, v in user_weights.items()}

    scored["Overall Score"] = 0.0
    for stat in REQUIRED_STATS:
        scored["Overall Score"] += scored[f"{stat}_scaled"] * normalized_user_weights[stat]

    return scored


def spot_score(row: pd.Series, spot: int, user_weights: Dict[str, float]) -> float:
    profile = SPOT_PROFILES[spot]
    total_user_weight = sum(user_weights.values()) or 1
    score = 0.0
    for stat in REQUIRED_STATS:
        user_component = user_weights[stat] / total_user_weight
        spot_component = profile[stat]
        combined_weight = 0.65 * user_component + 0.35 * spot_component
        score += row[f"{stat}_scaled"] * combined_weight
    return float(score)


def parse_positions(value) -> set[str]:
    """Turn a position cell into a set of eligible positions.

    Examples handled: "SS", "OF", "LF/CF/RF", "1B,3B", "C / 1B", "IF/OF".
    IF is treated as 1B/2B/3B/SS, and LF/CF/RF are treated as OF.
    """
    if pd.isna(value):
        return set()
    text = str(value).upper().strip()
    tokens = [t for t in re.split(r"[^A-Z0-9]+", text) if t]
    positions = set()
    for token in tokens:
        if token in {"LF", "CF", "RF", "OF"}:
            positions.add("OF")
        elif token == "IF":
            positions.update({"1B", "2B", "3B", "SS"})
        elif token in {"C", "1B", "2B", "3B", "SS", "DH"}:
            positions.add(token)
    return positions


def role_eligible(row: pd.Series, role: str) -> bool:
    if role == "DH":
        return True
    return role in row["Eligible Positions"]


def choose_positionally_valid_roster(scored_df: pd.DataFrame) -> pd.DataFrame | None:
    """Pick 9 players while satisfying C, 1B, 2B, 3B, SS, OF, OF, OF, DH.

    The app uses a small backtracking search over top candidates for each role. This is much faster
    than trying every possible lineup but avoids obvious mistakes like using the only catcher at DH.
    """
    df = scored_df.copy().reset_index(drop=True)

    # Give repeated OF slots unique internal labels.
    role_instances = ["C", "1B", "2B", "3B", "SS", "OF_1", "OF_2", "OF_3", "DH"]

    def base_role(role_instance: str) -> str:
        return "OF" if role_instance.startswith("OF") else role_instance

    eligible_by_role = {}
    for role in role_instances:
        role_base = base_role(role)
        eligible = [idx for idx, row in df.iterrows() if role_eligible(row, role_base)]
        eligible = sorted(eligible, key=lambda idx: df.loc[idx, "Overall Score"], reverse=True)[:14]
        if not eligible:
            return None
        eligible_by_role[role] = eligible

    # Fill scarce positions first, DH last.
    role_order = sorted(role_instances, key=lambda r: (999 if r == "DH" else len(eligible_by_role[r]), r))
    best_assignment = None
    best_score = -1.0
    calls = 0
    max_calls = 75000

    max_remaining = {}
    for i, role in enumerate(role_order):
        remaining_roles = role_order[i:]
        max_remaining[i] = sum(df.loc[eligible_by_role[r], "Overall Score"].max() for r in remaining_roles)

    def search(i: int, used: set[int], assignment: dict[str, int], score: float):
        nonlocal best_assignment, best_score, calls
        calls += 1
        if calls > max_calls:
            return
        if i >= len(role_order):
            if score > best_score:
                best_score = score
                best_assignment = assignment.copy()
            return
        if score + max_remaining.get(i, 0) < best_score:
            return

        role = role_order[i]
        for idx in eligible_by_role[role]:
            if idx in used:
                continue
            used.add(idx)
            assignment[role] = idx
            search(i + 1, used, assignment, score + float(df.loc[idx, "Overall Score"]))
            used.remove(idx)
            assignment.pop(role, None)

    search(0, set(), {}, 0.0)

    if not best_assignment:
        return None

    rows = []
    for role in role_instances:
        idx = best_assignment[role]
        row = df.loc[idx].copy()
        row["Assigned Position"] = "OF" if role.startswith("OF") else role
        rows.append(row)
    roster = pd.DataFrame(rows).drop_duplicates(subset=["Player Name"]).reset_index(drop=True)
    return roster


def optimize_lineup(scored_df: pd.DataFrame, player_col: str, user_weights: Dict[str, float]) -> pd.DataFrame:
    candidates = scored_df.sort_values("Overall Score", ascending=False).reset_index(drop=True)

    fit_scores = {
        idx: {spot: spot_score(row, spot, user_weights) for spot in range(1, 10)}
        for idx, row in candidates.iterrows()
    }

    selected_indices = set()
    spot_priority = [2, 1, 4, 3, 5, 6, 7, 8, 9]
    assigned = {}

    for spot in spot_priority:
        available = [idx for idx in candidates.index if idx not in selected_indices]
        best_idx = max(available, key=lambda idx: fit_scores[idx][spot])
        assigned[spot] = best_idx
        selected_indices.add(best_idx)

    lineup_indices = [assigned[spot] for spot in range(1, 10)]
    lineup = candidates.loc[lineup_indices].copy().reset_index(drop=True)
    lineup.insert(0, "Lineup Spot", range(1, len(lineup) + 1))
    lineup["Spot Fit Score"] = [spot_score(lineup.iloc[i], i + 1, user_weights) for i in range(len(lineup))]

    display_cols = ["Lineup Spot", "Assigned Position", player_col] + REQUIRED_STATS + ["Overall Score", "Spot Fit Score"]
    return lineup[display_cols]


st.set_page_config(page_title="Baseball Lineup Optimizer", layout="wide")

st.title("⚾ Baseball Lineup Optimizer")
st.write(
    "Upload a CSV with your players, stats, and positions. The app will choose a valid lineup with "
    "1B, 2B, 3B, SS, three OF, C, and DH, then optimize the batting order."
)

with st.expander("CSV format needed", expanded=False):
    st.write("Your CSV should include a name column, a position column, and these stat columns:")
    st.code("playerFullName, Position, AVG, OBP, SLG, ISO, SB")
    st.write("Positions can be simple or multi-position, like SS, OF, C/1B, IF/OF, LF/CF/RF.")
    st.dataframe(
        pd.DataFrame({
            "playerFullName": ["Player A", "Player B", "Player C"],
            "Position": ["SS", "OF", "C/1B"],
            "AVG": [.285, .260, .300],
            "OBP": [.360, .330, .390],
            "SLG": [.460, .500, .430],
            "ISO": [.175, .240, .130],
            "SB": [12, 3, 20],
        }),
        hide_index=True,
    )

uploaded_file = st.file_uploader("Upload your CSV", type=["csv"])

st.sidebar.header("Stat Weights")
st.sidebar.write("Increase a stat if you want the optimizer to value it more.")
weights = {
    "AVG": st.sidebar.slider("AVG weight", 0.0, 5.0, 1.0, 0.25),
    "OBP": st.sidebar.slider("OBP weight", 0.0, 5.0, 2.0, 0.25),
    "SLG": st.sidebar.slider("SLG weight", 0.0, 5.0, 1.5, 0.25),
    "ISO": st.sidebar.slider("ISO weight", 0.0, 5.0, 1.0, 0.25),
    "SB": st.sidebar.slider("SB weight", 0.0, 5.0, 0.75, 0.25),
}

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    df = normalize_columns(df)
    player_col = find_player_column(df)
    detected_position_col = find_position_column(df)

    position_options = list(df.columns)
    default_index = position_options.index(detected_position_col) if detected_position_col in position_options else 0
    position_col = st.selectbox("Position column", position_options, index=default_index)

    is_valid, missing_cols = validate_data(df, position_col)
    if not is_valid:
        st.error(f"Your CSV is missing these required columns: {', '.join(missing_cols)}")
        st.stop()

    for stat in REQUIRED_STATS:
        df[stat] = pd.to_numeric(df[stat], errors="coerce")

    df = df.dropna(subset=REQUIRED_STATS, how="all")
    df, player_col = build_player_display_name(df, player_col)
    df["Eligible Positions"] = df[position_col].apply(parse_positions)
    df["Position"] = df[position_col].astype(str).str.strip()

    no_position = df[df["Eligible Positions"].apply(lambda x: len(x) == 0)]
    if len(no_position) > 0:
        st.warning(f"{len(no_position)} player(s) had blank/unrecognized positions and cannot be used except as DH.")

    if len(df) < 9:
        st.warning("Upload at least 9 players to create a full lineup.")
    else:
        scored = prepare_scores(df, weights)
        roster = choose_positionally_valid_roster(scored)

        if roster is None or len(roster) < 9:
            st.error("Could not build a valid lineup. Make sure your CSV has at least one C, 1B, 2B, 3B, SS, three OF, and enough extra players for DH.")
            st.stop()

        lineup = optimize_lineup(roster, player_col, weights)

        st.subheader("Optimized Lineup")
        st.dataframe(lineup, hide_index=True, use_container_width=True)

        csv = lineup.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download optimized lineup as CSV",
            csv,
            "optimized_lineup.csv",
            "text/csv",
        )

        st.subheader("Selected Roster by Position")
        roster_cols = ["Assigned Position", player_col, "Position"] + REQUIRED_STATS + ["Overall Score"]
        st.dataframe(roster[roster_cols].sort_values("Assigned Position"), hide_index=True, use_container_width=True)

        st.subheader("Player Rankings by Your Weights")
        ranking_cols = [player_col, "Position"] + REQUIRED_STATS + ["Overall Score"]
        rankings = scored[ranking_cols].sort_values("Overall Score", ascending=False)
        st.dataframe(rankings, hide_index=True, use_container_width=True)

        st.caption(
            "Note: The optimizer first selects a positionally valid roster, then optimizes batting order. "
            "DH can be any unused player. This is a decision-support tool, not a true run expectancy simulator."
        )
else:
    st.info("Upload a CSV to begin.")
