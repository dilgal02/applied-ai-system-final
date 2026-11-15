# Model Card: Number Duel

| Item | Details |
|------|---------|
| System | Number Duel, a Streamlit app with a Solo Game and a Number Duel page |
| Opponent | Vector, a deterministic binary-search algorithm (`bot_agent.py`) |
| Machine learning in the game | None: Vector is a plain algorithm, and the game uses no model |
| Local model | Qwen/Qwen3-0.6B, a small pretrained language model (pinned revision `c1899de`), run on the CPU by `coach_model.py`; used by the Coach CLI, not by the game |
| Retrieval | BM25 keyword search over 22 sections of `knowledge/*.md` (`coach_retrieval.py`) |
| Strategy Coach | CLI prototype `coach.py`: question → knowledge search → local model → answer with checked source IDs (`text`) or an exact, checked quotation of one source (`quote`); not connected to the Streamlit app |
| Prompt profiles | `baseline` (default) and `specialized`, which adds three few-shot examples; prompt specialization only, no weight training |
| Not used | No training or fine-tuning, no external AI inference API, no Coach in the interface |
| Advanced feature | A built-in reliability system that checks every duel step before it is saved |
| Tested environment | Python 3.13.15, Streamlit 1.60.0; coach tools on macOS arm64 with torch 2.15.0 and transformers 5.23.0, CPU only |
| Last confirmed results | 188 automated tests passed; 6 of 6 evaluation scenarios passed |

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

The Strategy Coach prototype and its two parts, a local language model and
a knowledge search, are command-line tools described below. They are not
part of the game flow.

## No training; where a language model is used

Nothing in this project is trained or fine-tuned. Vector does not "think":
`choose_guess` returns the middle of the numbers that are still possible,
and `update_bounds` narrows that range after each hint. The same inputs
always give the same moves. The game does not use a language model.

`coach_model.py` downloads a small pretrained language model (Qwen3-0.6B)
and runs it locally on the CPU. The Coach prototype (`coach.py`) gives it
the sections found by the knowledge search. The game does not call either
of them. The project does not call any external AI inference API.

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
- the 188 passing tests and the 6 passing scenarios are separate measures.
  Neither proves that the app has no bugs.

## Local language model (separate CLI)

`coach_model.py` is the local backend of the Strategy Coach. Its
`LocalGenerator` loads the model lazily, once, and is shared by the
`smoke` check and the Coach.

- **Model:** Qwen/Qwen3-0.6B (Apache-2.0 license), a small pretrained
  model, pinned to revision `c1899de289a04d12100db370d81485cdf75e47ca`.
- **Download:** `python coach_model.py download` is the only step that
  needs the network. It saves about 1.5 GB to `models/Qwen3-0.6B`, which
  Git ignores.
- **Generation:** `python coach_model.py smoke` reads only local files and
  runs on the CPU in float32, with `model.eval()`, `torch.inference_mode()`,
  thinking turned off, greedy decoding and at most 64 new tokens by
  default.
- **Saved check:** [artifacts/local_model_smoke.json](artifacts/local_model_smoke.json),
  made with `HF_HUB_OFFLINE=1`. Asked to explain binary search, the model
  answered: "Binary search is a method of finding a target value in a
  sorted list by repeatedly dividing the search interval in half."

Limits: the model is small and can give wrong or incomplete answers. The
smoke check only shows that the model runs locally and answers in short
English; it does not check that answers are correct. Only macOS 26.6.1 on
arm64 was verified; Windows and Linux are not verified yet. The model is
used by the Coach CLI, not by the game.

## Knowledge retrieval (separate CLI)

`coach_retrieval.py` searches the game's own knowledge files:
`knowledge/rules.md`, `knowledge/strategy.md` and
`knowledge/reliability.md`, 22 sections with stable source IDs. It builds a
small BM25 index with the Python standard library and returns the best
sections with their source ID, path, score and text.

