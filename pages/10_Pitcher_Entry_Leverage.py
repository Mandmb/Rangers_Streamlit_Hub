import re
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

st.set_page_config(page_title="Pitcher Entry & Leverage", page_icon="⚾", layout="wide")

RANGERS_BLUE = "#002D72"
RANGERS_RED = "#BA0C2F"
DARK_GRAY = "#857874"

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
    h1, h2, h3 {letter-spacing: -0.02em;}
    div[data-testid="stMetric"] {border: 1px solid #E6E8EB; border-radius: 10px; padding: 10px 14px;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Pitcher Entry & Leverage Report")
st.caption("Upload multiple pitch-log CSVs to summarize when pitchers enter games and the leverage of their entry situations.")


def norm_col(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def get_col(df, *candidates):
    lookup = {norm_col(c): c for c in df.columns}
    for cand in candidates:
        key = norm_col(cand)
        if key in lookup:
            return lookup[key]
    return None


def parse_inning(value):
    if pd.isna(value):
        return None, None
    s = str(value).strip()
    m = re.search(r"(?i)\b(top|bot|bottom)\s*(\d+)\b", s)
    if not m:
        m = re.search(r"(?i)\b(\d+)\b", s)
        if not m:
            return None, None
        return int(m.group(1)), None
    half = "Top" if m.group(1).lower() == "top" else "Bot"
    return int(m.group(2)), half


def runners_from_situation(value):
    if pd.isna(value):
        return 0, False
    s = str(value).strip().lower()
    if not s or s in {"empty", "none", "nan"}:
        return 0, False
    bases = set()
    if "1st" in s or "first" in s:
        bases.add(1)
    if "2nd" in s or "second" in s:
        bases.add(2)
    if "3rd" in s or "third" in s:
        bases.add(3)
    return len(bases), bool({2, 3} & bases)


def leverage_score(inning, score_diff, runners, risp, outs):
    """Transparent heuristic for entry leverage; not an official MLB LI value."""
    # Score closeness: tied / one-run games matter most.
    if score_diff <= 0:
        score_component = 4.0
    elif score_diff == 1:
        score_component = 3.3
    elif score_diff == 2:
        score_component = 2.3
    elif score_diff == 3:
        score_component = 1.3
    elif score_diff == 4:
        score_component = 0.6
    else:
        score_component = 0.0

    # Later innings increase leverage.
    if inning is None:
        inning_component = 0.0
    elif inning <= 4:
        inning_component = 0.0
    elif inning == 5:
        inning_component = 0.5
    elif inning == 6:
        inning_component = 1.0
    elif inning == 7:
        inning_component = 1.6
    elif inning == 8:
        inning_component = 2.2
    else:
        inning_component = 2.8

    # Traffic on the bases raises immediate run-scoring pressure.
    runner_component = {0: 0.0, 1: 0.8, 2: 1.5, 3: 2.3}.get(int(runners), 0.0)
    if risp and runners > 0:
        runner_component += 0.4

    # Fewer outs generally means more remaining scoring opportunity.
    outs_component = {0: 0.9, 1: 0.5, 2: 0.2}.get(int(outs) if pd.notna(outs) else -1, 0.0)

    return round(score_component + inning_component + runner_component + outs_component, 2)


def classify_leverage(score, mid_cut, high_cut):
    if score >= high_cut:
        return "High"
    if score >= mid_cut:
        return "Mid"
    return "Low"


def score_margin_bucket(team_runs, opp_runs):
    """Bucket the score state from the pitcher's team perspective at entry."""
    if pd.isna(team_runs) or pd.isna(opp_runs):
        return None
    diff = int(team_runs) - int(opp_runs)
    if diff <= -5:
        return "Trail 5+"
    if diff < 0:
        return f"Trail {abs(diff)}"
    if diff == 0:
        return "Tied"
    if diff >= 5:
        return "Lead 5+"
    return f"Lead {diff}"


def outs_recorded_from_result(value):
    """Return pitcher outs credited by the terminal pitch result."""
    if pd.isna(value):
        return 0
    s = str(value).strip().lower()
    if "double play" in s:
        return 2
    one_out_results = (
        "strikeout", "ground out", "fly out", "line out", "pop out",
        "bunt pop out", "fielder's choice"
    )
    return 1 if any(term in s for term in one_out_results) else 0


def baseball_ip_from_outs(outs):
    """Format total innings pitched in baseball notation (e.g. 4 outs = 1.1 IP)."""
    outs = int(outs or 0)
    return f"{outs // 3}.{outs % 3}"


def build_pdf_report(view, inning_pivot, workload_table, lev_table, margin_table, mid_cut, high_cut):
    """Create a polished single-page landscape PDF with the three core bullpen usage sections."""
    buffer = BytesIO()
    page_w, page_h = landscape(letter)
    c = canvas.Canvas(buffer, pagesize=(page_w, page_h))
    c.setTitle("Pitcher Workload, Entry Inning & Leverage")

    margin_x = 18
    footer_h = 20
    header_h = 45
    section_gap = 6
    content_w = page_w - (2 * margin_x)
    content_top = page_h - header_h
    content_bottom = footer_h + 8
    usable_h = content_top - content_bottom

    # Three horizontal bands keep all four tables on one landscape page:
    # workload + leverage on top, inning usage in the middle, score margin at bottom.
    top_h = usable_h * 0.38
    middle_h = usable_h * 0.31
    bottom_h = usable_h - top_h - middle_h - (2 * section_gap)

    # Header
    c.setFillColor(colors.HexColor(RANGERS_BLUE))
    c.setFont("Helvetica-Bold", 17)
    c.drawString(margin_x, page_h - 23, "Pitcher Workload, Entry Inning & Leverage")
    c.setFillColor(colors.HexColor("#666666"))
    c.setFont("Helvetica", 6.6)
    c.drawString(
        margin_x,
        page_h - 34,
        f"{view['Pitcher'].nunique()} pitcher(s) | {len(view)} appearance(s) | "
        f"Leverage: Low < {mid_cut:.1f}, Mid {mid_cut:.1f} to < {high_cut:.1f}, High >= {high_cut:.1f}",
    )

    # Footer
    c.setStrokeColor(colors.HexColor(RANGERS_RED))
    c.setLineWidth(1.0)
    c.line(margin_x, 17, page_w - margin_x, 17)
    c.setFillColor(colors.HexColor("#666666"))
    c.setFont("Helvetica", 5.5)
    c.drawRightString(page_w - margin_x, 7, "Entry usage and leverage")

    def draw_section_title(text, x, y, width):
        c.setFillColor(colors.HexColor(RANGERS_BLUE))
        c.setFont("Helvetica-Bold", 9.2)
        c.drawString(x, y, text)
        c.setStrokeColor(colors.HexColor("#D8DDE3"))
        c.setLineWidth(0.45)
        c.line(x, y - 3, x + width, y - 3)

    def make_table(data, col_widths, row_height, font_size, highlight_cols=None):
        row_heights = [row_height] * len(data)
        tbl = Table(data, colWidths=col_widths, rowHeights=row_heights)
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(RANGERS_BLUE)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6DADE")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7F9")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2.2),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]
        if highlight_cols:
            for idx, bg in highlight_cols.items():
                commands.append(("BACKGROUND", (idx, 1), (idx, -1), colors.HexColor(bg)))
        tbl.setStyle(TableStyle(commands))
        return tbl

    # Prepare data
    wt = workload_table.reset_index().copy()
    wt_data = [[str(c) for c in wt.columns]] + [
        [str(v) for v in row] for row in wt.astype(object).where(pd.notna(wt), "").values.tolist()
    ]

    lt = lev_table.reset_index().copy()
    lt_data = [[str(c) for c in lt.columns]] + [
        [str(v) for v in row] for row in lt.astype(object).where(pd.notna(lt), "").values.tolist()
    ]

    ip = inning_pivot.reset_index().copy()
    ip_data = [[str(c) for c in ip.columns]] + [
        [str(v) for v in row] for row in ip.astype(object).where(pd.notna(ip), "").values.tolist()
    ]

    mt = margin_table.reset_index().copy()
    mt_data = [[str(c) for c in mt.columns]] + [
        [str(v) for v in row] for row in mt.astype(object).where(pd.notna(mt), "").values.tolist()
    ]

    # TOP BAND: Workload and leverage side-by-side.
    # report on a single page even with a full bullpen of pitchers.
    top_y = content_top
    top_table_y = top_y - 18
    top_table_h = top_h - 20
    top_gap = 10
    workload_w = content_w * 0.34
    leverage_w = content_w - workload_w - top_gap

    draw_section_title("Pitcher Workload", margin_x, top_y - 9, workload_w)
    draw_section_title("Leverage at Entry", margin_x + workload_w + top_gap, top_y - 9, leverage_w)

    wt_row_h = min(12.0, top_table_h / max(1, len(wt_data)))
    wt_font = max(4.4, min(6.0, wt_row_h * 0.48))
    wt_first = workload_w * 0.44
    wt_rest = (workload_w - wt_first) / max(1, len(wt.columns) - 1)
    wt_tbl = make_table(
        wt_data,
        [wt_first] + [wt_rest] * (len(wt.columns) - 1),
        wt_row_h,
        wt_font,
    )
    wt_h = wt_row_h * len(wt_data)
    wt_tbl.wrapOn(c, workload_w, wt_h)
    wt_tbl.drawOn(c, margin_x, top_table_y - wt_h)

    lev_row_h = min(12.0, top_table_h / max(1, len(lt_data)))
    lev_font = max(4.0, min(5.4, lev_row_h * 0.43))
    lev_first = leverage_w * 0.24
    lev_rest = (leverage_w - lev_first) / max(1, len(lt.columns) - 1)
    lev_highlights = {}
    for name, bg in [
        ("Low", "#E5E8EB"), ("Mid", "#FBE7A1"), ("High", "#F3C4C8"),
        ("Low %", "#EEF0F2"), ("Mid %", "#FFF3C8"), ("High %", "#F9DEE1"),
    ]:
        if name in lt.columns:
            lev_highlights[list(lt.columns).index(name)] = bg
    lev_tbl = make_table(
        lt_data,
        [lev_first] + [lev_rest] * (len(lt.columns) - 1),
        lev_row_h,
        lev_font,
        lev_highlights,
    )
    lev_h = lev_row_h * len(lt_data)
    lev_tbl.wrapOn(c, leverage_w, lev_h)
    lev_tbl.drawOn(c, margin_x + workload_w + top_gap, top_table_y - lev_h)

    # MIDDLE BAND: Entry inning usage across the full width.
    middle_top = content_top - top_h - section_gap
    draw_section_title("Entry Inning Usage", margin_x, middle_top - 9, content_w)
    entry_table_y = middle_top - 18
    entry_table_h = middle_h - 20
    ip_row_h = min(8.5, entry_table_h / max(1, len(ip_data)))
    ip_font = max(3.25, min(4.7, ip_row_h * 0.47))
    ip_first = content_w * 0.205
    ip_rest = (content_w - ip_first) / max(1, len(ip.columns) - 1)
    ip_tbl = make_table(
        ip_data,
        [ip_first] + [ip_rest] * (len(ip.columns) - 1),
        ip_row_h,
        ip_font,
    )
    ip_h = ip_row_h * len(ip_data)
    ip_tbl.wrapOn(c, content_w, ip_h)
    ip_tbl.drawOn(c, margin_x, entry_table_y - ip_h)

    # BOTTOM BAND: Score margin at entry.
    margin_top = middle_top - middle_h - section_gap
    draw_section_title("Score Margin at Entry", margin_x, margin_top - 9, content_w)
    margin_table_y = margin_top - 18
    margin_table_h = bottom_h - 20
    mt_row_h = min(8.5, margin_table_h / max(1, len(mt_data)))
    mt_font = max(3.2, min(4.6, mt_row_h * 0.47))
    mt_first = content_w * 0.205
    mt_rest = (content_w - mt_first) / max(1, len(mt.columns) - 1)
    margin_highlights = {}
    for name, bg in [
        ("Trail 5+", "#F8D7DA"), ("Trail 4", "#F8D7DA"), ("Trail 3", "#F8D7DA"),
        ("Trail 2", "#F8D7DA"), ("Trail 1", "#F8D7DA"), ("Tied", "#FFF3CD"),
        ("Lead 1", "#DDEEDB"), ("Lead 2", "#DDEEDB"), ("Lead 3", "#DDEEDB"),
        ("Lead 4", "#DDEEDB"), ("Lead 5+", "#DDEEDB"),
    ]:
        if name in mt.columns:
            margin_highlights[list(mt.columns).index(name)] = bg
    mt_tbl = make_table(
        mt_data,
        [mt_first] + [mt_rest] * (len(mt.columns) - 1),
        mt_row_h,
        mt_font,
        margin_highlights,
    )
    mt_h = mt_row_h * len(mt_data)
    mt_tbl.wrapOn(c, content_w, mt_h)
    mt_tbl.drawOn(c, margin_x, margin_table_y - mt_h)

    c.save()
    buffer.seek(0)
    return buffer.getvalue()

