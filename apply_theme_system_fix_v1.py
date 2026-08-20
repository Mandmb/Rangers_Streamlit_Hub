# apply_theme_system_fix_v1.py
from pathlib import Path

UI = Path("ui_styles.py")
HOME = Path("Home.py")

ui_styles_code = """
\"\"\"
Shared professional styling for the Baseball Apps Hub.
Theme system for all pages.
\"\"\"

import streamlit as st


THEMES = {
    "Neutral Baseball": {"primary": "#0f172a", "secondary": "#2563eb", "accent": "#f97316", "soft": "#eff6ff", "sidebar_1": "#0f172a", "sidebar_2": "#1e293b"},
    "Navy / Red": {"primary": "#0b1f3a", "secondary": "#1d4ed8", "accent": "#dc2626", "soft": "#fee2e2", "sidebar_1": "#071525", "sidebar_2": "#102a4c"},
    "Navy / Gold": {"primary": "#111827", "secondary": "#1d4ed8", "accent": "#d97706", "soft": "#fef3c7", "sidebar_1": "#111827", "sidebar_2": "#263244"},
    "Green / White": {"primary": "#064e3b", "secondary": "#059669", "accent": "#84cc16", "soft": "#dcfce7", "sidebar_1": "#052e24", "sidebar_2": "#064e3b"},
    "Black / Orange": {"primary": "#111827", "secondary": "#ea580c", "accent": "#f97316", "soft": "#ffedd5", "sidebar_1": "#111111", "sidebar_2": "#1f2937"},
}


def theme_picker(default="Neutral Baseball"):
    with st.sidebar:
        st.markdown('<div class="sidebar-section-title">Theme</div>', unsafe_allow_html=True)
        choice = st.selectbox(
            "Brand Theme",
            list(THEMES.keys()),
            index=list(THEMES.keys()).index(default) if default in THEMES else 0,
            key="hub_brand_theme",
        )
    return THEMES[choice]


def apply_page_style(theme=None):
    if theme is None:
        theme = THEMES["Neutral Baseball"]

    primary = theme["primary"]
    secondary = theme["secondary"]
    accent = theme["accent"]
    soft = theme.get("soft", "#eff6ff")
    sidebar_1 = theme["sidebar_1"]
    sidebar_2 = theme["sidebar_2"]

    st.markdown(f"""
    <style>
        :root {{
            --hub-primary: {primary};
            --hub-secondary: {secondary};
            --hub-accent: {accent};
            --hub-soft: {soft};
            --hub-sidebar-1: {sidebar_1};
            --hub-sidebar-2: {sidebar_2};
            --hub-text: #0f172a;
            --hub-muted: #64748b;
            --hub-card: #ffffff;
            --hub-border: #e5e7eb;
        }}

        .stApp {{
            background:
                radial-gradient(circle at top right, color-mix(in srgb, var(--hub-secondary) 14%, transparent), transparent 30%),
                linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        }}

        .block-container {{
            padding-top: 2.4rem;
            padding-bottom: 3rem;
            max-width: 1320px;
        }}

        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, var(--hub-sidebar-1) 0%, var(--hub-sidebar-2) 100%) !important;
            border-right: 1px solid rgba(255,255,255,.08);
        }}

        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {{
            color: #f8fafc !important;
        }}

        section[data-testid="stSidebar"] .sidebar-section-title {{
            color: #cbd5e1 !important;
            font-size: .78rem;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: .09em;
            margin: 1.25rem 0 .35rem 0;
        }}

        section[data-testid="stSidebar"] input,
        section[data-testid="stSidebar"] textarea {{
            color: #0f172a !important;
            background: #ffffff !important;
        }}

        section[data-testid="stSidebar"] [data-baseweb="select"] > div {{
            background-color: #ffffff !important;
            color: #0f172a !important;
            border-radius: 14px !important;
        }}

        section[data-testid="stSidebar"] [data-baseweb="select"] * {{
            color: #0f172a !important;
        }}

        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] {{
            background: rgba(255,255,255,.96) !important;
            border-radius: 18px !important;
            box-shadow: 0 10px 25px rgba(0,0,0,.18);
        }}

        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] * {{
            color: #0f172a !important;
            opacity: 1 !important;
        }}

        h1 {{
            color: #0f172a !important;
            font-weight: 950 !important;
            letter-spacing: -1.3px;
        }}

        h2, h3 {{
            color: #0f172a !important;
            font-weight: 850 !important;
        }}

        div[data-testid="stFileUploader"] {{
            background: #ffffff !important;
            border: 1px solid #e5e7eb !important;
            border-radius: 18px !important;
            padding: 16px !important;
            box-shadow: 0 8px 22px rgba(15,23,42,.08);
        }}

        div[data-testid="stFileUploader"] * {{
            color: #0f172a !important;
            opacity: 1 !important;
        }}

        div[data-testid="stAlert"] {{
            border-radius: 16px !important;
            border: none !important;
            box-shadow: 0 6px 16px rgba(15,23,42,.08);
        }}

        .stButton > button,
        .stDownloadButton > button {{
            border-radius: 12px !important;
            border: none !important;
            background: linear-gradient(135deg, var(--hub-primary), var(--hub-secondary)) !important;
            color: white !important;
            font-weight: 850 !important;
            padding: .65rem 1.1rem !important;
            box-shadow: 0 8px 18px color-mix(in srgb, var(--hub-secondary) 28%, transparent);
            transition: all .15s ease;
        }}

        .stButton > button:hover,
        .stDownloadButton > button:hover {{
            transform: translateY(-1px);
            box-shadow: 0 12px 24px color-mix(in srgb, var(--hub-secondary) 36%, transparent);
        }}

        div[data-testid="stNumberInput"] input {{
            color: #0f172a !important;
            background: #ffffff !important;
            font-weight: 800 !important;
        }}

        div[data-testid="stNumberInput"] button {{
            color: #0f172a !important;
            background: #ffffff !important;
            opacity: 1 !important;
            border-left: 1px solid #e5e7eb !important;
        }}

        div[data-testid="stNumberInput"] button svg,
        div[data-testid="stNumberInput"] button svg path {{
            color: #0f172a !important;
            fill: #0f172a !important;
            stroke: #0f172a !important;
            opacity: 1 !important;
        }}

        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {{
            border-radius: 18px !important;
            overflow: hidden;
            box-shadow: 0 8px 22px rgba(15,23,42,.08);
            border: 1px solid #e5e7eb;
        }}

        .app-header {{
            padding: 32px 38px;
            border-radius: 26px;
            background: linear-gradient(135deg, var(--hub-primary), var(--hub-secondary));
            color: white;
            margin-bottom: 28px;
            box-shadow: 0 16px 38px rgba(15,23,42,.22);
            position: relative;
            overflow: hidden;
        }}

        .app-header h1 {{
            color: white !important;
            margin: 0 0 8px 0;
            font-size: 44px !important;
            font-weight: 950 !important;
            position: relative;
            z-index: 1;
        }}

        .app-header p {{
            color: #dbeafe !important;
            font-size: 18px;
            margin: 0;
            position: relative;
            z-index: 1;
        }}

        .soft-card {{
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 22px;
            padding: 22px;
            box-shadow: 0 10px 26px rgba(15,23,42,.08);
        }}
    </style>
    """, unsafe_allow_html=True)


def app_header(title, subtitle="Baseball operations tool"):
    st.markdown(
        f"""
        <div class="app-header">
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
"""

UI.write_text(ui_styles_code)

home = HOME.read_text()

replacements = {
    "rgba(8,15,29,.97), rgba(30,64,175,.88)": "var(--hub-primary), var(--hub-secondary)",
    "rgba(249,115,22,.42)": "color-mix(in srgb, var(--hub-accent) 45%, transparent)",
    "rgba(59,130,246,.28)": "color-mix(in srgb, var(--hub-secondary) 32%, transparent)",
    "#2563eb": "var(--hub-secondary)",
    "#1d4ed8": "var(--hub-secondary)",
    "#eff6ff, #dbeafe": "var(--hub-soft), #ffffff",
}

for old, new in replacements.items():
    home = home.replace(old, new)

if "Fallback theme variables" not in home:
    home = home.replace(
        "except Exception:\n    theme = None",
        """except Exception:
    theme = None
    st.markdown(\"\"\"
    <style>
        :root {
            --hub-primary: #0f172a;
            --hub-secondary: #2563eb;
            --hub-accent: #f97316;
            --hub-soft: #eff6ff;
        }
    </style>
    \"\"\", unsafe_allow_html=True)  # Fallback theme variables"""
    )

HOME.write_text(home)
print("Applied brand theme fix to ui_styles.py and Home.py.")
