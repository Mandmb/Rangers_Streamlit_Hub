import re
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Baseball Operations Portal",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =====================================================
# BASEBALL OPERATIONS PORTAL - HOME PAGE v2
# Team-neutral Streamlit hub landing page
# Fixes page-link paths by auto-detecting actual files in /pages
# =====================================================

ROOT = Path(__file__).parent
PAGES_DIR = ROOT / "pages"


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def discover_pages() -> dict:
    """Return normalized filename/display-name keys mapped to Streamlit page paths."""
    page_map = {}
    if not PAGES_DIR.exists():
        return page_map

    for page_file in sorted(PAGES_DIR.glob("*.py")):
        rel_path = f"pages/{page_file.name}"
        stem = page_file.stem
        cleaned = re.sub(r"^\d+[_\-\s]*", "", stem)
        cleaned = cleaned.replace("_", " ").replace("-", " ")

        keys = {
            normalize_text(stem),
            normalize_text(cleaned),
            normalize_text(page_file.name),
        }
        for key in keys:
            page_map[key] = rel_path
    return page_map


PAGE_MAP = discover_pages()


def find_page(*candidates: str) -> str | None:
    """Find the best matching page from /pages using flexible candidate names."""
    normalized_pages = list(PAGE_MAP.items())

    for candidate in candidates:
        key = normalize_text(candidate)
        if key in PAGE_MAP:
            return PAGE_MAP[key]

    for candidate in candidates:
        key = normalize_text(candidate)
        for page_key, rel_path in normalized_pages:
            if key and (key in page_key or page_key in key):
                return rel_path

    return None


APP_SPECS = [
    {
        "title": "LIDOM Projection",
        "desc": "Project standings, team performance, and league outcomes with a clean upload-to-report workflow.",
        "icon": "📈",
        "accent": "#2563eb",
        "category": "Projection",
        "tags": ["Teams", "Standings", "League"],
        "match": ["LIDOM Projection", "lidom projection", "projection"],
    },
    {
        "title": "Lineup Optimization",
        "desc": "Build optimized lineups using offensive metrics, positions, roster rules, and game context.",
        "icon": "🧢",
        "accent": "#dc2626",
        "category": "Game Planning",
        "tags": ["Lineups", "Offense", "Optimization"],
        "match": ["Lineup Optimization", "lineup optimizer", "lineup"],
    },
    {
        "title": "Pitch Characteristics",
        "desc": "Analyze movement, velocity, pitch traits, similarity scores, and pitcher profile reports.",
        "icon": "⚾",
        "accent": "#16a34a",
        "category": "Player Analysis",
        "tags": ["Pitching", "Similarity", "Profiles"],
        "match": ["Pitch Characteristics", "pitch characteristics", "pitch similarity"],
    },
    {
        "title": "Leaderboard Report",
        "desc": "Generate polished leaderboards across hitting, baserunning, defense, and pitching categories.",
        "icon": "🏆",
        "accent": "#7c3aed",
        "category": "Reports",
        "tags": ["Leaders", "PDF", "Players"],
        "match": ["Leaderboard Report", "leaderboard", "4 leaderboard report"],
    },
    {
        "title": "Hitter vs Pitcher Matchup",
        "desc": "Explore hitter performance, pitcher history, and matchup advantages for game preparation.",
        "icon": "⚔️",
        "accent": "#f97316",
        "category": "Game Planning",
        "tags": ["Matchups", "Hitters", "Pitchers"],
        "match": ["Hitter vs Pitcher Matchup", "hitter pitcher matchup", "matchup"],
    },
    {
        "title": "Team Leaderboard",
        "desc": "Compare team rankings and advanced metrics across hitting, pitching, defense, and baserunning.",
        "icon": "📊",
        "accent": "#0891b2",
        "category": "Reports",
        "tags": ["Teams", "League", "Rankings"],
        "match": ["LIDOM Team Leaderboard", "Team Leaderboard", "team leaderboard"],
    },
    {
        "title": "Pregame Visual Report",
        "desc": "Create visual pregame reports for opponent preparation, coach meetings, and game strategy.",
        "icon": "📋",
        "accent": "#0ea5e9",
        "category": "Reports",
        "tags": ["Pregame", "Visuals", "Opponent"],
        "match": ["Pregame Visual Report", "pregame visual", "pregame report"],
    },
]

