#!/usr/bin/env python3
"""
NudgePilot - job-search ghosting nudger agentic workflow + memory & advisor.

Command-line demo / runner for the All Things Agentic Hackathon (Taskmaster).

Usage:
  python nudgepilot_cli.py seed                       # seed dev store
  python nudgepilot_cli.py auto                       # seed + run (deterministic demo)
  python nudgepilot_cli.py run                        # run one full tick + digest
  python nudgepilot_cli.py memory --firm "Nimbus Labs"  # full firm history + next steps

Backends:
  default 'offline' -> deterministic, zero-credential demo.
  Explicitly pass --backend google on 'run'/'memory' (or set GOOGLE_API_KEY) to
  use real Gemini (google-genai). The 'auto' demo path STAYS OFFLINE even if a key
  is present in .env, so a reproducible credential-free demo is always one command away.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

try:  # pragma: no cover - optional .env loader
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

if not os.getenv("PYTHONPATH"):  # pragma: no cover - direct-run convenience
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.store import build_store
from core.llm import build_backend
from core.domain import InboxEmail, Interaction, InteractionKind
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

    auto_p = sub.add_parser("auto", help="seed + run (deterministic demo)")
    auto_p.add_argument("--store", default="memory")
    auto_p.add_argument("--backend", default=None)
    auto_p.add_argument("--drafts-to-disk", action="store_true", help="write .eml drafts to disk")

    mem_p = sub.add_parser("memory", help="show full history + next steps for a firm")
    mem_p.add_argument("--firm", required=True, help="company name, e.g. 'Nimbus Labs'")
    mem_p.add_argument("--store", default="memory", choices=["memory", "firestore"])
    mem_p.add_argument("--backend", default="offline", help="google|offline")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.cmd == "seed":
        store = build_store(args.store)
        seed_store(store)
        print(f"[seed] wrote {len(store.list_apps())} applications to store='{args.store}'")
        return 0

    if args.cmd == "memory":
        _run_memory(args)
        return 0

    # ---- run / auto ----
    store = build_store(args.store)
    if args.cmd == "auto":
        seed_store(store)
        print(f"[auto] seeded {len(store.list_apps())} applications")

    # The 'auto' path stays on the deterministic OFFLINE backend unless --backend google
    # is explicitly passed, so a machine with GOOGLE_API_KEY in .env still gives a
    # reproducible, credential-free demo. The 'run' command auto-detects.
    backend = build_backend("offline" if args.cmd == "auto" else args.backend)
    sink = GmailDraftSink() if getattr(args, "drafts_to_disk", False) else MemoryDraftSink()
    pilot = NudgePilot(store=store, backend=backend, sink=sink)

    # ingest a batch of realistic inbound replies (the 'inbox watcher' event)
    _apps, _emails = seed_store(store, now=_dt.datetime.now(_dt.timezone.utc))
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
          f"classified={len(digest.classified)} "
          f"responses={len(digest.new_responses)} "
          f"recommendations={len(digest.recommendations)} errors={len(digest.errors)}")
    return 0


def _run_memory(args) -> None:
    """The 'remember your history + next steps' command for one firm."""
    store = build_store(args.store)
    # ensure the demo firms exist if the store is empty
    if not store.list_apps():
        seed_store(store)
        print(f"[memory] seeded {len(store.list_apps())} applications (store was empty)")
    backend = build_backend(args.backend or "offline")
    pilot = NudgePilot(store=store, backend=backend, sink=MemoryDraftSink())
    fm = pilot.memory_for_firm(args.firm)
    if fm.company == "":
        print(f"No applications found for firm '{args.firm}'.")
        print("Known firms:", ", ".join(sorted({a.company for a in store.list_apps()})))
        return
    print("=" * 60)
    print(f"MEMORY · {fm.company}  (latest status: {fm.latest_status})")
    print("=" * 60)
    print("\nSUMMARY")
    print("-" * 40)
    print(fm.summary)
    print("\nTIMELINE OF INTERACTIONS")
    print("-" * 40)
    if not fm.timeline:
        print("  (no recorded interactions)")
    for t in fm.timeline:
        print(f"  [{t['at']}] {t['direction']} {t['kind']}"
              + (f" ({t['classification']})" if t.get('classification') else "")
              + (f" - {t['detail']}" if t.get('detail') else ""))
    print("\nAPPLICATIONS")
    print("-" * 40)
    for a in fm.applications:
        print(f"  * {a['role']} (status: {a['status']}, nudges sent: {a['nudges_sent']})")
    print("\nNEXT BEST STEPS")
    print("-" * 40)
    for rec in sorted(
        pilot.recommendation_agent.recommend_all(
            [store.get_app(a['id']) for a in fm.applications],
            _dt.datetime.now(_dt.timezone.utc),
        ),
        key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r.priority, 3),
    ):
        print(f"  * [{rec.priority.upper()}] {rec.action}")
        print(f"      ({rec.company} / {rec.role}) - {rec.why}")


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