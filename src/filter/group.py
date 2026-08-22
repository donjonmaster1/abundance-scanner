"""Collapses triage survivors from the same jurisdiction + category into one
digest entry when there are enough of them to otherwise flood the digest —
e.g. a city council processing a dozen individual small rezonings in one
week. See CLAUDE.md's "Legistar/Phoenix over-representation" note; this is
what resolved it, based on a live test where 11 newly-added Legistar
jurisdictions turned 2 wins into 39, 21 of them near-identical Jacksonville
rezonings.

Runs after triage, before summarize — summarize.py's summarize_all() calls
summarize_group() instead of summarize() for any Candidate with
grouped_items populated.
"""

from collections import defaultdict

from src.models import Candidate

GROUP_THRESHOLD = 3  # jurisdiction+category clusters at or above this size get grouped


def group_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Return a new list: jurisdiction+category clusters >= GROUP_THRESHOLD are
    collapsed into one synthesized Candidate (grouped_items populated);
    everything else passes through unchanged. Does not mutate the input.
    """
    buckets: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for c in candidates:
        category = c.matched_categories[0] if c.matched_categories else "uncategorized"
        buckets[(c.jurisdiction, category)].append(c)

    result: list[Candidate] = []
    for (jurisdiction, category), items in buckets.items():
        if len(items) >= GROUP_THRESHOLD:
            result.append(_make_group(jurisdiction, category, items))
        else:
            result.extend(items)
    return result


def _make_group(jurisdiction: str, category: str, items: list[Candidate]) -> Candidate:
    first = items[0]
    group_id = f"group:{first.source}:{jurisdiction}:{category}:" + ",".join(sorted(i.id for i in items))
    return Candidate(
        id=group_id,
        source=first.source,
        title=f"{len(items)} {category.replace('_', ' ')} actions in {jurisdiction}",
        jurisdiction=jurisdiction,
        url=first.url,
        text="",
        date=max(i.date for i in items),
        matched_categories=[category],
        grouped_items=items,
    )
