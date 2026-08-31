# Root coordinator - runs one daily 'tick' of the NudgePilot workflow.
"""
This is the Taskmaster 'complete workflow' wiring. One call to run_tick()
performs the full autonomous pass:

  1. Intake: consume any new inbox emails -> classify with StatusAgent ->
     apply reply transitions.
  2. Nudge: for every application due (policy engine), draft a follow-up via
     NudgeAgent and emit a DrawnNudge (delivery is injectable; default goes to
     a drafts store, never auto-sent).
  3. Ghost-close: mark long-silent, twice-nudged applications GHOSTED with a
     reason, so the candidate redirects effort.
  4. Digest: assemble a 'while you slept' snapshot.

The coordinator holds NO policy numbers itself; it defers every green/red
decision to core.policy. That is the accountability/inspectability story.
"""

from __future__ import annotations

import datetime as _dt

from core.domain import (
    Application,
    InboxEmail,
    DigestRun,
    DrawnNudge,
    Status,
)
from core.store import BaseStore
from core.llm import LLMBackend
from core.policy import should_nudge, should_ghost, transition_for_nudge
from agents.nudge_agent import NudgeAgent
from agents.status_agent import StatusAgent


class DraftSink:
    """Where drafted nudges land. Default: just hold them in the digest."""

    def save(self, nudge: DrawnNudge, app: Application) -> None:
        pass


class MemoryDraftSink(DraftSink):
    def __init__(self) -> None:
        self.saved: list[DrawnNudge] = []

    def save(self, nudge: DrawnNudge, app: Application) -> None:
        self.saved.append(nudge)


class NudgePilot:
    def __init__(
        self,
        store: BaseStore,
        backend: LLMBackend,
        sink: DraftSink | None = None,
        now: _dt.datetime | None = None,
    ) -> None:
        self.store = store
        self.nudge_agent = NudgeAgent(backend)
        self.status_agent = StatusAgent(backend)
        self.sink = sink or MemoryDraftSink()
        self._now = now or _dt.datetime.now(_dt.timezone.utc)
        self.last_digest: DigestRun | None = None
        self._current: DigestRun | None = None
        self._class_records: list[str] = []

    # -- intake of new emails -------------------------------------------------
    def ingest_emails(self, emails: list[InboxEmail]) -> None:
        apps = self.store.list_apps()
        for email in emails:
            label, target = self.status_agent.apply(email, apps)
            stamp = self._clock_string()
            if target is not None:
                self.store.upsert_app(target)
                self._log(f"{stamp} classified reply from {email.from_addr} as {label} -> {target.role} @ {target.company} (now {target.status})")
            else:
                self._log(f"{stamp} classified {email.subject} as {label} (no open application matched)")
            # keep a durable classification record for the digest
            self._classify_record(label, email.subject)

    # -- the main workflow ---------------------------------------------------
    def run_tick(self) -> DigestRun:
        digest = DigestRun(run_at=self._now)
        self._current = digest
        apps = self.store.list_apps()
        # Inherit classifications captured during ingest (before this digest existed)
        for rec in self._class_records:
            digest.classified.append(rec)

        # 2) nudge pass
        due = []
        for app in apps:
            ok, reason = should_nudge(app, self._now)
            if ok:
                due.append(app)
        for app in due:
            nudge_number = app.nudges_sent + 1
            if nudge_number > 2:
                continue
            try:
                nudge = self.nudge_agent.draft(app, nudge_number)
                self.sink.save(nudge, app)
                app.nudges_sent = nudge_number
                app.status = transition_for_nudge(app)
                app.last_touch_at = self._now
                app.nudge_log.append({"at": self._now.isoformat(), "n": nudge_number})
                self.store.upsert_app(app)
                digest.drafted.append(nudge)
                self._log(f"{self._clock_string()} drafted nudge #{nudge_number} for {app.role} @ {app.company} -> {app.status}")
            except Exception as exc:  # noqa: BLE001
                digest.errors.append(f"nudge {app.id}: {exc}")
                self._log(f"{self._clock_string()} ERROR drafting nudge for {app.id}: {exc}")

        # 3) ghost pass
        for app in apps:
            ok, reason = should_ghost(app, self._now)
            if ok:
                app.status = Status.GHOSTED
                app.ghost_log.append({"at": self._now.isoformat(), "reason": reason})
                self.store.upsert_app(app)
                digest.ghosted.append(app.id)
                self._log(f"{self._clock_string()} closed {app.role} @ {app.company} as GHOSTED ({reason})")

        self.last_digest = digest
        self._current = None
        return digest

    # -- digest --------------------------------------------------------------
    def build_digest_text(self) -> str:
        d = self.last_digest or DigestRun()
        lines = [
            "NudgePilot - While you slept",
            "=" * 40,
            f"Run at: {d.run_at.strftime('%Y-%m-%d %H:%M')} UTC",
        ]
        if d.drafted:
            lines.append("\n[NUDGES DRAFTED]")
            for n in d.drafted:
                lines.append(f"  * {n.subject}")
        if d.ghosted:
            lines.append("\n[PIPELINES CLOSED AS GHOSTED]")
            for gid in d.ghosted:
                lines.append(f"  * {gid}")
        if d.classified:
            lines.append("\n[REPLIES CLASSIFIED]")
            for c in d.classified:
                lines.append(f"  * {c}")
        if not (d.drafted or d.ghosted or d.classified):
            lines.append("\nNothing scheduled. All quiet on the job front.")
        if d.errors:
            lines.append("\n[ERRORS]")
            for e in d.errors:
                lines.append(f"  ! {e}")
        return "\n".join(lines)

    # -- helpers -------------------------------------------------------------
    def _log(self, msg: str) -> None:
        if self._current is not None:
            self._current.action_log.append(msg)

    def _classify_record(self, label: str, subject: str) -> None:
        entry = f"{label}: {subject}"
        self._class_records.append(entry)
        # attach to the digest if one is being built right now
        if self._current is not None:
            self._current.classified.append(entry)

    @staticmethod
    def _clock_string() -> str:
        return _dt.datetime.now(_dt.timezone.utc).strftime("%H:%M:%S")