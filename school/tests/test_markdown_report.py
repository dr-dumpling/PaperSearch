"""The report on pages from sites not yet supported for Markdown (user, 2026-11-16): a ZIP
to look over and attach to an issue, and the issue's link, nothing uploaded."""
import json
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from paper_search_school import markdown_report as mr
from paper_search_school import progress_capsule as capsule

CONFIG = {'school_name': '红木兰大学', 'idp_entity_id': 'https://idp.hongmulan.example/idp/shibboleth'}
PAGE = '''<html><head><meta name="citation_reference" content="x"><script>token="secret1"</script></head>
<body><main class="article"><h2 class="section-title">Methods</h2><p>We read 12 plates at 红木兰大学 under the clouds.</p>
<img src="https://ard.eular.org/F1.large.jpg"><a href="https://ard.eular.org/doi/pdf/10.1/x?token=secret2">PDF</a>
<p>/Users/example-user/Downloads was where it went.</p></main></body></html>'''


def record(folder: Path, doi: str, host: str = 'ard.eular.org', attempt: str = '', **report) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    name = doi.replace('/', '_')
    page = folder / f'{name}_markdown-page.html'
    page.write_text(PAGE, encoding='utf-8', newline='\n')
    if attempt:
        (folder / f'{name}_markdown-attempt.md').write_text(attempt, encoding='utf-8', newline='\n')
    path = folder / f'{name}_markdown-report.json'
    path.write_text(json.dumps({'schemaVersion': 1, 'doi': doi, 'url': f'https://{host}/doi/{doi}?token=secret3',
                                'page': str(page), 'images': 2, 'host': host, 'template': 'elsevier-journal',
                                'shortfall': {'references': 1}, 'message': 'x', **report}), encoding='utf-8')
    return path


def unzip(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name).decode('utf-8') for name in archive.namelist()}


def test_the_zip_holds_each_page_as_a_structure_with_what_it_lacked_and_nothing_private(tmp_path):
    records = tmp_path / 'runs' / 'r1' / 'records'
    first = record(records, '10.1016/j.ard.2026.05.001', matchedBy='publisher', basis='Elsevier',
                   attempt='# Predicting\n\n## Methods\n\nWe read 12 plates at 红木兰大学 (user@example.edu).\n',
                   checks={'headings': ['## Methods'], 'missingParagraphs': ['In Delphi round 2 …'],
                           'page': {'title': 'Predicting rapid progression', 'publisher': 'Elsevier', 'platforms': ['Atypon'],
                                    'container': 'main.article', 'paragraphs': 2, 'paragraphChars': 120, 'headings': ['h2 Methods'],
                                    'figures': 1, 'images': 1, 'tables': 0, 'formulas': 0, 'citationReferences': 2},
                           'tried': [{'template': 'sciencedirect', 'layer': 'publisher', 'result': 'unrecognized'},
                                     {'template': 'elsevier-journal', 'layer': 'publisher', 'result': 'incomplete', 'shortfall': {'references': 1}},
                                     {'template': 'highwire', 'layer': 'other', 'result': 'unrecognized'}]})
    second = record(records, '10.1000/b', host='journals.example.org', template=None, shortfall={})
    batch = tmp_path / 'batch'
    entries = [{'report': str(first), 'doi': '10.1016/j.ard.2026.05.001', 'title': 'Predicting rapid progression'},
               {'report': str(second), 'doi': '10.1000/b', 'title': 'Another'},
               # Another DOI than the report's, a relative path: left out.
               {'report': str(first), 'doi': '10.9999/other'}, {'report': 'r_markdown-report.json', 'doi': '10.1000/c'}]
    result = mr.export(entries, batch, CONFIG, '0.7.0-preview.13', now=datetime(2026, 11, 16, 20, 5))
    assert result['name'] == 'PaperSearch-Markdown报告-20261116-2005.zip'
    assert Path(result['path']).parent == batch and result['papers'] == 2
    assert result['sites'] == ['ard.eular.org', 'journals.example.org']
    files = unzip(result['path'])
    assert sorted(files) == ['manifest.json', 'papers/001/attempt.md', 'papers/001/checks.json', 'papers/001/page.html',
                             'papers/002/checks.json', 'papers/002/page.html', 'summary.md']
    everything = '\n'.join(files.values())
    for private in ('secret1', 'secret2', 'secret3', '红木兰', 'example-user', 'hongmulan'):
        assert private not in everything
    # The whole page as it was, only what is private taken out (user, 2026-11-17).
    page = files['papers/001/page.html']
    assert 'class="section-title"' in page and 'We read 12 plates at [INSTITUTION] under the clouds.' in page
    assert '<script>' in page and '<meta name="citation_reference" content="x">' in page
    assert 'https://ard.eular.org/F1.large.jpg' in page and 'https://ard.eular.org/doi/pdf/10.1/x' in page
    # A title's slug in an address is not a token; a session in the path goes.
    redactor = mr.Redactor(CONFIG)
    assert mr.page_address('https://pubs.example.org/gsa/geosphere/article/799426/Erosion-and-sediment-transfer-by-debris-flows-on'
                           ';jsessionid=ABC123?token=t&page=2', redactor) == \
        'https://pubs.example.org/gsa/geosphere/article/799426/Erosion-and-sediment-transfer-by-debris-flows-on?page=2'
    assert mr.page_address('https://idp.hongmulan.example/idp/profile/SAML2?SAMLRequest=x', redactor).startswith('https://school.invalid/')
    assert files['papers/001/attempt.md'] == '# Predicting\n\n## Methods\n\nWe read 12 plates at [INSTITUTION] ([EMAIL]).\n'
    assert json.loads(files['papers/001/checks.json'])['checks']['missingParagraphs'] == ['In Delphi round 2 …']
    summary = files['summary.md']
    assert '## ard.eular.org（1 篇）' in summary and '参考文献不全' in summary and '没有规则能读出正文' in summary
    assert 'Predicting rapid progression' in summary
    assert 'elsevier-journal（按出版社 Elsevier）' in summary  # why these rules were the closest
    # What each site needs, first: the rules put right, or new ones (user, 2026-11-17).
    assert '结论：没有规则能完整转换；最接近的是 `elsevier-journal`。' in summary
    assert '结论：没有一套规则能读出正文，要为这个网站新写一套规则。' in summary
    # The page's facts and what each rule made of it.
    for said in ('网页写的出版社：Elsevier', '网站平台：Atypon', '正文所在元素：`main.article`', '段落 2 段',
                 '出版社：sciencedirect 认不出这种页面；elsevier-journal 不完整（参考文献少 1 条）', '其余规则：1 套都认不出这种页面',
                 'attempt.md 最接近的规则转出的 Markdown'):
        assert said in summary, said
    # A batch of the Markdown alone has no title: the page's.
    assert mr.export([{'report': str(first), 'doi': '10.1016/j.ard.2026.05.001'}], tmp_path / 'b2', CONFIG)['papers'] == 1
    assert 'Predicting rapid progression' in unzip(next((tmp_path / 'b2').glob('*.zip')))['summary.md']
    # Another export the same minute: a new file beside it, never over it.
    assert mr.export(entries[:1], batch, CONFIG, now=datetime(2026, 11, 16, 20, 5))['name'] == 'PaperSearch-Markdown报告-20261116-2005-2.zip'
    with pytest.raises(mr.ReportError):
        mr.export([{'report': str(tmp_path / 'gone_markdown-report.json'), 'doi': '10.1/x'}], batch)


