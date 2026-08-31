# NudgePilot Frontend

Static single-page site that explains the NudgePilot problem and solution.
Pure HTML + CSS + 2 small JS files. No build step. Deployable to Firebase Hosting, Cloud Storage + CDN, Netlify, Vercel, GitHub Pages, or any static host.

## Local preview

The site is fully static. Easiest way to preview:

```bash
# Python (no install needed if you have python3)
cd frontend
python -m http.server 8080
# open http://localhost:8080
```

Or with Node:
```bash
cd frontend
npx serve .
```

Or any other static server.

## Deploy to Firebase Hosting (one command)

The repo ships with a `firebase.json` + `.firebaserc` already configured.

```bash
# one-time setup
npm install -g firebase-tools
firebase login
firebase use --add   # pick your GCP project (the same one as the Cloud Run backend)

# deploy
firebase deploy --only hosting
# → https://nudgepilot-hackathon.web.app
```

The deploy publishes everything under `frontend/` and configures:
- SPA-friendly rewrites (everything → `index.html`)
- Aggressive caching for fonts
- `Cache-Control: must-revalidate` for HTML/CSS/JS/JSON/SVG (so updates propagate fast)

## Deploy to any other static host

Just upload the contents of `frontend/` to any static host. The relative
paths in the HTML (`styles/...`, `scripts/...`, `data/...`, `assets/...`)
work on any path prefix.

## File layout

```
frontend/
├── index.html                  # single-page entry
├── styles/
│   ├── tokens.css              # design tokens (colors, type, motion)
│   ├── reset.css               # modern minimal reset
│   ├── base.css                # typography defaults + body styles
│   ├── components.css          # Button, Card, Nav, Terminal, etc.
│   └── sections.css            # per-section layout
├── scripts/
│   ├── main.js                 # nav morph, scroll reveals, cost bars, sources
│   └── live-tick.js            # scroll-driven terminal animation
├── assets/
│   ├── mark.svg                # paper-plane → clock-hand brand mark
│   ├── architecture.svg        # hand-built architecture diagram
│   └── icons/                  # inline-able SVGs (cloud-run, firestore, …)
└── data/
    ├── tick-run.json           # frozen output of `python nudgepilot_cli.py auto`
    └── sources.json            # 8 citations from the README
```

## How to refresh the Live Tick capture

The Live Tick section (§08) plays a real captured run from `data/tick-run.json`.
To refresh it after code changes:

```bash
cd NudgePilot-1            # repo root
./scripts/capture_tick.py   # runs `cli auto`, parses stdout, writes tick-run.json
firebase deploy --only hosting
```

The script is non-destructive — only updates `frontend/data/tick-run.json`.

## Design system

Locked-in aesthetic: **Agentic Print-Bold** — maximalist editorial-tech hybrid.

- **Palette:** ink `#0B0B0F` · acid `#D7FF3C` · rust `#FF6B3C` · bone `#F2EFE6`
- **Type:** Playfair Display (display) · Inter Tight (body) · JetBrains Mono (code) · Anton (numerals)
  - Paid alternates documented in `.hermes/plans/frontend-design-plan.md`
- **Motion:** custom cubic-beziers only (`cubic-bezier(0.32, 0.72, 0, 1)`), `prefers-reduced-motion` honored everywhere
- **Layout:** Asymmetrical Bento + Z-Axis Cascade. All asymmetric layouts collapse to `w-full, px-4, py-8` below 768px

Full plan: `.hermes/plans/frontend-design-plan.md`

## Performance

- Total page weight under 300 KB on first load (no images of gradients, only one inline SVG architecture + one inline mark)
- Self-hosted-equivalent fonts via Google Fonts CDN (preconnected)
- Only `transform` + `opacity` animated (GPU-safe)
- All scroll listeners are passive; reveals are IntersectionObserver
- No layout-triggering properties ever animated

## Accessibility

- Semantic HTML5 (`<header>`, `<nav>`, `<main>`, `<section>`, `<footer>`)
- Skip link as first focusable element
- All text pairs ≥ 4.5:1 contrast against their background
- `:focus-visible` outline (acid 2px, 3px offset) on every interactive element
- `prefers-reduced-motion` honored across nav morph, scroll reveals, terminal stagger
- Live tick terminal is `aria-live="polite"`