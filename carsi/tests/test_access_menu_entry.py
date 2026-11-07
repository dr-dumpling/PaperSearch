"""The institution entry behind a site's access menu, for a site no rule names
(ascelibrary.org's "GET ACCESS" and "Login / Register", 2026-11-02). All
requests are answered locally."""
import os
import unittest
from unittest.mock import Mock

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.model import PublisherProfile
from paper_search_carsi.publishers.profiles import get_publisher_profile

DOI = "10.1061/jsendh.steng-16404"
ARTICLE = "https://ascelibrary.org/doi/10.1061/JSENDH.STENG-16404"
CHOOSER = "https://ascelibrary.org/action/ssostart?redirectUri=%2Fdoi%2F10.1061%2FJSENDH.STENG-16404"
LOGIN_PAGE = "https://ascelibrary.org/action/showLogin?uri=%2Fdoi%2F10.1061%2FJSENDH.STENG-16404"
PROFILE = PublisherProfile(name="Fixture Press", article_url_template="https://ascelibrary.org/doi/{doi}",
                           pdf_url_templates=(), success_url_markers=("ascelibrary.org/doi/",), auth_url_markers=(),
                           auth_title_markers=(), sso_text_markers=(), base_domains=("ascelibrary.org",))
MENU = f"""<div id="menu" hidden>
    <form><input type="text" name="user"><input type="password"><button>Sign in</button></form>
    <a href="/action/registration">Register</a>
    <a href="{CHOOSER}">Institutional Login</a></div>"""


JAMA_ARTICLE = "https://jamanetwork.com/journals/jama/fullarticle/2856275"
JAMA_SIGN_IN = "https://jamanetwork.com/signinshibboleth?returnUrl=https%3a%2f%2fjamanetwork.com%2fjournals%2fjama%2ffullarticle%2f2856275"
JAMA_MENU = f"""<button aria-label="Not signed in, user menu"><svg></svg></button>
    <div class="user-menu" style="display:none">
      <a class="auth--personal" href="/oauthsignin?returnUrl=%2Fjournals">Sign in | personal account</a>
      <a href="/register">Create a free account</a>
      <a class="auth--shib" href="{JAMA_SIGN_IN}">Sign In</a></div>
    <button class="sa-button" style="display:none">Access through your institution</button>"""


