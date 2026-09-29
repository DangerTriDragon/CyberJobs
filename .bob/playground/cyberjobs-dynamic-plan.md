# CyberJobs India — Dynamic Data Pipeline Plan

## Top-Level Overview

The goal is to transform `CyberJobs_India.html` from a static, hardcoded page into a
living job board that auto-refreshes its listings. The approach is:

1. **Decouple data from the page** — move the `jobs` array into a versioned `jobs.json`
   file served via GitHub Pages.
2. **Build a data pipeline** — a Python script (`fetch_jobs.py`) pulls individual
   postings from public RSS/JSON feeds (Remotive, Jobicy, company careers APIs) and
   normalises them into the existing job-object schema.
3. **Add newsletter ingestion** — a Mailgun/Postmark webhook receives forwarded
   newsletter emails, extracts job entries using an LLM or regex parser, and opens a
   GitHub dispatch event that triggers the same pipeline.
4. **Automate with GitHub Actions** — a daily scheduled workflow runs `fetch_jobs.py`,
   commits `data/jobs.json`, and GitHub Pages re-serves the HTML.
5. **Update the HTML** — swap inline `const jobs = [...]` for a `fetch('data/jobs.json')`
   call; keep the 19 aggregated "board link" cards as a permanent fallback category footer.

---

## Architecture

```
Newsletter email
    → Mailgun/Postmark webhook
        → GitHub repository_dispatch event
            → GitHub Action
                → fetch_jobs.py (RSS + careers feeds)
                    → data/jobs.json (committed to repo)
                        → GitHub Pages serves HTML
                            → CyberJobs_India.html fetches jobs.json at load
```

Separate from newsletter, the scheduled daily cron also triggers the same GitHub Action
independently.

---

## Sub-Tasks

---

### Sub-Task 1 — Extract jobs data into `data/jobs.json`

**Intent:** Remove the inline `jobs` array from the HTML and replace it with an external
file so the pipeline can write to it without touching the HTML.

**Expected Outcomes:**
- `data/jobs.json` exists in the repo and contains all 55 current job objects in the
  existing schema.
- `CyberJobs_India.html` fetches `data/jobs.json` at page load and passes it to
  `render()` and `catCounts()`.
- The page works identically to before (same filtering, same cards).
- The 19 aggregated "search" cards are preserved in `jobs.json` unchanged for now.

**Job object schema (unchanged):**
```json
{
  "title": "string",
  "company": "string",
  "location": "string",
  "exp": "0–2 years | 2–5 years | 5+ years | Internship",
  "cat": "SOC | VAPT | DFIR | Cloud Security | AppSec | IAM | GRC | Threat | Engineering | Architecture | Malware | Privacy",
  "skills": ["string"],
  "url": "string",
  "sourceType": "search | careers | posting",
  "intern": true
}
```

**Todo List:**
- [ ] Create `data/jobs.json` by extracting the 55-entry array from `CyberJobs_India.html`
- [ ] Remove inline `const jobs = [...]` from the HTML script block
- [ ] Wrap `render()` and `catCounts()` so they only run after fetch resolves
- [ ] Add a `fetch('data/jobs.json')` call that populates `window.jobs` then calls both functions
- [ ] Add a minimal loading state (e.g. "Loading jobs…" placeholder in `#jobs`)
- [ ] Add a fetch error state (e.g. "Could not load jobs. Refresh to try again.")
- [ ] Test that all 12 category filters, search, location, and experience dropdowns still work

**Relevant Context:**
- `render()` at line 478 of `CyberJobs_India.html` — reads `jobs` array directly; must
  switch to `window.jobs`
- `catCounts()` at line 470 — same dependency
- `resetFilters()` at line 508 — calls `render()`, no change needed
- `internCount` and `jobCount` tickers are set inside `render()` — no change needed

**Status:** [x] done

---

### Sub-Task 2 — Build the Python data-fetch script (`fetch_jobs.py`)

