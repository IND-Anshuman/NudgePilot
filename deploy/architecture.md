```mermaid
flowchart LR
    subgraph TRIGGERS["Triggers"]
        SCHED["Cloud Scheduler\n(daily 6am)"] --> RUN["Cloud Run\n(FastAPI service)"]
        GMAIL["Inbox watch\n(Gmail → Pub/Sub)"] --> RUN
    end

    subgraph AGENT["NudgePilot agent (ADK-style orchestration)"]
        RUN --> COORD["Root Coordinator\n(orchestrator.py)"]
        COORD --> INT["Intake Agent\n(status_agent.py)"]
        COORD --> NUD["Nudge Agent\n(nudge_agent.py)"]
        COORD --> POL["Policy Engine\ncore/policy.py — deterministic ⭐"]
        INT --> FS["Cloud Firestore\nnudgepilot_applications"]
        NUD --> FS
        POL --> FS
    end

    subgraph LLM["Text layer"]
        INT --> GEM["Gemini 3.5\n(Vertex or API)"]
        NUD --> GEM
        GEM -. "offline fallback\n(zero-cred demo)" .-> OFFLINE["Deterministic\nbackend"]
    end

    subgraph OUT["Deliverables"]
        NUD --> DRAFT["Gmail Drafts\n(1-click approval, never auto-sent)"]
        COORD --> DIGEST["'While you slept'\ndigest email"]
    end
```

**Design note:** every *decision* (when to nudge / stop / ghost) lives in deterministic,
unit-tested `core/policy.py`. Gemini is confined to language: extraction, classification,
drafting. That split is the architectural-discipline story.