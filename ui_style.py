"""Shared look for both pages: a dark game-arena style.

The base colors come from the dark theme in .streamlit/config.toml.
The CSS below only adds spacing, rounded corners, borders and the two
accent colors. It styles our own HTML blocks (class names start with
"arena-") and a few Streamlit elements through stable data-testid and
kind attributes, never through generated class names.
"""
from html import escape

import streamlit as st

BACKGROUND = "#0B0F19"
SURFACE = "#151B2B"
TEXT = "#E8EEF6"
MUTED = "#9AA6B8"
BORDER = "#26304A"
PLAYER_ACCENT = "#7DE2B8"
VECTOR_ACCENT = "#A995F8"

_CSS = f"""
<style>
[data-testid="stElementContainer"]:has(.arena-theme),
[data-testid="element-container"]:has(.arena-theme) {{
    display: none;
}}
h1 {{
    letter-spacing: -0.02em;
}}
[data-testid="stMetric"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 14px 18px;
}}
[data-testid="stMetricLabel"] p {{
    color: {MUTED};
}}
[data-testid="stForm"] {{
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
[data-testid="stExpander"] details {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
button[kind^="primary"],
button[kind^="primary"] p {{
    color: {BACKGROUND} !important;
    font-weight: 600;
}}
.arena-card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-top: 4px solid var(--arena-accent);
    border-radius: 16px;
    padding: 18px 20px;
    margin-bottom: 12px;
    overflow-wrap: anywhere;
}}
.arena-card--player {{
    --arena-accent: {PLAYER_ACCENT};
}}
.arena-card--vector {{
    --arena-accent: {VECTOR_ACCENT};
}}
.arena-card__head {{
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: baseline;
    gap: 4px 12px;
    margin-bottom: 14px;
}}
.arena-card__name {{
    color: var(--arena-accent);
    font-size: 1.15rem;
    font-weight: 700;
}}
.arena-card__tag {{
    color: {MUTED};
    font-size: 0.85rem;
}}
.arena-card__label {{
    color: {MUTED};
    font-size: 0.75rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}}
.arena-card__value {{
    color: {TEXT};
    font-size: 2.2rem;
    font-weight: 700;
    line-height: 1.2;
}}
.arena-card__value--empty {{
    color: {MUTED};
}}
.arena-card__hint {{
    color: {TEXT};
    margin-top: 4px;
}}
.arena-card__hint--empty {{
    color: {MUTED};
}}
.arena-card__hint--win {{
    color: var(--arena-accent);
    font-weight: 700;
}}
</style>
"""


def apply_theme() -> None:
    """Add the shared CSS. Call first in every page script.

    app.py has the only st.set_page_config, so this always runs after it.
    It is called in the pages, not in app.py: elements that app.py draws
    are only kept on the default page, so the duel page would lose them.

    New Streamlit versions drop <style> from st.markdown, and st.html with
    nothing but <style> goes to a side container where it may not stay.
    So the CSS is sent together with an empty marker element. The marker's
    own container is then collapsed by the CSS above (by our class name),
    and the <style> inside it still applies to the whole page.
    """
    st.html(_CSS + '<span class="arena-theme" aria-hidden="true"></span>')


def duel_card(
    name: str,
    side: str,
    tag: str,
    guess: int | None = None,
    hint: str | None = None,
    won: bool = False,
) -> None:
    """Show one duel player as a card with the last guess and its hint.

    side is "player" (mint accent) or "vector" (purple accent). With no
    guess yet, the card shows a neutral empty state.
    """
    if guess is None:
        value_html = (
            '<div class="arena-card__value arena-card__value--empty">'
            "&mdash;</div>"
        )
        hint_html = (
            '<div class="arena-card__hint arena-card__hint--empty">'
            "No guess yet</div>"
        )
    else:
        hint_class = "arena-card__hint"
        if won:
            hint_class += " arena-card__hint--win"
        value_html = (
            f'<div class="arena-card__value">{escape(str(guess))}</div>'
        )
        hint_html = f'<div class="{hint_class}">{escape(hint or "")}</div>'

    # One line of HTML: blank lines or indents would end the HTML block
    # in Markdown and show the rest as plain text.
    card_html = (
        f'<div class="arena-card arena-card--{escape(side)}">'
        f'<div class="arena-card__head">'
        f'<span class="arena-card__name">{escape(name)}</span>'
        f'<span class="arena-card__tag">{escape(tag)}</span>'
        f"</div>"
        f'<div class="arena-card__label">Last guess</div>'
        f"{value_html}{hint_html}"
        f"</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)
