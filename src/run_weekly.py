"""Orchestrates the full weekly pipeline: source -> filter -> publish.

Run manually with `python -m src.run_weekly` or via the GitHub Actions cron
job (.github/workflows/weekly_scan.yml).
"""

import argparse
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.cost_log import CostTracker
from src.filter.group import group_candidates
from src.filter.keyword_filter import filter_candidates
from src.filter.summarize import summarize_all
from src.filter.triage import triage_batch
from src.models import Candidate
from src.publish.digest import write_digest
from src.publish.email_digest import send_digest_email
from src.seen_state import SeenStore
from src.sources import federal_register, legiscan, legistar


def collect_candidates(days: int) -> list[Candidate]:
    candidates: list[Candidate] = []

    try:
        candidates.extend(federal_register.get_recent_candidates(days=days))
    except Exception as exc:  # keep other sources running even if one fails
        print(f"[run_weekly] federal_register source failed: {exc}")

    try:
        candidates.extend(legiscan.get_recent_candidates(days=days))
    except Exception as exc:
        print(f"[run_weekly] legiscan source failed: {exc}")

    try:
        candidates.extend(legistar.get_recent_candidates(days=days))
    except Exception as exc:
        print(f"[run_weekly] legistar source failed: {exc}")

    return candidates


def run(days: int = 7, dry_run: bool = False) -> None:
    load_dotenv()
    run_date = datetime.now(timezone.utc).date().isoformat()
    cost_tracker = CostTracker()

    print(f"[run_weekly] collecting candidates from the last {days} day(s)...")
    raw_candidates = collect_candidates(days)
    print(f"[run_weekly] {len(raw_candidates)} raw candidates")

    keyword_survivors = filter_candidates(raw_candidates)
    print(f"[run_weekly] {len(keyword_survivors)} survive keyword pre-filter")

    with SeenStore() as seen:
        unseen_ids = set(seen.filter_unseen([c.id for c in keyword_survivors]))
        keyword_survivors = [c for c in keyword_survivors if c.id in unseen_ids]
        print(f"[run_weekly] {len(keyword_survivors)} unseen after dedup")

        if dry_run:
            print("[run_weekly] dry run — skipping LLM stages and digest write")
            return

        if not keyword_survivors:
            write_digest([], run_date)
            send_digest_email([], run_date)
            print("[run_weekly] no candidates this week; empty digest written")
            return

        # Enrich LegiScan survivors with a fuller bill description before triage —
        # getMasterList only gives us a title.
        for c in keyword_survivors:
            if c.source == "legiscan":
                try:
                    legiscan.enrich_with_detail(c)
                except Exception as exc:
                    print(f"[run_weekly] failed to enrich {c.id}: {exc}")

        triage_survivors = triage_batch(keyword_survivors, cost_tracker=cost_tracker)
        print(f"[run_weekly] {len(triage_survivors)} survive Haiku triage")

        digest_entries = group_candidates(triage_survivors)
        if len(digest_entries) != len(triage_survivors):
            print(f"[run_weekly] grouped into {len(digest_entries)} digest entries")

        summarize_all(digest_entries, cost_tracker=cost_tracker)

        digest_path = write_digest(digest_entries, run_date)
        print(f"[run_weekly] digest written to {digest_path}")
        send_digest_email(digest_entries, run_date)

        # Mark every keyword survivor seen (not just triage winners) so rejected
        # items aren't re-spent on next week.
        seen.mark_seen(list(unseen_ids))

    cost_tracker.write_run_summary(run_date)
    print(f"[run_weekly] estimated LLM spend this run: ${cost_tracker.total_cost:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Abundance Wins weekly scan.")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Source + keyword-filter only; skip LLM calls and digest write",
    )
    args = parser.parse_args()
    run(days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
