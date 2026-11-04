"""A made-up journal site without a publisher profile, end to end in a local
headless Chrome (opt-in): "Access through your institution" on the article page, the site's chooser with a CARSI federation
list and a school list valued by entityID, a school IdP that returns, the
article page with the school's session and a PDF link carrying the DOI, the
PDF captured and verified. The same site with no institution entry ends as
generic_institution_entry_missing. Every request is answered locally."""
import dataclasses
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from paper_search_carsi.engine.batch import PaperRecord, PublisherBatchDownloader
from paper_search_carsi.engine.batch_login import GENERIC_ENTRY_MISSING
from paper_search_carsi.publishers.site import site_profile

DOI = "10.99977/medj.2026.0042"
TITLE = "A made-up randomised trial of morning light in shift workers"
HOST = "https://journals.medpress.example"
# The article's own address names no DOI (as on Silverchair sites): its citation_doi decides.
ARTICLE = HOST + "/medj/article/42/7/1201/880042/a-made-up-randomised-trial"
CHOOSER = HOST + "/action/ssostart"
SP_LOGIN = HOST + "/Shibboleth.sso/Login"
SP_RETURN = HOST + "/Shibboleth.sso/SAML2/POST"
PDF = HOST + "/doi/pdf/" + DOI
READER = HOST + "/doi/reader/" + DOI
ENTITY = "https://idp.example.edu.cn/idp/shibboleth"
OTHER_ENTITY = "https://idp.other.example.edu.cn/idp/shibboleth"
IDP = "https://idp.example.edu.cn/idp/profile/SAML2/Redirect/SSO"


def moved(target):
    """A page that moves on at once: Chrome does not follow a fulfilled 302 here."""
    return f"<title>Redirecting</title><script>location.replace({json.dumps(target)});</script>"


def synthetic_pdf():
    import pymupdf
    with pymupdf.open() as document:
        for _ in range(2):
            document.new_page().insert_text((40, 60), f"{TITLE}\nDOI: {DOI}\nAbstract\nMethods and results.")
        return document.tobytes() + b"\n%" + b"x" * 6000


def article_html(signed_in, entry=True, reader=False):
    head = (f'<title>{TITLE} | Journal of Made-up Medicine</title><meta name="citation_doi" content="{DOI}">'
            f'<meta name="citation_title" content="{TITLE}">')
    if signed_in:
        return (head + f'<meta name="citation_pdf_url" content="{PDF}"><header><a href="/">MedPress</a><div class="institution-banner">Access provided by '
                f'Example University</div></header><h1>{TITLE}</h1>'
                + (f'<p><a href="/doi/reader/{DOI}">PDF/EPUB</a></p>' if reader else f'<p><a href="/doi/pdf/{DOI}">Download PDF</a></p>')
                + '<p>Background. Methods. Results.</p>')
    access = (f'<a href="/action/ssostart?redirectUri=%2Fmedj%2Farticle%2F42%2F7%2F1201%2F880042">'
              'Access through your institution</a>' if entry else '<a href="/user/login">Log in</a>')
    return (head + f'<header><a href="/">MedPress</a></header><h1>{TITLE}</h1>'
            f'<div class="access">{access}<br><a href="/action/purchase">Purchase this article</a></div><p>Abstract.</p>')


CHOOSER_HTML = f"""<title>Institutional login | MedPress</title><h2>Find your institution</h2>
<div class="chooser">
  <label>Federation <select id="federation"><option value="">Select your federation</option>
    <option value="ukamf">UK Access Management Federation</option>
    <option value="carsi">China CERNET Federation (CARSI)</option></select></label>
  <label>Institution <select id="institution"><option value="">Select your institution</option></select></label>
  <button id="go" onclick="location.href='/Shibboleth.sso/Login?entityID='
      + encodeURIComponent(document.querySelector('#institution').value)">Continue</button>
</div>
<script>document.querySelector('#federation').addEventListener('change', e => setTimeout(() => {{
  const list = document.querySelector('#institution');
  list.innerHTML = "<option value=''>Select your institution</option>";
  if (e.target.value === 'carsi') list.insertAdjacentHTML('beforeend',
      "<option value='{OTHER_ENTITY}'>Other University</option><option value='{ENTITY}'>Example University</option>");
}}, 800));</script>"""

