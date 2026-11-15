# Number Duel

Number Duel is a Streamlit app with two separate games:

- **Solo Game**: guess the hidden number before your attempts run out.
- **Number Duel**: you and the computer opponent **Vector** each pick a
  secret number and race to guess the other's number, one guess each per
  round.

Vector is a **deterministic binary-search algorithm**, not an AI model.
The advanced part of this project is a **built-in reliability system**:
every round of the duel is checked by an independent inspector before the
new game state is saved.

> **Where AI is and is not used:** the game itself uses no AI model;
> Vector is a plain algorithm. Separately, the repository has a Strategy
> Coach prototype on the command line (`coach.py`): it searches the game's
> own knowledge files with BM25 and gives the found sections to a small
> pretrained language model (Qwen3-0.6B) that runs locally on the CPU. The
> Coach is not connected to the Streamlit app or to the game engine yet.
> No external AI inference API is used, and no model was trained or
> fine-tuned. The Solo game does not go through the duel inspector.

## Contents

- [Base Project](#base-project)
- [Pages](#pages)
- [New features and fixes](#new-features-and-fixes)
- [How a duel round works](#how-a-duel-round-works)
- [Reliability system](#reliability-system)
- [Architecture](#architecture)
- [Setup](#setup)
- [Running the app, tests and evaluation](#running-the-app-tests-and-evaluation)
- [Evaluation](#evaluation)
- [Strategy Coach prototype (CLI)](#strategy-coach-prototype-cli)
- [Design decisions and trade-offs](#design-decisions-and-trade-offs)
- [Results and limits of testing](#results-and-limits-of-testing)
- [Known limitations](#known-limitations)
- [Project structure](#project-structure)
- [Documentation and AI collaboration](#documentation-and-ai-collaboration)

## Base Project

This project started from **"Game Glitch Investigator: The Impossible
Guesser"**. It was a Streamlit number guessing game that came with bugs on
purpose: the player picked a difficulty, guessed a secret number and got
"higher / lower" hints, a score and a limited number of attempts. The hints
were reversed, the secret was compared as text on every second attempt,
and the attempts counter started at the wrong number. These bugs made the
hints unreliable and the game confusing to play.

During the base project the bugs above were fixed, the game logic was
moved into `logic_utils.py` and covered with pytest tests, and the game
got Hot / Warm / Cold hints, colored hint boxes, a guess history and a
summary table. The final project builds Number Duel on top of that.

## Pages

| Page | What you do | Ranges and limits |
|------|-------------|-------------------|
| **Solo Game** | Guess the hidden number. Each guess gets a hint (higher / lower) and a closeness label: Hot (at most 5 away), Warm (at most 15 away) or Cold. The page shows the score and a guess history, and a summary table when the game ends. | Easy 1-20, 6 attempts · Normal 1-100, 8 attempts · Hard 1-50, 5 attempts |
| **Number Duel** | Pick your secret number, then play rounds against Vector. In every round you guess Vector's number and Vector guesses yours. Two cards show the last guess and hint of each side, and a table shows the whole history. | Same ranges; Easy 6, Normal 8, Hard 5 rounds |

The pages are separate: each keeps its own state, and switching between
them does not reset either game.

## New features and fixes

### New features

- **Two pages** with `st.navigation`: Solo Game and Number Duel.
- **Number Duel** against Vector, a deterministic binary-search bot
  (`bot_agent.py`, `duel_logic.py`).
- **Reliability system**: an independent inspector
  (`guardrails.py`) checks every duel step, and a safe service
  (`duel_service.py`) accepts a round only after the check passes.
- **Logging** of accepted and rejected rounds, without secrets.
- **Reproducible evaluation script** (`evaluate.py`) with six fixed
  scenarios and a JSON report.
- **Dark arena theme** shared by both pages (`.streamlit/config.toml`,
  `ui_style.py`).
- **New Duel** is available during a duel and after it ends.

### Fixes to the Solo game

- New Game now resets the status, score and history. Before, it kept
  saying "You already won".
- New Game picks the secret from the selected difficulty's range instead
  of always 1-100.
- The prompt shows the selected range instead of a fixed "1 and 100".
- Changing the difficulty starts a new game.
- Empty or non-numeric input no longer uses up an attempt.
- The Developer Debug Info panel was removed, because it showed the
  secret during the game.
- Switching to Number Duel and back keeps the solo game and its
  difficulty.

## How a duel round works

1. **Start**: you choose a difficulty and enter your secret number.
   Vector's secret is drawn with `random.randint` only at this moment.
2. **Your move**: your guess is compared with Vector's secret
   (Too Low, Too High or Win).
3. **Vector's move**: Vector always guesses the middle of the numbers that
   are still possible (`choose_guess`). Its guess is compared with your
   secret, and its search range is narrowed (`update_bounds`). The bot
   functions only receive the range bounds and the hint, never your secret
   number.
4. **Result**, decided after both moves:
   both guessed right → draw; only you → you win; only Vector → Vector
   wins; nobody, but the round limit is reached → draw; otherwise the duel
   goes on.

Vector's number is shown only after the duel ends.

## Reliability system

Every duel round goes through `duel_service.safe_play_round`:

1. The engine (`duel_logic.play_round`) builds a **candidate** state. The
   game state is immutable (frozen dataclasses), so the old state is never
   changed.
2. The inspector (`guardrails.validate_transition`) checks the step from
   the old state to the candidate.
3. Only if the check passes is the candidate returned. The duel page then
   saves it as `duel_state`.

The inspector does **not** call the game functions (`check_guess`,
`play_round`, `choose_guess`, `update_bounds`). It works everything out
again with its own number comparisons:

- **Structure**: correct types, the duel was still running and had
  attempts left, settings and secrets kept their value and type, exactly
  one new round, earlier rounds unchanged.
- **Guesses and hints**: both guesses are whole numbers inside the range,
  and both hints match the secrets.
- **Vector's range**: it is rebuilt from the whole history and must match
  the stored range before and after the round; every Vector guess must lie
  inside the range it had at that time.
- **Result**: the status is worked out again from the history, and no round
  may follow a round that ended the duel.

When a round is rejected:

- bad input (empty, text, fractions, out of range) is caught by the duel
  page itself, gets a clear message and does not use up a round;
- an engine error (`ValueError`) is passed on unchanged by the service,
  and the page shows its message;
- the inspector raises a `ValueError` when a rule is broken. The service
  turns it into a `GuardrailViolation`, and the page shows only a general
  message, never the inner reason;
- the log shows `duel_round_rejected` with `stage=engine` or
  `stage=guardrail`, and the old `duel_state` stays as it was.

## Architecture

| Module | Role |
|--------|------|
| `app.py` | Page config and navigation between the two pages |
| `pages/solo.py` | Solo Game page |
| `pages/duel.py` | Number Duel page (setup, rounds, result, New Duel) |
| `ui_style.py` | Shared dark arena styles and the duel player cards |
| `logic_utils.py` | Solo rules: input parsing, hints, closeness, score |
| `bot_agent.py` | Vector's strategy: `choose_guess`, `update_bounds` |
| `duel_logic.py` | Duel state (`DuelState`, `DuelRound`), `create_duel`, `play_round` |
| `guardrails.py` | Independent inspector `validate_transition` |
| `duel_service.py` | `safe_play_round`, `GuardrailViolation`, logging |
| `evaluate.py` | Reproducible evaluation of six duel scenarios |
| `coach_model.py` | Local model: download the pinned Qwen3-0.6B, `LocalGenerator` for CPU generation, `smoke` check |
| `coach_retrieval.py` | BM25 search over `knowledge/*.md` |
| `coach.py` | Strategy Coach CLI prototype: search → local model → answer with source IDs |
| `coach_prompts.py` | Prompt profiles: `baseline` and `specialized` (three few-shot examples) |
| `evaluate_coach.py` | Compares both prompt profiles on six fixed questions |
| `knowledge/*.md` | The game's own knowledge files, 22 sections with stable IDs |

Mermaid source: [diagrams/architecture.mmd](diagrams/architecture.mmd)

```mermaid
flowchart TD
    %% Number Duel: architecture of the actual implementation.
    %% README.md shows the same diagram so GitHub can render it.
    %% coach.py connects the knowledge search to the local model on the
    %% command line. The coach is not connected to the Streamlit app or to
    %% the game engine yet.

    player(["Player<br/>(web browser)"])
    app["app.py<br/>set_page_config + st.navigation"]

    subgraph pages["Streamlit pages"]
        solo["pages/solo.py<br/>Solo Game"]
        duel["pages/duel.py<br/>Number Duel"]
    end

    subgraph session["st.session_state (one browser session)"]
        solo_state[("Solo keys<br/>secret, attempts, score,<br/>status, history, rounds")]
        duel_state[("duel_state<br/>frozen DuelState")]
    end

    subgraph core["Game core (plain Python, no Streamlit)"]
        logic["logic_utils.py<br/>parse_guess, check_guess,<br/>get_closeness, update_score"]
        service["duel_service.safe_play_round<br/>logs accepted / rejected rounds"]
        engine["duel_logic.py (engine)<br/>create_duel, play_round"]
        bot["bot_agent.py<br/>choose_guess, update_bounds"]
        inspector["guardrails.validate_transition<br/>(independent checks)"]
    end

    rejected["Round not accepted<br/>message on the page;<br/>old duel_state kept"]

    player --> app
    app --> solo
    app --> duel

    solo --> logic
    solo <--> solo_state

    duel -->|"Start Duel: create_duel"| engine
    duel -->|"empty, text, fraction<br/>or out of range"| rejected
    duel -->|"valid whole number"| service
    service -->|"1. play_round"| engine
    engine -->|"check_guess for hints"| logic
    engine -->|"bounds and outcome,<br/>no secret number"| bot
    bot -->|"next guess, new bounds"| engine
    engine -->|"candidate DuelState,<br/>or ValueError for bad input"| service
    service -->|"2. validate_transition<br/>(old state, candidate)"| inspector
    inspector -->|"ValueError if a rule is broken"| service
    service -->|"accepted: candidate"| duel
    service -->|"engine ValueError passed on;<br/>inspector ValueError becomes<br/>GuardrailViolation"| duel
    duel -->|"save"| duel_state
    duel -->|"GuardrailViolation: general message;<br/>engine ValueError: its message"| rejected

    subgraph evaluation["Evaluation (no Streamlit, no server)"]
        evaluate["evaluate.py<br/>6 fixed scenarios"]
        report[("artifacts/evaluation.json")]
        fault["mock.patch fault injection<br/>(evaluation only)"]
    end

    evaluate -->|"safe_play_round"| service
    evaluate -->|"create_duel; play_round<br/>to build the injected fault"| engine
    evaluate --> report
    fault -.->|"replaces play_round<br/>in guardrail-blocked"| service

    subgraph model_tool["Local model (coach_model.py)"]
        download_cmd["coach_model.py download"]
        hub[("Hugging Face Hub<br/>Qwen/Qwen3-0.6B<br/>pinned revision c1899de")]
        weights[("models/Qwen3-0.6B<br/>local weights, git-ignored")]
        smoke_cmd["coach_model.py smoke<br/>one fixed prompt"]
        generator["LocalGenerator<br/>Transformers + PyTorch on CPU,<br/>loaded lazily once, thinking off,<br/>greedy, token limit"]
        smoke_out["smoke answer and checks<br/>+ optional JSON report"]
    end

    download_cmd -->|"network needed only here"| hub
    hub -->|"snapshot_download"| weights
    weights -->|"local files only, no network"| generator
    smoke_cmd -->|"generate"| generator
    generator -->|"text, token counts"| smoke_cmd
    smoke_cmd --> smoke_out

    subgraph retrieval_tool["Knowledge search (coach_retrieval.py)"]
        knowledge[("knowledge/*.md<br/>rules, strategy, reliability<br/>22 sections with source_id")]
        bm25["BM25 index<br/>(Python standard library)<br/>term aliases: fractional,<br/>decimal → fraction"]
        query_cmd["coach_retrieval.py<br/>--query --top-k"]
        found["found sections:<br/>source_id, path, score, text<br/>score = word match,<br/>not model confidence"]
    end

    knowledge -->|"one entry per section"| bm25
    query_cmd -->|"search"| bm25
    bm25 --> found

    subgraph coach_tool["RAG Coach CLI prototype (coach.py), not in the app"]
        coach_cli["coach.py --question<br/>ask_coach(), --profile"]
        prompts["coach_prompts.py<br/>baseline (default) or<br/>specialized = + 3 few-shot examples"]
        abstain["abstained: no section found<br/>program rule, model not called"]
        citation_check["citation check: at least one<br/>[source_id], all IDs from the<br/>sources of this question (IDs only)"]
        coach_out["answer, sources, status<br/>+ optional JSON report"]
        eval_coach["evaluate_coach.py --suite<br/>fixed questions x 2 profiles"]
        spec_report[("artifacts/coach_specialization.json<br/>coach_fraction_regression.json")]
    end

    coach_cli -->|"1. search, top 3"| bm25
    bm25 -->|"sections: source_id,<br/>text, score"| coach_cli
    coach_cli -->|"no section found"| abstain
    coach_cli -->|"build messages<br/>for the profile"| prompts
    prompts -->|"example sections by ID"| bm25
    coach_cli -->|"2. messages: question + found sections<br/>(--no-retrieval: question only)"| generator
    generator -->|"raw answer"| coach_cli
    coach_cli -->|"with retrieval"| citation_check
    citation_check -->|"answered or<br/>validation_failed"| coach_out
    coach_cli -->|"--no-retrieval:<br/>answer without retrieval"| coach_out
    abstain --> coach_out
    eval_coach -->|"one search per question"| bm25
    eval_coach -->|"ask_coach for each profile,<br/>same sources, one generator"| coach_cli
    eval_coach --> spec_report

    tests["tests/ (pytest)"]
    tests -.->|"unit tests"| core
    tests -.->|"AppTest UI tests"| pages
    tests -.->|"CLI test"| evaluate
    tests -.->|"unit tests,<br/>no real model"| model_tool
    tests -.->|"unit and CLI tests"| retrieval_tool
    tests -.->|"unit tests,<br/>generation replaced"| coach_tool
```

## Setup

Requirements: Python 3 and the packages in
[requirements.txt](requirements.txt) (`streamlit>=1.36.0`, `altair<5`,
`pytest`).

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Tested environment:** Python 3.13.15 and Streamlit 1.60.0.

## Running the app, tests and evaluation

```bash
# The app (opens at http://localhost:8501)
python -m streamlit run app.py

# All automated tests
python -m pytest -q

# All six evaluation scenarios
python evaluate.py

# One scenario
python evaluate.py --case guardrail-blocked

# All scenarios, plus a JSON report
python evaluate.py --output artifacts/evaluation.json
```

`evaluate.py` exits with code 0 when every selected scenario passed and 1
when any scenario failed.

## Evaluation

`evaluate.py` runs fixed scenarios through the real `create_duel` and
`safe_play_round`, without Streamlit or a server. All numbers are **fixed
synthetic test data** in the range 1-100. The report has no times or random
values, so every run gives the same report.

| Scenario | Your secret | Vector's secret | Round limit | Your guesses | Expected |
|----------|-------------|-----------------|-------------|--------------|----------|
| `player-win` | 63 | 27 | 8 | 40, 27 | `player_won` |
| `bot-win` | 50 | 27 | 8 | 40 | `bot_won` |
| `simultaneous-win` | 50 | 27 | 8 | 27 | `draw` |
| `limit-draw` | 63 | 27 | 1 | 40 | `draw` |
| `invalid-input` | 63 | 27 | 8 | 101 | engine `ValueError`, state unchanged |
| `guardrail-blocked` | 63 | 27 | 8 | 40 | `GuardrailViolation`, state unchanged |

In `guardrail-blocked`, the script builds a correct result for guess 40,
changes its status to `player_won`, and uses a temporary `mock.patch` so
that the engine returns this wrong result. The real inspector stays on.
This fault injection exists only in the evaluation; the app has no such
switch.

A **trace** shows what the algorithm actually did in each accepted round:
both guesses, both hints, Vector's range before and after, and the
guardrail decision. It is a record of a deterministic algorithm, not hidden
reasoning of a language model.

The examples below are copied from the saved real runs in
[artifacts/execution_examples.txt](artifacts/execution_examples.txt). The
full JSON report is in
[artifacts/evaluation.json](artifacts/evaluation.json).

### Example: player-win

```text
$ .venv/bin/python evaluate.py --case player-win
Number Duel evaluation
Note: All numbers are fixed synthetic test data (range 1-100).
Note: Traces show observed moves of the deterministic binary-search bot and guardrail decisions, not hidden reasoning of a language model.

[1/1] player-win
  input:    player_secret=63, bot_secret=27, attempt_limit=8, guesses=[40, 27]
  expected: status='player_won'
  log:      INFO duel_service duel_round_accepted round=1 status=playing
  log:      INFO duel_service duel_round_accepted round=2 status=player_won
  trace:
    round 1: you 40 -> Too High | Vector 50 -> Too Low | bot range 1-100 -> 51-100 | guardrail: accepted | status: playing
    round 2: you 27 -> Win | Vector 75 -> Too High | bot range 51-100 -> 51-74 | guardrail: accepted | status: player_won
  actual:   status='player_won', rounds=2
  check:    [ok] status is player_won
  check:    [ok] one accepted round per guess
  result:   PASS

passed: 1  failed: 0  total: 1
[exit code: 0]
```

### Example: simultaneous-win

```text
$ .venv/bin/python evaluate.py --case simultaneous-win
Number Duel evaluation
Note: All numbers are fixed synthetic test data (range 1-100).
Note: Traces show observed moves of the deterministic binary-search bot and guardrail decisions, not hidden reasoning of a language model.

[1/1] simultaneous-win
  input:    player_secret=50, bot_secret=27, attempt_limit=8, guesses=[27]
  expected: status='draw'
  log:      INFO duel_service duel_round_accepted round=1 status=draw
  trace:
    round 1: you 27 -> Win | Vector 50 -> Win | bot range 1-100 -> 50-50 | guardrail: accepted | status: draw
  actual:   status='draw', rounds=1
  check:    [ok] status is draw
  check:    [ok] one accepted round per guess
  result:   PASS

passed: 1  failed: 0  total: 1
[exit code: 0]
```

### Example: guardrail-blocked

```text
$ .venv/bin/python evaluate.py --case guardrail-blocked
Number Duel evaluation
Note: All numbers are fixed synthetic test data (range 1-100).
Note: Traces show observed moves of the deterministic binary-search bot and guardrail decisions, not hidden reasoning of a language model.

[1/1] guardrail-blocked
  input:    player_secret=63, bot_secret=27, attempt_limit=8, guess=40, fake_status='player_won'
  expected: exception='GuardrailViolation', state_unchanged=True, rounds=0
  log:      WARNING duel_service duel_round_rejected round=1 stage=guardrail
  actual:   exception='GuardrailViolation', message='The game produced an invalid round, so it was not accepted.', inspector_reason="after.status is 'player_won', expected 'playing'.", engine_calls=1, state_unchanged=True, rounds=0, patch_removed=True
  check:    [ok] GuardrailViolation raised
  check:    [ok] real inspector gave the reason
  check:    [ok] patched engine was called once
  check:    [ok] state unchanged
  check:    [ok] no round added
  check:    [ok] patch removed after the case
  result:   PASS

passed: 1  failed: 0  total: 1
[exit code: 0]
```

## Strategy Coach prototype (CLI)

The Strategy Coach answers questions about the game on the command line.
It is a working prototype: question → knowledge search → local model →
answer with source IDs. It does not change the game, the game does not
need it, and it is not connected to the Streamlit app yet. There is no
match analysis yet. The prompt has two profiles: `baseline` (default) and
`specialized`, which adds few-shot examples.

**Coach (`coach.py`)**

- `ask_coach()` is the function for callers; the CLI uses it, and the app
  could call it later.
- **With retrieval** (default): it finds up to three sections and gives
  the model the question together with the full text and `source_id` of
  each section. It asks for a short English answer that cites sources like
  `[reliability-midpoint-not-required]`. The answer must cite at least one
  source, and every cited ID must be one of the found sections; otherwise
  the status is `validation_failed` and the raw answer is kept unchanged.
  This check only covers the IDs, not whether each sentence is true.
- **No match**: if the search finds nothing, the status is `abstained` and
  the model is not called. This refusal is a rule of the program, not an
  answer from the model.
- **`--no-retrieval`** (model only): skips the search and the knowledge
  files, but calls the same model with the same instructions and settings.
  Only the found sources are missing, so a missing citation is not an
  error; the status is `answered_without_retrieval`.
- The real runs are saved in [artifacts/rag_smoke.json](artifacts/rag_smoke.json):
  for the midpoint question, the answer with retrieval cited only found
  sections (status `answered`), but its last sentence starts with a
  contradicting "Yes". Without retrieval, the answer was vague and cited an
  invented "[Source: Game Rules]". The bread question was refused
  (`abstained`). These three runs are smoke checks, not an evaluation.
- **Prompt profiles**: `--profile baseline` (default) or
  `--profile specialized`, which puts three short few-shot examples
  (`coach_prompts.py`) before the question. This is prompt specialization
  only; no weights are trained, and everything else stays the same. The
  specialized profile only works with retrieval, and citations are only
  allowed from the sources found for the current question.
- **Profile comparison**: `evaluate_coach.py` ran both profiles on six
  fixed questions (12 real generations, saved in
  [artifacts/coach_specialization.json](artifacts/coach_specialization.json)).
  The specialized profile had no `validation_failed` answer (baseline: 1)
  and always cited valid sources, but its answers were longer and broke the
  three-sentence limit twice. Both profiles answered the fractional-guess
  question wrongly. This does not show a general improvement; details are
  in the [model card](model_card.md#few-shot-prompt-specialization). This
  comparison belongs to the code at commit `c8bec24` and is kept
  unchanged; after the error analysis, its questions are a development /
  regression set, not an independent evaluation.
- **Fractional-input fix**: the search did not connect "fractional" and
  "decimal" with "fraction", so the rule `rules-valid-guesses` ranked 3rd
  and 7th. Two term aliases after stemming (`fractional`, `decimal` →
  `fraction`) now rank it 1st and 2nd. A regression run of three
  fractional-input questions (6 real generations,
  [artifacts/coach_fraction_regression.json](artifacts/coach_fraction_regression.json))
  shows that the model still makes the error: four of six answers say such
  guesses are allowed, although the cited source says they are rejected.
  The fix improved the search, not the answers, and nothing here is credited
  to the few-shot profile; see the
  [model card](model_card.md#fractional-input-retrieval-fix).

**Local model (`coach_model.py`)**

- Model: [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B), a
  small pretrained language model (Apache-2.0 license), pinned to revision
  `c1899de289a04d12100db370d81485cdf75e47ca`. It was not trained or
  fine-tuned in this project.
- `download` is the only command that uses the network. It saves the model
  (about 1.5 GB) to `models/Qwen3-0.6B`, which Git ignores.
- `LocalGenerator` (shared through `get_generator()`) loads the model
  lazily, once, reads only local files and generates on the CPU with
  Transformers and PyTorch: `model.eval()`, `torch.inference_mode()`,
  thinking turned off and greedy decoding. It never downloads or prints
  anything. Importing the module does not import torch.
- `smoke` uses the same generator for one short answer (at most 64 new
  tokens by default) and can save a JSON report with `--output`. The coach
  uses at most 128 new tokens.
- If the dependencies or the model are missing, both commands print what
  to install or run.
- The saved check [artifacts/local_model_smoke.json](artifacts/local_model_smoke.json)
  was made with `HF_HUB_OFFLINE=1`. The model answered: "Binary search is a
  method of finding a target value in a sorted list by repeatedly dividing
  the search interval in half."

**Knowledge search (`coach_retrieval.py`)**

- Splits `knowledge/rules.md`, `knowledge/strategy.md` and
  `knowledge/reliability.md` into 22 sections, each with a stable
  `source_id` such as `rules-win-and-draw`.
- Builds its own BM25 index with the Python standard library and prints
  the best sections with their source ID, path, score and text.
- The score shows how well the words of the query match a section. It is
  not the confidence of a model.

```bash
# Optional coach dependencies (the game does not need them)
python -m pip install -r requirements-coach.txt

# Download the pinned model once (network needed)
python coach_model.py download

# Local CPU check (reads only local files)
python coach_model.py smoke

# Search the game's knowledge files
python coach_retrieval.py --query "What happens if both players guess correctly?" --top-k 3

# Ask the coach (search + local model)
python coach.py --question "Must the inspector require Vector to guess the exact midpoint?"

# The same question without retrieval (model only)
python coach.py --question "Must the inspector require Vector to guess the exact midpoint?" --no-retrieval

# The specialized prompt profile (few-shot examples, with retrieval)
python coach.py --question "Must the inspector require Vector to guess the exact midpoint?" --profile specialized

# Compare both prompt profiles on six fixed questions (12 generations)
python evaluate_coach.py --output artifacts/coach_specialization.json

# Regression set for fractional input (3 questions, 6 generations)
python evaluate_coach.py --suite fraction-regression --output artifacts/coach_fraction_regression.json
```

The coach tools were checked only on macOS 26.6.1 (arm64) with Python
3.13.15, torch 2.15.0 and transformers 5.23.0, on the CPU. Windows and
Linux are not verified yet.

## Design decisions and trade-offs

- **A deterministic bot instead of an AI service.** Vector works without
  API keys or a network, and every run is reproducible and testable. The
  trade-off is that Vector is fully predictable.
- **An inspector that does not trust the engine.** The inspector works out
  hints, ranges and the result on its own, so an engine bug cannot hide
  behind the engine's own functions. The trade-off is that the game rules
  exist twice and must be kept in sync.
- **Immutable state and "check before save".** Each round makes a new
  `DuelState`, so the old state can always be compared with the candidate
  and stays intact when a round is rejected.
- **A general error message for the player.** The player never sees the
  inspector's inner reason. Developers can still find it in the exception's
  cause and in the log stage.
- **Separate input rules per game.** The duel accepts only whole numbers
  and rejects fractions. The Solo game keeps the base project's
  `parse_guess`, which cuts a decimal like 3.7 down to 3.
- **Theme applied in each page.** Streamlit 1.60 removes `<style>` from
  `st.markdown`, and elements drawn by `app.py` only stay on the default
  page. So each page calls `apply_theme()`, which uses `st.html`. The CSS
  uses Streamlit's `data-testid` attributes, which can change between
  versions.
- **A pinned model that runs locally.** The exact model revision is fixed,
  so everyone downloads the same files, and generation never uses the
  network. The trade-off is about 1.5 GB of weights and slower answers on
  the CPU.
- **Keyword search without extra libraries.** BM25 with the standard
  library is easy to test and explain. The trade-off is that it matches
  words, not meaning, so a question worded differently can miss the right
  section.
- **The coach refuses instead of guessing.** With no matching section,
  the model is not called at all. The trade-off is that a question worded
  differently from the knowledge files can be refused.
- **Checked citations, kept answers.** The coach checks the cited source
  IDs and keeps the model's answer unchanged, even when the check fails.
  It never adds or fixes citations itself.

## Results and limits of testing

Last confirmed results, on Python 3.13.15 with Streamlit 1.60.0:

- **171 automated tests passed** (`python -m pytest -q`);
- **6 of 6 evaluation scenarios passed** (`python evaluate.py`).

These are two different measures, and neither is a guarantee that the app
has no bugs.

What the tests cover:

- unit tests for every game module, including negative tests that check
  each inspector rule rejects a broken step for the right reason;
- the safe service and its logs;
- the pages through Streamlit's `AppTest`: page switching keeps both
  games, bad input does not use up a round, a broken engine result is
  blocked without an error in the page, Vector's secret is not shown during
  the duel, and New Duel does not change the Solo game;
- the evaluation script through a real command-line run, including a
  check that two runs give the same JSON;
- the coach tools: messages for missing dependencies or a missing model,
  the pinned model revision, the knowledge search (expected sources,
  empty and unrelated queries, `top_k`, stable order, duplicate IDs, the
  fractional-input term aliases), and
  the coach (found texts and IDs reach the model, unknown or missing
  citations are blocked, no match does not call the model, the
  `--no-retrieval` mode skips the search), and the prompt profiles
  (baseline is the default, specialized only adds the examples, both get
  the same current sources, a citation copied from an example is
  rejected). These tests replace the model with a fake and never load the
  real one.

Limits of this testing:

- the evaluation uses six fixed, hand-picked scenarios, not random or
  exhaustive data;
- `AppTest` does not render a real browser. The look of the pages was
  checked with browser screenshots during development; there are no
  automated visual tests;
- only Python 3.13.15 and Streamlit 1.60.0 were tested. Streamlit 1.36 is
  the declared minimum, but it was not tested;
- the real local model is checked only by `coach_model.py smoke`,
  `coach.py` and `evaluate_coach.py` runs, which are not part of pytest.
  The profile comparison has only six questions and one generation per
  profile;
- there are no load or multi-user tests.

## Known limitations

- **Vector is predictable.** Anyone who knows binary search knows its next
  guess. On Easy and Normal it always finds your number within the round
  limit (at most 5 and 7 guesses); on Hard it needs up to 6 guesses but
  has only 5 rounds, so it cannot find 19 of the 50 possible numbers in
  time.
- **The inspector checks that Vector's guess is inside its range**, not that
  it is exactly the middle.
- **State lives only in the current browser session.** Reloading the
  browser tab or restarting the server starts both games over; nothing is
  saved to disk.
- **The engine knows both secrets** to decide the hints. Vector's strategy
  functions do not get your secret, but anyone who runs the server can read
  the session state or change the code. There is no protection against
  cheating by whoever controls the server.
- **Solo is not inspected.** Only duel rounds go through the inspector.
- **Solo scoring keeps a rule from the base project:** a "Too High" guess
  on an even attempt adds 5 points instead of taking 5 away.
- **The Coach is a command-line prototype.** The app and the game engine
  do not use it, and there is no Coach in the interface yet.
- **The local model is small.** Qwen3-0.6B can give wrong or incomplete
  answers, even with retrieval: in the saved run, the answer cited valid
  sources but also contained a contradicting sentence. The smoke check only
  shows that the model runs locally and gives a short English answer.
- **The citation check covers IDs only.** A cited ID must be one of the
  found sections, but the check cannot tell whether a sentence is true.
- **The knowledge search matches words, not meaning.**

## Project structure

```text
app.py                 navigation and page config
pages/solo.py          Solo Game page
pages/duel.py          Number Duel page
ui_style.py            shared styles and duel player cards
logic_utils.py         Solo game rules
bot_agent.py           Vector's binary-search strategy
duel_logic.py          duel state, create_duel, play_round
guardrails.py          independent inspector validate_transition
duel_service.py        safe_play_round, GuardrailViolation, logging
evaluate.py            reproducible evaluation script
coach.py               Strategy Coach CLI prototype (search + local model)
coach_model.py         local model: download, LocalGenerator, smoke check
coach_retrieval.py     BM25 search over the knowledge files
coach_prompts.py       prompt profiles and few-shot examples
evaluate_coach.py      comparison of the two prompt profiles
knowledge/             the game's knowledge files (22 sections)
requirements-coach.txt optional dependencies for the coach tools
models/                downloaded model weights (git-ignored)
tests/                 pytest tests (unit, AppTest UI, CLI)
artifacts/             saved evaluation report and real command output
diagrams/              Mermaid architecture source
assets/                folder kept for project images
.streamlit/config.toml dark theme
```

## Documentation and AI collaboration

- [model_card.md](model_card.md): how the system works, its limits,
  testing and the role of AI in building it.
- [ai_interactions.md](ai_interactions.md): decisions made while working
  with the AI agent, the observed `player-win` trace and the blocked
  example, plus the base project's history.
- [reflection.md](reflection.md): reflection from the base project.
