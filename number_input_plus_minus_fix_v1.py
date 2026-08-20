# number_input_plus_minus_fix_v1.py
from pathlib import Path

ui_file = Path("ui_styles.py")

if ui_file.exists():
    txt = ui_file.read_text()

    css = """
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
    """

    if css not in txt:
        txt += "\\n\\n# Number input contrast fix\\n"
        txt += f'\\nst.markdown("""<style>{css}</style>""", unsafe_allow_html=True)\\n'

    ui_file.write_text(txt)
    print("Updated ui_styles.py")
else:
    print("ui_styles.py not found")
