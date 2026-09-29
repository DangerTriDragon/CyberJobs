#!/usr/bin/env python3
"""
parse_newsletter.py — CyberJobs India newsletter email parser
Accepts a raw email body (HTML or plain text) via:
  - A filename as the first CLI argument, OR
  - stdin if no argument is given

Extracts job listings using 3 patterns (markdown/structured, HTML anchors,
loose keyword lines), appends matched jobs to data/jobs.json with
sourceType="newsletter", and saves unmatched lines to data/newsletter_queue.json.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Shared constants (mirrors fetch_jobs.py — kept in sync manually)
# ---------------------------------------------------------------------------

DATA_DIR        = os.path.join(os.path.dirname(__file__), "data")
JOBS_FILE       = os.path.join(DATA_DIR, "jobs.json")
QUEUE_FILE      = os.path.join(DATA_DIR, "newsletter_queue.json")

CAT_MAP = [
    ("SOC",            ["soc analyst", "security operations", "siem", "soc engineer"]),
    ("VAPT",           ["penetration", "pentest", "vapt", "red team", "offensive security", "bug bounty"]),
    ("DFIR",           ["incident response", "dfir", "forensic", "digital forensic"]),
    ("Cloud Security", ["cloud security", "aws security", "azure security", "gcp security", "cspm", "cnapp"]),
    ("AppSec",         ["appsec", "application security", "sast", "dast", "devsecops", "secure code"]),
    ("IAM",            ["identity", "iam", "access management", "sailpoint", "cyberark", "okta", "pam"]),
    ("GRC",            ["grc", "governance", "risk", "compliance", "iso 27001", "audit"]),
    ("Threat",         ["threat intel", "threat hunting", "threat intelligence", "mitre", "cti"]),
    ("Engineering",    ["security engineer", "security engineering", "detection engineer", "soar"]),
    ("Architecture",   ["security architect", "architecture", "zero trust", "sase"]),
    ("Malware",        ["malware", "reverse engineer", "reverse engineering", "ida pro", "assembly"]),
    ("Privacy",        ["privacy", "gdpr", "dpdp", "data protection", "onetrust"]),
]

# Flat keyword set used by Pattern 3 loose matching
_ALL_CAT_KEYWORDS = {kw for _, kws in CAT_MAP for kw in kws}

EXP_MAP = [
    ("Internship", ["intern", "trainee", "student"]),
    ("0–2 years",  ["junior", "associate", "fresher", "entry", "graduate", "analyst i", "level 1"]),
    ("5+ years",   ["senior", "lead", "principal", "manager", "director", "head of", "architect", "staff"]),
]
EXP_DEFAULT = "2–5 years"

HIRING_KEYWORDS = {"hiring", "opening", "role", "position", "vacancy", "job"}

# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------

def infer_cat(text: str) -> str:
    h = text.lower()
    for cat, keywords in CAT_MAP:
        if any(kw in h for kw in keywords):
            return cat
    return "Engineering"


def infer_exp(text: str) -> str:
    t = text.lower()
    for exp, keywords in EXP_MAP:
        if any(kw in t for kw in keywords):
            return exp
    return EXP_DEFAULT


def make_id(title: str, company: str, url: str) -> str:
    raw = (title + company + url).lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Strips HTML tags; preserves text content and href attributes."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.anchors = []   # list of (text, href) tuples
        self._cur_href = None
        self._cur_text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attr_dict = dict(attrs)
            self._cur_href = attr_dict.get("href", "")
            self._cur_text_parts = []

    def handle_endtag(self, tag):
        if tag == "a" and self._cur_href is not None:
            text = "".join(self._cur_text_parts).strip()
            if text:
                self.anchors.append((text, self._cur_href))
            self._cur_href = None
            self._cur_text_parts = []

    def handle_data(self, data):
        self.parts.append(data)
        if self._cur_href is not None:
            self._cur_text_parts.append(data)

    def get_text(self) -> str:
        return "\n".join(
            line.strip()
            for line in "".join(self.parts).splitlines()
            if line.strip()
        )


def strip_html(body: str):
    """
    Return (plain_text, anchors) where anchors is a list of (text, href).
    If body doesn't look like HTML, returns (body, []).
    """
    if not re.search(r"<[a-zA-Z]", body):
        return body, []
    extractor = _TextExtractor()
    try:
        extractor.feed(body)
    except Exception:
        pass
    return extractor.get_text(), extractor.anchors


# ---------------------------------------------------------------------------
# Pattern matchers
# ---------------------------------------------------------------------------

# Pattern 1 — structured/markdown separators
_P1_DASH  = re.compile(
    r"^(?P<A>[^—|\n]+?)\s*[—–-]{1,3}\s*(?P<B>[^—|\n]+?)\s*[—–-]{1,3}\s*(?P<C>[^—|\n]+?)\s*$"
)
_P1_PIPE  = re.compile(
    r"^(?P<A>[^|\n]+?)\s*\|\s*(?P<B>[^|\n]+?)\s*\|\s*(?P<C>[^|\n]+?)\s*$"
)
# "Role at Company (Location)"  or  "Role @ Company — Location"
_P1_AT    = re.compile(
    r"^(?P<role>[^@\n]+?)\s+(?:at|@)\s+(?P<company>[^(\-—\n]+?)"
    r"(?:\s*[\(\-—]\s*(?P<location>[^)\n]+?)\)?)?\s*$",
    re.IGNORECASE,
)


def _match_p1(line: str):
    """
    Try Pattern 1. Returns a partial job dict or None.
    Heuristic: at least one token must look job-related.
    """
    # dash / em-dash separator  →  Company — Role — Location
    m = _P1_DASH.match(line)
    if m:
        a, b, c = m.group("A").strip(), m.group("B").strip(), m.group("C").strip()
        # Determine which segment is the role (longest, or contains exp keywords)
        title    = b          # middle segment usually = role
        company  = a
        location = c
        return {"title": title, "company": company, "location": location, "url": ""}

    # pipe separator  →  Company | Role | Location
    m = _P1_PIPE.match(line)
    if m:
        a, b, c = m.group("A").strip(), m.group("B").strip(), m.group("C").strip()
        return {"title": b, "company": a, "location": c, "url": ""}

    # "Role at/@ Company (Location)"
    m = _P1_AT.match(line)
    if m:
        role     = m.group("role").strip()
        company  = m.group("company").strip()
        location = (m.group("location") or "India").strip()
        # Sanity: role shouldn't be a URL or purely numeric
        if not role or re.match(r"https?://", role):
            return None
        return {"title": role, "company": company, "location": location, "url": ""}

    return None


def _match_p2(text: str, href: str):
    """
    Pattern 2 — HTML anchor text.
    Tries to split anchor text into role/company.
    """
    # "Role Title at Company"
    m = re.match(r"^(?P<role>.+?)\s+at\s+(?P<company>.+)$", text, re.IGNORECASE)
    if m:
        return {
            "title":    m.group("role").strip(),
            "company":  m.group("company").strip(),
            "location": "India",
            "url":      href,
        }
    # Fallback: treat whole text as title
    return {"title": text, "company": "Unknown", "location": "India", "url": href}


def _match_p3(line: str):
    """
    Pattern 3 — loose keyword match.
    Line must contain ≥2 hiring-signal words AND ≥1 CAT keyword.
    """
    lower = line.lower()
    hiring_hits = sum(1 for kw in HIRING_KEYWORDS if kw in lower)
    cat_hit     = any(kw in lower for kw in _ALL_CAT_KEYWORDS)
    if hiring_hits >= 2 and cat_hit:
        return {"title": line.strip(), "company": "Unknown", "location": "India", "url": ""}
    return None


# ---------------------------------------------------------------------------
# Build a full job object from a partial dict
# ---------------------------------------------------------------------------

def _build_job(partial: dict) -> dict:
    title    = partial.get("title", "").strip() or "Unknown Role"
    company  = partial.get("company", "").strip() or "Unknown"
    location = partial.get("location", "").strip() or "India"
    url      = partial.get("url", "").strip()
    now_iso  = datetime.now(timezone.utc).isoformat()

    return {
        "id":         make_id(title, company, url),
        "title":      title,
        "company":    company,
        "location":   location,
        "exp":        infer_exp(title),
        "cat":        infer_cat(title),
        "skills":     [],
        "url":        url,
        "sourceType": "newsletter",
        "intern":     any(kw in title.lower() for kw in ["intern", "trainee", "student"]),
        "fetchedAt":  now_iso,
    }


# ---------------------------------------------------------------------------
# Load / merge / save helpers
# ---------------------------------------------------------------------------

def _load_json_list(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _merge_into_jobs(existing: list, incoming: list) -> tuple:
    """Deduplicate by id; never overwrite existing entries."""
    seen = {j["id"]: j for j in existing if j.get("id")}
    new_count = 0
    for job in incoming:
        jid = job["id"]
        if jid not in seen:
            seen[jid] = job
            new_count += 1
    return list(seen.values()), new_count


# ---------------------------------------------------------------------------
# Main parse logic
# ---------------------------------------------------------------------------

def parse(body: str) -> tuple:
    """
    Parse email body. Returns (jobs: list, queued: list).
    jobs   — fully formed job dicts ready to merge
    queued — raw lines that matched no pattern
    """
    plain_text, anchors = strip_html(body)

    jobs   = []
    queued = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # --- Pattern 2: HTML anchors (before splitting into lines) ---------------
    for text, href in anchors:
        text = text.strip()
        if not text or len(text) < 5:
            continue
        partial = _match_p2(text, href)
        if partial:
            jobs.append(_build_job(partial))

    # --- Patterns 1 & 3: line-by-line ----------------------------------------
    anchor_texts = {t.strip() for t, _ in anchors}

    for raw_line in plain_text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 5:
            continue
        # Skip lines already captured as anchor text (avoid duplicates)
        if line in anchor_texts:
            continue

        partial = _match_p1(line) or _match_p3(line)
        if partial:
            jobs.append(_build_job(partial))
        else:
            queued.append({"raw": line, "receivedAt": now_iso})

    return jobs, queued


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Read input: file arg or stdin
    if len(sys.argv) > 1:
        path = sys.argv[1]
        try:
            with open(path, "r", encoding="utf-8") as fh:
                body = fh.read()
        except OSError as exc:
            sys.exit(f"ERROR: Cannot read '{path}': {exc}")
    else:
        body = sys.stdin.read()

    if not body.strip():
        sys.exit("ERROR: Empty input — nothing to parse.")

    # Parse
    new_jobs, queued = parse(body)

    # Load existing data and merge
    existing = _load_json_list(JOBS_FILE)
    merged, added = _merge_into_jobs(existing, new_jobs)

    # Save jobs
    _save_json(JOBS_FILE, merged)

    # Append to queue file (load existing queue first)
    if queued:
        existing_queue = _load_json_list(QUEUE_FILE)
        _save_json(QUEUE_FILE, existing_queue + queued)

    # Summary
    print(f"Parsed     : {len(new_jobs)} job(s) extracted")
    print(f"New (added): {added}")
    print(f"Queued     : {len(queued)} unmatched line(s)")
    print(f"Total jobs : {len(merged)}")
    print(f"Saved to   : {JOBS_FILE}")
    if queued:
        print(f"Queue file : {QUEUE_FILE}")


if __name__ == "__main__":
    main()
