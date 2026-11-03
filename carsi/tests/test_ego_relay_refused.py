"""When ego refuses the relay, the backend says so at once instead of waiting 90 s."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_search_carsi.browser import backend


class EgoRelayRefusedTests(unittest.TestCase):
    def test_a_refused_relay_ends_the_wait_with_its_reason(self):
        state = Path(tempfile.mkdtemp()) / "ego-relay.json"
        log = state.with_suffix(".log")
        log.write_text("earlier run\n")

        def start_relay(*_a, stdout=None, **_kw):
            stdout.write(b"Traceback (most recent call last):\n  File x\n"
                         b"websockets.exceptions.InvalidStatus: server rejected WebSocket connection: HTTP 403\n")
            return Mock(poll=Mock(return_value=1))

        with patch.object(backend, "_relay_state_file", return_value=state), \
                patch("subprocess.Popen", side_effect=start_relay), \
                patch.object(backend.time, "sleep"):
            with self.assertRaises(backend.EgoUnavailable) as raised:
                backend._relay_endpoint("ws://127.0.0.1:1/devtools/browser/x")
        self.assertIn("server rejected WebSocket connection: HTTP 403", str(raised.exception))
        self.assertIn("Bring ego to the front", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
