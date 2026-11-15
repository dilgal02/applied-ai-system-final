import random
import re

import streamlit as st

from duel_logic import DuelState, create_duel
from duel_service import GuardrailViolation, safe_play_round
from logic_utils import get_range_for_difficulty

DIFFICULTIES = ["Easy", "Normal", "Hard"]
ATTEMPT_LIMITS = {"Easy": 6, "Normal": 8, "Hard": 5}

# Session keys of this page. Solo uses other keys, so the games never mix.
STATE_KEY = "duel_state"
ERROR_KEY = "duel_error"
# The chosen difficulty is kept apart from its widget, because Streamlit
# drops a widget's own state when another page is shown.
DIFFICULTY_KEY = "duel_difficulty"
DIFFICULTY_WIDGET_KEY = "duel_difficulty_select"
# Temporary input that New Duel clears.
TEMP_INPUT_PREFIXES = ("duel_guess_input", "duel_secret_input")

HINTS = {
    "Too Low": "too low, the number is higher",
    "Too High": "too high, the number is lower",
    "Win": "correct!",
}

GUARDRAIL_MESSAGE = (
    "A safety check stopped this round, so it was not counted. "
    "Your duel is unchanged. Please try again."
)


def parse_guess_text(raw) -> tuple[int | None, str | None]:
    """Read a whole number from the guess field.

    Returns (number, None) or (None, error message). A fraction is never
    rounded or cut: it is rejected.
    """
    text = (raw or "").strip()
    if not text:
        return None, "Enter a guess."
    if re.fullmatch(r"[+-]?[0-9]+", text):
        return int(text), None
    if re.fullmatch(r"[+-]?([0-9]+[.,][0-9]*|[.,][0-9]+)", text):
        return None, "Fractions are not allowed. Enter a whole number."
    return None, "That is not a number. Enter a whole number."


def start_duel(difficulty: str, player_secret) -> str | None:
    """Create a new duel. Returns an error message, or None on success."""
    low, high = get_range_for_difficulty(difficulty)
    if player_secret is None:
        return "Enter your secret number."
    if not low <= player_secret <= high:
        return f"Your secret number must be between {low} and {high}."
    try:
        state = create_duel(
            low=low,
            high=high,
            attempt_limit=ATTEMPT_LIMITS[difficulty],
            player_secret=player_secret,
            # The opponent's number is drawn only here, at the start.
            bot_secret=random.randint(low, high),
        )
    except ValueError:
        return (
            f"Your secret number must be a whole number "
            f"from {low} to {high}."
        )
    st.session_state[STATE_KEY] = state
    st.session_state[ERROR_KEY] = None
    return None


def submit_guess(state: DuelState, raw_guess) -> None:
    """Play one round from the form. On any error the duel stays as it was."""
    guess, problem = parse_guess_text(raw_guess)
    if problem is None and not state.low <= guess <= state.high:
        problem = f"Your guess must be between {state.low} and {state.high}."
    if problem is not None:
        st.session_state[ERROR_KEY] = problem
        return

    try:
        new_state = safe_play_round(state, guess)
    except GuardrailViolation:
        # Caught before ValueError, because it is a ValueError too.
        # Only a general message is shown, never the inner reason.
        st.session_state[ERROR_KEY] = GUARDRAIL_MESSAGE
        return
    except ValueError as error:
        st.session_state[ERROR_KEY] = str(error)
        return

    # The new state is stored only after the guarded round was accepted.
    st.session_state[STATE_KEY] = new_state
    st.session_state[ERROR_KEY] = None
    # A fresh run shows the new round and does not handle this submit again.
    st.rerun()


def reset_duel() -> None:
    """New Duel: forget the duel and its temporary input, keep difficulty."""
    for key in list(st.session_state.keys()):
        is_game = key in (STATE_KEY, ERROR_KEY)
        if is_game or key.startswith(TEMP_INPUT_PREFIXES):
            del st.session_state[key]


