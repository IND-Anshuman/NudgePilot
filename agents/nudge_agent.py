# The Nudge Agent - drafts context-rich follow-up emails via the LLM backend.
"""
Responsibilities:
  1. Read an Application + a decision ('first' or 'repeat').
  2. Ask the LLM backend to draft the follow-up copy (context-rich).
  3. Return a DrawnNudge; caller decides whether/where to place it
     (Gmail Drafts in prod, a folder/print in demo).
Drafts, never sends  -> the autonomy guardrail lives at orchestrator level.
"""

from __future__ import annotations

import datetime as _dt

from core.domain import Application, DrawnNudge
from core.llm import LLMBackend

PROMPT_TMPL = (
    "You are NudgePilot, a job-search follow-up agent.\n"
    "Draft a short, specific, professional follow-up email (<= 5 sentences) "
    "for a candidate chasing a silent recruiter. Reference the exact role and "
    "company by name. Do NOT sound needy; keep it warm and brief. Never claim "
    "the candidate applied if uncertain.\n\n"
    "APP=<<<COMPANY:{company}>> ROLE:{role}>> SOURCE:{source}>> CONTACT:{contact}>>\n"
    "NUDGE={nudge_number}\n\n"
    "Return ONLY the email body starting with 'Subject: '.\n"
)


class NudgeAgent:
    def __init__(self, backend: LLMBackend) -> None:
        self.backend = backend

    def draft(self, app: Application, nudge_number: int) -> DrawnNudge:
        if nudge_number < 1 or nudge_number > 2:
            raise ValueError("nudge_number must be 1 or 2")
        contact = app.contact_email or "recruiter@example.com"
        prompt = PROMPT_TMPL.format(
            company=app.company,
            role=app.role,
            source=app.source,
            contact=contact,
            nudge_number=nudge_number,
        )
        result = self.backend.complete(prompt)
        text = result.text.strip()
        # ensure we got a subject line; if not, synthesize one
        if not text.lower().startswith("subject:"):
            text = f"Subject: Re: {app.role} - {app.company}\n\n{text}"
        # split the subject off; it is stored separately, not in the body
        lines = text.splitlines()
        subject = lines[0].replace("Subject:", "").strip()
        body = "\n".join(lines[1:]).strip()
        return DrawnNudge(
            application_id=app.id,
            to=contact,
            subject=subject,
            body=body,
            nudge_number=nudge_number,
            reason=f"nudge #{nudge_number}",
        )