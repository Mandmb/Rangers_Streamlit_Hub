
import streamlit as st
import pandas as pd
import numpy as np
import html
from datetime import datetime
from io import BytesIO

st.set_page_config(page_title="Lineup Optimization", layout="wide")

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


def normalize_bats(value):
    if pd.isna(value):
        return "R"
    side = str(value).strip().upper()
    left_values = ["L", "LEFT", "LHH", "LH", "LEFT-HANDED", "LEFT HANDED"]
    right_values = ["R", "RIGHT", "RHH", "RH", "RIGHT-HANDED", "RIGHT HANDED"]
    switch_values = ["S", "SW", "SWITCH", "BOTH", "SH", "SWITCH-HITTER", "SWITCH HITTER"]
    if side in left_values:
        return "L"
    if side in right_values:
        return "R"
    if side in switch_values:
        return "S"
    return side


def hitter_name_color(side):
    side = normalize_bats(side)
    if side == "L":
        return "#BA0C2F"
    if side == "S":
        return "#002D72"
    return "#111111"


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
    total_weight = sum(weights.values()) or 1
    normalized = normalize_stats(df, REQUIRED_STATS)
    score = np.zeros(len(df))
    for stat, weight in weights.items():
        score += normalized[stat] * (weight / total_weight)
    return score


def calculate_spot_fit_score(row, spot, normalized_df, user_weights):
    spot_weights = LINEUP_SPOT_WEIGHTS[spot]
    user_total = max(sum(user_weights.values()), 1)
    combined_weights = {}
    for stat in REQUIRED_STATS:
        combined_weights[stat] = (spot_weights[stat] * 0.60) + (
            user_weights[stat] / user_total * 0.40
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
                f"Not enough eligible players for {required_pos}. Needed {count_needed}, found {len(eligible)}."
            )
            continue
        chosen = eligible.head(count_needed)
        selected_rows.append(chosen)
        used_indexes.update(chosen.index.tolist())
    if not selected_rows:
        return pd.DataFrame()
    selected = pd.concat(selected_rows)
    if len(selected) < 9:
        remaining = df[~df.index.isin(selected.index)].sort_values("Overall Score", ascending=False)
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
    if "PA" in lineup.columns:
        display_cols.append("PA")
    display_cols += REQUIRED_STATS + ["Overall Score", "Spot Fit Score"]
    return lineup[display_cols]


def format_cell(value, col):
    if pd.isna(value):
        return ""
    if col in ["AVG", "OBP", "SLG", "ISO"]:
        try:
            return f"{float(value):.3f}".replace("0.", ".")
        except Exception:
            return str(value)
    if col in ["Overall Score", "Spot Fit Score"]:
        try:
            return f"{float(value):.4f}"
        except Exception:
            return str(value)
    if col in ["SB", "PA"]:
        try:
            return f"{int(float(value))}"
        except Exception:
            return str(value)
    return str(value)


def render_lineup_table(lineup):
    cols = lineup.columns.tolist()
    table_html = """
    <style>
    .lineup-table {width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 15px;}
    .lineup-table th {background-color: #002D72; color: white; text-align: center; padding: 10px; border: 1px solid #d9d9d9; font-weight: 700;}
    .lineup-table td {padding: 9px; border: 1px solid #e1e1e1; text-align: center;}
    .lineup-table tr:nth-child(even) {background-color: #f7f7f7;}
    .lineup-table tr:nth-child(odd) {background-color: #ffffff;}
    .player-name-cell {text-align: left !important; font-weight: 800;}
    </style>
    <table class="lineup-table"><thead><tr>
    """
    for col in cols:
        table_html += f"<th>{html.escape(str(col))}</th>"
    table_html += "</tr></thead><tbody>"
    for _, row in lineup.iterrows():
        table_html += "<tr>"
        bats = row["Bats"] if "Bats" in lineup.columns else "R"
        name_color = hitter_name_color(bats)
        for col in cols:
            value = format_cell(row[col], col)
            safe_value = html.escape(value)
            if col == "playerFullName":
                table_html += f'<td class="player-name-cell" style="color:{name_color};">{safe_value}</td>'
            else:
                table_html += f"<td>{safe_value}</td>"
        table_html += "</tr>"
    table_html += "</tbody></table>"
    st.markdown(table_html, unsafe_allow_html=True)


