import streamlit as st

st.title("Number Duel")

st.subheader("Rules")
st.markdown(
    "- You and the computer each pick a secret number.\n"
    "- Every round, both of you get one guess at the other's number.\n"
    "- If you both guess right in the same round, the duel is a draw."
)
