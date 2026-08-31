/* ============================================================
   NudgePilot — main.js
   Nav morph · scroll reveals · keyboard a11y · mesh orb parallax
   ============================================================ */

(function () {
  'use strict';

  /* ----- 1. NAV (floating pill + hamburger morph + overlay) ----- */
  const nav = document.querySelector('.nav');
  const burger = document.querySelector('.nav__burger');
  const overlay = document.querySelector('.nav-overlay');

  function closeNav() {
    if (!nav) return;
    nav.classList.remove('is-open');
    if (overlay) overlay.classList.remove('is-open');
    document.body.style.overflow = '';
    if (burger) burger.setAttribute('aria-expanded', 'false');
  }

  function openNav() {
    if (!nav) return;
    nav.classList.add('is-open');
    if (overlay) overlay.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    if (burger) burger.setAttribute('aria-expanded', 'true');
  }

  if (burger) {
    burger.addEventListener('click', function () {
      if (nav.classList.contains('is-open')) {
        closeNav();
      } else {
        openNav();
      }
    });
  }

  if (overlay) {
    overlay.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', closeNav);
    });
  }

  // ESC closes nav
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && nav && nav.classList.contains('is-open')) {
      closeNav();
    }
  });

  /* ----- 2. SCROLL-TRIGGERED REVEALS (IntersectionObserver) ----- */
  const reveals = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && reveals.length) {
    const io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          io.unobserve(entry.target);
        }
      });
    }, {
      threshold: 0.12,
      rootMargin: '0px 0px -8% 0px'
    });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    // Fallback: just show everything
    reveals.forEach(function (el) { el.classList.add('is-visible'); });
  }

  /* ----- 3. MESH-ORB PARALLAX (subtle, GPU-safe) ----- */
  const orbs = document.querySelectorAll('.mesh-bg .orb');
  if (orbs.length && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    let ticking = false;
    const onScroll = function () {
      if (!ticking) {
        window.requestAnimationFrame(function () {
          const y = window.scrollY;
          orbs.forEach(function (orb, i) {
            const speed = (i + 1) * 0.08;
            orb.style.transform = 'translate3d(0,' + (y * speed) + 'px,0)';
          });
          ticking = false;
        });
        ticking = true;
      }
    };
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  /* ----- 4. TERMINAL: render the action log from JSON, reveal lines on scroll ----- */
  // Delegated to live-tick.js; just provide the mount point.

  /* ----- 5. COST-BAR ANIMATIONS (fills animate when scrolled into view) ----- */
  const costFills = document.querySelectorAll('.cost-bar__fill[data-w]');
  if (costFills.length && 'IntersectionObserver' in window) {
    const cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          const w = e.target.getAttribute('data-w') || '0';
          // Cap at 100%
          e.target.style.width = Math.min(100, Math.max(0, Number(w) * 10)) + '%';
          cio.unobserve(e.target);
        }
      });
    }, { threshold: 0.3 });
    costFills.forEach(function (el) { cio.observe(el); });
  } else {
    costFills.forEach(function (el) {
      const w = el.getAttribute('data-w') || '0';
      el.style.width = Math.min(100, Math.max(0, Number(w) * 10)) + '%';
    });
  }

  /* ----- 6. CITATION LIST: build from sources.json ----- */
  const sourcesMount = document.getElementById('sources-mount');
  if (sourcesMount) {
    fetch('data/sources.json')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        const html = (data.sources || []).map(function (s) {
          return [
            '<a class="source reveal" href="', s.url, '" target="_blank" rel="noopener noreferrer">',
              '<span class="source__n">', String(s.n).padStart(2, '0'), '</span>',
              '<span>',
                '<div class="source__title">', s.title, '</div>',
                '<div class="source__src">', s.src, ' · ', s.blurb, '</div>',
              '</span>',
              '<span class="source__ext"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M 4 12 L 12 4 M 6 4 L 12 4 L 12 10"/></svg></span>',
            '</a>'
          ].join('');
        }).join('');
        sourcesMount.innerHTML = html;
        // Re-observe newly added reveal elements
        if ('IntersectionObserver' in window) {
          const io = new IntersectionObserver(function (entries) {
            entries.forEach(function (e) {
              if (e.isIntersecting) {
                e.target.classList.add('is-visible');
                io.unobserve(e.target);
              }
            });
          }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
          sourcesMount.querySelectorAll('.reveal').forEach(function (el) { io.observe(el); });
        }
      })
      .catch(function (err) {
        console.warn('sources.json failed to load', err);
      });
  }
})();