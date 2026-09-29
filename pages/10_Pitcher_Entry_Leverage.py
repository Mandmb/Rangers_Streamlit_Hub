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
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)

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


def build_pdf_report(view, inning_pivot, workload_table, lev_table, mid_cut, high_cut):
    """Create a polished one-page PDF with the three core bullpen usage sections."""
    buffer = BytesIO()
    page_w, page_h = landscape(letter)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=0.34 * inch,
        leftMargin=0.34 * inch,
        topMargin=0.34 * inch,
        bottomMargin=0.30 * inch,
        title="Pitcher Workload, Entry Inning & Leverage",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RangersTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=18, leading=20, textColor=colors.HexColor(RANGERS_BLUE),
        alignment=TA_LEFT, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.2, leading=8.5, textColor=colors.HexColor("#666666"), spaceAfter=5,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=10, leading=11, textColor=colors.HexColor(RANGERS_BLUE),
        spaceBefore=3, spaceAfter=3,
    )

    def header_footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(RANGERS_RED))
        canvas.setLineWidth(1.1)
        canvas.line(0.34 * inch, 0.23 * inch, page_w - 0.34 * inch, 0.23 * inch)
        canvas.setFont("Helvetica", 6)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(0.34 * inch, 0.10 * inch, "Texas Rangers - Bullpen Usage Report")
        canvas.drawRightString(page_w - 0.34 * inch, 0.10 * inch, "Entry usage and leverage")
        canvas.restoreState()

    def style_table(tbl, header_bg=RANGERS_BLUE, font_size=6.5, row_pad=2.7):
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D6DADE")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7F9")]),
            ("TOPPADDING", (0, 0), (-1, -1), row_pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), row_pad),
        ]))
        return tbl

    story = []
    story.append(Paragraph("Pitcher Workload, Entry Inning & Leverage", title_style))
    story.append(Paragraph(
        f"{view['Pitcher'].nunique()} pitcher(s) | {len(view)} appearance(s) | "
        f"Leverage: Low &lt; {mid_cut:.1f}, Mid {mid_cut:.1f} to &lt; {high_cut:.1f}, High &gt;= {high_cut:.1f}",
        subtitle_style,
    ))

    # 1) Pitcher Workload
    story.append(Paragraph("Pitcher Workload", section_style))
    wt = workload_table.reset_index().copy()
    wt_data = [[str(c) for c in wt.columns]] + [
        [str(v) for v in row] for row in wt.astype(object).where(pd.notna(wt), "").values.tolist()
    ]
    wt_font = 6.6 if len(wt) <= 12 else 5.7
    wt_pad = 2.8 if len(wt) <= 12 else 1.8
    wt_tbl = Table(wt_data, colWidths=[2.65*inch, 1.20*inch, 1.10*inch, 1.45*inch])
    story.append(style_table(wt_tbl, font_size=wt_font, row_pad=wt_pad))
    story.append(Spacer(1, 0.07 * inch))

    # 2) Entry Inning Usage
    story.append(Paragraph("Entry Inning Usage", section_style))
    ip = inning_pivot.reset_index().copy()
    ip_cols = [str(c) for c in ip.columns]
    ip_data = [ip_cols] + [
        [str(v) for v in row] for row in ip.astype(object).where(pd.notna(ip), "").values.tolist()
    ]
    available = 10.15 * inch
    first_w = 2.15 * inch
    other_w = max(0.40 * inch, (available - first_w) / max(1, len(ip_cols) - 1))
    ip_font = 6.3 if len(ip) <= 12 else 5.4
    ip_pad = 2.5 if len(ip) <= 12 else 1.7
    ip_tbl = Table(ip_data, colWidths=[first_w] + [other_w] * (len(ip_cols) - 1))
    story.append(style_table(ip_tbl, font_size=ip_font, row_pad=ip_pad))
    story.append(Spacer(1, 0.07 * inch))

    # 3) Leverage at Entry
    story.append(Paragraph("Leverage at Entry", section_style))
    lt = lev_table.reset_index().copy()
    lt_data = [[str(c) for c in lt.columns]] + [
        [str(v) for v in row] for row in lt.astype(object).where(pd.notna(lt), "").values.tolist()
    ]
    first_lev_w = 2.15 * inch
    remaining = 10.15 * inch - first_lev_w
    lev_other_w = remaining / max(1, len(lt.columns) - 1)
    lev_font = 6.2 if len(lt) <= 12 else 5.3
    lev_pad = 2.4 if len(lt) <= 12 else 1.6
    lev_tbl = Table(lt_data, colWidths=[first_lev_w] + [lev_other_w] * (len(lt.columns) - 1))
    style_table(lev_tbl, font_size=lev_font, row_pad=lev_pad)

    # Soft highlights for leverage counts and percentages.
    for name, bg in [
        ("Low", "#E5E8EB"), ("Mid", "#FBE7A1"), ("High", "#F3C4C8"),
        ("Low %", "#EEF0F2"), ("Mid %", "#FFF3C8"), ("High %", "#F9DEE1"),
    ]:
        if name in lt.columns:
            idx = list(lt.columns).index(name)
            lev_tbl.setStyle(TableStyle([("BACKGROUND", (idx, 1), (idx, -1), colors.HexColor(bg))]))
    story.append(lev_tbl)

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
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
        diff = abs(team_runs - opp_runs) if pd.notna(team_runs) and pd.notna(opp_runs) else None
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
    "Outs Recorded", "IP", "Team Runs", "Opponent Runs", "Score Diff", "Leverage Score", "Leverage"
]
st.dataframe(
    view[detail_cols].sort_values(["Pitcher", "Date"], ascending=[True, False]),
    use_container_width=True,
    hide_index=True,
)

summary_csv = view[detail_cols + ["Game", "Source File"]].to_csv(index=False).encode("utf-8")
pdf_bytes = build_pdf_report(view, inning_pivot, workload_table, lev_table, mid_cut, high_cut)

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
