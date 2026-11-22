"""The progress window in other languages than its own simplified Chinese: ``assets/capsule_en.json`` maps each
Chinese text it can show (its own, the download's prompts and phases, PaperSearch's failure reasons) to a short
English one; ``assets/capsule_zh-Hant.json`` (made from it by ``school/tools/zh_hant_table.py``, user 2026-11-21)
says each in Traditional Chinese, and turns any other text character by character; ``capsule_ja.json``,
``capsule_ko.json`` and ``capsule_fr.json`` say them in Japanese, Korean and French (user, 2026-11-21), a text they
do not know in English. The page translates what it shows with them; the system notifications use them here. In
English a text the table does not know stays as it is."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
#: Each language's table; Chinese (zh, simplified) is the windows' own.
TABLES = {"en": ASSETS / "capsule_en.json", "zh-Hant": ASSETS / "capsule_zh-Hant.json",
          "ja": ASSETS / "capsule_ja.json", "ko": ASSETS / "capsule_ko.json", "fr": ASSETS / "capsule_fr.json"}
TABLE = TABLES["en"]
LANGUAGES = ("zh", "zh-Hant", "en", "ja", "ko", "fr")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_BRACKETS = re.compile(r"^(.+?)（(.+)）$")
_LISTED = re.compile(r"^([^：]+)：(.+)$")


@lru_cache(maxsize=None)
def table(lang: str = "en") -> dict:
    return json.loads(TABLES[lang].read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _patterns(lang: str = "en") -> list[tuple[re.Pattern, str]]:
    return [(re.compile(source), target) for source, target in table(lang)["patterns"]]


def _part(text: str, lang: str) -> str:
    return _one(text, lang) if _HAN.search(text) else text


def _one(text: str, lang: str = "en") -> str:
    core = text.strip()
    if not core or not _HAN.search(core):
        return text
    exact = table(lang)["exact"].get(core)
    if exact is None:
        for pattern, target in _patterns(lang):
            found = pattern.search(core)
            if found:
                # What it names is said too where it is a text of the table; a name keeps its words (as the page does).
                said = re.sub(r"\$(\d)", lambda m: _part(found.group(int(m.group(1))) or "", lang), target)
                exact = core[:found.start()] + said + core[found.end():]
                break
    if exact is None and lang == "zh-Hant":
        # Not a text of the table: its characters (a name keeps its words).
        chars = table(lang)["chars"]
        exact = "".join(chars.get(c, c) for c in core)
    parts = _BRACKETS.match(core) if exact is None else None
    if parts:
        # "开放下载 18（出版社 API 3、预印本 1）": the text and what its brackets list, each on its own.
        exact = f"{_one(parts[1], lang)} ({', '.join(_one(item, lang) for item in parts[2].split('、'))})"
    listed = _LISTED.match(core) if exact is None else None
    if listed and _one(listed[1], lang) != listed[1]:
        # "读取失败：TimeoutError": a known word, then what it says, each on its own (as the page does).
        exact = f"{_one(listed[1], lang)}: {', '.join(_one(item, lang) for item in listed[2].split('，'))}"
    if exact is None and lang not in ("en", "zh-Hant"):
        # Japanese, Korean, French: what their table does not know, in English rather than in Chinese.
        return _one(text, "en")
    return text if exact is None else text.replace(core, exact)


def translate(text: str, lang: str) -> str:
    """``text`` in ``lang``; its " · " parts one by one, as the page does."""
    if lang not in TABLES or not text:
        return text
    return " · ".join(_one(part, lang) for part in text.split(" · "))
