"""Publisher-specific behaviour belongs in adapters/: the engine's checks of a
publisher may only go down (docs/dependencies/institutional-publisher-adapters.zh.md).

A check is a string in the engine's code (not a docstring, not a comment, not a
comment line of an embedded script) that names a builtin publisher, by its name,
an alias or the registrable domain of one of its hosts ("ieee xplore is
temporarily unavailable", "ipblock@acs.org", "profile.thieme.de"), or a
comparison that reads ``profile.name``. Counted once per line."""
import ast
import json
import re
import unittest
from pathlib import Path

from paper_search_school.engine.access_rules import registrable_domain

PACKAGE = Path(__file__).resolve().parents[1] / "paper_search_school"
ENGINE = PACKAGE / "engine"
BUILTIN = PACKAGE / "publishers" / "builtin"
# Lower this when a publisher's checks move into its adapter. Never raise it:
# write the new behaviour as an adapter hook instead. What remains (2026-11-02)
# are the PDF router's URL helpers that adapters call (router.py).
LIMIT = 16
# Names in labels and settings, not checks: (file, word).
LABELS = {
    ("bridge.py", "elsevier"),  # the instsci package's settings elsevier_api_key, elsevier_insttoken
}
_SCRIPT_COMMENT = re.compile(r"^\s*//.*$", re.M)


def publisher_words() -> re.Pattern:
    words = set()
    for path in BUILTIN.glob("*.json"):
        profile = json.loads(path.read_text(encoding="utf-8"))["profile"]
        words |= {profile["name"].lower(), *(alias.lower() for alias in profile.get("aliases", ()))}
        words |= {registrable_domain(host) for host in profile.get("base_domains", ())}
    alternatives = "|".join(sorted(map(re.escape, words), key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{alternatives})(?![a-z0-9])")


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _reads_profile_name(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "name"
               and ((isinstance(n.value, ast.Attribute) and n.value.attr == "profile")
                    or (isinstance(n.value, ast.Name) and n.value.id == "profile"))
               for n in ast.walk(node))


def engine_checks() -> dict[tuple[str, int], set[str]]:
    words = publisher_words()
    checks: dict[tuple[str, int], set[str]] = {}
    for path in sorted(ENGINE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = _docstrings(tree)
        for node in ast.walk(tree):
            found: set[str] = set()
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                found = set(words.findall(_SCRIPT_COMMENT.sub("", node.value.lower())))
                found -= {word for file, word in LABELS if file == path.name}
            elif isinstance(node, ast.Compare) and _reads_profile_name(node):
                found = {"profile.name"}
            if found:
                checks.setdefault((path.name, node.lineno), set()).update(found)
    return checks


class EnginePublisherChecksTests(unittest.TestCase):
    def test_the_engine_gains_no_checks_of_a_publisher(self):
        checks = engine_checks()
        listed = "; ".join(f"{file}:{line} {sorted(words)}" for (file, line), words in sorted(checks.items()))
        self.assertLessEqual(len(checks), LIMIT, f"{len(checks)} publisher checks in the engine (limit {LIMIT}): "
                             f"{listed}; put publisher behaviour in adapters/")

    def test_the_scan_sees_hosts_names_and_profile_name_comparisons(self):
        words = publisher_words()
        for text in ("onlinesupport@ieee.org", "ieee xplore is temporarily unavailable", "ipblock@acs.org",
                     "profile.thieme.de", "annualreviews.org/session/ext/athens"):
            self.assertTrue(words.search(text), text)
        for text in ("signature", "access through your institution", "ds.carsi.edu.cn", "params"):
            self.assertFalse(words.search(text), text)
        tree = ast.parse('if self.profile.name.lower() == x:\n    pass\nlog(f"{profile.name}")')
        compares = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)]
        self.assertTrue(_reads_profile_name(compares[0]))
        self.assertEqual(len(compares), 1)  # a label is no comparison


if __name__ == "__main__":
    unittest.main()
