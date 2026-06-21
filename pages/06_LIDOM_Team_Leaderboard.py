import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from io import BytesIO
from datetime import datetime
import tempfile
import os
import textwrap


try:
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# =====================================================
# PAGE CONFIG
# =====================================================
st.set_page_config(
    page_title="LIDOM Team Hitting & Baserunning Leaderboard",
    page_icon="⚾",
    layout="wide",
)

# =====================================================
# TEAM COLORS
# =====================================================
TEAM_COLORS = {
    "Leones del Escogido": "#D71920",   # red
    "Tigres del Licey": "#0057B8",      # blue
    "Toros del Este": "#F58220",        # orange
    "Gigantes del Cibao": "#7A3E1D",    # brown
    "Estrellas Orientales": "#00843D",  # green
    "Aguilas Cibaenas": "#FFD200",      # yellow
    "Águilas Cibaeñas": "#FFD200",
}

HITTING_STATS = [
    "Hits", "Single", "Double", "Triple", "Homerun",
    "BA", "OBP", "SLG", "OPS", "BB%", "K%"
]
BASERUNNING_STATS = ["SB", "CS", "SB%"]
PITCHING_STATS = ["ERA", "FIP", "WHIP", "K%", "BB%", "HR%", "BAA"]
DEFENSE_STATS = ["CS%", "IFErr", "IFFld%", "OFErr", "OFFld%"]
RATE_STATS = {"BA", "OBP", "SLG", "OPS", "BB%", "K%", "SB%", "HR%", "BAA", "CS%", "IFFld%", "OFFld%"}

# =====================================================
# HELPERS
# =====================================================
def clean_text(x):
    if pd.isna(x):
        return ""
    return str(x).strip()


def is_ball_pitch(result: str) -> bool:
    r = result.lower()
    return r in {"ball", "ball in the dirt", "intent ball", "automatic ball"} or r.startswith("ball")


def hit_type(result: str) -> str | None:
    """Return Single/Double/Triple/Homerun if pitchResult is a hit."""
    r = result.lower()
    if r.startswith("single"):
        return "Single"
    if r.startswith("double on"):
        return "Double"
    if r.startswith("triple"):
        return "Triple"
    if r.startswith("home run") or r.startswith("homerun"):
        return "Homerun"
    return None


def is_walk(result: str) -> bool:
    r = result.lower()
    return r == "walk" or "intentional walk" in r


def is_hbp(result: str) -> bool:
    return "hit by pitch" in result.lower() or result.lower() == "hbp"


def is_strikeout(result: str) -> bool:
    return "strikeout" in result.lower()


def normalize_team_name(name: str, fallback: str = "Unknown") -> str:
    name = clean_text(name)
    if not name:
        return fallback
    # Normalize common no-accent file values to official display if desired.
    if name.lower() in {"aguilas cibaenas", "águilas cibaeñas"}:
        return "Aguilas Cibaenas"
    return name


def required_columns_ok(df: pd.DataFrame):
    required = ["fullName", "pitchResult", "BaseStealAtt", "outs"]
    missing = [c for c in required if c not in df.columns]
    return missing


def add_pa_id(df: pd.DataFrame) -> pd.DataFrame:
    """Create a plate appearance ID.

    Preferred method: gameId + abNumInGame, because your CSV contains both.
    Fallback: starts a new PA when pitchNumInAB == 1 or batter changes.
    """
    df = df.copy().reset_index(drop=True)

    if "gameId" in df.columns and "abNumInGame" in df.columns:
        df["pa_id"] = (
            df["gameId"].astype(str).fillna("")
            + "_"
            + df["abNumInGame"].astype(str).fillna("")
        )
        return df

    batter_col = "batterAbbrevName" if "batterAbbrevName" in df.columns else None
    new_pa = pd.Series(False, index=df.index)

    if "pitchNumInAB" in df.columns:
        new_pa |= pd.to_numeric(df["pitchNumInAB"], errors="coerce").fillna(0).eq(1)

    if batter_col:
        new_pa |= df[batter_col].ne(df[batter_col].shift(1))

    if "gameId" in df.columns:
        new_pa |= df["gameId"].ne(df["gameId"].shift(1))

    if len(new_pa):
        new_pa.iloc[0] = True
    df["pa_id"] = new_pa.cumsum()
    return df


