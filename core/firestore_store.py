# Cloud Firestore backend for NudgePilot (production store).
"""
Real backend. Uses google-cloud-firestore v2 async client. Replace the
InMemoryStore at runtime via --store firestore. Requires a GOOGLE_CLOUD_PROJECT
+ Application Default Credentials in prod; uses FIRESTORE_EMULATOR_HOST in
dev. This module is imported lazily, so the demo/local path never needs it.
"""

from __future__ import annotations

import datetime as _dt
import os

from core.domain import Application
from core.store import BaseStore

_COLLECTION = "nudgepilot_applications"


class FirestoreStore(BaseStore):
    def __init__(self) -> None:
        from google.cloud import firestore

        self._db = firestore.AsyncClient() if hasattr(firestore, "AsyncClient") else firestore.Client()
        self._col = self._db.collection(_COLLECTION)

    def _app_id(self, app_or_id):
        return app_or_id.id if isinstance(app_or_id, Application) else app_or_id

    async def upsert_app(self, app: Application) -> None:
        data = app.to_dict()
        data["applied_at"] = data["applied_at"].isoformat() if data.get("applied_at") else None
        for k in ("last_touch_at",):
            v = data.get(k)
            data[k] = v.isoformat() if hasattr(v, "isoformat") else v
        await self._col.document(app.id).set(data)

    async def get_app(self, app_id: str) -> Application | None:
        doc = await self._col.document(app_id).get()
        if not doc.exists:
            return None
        raw = dict(doc.to_dict())
        raw["applied_at"] = _iso(raw.get("applied_at"))
        raw["last_touch_at"] = _iso(raw.get("last_touch_at"))
        return Application(**raw)

    async def list_apps(self, status: str | None = None) -> list[Application]:
        ref = self._col
        if status:
            ref = ref.where("status", "==", status)
        out = []
        for doc in ref.stream() if not hasattr(ref, "__aiter__") else await ref.get():
            raw = dict(doc.to_dict())
            raw["applied_at"] = _iso(raw.get("applied_at"))
            raw["last_touch_at"] = _iso(raw.get("last_touch_at"))
            out.append(Application(**raw))
        return out

    # -- interaction memory --------------------------------------------------
    async def log_interaction(self, app_id: str, interaction: "Interaction") -> None:
        await self._col.document(app_id).collection("interactions").add(interaction.to_dict())

    async def list_recent_responses(self, now: _dt.datetime, window_h: float = 72.0) -> list:
        cutoff = (now - _dt.timedelta(hours=window_h)).isoformat()
        out = []
        for app in await self.list_apps():
            q = self._col.document(app.id).collection("interactions")
            docs = await q.where("kind", "==", "reply").where("at", ">=", cutoff).get()
            for doc in docs:
                it = _interaction_from_doc(doc.to_dict())
                out.append((app, it))
        return out

    async def firm_history(self, company: str) -> list[Application]:
        apps = await self.list_apps()
        return [a for a in apps if a.company.lower() == company.lower()]


def _interaction_from_doc(raw: dict) -> "Interaction":
    from core.domain import Interaction

    raw = dict(raw)
    raw["at"] = _iso(raw.get("at"))
    return Interaction(**raw)


def _iso(v):
    if v is None or isinstance(v, _dt.datetime):
        return v
    try:
        return _dt.datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None