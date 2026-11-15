import streamlit as st

st.set_page_config(page_title="Glitchy Guesser", page_icon="🎮")

solo_page = st.Page("pages/solo.py", title="Solo Game", default=True)
duel_page = st.Page("pages/duel.py", title="Number Duel")

page = st.navigation([solo_page, duel_page])
page.run()
