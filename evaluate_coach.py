"""Compare the baseline and the specialized (few-shot) coach prompts.

    python evaluate_coach.py --output artifacts/coach_specialization.json
    python evaluate_coach.py --suite fraction-regression \\
        --output artifacts/coach_fraction_regression.json
    python evaluate_coach.py --suite fraction-regression \\
        --answer-format quote --output artifacts/coach_quote_regression.json

Suites: "specialization" (default, six questions) and "fraction-regression"
(three questions about fractional input). After the error analysis both are
development / regression sets, not independent evaluations.

For each fixed question of a suite, the knowledge search runs once.
Both profiles get the same sources in the same order and use one shared,
loaded generator, with one generation each: 12 real generations. No answer
is picked from several tries, and greedy decoding is used.

The metrics are automatic counts of form, not of truth: words without
citation IDs, sentences (a simple heuristic that splits on . ! and ?), the
three-sentence limit, citations and their validity, and validation_failed.
They do not measure factual accuracy.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import coach
import coach_model
import coach_retrieval
from coach_prompts import (
    ANSWER_FORMATS,
    BASELINE,
    DEFAULT_ANSWER_FORMAT,
    FEW_SHOT_EXAMPLES,
    PROFILES,
    QUOTE,
    QUOTE_SYSTEM_PROMPT,
    SPECIALIZED,
    example_messages,
    quote_example_answer,
)

# Fixed before the first real run; not changed after seeing results.
QUESTIONS = (
    "What happens if both players guess correctly in the same round?",
    "What number range and round limit does Hard difficulty use?",
    "Does choose_guess receive the player secret number?",
    "Must the inspector require Vector to guess the exact midpoint?",
    "Does the Solo game pass through the duel inspector?",
    "Can I submit a fractional guess, and does it use a round?",
)

# Added after the error analysis of the question above.
FRACTION_REGRESSION_QUESTIONS = (
    "Can I submit a fractional guess, and does it use a round?",
    "Are decimal guesses allowed, and will they consume a round?",
    "What happens if I enter 4.5 as my guess?",
)

DEFAULT_SUITE = "specialization"
SUITES = {
    "specialization": QUESTIONS,
    "fraction-regression": FRACTION_REGRESSION_QUESTIONS,
}
SUITE_NOTES = {
    "specialization": (
        "These questions were fixed before the first run (commit c8bec24). "
        "After the error analysis that followed, they are a development / "
        "regression set, not an independent evaluation."
    ),
    "fraction-regression": (
        "Development / regression set, written after the error analysis of "
        "the fractional-guess answer. It is not an independent evaluation."
    ),
}

WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def without_citations(answer: str) -> str:
    return coach.CITATION.sub(" ", answer or "")


def count_words(answer: str) -> int:
    """Words in the answer, not counting the [citation-id] parts."""
    return len(WORD.findall(without_citations(answer)))


def count_sentences(answer: str) -> int:
    """Heuristic: split on . ! ? followed by space; keep parts with letters.

    Abbreviations or decimal numbers can make this count wrong.
    """
    text = " ".join(without_citations(answer).split())
    if not text:
        return 0
    return sum(1 for part in SENTENCE_END.split(text)
               if any(char.isalpha() for char in part))


def quote_metrics(result) -> dict:
    """Metrics for the quote format, read from the coach's own checks."""
    passed = {item["key"]: item["passed"] for item in result.checks
              if "key" in item}
    return {
        "valid_json": passed.get("valid_json", False),
        "selected_source_id": (result.citations[0]
                               if result.citations else None),
        "allowed_source": passed.get("allowed_source", False),
        "exact_full_quote": passed.get("exact_full_quote", False),
        "status": result.status,
        "generated_tokens": (result.generation or {}).get(
            "generated_tokens"
        ),
    }


def answer_metrics(result) -> dict:
    if result.answer_format == QUOTE:
        return quote_metrics(result)
    allowed = {source["source_id"] for source in result.sources}
    unknown = [citation for citation in result.citations
               if citation not in allowed]
    sentences = count_sentences(result.answer)
    return {
        "words_without_citations": count_words(result.answer),
        "sentences_heuristic": sentences,
        "within_three_sentences": sentences <= 3,
        "has_citation": bool(result.citations),
        "all_citations_valid": bool(result.citations) and not unknown,
        "unknown_citations": unknown,
        "validation_failed": result.status == coach.VALIDATION_FAILED,
        "generated_tokens": (result.generation or {}).get(
            "generated_tokens"
        ),
    }


