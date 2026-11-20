"""A report on the pages from sites not yet supported (user, 2026-11-16), for the maintainers
to list the site or write its rules from, and the issue it goes with: the pages whose Markdown
was not kept, and those another site's rules converted completely and saved (user,
2026-11-17: one report and one button; it says per site whether existing rules converted it,
so the site needs listing only, or new rules are wanted).

PaperSearch keeps each such page with its check results in the run's records
(``<DOI>_markdown-page.html``, ``<DOI>_markdown-report.json``, the closest rules' Markdown
``<DOI>_markdown-attempt.md``). The export is a ZIP in the batch's folder, to look over and
drag into the issue; nothing is uploaded. For each paper it holds what a maintainer needs
to write the site's rules (user, 2026-11-17: a structural specimen said too little): the
whole page (``page.html``), the closest rules' Markdown (``attempt.md``), and in
``checks.json`` and ``summary.md`` the page's own facts (its publisher, platform, the
element holding the text, its headings, figures, tables, formulas) and what each rule
made of it. Only what is private is taken out (``redact_page``): school names, home paths,
e-mail addresses, login and session parameters in addresses, and hidden form values,
CSRF and session tokens. Images are left out. The issue's link carries the site, the
version and the counts, never a DOI or a title.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from .report_sanitizer import Redactor

REPO = "https://github.com/dr-dumpling/PaperSearch"
MAX_PAPERS = 100
MAX_JSON_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
REPORT_SUFFIX = "_markdown-report.json"
PAGE_SUFFIX = "_markdown-page.html"
ATTEMPT_SUFFIX = "_markdown-attempt.md"
MAX_PAGE_BYTES = 16 * 1024 * 1024
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}\.)+[a-z]{2,63}")
# Why the closest rules were tried: the page's publisher's, its platform's, or the rest.
GROUNDS = {"publisher": "按出版社", "platform": "按网站平台", "other": "按其他出版社的规则"}
# What the closest rules lacked, in the words of the window's notes.
LACKS = {"references": "参考文献不全", "figures": "图片不全", "tables": "表格没取到", "text": "正文不全"}


class ReportError(ValueError):
    """A stable code; never the contents or paths it came from."""


def paper_search_version() -> str:
    """PaperSearch's version: as PaperSearch passes it to the backend (PAPER_SEARCH_VERSION),
    else as its install record says (the backend runs in the venv beside it); "" else."""
    given = os.environ.get("PAPER_SEARCH_VERSION", "")
    if re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?", given):
        return given
    try:
        record = json.loads((Path(sys.prefix).parent / "install.json").read_text(encoding="utf-8"))
        version = str(record.get("paperSearchVersion") or "")
        return version if re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?", version) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def support_doc(version: str) -> str:
    """The publisher support table (its Markdown column lists the sites with rules), on the
    branch of this version (a preview's sites are on the preview branch)."""
    branch = "preview" if "-preview" in version else "main"
    return f"{REPO}/blob/{branch}/skills/paper-search/references/publisher-support.md"


def _read_report(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not path.name.endswith(REPORT_SUFFIX):
        raise ReportError("missing_or_unsafe_file")
    with path.open("rb") as handle:
        raw = handle.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ReportError("file_size_limit")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schemaVersion") != 1 or not isinstance(data.get("host"), str):
        raise ReportError("invalid_report")
    return data


def _page_of(report: Path, suffix: str = PAGE_SUFFIX) -> Path | None:
    """The page (or the attempted Markdown) kept beside the report, and only that file."""
    page = report.with_name(report.name[: -len(REPORT_SUFFIX)] + suffix)
    return page if page.is_file() and not page.is_symlink() else None


_URL = re.compile(r'https?://[^\s<>"\'\\)]+', re.I)
_HIDDEN = re.compile(r'(<input\b[^>]*\btype\s*=\s*["\']?hidden["\']?[^>]*?\bvalue\s*=\s*)("[^"]*"|\'[^\']*\'|[^\s>]+)', re.I)
_HIDDEN_FIRST = re.compile(r'(<input\b[^>]*?\bvalue\s*=\s*)("[^"]*"|\'[^\']*\'|[^\s>]+)([^>]*\btype\s*=\s*["\']?hidden)', re.I)
_TOKEN_META = re.compile(r'(<meta\b[^>]*\bname\s*=\s*["\'][^"\']*(?:csrf|token|session|nonce)[^"\']*["\'][^>]*\bcontent\s*=\s*)("[^"]*"|\'[^\']*\')', re.I)
# A secret-named assignment: a name starting a word, at most 40 characters around the secret
# word (unbounded, a page's 100 000-character run of letters took minutes, 2026-11-17).
_ASSIGNED = re.compile(r'((?<![\w-])["\']?(?:[\w-]{0,40}?(?:token|session|csrf|nonce|secret|password|passwd|ticket|signature|api_?key|authorization|bearer)[\w-]{0,40})["\']?\s*[:=]\s*)("[^"\n]{4,}"|\'[^\'\n]{4,}\')', re.I)
_EMAIL = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)


def page_address(url: str, redactor: Redactor) -> str:
    """A publisher's address with its whole path (a title's slug is not a token) and only
    the safe query parameters; ``;jsessionid=…`` path parameters go. A school's address is
    taken out whole (``Redactor.url``)."""
    cleaned = redactor.url(url)
    if redactor.school_url(url):
        return cleaned
    try:
        parts, kept = urlsplit(url), urlsplit(cleaned)
    except ValueError:
        return cleaned
    if not kept.netloc:
        return cleaned
    return urlunsplit((kept.scheme, kept.netloc, re.sub(r";[^/]*", "", parts.path), kept.query, ""))


def redact_page(text: str, redactor: Redactor) -> str:
    """The whole page (or Markdown) with only what is private taken out: addresses lose
    their login and session parameters (``Redactor.url``), hidden form values and token
    tags their values, secret-named assignments in scripts their strings, and e-mail
    addresses, home paths and the school's names go. Nothing else changes."""
    text = _HIDDEN.sub(lambda m: m.group(1) + '""', text)
    text = _HIDDEN_FIRST.sub(lambda m: m.group(1) + '""' + m.group(3), text)
    text = _TOKEN_META.sub(lambda m: m.group(1) + '""', text)
    text = _ASSIGNED.sub(lambda m: m.group(1) + '"[SECRET_REMOVED]"', text)
    text = _URL.sub(lambda m: page_address(m.group(), redactor) if "?" in m.group() or ";" in m.group() or redactor.school_url(m.group())
                    else m.group(), text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = text.replace(redactor.home, "~")
    text = re.sub(r'(?i)(?:[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]|/(?:Users|home)/)[^/\\\s"\'<>]+', "~", text)
    return redactor._terms(text)


# A page not converted for another reason than a shortfall (the report's code).
REASONS = {"abstract_only": "只读到摘要", "page_not_entitled": "网页显示没有权限"}


def lacks_of(data: dict[str, Any]) -> list[str]:
    if data.get("status") == "ok":
        return []
    if data.get("code") in REASONS:
        return [REASONS[data["code"]]]
    shortfall = data.get("shortfall") if isinstance(data.get("shortfall"), dict) else {}
    lacks = [label for key, label in LACKS.items() if shortfall.get(key)]
    return lacks or ["没有规则能读出正文" if not data.get("template") else "核对没通过"]


def collect(entries: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any], Path]]:
    """Each entry's report (``report``: its absolute path; ``doi``, ``title``), read and
    checked: the DOI it names is the entry's."""
    loaded = []
    for entry in entries:
        raw = entry.get("report") if isinstance(entry, dict) else None
        if not isinstance(raw, str) or not os.path.isabs(raw):
            continue
        path = Path(raw)
        try:
            data = _read_report(path)
        except (OSError, ValueError):
            continue
        if str(data.get("doi") or "").lower() != str(entry.get("doi") or data.get("doi") or "").lower():
            continue
        loaded.append((entry, data, path))
    return loaded


