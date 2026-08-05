"""Federal Register source: final rules + notices published in the last 7 days.

Free, no API key required. Pulls only lightweight fields (title, abstract,
agency, url, date) — full rule text is never fetched, matching CLAUDE.md's
"use the abstract field for pre-filtering, not full text."
"""

from datetime import datetime, timedelta, timezone

import requests

from src.models import Candidate

API_BASE = "https://www.federalregister.gov/api/v1/documents.json"
DOC_TYPES = ["RULE", "NOTICE"]
FIELDS = ["title", "abstract", "html_url", "publication_date", "agencies", "type", "document_number"]
PER_PAGE = 1000


def get_recent_candidates(days: int = 7) -> list[Candidate]:
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    params = {
        "conditions[type][]": DOC_TYPES,
        "conditions[publication_date][gte]": cutoff,
        "per_page": PER_PAGE,
        "order": "newest",
        "fields[]": FIELDS,
    }

    candidates: list[Candidate] = []
    page = 1
    while True:
        resp = requests.get(API_BASE, params={**params, "page": page}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        for doc in results:
            agencies = ", ".join(a.get("name", "") for a in doc.get("agencies", []) if a.get("name"))
            candidates.append(
                Candidate(
                    id=f"fedreg:{doc['document_number']}",
                    source="federal_register",
                    title=doc.get("title", ""),
                    jurisdiction=f"US Federal — {agencies}" if agencies else "US Federal",
                    url=doc.get("html_url", ""),
                    text=doc.get("abstract") or "",
                    date=doc.get("publication_date", ""),
                    status=doc.get("type", ""),
                )
            )

        if not data.get("next_page_url"):
            break
        page += 1

    return candidates