class CountingGenerator:
    """Passes calls to the real generator and counts them."""

    def __init__(self, generator):
        self.generator = generator
        self.calls = 0

    def generate(self, messages, max_new_tokens):
        self.calls += 1
        return self.generator.generate(messages, max_new_tokens)

    def environment(self):
        environment = getattr(self.generator, "environment", None)
        return environment() if callable(environment) else None


def summarize(rows: list, profile: str,
              answer_format: str = DEFAULT_ANSWER_FORMAT) -> dict:
    metrics = [row["runs"][profile]["metrics"] for row in rows
               if row["runs"][profile]["generator_called"]]
    count = len(metrics)

    def mean(key):
        values = [m[key] for m in metrics if m[key] is not None]
        return round(sum(values) / len(values), 1) if values else None

    if answer_format == QUOTE:
        return {
            "answers": count,
            "valid_json": sum(m["valid_json"] for m in metrics),
            "allowed_source": sum(m["allowed_source"] for m in metrics),
            "exact_full_quote": sum(m["exact_full_quote"] for m in metrics),
            "answered": sum(m["status"] == coach.ANSWERED for m in metrics),
            "validation_failed": sum(m["status"] == coach.VALIDATION_FAILED
                                     for m in metrics),
            "abstained": sum(m["status"] == coach.ABSTAINED
                             for m in metrics),
            "mean_generated_tokens": mean("generated_tokens"),
        }
    return {
        "answers": count,
        "mean_words_without_citations": mean("words_without_citations"),
        "mean_sentences_heuristic": mean("sentences_heuristic"),
        "within_three_sentences": sum(m["within_three_sentences"]
                                      for m in metrics),
        "with_citation": sum(m["has_citation"] for m in metrics),
        "all_citations_valid": sum(m["all_citations_valid"]
                                   for m in metrics),
        "with_unknown_citation": sum(bool(m["unknown_citations"])
                                     for m in metrics),
        "validation_failed": sum(m["validation_failed"] for m in metrics),
        "mean_generated_tokens": mean("generated_tokens"),
    }


def run_comparison(questions=QUESTIONS, *, generator=None,
                   search=None, suite=DEFAULT_SUITE,
                   answer_format=DEFAULT_ANSWER_FORMAT) -> dict:
    """Run both profiles on every question and collect the results."""
    search = search or coach_retrieval.search
    counting = CountingGenerator(generator or coach_model.get_generator())
    search_calls = 0
    rows = []
    for question in questions:
        # One search per question; both profiles get exactly these results.
        results = list(search(question, coach.TOP_K))
        search_calls += 1

        def frozen_search(_question, _top_k, results=results):
            return results

        runs = {}
        for profile in PROFILES:
            result = coach.ask_coach(
                question, profile=profile, answer_format=answer_format,
                generator=counting, search=frozen_search,
            )
            runs[profile] = {**result.to_dict(),
                             "metrics": answer_metrics(result)}
        baseline, specialized = runs[BASELINE], runs[SPECIALIZED]
        rows.append({
            "question": question,
            "sources": baseline["sources"],
            "same_sources_for_both_profiles":
                baseline["sources"] == specialized["sources"],
            "same_current_turn_for_both_profiles": bool(
                baseline["messages"] and specialized["messages"]
                and baseline["messages"][-1] == specialized["messages"][-1]
            ),
            "runs": runs,
        })

    first = next((row["runs"][BASELINE] for row in rows
                  if row["runs"][BASELINE]["generator_called"]), None)
    quote = answer_format == QUOTE
    if quote:
        format_notes = [
            "Quote format: the model selects one found source and returns "
            "JSON with its full text. A quote is accepted only after it "
            "matches the whole section (only spaces are normalized).",
            "The metrics count valid JSON, an allowed source and an exact "
            "full quote. The three-sentence limit does not apply to a full "
            "quote. An exact quote confirms the text of a source, not that "
            "the source fits the question or that the knowledge is right.",
            "Only the sources found for the current question are allowed, "
            "never the sources of the few-shot examples.",
        ]
    else:
        format_notes = [
            "The metrics count form (words, sentences, citations). They do "
            "not measure factual accuracy. The sentence count is a "
            "heuristic.",
            "Citations are only allowed from the sources found for the "
            "current question, never from the few-shot examples.",
        ]
    examples = [
        {
            "question": example["question"],
            "source_ids": list(example["source_ids"]),
            "answer": (quote_example_answer(example) if quote
                       else example["answer"]),
        }
        for example in FEW_SHOT_EXAMPLES
    ]
    return {
        "suite": suite,
        "answer_format": answer_format,
        "description": (
            f"Baseline vs specialized (few-shot) coach prompts on "
            f"{len(questions)} fixed questions ({answer_format} format): one "
            f"search per question, the same sources for both profiles, one "
            f"shared generator, one greedy generation per profile."
        ),
        "notes": [
            SUITE_NOTES.get(suite, "Custom question list."),
            "Prompt specialization only: no model weights were trained.",
            "Both profiles use the same model, system instructions, "
            "retrieval, generation settings and token limit. The only "
            "difference is the three few-shot examples.",
            "The few-shot examples use their own questions, which are not "
            "among the evaluation questions.",
            *format_notes,
        ],
        "generation_settings": first["generation"] if first else None,
        "environment": counting.environment(),
        "system_prompt": QUOTE_SYSTEM_PROMPT if quote else coach.SYSTEM_PROMPT,
        "profiles": {
            BASELINE: {"few_shot_examples": 0},
            SPECIALIZED: {
                "few_shot_examples": len(FEW_SHOT_EXAMPLES),
                "examples": examples,
                "example_messages": example_messages(answer_format),
            },
        },
        "questions": list(questions),
        "search_calls": search_calls,
        "generations": counting.calls,
        "results": rows,
        "summary": {profile: summarize(rows, profile, answer_format)
                    for profile in PROFILES},
    }