def process_file(uploaded, mid_cut, high_cut):
    df = pd.read_csv(uploaded)

    c_name = get_col(df, "fullName", "fullname")
    c_game = get_col(df, "gameId", "gameid")
    c_date = get_col(df, "date", "gameDate", "gamedate")
    c_pitchnum = get_col(df, "pitchNumInGame", "pitchnumingame")
    c_inn = get_col(df, "inn", "inning")
    c_outs = get_col(df, "outs")
    c_sit = get_col(df, "Situation", "situation")
    c_pitch_result = get_col(df, "pitchResult", "pitchresult")
    c_runs = get_col(df, "currentRuns", "currentruns")
    c_opp_runs = get_col(df, "opponentCurrentRuns", "opponentcurrentruns")
    c_team = get_col(df, "team")
    c_opp = get_col(df, "opponent")

    required = {
        "fullName": c_name,
        "inning": c_inn,
        "outs": c_outs,
        "Situation": c_sit,
        "pitchResult": c_pitch_result,
        "currentRuns": c_runs,
        "opponentCurrentRuns": c_opp_runs,
    }
    missing = [label for label, col in required.items() if col is None]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")

    temp = df.copy()
    if c_game is not None:
        temp["_game_key"] = temp[c_game].astype(str)
    elif c_date is not None:
        temp["_game_key"] = temp[c_date].astype(str)
    else:
        raise ValueError("Need either gameId or date/gameDate to identify separate games.")

    temp["_pitcher"] = temp[c_name].astype(str).str.strip()
    if c_pitchnum is not None:
        temp["_pitch_order"] = pd.to_numeric(temp[c_pitchnum], errors="coerce")
    else:
        temp["_pitch_order"] = range(len(temp))

    temp["_row_order"] = range(len(temp))
    temp["_outs_recorded"] = temp[c_pitch_result].apply(outs_recorded_from_result)
    temp = temp.sort_values(["_pitcher", "_game_key", "_pitch_order", "_row_order"], na_position="last")

    # Calculate workload for the full appearance before reducing to the first pitch.
    outing_outs = (
        temp.groupby(["_pitcher", "_game_key"], as_index=False, sort=False)["_outs_recorded"]
        .sum()
        .rename(columns={"_outs_recorded": "_outing_outs"})
    )

    # One entry record per pitcher/game: first pitch thrown in that game.
    first = temp.groupby(["_pitcher", "_game_key"], as_index=False, sort=False).first()
    first = first.merge(outing_outs, on=["_pitcher", "_game_key"], how="left")

    records = []
    for _, row in first.iterrows():
        inning_num, half = parse_inning(row[c_inn])
        runners, risp = runners_from_situation(row[c_sit])
        team_runs = pd.to_numeric(row[c_runs], errors="coerce")
        opp_runs = pd.to_numeric(row[c_opp_runs], errors="coerce")
        outs = pd.to_numeric(row[c_outs], errors="coerce")
        signed_diff = (team_runs - opp_runs) if pd.notna(team_runs) and pd.notna(opp_runs) else None
        diff = abs(signed_diff) if signed_diff is not None else None
        margin_bucket = score_margin_bucket(team_runs, opp_runs)
        lev_score = leverage_score(inning_num, diff if diff is not None else 99, runners, risp, outs)

        records.append({
            "Pitcher": row["_pitcher"],
            "Game": row["_game_key"],
            "Date": row[c_date] if c_date is not None else "",
            "Team": row[c_team] if c_team is not None else "",
            "Opponent": row[c_opp] if c_opp is not None else "",
            "Entry": str(row[c_inn]),
            "Half": half or "",
            "Inning": inning_num,
            "Outs": int(outs) if pd.notna(outs) else None,
            "Situation": str(row[c_sit]),
            "Runners On": runners,
            "RISP": "Yes" if risp else "No",
            "Team Runs": int(team_runs) if pd.notna(team_runs) else None,
            "Opponent Runs": int(opp_runs) if pd.notna(opp_runs) else None,
            "Score Diff": int(diff) if diff is not None else None,
            "Score Margin": int(signed_diff) if signed_diff is not None else None,
            "Margin at Entry": margin_bucket or "",
            "Outs Recorded": int(row.get("_outing_outs", 0) or 0),
            "IP": baseball_ip_from_outs(row.get("_outing_outs", 0)),
            "Leverage Score": lev_score,
            "Leverage": classify_leverage(lev_score, mid_cut, high_cut),
            "Source File": getattr(uploaded, "name", "CSV"),
        })
    return pd.DataFrame(records)


