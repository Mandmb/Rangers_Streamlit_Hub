import streamlit as st
from pathlib import Path
from datetime import datetime

st.set_page_config(
    page_title="Baseball Operations Portal",
    page_icon="⚾",
    layout="wide",
)

try:
    from ui_styles import apply_page_style, theme_picker
    theme = theme_picker()
    apply_page_style(theme)
except Exception:
    theme = None

PAGES_DIR = Path("pages")

APP_LIBRARY = [
    {
        "title": "Pitch Characteristics",
        "category": "Analytics & Evaluation",
        "icon": "⚾",
        "desc": "Compare pitch traits, movement, velocity, similarity scores, and player profiles.",
        "keywords": "pitch characteristics similarity pitcher movement velocity",
        "priority": True,
    },
    {
        "title": "LIDOM Projection",
        "category": "Analytics & Evaluation",
        "icon": "📈",
        "desc": "Project league performance and translate hitter profiles across winter ball environments.",
        "keywords": "lidom projection winter league hitter grader",
        "priority": True,
    },
    {
        "title": "LIDOM Team Leaderboard",
        "category": "Analytics & Evaluation",
        "icon": "📊",
        "desc": "Compare team rankings, strengths, weaknesses, and advanced league-level metrics.",
        "keywords": "team leaderboard lidom rankings advanced metrics",
        "priority": False,
    },
    {
        "title": "Pregame Visual Report",
        "category": "Reports",
        "icon": "📋",
        "desc": "Create opponent reports, visuals, summaries, and game-planning material.",
        "keywords": "pregame report visual opponent scouting",
        "priority": True,
    },
    {
        "title": "Leaderboard Report",
        "category": "Reports",
        "icon": "🏆",
        "desc": "Generate clean player leaderboards across hitting, pitching, defense, and baserunning.",
        "keywords": "leaderboard report hitting pitching defense baserunning",
        "priority": True,
    },
    {
        "title": "Lineup Optimization",
        "category": "Game Planning",
        "icon": "🧢",
        "desc": "Build lineup combinations based on offensive value, role, handedness, and team constraints.",
        "keywords": "lineup optimization batting order",
        "priority": True,
    },
    {
        "title": "Hitter vs Pitcher Matchup",
        "category": "Game Planning",
        "icon": "⚔️",
        "desc": "Evaluate historical matchup performance between hitters and pitchers.",
        "keywords": "hitter pitcher matchup batter pitcher",
        "priority": False,
    },
]

UPDATES = [
    "Professional portal homepage added",
    "Shared page styling and contrast fixes applied",
    "Team-neutral theme system added",
    "Improved report navigation from homepage",
]


