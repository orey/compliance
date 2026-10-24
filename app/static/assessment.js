// Assessment work page: autosave each answer, live KPIs, filtering.
(() => {
  const form = document.getElementById('assessmentForm');
  if (!form) return;
  const locked = form.dataset.locked === '1';
  const baseUrl = form.dataset.autosaveUrl.replace(/\/0$/, '/');
  const saveState = document.getElementById('saveState');
  let pending = 0;

  function setState(text, cls) {
    saveState.textContent = text;
    saveState.className = `ms-auto save-state small ${cls}`;
  }

  function updateKpis(data) {
    for (const [key, value] of Object.entries(data.counts)) {
      const el = document.getElementById(`kpi-${key}`);
      if (el) el.textContent = value;
    }
    document.getElementById('kpi-progress').textContent = data.progress;
    document.getElementById('kpi-progress-bar').style.width = `${data.progress}%`;
    document.getElementById('kpi-score').textContent = data.score ?? 'n/a';
    document.getElementById('kpi-review').textContent = data.needs_review;
  }

  async function save(card, payload) {
    pending++;
    setState('Saving…', 'text-muted');
    try {
      const resp = await fetch(baseUrl + card.dataset.id, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || resp.statusText);
      updateKpis(data);
      if (--pending === 0) setState('All changes saved ✓', 'text-success');
    } catch (err) {
      pending--;
      setState(`Not saved: ${err.message}`, 'text-danger');
    }
  }

  if (!locked) {
    form.addEventListener('change', (e) => {
      if (!e.target.classList.contains('status-radio')) return;
      const card = e.target.closest('.req-card');
      card.dataset.status = e.target.value || 'not_assessed';
      card.dataset.review = '0';
      card.querySelector('.review-badge').classList.add('d-none');
      save(card, { status: e.target.value });
    });

    form.addEventListener('click', (e) => {
      const badge = e.target.closest('.review-badge');
      if (!badge) return;
      const card = badge.closest('.req-card');
      card.dataset.review = '0';
      badge.classList.add('d-none');
      const status = card.dataset.status === 'not_assessed' ? '' : card.dataset.status;
      save(card, { status });  // re-sending the current answer confirms it
    });

    const timers = new WeakMap();
    form.addEventListener('input', (e) => {
      if (!e.target.classList.contains('autosave')) return;
      const el = e.target;
      setState('Editing…', 'text-muted');
      clearTimeout(timers.get(el));
      timers.set(el, setTimeout(() => save(el.closest('.req-card'), { [el.dataset.field]: el.value }), 700));
    });

    window.addEventListener('beforeunload', (e) => {
      if (pending > 0) { e.preventDefault(); e.returnValue = ''; }
    });
  }

  // Filtering by status / review flag / free text.
  let filter = '';
  const search = document.getElementById('search');
  function applyFilter() {
    const q = search.value.trim().toLowerCase();
    const visibleSections = new Set();
    document.querySelectorAll('.req-card').forEach((card) => {
      const matchStatus = !filter || (filter === 'review' ? card.dataset.review === '1' : card.dataset.status === filter);
      const text = card.innerText.toLowerCase() + ' ' +
        [...card.querySelectorAll('textarea')].map((t) => t.value.toLowerCase()).join(' ');
      const show = matchStatus && (!q || text.includes(q));
      card.classList.toggle('d-none', !show);
      if (show) visibleSections.add(card.dataset.section);
    });
    document.querySelectorAll('.section-title').forEach((h) => {
      h.classList.toggle('d-none', !visibleSections.has(h.dataset.section));
    });
  }
  document.querySelectorAll('#filters [data-filter]').forEach((btn) => {
    btn.addEventListener('click', () => {
      filter = btn.dataset.filter;
      document.querySelectorAll('#filters [data-filter]').forEach((b) => {
        b.classList.toggle('btn-dark', b === btn);
        b.classList.toggle('btn-outline-dark', b !== btn);
      });
      applyFilter();
    });
  });
  search.addEventListener('input', applyFilter);
})();
