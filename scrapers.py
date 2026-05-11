"""
Playwright-based scrapers for logged-in job sources (arc.dev / LinkedIn / Indeed KR).

These three platforms can't be polled with plain `requests` — Cloudflare blocks
Indeed, LinkedIn is JS-rendered, arc.dev needs your session. We launch a real
headless Chromium that reuses a persistent profile stored in `browser_profile/`,
*separate* from the user's normal Chrome/Edge so the agent never fights the user
for the same cookie jar.

One-time setup (run once, then every hourly task uses the saved cookies):

    pip install playwright
    playwright install chromium
    python agent.py --login          # opens browser; log in to each tab; press Enter

CAVEATS
- Selectors below are best-effort. When a site redesigns, the corresponding
  fetcher will return zero jobs — check the per-source `scanned` count in the
  agent's console output and update the selectors here.
- LinkedIn/Indeed actively discourage scraping. This is personal use only; one
  search page per run, hourly cadence, modest volume.
- If sites start serving captchas, switch HEADLESS to False (cookies + a visible
  browser usually bypasses bot detection) or skip that source until you can
  re-login via `--login`.
"""

import atexit
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PROFILE_DIR = ROOT / "browser_profile"

# Search URLs — edit these to change what gets polled.
LINKEDIN_SEARCH_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords=software%20engineer"
    "&f_E=2%2C3"       # experience: entry-level + associate
    "&f_WT=2"          # remote
    "&f_TPR=r86400"    # posted in last 24h
    "&sortBy=DD"       # sort by date desc
)
INDEED_KR_SEARCH_URL = "https://kr.indeed.com/jobs?q=software+developer&sort=date&fromage=3"
ARC_DEV_URL = "https://arc.dev/dashboard/d/full-time-jobs/browse"

LOGIN_TARGETS = [
    ("LinkedIn",  "https://www.linkedin.com/login"),
    ("Indeed KR", "https://kr.indeed.com/account/login"),
    ("arc.dev",   "https://arc.dev/login"),
]

HEADLESS = True
PAGE_TIMEOUT_MS = 30_000
MAX_PER_SOURCE = 30
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Cloud runs (GitHub Actions) set SKIP_PLAYWRIGHT=1 because they can't carry the
# logged-in browser_profile/ — cookies stay on the user's local machine. Honoring
# the env var skips both the playwright import and any attempt to launch Chromium,
# so CI runs don't waste minutes downloading a browser that would never authenticate.
if os.getenv("SKIP_PLAYWRIGHT") == "1":
    HAVE_PLAYWRIGHT = False
else:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        HAVE_PLAYWRIGHT = True
    except ImportError:
        HAVE_PLAYWRIGHT = False


_state = {"pw": None, "ctx": None}


def _get_context(headless=HEADLESS):
    if _state["ctx"] is None:
        from playwright.sync_api import sync_playwright
        PROFILE_DIR.mkdir(exist_ok=True)
        pw = sync_playwright().start()
        _state["pw"] = pw
        _state["ctx"] = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1440, "height": 900},
            user_agent=UA,
        )
        atexit.register(_close)
    return _state["ctx"]


def _close():
    try:
        if _state["ctx"]:
            _state["ctx"].close()
        if _state["pw"]:
            _state["pw"].stop()
    except Exception:
        pass
    _state["ctx"] = None
    _state["pw"] = None


def _new_page():
    page = _get_context().new_page()
    page.set_default_timeout(PAGE_TIMEOUT_MS)
    return page


def fetch_arc_dev():
    """arc.dev full-time jobs dashboard. Selectors are heuristic — arc is an
    SPA with hashed class names, so we look for anchors that point at job /
    company detail pages and grab the nearest readable text block as title."""
    page = _new_page()
    try:
        page.goto(ARC_DEV_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        # let lazy-loaded cards render
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 1200)")
            page.wait_for_timeout(600)

        cards = page.evaluate("""
            () => {
              const out = [];
              const seen = new Set();
              const anchors = document.querySelectorAll(
                'a[href*="/job/"], a[href*="/jobs/"], a[href*="/companies/"]'
              );
              for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                if (!href || seen.has(href)) continue;
                if (href.startsWith('#') || href === '/jobs/' || href === '/job/') continue;
                seen.add(href);
                let el = a;
                for (let i = 0; i < 6 && el && el.parentElement; i++) {
                  const r = el.getBoundingClientRect();
                  if (r && r.height > 80 && r.width > 200) break;
                  el = el.parentElement;
                }
                if (!el) el = a;
                const lines = (el.innerText || '').split('\\n')
                  .map(s => s.trim()).filter(Boolean);
                if (!lines.length) continue;
                out.push({
                  url: href.startsWith('http') ? href : 'https://arc.dev' + href,
                  lines: lines.slice(0, 8),
                });
              }
              return out;
            }
        """) or []

        seen_urls = set()
        count = 0
        for c in cards:
            if count >= MAX_PER_SOURCE:
                break
            url = c.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            lines = c.get("lines") or []
            title = lines[0] if lines else ""
            company = lines[1] if len(lines) > 1 else ""
            location = lines[2] if len(lines) > 2 else "Remote"
            if not title or len(title) < 4:
                continue
            yield {
                "id": f"arcdev:{url}",
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "tags": " ".join(lines[3:6]),
                "source": "arc.dev",
            }
            count += 1
    finally:
        try:
            page.close()
        except Exception:
            pass