def prepare_dataframe(uploaded_file, label):
    try:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Could not read {label} CSV: {e}")
        return None

    df = clean_colnames(df)

    name_col = find_column(df, ["playerFullName", "PlayerFullName", "player_name", "playerName", "Name", "Player"])
    if name_col is None:
        st.error(f"Could not find a player name column in {label}. The app expects `playerFullName`.")
        return None

    df["playerFullName"] = df[name_col].astype(str).str.strip()
    bad_names = ["", "none", "nan", "null", "unknown"]
    df = df[~df["playerFullName"].str.lower().isin(bad_names)].copy()

    missing_stats = [stat for stat in REQUIRED_STATS if stat not in df.columns]
    if missing_stats:
        st.error(f"Missing required stat columns in {label}: {missing_stats}")
        st.write("Your CSV must include:", REQUIRED_STATS)
        return None

    for stat in REQUIRED_STATS:
        df[stat] = pd.to_numeric(df[stat], errors="coerce").fillna(0)

    position_col = find_column(df, ["Position", "position", "POS", "pos", "PrimaryPosition", "primaryPosition"])
    if position_col:
        df["Position"] = df[position_col].apply(normalize_position)

    bats_col = find_column(
        df,
        [
            "batsHand", "BatsHand", "batshand", "BATS HAND", "Bats Hand",
            "Bats", "bats", "BatSide", "batSide", "BatterSide", "batterSide",
            "HitterSide", "hitterSide", "Side", "side", "battingSide", "BattingSide",
            "BatterHand", "batterHand", "HitterHand", "hitterHand", "BatHand", "batHand",
            "Bats/Throws", "BatsThrows",
        ],
    )
    if bats_col:
        df["Bats"] = df[bats_col].apply(normalize_bats)
    else:
        df["Bats"] = "R"

    pa_col = find_column(
        df,
        [
            "PA", "pa", "PlateAppearances", "plateAppearances",
            "Plate Appearances", "plate appearances", "PAs", "pas",
        ],
    )
    if pa_col:
        df["PA"] = pd.to_numeric(df[pa_col], errors="coerce").fillna(0).astype(int)

    return df


def build_lineup(df, weights, enforce_positions, label):
    df = df.copy()
    df["Overall Score"] = calculate_overall_score(df, weights)
    df["Overall Score"] = df["Overall Score"].round(4)

    if len(df) < 9:
        st.error(f"{label}: You need at least 9 players in the CSV.")
        return None, df

    can_enforce = enforce_positions and "Position" in df.columns
    if enforce_positions and not can_enforce:
        st.warning(f"{label}: No position column found. Position requirements were ignored.")

    if can_enforce:
        selected = select_best_9_with_positions(df, "Position")
    else:
        selected = select_best_9_no_positions(df)

    if len(selected) < 9:
        st.error(f"{label}: Could not select 9 players. Check player pool and positions.")
        return None, df

    lineup = optimize_order(selected, weights)
    return lineup, df


def show_player_pool(df):
    preview_cols = ["playerFullName"]
    if "Position" in df.columns:
        preview_cols.append("Position")
    preview_cols.append("Bats")
    if "PA" in df.columns:
        preview_cols.append("PA")
    preview_cols += REQUIRED_STATS + ["Overall Score"]
    st.dataframe(
        df[preview_cols].sort_values("Overall Score", ascending=False),
        use_container_width=True,
        hide_index=True,
    )


