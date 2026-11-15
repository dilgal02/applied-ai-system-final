"""Strategy Coach prototype on the command line.

question -> search the game's knowledge files -> local model -> answer
with source IDs.

    python coach.py --question \\
        "Must the inspector require Vector to guess the exact midpoint?"
    python coach.py --question "..." --no-retrieval   # model only, no search
    python coach.py --question "..." --profile specialized  # few-shot
    python coach.py --question "..." --answer-format quote  # exact quote
    python coach.py --question "..." --output report.json

ask_coach() is the function for callers such as this CLI or, later, the
app. The coach is not connected to the Streamlit app yet.

The citation check only looks at source IDs: every ID in square brackets
must be one of the sections that were found. It does not check whether
each sentence of the answer is true.

With --answer-format quote the model picks one found source and returns
JSON with the full text of that section. The quote is accepted only if it
matches the whole section (only spaces are normalized). A match confirms
the text of the source, not that the source fits the question or that the
knowledge files are right.
"""
import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import coach_model
import coach_retrieval
from coach_prompts import (
    ANSWER_FORMATS,
    DEFAULT_ANSWER_FORMAT,
    DEFAULT_PROFILE,
    PROFILES,
    QUOTE,
    QUOTE_SYSTEM_PROMPT,
    SPECIALIZED,
    check_answer_format,
    check_profile,
    example_messages,
    format_user_message,
)

TOP_K = 3
MAX_NEW_TOKENS = 128
# A full section in JSON needs more room than a short text answer.
QUOTE_MAX_NEW_TOKENS = 192

# The same instructions for both modes. Only the user message differs:
# with retrieval it starts with the found sources.
SYSTEM_PROMPT = (
    "You are the Strategy Coach for the game Number Duel. Answer the "
    "player's question in English in at most three short sentences. If "
    "sources are given, use only those sources and cite each source you "
    "use by writing its ID in square brackets, exactly as it is written in "
    "the source list. If you are not sure, say so."
)

MODE_RAG = "rag"
MODE_NO_RETRIEVAL = "no_retrieval"

ANSWERED = "answered"
VALIDATION_FAILED = "validation_failed"
ABSTAINED = "abstained"
ANSWERED_WITHOUT_RETRIEVAL = "answered_without_retrieval"

ABSTAIN_NOTE = (
    "No section of the game's knowledge files matches this question, so "
    "the coach did not ask the model. This refusal is a rule of the "
    "program, not an answer from the model."
)
RAG_NOTE = (
    "The citation check only checks the source IDs, not whether each "
    "sentence of the answer is true."
)
NO_RETRIEVAL_NOTE = (
    "Answer without retrieval: no sources were given to the model, so a "
    "missing citation is not an error. Bracketed IDs in this answer, if "
    "any, were not checked against any source."
)
QUOTE_NOTE = (
    "Quote format: a quote is accepted only after it matches the full text "
    "of a source found for this question (only spaces are normalized). A "
    "match confirms the text of the source, not that the source fits the "
    "question or that the knowledge files are right."
)
QUOTE_ABSTAIN_NOTE = (
    "The model returned null / null: it found no supplied source that "
    "answers the question. This is the model's choice, checked by the "
    "program; no quote was accepted."
)

# Anything in square brackets counts as a citation, so a citation in a
# wrong format is caught too.
CITATION = re.compile(r"\[([^\[\]\n]{1,80})\]")


@dataclass
class CoachResult:
    question: str
    mode: str  # "rag" or "no_retrieval"
    profile: str  # "baseline" or "specialized" (few-shot examples)
    answer_format: str  # "text" or "quote"
    status: str
    answer: str | None  # the model's answer, unchanged; None if not called
    sources: list  # found sections: source_id, path, title, score, text
    messages: list | None  # what the model got; None if it was not called
    citations: list
    accepted_quote: dict | None  # quote format: set only after all checks
    checks: list
    generator_called: bool
    generation: dict | None  # model, revision, settings, tokens, seconds
    environment: dict | None
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_messages(question: str, sections=None,
                   profile: str = DEFAULT_PROFILE,
                   answer_format: str = DEFAULT_ANSWER_FORMAT) -> list:
    """Chat messages for the model. sections=None means no retrieval.

    The specialized profile puts the few-shot examples between the system
    instructions and the current question; everything else is the same.
    The quote format uses its own system prompt and quote examples.
    """
    check_profile(profile)
    check_answer_format(answer_format)
    system = QUOTE_SYSTEM_PROMPT if answer_format == QUOTE else SYSTEM_PROMPT
    messages = [{"role": "system", "content": system}]
    if profile == SPECIALIZED:
        messages += example_messages(answer_format)
    messages.append(
        {"role": "user", "content": format_user_message(question, sections)}
    )
    return messages


def find_citations(answer: str) -> list:
    return [citation.strip() for citation in CITATION.findall(answer)]


