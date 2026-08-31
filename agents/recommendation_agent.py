# Recommendation Agent - the "next best steps" advisor.
"""
Produces deterministic, actionable next-step recommendations for every open
application, based purely on application state + policy timings + the history
of interactions. No LLM guessing about *what* to do -- the advisor encodes
best-practice playbooks; Gemini is optionally used only to phrase them (offline
fallback returns the plain text).

This is the "tell the user the next best possible steps to take" requirement.
"""

from __future__ import annotations

import datetime as _dt

from core.domain import Application, Recommendation, Status
from core.policy import should_nudge
from core.llm import LLMBackend

# Playbooks keyed by (status) -> (action, why, priority)
# Deterministic so it is unit-testable and auditable.
_PLAYBOOK = {
    Status.APPLIED: (
        "Follow up - application is sitting unanswered past the typical first-response window",
        "Median first response is 6-7 days; a polite nudge revives overlooked applications",
        "high",
    ),
    Status.NUDGED_1: (
        "Send second follow-up, then set a decision date",
        "One nudge sent with no reply; one final check-in closes the loop",
        "medium",
    ),
    Status.NUDGED_2: (
        "Treat as ghosted unless it replies - redirect energy to newer leads",
        "Two nudges ignored means the pipeline is effectively closed",
        "medium",
    ),
    Status.RESPONDED: (
        "Reply promptly and keep the thread warm",
        "A response means you're in the running - do not stall the ball",
        "high",
    ),
    Status.INTERVIEW: (
        "Prepare: research the team, role, and rehearse answers to their JD",
        "Interviews are won in preparation, not in the call",
        "high",
    ),
    Status.REJECTED: (
        "Thank them briefly and ask for one line of feedback; keep momentum",
        "A graceful close keeps the door open for future roles and gathers signal",
        "low",
    ),
    Status.OFFER: (
        "Review the offer against your priorities and decide on a timeline",
        "An offer is the reward - handle it deliberately, not out of relief",
        "high",
    ),
    Status.GHOSTED: (
        "Close this one; redirect effort to the warmest active pipelines",
        "Two ignored nudges = move on",
        "low",
    ),
    Status.FAILED: (
        "Archived - no action needed",
        "Pipeline is closed",
        "low",
    ),
}


class RecommendationAgent:
    def __init__(self, backend: LLMBackend) -> None:
        self.backend = backend

    def recommend(self, app: Application, now: _dt.datetime | None = None) -> Recommendation:
        now = now or _dt.datetime.now(_dt.timezone.utc)
        action, why, priority = self._playbook_for(app, now)
        return Recommendation(
            application_id=app.id,
            company=app.company,
            role=app.role,
            priority=priority,
            action=action,
            why=why,
        )

    def recommend_all(self, apps: list[Application], now: _dt.datetime | None = None) -> list[Recommendation]:
        return [self.recommend(a, now) for a in apps]

    def _playbook_for(self, app: Application, now: _dt.datetime):
        # overrides beyond the naive status map (data-aware)
        if app.status == Status.APPLIED:
            due, _ = should_nudge(app, now)
            if due:
                return (
                    "Send nudge #1 today - this application is due for its first follow-up",
                    "It has been at/over the targeted response window with no reply",
                    "high",
                )
        if app.status == Status.NUDGED_2 and app.nudges_sent >= 2:
            return (
                "Treat as ghosted unless it replies - redirect energy to newer leads",
                "Final nudge already sent; silence past the cutoff means it is likely closed",
                "medium",
            )
        return _PLAYBOOK.get(app.status, (
            "Review this application for next actions",
            "Status not in the standard playbook",
            "medium",
        ))