def print_report(report: dict) -> None:
    for number, row in enumerate(report["results"], start=1):
        print(f"[{number}] {row['question']}")
        ids = ", ".join(source["source_id"] for source in row["sources"])
        print(f"    sources: {ids or '(none)'}")
        for profile in PROFILES:
            run = row["runs"][profile]
            m = run["metrics"]
            print(f"    {profile}: {run['status']}")
            print(f"      answer: {run['answer']}")
            if report["answer_format"] == QUOTE:
                print(
                    f"      valid JSON {m['valid_json']}, source "
                    f"{m['selected_source_id']}, allowed "
                    f"{m['allowed_source']}, exact full quote "
                    f"{m['exact_full_quote']}"
                )
            else:
                print(
                    f"      words {m['words_without_citations']}, sentences "
                    f"(heuristic) {m['sentences_heuristic']}, citations "
                    f"{run['citations']}, unknown {m['unknown_citations']}"
                )
        print()

    header = (f"{'metric':38s}" + "".join(f"{profile:>13s}"
                                          for profile in PROFILES))
    print(header)
    keys = list(report["summary"][BASELINE])
    for key in keys:
        values = "".join(f"{str(report['summary'][profile][key]):>13s}"
                         for profile in PROFILES)
        print(f"{key:38s}{values}")
    print(f"\nsearch calls: {report['search_calls']}, "
          f"generations: {report['generations']}")
    if report["answer_format"] == QUOTE:
        print("An exact quote confirms the source text, not that the source "
              "fits the question.")
    else:
        print("Metrics count form, not factual accuracy; the sentence count "
              "is a heuristic.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare baseline and specialized coach prompts."
    )
    parser.add_argument(
        "--suite",
        choices=list(SUITES),
        default=DEFAULT_SUITE,
        help="question set (default: specialization)",
    )
    parser.add_argument(
        "--answer-format",
        choices=ANSWER_FORMATS,
        default=DEFAULT_ANSWER_FORMAT,
        help="text (default) or quote (exact source quotation)",
    )
    parser.add_argument("--output", help="save the JSON report here")
    args = parser.parse_args(argv)

    try:
        report = run_comparison(SUITES[args.suite], suite=args.suite,
                                answer_format=args.answer_format)
    except coach_model.CoachSetupError as error:
        print(error, file=sys.stderr)
        return 2

    print_report(report)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"report saved: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
