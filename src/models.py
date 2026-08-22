"""Shared data model that flows through the pipeline: source -> filter -> publish."""

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """A single candidate document pulled from a source, enriched as it moves
    through the filter stages."""

    id: str  # stable dedup key, e.g. "legiscan:1234567" or "fedreg:2026-12345"
    source: str  # "legiscan" | "federal_register" | "legistar"
    title: str
    jurisdiction: str  # e.g. "Virginia", "US Federal", "Alexandria, VA"
    url: str
    text: str  # abstract/summary used for filtering — not full bill/rule text
    date: str  # ISO date (action date, publication date, etc.)
    status: str = ""  # e.g. "Passed", "Final Rule", "Adopted"

    # populated by keyword_filter
    matched_keywords: list[str] = field(default_factory=list)
    matched_categories: list[str] = field(default_factory=list)

    # populated by triage (Haiku pass)
    triage_verdict: str = ""  # "WIN" | "NOT"
    triage_reason: str = ""

    # populated by summarize (Sonnet pass)
    summary: str = ""
    significance: str = ""

    # populated by group.group_candidates() — when non-empty, this Candidate is a
    # synthesized stand-in for multiple same-jurisdiction/category triage survivors
    # (see src/filter/group.py); title/summary/significance describe the group as a
    # whole rather than any single item, and digest/email rendering lists each of
    # these individually instead of using this candidate's own url/status/date.
    grouped_items: list["Candidate"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "jurisdiction": self.jurisdiction,
            "url": self.url,
            "text": self.text,
            "date": self.date,
            "status": self.status,
            "matched_keywords": self.matched_keywords,
            "matched_categories": self.matched_categories,
            "triage_verdict": self.triage_verdict,
            "triage_reason": self.triage_reason,
            "summary": self.summary,
            "significance": self.significance,
        }
