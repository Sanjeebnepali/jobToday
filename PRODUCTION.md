# Going to Production — TimeJob

This document maps out what to do if you want to take TimeJob beyond a local Windows-only tool. Read it top-to-bottom — items are ordered **highest impact / lowest effort first**.

You don't need to do everything. Pick the phase that matches your ambition:

| If your goal is… | Do at least… |
|---|---|
| "I want it always available, even when my PC is off" | Phase 1 |
| "I want it polished + reliable + smarter filtering" | Phase 1 + 2 |
| "I want other people to use it too" | Phase 1 + 2 + 3 |

---

## Phase 1 — Make it always-on and accessible from your phone

The biggest limitation right now: TimeJob only runs when your PC is on. Phase 1 fixes that and gives you a public URL you can open from any device.

### 1.1 Move the agent to GitHub Actions (free, runs every hour in the cloud)

**Why**: GitHub Actions gives you a free Linux machine that runs your script on a schedule. No PC required, no cost, no signups.

**Steps**:

1. Create a free account at [github.com](https://github.com) if you don't have one
2. Create a new repository called `timejob` (set it to **public** — GitHub Actions on private repos has a free-minute cap)
3. Push the `TimeJob` folder contents to that repo:
   ```powershell
   cd C:\Users\Sanju\TimeJob
   git init
   git add agent.py index.html style.css script.js requirements.txt README.md PRODUCTION.md
   git commit -m "Initial TimeJob commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/timejob.git
   git push -u origin main
   ```
4. Create a `.github/workflows/refresh.yml` file with this content:
   ```yaml
   name: Refresh jobs
   on:
     schedule:
       - cron: "0 * * * *"   # every hour at minute 0
     workflow_dispatch:        # also lets you trigger manually
   jobs:
     refresh:
       runs-on: ubuntu-latest
       permissions:
         contents: write
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with: { python-version: "3.11" }
         - run: pip install -r requirements.txt
         - run: python agent.py
         - name: Commit updated jobs
           run: |
             git config user.name "github-actions"
             git config user.email "actions@github.com"
             git add jobs.js seen_jobs.json meta.json
             git diff --cached --quiet || git commit -m "chore: refresh jobs"
             git push
   ```
5. Push that file. Go to **GitHub → your repo → Actions** tab — you'll see the workflow scheduled.

**Time**: 30 minutes. **Cost**: $0. **Result**: jobs refresh every hour in the cloud, even with your PC off.

### 1.2 Host the dashboard on GitHub Pages (public URL, free)

**Why**: Once the data lives in your repo, you can serve the dashboard for free from `https://YOUR_USERNAME.github.io/timejob/`.

**Steps**:
1. In your repo: **Settings → Pages → Source: Deploy from a branch → `main` / `(root)` → Save**
2. Wait ~1 minute, then open `https://YOUR_USERNAME.github.io/timejob/`
3. Bookmark it on your phone. Add it to your home screen on iOS (Safari → Share → Add to Home Screen) or Android (Chrome → ⋮ → Install app).

**Time**: 5 minutes. **Cost**: $0. **Result**: dashboard accessible from anywhere, including your phone.

### 1.3 Delete the Windows scheduled task

Once cloud refresh works:
```powershell
schtasks /Delete /TN "TimeJob Refresh" /F
```

Your PC no longer needs to be involved at all.

### 1.4 Get notified when the agent breaks

GitHub already emails you when a workflow fails. Make sure your GitHub account email is correct. To customize:
- **Settings → Notifications → Actions → Email** on failure.

---

## Phase 2 — Reliability, smarter filtering, better UX

### 2.1 Add error handling and a status badge

Currently if a job board's API changes, the agent silently logs an error and moves on. For production:
- Add per-source retry with exponential backoff (use `tenacity` library)
- Add a "stale source" warning: if a source returns 0 jobs for 3 runs in a row, flag it in `meta.json` and show a warning banner in the dashboard
- Add a GitHub Actions status badge to your `README.md`:
  ```markdown
  ![Refresh status](https://github.com/YOUR_USERNAME/timejob/actions/workflows/refresh.yml/badge.svg)
  ```

### 2.2 Use an LLM to score each job (way better filtering)

**The problem**: keyword filters miss nuance. "Junior Mobile Engineer" with a JD requiring 5 years experience slips through. A senior-titled job that actually accepts juniors gets blocked.

**The fix**: have Claude (or any LLM) read each new job's description and assign a 0–100 "fit for junior dev" score. Filter to score >= 60 in the dashboard.

- Use Anthropic's API: `claude-haiku-4-5-20251001` is the cheapest model
- 1 call per new job × ~50 new jobs/day × ~500 tokens each = ~$0.50/month total
- Cache responses in `seen_jobs.json` so a job is only scored once

```python
# pseudocode inside agent.py
import anthropic
client = anthropic.Anthropic()

def llm_score(job):
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[{"role": "user", "content": f"Rate this job's fit for a junior developer (0-100). Return only the number.\n\nTitle: {job['title']}\nDescription: {job.get('description', '')[:1000]}"}],
    )
    return int(resp.content[0].text.strip())
```

Set the API key as a GitHub Actions secret (`ANTHROPIC_API_KEY`) and reference it in the workflow file.

**Time**: 2–3 hours. **Cost**: < $1/month. **Result**: dramatically fewer false matches.

### 2.3 Persist application state ("I applied to this")

Right now you can't track which jobs you've applied to. Add:
- An "Applied ✓" button on each card
- Store the applied set in `localStorage` (browser-side, no server needed)
- Add a filter chip: "Hide already-applied"

This is a 30-minute frontend change to `script.js`. No backend required.

### 2.4 Add more free sources

Free APIs you can integrate (no payment, no key):
- **Hacker News "Who is hiring"** — monthly thread, use the Algolia HN API: `https://hn.algolia.com/api/v1/search?tags=comment,story_45000000`
- **GitHub Jobs alternatives** — `https://www.larajobs.com/feed` (Laravel-specific, RSS), `https://golangprojects.com/golang-jobs.json`
- **Native Indian boards** — many have unofficial scraping libraries on GitHub; if you find one you can wrap, do it

### 2.5 Salary parsing and a "min salary" filter

Job descriptions often have salaries in the body. Use a regex like `r"\$?\s*\d{2,3}[k,K]\s*[-–]\s*\$?\d{2,3}[k,K]"` to extract ranges. Surface as a filter slider in the dashboard.

### 2.6 Frontend polish

- **Dark mode** — `prefers-color-scheme` media query in CSS, takes 15 min
- **URL-shareable filters** — sync state to `window.location.hash`, lets you share `?q=react&category=Junior` links
- **Job description preview** — pull `description` from APIs that include it (RemoteOK, Remotive, Himalayas), show in a modal on click

---

## Phase 3 — Going public (multi-user product)

Only do this if you genuinely want other people to use it. Big jump in complexity.

### 3.1 Real backend

Replace `jobs.js` with a database:
- **Supabase** (free tier: 500 MB Postgres + auth) — easiest path
- **Cloudflare D1** (free SQLite) — second easiest
- **Self-host Postgres on Fly.io / Railway** — more control

Schema sketch:
```sql
CREATE TABLE jobs (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  company     TEXT,
  location    TEXT,
  url         TEXT NOT NULL,
  source      TEXT,
  categories  TEXT[],
  first_seen  TIMESTAMPTZ NOT NULL,
  description TEXT,
  llm_score   INT
);
CREATE INDEX jobs_first_seen_idx ON jobs(first_seen DESC);
```

### 3.2 User accounts and per-user preferences

Supabase Auth (Google login) handles this in ~50 lines. Schema:
```sql
CREATE TABLE user_preferences (
  user_id      UUID PRIMARY KEY REFERENCES auth.users(id),
  role_filters TEXT[],
  min_salary   INT,
  locations    TEXT[]
);
CREATE TABLE applied_jobs (
  user_id  UUID REFERENCES auth.users(id),
  job_id   TEXT REFERENCES jobs(id),
  applied_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (user_id, job_id)
);
```

### 3.3 Rebuild the frontend in a real framework

Once you have auth + multiple views, vanilla JS gets painful. Recommended:
- **Next.js** (React) — most popular, easy Vercel deploy
- **SvelteKit** — leaner, you'd learn faster as a junior

Deploy on Vercel or Cloudflare Pages (free tiers generous).

### 3.4 Legal / compliance basics

If you're collecting user data:
- Terms of Service + Privacy Policy (use a generator like termsfeed.com)
- Cookie banner if you have EU users (GDPR)
- Don't redistribute job data in a way that violates the source platforms' ToS — read each one. WWR RSS is fine to republish; some APIs require attribution or disallow commercial use.

### 3.5 Cost at scale

| Users | Hosting | DB | LLM scoring | Total |
|---|---|---|---|---|
| 1 (you) | Free (Pages) | Free (Supabase) | $1/mo | **~$1/mo** |
| 100 | Free | Free | $5/mo | **~$5/mo** |
| 1,000 | $5/mo (Vercel) | $25/mo (Supabase Pro) | $30/mo | **~$60/mo** |
| 10,000 | $20/mo | $25/mo | $200/mo | **~$245/mo** |

At ~100 users you'd want to start charging or running affiliate links to break even.

---

## Reliability checklist

Before calling anything "production":

- [ ] Agent has retry logic for transient API failures
- [ ] You're notified within 24 hours if the agent breaks
- [ ] `seen_jobs.json` doesn't grow unbounded — entries older than 90 days are pruned
- [ ] Source-level error isolation: one broken API doesn't kill the whole run
- [ ] Dashboard handles "no data" gracefully (shows a helpful message, not a blank page)
- [ ] No secrets in the repo (API keys live in GitHub Actions secrets)
- [ ] You have a way to roll back: keep last N versions of `jobs.js` in git history (already free with the workflow above)

---

## What to do *first*

If you only have one hour today:

1. Create the GitHub repo
2. Add `.github/workflows/refresh.yml`
3. Turn on GitHub Pages
4. Open the public URL on your phone, add to home screen
5. Delete the Windows scheduled task

That single hour gets you from "Windows-only tool" to "production-quality personal job radar accessible from anywhere, free forever."

Phase 2 and 3 are for later — start with Phase 1, use it for a week, and you'll know what feature you actually want next.
