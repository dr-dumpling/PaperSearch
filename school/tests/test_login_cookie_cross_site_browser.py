"""In Chrome itself: a school sign-in's session cookie set as Lax is left out of a publisher's
cross-site SAML POST, and goes with it once ``cross_site_login`` has re-set it (a school
tested, 2026-11-19: Nature, Taylor & Francis and Science asked for the password again; opt-in)."""
from __future__ import annotations

import os
import unittest

from paper_search_school.browser import profiles

IDP_LOGIN = "https://idp.school.example/idp/login"
IDP_POST = "https://idp.school.example/idp/profile/SAML2/POST/SSO"
SP_START = "https://www.publisher.example/action/ssostart"

# The publisher's page that sends the SAML request with a form, as Nature and Atypon do.
SP_HTML = f"""<title>Redirecting</title><form method="post" action="{IDP_POST}">
<input type="hidden" name="SAMLRequest" value="fixture"></form>
<script>document.forms[0].submit();</script>"""


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class CrossSiteLoginCookieTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True,
            args=["--disable-background-networking", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"])
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.sent: list[str] = []

        def respond(route):
            request = route.request
            url = request.url.split("?", 1)[0]
            if url == IDP_LOGIN:
                # A sign-in that names Lax itself (one that names nothing gets Lax as well).
                route.fulfill(status=200, content_type="text/html", body="<title>Signed in</title>",
                              headers={"Set-Cookie": "shib_idp_session=abc; Path=/idp; SameSite=Lax; Secure; HttpOnly"})
            elif url == IDP_POST:
                self.sent.append(request.headers.get("cookie", ""))
                route.fulfill(status=200, content_type="text/html", body="<title>信息释放</title>")
            elif url == SP_START:
                route.fulfill(status=200, content_type="text/html", body=SP_HTML)
            else:
                route.fulfill(status=404, body="")

        self.context.route("**/*", respond)
        self.page = self.context.new_page()

    def post_from_the_publisher(self) -> str:
        self.page.goto(SP_START)
        self.page.wait_for_url(IDP_POST)
        return self.sent[-1]

    def test_the_schools_session_goes_with_the_publishers_post_once_re_set(self):
        self.page.goto(IDP_LOGIN)
        self.assertNotIn("shib_idp_session", self.post_from_the_publisher())
        self.assertEqual(profiles.cross_site_login(self.context, {"idp.school.example"}), 1)
        cookie = next(c for c in self.context.cookies() if c["name"] == "shib_idp_session")
        self.assertEqual((cookie["sameSite"], cookie["secure"], cookie["httpOnly"]), ("None", True, True))
        self.assertIn("shib_idp_session=abc", self.post_from_the_publisher())

    def test_a_publishers_cookie_is_left_as_it_is(self):
        self.context.add_cookies([{"name": "publisher", "value": "p", "domain": "www.publisher.example", "path": "/",
                                   "sameSite": "Lax", "secure": True}])
        self.page.goto(IDP_LOGIN)
        profiles.cross_site_login(self.context, {"idp.school.example"}, {"school.example"})
        same = {c["name"]: c["sameSite"] for c in self.context.cookies()}
        self.assertEqual(same, {"publisher": "Lax", "shib_idp_session": "None"})


if __name__ == "__main__":
    unittest.main()
