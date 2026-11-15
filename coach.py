"""Strategy Coach prototype on the command line.

question -> search the game's knowledge files -> local model -> answer
with source IDs.

    python coach.py --question \\
        "Must the inspector require Vector to guess the exact midpoint?"
    python coach.py --question "..." --no-retrieval   # model only, no search
    python coach.py --question "..." --output report.json

ask_coach() is the function for callers such as this CLI or, later, the
app. The coach is not connected to the Streamlit app yet.

The citation check only looks at source IDs: every ID in square brackets
must be one of the sections that were found. It does not check whether
each sentence of the answer is true.
"""
import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import coach_model
import coach_retrieval

TOP_K = 3
MAX_NEW_TOKENS = 128

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

# Anything in square brackets counts as a citation, so a citation in a
# wrong format is caught too.
CITATION = re.compile(r"\[([^\[\]\n]{1,80})\]")


@dataclass
class CoachResult:
    question: str
    mode: str  # "rag" or "no_retrieval"
    status: str
    answer: str | None  # the model's answer, unchanged; None if not called
    sources: list  # found sections: source_id, path, title, score, text
    messages: list | None  # what the model got; None if it was not called
    citations: list
    checks: list
    generator_called: bool
    generation: dict | None  # model, revision, settings, tokens, seconds
    environment: dict | None
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_messages(question: str, sections=None) -> list:
    """Chat messages for the model. sections=None means no retrieval."""
    if sections is None:
        user = f"Question: {question}"
    else:
        blocks = [
            f"[{section.source_id}] {section.title}\n{section.text}"
            for section in sections
        ]
        user = (
            "Sources:\n\n" + "\n\n".join(blocks)
            + f"\n\nQuestion: {question}"
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def find_citations(answer: str) -> list:
    return [citation.strip() for citation in CITATION.findall(answer)]


def check(description: str, passed, **details) -> dict:
    return {"check": description, "passed": bool(passed), **details}


def ask_coach(question: str, use_retrieval: bool = True, *,
              generator=None, search=None) -> CoachResult:
    """Answer a question about the game.

    With retrieval: search the knowledge files, give the model the found
    sections, and check the source IDs it cites. If nothing is found, the
    coach abstains and does not call the model.
    Without retrieval: give the model only the question, with the same
    instructions and settings.

    generator and search can be replaced, for example in tests. Raises
    coach_model.CoachSetupError if the model or its libraries are missing.
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty.")

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
                status=ABSTAINED,
                answer=None,
                sources=[],
                messages=None,
                citations=[],
                checks=[check("knowledge search found a section", False)],
                generator_called=False,
                generation=None,
                environment=None,
                note=ABSTAIN_NOTE,
            )
        messages = build_messages(
            question, [result.section for result in results]
        )
    else:
        messages = build_messages(question, None)

    generator = generator or coach_model.get_generator()
    generation = generator.generate(messages, MAX_NEW_TOKENS)
    answer = generation.text
    citations = find_citations(answer)

    checks = [
        check("answer is not empty", answer),
        check(
            "no thinking block in the answer",
            "<think>" not in generation.raw_text
            and "</think>" not in generation.raw_text,
        ),
    ]
    if use_retrieval:
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
        passed = all(item["passed"] for item in checks)
        status = ANSWERED_WITHOUT_RETRIEVAL if passed else VALIDATION_FAILED
        note = NO_RETRIEVAL_NOTE

    environment = getattr(generator, "environment", None)
    return CoachResult(
        question=question,
        mode=MODE_RAG if use_retrieval else MODE_NO_RETRIEVAL,
        status=status,
        answer=answer,
        sources=sources,
        messages=messages,
        citations=citations,
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
        help="skip the knowledge search (baseline: the model only)",
    )
    parser.add_argument("--output", help="save a JSON report here")
    args = parser.parse_args(argv)

    try:
        result = ask_coach(args.question, use_retrieval=not args.no_retrieval)
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
