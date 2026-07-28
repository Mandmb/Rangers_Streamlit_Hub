import streamlit as st

st.set_page_config(
    page_title="Rangers Streamlit Hub",
    page_icon="⚾",
    layout="wide",
)

st.title("⚾ Rangers Streamlit Hub")
st.success("The application is online.")

st.markdown(
    '''
    Use the sidebar to open the available tools.

    This temporary recovery homepage is intentionally minimal so the
    Streamlit deployment can start without loading custom homepage code.
    '''
)
