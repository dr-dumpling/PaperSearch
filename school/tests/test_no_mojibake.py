"""Source text must not carry mojibake (UTF-8 Chinese read as GBK, stored again).

A marker written that way never matches the page it was meant for, and a test
that used the same wrong string hides it: Cloudflare's Chinese marker sat as
mojibake for months while its test passed (found and fixed 2026-11-18).

The check is a round trip, not a list of suspicious characters, so ordinary
Chinese that happens to look odd (楠, 浠) is never reported: only text whose
GBK bytes decode as different valid UTF-8 is mojibake.
"""
from __future__ import annotations

from pathlib import Path

SCHOOL = Path(__file__).resolve().parents[1]
#: Directories whose text is shipped or run: the Python, and the windows' pages and
#: string tables (assets/capsule.html, capsule_en.json), whose Chinese users read. Docs
#: and history are not; fixtures are third parties' pages, kept as they came. The core,
#: Pro and the Skill have the same check (tests/core/noMojibake.test.ts).
SEARCHED = ("paper_search_school", "tests")
TEXT_SUFFIXES = {".py", ".html", ".js", ".css", ".json", ".md", ".txt", ".toml"}


def _mojibake_of(line: str) -> str | None:
    """The text ``line`` becomes when its GBK bytes are read as UTF-8, or None."""
    if not any(ord(char) > 127 for char in line):
        return None
    try:
        raw = line.encode("gbk")
    except UnicodeEncodeError:
        return None
    try:
        recovered = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if recovered == line or not any("\u4e00" <= char <= "\u9fff" for char in recovered):
        return None
    return recovered


def _source_files():
    for folder in SEARCHED:
        root = SCHOOL / folder
        if root.is_dir():
            yield from sorted(path for path in root.rglob("*") if path.suffix in TEXT_SUFFIXES and path.is_file()
                              and not {"fixtures", "__pycache__"} & set(path.relative_to(root).parts))


def test_source_text_carries_no_mojibake():
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            recovered = _mojibake_of(line)
            if recovered is not None:
                offenders.append(f"{path.relative_to(SCHOOL)}:{number}: {line.strip()[:70]}"
                                 f"  (reads as {recovered.strip()[:40]})")
    assert not offenders, "mojibake in source text:\n" + "\n".join(offenders)


def test_the_check_finds_mojibake_and_leaves_ordinary_chinese_alone():
    # What Cloudflare's Chinese marker was stored as until 2026-11-18, written as
    # escapes so this file carries no mojibake of its own.
    mojibake = "\u7039\u590a\u53cf\u6960\u5c83\u7609"
    assert _mojibake_of(f'    "{mojibake}",') is not None
    # Ordinary Chinese that merely looks unusual is not reported.
    assert _mojibake_of('    "楠木与浠水的例子",') is None
    assert _mojibake_of('    "安全验证",') is None
