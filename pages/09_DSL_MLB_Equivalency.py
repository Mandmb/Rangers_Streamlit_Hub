
import math
import re
from io import BytesIO

import numpy as np
import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="DSL → MLB Equivalencies",
    page_icon="⚾",
    layout="wide",
)

RANGERS_BLUE = "#002D72"
RANGERS_RED = "#BA0C2F"
NAVY = "#071B33"
INK = "#172033"
MUTED = "#667085"
LIGHT_BLUE = "#EAF1FA"
LIGHT_RED = "#FCECEF"
WHITE = "#FFFFFF"

st.markdown(
    f"""
    <style>
        .stApp {{
            background:
                radial-gradient(circle at top right, rgba(0,45,114,.10), transparent 28rem),
                linear-gradient(180deg, #F7F9FC 0%, #EEF2F7 100%);
        }}
        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, {NAVY} 0%, {RANGERS_BLUE} 100%);
        }}
        [data-testid="stSidebar"] * {{
            color: white !important;
        }}
        .block-container {{
            max-width: 1500px;
            padding-top: 1.4rem;
            padding-bottom: 3rem;
        }}
        .hero {{
            background: linear-gradient(120deg, {NAVY} 0%, {RANGERS_BLUE} 72%, {RANGERS_RED} 130%);
            border-radius: 22px;
            padding: 28px 32px;
            color: white;
            box-shadow: 0 16px 35px rgba(7,27,51,.18);
            margin-bottom: 18px;
        }}
        .hero h1 {{
            margin: 0;
            font-size: 2.15rem;
            line-height: 1.05;
            letter-spacing: -.03em;
        }}
        .hero p {{
            margin: 10px 0 0 0;
            opacity: .88;
            font-size: 1rem;
        }}
        .section-title {{
            font-weight: 800;
            font-size: 1.15rem;
            color: {NAVY};
            margin: 12px 0 8px 0;
        }}
        .model-card {{
            background: white;
            border: 1px solid #DDE3EC;
            border-radius: 18px;
            padding: 18px;
            box-shadow: 0 9px 24px rgba(16,24,40,.07);
        }}
        .note {{
            border-left: 5px solid {RANGERS_RED};
            background: {LIGHT_RED};
            border-radius: 10px;
            padding: 12px 14px;
            color: {INK};
        }}
        .small-note {{
            color: {MUTED};
            font-size: .88rem;
        }}
        div[data-testid="stMetric"] {{
            background: white;
            border: 1px solid #DFE5EE;
            border-radius: 16px;
            padding: 12px 14px;
            box-shadow: 0 6px 16px rgba(16,24,40,.05);
        }}
        div[data-testid="stMetricLabel"] {{
            color: {MUTED};
        }}
        div[data-testid="stMetricValue"] {{
            color: {NAVY};
        }}
        .stTabs [data-baseweb="tab-list"] {{
            gap: 8px;
        }}
        .stTabs [data-baseweb="tab"] {{
            border-radius: 12px 12px 0 0;
            padding: 10px 18px;
            font-weight: 700;
        }}
        .stButton button, .stDownloadButton button {{
            border-radius: 11px;
            font-weight: 700;
        }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <h1>DSL → MLB Equivalencies</h1>
        <p>Translate a hitter's current DSL production into estimated Complex, Single-A, and Major League equivalents.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# Model assumptions learned from the supplied 2024–2026 dataset.
# DSL→Complex and Complex→A are empirical matched-player estimates.
# A→MLB is provisional, inferred from the adjusted/MLE example supplied.
# ---------------------------------------------------------------------

MODEL = {
    "AVG":  {"dsl_avg": 0.2450764787, "prior_pa": 200, "kind": "logit",
             "dsl_complex": -0.1093714652, "complex_a": -0.2619545344, "a_mlb": -0.2056024667},
    "OBP":  {"dsl_avg": 0.3779084691, "prior_pa": 200, "kind": "logit",
             "dsl_complex": -0.1377167422, "complex_a": -0.2611053822, "a_mlb": -0.3613313845},
    "SLG":  {"dsl_avg": 0.3518080947, "prior_pa": 250, "kind": "log",
             "dsl_complex": -0.0691217152, "complex_a": -0.2366810159, "a_mlb": -0.2376514655},
    "OPS":  {"dsl_avg": 0.7297073935, "prior_pa": 250, "kind": "log",
             "dsl_complex": -0.0762161898, "complex_a": -0.2036886003, "a_mlb": -0.2455554359},
    "ISO":  {"dsl_avg": 0.1067498424, "prior_pa": 300, "kind": "log",
             "dsl_complex": -0.0496062982, "complex_a": -0.3432190891, "a_mlb": -0.4552523974},
    "BB%":  {"dsl_avg": 0.1484243980, "prior_pa": 100, "kind": "logit",
             "dsl_complex": -0.1243257912, "complex_a": -0.1869968697, "a_mlb": -0.6746210831},
    "K%":   {"dsl_avg": 0.2077629938, "prior_pa": 75, "kind": "logit",
             "dsl_complex": 0.3334966619, "complex_a": 0.2241060833, "a_mlb": 0.4643489386},
    "wOBA": {"dsl_avg": 0.3323409491, "prior_pa": 250, "kind": "logit",
             "dsl_complex": -0.1049182790, "complex_a": -0.2702404048, "a_mlb": -0.3248871067},
}

ALIASES = {
    "Player": ["playerFullName", "Player", "Name", "player", "Player Name", "Batter"],
    "Season": ["season", "Season", "Year", "year"],
    "Age": ["Age", "age"],
    "PA": ["PA", "Plate Appearances", "PlateAppearances", "plateAppearances"],
    "AVG": ["BA", "AVG", "Avg", "Batting Average"],
    "OBP": ["OBP", "On Base Percentage", "OnBasePercentage"],
    "SLG": ["SLG", "Slugging", "Slugging Percentage"],
    "OPS": ["OPS"],
    "ISO": ["ISO"],
    "BB%": ["BB%", "BBPct", "BB Pct", "Walk%", "Walk Rate"],
    "K%": ["K%", "SO%", "KPct", "K Pct", "Strikeout%", "Strikeout Rate"],
    "wOBA": ["wOBA", "WOBA"],
}


def first_matching_column(df: pd.DataFrame, names: list[str]) -> str | None:
    normalized = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        key = name.strip().lower()
        if key in normalized:
            return normalized[key]
    return None


def clean_number(value, percentage=False):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    text = str(value).strip().replace(",", "")
    if not text:
        return np.nan
    had_pct = "%" in text
    text = text.replace("%", "")
    try:
        number = float(text)
    except ValueError:
        return np.nan
    if percentage and (had_pct or number > 1):
        number /= 100.0
    return number


def logit(p: float) -> float:
    p = min(max(float(p), 1e-7), 1 - 1e-7)
    return math.log(p / (1 - p))


def inv_logit(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def regress_rate(value: float, pa: float, dsl_avg: float, prior_pa: float) -> float:
    return ((value * pa) + (dsl_avg * prior_pa)) / (pa + prior_pa)


def translate(value: float, delta: float, kind: str) -> float:
    if kind == "logit":
        return inv_logit(logit(value) + delta)
    if value <= 0:
        return 0.0
    return value * math.exp(delta)


def calculate_equivalencies(inputs: dict, pa: float) -> pd.DataFrame:
    records = []
    for metric, cfg in MODEL.items():
        raw = float(inputs[metric])
        regressed = regress_rate(raw, pa, cfg["dsl_avg"], cfg["prior_pa"])
        complex_eq = translate(regressed, cfg["dsl_complex"], cfg["kind"])
        a_eq = translate(complex_eq, cfg["complex_a"], cfg["kind"])
        mlb_eq = translate(a_eq, cfg["a_mlb"], cfg["kind"])
        records.append({
            "Metric": metric,
            "DSL Actual": raw,
            "Regressed DSL": regressed,
            "Complex Eq.": complex_eq,
            "Single-A Eq.": a_eq,
            "MLB Eq.": mlb_eq,
        })
    return pd.DataFrame(records)


def normalize_uploaded_data(raw: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=raw.index)
    for target, aliases in ALIASES.items():
        col = first_matching_column(raw, aliases)
        if col is not None:
            out[target] = raw[col]

    if "Player" not in out:
        out["Player"] = [f"Player {i+1}" for i in range(len(raw))]
    if "Season" not in out:
        out["Season"] = ""
    if "Age" not in out:
        out["Age"] = np.nan

    required = ["PA", "AVG", "OBP", "SLG"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(missing))

    out["PA"] = out["PA"].map(clean_number)
    for stat in ["AVG", "OBP", "SLG", "OPS", "ISO", "wOBA"]:
        if stat in out:
            out[stat] = out[stat].map(clean_number)
    for stat in ["BB%", "K%"]:
        if stat in out:
            out[stat] = out[stat].map(lambda x: clean_number(x, percentage=True))

    if "OPS" not in out:
        out["OPS"] = out["OBP"] + out["SLG"]
    if "ISO" not in out:
        out["ISO"] = out["SLG"] - out["AVG"]
    if "wOBA" not in out:
        # Displayed clearly as an estimate when not present.
        out["wOBA"] = np.nan

    return out


def display_value(metric: str, value: float) -> str:
    if pd.isna(value):
        return "—"
    if metric in ("BB%", "K%"):
        return f"{value:.1%}"
    return f"{value:.3f}".replace("0.", ".")


def styled_table(df: pd.DataFrame):
    shown = df.copy()
    for col in shown.columns[1:]:
        shown[col] = [
            display_value(metric, val)
            for metric, val in zip(shown["Metric"], shown[col])
        ]
    return shown


def downloadable_results(df: pd.DataFrame, player: str, season, age, pa) -> bytes:
    export = df.copy()
    export.insert(0, "Player", player)
    export.insert(1, "Season", season)
    export.insert(2, "Age", age)
    export.insert(3, "PA", pa)
    return export.to_csv(index=False).encode("utf-8")


upload_tab, manual_tab, method_tab = st.tabs(
    ["Upload Player CSV", "Manual Entry", "Model Methodology"]
)

with upload_tab:
    left, right = st.columns([0.72, 0.28], gap="large")

    with left:
        uploaded = st.file_uploader(
            "Upload a CSV containing one or more DSL hitters",
            type=["csv"],
            help="Required columns: PA, AVG/BA, OBP and SLG. BB%, K%, OPS, ISO and wOBA are recommended.",
        )

    with right:
        st.markdown(
            """
            <div class="note">
                <b>Best results:</b><br>
                PA, AVG, OBP, SLG, OPS, ISO, BB%, K%, and wOBA.
            </div>
            """,
            unsafe_allow_html=True,
        )

    if uploaded is not None:
        try:
            raw_df = pd.read_csv(uploaded)
            player_df = normalize_uploaded_data(raw_df)
            player_df = player_df[player_df["PA"].notna() & (player_df["PA"] > 0)].reset_index(drop=True)

            if player_df.empty:
                st.error("No valid player rows with plate appearances were found.")
            else:
                selector_cols = st.columns([0.44, 0.18, 0.18, 0.20])
                labels = []
                for i, row in player_df.iterrows():
                    year_text = f" — {row['Season']}" if str(row["Season"]).strip() else ""
                    labels.append(f"{row['Player']}{year_text} [{i + 1}]")

                selected_label = selector_cols[0].selectbox("Player", labels)
                selected_index = int(re.search(r"\[(\d+)\]$", selected_label).group(1)) - 1
                selected = player_df.iloc[selected_index]

                season = selector_cols[1].text_input("Season", value=str(selected.get("Season", "")))
                age_default = 0 if pd.isna(selected.get("Age")) else int(round(float(selected["Age"])))
                age = selector_cols[2].number_input("Age", min_value=0, max_value=50, value=age_default)
                pa = selector_cols[3].number_input(
                    "Plate Appearances",
                    min_value=1,
                    value=max(1, int(round(float(selected["PA"])))),
                )

                metric_inputs = {}
                missing_optional = []
                for metric in MODEL:
                    val = selected.get(metric, np.nan)
                    if pd.isna(val):
                        missing_optional.append(metric)
                        val = MODEL[metric]["dsl_avg"]
                    metric_inputs[metric] = float(val)

                if missing_optional:
                    st.warning(
                        "Missing values were replaced with the DSL model average for: "
                        + ", ".join(missing_optional)
                        + ". Uploading those statistics will improve the output."
                    )

                results = calculate_equivalencies(metric_inputs, pa)

                st.markdown('<div class="section-title">Major League Equivalent Snapshot</div>', unsafe_allow_html=True)
                metric_map = results.set_index("Metric")["MLB Eq."].to_dict()
                snapshot_cols = st.columns(6)
                for col, metric in zip(snapshot_cols, ["AVG", "OBP", "SLG", "OPS", "BB%", "K%"]):
                    col.metric(metric, display_value(metric, metric_map[metric]))

                st.markdown('<div class="section-title">Level-by-Level Translation</div>', unsafe_allow_html=True)
                st.dataframe(
                    styled_table(results),
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Metric": st.column_config.TextColumn(width="small"),
                    },
                )

                chart_df = results[
                    results["Metric"].isin(["AVG", "OBP", "SLG", "OPS", "wOBA"])
                ].set_index("Metric")[["DSL Actual", "Regressed DSL", "Complex Eq.", "Single-A Eq.", "MLB Eq."]].T
                st.line_chart(chart_df, use_container_width=True)

                filename_player = re.sub(r"[^A-Za-z0-9_-]+", "_", str(selected["Player"])).strip("_")
                st.download_button(
                    "Download Equivalency Results",
                    data=downloadable_results(results, str(selected["Player"]), season, age, pa),
                    file_name=f"{filename_player or 'player'}_DSL_MLB_equivalencies.csv",
                    mime="text/csv",
                )
        except Exception as exc:
            st.error(f"Could not process the uploaded CSV: {exc}")

with manual_tab:
    st.markdown('<div class="section-title">Enter a DSL Stat Line</div>', unsafe_allow_html=True)

    identity = st.columns([0.38, 0.20, 0.18, 0.24])
    player_name = identity[0].text_input("Player Name", value="DSL Player")
    season_manual = identity[1].number_input("Season", min_value=2000, max_value=2100, value=2026)
    age_manual = identity[2].number_input("Age", min_value=14, max_value=40, value=18)
    pa_manual = identity[3].number_input("Plate Appearances", min_value=1, max_value=1000, value=200)

    stat_cols = st.columns(4)
    manual_inputs = {
        "AVG": stat_cols[0].number_input("AVG", min_value=0.000, max_value=1.000, value=0.280, step=0.001, format="%.3f"),
        "OBP": stat_cols[1].number_input("OBP", min_value=0.000, max_value=1.000, value=0.370, step=0.001, format="%.3f"),
        "SLG": stat_cols[2].number_input("SLG", min_value=0.000, max_value=2.000, value=0.420, step=0.001, format="%.3f"),
        "OPS": stat_cols[3].number_input("OPS", min_value=0.000, max_value=3.000, value=0.790, step=0.001, format="%.3f"),
    }

    stat_cols_2 = st.columns(4)
    manual_inputs.update({
        "ISO": stat_cols_2[0].number_input("ISO", min_value=0.000, max_value=1.000, value=0.140, step=0.001, format="%.3f"),
        "BB%": stat_cols_2[1].number_input("BB%", min_value=0.0, max_value=100.0, value=12.0, step=0.1) / 100,
        "K%": stat_cols_2[2].number_input("K%", min_value=0.0, max_value=100.0, value=20.0, step=0.1) / 100,
        "wOBA": stat_cols_2[3].number_input("wOBA", min_value=0.000, max_value=1.000, value=0.360, step=0.001, format="%.3f"),
    })

    manual_results = calculate_equivalencies(manual_inputs, pa_manual)
    manual_map = manual_results.set_index("Metric")["MLB Eq."].to_dict()

    st.markdown('<div class="section-title">Major League Equivalent Snapshot</div>', unsafe_allow_html=True)
    manual_snapshot = st.columns(6)
    for col, metric in zip(manual_snapshot, ["AVG", "OBP", "SLG", "OPS", "BB%", "K%"]):
        col.metric(metric, display_value(metric, manual_map[metric]))

    st.dataframe(styled_table(manual_results), hide_index=True, use_container_width=True)

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", player_name).strip("_")
    st.download_button(
        "Download Equivalency Results",
        data=downloadable_results(manual_results, player_name, season_manual, age_manual, pa_manual),
        file_name=f"{safe_name or 'player'}_DSL_MLB_equivalencies.csv",
        mime="text/csv",
        key="manual_download",
    )

with method_tab:
    st.markdown(
        """
        <div class="model-card">
            <div class="section-title">How the model works</div>
            <p><b>1. Sample-size regression:</b> The player's DSL rate is pulled toward the 2024–2026 DSL average. The amount depends on PA and the reliability of each statistic.</p>
            <p><b>2. DSL → Complex:</b> Applies the matched-player change learned from hitters appearing in the DSL and ACL/FCL.</p>
            <p><b>3. Complex → Single-A:</b> Applies the matched-player change learned from hitters appearing at both levels.</p>
            <p><b>4. Single-A → MLB:</b> Applies the provisional bridge inferred from the adjusted/MLE example that was supplied.</p>
            <p><b>5. Component-specific translation:</b> AVG, OBP, BB%, K% and wOBA use log-odds adjustments. SLG, OPS and ISO use multiplicative log adjustments.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("")
    st.markdown(
        """
        <div class="note">
            <b>Important:</b> This estimates the player's current MLB-equivalent performance. It is not a projection of his eventual ceiling.
            The DSL→Complex and Complex→A steps are data-derived. The last bridge remains provisional until AA, AAA and MLB transition data are added.
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    '<p class="small-note">Model calibrated from the supplied 2024–2026 matched-player dataset. Rangers internal evaluation tool.</p>',
    unsafe_allow_html=True,
)
