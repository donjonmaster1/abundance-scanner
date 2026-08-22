"""Sonnet summary pass: generate the real digest entry for triage survivors only.

Thinking is disabled and effort kept low — these are short, well-scoped writing
tasks and adaptive thinking's extra spend isn't worth it under the budget ceiling.
"""

import json
import os

from anthropic import Anthropic

from src.cost_log import CostTracker
from src.models import Candidate

MODEL = "claude-sonnet-5"
MAX_TEXT_CHARS = 4000

SYSTEM_PROMPT = (
    'You write entries for a weekly "Abundance wins" digest — local, state, and federal '
    "agency actions that are substantial steps forward on state capacity, housing supply, "
    "energy supply, or effective public service delivery. For the given item, produce: "
    "a 2-4 sentence summary in plain English (what changed, who did it, why it matters), "
    "a category tag, and a one-sentence significance note (how big a deal this is, and "
    "for whom)."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "category": {
            "type": "string",
            "enum": ["state_capacity", "housing_supply", "energy_supply", "service_provision"],
        },
        "significance": {"type": "string"},
    },
    "required": ["summary", "category", "significance"],
    "additionalProperties": False,
}

GROUP_SYSTEM_PROMPT = (
    'You write entries for a weekly "Abundance wins" digest — local, state, and federal '
    "agency actions that are substantial steps forward on state capacity, housing supply, "
    "energy supply, or effective public service delivery. You are given several items "
    "from the same jurisdiction, all triaged as wins in the same category in the same "
    "week — write ONE combined entry for the group, not one per item. Describe the "
    "overall pattern and scale (how many actions, what kind, any notably large or "
    "distinctive ones) rather than repeating each item individually. Produce: a 2-4 "
    "sentence summary in plain English, a category tag, and a one-sentence "
    "significance note (how big a deal this is, and for whom)."
)


def _client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=api_key)


def summarize(
    candidate: Candidate,
    client: Anthropic | None = None,
    cost_tracker: CostTracker | None = None,
) -> Candidate:
    client = client or _client()
    prompt = (
        f"Source: {candidate.source}\nJurisdiction: {candidate.jurisdiction}\n"
        f"Status: {candidate.status or 'n/a'}\nDate: {candidate.date}\n"
        f"Title: {candidate.title}\nURL: {candidate.url}\n"
        f"Text: {candidate.text[:MAX_TEXT_CHARS]}\n"
        f"Triage note: {candidate.triage_reason}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        thinking={"type": "disabled"},
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
        },
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if cost_tracker is not None:
        cost_tracker.record(MODEL, response.usage.input_tokens, response.usage.output_tokens)
    text = next(b.text for b in response.content if b.type == "text")
    parsed = json.loads(text)
    candidate.summary = parsed["summary"]
    candidate.significance = parsed["significance"]
    if parsed["category"] not in candidate.matched_categories:
        candidate.matched_categories.append(parsed["category"])
    return candidate


def summarize_group(
    candidate: Candidate,
    client: Anthropic | None = None,
    cost_tracker: CostTracker | None = None,
) -> Candidate:
    """Like summarize(), but for a grouped Candidate (grouped_items populated) —
    synthesizes one combined summary/significance across all its individual items
    instead of writing one entry per item."""
    client = client or _client()
    items_text = "\n\n".join(
        f"- {item.title.strip()} (status: {item.status or 'n/a'}, {item.date}): "
        f"{item.text[:400]}"
        for item in candidate.grouped_items
    )
    prompt = (
        f"Jurisdiction: {candidate.jurisdiction}\n"
        f"Number of items in this group: {len(candidate.grouped_items)}\n\n"
        f"Items:\n{items_text}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        thinking={"type": "disabled"},
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
        },
        system=GROUP_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if cost_tracker is not None:
        cost_tracker.record(MODEL, response.usage.input_tokens, response.usage.output_tokens)
    text = next(b.text for b in response.content if b.type == "text")
    parsed = json.loads(text)
    candidate.summary = parsed["summary"]
    candidate.significance = parsed["significance"]
    if parsed["category"] not in candidate.matched_categories:
        candidate.matched_categories.append(parsed["category"])
    return candidate


def summarize_all(
    candidates: list[Candidate],
    client: Anthropic | None = None,
    cost_tracker: CostTracker | None = None,
) -> list[Candidate]:
    client = client or _client()
    return [
        summarize_group(c, client=client, cost_tracker=cost_tracker)
        if c.grouped_items
        else summarize(c, client=client, cost_tracker=cost_tracker)
        for c in candidates
    ]
