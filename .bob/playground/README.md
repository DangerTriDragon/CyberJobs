# CyberJobs India

A self-updating cybersecurity job board for India, powered by GitHub Pages + GitHub Actions.

---

## Repository Structure

```
/
├── CyberJobs_India.html          # Front-end; fetches data/jobs.json at load
├── data/
│   ├── jobs.json                 # All job postings (auto-updated by pipeline)
│   └── newsletter_queue.json     # Unparsed newsletter lines (manual review)
├── fetch_jobs.py                 # RSS/API poller (Remotive, Jobicy)
├── parse_newsletter.py           # Newsletter email body parser
├── requirements.txt              # feedparser, requests
├── README.md                     # This file
└── .github/
    └── workflows/
        ├── refresh-jobs.yml      # Daily cron (Sub-Task 4)
        └── newsletter-ingest.yml # Triggered by repository_dispatch
```

---

## GitHub Pages Setup

1. Push the repository to GitHub.
2. Go to **Settings → Pages**.
3. Under *Source*, select **Deploy from a branch** → branch `master` (or `main`) → folder `/` (root).
4. Save. GitHub Pages will publish `CyberJobs_India.html` at `https://<user>.github.io/<repo>/CyberJobs_India.html`.

The page loads `data/jobs.json` relative to itself, so no path changes are needed.

---


## GitHub Actions Workflows

Two workflows automate the data pipeline. No extra secrets are required for the
refresh workflow — the auto-provided `GITHUB_TOKEN` is sufficient.

### Workflows at a glance

| Workflow file | Trigger | Purpose |
|---|---|---|
| `.github/workflows/refresh-jobs.yml` | Daily cron (06:00 UTC) **+** manual `workflow_dispatch` | Runs `fetch_jobs.py`, writes `data/jobs.json` + `data/meta.json`, commits & pushes if changed |
| `.github/workflows/newsletter-ingest.yml` | `repository_dispatch` (event type `newsletter_ingest`) | Runs `parse_newsletter.py` on a forwarded newsletter email body, commits result |

### Permissions

Both workflows declare:

```yaml
permissions:
  contents: write
```

This grants the auto-provided `GITHUB_TOKEN` write access to the repository so the
bot can commit and push without any additional PAT. No extra secrets are needed for
the refresh workflow.

### Manual trigger — refresh-jobs workflow

```bash
# Requires GitHub CLI (gh) installed and authenticated
gh workflow run refresh-jobs.yml
```

Or use the GitHub web UI: **Actions → Refresh Jobs → Run workflow**.

### `[skip ci]` in commit messages

Both workflows append `[skip ci]` to their automated commit messages:

```
chore: refresh jobs [skip ci]
chore: ingest newsletter jobs [skip ci]
```

This tells GitHub Actions **not** to re-trigger any workflow on that push, preventing
an infinite loop where a bot commit would kick off another run of the same workflow.

---


## Required Secrets

Add these under **Settings → Secrets and variables → Actions**:

| Secret name            | Value                                                                                     |
|------------------------|-------------------------------------------------------------------------------------------|
| `GITHUB_TOKEN`         | Auto-provided by Actions — no setup needed (used for `git push` in workflows)            |
| `GITHUB_PAT`           | A classic PAT (or fine-grained PAT with *Contents: write*) — needed if you call the dispatch webhook from outside GitHub (e.g. Mailgun, Cloudflare Worker) |
| `MAILGUN_SIGNING_KEY`  | Your Mailgun webhook signing key — used to verify that the inbound POST is genuinely from Mailgun |

### Creating a `GITHUB_PAT`

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**.
2. Click **Generate new token (classic)**.
3. Select scope: **repo** (full control of private repositories) — or use a fine-grained token with *Contents: Read and Write* on this repo.
4. Copy the token and add it as a repository secret named `GITHUB_PAT`.

---

## Newsletter Ingestion — Mailgun Inbound Route Setup

### Overview

```
Newsletter email
  → Your Mailgun receiving address (e.g. jobs@mg.yourdomain.com)
    → Mailgun inbound route (HTTP forward)
      → Cloudflare Worker (or any relay)
        → GitHub repository_dispatch API  (event_type: newsletter_ingest)
          → .github/workflows/newsletter-ingest.yml
            → parse_newsletter.py → data/jobs.json committed
```

