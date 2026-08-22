"""Writes the weekly digest to digests/YYYY-MM-DD.md."""

from pathlib import Path

from src.models import Candidate

DIGESTS_DIR = Path(__file__).resolve().parents[2] / "digests"

CATEGORY_LABELS = {
    "state_capacity": "State Capacity",
    "housing_supply": "Housing Supply",
    "energy_supply": "Energy Supply",
    "service_provision": "Effective Service Provision",
}

SOURCE_LABELS = {
    "legiscan": "LegiScan (state legislature)",
    "federal_register": "Federal Register",
    "legistar": "Legistar (municipal)",
}


def _entry_md(c: Candidate) -> str:
    source_label = SOURCE_LABELS.get(c.source, c.source)
    lines = [f"### {c.title.strip()}", f"- **Jurisdiction:** {c.jurisdiction}"]
    if c.grouped_items:
        lines.append(f"- **Source:** {source_label}, {len(c.grouped_items)} individual actions:")
        for item in c.grouped_items:
            lines.append(
                f"  - [{item.title.strip()}]({item.url}) "
                f"(status: {item.status or 'n/a'}, {item.date})"
            )
    else:
        lines.append(f"- **Source:** [{source_label}]({c.url})")
        lines.append(f"- **Status:** {c.status or 'n/a'} (as of {c.date})")
    lines.append(f"- **Summary:** {c.summary}")
    lines.append(f"- **Why it matters:** {c.significance}")
    return "\n".join(lines)


def build_digest_markdown(candidates: list[Candidate], run_date: str) -> str:
    by_category: dict[str, list[Candidate]] = {}
    for c in candidates:
        category = c.matched_categories[0] if c.matched_categories else "uncategorized"
        by_category.setdefault(category, []).append(c)

    parts = [f"# Abundance Wins — {run_date}", ""]
    if not candidates:
        parts.append("No candidate wins cleared triage this week.")
        return "\n".join(parts) + "\n"

    total_wins = sum(len(c.grouped_items) or 1 for c in candidates)
    if total_wins != len(candidates):
        parts.append(f"{total_wins} win(s) this week, grouped into {len(candidates)} entries below.")
    else:
        parts.append(f"{len(candidates)} win(s) this week.")
    parts.append("")

    for category in sorted(by_category, key=lambda k: CATEGORY_LABELS.get(k, k)):
        label = CATEGORY_LABELS.get(category, category.replace("_", " ").title())
        entries = sorted(by_category[category], key=lambda c: c.date, reverse=True)
        parts.append(f"## {label}")
        parts.append("")
        for c in entries:
            parts.append(_entry_md(c))
            parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def write_digest(candidates: list[Candidate], run_date: str, out_dir: Path = DIGESTS_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_date}.md"
    path.write_text(build_digest_markdown(candidates, run_date), encoding="utf-8")
    return path
