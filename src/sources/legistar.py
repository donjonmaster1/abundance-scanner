"""Legistar source (Tier 2): municipal ordinances/resolutions ("matters") with
recent action, across the curated jurisdiction list in config/jurisdictions.yaml.

Unlike LegiScan, Legistar has no cross-jurisdiction status vocabulary — each
city/county names its own statuses ("Passed", "Adopted", "30 Day Rule", ...) —
so this source does not filter by status the way legiscan.py does. All matches
flow to keyword filtering and Haiku/Sonnet triage, which screen for substance.

Liveness varies by client: some jurisdictions in jurisdictions.yaml may be
sandbox/inactive Legistar tenants even though the client code itself is valid
(verified live against the Web API, see that file's header comment) — spot
check MatterLastModifiedUtc periodically and prune dead ones.
"""

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

from src.models import Candidate

API_BASE = "https://webapi.legistar.com/v1"
JURISDICTIONS_PATH = Path(__file__).resolve().parents[2] / "config" / "jurisdictions.yaml"
REQUEST_DELAY_SECONDS = 0.3
PAGE_SIZE = 1000
TITLE_MAX_LEN = 200

_SUBJECT_LINE_RE = re.compile(r"^\s*subject\s*:\s*(.*)$", re.IGNORECASE)
_MEMO_FIELD_RE = re.compile(r"^\s*(from|recommendation|sponsors?|department|division|to)\s*:", re.IGNORECASE)


def load_jurisdictions(path: Path = JURISDICTIONS_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    jurisdictions = []
    for group in data.values():
        jurisdictions.extend(group)
    return jurisdictions


def _detail_url(code: str, matter_id: int, matter_guid: str) -> str:
    return f"https://{code}.legistar.com/LegislationDetail.aspx?ID={matter_id}&GUID={matter_guid}"


def _clean_title(raw: str, max_len: int = TITLE_MAX_LEN) -> str:
    """Some Legistar jurisdictions put a full staff-report memo (Subject/From/
    Recommendation lines) into MatterTitle instead of a plain title; others
    just have a long plain sentence. Extract the Subject line when present,
    otherwise use the whole text, then collapse whitespace and truncate at a
    word boundary instead of mid-word.
    """
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    subject_lines: list[str] = []
    in_subject = False
    found_subject = False

    for line in lines:
        subject_match = _SUBJECT_LINE_RE.match(line)
        if subject_match:
            found_subject = True
            in_subject = True
            subject_lines.append(subject_match.group(1))
            continue
        if in_subject:
            if _MEMO_FIELD_RE.match(line):
                break
            subject_lines.append(line)

    text = " ".join(subject_lines) if found_subject else raw
    text = " ".join(text.split())

    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0].rstrip(",;: ") + "…"
    return text


def get_recent_candidates(days: int = 7, jurisdictions: list[dict] | None = None) -> list[Candidate]:
    jurisdictions = jurisdictions if jurisdictions is not None else load_jurisdictions()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    candidates: list[Candidate] = []

    for j in jurisdictions:
        code = j["code"]
        url = f"{API_BASE}/{code}/matters"
        params = {
            "$filter": f"MatterLastModifiedUtc ge datetime'{cutoff}'",
            "$orderby": "MatterLastModifiedUtc desc",
            "$top": PAGE_SIZE,
        }
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            matters = resp.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"[legistar] skipping {code}: {exc}")
            continue
        time.sleep(REQUEST_DELAY_SECONDS)

        for matter in matters:
            text = matter.get("MatterTitle") or matter.get("MatterName") or ""
            if not text:
                continue
            last_modified = matter.get("MatterLastModifiedUtc") or ""
            candidates.append(
                Candidate(
                    id=f"legistar:{code}:{matter['MatterId']}",
                    source="legistar",
                    title=matter.get("MatterName") or _clean_title(text),
                    jurisdiction=f"{j['name']}, {j['state']}",
                    url=_detail_url(code, matter["MatterId"], matter.get("MatterGuid", "")),
                    text=text,
                    date=last_modified[:10] if last_modified else "",
                    status=matter.get("MatterStatusName", ""),
                )
            )

    return candidates