def export(entries: list[dict[str, Any]], folder: Path, config: dict | None = None, version: str = "",
           now: datetime | None = None, output: Path | None = None) -> dict[str, Any]:
    """The ZIP ``PaperSearch-Markdown报告-<date>.zip`` in ``folder`` (or ``output``, a new
    .zip); its path, counts and the issue's link (``issueUrl``)."""
    loaded = collect(entries)
    if not loaded:
        raise ReportError("no_reports")
    if len(loaded) > MAX_PAPERS:
        loaded = loaded[:MAX_PAPERS]
    now = now or datetime.now()
    if output is not None:
        output = output.expanduser().absolute()
        if output.suffix.lower() != ".zip":
            raise ReportError("export_path_must_end_in_zip")
        if output.exists() or output.is_symlink():
            raise ReportError("export_target_exists")
        folder = output.parent
    folder = folder.expanduser().absolute()
    folder.mkdir(parents=True, exist_ok=True)
    if output is None:
        stem = f"PaperSearch-Markdown报告-{now.strftime('%Y%m%d-%H%M')}"
        output = folder / f"{stem}.zip"
        for n in range(2, 100):
            if not output.exists():
                break
            output = folder / f"{stem}-{n}.zip"
    redactor = Redactor(config)
    for entry, data, _ in loaded:
        redactor.observe(entry)
        redactor.observe(data)
    manifest: dict[str, Any] = {
        "schemaVersion": 1, "createdAt": datetime.now(timezone.utc).isoformat(),
        "version": version or "unknown", "system": platform.system(), "reviewRequired": True,
        "papers": [], "files": [],
    }
    fd, temp = tempfile.mkstemp(prefix=".papersearch-markdown-", suffix=".zip", dir=folder)
    os.close(fd)
    total = 0
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            def add(name: str, content: bytes) -> None:
                nonlocal total
                total += len(content)
                if total > MAX_PACKAGE_BYTES:
                    raise ReportError("package_size_limit")
                archive.writestr(name, content)
                manifest["files"].append({"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})

            for i, (entry, data, path) in enumerate(loaded, 1):
                at = f"papers/{i:03d}"  # no DOI or title in the archive's paths
                host = data["host"] if _HOST.fullmatch(data["host"]) else "unknown"
                checks = data.get("checks") if isinstance(data.get("checks"), dict) else {}
                facts = checks.get("page") if isinstance(checks.get("page"), dict) else {}
                paper = {
                    "folder": at, "doi": redactor.text(str(data.get("doi") or "")),
                    # A batch of the Markdown alone looked up no title: the page's own.
                    "title": redactor.text(str(entry.get("title") or facts.get("title") or "")), "site": host,
                    "page": redactor.clean(facts), "tried": redactor.clean(checks.get("tried") or []),
                    "rules": redactor.text(str(data.get("template") or "")), "rulesName": redactor.text(str(data.get("rules") or "")),
                    "saved": data.get("status") == "ok", "url": page_address(str(data.get("url") or ""), redactor),
                    "ground": " ".join(filter(None, [GROUNDS.get(str(data.get("matchedBy") or ""), ""),
                                                    redactor.text(str(data.get("basis") or ""))])),
                    "lacks": lacks_of(data), "omitted": [],
                }
                add(f"{at}/checks.json", _json(redactor.clean({
                    key: data.get(key) for key in ("host", "template", "rules", "matchedBy", "basis", "status", "code", "shortfall", "checks",
                                                   "images", "message")})))
                page = _page_of(path)
                if page is None:
                    paper["omitted"].append("page_missing")
                else:
                    with page.open("rb") as handle:
                        source = handle.read(MAX_PAGE_BYTES + 1)
                    if len(source) > MAX_PAGE_BYTES:
                        paper["omitted"].append("page_cut_at_16_MiB")
                    add(f"{at}/page.html", redact_page(source[:MAX_PAGE_BYTES].decode("utf-8", "replace"), redactor).encode("utf-8"))
                attempt = _page_of(path, ATTEMPT_SUFFIX)
                paper["attempt"] = attempt is not None
                if attempt is not None:
                    with attempt.open("rb") as handle:
                        add(f"{at}/attempt.md", redact_page(handle.read(MAX_PAGE_BYTES).decode("utf-8", "replace"), redactor).encode("utf-8"))
                manifest["papers"].append(paper)
            add("summary.md", _summary(manifest).encode("utf-8"))
            archive.writestr("manifest.json", _json(manifest))
        os.link(temp, output)  # never over another report
    finally:
        Path(temp).unlink(missing_ok=True)
    # The issue from the reports alone (the pages a batch gave up have none).
    sites: dict[str, dict[str, Any]] = {}
    for _, data, _ in loaded:
        if _HOST.fullmatch(data["host"]):
            site = sites.setdefault(data["host"], {"host": data["host"], "saved": 0, "unsaved": 0, "skipped": 0, "lacks": {}, "rules": {}})
            _count(site, data.get("status") == "ok", str(data.get("rules") or ""), lacks_of(data))
    return {"ok": True, "path": str(output), "name": output.name, "papers": len(loaded),
            "sites": sorted(sites), "bytes": output.stat().st_size,
            "issueUrl": issue_url(sorted(sites.values(), key=lambda s: -(s["saved"] + s["unsaved"])), version)}


def _count(site: dict[str, Any], saved: bool, rules: str, lacks: list[str]) -> None:
    """One page in its site's tally: saved or not, whose rules, what it lacked."""
    site["saved" if saved else "unsaved"] += 1
    if rules:
        site["rules"][rules] = site["rules"].get(rules, 0) + 1
    for label in lacks:
        site["lacks"][label] = site["lacks"].get(label, 0) + 1


def _rules_said(tally: dict[str, int]) -> str:
    """"Atypon" or "Atypon / Silverchair", most papers first."""
    return " / ".join(name for name, _ in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])))