with st.sidebar:
    st.header("Leverage Settings")
    mid_cut = st.number_input("Mid leverage starts at", min_value=0.0, max_value=15.0, value=3.5, step=0.1)
    high_cut = st.number_input("High leverage starts at", min_value=0.0, max_value=15.0, value=6.5, step=0.1)
    st.caption("These cutoffs apply to the transparent leverage score shown in the report.")

uploads = st.file_uploader(
    "Pitch log CSV files",
    type=["csv"],
    accept_multiple_files=True,
    help="Upload one or many pitcher pitch-log CSVs.",
)

if not uploads:
    st.info("Upload pitch-log CSVs to generate the report.")
    st.stop()

frames = []
errors = []
for uploaded in uploads:
    try:
        frames.append(process_file(uploaded, mid_cut, high_cut))
    except Exception as exc:
        errors.append(f"{uploaded.name}: {exc}")

if errors:
    for err in errors:
        st.error(err)

if not frames:
    st.stop()

entries = pd.concat(frames, ignore_index=True)
# Protect against the same pitcher/game appearing in overlapping uploads.
entries = entries.sort_values(["Pitcher", "Game", "Source File"]).drop_duplicates(["Pitcher", "Game"], keep="first")
entries["Inning"] = pd.to_numeric(entries["Inning"], errors="coerce").astype("Int64")

