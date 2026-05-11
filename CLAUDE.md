# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

TimeJob is a single-user, local-first job dashboard. A Python script polls five free remote-job APIs/RSS feeds, filters them for junior/mid dev roles, and emits a static `jobs.js` data file that a no-build vanilla-JS dashboard (`index.html`) loads via `<script>` tag. There is no server, no database, no build step. Hourly refresh runs via Windows Task Scheduler (`TimeJob Refresh`) — `PRODUCTION.md` documents the migration path to GitHub Actions + Pages for cloud-hosted Phase 1.

## Common commands

All commands assume the working directory is the project root: `C:\Users\Sanju\TimeJob`.

```powershell
python agent.py            # poll all sources, write jobs.js + meta.json + seen_jobs.json
python agent.py --seed     # stamp every currently-posted job with now, then exit WITHOUT touching jobs.js
                           # (use to suppress "NEW" badges for the existing backlog; the dashboard data is unchanged)
python agent.py --login    # open visible Chromium; user logs in to arc.dev/LinkedIn/Indeed once
                           # (cookies persist in browser_profile/ for subsequent headless scrapes)
pip install -r requirements.txt
playwright install chromium  # one-time, required for the logged-in sources

# Open the dashboard
Start-Process index.html   # or bookmark file:///C:/Users/Sanju/TimeJob/index.html

# Manage the scheduled task
schtasks /Query  /TN "TimeJob Refresh"        # status
schtasks /Run    /TN "TimeJob Refresh"        # fire now
schtasks /Delete /TN "TimeJob Refresh" /F     # remove auto-run

# Optional local server (only if file:// causes browser issues)
python -m http.server 8000
```

There is no test suite, no linter, no build. Tuning means editing constants at the top of `agent.py` and re-running it.

## Data flow

```
agent.py  ──► seen_jobs.json     (id → first_seen ISO timestamp; dedup + freshness state)
agent.py  ──► meta.json          (last_updated + per-source scanned/matched counts)
agent.py  ──► jobs.js            (window.JOB_DATA = {meta, jobs}; the only data the page reads)
                  ▲
index.html, script.js, style.css ─ load jobs.js, render filters + cards, no fetch() calls
```

**Why `jobs.js` instead of `jobs.json`**: opening `index.html` via `file://` blocks `fetch("jobs.json")` in most browsers (CORS for local files). Loading the same payload via `<script src="jobs.js">` and assigning to `window.JOB_DATA` bypasses that entirely — the page works with a double-click, no local server required.

## Architecture details

### Source plugin pattern (`agent.py`)

Each platform is a generator function (e.g. `fetch_remotive`, `fetch_weworkremotely`) yielding a normalized dict:
```python
{"id", "title", "company", "location", "url", "tags", "source"}
```
The `PLATFORMS` list registers `(display_name, fetcher)` tuples. To add a source: write a generator, append to `PLATFORMS`. Per-source errors are caught and logged; one broken API never kills the whole run. IDs are always prefixed with the source slug (`remotive:`, `wwr:`, etc.) to keep namespaces clean across boards.

**Per-source quirks worth knowing**:
- **Remotive**: API returns the platform's *entire* current catalog (~20 jobs total). Don't expect a large yield — it's a curated small board.
- **WeWorkRemotely**: pulls from 4 category RSS feeds and concatenates. Each entry has no `tags` field, so inclusion matching for WWR effectively runs against the title alone.
- **Working Nomads**: `url` is a tracker-redirect (`workingnomads.com/job/go/<id>/`) that 302s to the original company posting. That's intentional — leave it; the redirect is what makes it free for the user to apply.
- **Arbeitnow**: heavily EU-focused; expect German-language titles like `Fullstack-Entwickler` to slip through the filter (which works because `fullstack` is still a substring match).
- **Jobicy**: `jobIndustry` and `jobType` are sometimes strings, sometimes lists — the fetcher normalizes both.

If a source's results vanish (matched count drops to 0), check whether the API changed its response schema before assuming a filter regression.

### Logged-in sources (`scrapers.py`)

