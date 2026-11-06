"""Offline failure packet export. Never opens a browser or modifies evidence."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .report_sanitizer import MAX_HTML_BYTES, Redactor, sanitize_html

MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_PAPERS = 100


class ExportError(ValueError):
    """Stable public error code; never includes original contents/paths."""


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ExportError('missing_or_unsafe_file')
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ExportError('file_size_limit')
    return data


def _artifact(root: Path, raw: str, limit: int) -> bytes:
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    # No symlinks or traversal out of the diagnostic directory. We never glob
    # a download directory (which can contain PDFs, cookies and profiles).
    try:
        relative = path.absolute().relative_to(root.absolute())
        if '..' in relative.parts:
            raise ValueError()
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError()
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ExportError('unsafe_artifact_path') from None
    return _read(path, limit)


def _load_record(row: dict) -> tuple[dict, Path | None, str | None]:
    source = row.get('diagnostic') or row.get('record')
    if not isinstance(source, str) or not source:
        return row.get('detail') or {}, None, 'diagnostic_missing; ledger_only'
    path = Path(source)
    try:
        data = json.loads(_read(path, MAX_JSON_BYTES))
        if not isinstance(data, dict) or str(data.get('doi') or data.get('raw_doi') or '').lower() != row['doi'].lower():
            raise ExportError('diagnostic_identity_mismatch')
        if any(key in data and not isinstance(data[key], list) for key in ('events', 'snapshots', 'pages')):
            raise ExportError('invalid_diagnostic_shape')
        return data, path.parent, None
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ExportError) else 'diagnostic_unreadable'
        return row.get('detail') or {}, None, reason + '; ledger_only'


def export_report(request: dict, output: Path, config: dict | None = None) -> dict:
    if request.get('schemaVersion') != 1 or not isinstance(request.get('papers'), list):
        raise ExportError('invalid_export_request')
    rows = request['papers']
    if not rows:
        raise ExportError('no_matching_failures')
    if len(rows) > MAX_PAPERS:
        raise ExportError('too_many_failures; select_a_run_or_doi; limit=100')
    if any(not isinstance(row, dict) or not isinstance(row.get('doi'), str)
           or ('detail' in row and not isinstance(row['detail'], dict)) for row in rows):
        raise ExportError('invalid_export_request')
    if output.suffix.lower() != '.zip':
        raise ExportError('export_path_must_end_in_zip')
    if output.exists() or output.is_symlink():
        raise ExportError('export_target_exists')
    redactor = Redactor(config)
    loaded = []
    total_input = 0
    for row in rows:
        data, root, problem = _load_record(row)
        total_input += len(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        if total_input > MAX_PACKAGE_BYTES:
            raise ExportError('source_size_limit; select_a_run_or_doi')
        loaded.append((row, data, root, problem))
        redactor.observe(row)
        redactor.observe(data)
    manifest = {
        'schemaVersion': 1, 'createdAt': datetime.now(timezone.utc).isoformat(),
        'version': redactor.text(str(request.get('version') or 'unknown')),
        'exportSystem': platform.system(),
        'reviewRequired': True, 'papers': [], 'files': [],
        'limits': {'papers': MAX_PAPERS, 'htmlBytes': MAX_HTML_BYTES,
                   'imageBytes': MAX_IMAGE_BYTES, 'packageBytes': MAX_PACKAGE_BYTES},
    }
    output = output.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.papersearch-report-', suffix='.zip', dir=output.parent)
    os.close(fd)
    total = 0
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            def add(name: str, content: bytes) -> None:
                nonlocal total
                total += len(content)
                if total > MAX_PACKAGE_BYTES:
                    raise ExportError('package_size_limit; select_a_run_or_doi')
                archive.writestr(name, content)
                manifest['files'].append({'path': name, 'bytes': len(content),
                                          'sha256': hashlib.sha256(content).hexdigest()})

            for i, (row, data, root, problem) in enumerate(loaded, 1):
                folder = f'papers/{i:03d}'  # no DOI/path/user content in archive paths
                paper = redactor.clean({k: row.get(k) for k in
                                       ('doi', 'runId', 'publisher', 'failureClass', 'code', 'part', 'stoppedAt', 'evidence')})
                paper.update(folder=folder, materials=[], omitted=[])
                if not paper.get('stoppedAt'):
                    steps = [e for e in data.get('events', []) if isinstance(e, dict) and e.get('state')
                             and e['state'] not in {'snapshot', 'wait', 'publisher_session_saved'}]
                    paper['stoppedAt'] = redactor.text(str(steps[-1]['state'] if steps else data.get('state') or row.get('code') or 'unknown'))
                paper['finalUrl'] = redactor.text(str(data.get('final_url') or data.get('article_url') or 'unknown'))
                paper['captureSystem'] = redactor.clean(data.get('capture_system') or 'unknown (legacy record)')
                paper['captureVersion'] = redactor.clean(data.get('capture_version') or 'unknown (legacy record)')
                if problem:
                    paper['omitted'].append(problem)
                clean = redactor.clean(data)
                add(folder + '/diagnostic.json', _json(clean))
                # Ledger provides the caller's attachment outcome even when the
                # backend's original record pre-dates the supplementary step.
                add(folder + '/outcome.json', _json(redactor.clean(row.get('outcome') or {})))
                pages = [p for key in ('snapshots', 'pages') for p in (data.get(key) or []) if isinstance(p, dict)]
                if len(pages) > 8:
                    paper['omitted'].append('page_count_limit')
                for number, page in enumerate(pages[:8], 1):
                    for kind, limit, suffix in (('html', MAX_HTML_BYTES, '.html'), ('screenshot', MAX_IMAGE_BYTES, '.png')):
                        source = page.get(kind)
                        if not source or root is None:
                            if page.get(kind + '_omitted'):
                                paper['omitted'].append(f'page{number}/{kind}: capture_unavailable')
                            continue
                        if kind == 'screenshot':
                            if (page.get('screenshot_masked') is not True or page.get('screenshot_private') is True
                                    or page.get('html_omitted') or redactor.private_page(
                                str(page.get('url') or ''), str(page.get('title') or ''), str(page.get('why') or '')
                            )):
                                paper['omitted'].append(f'page{number}/screenshot: login_school_or_unverified_origin')
                                continue
                        try:
                            content = _artifact(root, str(source), limit)
                            if kind == 'html':
                                content, truncated = sanitize_html(content.decode('utf-8'), redactor)
                                content = content.encode('utf-8')
                                if truncated or page.get('html_truncated'):
                                    paper['omitted'].append(f'page{number}/html: truncated')
                            else:
                                if content.startswith(b'\x89PNG\r\n\x1a\n'):
                                    suffix = '.png'
                                elif content.startswith(b'\xff\xd8\xff'):
                                    suffix = '.jpg'
                                else:
                                    raise ExportError('invalid_image')
                            name = f'{folder}/pages/{number:02d}{suffix}'
                            add(name, content)
                            paper['materials'].append({'path': name, 'kind': kind,
                                                       'url': redactor.text(str(page.get('url') or '')),
                                                       'why': redactor.text(str(page.get('why') or ''))})
                        except (OSError, ValueError, UnicodeError) as exc:
                            if isinstance(exc, ExportError) and str(exc).startswith('package_size_limit'):
                                raise
                            code = str(exc) if isinstance(exc, ExportError) else 'artifact_unreadable'
                            paper['omitted'].append(f'page{number}/{kind}: {code}')
                if not any(p['kind'] == 'html' for p in paper['materials']):
                    paper['omitted'].append('html_unavailable; original_page_cannot_be_reconstructed')
                if not any(p['kind'] == 'screenshot' for p in paper['materials']):
                    paper['omitted'].append('screenshots_unavailable_or_excluded')
                manifest['papers'].append(paper)
            add('summary.md', _summary(manifest).encode('utf-8'))
            manifest_bytes = _json(manifest)
            if total + len(manifest_bytes) > MAX_PACKAGE_BYTES:
                raise ExportError('package_size_limit; select_a_run_or_doi')
            archive.writestr('manifest.json', manifest_bytes)
        # Exclusive final publication: a racing export cannot overwrite another
        # report. Temporary file is on the same filesystem on Windows and Unix.
        os.link(temp, output)
    finally:
        Path(temp).unlink(missing_ok=True)
    return {'ok': True, 'schemaVersion': 1, 'path': str(output), 'papers': len(rows),
            'files': len(manifest['files']) + 1, 'bytes': output.stat().st_size,
            'reviewRequired': True,
            'incompletePapers': sum(bool(p['omitted']) for p in manifest['papers'])}


def _json(data) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')


def _summary(manifest: dict) -> str:
    # Keep site text from becoming active Markdown/HTML or injected issue UI.
    def plain(value) -> str:
        text = str(value or 'unknown').replace('\n', ' ').replace('\r', ' ').replace('<', '&lt;').replace('>', '&gt;').replace('`', "'")
        return re.sub(r'([\\*_{}\[\]()#+!|])', r'\\\1', text)

    lines = ['# PaperSearch 下载失败记录', '',
             f"导出版本：{plain(manifest['version'])}；导出系统：{plain(manifest['exportSystem'])}", '',
             '## 公开前请核对', '',
             '- [ ] 检查所有 HTML、诊断文本和截图中的姓名、邮箱、学号、学校标识及其他个人信息。',
             '- [ ] 检查图片；字符串脱敏不能保证移除图片像素中的个人信息。',
             '- [ ] 确认只分享这个导出包，不附原始 diagnostics、浏览器 profile、Cookie 或下载正文。',
             '', 'HTML 为不可执行结构快照，href/action 记录为 data-href/data-action；只保留有限文本片段。',
             '旧记录缺失的材料不会补造；导出不会重跑下载。', '']
    for p in manifest['papers']:
        lines.extend([f"## {plain(p['doi'])}", '',
                      f"- 出版社：{plain(p['publisher'])}",
                      f"- 失败部分：{plain(p.get('part') or 'main')}；分类：{plain(p['failureClass'])}；原因：{plain(p['code'])}",
                      f"- 停止步骤：{plain(p['stoppedAt'])}",
                      f"- 最后网址：`{plain(p['finalUrl'])}`",
                      f"- 采集版本 / 系统：{plain(p['captureVersion'])} / {plain(p['captureSystem'])}",
                      f"- 材料目录：{p['folder']}"])
        if p.get('evidence'):
            lines.append(f"- 依据：{plain(p['evidence'])}")
        for material in p['materials']:
            lines.append(f"- 检查文件：{material['path']}")
        for omission in p['omitted']:
            lines.append(f"- 材料缺项或限制：{plain(omission)}")
        lines.append('')
    return '\n'.join(lines)
