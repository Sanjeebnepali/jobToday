(function () {
  const data = window.JOB_DATA || { meta: {}, jobs: [] };
  const allJobs = data.jobs || [];
  const meta = data.meta || {};

  const state = {
    search: "",
    source: "",
    categories: new Set(),
    freshOnly: false,
  };

  const $search = document.getElementById("search");
  const $sourceFilter = document.getElementById("source-filter");
  const $freshOnly = document.getElementById("fresh-only");
  const $reset = document.getElementById("reset-filters");
  const $chips = document.getElementById("category-chips");
  const $grid = document.getElementById("job-grid");
  const $count = document.getElementById("results-count");
  const $empty = document.getElementById("empty-state");
  const $statTotal = document.getElementById("stat-total");
  const $statFresh = document.getElementById("stat-fresh");
  const $statUpdated = document.getElementById("stat-updated");

  // ---------- Init stats ----------
  $statTotal.textContent = allJobs.length;
  $statFresh.textContent = allJobs.filter(isFresh).length;
  $statUpdated.textContent = formatRelative(meta.last_updated) || "—";

  // ---------- Init source dropdown ----------
  const sources = [...new Set(allJobs.map((j) => j.source))].sort();
  for (const s of sources) {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    $sourceFilter.appendChild(opt);
  }

  // ---------- Init category chips ----------
  const catCounts = {};
  for (const job of allJobs) {
    for (const c of job.categories || []) {
      catCounts[c] = (catCounts[c] || 0) + 1;
    }
  }
  const orderedCats = ["Junior", "React Native", "Android", "Frontend", "Backend", "Full Stack", "Web", "Mobile", "Other"];
  for (const cat of orderedCats) {
    if (!catCounts[cat]) continue;
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.dataset.cat = cat;
    chip.innerHTML = `${cat} <span class="count">${catCounts[cat]}</span>`;
    chip.addEventListener("click", () => {
      if (state.categories.has(cat)) {
        state.categories.delete(cat);
        chip.classList.remove("active");
      } else {
        state.categories.add(cat);
        chip.classList.add("active");
      }
      render();
    });
    $chips.appendChild(chip);
  }

  // ---------- Wire filters ----------
  $search.addEventListener("input", (e) => {
    state.search = e.target.value.trim().toLowerCase();
    render();
  });
  $sourceFilter.addEventListener("change", (e) => {
    state.source = e.target.value;
    render();
  });
  $freshOnly.addEventListener("change", (e) => {
    state.freshOnly = e.target.checked;
    render();
  });
  $reset.addEventListener("click", () => {
    state.search = "";
    state.source = "";
    state.categories.clear();
    state.freshOnly = false;
    $search.value = "";
    $sourceFilter.value = "";
    $freshOnly.checked = false;
    document.querySelectorAll(".chip.active").forEach((c) => c.classList.remove("active"));
    render();
  });

  render();

  // ---------- Helpers ----------
  function isFresh(job) {
    if (!job.first_seen) return false;
    const t = new Date(job.first_seen).getTime();
    if (isNaN(t)) return false;
    return Date.now() - t < 24 * 60 * 60 * 1000;
  }

  function formatRelative(iso) {
    if (!iso) return "";
    const t = new Date(iso).getTime();
    if (isNaN(t)) return iso;
    const diff = Date.now() - t;
    const min = Math.floor(diff / 60000);
    if (min < 1) return "just now";
    if (min < 60) return `${min}m ago`;
    const hrs = Math.floor(min / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  }

  function filterJobs() {
    return allJobs.filter((job) => {
      if (state.source && job.source !== state.source) return false;
      if (state.freshOnly && !isFresh(job)) return false;
      if (state.categories.size > 0) {
        const cats = new Set(job.categories || []);
        let ok = false;
        for (const c of state.categories) if (cats.has(c)) { ok = true; break; }
        if (!ok) return false;
      }
      if (state.search) {
        const hay = `${job.title} ${job.company} ${job.tags}`.toLowerCase();
        if (!hay.includes(state.search)) return false;
      }
      return true;
    });
  }

  function escapeHTML(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function jobCard(job) {
    const fresh = isFresh(job);
    const cats = (job.categories || []).slice(0, 3).map(
      (c) => `<span class="tag">${escapeHTML(c)}</span>`
    ).join("");

    const salary = (job.salary || "").trim();
    const empType = (job.employment_type || "").trim();
    const excerpt = (job.excerpt || "").trim();

    const detailRow = (salary || empType)
      ? `<div class="job-details">
           ${salary ? `<span class="detail-salary">💰 ${escapeHTML(salary)}</span>` : ""}
           ${empType ? `<span class="detail-type">${escapeHTML(empType)}</span>` : ""}
         </div>`
      : "";

    const excerptHTML = excerpt
      ? `<p class="job-excerpt">${escapeHTML(excerpt)}</p>`
      : "";

    return `
      <article class="job-card">
        <div class="job-card-header">
          <h3 class="job-title"><a href="${escapeHTML(job.url)}" target="_blank" rel="noopener">${escapeHTML(job.title)}</a></h3>
          ${fresh ? '<span class="badge-new">New</span>' : ""}
        </div>
        <div class="job-meta">
          <span class="job-company">${escapeHTML(job.company || "Unknown")}</span>
          <span class="dot"></span>
          <span>${escapeHTML(job.location || "Remote")}</span>
        </div>
        ${detailRow}
        ${excerptHTML}
        <div class="job-tags">
          ${cats}
          <span class="tag tag-source">${escapeHTML(job.source)}</span>
        </div>
        <div class="job-footer">
          <span class="job-time">${escapeHTML(formatRelative(job.first_seen) || "")}</span>
          <a class="apply-btn" href="${escapeHTML(job.url)}" target="_blank" rel="noopener">Apply →</a>
        </div>
      </article>
    `;
  }

  function render() {
    const filtered = filterJobs();
    $count.textContent =
      filtered.length === allJobs.length
        ? `Showing all ${filtered.length} jobs`
        : `Showing ${filtered.length} of ${allJobs.length} jobs`;
    if (filtered.length === 0) {
      $grid.innerHTML = "";
      $empty.classList.remove("hidden");
    } else {
      $empty.classList.add("hidden");
      $grid.innerHTML = filtered.map(jobCard).join("");
    }
  }
})();