def check(description: str, passed, **details) -> dict:
    return {"check": description, "passed": bool(passed), **details}


def normalize_spaces(text: str) -> str:
    """Only spaces and line breaks change; every other character stays."""
    return " ".join(text.split())


def check_quote(answer: str, sources: list) -> tuple:
    """Check a quote-format answer against the sources of this question.

    Returns (status, checks, accepted_quote, selected_source_id). The
    accepted quote is only set when every check passed.
    """
    checks = []
    try:
        data = json.loads(answer)
        valid_json = True
    except ValueError:
        data, valid_json = None, False
    checks.append(check("answer is valid JSON", valid_json,
                        key="valid_json"))
    if not valid_json:
        return VALIDATION_FAILED, checks, None, None

    keys_ok = isinstance(data, dict) and set(data) == {"source_id", "quote"}
    checks.append(check('JSON has exactly the keys "source_id" and "quote"',
                        keys_ok, key="two_keys"))
    if not keys_ok:
        return VALIDATION_FAILED, checks, None, None

    source_id, quote = data["source_id"], data["quote"]
    if source_id is None and quote is None:
        checks.append(check("model found no fitting source (null / null)",
                            True, key="null_pair"))
        return ABSTAINED, checks, None, None

    types_ok = isinstance(source_id, str) and isinstance(quote, str)
    checks.append(check("source_id and quote are strings", types_ok,
                        key="types"))
    if not types_ok:
        return VALIDATION_FAILED, checks, None, None

    by_id = {source["source_id"]: source for source in sources}
    known = source_id in by_id
    checks.append(check("source_id is one of the sources found for this "
                        "question", known, key="allowed_source",
                        source_id=source_id))
    if not known:
        return VALIDATION_FAILED, checks, None, source_id

    expected = normalize_spaces(by_id[source_id]["text"])
    exact = normalize_spaces(quote) == expected
    checks.append(check(
        "quote is the full text of that source (only spaces normalized)",
        exact,
        key="exact_full_quote",
        quote_words=len(quote.split()),
        source_words=len(expected.split()),
    ))
    if not exact:
        return VALIDATION_FAILED, checks, None, source_id
    return ANSWERED, checks, {"source_id": source_id, "quote": quote}, \
        source_id


