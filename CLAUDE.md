# Abundance Wins Scanner

## Status: v1 built, deployed, and running on GitHub Actions

The full pipeline (Tier 1 + Tier 2 sources, all three filter stages, digest
publishing, seen-state dedup, cost logging) is implemented and has been run
successfully against live APIs multiple times, including real LLM triage/
summarize calls. As of 2026-08-05:

- **Pushed to GitHub**: private repo at
  `github.com/donjonmaster1/abundance-scanner`, `master` branch.
- **`.env` exists locally only** with real `LEGISCAN_API_KEY` and
  `ANTHROPIC_API_KEY` values (gitignored, never commit it). `LEGISTAR_TOKEN`
  is unset — Legistar's API doesn't require one for the jurisdictions in use.
- **Repository secrets set**: `LEGISCAN_API_KEY` and `ANTHROPIC_API_KEY` are
  configured under Settings → Secrets and variables → Actions.
- **GitHub Actions verified live**: a manual `workflow_dispatch` run
  (2026-08-05) completed successfully end-to-end in 56s and committed
  `digests/`, `state/seen.sqlite`, and `state/cost_log.csv` back to `master`.
  The Friday 15:00 UTC cron should fire on its own from here.
- Email delivery is live (see Stage 3 notes below); static site (v2,
  optional) — not started.

If you're picking this up fresh: the fastest way to understand the system is
to read this file, then run `python -m src.run_weekly --days 7` (needs
`.env` populated) and look at the printed funnel counts and the resulting
`digests/<date>.md`.

## Purpose

A weekly automated system that scans structured legislative/regulatory sources for
"Abundance wins" — local, state, and federal agency actions that represent substantial
steps forward on:

- State capacity (permitting reform, agency staffing/process improvements, procurement reform)
- Housing supply (zoning reform, upzoning, ADU legalization, parking minimum repeal, permitting streamlining)
- Energy supply (siting/permitting reform, transmission approval, interconnection reform)
- Effective service provision (agency modernization, service delivery improvements)

Output: a weekly digest (markdown file) summarizing candidate wins, each with source
link, jurisdiction, one-paragraph summary, and a significance note.

## Budget constraint

Hard ceiling: <$100/year all-in (API costs + compute + LLM costs). Target: $2-10/month.

**Observed real-world cost** (from `state/cost_log.csv`, Claude Haiku 4.5 +
Claude Sonnet 5): a normal 7-day window ran ~$0.02; a 30-day backfill (18
triage survivors, much heavier than a normal week) ran ~$0.12. A weekly
cadence at that rate projects to well under $5/year — LegiScan and Federal
Register API usage are both free-tier and nowhere near their limits (see
"API usage" below). The budget is not a binding constraint at current scale;
don't over-optimize for cost at the expense of triage/summary quality unless
actual spend starts approaching the ceiling.

## Architecture

Three-stage pipeline, orchestrated by `src/run_weekly.py`:

```
1. SOURCE   → src/sources/{legiscan,federal_register,legistar}.py
2. FILTER   → src/filter/{keyword_filter,triage,summarize}.py
3. PUBLISH  → src/publish/digest.py + src/seen_state.py + src/cost_log.py
```

All data flows through the `Candidate` dataclass (`src/models.py`), which
accumulates fields as it moves through the pipeline (matched keywords →
triage verdict → summary).

### Stage 1: Sourcing (all three tiers implemented)

**`src/sources/legiscan.py`** — state legislature bills (LegiScan API, free
tier, 30k queries/month). Two-tier fetch to control API usage:
`getMasterList` once per state (51 calls/week: all 50 states + DC) returns
title/status/date only; `getBill` (fuller detail, including description) is
only called for candidates that survive the keyword filter. Filters to
`status` codes 3 (Enrolled) or 4 (Passed) — see `STATUS_LABELS` /
`PASSED_STATUS_CODES` in that file. This is a deliberate v1 assumption
("focus on passed/enacted actions only"); revisit if it's missing wins that
matter at an earlier stage.

**`src/sources/federal_register.py`** — federal agency rules/notices
(Federal Register API, free, no key). Pulls `type=RULE` and `type=NOTICE`
documents server-side filtered by `publication_date`, using only lightweight
fields (title, abstract, agency, url, date) — full rule text is never
fetched.

