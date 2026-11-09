"""Reading PDFs: page count, page text, and whether a transfer ended whole.

Every PDF the backend reads goes through here, so the library can change in one
place. It is pypdfium2 (PDFium, Chrome's PDF engine; BSD/Apache, about 10 MB),
which replaced PyMuPDF (AGPL, about 54 MB) in 2026-11. PDFium allows one call at
a time in a process, even on different documents, so every call takes a lock."""
from __future__ import annotations

import re
import threading
from pathlib import Path

_LOCK = threading.Lock()
# The last startxref of a file and the cross-reference it names.
_STARTXREF = re.compile(rb"startxref\s+(\d+)\s+%%EOF")
_XREF_OBJECT = re.compile(rb"\d+\s+\d+\s+obj\b")


class PdfError(Exception):
    """Not a PDF the library can read, or one without pages."""


def _open(source: bytes | str | Path):
    import pypdfium2

    try:
        return pypdfium2.PdfDocument(bytes(source) if isinstance(source, (bytes, bytearray)) else str(source))
    except pypdfium2.PdfiumError as exc:
        raise PdfError(str(exc)) from exc


def page_count(source: bytes | str | Path) -> int:
    with _LOCK:
        document = _open(source)
        try:
            return len(document)
        finally:
            document.close()


def page_texts(source: bytes | str | Path, pages: int | None = None) -> list[str]:
    """The text of each of the first ``pages`` pages (all when None)."""
    with _LOCK:
        document = _open(source)
        try:
            count = len(document)
            if not count:
                raise PdfError("no pages")
            texts = []
            for index in range(count if pages is None else min(pages, count)):
                page = document[index]
                textpage = page.get_textpage()
                try:
                    texts.append(_clean(textpage.get_text_bounded()))
                finally:
                    textpage.close()
                    page.close()
            return texts
        finally:
            document.close()


def text(source: bytes | str | Path, pages: int | None = None) -> str:
    """The first ``pages`` pages' text (all when None), a line break between pages."""
    return "\n".join(page_texts(source, pages))


def _clean(text: str) -> str:
    # PDFium ends lines with \r\n and writes a hyphen it found at a line's end as \x02.
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x02", "-")


def complete(body: bytes) -> bool:
    """Whether the bytes end as a whole PDF: %%EOF after a startxref that points
    at a cross-reference table or stream. A cut-off or damaged transfer, which
    a reader would have to repair, does not."""
    found = list(_STARTXREF.finditer(body[-2048:]))
    if not found:
        return False
    offset = int(found[-1].group(1))
    if offset >= len(body):
        return False
    head = body[offset:offset + 64].lstrip()
    return head.startswith(b"xref") or _XREF_OBJECT.match(head) is not None
