# Unit tests for the NudgePilot policy engine and state machine (unittest, no deps).
"""
These tests are the 'Architectural Discipline' receipt: every autonomy decision
the agent makes (when to nudge, when to stop, when to ghost) is deterministic,
testable code, independent of any LLM. Run:  python -m unittest discover -s tests
"""

from __future__ import annotations

import datetime as _dt
import unittest

from core.domain import Application, Status, InboxEmail
from core.policy import (
    should_nudge,
    should_ghost,
    apply_reply,
    transition_for_nudge,
    NUDGE_CEILING,
)
from agents.status_agent import _match_app, StatusAgent
from core.llm import OfflineBackend


def _utc(y, m, d, hour=0, minute=0):
    return _dt.datetime(y, m, d, hour, minute, tzinfo=_dt.timezone.utc)


def _app(**kw):
    defaults = dict(
        id="test", company="Acme Analytics", role="Data Analyst", source="LinkedIn",
        contact_email="recruiter@acmeanalytics.com",
    )
    defaults.update(kw)
    return Application(**defaults)


class PolicyNudgeTest(unittest.TestCase):
    def test_no_nudge_when_too_young(self):
        now = _utc(2026, 8, 31)
        app = _app(applied_at=_utc(2026, 8, 25))  # 6 days
        ok, why = should_nudge(app, now)
        self.assertFalse(ok)
        self.assertIn("too early", why)

    def test_first_nudge_at_day_7(self):
        now = _utc(2026, 8, 31)
        app = _app(applied_at=_utc(2026, 8, 23))  # 8 days, applied state
        ok, why = should_nudge(app, now)
        self.assertTrue(ok)
        self.assertEqual(why, "first_nudge")

    def test_no_nudge_without_contact(self):
        now = _utc(2026, 8, 31)
        app = _app(contact_email=None, applied_at=_utc(2026, 8, 10))
        ok, why = should_nudge(app, now)
        self.assertFalse(ok)
        self.assertIn("no recruiter contact", why)

    def test_repeat_nudge_respects_cooldown(self):
        now = _utc(2026, 8, 31)
        app = _app(
            status=Status.NUDGED_1, nudges_sent=1,
            applied_at=_utc(2026, 8, 10),
            last_touch_at=_utc(2026, 8, 29),  # 2 days ago -> too soon
        )
        ok, why = should_nudge(app, now)
        self.assertFalse(ok)
        self.assertIn("cooling", why)

    def test_repeat_nudge_after_gap(self):
        now = _utc(2026, 8, 31)
        app = _app(
            status=Status.NUDGED_1, nudges_sent=1,
            applied_at=_utc(2026, 8, 5),
            last_touch_at=_utc(2026, 8, 21),  # 10 days ago
        )
        ok, why = should_nudge(app, now)
        self.assertTrue(ok)
        self.assertEqual(why, "repeat_nudge")

    def test_nudge_ceiling_hard_cap(self):
        now = _utc(2026, 8, 31)
        app = _app(
            status=Status.NUDGED_2, nudges_sent=NUDGE_CEILING,
            applied_at=_utc(2026, 7, 1),
            last_touch_at=_utc(2026, 8, 1),
        )
        ok, why = should_nudge(app, now)
        self.assertFalse(ok)
        self.assertIn("ceiling", why)


class PolicyGhostTest(unittest.TestCase):
    def test_ghost_only_after_two_nudges(self):
        now = _utc(2026, 8, 31)
        app = _app(
            status=Status.NUDGED_1, nudges_sent=1,
            applied_at=_utc(2026, 7, 1),  # very old
            last_touch_at=_utc(2026, 7, 10),
        )
        ok, why = should_ghost(app, now)
        self.assertFalse(ok)
        self.assertIn("only 1 nudges", why)

    def test_ghost_after_two_nudges_and_cutoff(self):
        now = _utc(2026, 9, 30)
        app = _app(
            status=Status.NUDGED_2, nudges_sent=2,
            applied_at=_utc(2026, 6, 1),
            last_touch_at=_utc(2026, 6, 20),  # > 21d before now
        )
        ok, why = should_ghost(app, now)
        self.assertTrue(ok)
        self.assertIn("cutoff", why)


class ReplyTransitionTest(unittest.TestCase):
    def test_rejection_transition(self):
        app = _app()
        new_status = apply_reply(app, "rejection")
        self.assertEqual(new_status, Status.REJECTED)
        self.assertTrue(app.is_terminal)

    def test_interview_transition(self):
        app = _app()
        new_status = apply_reply(app, "interview")
        self.assertEqual(new_status, Status.INTERVIEW)

    def test_terminal_not_resurrected_by_reply(self):
        app = _app(status=Status.GHOSTED)
        new_status = apply_reply(app, "interview")
        self.assertEqual(new_status, Status.GHOSTED)  # stays closed


class MatchTest(unittest.TestCase):
    def test_domain_match_from_demo(self):
        app = _app(company="Acme Analytics", contact_email="j.romano@acmeanalytics.com")
        email = InboxEmail(
            id="e1", from_addr="recruiter@acmeanalytics.com", subject="Job application update",
            snippet="we have decided to move forward with other candidates",
        )
        self.assertIs(_match_app(email, [app]), app)

    def test_no_match_for_unrelated(self):
        app = _app(company="Acme Analytics", contact_email="j.romano@acmeanalytics.com")
        email = InboxEmail(
            id="e2", from_addr="newsletter@somewhere.io", subject="Weekly digest",
            snippet="here are this week's highlights",
        )
        self.assertIsNone(_match_app(email, [app]))

    def test_offline_classifier(self):
        backend = OfflineBackend()
        sa = StatusAgent(backend)
        rej = sa.classify(InboxEmail(
            id="e3", from_addr="x@y.com", subject="update",
            snippet="Regret to inform you we will not be moving forward.",
        ))
        self.assertEqual(rej, "rejection")
        iv = sa.classify(InboxEmail(
            id="e4", from_addr="x@y.com", subject="Interview",
            snippet="We would love to schedule an interview.",
        ))
        self.assertEqual(iv, "interview")


class TransitionTest(unittest.TestCase):
    def test_transition_for_nudge(self):
        self.assertEqual(transition_for_nudge(_app()), Status.NUDGED_1)
        self.assertEqual(
            transition_for_nudge(_app(status=Status.NUDGED_1)),
            Status.NUDGED_2,
        )


if __name__ == "__main__":
    unittest.main()