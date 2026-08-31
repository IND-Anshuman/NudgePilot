# Gmail delivery - drafts by default (never auto-send).
"""
Production sends drafted nudges into the user's Gmail DRAFTS folder for
1-click approval, honouring the 'drafts not sends' guardrail. Implementing the
full Gmail OAuth + gmail.users.drafts.create here is production roadmap; for
the hackathon we provide a deterministic DraftStore sink that mirrors where the
email *would* land (and prints for the demo) plus a clearly-marked function
stub for the real Gmail integration. The orchestrator never auto-sends.
"""

from __future__ import annotations

import os

from core.domain import DrawnNudge, Application


class GmailDraftSink:
    """Writes drafted nudges as flat .eml files in ~/nudgepilot_drafts (demo-able)
    and prints them. In production this would call gmail users.drafts.create."""

    def __init__(self, out_dir: str | None = None) -> None:
        self.out_dir = out_dir or os.getenv(
            "NUDGEPILOT_DRAFTS_DIR",
            os.path.join(os.getcwd(), "nudgepilot_drafts"),
        )
        os.makedirs(self.out_dir, exist_ok=True)

    def save(self, nudge: DrawnNudge, app: Application) -> None:
        fname = f"{app.id}__nudge{nudge.nudge_number}.eml"
        path = os.path.join(self.out_dir, fname)
        content = (
            "To: {to}\n"
            "Subject: {subject}\n"
            "From: **YOUR GMAIL** (draft - not sent)\n"
            "Content-Type: text/plain; charset=utf-8\n\n"
            "{body}\n".format(to=nudge.to, subject=nudge.subject, body=nudge.body)
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        # demo visibility
        print(f"[gmail-drafts] #{app.id} -> {path}")


def create_gmail_draft(  # pragma: no cover - production stub
    nudge: DrawnNudge, app: Application, credentials: dict
) -> None:
    """Production endpoint - would call google.gmail.drafts.create. Stubbed.
    Left intentionally un-importable without google client so the demo path is
    import-safe."""
    raise NotImplementedError(
        "Gmail OAuth send is production roadmap; see README for scopes required."
    )