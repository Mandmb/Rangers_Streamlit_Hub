import streamlit as st
from pathlib import Path

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
    {"title": "LIDOM Projection", "category": "League Tools", "icon": "📈", "desc": "Project league performance and translate hitter profiles across winter ball environments.", "keywords": "lidom projection winter league hitter grader"},
    {"title": "Lineup Optimization", "category": "Game Planning", "icon": "🧢", "desc": "Build lineup combinations based on offensive value, role, handedness, and team constraints.", "keywords": "lineup optimization batting order"},
    {"title": "Pitch Characteristics", "category": "Player Analysis", "icon": "⚾", "desc": "Compare pitch traits, movement, velocity, similarity scores, and player profiles.", "keywords": "pitch characteristics similarity pitcher movement velocity"},
    {"title": "Leaderboard Report", "category": "Reports", "icon": "🏆", "desc": "Generate clean player leaderboards across hitting, pitching, defense, and baserunning.", "keywords": "leaderboard report hitting pitching defense baserunning"},
    {"title": "Hitter vs Pitcher Matchup", "category": "Game Planning", "icon": "⚔️", "desc": "Evaluate historical matchup performance between hitters and pitchers.", "keywords": "hitter pitcher matchup batter pitcher"},
    {"title": "LIDOM Team Leaderboard", "category": "League Tools", "icon": "📊", "desc": "Compare team rankings, strengths, weaknesses, and advanced league-level metrics.", "keywords": "team leaderboard lidom rankings advanced metrics"},
    {"title": "Pregame Visual Report", "category": "Reports", "icon": "📋", "desc": "Create opponent reports, visuals, summaries, and game-planning material.", "keywords": "pregame report visual opponent scouting"},
]