The score shows how well the words of a question match a section. It is
not the confidence of a model. Limits: the search matches words, not
meaning, so a question worded differently can miss the right section. The
knowledge files were written by hand from the current code and must be
updated when the rules change. The Coach CLI uses this search; the app
and the game engine do not.

## Strategy Coach prototype (CLI)

`coach.py` answers a question about the game: it searches the knowledge
files (up to three sections), gives the model the question with the full
text and `source_id` of each section, and asks for a short English answer
that cites sources like `[reliability-midpoint-not-required]`.

- **Citation check**: the answer must cite at least one source, and every
  cited ID must be one of the found sections. If not, the status is
  `validation_failed` and the raw answer is kept unchanged; the coach never
  adds or fixes citations. The check only covers the IDs, not whether each
  sentence is true.
- **Abstaining**: if the search finds nothing, the status is `abstained`
  and the model is not called. This refusal is a rule of the program, not
  an answer from the model.
- **Without retrieval**: `--no-retrieval` skips the search and calls the
  same model with the same instructions and settings, without sources. Its
  status is `answered_without_retrieval`.
- **Quote format**: `--answer-format quote` asks the model to pick one
  found source and return its full text as JSON. The quote is checked
  before it is accepted; see "Exact-quote answer format" below.

Three real runs are saved in [artifacts/rag_smoke.json](artifacts/rag_smoke.json),
all with `HF_HUB_OFFLINE=1`:

- with retrieval, the midpoint question found
  `reliability-midpoint-not-required` first. The answer said the inspector
  does not require the exact midpoint and cited only found sources
  (`answered`), but its last sentence starts with a contradicting "Yes";
