import streamlit as st
from pathlib import Path
from datetime import datetime

st.set_page_config(
    page_title="Baseball Operations Portal",
    page_icon="⚾",
    layout="wide",
)

# Safe fallback theme values. This version avoids experimental CSS features.
THEME = {
    "primary": "#0f172a",
    "secondary": "#2563eb",
    "accent": "#f97316",
    "soft": "#eff6ff",
}

# Shared styling, if available
try:
    from ui_styles import apply_page_style, theme_picker
    selected_theme = theme_picker()
    apply_page_style(selected_theme)
    THEME.update(selected_theme)
except Exception:
    pass

PAGES_DIR = Path("pages")

APP_LIBRARY = [
    {
        "title": "Pregame Visual Report",
        "category": "Reports",
        "icon": "📋",
        "desc": "Build game-planning reports with matchup notes, charts, summaries, and PDF-ready outputs.",
        "keywords": "pregame report visual opponent scouting game plan",
        "status": "Ready",
        "priority": True,
        "aliases": ["pregame", "visual", "report"],
    },
    {
        "title": "Pitch Characteristics",
        "category": "Analytics & Evaluation",
        "icon": "⚾",
        "desc": "Compare pitch traits, movement, velocity, similarity scores, and pitcher profiles.",
        "keywords": "pitch characteristics similarity pitcher movement velocity",
        "status": "Ready",
        "priority": True,
        "aliases": ["pitch", "characteristics"],
    },
    {
        "title": "Leaderboard Report",
        "category": "Reports",
        "icon": "🏆",
        "desc": "Generate clean player leaderboards across hitting, pitching, defense, and baserunning.",
        "keywords": "leaderboard report hitting pitching defense baserunning",
        "status": "Ready",
        "priority": True,
        "aliases": ["leaderboard", "report"],
    },
    {
        "title": "Lineup Optimization",
        "category": "Game Planning",
        "icon": "🧢",
        "desc": "Build lineup combinations based on offensive value, handedness, roles, and constraints.",
        "keywords": "lineup optimization batting order",
        "status": "Ready",
        "priority": True,
        "aliases": ["lineup", "optimization"],
    },
    {
        "title": "Hitter vs Pitcher Matchup",
        "category": "Game Planning",
        "icon": "⚔️",
        "desc": "Evaluate historical hitter performance against specific pitchers and matchup groups.",
        "keywords": "hitter pitcher matchup batter pitcher",
        "status": "Ready",
        "priority": False,
        "aliases": ["hitter", "pitcher", "matchup"],
    },
    {
        "title": "LIDOM Projection",
        "category": "Analytics & Evaluation",
        "icon": "📈",
        "desc": "Project league performance and translate hitter profiles across winter ball environments.",
        "keywords": "lidom projection winter league hitter grader",
        "status": "Ready",
        "priority": False,
        "aliases": ["lidom", "projection"],
    },
    {
        "title": "LIDOM Team Leaderboard",
        "category": "Analytics & Evaluation",
        "icon": "📊",
        "desc": "Compare team rankings, strengths, weaknesses, and advanced league-level metrics.",
        "keywords": "team leaderboard lidom rankings advanced metrics",
        "status": "Ready",
        "priority": False,
        "aliases": ["team", "leaderboard", "lidom"],
    },
]

RECENT_REPORTS = [
    {"title": "Pregame Report", "meta": "Opponent prep workflow", "icon": "📋"},
    {"title": "Pitch Similarity", "meta": "Pitcher profile comparison", "icon": "⚾"},
    {"title": "Leaderboard PDF", "meta": "Player ranking export", "icon": "🏆"},
]

LATEST_UPDATES = [
    "Command Center homepage added",
    "Theme system improved for team-neutral branding",
    "Professional page styling added across app pages",
    "Input contrast and sidebar readability improved",
]


def find_available_pages():
    if not PAGES_DIR.exists():
        return {}

    files = list(PAGES_DIR.glob("*.py"))
    mapping = {}

    for app in APP_LIBRARY:
        aliases = app.get("aliases") or app["title"].lower().split()
        best_file = None
        best_score = 0

        for file in files:
            normalized = file.stem.lower().replace("_", " ").replace("-", " ")
            score = sum(1 for word in aliases if word in normalized)

            if score > best_score:
                best_score = score
                best_file = file

        if best_file and best_score >= 1:
            mapping[app["title"]] = str(best_file)

    return mapping


