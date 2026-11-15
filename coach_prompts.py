"""Prompt profiles for the Strategy Coach.

- "baseline" (default): the system instructions, then the current sources
  and question.
- "specialized": the same, plus three short few-shot examples placed before
  the current question.

This is prompt specialization through examples. No model weights are
trained or changed: both profiles use the same model, instructions,
retrieval and generation settings. The only difference is the examples.

The examples have their own sources, taken from the knowledge files, and
questions that are not among the questions in evaluate_coach.py.

Two answer formats:
- "text" (default): a short answer with [source-id] citations.
- "quote": the model picks one found source and returns it as JSON with
  the full, word-for-word text of that section. The coach then checks the
  quote against the section before accepting it.
"""
import json

from coach_retrieval import default_index

BASELINE = "baseline"
SPECIALIZED = "specialized"
PROFILES = (BASELINE, SPECIALIZED)
DEFAULT_PROFILE = BASELINE

TEXT = "text"
QUOTE = "quote"
ANSWER_FORMATS = (TEXT, QUOTE)
DEFAULT_ANSWER_FORMAT = TEXT

# The same system prompt for both profiles in the quote format.
QUOTE_SYSTEM_PROMPT = (
    "You are the Number Duel evidence assistant. Select exactly one source "
    "that directly answers the current question. Return ONLY a JSON object "
    'with exactly two keys: "source_id" and "quote". The quote must copy '
    "the ENTIRE text of the selected source, without its heading. Preserve "
    "every word, restriction, negation, number and punctuation mark. You "
    "may replace line breaks with spaces. Do not paraphrase, explain, "
    "invent rules or add any other text. If no supplied source answers the "
    'question, return {"source_id": null, "quote": null}.'
)

# The wanted style: a direct answer, one useful detail, no repetition, at
# most three short sentences, and a citation of the example's own source.
FEW_SHOT_EXAMPLES = (
    {
        "source_ids": ("rules-starting-a-duel",),
        "question": "What do I need to do before a duel starts?",
        "answer": (
            "Choose a difficulty, enter your secret number and press Start "
            "Duel. Vector's secret number is drawn at random only at that "
            "moment [rules-starting-a-duel]."
        ),
    },
    {
        "source_ids": ("rules-new-duel",),
        "question": "Can I use New Duel in the middle of a duel?",
        "answer": (
            "Yes, New Duel works during a duel and after it ends. It clears "
            "the current duel and its history but keeps the chosen "
            "difficulty [rules-new-duel]."
        ),
    },
    {
        "source_ids": ("reliability-logs",),
        "question": "Do the game logs show my secret number?",
        "answer": (
            "No, the logs never contain secret numbers or full game states. "
            "A rejected round is logged only with its round number and its "
            "stage, engine or guardrail [reliability-logs]."
        ),
    },
)


def format_user_message(question: str, sections=None) -> str:
    """The user turn: optional sources, then the question."""
    if sections is None:
        return f"Question: {question}"
    blocks = [
        f"[{section.source_id}] {section.title}\n{section.text}"
        for section in sections
    ]
    return "Sources:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"


def example_sections(example: dict) -> list:
    """The knowledge sections that an example uses as its sources."""
    by_id = {section.source_id: section
             for section in default_index().sections}
    missing = [source_id for source_id in example["source_ids"]
               if source_id not in by_id]
    if missing:
        raise ValueError(f"Few-shot example uses unknown sources: {missing}")
    return [by_id[source_id] for source_id in example["source_ids"]]


def quote_example_answer(example: dict) -> str:
    """The JSON answer for a quote example: its source, full text.

    Built from the knowledge file, with spaces and line breaks reduced to
    single spaces, so the quote is exactly the section's text.
    """
    section = example_sections(example)[0]
    return json.dumps({
        "source_id": section.source_id,
        "quote": " ".join(section.text.split()),
    })


def example_messages(answer_format: str = DEFAULT_ANSWER_FORMAT) -> list:
    """The few-shot examples as user / assistant chat turns.

    The text format uses the short written answers. The quote format uses
    the same questions and sources, and a JSON answer with the full text.
    """
    check_answer_format(answer_format)
    messages = []
    for example in FEW_SHOT_EXAMPLES:
        messages.append({
            "role": "user",
            "content": format_user_message(
                example["question"], example_sections(example)
            ),
        })
        if answer_format == QUOTE:
            answer = quote_example_answer(example)
        else:
            answer = example["answer"]
        messages.append({"role": "assistant", "content": answer})
    return messages


def check_profile(profile: str) -> str:
    if profile not in PROFILES:
        raise ValueError(
            f"Unknown profile {profile!r}; use one of: {', '.join(PROFILES)}."
        )
    return profile


def check_answer_format(answer_format: str) -> str:
    if answer_format not in ANSWER_FORMATS:
        raise ValueError(
            f"Unknown answer format {answer_format!r}; use one of: "
            f"{', '.join(ANSWER_FORMATS)}."
        )
    return answer_format
