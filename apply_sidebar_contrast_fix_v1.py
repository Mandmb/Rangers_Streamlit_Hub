from pathlib import Path

ROOT = Path.cwd()
UI = ROOT / "ui_styles.py"

css_fix = r'''

def apply_sidebar_contrast_fix():
    import streamlit as st
    st.markdown("""
    <style>
        /* Sidebar readability fix */
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%) !important;
            border-right: 1px solid #d8dee8 !important;
        }

        section[data-testid="stSidebar"] * {
            color: #0f172a !important;
            opacity: 1 !important;
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] div {
            color: #0f172a !important;
        }

        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
            color: #0f172a !important;
        }

        section[data-testid="stSidebar"] .stSelectbox,
        section[data-testid="stSidebar"] .stMultiSelect,
        section[data-testid="stSidebar"] .stTextInput,
        section[data-testid="stSidebar"] .stNumberInput,
        section[data-testid="stSidebar"] .stDateInput {
            color: #0f172a !important;
        }

        section[data-testid="stSidebar"] div[data-baseweb="select"] > div,
        section[data-testid="stSidebar"] input,
        section[data-testid="stSidebar"] textarea {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 12px !important;
        }

        section[data-testid="stSidebar"] hr {
            border-color: #cbd5e1 !important;
        }

        section[data-testid="stSidebar"] [data-testid="stAlert"] {
            background: #dbeafe !important;
            color: #0f172a !important;
            border: 1px solid #bfdbfe !important;
        }

        section[data-testid="stSidebar"] [data-testid="stFileUploader"] {
            background: #ffffff !important;
            border: 1px solid #d8dee8 !important;
            border-radius: 18px !important;
        }

        section[data-testid="stSidebar"] button {
            color: #0f172a !important;
        }

        section[data-testid="stSidebar"] .stButton > button,
        section[data-testid="stSidebar"] .stDownloadButton > button {
            background: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #cbd5e1 !important;
            box-shadow: none !important;
        }

        /* Keep main app uploaders readable too */
        div[data-testid="stFileUploader"] * {
            color: #0f172a !important;
            opacity: 1 !important;
        }

        div[data-testid="stFileUploader"] button {
            background: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #cbd5e1 !important;
        }
    </style>
    """, unsafe_allow_html=True)
'''

if not UI.exists():
    UI.write_text("import streamlit as st\n" + css_fix + "\n", encoding="utf-8")
else:
    text = UI.read_text(encoding="utf-8")
    if "def apply_sidebar_contrast_fix" not in text:
        text += "\n" + css_fix + "\n"
    # Ensure the contrast fix is called inside apply_page_style if it exists.
    if "def apply_page_style" in text and "apply_sidebar_contrast_fix()" not in text:
        # Insert call near the end of apply_page_style by adding it immediately before next def after apply_page_style
        marker = "\ndef app_header"
        if marker in text:
            text = text.replace(marker, "\n    apply_sidebar_contrast_fix()\n" + marker, 1)
        else:
            text += "\n# Auto-apply sidebar contrast fix when imported directly\n"
    UI.write_text(text, encoding="utf-8")

# Also make sure pages that import apply_page_style keep working.
print("✅ Sidebar contrast fix applied to ui_styles.py")
print("Next: run python3 -m py_compile ui_styles.py pages/*.py, then commit/push.")
