import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

st.set_page_config(page_title="League Projection Hitter Grader", layout="wide")
st.title("League Projection Hitter Grader")
st.caption("Upload a hitter CSV, select a league, and grade players based on how their profile may translate.")

LEAGUE_PROFILES = {
    "LIDOM": {
        "description": "High-stuff winter league. Rewards contact vs velocity, hard contact, and fastball performance.",
        "weights": {"Forward Velocity":15,"Exit Velocity":20,"Launch Angle":12,"Hard Hit":17,"Contact":18,"Pull":8,"OPS vs FB95":10},
        "ideal_la": (8.0, 24.0)
    },
    "PR League": {
        "description": "Winter league where bat-to-ball, game speed, and offensive efficiency matter heavily.",
        "weights": {"Forward Velocity":16,"Exit Velocity":17,"Launch Angle":12,"Hard Hit":15,"Contact":22,"Pull":8,"OPS vs FB95":10},
        "ideal_la": (7.0, 23.0)
    },
    "MLB": {
        "description": "Highest pitching quality. Rewards damage, contact quality, and performance vs elite velocity.",
        "weights": {"Forward Velocity":8,"Exit Velocity":24,"Launch Angle":14,"Hard Hit":20,"Contact":14,"Pull":7,"OPS vs FB95":13},
        "ideal_la": (10.0, 28.0)
    },
    "MiLB / AAA": {
        "description": "Upper-minors projection. Balanced model between tools, contact, and power translation.",
        "weights": {"Forward Velocity":12,"Exit Velocity":21,"Launch Angle":14,"Hard Hit":18,"Contact":16,"Pull":8,"OPS vs FB95":11},
        "ideal_la": (9.0, 27.0)
    },
    "NPB": {
        "description": "Contact-oriented high-execution league. Rewards contact and usable line-drive power.",
        "weights": {"Forward Velocity":11,"Exit Velocity":17,"Launch Angle":16,"Hard Hit":14,"Contact":26,"Pull":6,"OPS vs FB95":10},
        "ideal_la": (8.0, 24.0)
    },
    "KBO": {
        "description": "Rewards contact and hard contact with slightly more tolerance for pull power.",
        "weights": {"Forward Velocity":11,"Exit Velocity":20,"Launch Angle":14,"Hard Hit":17,"Contact":19,"Pull":9,"OPS vs FB95":10},
        "ideal_la": (9.0, 26.0)
    },
    "Mexican League": {
        "description": "Run-scoring environment. Rewards power, pull damage, and hard contact.",
        "weights": {"Forward Velocity":9,"Exit Velocity":23,"Launch Angle":15,"Hard Hit":19,"Contact":13,"Pull":11,"OPS vs FB95":10},
        "ideal_la": (11.0, 29.0)
    },
    "Custom": {
        "description": "Build your own scoring model.",
        "weights": {"Forward Velocity":15,"Exit Velocity":20,"Launch Angle":15,"Hard Hit":15,"Contact":15,"Pull":10,"OPS vs FB95":10},
        "ideal_la": (8.0, 28.0)
    }
}

def norm(x):
    return str(x).strip().lower().replace(" ","").replace("_","").replace("-","").replace("/","")

def find_col(columns, candidates):
    m = {norm(c): c for c in columns}
    for cand in candidates:
        if norm(cand) in m:
            return m[norm(cand)]
    return None

def safe_numeric(series):
    if series is None:
        return np.nan
    s = series.astype(str).str.replace("%","",regex=False).str.replace(",","",regex=False)
    return pd.to_numeric(s, errors="coerce")

def maybe_percent(series):
    s = safe_numeric(series)
    if s.dropna().empty:
        return s
    return s/100 if s.dropna().median() > 1.5 else s

def percentile_score(series):
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() <= 1:
        return pd.Series(np.full(len(s), 50.0), index=s.index)
    return (s.rank(pct=True, method="average") * 100).fillna(50)

def launch_angle_score(series, low, high):
    la = pd.to_numeric(series, errors="coerce")
    mid = (low + high) / 2
    half = max((high - low) / 2, 1)
    return (100 - (abs(la - mid) / half * 50)).clip(0, 100).fillna(50)

