# Tests for the interaction memory, response-monitor, firm-memory & recommendation features.
"""Run:  python -m unittest discover -s tests"""

from __future__ import annotations

import datetime as _dt
import unittest

from core.domain import (
    Application, InboxEmail, Interaction, InteractionKind,
    ReplyKind, Status,
)
from core.store import InMemoryStore
from core.llm import OfflineBackend, _timeline_summary
from orchestrator import NudgePilot, MemoryDraftSink
from agents.history_agent import HistoryAgent
from agents.recommendation_agent import RecommendationAgent
from seed import seed_store


def _utc(y, m, d, h=0):
    return _dt.datetime(y, m, d, h, tzinfo=_dt.timezone.utc)


class InteractionMemoryTest(unittest.TestCase):
    def test_logging_applied_interaction_sorted(self):
        store = InMemoryStore()
        app = Application(id="a1", company="Acme", role="Dev", source="LinkedIn",
                          applied_at=_utc(2026, 8, 1))
        store.upsert_app(app)
        old = Interaction(kind=InteractionKind.APPLIED, at=_utc(2026, 8, 1))
        new = Interaction(kind=InteractionKind.REPLY, at=_utc(2026, 8, 5))
        store.log_interaction("a1", new)
        store.log_interaction("a1", old)
        got = store.get_app("a1").interactions
        self.assertEqual([i.at for i in got], [_utc(2026, 8, 1), _utc(2026, 8, 5)])

    def test_firm_history_filters_by_company(self):
        store = InMemoryStore()
        store.upsert_app(Application(id="a", company="Acme", role="R", source="S"))
        store.upsert_app(Application(id="b", company="Nimbus", role="R2", source="S"))
        self.assertEqual(len(store.firm_history("acme")), 1)
        self.assertEqual(store.firm_history("acme")[0].id, "a")


class ResponseMonitorTest(unittest.TestCase):
    def test_real_reply_emits_response_notification(self):
        store = InMemoryStore()
        app = Application(id="a1", company="Nimbus Labs", role="ML Engineer",
                          source="Ref", contact_email="t.nguyen@nimbuslabs.dev",
                          applied_at=_utc(2026, 8, 1))
        store.upsert_app(app)
        pilot = NudgePilot(store=store, backend=OfflineBackend(), sink=MemoryDraftSink())
        email = InboxEmail(id="e1", from_addr="t.nguyen@nimbuslabs.dev",
                           subject="Interview invitation - ML Engineer",
                           snippet="We were very impressed and would love to schedule an interview.",
                           received_at=_utc(2026, 8, 10))
        pilot.ingest_emails([email])
        digest = pilot.run_tick()
        self.assertEqual(len(digest.new_responses), 1)
        r = digest.new_responses[0]
        self.assertEqual(r.classification, ReplyKind.INTERVIEW)
        self.assertEqual(r.company, "Nimbus Labs")
        # state advanced
        self.assertEqual(store.get_app("a1").status, Status.INTERVIEW)

    def test_unrelated_email_matches_no_app(self):
        store = InMemoryStore()
        store.upsert_app(Application(id="a1", company="Acme", role="Dev", source="S",
                                     contact_email="r@acmeanalytics.com"))
        pilot = NudgePilot(store=store, backend=OfflineBackend(), sink=MemoryDraftSink())
        pilot.ingest_emails([InboxEmail(id="e9", from_addr="news@elsewhere.com",
                                        subject="Weekly", snippet="hi there",
                                        received_at=_utc(2026, 8, 10))])
        digest = pilot.run_tick()
        self.assertEqual(len(digest.new_responses), 0)


class RecommendationTest(unittest.TestCase):
    def test_high_priority_for_interview(self):
        app = Application(id="a", company="X", role="Y", source="S", status=Status.INTERVIEW)
        rec = RecommendationAgent(OfflineBackend()).recommend(app)
        self.assertEqual(rec.priority, "high")
        self.assertIn("prepare", rec.action.lower())

    def test_low_priority_for_rejected(self):
        app = Application(id="a", company="X", role="Y", source="S", status=Status.REJECTED)
        rec = RecommendationAgent(OfflineBackend()).recommend(app)
        self.assertEqual(rec.priority, "low")

    def test_applied_due_for_nudge_high(self):
        app = Application(id="a", company="X", role="Y", source="S",
                          contact_email="r@x.com", status=Status.APPLIED,
                          applied_at=_utc(2026, 8, 1))
        rec = RecommendationAgent(OfflineBackend()).recommend(app, now=_utc(2026, 8, 31))
        self.assertEqual(rec.priority, "high")
        self.assertIn("Send nudge #1", rec.action)


class HistorySummaryTest(unittest.TestCase):
    def test_timeline_summary_parses(self):
        prompt = (
            "You are NudgePilot... remember this firm...\nHISTORY:\n"
            "Application app_000: ML Engineer @ Nimbus Labs (Ref)\n"
            "  [Aug 27 21:38] outbound applied - applied via Referral\n"
            "  [Aug 31 21:30] inbound reply (interview) - t.nguyen@nimbuslabs.dev / Hi\n"
            "  -> current status: INTERVIEW\nSUMMARY:"
        )
        out = _timeline_summary(prompt)
        self.assertIn("ML Engineer at Nimbus Labs", out)
        self.assertIn("INTERVIEW", out)
        self.assertNotIn("Subject:", out)  # must NOT be the nudge draft

    def test_history_agent_builds_firm_memory(self):
        store = InMemoryStore()
        seed_store(store, now=_utc(2026, 8, 31, 12))
        app = store.firm_history("nimbus labs")[0]
        fm = HistoryAgent(OfflineBackend()).build_memory(app)
        self.assertEqual(fm.company, "Nimbus Labs")


if __name__ == "__main__":
    unittest.main()