"""Offline evidence export: secrets, bounded specimens and unchanged originals."""
import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_search_carsi.failure_export import ExportError, export_report
from paper_search_carsi.report_sanitizer import Redactor, sanitize_html, MAX_HTML_BYTES
from paper_search_carsi.page_snapshot import capture_structure

CONFIG = {'carsi_idp_name': '红木兰大学', 'carsi_idp_name_en': 'Hong Mu-lan University',
          'idp_entity_id': 'https://idp.hongmulan.example/idp/shibboleth'}
DOI = '10.1234/fixture'


def packet(tmp_path, data=None):
    folder = tmp_path / 'original'
    folder.mkdir(exist_ok=True)
    diagnostic = folder / 'diagnostic.json'
    data = data or {'doi': DOI, 'state': 'generic_institution_entry_missing',
                    'final_url': 'https://publisher.example/article/123?token=secret1',
                    'events': [{'state': 'login_entry_missing', 'detail': 'a.institution'}]}
    diagnostic.write_text(json.dumps(data), encoding='utf-8')
    return {'schemaVersion': 1, 'version': '0.4.7', 'papers': [
        {'doi': DOI, 'diagnostic': str(diagnostic), 'publisher': 'Fixture',
         'failureClass': 'unsupported', 'code': 'generic_institution_entry_missing',
         'runId': 'fixture', 'stoppedAt': 'login_entry_missing', 'detail': {},
         'outcome': {'status': 'error'}}]}, diagnostic


def unzip(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_structure_is_inert_and_keeps_selector_evidence():
    source = '''<html><body><script>Cookie=secret</script><iframe src="https://evil.example"></iframe>
    <form action="https://idp.hongmulan.example/login?SAMLRequest=secret2">
    <input type="hidden" value="secret3"><input name="username" value="person">
    <textarea>private</textarea><select><option selected>private</option></select></form>
    <a class="pdf" href="https://publisher.example/pdf/1?token=secret4" onclick="fetch('x')">Download PDF</a>
    <p>红木兰大学 Hong Mu-lan University</p><img src="https://evil.example" onerror="bad()"></body></html>'''
    content, _ = sanitize_html(source, Redactor(CONFIG))
    for word in ('secret', 'Cookie', 'SAMLRequest', 'private', 'person', 'onclick', 'onerror', 'src=', '红木兰', 'hongmulan.example'):
        assert word not in content
    assert 'class="pdf"' in content
    assert 'data-href="https://publisher.example/pdf/1"' in content
    assert 'Download PDF' in content
    assert "default-src 'none'" in content


def test_urls_nested_encoding_headers_and_personal_paths():
    redactor = Redactor(CONFIG)
    text = '''https://publisher.example/article/2?doi=10.1234%2Fx&token=secret5&return=https%253A%252F%252Fidp.hongmulan.example%252Flogin%253Fticket%253Dsecret6#code=secret7
Cookie: SID=one; tracking=two
Authorization: Bearer three
SAMLResponse="secret8" /Users/example-user/test C:\\Users\\example-user\\stuff a.person@example.edu'''
    clean = redactor.text(text)
    for value in ('secret', 'SAMLResponse', 'ticket=', 'token=', 'Cookie', 'one', 'two', 'three', 'example-user', 'a.person', 'hongmulan.example'):
        assert value not in clean
    assert 'https://publisher.example/article/2?doi=10.1234%2Fx' in clean
    assert '~' in clean


def test_export_does_not_change_original_and_lists_materials(tmp_path):
    request, diagnostic = packet(tmp_path)
    page = diagnostic.parent / 'page.html'
    page.write_text('<a class="institution" href="/institution?ticket=secret9">Institutional access</a>')
    image = diagnostic.parent / 'page.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
    data = json.loads(diagnostic.read_text())
    data['pages'] = [{'html': str(page), 'screenshot': str(image), 'screenshot_masked': True,
                      'url': data['final_url'], 'why': 'entry missing'}]
    data['full_text'] = 'entire article must not be exported'
    data['headers'] = {'Cookie': 'secret10'}
    diagnostic.write_text(json.dumps(data))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (diagnostic, page, image)}
    output = tmp_path / 'report.zip'
    result = export_report(request, output, CONFIG)
    files = unzip(output)
    assert result['papers'] == 1 and result['reviewRequired'] is True
    assert result['incompletePapers'] == 0
    assert 'papers/001/pages/01.html' in files
    assert 'papers/001/pages/01.png' in files
    assert b'entire article' not in b''.join(files.values())
    assert b'secret' not in b''.join(files.values())
    assert b'Institutional access' in files['papers/001/pages/01.html']
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    assert r'login\_entry\_missing' in files['summary.md'].decode()
    assert json.loads(files['manifest.json'])['papers'][0]['stoppedAt'] == 'login_entry_missing'
    assert all(not name.startswith('/') and '..' not in name.split('/') for name in files)


