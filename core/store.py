# Storage abstraction: Firestore in prod, in-memory for dev/demo.
"""
Store keeps the agent's source of truth. Production uses the live Google
Cloud Firestore emulator/client; local dev + the hackathon demo use an
in-memory implementation so the whole pipeline is runnable with zero setup
and no credentials. Both backends satisfy the same Read/Write contract.
"""

from __future__ import annotations

import datetime as _dt

from core.domain import Application, Interaction


class BaseStore:
    """Contract both backends implement."""

    def upsert_app(self, app: Application) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def get_app(self, app_id: str) -> Application | None:  # pragma: no cover
        raise NotImplementedError

    def list_apps(self, status: str | None = None) -> list[Application]:  # pragma: no cover
        raise NotImplementedError

    def list_apps_due_for_nudge(self, now: _dt.datetime) -> list[Application]:  # pragma: no cover
        raise NotImplementedError

    # -- interaction memory (history with each firm) -------------------------
    def log_interaction(self, app_id: str, interaction: "Interaction") -> None:  # pragma: no cover
        """Append an interaction to an application's chronological history."""
        raise NotImplementedError

    def list_recent_responses(self, now: _dt.datetime, window_h: float = 72.0) -> list:  # pragma: no cover
        """Inbound replies within the last `window_h` hours (for notifications)."""
        raise NotImplementedError

    def firm_history(self, company: str) -> list[Application]:  # pragma: no cover
        """All applications (and their interactions) for a given company."""
        raise NotImplementedError

    def list_apps_candidates_for_ghost(self, now: _dt.datetime) -> list[Application]:  # pragma: no cover
        raise NotImplementedError


class InMemoryStore(BaseStore):
    """Dev/demo store. Replaces Firestore client when no GCP creds present."""

    def __init__(self) -> None:
        self._apps: dict[str, Application] = {}

    def upsert_app(self, app: Application) -> None:
        self._apps[app.id] = app

    def get_app(self, app_id: str) -> Application | None:
        return self._apps.get(app_id)

    def list_apps(self, status: str | None = None) -> list[Application]:
        apps = list(self._apps.values())
        if status:
            apps = [a for a in apps if a.status == status]
        return apps

    def list_apps_due_for_nudge(self, now: _dt.datetime) -> list[Application]:
        from core.policy import should_nudge

        due = []
        for app in self._apps.values():
            ok, reason = should_nudge(app, now)
            if ok:
                due.append(app)
        return due

    def list_apps_candidates_for_ghost(self, now: _dt.datetime) -> list[Application]:
        from core.policy import should_ghost

        cands = []
        for app in self._apps.values():
            ok, reason = should_ghost(app, now)
            if ok:
                cands.append(app)
        return cands

    # -- interaction memory --------------------------------------------------
    def log_interaction(self, app_id: str, interaction: "Interaction") -> None:
        app = self._apps.get(app_id)
        if app is None:
            return
        app.interactions.append(interaction)
        # keep chronological
        app.interactions.sort(key=lambda i: i.at)

    def list_recent_responses(self, now: _dt.datetime, window_h: float = 72.0) -> list:
        cutoff = now - _dt.timedelta(hours=window_h)
        out = []
        for app in self._apps.values():
            for it in app.interactions:
                if it.kind == "reply" and it.at >= cutoff and it.classification:
                    out.append((app, it))
        return out

    def firm_history(self, company: str) -> list[Application]:
        return [a for a in self._apps.values() if a.company.lower() == company.lower()]


def build_store(kind: str = "memory") -> BaseStore:
    """Factory. 'memory' -> InMemoryStore; 'firestore' -> FirestoreStore (lazy)."""
    if kind == "firestore":
        # Imported lazily so the proxy/local stack never needs GCP deps.
        try:
            from core.firestore_store import FirestoreStore

            return FirestoreStore()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "firestore store requested but unavailable: %s" % exc
            ) from exc
    return InMemoryStore()