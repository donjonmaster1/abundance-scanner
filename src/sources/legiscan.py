"""LegiScan source: state-legislature bills with recent status changes.

Two-tier fetch to control API usage: getMasterList (cheap, title-only) for all
tracked states, then getBill (fuller detail) only for candidates that survive
local keyword filtering — see CLAUDE.md Stage 1/Stage 2.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import requests

from src.models import Candidate

API_BASE = "https://api.legiscan.com/"

# All 50 states + DC. LegiScan uses standard USPS 2-letter codes.
STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
]

# LegiScan bill status codes: 1=Introduced, 2=Engrossed, 3=Enrolled, 4=Passed,
# 5=Vetoed, 6=Failed. 3/4 are treated as "enacted-ish" per CLAUDE.md's "v1
# should focus on passed/enacted actions only" — tune based on observed
# false positive/negative rate.
STATUS_LABELS = {
    1: "Introduced",
    2: "Engrossed",
    3: "Enrolled",
    4: "Passed",
    5: "Vetoed",
    6: "Failed",
}
PASSED_STATUS_CODES = {3, 4}

REQUEST_DELAY_SECONDS = 0.2  # be polite; well within the 30k/month free tier


def _api_key() -> str:
    key = os.environ.get("LEGISCAN_API_KEY")
    if not key:
        raise RuntimeError("LEGISCAN_API_KEY is not set")
    return key


def _call(op: str, **params) -> dict:
    query = {"key": _api_key(), "op": op, **params}
    resp = requests.get(API_BASE, params=query, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK":
        raise RuntimeError(f"LegiScan API error for op={op}: {data}")
    return data


def fetch_master_list(state: str) -> dict:
    """Raw getMasterList response for one state, keyed by an internal index."""
    data = _call("getMasterList", state=state)
    masterlist = data.get("masterlist", {})
    return {k: v for k, v in masterlist.items() if k != "session"}


def get_recent_candidates(days: int = 7, states: list[str] | None = None) -> list[Candidate]:
    """Pull bills across all tracked states whose last action fell within the
    last `days` days. Text is the bill title only — getMasterList doesn't
    include a description; call enrich_with_detail() on keyword survivors
    before running them through triage/summarize.
    """
    states = states or STATES
    _api_key()  # fail fast with one clear error instead of once per state
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    candidates: list[Candidate] = []

    for state in states:
        try:
            bills = fetch_master_list(state)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"[legiscan] skipping {state}: {exc}")
            continue
        time.sleep(REQUEST_DELAY_SECONDS)

        for bill in bills.values():
            last_action_date = bill.get("last_action_date")
            if not last_action_date:
                continue
            try:
                action_date = datetime.strptime(last_action_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if action_date < cutoff:
                continue
            if bill.get("status") not in PASSED_STATUS_CODES:
                continue

            candidates.append(
                Candidate(
                    id=f"legiscan:{bill['bill_id']}",
                    source="legiscan",
                    title=bill.get("title", ""),
                    jurisdiction=state,
                    url=bill.get("url", ""),
                    text=bill.get("title", ""),
                    date=last_action_date,
                    status=STATUS_LABELS.get(bill.get("status"), str(bill.get("status", ""))),
                )
            )

    return candidates


def enrich_with_detail(candidate: Candidate) -> Candidate:
    """Fetch the fuller bill record (description) for a keyword-filter survivor.
    Only call after keyword_filter has narrowed the candidate set — getBill is
    a heavier call than getMasterList.
    """
    bill_id = candidate.id.split(":", 1)[1]
    data = _call("getBill", id=bill_id)
    bill = data.get("bill", {})
    candidate.text = bill.get("description") or bill.get("title") or candidate.text
    time.sleep(REQUEST_DELAY_SECONDS)
    return candidate
