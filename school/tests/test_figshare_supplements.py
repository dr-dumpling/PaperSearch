"""Figshare association, bounded discovery and shared collector integration."""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from paper_search_school.adapters.platforms.figshare import resource, supplement_links
from paper_search_school.engine.supplements import collect, supplements_dir
from paper_search_school.entitlements import UserStoppedBatch

DOI = '10.1098/rsif.2026.0072'
ROOT = 'https://doi.org/10.6084/m9.figshare.c.8675280'
FILE = {'id': 123, 'name': 'Supplement.pdf', 'size': 100, 'is_link_only': False}


def page_for(detail=None, members=None, item=None, links=None):
    page = MagicMock()
    page.evaluate.return_value = {'doi': DOI, 'links': links or [ROOT]}
    responses = {
        '/collections/8675280': {'doi': '10.6084/m9.figshare.c.8675280.v1', **(detail or {'id': 8675280, 'resource_doi': DOI})},
        '/collections/8675280/articles?page_size=51&page=1': members if members is not None else [{'id': 5, 'version': 2}],
        '/articles/5/versions/2': item or {'id': 5, 'files': [FILE]},
    }
    def get(url, **kwargs):
        value = responses[url.removeprefix('https://api.figshare.com/v2')]
        return SimpleNamespace(ok=True, status=200, json=lambda: value)
    page.context.request.get.side_effect = get
    return page


@pytest.mark.parametrize('url,expected', [
    (ROOT, ('collections', '8675280', '')),
    ('https://widgets.figshare.com/articles/42/embed?show_title=1', ('articles', '42', '')),
    (ROOT + '.v1', ('collections', '8675280', '1')),
    ('https://doi.org/10.60893/figshare.adv.c.8713366', ('collections', '8713366', '')),
    ('https://doi.org/10.60893/figshare.adv.33738526.v2', ('articles', '33738526', '2')),
    ('https://doi.org/10.6084/m9.figshare.42.v3', ('articles', '42', '3')),
    ('https://rs.figshare.com/articles/journal_contribution/Title/42/3', ('articles', '42', '3')),
    ('https://aip.figshare.com/articles/Title/42', ('articles', '42', '')),
    ('https://evil.figshare.com.evil.org/articles/42', None),
    ('https://user@figshare.com/articles/42', None),
    ('https://figshare.com.evil.org/articles/42', None),
])
def test_official_resource_forms(url, expected):
    assert resource(url) == expected


def test_collection_pins_member_version_and_keeps_exact_link():
    page = page_for()
    links = supplement_links(page, DOI, pause=lambda _: None)
    assert [(link.url, link.error) for link in links] == [('https://api.figshare.com/v2/file/download/123', '')]
    assert '/articles/5/versions/2' in page.context.request.get.call_args.args[0]


@pytest.mark.parametrize('item', [
    {'id': 5, 'resource_doi': '10.1000/other', 'files': [FILE]},
    {'id': 5, 'related_materials': [{'relation': 'IsSupplementTo', 'identifier': '10.1000/other'}], 'files': [FILE]},
])
def test_collection_does_not_override_member_conflict(item):
    assert supplement_links(page_for(item=item), DOI, pause=lambda _: None)[0].set_aside == 'figshare_article_mismatch'


def test_exact_association_required_and_reference_is_not_evidence():
    for detail in [{'id': 8675280}, {'id': 8675280, 'resource_doi': '10.1000/other'},
                   {'id': 8675280, 'related_materials': [{'relation': 'References', 'identifier': DOI}]}]:
        assert supplement_links(page_for(detail=detail), DOI, pause=lambda _: None)[0].set_aside == 'figshare_article_mismatch'
    detail = {'id': 8675280, 'related_materials': [{'relation': 'IsSupplementTo', 'identifier': DOI}]}
    assert not supplement_links(page_for(detail=detail), DOI, pause=lambda _: None)[0].error


def test_explicit_supplement_label_fills_missing_backlink_but_never_overrides_conflict():
    page = page_for(detail={'id': 8675280})
    page.evaluate.return_value['labelled'] = [ROOT]
    assert not supplement_links(page, DOI, pause=lambda _: None)[0].error
    for detail in [
        {'id': 8675280, 'resource_doi': '10.1/other'},
        {'id': 8675280, 'related_materials': [{'relation': 'IsSupplementTo', 'identifier': '10.1/other'}]},
    ]:
        page = page_for(detail=detail)
        page.evaluate.return_value['labelled'] = [ROOT]
        assert supplement_links(page, DOI, pause=lambda _: None)[0].set_aside == 'figshare_article_mismatch'


@pytest.mark.parametrize('file,error', [
    ({**FILE, 'size': 201 * 1024 * 1024}, 'too_large'),
    ({**FILE, 'is_link_only': True}, 'figshare_link_only'),
    ({**FILE, 'size': None}, 'figshare_invalid_file'),
    ({**FILE, 'id': -1}, 'figshare_invalid_file'),
])
def test_unusable_files_are_reported_without_download(file, error, tmp_path):
    page = page_for(item={'id': 5, 'files': [file]})
    links = supplement_links(page, DOI, pause=lambda _: None)
    assert links[0].error == error
    request = MagicMock()
    files = collect(request, links, tmp_path, DOI)
    request.get.assert_not_called()
    assert files[0]['reason'] == error
    assert json.loads((supplements_dir(tmp_path, DOI) / 'manifest.json').read_text())['files'] == files


