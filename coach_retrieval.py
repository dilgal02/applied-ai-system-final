"""Keyword search over the game's own knowledge files, for the Coach.

Every "## [source-id] Title" section in knowledge/*.md is one searchable
document. The search uses a small BM25 index built with the Python
standard library only.

A score tells how well the words of the query match the words of a
section. It is a word-matching score, not a confidence value of an AI.

Usage:
    python coach_retrieval.py --top-k 3 \\
        --query "What happens if both players guess correctly?"
"""
import argparse
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"

# "## [rules-paired-rounds] Paired rounds"
SECTION_HEADING = re.compile(r"^## \[([a-z0-9]+(?:-[a-z0-9]+)*)\] (\S.*?)\s*$")
WORD = re.compile(r"[a-z0-9]+")

# Common words that carry no meaning for the search. "s" and "t" are the
# pieces left over from words like "Vector's" or "don't".
STOP_WORDS = frozenset("""
a about after all also am an and any are as at be been before being but
by can could did do does doing for from had has have how i if in into is
it its me my of on or our s so t than that the their them then there
these they this those to too us was we were what when where which while
who why will with would you your
""".split())

# BM25 settings (common default values).
K1 = 1.5
B = 0.75


@dataclass(frozen=True)
class Section:
    source_id: str
    path: str  # relative to the project, for example knowledge/rules.md
    title: str
    text: str  # the full text of the section, without its heading


@dataclass(frozen=True)
class SearchResult:
    section: Section
    score: float  # word-matching score, not AI confidence


def normalize_word(word: str) -> str:
    """Very small stemmer: guesses/guessed/guessing -> guess."""
    if len(word) > 4 and word.endswith("sses"):
        return word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed", "ly"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    if (len(word) > 3 and word.endswith("s")
            and not word.endswith(("ss", "us", "is"))):
        return word[:-1]
    return word


def tokenize(text: str) -> list:
    """Lower-case words without stop words, each in a normalized form."""
    words = WORD.findall(text.lower())
    return [normalize_word(word) for word in words if word not in STOP_WORDS]


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def parse_sections(path: Path) -> list:
    """Split one knowledge file into its "## [id] Title" sections."""
    sections = []
    current = None
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        match = SECTION_HEADING.match(line)
        if match:
            current = {"id": match.group(1), "title": match.group(2),
                       "lines": []}
            sections.append(current)
        elif line.startswith("## "):
            raise ValueError(
                f"{relative_path(path)}:{number}: a section heading needs "
                f"an ID, like '## [rules-example] Title'."
            )
        elif current is None:
            # Before the first section only the "# " title may appear.
            if line.strip() and not line.startswith("# "):
                raise ValueError(
                    f"{relative_path(path)}:{number}: text before the "
                    f"first section would not be searchable."
                )
        else:
            current["lines"].append(line)

    result = []
    for item in sections:
        text = "\n".join(item["lines"]).strip()
        if not text:
            raise ValueError(
                f"{relative_path(path)}: section [{item['id']}] is empty."
            )
        result.append(Section(item["id"], relative_path(path),
                              item["title"], text))
    return result


class KnowledgeIndex:
    """A small BM25 index over knowledge sections."""

    def __init__(self, sections):
        seen = {}
        for section in sections:
            if section.source_id in seen:
                raise ValueError(
                    f"Duplicate source_id '{section.source_id}' in "
                    f"{section.path} (already used in "
                    f"{seen[section.source_id]})."
                )
            seen[section.source_id] = section.path
        self.sections = tuple(sections)
        self._term_counts = [
            Counter(tokenize(section.title + "\n" + section.text))
            for section in self.sections
        ]
        self._lengths = [sum(counts.values()) for counts in self._term_counts]
        total = sum(self._lengths)
        self._average_length = total / len(self._lengths) if total else 0.0
        self._document_frequency = Counter(
            term for counts in self._term_counts for term in counts
        )

    def _idf(self, term: str) -> float:
        count = len(self.sections)
        frequency = self._document_frequency[term]
        return math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))

    def search(self, query: str, top_k: int = 3) -> list:
        """Best matching sections, best first, at most top_k of them.

        Sections without any query word are left out. Equal scores are
        ordered by source_id, so the order is always the same.
        """
        if isinstance(top_k, bool) or not isinstance(top_k, int) \
                or top_k < 1:
            raise ValueError(
                f"top_k must be a whole number of at least 1, "
                f"got {top_k!r}."
            )
        terms = set(tokenize(query or ""))
        if not terms:
            return []

        results = []
        for section, counts, length in zip(
                self.sections, self._term_counts, self._lengths):
            score = 0.0
            for term in terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                norm = 1 - B + B * length / self._average_length
                score += self._idf(term) * (
                    frequency * (K1 + 1) / (frequency + K1 * norm)
                )
            if score > 0:
                results.append(SearchResult(section, score))

        results.sort(key=lambda result: (-result.score,
                                         result.section.source_id))
        return results[:top_k]


def load_index(knowledge_dir: Path = KNOWLEDGE_DIR) -> KnowledgeIndex:
    """Build an index from every .md file in knowledge_dir."""
    files = sorted(Path(knowledge_dir).glob("*.md"))
    if not files:
        folder = relative_path(Path(knowledge_dir))
        raise ValueError(f"No knowledge files in {folder}.")
    sections = []
    for path in files:
        sections.extend(parse_sections(path))
    return KnowledgeIndex(sections)


@lru_cache(maxsize=1)
def default_index() -> KnowledgeIndex:
    return load_index(KNOWLEDGE_DIR)


def search(query: str, top_k: int = 3) -> list:
    """Search the project's knowledge files."""
    return default_index().search(query, top_k)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Search the Number Duel knowledge files (BM25)."
    )
    parser.add_argument("--query", required=True, help="question to search")
    parser.add_argument("--top-k", type=int, default=3,
                        help="maximum number of sections (default 3)")
    args = parser.parse_args(argv)

    try:
        results = search(args.query, args.top_k)
    except ValueError as error:
        parser.error(str(error))

    print(f"query: {args.query}")
    print("score = how well the query words match a section "
          "(not AI confidence)")
    if not results:
        print("no matching sections")
        return 0
    for rank, result in enumerate(results, start=1):
        section = result.section
        print()
        print(f"{rank}. [{section.source_id}] {section.title}")
        print(f"   source: {section.path}")
        print(f"   score:  {result.score:.3f}")
        for line in section.text.splitlines():
            print(f"   | {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
