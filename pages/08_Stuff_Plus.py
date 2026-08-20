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
    "Physical pitch-quality model. Upload one CSV per pitch type; scores are normalized so 100 = the uploaded peer-group average."
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
    cols = ["player_id", "name", "velo", "ivb", "hb", "rel_height", "rel_side", "extension", "vaa", "haa"]
    fb = fastball_df[cols].copy()
    fb = fb.rename(columns={c: f"fb_{c}" for c in cols if c not in ["player_id", "name"]})
    return fb


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
    x["fb_sep_component"] = 0.0
    if fb_reference is not None and pitch_type not in {"Fastball", "Sinker"}:
        merged = x.merge(fb_reference, on="player_id", how="left", suffixes=("", "_ref"))

        # Fallback by name if IDs don't match.
        missing_fb = merged["fb_velo"].isna()
        if missing_fb.any():
            fb_by_name = fb_reference.drop(columns=["player_id"]).drop_duplicates("name")
            fallback = x.loc[missing_fb].merge(fb_by_name, on="name", how="left")
            for c in [c for c in fb_reference.columns if c.startswith("fb_")]:
                merged.loc[missing_fb, c] = fallback[c].values

        merged["velo_sep"] = merged["fb_velo"] - merged["velo"]
        merged["ivb_sep"] = (merged["fb_ivb"] - merged["ivb"]).abs()
        merged["hb_sep"] = (merged["fb_hb"] - merged["hb"]).abs()

        release_dist = np.sqrt(
            (merged["fb_rel_height"] - merged["rel_height"]) ** 2 +
            (merged["fb_rel_side"] - merged["rel_side"]) ** 2
        )
        merged["release_match"] = -release_dist

        sep = (
            0.40 * safe_z(winsorize(merged["velo_sep"])) +
            0.25 * safe_z(winsorize(merged["ivb_sep"])) +
            0.25 * safe_z(winsorize(merged["hb_sep"])) +
            0.10 * safe_z(winsorize(merged["release_match"]))
        )
        x["fb_sep_component"] = sep.values

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
        raw = pd.read_csv(file)
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
    use_container_width=True,
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
                use_container_width=True,
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
            st.dataframe(detail_df, use_container_width=True, hide_index=True)

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
    st.dataframe(arsenal_table, use_container_width=True, hide_index=True)

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

st.download_button(
    "Download Stuff+ Results CSV",
    data=csv_bytes,
    file_name="stuff_plus_results.csv",
    mime="text/csv",
    use_container_width=False,
)

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
