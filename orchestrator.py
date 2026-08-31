# Root coordinator - runs one daily 'tick' of the NudgePilot workflow.
"""
This is the Taskmaster 'complete workflow' wiring. One call to run_tick()
performs the full autonomous pass:

  1. Intake: consume any new inbox emails -> classify with StatusAgent ->
     apply reply transitions -> persist the interaction to the memory log ->
     emit a NewResponse notification if it's a real recruiter response.
  2. Nudge: for every application due (policy engine), draft a follow-up via
     NudgeAgent and emit a DrawnNudge (delivery is injectable; default goes to
     a drafts store, never auto-sent). Nudges are logged as interactions too.
  3. Ghost-close: mark long-silent, twice-nudged applications GHOSTED.
  4. Memory + advice: build a per-firm 'remember your history' FirmMemory and
     deterministic next-best-step Recommendations.
  5. Digest: assemble a 'while you slept' snapshot with NEW-RESPONSES and
     RECOMMENDED-STEPS sections.

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
    NewResponse,
    Interaction,
    InteractionKind,
    ReplyKind,
    Status,
)
from core.store import BaseStore
from core.llm import LLMBackend
from core.policy import should_nudge, should_ghost, transition_for_nudge
from agents.nudge_agent import NudgeAgent
from agents.status_agent import StatusAgent
from agents.history_agent import HistoryAgent
from agents.recommendation_agent import RecommendationAgent

# NewResponse is surfaced when a reply is one of these meaningful human responses.
NOTIFY_KINDS = (ReplyKind.REJECTION, ReplyKind.INTERVIEW, ReplyKind.ADVANCE,
                ReplyKind.SOFT_PENDING, ReplyKind.QUESTION)


class DraftSink:
    """Where drafted nudges land. Default: just hold them in the digest."""

    def save(self, nudge: DrawnNudge, app: Application) -> None:
        pass


class MemoryDraftSink(DraftSink):
    def __init__(self) -> None:
        self.saved: list[DrawnNudge] = []

    def save(self, nudge: DrawnNudge, app: Application) -> None:
        self.saved.append(nudge)


_ONE_LINE = {
    ReplyKind.REJECTION: "Rejections are hard but this frees your focus.",
    ReplyKind.INTERVIEW: "Interview invite - respond with available times.",
    ReplyKind.ADVANCE: "You're advancing - keep momentum, reply promptly.",
    ReplyKind.SOFT_PENDING: "Still pending - they asked you to keep waiting.",
    ReplyKind.QUESTION: "They asked you something - answer within a business day.",
    ReplyKind.OTHER: "A reply arrived.",
}


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
        self.history_agent = HistoryAgent(backend)
        self.recommendation_agent = RecommendationAgent(backend)
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
                # persist the interaction into the app's memory log
                interaction = Interaction(
                    kind=InteractionKind.REPLY,
                    at=email.received_at,
                    detail=f"{email.from_addr} / {email.subject}",
                    direction="inbound",
                    classification=label,
                    content=email.snippet,
                    email_id=email.id,
                )
                self.store.log_interaction(target.id, interaction)
                self.store.upsert_app(target)
                self._log(f"{stamp} reply from {email.from_addr} -> {target.role} @ {target.company} ({label}); state now {target.status}")
                # notify on meaningful responses (the "ping me" requirement)
                if label in NOTIFY_KINDS:
                    self._emit_response(target, email, label)
            else:
                self._log(f"{stamp} classified {email.subject} as {label} (no open application matched)")
            # keep a durable classification record for the digest
            self._classify_record(label, email.subject)

    def _emit_response(self, app: Application, email: InboxEmail, label: str) -> None:
        resp = NewResponse(
            application_id=app.id,
            company=app.company,
            role=app.role,
            from_addr=email.from_addr,
            subject=email.subject,
            classification=label,
            detail=_ONE_LINE.get(label, "A reply arrived."),
            email_id=email.id,
            matched=True,
        )
        if self._current is not None:
            self._current.new_responses.append(resp)
        # keep a durable copy even if no digest is being built
        self._pending_responses = getattr(self, "_pending_responses", [])
        self._pending_responses.append(resp)

    # -- the main workflow ---------------------------------------------------
    def run_tick(self) -> DigestRun:
        digest = DigestRun(run_at=self._now)
        self._current = digest
        apps = self.store.list_apps()
        # Inherit classifications captured during ingest (before this digest existed)
        for rec in self._class_records:
            digest.classified.append(rec)
        # Inherit any responses emitted during ingest before the digest was made
        for resp in getattr(self, "_pending_responses", []):
            digest.new_responses.append(resp)

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
                # log the outbound nudge as an interaction
                self.store.log_interaction(app.id, Interaction(
                    kind=InteractionKind.NUDGE,
                    at=self._now,
                    detail=f"nudge #{nudge_number} to {nudge.to}",
                    direction="outbound",
                    content=nudge.body[:200],
                ))
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

        # 4) memory + advice pass
        digest.recommendations = [
            self.recommendation_agent.recommend(a, self._now) for a in apps
        ]
        digest.firm_memories = self._build_firm_memories(apps)

        self.last_digest = digest
        self._current = None
        return digest

    def _build_firm_memories(self, apps: list[Application]) -> list:
        """Aggregate a FirmMemory per distinct company."""
        by_company: dict[str, list[Application]] = {}
        for a in apps:
            by_company.setdefault(a.company.lower(), []).append(a)
        return [
            self.history_agent.build_firm_memory(company_apps)
            for _, company_apps in by_company.items()
        ]

    def memory_for_firm(self, company: str) -> "FirmMemory":
        """Public helper for the CLI: full history + summary for one company."""
        apps = self.store.firm_history(company)
        return self.history_agent.build_firm_memory(apps)

    # -- digest --------------------------------------------------------------
    def build_digest_text(self) -> str:
        d = self.last_digest or DigestRun()
        lines = [
            "NudgePilot - While you slept",
            "=" * 40,
            f"Run at: {d.run_at.strftime('%Y-%m-%d %H:%M')} UTC",
        ]
        if d.new_responses:
            lines.append("\n🚨 NEW RESPONSES")
            for r in d.new_responses:
                lines.append(f"  * [{r.classification.upper()}] {r.company} / {r.role}: {r.detail}")
                lines.append(f"      ({r.from_addr} - '{r.subject}')")
        if d.drafted:
            lines.append("\n[NUDGES DRAFTED]")
            for n in d.drafted:
                lines.append(f"  * {n.subject}")
        if d.ghosted:
            lines.append("\n[PIPELINES CLOSED AS GHOSTED]")
            for gid in d.ghosted:
                lines.append(f"  * {gid}")
        if d.firm_memories:
            lines.append("\n[YOUR HISTORY WITH EACH FIRM]")
            for fm in d.firm_memories:
                lines.append(f"  • {fm.company} ({fm.latest_status})")
                lines.append(f"      {fm.summary}")
        if d.recommendations:
            lines.append("\n[🎯 RECOMMENDED NEXT STEPS]")
            for rec in sorted(d.recommendations,
                              key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r.priority, 3)):
                lines.append(f"  * [{rec.priority.upper()}] {rec.action}")
                lines.append(f"      ({rec.company} / {rec.role}) - {rec.why}")
        if d.classified:
            lines.append("\n[REPLIES CLASSIFIED]")
            for c in d.classified:
                lines.append(f"  * {c}")
        if not (d.new_responses or d.drafted or d.ghosted or d.firm_memories):
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