- without retrieval, the same question got a vague answer ("the
  requirement depends on the game's specific rules") with an invented
  "[Source: Game Rules]";
- "How do I bake sourdough bread?" found no section and was refused
  (`abstained`) without calling the model.

These are three smoke runs, not an evaluation. They do not show whether
retrieval makes answers better or worse in general.

## Few-shot prompt specialization

**Method.** The coach has two prompt profiles (`coach_prompts.py`).
`baseline`, the default, gives the model the system instructions, the
current sources and the question. `specialized` gives exactly the same,
plus three short few-shot examples placed as earlier chat turns. Each
example has its own sources from the knowledge files, a question and a
short answer with a citation. The topics are setting up a new duel, the
New Duel button, and logs without secret numbers. The examples show the
wanted style: a direct answer, one useful detail, no repetition. This is
prompt specialization only: no model weights were trained or changed. The
model, system instructions, retrieval, greedy decoding and the limit of
128 new tokens are the same in both profiles.

**Keeping examples and evaluation apart.** The example questions are not
among the six evaluation questions. Citations are only allowed from the
sources found for the current question: an ID copied from an example is
rejected unless it was also found for the current question. Two example
sources, `rules-starting-a-duel` and `rules-new-duel`, were found as the
third source for two evaluation questions; there, citing them is allowed
because they are current sources.

**Comparison.** `evaluate_coach.py` uses six questions fixed before the
first run. For each question the knowledge search runs once, both profiles
get the same sources in the same order, one loaded generator is shared,
and each profile makes one greedy generation: 12 generations in total,
with `HF_HUB_OFFLINE=1`. Everything, including all raw answers and full
messages, is saved in
[artifacts/coach_specialization.json](artifacts/coach_specialization.json).

| Metric (6 questions, 1 generation each) | baseline | specialized |
|------------------------------------------|----------|-------------|
| Mean words, without citation IDs | 35.8 | 39.3 |
| Mean sentences (heuristic) | 2.0 | 2.7 |
| Answers within three sentences (heuristic) | 6 of 6 | 4 of 6 |
| Answers with at least one citation | 5 of 6 | 6 of 6 |
| Answers whose citations are all valid | 5 of 6 | 6 of 6 |
| Answers with an unknown citation | 0 | 0 |
| `validation_failed` | 1 | 0 |
| Mean generated tokens | 54.0 | 60.3 |

These metrics count the form of the answers. They are not factual
accuracy, and the sentence count is a simple heuristic.

One pair of raw answers, for "What happens if both players guess
correctly in the same round?":

> **baseline** (`validation_failed`): If both players guess correctly in
> the same round, the duel is a draw. This is determined by the rules
> provided, and no source is needed for this specific information.

> **specialized** (`answered`): If both players guess correctly in the
> same round, the duel is a draw [rules-win-and-draw]. If only you guess
> correctly, you win; if only Vector guesses correctly, Vector wins. If
> nobody guesses correctly and the round limit is reached, the duel is a
> draw [rules-win-and-draw]. If the duel is rejected, the game state does
> not change, and no round is added [reliability-rejected-round].

**What the results show.** On these six questions the specialized profile
always cited valid sources and had no `validation_failed` answer, while
the baseline gave one answer without any citation. But the specialized
answers were longer and broke the three-sentence limit twice, so the
examples did not make the answers shorter or more focused; in the pair
above, the specialized answer has four sentences and adds an unrelated one
about rejected rounds. Reading the answers by hand, not as a metric: for
"Can I submit a fractional guess, and does it use a round?" both profiles
wrongly said that a fractional guess is allowed, although the knowledge
files say it is rejected; the search ranked the right section,
`rules-valid-guesses`, only third. With one generation per profile on six
questions, these differences are too small to show a general improvement.

**Status of this comparison.** The table above was measured with the code
at commit `c8bec24`, before the retrieval fix described below. The table
and [artifacts/coach_specialization.json](artifacts/coach_specialization.json)
are kept unchanged. After the error analysis, these six questions are a
development / regression set, not an independent evaluation.

## Fractional-input retrieval fix

**Cause.** The rule is in `rules-valid-guesses`: "a fraction such as 4.5
... is rejected" and "A rejected guess does not use up a round". The
search's simple stemming kept "fractional" and "decimal" as words that
differ from "fraction", so these questions did not match the rule's key
word, and other sections ranked higher.

**Change.** `coach_retrieval.py` now maps two terms after stemming, in the
same way for questions and for the knowledge files: `fractional` →
`fraction` and `decimal` → `fraction` ("decimals" is stemmed to "decimal"
first). There are no rules for whole questions, no forced ranking of a
source and no general cutting of "-al". Prompts, few-shot examples, the
model and the generation settings did not change.

| Question | Rank of `rules-valid-guesses` before | After |
|----------|--------------------------------------|-------|
| Can I submit a fractional guess, and does it use a round? | 3 | 1 |
| Are decimal guesses allowed, and will they consume a round? | 7 | 2 |
| What happens if I enter 4.5 as my guess? | 1 | 1 |

The decimal question still ranks `rules-difficulty-limits` first, because
"allowed" also matches "allows" there; the rule is still among the three
sources the model gets.

**Real answers.** `evaluate_coach.py --suite fraction-regression` ran these
three questions with both profiles: one search per question, the same
sources for both profiles, one shared generator, the same settings, 6 real
generations with `HF_HUB_OFFLINE=1`. Everything is saved in
[artifacts/coach_fraction_regression.json](artifacts/coach_fraction_regression.json).
This is a development / regression set written after the error analysis,
not an independent evaluation.

> **Fractional, baseline** (`validation_failed`): Yes, you can submit a
> fractional guess, and it does not use a round. A fractional guess is
> allowed as long as it is a whole number within the difficulty range. A
> rejected guess does not use up a round.

> **Fractional, specialized** (`answered`): Yes, a fractional guess is
> allowed, and it does not use a round [rules-valid-guesses]. A guess must
> be a whole number inside the range of the difficulty
> [rules-difficulty-limits].

> **Decimal, baseline** (`answered`): Decimal guesses are allowed, but
> they do not consume a round. A guess must be a whole number inside the
> range of the difficulty. If a guess is invalid (e.g., decimal or outside
> the range), it is rejected. [rules-valid-guesses]

> **Decimal, specialized** (`answered`): Decimal guesses are allowed, and
> they will consume a round [rules-valid-guesses].

> **4.5, baseline** (`answered`): If you enter 4.5 as your guess, it is
> rejected because it is not a whole number within the range of the
> difficulty. [rules-valid-guesses]

> **4.5, specialized** (`answered`): If you enter 4.5 as your guess, it is
> rejected because it is outside the range of the difficulty
> [rules-valid-guesses]. A rejected guess does not use up a round
> [rules-valid-guesses].

**Manual reading of these six answers.** This is a manual check of these
specific cases against the knowledge files. It is not an automatic metric
and not a general test of truthfulness.

| Question | Profile | Says the input is rejected | Says no round is used | No claim that it is allowed | Cited source supports the answer |
|----------|---------|----------------------------|-----------------------|-----------------------------|----------------------------------|
| Fractional | baseline | No | Yes | No | No citation (`validation_failed`) |
| Fractional | specialized | No | Yes | No | No: `rules-valid-guesses` says fractions are rejected |
| Decimal | baseline | Yes | Yes | No | Partly: it supports the rejection, not "allowed" |
| Decimal | specialized | No | No (says it consumes a round) | No | No |
| 4.5 | baseline | Yes | Not mentioned | Yes | Yes |
| 4.5 | specialized | Yes, with a wrong reason ("outside the range") | Yes | Yes | Partly: it supports the rejection and the round, not the reason |

**Result.** The retrieval fix put the rule into the model's context for all
three questions, first for two of them. It did not fix the generation
error: four of the six answers still say that fractional or decimal guesses
are allowed, although the cited source says they are rejected, and none of
the six answers meets all four points. The 4.5 question already found the
rule first before the fix, so its answers do not show an effect of the
fix. Nothing here can be credited to the few-shot profile: both profiles
made the error.

## Exact-quote answer format

**Contract.** With `--answer-format quote`, the model does not write its
own answer. It selects one of the sources found for the current question
and returns only a JSON object with `source_id` and `quote`, where `quote`
is the entire text of that section. The coach checks the answer before it
accepts the quote:

1. the answer is valid JSON;
2. it has exactly the two keys `source_id` and `quote`;
3. both are strings (`null` / `null` means the model found no fitting
   source, and the status is `abstained`);
4. `source_id` is one of the sources found for this question; sources of
   the few-shot examples are not allowed automatically;
5. the quote equals the full text of that section. Only spaces and line
   breaks are normalized; no word, negation, number or punctuation mark may
   change, and a part of the section is not enough.

A wrong format, source or text gives `validation_failed`. The model's raw
answer is always kept unchanged, `accepted_quote` is only set after every
check passed, and a wrong quote is never replaced by the right one.

**Setup.** The quote format uses its own system prompt, the same for both
profiles (`coach_prompts.QUOTE_SYSTEM_PROMPT`), the same knowledge search
with three sources, the same user message format, and at most 192 new
tokens instead of 128. The model and the other settings are unchanged.
`baseline` gets the prompt and the current question. `specialized` also
gets three quote examples on the same topics as before (setting up a duel,
New Duel, logs); each answers with the JSON of its own section's full
text. The text-format examples did not change, and no example is about
fractions.

**Real run.** `evaluate_coach.py --suite fraction-regression
--answer-format quote` ran the three fractional-input questions with both
profiles: one search per question, the same sources and the same current
turn within each pair, one shared generator, 6 real generations with
`HF_HUB_OFFLINE=1`. Everything is saved in
[artifacts/coach_quote_regression.json](artifacts/coach_quote_regression.json).

| Metric (3 questions, 1 generation each) | baseline | specialized |
|------------------------------------------|----------|-------------|
| Valid JSON | 3 of 3 | 3 of 3 |
| Selected source is one of the found sources | 3 of 3 | 3 of 3 |
| Exact full quote | 1 of 3 | 3 of 3 |
| `answered` | 1 | 3 |
| `validation_failed` | 2 | 0 |
| `abstained` | 0 | 0 |
| Mean generated tokens | 55.0 | 68.0 |

One accepted quote (specialized, "Are decimal guesses allowed, and will
they consume a round?"):

> {"source_id": "rules-valid-guesses", "quote": "A guess must be a whole
> number inside the range of the difficulty. An empty guess, text, a
> fraction such as 4.5, or a number outside the range is rejected with a
> message. A rejected guess does not use up a round."}

One rejected answer (baseline, "Can I submit a fractional guess, and does
it use a round?"). It picked the right source, but wrote "does not use a
round" instead of "does not use up a round", so the quote is not the full
text of the section:

> {"source_id": "rules-valid-guesses", "quote": "A guess must be a whole
> number inside the range of the difficulty. An empty guess, text, a
> fraction such as 4.5, or a number outside the range is rejected with a
> message. A rejected guess does not use a round."}

The other rejected answer (baseline, decimal question) picked
`rules-difficulty-limits` and quoted only one of its sentences.

**Manual reading.** This is a manual check of these six cases, not an
automatic metric.

| Question | Profile | Source selected | Quote accepted | Accepted text says fractions are rejected | Accepted text says no round is used |
|----------|---------|-----------------|----------------|-------------------------------------------|-------------------------------------|
| Fractional | baseline | `rules-valid-guesses` | No (one word changed) | — | — |
| Fractional | specialized | `rules-valid-guesses` | Yes | Yes | Yes |
| Decimal | baseline | `rules-difficulty-limits` | No (only one sentence) | — | — |
| Decimal | specialized | `rules-valid-guesses` | Yes | Yes ("a fraction such as 4.5") | Yes |
| 4.5 | baseline | `rules-valid-guesses` | Yes | Yes | Yes |
| 4.5 | specialized | `rules-valid-guesses` | Yes | Yes | Yes |

**What this shows, and its limits.** All four accepted quotes are the full
`rules-valid-guesses` section, so each states that fractional input is
rejected and does not use up a round. In this run the only difference
between the two profiles was the examples, and the specialized profile got
three exact quotes against one. These are three questions with one
generation each, from a development / regression set written after the
error analysis, so the result does not generalize. It belongs to the new
quote contract; the earlier text-format comparisons stay as historical
results for their own contract.

An exact match confirms that the accepted text is the text of a found
source. It does not show that this source answers the question: had a model
quoted the full `rules-difficulty-limits` section for the decimal question,
the quote would have been accepted although it does not answer it. It also
cannot show that the knowledge files themselves are correct. And the check
is strict on purpose: the baseline's fractional answer kept the meaning but
changed one word, and it was rejected.

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
- The local model runs on the user's own machine, so prompts are not sent
  to any server. Only `coach_model.py download` contacts the Hugging Face
  Hub, to fetch the model files.

## Possible misuse and safeguards

| Possible misuse | What the system does | What it does not do |
|-----------------|----------------------|---------------------|
| Reading the opponent's secret | The page does not show it until the duel ends; there is no debug panel | It cannot stop someone who runs the server from reading the session state or the code |
| Predicting Vector's guesses | Nothing: the strategy is simple and documented on purpose | It does not hide or randomize the strategy |
| Bad input (empty, text, fractions, numbers out of range) | The page shows a clear message and the round is not used up | — |
| A broken or changed engine result (wrong hint, changed secret or setting, extra round, false status) | The inspector rejects it, the player sees a general message, the old state is kept | It does not protect against someone who changes both the engine and the inspector |
| Trusting Vector as "AI" | The README and this card state that Vector is a plain algorithm | — |
| Trusting the local model's answers | The model is not connected to the game, so it cannot change any game state; the Coach checks cited source IDs and refuses questions with no matching section | It does not check whether an answer is correct |

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
