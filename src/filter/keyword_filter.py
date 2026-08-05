"""Free, local pre-filter: discard candidates whose title/text doesn't match any
keyword in config/keywords.yaml before anything touches an LLM.
"""

import re
from pathlib import Path

import yaml

from src.models import Candidate

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "keywords.yaml"


def load_keywords(path: Path = CONFIG_PATH) -> dict[str, list[str]]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _compile_patterns(keywords_by_category: dict[str, list[str]]) -> dict[str, list[tuple[str, re.Pattern]]]:
    """Word-boundary, case-insensitive patterns per category, keyed on the original
    keyword string so matches can be reported back readably."""
    compiled = {}
    for category, keywords in keywords_by_category.items():
        compiled[category] = [
            (kw, re.compile(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", re.IGNORECASE))
            for kw in keywords
        ]
    return compiled


def filter_candidates(
    candidates: list[Candidate], keywords_by_category: dict[str, list[str]] | None = None
) -> list[Candidate]:
    """Return the subset of candidates matching >=1 keyword, with matched_keywords
    and matched_categories populated on each survivor."""
    if keywords_by_category is None:
        keywords_by_category = load_keywords()
    patterns = _compile_patterns(keywords_by_category)

    survivors = []
    for candidate in candidates:
        haystack = f"{candidate.title}\n{candidate.text}"
        matched_keywords: list[str] = []
        matched_categories: list[str] = []
        for category, kw_patterns in patterns.items():
            for keyword, pattern in kw_patterns:
                if pattern.search(haystack):
                    matched_keywords.append(keyword)
                    if category not in matched_categories:
                        matched_categories.append(category)
        if matched_keywords:
            candidate.matched_keywords = matched_keywords
            candidate.matched_categories = matched_categories
            survivors.append(candidate)
    return survivors