# The school's IdP hands the login back by itself (a SAML response form).
IDP_HTML = f"""<title>Example University sign-in</title><form method="post" action="{SP_RETURN}">
<input type="hidden" name="SAMLResponse" value="fixture"><input type="hidden" name="RelayState" value="fixture"></form>
<p>Signing you in</p><script>setTimeout(() => {{ location.href = '{SP_RETURN}'; }}, 1500);</script>"""


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class GenericSiteFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True,
            args=["--disable-background-networking", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"])
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch.dict(os.environ, CARSI_DATA_DIR=str(self.root / "data")))
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.requests, self.signed_in, self.entry, self.body = [], False, True, synthetic_pdf()
        self.reader = False
        self.article_delay_ms = 0

        def respond(route):
            url = route.request.url
            self.requests.append(url)
            plain = url.split("?", 1)[0]
            if plain == ARTICLE:
                html = article_html(self.signed_in, self.entry, self.reader)
                if self.article_delay_ms:
                    html = ("<title>Loading article</title><body><script>setTimeout(() => {document.body.innerHTML = "
                            + json.dumps(html) + ";}, " + str(self.article_delay_ms) + ");</script></body>")
                route.fulfill(status=200, content_type="text/html", body=html)
            elif plain == READER:
                route.fulfill(status=200, content_type="text/html",
                              body=f"<title>{TITLE} | Reader</title><div id='viewer'>EPUB reader</div>")
            elif plain == CHOOSER:
                route.fulfill(status=200, content_type="text/html", body=CHOOSER_HTML)
            elif plain == SP_LOGIN:
                entity = parse_qs(urlparse(url).query).get("entityID", [""])[0]
                host = urlparse(entity).hostname or "unknown.example"
                route.fulfill(status=200, content_type="text/html",
                              body=moved(f"https://{host}/idp/profile/SAML2/Redirect/SSO?SAMLRequest=x"))
            elif plain == IDP:
                route.fulfill(status=200, content_type="text/html", body=IDP_HTML)
            elif plain == SP_RETURN:
                self.signed_in = True
                route.fulfill(status=200, content_type="text/html", body=moved(ARTICLE))
            elif plain == PDF and self.signed_in:
                # Served as a download: headless Chrome keeps an inline PDF's body in its
                # viewer, out of the capture's reach (the transport has its own tests).
                route.fulfill(status=200, content_type="application/pdf", body=self.body,
                              headers={"Content-Disposition": 'attachment; filename="medj.2026.0042.pdf"'})
            else:
                route.fulfill(status=404, content_type="text/html", body="<title>Not found</title>")
        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        # doi.org's redirect target, as the bridge resolves it; the article is
        # opened at that address (doi.org redirects there in production).
        profile = dataclasses.replace(site_profile(DOI, ARTICLE), article_url_template=ARTICLE)
        self.d = PublisherBatchDownloader(
            {"publisher_institution_federation": "carsi", "carsi_idp_name": "Example University",
             "idp_entity_id": ENTITY, "cache_dir": str(self.root / "cache")},
            profile=profile, institution_query="Example University", login_timeout_sec=60, pdf_timeout_sec=10)

    def test_the_shared_rules_sign_in_on_a_site_without_profile_and_take_its_pdf(self):
        self.assertEqual(self.d.profile.name, "site:medpress.example")
        result = self.d.fetch_one(self.page, PaperRecord(doi=DOI, title=TITLE), self.root / "run")
        states = [e["state"] for e in result.events]
        self.assertTrue(result.ok, (result.state, result.reason, result.events[-12:]))
        self.assertTrue(result.verified_match)
        self.assertEqual(Path(result.pdf_path).read_bytes(), self.body)
        self.assertEqual(result.pdf_url.split("?", 1)[0], PDF)
        # The way there: the entry, CARSI, the school by its entityID, the IdP, back on the article.
        for state in ("sso_entry_clicked", "institution_federation_selected", "institution_selected",
                      "institution_list_submitted", "article_access_ready", "pdf_saved"):
            self.assertIn(state, states)
        selected = next(e["detail"] for e in result.events if e["state"] == "institution_selected")
        self.assertEqual(selected, "Example University (entityID, #institution)")
        self.assertIn(IDP + "?SAMLRequest=x", self.requests)
        self.assertNotIn("idp.other.example.edu.cn", " ".join(self.requests))
        decisions = [e["detail"] for e in result.events if e["state"] == "access_decision"]
        self.assertTrue(decisions[0].startswith("out (closed)"), decisions)
        self.assertTrue(decisions[-1].startswith("in (session): session line: Example University"), decisions)
        record = json.loads(Path(result.record_path).read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "success")

    def test_the_article_page_s_pdf_is_taken_when_its_pdf_control_opens_a_reader(self):
        # ASM (2026-11-02): "PDF/EPUB" opens a reader page that links no PDF; the
        # article page's own PDF (here its citation_pdf_url) is still tried.
        self.signed_in, self.reader = True, True
        result = self.d.fetch_one(self.page, PaperRecord(doi=DOI, title=TITLE), self.root / "run")
        self.assertTrue(result.ok, (result.state, result.reason, result.events[-12:]))
        self.assertEqual(result.pdf_url.split("?", 1)[0], PDF)
        self.assertLess(self.requests.index(READER), self.requests.index(PDF))

    def test_a_captcha_route_waits_for_completion_before_fetching_the_article(self):
        self.signed_in = True
        captcha = HOST + "/captcha/(S(fixture))/"
        self.context.route(ARTICLE, lambda route: route.fulfill(
            status=200, content_type="text/html", body=moved(captcha)), times=1)
        self.context.route(captcha, lambda route: route.fulfill(
            status=200, content_type="text/html",
            body='<title>Captcha</title><p>Enter the displayed code.</p><script>'
                 f'setTimeout(() => location.replace({json.dumps(ARTICLE)}), 4000);</script>'))
        result = self.d.fetch_one(self.page, PaperRecord(doi=DOI, title=TITLE), self.root / "run")
        self.assertTrue(result.ok, (result.state, result.reason, result.events[-12:]))
        self.assertTrue(result.verified_match)
        self.assertEqual(Path(result.pdf_path).read_bytes(), self.body)
        states = [event["state"] for event in result.events]
        self.assertIn("challenge_manual_wait", states)
        self.assertIn("challenge_resolved", states)
        self.assertNotIn("sso_start", states)
        self.assertNotIn("login_entry_missing", states)

    def test_a_pdf_captcha_route_waits_and_keeps_the_verified_pdf(self):
        self.signed_in = True
        self.d.login_timeout_sec = 20
        captcha = HOST + "/captcha/(S(fixture))/"
        completed_url = HOST + "/fixture/verification-completed"
        completed = [False]

        def pdf(route):
            if completed[0]:
                route.fallback()
            else:
                route.fulfill(status=200, content_type="text/html", body=moved(captcha))

        def complete(route):
            completed[0] = True
            route.fulfill(status=200, content_type="text/html", body=moved(PDF))

        self.context.route(PDF, pdf)
        self.context.route(completed_url, complete)
        self.context.route(captcha, lambda route: route.fulfill(
            status=200, content_type="text/html",
            body='<title>Captcha</title><p>Enter the displayed code.</p><script>'
                 f'setTimeout(() => location.replace({json.dumps(completed_url)}), 8000);</script>'))
        # Browser routes do not intercept the separate HTTP transport. Model
        # the same gate there; it cannot return the PDF before verification.
        from requests import Response
        http_calls = []

        def reply(url, **kwargs):
            http_calls.append((url, completed[0]))
            response = Response()
            response.status_code = 200
            response.url = PDF if completed[0] else captcha
            response.headers["Content-Type"] = "application/pdf" if completed[0] else "text/html"
            response._content = self.body if completed[0] else b"<title>Captcha</title>"
            return response

        with patch("paper_search_carsi.engine.batch_capture.requests.get", side_effect=reply):
            result = self.d.fetch_one(self.page, PaperRecord(doi=DOI, title=TITLE), self.root / "run")
        self.assertTrue(result.ok, (result.state, result.reason, result.events[-12:]))
        self.assertTrue(result.verified_match)
        self.assertEqual(Path(result.pdf_path).read_bytes(), self.body)
        self.assertTrue(all(url == PDF for url, _ in http_calls), http_calls)
        states = [event["state"] for event in result.events]
        self.assertIn("challenge_manual_wait", states)
        self.assertIn("challenge_resolved", states)
        self.assertNotIn("sso_start", states)
        self.assertNotIn("login_entry_missing", states)

    def test_a_slowly_drawn_article_reaches_its_pdf_without_an_unnecessary_login(self):
        self.signed_in, self.article_delay_ms = True, 25_000
        result = self.d.fetch_one(self.page, PaperRecord(doi=DOI, title=TITLE), self.root / "run")
        self.assertTrue(result.ok, (result.state, result.reason, result.events[-12:]))
        self.assertTrue(result.verified_match)
        self.assertEqual(Path(result.pdf_path).read_bytes(), self.body)
        self.assertNotIn(CHOOSER, self.requests)
        self.assertIn("pdf_capture_started", [event["state"] for event in result.events])

    def test_without_an_institution_entry_the_site_ends_saying_so(self):
        self.entry = False
        result = self.d.fetch_one(self.page, PaperRecord(doi=DOI, title=TITLE), self.root / "run")
        self.assertEqual((result.status, result.reason, result.state),
                         ("failed", GENERIC_ENTRY_MISSING, GENERIC_ENTRY_MISSING), result.events[-8:])
        events = {e["state"]: e.get("detail", "") for e in result.events}
        self.assertIn("access through your institution", events["login_entry_missing"])
        self.assertEqual(events["login_entry_controls"],
                         f'{ARTICLE} | sign-in or access controls: "Log in" -> /user/login')
        self.assertEqual(result.snapshots[-1]["why"], "login entry missing")
        self.assertTrue(Path(result.snapshots[-1]["screenshot"]).is_file())
        diagnostic = json.loads(Path(result.diagnostic_path).read_text(encoding="utf-8"))
        self.assertEqual((diagnostic["state"], diagnostic["reason"]), (GENERIC_ENTRY_MISSING, GENERIC_ENTRY_MISSING))
        self.assertFalse(any(u.startswith(CHOOSER) or "idp." in u for u in self.requests))


if __name__ == "__main__":
    unittest.main()