Three platforms require an authenticated browser session and live in `scrapers.py` instead of `agent.py`: **arc.dev**, **LinkedIn**, and **Indeed KR**. They use Playwright with a *persistent* Chromium profile stored at `browser_profile/` — separate from the user's normal Chrome/Edge so the scraper never fights the user for cookies.

The lifecycle is:
1. User runs `python agent.py --login` once. Visible Chromium opens with three tabs (LinkedIn/Indeed KR/arc.dev login). User logs in. Pressing Enter closes the browser and persists cookies into `browser_profile/`.
2. Every subsequent `python agent.py` run launches headless Chromium against the same profile and scrapes the search URLs defined at the top of `scrapers.py` (`LINKEDIN_SEARCH_URL`, `INDEED_KR_SEARCH_URL`, `ARC_DEV_URL`).
3. The browser context is module-global with `atexit` cleanup — all three scrapers reuse a single Chromium launch instead of cold-starting one each.

`scrapers.py` exposes `HAVE_PLAYWRIGHT` and `agent.py` gates the platforms behind it, so a fresh checkout without Playwright installed still runs all five RSS sources normally — only the logged-in trio is skipped with a stderr warning.

**Selector fragility is expected.** LinkedIn/Indeed/arc.dev redesign their markup periodically. When a source's `matched` count drops to 0 in console output and the RSS sources still work, the first thing to check is the JS selectors inside the three `fetch_*` functions — not the role-keyword filter. Each scraper uses multiple selector fallbacks (`.job-card-container, [data-occludable-job-id], ...`) so partial breakage tends to still yield *some* results, which is the signal that a full selector refresh is overdue.

**LinkedIn caveats**: heavy scraping risks account flags. The default config polls one search page (~25 results), once per hour, with realistic UA and viewport. Don't crank this up. If LinkedIn starts serving sign-in walls or captchas in headless mode, flip `HEADLESS = False` at the top of `scrapers.py` — a visible browser usually bypasses bot detection because the persistent profile carries human-like fingerprint history.

**Search URLs are config, not constants of nature.** They're literal strings at the top of `scrapers.py` — when the user wants different filters (different location, different keywords, different recency window), edit those URLs rather than threading parameters through the fetcher signatures.

### Two-stage filter

1. **Inclusion** — `ROLE_KEYWORDS` (substring match on lowercased `title + tags`). At least one must hit.
2. **Exclusion** — `EXCLUDE_PATTERNS` (regex with word boundaries, applied to **title only**). Senior/lead/principal/staff/manager/architect + non-software "engineer" suffixes (design/quality/network) get dropped.

The exclusion runs on `title` (not the full text) on purpose: tags often legitimately contain words like "manager" that would over-filter. Word boundaries (`\b`) are required so `senior` matches `Senior Engineer` and `Mid-Senior` but not `seniority`.

**`FILTER_JOBS` toggle (top of `agent.py`)** — controls whether either of the above filters runs at all. Currently defaults to `False`: every scanned job is written to `jobs.js` and the dashboard's in-browser search/source/category filters do the narrowing. Flip to `True` to restore the original server-side filter (smaller `jobs.js`, faster page load, but you lose visibility into roles the keyword list doesn't anticipate). `categorize()` always runs regardless — jobs that don't match any category just land in "Other".

### Categories (`CATEGORY_RULES`)

A job can land in multiple categories (e.g. both "Frontend" and "Junior"). The dashboard's chip filter uses OR semantics across selected categories. Categories are computed at agent time and stored on each job in `jobs.js` — the frontend does not re-derive them.

### `seen_jobs.json` — dedup + freshness

Maps `job_id → first_seen_iso`. On every run, unseen IDs get stamped with `now`. This timestamp powers the dashboard's "NEW" badge (less than 24h since first_seen) and the "Posted Today" stat. `load_seen()` migrates the legacy list-of-IDs format to the dict format transparently — if you see `seen_jobs.json` as a JSON array in old branches/backups, the migration handles it but `first_seen` will be empty string (so those jobs never appear "fresh").