**Intent:** Create a standalone Python script that queries public RSS feeds and JSON
APIs to collect individual cybersecurity job postings for India, normalises them into
the `jobs.json` schema, and writes/merges the output to `data/jobs.json`.

**Expected Outcomes:**
- `fetch_jobs.py` runs with `python fetch_jobs.py` and updates `data/jobs.json`.
- Each fetched job has a stable `id` field (hash of `title+company+url`) for deduplication.
- Old jobs older than 60 days are pruned from the file on each run.
- The 19 aggregated fallback cards (those with `sourceType: "search"`) are never pruned
  (they carry a `pinned: true` flag).
- A `requirements.txt` lists only stdlib + `requests` + `feedparser`.

**Feed sources to implement (start small, expand later):**

| Feed | Type | Notes |
|------|------|-------|
| Remotive API `https://remotive.com/api/remote-jobs?category=security` | JSON | Free, no key |
| Jobicy API `https://jobicy.com/api/v2/remote-jobs?industry=security` | JSON | Free, no key |
| TCS Cybersecurity `https://www.tcs.com/careers/india/tcs-cybersecurity-hiring` | HTML | Careers page scrape |
| Wipro `https://careers.wipro.com/` | HTML | Careers page scrape |
| Accenture `https://www.accenture.com/in-en/careers` | HTML | Careers page scrape |

India-filter: keep only jobs whose `location` string contains India city keywords
(Bengaluru, Hyderabad, Pune, Mumbai, Delhi, Chennai, Kochi, India, Remote).

**Field mapping from Remotive/Jobicy to schema:**

| Source field | Schema field |
|---|---|
| `title` | `title` |
| `company_name` | `company` |
| `candidate_required_location` / `jobGeo` | `location` |
| inferred from title | `exp` |
| inferred from tags/category | `cat` |
| `tags` | `skills` |
| `url` | `url` |
| `"api"` (constant) | `sourceType` |
| derived from title keywords | `intern` |

Category inference: keyword map — e.g. title contains "SOC" → cat = "SOC", "penetration"
or "VAPT" → cat = "VAPT", etc. Fallback → "Engineering".

**Todo List:**
- [ ] Create `fetch_jobs.py` with functions: `fetch_remotive()`, `fetch_jobicy()`,
  `load_existing()`, `merge()`, `prune_old()`, `save()`
- [ ] Add India location filter
- [ ] Add category inference keyword map
- [ ] Add experience inference from title keywords (senior/lead → "5+ years", junior/fresher → "0–2 years")
- [ ] Add `id` field (SHA-256 first 12 chars of `title+company+url`)
- [ ] Add `fetchedAt` ISO timestamp field per job
- [ ] Mark pinned aggregated cards with `pinned: true` in `data/jobs.json` (do this in Sub-Task 1 prep)
- [ ] Prune jobs where `fetchedAt` is older than 60 days and `pinned` is not true
- [ ] Write `requirements.txt`
- [ ] Test locally: `python fetch_jobs.py` should add new jobs without removing pinned fallbacks

**Relevant Context:**
- Remotive API returns `{jobs: [{id, title, url, company_name, tags, ...}]}`
- Jobicy API returns `{jobs: [{id, jobTitle, url, companyName, jobGeo, jobIndustry, jobType}]}`
- Pinned fallback cards live in `data/jobs.json` with `pinned: true`

**Status:** [x] done

---

### Sub-Task 3 — Newsletter email webhook ingestion

**Intent:** Allow job data to enter the pipeline via forwarded newsletter emails. A
Mailgun/Postmark inbound webhook receives the email, a small Python cloud function
(or GitHub Actions webhook handler) parses job listings out of the email body, and
triggers the main GitHub Action to refresh `jobs.json`.

**Expected Outcomes:**
- Forwarding a cybersecurity newsletter email to a designated inbox triggers a GitHub
  `repository_dispatch` event of type `newsletter_ingest`.
