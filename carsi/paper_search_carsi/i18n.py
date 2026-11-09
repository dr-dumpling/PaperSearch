"""The progress window in English: ``assets/capsule_en.json`` maps each Chinese
text it can show (its own, the download's prompts and phases, PaperSearch's
failure reasons) to a short English one. The page translates what it shows with
it; the system notifications use it here. A text the table does not know stays
as it is."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

TABLE = Path(__file__).resolve().parent / "assets" / "capsule_en.json"
LANGUAGES = ("zh", "en")
_HAN = re.compile(r"[\u4e00-\u9fff]")


@lru_cache(maxsize=1)
def table() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, str]]:
    # The table's replacements are written for JavaScript ($1); Python's are \g<1>.
    return [(re.compile(source), re.sub(r"\$(\d)", r"\\g<\1>", target)) for source, target in table()["patterns"]]


def _one(text: str) -> str:
    core = text.strip()
    if not core or not _HAN.search(core):
        return text
    exact = table()["exact"].get(core)
    if exact is None:
        for pattern, target in _patterns():
            if pattern.search(core):
                exact = pattern.sub(target, core)
                break
    return text if exact is None else text.replace(core, exact)


def translate(text: str, lang: str) -> str:
    """``text`` in ``lang``; its " · " parts one by one, as the page does."""
    if lang != "en" or not text:
        return text
    return " · ".join(_one(part) for part in text.split(" · "))