def _json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _plain(value: Any) -> str:
    text = str(value or "—").replace("\n", " ").replace("\r", " ").replace("<", "&lt;").replace(">", "&gt;").replace("`", "'")
    return re.sub(r"([\\*_{}\[\]()#+!|])", r"\\\1", text)


LAYER_NAMES = {"publisher": "出版社", "platform": "网站平台", "other": "其余规则"}
RESULT_NAMES = {"unrecognized": "认不出这种页面", "denied": "判为没有权限", "abstract": "只读到摘要",
                "incomplete": "不完整", "passed": "通过"}
LACK_NAMES = {"figures": "少 {} 张图", "references": "参考文献少 {} 条", "text": "正文缺约 {}%", "tables": "缺表"}


def _shortfall(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return "，".join(LACK_NAMES[key].format(n) for key, n in value.items() if key in LACK_NAMES and n)


def _paper_lines(paper: dict[str, Any]) -> list[str]:
    """What a maintainer reads first of a page: its facts, then what each rule made of it."""
    facts = paper.get("page") if isinstance(paper.get("page"), dict) else {}
    lines = [f"### {_plain(paper['doi'])} · {_plain(paper['title'])}", "",
             f"- 网址：{_plain(paper['url'])}",
             f"- 网页写的出版社：{_plain(facts.get('publisher') or '没写')}；期刊：{_plain(facts.get('journal') or '没写')}；"
             f"网站平台：{_plain('、'.join(facts.get('platforms') or []) or '没认出')}"]
    if facts:
        lines.append(f"- 正文所在元素：`{str(facts.get('container') or '没找到').replace('`', '')}`；段落 {facts.get('paragraphs', 0)} 段"
                     f"（{facts.get('paragraphChars', 0)} 字）；标题 {len(facts.get('headings') or [])} 个；"
                     f"图 {facts.get('figures', 0)}、图片 {facts.get('images', 0)}、表 {facts.get('tables', 0)}、公式 {facts.get('formulas', 0)}；"
                     f"citation_reference {facts.get('citationReferences', 0)} 条")
    tried = [t for t in paper.get("tried") or [] if isinstance(t, dict)]
    if tried:
        lines.append("- 试过的规则：")
        for layer in ("publisher", "platform", "other"):
            rules = [t for t in tried if t.get("layer") == layer]
            if not rules:
                continue
            # The publisher's and the platform's few rules each by name; of the rest, those that read something.
            shown = rules if layer != "other" else [t for t in rules if t.get("result") != "unrecognized"]
            unread = len(rules) - len(shown)
            parts = [f"{t.get('template')} {RESULT_NAMES.get(str(t.get('result')), t.get('result'))}"
                     + (f"（{_shortfall(t.get('shortfall'))}）" if _shortfall(t.get("shortfall")) else "") for t in shown]
            if unread:
                parts.append(f"另 {unread} 套认不出这种页面" if shown else f"{unread} 套都认不出这种页面")
            lines.append(f"  - {LAYER_NAMES[layer]}：" + "；".join(parts))
    rules = paper["rules"] + (f"（{paper['ground']}）" if paper.get("ground") else "")
    if paper.get("saved"):
        lines.append(f"- 结果：完整转换，已保存；用的规则：{_plain(rules)}")
    else:
        lines.append(f"- 结果：{_plain('、'.join(paper['lacks']))}" + (f"；最接近的规则：{_plain(rules)}" if paper["rules"] else ""))
    made = "转出并保存的 Markdown" if paper.get("saved") else "最接近的规则转出的 Markdown"
    lines += [f"- 材料：{paper['folder']}/（page.html 完整网页" + (f"、attempt.md {made}" if paper.get("attempt") else "")
              + "、checks.json 全部核对结果）", ""]
    return lines


def _verdict(papers: list[dict[str, Any]]) -> str:
    """What a site needs, from its pages: listing (existing rules converted them), the rules
    put right, or new rules (user, 2026-11-17)."""
    saved = [p for p in papers if p.get("saved")]
    unsaved = [p for p in papers if not p.get("saved")]
    names = _rules_said({name: sum(1 for p in saved if (p.get("rulesName") or p["rules"]) == name)
                         for name in {p.get("rulesName") or p["rules"] for p in saved}})
    templates = "、".join(sorted({f"`{p['rules']}`" for p in saved if p["rules"]}))
    if saved and not unsaved:
        return (f"结论：现有规则能完整转换（采用 {_plain(names)} 规则，模板 {templates}，{len(saved)} 篇都转全）。"
                "核对后加登记文件即可，不用写新规则。")
    closest = {p["rules"] for p in unsaved if p["rules"]}
    if saved:
        return (f"结论：采用 {_plain(names)} 规则转全了 {len(saved)} 篇，另 {len(unsaved)} 篇没转全。"
                "先看没转全的缺什么，多半是这套规则要改；改好、核对后加登记文件。")
    if closest:
        return (f"结论：没有规则能完整转换；最接近的是 {'、'.join(f'`{t}`' for t in sorted(closest))}。"
                "看缺什么：差得少就改这套规则，差得多就为这个网站新写一套。")
    return "结论：没有一套规则能读出正文，要为这个网站新写一套规则。"


def _summary(manifest: dict[str, Any]) -> str:
    by_site: dict[str, list[dict[str, Any]]] = {}
    for paper in manifest["papers"]:
        by_site.setdefault(paper["site"], []).append(paper)
    lines = ["# PaperSearch Markdown 报告", "",
             f"版本：{_plain(manifest['version'])}；系统：{_plain(manifest['system'])}", "",
             "这些网站还没有登记 Markdown 规则。下面的文章按各层规则试转（先按出版社，再按网站平台，最后其余规则），"
             "核对图片、表格、参考文献和正文都齐才保存。每个网站开头的“结论”说明它需要什么：现有规则能完整转换的，登记即可；"
             "转不全或读不出正文的，要改规则或新写一套。", "",
             "## 公开前请核对", "",
             "- [ ] 打开各篇的 page.html、attempt.md 和 checks.json，确认没有姓名、邮箱、学号、学校标识或其他个人信息。",
             "- [ ] page.html 是完整网页（含论文正文），公开前确认可以分享；不附 PDF、Cookie 或浏览器数据。", "",
             "page.html 已去掉学校名、本机路径、邮箱、网址里的登录和会话参数、隐藏表单和令牌的值，其余是网页原样；图片没有放进来。", ""]
    for site, papers in sorted(by_site.items(), key=lambda kv: -len(kv[1])):
        lines += [f"## {_plain(site)}（{len(papers)} 篇）", "", _verdict(papers), ""]
        for paper in papers:
            lines += _paper_lines(paper)
    return "\n".join(lines)


def issue_url(sites: list[dict[str, Any]], version: str) -> str:
    """GitHub's new issue with the Markdown site template, filled in: the sites, the
    version, the system, the counts and what was missing; no DOI, no title."""
    names = [s["host"] for s in sites if _HOST.fullmatch(str(s.get("host") or ""))][:10]
    results = [f"{s['host']}：" + (f"采用 {_rules_said(s['rules'])} 规则；" if s.get("rules") else "")
               + f"已尝试 {s['saved'] + s['unsaved']} 篇，{s['saved']} 篇完整已保存，{s['unsaved']} 篇不完整未保存"
               + (f"，{s['skipped']} 篇未再尝试" if s.get("skipped") else "") for s in sites if s.get("host") in names]
    lacks = [f"{s['host']}：" + "、".join(f"{label} {n} 篇" for label, n in s.get("lacks", {}).items())
             for s in sites if s.get("host") in names and s.get("lacks")]
    fields = {
        "template": "markdown-site.yml",
        "title": "[Markdown] " + "、".join(names),
        "site": "、".join(names),
        "version": version,
        "system": f"{platform.system()} {platform.release()}".strip(),
        "result": "\n".join(results),
        "missing": "\n".join(lacks),
    }
    return f"{REPO}/issues/new?" + urlencode({k: v for k, v in fields.items() if v})


def site_counts(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per site not yet supported, from a batch's papers (papers.json): saved, unsaved,
    skipped, whose rules (``markdown_rules``), and what the unsaved lacked (from their kept
    reports)."""
    sites: dict[str, dict[str, Any]] = {}
    for paper in papers:
        host = str(paper.get("markdown_host") or "")
        if not _HOST.fullmatch(host):
            continue
        site = sites.setdefault(host, {"host": host, "saved": 0, "unsaved": 0, "skipped": 0, "lacks": {}, "rules": {}})
        if paper.get("markdown_skipped") and not paper.get("markdown_saved"):
            site["skipped"] += 1
            continue
        lacks: list[str] = []
        report = paper.get("markdown_report")
        if not paper.get("markdown_saved"):
            try:
                lacks = lacks_of(_read_report(Path(report))) if isinstance(report, str) and os.path.isabs(report) else []
            except (OSError, ValueError):
                lacks = []
        _count(site, bool(paper.get("markdown_saved")), str(paper.get("markdown_rules") or ""), lacks)
    return sorted(sites.values(), key=lambda s: -(s["saved"] + s["unsaved"] + s["skipped"]))