- The GitHub Action on `newsletter_ingest` runs `parse_newsletter.py <email_body>` which
  extracts job objects and appends them to `data/jobs.json`.
- No cloud function infrastructure needed beyond a Mailgun/Postmark route rule (both
  have free tiers with inbound routing).

**Architecture:**
```
Newsletter email → Mailgun inbound route → GitHub Actions webhook endpoint
    → workflow trigger: repository_dispatch{event_type: "newsletter_ingest", payload: {body}}
        → parse_newsletter.py writes to data/jobs.json → commit
```

**Mailgun/Postmark config:**
- Create a receiving route that HTTP POSTs to a GitHub Actions `workflow_dispatch`
  endpoint (authenticated with a PAT stored as a Mailgun/Postmark route variable).
- Alternative: use a single Cloudflare Worker (free tier) as the relay between
  Mailgun and GitHub.

**`parse_newsletter.py` logic:**
- Input: raw email body (HTML or plain text)
- Strategy: regex patterns matching common newsletter job-listing formats:
  - Lines containing `[Company] — [Role] — [Location]`
  - Markdown-style job blocks
  - HTML anchor tags with job title text
- Fallback: output unparsed lines to a `data/newsletter_queue.json` for manual review
- Output: appends new job objects (with `sourceType: "newsletter"`) to `data/jobs.json`

**Todo List:**
- [ ] Create `parse_newsletter.py` with regex-based job extraction
- [ ] Add `sourceType: "newsletter"` as a new valid value in the HTML render function
  (display label: "newsletter")
- [ ] Document the Mailgun inbound route setup in `README.md`
- [ ] Add `GITHUB_PAT` and `MAILGUN_WEBHOOK_KEY` to the repo secrets documentation
- [ ] Create `.github/workflows/newsletter-ingest.yml` — triggered by `repository_dispatch`
  with event type `newsletter_ingest`; runs `parse_newsletter.py`; commits changes
- [ ] Test with a sample newsletter HTML file

**Relevant Context:**
- `render()` in HTML at line 496 reads `sourceType` — needs "newsletter" → "newsletter"
  label added to the ternary
- `data/newsletter_queue.json` is a fallback file for lines that couldn't be auto-parsed

**Status:** [x] done

---

### Sub-Task 4 — GitHub Actions scheduled pipeline

**Intent:** Wire everything into a fully automated daily refresh via GitHub Actions +
GitHub Pages so zero manual steps are needed for the RSS/API feed path.

**Expected Outcomes:**
- `.github/workflows/refresh-jobs.yml` runs daily at 06:00 UTC.
- The workflow installs Python deps, runs `fetch_jobs.py`, commits `data/jobs.json` if
  it changed, and GitHub Pages re-deploys the site automatically.
- A separate workflow `.github/workflows/newsletter-ingest.yml` is triggered by
  `repository_dispatch` for the email path.
- The repo has a `README.md` explaining the full setup (GitHub Pages config, Mailgun
  route, secrets needed).

**Workflow: `refresh-jobs.yml`**
```
trigger: schedule (cron "0 6 * * *") + workflow_dispatch (manual)
steps:
  1. checkout repo
  2. setup python 3.11
  3. pip install -r requirements.txt
  4. python fetch_jobs.py
  5. git diff --quiet data/jobs.json || git commit -am "chore: refresh jobs [skip ci]"
  6. git push
```

**Workflow: `newsletter-ingest.yml`**
```
trigger: repository_dispatch (event_type: newsletter_ingest)
steps:
  1. checkout repo
  2. setup python 3.11
  3. pip install -r requirements.txt
  4. python parse_newsletter.py "${{ github.event.client_payload.body }}"
  5. git commit / push if jobs.json changed
```