class HiddenInstitutionLinkTests(unittest.TestCase):
    """JAMA (2026-11-02): the institution sign-in is a hidden link in an account menu
    whose toggle has no words; it is opened by its address, once per page."""

    def setUp(self):
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"},
                                          profile=get_publisher_profile("jama"), institution_query="Example University")
        self.d._is_human_login_page = Mock(return_value=False)
        self.d._has_visible_editable_input = Mock(return_value=False)
        self.page = Mock(url=JAMA_ARTICLE)
        self.page.locator.return_value.count.return_value = 0  # no institution field
        self.result = DownloadResult(doi="10.1001/jama.2026.20039", status="failed")

    def test_the_hidden_sign_in_link_is_opened_by_its_address(self):
        self.page.evaluate.return_value = {"href": JAMA_SIGN_IN, "label": "Sign In", "shown": False}
        self.assertTrue(self.d._follow_hidden_institution_link(self.page, self.result))
        self.page.goto.assert_called_once_with(JAMA_SIGN_IN, wait_until="commit", timeout=30_000)
        self.assertEqual(self.result.events[-1]["state"], "sso_entry_clicked")
        self.assertIn("hidden institution link", self.result.events[-1]["detail"])
        self.assertFalse(self.d._follow_hidden_institution_link(self.page, self.result))  # once per page

    def test_an_address_choosing_an_idp_or_another_site_is_refused(self):
        for href in ("https://jamanetwork.com/signinshibboleth?entityID=https%3A%2F%2Fidp.other.example",
                     "https://other.example/shibboleth/login"):
            with self.subTest(href=href):
                result = DownloadResult(doi="10.1001/x", status="failed")
                self.page.evaluate.return_value = {"href": href, "label": "Sign In", "shown": False}
                self.assertFalse(self.d._follow_hidden_institution_link(self.page, result))
                self.page.goto.assert_not_called()

    def test_never_while_the_user_types_or_on_an_untrusted_page(self):
        self.page.evaluate.return_value = {"href": JAMA_SIGN_IN, "label": "Sign In", "shown": False}
        self.d._has_visible_editable_input.return_value = True
        self.assertFalse(self.d._follow_hidden_institution_link(self.page, self.result))
        self.d._has_visible_editable_input.return_value = False
        self.page.url = JAMA_ARTICLE.replace("https:", "http:")
        self.assertFalse(self.d._follow_hidden_institution_link(self.page, self.result))
        self.page.goto.assert_not_called()

    def test_not_on_login_pages_or_other_sites(self):
        for url in ("https://jamanetwork.com/signinshibboleth?returnUrl=x", "https://idp.school.example/login"):
            with self.subTest(url=url):
                self.page.url = url
                self.assertFalse(self.d._follow_hidden_institution_link(self.page, self.result))
        self.page.evaluate.assert_not_called()


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class AccessMenuEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.requests = []
        self.html = ""

        def respond(route):
            self.requests.append(route.request.url)
            body = self.html if route.request.url == ARTICLE else "<title>Elsewhere</title>"
            route.fulfill(status=200, content_type="text/html", body=body)
        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=PROFILE,
                                          institution_query="Synthetic University A")
        self.result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)

    def test_get_access_opens_the_menu_and_its_institution_login(self):
        self.html = ("<title>Article</title><h1>Article</h1>"
                     "<button onclick=\"document.getElementById('menu').hidden=false\">GET ACCESS</button>" + MENU)
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._looks_logged_out(self.page))  # "GET ACCESS"
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.url, CHOOSER)
        self.assertEqual(self.requests, [ARTICLE, CHOOSER])
        states = [e["state"] for e in self.result.events]
        self.assertEqual(states[-2:], ["access_menu_opened", "sso_entry_clicked"])

    def test_a_login_register_toggle_works_the_same_way(self):
        self.html = ("<title>Article</title><h1>Article</h1>"
                     "<a href=\"#\" aria-haspopup=\"true\" onclick=\"document.getElementById('menu').hidden=false\">"
                     "Login / Register</a>" + MENU)
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.url, CHOOSER)

    def test_a_sign_in_toggle_with_an_accessibility_hint_reveals_institution_login(self):
        # Emerald's diagnostic names this control "Sign In Open Menu" although
        # the screenshot shows only "Sign In". Build the entry on expansion so
        # the hidden-link fallback cannot bypass the toggle in this fixture.
        self.html = ("<title>Article</title><h1>Article</h1>"
                     "<button aria-haspopup='true' aria-controls='menu' onclick=\""
                     "document.getElementById('menu').innerHTML = "
                     "'&lt;a href=&quot;" + CHOOSER + "&quot;&gt;Institutional Login&lt;/a&gt;';"
                     "document.getElementById('menu').hidden=false\">"
                     "Sign In <span>Open Menu</span></button><div id='menu' hidden></div>")
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.url, CHOOSER)
        self.assertEqual(self.requests, [ARTICLE, CHOOSER])
        self.assertEqual([e['state'] for e in self.result.events],
                         ['access_menu_opened', 'sso_entry_clicked'])

    def test_a_personal_login_link_with_an_accessibility_hint_is_left_alone(self):
        self.html = (f'<title>Article</title><h1>Article</h1><a href="{LOGIN_PAGE}">'
                     'Sign In <span>Open Menu</span></a>')
        self.page.goto(ARTICLE)
        self.assertFalse(self.d._click_sso_entry(self.page, self.result))
        self.assertEqual(self.requests, [ARTICLE])
        self.assertEqual(self.result.events, [])

    def test_a_hidden_link_named_an_institution_entry_is_opened_by_its_address(self):
        # De Gruyter (2026-11-02): "Add institutional access" (/login, its WAYF) in a closed menu.
        self.html = ("<title>Article</title><h1>Article</h1><div style='display:none'>"
                     "<a href='/publishing/for-librarians'>Information for institutions</a>"
                     "<a href='/register'>Register for institutional access</a>"
                     "<a href='/login' class='addAccess'>Add institutional access</a></div>")
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.url, "https://ascelibrary.org/login")
        self.assertEqual(self.requests, [ARTICLE, "https://ascelibrary.org/login"])
        self.assertIn('"Add institutional access" -> https://ascelibrary.org/login', self.result.events[-1]["detail"])

    def test_a_seamlessaccess_button_opens_a_search_box_where_the_school_is_found(self):
        # De Gruyter's LibLynx page (2026-11-02): the standard SeamlessAccess button opens
        # a search box named only by its id; the school is listed as "<school>, Library".
        self.html = """<title>Where Are You From</title>
            <button class="ra21-button" id="idpbutton" onclick="openPicker()">Access through your institution</button>
            <iframe src="https://service.seamlessaccess.org/ps/"></iframe>
            <div id="picker" hidden><input type="search" id="institutionsearch" oninput="search(this.value)"><ul id="found"></ul></div>
            <script>
              function openPicker() { document.getElementById('picker').hidden = false; location.hash = 'institutionpicker'; }
              function search(value) {
                const found = document.getElementById('found');
                found.innerHTML = '';
                if (value.length < 4) return;
                for (const [name, target] of [['National Synthetic University A', ''],
                                              ['Synthetic University A, Library', 'https://idp.synthetic-a.example/login']]) {
                  const a = document.createElement('a');
                  a.href = '#'; a.className = 'institution'; a.textContent = name;
                  a.onclick = () => { if (target) location.href = target; return false; };
                  const li = document.createElement('li'); li.append(a); found.append(li);
                }
              }
            </script>"""
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._select_institution(self.page, self.result))  # the button
        self.assertTrue(self.d._select_institution(self.page, self.result))  # the search and the school
        self.page.wait_for_url("https://idp.synthetic-a.example/login")
        states = [e["state"] for e in self.result.events]
        self.assertIn("seamlessaccess_chooser_opened", states)
        self.assertIn("auto_institution_search", states, self.result.events)

    def test_a_link_to_the_login_page_and_a_menu_without_institution_login_are_left_alone(self):
        self.html = f"<title>Article</title><h1>Article</h1><a href=\"{LOGIN_PAGE}\">Login / Register</a>"
        self.page.goto(ARTICLE)
        self.assertFalse(self.d._click_sso_entry(self.page, self.result))
        self.assertEqual(self.requests, [ARTICLE])
        self.html = ("<title>Article</title><h1>Article</h1>"
                     "<button onclick=\"document.getElementById('m').hidden=false\">Get access</button>"
                     "<div id='m' hidden><a href='/action/registration'>Register</a>"
                     "<a href='/action/purchase'>Buy this article</a></div>")
        self.page.goto(ARTICLE)
        self.result.events.clear()
        self.assertFalse(self.d._click_sso_entry(self.page, self.result))
        self.assertEqual(self.requests, [ARTICLE, ARTICLE])
        self.assertEqual([e["state"] for e in self.result.events], ["access_menu_opened"])


    def test_a_hidden_institution_sign_in_is_followed_never_the_personal_one(self):
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"},
                                          profile=get_publisher_profile("jama"), institution_query="Synthetic University A")
        pages = {JAMA_ARTICLE: "<title>Article</title><h1>Article</h1>" + JAMA_MENU}
        self.context.unroute("**/*")

        def respond(route):
            self.requests.append(route.request.url)
            route.fulfill(status=200, content_type="text/html", body=pages.get(route.request.url, "<title>Chooser</title>"))
        self.context.route("**/*", respond)
        self.page.goto(JAMA_ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.url, JAMA_SIGN_IN)
        self.assertEqual(self.requests, [JAMA_ARTICLE, JAMA_SIGN_IN])


if __name__ == "__main__":
    unittest.main()
