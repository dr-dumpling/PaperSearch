"""In a local browser fixture the context's route is the network.

The PDF step sends a PDF address opened in the tab past every route with ``route.continue_()``
(batch_capture's ``as_sent``), so Patchright does not read a large PDF whole to write its init
script in (Cell, 2026-11-18). That passed the fixture's context route by as well: the PDF request
went to the real network, which had no host for it or, without ``MAP * ~NOTFOUND``, the
publisher's own (Ovid's "Page Not Found"), and nothing was captured (2026-11-19). Patched in for a
test, ``continue_`` falls back to the routes after it, the fixture's among them, as a real request
reaches the network. No fixture's own route calls ``continue_``.
"""
from typing import Any
from unittest.mock import patch


def network_is_the_fixture(test: Any) -> None:
    """For ``test``: a route sent on with ``continue_`` reaches the context's routes."""
    from patchright.sync_api import Route

    test.enterContext(patch.object(Route, "continue_", Route.fallback))
