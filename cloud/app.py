# NudgePilot Cloud Run service — exposes the agent as an HTTP endpoint.
"""
Taskmaster 'deployed & running on Google Cloud' proof:
  GET  /health   -> liveness (billing-zero proof helper)
  POST /run      -> run one full NudgePilot tick, return digest JSON
  GET  /docs     -> OpenAPI/Swagger UI (great for the demo video)

Runs the exact same orchestration as the CLI, over a shared store/backend, so
the local demo and the GCP deployment are the SAME agent.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException

try:  # optional: load .env if present (never required)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from core.store import build_store
from core.llm import build_backend
from orchestrator import NudgePilot, MemoryDraftSink
from delivery.gmail_sink import GmailDraftSink as _GmailSink
from seed import seed_store

app = FastAPI(title="NudgePilot", version="0.9.0",
              description="Agentic job-search ghosting nudger (Taskmaster)".replace(" (Taskmaster)", ""))


def _build_pilot() -> NudgePilot:
    store_kind = os.getenv("NUDGEPILOT_STORE", "memory")
    store = build_store("firestore" if store_kind == "firestore" else "memory")
    backend = build_backend()  # auto: google if key present else offline
    sink = _GmailSink() if os.getenv("NUDGEPILOT_DRAFTS_DIR") else MemoryDraftSink()
    return NudgePilot(store=store, backend=backend, sink=sink)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "nudgepilot",
            "backend": build_backend().__class__.__name__}


@app.post("/run")
def run_tick(payload: dict | None = None) -> dict:
    """Run one NudgePilot tick (intake→nudge→ghost→digest). If the store is empty
    and payload {seed: true} is given, prime the store for a reproducible demo."""
    pilot = _build_pilot()
    if payload and payload.get("seed"):
        seed_store(pilot.store)
    try:
        digest = pilot.run_tick()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "run_at": digest.run_at.isoformat(),
        "drafted": [n.subject for n in digest.drafted],
        "ghosted": digest.ghosted,
        "classified": digest.classified,
        "errors": digest.errors,
        "action_log": digest.action_log,
        "digest_text": pilot.build_digest_text(),
    }


@app.get("/applications")
def list_applications() -> list[dict]:
    pilot = _build_pilot()
    return [a.to_dict() for a in pilot.store.list_apps()]