def available_pages():
    if not PAGES_DIR.exists():
        return {}
    files = list(PAGES_DIR.glob("*.py"))
    mapping = {}
    for file in files:
        normalized = file.stem.lower().replace("_", " ").replace("-", " ")
        for app in APP_LIBRARY:
            words = app["title"].lower().split()
            score = sum(1 for word in words if word in normalized)
            if score >= max(1, len(words) // 2):
                mapping[app["title"]] = str(file)
    return mapping

page_map = available_pages()

st.markdown("""
<style>
.portal-hero {
    padding: 42px 46px;
    border-radius: 30px;
    background:
        linear-gradient(135deg, rgba(15,23,42,.96), rgba(37,99,235,.86)),
        radial-gradient(circle at top right, rgba(249,115,22,.38), transparent 35%);
    color: white;
    box-shadow: 0 18px 42px rgba(15,23,42,.24);
    margin-bottom: 28px;
    overflow: hidden;
    position: relative;
}
.portal-hero::after {
    content: "";
    position: absolute;
    right: -90px;
    top: -80px;
    width: 260px;
    height: 260px;
    border-radius: 999px;
    background: rgba(255,255,255,.10);
}
.hero-kicker {
    font-size: .85rem;
    font-weight: 900;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: #bfdbfe;
    margin-bottom: 10px;
    position: relative;
    z-index: 1;
}
.portal-hero h1 {
    font-size: 3.35rem !important;
    line-height: 1.02;
    margin: 0 0 12px 0;
    color: white !important;
    position: relative;
    z-index: 1;
}
.portal-hero p {
    font-size: 1.15rem;
    color: #e0f2fe;
    max-width: 760px;
    margin: 0;
    position: relative;
    z-index: 1;
}
.metric-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin: 22px 0 30px 0;
}
.metric-box {
    background: rgba(255,255,255,.92);
    border: 1px solid #e5e7eb;
    border-radius: 18px;
    padding: 18px;
    box-shadow: 0 9px 24px rgba(15,23,42,.08);
}
.metric-label {
    color: #64748b;
    font-weight: 900;
    text-transform: uppercase;
    font-size: .76rem;
    letter-spacing: .06em;
}
.metric-value {
    color: #0f172a;
    font-size: 1.55rem;
    font-weight: 950;
    margin-top: 4px;
}
.section-title {
    margin-top: 10px;
    font-size: 1.45rem;
    font-weight: 950;
    color: #0f172a;
}
.section-subtitle {
    color: #64748b;
    margin-bottom: 18px;
}
.app-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 24px;
    padding: 24px;
    min-height: 238px;
    box-shadow: 0 9px 24px rgba(15,23,42,.08);
    transition: all .16s ease;
    border-top: 5px solid #2563eb;
}
.app-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 14px 34px rgba(15,23,42,.14);
}
.app-category {
    font-size: .75rem;
    color: #64748b;
    font-weight: 900;
    letter-spacing: .08em;
    text-transform: uppercase;
}
.app-icon {
    width: 58px;
    height: 58px;
    border-radius: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #eff6ff, #dbeafe);
    font-size: 2rem;
    margin: 13px 0 14px 0;
}
.app-title {
    color: #0f172a;
    font-size: 1.18rem;
    font-weight: 950;
    margin-bottom: 8px;
}
.app-desc {
    color: #475569;
    font-size: .95rem;
    line-height: 1.45;
    min-height: 70px;
}
.workflow {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 24px;
    padding: 24px;
    box-shadow: 0 9px 24px rgba(15,23,42,.08);
    margin-top: 30px;
}
.workflow-step {
    padding: 13px 15px;
    border-left: 4px solid #2563eb;
    background: #f8fafc;
    border-radius: 12px;
    margin-bottom: 10px;
    color: #0f172a;
    font-weight: 750;
}
.footer-line {
    text-align: center;
    color: #64748b;
    margin-top: 38px;
    padding-top: 18px;
    border-top: 1px solid #e5e7eb;
    font-size: .92rem;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="portal-hero">
    <div class="hero-kicker">Baseball Operations Platform</div>
    <h1>Baseball Apps Hub</h1>
    <p>One central portal for reports, projections, matchups, leaderboards, player analysis, and game-planning workflows.</p>
</div>
""", unsafe_allow_html=True)

total_apps = len(APP_LIBRARY)
available = len(page_map)
categories = len(set(app["category"] for app in APP_LIBRARY))

st.markdown(f"""
<div class="metric-strip">
    <div class="metric-box"><div class="metric-label">Available Apps</div><div class="metric-value">{available}/{total_apps}</div></div>
    <div class="metric-box"><div class="metric-label">Categories</div><div class="metric-value">{categories}</div></div>
    <div class="metric-box"><div class="metric-label">Focus</div><div class="metric-value">PD / Scouting</div></div>
    <div class="metric-box"><div class="metric-label">Workflow</div><div class="metric-value">Reports</div></div>
</div>
""", unsafe_allow_html=True)

search = st.text_input("Search apps", placeholder="Search reports, projections, matchups, pitching, leaderboard...", label_visibility="collapsed")
category_options = ["All"] + sorted(set(app["category"] for app in APP_LIBRARY))
category = st.selectbox("Filter by category", category_options, label_visibility="collapsed")

filtered = []
for app in APP_LIBRARY:
    haystack = f'{app["title"]} {app["category"]} {app["desc"]} {app["keywords"]}'.lower()
    if search and search.lower() not in haystack:
        continue
    if category != "All" and app["category"] != category:
        continue
    filtered.append(app)

st.markdown("""
<div class="section-title">App Library</div>
<div class="section-subtitle">Choose a tool below or use the sidebar navigation.</div>
""", unsafe_allow_html=True)

for row_start in range(0, len(filtered), 3):
    cols = st.columns(3)
    for col, app in zip(cols, filtered[row_start:row_start + 3]):
        page = page_map.get(app["title"])
        with col:
            st.markdown(f"""
            <div class="app-card">
                <div class="app-category">{app["category"]}</div>
                <div class="app-icon">{app["icon"]}</div>
                <div class="app-title">{app["title"]}</div>
                <div class="app-desc">{app["desc"]}</div>
            </div>
            """, unsafe_allow_html=True)
            if page:
                st.page_link(page, label=f"Launch {app['title']}", icon="➡️")
            else:
                st.caption("Page file not detected yet.")
            st.write("")

st.markdown("""
<div class="workflow">
    <div class="section-title" style="margin-top:0;">Recommended Workflow</div>
    <div class="section-subtitle">A simple way to move from preparation to reporting.</div>
    <div class="workflow-step">1. Upload or prepare source CSVs in the app that matches your task.</div>
    <div class="workflow-step">2. Review filters, thresholds, and league/team context.</div>
    <div class="workflow-step">3. Generate tables, visuals, summaries, or PDFs.</div>
    <div class="workflow-step">4. Share the output with coaches, analysts, scouts, or decision-makers.</div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="footer-line">
    Baseball Operations Portal • Team-neutral analytics, reports, and game-planning tools
</div>
""", unsafe_allow_html=True)