**Todo List:**
- [ ] Create `.github/workflows/refresh-jobs.yml`
- [ ] Create `.github/workflows/newsletter-ingest.yml`
- [ ] Add `GITHUB_TOKEN` write permissions block to both workflows
- [ ] Add `[skip ci]` to commit message to prevent infinite loop
- [ ] Configure `gh-pages` branch or `docs/` folder as GitHub Pages source in repo settings
  (document in README)
- [ ] Write `README.md` covering: repo structure, GitHub Pages setup, secrets list
  (PAT, Mailgun signing key), manual run instructions, how to add new RSS sources

**Relevant Context:**
- GitHub Actions `GITHUB_TOKEN` has write access to the repo by default when
  `permissions: contents: write` is declared
- `[skip ci]` in commit message prevents the push from re-triggering the workflow

**Status:** [x] done

---

### Sub-Task 5 — Promote aggregated cards to category-footer fallbacks in the HTML

**Intent:** The 19 "Various — board" cards currently appear inline in the job grid.
They should be moved to a dedicated per-category fallback section that appears below
the individual-posting cards for each active category filter, not mixed into the main grid.

**Expected Outcomes:**
- Individual job cards (sourceType != "search") appear in the main `#jobs` grid.
- Aggregated "search" cards render as a compact link strip (`boardlinks`-style) below
  the grid, labelled "Browse all [category] openings →".
- The strip only shows categories that are currently visible (i.e. match the active
  filters).
- No data is deleted — aggregated cards remain in `jobs.json` with `sourceType: "search"`
  and `pinned: true`.

**Todo List:**
- [ ] Split `render()` into two passes: one for real postings (`sourceType !== "search"`),
  one for aggregated fallbacks (`sourceType === "search"`)
- [ ] Render real postings into `#jobs` grid as today
- [ ] Render aggregated fallbacks into a new `#fallback-boards` div below `#jobs`
  as styled link buttons (reuse `.boardlinks a` CSS)
- [ ] Show `#fallback-boards` only when there are matching aggregated cards for the
  current filter state
- [ ] Update the ticker `jobCount` to count only non-aggregated postings
- [ ] Add a secondary count label "N live board links" for the aggregated strip

**Relevant Context:**
- `render()` at line 478 — currently renders all jobs (both types) into one grid
- `.boardlinks` CSS already exists (line 82–84) and can be reused for the fallback strip
- `#catmore` div (line 165) is a category-specific link strip that already exists —
  the fallback strip is similar but driven by the filtered aggregated cards

**Status:** [x] done

---

## Repository Structure After All Sub-Tasks

```
/
├── CyberJobs_India.html       # front-end, fetches data/jobs.json
├── data/
│   ├── jobs.json              # all job postings (auto-updated)
│   └── newsletter_queue.json  # unparsed newsletter lines (manual review)
├── fetch_jobs.py              # RSS/API poller
├── parse_newsletter.py        # newsletter email parser
├── requirements.txt           # feedparser, requests
├── README.md                  # setup guide
└── .github/
    └── workflows/
        ├── refresh-jobs.yml       # daily cron
        └── newsletter-ingest.yml  # email webhook trigger
```

---

## Decisions Made

| Decision | Choice |
|---|---|
| Hosting | GitHub Pages (no server) |
| Automation | GitHub Actions (cron + repository_dispatch) |
| Email ingestion | Mailgun/Postmark inbound → GitHub repository_dispatch |
| Aggregated cards | Kept permanently as pinned fallback strip, not deleted |
| Data dedup | SHA-256 id field on title+company+url |
| Stale pruning | 60-day TTL, pinned cards exempt |
| New sourceType | "newsletter" added for email-ingested jobs |

---

## Open Questions / Post-MVP Ideas

- Add LLM-based parsing for newsletter ingestion (better accuracy than regex) — can
  use OpenAI API key stored as GitHub secret.
- Add `salary` field to schema once feeds provide it.
- Add a "last refreshed" timestamp display in the page header (read from a
  `data/meta.json` file written by `fetch_jobs.py`).
- Add a GitHub Pages custom domain.
