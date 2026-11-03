"""Diagnostic files are written unmasked; manifests and CSV stay allowlisted."""
import unittest
from types import SimpleNamespace

from paper_search_carsi.download_diagnostics import serialize_download_result

SIGNED = "https://pdf.sciencedirectassets.com/271/main.pdf?X-Amz-Security-Token=fixture-token&X-Amz-Signature=abc"


def result():
    return SimpleNamespace(
        doi="10.1016/j.fixture.2025.01.001", status="failed", state="ip_blocked", reason="ip_blocked",
        title="Fixture", article_url="https://www.sciencedirect.com/science/article/pii/S1",
        final_url=SIGNED, pdf_url=SIGNED, size_bytes=0, text_length=0, verified_match=False,
        events=[{"state": "pdf_button_clicked", "detail": "a.pdf-download"},
                {"state": "ip_blocked_response", "detail": "403 " + SIGNED},
                {"state": "brand_new_event", "detail": "cookie=fixture-session"}])


class DiagnosticUnmaskedTests(unittest.TestCase):
    def test_diagnostic_keeps_full_details_urls_and_unknown_events(self):
        packet = serialize_download_result(result(), diagnostic=True)
        self.assertEqual(packet["final_url"], SIGNED)
        self.assertEqual(packet["pdf_url"], SIGNED)
        self.assertEqual(packet["events"][1], {"state": "ip_blocked_response", "detail": "403 " + SIGNED})
        self.assertEqual(packet["events"][2]["state"], "brand_new_event")
        self.assertEqual(packet["events"][2]["detail"], "cookie=fixture-session")
        self.assertEqual(packet["final_url_role"], "external")

    def test_default_mode_is_still_allowlisted(self):
        packet = serialize_download_result(result())
        self.assertNotIn("final_url", packet)
        self.assertNotIn("fixture-token", str(packet))
        self.assertEqual(packet["events"][2], {"state": "unknown"})


if __name__ == "__main__":
    unittest.main()
