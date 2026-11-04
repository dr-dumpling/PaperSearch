"""Per-publisher adapters for the publisher browser driver.

The shared engine (``PublisherBatchDownloader``) owns navigation, waits for
human verification, the PDF capture channels and the run records. An adapter
answers only its publisher's questions: is this reader signed in, where is
the institution entry, which URL is the article PDF, which links are its
supplementary files. Every hook returns ``None`` for "no opinion", and the
engine then applies its generic behaviour, so publishers without an adapter
keep working unchanged.

Each publisher, and each platform shared by several publishers (``atypon``,
``silverchair``), has its own folder here: its rules in ``<name>/__init__.py``,
and one more module per site type when it has several (``elsevier/``,
``lww/``). ``base.py`` holds the shared base class and its defaults.

Adding a publisher: subclass :class:`PublisherAdapter` in ``<name>/__init__.py``,
decorate it with :func:`register`, and import the package below.
"""

from .base import PublisherAdapter, SupplementLink, adapter_class, adapter_for, register
from . import (  # noqa: F401  (register the adapters)
    acm, acs, aha_journals, ams, annual_reviews, aps, asce, bmj, copernicus, dovepress, elsevier, frontiers, ieee, iop,
    jama, karger, lww, mdpi, nejm, neurology, optica, oup, plos, pnas, rsc, sage, science, springer,
    taylor_francis, thieme, wiley, world_scientific)

__all__ = ["PublisherAdapter", "SupplementLink", "adapter_class", "adapter_for", "register"]
