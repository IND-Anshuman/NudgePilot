# History Agent - turns an application's interaction log into a "remember" summary.
"""
Builds the user's memory of each firm from the persisted interaction log:

  * A chronological timeline (applied -> nudges -> replies).
  * A prose summary (Gemini in prod; deterministic fallback offline) so the
    user remembers WHO they talked to, WHAT was said, and where things stand.

This directly satisfies: "tell the user the summary and details of the earlier
interactions with the job firm so they remember their history."
"""

from __future__ import annotations

import datetime as _dt

from core.domain import Application, Interaction, FirmMemory
from core.llm import LLMBackend

TIMELINE_PROMPT = (
    "You are NudgePilot, a job-search assistant. Below is the full chronological "
    "history of interactions for a job application. Write a concise, warm, 2-4 "
    "sentence 'remember this firm' summary for the candidate: who they applied "
    "to, what role, what has happened so far (nudges sent, replies received, "
    "rejections/interviews), and where things currently stand. Do not invent "
    "facts that are not in the history.\n\nHISTORY:\n{history}\n\nSUMMARY:"
)


def _format_timeline(app: Application) -> str:
    """Deterministic human-readable timeline from the interaction log."""
    lines = [f"Application {app.id}: {app.role} @ {app.company} ({app.source})"]
    if app.interactions:
        for it in sorted(app.interactions, key=lambda i: i.at):
            ts = it.at.strftime("%b %d %H:%M") if isinstance(it.at, _dt.datetime) else str(it.at)
            lines.append(f"  [{ts}] {it.direction} {it.kind}"
                         + (f" ({it.classification})" if it.classification else "")
                         + (f" - {it.detail}" if it.detail else ""))
    else:
        lines.append("  (no recorded interactions yet)")
    lines.append(f"  -> current status: {app.status}")
    return "\n".join(lines)


class HistoryAgent:
    def __init__(self, backend: LLMBackend) -> None:
        self.backend = backend

    def build_memory(self, app: Application) -> FirmMemory:
        """One firm-memory for a single application."""
        timeline_text = _format_timeline(app)
        prompt = TIMELINE_PROMPT.format(history=timeline_text)
        result = self.backend.complete(prompt)
        summary = result.text.strip() or (
            f"You applied to {app.role} at {app.company}. Current status: {app.status}."
        )
        timeline = [
            {
                "at": it.at.isoformat() if isinstance(it.at, _dt.datetime) else str(it.at),
                "kind": it.kind,
                "direction": it.direction,
                "classification": it.classification,
                "detail": it.detail,
            }
            for it in sorted(app.interactions, key=lambda i: i.at)
        ]
        return FirmMemory(
            company=app.company,
            applications=[app.to_dict()],
            timeline=timeline,
            summary=summary,
            latest_status=app.status,
        )

    def build_firm_memory(self, apps: list[Application]) -> FirmMemory:
        """Aggregate memory across all applications at one company."""
        if not apps:
            return FirmMemory(company="", applications=[], timeline=[], summary="")
        first = apps[0]
        full_timeline = "\n\n".join(_format_timeline(a) for a in apps)
        prompt = TIMELINE_PROMPT.format(history=full_timeline)
        result = self.backend.complete(prompt)
        summary = result.text.strip() or (
            f"You've applied to {len(apps)} role{'s' if len(apps)>1 else ''} at {first.company}. "
            f"Latest status: {first.status}."
        )
        timeline = []
        for a in apps:
            timeline += [
                {
                    "at": it.at.isoformat() if isinstance(it.at, _dt.datetime) else str(it.at),
                    "kind": it.kind,
                    "direction": it.direction,
                    "classification": it.classification,
                    "detail": it.detail,
                }
                for it in sorted(a.interactions, key=lambda i: i.at)
            ]
        timeline.sort(key=lambda t: t["at"])
        return FirmMemory(
            company=first.company,
            applications=[a.to_dict() for a in apps],
            timeline=timeline,
            summary=summary,
            latest_status=first.status,
        )