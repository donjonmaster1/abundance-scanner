"""Emails the weekly digest to the mailing list in config/subscribers.yaml via
Resend. Best-effort: a missing API key, missing sender, or send failure logs
a warning and does not raise — the digest file and seen-state are already
written by this point, so a broken email step shouldn't fail the whole run.
"""

import html
import os
from pathlib import Path

import requests
import yaml

from src.models import Candidate
from src.publish.digest import CATEGORY_LABELS, SOURCE_LABELS

SUBSCRIBERS_PATH = Path(__file__).resolve().parents[2] / "config" / "subscribers.yaml"
RESEND_API_URL = "https://api.resend.com/emails"


def load_subscribers(path: Path = SUBSCRIBERS_PATH) -> list[str]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("subscribers") or []


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _entry_html(c: Candidate) -> str:
    source_label = SOURCE_LABELS.get(c.source, c.source)
    return f"""
    <div style="margin-bottom:20px;">
      <h3 style="margin:0 0 6px;"><a href="{_esc(c.url)}">{_esc(c.title.strip())}</a></h3>
      <p style="margin:2px 0;"><b>Jurisdiction:</b> {_esc(c.jurisdiction)}</p>
      <p style="margin:2px 0;"><b>Source:</b> {_esc(source_label)}</p>
      <p style="margin:2px 0;"><b>Status:</b> {_esc(c.status or 'n/a')} (as of {_esc(c.date)})</p>
      <p style="margin:8px 0;">{_esc(c.summary)}</p>
      <p style="margin:2px 0;"><i>Why it matters:</i> {_esc(c.significance)}</p>
    </div>"""


def build_digest_html(candidates: list[Candidate], run_date: str) -> str:
    by_category: dict[str, list[Candidate]] = {}
    for c in candidates:
        category = c.matched_categories[0] if c.matched_categories else "uncategorized"
        by_category.setdefault(category, []).append(c)

    parts = [f"<h1>Abundance Wins &mdash; {_esc(run_date)}</h1>"]
    if not candidates:
        parts.append("<p>No candidate wins cleared triage this week.</p>")
        return "".join(parts)

    parts.append(f"<p>{len(candidates)} win(s) this week.</p>")
    for category in sorted(by_category, key=lambda k: CATEGORY_LABELS.get(k, k)):
        label = CATEGORY_LABELS.get(category, category.replace("_", " ").title())
        entries = sorted(by_category[category], key=lambda c: c.date, reverse=True)
        parts.append(f"<h2>{_esc(label)}</h2>")
        parts.extend(_entry_html(c) for c in entries)

    return "".join(parts)


def send_digest_email(candidates: list[Candidate], run_date: str) -> None:
    subscribers = load_subscribers()
    if not subscribers:
        print("[email_digest] no subscribers configured; skipping email")
        return

    api_key = os.environ.get("RESEND_API_KEY")
    email_from = os.environ.get("EMAIL_FROM")
    if not api_key or not email_from:
        print("[email_digest] RESEND_API_KEY/EMAIL_FROM not set; skipping email")
        return

    payload = {
        "from": email_from,
        "to": email_from,
        "bcc": subscribers,
        "subject": f"Abundance Wins — {run_date}",
        "html": build_digest_html(candidates, run_date),
    }
    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        print(f"[email_digest] sent digest to {len(subscribers)} subscriber(s)")
    except requests.RequestException as exc:
        print(f"[email_digest] failed to send digest email: {exc}")
