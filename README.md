# TimeJob — your remote dev job dashboard

A single-page dashboard that shows fresh remote developer jobs filtered for **junior**, **React Native**, **Android**, **frontend**, **backend**, **full-stack**, and **DevOps** roles. No backend, no signups, no email — just open `index.html` in your browser.

**Every source listed below is 100% free** — apply links go directly to the company's application page, no subscription popups.

## How it works

```
   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
   │  agent.py    │   →     │   jobs.js    │   ←     │  index.html  │
   │  (Python)    │  writes │  (data)      │  loads  │  (dashboard) │
   └──────────────┘         └──────────────┘         └──────────────┘
          │
          ▼
   Polls 5 free job boards (no paywalls),
   filters out senior roles, dedupes,
   tracks "first seen" timestamps.
```

- Run `python agent.py` once → it fills `jobs.js` with the latest matching jobs
- Open `index.html` in your browser → live dashboard with filters and search
- Schedule the agent to run hourly via Task Scheduler → reload the page anytime to see updates

## Files (all in `C:\Users\Sanju\TimeJob\`)

| File | Purpose |
|---|---|
| `agent.py` | Polls job boards, filters, writes `jobs.js` |
| `index.html` + `style.css` + `script.js` | The dashboard UI |
| `jobs.js` | Auto-generated data file (don't edit by hand) |
| `seen_jobs.json` | Tracks when each job was first spotted (powers the "NEW" badge) |
| `meta.json` | Last run timestamp + per-source counts |
| `requirements.txt` | Python dependencies (already installed) |

## Sources (all free, no paywalls)

| Platform | Why |
|---|---|
| **Remotive** | Curated remote jobs, direct company application links |
| **WeWorkRemotely** | Programming + frontend + backend + full-stack RSS — biggest source |
| **Arbeitnow** | EU + global remote (great for German/European companies) |
| **Jobicy** | Curated remote roles, sometimes India-friendly |
| **Working Nomads** | Aggregator with direct redirects to original postings |

RemoteOK was removed because it shows a subscription popup when you click Apply.
LinkedIn isn't included (it blocks scraping). If you want LinkedIn later we'd need a paid API (~$10/mo).

---

## Daily use

### 1. See current jobs
Double-click `index.html` in `C:\Users\Sanju\TimeJob\` — it'll open in your default browser.
Bookmark `file:///C:/Users/Sanju/TimeJob/index.html` for one-click access.

### 2. Filter and search
- **Search box** — filter by title/company (e.g. type "react" or "node")
- **Source dropdown** — limit to one job board
- **Role chips** — click any to filter; click again to unselect; multiple = "show jobs matching any"
- **Fresh (24h) only** — shows just jobs added in the last day
- **Clear filters** — reset

### 3. Apply
Each card has an "Apply →" button that opens the original company posting in a new tab.

---

## Refresh the job list

### Manually (anytime)

```powershell
python C:\Users\Sanju\TimeJob\agent.py
```

Then reload the browser tab.

### Automatically every hour (recommended)

**Option A — quickest, one PowerShell command:**

```powershell
schtasks /Create /TN "TimeJob Refresh" /TR "python C:\Users\Sanju\TimeJob\agent.py" /SC HOURLY /F
```

Then run it once now so the first refresh fires right away:

```powershell
schtasks /Run /TN "TimeJob Refresh"
```

**Option B — visual setup via Task Scheduler GUI:**

Open **Task Scheduler** (Win key → type "Task Scheduler") and:

1. **Create Basic Task** → Name: `TimeJob Refresh`
2. **Trigger**: Daily → Recur every: 1 day
3. **Action**: Start a program
   - **Program**: `python`
   - **Arguments**: `C:\Users\Sanju\TimeJob\agent.py`
   - **Start in**: `C:\Users\Sanju\TimeJob`
4. Click **Finish**
5. Right-click the task → **Properties** → **Triggers** → **Edit** → check **Repeat task every: 1 hour** → for a duration of: **Indefinitely** → OK
6. (Optional) Under **General** tab, tick **Run whether user is logged on or not** so it refreshes even when you're not signed in

The PC must be **on** for the scheduled run to fire (sleep is OK if you allow wake-on-task).

**Useful follow-up commands:**

```powershell
schtasks /Query /TN "TimeJob Refresh"     # check status
schtasks /Run   /TN "TimeJob Refresh"     # run it right now
schtasks /Delete /TN "TimeJob Refresh" /F # remove the schedule
```

---

## Tuning the filters

Edit the top of `agent.py`:

- **`ROLE_KEYWORDS`** — title or tags must contain at least one. Add (`"data engineer"`, `"qa engineer"`) to broaden; remove some to narrow.
- **`EXCLUDE_PATTERNS`** — regex patterns; if any matches the title the job is dropped. This is how senior/lead/principal roles get filtered out.
- **`CATEGORY_RULES`** — controls the role chips in the dashboard.

After editing, run `python agent.py` to refresh.

## Manual commands

```powershell
python agent.py            # poll all sources and refresh jobs.js
python agent.py --seed     # mark all currently-posted jobs as already-seen (skip "New" badges for them)
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard says "Loading jobs…" forever | `jobs.js` is missing — run `python agent.py` once |
| Same jobs shown for days | Scheduled task isn't firing — `schtasks /Query /TN "TimeJob Refresh"` to check |
| No jobs at all | Filters too strict — broaden `ROLE_KEYWORDS` in `agent.py` |
| Want to start fresh | Delete `seen_jobs.json` then run `python agent.py` |
| Apply link redirects oddly | All 5 sources go to the original company posting — sometimes the company itself has a login wall (not the job board's fault) |
