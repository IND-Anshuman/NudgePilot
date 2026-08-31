#!/usr/bin/env python3
"""
NudgePilot - job-search ghosting nudger agentic workflow.

Command-line demo / runner for the All Things Agentic Hackathon (Taskmaster).

Usage:
  python nudgepilot_cli.py seed [--days 0]      # seed dev store
  python nudgepilot_cli.py run [--store memory] # run one full tick + digest
  python nudgepilot_cli.py auto                 # seed + run (demo path)

Backends: default 'offline' (zero-credential deterministic LLM). Set
GOOGLE_API_KEY / GOOGLE_GENAI_USE_VERTEXAI=1 to use real Gemini.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys

from core.store import build_store
from core.llm import build_backend
from core.domain import InboxEmail
from orchestrator import NudgePilot, MemoryDraftSink
from delivery.gmail_sink import GmailDraftSink
from seed import seed_store


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NudgePilot job-ghosting nudger agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    seed_p = sub.add_parser("seed", help="seed the store with demo applications")
    seed_p.add_argument("--store", default="memory", choices=["memory", "firestore"])

    run_p = sub.add_parser("run", help="run one full NudgePilot tick")
    run_p.add_argument("--store", default="memory", choices=["memory", "firestore"])
    run_p.add_argument("--backend", default=None, help="google|offline (default auto)")
    run_p.add_argument("--drafts-to-disk", action="store_true", help="write .eml drafts to disk")

    auto_p = sub.add_parser("auto", help="seed + run (demo path)")
    auto_p.add_argument("--store", default="memory")
    auto_p.add_argument("--backend", default=None)
    auto_p.add_argument("--drafts-to-disk", action="store_true", help="write .eml drafts to disk")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.cmd == "seed":
        store = build_store(args.store)
        seed_store(store)
        print(f"[seed] wrote {len(store.list_apps())} applications to store='{args.store}'")
        return 0

    # run / auto
    store = build_store(args.store)
    if args.cmd == "auto":
        seed_store(store)
        print(f"[auto] seeded {len(store.list_apps())} applications")

    backend = build_backend(args.backend)
    sink = GmailDraftSink() if getattr(args, "drafts_to_disk", False) else MemoryDraftSink()
    pilot = NudgePilot(store=store, backend=backend, sink=sink)

    # ingest a batch of realistic inbound replies (the 'inbox watcher' event)
    _apps, emails = seed_store(store, now=_dt.datetime.now(_dt.timezone.utc))
    reply_batch = _demo_replies()
    pilot.ingest_emails(reply_batch)

    digest = pilot.run_tick()
    print("\n" + "=" * 60)
    print("ACTION LOG")
    print("=" * 60)
    for line in digest.action_log:
        print("  " + line)
    print("\n" + "=" * 60)
    print("DIGEST")
    print("=" * 60)
    print(pilot.build_digest_text())
    print("\n" + "=" * 60)
    print(f"[done] drafted={len(digest.drafted)} ghosted={len(digest.ghosted)} "
          f"classified={len(digest.classified)} errors={len(digest.errors)}")
    return 0


def _demo_replies() -> list[InboxEmail]:
    """Small, self-contained inbound email batch used for the demo tick."""
    now = _dt.datetime.now(_dt.timezone.utc)
    spec = [
        ("Acme Analytics", "Data Analyst", "recruiter@acmeanalytics.com",
         "Job application update",
         "Thanks for your interest, unfortunately we have decided to move "
         "forward with other candidates this time."),
        ("Nimbus Labs", "ML Engineer", "t.nguyen@nimbuslabs.dev",
         "Interview invitation - ML Engineer",
         "We were very impressed and would love to schedule an interview this week."),
        ("Hexmark", "Frontend Engineer", "alex@hexmark.co",
         "Status update",
         "Thanks for your patience, we are still reviewing shortlists and hope to "
         "update you within a week."),
    ]
    return [
        InboxEmail(
            id=f"demo_{i}", from_addr=fr, subject=sub, snippet=sni,
            body=sni, received_at=now - _dt.timedelta(minutes=8),
        )
        for i, (_c, _r, fr, sub, sni) in enumerate(spec)
    ]


if __name__ == "__main__":
    raise SystemExit(main())