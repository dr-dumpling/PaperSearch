"""Publisher rules take any DOI: a journal a publisher took over keeps its DOI prefix
(Thieme's Thrombosis and Haemostasis, Schattauer's 10.1160, 2026-11-22: its article page was not
taken for Thieme's, whose rule knew only 10.1055, and the download ended without a login).

A rule is a string in the code of adapters/ or engine/ (not a docstring, not a comment line of an
embedded script) that names a DOI prefix. Each one left is listed below with why it may name it:
the publisher registers every article under that prefix and the rule reads the DOI's structure,
or the prefix is not a publisher's. A new one is written for any DOI (``10\\.\\d{4,9}/``) instead."""
import ast
import re
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "paper_search_school"
_PREFIX = re.compile(r"10\\?\.(\d{4,9})(?!\d)")
_SCRIPT_COMMENT = re.compile(r"^\s*//.*$", re.M)

ALLOWED = {
    ("adapters/ams/__init__.py", "10.1175"): "AMS registers every article under 10.1175; supplement paths name the DOI's suffix",
    ("adapters/copernicus/__init__.py", "10.5194"): "Copernicus DOIs spell journal, volume, page and year",
    ("adapters/dovepress/__init__.py", "10.2147"): "Dove Press DOIs carry the article number",
    ("adapters/elsevier/__init__.py", "10.1182"): "one journal's check: ASH's Blood and Blood Advances, on ashpublications.org",
    ("adapters/frontiers/__init__.py", "10.3389"): "Frontiers DOIs carry the article number",
    ("adapters/plos/__init__.py", "10.1371"): "PLOS DOIs name the journal; its XML address takes only them",
    ("engine/router.py", "10.1371"): "PLOS DOIs name the journal",
    ("engine/router.py", "10.5194"): "Copernicus DOIs spell journal, volume, page and year",
    ("engine/router.py", "10.3390"): "MDPI DOIs name the journal, read for its landing page",
    ("engine/router.py", "10.1038"): "nature.com addresses carry only the suffix of a 10.1038 DOI",
    **{("engine/pdf_guard.py", prefix): "a data or registration repository's DOI, not an article's"
       for prefix in ("10.17605", "10.5281", "10.6084", "10.5061", "10.17632", "10.7910")},
}


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def prefix_rules() -> dict[tuple[str, str], list[int]]:
    rules: dict[tuple[str, str], list[int]] = {}
    for path in sorted([*(PACKAGE / "adapters").rglob("*.py"), *(PACKAGE / "engine").rglob("*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = _docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                for match in _PREFIX.finditer(_SCRIPT_COMMENT.sub("", node.value)):
                    key = (path.relative_to(PACKAGE).as_posix(), "10." + match.group(1))
                    rules.setdefault(key, []).append(node.lineno)
    return rules


class DoiPrefixRulesTests(unittest.TestCase):
    def test_no_rule_names_a_doi_prefix_without_its_reason(self):
        new = {key: lines for key, lines in prefix_rules().items() if key not in ALLOWED}
        self.assertEqual(new, {}, "rules naming a DOI prefix: write them for any DOI (10\\.\\d{4,9}/), "
                                  "or list one in ALLOWED with why it may name it: "
                                  + "; ".join(f"{file}:{lines} {prefix}" for (file, prefix), lines in sorted(new.items())))

    def test_the_list_holds_no_rule_that_is_gone(self):
        self.assertEqual(sorted(set(ALLOWED) - set(prefix_rules())), [])

    def test_a_prefix_in_a_rule_is_found(self):
        tree = ast.parse('A = re.compile(r"/doi/(?:full/)?10\\.1177/")\nB = "10.1055/"\nC = r"10\\.\\d{4,9}/"\n')
        found = [m.group(1) for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
                 for m in _PREFIX.finditer(node.value)]
        self.assertEqual(sorted(found), ["1055", "1177"])


if __name__ == "__main__":
    unittest.main()
