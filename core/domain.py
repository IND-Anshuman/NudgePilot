# Firestore-shaped domain model for NudgePilot.
"""
Business objects for the job-search ghosting nudger.

Every object here maps 1:1 to a Firestore document/collection so the same domain
code runs (a) against a live Google Cloud Firestore store in production and
(b) against an in-memory/simulated store for local dev + the hackathon demo.

Design intent (Architectural Discipline):
  - Deterministic state machine lives in *code*, not in the LLM.
  - Gemini is used only where an LLM genuinely helps: extraction,
    classification, and drafting.
  - All times are timezone-aware UTC; the digest renders to the user's zone.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------


class Status:
    """Valid lifecycle states of one job application."""

    APPLIED = "APPLIED"  # submitted, waiting
    NUDGED_1 = "NUDGED_1"  # first follow-up drafted/sent
    NUDGED_2 = "NUDGED_2"  # second (final) follow-up
    RESPONDED = "RESPONDED"  # any meaningful human reply received
    INTERVIEW = "INTERVIEW"  # interview invite / in-interview stage
    REJECTED = "REJECTED"  # explicit rejection received
    OFFER = "OFFER"  # offer received
    GHOSTED = "GHOSTED"  # timed out after 2 ignored nudges -> redirect effort
    FAILED = "FAILED"  # pipeline closed, user marked done

    ALL = (
        APPLIED,
        NUDGED_1,
        NUDGED_2,
        RESPONDED,
        INTERVIEW,
        REJECTED,
        OFFER,
        GHOSTED,
        FAILED,
    )

    # Terminal states: nothing else the agent will ever do for these.
    TERMINAL = (REJECTED, OFFER, GHOSTED, FAILED)


class ReplyKind:
    """Classification of an inbound reply email from a recruiter/company."""

    REJECTION = "rejection"
    INTERVIEW = "interview"
    ADVANCE = "advance"  # positive signal / next-round, not yet interview
    SOFT_PENDING = "soft_pending"  # "still reviewing / deciding" - keep waiting
    QUESTION = "question"  # recruiter asked something; needs human
    OTHER = "other"  # noise / auto-noreply / not relevant
    ALL = (REJECTION, INTERVIEW, ADVANCE, SOFT_PENDING, QUESTION, OTHER)


class EntityKind:
    """Email entity classification done at intake."""

    CONFIRMATION = "confirmation"  # application received
    RECRUITER_REPLY = "recruiter_reply"  # human/inbound reply to a nudge
    REJECTION = "rejection"  # explicit no
    AUTOMATED = "automated"  # noreply / notifications / jobs digest spam
    SPAM = "spam"
    NEUTRAL = "neutral"  # anything we can't place -> ignore for workflow
    ALL = (CONFIRMATION, RECRUITER_REPLY, REJECTION, AUTOMATED, SPAM, NEUTRAL)


# Policy constants (timings pulled from research). See README citations.
FIRST_NUDGE_DAYS = 7  # median first response is 6-7 days; nudge just after
SECOND_NUDGE_DAYS = 7  # gap between nudge 1 and nudge 2
NUDGE_CEILING = 2  # never send more than two nudges per application
GHOST_CUTOFF_DAYS = 21  # after last nudge + silence -> mark GHOSTED
MIN_COOLDOWN_BETWEEN_TOUCHES_H = 48  # never poke the same thread twice < 48h


# ---------------------------------------------------------------------------
# Application record
# ---------------------------------------------------------------------------


@dataclass
class Application:
    """One job application, stored as a Firestore document."""

    id: str
    company: str
    role: str
    source: str  # where applied: LinkedIn / company site / referral
    jd_url: str = ""
    contact_email: Optional[str] = None
    applied_at: _dt.datetime = field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))
    status: str = Status.APPLIED
    nudges_sent: int = 0
    nudge_log: list = field(default_factory=list)  # list[dict]
    reply_log: list = field(default_factory=list)  # list[dict]
    last_touch_at: Optional[_dt.datetime] = None
    ghost_log: list = field(default_factory=list)  # why it closed
    resume_highlights: str = ""
    notes: str = ""
    interactions: list = field(default_factory=list)  # unified, chronological Interaction records

    @property
    def is_terminal(self) -> bool:
        return self.status in Status.TERMINAL

    def days_since_applied(self, now: _dt.datetime) -> float:
        return (now - self.applied_at).total_seconds() / 86400.0

    def days_since_last_touch(self, now: _dt.datetime) -> Optional[float]:
        if self.last_touch_at is None:
            return None
        return (now - self.last_touch_at).total_seconds() / 86400.0

    def to_dict(self) -> dict:
        """Firestore-compatible dict (datetimes kept as-is; Firestore maps them)."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Inbound email (the thing the inbox watcher emits)