for app in APP_SPECS:
    app["page"] = find_page(*app["match"])

available_apps = [app for app in APP_SPECS if app["page"]]

# -----------------------------
# CSS
# -----------------------------
st.markdown(
    """
    <style>
        :root {
            --navy: #0b1220;
            --navy-2: #111827;
            --slate: #475569;
            --muted: #64748b;
            --light: #f8fafc;
            --card: #ffffff;
            --border: #e2e8f0;
        }

        .stApp {
            background:
                radial-gradient(circle at 12% 8%, rgba(37, 99, 235, 0.12), transparent 24%),
                radial-gradient(circle at 88% 14%, rgba(14, 165, 233, 0.10), transparent 22%),
                linear-gradient(135deg, #f8fafc 0%, #edf2f7 100%);
        }

        .main .block-container {
            padding-top: 1.65rem;
            padding-bottom: 3rem;
            max-width: 1380px;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #08111f 0%, #0f172a 55%, #172033 100%);
            border-right: 1px solid rgba(255,255,255,0.08);
        }

        section[data-testid="stSidebar"] * {
            color: #f8fafc !important;
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li div a {
            border-radius: 13px;
            margin: 3px 8px;
            padding: 10px 12px;
            transition: all .15s ease;
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li div a:hover {
            background: rgba(255,255,255,0.10);
            transform: translateX(2px);
        }

        .sidebar-brand {
            padding: 18px 8px 12px 8px;
        }

        .sidebar-logo {
            width: 54px;
            height: 54px;
            border-radius: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 30px;
            background: rgba(255,255,255,0.10);
            border: 1px solid rgba(255,255,255,0.16);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.16);
        }

        .sidebar-title {
            font-size: 18px;
            font-weight: 950;
            margin-top: 12px;
            letter-spacing: -0.02em;
        }

        .sidebar-caption {
            color: #cbd5e1 !important;
            font-size: 12px;
            line-height: 1.35;
            margin-top: 4px;
        }

        .sidebar-rule {
            height: 2px;
            width: 86px;
            background: linear-gradient(90deg, #60a5fa, #ef4444);
            margin-top: 14px;
            border-radius: 999px;
        }

        .hero-grid {
            display: grid;
            grid-template-columns: 1.6fr .85fr;
            gap: 18px;
            margin-bottom: 20px;
        }

        .portal-hero {
            position: relative;
            overflow: hidden;
            padding: 42px 46px;
            border-radius: 30px;
            background:
                linear-gradient(135deg, rgba(8, 17, 31, 0.97), rgba(30, 64, 175, 0.88)),
                repeating-linear-gradient(45deg, rgba(255,255,255,.035) 0px, rgba(255,255,255,.035) 2px, transparent 2px, transparent 11px);
            color: white;
            box-shadow: 0 20px 50px rgba(15, 23, 42, 0.22);
            border: 1px solid rgba(255,255,255,0.14);
            min-height: 294px;
        }

        .portal-hero:after {
            content: "";
            position: absolute;
            right: -105px;
            bottom: -110px;
            width: 310px;
            height: 310px;
            border-radius: 999px;
            border: 46px solid rgba(255,255,255,0.065);
        }

        .portal-kicker {
            font-size: 12px;
            font-weight: 900;
            letter-spacing: 0.17em;
            text-transform: uppercase;
            color: #bfdbfe;
            margin-bottom: 11px;
        }

        .portal-title {
            font-size: 54px;
            line-height: 1.02;
            font-weight: 950;
            color: white;
            margin: 0 0 14px 0;
            letter-spacing: -0.045em;
            max-width: 870px;
        }

        .portal-subtitle {
            font-size: 18px;
            line-height: 1.5;
            color: #e5e7eb;
            max-width: 820px;
            margin-bottom: 22px;
        }

        .pill-row {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 9px 14px;
            border-radius: 999px;
            background: rgba(255,255,255,0.11);
            border: 1px solid rgba(255,255,255,0.16);
            color: white;
            font-size: 13px;
            font-weight: 800;
        }

        .snapshot-panel {
            border-radius: 30px;
            background: rgba(255,255,255,0.88);
            border: 1px solid #e2e8f0;
            padding: 24px 24px;
            box-shadow: 0 14px 36px rgba(15,23,42,0.10);
            height: 100%;
        }

        .snapshot-title {
            color: #0f172a;
            font-size: 17px;
            font-weight: 950;
            margin-bottom: 14px;
        }

        .snapshot-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 12px 0;
            border-bottom: 1px solid #e2e8f0;
        }

        .snapshot-item:last-child { border-bottom: 0; }

        .snapshot-label {
            color: #64748b;
            font-size: 13px;
            font-weight: 800;
        }

        .snapshot-value {
            color: #0f172a;
            font-size: 18px;
            font-weight: 950;
        }

        .section-head {
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 18px;
            margin: 20px 0 12px 0;
        }

        .section-title {
            color: #0f172a;
            font-size: 27px;
            font-weight: 950;
            margin: 0 0 3px 0;
            letter-spacing: -0.025em;
        }

        .section-subtitle {
            color: #64748b;
            font-size: 14.5px;
        }

        .app-card {
            background: rgba(255,255,255,0.96);
            border: 1px solid var(--border);
            border-radius: 24px;
            padding: 24px 22px 18px 22px;
            min-height: 268px;
            box-shadow: 0 10px 28px rgba(15, 23, 42, 0.075);
            transition: all .18s ease-in-out;
            position: relative;
            overflow: hidden;
        }

        .app-card:before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 5px;
            background: var(--accent, #2563eb);
        }

        .app-card:after {
            content: "";
            position: absolute;
            right: -44px;
            top: -44px;
            width: 118px;
            height: 118px;
            border-radius: 999px;
            background: color-mix(in srgb, var(--accent, #2563eb) 13%, transparent);
        }

        .app-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 18px 42px rgba(15, 23, 42, 0.14);
        }

        .app-icon {
            width: 60px;
            height: 60px;
            border-radius: 19px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 31px;
            background: color-mix(in srgb, var(--accent, #2563eb) 13%, white);
            border: 1px solid color-mix(in srgb, var(--accent, #2563eb) 24%, white);
            margin-bottom: 16px;
        }

        .app-name {
            color: #0f172a;
            font-size: 20px;
            font-weight: 950;
            margin-bottom: 8px;
            letter-spacing: -0.02em;
        }

        .app-desc {
            color: #475569;
            font-size: 14.4px;
            line-height: 1.48;
            min-height: 68px;
            margin-bottom: 13px;
        }

        .tag-row {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 10px;
        }

        .tag {
            font-size: 10.5px;
            font-weight: 900;
            text-transform: uppercase;
            color: #334155;
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            padding: 5px 8px;
            border-radius: 999px;
        }

        .category-label {
            color: var(--accent, #2563eb);
            font-size: 11px;
            font-weight: 950;
            text-transform: uppercase;
            letter-spacing: .10em;
            margin-bottom: 9px;
        }

        .footer-line {
            height: 1px;
            background: linear-gradient(90deg, transparent, #cbd5e1, transparent);
            margin: 34px 0 14px 0;
        }

        .portal-footer {
            color: #64748b;
            font-size: 13px;
            text-align: center;
        }

        div[data-testid="stPageLink"] a {
            border-radius: 13px !important;
            border: 1px solid #dbeafe !important;
            font-weight: 900 !important;
            background: white !important;
            transition: all .15s ease !important;
        }

        div[data-testid="stPageLink"] a:hover {
            transform: translateY(-1px);
            border-color: #93c5fd !important;
        }

        @media (max-width: 1000px) {
            .hero-grid { grid-template-columns: 1fr; }
            .portal-title { font-size: 40px; }
            .portal-hero { padding: 30px 28px; min-height: auto; }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Sidebar branding
# -----------------------------
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-logo">⚾</div>
            <div class="sidebar-title">Baseball Ops Portal</div>
            <div class="sidebar-caption">Reports • Projections • Player Tools</div>
            <div class="sidebar-rule"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------
# Hero + snapshot
# -----------------------------
st.markdown(
    f"""
    <div class="hero-grid">
        <div class="portal-hero">
            <div class="portal-kicker">Baseball Operations Portal</div>
            <div class="portal-title">Smarter baseball decisions, all in one place.</div>
            <div class="portal-subtitle">
                A team-neutral hub for projections, lineup optimization, matchup reports, pitch analysis,
                leaderboards, and pregame preparation tools.
            </div>
            <div class="pill-row">
                <div class="pill">📊 Reports</div>
                <div class="pill">📈 Projections</div>
                <div class="pill">⚾ Player Analysis</div>
                <div class="pill">🧠 Game Planning</div>
            </div>
        </div>
        <div class="snapshot-panel">
            <div class="snapshot-title">Portal Snapshot</div>
            <div class="snapshot-item"><div class="snapshot-label">Available Apps</div><div class="snapshot-value">{len(available_apps)}</div></div>
            <div class="snapshot-item"><div class="snapshot-label">Workflow</div><div class="snapshot-value">Upload → Analyze → Export</div></div>
            <div class="snapshot-item"><div class="snapshot-label">Primary Users</div><div class="snapshot-value">Staff</div></div>
            <div class="snapshot-item"><div class="snapshot-label">Focus</div><div class="snapshot-value">Game Prep</div></div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Search + app cards
# -----------------------------
left, right = st.columns([2.2, 1])
with left:
    st.markdown(
        """
        <div class="section-head">
            <div>
                <div class="section-title">Available Tools</div>
                <div class="section-subtitle">Choose an app below or use the sidebar navigation.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with right:
    search_term = st.text_input("Search tools", placeholder="Search reports, lineups, pitching...", label_visibility="collapsed")

query = normalize_text(search_term or "")
filtered_apps = []
for app in APP_SPECS:
    searchable = normalize_text(" ".join([app["title"], app["desc"], app["category"], " ".join(app["tags"])]))
    if not query or query in searchable:
        filtered_apps.append(app)

if not filtered_apps:
    st.info("No tools match that search.")

for row_start in range(0, len(filtered_apps), 3):
    cols = st.columns(3)
    for col, app in zip(cols, filtered_apps[row_start:row_start + 3]):
        tags_html = "".join([f'<span class="tag">{tag}</span>' for tag in app["tags"]])
        with col:
            st.markdown(
                f"""
                <div class="app-card" style="--accent: {app['accent']};">
                    <div class="category-label" style="--accent: {app['accent']};">{app['category']}</div>
                    <div class="app-icon">{app['icon']}</div>
                    <div class="app-name">{app['title']}</div>
                    <div class="app-desc">{app['desc']}</div>
                    <div class="tag-row">{tags_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if app["page"]:
                st.page_link(app["page"], label=f"Launch {app['title']}", icon="➡️")
            else:
                st.caption("Page file not found in the pages folder.")
            st.write("")

# Optional developer check tucked away
with st.expander("Developer check: detected page files", expanded=False):
    if PAGE_MAP:
        detected = sorted(set(PAGE_MAP.values()))
        st.write("Detected pages:")
        for page in detected:
            st.code(page, language="text")
    else:
        st.warning("No .py files were detected inside the pages folder.")

st.markdown('<div class="footer-line"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="portal-footer">Baseball Operations Portal • Built for scouting, player development, game planning, and reporting workflows</div>',
    unsafe_allow_html=True,
)