def available_pages():
    if not PAGES_DIR.exists():
        return {}
    files = list(PAGES_DIR.glob("*.py"))
    mapping = {}

    manual_aliases = {
        "Pregame Visual Report": ["pregame", "visual"],
        "LIDOM Team Leaderboard": ["team", "leaderboard"],
        "Hitter vs Pitcher Matchup": ["hitter", "pitcher", "matchup"],
        "Leaderboard Report": ["leaderboard", "report"],
        "Pitch Characteristics": ["pitch", "characteristics"],
        "Lineup Optimization": ["lineup", "optimization"],
        "LIDOM Projection": ["lidom", "projection"],
    }

    for app in APP_LIBRARY:
        aliases = manual_aliases.get(app["title"], app["title"].lower().split())
        best_file = None
        best_score = 0
        for file in files:
            normalized = file.stem.lower().replace("_", " ").replace("-", " ")
            score = sum(1 for word in aliases if word in normalized)
            if score > best_score:
                best_score = score
                best_file = file
        if best_file and best_score >= max(1, len(aliases) // 2):
            mapping[app["title"]] = str(best_file)

    return mapping


page_map = available_pages()
available = len(page_map)
total_apps = len(APP_LIBRARY)
categories = sorted(set(app["category"] for app in APP_LIBRARY))
today = datetime.now().strftime("%b %d, %Y")

st.markdown("""
<style>
    .command-hero {
        position: relative;
        padding: 48px 50px;
        border-radius: 34px;
        background:
            linear-gradient(135deg, rgba(8,15,29,.97), rgba(30,64,175,.88)),
            radial-gradient(circle at 88% 18%, rgba(249,115,22,.42), transparent 28%),
            radial-gradient(circle at 18% 85%, rgba(59,130,246,.28), transparent 32%);
        color: white;
        box-shadow: 0 24px 55px rgba(15,23,42,.28);
        overflow: hidden;
        margin-bottom: 26px;
    }

    .command-hero:before {
        content: "";
        position: absolute;
        inset: 0;
        background-image:
            linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
        background-size: 42px 42px;
        opacity: .25;
    }

    .command-hero:after {
        content: "⚾";
        position: absolute;
        right: 44px;
        top: 28px;
        font-size: 8rem;
        opacity: .12;
        transform: rotate(-14deg);
    }

    .hero-content {
        position: relative;
        z-index: 2;
        max-width: 850px;
    }

    .hero-kicker {
        display: inline-flex;
        align-items: center;
        gap: 9px;
        padding: 7px 12px;
        border-radius: 999px;
        background: rgba(255,255,255,.12);
        border: 1px solid rgba(255,255,255,.16);
        color: #bfdbfe;
        font-size: .78rem;
        font-weight: 950;
        letter-spacing: .12em;
        text-transform: uppercase;
        margin-bottom: 16px;
    }

    .command-hero h1 {
        color: white !important;
        font-size: 3.75rem !important;
        line-height: .98;
        margin: 0 0 14px 0;
        letter-spacing: -2px;
        font-weight: 950 !important;
    }

    .command-hero p {
        color: #e0f2fe;
        font-size: 1.18rem;
        line-height: 1.55;
        margin: 0;
    }

    .hero-stats {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 13px;
        margin-top: 28px;
        max-width: 900px;
    }

    .hero-stat {
        background: rgba(255,255,255,.13);
        border: 1px solid rgba(255,255,255,.16);
        border-radius: 18px;
        padding: 15px 16px;
        backdrop-filter: blur(8px);
    }

    .hero-stat-label {
        color: #cbd5e1;
        font-size: .72rem;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: .08em;
    }

    .hero-stat-value {
        color: white;
        font-size: 1.45rem;
        font-weight: 950;
        margin-top: 3px;
    }

    .section-row {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 18px;
        margin: 26px 0 14px 0;
    }

    .section-title {
        color: #0f172a;
        font-size: 1.5rem;
        font-weight: 950;
        margin: 0;
        letter-spacing: -.4px;
    }

    .section-subtitle {
        color: #64748b;
        margin-top: 4px;
        font-size: .97rem;
    }

    .pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 8px 12px;
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 999px;
        color: #334155;
        font-weight: 800;
        box-shadow: 0 6px 18px rgba(15,23,42,.06);
        font-size: .86rem;
    }

    .quick-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 16px;
        margin-bottom: 12px;
    }

    .quick-card {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 22px;
        padding: 20px;
        min-height: 172px;
        box-shadow: 0 10px 26px rgba(15,23,42,.08);
        border-top: 4px solid #2563eb;
    }

    .quick-icon {
        width: 50px;
        height: 50px;
        border-radius: 16px;
        background: linear-gradient(135deg, #eff6ff, #dbeafe);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.75rem;
        margin-bottom: 12px;
    }

    .quick-title {
        color: #0f172a;
        font-weight: 950;
        font-size: 1rem;
        margin-bottom: 6px;
    }

    .quick-desc {
        color: #64748b;
        font-size: .9rem;
        line-height: 1.4;
    }

    .category-card {
        background: rgba(255,255,255,.94);
        border: 1px solid #e5e7eb;
        border-radius: 26px;
        padding: 22px;
        box-shadow: 0 10px 28px rgba(15,23,42,.08);
        margin-bottom: 22px;
    }

    .category-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding-bottom: 14px;
        margin-bottom: 16px;
        border-bottom: 1px solid #e5e7eb;
    }

    .category-title {
        color: #0f172a;
        font-size: 1.16rem;
        font-weight: 950;
    }

    .category-count {
        color: #64748b;
        font-size: .84rem;
        font-weight: 850;
    }

    .app-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 22px;
        padding: 21px;
        min-height: 232px;
        box-shadow: 0 8px 22px rgba(15,23,42,.07);
        transition: all .16s ease;
        position: relative;
        overflow: hidden;
    }

    .app-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 16px 36px rgba(15,23,42,.13);
    }

    .app-card:after {
        content: "";
        position: absolute;
        width: 120px;
        height: 120px;
        border-radius: 999px;
        right: -55px;
        top: -55px;
        background: rgba(37,99,235,.08);
    }

    .app-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 14px;
    }

    .app-icon {
        width: 54px;
        height: 54px;
        border-radius: 17px;
        background: linear-gradient(135deg, #eff6ff, #dbeafe);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.8rem;
    }

    .app-tag {
        background: #f1f5f9;
        color: #475569;
        border-radius: 999px;
        padding: 5px 9px;
        font-size: .72rem;
        font-weight: 900;
        text-transform: uppercase;
    }

    .app-title {
        color: #0f172a;
        font-size: 1.15rem;
        font-weight: 950;
        margin-bottom: 8px;
    }

    .app-desc {
        color: #475569;
        font-size: .93rem;
        line-height: 1.45;
        min-height: 66px;
    }

    .lower-grid {
        display: grid;
        grid-template-columns: 1.25fr .75fr;
        gap: 22px;
        margin-top: 8px;
    }

    .panel {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 26px;
        padding: 24px;
        box-shadow: 0 10px 28px rgba(15,23,42,.08);
    }

    .workflow-step {
        display: grid;
        grid-template-columns: 36px 1fr;
        gap: 12px;
        align-items: start;
        margin-bottom: 14px;
    }

    .step-num {
        width: 36px;
        height: 36px;
        border-radius: 12px;
        background: #eff6ff;
        color: #1d4ed8;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 950;
    }

    .step-text {
        color: #334155;
        font-weight: 750;
        padding-top: 6px;
    }

    .update-item {
        padding: 12px 0;
        border-bottom: 1px solid #e5e7eb;
        color: #334155;
        font-weight: 750;
    }

    .update-item:last-child {
        border-bottom: none;
    }

    .footer-line {
        text-align: center;
        color: #64748b;
        margin-top: 34px;
        padding-top: 18px;
        border-top: 1px solid #e5e7eb;
        font-size: .92rem;
    }

    @media (max-width: 1150px) {
        .quick-grid { grid-template-columns: repeat(2, 1fr); }
        .hero-stats { grid-template-columns: repeat(2, 1fr); }
        .lower-grid { grid-template-columns: 1fr; }
    }

    @media (max-width: 760px) {
        .quick-grid { grid-template-columns: 1fr; }
        .hero-stats { grid-template-columns: 1fr; }
        .command-hero h1 { font-size: 2.55rem !important; }
        .command-hero { padding: 34px 28px; }
    }
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="command-hero">
    <div class="hero-content">
        <div class="hero-kicker">⚾ Baseball Operations Command Center</div>
        <h1>Analytics. Reports. Game Planning.</h1>
        <p>One team-neutral platform for player development, scouting, league evaluation, and pregame decision-making.</p>
        <div class="hero-stats">
            <div class="hero-stat">
                <div class="hero-stat-label">Applications</div>
                <div class="hero-stat-value">{available}/{total_apps}</div>
            </div>
            <div class="hero-stat">
                <div class="hero-stat-label">Workflows</div>
                <div class="hero-stat-value">{len(categories)}</div>
            </div>
            <div class="hero-stat">
                <div class="hero-stat-label">Platform Type</div>
                <div class="hero-stat-value">Portal</div>
            </div>
            <div class="hero-stat">
                <div class="hero-stat-label">Updated</div>
                <div class="hero-stat-value">{today}</div>
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

priority_apps = [app for app in APP_LIBRARY if app["priority"]][:4]

st.markdown("""
<div class="section-row">
    <div>
        <div class="section-title">Quick Actions</div>
        <div class="section-subtitle">Start with the most common baseball operations tasks.</div>
    </div>
    <div class="pill">⚡ Fast Launch</div>
</div>
""", unsafe_allow_html=True)

cols = st.columns(4)
for col, app in zip(cols, priority_apps):
    page = page_map.get(app["title"])
    with col:
        st.markdown(f"""
        <div class="quick-card">
            <div class="quick-icon">{app["icon"]}</div>
            <div class="quick-title">{app["title"]}</div>
            <div class="quick-desc">{app["desc"]}</div>
        </div>
        """, unsafe_allow_html=True)
        if page:
            st.page_link(page, label="Open Tool", icon="➡️")
        else:
            st.caption("Page file not detected.")
        st.write("")

st.markdown("""
<div class="section-row">
    <div>
        <div class="section-title">App Library</div>
        <div class="section-subtitle">Browse tools by workflow category.</div>
    </div>
    <div class="pill">🧭 Sidebar navigation also available</div>
</div>
""", unsafe_allow_html=True)

search = st.text_input(
    "Search apps",
    placeholder="Search reports, projections, matchups, pitching, leaderboard...",
    label_visibility="collapsed",
)

for category in categories:
    category_apps = []
    for app in APP_LIBRARY:
        if app["category"] != category:
            continue
        haystack = f'{app["title"]} {app["category"]} {app["desc"]} {app["keywords"]}'.lower()
        if search and search.lower() not in haystack:
            continue
        category_apps.append(app)

    if not category_apps:
        continue

    st.markdown(f"""
    <div class="category-card">
        <div class="category-header">
            <div class="category-title">{category}</div>
            <div class="category-count">{len(category_apps)} tools</div>
        </div>
    """, unsafe_allow_html=True)

    for row_start in range(0, len(category_apps), 3):
        cols = st.columns(3)
        for col, app in zip(cols, category_apps[row_start:row_start + 3]):
            page = page_map.get(app["title"])
            with col:
                st.markdown(f"""
                <div class="app-card">
                    <div class="app-top">
                        <div class="app-icon">{app["icon"]}</div>
                        <div class="app-tag">{app["category"].split()[0]}</div>
                    </div>
                    <div class="app-title">{app["title"]}</div>
                    <div class="app-desc">{app["desc"]}</div>
                </div>
                """, unsafe_allow_html=True)
                if page:
                    st.page_link(page, label=f"Launch {app['title']}", icon="➡️")
                else:
                    st.caption("Page file not detected.")
                st.write("")

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("""
<div class="lower-grid">
    <div class="panel">
        <div class="section-title" style="margin-top:0;">Recommended Workflow</div>
        <div class="section-subtitle">A clean process from raw data to decision-ready output.</div>
        <div class="workflow-step">
            <div class="step-num">1</div>
            <div class="step-text">Select the tool that matches your task: report, matchup, projection, or player analysis.</div>
        </div>
        <div class="workflow-step">
            <div class="step-num">2</div>
            <div class="step-text">Upload source files and review filters, minimums, league context, or team settings.</div>
        </div>
        <div class="workflow-step">
            <div class="step-num">3</div>
            <div class="step-text">Generate leaderboards, tables, visuals, summaries, or PDF-ready outputs.</div>
        </div>
        <div class="workflow-step">
            <div class="step-num">4</div>
            <div class="step-text">Share results with coaches, analysts, scouts, front office, or game-planning staff.</div>
        </div>
    </div>
    <div class="panel">
        <div class="section-title" style="margin-top:0;">Latest Updates</div>
        <div class="section-subtitle">Recent platform improvements.</div>
""", unsafe_allow_html=True)

for update in UPDATES:
    st.markdown(f'<div class="update-item">✓ {update}</div>', unsafe_allow_html=True)

st.markdown("""
    </div>
</div>
<div class="footer-line">
    Baseball Operations Portal • Team-neutral analytics, reports, projections, and game-planning tools
</div>
""", unsafe_allow_html=True)