pitchers = sorted(entries["Pitcher"].dropna().unique().tolist())
selected_pitchers = st.multiselect("Pitcher filter", pitchers, default=pitchers)
view = entries[entries["Pitcher"].isin(selected_pitchers)].copy()

if view.empty:
    st.warning("No appearances match the selected pitcher filter.")
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Pitchers", view["Pitcher"].nunique())
c2.metric("Appearances", len(view))
c3.metric("High leverage", int((view["Leverage"] == "High").sum()))
c4.metric("Avg. entry inning", f"{view['Inning'].dropna().mean():.1f}" if view["Inning"].notna().any() else "—")
overall_avg_ip = view["Outs Recorded"].sum() / 3 / len(view) if len(view) else 0
c5.metric("Avg. IP / outing", f"{overall_avg_ip:.2f}")

st.subheader("Pitcher Workload")
workload_table = (
    view.groupby("Pitcher")
    .agg(Appearances=("Game", "count"), **{"Total Outs": ("Outs Recorded", "sum")})
)
workload_table["Total IP"] = workload_table["Total Outs"].apply(baseball_ip_from_outs)
workload_table["Avg. IP / Outing"] = (workload_table["Total Outs"] / 3 / workload_table["Appearances"]).round(2)
workload_table = workload_table[["Appearances", "Total IP", "Avg. IP / Outing"]]
st.dataframe(workload_table, use_container_width=True)