@pytest.mark.parametrize('url,title,masked', [
    ('https://idp.hongmulan.example/page', '', True),
    ('https://publisher.example/login', '', True),
    ('https://publisher.example/article', 'Sign in', True),
    ('', '', True),
    ('https://publisher.example/article', '', False),
])
def test_private_or_legacy_screenshots_are_excluded(tmp_path, url, title, masked):
    request, diagnostic = packet(tmp_path)
    image = diagnostic.parent / 'page.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\nprivate image')
    data = json.loads(diagnostic.read_text())
    data['snapshots'] = [{'url': url, 'title': title, 'screenshot': str(image), 'screenshot_masked': masked}]
    diagnostic.write_text(json.dumps(data))
    export_report(request, tmp_path / 'report.zip', CONFIG)
    files = unzip(tmp_path / 'report.zip')
    assert not any(n.endswith('.png') for n in files)
    assert b'html_unavailable' in files['manifest.json']


@pytest.mark.parametrize('kind', ['traversal', 'symlink', 'large', 'missing'])
def test_artifact_boundaries_are_reported_without_copying(tmp_path, kind):
    request, diagnostic = packet(tmp_path)
    outside = tmp_path / 'outside.html'
    outside.write_text('private outside data')
    target = diagnostic.parent / 'page.html'
    source = str(target)
    if kind == 'traversal':
        source = '../outside.html'
    elif kind == 'symlink':
        target.symlink_to(outside)
    elif kind == 'large':
        target.write_bytes(b'X' * (MAX_HTML_BYTES + 1))
    data = json.loads(diagnostic.read_text())
    data['pages'] = [{'html': source, 'url': 'https://publisher.example/article'}]
    diagnostic.write_text(json.dumps(data))
    export_report(request, tmp_path / 'report.zip', CONFIG)
    files = unzip(tmp_path / 'report.zip')
    assert b'private outside data' not in b''.join(files.values())
    assert not any(name.endswith('.html') for name in files)
    assert b'html_unavailable' in files['manifest.json']


def test_legacy_missing_and_identity_mismatch_do_not_fabricate_html(tmp_path):
    request, diagnostic = packet(tmp_path, {'doi': '10.9999/other', 'secret': 'do not export'})
    request['papers'][0]['detail'] = {'events': [{'state': 'login_failed'}]}
    export_report(request, tmp_path / 'report.zip', CONFIG)
    files = unzip(tmp_path / 'report.zip')
    assert b'diagnostic_identity_mismatch' in files['manifest.json']
    assert b'login_failed' in files['papers/001/diagnostic.json']
    assert b'do not export' not in b''.join(files.values())


def test_existing_target_and_empty_selection_are_errors(tmp_path):
    request, _ = packet(tmp_path)
    target = tmp_path / 'report.zip'
    target.write_bytes(b'keep')
    with pytest.raises(ExportError, match='target_exists'):
        export_report(request, target, CONFIG)
    assert target.read_bytes() == b'keep'
    with pytest.raises(ExportError, match='no_matching_failures'):
        export_report({'schemaVersion': 1, 'papers': []}, tmp_path / 'empty.zip')