def test_a_page_another_sites_rules_converted_is_in_the_report_too_saying_the_site_needs_listing(tmp_path):
    # One report for both (user, 2026-11-17): the saved page, the Markdown it made, and what the site needs.
    records = tmp_path / 'records'
    saved = [record(records, f'10.1016/j.jacc.2026.06.01{i}', host='www.jacc.org', attempt='# Guideline\n', template='atypon-current',
                    rules='Atypon', matchedBy='platform', basis='Atypon', status='ok', shortfall=None) for i in (7, 8)]
    unsaved = record(records, '10.1000/mixed', host='mixed.example.org', template='atypon-current', rules='Atypon', status='incomplete')
    mixed = record(records, '10.1000/mixed2', host='mixed.example.org', attempt='# M\n', template='atypon-current', rules='Atypon', status='ok',
                   shortfall=None)
    entries = [{'report': str(path), 'doi': json.loads(path.read_text(encoding='utf-8'))['doi']} for path in (*saved, unsaved, mixed)]
    result = mr.export(entries, tmp_path / 'batch', CONFIG, '0.7.0-preview.13')
    files = unzip(result['path'])
    summary = files['summary.md']
    assert ('结论：现有规则能完整转换（采用 Atypon 规则，模板 `atypon-current`，2 篇都转全）。核对后加登记文件即可，不用写新规则。'
            in summary)
    assert '结论：采用 Atypon 规则转全了 1 篇，另 1 篇没转全。' in summary
    assert '- 结果：完整转换，已保存；用的规则：atypon-current（按网站平台 Atypon）' in summary
    assert 'attempt.md 转出并保存的 Markdown' in summary
    assert files['papers/001/attempt.md'] == '# Guideline\n' and 'page.html' in ' '.join(files)
    fields = {k: v[0] for k, v in parse_qs(urlsplit(result['issueUrl']).query).items()}
    assert fields['result'].split('\n') == ['www.jacc.org：采用 Atypon 规则；已尝试 2 篇，2 篇完整已保存，0 篇不完整未保存',
                                            'mixed.example.org：采用 Atypon 规则；已尝试 2 篇，1 篇完整已保存，1 篇不完整未保存']
    assert fields['missing'] == 'mixed.example.org：参考文献不全 1 篇'


