# LLM interface with graceful offline fallback.
"""
NudgePilot's text layer. Two interchangeable backends:

  * Google backend  - real Gemini 3.5 via google-genai (ADK style). This is the
                      production path and the mandatory-stack "Gemini" box.
  * offline/simulated - deterministic template backend used when no API key is
                      present (local dev, CI, hackathon demo). It produces
                      realistic, context-rich output *without any credentials*,
                      so the entire pipeline is runnable and demonstrable now.

The rest of the codebase talks ONLY to `StubModel.complete(...)`, never to a
concrete API, so switching between backends is a config change.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

from core.domain import Application, ReplyKind


@dataclass
class Completion:
    text: str
    model: str = "offline-deterministic"
    usage: dict = field(default_factory=dict)


class ModelError(RuntimeError):
    pass


class LLMBackend:
    """Minimal interface: complete(text) -> Completion."""

    def complete(self, text: str) -> Completion:  # pragma: no cover - interface
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Google / Gemini backend (production path)
# ---------------------------------------------------------------------------


class GeminiBackend(LLMBackend):
    """Direct google-genai calls. No ADK import trampoline needed for simple use."""

    def __init__(self, model: str = "gemini-3.5-flash") -> None:
        self.model = model
        # late import keeps this module import-safe without the package
        from google import genai  # noqa: F401

    def complete(self, text: str) -> Completion:
        from google import genai

        client = genai.Client()
        resp = client.models.generate_content(model=self.model, contents=text)
        return Completion(text=resp.text, model=self.model, usage=getattr(resp, "usage_metadata", {}) or {})


# ---------------------------------------------------------------------------
# Offline / simulated backend (demo path)
# ---------------------------------------------------------------------------


_ROLE_SNIPPETS = [
    "Typescript", "Python/Data", "Frontend (React)", "Backend (Go)", "Product Design",
    "DevRel", "Sales/GTM", "ML/Infra", "Mobile", "Full-stack generalist",
]


def _build_nudge_body(app: Application, nudge_number: int, now) -> str:
    """Deterministic, sensible follow-up copy. Kept reusable across backends."""
    if nudge_number == 1:
        subject = f"Re: {app.role} - {app.company} application"
        body = (
            f"Hi {app.contact_email.split('@')[0].split('.')[0].capitalize() or 'there'},\n\n"
            f"Following up on my application for the {app.role} position at {app.company} "
            f"({app.source}). I'm still very interested in the role and would welcome an "
            f"opportunity to discuss how my background fits. Happy to provide anything further.\n\n"
            f"Thanks for your time.\nBest,"
        )
    else:
        subject = f"Quick check-in - {app.role} @ {app.company}"
        body = (
            f"Hi,\n\nJust checking in on the {app.role} role at {app.company} - I completely "
            f"understand you're busy, and I wanted to keep the door open. If the team has "
            f"gone another direction, no hard feelings at all - just a quick note would "
            f"help me close the loop.\n\nThanks again,\n"
        )
    return f"Subject: {subject}\n\n{body}"


def _classify_reply(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("unfortunately", "sorry", "not moving forward", "we have decided", "not to proceed", "regret to inform", "other candidates")):
        return ReplyKind.REJECTION
    if any(k in low for k in ("interview", "schedule a call", "screen", "availability")):
        return ReplyKind.INTERVIEW
    if any(k in low for k in ("impressed", "moving forward", "next round", "love to", "great to see", "advancing")):
        return ReplyKind.ADVANCE
    if any(k in low for k in ("still reviewing", "still considering", "decision", "shortlist", "week")):
        return ReplyKind.SOFT_PENDING
    if any(k in low for k in ("question", "could you", "can you", "tell me")):
        return ReplyKind.QUESTION
    return ReplyKind.OTHER


def _timeline_summary(text: str) -> str:
    """Deterministic 'remember this firm' summary from the HISTORY prompt block.

    Parses the timeline lines the HistoryAgent injects (each 'APP id: role @ company'
    and '  [ts] direction kind (class) - detail') and hand-writes a concise summary
    so the offline/zero-credential demo produces a real, useful memory instead of
    falling through to the nudge-draft handler.
    """
    role = company = source = None
    events: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        low = s.lower()
        if s.startswith("Application") and "@" in s and "(" in s:
            # "Application app_000: Data Analyst @ Acme Analytics (LinkedIn)"
            try:
                body = s.split(":", 1)[1].strip()
                role_part = body.split("@")[0].strip()
                comp_part = body.split("@")[1].strip()
                company = comp_part.split("(")[0].strip()
                source = comp_part.split("(")[-1].rstrip(")").strip()
                role = role_part or role
            except Exception:
                pass
        elif "[" in s and "]" in s and ("nudge" in low or "reply" in low or "applied" in low):
            events.append(s)
    status = "UNKNOWN"
    if "current status:" in text.lower():
        status = text.split("current status:")[-1].splitlines()[0].strip().upper()
    parts = []
    if company and role:
        parts.append(f"You applied to {role} at {company}")
    elif company:
        parts.append(f"You applied to a role at {company}")
    if events:
        parts.append(f"so far: {'; '.join(events[-4:])}")
    else:
        parts.append("so far: application submitted, no recorded follow-ups yet")
    if status:
        parts.append(f"current status: {status}")
    return ". ".join(parts) + "."


class OfflineBackend(LLMBackend):
    """Template backend. Uses the same drafting/classification prompts, but resolves
    deterministically so the demo runs with no credentials."""

    def complete(self, text: str) -> Completion:
        # Peek at the instruction block to route to the right deterministic impl.
        lowered = text.lower()
        if "classify" in lowered:
            # extract the snippet marker we inject in prompts
            m = re.search(r"SNIPPET=<<<(.*?)>>>", text, re.DOTALL)
            snippet = m.group(1) if m else text
            kind = _classify_reply(snippet)
            return Completion(text=kind, usage={"offline": True})
        if "history" in lowered and "summary" in lowered:
            # firm-memory / timeline summary request
            return Completion(text=_timeline_summary(text), usage={"offline": True})
        # default: drafting request
        return Completion(text=_draft_from_prompt(text), usage={"offline": True})


def _draft_from_prompt(text: str) -> str:
    """Produce a reasonable nudge draft from a structured prompt using markers."""
    n = 1
    mn = re.search(r"NUDGE=(\d+)", text)
    if mn:
        n = int(mn.group(1))
    company = _extract_marked(text, "COMPANY")
    role = _extract_marked(text, "ROLE")
    source = _extract_marked(text, "SOURCE") or "online"
    contact = _extract_marked(text, "CONTACT") or "recruiter"
    first = contact.split("@")[0].replace(".", " ").title()
    body = _build_nudge_body_n(company, role, source, first, n)
    return body


def _extract_marked(text: str, key: str) -> str | None:
    m = re.search(rf"{key}:(.*?)(?:>>>|>>|$)", text)
    return m.group(1).strip() if m else None


def _build_nudge_body_n(company: str, role: str, source: str, first: str, n: int) -> str:
    if n == 1:
        return (
            f"Subject: Re: {role} - {company} application\n\n"
            f"Hi {first or 'there'},\n\n"
            f"Following up on my application for the {role} position at {company} ({source}). "
            f"I'm still very interested and would welcome a chance to discuss my background. "
            f"Happy to provide anything further.\n\nThanks for your time.\nBest,\n[Your name]"
        )
    return (
        f"Subject: Quick check-in - {role} @ {company}\n\n"
        f"Hi {first or 'there'},\n\nJust checking in on the {role} role at {company} - I "
        f"understand you're busy and I wanted to keep the door open. If the team has gone "
        f"another direction, no hard feelings - a quick note would help me close the loop.\n\n"
        f"Thanks again,\n[Your name]"
    )


def build_backend(kind: str | None = None) -> LLMBackend:
    """kind: 'google' | 'offline' | None(auto). Auto uses offline unless GOOGLE_API_KEY."""
    kind = kind or ("google" if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_GENAI_USE_VERTEXAI") else "offline")
    if kind == "google":
        try:
            return GeminiBackend()
        except Exception as exc:  # noqa: BLE001
            raise ModelError(f"Gemini backend unavailable: {exc}") from exc
    return OfflineBackend()