page_map = find_available_pages()
available_apps = len(page_map)
total_apps = len(APP_LIBRARY)
categories = sorted(set(app["category"] for app in APP_LIBRARY))
today = datetime.now().strftime("%b %d, %Y")

primary = THEME.get("primary", "#0f172a")
secondary = THEME.get("secondary", "#2563eb")
accent = THEME.get("accent", "#f97316")
soft = THEME.get("soft", "#eff6ff")

st.markdown(f"""
<style>
    .main .block-container {{
        padding-top: 2rem;
    }}

    .cmd-hero {{
        display: grid;
        grid-template-columns: 1.45fr .55fr;
        gap: 26px;
        padding: 44px;
        border-radius: 34px;
        background: linear-gradient(135deg, {primary}, {secondary});
        color: white;
        box-shadow: 0 24px 55px rgba(15,23,42,.26);
        overflow: hidden;
        margin-bottom: 24px;
        position: relative;
    }}

    .cmd-hero:before {{
        content: "";
        position: absolute;
        inset: 0;
        background-image:
            linear-gradient(rgba(255,255,255,.055) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,.055) 1px, transparent 1px);
        background-size: 42px 42px;
        opacity: .38;
    }}

    .cmd-hero:after {{
        content: "⚾";
        position: absolute;
        right: 34px;
        top: 16px;
        font-size: 9rem;
        opacity: .12;
        transform: rotate(-13deg);
    }}

    .hero-left, .hero-right {{
        position: relative;
        z-index: 2;
    }}

    .hero-kicker {{
        display: inline-flex;
        padding: 8px 13px;
        border-radius: 999px;
        background: rgba(255,255,255,.13);
        border: 1px solid rgba(255,255,255,.18);
        color: #dbeafe;
        font-size: .78rem;
        font-weight: 950;
        letter-spacing: .12em;
        text-transform: uppercase;
        margin-bottom: 16px;
    }}

    .cmd-hero h1 {{
        color: white !important;
        font-size: 4rem !important;
        line-height: .96;
        margin: 0 0 16px 0;
        letter-spacing: -2.4px;
        font-weight: 950 !important;
    }}

    .cmd-hero p {{
        color: #e0f2fe;
        font-size: 1.16rem;
        line-height: 1.55;
        max-width: 800px;
        margin: 0;
    }}

    .hero-panel {{
        background: rgba(255,255,255,.12);
        border: 1px solid rgba(255,255,255,.18);
        border-radius: 26px;
        padding: 22px;
        min-height: 100%;
    }}

    .hero-panel-title {{
        color: white;
        font-weight: 950;
        font-size: 1.05rem;
        margin-bottom: 14px;
    }}

    .hero-panel-item {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 12px 0;
        border-bottom: 1px solid rgba(255,255,255,.15);
        color: #e0f2fe;
        font-weight: 800;
    }}

    .hero-panel-item:last-child {{
        border-bottom: none;
    }}

    .hero-panel-badge {{
        padding: 5px 9px;
        border-radius: 999px;
        background: rgba(255,255,255,.15);
        color: white;
        font-size: .75rem;
        font-weight: 950;
    }}

    .stat-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 15px;
        margin: 0 0 24px 0;
    }}

    .stat-card {{
        background: rgba(255,255,255,.96);
        border: 1px solid #e5e7eb;
        border-radius: 22px;
        padding: 19px;
        box-shadow: 0 10px 26px rgba(15,23,42,.08);
    }}

    .stat-label {{
        color: #64748b;
        font-size: .74rem;
        font-weight: 950;
        letter-spacing: .08em;
        text-transform: uppercase;
    }}

    .stat-value {{
        color: #0f172a;
        font-size: 1.65rem;
        font-weight: 950;
        margin-top: 4px;
    }}

    .section-head {{
        display: flex;
        justify-content: space-between;
        align-items: end;
        gap: 16px;
        margin: 28px 0 14px 0;
    }}

    .section-title {{
        color: #0f172a;
        font-size: 1.48rem;
        font-weight: 950;
        letter-spacing: -.5px;
    }}

    .section-subtitle {{
        color: #64748b;
        margin-top: 4px;
        font-size: .96rem;
    }}

    .pill {{
        display: inline-flex;
        padding: 8px 12px;
        border-radius: 999px;
        background: white;
        border: 1px solid #e5e7eb;
        color: #334155;
        font-weight: 850;
        font-size: .84rem;
        box-shadow: 0 6px 18px rgba(15,23,42,.06);
        white-space: nowrap;
    }}

    .quick-card, .app-card, .panel, .category-wrap {{
        background: white;
        border: 1px solid #e5e7eb;
        box-shadow: 0 10px 28px rgba(15,23,42,.08);
    }}

    .quick-card {{
        border-radius: 24px;
        padding: 22px;
        min-height: 190px;
        border-top: 5px solid {secondary};
        transition: all .16s ease;
    }}

    .quick-card:hover, .app-card:hover {{
        transform: translateY(-3px);
        box-shadow: 0 16px 38px rgba(15,23,42,.14);
    }}

    .quick-icon, .app-icon, .recent-icon, .step-num {{
        background: linear-gradient(135deg, {soft}, #ffffff);
    }}

    .quick-icon, .app-icon {{
        width: 56px;
        height: 56px;
        border-radius: 18px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.9rem;
        margin-bottom: 14px;
    }}

    .quick-title, .app-title {{
        color: #0f172a;
        font-weight: 950;
        font-size: 1.08rem;
        margin-bottom: 7px;
    }}

    .quick-desc, .app-desc {{
        color: #475569;
        font-size: .92rem;
        line-height: 1.45;
    }}

    .category-wrap {{
        border-radius: 28px;
        padding: 22px;
        margin-bottom: 22px;
    }}

    .category-top {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-bottom: 14px;
        margin-bottom: 16px;
        border-bottom: 1px solid #e5e7eb;
    }}

    .category-name {{
        color: #0f172a;
        font-weight: 950;
        font-size: 1.14rem;
    }}

    .category-count {{
        color: #64748b;
        font-weight: 900;
        font-size: .82rem;
    }}

    .app-card {{
        border-radius: 24px;
        padding: 22px;
        min-height: 235px;
        transition: all .16s ease;
    }}

    .app-top {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
    }}

    .status-badge {{
        padding: 5px 9px;
        border-radius: 999px;
        background: #ecfdf5;
        color: #047857;
        font-size: .72rem;
        font-weight: 950;
        text-transform: uppercase;
    }}

    .lower-grid {{
        display: grid;
        grid-template-columns: 1.15fr .85fr;
        gap: 22px;
        margin-top: 6px;
    }}

    .panel {{
        border-radius: 28px;
        padding: 24px;
    }}

    .recent-item {{
        display: grid;
        grid-template-columns: 42px 1fr;
        gap: 12px;
        padding: 13px 0;
        border-bottom: 1px solid #e5e7eb;
    }}

    .recent-item:last-child {{
        border-bottom: none;
    }}

    .recent-icon {{
        width: 42px;
        height: 42px;
        border-radius: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.35rem;
    }}

    .recent-title {{
        color: #0f172a;
        font-weight: 950;
        line-height: 1.2;
    }}

    .recent-meta {{
        color: #64748b;
        font-size: .88rem;
        margin-top: 2px;
    }}

    .workflow-step {{
        display: grid;
        grid-template-columns: 38px 1fr;
        gap: 12px;
        align-items: start;
        margin-bottom: 14px;
    }}

    .step-num {{
        width: 38px;
        height: 38px;
        border-radius: 13px;
        color: {secondary};
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 950;
    }}

    .step-text {{
        color: #334155;
        font-weight: 750;
        padding-top: 6px;
        line-height: 1.35;
    }}

    .update-item {{
        padding: 11px 0;
        border-bottom: 1px solid #e5e7eb;
        color: #334155;
        font-weight: 760;
    }}

    .update-item:last-child {{
        border-bottom: none;
    }}

    .footer-line {{
        text-align: center;
        color: #64748b;
        margin-top: 34px;
        padding-top: 18px;
        border-top: 1px solid #e5e7eb;
        font-size: .92rem;
    }}

    @media (max-width: 1150px) {{
        .cmd-hero {{ grid-template-columns: 1fr; }}
        .stat-grid {{ grid-template-columns: repeat(2, 1fr); }}
        .lower-grid {{ grid-template-columns: 1fr; }}
        .cmd-hero h1 {{ font-size: 3.1rem !important; }}
    }}

    @media (max-width: 760px) {{
        .stat-grid {{ grid-template-columns: 1fr; }}
        .section-head {{ align-items: flex-start; flex-direction: column; }}
        .cmd-hero {{ padding: 30px 24px; }}
        .cmd-hero h1 {{ font-size: 2.35rem !important; }}
    }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="cmd-hero">
    <div class="hero-left">
        <div class="hero-kicker">Baseball Operations Portal</div>
        <h1>Today&apos;s Workspace</h1>
        <p>Analytics, reports, projections, matchup tools, and game-planning workflows in one team-neutral command center.</p>
    </div>
    <div class="hero-right">
        <div class="hero-panel">
            <div class="hero-panel-title">Platform Snapshot</div>
            <div class="hero-panel-item"><span>Apps Online</span><span class="hero-panel-badge">{available_apps}/{total_apps}</span></div>
            <div class="hero-panel-item"><span>Workflows</span><span class="hero-panel-badge">{len(categories)}</span></div>
            <div class="hero-panel-item"><span>Last Updated</span><span class="hero-panel-badge">{today}</span></div>
            <div class="hero-panel-item"><span>Branding</span><span class="hero-panel-badge">Team-Neutral</span></div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="stat-grid">
    <div class="stat-card"><div class="stat-label">Applications</div><div class="stat-value">{available_apps}/{total_apps}</div></div>
    <div class="stat-card"><div class="stat-label">Categories</div><div class="stat-value">{len(categories)}</div></div>
    <div class="stat-card"><div class="stat-label">Primary Use</div><div class="stat-value">Reports</div></div>
    <div class="stat-card"><div class="stat-label">Audience</div><div class="stat-value">Ops / PD</div></div>
</div>
""", unsafe_allow_html=True)