def test_the_issue_link_fills_in_the_sites_version_and_counts_never_a_doi_or_title(tmp_path):
    report = record(tmp_path, '10.1016/j.ard.2026.05.001')
    papers = [
        {'doi': '10.1016/j.ard.2026.05.001', 'title': 'Secret title', 'markdown_host': 'ard.eular.org', 'markdown_saved': False,
         'markdown_report': str(report)},
        {'doi': '10.1016/j.ard.2026.05.002', 'title': 'Saved', 'markdown_host': 'ard.eular.org', 'markdown_saved': True,
         'markdown_rules': 'Atypon'},
        {'doi': '10.1016/j.ard.2026.05.003', 'markdown_host': 'ard.eular.org', 'markdown_skipped': True},
    ]
    sites = mr.site_counts(papers)
    assert sites == [{'host': 'ard.eular.org', 'saved': 1, 'unsaved': 1, 'skipped': 1, 'lacks': {'参考文献不全': 1}, 'rules': {'Atypon': 1}}]
    url = mr.issue_url(sites, '0.7.0-preview.13')
    assert url.startswith('https://github.com/dr-dumpling/PaperSearch/issues/new?')
    fields = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert fields['template'] == 'markdown-site.yml' and fields['site'] == 'ard.eular.org'
    assert fields['title'] == '[Markdown] ard.eular.org' and fields['version'] == '0.7.0-preview.13'
    assert fields['result'] == 'ard.eular.org：采用 Atypon 规则；已尝试 2 篇，1 篇完整已保存，1 篇不完整未保存，1 篇未再尝试'
    assert fields['missing'] == 'ard.eular.org：参考文献不全 1 篇'
    assert '10.1016' not in url and 'Secret' not in url


def test_a_long_run_of_letters_does_not_stall_the_report():
    # A 5 MB JACC page with a 97 643-character run took minutes in the secret-assignment pattern (2026-11-17).
    import time
    redactor = mr.Redactor(CONFIG)
    page = '<script>var x = "' + 'a' * 100_000 + '"; var csrfToken = "s3cret-value";</script>'
    started = time.monotonic()
    out = mr.redact_page(page, redactor)
    assert time.monotonic() - started < 2
    assert 'csrfToken = "[SECRET_REMOVED]"' in out and 's3cret' not in out


def test_the_supported_sites_are_on_the_branch_of_the_version():
    assert mr.support_doc('0.7.0-preview.13').endswith('/blob/preview/skills/paper-search/references/publisher-support.md')
    assert '/blob/main/' in mr.support_doc('0.7.0') and '/blob/main/' in mr.support_doc('')


def test_the_windows_one_button_exports_beside_the_batch_and_opens_the_issue(tmp_path):
    report = record(tmp_path / 'records', '10.1016/j.ard.2026.05.001')
    listed = {'batch_id': 'b1', 'folder': str(tmp_path / 'batch'), 'papers': {
        '1': {'index': 1, 'state': 'ok', 'doi': '10.1016/j.ard.2026.05.001', 'title': 'T', 'markdown_host': 'ard.eular.org',
              'markdown_saved': False, 'markdown_report': str(report)}}}
    api = capsule.Api(MagicMock(), MagicMock(), MagicMock())
    with patch.object(capsule, 'read_papers', return_value=listed), \
            patch.object(capsule, 'read_state', return_value={'batch_id': 'b1', 'status': 'done'}), \
            patch('paper_search_school.config.load_config', return_value=CONFIG), \
            patch.object(capsule.progress_view, 'reveal_file', return_value=True) as shown, \
            patch('webbrowser.open', return_value=True) as browser:
        said = api.markdown_issue()
        assert said.startswith('已导出报告 PaperSearch-Markdown报告-') and said.endswith('.zip 并打开 issue 页面，把它拖进去')
        assert Path(shown.call_args.args[0]).parent == tmp_path / 'batch'
        assert 'template=markdown-site.yml' in browser.call_args.args[0]
        assert api.open_markdown_support() == '已在浏览器打开'
    # Another batch's papers: nothing to export.
    with patch.object(capsule, 'read_papers', return_value={**listed, 'batch_id': 'b0'}), \
            patch.object(capsule, 'read_state', return_value={'batch_id': 'b1'}):
        assert api.markdown_issue() == '这批没有暂未正式支持的网站'