### Step 1 — Configure a Mailgun receiving domain

1. In the Mailgun dashboard go to **Receiving → Add Receiving Domain**.
2. Add DNS MX records as instructed by Mailgun for your domain.

### Step 2 — Create an inbound route

1. Go to **Receiving → Create Route**.
2. Expression type: **Match Recipient** → `jobs@mg.yourdomain.com` (or use **Catch-All**).
3. Action: **Forward** → set the URL to your relay endpoint (see Step 3).
4. Optionally enable **Store and notify** for debugging.

### Step 3 — Relay endpoint

Mailgun cannot POST directly to the GitHub `repository_dispatch` API because it sends
`multipart/form-data` rather than JSON. Use one of:

**Option A — Cloudflare Worker (recommended, free tier)**

Deploy a small Worker that:
1. Verifies the `X-Mailgun-Signature-V2` header using `MAILGUN_SIGNING_KEY`.
2. Extracts the `body-plain` or `body-html` field from the form data.
3. Base64-encodes the body.
4. POSTs to:

```
POST https://api.github.com/repos/<owner>/<repo>/dispatches
Authorization: token <GITHUB_PAT>
Content-Type: application/json

{
  "event_type": "newsletter_ingest",
  "client_payload": {
    "body": "<base64-encoded email body>"
  }
}
```

**Option B — Postmark inbound webhook**

Postmark sends JSON directly; the `TextBody` / `HtmlBody` fields can be forwarded
to the GitHub dispatch endpoint with no intermediary Worker needed.

### Step 4 — Verify the Mailgun signing key

Retrieve your key from **Mailgun → Settings → Webhooks → HTTP webhook signing key**.
Store it as the `MAILGUN_SIGNING_KEY` repository secret (used in your relay Worker).

---

## Manual Trigger — newsletter-ingest workflow

### Using the GitHub CLI

```bash
# Plain-text body
gh workflow run newsletter-ingest.yml \
  -f body="SOC Analyst at Wipro — Bengaluru"
```

> **Note:** `gh workflow run` triggers `workflow_dispatch`, not `repository_dispatch`.
> The newsletter workflow uses `repository_dispatch`, so use the `curl` method below
> for a true end-to-end test.

### Using curl (repository_dispatch)

```bash
OWNER="your-github-username"
REPO="your-repo-name"
PAT="ghp_xxxxxxxxxxxxxxxxxxxx"

# Base64-encode the email body
BODY_B64=$(echo "SOC Analyst at Wipro — Bengaluru" | base64 -w 0)

curl -s -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: token $PAT" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/$OWNER/$REPO/dispatches" \
  -d "{\"event_type\":\"newsletter_ingest\",\"client_payload\":{\"body\":\"$BODY_B64\"}}"
```

A `204 No Content` response means the event was accepted. Check the **Actions** tab
to see the workflow run.

---

## Local Testing

### Parse a newsletter file directly

```bash
# Plain-text email body from a file
python parse_newsletter.py path/to/newsletter.txt

# Pipe from stdin
echo "SOC Analyst at Wipro — Bengaluru" | python parse_newsletter.py
```

### Run the RSS/API poller

```bash
pip install -r requirements.txt
python fetch_jobs.py
```

---

## Adding New RSS / API Sources

1. Open `fetch_jobs.py`.
2. Add a new `fetch_<source>()` function following the pattern of `fetch_remotive()`.
3. Call it in `main()` and add its output to the `incoming` list.
4. The `merge()` and `prune_old()` functions handle deduplication and TTL automatically.

---

## Data Schema

```jsonc
{
  "id":         "abc123def456",         // SHA-256[:12] of title+company+url
  "title":      "SOC Analyst",
  "company":    "Wipro",
  "location":   "Bengaluru, India",
  "exp":        "2–5 years",            // Internship | 0–2 years | 2–5 years | 5+ years
  "cat":        "SOC",                  // see CAT_MAP in fetch_jobs.py
  "skills":     ["SIEM", "Splunk"],
  "url":        "https://...",
  "sourceType": "api",                  // search | careers | api | newsletter | posting
  "intern":     false,
  "fetchedAt":  "2025-01-01T06:00:00+00:00",
  "pinned":     true                    // optional — exempt from 60-day pruning
}
```