st.subheader("Entry Inning Usage")
inning_counts = (
    view.dropna(subset=["Inning"])
    .groupby(["Pitcher", "Inning"], as_index=False)
    .size()
    .rename(columns={"size": "Appearances"})
)
if not inning_counts.empty:
    inning_counts["Inning"] = inning_counts["Inning"].astype(int).astype(str)
    fig_inn = px.bar(
        inning_counts,
        x="Inning",
        y="Appearances",
        color="Pitcher",
        barmode="group",
        text="Appearances",
        category_orders={"Inning": [str(i) for i in range(1, 16)]},
    )
    fig_inn.update_traces(textposition="outside")
    fig_inn.update_layout(
        xaxis_title="Inning pitcher entered",
        yaxis_title="Number of appearances",
        legend_title_text="Pitcher",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig_inn, use_container_width=True)

st.subheader("Entry Inning Table")
inning_pivot = (
    view.dropna(subset=["Inning"])
    .pivot_table(index="Pitcher", columns="Inning", values="Game", aggfunc="count", fill_value=0)
    .sort_index(axis=1)
)
inning_pivot.columns = [f"{int(c)}th" if int(c) not in [1,2,3] else {1:"1st",2:"2nd",3:"3rd"}[int(c)] for c in inning_pivot.columns]
inning_pivot["Total"] = inning_pivot.sum(axis=1)
st.dataframe(inning_pivot, use_container_width=True)