The file is read via `encoding="utf-8-sig"` so a BOM (e.g. from PowerShell `Out-File`) doesn't silently corrupt the dedup state into an empty set. Writes always use `utf-8` (no BOM) — this asymmetry is intentional: tolerate junk on read, emit clean bytes on write.

**First-run behavior**: when `seen_jobs.json` is missing, the agent runs normally — every fetched job is treated as unseen and stamped with the current run's `now`. The dashboard will then show every matching job as "fresh in last 24h" until the next agent run replaces the data. If you want a clean baseline without the badge flood, run `python agent.py --seed` first (it stamps everything but doesn't write `jobs.js`), then a normal `python agent.py`.

### Frontend (`index.html` + `script.js` + `style.css`)

- Vanilla JS, no framework, no bundler.
- `script.js` reads `window.JOB_DATA` synchronously at IIFE start. If the agent hasn't run yet, `JOB_DATA` is undefined and the page falls back to `{meta:{}, jobs:[]}`.
- All filter state lives in a single `state` object; every UI change calls `render()` which re-derives the filtered list and rewrites `#job-grid.innerHTML`. Acceptable for ~100 cards; if the list grows past ~1000, switch to incremental DOM updates.
- All user-supplied strings flow through `escapeHTML()` before going into `innerHTML` templates. Don't bypass this when adding new fields — job titles from external APIs are untrusted input.

## When changing things

- **Adding a new source**: write the fetcher, add to `PLATFORMS`, run `python agent.py` once. Check the new platform's row in console output and the source dropdown on the dashboard. If a source needs auth, store the key in env vars and load via `os.getenv()` — don't commit it.
- **Filters too loose / too tight**: edit `ROLE_KEYWORDS` or `EXCLUDE_PATTERNS`, then run `python agent.py`. The console prints per-source `scanned, matched` counts — the fastest sanity check. Reload the dashboard tab to see the new list. Categories and matches re-derive every run from the current keyword tables; only `first_seen` is sticky. Delete `seen_jobs.json` *only* if you want fresh first-seen timestamps (e.g. after a big filter change that admits previously-rejected jobs you'd like badged as "new").
- **Changing the `jobs.js` schema**: also update `script.js` (it reads `job.title/company/location/url/source/tags/categories/first_seen`) and the JSDoc-ish field references in `jobCard()`.
- **Cross-platform paths**: `agent.py` uses `Path(__file__).parent` for all file IO, so it works whether invoked via `python agent.py`, an absolute path, or a scheduled task with a different working directory.
- **Recreating the scheduled task**: the existing `TimeJob Refresh` task was created with the *absolute* path to `python.exe`, not a bare `python`. Non-interactive scheduled contexts on Windows often have a different PATH than the user's shell, and bare `python` can fail to resolve. Always pass `C:\Users\Sanju\AppData\Local\Programs\Python\Python311\python.exe` (or whatever `(Get-Command python).Source` returns) when re-creating via `schtasks /Create`.

## Gotchas

- **Don't hand-edit `seen_jobs.json` with PowerShell `Out-File`** (or anything that emits UTF-8 with BOM). `load_json` does survive a BOM via `utf-8-sig`, but `Get-Content` displays the contents with mojibake and a careless re-save can compound encoding issues. Use Python or a UTF-8-safe editor.
- **Filters operate on lowercased title+tags for inclusion, raw title (any case) for exclusion**. `EXCLUDE_RE` is compiled with `re.IGNORECASE`, so case doesn't matter for exclusion — but if you add new include keywords, lowercase them.
- **Job IDs are source-prefixed but otherwise opaque**. RemoteOK numeric IDs and slug fallbacks both work; don't assume any specific shape when grepping or filtering by ID.
- **`meta.json` duplicates the meta block already embedded in `jobs.js`**. It exists as a standalone file purely for debugging/monitoring (cron jobs, status badges) — the dashboard reads only `jobs.js`.

## Related docs

- `README.md` — end-user setup (Task Scheduler, filter tuning, troubleshooting)
- `PRODUCTION.md` — phased roadmap for cloud hosting (GitHub Actions + Pages), LLM-scored filtering, multi-user expansion
