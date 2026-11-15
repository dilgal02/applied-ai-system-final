# Model Card: Number Duel

| Item | Details |
|------|---------|
| System | Number Duel, a Streamlit app with a Solo Game and a Number Duel page |
| Opponent | Vector, a deterministic binary-search algorithm (`bot_agent.py`) |
| Machine learning | None: no training, no trained model, no language model, no external AI API, no RAG |
| Advanced feature | A built-in reliability system that checks every duel step before it is saved |
| Tested environment | Python 3.13.15, Streamlit 1.60.0 |
| Last confirmed results | 119 automated tests passed; 6 of 6 evaluation scenarios passed |

## Purpose and intended use

Number Duel is a small number guessing game for one player in a web
browser. It is a course project that shows how to build a game step by step
with tests, and how to protect the game state with independent checks.
It is meant for fun and for learning, not for betting, grading people or
any decision about real people.

## How the system works

- **Solo Game** (`pages/solo.py`, `logic_utils.py`): the player guesses a
  hidden number and gets higher / lower hints, a closeness label, a score
  and a guess history.
- **Number Duel** (`pages/duel.py`): the player and Vector each pick a
  secret number. In every round both make one guess at the other's number.
- **Engine** (`duel_logic.play_round`): plays one round and builds a new,
  immutable candidate state.
- **Inspector** (`guardrails.validate_transition`): checks the step from the
  old state to the candidate. It works out the hints, Vector's search range
  and the result again with its own comparisons and does not call the game
  functions.
- **Safe service** (`duel_service.safe_play_round`): returns the candidate
  only after the inspector accepted it. The page saves the new state only
  then. The service logs `duel_round_accepted` or `duel_round_rejected`,
  without secrets.

The Solo game does not go through the inspector.

## No training and no language model

Nothing in this system is trained or learned from data. Vector does not
"think": `choose_guess` returns the middle of the numbers that are still
possible, and `update_bounds` narrows that range after each hint. The same
inputs always give the same moves. The project does not call any external
AI API and does not use a language model or retrieval (RAG).

## Algorithmic limits and how predictable Vector is

Vector is fully predictable. A player who knows binary search knows its next
guess. The table shows the most guesses Vector can need for each difficulty,
worked out over every possible secret:

| Difficulty | Range | Round limit | Vector's worst case | Secrets Vector cannot find in time |
|------------|-------|-------------|---------------------|------------------------------------|
| Easy | 1-20 | 6 | 5 guesses | 0 of 20 |
| Normal | 1-100 | 8 | 7 guesses | 0 of 100 |
| Hard | 1-50 | 5 | 6 guesses | 19 of 50 |

So on Easy and Normal, Vector always finds the player's number within the
limit, and the player has to be at least as fast to win or draw. On Hard,
the round limit can run out first.

The inspector checks that each of Vector's guesses is inside its current
range, but not that it is exactly the middle. A different strategy that
stays inside the range would still pass.

## Evaluation and its limits

`evaluate.py` runs six fixed scenarios through the real `create_duel` and
`safe_play_round`: a player win, a Vector win, a draw where both guess right,
a draw at the round limit, a bad guess rejected by the engine, and a broken
engine result blocked by the inspector. The last confirmed run passed 6 of 6.
The report is saved in [artifacts/evaluation.json](artifacts/evaluation.json)
and the real command output in
[artifacts/execution_examples.txt](artifacts/execution_examples.txt).

Limits:

- the numbers are **fixed synthetic test data**, chosen by hand, in the
  range 1-100. They are not real player data and not random or exhaustive
  inputs;
- only one kind of broken engine result (a false `player_won` status) is
  injected in the evaluation. Other broken steps are covered by the unit
  tests in `tests/test_guardrails.py`;
- the scenarios test the game core, not the browser page;
- the tests and the evaluation were written with help from the same AI
  agent that helped write the code, so they may share blind spots with it;
- the 119 passing tests and the 6 passing scenarios are separate measures.
  Neither proves that the app has no bugs.

## State, data and privacy

- All game state lives in Streamlit's `st.session_state` for **one browser
  session only**. Switching pages keeps it; reloading the browser tab or
  restarting the server starts both games over.
- Nothing is saved to disk, there are no accounts, and the app collects no
  personal data.
- Vector's secret is not shown on the page until the duel ends. The old
  Developer Debug Info panel, which showed the Solo secret during the game,
  was removed.
- The logs contain only the event, the round number, the stage and the
  final status, never secrets or full states.

## Possible misuse and safeguards

| Possible misuse | What the system does | What it does not do |
|-----------------|----------------------|---------------------|
| Reading the opponent's secret | The page does not show it until the duel ends; there is no debug panel | It cannot stop someone who runs the server from reading the session state or the code |
| Predicting Vector's guesses | Nothing: the strategy is simple and documented on purpose | It does not hide or randomize the strategy |
| Bad input (empty, text, fractions, numbers out of range) | The page shows a clear message and the round is not used up | — |
| A broken or changed engine result (wrong hint, changed secret or setting, extra round, false status) | The inspector rejects it, the player sees a general message, the old state is kept | It does not protect against someone who changes both the engine and the inspector |
| Trusting Vector as "AI" | The README and this card state that Vector is a plain algorithm | — |

## Testing: what surprised me

Student reflection:

> I learned that passing unit tests does not always mean the whole app
> works correctly. I was surprised that the original 11 tests passed even
> though the New Game button was still broken.

The same thing happened later in the final project: all automated tests
passed while the new dark theme was not applied in the browser at all. It
was found only by looking at browser screenshots of the pages.

## Collaboration with AI

The project was built with Claude Code, an AI coding agent. Its actual role:

- **Planning**: helping to split the duel into small steps (bot strategy,
  duel state, paired rounds, inspector, safe service, pages, design,
  evaluation).
- **Implementation help**: writing the code for each step from the
  student's prompts, which named the files it could change and the rules it
  had to follow.
- **Tests**: writing the tests, running pytest and the git checks, and
  checking the pages with browser screenshots.
- **Documentation**: drafting the README, this model card and the AI
  interactions log.

The student decided the order of the steps and the rules for each one,
reviewed the diffs and test results, and decided when to commit.

### A suggestion I accepted

> I accepted the suggestion to add an independent guardrail checker
> because I wanted incorrect rounds to be blocked before they changed the
> game.

This became `guardrails.validate_transition` together with
`duel_service.safe_play_round`.

### A suggestion I changed

> I changed the AI's suggestion of an API-based coach into a local number
> duel because I wanted a more interesting game that works without API keys
> or external AI services.

This is why Vector is a local, deterministic algorithm and the project
needs no API keys.

## Future improvements

In the future, I would expand evaluation across all difficulties
and add randomized inputs. I would also add automated browser
checks for layout and theme rendering. Finally, I would compare
other local opponent strategies while keeping the independent
guardrails.