def create_all_lineups_pdf(lineups_by_mode):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buffer = BytesIO()
    page_size = landscape(letter)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=0.35 * inch,
        rightMargin=0.35 * inch,
        topMargin=0.25 * inch,
        bottomMargin=0.25 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=20,
        textColor=colors.HexColor("#002D72"),
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=12,
        textColor=colors.white,
        alignment=TA_LEFT,
        leftIndent=4,
        spaceAfter=0,
    )
    name_style_base = ParagraphStyle(
        "NameBase",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6.6,
        leading=7.5,
        alignment=TA_LEFT,
    )
    cell_style = ParagraphStyle(
        "CellStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=6.6,
        leading=7.5,
        alignment=TA_CENTER,
    )

    story = []
    story.append(Paragraph("LINEUP OPTIMIZATION REPORT", title_style))
    story.append(
        Paragraph(
            f"Overall, vs RHP, and vs LHP optimized lineups • Generated {datetime.now().strftime('%b %d, %Y')}",
            subtitle_style,
        )
    )

    def p(txt, style):
        return Paragraph(str(txt), style)

    def name_paragraph(name, bats):
        style = ParagraphStyle(
            f"Name_{str(bats)}_{str(name)[:4]}",
            parent=name_style_base,
            textColor=colors.HexColor(hitter_name_color(bats)),
        )
        return Paragraph(html.escape(str(name)), style)

    table_cols = ["#", "Player", "Pos", "Bats", "PA", "AVG", "OBP", "SLG", "ISO", "SB", "Score"]
    col_widths = [0.27*inch, 1.75*inch, 0.42*inch, 0.35*inch, 0.38*inch, 0.48*inch, 0.48*inch, 0.48*inch, 0.48*inch, 0.35*inch, 0.55*inch]

    for mode, lineup in lineups_by_mode.items():
        section = Table(
            [[Paragraph(mode.upper(), section_style)]],
            colWidths=[sum(col_widths)],
            rowHeights=[0.22 * inch],
        )
        section.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#002D72")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#002D72")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(section)

        data = [[p(c, cell_style) for c in table_cols]]
        for _, row in lineup.iterrows():
            pos = row["Position"] if "Position" in lineup.columns else ""
            bats = row["Bats"] if "Bats" in lineup.columns else "R"
            pa = row["PA"] if "PA" in lineup.columns else ""
            data.append(
                [
                    p(format_cell(row["Lineup Spot"], "Lineup Spot"), cell_style),
                    name_paragraph(row["playerFullName"], bats),
                    p(format_cell(pos, "Position"), cell_style),
                    p(format_cell(bats, "Bats"), cell_style),
                    p(format_cell(pa, "PA"), cell_style),
                    p(format_cell(row["AVG"], "AVG"), cell_style),
                    p(format_cell(row["OBP"], "OBP"), cell_style),
                    p(format_cell(row["SLG"], "SLG"), cell_style),
                    p(format_cell(row["ISO"], "ISO"), cell_style),
                    p(format_cell(row["SB"], "SB"), cell_style),
                    p(format_cell(row["Overall Score"], "Overall Score"), cell_style),
                ]
            )

        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#BA0C2F")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("ALIGN", (1, 1), (1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F7FA")]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.6),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 0.10 * inch))

    story.append(
        Paragraph(
            '<font color="#BA0C2F"><b>LHH</b></font> = red &nbsp;&nbsp; | &nbsp;&nbsp; '
            '<font color="#002D72"><b>Switch</b></font> = blue &nbsp;&nbsp; | &nbsp;&nbsp; '
            '<font color="#111111"><b>RHH</b></font> = black',
            subtitle_style,
        )
    )

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def build_pdf_lineups(files, weights, enforce_positions):
    lineups = {}
    for mode_name, uploaded in files.items():
        if uploaded is None:
            return None, f"Missing {mode_name} CSV. Upload all 3 CSVs to create the PDF."
        df_mode = prepare_dataframe(uploaded, mode_name)
        if df_mode is None:
            return None, f"Could not prepare {mode_name} CSV."
        lineup_mode_df, _ = build_lineup(df_mode, weights, enforce_positions, mode_name)
        if lineup_mode_df is None:
            return None, f"Could not build {mode_name} lineup."
        lineups[mode_name] = lineup_mode_df
    return lineups, None


st.title("Lineup Optimization")
st.caption("Upload CSV files and optimize lineups overall, vs right-handed pitchers, and vs left-handed pitchers.")

