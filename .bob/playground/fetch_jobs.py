#!/usr/bin/env python3
"""
fetch_jobs.py — CyberJobs India data pipeline
Fetches cybersecurity job listings from Remotive and Jobicy APIs,
normalises them into the data/jobs.json schema, deduplicates by id,
prunes stale entries (>60 days), and writes the merged result back.
"""

import hashlib
import json
import os
import sys
import warnings
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    sys.exit("ERROR: 'requests' is not installed. Run: pip install requests")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "jobs.json")

INDIA_KEYWORDS = [
    "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi",
    "chennai", "kochi", "india", "remote", "worldwide", "anywhere",
    "pan india", "noida", "gurugram", "gurgaon", "kolkata", "ahmedabad",
]

CAT_MAP = [
    ("SOC",           ["soc analyst", "security operations", "siem", "soc engineer"]),
    ("VAPT",          ["penetration", "pentest", "vapt", "red team", "offensive security", "bug bounty"]),
    ("DFIR",          ["incident response", "dfir", "forensic", "digital forensic"]),
    ("Cloud Security",["cloud security", "aws security", "azure security", "gcp security", "cspm", "cnapp"]),
    ("AppSec",        ["appsec", "application security", "sast", "dast", "devsecops", "secure code"]),
    ("IAM",           ["identity", "iam", "access management", "sailpoint", "cyberark", "okta", "pam"]),
    ("GRC",           ["grc", "governance", "risk", "compliance", "iso 27001", "audit"]),
    ("Threat",        ["threat intel", "threat hunting", "threat intelligence", "mitre", "cti"]),
    ("Engineering",   ["security engineer", "security engineering", "detection engineer", "soar"]),
    ("Architecture",  ["security architect", "architecture", "zero trust", "sase"]),
    ("Malware",       ["malware", "reverse engineer", "reverse engineering", "ida pro", "assembly"]),
    ("Privacy",       ["privacy", "gdpr", "dpdp", "data protection", "onetrust"]),
]

EXP_MAP = [
    ("Internship", ["intern", "trainee", "student"]),
    ("0–2 years",  ["junior", "associate", "fresher", "entry", "graduate", "analyst i", "level 1"]),
    ("5+ years",   ["senior", "lead", "principal", "manager", "director", "head of", "architect", "staff"]),
]
EXP_DEFAULT = "2–5 years"

PRUNE_DAYS = 60

# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------

def infer_cat(title: str, tags: str = "") -> str:
    """Return the best-matching category from CAT_MAP, or 'Engineering'."""
    haystack = (title + " " + tags).lower()
    for cat, keywords in CAT_MAP:
        if any(kw in haystack for kw in keywords):
            return cat
    return "Engineering"


def infer_exp(title: str) -> str:
    """Return the best-matching experience band from EXP_MAP."""
    t = title.lower()
    for exp, keywords in EXP_MAP:
        if any(kw in t for kw in keywords):
            return exp
    return EXP_DEFAULT


def make_id(title: str, company: str, url: str) -> str:
    """Stable 12-char SHA-256 id of lowercase-stripped title+company+url."""
    raw = (title + company + url).lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def is_india_relevant(location: str) -> bool:
    loc = location.lower()
    return any(kw in loc for kw in INDIA_KEYWORDS)


# ---------------------------------------------------------------------------
# API fetchers
# ---------------------------------------------------------------------------

def fetch_remotive() -> list:
    """Fetch from Remotive JSON API and return normalised job dicts."""
    url = "https://remotive.com/api/remote-jobs?category=security"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        warnings.warn(f"[Remotive] fetch failed: {exc}")
        return []

    jobs = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for j in data.get("jobs", []):
        location = j.get("candidate_required_location", "") or ""
        if not is_india_relevant(location):
            continue
        title   = (j.get("title") or "").strip()
        company = (j.get("company_name") or "").strip()
        raw_url = (j.get("url") or "").strip()
        tags_raw = j.get("tags") or ""
        # tags can be a comma-separated string or a list
        if isinstance(tags_raw, list):
            tags = [str(t).strip() for t in tags_raw]
        else:
            tags = [t.strip() for t in str(tags_raw).split(",") if t.strip()]
        skills = tags[:5]
        tags_str = " ".join(tags)

        jobs.append({
            "id":         make_id(title, company, raw_url),
            "title":      title,
            "company":    company,
            "location":   location,
            "exp":        infer_exp(title),
            "cat":        infer_cat(title, tags_str),
            "skills":     skills,
            "url":        raw_url,
            "sourceType": "api",
            "intern":     any(kw in title.lower() for kw in ["intern", "trainee", "student"]),
            "fetchedAt":  now_iso,
        })
    return jobs


