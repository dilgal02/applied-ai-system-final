import streamlit as st

# The only st.set_page_config of the app. Each page then calls
# ui_style.apply_theme() first, so the shared styles come after this.
st.set_page_config(page_title="Number Duel", page_icon="⚔️", layout="wide")

solo_page = st.Page(
    "pages/solo.py", title="Solo Game", icon="🎯", default=True
)
duel_page = st.Page("pages/duel.py", title="Number Duel", icon="⚔️")

page = st.navigation([solo_page, duel_page])
page.run()
