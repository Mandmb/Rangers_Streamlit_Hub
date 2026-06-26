import streamlit as st
import pandas as pd
import numpy as np
from itertools import combinations

st.set_page_config(page_title="Lineup Optimization", layout="wide")

# =====================================================
# HELPERS
# =====================================================

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
    total_weight = sum(weights.values())

    if total_weight == 0:
        total_weight = 1

    normalized = normalize_stats(df, REQUIRED_STATS)

    score = np.zeros(len(df))
    for stat, weight in weights.items():
        score += normalized[stat] * (weight / total_weight)

    return score


def calculate_spot_fit_score(row, spot, normalized_df, user_weights):
    spot_weights = LINEUP_SPOT_WEIGHTS[spot]

    combined_weights = {}
    for stat in REQUIRED_STATS:
        combined_weights[stat] = (spot_weights[stat] * 0.60) + (
            user_weights[stat] / max(sum(user_weights.values()), 1) * 0.40
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
                f"Not enough eligible players for {required_pos}. "
                f"Needed {count_needed}, found {len(eligible)}."
            )
            continue

        chosen = eligible.head(count_needed)
        selected_rows.append(chosen)
        used_indexes.update(chosen.index.tolist())

    if not selected_rows:
        return pd.DataFrame()

    selected = pd.concat(selected_rows)

    if len(selected) < 9:
        remaining = df[~df.index.isin(selected.index)].sort_values(
            "Overall Score", ascending=False
        )
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

    display_cols += REQUIRED_STATS + ["Overall Score", "Spot Fit Score"]

    return lineup[display_cols]


# =====================================================
# APP UI
# =====================================================

st.title("Lineup Optimization")
st.caption("Upload a CSV and optimize a batting lineup using adjustable stat weights.")

uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

if uploaded_file is None:
    st.info("Upload your CSV to begin.")
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

df = clean_colnames(df)

name_col = find_column(
    df,
    [
        "playerFullName",
        "PlayerFullName",
        "player_name",
        "playerName",
        "Name",
        "Player",
    ],
)

if name_col is None:
    st.error("Could not find a player name column. The app expects `playerFullName`.")
    st.stop()

df["playerFullName"] = df[name_col].astype(str).str.strip()

bad_names = ["", "none", "nan", "null", "unknown"]
df = df[~df["playerFullName"].str.lower().isin(bad_names)].copy()

missing_stats = [stat for stat in REQUIRED_STATS if stat not in df.columns]

if missing_stats:
    st.error(f"Missing required stat columns: {missing_stats}")
    st.write("Your CSV must include:", REQUIRED_STATS)
    st.stop()

for stat in REQUIRED_STATS:
    df[stat] = pd.to_numeric(df[stat], errors="coerce").fillna(0)

position_col = find_column(
    df,
    [
        "Position",
        "position",
        "POS",
        "pos",
        "PrimaryPosition",
        "primaryPosition",
    ],
)

if position_col:
    df["Position"] = df[position_col].apply(normalize_position)

bats_col = find_column(
    df,
    [
        "Bats",
        "bats",
        "BatSide",
        "batSide",
        "BatterSide",
        "batterSide",
        "HitterSide",
        "hitterSide",
        "Side",
        "side",
    ],
)

if bats_col:
    df["Bats"] = df[bats_col].astype(str).str.upper().str.strip()

st.sidebar.header("Stat Weights")

avg_weight = st.sidebar.slider("AVG Weight", 0.0, 5.0, 1.0, 0.1)
obp_weight = st.sidebar.slider("OBP Weight", 0.0, 5.0, 2.0, 0.1)
slg_weight = st.sidebar.slider("SLG Weight", 0.0, 5.0, 2.0, 0.1)
iso_weight = st.sidebar.slider("ISO Weight", 0.0, 5.0, 1.5, 0.1)
sb_weight = st.sidebar.slider("SB Weight", 0.0, 5.0, 0.8, 0.1)

weights = {
    "AVG": avg_weight,
    "OBP": obp_weight,
    "SLG": slg_weight,
    "ISO": iso_weight,
    "SB": sb_weight,
}

st.sidebar.divider()

enforce_positions = st.sidebar.checkbox(
    "Use position requirements",
    value=False,
    help="Optional. If checked, the app will try to include C, 1B, 2B, 3B, SS, 3 OF, and DH.",
)

if enforce_positions and not position_col:
    st.sidebar.warning("No position column found. Position requirements will be ignored.")
    enforce_positions = False

df["Overall Score"] = calculate_overall_score(df, weights)
df["Overall Score"] = df["Overall Score"].round(4)

st.subheader("Uploaded Player Pool")

preview_cols = ["playerFullName"]

if "Position" in df.columns:
    preview_cols.append("Position")

if "Bats" in df.columns:
    preview_cols.append("Bats")

preview_cols += REQUIRED_STATS + ["Overall Score"]

st.dataframe(
    df[preview_cols].sort_values("Overall Score", ascending=False),
    use_container_width=True,
    hide_index=True,
)

if st.button("Optimize Lineup", type="primary"):
    if len(df) < 9:
        st.error("You need at least 9 players in the CSV.")
        st.stop()

    if enforce_positions:
        selected = select_best_9_with_positions(df, "Position")
    else:
        selected = select_best_9_no_positions(df)

    if len(selected) < 9:
        st.error("Could not select 9 players. Check your player pool and positions.")
        st.stop()

    lineup = optimize_order(selected, weights)

    st.subheader("Optimized Lineup")

    def color_hitter_name(row):
        if "Bats" not in lineup.columns:
            return ""

        side = str(row["Bats"]).upper().strip()

        if side == "L":
            return "color: red; font-weight: bold;"
        elif side == "S":
            return "color: blue; font-weight: bold;"
        else:
            return "color: black;"

    styled_lineup = lineup.style.apply(
        lambda row: [
            color_hitter_name(row) if col == "playerFullName" else ""
            for col in lineup.columns
        ],
        axis=1,
    )

    st.dataframe(
        styled_lineup,
        use_container_width=True,
        hide_index=True,
    )

    csv = lineup.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download Optimized Lineup CSV",
        data=csv,
        file_name="optimized_lineup.csv",
        mime="text/csv",
    )

    st.markdown("### Lineup Notes")
    st.write(
        """
        - Position requirements are optional.
        - When position requirements are off, the app selects the best 9 offensive players.
        - When position requirements are on, the app attempts to include C, 1B, 2B, 3B, SS, 3 OF, and DH.
        - The batting order uses both your selected stat weights and spot-specific logic.
        """
    )
