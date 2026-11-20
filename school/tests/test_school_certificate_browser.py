"""A school's login page whose certificate Chrome will not take (one tested had run out in 2022), in a real
Chrome: its warning read, passed for the very certificate Pro's survey saw there only, and that certificate
read again on the page (school_login.page_certificate, warning_for, pass_warning; the login wait's
_past_school_certificate_warning). A made-up school served on this computer with a certificate of its own,
reached from a publisher's page by a redirect, as a sign-in is. Opt-in: SCHOOL_LOCAL_BROWSER_TEST=1
(SCHOOL_TEST_BROWSER: a Chromium to run instead of Google Chrome)."""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import os
import ssl
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_search_school import school_login
from paper_search_school.engine import batch_login

SCHOOL = "cas.hongmulan.test"
PUBLISHER = "www.publisher.test"
PAGE = "<html><head><title>红木兰大学统一身份认证</title></head><body><input name=username><input type=password></body></html>"


def certificate(folder: Path, name: str) -> tuple[Path, Path, str]:
    """A certificate of its own for ``name`` (no authority Chrome trusts), its key, and its SHA-256."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_file, key_file = folder / f"{name}-{id(key)}.crt", folder / f"{name}-{id(key)}.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_file, key_file, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


class _School(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(handler, cert: tuple[Path, Path] | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    if cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*cert)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1" and importlib.util.find_spec("cryptography"),
                     "local Chrome fixture opt-in, with cryptography for the certificate")
class ALoginPageWithACertificateChromeWillNotTake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        *files, cls.digest = certificate(Path(folder.name), SCHOOL)
        cls.school = serve(_School, tuple(files))
        cls.addClassCleanup(cls.school.shutdown)
        port = cls.school.server_address[1]
        cls.url = f"https://{SCHOOL}:{port}/cas/login"

        class Publisher(BaseHTTPRequestHandler):  # its sign-in sends the browser on to the school's page
            def do_GET(self):  # noqa: N802
                self.send_response(302)
                self.send_header("Location", cls.url)
                self.end_headers()

            def log_message(self, *args):
                pass

        cls.publisher = serve(Publisher)
        cls.addClassCleanup(cls.publisher.shutdown)
        cls.start = f"http://{PUBLISHER}:{cls.publisher.server_address[1]}/action/ssostart"
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        own = os.environ.get("SCHOOL_TEST_BROWSER")
        cls.browser = cls.driver.chromium.launch(
            **({"executable_path": own} if own else {"channel": "chrome"}), headless=True,
            args=["--disable-background-networking", "--no-proxy-server",
                  f"--host-resolver-rules=MAP {SCHOOL} 127.0.0.1, MAP {PUBLISHER} 127.0.0.1, MAP * ~NOTFOUND"])
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context()  # Chrome's "proceed" kept per context: each test its own
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()

    def at_the_warning(self) -> None:
        try:
            self.page.goto(self.start, wait_until="domcontentloaded", timeout=15_000)
        except Exception:
            pass  # Chrome's warning: the page did not load
        self.page.wait_for_timeout(1000)

    def test_the_warning_read_passed_and_the_certificate_read_again(self):
        self.at_the_warning()
        self.assertEqual(school_login.warning_for(self.page, ("other.example", SCHOOL)), SCHOOL)
        self.assertEqual(school_login.warning_for(self.page, ("other.example",)), "")  # not a page Pro has one for
        error, digest = school_login.page_certificate(self.page)  # on the warning: the one offered
        self.assertEqual((error, digest), ("net::ERR_CERT_AUTHORITY_INVALID", self.digest))
        self.assertTrue(school_login.warning_certificate(SCHOOL, error, digest, {SCHOOL: self.digest}))
        self.assertTrue(school_login.pass_warning(self.page, SCHOOL))
        self.assertIn("统一身份认证", self.page.title())
        self.assertEqual(school_login.page_certificate(self.page), (error, self.digest))

    def test_a_valid_page_reads_as_one_chrome_takes(self):
        self.page.set_content("<p>x</p>")
        self.assertEqual(school_login.page_certificate(self.page)[0], "")

    def login_wait(self, pins: dict[str, str]) -> tuple[bool, SimpleNamespace, list]:
        events: list = []
        pro = SimpleNamespace(certificates=lambda entity: pins)
        d = SimpleNamespace(config={"idp_entity_id": "https://idp.hongmulan.test/idp/shibboleth"},
                            _event=lambda result, state, detail="": events.append((state, detail)))
        result = SimpleNamespace()
        with patch.object(school_login, "saved", return_value={"enabled": True, "username": "u", "password": "p"}), \
                patch.object(school_login, "module", return_value=pro):
            went = batch_login.LoginMixin._past_school_certificate_warning(d, self.page, result)
        return went, result, events

    def test_the_login_wait_passes_it_for_the_certificate_surveyed(self):
        self.at_the_warning()
        went, result, events = self.login_wait({SCHOOL: self.digest})
        self.assertTrue(went, events)
        self.assertIn("统一身份认证", self.page.title())
        self.assertFalse(hasattr(result, "_sign_in_note"))

    def test_the_login_wait_leaves_another_certificate_to_the_user(self):
        self.at_the_warning()
        went, result, events = self.login_wait({SCHOOL: "0" * 64})
        self.assertFalse(went)
        self.assertEqual(result._sign_in_note, batch_login.SIGN_IN_CERTIFICATE)
        self.assertEqual(school_login.warning_for(self.page, (SCHOOL,)), SCHOOL)  # still at Chrome's warning
        self.assertIn("not the certificate surveyed", events[-1][1])


if __name__ == "__main__":
    unittest.main()