st.subheader("Leverage at Entry")
lev_order = ["Low", "Mid", "High"]
lev_counts = (
    view.groupby(["Pitcher", "Leverage"], as_index=False)
    .size()
    .rename(columns={"size": "Appearances"})
)
fig_lev = px.bar(
    lev_counts,
    x="Pitcher",
    y="Appearances",
    color="Leverage",
    barmode="stack",
    text="Appearances",
    category_orders={"Leverage": lev_order},
    color_discrete_map={"Low": "#C7CDD4", "Mid": "#F2C14E", "High": RANGERS_RED},
)
fig_lev.update_traces(textposition="inside")
fig_lev.update_layout(
    xaxis_title="Pitcher",
    yaxis_title="Number of appearances",
    legend_title_text="Entry leverage",
    margin=dict(l=10, r=10, t=20, b=10),
)
st.plotly_chart(fig_lev, use_container_width=True)

lev_table = (
    view.pivot_table(index="Pitcher", columns="Leverage", values="Game", aggfunc="count", fill_value=0)
    .reindex(columns=lev_order, fill_value=0)
)
lev_table["Total"] = lev_table.sum(axis=1)
for col in lev_order:
    lev_table[f"{col} %"] = (lev_table[col] / lev_table["Total"] * 100).round(1)
st.dataframe(lev_table, use_container_width=True)

st.subheader("Score Margin at Entry")
margin_order = [
    "Trail 5+", "Trail 4", "Trail 3", "Trail 2", "Trail 1",
    "Tied",
    "Lead 1", "Lead 2", "Lead 3", "Lead 4", "Lead 5+",
]
margin_table = (
    view.pivot_table(index="Pitcher", columns="Margin at Entry", values="Game", aggfunc="count", fill_value=0)
    .reindex(columns=margin_order, fill_value=0)
)
margin_table["Total"] = margin_table.sum(axis=1)
st.caption("Counts show the score margin from the pitcher's team perspective when he threw his first pitch of the appearance.")
st.dataframe(margin_table, use_container_width=True)

with st.expander("How leverage is calculated", expanded=False):
    st.markdown(
        f"""
The leverage score is calculated **only from the game state when the pitcher throws his first pitch**.

- **Score:** tied and one-run games receive the most weight; large margins receive less.
- **Inning:** leverage increases from the 5th inning forward, with the strongest weight in the 9th or later.
- **Runners:** more runners on base increases leverage; runners in scoring position add extra weight.
- **Outs:** zero outs receives more pressure weight than one or two outs because more scoring opportunity remains.
- **Classification:** Low `< {mid_cut:.1f}`, Mid `{mid_cut:.1f}–<{high_cut:.1f}`, High `≥ {high_cut:.1f}`.

This is a **transparent internal leverage model**, not an official MLB Leverage Index (LI). The cutoffs can be adjusted in the sidebar.
        """
    )

st.subheader("Appearance Detail")
detail_cols = [
    "Pitcher", "Date", "Opponent", "Entry", "Outs", "Situation",
    "Outs Recorded", "IP", "Team Runs", "Opponent Runs", "Score Margin", "Margin at Entry", "Leverage Score", "Leverage"
]
st.dataframe(
    view[detail_cols].sort_values(["Pitcher", "Date"], ascending=[True, False]),
    use_container_width=True,
    hide_index=True,
)

summary_csv = view[detail_cols + ["Game", "Source File"]].to_csv(index=False).encode("utf-8")
pdf_bytes = build_pdf_report(view, inning_pivot, workload_table, lev_table, margin_table, mid_cut, high_cut)

btn1, btn2 = st.columns(2)
with btn1:
    st.download_button(
        "Download PDF Report",
        data=pdf_bytes,
        file_name="pitcher_bullpen_usage_report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
with btn2:
    st.download_button(
        "Download appearance summary CSV",
        data=summary_csv,
        file_name="pitcher_entry_leverage_summary.csv",
        mime="text/csv",
        use_container_width=True,
    )