# ---------------------------------------------------------------------------


@dataclass
class InboxEmail:
    """A raw-ish email that the Gmail watcher (Pub/Sub) hands to the agent."""

    id: str
    from_addr: str
    subject: str
    snippet: str
    received_at: _dt.datetime = field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))
    thread_id: str = ""
    body: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Agent output artifacts (what the digest + demo surface)
# ---------------------------------------------------------------------------


@dataclass
class DrawnNudge:
    """A follow-up email the agent drafted (drafts-by-default, never auto-sent)."""

    application_id: str
    to: str
    subject: str
    body: str
    nudge_number: int
    reason: str  # why now

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Interaction memory (the 'history with the firm')
# ---------------------------------------------------------------------------


class InteractionKind:
    APPLIED = "applied"
    NUDGE = "nudge"
    REPLY = "reply"

    OUTBOUND = (NUDGE,)
    INBOUND = (REPLY,)


@dataclass
class Interaction:
    """A single touchpoint in one application's history (chronological)."""

    kind: str  # InteractionKind: applied | nudge | reply
    at: _dt.datetime = field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))
    detail: str = ""  # subject/sender or message
    direction: str = "inbound"  # inbound (recruiter->you) | outbound (you->recruiter)
    classification: str = ""  # for replies: ReplyKind value
    content: str = ""  # full message body/snippet
    email_id: str = ""  # ref to the inbound InboxEmail, if any

    def to_dict(self) -> dict:
        d = asdict(self)
        d["at"] = d["at"].isoformat() if isinstance(d["at"], _dt.datetime) else d["at"]
        return d


@dataclass
class NewResponse:
    """A freshly-arrived response worth notifying the user about."""

    application_id: str
    company: str
    role: str
    from_addr: str
    subject: str
    classification: str  # ReplyKind
    detail: str  # short human summary of what it means
    email_id: str = ""
    matched: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Recommendation:
    """One suggested next action for an application."""

    application_id: str
    company: str
    role: str
    priority: str  # high | medium | low
    action: str  # what to do
    why: str  # context / reason

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FirmMemory:
    """The 'remember your history' summary for a given company."""

    company: str
    applications: list = field(default_factory=list)  # list[dict] app snapshots
    timeline: list = field(default_factory=list)  # list of (at, kind, detail)
    summary: str = ""  # prose/gemini or deterministic summary
    latest_status: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class DigestRun:
    """Summary of one agent run - the 'while you slept' report."""

    run_at: _dt.datetime = field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))
    drafted: list = field(default_factory=list)  # DrawnNudge
    classified: list = field(default_factory=list)  # dict[email_id -> classification]
    ghosted: list = field(default_factory=list)  # application_ids newly ghosted
    responded: list = field(default_factory=list)  # application_ids that advanced
    errors: list = field(default_factory=list)  # strings
    action_log: list = field(default_factory=list)  # chronological stamp lines
    new_responses: list = field(default_factory=list)  # NewResponse (notifications)
    recommendations: list = field(default_factory=list)  # Recommendation (next best steps)
    firm_memories: list = field(default_factory=list)  # FirmMemory (history summaries)

    def to_dict(self) -> dict:
        return asdict(self)