"""Cheap Haiku triage pass: tight WIN/NOT + one-line-reason for keyword survivors.

Batches multiple candidates into a single request to keep call overhead down.
Uses title + short summary text only — never full bill/rule text.
"""

import json
import os

from anthropic import Anthropic

from src.cost_log import CostTracker
from src.models import Candidate

MODEL = "claude-haiku-4-5"
BATCH_SIZE = 10
MAX_TEXT_CHARS = 600

SYSTEM_PROMPT = (
    'You triage legislative/regulatory items for a weekly "Abundance wins" digest. '
    "An Abundance win is a substantial, concrete step forward on: state capacity "
    "(permitting reform, agency staffing/process improvements, procurement reform), "
    "housing supply (zoning reform, upzoning, ADU legalization, parking minimum repeal, "
    "permitting streamlining), energy supply (siting/permitting reform, transmission "
    "approval, interconnection reform), or effective service provision (agency "
    "modernization, service delivery improvements). Introduced-but-not-yet-passed bills "
    "and purely symbolic actions are NOT wins. For each numbered item, answer WIN or NOT "
    "and give one short sentence why."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["WIN", "NOT"]},
                    "reason": {"type": "string"},
                },
                "required": ["index", "verdict", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def _client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=api_key)


def _build_prompt(batch: list[Candidate]) -> str:
    lines = []
    for i, c in enumerate(batch):
        lines.append(
            f"{i}. [{c.source} | {c.jurisdiction} | status: {c.status or 'n/a'}]\n"
            f"Title: {c.title}\nSummary: {c.text[:MAX_TEXT_CHARS]}"
        )
    return "\n\n".join(lines)


def triage_batch(
    candidates: list[Candidate],
    client: Anthropic | None = None,
    cost_tracker: CostTracker | None = None,
) -> list[Candidate]:
    """Run Haiku triage over candidates in batches. Mutates each candidate's
    triage_verdict/triage_reason and returns the WIN survivors."""
    client = client or _client()
    survivors: list[Candidate] = []

    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start : start + BATCH_SIZE]
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": _build_prompt(batch)}],
        )
        if cost_tracker is not None:
            cost_tracker.record(MODEL, response.usage.input_tokens, response.usage.output_tokens)
        text = next(b.text for b in response.content if b.type == "text")
        parsed = json.loads(text)
        for result in parsed["results"]:
            candidate = batch[result["index"]]
            candidate.triage_verdict = result["verdict"]
            candidate.triage_reason = result["reason"]
            if result["verdict"] == "WIN":
                survivors.append(candidate)

    return survivors