def letter_grade(x):
    if x >= 90: return "A+"
    if x >= 85: return "A"
    if x >= 80: return "A-"
    if x >= 75: return "B+"
    if x >= 70: return "B"
    if x >= 65: return "B-"
    if x >= 60: return "C+"
    if x >= 55: return "C"
    return "D"

def player_type(row):
    ev, contact, hh, pull, ops = row["Exit Velocity"], row["Contact"], row["Hard Hit"], row["Pull"], row["OPS vs FB95"]
    if pd.notna(ev) and pd.notna(hh) and ev >= 92 and hh >= 0.40:
        return "Impact Power + Contact" if pd.notna(contact) and contact >= 0.72 else "Power Profile"
    if pd.notna(contact) and contact >= 0.75:
        return "Contact / Bat-to-Ball"
    if pd.notna(ops) and ops >= 0.850:
        return "Velocity Performer"
    if pd.notna(pull) and pull >= 0.45:
        return "Pull Damage Profile"
    return "Balanced / Needs Context"

def export_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Projection Grades")
    return output.getvalue()

st.sidebar.header("League Projection")
league = st.sidebar.selectbox("Select league", list(LEAGUE_PROFILES.keys()))
profile = LEAGUE_PROFILES[league]
st.sidebar.info(profile["description"])

st.sidebar.header("Grade Weights")
weights = {}
locked = league != "Custom"
for k, v in profile["weights"].items():
    weights[k] = st.sidebar.slider(k, 0, 40, v, disabled=locked)
if locked:
    st.sidebar.caption("Choose Custom to manually adjust weights.")

st.sidebar.header("Launch Angle Settings")
la_low_default, la_high_default = profile["ideal_la"]
la_low = st.sidebar.number_input("Ideal LA lower bound", value=float(la_low_default), disabled=locked)
la_high = st.sidebar.number_input("Ideal LA upper bound", value=float(la_high_default), disabled=locked)

uploaded = st.file_uploader("Upload hitter CSV", type=["csv"])
if uploaded is None:
    st.info("Upload your hitter CSV to begin.")
    st.markdown("""
Expected columns:
- playerFullName
- ForwVel
- ExitVel
- LaunchAng
- OPS vs FB95
- Contact%
- Hard Hit%
- Pull%
""")
    st.stop()

df = pd.read_csv(uploaded)
df.columns = [str(c).strip() for c in df.columns]
cols = ["-- None --"] + list(df.columns)

auto = {
    "player": find_col(df.columns, ["playerFullName","Player","Batter","Hitter"]),
    "fv": find_col(df.columns, ["ForwVel","Forward Velocity","ForwardVelocity","FV"]),
    "ev": find_col(df.columns, ["ExitVel","Exit Velocity","ExitVelocity","EV"]),
    "la": find_col(df.columns, ["LaunchAng","Launch Angle","LaunchAngle","LA"]),
    "ops": find_col(df.columns, ["OPS vs FB95","OPSvsFB95","OPS vs 95+","OPS v FB95"]),
    "contact": find_col(df.columns, ["Contact%","Contact","Contact Rate"]),
    "hardhit": find_col(df.columns, ["Hard Hit%","HardHit%","Hard Hit","HardHit","Hard Hit Rate"]),
    "pull": find_col(df.columns, ["Pull%","Pull","Pull Rate"]),
}

def select_col(label, key):
    default = auto.get(key)
    index = cols.index(default) if default in cols else 0
    val = st.selectbox(label, cols, index=index, key=key)
    return None if val == "-- None --" else val

st.subheader("Column Mapping")
c1, c2 = st.columns(2)
with c1:
    player_col = select_col("Player column", "player")
    fv_col = select_col("Forward Velocity column", "fv")
    ev_col = select_col("Exit Velocity column", "ev")
    la_col = select_col("Launch Angle column", "la")
with c2:
    ops_col = select_col("OPS vs FB95 column", "ops")
    contact_col = select_col("Contact column", "contact")
    hardhit_col = select_col("Hard Hit column", "hardhit")
    pull_col = select_col("Pull column", "pull")

if not player_col:
    st.error("Please select a player column.")
    st.stop()

