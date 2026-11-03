"""Load the builtin tier-1 profiles from ``publishers/builtin/*.json``.

The JSON files are the only source of truth. Each file is
``{"schema_version": 1, "profile": {...}}``; the registry key is the file stem
(``elsevier.json`` -> ``elsevier``). Loading fails loudly on malformed data or
on two profiles claiming the same name, alias or DOI prefix, so a bad
contribution breaks the test-suite instead of silently changing routing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .model import PROFILE_FIELDS, PROFILE_LIST_FIELDS, PROFILE_REQUIRED, PdfSourcePathTemplate, PublisherProfile

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
_KEY_RE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_PLATFORM_RE = re.compile(r"[a-z][a-z0-9 _-]{0,40}")


class BuiltinProfileError(ValueError):
    """A builtin profile file is malformed or conflicts with another one."""


def _strings(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise BuiltinProfileError(f"{where}: expected an array of nonempty strings")
    return tuple(value)


def profile_from_mapping(raw: object, where: str) -> PublisherProfile:
    """Build a profile from the ``profile`` object of one JSON document."""
    if not isinstance(raw, dict):
        raise BuiltinProfileError(f"{where}: profile must be an object")
    unknown = set(raw) - PROFILE_FIELDS
    missing = PROFILE_REQUIRED - set(raw)
    if unknown or missing:
        raise BuiltinProfileError(f"{where}: unknown fields {sorted(unknown)} / missing fields {sorted(missing)}")
    values: dict[str, object] = {}
    for key, value in raw.items():
        if key in PROFILE_LIST_FIELDS:
            values[key] = _strings(value, f"{where}.{key}")
        elif key == "pdf_source_path_templates":
            if not isinstance(value, list):
                raise BuiltinProfileError(f"{where}.pdf_source_path_templates: expected an array")
            routes = []
            for item in value:
                if not isinstance(item, dict) or set(item) != {"domain", "path_prefix", "path_template"}:
                    raise BuiltinProfileError(f"{where}.pdf_source_path_templates: expected domain/path_prefix/path_template objects")
                routes.append(PdfSourcePathTemplate(**{k: str(v) for k, v in item.items()}))
            values[key] = tuple(routes)
        elif key == "platform":
            if not isinstance(value, str) or not _PLATFORM_RE.fullmatch(value):
                raise BuiltinProfileError(f"{where}.platform: expected a short lowercase platform name")
            values[key] = value
        else:
            if not isinstance(value, str) or not value.strip():
                raise BuiltinProfileError(f"{where}.{key}: expected a nonempty string")
            values[key] = value
    return PublisherProfile(**values)  # type: ignore[arg-type]


def load_builtin_profiles(directory: Path = BUILTIN_DIR) -> dict[str, PublisherProfile]:
    profiles: dict[str, PublisherProfile] = {}
    names: dict[str, str] = {}
    prefixes: dict[str, str] = {}
    for path in sorted(directory.glob("*.json")):
        key = path.stem
        if not _KEY_RE.fullmatch(key) or len(key) > 80:
            raise BuiltinProfileError(f"{path.name}: file stem must be a lowercase hyphen-separated key")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BuiltinProfileError(f"{path.name}: cannot read JSON ({type(exc).__name__})") from exc
        if (not isinstance(document, dict) or set(document) != {"schema_version", "profile"}
                or document.get("schema_version") != 1):
            raise BuiltinProfileError(f"{path.name}: expected {{schema_version: 1, profile: {{...}}}}")
        profile = profile_from_mapping(document["profile"], path.name)
        for alias in (key, profile.name, *profile.aliases):
            folded = alias.casefold()
            if folded in names and names[folded] != key:
                raise BuiltinProfileError(f"{path.name}: name/alias '{alias}' already used by {names[folded]}")
            names[folded] = key
        for prefix in profile.doi_prefixes:
            if prefix in prefixes and prefixes[prefix] != key:
                raise BuiltinProfileError(f"{path.name}: DOI prefix {prefix} already claimed by {prefixes[prefix]}")
            prefixes[prefix] = key
        profiles[key] = profile
    if not profiles:
        raise BuiltinProfileError(f"no builtin profiles found under {directory}")
    return profiles
