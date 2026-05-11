"""
Job-watcher agent.

Polls free remote job boards, filters for junior / React Native / Android /
frontend / backend / full-stack / web-dev roles, tracks when each job was
first seen, and writes the full filtered list to jobs.js so the local
dashboard (index.html) can render it.

Usage:
    python agent.py            # poll + update jobs.js
    python agent.py --seed     # mark everything currently posted as already-seen
    python agent.py --login    # open browser; log in to arc.dev/LinkedIn/Indeed once
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).parent
SEEN_FILE = ROOT / "seen_jobs.json"      # {id: first_seen_iso}
JOBS_JS = ROOT / "jobs.js"               # window.JOBS payload for the dashboard
META_FILE = ROOT / "meta.json"           # last run timestamp + counts

ROLE_KEYWORDS = [
    "react native", "react-native",
    "android developer", "android engineer",
    "frontend", "front-end", "front end",
    "backend", "back-end", "back end",
    "full stack", "fullstack", "full-stack",
    "web developer", "web engineer",
    "mobile developer", "mobile engineer",
    "software developer", "software engineer", "software development engineer",
    "javascript developer", "react developer", "node developer", "node.js developer",
    "python developer", "java developer", "php developer",
    "frontend engineer", "backend engineer", "fullstack engineer", "full-stack engineer",
    "ui developer", "ui engineer", "ux engineer",
    "ios developer", "ios engineer",
    "programmer", "devops engineer",
]

EXCLUDE_PATTERNS = [
    r"\bsenior\b", r"\bsr\.?\b",
    r"\blead\b", r"\bprincipal\b", r"\bstaff\b",
    r"\bdirector\b", r"\barchitect\b", r"\bmanager\b",
    r"\bvp\b", r"vice president", r"head of",
    r"design engineer", r"quality engineer", r"\bqa engineer\b",
    r"network engineer", r"systems research",
    r"\d+\+\s*years",
]

EXCLUDE_RE = re.compile("|".join(EXCLUDE_PATTERNS), re.IGNORECASE)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _excerpt(text, limit=220):
    """Strip HTML tags and collapse whitespace; truncate to roughly `limit` chars
    at a word boundary. Returns empty string if input is falsy."""
    if not text:
        return ""
    plain = _HTML_TAG_RE.sub(" ", str(text))
    plain = _WHITESPACE_RE.sub(" ", plain).strip()
    if len(plain) <= limit:
        return plain
    cut = plain[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def _salary_range(lo, hi, currency="USD"):
    """Format numeric salary_min / salary_max into '$80k – $120k' style. Skips
    zero / None values gracefully."""
    def _fmt(n):
        try:
            n = float(n)
        except (TypeError, ValueError):
            return None
        if n <= 0:
            return None
        if n >= 1000:
            return f"{int(round(n / 1000))}k"
        return str(int(n))
    a, b = _fmt(lo), _fmt(hi)
    sym = "$" if (currency or "").upper() == "USD" else f"{currency} "
    if a and b:
        return f"{sym}{a} – {sym}{b}"
    if a or b:
        return f"{sym}{a or b}"
    return ""

CATEGORY_RULES = [
    ("React Native", ["react native", "react-native"]),
    ("Android",      ["android"]),
    ("Frontend",     ["frontend", "front-end", "front end"]),
    ("Backend",      ["backend", "back-end", "back end"]),
    ("Full Stack",   ["full stack", "fullstack", "full-stack"]),
    ("Web",          ["web developer", "web engineer"]),
    ("Mobile",       ["mobile developer", "mobile engineer"]),
    ("Junior",       ["junior", "entry level", "entry-level", "fresher", "trainee", "graduate"]),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (job-agent for personal use)"}
TIMEOUT = 20

# If True, agent.py drops jobs that don't match ROLE_KEYWORDS / hit EXCLUDE_PATTERNS
# before writing jobs.js (the original behavior — server-side narrowing).
# If False, every scanned job is written through; the dashboard's search /
# source / category filters do all the narrowing in the browser. Flip this
# back to True if jobs.js gets too big to render comfortably.
FILTER_JOBS = False


def fetch_remotive():
    """Remotive — free remote-jobs API. Application links go straight to the company."""
    r = requests.get(
        "https://remotive.com/api/remote-jobs",
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    for item in data.get("jobs", []):
        tags_list = item.get("tags") or []
        extra = [item.get("category", ""), item.get("job_type", "")]
        yield {
            "id": f"remotive:{item.get('id')}",
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "location": item.get("candidate_required_location", "") or "Remote",
            "url": item.get("url", ""),
            "tags": " ".join([t for t in tags_list + extra if t]),
            "source": "Remotive",
            "salary": item.get("salary", "") or "",
            "employment_type": item.get("job_type", "") or "",
            "excerpt": _excerpt(item.get("description", "")),
            "posted_date": item.get("publication_date", "") or "",
        }


def fetch_weworkremotely():
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    ]
    for feed_url in feeds:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            company = ""
            if entry.get("title") and ":" in entry.title:
                company = entry.title.split(":", 1)[0].strip()
            yield {
                "id": f"wwr:{entry.get('id') or entry.link}",
                "title": entry.title,
                "company": company,
                "location": "Remote",
                "url": entry.link,
                "tags": "",
                "source": "WeWorkRemotely",
                "salary": "",
                "employment_type": "",
                "excerpt": _excerpt(entry.get("summary", "")),
                "posted_date": entry.get("published", "") or "",
            }


def fetch_arbeitnow():
    r = requests.get("https://www.arbeitnow.com/api/job-board-api", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    for item in data.get("data", []):
        job_types = item.get("job_types") or []
        yield {
            "id": f"arbeitnow:{item.get('slug')}",
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "location": item.get("location", "") or "Remote",
            "url": item.get("url", ""),
            "tags": " ".join((item.get("tags") or []) + job_types),
            "source": "Arbeitnow",
            "salary": "",
            "employment_type": ", ".join(job_types),
            "excerpt": _excerpt(item.get("description", "")),
            "posted_date": item.get("created_at", "") or "",
        }


def fetch_working_nomads():
    """Working Nomads — free, redirects directly to original posting."""
    r = requests.get(
        "https://www.workingnomads.com/api/exposed_jobs/?category=development",
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    for item in data:
        url = item.get("url", "")
        slug = url.rstrip("/").split("/")[-1] if url else item.get("title", "")
        yield {
            "id": f"wnomads:{slug}",
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "location": item.get("location", "") or "Remote",
            "url": url,
            "tags": item.get("tags", "") or "",
            "source": "Working Nomads",
            "salary": "",
            "employment_type": "",
            "excerpt": _excerpt(item.get("description", "")),
            "posted_date": item.get("pub_date", "") or "",
        }


def fetch_remoteok():
    """RemoteOK — free JSON API. First element is a legal disclaimer; skip it."""
    r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    for item in data:
        if not isinstance(item, dict) or not item.get("id"):
            continue  # disclaimer entry
        tags = item.get("tags") or []
        yield {
            "id": f"remoteok:{item.get('id')}",
            "title": item.get("position", "") or item.get("title", ""),
            "company": item.get("company", ""),
            "location": item.get("location", "") or "Remote",
            "url": item.get("url", "") or f"https://remoteok.com/remote-jobs/{item.get('slug', '')}",
            "tags": " ".join(tags) if isinstance(tags, list) else str(tags),
            "source": "RemoteOK",
            "salary": _salary_range(item.get("salary_min"), item.get("salary_max")),
            "employment_type": "",
            "excerpt": _excerpt(item.get("description", "")),
            "posted_date": item.get("date", "") or "",
        }


def fetch_himalayas():
    """Himalayas — free JSON API. Hard-caps each response at 20 regardless of
    limit/pageSize params; only `offset` actually paginates. We pull 5 pages
    (100 jobs) and let the role-keyword filter do the narrowing."""
    seen_titles = set()
    for offset in (0, 20, 40, 60, 80):
        try:
            r = requests.get(
                f"https://himalayas.app/jobs/api?offset={offset}",
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            break
        jobs = data.get("jobs", [])
        if not jobs:
            break
        for item in jobs:
            title = item.get("title", "")
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            cats = item.get("categories") or []
            seniority = item.get("seniority") or []
            loc_list = item.get("locationRestrictions") or []
            slug = item.get("companySlug", "") or title.lower().replace(" ", "-")[:60]
            yield {
                "id": f"himalayas:{slug}:{title[:80]}",
                "title": title,
                "company": item.get("companyName", ""),
                "location": ", ".join(loc_list) if loc_list else "Remote",
                "url": f"https://himalayas.app/jobs/{slug}" if slug else "https://himalayas.app/jobs",
                "tags": " ".join(cats + seniority + [item.get("employmentType", "")]),
                "source": "Himalayas",
                "salary": _salary_range(item.get("minSalary"), item.get("maxSalary"), item.get("currency", "USD")),
                "employment_type": item.get("employmentType", "") or "",
                "excerpt": _excerpt(item.get("excerpt", "") or item.get("description", "")),
                "posted_date": "",
            }


def fetch_hn_jobs():
    """Hacker News /jobs section (Firebase API). One request for the ID list,
    then one per item. Cap at 25 to keep the run snappy."""
    list_resp = requests.get(
        "https://hacker-news.firebaseio.com/v0/jobstories.json",
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    list_resp.raise_for_status()
    ids = list_resp.json() or []
    for jid in ids[:25]:
        try:
            r = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{jid}.json",
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            item = r.json() or {}
        except Exception:
            continue
        title = item.get("title", "") or ""
        # Title shape: "Company (YC W22) Is Hiring a Senior Frontend Engineer"
        # Extract company as everything before the first " (" or " Is Hiring".
        company = title
        for sep in [" (", " Is Hiring", " is hiring", " is Hiring"]:
            idx = title.find(sep)
            if idx > 0:
                company = title[:idx].strip()
                break
        yield {
            "id": f"hn:{item.get('id')}",
            "title": title,
            "company": company,
            "location": "Remote",
            "url": item.get("url", "") or f"https://news.ycombinator.com/item?id={item.get('id')}",
            "tags": "",
            "source": "Hacker News",
            "salary": "",
            "employment_type": "",
            "excerpt": _excerpt(item.get("text", "")),
            "posted_date": "",
        }


def fetch_jobicy():
    r = requests.get("https://jobicy.com/api/v2/remote-jobs?count=50", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    for item in data.get("jobs", []):
        industry = item.get("jobIndustry") or []
        jtype = item.get("jobType") or []
        if isinstance(industry, str):
            industry = [industry]
        if isinstance(jtype, str):
            jtype = [jtype]
        yield {
            "id": f"jobicy:{item.get('id')}",
            "title": item.get("jobTitle", ""),
            "company": item.get("companyName", ""),
            "location": item.get("jobGeo", "") or "Remote",
            "url": item.get("url", ""),
            "tags": " ".join(industry + jtype),
            "source": "Jobicy",
            "salary": item.get("annualSalary", "") or "",
            "employment_type": ", ".join(jtype),
            "excerpt": _excerpt(item.get("jobDescription", "") or item.get("jobExcerpt", "")),
            "posted_date": item.get("pubDate", "") or "",
        }


PLATFORMS = [
    ("Remotive", fetch_remotive),
    ("WeWorkRemotely", fetch_weworkremotely),
    ("Arbeitnow", fetch_arbeitnow),
    ("Jobicy", fetch_jobicy),
    ("Working Nomads", fetch_working_nomads),
    ("RemoteOK", fetch_remoteok),
    ("Himalayas", fetch_himalayas),
    ("Hacker News", fetch_hn_jobs),
]

# Logged-in sources via Playwright. Skipped silently if Playwright isn't
# installed so the agent still runs on a fresh checkout.
try:
    from scrapers import (
        HAVE_PLAYWRIGHT,
        fetch_arc_dev,
        fetch_linkedin,
        fetch_indeed_kr,
    )
    if HAVE_PLAYWRIGHT:
        PLATFORMS.extend([
            ("arc.dev",   fetch_arc_dev),
            ("LinkedIn",  fetch_linkedin),
            ("Indeed KR", fetch_indeed_kr),
        ])
    else:
        print("[playwright] not installed — skipping arc.dev/LinkedIn/Indeed.",
              "Run: pip install playwright && playwright install chromium",
              file=sys.stderr)
except ImportError as _e:
    print(f"[scrapers] failed to import ({_e}) — logged-in sources skipped",
          file=sys.stderr)


def matches(job):
    text = f"{job['title']} {job['tags']}".lower()
    if not any(kw in text for kw in ROLE_KEYWORDS):
        return False
    if EXCLUDE_RE.search(job["title"]):
        return False
    return True


def categorize(job):
    text = f"{job['title']} {job['tags']}".lower()
    cats = [name for name, kws in CATEGORY_RULES if any(k in text for k in kws)]
    return cats or ["Other"]


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return default
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_seen():
    raw = load_json(SEEN_FILE, {})
    if isinstance(raw, list):
        return {jid: "" for jid in raw}
    return raw


def write_jobs_js(jobs, meta):
    payload = {"meta": meta, "jobs": jobs}
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    JOBS_JS.write_text(f"window.JOB_DATA = {body};\n", encoding="utf-8")


def main():
    if "--login" in sys.argv:
        from scrapers import interactive_login
        interactive_login()
        return

    seed = "--seed" in sys.argv
    now_iso = datetime.now(timezone.utc).isoformat()

    seen = load_seen()
    current_jobs = []
    counts = {}

    for name, fetcher in PLATFORMS:
        platform_total = 0
        platform_matched = 0
        try:
            for job in fetcher():
                if not job.get("id"):
                    continue
                platform_total += 1
                if job["id"] not in seen:
                    seen[job["id"]] = now_iso
                if FILTER_JOBS and not matches(job):
                    continue
                job["first_seen"] = seen[job["id"]]
                job["categories"] = categorize(job)
                current_jobs.append(job)
                platform_matched += 1
            print(f"[{name}] {platform_total} scanned, {platform_matched} included")
            counts[name] = {"scanned": platform_total, "matched": platform_matched}
        except Exception as e:
            print(f"[{name}] error: {e}", file=sys.stderr)
            counts[name] = {"error": str(e)}

    print(f"Total matching jobs: {len(current_jobs)}")

    save_json(SEEN_FILE, seen)

    if seed:
        print("Seed mode — skipping jobs.js write.")
        return

    current_jobs.sort(key=lambda j: j.get("first_seen", ""), reverse=True)

    meta = {
        "last_updated": now_iso,
        "total_jobs": len(current_jobs),
        "sources": counts,
    }
    write_jobs_js(current_jobs, meta)
    save_json(META_FILE, meta)
    print(f"Wrote {JOBS_JS.name} with {len(current_jobs)} jobs.")


if __name__ == "__main__":
    main()
