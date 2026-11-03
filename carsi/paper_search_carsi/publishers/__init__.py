"""Tier 1: declarative publisher profiles.

- builtin/<key>.json   the only source of truth; one publisher per file, file stem = registry key
- schema.json          what a profile may contain (also used by tests)
- model.py             PublisherProfile dataclass
- loader.py            loads builtin/*.json and rejects conflicts
- profiles.py          lookup API (get / infer by DOI or URL) and legacy *_PROFILE constants
- site.py              run-time profile for a site without a profile (shared rules only)
- extensions.py        strict loader for a user-provided publisher_profiles_file
"""
