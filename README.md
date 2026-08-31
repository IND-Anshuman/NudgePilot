# NudgePilot 🚀
### An agentic job-search ghosting nudger · *All Things Agentic Hackathon — Taskmaster*

> **Trackers remember. NudgePilot acts.**

Rejections stink. **Ghosting** — applying to dozens of jobs and hearing *nothing back* — 
is the #1 frustration of the modern job search. **48% of applicants got zero response in 
2025**, a three-year high [1]. Most candidates *never follow up* [2], and the ones who do 
mis-time it — panicking at day 2 or giving up at day 10, when the median first response 
is **6–7 days** [3] and the median employer time-to-fill runs **~44 days** [4].

**NudgePilot** is an agent that does the follow-up for you: it reads your inbox, tracks every 
application through a status state machine, **drafts the perfectly-timed follow-ups**, detects 
dead pipelines, and emails you a *“While you slept”* report — **asynchronously, while you do 
something else**. It never auto-sends; every nudge lands as a Gmail **draft** awaiting your 
one-click approval.

---

## 🎯 The problem in numbers

| Fact | Number | Source |
|---|---|---|
| Time to complete one application | **~23 min** | [5] |
| Applications per successful hire | **~32** | [6] |
| Applicants getting **zero response** (2025) | **48%** — 3-yr high | [1] |
| Job seekers who experienced ghosting | **53%** | [7] |
| Median time to first response | **6–7 days** | [3] |
| Median employer time-to-fill | **~44 days** | [4] |

**The honest mechanism:** most ATS systems don't auto-reject — the infamous “75% auto-rejected” 
stat has no credible source [8]. The black hole is *human inattention at scale*: overwhelmed 
recruiters simply drop threads. So the fix isn't “beating the robot” — it's **systematic, 
well-timed, human follow-up that overwhelmed humans never get around to.** That's exactly 
what an agent is for.

---

## ✨ What it does (one full “tick”)

1. **Intake** — consumes new inbox emails, Classifies them (rejection / interview / soft-pending /
   question / other) with Gemini, and updates application state.
2. **Nudge** — asks the policy engine which applications are *due* for a follow-up; drafts a 
   context-rich nudge via Gemini for each; lands it in Gmail **Drafts** (never auto-sent).
3. **Ghost-close** — after **two ignored nudges** and a **21-day silence**, marks the pipeline 
   `GHOSTED` with the reason, so you stop spending energy on it.
4. **Digest** — emails you the *“While you slept”* report (what it drafted, what it closed, 
   what it caught).

### State machine (deterministic code — the heart of the design)

```
APPLIED ──day 7, silent──► NUDGED_1 ──day 7 more──► NUDGED_2 ──21d silent──► GHOSTED
   │                          │                        │
   └── reply?? ───────────────┴────────────────────────┴──► RESPONDED / INTERVIEW / REJECTED / OFFER
```

**Design principle:** *LLMs for language, code for decisions.* Every “when/stop/ghost” decision 
is deterministic, unit-tested `core/policy.py` — Gemini is used only for extraction, 
classification, and drafting. That's the Architectural Discipline story.

---

## 🗂 Repository layout

```
nudgepilot/
├── core/
│   ├── domain.py            # Firestore-shaped Application model + digest artifacts
│   ├── policy.py            # ⭐ all nudge/ghost/transition DECISIONS (testable, no LLM)
│   ├── llm.py               # LLM backend: Gemini (prod) ⊕ offline deterministic fallback
│   ├── store.py             # storage contract: InMemoryStore (dev) ⊕ FirestoreStore (prod)
│   └── firestore_store.py   # Google Cloud Firestore backend (production)
├── agents/
│   ├── nudge_agent.py       # drafts context-rich follow-ups via LLM
│   └── status_agent.py      # classifies inbox replies + matches to applications
├── delivery/
│   └── gmail_sink.py        # Gmail Drafts delivery (drafts, never auto-send) + .eml writer
├── orchestrator.py          # ⭐ root coordinator: intake → nudge → ghost-close → digest
├── seed.py                  # deterministic demo data (30 apps + reply corpus)
├── nudgepilot_cli.py        # CLI: `seed`, `run`, `auto` (seed+run)
├── reqs/cloud_arg.py        # (see deploy/) Cloud Run entrypoint
├── tests/
│   └── test_policy.py       # 15 unit tests on the policy engine + guardrails
├── cloud/                   # deployment manifests (Cloud Run, Scheduler, IAM, Dockerfile)
├── deploy/                  # deployment runbook + architecture diagram (mermaid)
├── README.md                # ← you are here
└── requirements.txt
```

