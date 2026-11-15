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
"""
from coach_retrieval import default_index

BASELINE = "baseline"
SPECIALIZED = "specialized"
PROFILES = (BASELINE, SPECIALIZED)
DEFAULT_PROFILE = BASELINE

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


def example_messages() -> list:
    """The few-shot examples as user / assistant chat turns."""
    messages = []
    for example in FEW_SHOT_EXAMPLES:
        messages.append({
            "role": "user",
            "content": format_user_message(
                example["question"], example_sections(example)
            ),
        })
        messages.append({"role": "assistant", "content": example["answer"]})
    return messages


def check_profile(profile: str) -> str:
    if profile not in PROFILES:
        raise ValueError(
            f"Unknown profile {profile!r}; use one of: {', '.join(PROFILES)}."
        )
    return profile
