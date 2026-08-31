# Deterministic seed-data generator for a reproducible demo.
"""
Populates the store with ~30 applications at staggered ages plus realistic
inbound recruiter emails, so a single `python nudgepilot_cli.py auto` produces
a believable full workflow: some apps due for nudge #1, some due for nudge #2,
some to be ghost-closed, and inbound replies (interview invite, rejection,
soft-pending, a question) for the response monitor + firm-memory + advisor.

All data is synthetic and generated with a fixed RNG seed for reproducibility.
"""

from __future__ import annotations

import datetime as _dt
import random

from core.domain import Application, InboxEmail, Status, Interaction, InteractionKind
from core.store import BaseStore

_COMPANIES = [
    ("Acme Analytics", "Data Analyst", "LinkedIn"),
    ("Blockcode", "Backend Engineer", "Company site"),
    ("Nimbus Labs", "ML Engineer", "Referral"),
    ("Hexmark", "Frontend Engineer", "LinkedIn"),
    ("Orbit Systems", "Product Manager", "Company site"),
    ("Veldex", "DevOps Engineer", "LinkedIn"),
    ("Packraft", "Mobile Engineer", "Company site"),
    ("Quantia", "Data Scientist", "Referral"),
    ("Solstice AI", "AI Researcher", "LinkedIn"),
    ("Brightform", "Design Engineer", "Referral"),
    ("Meridian Goods", "QA Engineer", "Company site"),
    ("Northpeak", "Backend Engineer", "LinkedIn"),
    ("Luminous", "Frontend Engineer", "LinkedIn"),
    ("Trillium", "Data Engineer", "Company site"),
    ("Aperture Cloud", "Solutions Architect", "Referral"),
    ("Copperline", "Site Reliability Eng", "LinkedIn"),
    ("Harrow & Co", "Product Designer", "Company site"),
    ("Zephyr Metrics", "Growth Engineer", "Referral"),
    ("Fathom Point", "Platform Engineer", "LinkedIn"),
    ("Ridgetop", "Staff Engineer", "Company site"),
    ("Cinder Well", "iOS Engineer", "LinkedIn"),
    ("Bramble", "Data Analyst", "Company site"),
    ("Stellara", "ML Ops Engineer", "Referral"),
    ("Northwind Data", "Data Engineer", "LinkedIn"),
    ("Kelpbyte", "Fullstack Engineer", "Referral"),
    ("Astra & Vine", "UX Researcher", "Company site"),
    ("Cobalt Peak", "Security Engineer", "LinkedIn"),
    ("Sunforge", "Android Engineer", "Company site"),
    ("Tidalworks", "Backend Engineer", "LinkedIn"),
    ("Kindling Co", "Founding Engineer", "Referral"),
]

_CONTACTS = [
    "j.romano@acmeanalytics.com", "hr@blockcode.io", "t.nguyen@nimbuslabs.dev",
    "alex@hexmark.co", "m.stern@orbitsystems.com", "dev.hiring@veldex.io",
    "careers@packraft.app", "j.das@quantia.ai", "recruiting@solsticeai.dev",
    "hi@brightform.studio", "talent@meridiangoods.com", "b.hughes@northpeak.io",
    "talent@lightmode.app", "d.kim@trilliumdata.com", "team@aperture.cloud",
]

_RESPONSE_SEED = [
    # (company-fragment, subject, snippet, expected-kind)
    ("acme", "Re: Data Analyst application",
     "Thanks for your interest, unfortunately we have decided to move forward with other candidates this time.",
     "rejection"),
    ("nimbus", "Interview invitation - ML Engineer",
     "We were very impressed with your background and would love to schedule a first interview this week.",
     "interview"),
    ("hexmark", "Status update - Frontend Engineer",
     "Thanks for your patience, we're still reviewing a few shortlists and hope to update you within a week.",
     "soft_pending"),
    ("veldex", "Question about your availability",
     "Hi! Could you tell us your notice period and whether you're open to a hybrid schedule?",
     "question"),
]


def _age(now: _dt.datetime, days: float) -> _dt.datetime:
    return now - _dt.timedelta(days=days)


def seed_store(
    store: BaseStore,
    now: _dt.datetime | None = None,
) -> tuple[list[Application], list[InboxEmail]]:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    _rng = random.Random(42)

    apps: list[Application] = []
    # Explicit ages trigger the interesting policy outcomes:
    #   day 8-9  -> due nudge #1
    #   day 12+ already nudged once -> due nudge #2
    #   day 35+ nudged twice + old -> ghost candidate
    age_plan = [
        2, 3, 4, 5, 6, 7, 8, 8, 9, 9, 10, 10, 11, 12, 14, 24, 40, 45, 50, 55,
        60, 65, 8, 9, 10, 14, 20, 30, 45, 60,
    ]
    for i, (company, role, source) in enumerate(_COMPANIES):
        contact = _CONTACTS[i % len(_CONTACTS)]
        days_old = age_plan[i]
        applied_at = _age(now, days_old)
        app = Application(
            id=f"app_{i:03d}",
            company=company,
            role=role,
            source=source,
            jd_url=f"https://careers.example.com/jobs/{company.lower().replace(' ', '-')}",
            contact_email=contact,
            applied_at=applied_at,
            status=Status.APPLIED,
            resume_highlights="4+ yrs relevant experience; shipped 3 production systems",
        )
        # simulate prior nudges for older applications so ghost logic can fire
        if days_old >= 12:
            app.status = Status.NUDGED_1
            app.nudges_sent = 1
            app.last_touch_at = _age(now, days_old - 2)
        if days_old >= 35:
            app.status = Status.NUDGED_2
            app.nudges_sent = 2
            app.last_touch_at = _age(now, days_old - 8)
        # record the "applied" interaction so history/firm-memory has a base
        app.interactions.append(Interaction(
            kind=InteractionKind.APPLIED,
            at=applied_at,
            detail=f"applied via {source}",
            direction="outbound",
            content=f"Submitted application for {role} at {company}.",
        ))
        apps.append(app)
        store.upsert_app(app)

    # inbound replies for the tick to classify
    emails: list[InboxEmail] = []
    for j, (frag, subj, snap, _kind) in enumerate(_RESPONSE_SEED):
        emails.append(InboxEmail(
            id=f"email_{j}",
            from_addr=f"{frag}recruiter@example.com",
            subject=subj,
            snippet=snap,
            body=snap,
            received_at=_age(now, 0.2),
            thread_id=f"thread_{j}",
        ))

    return apps, emails


def fresh_seed(store: BaseStore) -> None:
    """Separate helper that only writes apps (used when reply emails are managed
    separately through the inbox pipeline). Kept for API completeness."""
    seed_store(store)