missing = []
required = {"Forward Velocity":fv_col,"Exit Velocity":ev_col,"Launch Angle":la_col,"OPS vs FB95":ops_col,"Contact":contact_col,"Hard Hit":hardhit_col,"Pull":pull_col}
for k, v in required.items():
    if v is None:
        missing.append(k)
if missing:
    st.warning("Missing columns will be treated as neutral 50 scores: " + ", ".join(missing))

work = pd.DataFrame()
work["Player"] = df[player_col].astype(str)
work["Forward Velocity"] = safe_numeric(df[fv_col]) if fv_col else np.nan
work["Exit Velocity"] = safe_numeric(df[ev_col]) if ev_col else np.nan
work["Launch Angle"] = safe_numeric(df[la_col]) if la_col else np.nan
work["OPS vs FB95"] = safe_numeric(df[ops_col]) if ops_col else np.nan
work["Contact"] = maybe_percent(df[contact_col]) if contact_col else np.nan
work["Hard Hit"] = maybe_percent(df[hardhit_col]) if hardhit_col else np.nan
work["Pull"] = maybe_percent(df[pull_col]) if pull_col else np.nan

summary = work.groupby("Player", dropna=False).mean(numeric_only=True).reset_index()

scores = pd.DataFrame({"Player": summary["Player"]})
scores["Forward Velocity Score"] = percentile_score(summary["Forward Velocity"])
scores["Exit Velocity Score"] = percentile_score(summary["Exit Velocity"])
scores["Launch Angle Score"] = launch_angle_score(summary["Launch Angle"], la_low, la_high)
scores["Hard Hit Score"] = percentile_score(summary["Hard Hit"])
scores["Contact Score"] = percentile_score(summary["Contact"])
scores["Pull Score"] = percentile_score(summary["Pull"])
scores["OPS vs FB95 Score"] = percentile_score(summary["OPS vs FB95"])

score_map = {
    "Forward Velocity":"Forward Velocity Score",
    "Exit Velocity":"Exit Velocity Score",
    "Launch Angle":"Launch Angle Score",
    "Hard Hit":"Hard Hit Score",
    "Contact":"Contact Score",
    "Pull":"Pull Score",
    "OPS vs FB95":"OPS vs FB95 Score",
}
for metric, col in score_map.items():
    if required[metric] is None:
        scores[col] = 50.0

total_weight = sum(weights.values())
final = pd.Series(0.0, index=summary.index)
for metric, score_col in score_map.items():
    final += scores[score_col] * (weights[metric] / total_weight)

summary["Projected League"] = league
summary["Projection Grade"] = final.round(1)
summary["Letter Grade"] = summary["Projection Grade"].apply(letter_grade)
summary["Player Type"] = summary.apply(player_type, axis=1)

out = summary.merge(scores, on="Player", how="left").sort_values("Projection Grade", ascending=False)

st.subheader(f"{league} Projection Leaderboard")
display = out.copy()
for col in ["Contact", "Hard Hit", "Pull"]:
    display[col] = display[col].apply(lambda x: "" if pd.isna(x) else f"{x:.1%}")
st.dataframe(display, use_container_width=True, hide_index=True)

top = out.head(10)
if len(top):
    st.subheader(f"Top 10 Fits for {league}")
    st.bar_chart(top[["Player", "Projection Grade"]].set_index("Player"))

st.subheader("Selected League Model")
st.dataframe(pd.DataFrame({"Metric": list(weights.keys()), "Weight": list(weights.values())}), hide_index=True, use_container_width=True)

st.markdown(f"""
### Model Notes
- Current league: **{league}**
- Launch Angle target range: **{la_low:.1f}° to {la_high:.1f}°**
- Grades are percentile-based inside the uploaded CSV.
- Missing columns are treated as neutral 50 scores.
""")

excel_data = export_excel(out)
safe_league = league.lower().replace(" ", "_").replace("/", "_")
st.download_button("Download Results as Excel", excel_data, file_name=f"{safe_league}_projection_grades.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.download_button("Download Results as CSV", out.to_csv(index=False).encode("utf-8"), file_name=f"{safe_league}_projection_grades.csv", mime="text/csv")