def fetch_linkedin():
    """LinkedIn jobs search (logged-in view). Selectors target both the
    classic `.job-card-container` markup and the newer occludable-list one."""
    page = _new_page()
    try:
        page.goto(LINKEDIN_SEARCH_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(
                '[data-occludable-job-id], .job-card-container, '
                '.jobs-search-results__list li, .base-card',
                timeout=15_000,
            )
        except Exception:
            pass
        for _ in range(4):
            page.evaluate("window.scrollBy(0, 1200)")
            page.wait_for_timeout(700)

        results = page.evaluate("""
            () => {
              const cards = document.querySelectorAll(
                '[data-occludable-job-id], .job-card-container, '
                'li.jobs-search-results__list-item, .base-card'
              );
              const out = [];
              for (const card of cards) {
                const link = card.querySelector('a[href*="/jobs/view/"]')
                          || card.querySelector('a.base-card__full-link')
                          || card.querySelector('a[href*="/jobs/"]');
                if (!link) continue;
                const href = link.href || '';
                const titleEl = card.querySelector(
                  '.job-card-list__title, .base-search-card__title, '
                  '[class*="job-card-list__title"], h3'
                );
                const companyEl = card.querySelector(
                  '.job-card-container__company-name, '
                  '.base-search-card__subtitle, [class*="company-name"], h4'
                );
                const locEl = card.querySelector(
                  '.job-card-container__metadata-item, '
                  '.job-search-card__location, [class*="metadata-item"]'
                );
                const id = card.getAttribute('data-occludable-job-id')
                  || card.getAttribute('data-job-id')
                  || (href.match(/\\/jobs\\/view\\/(\\d+)/) || [])[1]
                  || href;
                out.push({
                  id,
                  url: href,
                  title: titleEl ? titleEl.innerText.trim() : '',
                  company: companyEl ? companyEl.innerText.trim() : '',
                  location: locEl ? locEl.innerText.trim() : 'Remote',
                });
              }
              return out;
            }
        """) or []

        seen = set()
        count = 0
        for r in results:
            if count >= MAX_PER_SOURCE:
                break
            jid = (r.get("id") or "").strip() or r.get("url", "")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            title = (r.get("title") or "").strip()
            if not title:
                continue
            yield {
                "id": f"linkedin:{jid}",
                "title": title,
                "company": (r.get("company") or "").strip(),
                "location": (r.get("location") or "Remote").strip() or "Remote",
                "url": r.get("url", ""),
                "tags": "",
                "source": "LinkedIn",
            }
            count += 1
    finally:
        try:
            page.close()
        except Exception:
            pass


def fetch_indeed_kr():
    """Indeed Korea (kr.indeed.com). Cloudflare-protected — the persistent
    profile + real Chromium UA is what gets us through. Selectors cover both
    the slider_item and job_seen_beacon card flavours Indeed uses."""
    page = _new_page()
    try:
        page.goto(INDEED_KR_SEARCH_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(
                '[data-testid="slider_item"], .job_seen_beacon, '
                'div.cardOutline, .resultContent',
                timeout=15_000,
            )
        except Exception:
            pass

        results = page.evaluate("""
            () => {
              const cards = document.querySelectorAll(
                '[data-testid="slider_item"], .job_seen_beacon, div.cardOutline'
              );
              const out = [];
              for (const card of cards) {
                const link = card.querySelector(
                  'h2.jobTitle a, a[id^="job_"], '
                  'a[href*="/rc/clk"], a[href*="/viewjob"]'
                );
                if (!link) continue;
                const href = link.href || '';
                const titleEl = card.querySelector(
                  'h2.jobTitle span[title], h2.jobTitle a span, '
                  'h2.jobTitle, [class*="jobTitle"] span'
                );
                const companyEl = card.querySelector(
                  '[data-testid="company-name"], span.companyName, .companyName'
                );
                const locEl = card.querySelector(
                  '[data-testid="text-location"], .companyLocation, div.companyLocation'
                );
                out.push({
                  url: href,
                  title: titleEl ? titleEl.innerText.trim() : '',
                  company: companyEl ? companyEl.innerText.trim() : '',
                  location: locEl ? locEl.innerText.trim() : 'Remote',
                });
              }
              return out;
            }
        """) or []

        seen = set()
        count = 0
        for r in results:
            if count >= MAX_PER_SOURCE:
                break
            url = r.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            title = (r.get("title") or "").strip()
            if not title:
                continue
            yield {
                "id": f"indeedkr:{url}",
                "title": title,
                "company": (r.get("company") or "").strip(),
                "location": (r.get("location") or "Remote").strip() or "Remote",
                "url": url,
                "tags": "",
                "source": "Indeed KR",
            }
            count += 1
    finally:
        try:
            page.close()
        except Exception:
            pass


def interactive_login():
    """Open a visible Chromium with the persistent profile, navigate to each
    site's login page, and wait for the user to finish logging in. Run once;
    cookies persist in browser_profile/ for subsequent headless scrapes."""
    if not HAVE_PLAYWRIGHT:
        print("Playwright is not installed. Run:\n"
              "  pip install playwright\n"
              "  playwright install chromium", file=sys.stderr)
        sys.exit(1)

    from playwright.sync_api import sync_playwright
    PROFILE_DIR.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1366, "height": 900},
            user_agent=UA,
        )
        for label, url in LOGIN_TARGETS:
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                print(f"  [{label}] opened: {url}")
            except Exception as e:
                print(f"  [{label}] failed to open ({e}); URL: {url}", file=sys.stderr)
        print()
        print("Log in to each tab as needed. Cookies are saved automatically.")
        try:
            input("Press Enter once you're done logging in to all sites... ")
        except EOFError:
            pass
        ctx.close()
    print(f"Profile saved to: {PROFILE_DIR}")
    print("You can now run `python agent.py` normally; scraping will use these cookies.")
