# Status Agent - classifies inbound recruiter replies and updates app state.
"""
Responsibilities:
  1. Take an InboxEmail.
  2. Ask the LLM backend to classify it (rejection / interview / advance /
     soft_pending / question / other).
  3. If the email mentions a company/role it can map to an open Application,
     apply the reply transition via the policy engine (keeps state in code).
Returns the classification + any application it affected.
"""

from __future__ import annotations

import datetime as _dt

from core.domain import InboxEmail, Application, ReplyKind
from core.llm import LLMBackend
from core.policy import apply_reply

CLASSIFY_PROMPT_TPL = (
    "You are NudgePilot, a job-search inbox analyst. Classify the recruiter "
    "reply below into exactly one of these labels: "
    f"{', '.join(ReplyKind.ALL)}.\n"
    "SNIPPET=<<<{snippet}>>>\n"
    "Reply with the label only.\n"
)


class StatusAgent:
    def __init__(self, backend: LLMBackend) -> None:
        self.backend = backend

    def classify(self, email: InboxEmail) -> str:
        prompt = CLASSIFY_PROMPT_TPL.format(snippet=email.snippet or email.body)
        result = self.backend.complete(prompt)
        label = result.text.strip().lower()
        if label not in ReplyKind.ALL:
            label = ReplyKind.OTHER
        return label

    def apply(self, email: InboxEmail, apps: list[Application]) -> tuple[str, Application | None]:
        """Classify email; if it maps to a known app by company derive, apply it."""
        label = self.classify(email)
        target = _match_app(email, apps)
        if target is not None:
            apply_reply(target, label, detail=email.subject)
            return label, target
        return label, None


def _match_app(email: InboxEmail, apps: list[Application]) -> Application | None:
    """Best-effort match of an inbound email to an open application.

    Matches on: (1) exact contact-email presence, (2) a normalized company
    name/keyword token in the email text, or (3) the domain of the sender
    matching the company's contact domain. This is deliberately permissive:
    misclassifying EMAIL->APP association is low-cost (state stays human-auditable)
    compared to missing a response entirely.
    """
    text = f"{email.from_addr} {email.subject} {email.snippet}".lower()
    from_domain = email.from_addr.lower().split("@")[-1] if "@" in email.from_addr else ""
    for app in apps:
        if app.is_terminal:
            continue  # already closed; do not resurrect
        company = app.company.lower()
        # (1) exact contact email echoed
        if app.contact_email and app.contact_email.lower() in text:
            return app
        # (2) company name tokens split on punctuation/space
        tokens = [t for t in set(company.split()) if len(t) > 2]
        if any(tok in text for tok in tokens):
            return app
        # (3) sender domain matches company's domain
        if app.contact_email and from_domain and from_domain in app.contact_email.lower():
            return app
    return None