def fetch_jobicy() -> list:
    """Fetch from Jobicy JSON API and return normalised job dicts."""
    url = "https://jobicy.com/api/v2/remote-jobs?industry=security&count=50"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        warnings.warn(f"[Jobicy] fetch failed: {exc}")
        return []

    jobs = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for j in data.get("jobs", []):
        location = j.get("jobGeo", "") or ""
        if not is_india_relevant(location):
            continue
        title   = (j.get("jobTitle") or "").strip()
        company = (j.get("companyName") or "").strip()
        raw_url = (j.get("url") or "").strip()
        tags_raw = j.get("jobTags") or []
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        else:
            tags = [str(t).strip() for t in tags_raw]
        skills = tags[:5]
        tags_str = " ".join(tags)

        jobs.append({
            "id":         make_id(title, company, raw_url),
            "title":      title,
            "company":    company,
            "location":   location,
            "exp":        infer_exp(title),
            "cat":        infer_cat(title, tags_str),
            "skills":     skills,
            "url":        raw_url,
            "sourceType": "api",
            "intern":     any(kw in title.lower() for kw in ["intern", "trainee", "student"]),
            "fetchedAt":  now_iso,
        })
    return jobs


# ---------------------------------------------------------------------------
# Load / merge / prune / save
# ---------------------------------------------------------------------------

def load_existing() -> list:
    """Load data/jobs.json; return empty list if missing or invalid."""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        warnings.warn(f"[load] Could not parse {DATA_FILE}: {exc}")
        return []


def merge(existing: list, incoming: list) -> tuple:
    """
    Merge incoming jobs into existing, deduplicating by id.
    Existing jobs without an id get one assigned on-the-fly.
    Returns (merged_list, new_count).
    """
    seen = {}
    for job in existing:
        # Backfill id for legacy entries that pre-date this script
        if not job.get("id"):
            job["id"] = make_id(
                job.get("title", ""),
                job.get("company", ""),
                job.get("url", ""),
            )
        seen[job["id"]] = job

    new_count = 0
    for job in incoming:
        jid = job["id"]
        if jid not in seen:
            seen[jid] = job
            new_count += 1
        # If already present, do NOT overwrite — preserves manual edits / pinned state

    return list(seen.values()), new_count


def prune_old(jobs: list) -> tuple:
    """
    Remove jobs where fetchedAt is older than PRUNE_DAYS days,
    unless pinned is True or fetchedAt is absent (legacy entries).
    Returns (pruned_list, prune_count).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=PRUNE_DAYS)
    kept, pruned = [], 0
    for job in jobs:
        if job.get("pinned"):
            kept.append(job)
            continue
        fetched_at = job.get("fetchedAt")
        if not fetched_at:
            # Legacy entry with no fetchedAt — keep it
            kept.append(job)
            continue
        try:
            ts = datetime.fromisoformat(fetched_at)
            # Ensure timezone-aware for comparison
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            kept.append(job)
            continue
        if ts >= cutoff:
            kept.append(job)
        else:
            pruned += 1
    return kept, pruned


def save(jobs: list) -> None:
    """Write jobs list to DATA_FILE, creating directories as needed."""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== CyberJobs India - fetch_jobs.py ===")

    # 1. Fetch from all sources
    print("Fetching from Remotive ...", end=" ", flush=True)
    remotive_jobs = fetch_remotive()
    print(f"{len(remotive_jobs)} India-relevant jobs")

    print("Fetching from Jobicy ...", end=" ", flush=True)
    jobicy_jobs = fetch_jobicy()
    print(f"{len(jobicy_jobs)} India-relevant jobs")

    fetched_total = len(remotive_jobs) + len(jobicy_jobs)
    incoming = remotive_jobs + jobicy_jobs

    # 2. Load existing data
    existing = load_existing()
    print(f"Loaded {len(existing)} existing jobs from {DATA_FILE}")

    # 3. Merge
    merged, new_count = merge(existing, incoming)

    # 4. Prune old entries
    merged, pruned_count = prune_old(merged)

    # 5. Save
    save(merged)

    print()
    print("-- Summary ------------------------------------------")
    print(f"  Fetched  : {fetched_total}")
    print(f"  New      : {new_count}")
    print(f"  Pruned   : {pruned_count}")
    print(f"  Total    : {len(merged)}")
    print(f"  Saved to : {DATA_FILE}")


if __name__ == "__main__":
    main()
