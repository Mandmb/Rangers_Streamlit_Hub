from pathlib import Path

ROOT = Path.cwd()
PAGES_DIR = ROOT / "pages"
STYLE_FILE = ROOT / "ui_styles.py"

STYLE_CODE = r'''import streamlit as st


def apply_page_style():
    st.markdown("""
    <style>
        :root {
            --bb-navy: #0f172a;
            --bb-blue: #1d4ed8;
            --bb-soft-blue: #dbeafe;
            --bb-gray: #64748b;
            --bb-border: #e5e7eb;
            --bb-card: #ffffff;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(29,78,216,.10), transparent 32%),
                linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        }

        .block-container {
            padding-top: 2.4rem;
            padding-bottom: 3rem;
            max-width: 1320px;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
            border-right: 1px solid rgba(255,255,255,.08);
        }

        section[data-testid="stSidebar"] * {
            color: #f8fafc !important;
        }

        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        section[data-testid="stSidebar"] label {
            color: #e5e7eb !important;
        }

        h1 {
            font-size: 46px !important;
            line-height: 1.05 !important;
            font-weight: 900 !important;
            letter-spacing: -1.4px !important;
            color: var(--bb-navy) !important;
        }

        h2, h3 {
            color: var(--bb-navy) !important;
            font-weight: 850 !important;
            letter-spacing: -.4px !important;
        }

        div[data-testid="stFileUploader"],
        div[data-testid="stForm"],
        div[data-testid="stExpander"],
        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {
            background: rgba(255,255,255,.92);
            border: 1px solid var(--bb-border);
            border-radius: 18px;
            box-shadow: 0 10px 28px rgba(15,23,42,.08);
        }

        div[data-testid="stFileUploader"] {
            padding: 16px;
        }

        div[data-testid="stAlert"] {
            border-radius: 16px;
            border: 1px solid rgba(37,99,235,.12);
            box-shadow: 0 6px 18px rgba(15,23,42,.07);
        }

        .stButton > button,
        .stDownloadButton > button,
        div[data-testid="stBaseButton-secondary"] button {
            border-radius: 12px !important;
            border: 0 !important;
            background: linear-gradient(135deg, #0f172a, #2563eb) !important;
            color: white !important;
            font-weight: 800 !important;
            box-shadow: 0 8px 18px rgba(37,99,235,.24) !important;
            transition: all .18s ease !important;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 12px 24px rgba(37,99,235,.30) !important;
        }

        div[data-baseweb="select"] > div,
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input {
            border-radius: 12px !important;
            border-color: #d7dde8 !important;
            background-color: white !important;
        }

        hr {
            border: none;
            height: 1px;
            background: linear-gradient(90deg, transparent, #cbd5e1, transparent);
            margin: 2rem 0;
        }

        .bb-hero {
            padding: 30px 34px;
            border-radius: 26px;
            background:
                linear-gradient(135deg, rgba(15,23,42,.96), rgba(30,64,175,.90)),
                radial-gradient(circle at top right, rgba(255,255,255,.22), transparent 30%);
            color: white;
            margin-bottom: 28px;
            box-shadow: 0 18px 42px rgba(15,23,42,.22);
            position: relative;
            overflow: hidden;
        }

        .bb-hero:after {
            content: "";
            position: absolute;
            width: 260px;
            height: 260px;
            border-radius: 50%;
            right: -90px;
            top: -110px;
            background: rgba(255,255,255,.10);
        }

        .bb-hero-kicker {
            text-transform: uppercase;
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 1.5px;
            color: #bfdbfe;
            margin-bottom: 8px;
        }

        .bb-hero h1 {
            color: white !important;
            margin: 0 0 10px 0 !important;
        }

        .bb-hero p {
            color: #dbeafe;
            font-size: 18px;
            margin: 0;
            max-width: 780px;
        }

        .bb-card {
            background: rgba(255,255,255,.94);
            border: 1px solid #e5e7eb;
            border-radius: 20px;
            padding: 22px;
            box-shadow: 0 10px 28px rgba(15,23,42,.08);
            margin-bottom: 18px;
        }

        .bb-card-title {
            font-size: 17px;
            font-weight: 850;
            color: #0f172a;
            margin-bottom: 5px;
        }

        .bb-muted {
            color: #64748b;
            font-size: 14px;
        }
    </style>
    """, unsafe_allow_html=True)


def app_header(title, subtitle="Upload data, review insights, and generate baseball operations reports.", kicker="Baseball Operations Tool"):
    st.markdown(f"""
    <div class="bb-hero">
        <div class="bb-hero-kicker">{kicker}</div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)


def section_card(title, subtitle=""):
    st.markdown(f"""
    <div class="bb-card">
        <div class="bb-card-title">{title}</div>
        <div class="bb-muted">{subtitle}</div>
    </div>
    """, unsafe_allow_html=True)
'''

INJECTION = "from ui_styles import apply_page_style\napply_page_style()\n"


def has_streamlit_import(text: str) -> bool:
    return "import streamlit as st" in text or "from streamlit" in text


def inject_after_streamlit_import(text: str) -> str:
    if "apply_page_style()" in text:
        return text
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "import streamlit as st":
            lines.insert(i + 1, "from ui_styles import apply_page_style")
            lines.insert(i + 2, "apply_page_style()")
            return "\n".join(lines) + "\n"
    return INJECTION + "\n" + text


def main():
    if not PAGES_DIR.exists():
        raise SystemExit("Could not find a pages/ folder. Run this from the Streamlit Hub folder.")

    STYLE_FILE.write_text(STYLE_CODE, encoding="utf-8")
    print(f"Wrote {STYLE_FILE}")

    changed = []
    for page in sorted(PAGES_DIR.glob("*.py")):
        text = page.read_text(encoding="utf-8")
        if not has_streamlit_import(text):
            print(f"Skipped {page}: no streamlit import found")
            continue
        new_text = inject_after_streamlit_import(text)
        if new_text != text:
            page.write_text(new_text, encoding="utf-8")
            changed.append(page)
            print(f"Styled {page}")
        else:
            print(f"Already styled {page}")

    print("\nDone.")
    print(f"Updated {len(changed)} page file(s).")


if __name__ == "__main__":
    main()
