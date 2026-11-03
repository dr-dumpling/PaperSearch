"""Data model for tier-1 publisher profiles.

A profile is pure data: URL templates, page markers and selectors that describe
one publisher's site. The browser logic that consumes it is the engine
(``engine/``) with the publisher's adapter (``adapters/``).
"""
from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from typing import ClassVar
from urllib.parse import quote


@dataclass(frozen=True)
class PdfSourcePathTemplate:
    """Route a publisher landing/source URL path to a PDF path."""

    domain: str
    path_prefix: str
    path_template: str


@dataclass(frozen=True)
class PublisherProfile:
    """Declarative rules for a publisher-specific download workflow."""

    name: str
    article_url_template: str
    pdf_url_templates: tuple[str, ...]
    success_url_markers: tuple[str, ...]
    auth_url_markers: tuple[str, ...]
    sso_text_markers: tuple[str, ...]
    #: Ignored: no code reads it (a login page is told by its address, the shared
    #: access rule's). Optional, kept so that profile files that have it still
    #: load (review 2026-11-02).
    auth_title_markers: tuple[str, ...] = field(default_factory=tuple)
    aliases: tuple[str, ...] = field(default_factory=tuple)
    doi_prefixes: tuple[str, ...] = field(default_factory=tuple)
    sample_dois: tuple[str, ...] = field(default_factory=tuple)
    base_domains: tuple[str, ...] = field(default_factory=tuple)
    pdf_source_path_templates: tuple[PdfSourcePathTemplate, ...] = field(default_factory=tuple)
    pdf_url_markers: tuple[str, ...] = (
        "/doi/pdf/",
        "/doi/epdf/",
        "/pdf/",
        "/pdf",
        "pdf",
    )
    pdf_link_text_markers: tuple[str, ...] = ("pdf",)
    supplementary_url_markers: tuple[str, ...] = (
        "suppl_file",
        "suppdata",
        "supporting-information",
        "supplementary",
    )
    institution_input_selectors: tuple[str, ...] = field(default_factory=tuple)
    institution_result_selectors: tuple[str, ...] = field(default_factory=tuple)
    #: Platform label (the builtin profiles' are listed by the MCP tool
    #: ``carsi_list_publishers``); no download code reads it. ``generic`` when
    #: the profile names none.
    platform: str = "generic"
    #: Built at run time for a site without a publisher profile (``site.py``):
    #: only the shared rules apply there. Not a field: never in a profile file.
    generic: ClassVar[bool] = False

    def article_url(self, doi: str) -> str:
        """The profile's article address; a publisher whose address cannot be
        a template answers through its adapter's ``article_url`` (APS)."""
        return self.article_url_template.format(doi=doi)

    def pdf_urls(self, doi: str) -> list[str]:
        doi_suffix = doi.split("/", 1)[-1] if "/" in doi else doi
        values = {
            "doi": doi,
            "doi_quoted": quote(doi, safe=""),
            "doi_suffix": doi_suffix,
            "doi_suffix_quoted": quote(doi_suffix, safe=""),
        }
        return [template.format(**values) for template in self.pdf_url_templates]


PROFILE_FIELDS: frozenset[str] = frozenset(f.name for f in fields(PublisherProfile))
PROFILE_REQUIRED: frozenset[str] = frozenset(
    f.name for f in fields(PublisherProfile) if f.default is MISSING and f.default_factory is MISSING
)
PROFILE_LIST_FIELDS: frozenset[str] = frozenset(
    f.name for f in fields(PublisherProfile)
    if f.name not in {"name", "article_url_template", "platform", "pdf_source_path_templates"}
)