def show_setup() -> None:
    saved = st.session_state.get(DIFFICULTY_KEY, "Normal")
    difficulty = st.selectbox(
        "Difficulty",
        DIFFICULTIES,
        index=DIFFICULTIES.index(saved) if saved in DIFFICULTIES else 1,
        key=DIFFICULTY_WIDGET_KEY,
    )
    st.session_state[DIFFICULTY_KEY] = difficulty
    low, high = get_range_for_difficulty(difficulty)
    st.caption(
        f"Pick a whole number from {low} to {high}. "
        f"The duel lasts at most {ATTEMPT_LIMITS[difficulty]} rounds."
    )

    with st.form("duel_setup_form"):
        player_secret = st.number_input(
            "Your secret number",
            min_value=low,
            max_value=high,
            value=None,
            step=1,
            key=f"duel_secret_input_{difficulty}",
        )
        started = st.form_submit_button("Start Duel")

    if started:
        error = start_duel(difficulty, player_secret)
        if error:
            st.error(error)
        else:
            st.rerun()


def show_result(state: DuelState) -> None:
    reveal = f"The opponent's number was {state.bot_secret}."
    if state.status == "player_won":
        st.success(
            f"🎉 You won! You guessed the opponent's number first. {reveal}"
        )
    elif state.status == "bot_won":
        st.warning(f"🤖 The opponent guessed your number first. {reveal}")
    else:
        last = state.rounds[-1]
        if last.player_outcome == "Win" and last.bot_outcome == "Win":
            reason = "you both guessed right in the same round"
        else:
            reason = (
                f"all {state.attempt_limit} rounds were used "
                f"and nobody guessed right"
            )
        st.info(f"🤝 It's a draw: {reason}. {reveal}")


def history_rows(state: DuelState) -> list[dict]:
    return [
        {
            "Round": number,
            "Your guess": round_.player_guess,
            "Your hint": round_.player_outcome,
            "Opponent's guess": round_.bot_guess,
            "Opponent's hint": round_.bot_outcome,
        }
        for number, round_ in enumerate(state.rounds, start=1)
    ]


def show_game(state: DuelState) -> None:
    # The opponent's secret is not shown while the duel is on.
    st.caption(
        f"Difficulty: {st.session_state.get(DIFFICULTY_KEY, '')} · "
        f"Range: {state.low} to {state.high} · "
        f"Your secret number: {state.player_secret}"
    )
    played = len(state.rounds)
    played_col, left_col = st.columns(2)
    played_col.metric("Rounds played", played)
    left_col.metric("Rounds left", state.attempt_limit - played)

    if state.rounds:
        last = state.rounds[-1]
        st.subheader(f"Round {played}")
        st.write(
            f"**You** guessed {last.player_guess}: "
            f"{HINTS[last.player_outcome]}"
        )
        st.write(
            f"**Opponent** guessed {last.bot_guess}: "
            f"{HINTS[last.bot_outcome]}"
        )

    if state.status == "playing":
        with st.form("duel_guess_form"):
            # A new key each round gives an empty field after a good move.
            raw_guess = st.text_input(
                "Your guess", key=f"duel_guess_input_{played}"
            )
            submitted = st.form_submit_button("Submit Guess")
        if submitted:
            submit_guess(state, raw_guess)
        if st.session_state.get(ERROR_KEY):
            st.error(st.session_state[ERROR_KEY])
    else:
        show_result(state)
        st.button("New Duel", key="duel_new_button", on_click=reset_duel)

    if state.rounds:
        st.subheader("History")
        st.dataframe(history_rows(state), hide_index=True)


st.title("Number Duel")

st.subheader("Rules")
st.markdown(
    "- You and the computer each pick a secret number.\n"
    "- Every round, both of you get one guess at the other's number.\n"
    "- If you both guess right in the same round, the duel is a draw."
)

duel_state = st.session_state.get(STATE_KEY)
if duel_state is None:
    show_setup()
else:
    show_game(duel_state)