def summarize_hitting(df: pd.DataFrame) -> pd.DataFrame:
    df = add_pa_id(df.copy())
    df["pitchResult_clean"] = df["pitchResult"].apply(clean_text)
    df["fullName"] = df["fullName"].apply(normalize_team_name)

    date_col = "date" if "date" in df.columns else "gameDate" if "gameDate" in df.columns else None
    if date_col:
        df["game_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    else:
        df["game_date"] = pd.NaT

    rows = []
    group_cols = ["fullName", "game_date", "pa_id"]
    for (team, game_date, pa_id), pa in df.groupby(group_cols, dropna=False, sort=False):
        results = pa["pitchResult_clean"].tolist()
        final_result = results[-1] if results else ""
        balls_in_pa = sum(is_ball_pitch(r) for r in results)

        htype = None
        for r in results[::-1]:
            htype = hit_type(r)
            if htype:
                break

        walk = is_walk(final_result) or balls_in_pa >= 4
        hbp = is_hbp(final_result)
        strikeout = is_strikeout(final_result)

        single = int(htype == "Single")
        double = int(htype == "Double")
        triple = int(htype == "Triple")
        homerun = int(htype == "Homerun")
        hits = single + double + triple + homerun
        total_bases = single + 2 * double + 3 * triple + 4 * homerun

        rows.append({
            "fullName": normalize_team_name(team),
            "game_date": game_date,
            "PA": 1,
            "AB": 0 if (walk or hbp) else 1,
            "Hits": hits,
            "Single": single,
            "Double": double,
            "Triple": triple,
            "Homerun": homerun,
            "BB": int(walk),
            "HBP": int(hbp),
            "K": int(strikeout),
            "TB": total_bases,
            "ReachedBase": int(hits > 0 or walk or hbp),
        })

    pa_df = pd.DataFrame(rows)
    return pa_df


def summarize_baserunning(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    df["fullName"] = df["fullName"].apply(normalize_team_name)
    date_col = "date" if "date" in df.columns else "gameDate" if "gameDate" in df.columns else None
    if date_col:
        df["game_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    else:
        df["game_date"] = pd.NaT

    df["outs_num"] = pd.to_numeric(df["outs"], errors="coerce")
    df["next_outs"] = df["outs_num"].shift(-1)
    if "gameId" in df.columns:
        # Do not compare outs across games.
        same_game_next = df["gameId"].eq(df["gameId"].shift(-1))
        df.loc[~same_game_next, "next_outs"] = np.nan

    attempts = df[df["BaseStealAtt"].notna() & (df["BaseStealAtt"].astype(str).str.strip() != "")].copy()
    if attempts.empty:
        return pd.DataFrame(columns=["fullName", "game_date", "SB", "CS", "SBA"])

    def cs_from_outs(row):
        outs = row["outs_num"]
        nxt = row["next_outs"]
        if pd.isna(outs) or pd.isna(nxt):
            return 0
        # User rule: 0->1, 1->2, or 2->0 means unsuccessful steal / caught stealing.
        return int((outs == 0 and nxt == 1) or (outs == 1 and nxt == 2) or (outs == 2 and nxt == 0))

    attempts["CS"] = attempts.apply(cs_from_outs, axis=1)
    attempts["SB"] = 1 - attempts["CS"]
    attempts["SBA"] = 1
    return attempts[["fullName", "game_date", "SB", "CS", "SBA"]]


def add_hitting_rates(team_df: pd.DataFrame) -> pd.DataFrame:
    out = team_df.copy()
    out["BA"] = np.where(out["AB"] > 0, out["Hits"] / out["AB"], np.nan)
    out["OBP"] = np.where(out["PA"] > 0, out["ReachedBase"] / out["PA"], np.nan)
    # Per your request, SLG uses PA as denominator.
    out["SLG"] = np.where(out["PA"] > 0, out["TB"] / out["PA"], np.nan)
    out["OPS"] = out["OBP"].fillna(0) + out["SLG"].fillna(0)
    out["BB%"] = np.where(out["PA"] > 0, out["BB"] / out["PA"], np.nan)
    out["K%"] = np.where(out["PA"] > 0, out["K"] / out["PA"], np.nan)
    return out


def add_baserunning_rates(team_df: pd.DataFrame) -> pd.DataFrame:
    out = team_df.copy()
    out["SB%"] = np.where(out["SBA"] > 0, out["SB"] / out["SBA"], np.nan)
    return out


def build_team_hitting(pa_df: pd.DataFrame) -> pd.DataFrame:
    sum_cols = ["PA", "AB", "Hits", "Single", "Double", "Triple", "Homerun", "BB", "HBP", "K", "TB", "ReachedBase"]
    team = pa_df.groupby("fullName", as_index=False)[sum_cols].sum()
    return add_hitting_rates(team)


def build_team_baserunning(br_df: pd.DataFrame) -> pd.DataFrame:
    if br_df.empty:
        return pd.DataFrame(columns=["fullName", "SB", "CS", "SBA", "SB%"])
    team = br_df.groupby("fullName", as_index=False)[["SB", "CS", "SBA"]].sum()
    return add_baserunning_rates(team)


def build_rolling_hitting(pa_df: pd.DataFrame) -> pd.DataFrame:
    sum_cols = ["PA", "AB", "Hits", "Single", "Double", "Triple", "Homerun", "BB", "HBP", "K", "TB", "ReachedBase"]
    daily = pa_df.groupby(["fullName", "game_date"], as_index=False)[sum_cols].sum().sort_values(["fullName", "game_date"])
    for c in sum_cols:
        daily[c] = daily.groupby("fullName")[c].cumsum()
    return add_hitting_rates(daily)


def build_rolling_baserunning(br_df: pd.DataFrame) -> pd.DataFrame:
    if br_df.empty:
        return pd.DataFrame(columns=["fullName", "game_date", "SB", "CS", "SBA", "SB%"])
    daily = br_df.groupby(["fullName", "game_date"], as_index=False)[["SB", "CS", "SBA"]].sum().sort_values(["fullName", "game_date"])
    for c in ["SB", "CS", "SBA"]:
        daily[c] = daily.groupby("fullName")[c].cumsum()
    return add_baserunning_rates(daily)


def format_value(stat, val):
    if pd.isna(val):
        return "—"
    if stat in {"BA", "OBP", "SLG", "OPS", "BAA"}:
        return f"{float(val):.3f}".replace("0.", ".")
    if stat in {"ERA", "FIP", "WHIP"}:
        return f"{float(val):.2f}"
    if stat in {"BB%", "K%", "SB%", "HR%", "CS%", "IFFld%", "OFFld%"}:
        return f"{val:.1%}"
    return f"{int(val)}"


def leaderboard_table(df: pd.DataFrame, stat: str, ascending: bool = False):
    if df.empty or stat not in df.columns:
        return pd.DataFrame(columns=["Rank", "Team", stat])
    show = df[["fullName", stat]].copy()
    show = show.sort_values(stat, ascending=ascending, na_position="last").reset_index(drop=True)
    show.insert(0, "Rank", np.arange(1, len(show) + 1))
    show[stat] = show[stat].apply(lambda v: format_value(stat, v))
    show = show.rename(columns={"fullName": "Team"})
    return show


def style_table(df: pd.DataFrame):
    return df.style.set_properties(**{
        "text-align": "center",
        "white-space": "nowrap",
    }).set_table_styles([
        {"selector": "th", "props": [("background-color", "#333333"), ("color", "white"), ("text-align", "center")]},
        {"selector": "td", "props": [("text-align", "center")]},
    ])


def make_chart(df: pd.DataFrame, stat: str, title: str):
    chart_df = df.dropna(subset=["game_date"]).copy()
    chart_df["game_date"] = pd.to_datetime(chart_df["game_date"])
    chart_df = chart_df.sort_values(["fullName", "game_date"])
    fig = px.line(
        chart_df,
        x="game_date",
        y=stat,
        color="fullName",
        markers=True,
        color_discrete_map=TEAM_COLORS,
        title=title,
        labels={"game_date": "Date", "fullName": "Team", stat: stat},
    )
    if stat in {"BB%", "K%", "SB%"}:
        fig.update_yaxes(tickformat=".0%")
    fig.update_layout(height=440, legend_title_text="Team")
    return fig


def _parse_percent_or_number(x):
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    if not s or s.lower() in {"nan", "none", "-"}:
        return np.nan
    if s.endswith("%"):
        return pd.to_numeric(s[:-1], errors="coerce") / 100.0
    return pd.to_numeric(s, errors="coerce")


def pitching_lower_is_better(stat: str) -> bool:
    return stat in {"ERA", "FIP", "WHIP", "BB%", "HR%", "BAA"}


def build_pitching_from_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Clean LIDOM Draft pitching CSV and return one row per team."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["fullName"] + PITCHING_STATS)
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    if "teamFullName" not in out.columns:
        return pd.DataFrame(columns=["fullName"] + PITCHING_STATS)
    out = out[out["teamFullName"].notna()].copy()
    out["teamFullName"] = out["teamFullName"].astype(str).str.strip()
    out = out[~out["teamFullName"].str.upper().isin(["TOTAL", "AVERAGE", "TEAMFULLNAME", "NAN", "-"])]
    out = out[out["teamFullName"].ne("")]
    keep_map = {
        "teamFullName": "fullName",
        "ERA": "ERA",
        "FIP": "FIP",
        "WHIP": "WHIP",
        "K%": "K%",
        "BB%": "BB%",
        "HR%": "HR%",
        "AVG": "BAA",
    }
    available = [c for c in keep_map if c in out.columns]
    out = out[available].rename(columns=keep_map)
    out["fullName"] = out["fullName"].apply(normalize_team_name)
    for col in PITCHING_STATS:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = out[col].apply(_parse_percent_or_number)
    return out[["fullName"] + PITCHING_STATS].reset_index(drop=True)



def defense_lower_is_better(stat: str) -> bool:
    return stat in {"IFErr", "OFErr"}


def _clean_team_snapshot_df(df: pd.DataFrame, required_team_col: str = "teamFullName") -> pd.DataFrame:
    """Remove TOTAL/AVERAGE/repeated header rows and normalize team names."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    if required_team_col not in out.columns:
        return pd.DataFrame()
    out = out[out[required_team_col].notna()].copy()
    out[required_team_col] = out[required_team_col].astype(str).str.strip()
    bad = {"TOTAL", "AVERAGE", required_team_col.upper(), "TEAMFULLNAME", "NAN", "-", ""}
    out = out[~out[required_team_col].str.upper().isin(bad)].copy()
    out["fullName"] = out[required_team_col].apply(normalize_team_name)
    return out


def build_defense_from_csvs(catcher_df=None, infield_df=None, outfield_df=None) -> pd.DataFrame:
    """Build one team-level defense table from catcher, infield, and outfield CSVs."""
    frames = []

    # Catchers: 2022 Game Review, use CS% only.
    cdf = _clean_team_snapshot_df(catcher_df) if catcher_df is not None else pd.DataFrame()
    if not cdf.empty and "CS%" in cdf.columns:
        tmp = cdf[["fullName", "CS%"]].copy()
        tmp["CS%"] = tmp["CS%"].apply(_parse_percent_or_number)
        frames.append(tmp)

    # Infield: Infield Counting, use IFErr and IFFld%.
    idf = _clean_team_snapshot_df(infield_df) if infield_df is not None else pd.DataFrame()
    if not idf.empty:
        fld_col = "IFFld%" if "IFFld%" in idf.columns else "INFld%" if "INFld%" in idf.columns else None
        cols = ["fullName"]
        if "IFErr" in idf.columns:
            cols.append("IFErr")
        if fld_col:
            cols.append(fld_col)
        if len(cols) > 1:
            tmp = idf[cols].copy()
            if fld_col and fld_col != "IFFld%":
                tmp = tmp.rename(columns={fld_col: "IFFld%"})
            if "IFErr" in tmp.columns:
                tmp["IFErr"] = pd.to_numeric(tmp["IFErr"], errors="coerce")
            if "IFFld%" in tmp.columns:
                tmp["IFFld%"] = tmp["IFFld%"].apply(_parse_percent_or_number)
            frames.append(tmp)

    # Outfield: Outfield Counting, use OFErr and OFFld%.
    odf = _clean_team_snapshot_df(outfield_df) if outfield_df is not None else pd.DataFrame()
    if not odf.empty:
        cols = ["fullName"]
        if "OFErr" in odf.columns:
            cols.append("OFErr")
        if "OFFld%" in odf.columns:
            cols.append("OFFld%")
        if len(cols) > 1:
            tmp = odf[cols].copy()
            if "OFErr" in tmp.columns:
                tmp["OFErr"] = pd.to_numeric(tmp["OFErr"], errors="coerce")
            if "OFFld%" in tmp.columns:
                tmp["OFFld%"] = tmp["OFFld%"].apply(_parse_percent_or_number)
            frames.append(tmp)

    if not frames:
        return pd.DataFrame(columns=["fullName"] + DEFENSE_STATS)

    defense = frames[0]
    for frame in frames[1:]:
        defense = defense.merge(frame, on="fullName", how="outer")
    for col in DEFENSE_STATS:
        if col not in defense.columns:
            defense[col] = np.nan
    return defense[["fullName"] + DEFENSE_STATS].reset_index(drop=True)


def make_pitching_bar_chart(df: pd.DataFrame, stat: str, title: str):
    if df.empty or stat not in df.columns:
        return None
    chart_df = df[["fullName", stat]].dropna().sort_values(stat, ascending=pitching_lower_is_better(stat))
    fig = px.bar(chart_df, x="fullName", y=stat, color="fullName", color_discrete_map=TEAM_COLORS, title=title, labels={"fullName": "Team", stat: stat})
    if stat in {"K%", "BB%", "HR%"}:
        fig.update_yaxes(tickformat=".0%")
    fig.update_layout(height=420, showlegend=False)
    return fig


def to_excel(hitting, baserunning, rolling_hitting, rolling_baserunning, pitching=None, defense=None):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        hitting.to_excel(writer, index=False, sheet_name="Hitting Leaderboard")
        baserunning.to_excel(writer, index=False, sheet_name="Baserunning")
        rolling_hitting.to_excel(writer, index=False, sheet_name="Rolling Hitting")
        rolling_baserunning.to_excel(writer, index=False, sheet_name="Rolling Baserunning")
        if pitching is not None and not pitching.empty:
            pitching.to_excel(writer, index=False, sheet_name="Pitching Leaderboard")
        if defense is not None and not defense.empty:
            defense.to_excel(writer, index=False, sheet_name="Defense Leaderboard")
    output.seek(0)
    return output



# =====================================================
# BEAUTIFUL PDF EXPORT HELPERS
# =====================================================
def pdf_rank_table(df: pd.DataFrame, stat: str, ascending: bool = False) -> pd.DataFrame:
    table = leaderboard_table(df, stat, ascending=ascending)
    return table


TEAM_LOGO_KEYS = {
    "Aguilas Cibaenas": "aguilas",
    "Águilas Cibaeñas": "aguilas",
    "Leones del Escogido": "escogido",
    "Estrellas Orientales": "estrellas",
    "Gigantes del Cibao": "gigantes",
    "Tigres del Licey": "licey",
    "Toros del Este": "toros",
}

LOGO_FILENAMES = {
    "lidom": "LIDOM.png",
    "aguilas": "aguilas.png",
    "escogido": "escogido.png",
    "estrellas": "estrellas.png",
    "gigantes": "gigantes.png",
    "licey": "licey.png",
    "toros": "toros.png",
    "baserunning": "baserunning.png",
}

STAT_LABELS = {
    "Hits": ("HITS", "Total hits"),
    "Single": ("SINGLES", "Base hits"),
    "Double": ("DOUBLES", "Extra-base hits"),
    "Triple": ("TRIPLES", "Speed + power"),
    "Homerun": ("HOME RUNS", "Most HR"),
    "BA": ("BA", "Batting average"),
    "OBP": ("OBP", "On-base percentage"),
    "SLG": ("SLG", "Slugging percentage"),
    "OPS": ("OPS", "On-base plus slugging"),
    "BB%": ("BB%", "Walk percentage"),
    "K%": ("K%", "Strikeout percentage"),
    "SB": ("SB", "Stolen bases"),
    "CS": ("CS", "Caught stealing"),
    "SB%": ("SB%", "Success rate"),
    "ERA": ("ERA", "Earned run average"),
    "FIP": ("FIP", "Fielding independent pitching"),
    "WHIP": ("WHIP", "Walks + hits per inning"),
    "BAA": ("BAA", "Opponent batting average"),
    "HR%": ("HR%", "Home run percentage"),
    "CS%": ("CATCHER CS%", "Caught stealing rate"),
    "IFErr": ("IF ERRORS", "Infield errors"),
    "IFFld%": ("IF FIELD%", "Infield fielding percentage"),
    "OFErr": ("OF ERRORS", "Outfield errors"),
    "OFFld%": ("OF FIELD%", "Outfield fielding percentage"),
}

ICON_SYMBOLS = {
    "SB": "⚡",
    "CS": "◇",
    "SB%": "%",
}


def find_default_logo_path(key: str) -> str | None:
    """Find a logo next to the app file or in /mnt/data during ChatGPT testing."""
    filename = LOGO_FILENAMES.get(key)
    if not filename:
        return None
    candidates = []
    try:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename))
    except Exception:
        pass
    candidates.extend([
        os.path.join(os.getcwd(), filename),
        os.path.join('/mnt/data', filename),
    ])
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def prepare_logo_paths(logo_uploads: dict | None = None) -> dict:
    paths = {}
    logo_uploads = logo_uploads or {}
    for key in LOGO_FILENAMES:
        upload = logo_uploads.get(key)
        if upload is not None:
            suffix = os.path.splitext(LOGO_FILENAMES[key])[1] or '.png'
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            try:
                tmp.write(upload.getvalue())
            except Exception:
                tmp.write(upload.read())
            tmp.close()
            paths[key] = tmp.name
        else:
            default_path = find_default_logo_path(key)
            if default_path:
                paths[key] = default_path
    return paths


def team_logo_key(team: str) -> str | None:
    return TEAM_LOGO_KEYS.get(normalize_team_name(team))


def safe_draw_image(c, path, x, y, w, h):
    if not path or not os.path.exists(path):
        return False
    try:
        c.drawImage(ImageReader(path), x, y, width=w, height=h, preserveAspectRatio=True, mask='auto')
        return True
    except Exception:
        return False


def draw_wrapped_text(c, text, x, y, width, font="Helvetica", size=8, color="#111111", leading=10, max_lines=6):
    c.setFillColor(colors.HexColor(color))
    c.setFont(font, size)
    avg_char = max(size * 0.47, 3.2)
    max_chars = max(20, int(width / avg_char))
    lines = []
    for para in str(text).split('\n'):
        lines.extend(textwrap.wrap(para, max_chars) or [""])
    for line in lines[:max_lines]:
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_header(c, title, subtitle, bg, logo_paths, page_type="blue"):
    W, H = landscape(letter)
    c.setFillColor(colors.HexColor(bg))
    c.rect(0, H - 84, W, 84, fill=1, stroke=0)
    # small accent ribbon
    accent = "#BA0C2F" if page_type == "blue" else "#002D72"
    c.setFillColor(colors.HexColor(accent))
    c.rect(0, H - 92, W, 8, fill=1, stroke=0)
    safe_draw_image(c, logo_paths.get("lidom"), 28, H - 76, 56, 56)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(96, H - 42, title)
    c.setFont("Helvetica", 9)
    c.drawString(98, H - 63, subtitle)


def draw_footer(c, page_num, logo_paths, bg="#001F4E"):
    W, H = landscape(letter)
    c.setFillColor(colors.HexColor(bg))
    c.rect(0, 0, W, 28, fill=1, stroke=0)
    safe_draw_image(c, logo_paths.get("escogido"), 24, 5, 52, 18)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(W / 2, 10, "PASIÓN   ★   TRADICIÓN   ★   GLORIA")
    c.drawRightString(W - 24, 10, f"Page {page_num}")


def draw_section_title(c, text, x, y, color="#002D72"):
    c.setFillColor(colors.HexColor(color))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y, text)
    c.setFont("Helvetica", 8)


def rank_position(df, stat, team="Leones del Escogido", ascending=False):
    if df.empty or stat not in df.columns:
        return None, None
    show = df[["fullName", stat]].copy().sort_values(stat, ascending=ascending, na_position="last").reset_index(drop=True)
    mask = show["fullName"].eq(team)
    if not mask.any():
        return None, None
    idx = int(show.index[mask][0])
    return idx + 1, show.loc[idx, stat]


def safe_fmt(stat, val):
    return format_value(stat, val) if val is not None and not pd.isna(val) else "—"


def make_escogido_summary(section, hitting, baserunning):
    if section == "hitting":
        ops_r, ops_v = rank_position(hitting, "OPS", ascending=False)
        obp_r, obp_v = rank_position(hitting, "OBP", ascending=False)
        slg_r, slg_v = rank_position(hitting, "SLG", ascending=False)
        ba_r, ba_v = rank_position(hitting, "BA", ascending=False)
        bb_r, bb_v = rank_position(hitting, "BB%", ascending=False)
        k_r, k_v = rank_position(hitting, "K%", ascending=True)
        hits_r, hits_v = rank_position(hitting, "Hits", ascending=False)
        hr_r, hr_v = rank_position(hitting, "Homerun", ascending=False)
        return (
            f"FORTALEZA: Escogido crea tráfico: OBP #{obp_r or '-'} ({safe_fmt('OBP', obp_v)}) y BB% #{bb_r or '-'} ({safe_fmt('BB%', bb_v)}).\n"
            f"PRODUCCIÓN: OPS #{ops_r or '-'} ({safe_fmt('OPS', ops_v)}), SLG #{slg_r or '-'} ({safe_fmt('SLG', slg_v)}) y BA #{ba_r or '-'} ({safe_fmt('BA', ba_v)}).\n"
            f"VOLUMEN/DAÑO: Hits #{hits_r or '-'} ({safe_fmt('Hits', hits_v)}) y HR #{hr_r or '-'} ({safe_fmt('Homerun', hr_v)}).\n"
            f"ENFOQUE: mantener la disciplina de zona, bajar K% #{k_r or '-'} ({safe_fmt('K%', k_v)}) y convertir más corredores en daño."
        )
    if section == "baserunning":
        sb_r, sb_v = rank_position(baserunning, "SB", ascending=False)
        cs_r, cs_v = rank_position(baserunning, "CS", ascending=True)
        rate_r, rate_v = rank_position(baserunning, "SB%", ascending=False)
        sba_r, sba_v = rank_position(baserunning, "SBA", ascending=False)
        return (
            f"AGRESIVIDAD: Escogido está #{sb_r or '-'} en SB ({safe_fmt('SB', sb_v)}) y #{sba_r or '-'} en intentos ({safe_fmt('SBA', sba_v)}).\n"
            f"EFICIENCIA: SB% #{rate_r or '-'} ({safe_fmt('SB%', rate_v)}) muestra espacio para ganar más valor por intento.\n"
            f"RIESGO: CS #{cs_r or '-'} ({safe_fmt('CS', cs_v)}) exige mejores selecciones de conteo, pitcher y situación.\n"
            f"ENFOQUE: mantener presión en bases, pero priorizar robos de alta probabilidad."
        )
    return (
        "IDENTIDAD: la tendencia de Escogido se apoya en llegar a base, competir turnos y presionar con velocidad.\n"
        "SEÑAL POSITIVA: OBP/BB% sostienen tráfico ofensivo y SB mantiene volumen dentro de la liga.\n"
        "ÁREA CLAVE: transformar ese tráfico en slugging/OPS y reducir outs evitables en bases.\n"
        "CIERRE: proteger OBP, buscar más contacto de impacto y mejorar eficiencia sin perder agresividad."
    )

def make_escogido_pitching_summary(pitching):
    if pitching is None or pitching.empty:
        return "Carga el archivo LIDOM Draft para generar el resumen de pitcheo de Escogido."
    era_r, era_v = rank_position(pitching, "ERA", ascending=True)
    fip_r, fip_v = rank_position(pitching, "FIP", ascending=True)
    whip_r, whip_v = rank_position(pitching, "WHIP", ascending=True)
    k_r, k_v = rank_position(pitching, "K%", ascending=False)
    bb_r, bb_v = rank_position(pitching, "BB%", ascending=True)
    hr_r, hr_v = rank_position(pitching, "HR%", ascending=True)
    baa_r, baa_v = rank_position(pitching, "BAA", ascending=True)
    return (
        f"CONTROL DE DAÑO: ERA #{era_r or '-'} ({safe_fmt('ERA', era_v)}) y FIP #{fip_r or '-'} ({safe_fmt('FIP', fip_v)}) resumen prevención de carreras.\n"
        f"TRÁFICO: WHIP #{whip_r or '-'} ({safe_fmt('WHIP', whip_v)}) y BAA #{baa_r or '-'} ({safe_fmt('BAA', baa_v)}) muestran qué tan difícil es llegar a base.\n"
        f"DOMINIO/COMANDO: K% #{k_r or '-'} ({safe_fmt('K%', k_v)}) vs BB% #{bb_r or '-'} ({safe_fmt('BB%', bb_v)}) marca el balance principal.\n"
        f"ENFOQUE: limitar HR% #{hr_r or '-'} ({safe_fmt('HR%', hr_v)}), atacar la zona y convertir ventajas en outs rápidos."
    )



def make_escogido_defense_summary(defense):
    if defense is None or defense.empty:
        return "Carga los archivos de defensa para generar el resumen defensivo de Escogido."
    cs_r, cs_v = rank_position(defense, "CS%", ascending=False)
    ife_r, ife_v = rank_position(defense, "IFErr", ascending=True)
    iff_r, iff_v = rank_position(defense, "IFFld%", ascending=False)
    ofe_r, ofe_v = rank_position(defense, "OFErr", ascending=True)
    off_r, off_v = rank_position(defense, "OFFld%", ascending=False)
    return (
        f"CATCHING: CS% #{cs_r or '-'} ({safe_fmt('CS%', cs_v)}) mide control del juego de correr y apoyo al pitcheo.\n"
        f"INFIELD: IFErr #{ife_r or '-'} ({safe_fmt('IFErr', ife_v)}) y IFFld% #{iff_r or '-'} ({safe_fmt('IFFld%', iff_v)}) muestran seguridad en outs rutinarios.\n"
        f"OUTFIELD: OFErr #{ofe_r or '-'} ({safe_fmt('OFErr', ofe_v)}) y OFFld% #{off_r or '-'} ({safe_fmt('OFFld%', off_v)}) resumen confiabilidad en el espacio.\n"
        f"ENFOQUE: convertir bolas en juego en outs, limitar errores gratis y sostener comunicación defensiva."
    )


def draw_summary_box(c, title, body, x, y, w, h, logo_paths):
    c.setStrokeColor(colors.HexColor("#BA0C2F"))
    c.setLineWidth(0.9)
    c.setFillColor(colors.white)
    c.roundRect(x, y, w, h, 7, fill=1, stroke=1)
    safe_draw_image(c, logo_paths.get("escogido"), x + 8, y + h - 28, 32, 18)
    c.setFillColor(colors.HexColor("#BA0C2F"))
    c.setFont("Helvetica-Bold", 8.0)
    c.drawString(x + 45, y + h - 19, title.upper())
    # Detailed but still compact: bold-style labels are written in all caps in the text itself.
    draw_wrapped_text(c, body, x + 10, y + h - 39, w - 20, size=6.1, leading=7.4, max_lines=11)


def draw_stat_table(c, df, stat, x, y, w, h, logo_paths, theme="#002D72", ascending=False, icon=None, icon_image=None):
    title, subtitle = STAT_LABELS.get(stat, (stat, stat))
    # Clean card with a little breathing room
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#D7DEE9"))
    c.setLineWidth(0.55)
    c.roundRect(x, y, w, h, 6, fill=1, stroke=1)

    header_h = 26
    c.setFillColor(colors.HexColor(theme))
    c.roundRect(x, y + h - header_h, w, header_h, 6, fill=1, stroke=0)
    c.rect(x, y + h - header_h, w, header_h - 5, fill=1, stroke=0)

    if icon_image:
        c.setFillColor(colors.white)
        c.circle(x + 19, y + h - 16, 12, fill=0, stroke=1)
        safe_draw_image(c, icon_image, x + 9, y + h - 26, 20, 20)
        title_x = x + 40
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(title_x, y + h - 14, title)
        c.setFont("Helvetica", 6.3)
        c.drawString(title_x, y + h - 25, subtitle)
    elif icon:
        c.setFillColor(colors.white)
        c.circle(x + 19, y + h - 16, 11, fill=0, stroke=1)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(x + 19, y + h - 20, icon)
        title_x = x + 38
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(title_x, y + h - 14, title)
        c.setFont("Helvetica", 6.3)
        c.drawString(title_x, y + h - 25, subtitle)
    else:
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(x + w / 2, y + h - 14, title)
        c.setFont("Helvetica", 6.2)
        c.drawCentredString(x + w / 2, y + h - 25, subtitle)

    # Column header
    ch_h = 15
    ch_y = y + h - header_h - ch_h
    c.setFillColor(colors.HexColor(theme))
    c.rect(x, ch_y, w, ch_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 6.2)
    c.drawCentredString(x + 17, ch_y + 5, "RANK")
    c.drawCentredString(x + w * 0.52, ch_y + 5, "TEAM")
    c.drawCentredString(x + w - 20, ch_y + 5, stat.upper())

    table = pdf_rank_table(df, stat, ascending=ascending)
    row_h = (h - header_h - ch_h) / 6.0
    top = ch_y
    for i in range(6):
        ry = top - (i + 1) * row_h
        if i < len(table):
            r = table.iloc[i]
            team = str(r["Team"])
            is_esc = normalize_team_name(team) == "Leones del Escogido"
        else:
            is_esc = False
        if is_esc:
            c.setFillColor(colors.HexColor("#FFF1F3"))
        else:
            c.setFillColor(colors.HexColor("#F6F8FB") if i % 2 else colors.white)
        c.rect(x, ry, w, row_h, fill=1, stroke=0)
        if i < len(table):
            r = table.iloc[i]
            team = str(r["Team"])
            val = str(r[stat])
            is_esc = normalize_team_name(team) == "Leones del Escogido"
            color = "#BA0C2F" if is_esc else "#111111"
            font = "Helvetica-Bold" if is_esc else "Helvetica"
            c.setFillColor(colors.HexColor(color))
            c.setFont(font, 8.0)
            c.drawCentredString(x + 17, ry + row_h / 2 - 2.2, str(r["Rank"]))
            key = team_logo_key(team)
            safe_draw_image(c, logo_paths.get(key), x + 40, ry + 2.0, 12, row_h - 4.0)
            c.drawString(x + 56, ry + row_h / 2 - 2.2, team[:30])
            c.drawRightString(x + w - 10, ry + row_h / 2 - 2.2, val)
        c.setStrokeColor(colors.HexColor("#E3E8F0"))
        c.setLineWidth(0.25)
        c.line(x, ry, x + w, ry)
    c.setStrokeColor(colors.HexColor("#DDE5EF"))
    c.line(x + 35, y, x + 35, ch_y + ch_h)
    c.line(x + w - 45, y, x + w - 45, ch_y + ch_h)

def make_pdf_chart_image(rolling_df: pd.DataFrame, stat: str, title: str, width: float = 2.35, height: float = 1.42):
    """Create a PNG chart for the ReportLab PDF using matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    chart_df = rolling_df.dropna(subset=["game_date"]).copy()
    if chart_df.empty or stat not in chart_df.columns:
        return None

    chart_df["game_date"] = pd.to_datetime(chart_df["game_date"], errors="coerce")
    chart_df = chart_df.dropna(subset=["game_date"]).sort_values(["fullName", "game_date"])
    if chart_df.empty:
        return None

    fig, ax = plt.subplots(figsize=(width, height), dpi=180)
    for team, team_df in chart_df.groupby("fullName", sort=False):
        color = TEAM_COLORS.get(team, None)
        ax.plot(team_df["game_date"], team_df[stat], linewidth=1.55, label=team, color=color)

    ax.set_title(title, fontsize=8, fontweight="bold", pad=5)
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.grid(True, linewidth=0.3, alpha=0.28)
    ax.tick_params(axis="both", labelsize=5)
    fig.autofmt_xdate(rotation=0)
    if stat in {"BA", "OBP", "SLG", "OPS"}:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{x:.3f}".replace("0.", ".")))
    elif stat in {"BB%", "K%", "SB%"}:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{x:.0%}"))
    fig.tight_layout(pad=0.7)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    fig.savefig(tmp.name, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return tmp.name


def draw_chart_grid(c, rolling_hitting, rolling_baserunning, x, y, w, h, logo_paths):
    """Cleaner rolling page: six key hitting trends plus three baserunning trends."""
    def chart(path_df, stat, title, cx, cy, cw, ch, width=2.45, height=1.25):
        path = make_pdf_chart_image(path_df, stat, title, width=width, height=height)
        if path:
            # Subtle chart card background
            c.setFillColor(colors.white)
            c.setStrokeColor(colors.HexColor("#E2E7EF"))
            c.roundRect(cx - 3, cy - 3, cw + 6, ch + 6, 5, fill=1, stroke=1)
            safe_draw_image(c, path, cx, cy, cw, ch)

    # Hitting key metrics: 3 columns x 2 rows, bigger and easier to read
    hit_stats = ["OPS", "OBP", "SLG", "BA", "BB%", "K%"]
    gx, gy, gw, gh = x, 292, w, 184
    gap_x, gap_y = 22, 18
    cols = 3
    cw = (gw - gap_x * (cols - 1)) / cols
    ch = (gh - gap_y) / 2
    for idx, stat in enumerate(hit_stats):
        row = idx // cols
        col = idx % cols
        cx = gx + col * (cw + gap_x)
        cy = gy + gh - (row + 1) * ch - row * gap_y
        chart(rolling_hitting, stat, stat, cx, cy, cw, ch, width=2.7, height=1.25)

    # Baserunning metrics: 3 wide charts in one row
    bx, by, bw, bh = x, 118, w * 0.68, 86
    gap_x = 18
    cw = (bw - gap_x * 2) / 3
    for idx, stat in enumerate(["SB", "CS", "SB%"]):
        cx = bx + idx * (cw + gap_x)
        chart(rolling_baserunning, stat, stat, cx, by, cw, bh, width=2.35, height=1.15)

    # Clean legend, one row when possible
    legend_y = 72
    lx = x + 4
    c.setFont("Helvetica", 6.0)
    for team in ["Aguilas Cibaenas", "Estrellas Orientales", "Toros del Este", "Leones del Escogido", "Gigantes del Cibao", "Tigres del Licey"]:
        c.setStrokeColor(colors.HexColor(TEAM_COLORS.get(team, "#333333")))
        c.setLineWidth(2.0)
        c.line(lx, legend_y, lx + 15, legend_y)
        c.setFillColor(colors.HexColor("#222222"))
        c.drawString(lx + 19, legend_y - 2.2, team.replace(" del ", " ").replace(" Orientales", ""))
        lx += 112

def to_pdf(hitting: pd.DataFrame, baserunning: pd.DataFrame, rolling_hitting: pd.DataFrame, rolling_baserunning: pd.DataFrame, pitching: pd.DataFrame | None = None, defense: pd.DataFrame | None = None, logo_uploads: dict | None = None) -> BytesIO:
    if not REPORTLAB_AVAILABLE:
        raise ImportError("ReportLab is not installed. Run: pip install reportlab")

    logo_paths = prepare_logo_paths(logo_uploads)
    output = BytesIO()
    c = canvas.Canvas(output, pagesize=landscape(letter))
    W, H = landscape(letter)
    date_txt = f"Generated {datetime.now().strftime('%b %d, %Y')}"

    # Page 1 - Hitting category leaderboards, cleaner 3-column layout
    draw_header(c, "LIDOM TEAM HITTING LEADERBOARDS", date_txt, "#001F4E", logo_paths, "blue")
    draw_section_title(c, "HITTING LEADERBOARDS BY CATEGORY   ★   ★", 24, H - 119, "#001F4E")

    left = 24
    top = H - 140
    gap_x = 14
    gap_y = 8
    table_w = (W - 2 * left - 2 * gap_x) / 3
    table_h = 93
    hit_stats = ["OPS", "OBP", "SLG", "BA", "Hits", "Homerun", "Double", "Triple", "BB%", "K%", "Single"]
    for idx, stat in enumerate(hit_stats):
        row = idx // 3
        col = idx % 3
        x = left + col * (table_w + gap_x)
        y = top - (row + 1) * table_h - row * gap_y
        draw_stat_table(c, hitting, stat, x, y, table_w, table_h, logo_paths, theme="#001F4E", ascending=(stat == "K%"))

    # Summary occupies the last open slot in the 3-column grid
    sx = left + 2 * (table_w + gap_x)
    sy = top - 4 * table_h - 3 * gap_y
    draw_summary_box(
        c,
        "Escogido Hitting Summary",
        make_escogido_summary("hitting", hitting, baserunning),
        sx,
        sy,
        table_w,
        table_h,
        logo_paths,
    )
    draw_footer(c, 1, logo_paths, "#001F4E")
    c.showPage()

    # Page 2 - Baserunning category leaderboards, bigger feature cards
    draw_header(c, "LIDOM TEAM BASERUNNING LEADERBOARDS", date_txt, "#A00012", logo_paths, "red")
    draw_section_title(c, "BASERUNNING LEADERBOARDS BY CATEGORY   ★", 34, H - 119, "#A00012")

    br_left = 44
    br_top = H - 148
    br_w = (W - 2 * br_left - 2 * 24) / 3
    br_h = 188
    for idx, stat in enumerate(["SB", "CS", "SB%"]):
        x = br_left + idx * (br_w + 24)
        y = br_top - br_h
        draw_stat_table(
            c,
            baserunning,
            stat,
            x,
            y,
            br_w,
            br_h,
            logo_paths,
            theme="#A00012",
            ascending=(stat == "CS"),
            icon=None if stat in ["SB", "CS"] else ICON_SYMBOLS.get(stat),
            icon_image=logo_paths.get("baserunning") if stat in ["SB", "CS"] else None,
        )

    # Rank callout strip for Escogido
    sb_r, sb_v = rank_position(baserunning, "SB", ascending=False)
    cs_r, cs_v = rank_position(baserunning, "CS", ascending=True)
    sbp_r, sbp_v = rank_position(baserunning, "SB%", ascending=False)
    c.setFillColor(colors.HexColor("#FFF2F4"))
    c.setStrokeColor(colors.HexColor("#BA0C2F"))
    c.roundRect(54, 198, W - 108, 46, 8, fill=1, stroke=1)
    safe_draw_image(c, logo_paths.get("escogido"), 66, 208, 54, 25)
    c.setFillColor(colors.HexColor("#A00012"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(132, 226, "ESCOGIDO BASERUNNING SNAPSHOT")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(132, 209, f"SB: #{sb_r or '-'} ({format_value('SB', sb_v) if sb_v is not None else '-'})   |   CS: #{cs_r or '-'} ({format_value('CS', cs_v) if cs_v is not None else '-'})   |   SB%: #{sbp_r or '-'} ({format_value('SB%', sbp_v) if sbp_v is not None else '-'})")

    draw_summary_box(
        c,
        "Escogido Baserunning Summary",
        make_escogido_summary("baserunning", hitting, baserunning),
        96,
        82,
        W - 192,
        88,
        logo_paths,
    )
    draw_footer(c, 2, logo_paths, "#A00012")
    c.showPage()

    # Page 3 - Rolling performance, larger key charts only
    draw_header(c, "LIDOM TEAM ROLLING PERFORMANCE", f"Rolling Cumulative Charts - {date_txt}", "#001F4E", logo_paths, "blue")
    draw_section_title(c, "HITTING METRICS (Rolling Cumulative)   ★", 30, H - 120, "#001F4E")
    draw_section_title(c, "BASERUNNING METRICS (Rolling Cumulative)   ★", 30, 226, "#BA0C2F")
    draw_chart_grid(c, rolling_hitting, rolling_baserunning, 38, 82, W - 76, 390, logo_paths)
    draw_summary_box(
        c,
        "Escogido Team Rolling Summary",
        make_escogido_summary("rolling", hitting, baserunning),
        535,
        100,
        235,
        125,
        logo_paths,
    )
    draw_footer(c, 3, logo_paths, "#001F4E")
    c.showPage()

    # Page 4 - Pitching category leaderboards from LIDOM Draft snapshot
    draw_header(c, "LIDOM TEAM PITCHING LEADERBOARDS", date_txt, "#001F4E", logo_paths, "blue")
    draw_section_title(c, "PITCHING LEADERBOARDS BY CATEGORY   ★", 24, H - 119, "#001F4E")

    if pitching is None or pitching.empty:
        c.setFillColor(colors.HexColor("#444444"))
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(W / 2, H / 2, "Upload the LIDOM Draft pitching CSV to generate this page.")
    else:
        p_left = 42
        p_top = H - 148
        p_gap_x = 20
        p_gap_y = 14
        p_table_w = (W - 2 * p_left - 2 * p_gap_x) / 3
        p_table_h = 126
        for idx, stat in enumerate(PITCHING_STATS):
            row = idx // 3
            col = idx % 3
            x = p_left + col * (p_table_w + p_gap_x)
            y = p_top - (row + 1) * p_table_h - row * p_gap_y
            draw_stat_table(
                c,
                pitching,
                stat,
                x,
                y,
                p_table_w,
                p_table_h,
                logo_paths,
                theme="#001F4E",
                ascending=pitching_lower_is_better(stat),
            )
        draw_summary_box(
            c,
            "Escogido Pitching Summary",
            make_escogido_pitching_summary(pitching),
            p_left + (p_table_w + p_gap_x),
            62,
            (p_table_w * 2) + p_gap_x,
            94,
            logo_paths,
        )
    draw_footer(c, 4, logo_paths, "#001F4E")
    c.showPage()

    # Page 5 - Defense category leaderboards from catcher, infield, and outfield snapshots
    draw_header(c, "LIDOM TEAM DEFENSE LEADERBOARDS", date_txt, "#A00012", logo_paths, "red")
    draw_section_title(c, "DEFENSE LEADERBOARDS BY CATEGORY   ★", 24, H - 119, "#A00012")

    if defense is None or defense.empty:
        c.setFillColor(colors.HexColor("#444444"))
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(W / 2, H / 2, "Upload 2022 Game Review, Infield Counting, and Outfield Counting CSVs to generate this page.")
    else:
        d_left = 34
        d_top = H - 148
        d_gap_x = 18
        d_gap_y = 16
        d_table_w = (W - 2 * d_left - 2 * d_gap_x) / 3
        d_table_h = 142
        d_stats = ["CS%", "IFErr", "IFFld%", "OFErr", "OFFld%"]
        for idx, stat in enumerate(d_stats):
            row = idx // 3
            col = idx % 3
            x = d_left + col * (d_table_w + d_gap_x)
            y = d_top - (row + 1) * d_table_h - row * d_gap_y
            draw_stat_table(
                c,
                defense,
                stat,
                x,
                y,
                d_table_w,
                d_table_h,
                logo_paths,
                theme="#A00012",
                ascending=defense_lower_is_better(stat),
            )
        draw_summary_box(
            c,
            "Escogido Defense Summary",
            make_escogido_defense_summary(defense),
            d_left + 2 * (d_table_w + d_gap_x),
            d_top - 2 * d_table_h - d_gap_y,
            d_table_w,
            d_table_h,
            logo_paths,
        )
    draw_footer(c, 5, logo_paths, "#A00012")
    c.save()
    output.seek(0)
    return output
# =====================================================
# UI
# =====================================================
st.title("⚾ LIDOM Team Leaderboard Report")
st.caption("✅ PDF DESIGN VERSION: 5-PAGE BEAUTIFUL REPORT — detailed Escogido summaries, one upload box, category tables, logos, rolling charts")
st.caption("Upload all CSVs together: six team Pregame files, LIDOM Draft pitching, 2022 Game Review catching, Infield Counting, and Outfield Counting.")

all_csv_files = st.file_uploader(
    "Upload all LIDOM CSV files here",
    type=["csv"],
    accept_multiple_files=True,
    help="You can select every CSV at once. The app will identify team, pitching, catcher, infield, and outfield files automatically by filename and columns.",
)

with st.sidebar.expander("🖼️ PDF Logos", expanded=False):
    st.caption("Optional: upload logos here, or keep files named aguilas.png, escogido.png, estrellas.png, gigantes.png, licey.png, toros.png, baserunning.png, and LIDOM.png in the same folder as the app.")
    logo_uploads = {
        "lidom": st.file_uploader("LIDOM logo", type=["png", "jpg", "jpeg"], key="logo_lidom"),
        "aguilas": st.file_uploader("Aguilas logo", type=["png", "jpg", "jpeg"], key="logo_aguilas"),
        "escogido": st.file_uploader("Escogido logo", type=["png", "jpg", "jpeg"], key="logo_escogido"),
        "estrellas": st.file_uploader("Estrellas logo", type=["png", "jpg", "jpeg"], key="logo_estrellas"),
        "gigantes": st.file_uploader("Gigantes logo", type=["png", "jpg", "jpeg"], key="logo_gigantes"),
        "licey": st.file_uploader("Licey logo", type=["png", "jpg", "jpeg"], key="logo_licey"),
        "toros": st.file_uploader("Toros logo", type=["png", "jpg", "jpeg"], key="logo_toros"),
        "baserunning": st.file_uploader("Baserunning icon", type=["png", "jpg", "jpeg"], key="logo_baserunning"),
    }

if not all_csv_files:
    st.info("Upload all LIDOM CSVs together to generate the report.")
    st.stop()

team_frames = []
pitching_source_df = None
catcher_df = None
infield_df = None
outfield_df = None
errors = []
loaded_names = {
    "team": [],
    "pitching": None,
    "catcher": None,
    "infield": None,
    "outfield": None,
    "ignored": [],
}


def _read_uploaded_csv(uploaded_file):
    """Read an uploaded CSV safely even if Streamlit has already touched the file pointer."""
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    return pd.read_csv(uploaded_file)


def _classify_csv_file(file_name: str, df: pd.DataFrame) -> str:
    """Classify uploaded CSV using filename first, then column signatures."""
    name = file_name.lower()
    cols = set(str(c).strip() for c in df.columns)

    if "lidom draft" in name or ("teamFullName" in cols and {"ERA", "FIP", "WHIP"}.issubset(cols)):
        return "pitching"
    if "game review" in name or "2022 game review" in name:
        return "catcher"
    if "infield counting" in name or {"IFErr", "INFld%"}.issubset(cols) or {"IFErr", "IFFld%"}.issubset(cols):
        return "infield"
    if "outfield counting" in name or {"OFErr", "OFFld%"}.issubset(cols):
        return "outfield"
    if set(["fullName", "pitchResult", "BaseStealAtt", "outs"]).issubset(cols):
        return "team"
    return "ignored"

for file in all_csv_files:
    try:
        df = _read_uploaded_csv(file)
        kind = _classify_csv_file(file.name, df)

        if kind == "team":
            missing = required_columns_ok(df)
            if missing:
                errors.append(f"{file.name}: missing {missing}")
            else:
                team_frames.append((file.name, df))
                loaded_names["team"].append(file.name)
        elif kind == "pitching":
            pitching_source_df = df
            loaded_names["pitching"] = file.name
        elif kind == "catcher":
            catcher_df = df
            loaded_names["catcher"] = file.name
        elif kind == "infield":
            infield_df = df
            loaded_names["infield"] = file.name
        elif kind == "outfield":
            outfield_df = df
            loaded_names["outfield"] = file.name
        else:
            loaded_names["ignored"].append(file.name)
    except Exception as e:
        errors.append(f"{file.name}: {e}")

with st.expander("📦 Loaded CSV status", expanded=True):
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Team files", len(loaded_names["team"]))
    c2.metric("Pitching", "Yes" if loaded_names["pitching"] else "No")
    c3.metric("Catching", "Yes" if loaded_names["catcher"] else "No")
    c4.metric("Infield", "Yes" if loaded_names["infield"] else "No")
    c5.metric("Outfield", "Yes" if loaded_names["outfield"] else "No")

    if loaded_names["team"]:
        st.success("Team files: " + ", ".join(loaded_names["team"]))
    if loaded_names["pitching"]:
        st.success(f"Pitching file: {loaded_names['pitching']}")
    if loaded_names["catcher"]:
        st.success(f"Catcher defense file: {loaded_names['catcher']}")
    if loaded_names["infield"]:
        st.success(f"Infield defense file: {loaded_names['infield']}")
    if loaded_names["outfield"]:
        st.success(f"Outfield defense file: {loaded_names['outfield']}")
    if loaded_names["ignored"]:
        st.warning("Ignored/unrecognized files: " + ", ".join(loaded_names["ignored"]))

if errors:
    st.error("Some files could not be processed:")
    for err in errors:
        st.write(f"- {err}")

if not team_frames:
    st.warning("No team Pregame CSVs were detected. Make sure those files include fullName, pitchResult, BaseStealAtt, and outs.")
    st.stop()

all_pa = []
all_br = []
for file_name, df in team_frames:
    try:
        all_pa.append(summarize_hitting(df))
        all_br.append(summarize_baserunning(df))
    except Exception as e:
        errors.append(f"{file_name}: {e}")

if errors:
    st.error("Some team files could not be summarized:")
    for err in errors:
        st.write(f"- {err}")

if not all_pa:
    st.stop()

pa_df = pd.concat(all_pa, ignore_index=True)
br_df = pd.concat(all_br, ignore_index=True) if all_br else pd.DataFrame(columns=["fullName", "game_date", "SB", "CS", "SBA"])

hitting = build_team_hitting(pa_df)
baserunning = build_team_baserunning(br_df)
rolling_hitting = build_rolling_hitting(pa_df)
rolling_baserunning = build_rolling_baserunning(br_df)

pitching = pd.DataFrame(columns=["fullName"] + PITCHING_STATS)
if pitching_source_df is not None:
    try:
        pitching = build_pitching_from_csv(pitching_source_df)
    except Exception as e:
        st.error(f"Could not process pitching CSV: {e}")

defense = pd.DataFrame(columns=["fullName"] + DEFENSE_STATS)
try:
    defense = build_defense_from_csvs(catcher_df, infield_df, outfield_df)
except Exception as e:
    st.error(f"Could not process defense CSVs: {e}")

# Sort final raw tables for easier reading.
hitting = hitting.sort_values("OPS", ascending=False).reset_index(drop=True)
baserunning = baserunning.sort_values("SB", ascending=False).reset_index(drop=True)

# =====================================================
# TABS
# =====================================================
tab1, tab2, tab3, tab4 = st.tabs(["🏆 Leaderboard Tables", "📈 Rolling Charts", "📋 Full Summary", "⬇️ Export"])

with tab1:
    st.subheader("Hitting Leaderboards")
    cols = st.columns(3)
    for i, stat in enumerate(HITTING_STATS):
        with cols[i % 3]:
            st.markdown(f"#### {stat}")
            ascending = stat == "K%"  # lower K% is better
            st.dataframe(style_table(leaderboard_table(hitting, stat, ascending=ascending)), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Baserunning Leaderboards")
    cols = st.columns(3)
    for i, stat in enumerate(BASERUNNING_STATS):
        with cols[i % 3]:
            st.markdown(f"#### {stat}")
            st.dataframe(style_table(leaderboard_table(baserunning, stat, ascending=False)), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Pitching Leaderboards")
    if pitching.empty:
        st.info("Upload the pitching CSV labeled LIDOM Draft to view pitching leaderboards.")
    else:
        cols = st.columns(3)
        for i, stat in enumerate(PITCHING_STATS):
            with cols[i % 3]:
                st.markdown(f"#### {stat}")
                st.dataframe(style_table(leaderboard_table(pitching, stat, ascending=pitching_lower_is_better(stat))), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Defense Leaderboards")
    if defense.empty:
        st.info("Upload 2022 Game Review, Infield Counting, and Outfield Counting to view defense leaderboards.")
    else:
        cols = st.columns(3)
        for i, stat in enumerate(DEFENSE_STATS):
            with cols[i % 3]:
                st.markdown(f"#### {STAT_LABELS.get(stat, (stat,))[0]}")
                st.dataframe(style_table(leaderboard_table(defense, stat, ascending=defense_lower_is_better(stat))), use_container_width=True, hide_index=True)

with tab2:
    chart_group = st.radio("Chart section", ["Hitting", "Baserunning"], horizontal=True)
    if chart_group == "Hitting":
        stat = st.selectbox("Select hitting category", HITTING_STATS, index=8)
        st.plotly_chart(make_chart(rolling_hitting, stat, f"Rolling {stat} by Team"), use_container_width=True)
    else:
        stat = st.selectbox("Select baserunning category", BASERUNNING_STATS, index=0)
        st.plotly_chart(make_chart(rolling_baserunning, stat, f"Rolling {stat} by Team"), use_container_width=True)

with tab3:
    st.subheader("Team Hitting Summary")
    display_hitting = hitting.copy()
    for stat in ["BA", "OBP", "SLG", "OPS", "BB%", "K%"]:
        display_hitting[stat] = display_hitting[stat].apply(lambda v: format_value(stat, v))
    cols_to_show = ["fullName", "PA", "AB", "Hits", "Single", "Double", "Triple", "Homerun", "BB", "HBP", "K", "BA", "OBP", "SLG", "OPS", "BB%", "K%"]
    st.dataframe(style_table(display_hitting[cols_to_show].rename(columns={"fullName": "Team"})), use_container_width=True, hide_index=True)

    st.subheader("Team Baserunning Summary")
    display_br = baserunning.copy()
    if not display_br.empty:
        display_br["SB%"] = display_br["SB%"].apply(lambda v: format_value("SB%", v))
    st.dataframe(style_table(display_br.rename(columns={"fullName": "Team"})), use_container_width=True, hide_index=True)

    st.subheader("Team Pitching Summary")
    if pitching.empty:
        st.info("Upload LIDOM Draft pitching CSV to view pitching summary.")
    else:
        display_pitching = pitching.copy()
        for stat in PITCHING_STATS:
            display_pitching[stat] = display_pitching[stat].apply(lambda v, s=stat: format_value(s, v))
        st.dataframe(style_table(display_pitching.rename(columns={"fullName": "Team"})), use_container_width=True, hide_index=True)

    st.subheader("Team Defense Summary")
    if defense.empty:
        st.info("Upload defense CSVs to view defense summary.")
    else:
        display_defense = defense.copy()
        for stat in DEFENSE_STATS:
            display_defense[stat] = display_defense[stat].apply(lambda v, s=stat: format_value(s, v))
        st.dataframe(style_table(display_defense.rename(columns={"fullName": "Team"})), use_container_width=True, hide_index=True)

with tab4:
    st.subheader("Export Report")

    col1, col2 = st.columns(2)

    with col1:
        st.download_button(
            "📊 Download Excel Report",
            data=to_excel(hitting, baserunning, rolling_hitting, rolling_baserunning, pitching, defense),
            file_name="lidom_team_leaderboard_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col2:
        if REPORTLAB_AVAILABLE:
            st.download_button(
                "📄 Download Beautiful PDF",
                data=to_pdf(hitting, baserunning, rolling_hitting, rolling_baserunning, pitching, defense, logo_uploads),
                file_name="lidom_team_leaderboard_report.pdf",
                mime="application/pdf",
            )
        else:
            st.warning("To export PDF, install ReportLab first: `pip install reportlab`")

    st.caption("Excel includes final leaderboards and rolling cumulative data. PDF includes page 1 hitting, page 2 baserunning, page 3 rolling charts, page 4 pitching, and page 5 defense leaderboards.")