def test_snapshot_rpc_is_bounded_and_masks_before_write(tmp_path, monkeypatch):
    from paper_search_carsi.browser import watchdog
    monkeypatch.setattr(watchdog, 'fired', None)
    calls = []
    class Locator:
        def evaluate(self, script, limit, timeout):
            calls.append((limit, timeout))
            return {'html': '<input value="private"><script>token=private</script><a href="/pdf">PDF</a>', 'truncated': False}
    page = SimpleNamespace(locator=lambda _: Locator())
    out = capture_structure(page, tmp_path / 'page.html', CONFIG)
    assert out['html']
    assert calls == [(MAX_HTML_BYTES // 2, 3000)]
    assert 'private' not in (tmp_path / 'page.html').read_text()
    monkeypatch.setattr(watchdog, 'fired', True)
    assert capture_structure(page, tmp_path / 'stopped.html')['html_omitted'] == 'browser_stopped'
    assert len(calls) == 1


def test_school_domain_observed_in_events_but_federation_host_preserved():
    redactor = Redactor()
    redactor.observe({'events': [{'state': 'school_login', 'detail': 'https://login.hongmulan.example/auth?ticket=x'},
                                 {'state': 'institution_entry', 'detail': 'https://federation.example/login?code=y'}]})
    clean = redactor.text('https://login.hongmulan.example/auth?ticket=x https://federation.example/login?code=y')
    assert 'hongmulan.example' not in clean
    assert 'federation.example/login' in clean
    assert 'code=' not in clean


def test_selectors_remain_without_form_values_or_active_meta():
    content, _ = sanitize_html('''<meta http-equiv=refresh content="0;url=https://evil.example">
      <select id="institution-picker"><option value="private">private</option></select>
      <textarea id="message">private</textarea><input type value="private"><a href="javascript:bad()">PDF</a>''', Redactor())
    assert '<select id="institution-picker"></select>' in content
    assert '<textarea id="message"></textarea>' in content
    assert 'private' not in content
    assert 'evil.example' not in content
    assert 'javascript:' not in content


def test_known_secret_values_and_historic_usernames_are_removed_everywhere():
    redactor = Redactor(CONFIG)
    evidence = {'headers': {'Authorization': 'fixture-secret-header'}, 'pdf_path': 'C:\\Users\\old-user\\file.pdf',
                'events': [{'detail': 'old-user used fixture-secret-header at https://idp.hongmulan.example/login'}]}
    redactor.observe(evidence)
    clean = json.dumps(redactor.clean(evidence))
    assert 'old-user' not in clean and 'fixture-secret-header' not in clean


def test_inline_login_form_excludes_screenshot_even_on_article_url(tmp_path):
    request, diagnostic = packet(tmp_path)
    image = diagnostic.parent / 'inline.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\nprivate')
    data = json.loads(diagnostic.read_text())
    data['pages'] = [{'url': 'https://publisher.example/article', 'screenshot': str(image),
                      'screenshot_masked': True, 'screenshot_private': True}]
    diagnostic.write_text(json.dumps(data))
    export_report(request, tmp_path / 'report.zip')
    assert not any(n.endswith('.png') for n in unzip(tmp_path / 'report.zip'))


def test_total_package_limit_is_atomic(tmp_path, monkeypatch):
    from paper_search_carsi import failure_export
    request, _ = packet(tmp_path)
    monkeypatch.setattr(failure_export, 'MAX_PACKAGE_BYTES', 1000)
    with pytest.raises(ExportError, match='package_size_limit'):
        export_report(request, tmp_path / 'report.zip')
    assert not (tmp_path / 'report.zip').exists()
    assert not list(tmp_path.glob('.papersearch-report-*'))


@pytest.mark.parametrize('verified,mode,keep', [(False, '', True), (True, '', False), (True, 'with', True)])
def test_page_evidence_waits_for_identity_and_attachment_completion(tmp_path, monkeypatch, verified, mode, keep):
    from paper_search_carsi.engine.batch import PublisherBatchDownloader, DownloadResult, PaperRecord
    from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE
    from paper_search_carsi.engine import pdf_guard, batch
    from paper_search_carsi.browser import preview
    d = PublisherBatchDownloader({'supplements': mode}, profile=ELSEVIER_PROFILE)
    monkeypatch.setattr(pdf_guard, 'names_other_article', lambda *a: [])
    monkeypatch.setattr(batch.pdf_extractor, 'extract_from_bytes', lambda _: DOI)
    monkeypatch.setattr(d, '_text_matches_record', lambda *a, **kw: verified)
    monkeypatch.setattr(d, '_save_publisher_session', lambda *a: None)
    monkeypatch.setattr(preview, 'discard_frames', lambda *a: None)
    html = tmp_path / 'page.html'
    html.write_text('<a>PDF</a>')
    result = DownloadResult(doi=DOI, status='failed', snapshots=[{'html': str(html), 'url': 'https://publisher.example/article'}])
    d._save_captured_pdf(SimpleNamespace(), PaperRecord(doi=DOI), result, tmp_path, b'%PDF-fixture', 'https://publisher.example/article.pdf')
    assert html.exists() is keep
    assert ('html' in result.snapshots[0]) is keep


def test_deeply_encoded_and_path_credentials_are_removed():
    from urllib.parse import quote
    redactor = Redactor(CONFIG)
    url = 'https://publisher.example/oauth/token/path-secret?code=query-secret'
    assert 'path-secret' not in redactor.text(url)
    for _ in range(6):
        url = quote(url, safe='')
    assert 'path-secret' not in redactor.text(url)
    assert 'query-secret' not in redactor.text(url)


def test_summary_does_not_turn_site_text_into_markdown_images(tmp_path):
    request, _ = packet(tmp_path)
    request['papers'][0]['publisher'] = '![beacon](https://evil.example/pixel)'
    export_report(request, tmp_path / 'report.zip')
    summary = unzip(tmp_path / 'report.zip')['summary.md'].decode()
    assert '![beacon]' not in summary
    assert r'\!\[beacon\]\(https://evil.example/pixel\)' in summary
