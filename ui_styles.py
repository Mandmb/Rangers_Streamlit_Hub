"""
Shared professional styling for the Baseball Apps Hub.
"""

import streamlit as st


def apply_page_style():
    st.markdown("""
    <style>
        :root {
            --navy: #0f172a;
            --navy2: #1e293b;
            --blue: #2563eb;
            --text: #0f172a;
            --muted: #64748b;
            --card: #ffffff;
            --border: #e5e7eb;
        }

        .stApp {
            background: linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        }

        .block-container {
            padding-top: 2.75rem;
            padding-bottom: 3rem;
            max-width: 1320px;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%) !important;
            border-right: 1px solid rgba(255,255,255,.08);
        }

        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
            color: #f8fafc !important;
        }

        section[data-testid="stSidebar"] input {
            color: #0f172a !important;
            background: #ffffff !important;
        }

        section[data-testid="stSidebar"] [data-baseweb="select"] div {
            color: #0f172a !important;
            background-color: #ffffff !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] {
            background: rgba(255,255,255,.96) !important;
            border: 1px solid rgba(255,255,255,.25) !important;
            border-radius: 18px !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] * {
            color: #0f172a !important;
            opacity: 1 !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stFileUploader"] button {
            color: #0f172a !important;
            background: #ffffff !important;
            border: 1px solid #cbd5e1 !important;
        }

        h1 {
            color: #0f172a !important;
            font-weight: 900 !important;
            letter-spacing: -1px;
        }

        h2, h3 {
            color: #0f172a !important;
            font-weight: 800 !important;
        }

        div[data-testid="stFileUploader"] {
            background: #ffffff !important;
            border: 1px solid #e5e7eb !important;
            border-radius: 18px !important;
            padding: 16px !important;
            box-shadow: 0 8px 22px rgba(15,23,42,.08);
        }

        div[data-testid="stFileUploader"] * {
            color: #0f172a !important;
            opacity: 1 !important;
        }

        div[data-testid="stAlert"] {
            border-radius: 16px !important;
            border: none !important;
            box-shadow: 0 6px 16px rgba(15,23,42,.08);
        }

        .stButton > button,
        .stDownloadButton > button {
            border-radius: 12px !important;
            border: none !important;
            background: linear-gradient(135deg, #0f172a, #2563eb) !important;
            color: white !important;
            font-weight: 800 !important;
            padding: .65rem 1.1rem !important;
            box-shadow: 0 8px 18px rgba(37,99,235,.22);
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 12px 24px rgba(37,99,235,.30);
        }

        div[data-testid="stNumberInput"] input {
            color: #0f172a !important;
            background: #ffffff !important;
            font-weight: 700 !important;
        }

        div[data-testid="stNumberInput"] button {
            color: #0f172a !important;
            background: #ffffff !important;
            opacity: 1 !important;
            border-left: 1px solid #e5e7eb !important;
        }

        div[data-testid="stNumberInput"] button svg,
        div[data-testid="stNumberInput"] button svg path {
            color: #0f172a !important;
            fill: #0f172a !important;
            stroke: #0f172a !important;
            opacity: 1 !important;
        }

        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {
            border-radius: 18px !important;
            overflow: hidden;
            box-shadow: 0 8px 22px rgba(15,23,42,.08);
            border: 1px solid #e5e7eb;
        }

        .app-header {
            padding: 30px 36px;
            border-radius: 24px;
            background: linear-gradient(135deg, #0f172a, #1d4ed8);
            color: white;
            margin-bottom: 28px;
            box-shadow: 0 14px 35px rgba(15,23,42,.20);
        }

        .app-header h1 {
            color: white !important;
            margin: 0 0 8px 0;
            font-size: 44px !important;
            font-weight: 900 !important;
        }

        .app-header p {
            color: #dbeafe !important;
            font-size: 18px;
            margin: 0;
        }
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
