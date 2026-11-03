"""Explicit, data-only publisher profiles; no global registration or config IO.

Call load_publisher_profiles(config) once at the workflow boundary, then pass
the returned mapping to the profile lookup functions. Invalid configuration
raises PublisherProfileConfigError; it must not silently select another route.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from string import Formatter
from urllib.parse import parse_qsl, urlsplit

from .model import PdfSourcePathTemplate, PublisherProfile
from .profiles import PUBLISHER_PROFILES


MAX_FILE_BYTES = 1_048_576
MAX_PROFILES = 128
_DOI_FIELDS = {"doi", "doi_quoted", "doi_suffix", "doi_suffix_quoted"}
_SOURCE_FIELDS = _DOI_FIELDS | {"source_path", "source_path_after_prefix"}
_REQUIRED = {
    "name", "article_url_template", "pdf_url_templates", "base_domains", "doi_prefixes",
    "success_url_markers", "auth_url_markers", "sso_text_markers",
}
_LIST_FIELDS = {
    "pdf_url_templates", "base_domains", "doi_prefixes", "aliases", "sample_dois",
    "success_url_markers", "auth_url_markers", "auth_title_markers", "sso_text_markers",
    "pdf_url_markers", "pdf_link_text_markers", "supplementary_url_markers",
    "institution_input_selectors",
}
_ALLOWED = _LIST_FIELDS | {"name", "article_url_template", "pdf_source_path_templates", "platform"}


class PublisherProfileConfigError(ValueError):
    """Invalid explicit profile configuration; messages never echo its values."""


def _error(field: str, rule: str) -> None:
    raise PublisherProfileConfigError(f"publisher profiles: {field}: {rule}") from None


def _text(value: object, field: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 2048
            or value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _error(field, "expected a nonempty trimmed string without control characters (max 2048)")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 64:
        _error(field, "expected an array of at most 64 strings")
    values = tuple(_text(item, field) for item in value)
    if len({item.casefold() for item in values}) != len(values):
        _error(field, "duplicate entries")
    return values


def _domain(value: str, field: str) -> str:
    # Explicit DNS names only. Do not resolve DNS or read a public-suffix file.
    domain = value.lower()
    labels = domain.split(".")
    if (len(domain) > 253 or len(labels) < 2 or labels[-1].isdigit()
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)):
        _error(field, "expected a DNS hostname, without scheme/port/path/wildcard")
    return domain


def _owns(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _template(value: str, allowed: set[str], field: str) -> str:
    try:
        parts = list(Formatter().parse(value))
    except ValueError:
        _error(field, "malformed template")
    used = set()
    for _, name, spec, conversion in parts:
        if name is not None:
            if name not in allowed or spec or conversion:
                _error(field, "unsupported placeholder, attribute/index access, conversion or format spec")
            used.add(name)
    if not used:
        _error(field, "a DOI/source placeholder is required")
    rendered = value.format(**{name: "/article/fixture" if name == "source_path" else "fixture" for name in allowed})
    if "{" in rendered or "}" in rendered:
        _error(field, "literal braces are not supported")
    return rendered


def _https_url(value: str, domains: tuple[str, ...], field: str, *, resolver: bool = False) -> None:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        _error(field, "invalid URL")
    if (parsed.scheme != "https" or not host or parsed.username is not None
            or parsed.password is not None or port not in (None, 443) or parsed.fragment
            or "\\" in value or any(char.isspace() for char in value)):
        _error(field, "expected HTTPS without credentials, fragment or nonstandard port")
    _domain(host, field)
    if any(re.search(r"token|secret|password|cookie|session|signature|api[_-]?key|access[_-]?key|auth|credential", key, re.I)
           or key.lower() in {"key", "sig", "username", "email"}
           for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        _error(field, "credentials and signed/session query parameters are not profile data")
    if not _owns(host, domains) and not (resolver and host == "doi.org"):
        _error(field, "URL host must belong to base_domains (article resolver may use doi.org)")


def _profile(raw: object) -> PublisherProfile:
    if not isinstance(raw, dict) or not _REQUIRED <= raw.keys() or raw.keys() - _ALLOWED:
        _error("profile", "missing required or unknown fields; school-specific selectors/credentials are not supported")
    values = {field: _strings(value, field) if field in _LIST_FIELDS else value for field, value in raw.items()}
    values["name"] = _text(values["name"], "name")
    if "platform" in values:
        platform = _text(values["platform"], "platform")
        if not re.fullmatch(r"[a-z][a-z0-9 _-]{0,40}", platform):
            _error("platform", "expected a short lowercase platform label")
        values["platform"] = platform
    values["article_url_template"] = _text(values["article_url_template"], "article_url_template")
    domains = tuple(_domain(domain, "base_domains") for domain in values["base_domains"])
    if not domains:
        _error("base_domains", "at least one domain is required")
    values["base_domains"] = domains
    # v1 matches whole registrant prefixes, not arbitrary prefix/regex rules.
    if not values["doi_prefixes"] or any(not re.fullmatch(r"10\.\d{4,9}", prefix) for prefix in values["doi_prefixes"]):
        _error("doi_prefixes", "expected nonempty whole DOI registrant prefixes (10. plus 4-9 digits)")
    for doi in values.get("sample_dois", ()):
        if (not re.fullmatch(r"10\.\d{4,9}/[^\s?#]+", doi)
                or doi.split("/", 1)[0] not in values["doi_prefixes"]):
            _error("sample_dois", "expected DOI identifiers belonging to this profile")
    article = values["article_url_template"]
    _https_url(article, domains, "article_url_template", resolver=True)
    _https_url(_template(article, {"doi"}, "article_url_template"), domains, "article_url_template", resolver=True)
    for template in values["pdf_url_templates"]:
        _https_url(template, domains, "pdf_url_templates")
        _https_url(_template(template, _DOI_FIELDS, "pdf_url_templates"), domains, "pdf_url_templates")
    if not values["success_url_markers"]:
        _error("success_url_markers", "at least one publisher host/path marker is required")
    for marker in values["success_url_markers"]:
        _https_url(marker if "://" in marker else "https://" + marker, domains, "success_url_markers")
        if "{" in marker or "}" in marker or "?" in marker:
            _error("success_url_markers", "expected literal host/path markers without query or template")
    templates = values.get("pdf_source_path_templates", [])
    if not isinstance(templates, list) or len(templates) > 64:
        _error("pdf_source_path_templates", "expected an array of at most 64 objects")
    paths = []
    for item in templates:
        if not isinstance(item, dict) or set(item) != {"domain", "path_prefix", "path_template"}:
            _error("pdf_source_path_templates", "expected domain, path_prefix and path_template only")
        domain = _domain(_text(item["domain"], "domain"), "domain")
        if not _owns(domain, domains):
            _error("pdf_source_path_templates", "domain must belong to base_domains")
        prefix = _text(item["path_prefix"], "path_prefix")
        path = _text(item["path_template"], "path_template")
        rendered = _template(path, _SOURCE_FIELDS, "path_template")
        if (not prefix.startswith("/") or prefix.startswith("//")
                or any(char in prefix for char in "{}?#\\")
                or not rendered.startswith("/") or rendered.startswith("//")
                or any(char in path for char in "?#\\") or "://" in path):
            _error("pdf_source_path_templates", "expected same-host absolute paths, no query/fragment/URL")
        route = PdfSourcePathTemplate(domain=domain, path_prefix=prefix, path_template=path)
        if route in paths:
            _error("pdf_source_path_templates", "duplicate route")
        paths.append(route)
    values["pdf_source_path_templates"] = tuple(paths)
    return PublisherProfile(**values)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            _error("JSON", "duplicate object key")
        value[key] = item
    return value


def _reject_constant(_: str) -> None:
    _error("JSON", "non-finite numbers are not allowed")


def load_publisher_profiles(config: Mapping) -> dict[str, PublisherProfile]:
    """Copy builtins and load one explicitly selected local JSON, or raise.

    With no publisher_profiles_file key, this performs no filesystem/network
    IO. Even an explicitly empty/None path is an error, not a builtin fallback.
    Input config and the module-level registry are never modified.
    """
    if not isinstance(config, Mapping):
        _error("config", "expected a mapping")
    profiles = dict(PUBLISHER_PROFILES)
    if "publisher_profiles_file" not in config:
        return profiles
    filename = config["publisher_profiles_file"]
    if not isinstance(filename, (str, os.PathLike)) or not os.fspath(filename):
        _error("publisher_profiles_file", "expected a nonempty local file path")
    try:
        path = Path(filename)
        if not path.is_file():
            _error("publisher_profiles_file", "expected a readable regular file")
        with path.open("rb") as handle:
            payload = handle.read(MAX_FILE_BYTES + 1)
        if len(payload) > MAX_FILE_BYTES:
            _error("publisher_profiles_file", "file exceeds 1 MiB")
        document = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except PublisherProfileConfigError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        _error("publisher_profiles_file", "cannot read valid JSON")
    if (not isinstance(document, dict) or set(document) != {"schema_version", "profiles"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or not isinstance(document["profiles"], dict) or len(document["profiles"]) > MAX_PROFILES):
        _error("document", "expected schema_version=1 and a profiles map of at most 128 entries")
    for key, raw in document["profiles"].items():
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", key) or len(key) > 80:
            _error("profiles key", "expected a lowercase hyphen-separated identifier (max 80)")
        profile = _profile(raw)
        names = {value.casefold() for value in (key, profile.name, *profile.aliases)}
        for existing_key, existing in profiles.items():
            existing_names = {value.casefold() for value in (existing_key, existing.name, *existing.aliases)}
            if names & existing_names:
                _error("profile names", "key/name/alias conflicts with another profile")
            if set(profile.doi_prefixes) & set(existing.doi_prefixes):
                _error("doi_prefixes", "conflicts with another profile")
            # Shared/subdomain authorities would make URL inference depend on
            # insertion order. Include builtin marker-only hosts as well.
            existing_domains = set(existing.base_domains)
            existing_domains.update(urlsplit(marker if "://" in marker else "//" + marker).hostname or ""
                                    for marker in existing.success_url_markers)
            if any(a and b and (_owns(a, (b,)) or _owns(b, (a,)))
                   for a in profile.base_domains for b in existing_domains):
                _error("base_domains", "overlaps another profile's publisher host")
        profiles[key] = profile
    return profiles