def test_no_files_http_failure_cancel_and_article_identity():
    assert supplement_links(page_for(item={'id': 5, 'files': []}), DOI, pause=lambda _: None)[0].error == 'figshare_no_files'
    page = page_for()
    page.context.request.get.side_effect = lambda *a, **k: SimpleNamespace(ok=False, status=403)
    assert supplement_links(page, DOI)[0].error == 'figshare_http_403'
    page.context.request.get.side_effect = UserStoppedBatch('stop')
    with pytest.raises(UserStoppedBatch):
        supplement_links(page, DOI)
    page.evaluate.return_value['doi'] = '10.1000/other'
    assert supplement_links(page, DOI) is None


def test_deadline_and_resource_limit_are_visible():
    ticks = iter([0, 31])
    assert supplement_links(page_for(), DOI, clock=lambda: next(ticks))[0].error == 'figshare_time_budget'
    page = page_for(links=[ROOT + '#' + str(i) for i in range(8)])
    assert len(supplement_links(page, DOI, pause=lambda _: None)) == 1


@pytest.mark.skipif(os.getenv('SCHOOL_LOCAL_BROWSER_TEST') != '1', reason='local browser fixture opt-in')
def test_real_dom_article_link_without_publisher_specific_hook(tmp_path):
    from patchright.sync_api import sync_playwright
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.route('**/*', lambda route: route.abort())
            page.set_content(f'<meta name="citation_doi" content="{DOI}"><iframe src="{ROOT}"></iframe>')
            # Exercise actual DOM extraction with an isolated API fixture.
            fake = page_for()
            proxy = SimpleNamespace(evaluate=page.evaluate, context=fake.context)
            links = supplement_links(proxy, DOI, pause=lambda _: None)
            request = MagicMock()
            request.get.return_value = SimpleNamespace(ok=True, status=200, headers={'content-type': 'application/pdf'}, body=lambda: b'%PDF-1.7 fixture')
            assert collect(request, links, tmp_path, DOI)[0]['status'] == 'saved'
        finally:
            browser.close()


@pytest.mark.skipif(os.getenv('SCHOOL_LOCAL_BROWSER_TEST') != '1', reason='local browser fixture opt-in')
def test_real_dom_references_are_not_supplement_candidates():
    from patchright.sync_api import sync_playwright

    reference = 'https://doi.org/10.6084/m9.figshare.24512944.v3'
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page()
            page.route('**/*', lambda route: route.abort())
            for section in ['role="doc-bibliography"', 'class="article-section__references"',
                            'id="references"', 'id="articleReferences"']:
                page.set_content(f'''<meta name="citation_doi" content="{DOI}">
                    <section {section}><a href="{reference}">Supplement 1</a></section>''')
                fake = page_for()
                proxy = SimpleNamespace(evaluate=page.evaluate, context=fake.context)
                assert supplement_links(proxy, DOI, pause=lambda _: None) is None
                fake.context.request.get.assert_not_called()

                # The same resource outside the bibliography must still be checked.
                page.set_content(f'''<meta name="citation_doi" content="{DOI}">
                    <section {section}><a href="{reference}">Cited dataset</a></section>
                    <section><h2>Supporting information</h2><a href="{ROOT}">Files</a></section>''')
                links = supplement_links(proxy, DOI, pause=lambda _: None)
                assert [(link.url, link.error) for link in links] == [
                    ('https://api.figshare.com/v2/file/download/123', '')]
        finally:
            browser.close()


@pytest.mark.skipif(os.getenv('SCHOOL_LOCAL_BROWSER_TEST') != '1', reason='local browser fixture opt-in')
def test_real_dom_explicit_supplement_label_can_supply_missing_backlink():
    from patchright.sync_api import sync_playwright

    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page()
            page.route('**/*', lambda route: route.abort())
            for label, expected in [('Supplement 1', ''), ('Cited dataset', 'figshare_article_mismatch')]:
                page.set_content(f'''<meta name="citation_doi" content="{DOI}">
                    <article><a href="{ROOT}">{label}</a></article>''')
                fake = page_for(detail={'id': 8675280})
                proxy = SimpleNamespace(evaluate=page.evaluate, context=fake.context)
                links = supplement_links(proxy, DOI, pause=lambda _: None)
                assert len(links) == 1 and links[0].set_aside == expected and not links[0].error
        finally:
            browser.close()


def test_collection_reports_truncation_and_resource_budget():
    links = supplement_links(page_for(members=[{'id': 5, 'version': 2}] * 51), DOI, pause=lambda _: None)
    assert any(link.error == 'figshare_article_limit' for link in links)
    assert any(not link.error and '/file/download/' in link.url for link in links)
    page = page_for(links=[f'https://doi.org/10.6084/m9.figshare.{i}' for i in range(1, 8)])
    page.context.request.get.side_effect = lambda *a, **k: SimpleNamespace(ok=False, status=404)
    links = supplement_links(page, DOI, pause=lambda _: None)
    assert page.context.request.get.call_count == 5
    assert links[-1].error == 'figshare_resource_limit'


def test_engine_discovers_external_files_when_publisher_has_no_hook(monkeypatch):
    from paper_search_school.engine.batch import PublisherBatchDownloader
    from paper_search_school.adapters.platforms import figshare
    original = figshare.supplement_links
    monkeypatch.setattr(figshare, 'supplement_links', lambda page, doi: original(page, doi, pause=lambda _: None))
    downloader = SimpleNamespace(adapter=SimpleNamespace(supplement_links=lambda *args: None))
    links = PublisherBatchDownloader._settled_supplement_links(downloader, page_for(), DOI)
    assert len(links) == 1 and not links[0].error


def test_resource_doi_must_match_link_not_just_numeric_id():
    page = page_for(detail={'id': 8675280, 'resource_doi': DOI, 'doi': '10.60893/figshare.adv.c.8675280'})
    assert supplement_links(page, DOI, pause=lambda _: None)[0].error == 'figshare_resource_doi_mismatch'
