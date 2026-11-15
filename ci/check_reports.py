"""Checks for the cross-platform CI run (standard library only).

An exit code alone is not enough: evaluate_coach.py also exits with 0 when
answers are rejected. So this script reads the saved JSON reports and
checks what really happened.

    python ci/check_reports.py game ci-out
    python ci/check_reports.py coach ci-out
    python ci/check_reports.py mermaid-copy
    python ci/check_reports.py rendered ci-out/architecture.svg \
        ci-out/architecture.png

Exit code 0 when every check passed, 1 otherwise.
"""
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import coach_model  # noqa: E402  (pure import: no torch, no weights)
import coach_retrieval  # noqa: E402

EXPECTED_QUOTE_SOURCE = "rules-valid-guesses"


class Checks:
    def __init__(self, title):
        self.title = title
        self.failures = []

    def require(self, condition, message):
        mark = "ok  " if condition else "FAIL"
        print(f"  [{mark}] {message}")
        if not condition:
            self.failures.append(message)

    def finish(self) -> int:
        if self.failures:
            print(f"{self.title}: {len(self.failures)} check(s) failed")
            return 1
        print(f"{self.title}: all checks passed")
        return 0


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def spaces(text: str) -> str:
    return " ".join((text or "").split())


def check_game(folder: Path) -> int:
    checks = Checks("game evaluation")
    report = load(folder / "evaluation.json")
    checks.require(report["summary"] == {"passed": 6, "failed": 0,
                                         "total": 6},
                   f"evaluate.py summary is 6/6: {report['summary']}")
    return checks.finish()


def same_settings(a: dict, b: dict) -> bool:
    keep = ("model", "revision", "device", "dtype", "local_files_only",
            "inference_mode", "enable_thinking", "do_sample",
            "max_new_tokens")
    return all(a.get(key) == b.get(key) for key in keep)


def check_coach(folder: Path) -> int:
    checks = Checks("coach")
    sections = {section.source_id: section.text
                for section in coach_retrieval.default_index().sections}

    smoke = load(folder / "local_model_smoke.json")
    checks.require(smoke["result"] == "PASS", "smoke result is PASS")
    checks.require(smoke["model"]["revision"] == coach_model.MODEL_REVISION,
                   "smoke used the pinned model revision")
    checks.require(smoke["environment"]["device"] == "cpu",
                   "smoke ran on the CPU")
    checks.require(smoke["environment"]["HF_HUB_OFFLINE"] == "1",
                   "smoke ran with HF_HUB_OFFLINE=1")
    print(f"  smoke answer: {smoke['answer']}")

    report = load(folder / "coach_quote_regression.json")
    checks.require(report["suite"] == "fraction-regression"
                   and report["answer_format"] == "quote",
                   "report is the fraction-regression quote run")
    checks.require(report["search_calls"] == 3,
                   f"3 searches (got {report['search_calls']})")
    checks.require(report["generations"] == 6,
                   f"6 generations (got {report['generations']})")
    checks.require(len(report["results"]) == 3, "3 questions in the report")

    settings = report["generation_settings"] or {}
    checks.require(settings.get("model") == coach_model.MODEL_ID
                   and settings.get("revision") == coach_model.MODEL_REVISION,
                   "pinned model and revision")
    checks.require(settings.get("device") == "cpu", "generation on the CPU")
    checks.require(settings.get("local_files_only") is True
                   and settings.get("do_sample") is False
                   and settings.get("max_new_tokens") == 192,
                   "local files only, greedy decoding, 192 new tokens")
    environment = report["environment"] or {}
    checks.require(environment.get("HF_HUB_OFFLINE") == "1"
                   and environment.get("device") == "cpu",
                   "inference ran offline (HF_HUB_OFFLINE=1) on the CPU")

    specialized_ok = 0
    for row in report["results"]:
        question = row["question"]
        baseline = row["runs"]["baseline"]
        specialized = row["runs"]["specialized"]
        checks.require(row["same_sources_for_both_profiles"]
                       and row["same_current_turn_for_both_profiles"]
                       and baseline["messages"][-1]
                       == specialized["messages"][-1],
                       f"same current context for both profiles: {question}")
        checks.require(baseline["generator_called"]
                       and specialized["generator_called"]
                       and same_settings(baseline["generation"],
                                         specialized["generation"]),
                       f"both profiles generated with the same settings: "
                       f"{question}")
        for profile, run in (("baseline", baseline),
                             ("specialized", specialized)):
            accepted = run["accepted_quote"]
            print(f"  {profile:11s} {run['status']:17s} "
                  f"selected={run['metrics']['selected_source_id']} "
                  f"accepted={'yes' if accepted else 'no'}  | {question}")
            if accepted:
                found = {source["source_id"]: source["text"]
                         for source in run["sources"]}
                source_id = accepted["source_id"]
                checks.require(
                    source_id in found
                    and spaces(accepted["quote"]) == spaces(found[source_id])
                    and spaces(found[source_id])
                    == spaces(sections.get(source_id)),
                    f"{profile} accepted quote equals the full source "
                    f"{source_id} and the knowledge file",
                )
        accepted = specialized["accepted_quote"] or {}
        if (specialized["status"] == "answered"
                and accepted.get("source_id") == EXPECTED_QUOTE_SOURCE
                and spaces(accepted.get("quote"))
                == spaces(sections[EXPECTED_QUOTE_SOURCE])):
            specialized_ok += 1

    checks.require(specialized_ok == 3,
                   f"specialized: 3 answered, exact full quotes of "
                   f"{EXPECTED_QUOTE_SOURCE} (got {specialized_ok})")
    print(f"  summary: {json.dumps(report['summary'])}")
    print("  (rejected baseline answers are expected and are not a failure)")
    return checks.finish()


