# State machine transitions for NudgePilot - pure, deterministic, testable code.
"""
All policy decisions for how/when to nudge live here, NOT in the LLM.

This is the 'Architectural Discipline' proof point: an agent whose *autonomy
decisions* are deterministic, auditable, and unit-testable, and which delegates
only language tasks (extraction / classification / drafting) to Gemini.

Research-backed timings (see README for full citations):
  - Median time to first response is 6-7 days   -> first nudge at ~day 7
  - Median employer time-to-fill is ~44 days    -> a 21-day ghost cutoff is sane
  - Most candidates never follow up             -> the agent's whole job
"""

from __future__ import annotations

import datetime as _dt

from core.domain import (
    Application,
    Status,
    FIRST_NUDGE_DAYS,
    SECOND_NUDGE_DAYS,
    NUDGE_CEILING,
    GHOST_CUTOFF_DAYS,
    MIN_COOLDOWN_BETWEEN_TOUCHES_H,
    ReplyKind,
)


class PolicyError(Exception):
    pass


def should_nudge(app: Application, now: _dt.datetime) -> tuple[bool, str]:
    """
    Decide whether an application is due for a follow-up right now.

    Returns (False, reason) when it must NOT be nudged and (True, nudge_number)
    is encoded in the reason string for logging.
    """
    if app.is_terminal:
        return False, f"terminal state {app.status}"
    if app.status not in (Status.APPLIED, Status.NUDGED_1, Status.NUDGED_2):
        return False, f"state {app.status} is not nudge-eligible"

    # Ceiling: never send more than NUDGE_CEILING nudges, ever.
    if app.nudges_sent >= NUDGE_CEILING:
        return False, f"nudge ceiling reached ({app.nudges_sent})"

    # Need a direct line; we won't nudge into the void of a portal inbox.
    if not app.contact_email:
        return False, "no recruiter contact email on file"

    age_days = app.days_since_applied(now)
    if app.status == Status.APPLIED:
        if age_days < FIRST_NUDGE_DAYS:
            return False, f"too early ({age_days:.1f}d < {FIRST_NUDGE_DAYS}d)"
        return True, "first_nudge"
    # NUDGED_1 or NUDGED_2
    if app.status == Status.NUDGED_2 and app.nudges_sent >= 2:
        return False, "already sent final nudge"
    gap_d = SECOND_NUDGE_DAYS
    since_touch = app.days_since_last_touch(now)
    if since_touch is None or since_touch < (MIN_COOLDOWN_BETWEEN_TOUCHES_H / 24.0):
        return False, f"cooling off (last touch {since_touch}s ago)" if since_touch else "never touched"
    if since_touch < gap_d:
        return False, f"cooling off ({since_touch:.1f}d < {gap_d}d)"
    return True, "repeat_nudge"


def should_ghost(app: Application, now: _dt.datetime) -> tuple[bool, str]:
    """True when the app has gone silent far past the cutoff and should close."""
    if app.is_terminal:
        return False, "already terminal"
    if not app.contact_email:
        return False, "never had a contact"
    reference = app.last_touch_at or app.applied_at
    elapsed = (now - reference).total_seconds() / 86400.0
    # Only close the loop if we actually did our two nudges; don't ghost a
    # barely-touched application (it may simply be early in day-7 cadence).
    if app.nudges_sent < NUDGE_CEILING:
        return False, f"only {app.nudges_sent} nudges sent (< {NUDGE_CEILING})"
    if elapsed < GHOST_CUTOFF_DAYS:
        return False, f"{elapsed:.1f}d < cutoff {GHOST_CUTOFF_DAYS}d"
    return True, f"silent for {elapsed:.1f}d past cutoff"


def apply_reply(app: Application, kind: str, detail: str = "") -> str:
    """
    Mutate application state in response to a classified inbound reply.
    Returns the new status string.
    Returns the prompt for the handler to keep a record (helper semantics).
    """
    NEW = {
        ReplyKind.REJECTION: Status.REJECTED,
        ReplyKind.INTERVIEW: Status.INTERVIEW,
        ReplyKind.ADVANCE: Status.RESPONDED,
        ReplyKind.SOFT_PENDING: Status.RESPONDED,
        ReplyKind.QUESTION: Status.RESPONDED,
        ReplyKind.OTHER: None,
    }.get(kind)
    # A terminal application (GHOSTED / REJECTED / OFFER / FAILED) is closed;
    # do NOT resurrect it from a late reply - the candidate has already moved on.
    # This preserves the guardrail 'do not spam closed pipelines'.
    if app.is_terminal:
        return app.status
    if NEW is not None:
        app.status = NEW
        app.last_touch_at = _dt.datetime.now(_dt.timezone.utc)
        return NEW
    return app.status


def transition_for_nudge(app: Application) -> str:
    """Return the state code an application moves *into* after a nudge is sent."""
    return Status.NUDGED_1 if app.status == Status.APPLIED else Status.NUDGED_2