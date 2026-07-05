
import streamlit as st


def apply_page_style():
    st.markdown("""
    <style>
        :root {
            --portal-navy: #0f172a;
            --portal-navy-2: #1e293b;
            --portal-blue: #2563eb;
            --portal-text: #0f172a;
            --portal-muted: #475569;
            --portal-border: #e2e8f0;
            --portal-card: #ffffff;
            --portal-soft: #f8fafc;
        }

        .stApp {
            background: linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        }

        .block-container {
            padding-top: 3rem;
            padding-bottom: 3rem;
            max-width: 1320px;
        }

        /* =========================
           SIDEBAR BASE
        ========================= */
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%) !important;
            border-right: 1px solid rgba(255,255,255,.08) !important;
        }

        section[data-testid="stSidebar"] > div {
            background: transparent !important;
        }

        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] *,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] h4,
        section[data-testid="stSidebar"] div {
            color: #f8fafc !important;
        }

        section[data-testid="stSidebar"] hr {
            border-color: rgba(255,255,255,.14) !important;
        }

        /* Sidebar page navigation */
        section[data-testid="stSidebar"] a,
        section[data-testid="stSidebar"] a span,
        section[data-testid="stSidebar"] button,
        section[data-testid="stSidebar"] button span {
            color: #f8fafc !important;
            opacity: 1 !important;
        }

        section[data-testid="stSidebar"] a[aria-current="page"],
        section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"][aria-current="page"],
        section[data-testid="stSidebar"] a:hover {
            background: rgba(148, 163, 184, .22) !important;
            border-radius: 12px !important;
        }

        /* =========================
           SIDEBAR INPUTS / UPLOADERS
        ========================= */
        section[data-testid="stSidebar"] div[data-testid="stFileUploader"],
        section[data-testid="stSidebar"] div[data-testid="stFileUploaderDropzone"] {
            background: #ffffff !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 18px !important;
            box-shadow: 0 10px 25px rgba(0,0,0,.18) !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] *,
        section[data-testid="stSidebar"] div[data-testid="stFileUploaderDropzone"] *,
        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] small,
        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] span,
        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] p {
            color: #0f172a !important;
            opacity: 1 !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] label,
        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] label * {
            color: #0f172a !important;
            opacity: 1 !important;
            font-weight: 700 !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] button,
        section[data-testid="stSidebar"] div[data-testid="stFileUploaderDropzone"] button {
            background: #f8fafc !important;
            color: #0f172a !important;
            border: 1px solid #94a3b8 !important;
            box-shadow: none !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] button *,
        section[data-testid="stSidebar"] div[data-testid="stFileUploaderDropzone"] button * {
            color: #0f172a !important;
        }

        section[data-testid="stSidebar"] [data-baseweb="select"],
        section[data-testid="stSidebar"] [data-baseweb="select"] > div {
            background: #ffffff !important;
            color: #0f172a !important;
            border-color: #cbd5e1 !important;
        }

        section[data-testid="stSidebar"] [data-baseweb="select"] *,
        section[data-testid="stSidebar"] [data-baseweb="popover"] *,
        section[data-testid="stSidebar"] input,
        section[data-testid="stSidebar"] textarea {
            color: #0f172a !important;
            opacity: 1 !important;
        }

        section[data-testid="stSidebar"] [data-baseweb="select"] svg {
            fill: #0f172a !important;
        }

        /* Expander in sidebar */
        section[data-testid="stSidebar"] [data-testid="stExpander"] {
            background: rgba(255,255,255,.08) !important;
            border: 1px solid rgba(255,255,255,.16) !important;
            border-radius: 14px !important;
        }

        section[data-testid="stSidebar"] [data-testid="stExpander"] summary,
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary * {
            color: #f8fafc !important;
        }

        /* =========================
           MAIN PAGE TEXT
        ========================= */
        h1 {
            font-size: 48px !important;
            font-weight: 900 !important;
            color: #0f172a !important;
            letter-spacing: -1px;
        }

        h2, h3 {
            color: #0f172a !important;
            font-weight: 800 !important;
        }

        p, li, label, span {
            color: inherit;
        }

        /* Main page uploaders */
        .main div[data-testid="stFileUploader"],
        .main div[data-testid="stFileUploaderDropzone"] {
            background: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 18px !important;
            box-shadow: 0 8px 22px rgba(15,23,42,.08) !important;
        }

        .main div[data-testid="stFileUploader"] *,
        .main div[data-testid="stFileUploaderDropzone"] * {
            color: #0f172a !important;
            opacity: 1 !important;
        }

        .main div[data-testid="stFileUploader"] button,
        .main div[data-testid="stFileUploaderDropzone"] button {
            background: #f8fafc !important;
            color: #0f172a !important;
            border: 1px solid #94a3b8 !important;
            box-shadow: none !important;
        }

        div[data-testid="stAlert"] {
            border-radius: 16px !important;
            border: none !important;
            box-shadow: 0 6px 16px rgba(15,23,42,.08) !important;
        }

        .stButton > button,
        .stDownloadButton > button {
            border-radius: 12px !important;
            border: none !important;
            background: linear-gradient(135deg, #0f172a, #2563eb) !important;
            color: white !important;
            font-weight: 800 !important;
            padding: .65rem 1.1rem !important;
            box-shadow: 0 8px 18px rgba(37,99,235,.22) !important;
        }

        .stButton > button *,
        .stDownloadButton > button * {
            color: white !important;
        }

        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {
            border-radius: 18px !important;
            overflow: hidden !important;
            box-shadow: 0 8px 22px rgba(15,23,42,.08) !important;
            border: 1px solid #e5e7eb !important;
        }

        .app-header {
            padding: 28px 34px;
            border-radius: 24px;
            background: linear-gradient(135deg, #0f172a, #1d4ed8);
            color: white;
            margin-bottom: 28px;
            box-shadow: 0 14px 35px rgba(15,23,42,.20);
        }

        .app-header h1 {
            color: white !important;
            margin-bottom: 8px;
        }

        .app-header p {
            color: #dbeafe !important;
            font-size: 18px;
            margin: 0;
        }
    </style>
    """, unsafe_allow_html=True)


def app_header(title, subtitle="Baseball operations tool"):
    st.markdown(f"""
    <div class="app-header">
        <h1>{title}</h1>
        <p>{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)
\n\n# Number input contrast fix\n\nst.markdown("""<style>
        div[data-testid="stNumberInput"] button {
            color: #0f172a !important;
            background: #ffffff !important;
            opacity: 1 !important;
            font-weight: 900 !important;
        }

        div[data-testid="stNumberInput"] button svg {
            fill: #0f172a !important;
            color: #0f172a !important;
        }
    </style>""", unsafe_allow_html=True)\n