---

## 🚀 Quick start (zero credentials — runs right now)

```bash
python -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt

# Option A — one-shot demo (seed + run, deterministic "offline" Gemini backend):
python nudgepilot_cli.py auto

# Option B — seed the store, then run:
python nudgepilot_cli.py seed
python nudgepilot_cli.py run --drafts-to-disk   # writes drafts to ~/nudgepilot_drafts

# Option C — real Gemini (set GOOGLE_API_KEY):
GOOGLE_API_KEY=... python nudgepilot_cli.py run --backend google

# Tests (policy engine must stay green):
python -m unittest discover -s tests
```

> **No API key required for the demo.** NudgePilot ships an *offline deterministic* LLM backend 
> that produces realistic, context-rich drafts so the whole pipeline runs and is verifiable with 
> zero credentials. Flip to real Gemini with one flag.

---

## ☁️ Google Cloud deployment (production / prove-it-runs-on-GCP)

The mandatory stack, all wired in this repo:

| Requirement | Implementation |
|---|---|
| **Gemini 3.5 via Vertex AI** | `core/llm.py::GeminiBackend` (`gemini-3.5-flash`), used by both agents |
| **Google Agent Framework** | Google **ADK**-style orchestration in `orchestrator.py` (root coordinator + sub-agents, tool-using), plus a Google GenAI SDK adapter. See `cloud/` |
| **GCP service** | **Cloud Run** (server, scale-to-zero), **Cloud Firestore** (state), **Cloud Scheduler** (daily 6am tick), optionally **Pub/Sub** (Gmail Watch push) |
| **Prove it runs** | Deploy with `cloud/`, hit the `/docs` + `/run` endpoints; video screenshots the Cloud Run dashboard & Firestore console |

See **[`deploy/RUNBOOK.md`](deploy/RUNBOOK.md)** for the full step-by-step. Cost at demo scale:
scale-to-zero Cloud Run + Flash model ≈ **effectively $0/month** — we show a near-zero billing
screenshot.

### Guardrails & autonomy dial (judges will ask about this)

| Guardrail | Rule |
|---|---|
| **Drafts, not sends** (default) | All nudges land in Gmail Drafts for 1-click approval (“full-auto” is an opt-in toggle) |
| Nudge ceiling | **max 2** follow-ups per application, ever |
| Cooldown | **min 7 days** between touches; **48h** before re-poking the same thread |
| Hard stops | never nudge after an explicit rejection; **never resurrect a closed pipeline** |
| Ghost closure | after day-21 + 2 ignored nudges → `GHOSTED`, redirect effort |

---

## 🏆 Judging-criteria mapping

- **Innovation & Operational Utility (40%)** — removes the single most-skipped chore of a 
  12-hour, 2–3%-response grind *autonomously*, and *proves* it via the digest + action log.
- **Architectural Discipline & Stack (30%)** — deterministic state machine + policy engine; LLM 
  confined to language; event-driven intake; scale-to-zero deployment; 15 unit tests.
- **Demo & Production Readiness (30%)** — unedited `python nudgepilot_cli.py auto` run; 
  `cloud/` deploy; architecture diagram; reproducible seed.

---

## 📊 Sources
1. [Candidates ghosted at 3-year high — Fortune](https://fortune.com/2026/03/20/job-seekers-arent-imagining-things-candidates-ghosted-by-employers-hit-three-year-high/) · 2. [The Exact Follow-Up Formula — Gaply](https://usegaply.com/blog/how-to-get-recruiter-response-follow-up-formula) · 3. [How Long to Hear Back After Applying — Careery](https://careery.pro/blog/resume-applications/how-long-to-hear-back-from-job-application) · 4. [State of Recruiting 2025 — SHRM](https://www.shrm.org/executive-network/insights/people-strategy/state-of-recruiting-2025-insights-to-maximize-recruitment) · 5. [The Job Application Process — LinkedIn](https://www.linkedin.com/pulse/job-application-process-facts-figures-alb) · 6. [State of Job Search 2025 — Interview Guys](https://blog.theinterviewguys.com/state-of-job-search-2025-research-report/) · 7. [Ghosting statistics — Glozo](https://www.glozo.com/blog/candidate-ghosting-statistics) · 8. [ATS Statistics: the 75% stat is fake — ResumeAdapter](https://www.resumeadapter.com/ats-statistics)

---

*Built for the [All Things Agentic Hackathon](https://allthingsagentichackathon.devpost.com/) — 
Taskmaster track. Deadline Aug 31, 2026 @ 5:00pm PDT.*