/* ============================================================
   NudgePilot — live-tick.js
   Loads tick-run.json, renders action_log lines into the
   terminal panel, and reveals them progressively as the user
   scrolls into the section. Progress bar tracks scroll.
   Honors prefers-reduced-motion (renders all lines immediately).
   ============================================================ */

(function () {
  'use strict';

  const termBody = document.getElementById('terminal-body');
  const termProgress = document.getElementById('terminal-progress-bar');
  const termSummary = document.getElementById('terminal-summary');

  if (!termBody) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Classify log lines by what they did (for color tags) */
  function classify(line) {
    if (line.indexOf('classified') !== -1) {
      if (line.indexOf('rejection') !== -1) return { cls: 'tag-rust',  label: 'classified' };
      if (line.indexOf('interview') !== -1) return { cls: 'tag-sky',   label: 'classified' };
      if (line.indexOf('soft_pending') !== -1) return { cls: 'tag-acid', label: 'classified' };
      return { cls: 'tag-sky', label: 'classified' };
    }
    if (line.indexOf('closed') !== -1 && line.indexOf('GHOSTED') !== -1) return { cls: 'tag-rust', label: 'ghosted' };
    if (line.indexOf('drafted nudge') !== -1) return { cls: 'tag-acid', label: 'drafted' };
    if (line.indexOf('ERROR') !== -1) return { cls: 'tag-rust', label: 'error' };
    return null;
  }

  function renderLine(line) {
    const span = document.createElement('span');
    span.className = 'terminal__line';
    // split timestamp prefix if present (format: HH:MM:SS ...)
    const m = /^(\d{2}:\d{2}:\d{2})\s+(.*)$/.exec(line);
    const ts = m ? m[1] : '';
    const rest = m ? m[2] : line;
    const cls = classify(line);
    let html = '';
    if (ts) html += '<span class="ts">' + ts + '</span>';
    if (cls) html += '<span class="tag ' + cls.cls + '">' + cls.label + '</span>';
    html += escape(rest);
    span.innerHTML = html;
    return span;
  }

  function escape(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  fetch('data/tick-run.json')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      // 1) Render summary counters
      if (termSummary && data.counts) {
        const c = data.counts;
        termSummary.innerHTML =
          '<span><b style="color:var(--acid)">' + c.drafted + '</b> drafted</span>' +
          '<span><b style="color:var(--rust)">' + c.ghosted + '</b> ghosted</span>' +
          '<span><b style="color:var(--sky)">' + c.classified + '</b> classified</span>' +
          '<span style="color:var(--bone-mute)">' + (data.captured_at || '').slice(0, 16).replace('T', ' ') + '</span>';
      }

      // 1b) Populate outcome counter tiles (§08 bottom row)
      const outDrafted = document.getElementById('out-drafted');
      const outGhosted = document.getElementById('out-ghosted');
      const outClassified = document.getElementById('out-classified');
      if (outDrafted) outDrafted.textContent = String(data.counts.drafted).padStart(2, '0');
      if (outGhosted) outGhosted.textContent = String(data.counts.ghosted).padStart(2, '0');
      if (outClassified) outClassified.textContent = String(data.counts.classified).padStart(2, '0');

      // 2) Render all lines as DOM (hidden initially via .terminal__line default styles)
      const lines = data.action_log || [];
      const frag = document.createDocumentFragment();
      lines.forEach(function (l) {
        frag.appendChild(renderLine(l));
      });
      termBody.appendChild(frag);
      // final cursor line
      const cursorLine = document.createElement('span');
      cursorLine.className = 'terminal__line';
      cursorLine.innerHTML = '<span class="ts">--:--:--</span><span>$</span><span class="terminal__cursor"></span>';
      termBody.appendChild(cursorLine);

      // 3) Reveal logic: scroll-driven, not time-driven, so it's bound to user action
      const lineEls = termBody.querySelectorAll('.terminal__line');
      const N = lineEls.length;

      if (reducedMotion) {
        // No animation: render all visible immediately, jump scroll to bottom
        lineEls.forEach(function (el) { el.classList.add('is-visible'); });
        if (termProgress) termProgress.style.transform = 'scaleX(1)';
        termBody.scrollTop = termBody.scrollHeight;
        return;
      }

      // Reveal each line once user has scrolled into the terminal panel.
      // Each reveal adds a small stagger so it feels typed.
      function revealUpTo(idx) {
        for (let i = 0; i < idx && i < N; i++) {
          lineEls[i].classList.add('is-visible');
        }
        if (termProgress) termProgress.style.transform = 'scaleX(' + Math.min(1, idx / N) + ')';
        // auto-scroll to keep current line in view
        const target = lineEls[Math.min(idx - 1, N - 1)];
        if (target) {
          const tbRect = termBody.getBoundingClientRect();
          const tRect = target.getBoundingClientRect();
          if (tRect.bottom > tbRect.bottom - 20) {
            termBody.scrollTop = termBody.scrollHeight;
          }
        }
      }

      // Use IntersectionObserver on the terminal panel itself: reveal a fraction of
      // lines proportional to how far the panel has scrolled through the viewport.
      const panel = document.querySelector('.terminal');
      if (!panel || !('IntersectionObserver' in window)) {
        revealUpTo(N);
        return;
      }

      // Compute reveal index from panel's visibility & scroll progress
      function tick() {
        const rect = panel.getBoundingClientRect();
        const vh = window.innerHeight;
        // progress: 0 when panel top enters bottom of viewport, 1 when panel bottom leaves top
        const total = rect.height + vh;
        const seen = vh - rect.top;
        const p = Math.max(0, Math.min(1, seen / total));
        const targetIdx = Math.max(1, Math.ceil(p * (N + 1)));
        if (targetIdx !== panel._lastIdx) {
          panel._lastIdx = targetIdx;
          revealUpTo(targetIdx);
        }
      }

      const io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            // start revealing as user scrolls
            window.addEventListener('scroll', tick, { passive: true });
            tick();
          }
        });
      }, { threshold: 0 });

      io.observe(panel);
    })
    .catch(function (err) {
      termBody.innerHTML =
        '<span class="terminal__line is-visible" style="color:var(--rust)">' +
        '[!] could not load data/tick-run.json — ' + (err.message || err) +
        '</span>';
    });
})();