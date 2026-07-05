import streamlit as st

st.set_page_config(
    page_title="Baseball Operations Portal",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =====================================================
# BASEBALL OPERATIONS PORTAL - HOME PAGE
# Team-neutral Streamlit hub landing page
# =====================================================

st.markdown(
    """
    <style>
        :root {
            --navy: #0f172a;
            --navy-2: #1e293b;
            --blue: #2563eb;
            --red: #dc2626;
            --slate: #475569;
            --light: #f8fafc;
            --card: #ffffff;
            --border: #e2e8f0;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(37, 99, 235, 0.10), transparent 28%),
                radial-gradient(circle at bottom right, rgba(220, 38, 38, 0.08), transparent 25%),
                linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #111827 55%, #1e293b 100%);
            border-right: 1px solid rgba(255,255,255,0.08);
        }

        section[data-testid="stSidebar"] * {
            color: #f8fafc !important;
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] ul {
            padding-top: 1rem;
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li div a {
            border-radius: 12px;
            margin: 4px 8px;
            padding: 10px 12px;
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li div a:hover {
            background: rgba(255,255,255,0.10);
        }

        .main .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1320px;
        }

        .portal-hero {
            position: relative;
            overflow: hidden;
            padding: 44px 48px;
            border-radius: 28px;
            background:
                linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 64, 175, 0.86)),
                repeating-linear-gradient(45deg, rgba(255,255,255,.04) 0px, rgba(255,255,255,.04) 2px, transparent 2px, transparent 10px);
            color: white;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.20);
            margin-bottom: 26px;
            border: 1px solid rgba(255,255,255,0.14);
        }

        .portal-kicker {
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: #bfdbfe;
            margin-bottom: 10px;
        }

        .portal-title {
            font-size: 58px;
            line-height: 1.02;
            font-weight: 900;
            color: white;
            margin: 0 0 14px 0;
        }

        .portal-subtitle {
            font-size: 20px;
            line-height: 1.45;
            color: #e5e7eb;
            max-width: 850px;
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
            font-size: 14px;
            font-weight: 700;
        }

        .section-title {
            color: #0f172a;
            font-size: 26px;
            font-weight: 900;
            margin: 10px 0 6px 0;
        }

        .section-subtitle {
            color: #64748b;
            font-size: 15px;
            margin-bottom: 14px;
        }

        .app-card {
            background: rgba(255,255,255,0.94);
            border: 1px solid var(--border);
            border-radius: 22px;
            padding: 24px 22px 20px 22px;
            min-height: 252px;
            box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
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

        .app-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 18px 38px rgba(15, 23, 42, 0.14);
        }

        .app-icon {
            width: 58px;
            height: 58px;
            border-radius: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 30px;
            background: color-mix(in srgb, var(--accent, #2563eb) 15%, white);
            border: 1px solid color-mix(in srgb, var(--accent, #2563eb) 25%, white);
            margin-bottom: 16px;
        }

        .app-name {
            color: #0f172a;
            font-size: 20px;
            font-weight: 900;
            margin-bottom: 8px;
        }

        .app-desc {
            color: #475569;
            font-size: 14.5px;
            line-height: 1.45;
            min-height: 62px;
            margin-bottom: 14px;
        }

        .tag-row {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 10px;
        }

        .tag {
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            color: #334155;
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            padding: 5px 8px;
            border-radius: 999px;
        }

        .quick-panel {
            background: rgba(255,255,255,0.88);
            border: 1px solid #e2e8f0;
            border-radius: 20px;
            padding: 20px 22px;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
            height: 100%;
        }

        .metric-label {
            color: #64748b;
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .metric-value {
            color: #0f172a;
            font-size: 30px;
            font-weight: 900;
            line-height: 1.1;
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

        div[data-testid="stLinkButton"] a,
        div[data-testid="stPageLink"] a {
            border-radius: 12px !important;
            border: 1px solid #dbeafe !important;
            font-weight: 800 !important;
            background: white !important;
        }

        @media (max-width: 900px) {
            .portal-title { font-size: 40px; }
            .portal-hero { padding: 30px 28px; }
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
        <div style="padding: 16px 8px 8px 8px;">
            <div style="font-size: 42px; line-height: 1;">⚾</div>
            <div style="font-size: 19px; font-weight: 900; margin-top: 8px;">Baseball Ops Portal</div>
            <div style="font-size: 12px; color: #cbd5e1 !important; margin-top: 4px;">Reports • Projections • Player Tools</div>
            <div style="height: 2px; width: 72px; background: #ef4444; margin-top: 14px; border-radius: 999px;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------
# Hero section
# -----------------------------
st.markdown(
    """
    <div class="portal-hero">
        <div class="portal-kicker">Baseball Operations Portal</div>
        <div class="portal-title">Smarter baseball decisions, all in one place.</div>
        <div class="portal-subtitle">
            A clean hub for projections, lineup optimization, matchup reports, pitch analysis,
            team leaderboards, and pregame preparation tools.
        </div>
        <div class="pill-row">
            <div class="pill">📊 Reports</div>
            <div class="pill">📈 Projections</div>
            <div class="pill">⚾ Player Analysis</div>
            <div class="pill">🧠 Game Planning</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Quick overview
# -----------------------------
stat_cols = st.columns(4)
quick_stats = [
    ("Apps Available", "7"),
    ("Main Focus", "Game Prep"),
    ("Users", "Staff"),
    ("Workflow", "Upload → Analyze → Export"),
]

for col, (label, value) in zip(stat_cols, quick_stats):
    with col:
        st.markdown(
            f"""
            <div class="quick-panel">
                <div class="metric-label">{label}</div>
                <div class="metric-value">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.write("")
st.markdown('<div class="section-title">Available Tools</div>', unsafe_allow_html=True)
st.markdown('<div class="section-subtitle">Choose an app below or use the sidebar navigation.</div>', unsafe_allow_html=True)

apps = [
    {
        "title": "LIDOM Projection",
        "desc": "Project team performance and league standings with a clean, decision-ready workflow.",
        "icon": "📈",
        "accent": "#2563eb",
        "page": "pages/1_LIDOM_Projection.py",
        "tags": ["Projection", "Teams"],
    },
    {
        "title": "Lineup Optimization",
        "desc": "Build optimized lineups using offensive metrics, roster constraints, and game context.",
        "icon": "🧢",
        "accent": "#dc2626",
        "page": "pages/2_Lineup_Optimization.py",
        "tags": ["Lineups", "Offense"],
    },
    {
        "title": "Pitch Characteristics",
        "desc": "Analyze pitch traits, movement profiles, velocity, and similarity across pitchers.",
        "icon": "⚾",
        "accent": "#16a34a",
        "page": "pages/3_Pitch_Characteristics.py",
        "tags": ["Pitching", "Similarity"],
    },
    {
        "title": "Leaderboard Report",
        "desc": "Generate player leaderboards across hitting, baserunning, defense, and pitching.",
        "icon": "🏆",
        "accent": "#7c3aed",
        "page": "pages/4_Leaderboard_Report.py",
        "tags": ["Reports", "Leaders"],
    },
    {
        "title": "Hitter vs Pitcher Matchup",
        "desc": "Evaluate hitter performance and matchup history against specific pitchers.",
        "icon": "⚔️",
        "accent": "#f97316",
        "page": "pages/5_Hitter_vs_Pitcher_Matchup.py",
        "tags": ["Matchups", "Game Plan"],
    },
    {
        "title": "Team Leaderboard",
        "desc": "Compare team rankings and advanced metrics across categories and report pages.",
        "icon": "📊",
        "accent": "#0891b2",
        "page": "pages/6_LIDOM_Team_Leaderboard.py",
        "tags": ["Teams", "League"],
    },
    {
        "title": "Pregame Visual Report",
        "desc": "Create visual pregame reports for opponent preparation and staff meetings.",
        "icon": "📋",
        "accent": "#0ea5e9",
        "page": "pages/7_Pregame_Visual_Report.py",
        "tags": ["Pregame", "Visuals"],
    },
]

# Render cards in rows of three
for row_start in range(0, len(apps), 3):
    cols = st.columns(3)
    for col, app in zip(cols, apps[row_start:row_start + 3]):
        tags_html = "".join([f'<span class="tag">{tag}</span>' for tag in app["tags"]])
        with col:
            st.markdown(
                f"""
                <div class="app-card" style="--accent: {app['accent']};">
                    <div class="app-icon">{app['icon']}</div>
                    <div class="app-name">{app['title']}</div>
                    <div class="app-desc">{app['desc']}</div>
                    <div class="tag-row">{tags_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            try:
                st.page_link(app["page"], label=f"Launch {app['title']}", icon="➡️")
            except Exception:
                st.info("This app page is not available yet.")
            st.write("")

st.markdown('<div class="footer-line"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="portal-footer">Baseball Operations Portal • Built for scouting, player development, game planning, and reporting workflows</div>',
    unsafe_allow_html=True,
)