**`src/sources/legistar.py`** — municipal ordinances/resolutions ("matters")
via the Legistar OData Web API, across the curated jurisdiction list in
`config/jurisdictions.yaml` (27 client codes, individually verified live
against the real Web API — see that file's header for the verification
method, since `*.legistar.com` returns HTTP 200 for *any* subdomain
including invalid ones, so HTTP status alone doesn't prove a code is real).
Filters on `MatterLastModifiedUtc` for recency. **Does not filter by
status** — Legistar has no cross-jurisdiction status vocabulary (each city
names its own: "Passed", "Adopted", "30 Day Rule", ...), so all matches flow
to keyword filtering and LLM triage, which screen for substance instead.
Titles go through `_clean_title()` in that file — some jurisdictions embed a
full staff-report memo (Subject/From/Recommendation lines) directly in
`MatterTitle` instead of a plain title, so the raw field can't just be
truncated blindly.

Legistar data quality varies by tenant — some client codes in
`jurisdictions.yaml` may point to low-activity or stale tenants even though
the code itself is a real, live Legistar client. Spot-check periodically.

In practice, Legistar currently dominates the weekly hit count (municipal
zoning/rezoning actions are common and match the housing keywords well);
LegiScan and Federal Register contribute far fewer. This is expected given
LegiScan's conservative status filter and the tightened Federal Register
keyword list — not a bug — but worth knowing if the digest reads as
"mostly municipal zoning."

### Stage 2: Filtering

1. **`src/filter/keyword_filter.py`** — free, local, word-boundary regex
   match against `config/keywords.yaml` (tagged by category: state_capacity,
   housing_supply, energy_supply, service_provision). Matches on title + the
   available text (abstract/description/title depending on source).

   **Tuning note:** the keyword list has already been empirically tightened
   once — `"paperwork reduction"` alone used to match ~94 of ~102 Federal
   Register survivors in one real test, because it's boilerplate language in
   nearly every routine Paperwork-Reduction-Act information-collection
   notice, not a sign of actual reform. It was replaced with more specific
   phrases (`"reduces paperwork burden"`, `"cuts red tape"`). If a keyword
   is producing a similarly lopsided survivor count, that's the pattern to
   check for — grep survivor counts per matched keyword before assuming the
   LLM triage stage will clean it up for free.

2. **`src/filter/triage.py`** — Claude Haiku 4.5 (`claude-haiku-4-5`),
   batched (10 candidates/request), structured JSON output
   (`output_config.format` with a `json_schema`) rather than free-text
   parsing. Returns WIN/NOT + one-line reason per candidate.

3. **`src/filter/summarize.py`** — Claude Sonnet 5 (`claude-sonnet-5`), one
   call per triage survivor, also structured JSON output. Thinking is
   explicitly disabled (`thinking: {"type": "disabled"}`) with
   `effort: "low"` — these are short, well-scoped writing tasks and Sonnet 5
   thinks by default when `thinking` is omitted, which isn't worth the extra
   spend here. Do not remove the explicit disable without a reason.

   **Known soft spot:** the `service_provision` category is the vaguest of
   the four and has let through some fairly minor items (e.g. an agency
   switching from paper checks to electronic payments). If this keeps
   happening across multiple runs, tighten `SYSTEM_PROMPT` in `triage.py` to
   exclude routine IT/payment-system modernization rather than touching the
   keyword list — the keyword filter did its job correctly in that case.

Both `triage_batch()` and `summarize_all()`/`summarize()` accept an optional
`cost_tracker: CostTracker` and record token usage via `response.usage` —
always pass one through from `run_weekly.py`, don't call them bare in new
code paths.

### Stage 3: Publishing

- **`src/publish/digest.py`** — writes `digests/<run_date>.md`, grouped by
  category. **The filename is dated by the run date, not the `--days`
  lookback window** — running `--days 30` today overwrites the same-day
  `--days 7` digest from earlier today. This is intentional (there's one
  digest per calendar day the job runs) but worth knowing before re-running
  with a different window on the same day if you want to keep the earlier
  output.
- **`src/seen_state.py`** — `state/seen.sqlite`, a single `seen` table keyed
  on `Candidate.id` (e.g. `legiscan:1234567`, `fedreg:2026-15920`,
  `legistar:oakland:37309`). **Every keyword-filter survivor is marked seen,
  not just triage winners** — this is deliberate, so a rejected candidate
  doesn't get re-sent through paid LLM triage every subsequent week. The
  sqlite file is committed to git (not gitignored) so state persists across
  GitHub Actions runs.
- **`src/cost_log.py`** — appends per-run, per-model token/cost rows to
  `state/cost_log.csv` with a running grand total. Pricing constants
  (`PRICING` dict) are standard (non-introductory) per-1M-token rates,
  checked 2026-08-05 — re-verify against current Anthropic pricing if this
  file is being revisited long after that date.
- **`src/publish/email_digest.py`** (added 2026-08-05, live as of
  2026-08-10) — emails the same candidates that go into the markdown
  digest, as HTML, via the Resend API (`https://api.resend.com/emails`).
  Recipients come from `subscribers:` in `config/subscribers.yaml` — a
  plain list of addresses committed to this (private) repo; add/remove
  addresses by editing that file directly (then commit + push — GitHub
  Actions reads the pushed repo state, not your local disk). Sent as a
  single Resend call with `to` set to `EMAIL_FROM` itself and the real
  recipient list in `bcc`, so subscribers never see each other's addresses.
  `EMAIL_FROM` is `digest@scanner.abundancecorps.org` — a subdomain of a
  domain owned by a collaborator, verified in Resend via DNS records (SPF +
  DKIM) added by them. Confirmed working with a real test send on
  2026-08-10. Requires `RESEND_API_KEY` and `EMAIL_FROM`, both set locally
  in `.env` and as GitHub repo secrets. Best-effort by design (never
  raises) — a missing/broken email step logs a warning but can't fail the
  digest/seen-state/cost-log parts of the run.
  - **Dead end worth knowing about**: Resend's shared sender
    (`onboarding@resend.com`) cannot be used at all without *some* verified
    domain — there's no sandbox/test-mode exception that lets it deliver
    even to a single address. Confirmed via a live 403
    (`"The resend.com domain is not verified"`). Don't reach for it as a
    stopgap; a verified domain (or subdomain) is the only path that works.

## Repo structure (actual)

```
abundance-scanner/
├── CLAUDE.md
├── .env                        # gitignored; real keys, not committed
├── .env.example
├── .gitignore
├── requirements.txt
├── config/
│   ├── keywords.yaml
│   ├── jurisdictions.yaml      # 27 verified Legistar client codes
│   └── subscribers.yaml        # digest email mailing list (plain addresses)
├── src/
│   ├── models.py                # Candidate dataclass — the shared pipeline object
│   ├── cost_log.py
│   ├── seen_state.py
│   ├── run_weekly.py            # orchestrator / CLI entry point
│   ├── sources/
│   │   ├── legiscan.py
│   │   ├── federal_register.py
│   │   └── legistar.py
│   ├── filter/
│   │   ├── keyword_filter.py
│   │   ├── triage.py            # Haiku pass
│   │   └── summarize.py         # Sonnet pass
│   └── publish/
│       ├── digest.py
│       └── email_digest.py      # Resend email delivery, live as of 2026-08-10
├── state/
│   ├── seen.sqlite               # committed — cross-run dedup state
│   └── cost_log.csv              # committed — running spend log
├── digests/
│   └── YYYY-MM-DD.md             # one per run date
└── .github/
    └── workflows/
        └── weekly_scan.yml       # Friday 15:00 UTC cron + workflow_dispatch
```

## Running it

```
pip install -r requirements.txt
cp .env.example .env     # fill in LEGISCAN_API_KEY, ANTHROPIC_API_KEY
python -m src.run_weekly --days 7          # normal weekly run
python -m src.run_weekly --days 7 --dry-run  # sources + keyword filter only, no LLM calls, no digest write
```

`--dry-run` is the cheap way to sanity-check source/keyword-filter changes
(new keywords, new jurisdictions, source bugs) without spending on Haiku/
Sonnet calls.

## GitHub Actions setup checklist (done, 2026-08-05)

1. ✅ `git init`, commit, create a GitHub repo, push — private repo at
   `github.com/donjonmaster1/abundance-scanner`.
2. ✅ Repo Settings → Secrets and variables → Actions → `LEGISCAN_API_KEY`
   and `ANTHROPIC_API_KEY` added.
3. ✅ Actions tab → "Weekly Abundance Wins Scan" → Run workflow — manual
   `workflow_dispatch` test run completed successfully (run 31026801382,
   56s).
4. ✅ Confirmed the workflow commits `digests/`, `state/seen.sqlite`, and
   `state/cost_log.csv` back to the repo (see the "Commit digest, seen-state,
   and cost log" step in `.github/workflows/weekly_scan.yml`) — verified via
   the auto-pushed commit from the test run.

Cost note: `ubuntu-latest` runner, weekly schedule, a few minutes per run —
free on a public repo (unlimited Actions minutes) and trivially within the
2,000 free minutes/month on a private repo. Not a budget concern either way.

## Open questions / things to revisit

- **Jurisdiction list curation**: `config/jurisdictions.yaml` has 27 verified
  Legistar codes (DC-area + national sample). Prune low-signal ones and add
  new ones as real-world digest output reveals which jurisdictions actually
  produce Abundance-relevant matters.
- **LegiScan status filter** (`PASSED_STATUS_CODES = {3, 4}`): an assumption,
  not verified against LegiScan's own docs at build time beyond training
  knowledge. If passed/enacted bills seem to be getting missed, this is the
  first place to check.
- **`service_provision` triage looseness**: see Stage 2 notes above.
- **Legistar/Phoenix over-representation**: a single active jurisdiction
  with many small rezonings can dominate a digest. Consider whether digest
  output should be capped or re-ranked per jurisdiction if this becomes a
  recurring pattern — not implemented, no strong opinion yet on whether it's
  actually a problem versus just how the data looks.
- **Email delivery**: live as of 2026-08-10, sending from
  `digest@scanner.abundancecorps.org` (a subdomain of a collaborator-owned
  domain, verified in Resend). Only one subscriber so far
  (`ate20@georgetown.edu`) — add more by editing `config/subscribers.yaml`
  and pushing. See Stage 3 notes above.
- **Static site (v2)**: out of scope, not started.