def ask_coach(question: str, use_retrieval: bool = True, *,
              profile: str = DEFAULT_PROFILE,
              answer_format: str = DEFAULT_ANSWER_FORMAT,
              generator=None, search=None) -> CoachResult:
    """Answer a question about the game.

    With retrieval: search the knowledge files, give the model the found
    sections, and check the source IDs it cites. Only the sections found
    for this question are allowed, never the sources of the few-shot
    examples. If nothing is found, the coach abstains and does not call
    the model.
    Without retrieval: give the model only the question, with the same
    instructions and settings.

    profile: "baseline" (default) or "specialized" (adds few-shot
    examples). The specialized profile is only for comparing profiles with
    retrieval, so it cannot be used without retrieval.

    answer_format: "text" (default) or "quote". In the quote format the
    model returns JSON with one found source and its full text, and the
    quote is accepted only after it matches that section. Quote needs
    retrieval.

    generator and search can be replaced, for example in tests. Raises
    coach_model.CoachSetupError if the model or its libraries are missing.
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty.")
    check_profile(profile)
    check_answer_format(answer_format)
    if profile == SPECIALIZED and not use_retrieval:
        raise ValueError(
            "The specialized profile compares prompts with retrieval, so it "
            "cannot be used with --no-retrieval."
        )
    if answer_format == QUOTE and not use_retrieval:
        raise ValueError(
            "The quote format needs found sources, so it cannot be used "
            "with --no-retrieval."
        )

    sources = []
    if use_retrieval:
        search = search or coach_retrieval.search
        results = search(question, TOP_K)
        sources = [
            {
                "source_id": result.section.source_id,
                "path": result.section.path,
                "title": result.section.title,
                "score": round(result.score, 3),
                "text": result.section.text,
            }
            for result in results
        ]
        if not results:
            return CoachResult(
                question=question,
                mode=MODE_RAG,
                profile=profile,
                answer_format=answer_format,
                status=ABSTAINED,
                answer=None,
                sources=[],
                messages=None,
                citations=[],
                accepted_quote=None,
                checks=[check("knowledge search found a section", False)],
                generator_called=False,
                generation=None,
                environment=None,
                note=ABSTAIN_NOTE,
            )
        messages = build_messages(
            question, [result.section for result in results], profile,
            answer_format,
        )
    else:
        messages = build_messages(question, None, profile, answer_format)

    generator = generator or coach_model.get_generator()
    max_new_tokens = (QUOTE_MAX_NEW_TOKENS if answer_format == QUOTE
                      else MAX_NEW_TOKENS)
    generation = generator.generate(messages, max_new_tokens)
    answer = generation.text
    accepted_quote = None

    checks = [
        check("answer is not empty", answer),
        check(
            "no thinking block in the answer",
            "<think>" not in generation.raw_text
            and "</think>" not in generation.raw_text,
        ),
    ]
    if answer_format == QUOTE:
        status, quote_checks, accepted, selected = check_quote(
            answer, sources
        )
        checks += quote_checks
        citations = [selected] if selected else []
        if status == ANSWERED and all(item["passed"] for item in checks):
            accepted_quote = accepted  # every check passed
        elif status == ANSWERED:
            status = VALIDATION_FAILED
        note = QUOTE_ABSTAIN_NOTE if status == ABSTAINED else QUOTE_NOTE
    elif use_retrieval:
        citations = find_citations(answer)
        allowed = {source["source_id"] for source in sources}
        unknown = [citation for citation in citations
                   if citation not in allowed]
        checks += [
            check("answer cites at least one source", citations),
            check(
                "every cited ID is one of the found sources",
                not unknown,
                unknown_ids=unknown,
            ),
        ]
        passed = all(item["passed"] for item in checks)
        status = ANSWERED if passed else VALIDATION_FAILED
        note = RAG_NOTE
    else:
        citations = find_citations(answer)
        passed = all(item["passed"] for item in checks)
        status = ANSWERED_WITHOUT_RETRIEVAL if passed else VALIDATION_FAILED
        note = NO_RETRIEVAL_NOTE

    environment = getattr(generator, "environment", None)
    return CoachResult(
        question=question,
        mode=MODE_RAG if use_retrieval else MODE_NO_RETRIEVAL,
        profile=profile,
        answer_format=answer_format,
        status=status,
        answer=answer,
        sources=sources,
        messages=messages,
        citations=citations,
        accepted_quote=accepted_quote,
        checks=checks,
        generator_called=True,
        generation={
            **generation.settings(),
            "prompt_tokens": generation.prompt_tokens,
            "generated_tokens": generation.generated_tokens,
            "thinking_off": generation.thinking_off,
            "seconds": {
                "load": generation.load_seconds,
                "generate": generation.generate_seconds,
            },
        },
        environment=environment() if callable(environment) else None,
        note=note,
    )


def print_result(result: CoachResult) -> None:
    if result.mode == MODE_RAG:
        mode = "rag (knowledge search + local model)"
    else:
        mode = "no_retrieval (local model only, no sources given)"
    print(f"question:  {result.question}")
    print(f"mode:      {mode}")
    print(f"profile:   {result.profile}")
    print(f"format:    {result.answer_format}")
    if result.mode == MODE_RAG:
        print("sources:   (score = word match, not model confidence)")
        for source in result.sources:
            print(f"  [{source['source_id']}] {source['path']}  "
                  f"score {source['score']:.3f}")
        if not result.sources:
            print("  (none found)")
    if result.generator_called:
        print(f"answer:    {result.answer}")
        print(f"citations: {result.citations}")
        if result.answer_format == QUOTE:
            accepted = result.accepted_quote
            print("accepted:  "
                  + (f"[{accepted['source_id']}] {accepted['quote']}"
                     if accepted else "(no quote accepted)"))
        tokens = result.generation["generated_tokens"]
        limit = result.generation["max_new_tokens"]
        print(f"tokens:    {tokens} of max {limit}")
    else:
        print("answer:    (none: the model was not called)")
    for item in result.checks:
        mark = "ok" if item["passed"] else "FAIL"
        extra = ""
        if item.get("unknown_ids"):
            extra = f" {item['unknown_ids']}"
        print(f"check:     [{mark}] {item['check']}{extra}")
    print(f"status:    {result.status}")
    print(f"note:      {result.note}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Ask the local Strategy Coach a question about the game."
    )
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--no-retrieval",
        action="store_true",
        help="skip the knowledge search (the model only)",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=DEFAULT_PROFILE,
        help="prompt profile (default: baseline; specialized adds "
             "few-shot examples, only with retrieval)",
    )
    parser.add_argument(
        "--answer-format",
        choices=ANSWER_FORMATS,
        default=DEFAULT_ANSWER_FORMAT,
        help="text (default) or quote: one found source as JSON with its "
             "full text, checked before it is accepted (only with "
             "retrieval)",
    )
    parser.add_argument("--output", help="save a JSON report here")
    args = parser.parse_args(argv)

    try:
        result = ask_coach(args.question,
                           use_retrieval=not args.no_retrieval,
                           profile=args.profile,
                           answer_format=args.answer_format)
    except coach_model.CoachSetupError as error:
        print(error, file=sys.stderr)
        return 2
    except ValueError as error:
        parser.error(str(error))

    print_result(result)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        print(f"report saved: {args.output}")
    return 1 if result.status == VALIDATION_FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