st.markdown(
    """
    **Bats color key:**  
    <span style="color:#BA0C2F;font-weight:800;">Left-handed hitters</span> = red &nbsp; | &nbsp;
    <span style="color:#002D72;font-weight:800;">Switch hitters</span> = blue &nbsp; | &nbsp;
    <span style="color:#111111;font-weight:800;">Right-handed hitters</span> = black
    """,
    unsafe_allow_html=True,
)

st.sidebar.header("Stat Weights")
avg_weight = st.sidebar.slider("AVG Weight", 0.0, 5.0, 1.0, 0.1)
obp_weight = st.sidebar.slider("OBP Weight", 0.0, 5.0, 2.0, 0.1)
slg_weight = st.sidebar.slider("SLG Weight", 0.0, 5.0, 2.0, 0.1)
iso_weight = st.sidebar.slider("ISO Weight", 0.0, 5.0, 1.5, 0.1)
sb_weight = st.sidebar.slider("SB Weight", 0.0, 5.0, 0.8, 0.1)
weights = {"AVG": avg_weight, "OBP": obp_weight, "SLG": slg_weight, "ISO": iso_weight, "SB": sb_weight}

st.sidebar.divider()
enforce_positions = st.sidebar.checkbox(
    "Use position requirements",
    value=False,
    help="Optional. If checked, the app will try to include C, 1B, 2B, 3B, SS, 3 OF, and DH.",
)

st.sidebar.divider()
lineup_mode = st.sidebar.radio(
    "Lineup Type",
    ["Overall", "Vs RHP", "Vs LHP"],
    help="Choose which uploaded CSV to use for the optimized lineup.",
)

col1, col2, col3 = st.columns(3)
with col1:
    overall_file = st.file_uploader("Overall CSV", type=["csv"], key="overall_csv")
with col2:
    vs_rhp_file = st.file_uploader("Vs RHP CSV", type=["csv"], key="vs_rhp_csv")
with col3:
    vs_lhp_file = st.file_uploader("Vs LHP CSV", type=["csv"], key="vs_lhp_csv")

files = {
    "Overall": overall_file,
    "Vs RHP": vs_rhp_file,
    "Vs LHP": vs_lhp_file,
}

selected_file = files[lineup_mode]

if selected_file is None:
    st.info(f"Upload the {lineup_mode} CSV to generate that lineup.")
    st.stop()

df = prepare_dataframe(selected_file, lineup_mode)
if df is None:
    st.stop()

lineup, scored_df = build_lineup(df, weights, enforce_positions, lineup_mode)
if lineup is None:
    st.stop()

st.subheader(f"Uploaded Player Pool — {lineup_mode}")
show_player_pool(scored_df)

st.subheader(f"Optimized Lineup — {lineup_mode}")
render_lineup_table(lineup)

csv = lineup.to_csv(index=False).encode("utf-8")
st.download_button(
    label=f"Download {lineup_mode} Optimized Lineup CSV",
    data=csv,
    file_name=f"optimized_lineup_{lineup_mode.lower().replace(' ', '_')}.csv",
    mime="text/csv",
)

st.divider()
st.subheader("PDF Report")

pdf_lineups, pdf_error = build_pdf_lineups(files, weights, enforce_positions)

if pdf_error:
    st.info(pdf_error)
else:
    try:
        pdf_bytes = create_all_lineups_pdf(pdf_lineups)
        st.download_button(
            label="Download PDF with All 3 Optimized Lineups",
            data=pdf_bytes,
            file_name="all_three_optimized_lineups.pdf",
            mime="application/pdf",
            type="primary",
        )
    except Exception as e:
        st.error(f"Could not create PDF report: {e}")

st.markdown("### Lineup Notes")
st.write(
    """
    - Use the sidebar to choose between Overall, Vs RHP, and Vs LHP.
    - Upload only the CSVs you need. Each lineup uses the stats from its selected CSV.
    - Position requirements are optional.
    - When position requirements are off, the app selects the best 9 offensive players.
    - When position requirements are on, the app attempts to include C, 1B, 2B, 3B, SS, 3 OF, and DH.
    - The batting order uses both your selected stat weights and spot-specific logic.
    """
)