def check_mermaid_copy() -> int:
    checks = Checks("Mermaid copy")
    source = (ROOT / "diagrams" / "architecture.mmd").read_text(
        encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```mermaid\n(.*?)\n```", readme, flags=re.S)
    checks.require(len(blocks) == 1, f"README has one Mermaid block "
                   f"(found {len(blocks)})")
    checks.require(bool(blocks) and blocks[0] == source.rstrip("\n"),
                   "README Mermaid block equals diagrams/architecture.mmd")
    return checks.finish()


def check_rendered(svg_path: Path, png_path: Path) -> int:
    checks = Checks("rendered diagram")
    svg = svg_path.read_text(encoding="utf-8")
    checks.require("<svg" in svg and len(svg) > 10_000,
                   f"SVG exists ({len(svg)} characters)")
    for marker in ("Syntax error", "Parse error"):
        checks.require(marker not in svg, f"no {marker!r} in the SVG")
    # Every Mermaid SVG has CSS rules named .error-icon / .error-text, so
    # look for an element that uses them: that is what an error render has.
    checks.require(
        not re.search(r'class="[^"]*\berror-(icon|text)\b', svg),
        "no error-icon / error-text element in the SVG",
    )
    for label in ("app.py", "safe_play_round", "validate_transition",
                  "BM25 index", "LocalGenerator", "coach.py",
                  "evaluate_coach.py", "tests/ (pytest)"):
        checks.require(label in svg, f"label {label!r} is in the SVG")
    data = png_path.read_bytes()
    is_png = data[:8] == b"\x89PNG\r\n\x1a\n"
    checks.require(is_png, "PNG has a valid signature")
    if is_png:
        width, height = struct.unpack(">II", data[16:24])
        print(f"  PNG size: {width} x {height} pixels, {len(data)} bytes")
        checks.require(width >= 800 and height >= 600,
                       "PNG is large enough to read")
    return checks.finish()


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, args = argv[0], argv[1:]
    if command == "game":
        return check_game(Path(args[0]))
    if command == "coach":
        return check_coach(Path(args[0]))
    if command == "mermaid-copy":
        return check_mermaid_copy()
    if command == "rendered":
        return check_rendered(Path(args[0]), Path(args[1]))
    print(f"unknown command {command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