priority_apps = [app for app in APP_LIBRARY if app["priority"]][:4]

st.markdown("""
<div class="section-head">
    <div>
        <div class="section-title">Quick Actions</div>
        <div class="section-subtitle">Open the most common tools directly from the workspace.</div>
    </div>
    <div class="pill">⚡ Fast launch</div>
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
<div class="section-head">
    <div>
        <div class="section-title">App Library</div>
        <div class="section-subtitle">Browse by workflow category or search for a tool.</div>
    </div>
    <div class="pill">🧭 Sidebar navigation available</div>
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
    <div class="category-wrap">
        <div class="category-top">
            <div class="category-name">{category}</div>
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
                        <div class="status-badge">{app["status"]}</div>
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
        <div class="section-title">Recommended Workflow</div>
        <div class="section-subtitle">A clean path from raw data to decision-ready output.</div>
        <div class="workflow-step">
            <div class="step-num">1</div>
            <div class="step-text">Choose the tool that matches the baseball question: report, matchup, projection, leaderboard, or player analysis.</div>
        </div>
        <div class="workflow-step">
            <div class="step-num">2</div>
            <div class="step-text">Upload the source file and confirm filters, minimums, league context, or team settings.</div>
        </div>
        <div class="workflow-step">
            <div class="step-num">3</div>
            <div class="step-text">Generate tables, visuals, summaries, or PDF-ready outputs for staff review.</div>
        </div>
        <div class="workflow-step">
            <div class="step-num">4</div>
            <div class="step-text">Share results with coaches, analysts, scouts, front office, or game-planning staff.</div>
        </div>
    </div>
    <div class="panel">
        <div class="section-title">Recent Reports</div>
        <div class="section-subtitle">Placeholder workspace items for future report history.</div>
""", unsafe_allow_html=True)

for report in RECENT_REPORTS:
    st.markdown(f"""
    <div class="recent-item">
        <div class="recent-icon">{report["icon"]}</div>
        <div>
            <div class="recent-title">{report["title"]}</div>
            <div class="recent-meta">{report["meta"]}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("""
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="lower-grid">
    <div class="panel">
        <div class="section-title">Latest Updates</div>
        <div class="section-subtitle">Recent improvements to the portal experience.</div>
""", unsafe_allow_html=True)

for update in LATEST_UPDATES:
    st.markdown(f'<div class="update-item">✓ {update}</div>', unsafe_allow_html=True)

st.markdown("""
    </div>
    <div class="panel">
        <div class="section-title">Platform Direction</div>
        <div class="section-subtitle">Built to support multiple teams, leagues, and workflows.</div>
        <div class="update-item">✓ Team-neutral branding</div>
        <div class="update-item">✓ Modular app structure</div>
        <div class="update-item">✓ PDF/report-oriented workflow</div>
        <div class="update-item">✓ Scalable for future tools</div>
    </div>
</div>

<div class="footer-line">
    Baseball Operations Portal • Analytics, reports, projections, and game-planning tools
</div>
""", unsafe_allow_html=True)
