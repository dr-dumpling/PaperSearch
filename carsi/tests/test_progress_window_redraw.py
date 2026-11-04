"""Real Tk regression for the Windows handoff's growing Canvas callbacks.

Opt in with CARSI_LOCAL_GUI_TEST=1 on a desktop; no real task/config is read.
"""
import os
import re
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CARSI_LOCAL_GUI_TEST") != "1",
                                reason="local Tk desktop opt-in")


@pytest.fixture
def window():
    from paper_search_carsi.progress_bar import ProgressWindow

    window = ProgressWindow()
    for timer in window.root.tk.call("after", "info"):
        window.root.after_cancel(timer)
    window.root.withdraw()
    yield window
    window.root.destroy()


def state(**changes):
    return {"status": "running", "run_id": "redraw-fixture", "current": "10.1000/first",
            "total": 8, "done": 5, "success": 2, "failed": 3, "output_dir": "fixture-output",
            "stage": "fetching_pdf", "part": "main", **changes}


def invoke(window, tag, sequence="<Button-1>"):
    # Invoke the registered Tcl command: Tk's event substitution passes the
    # synthetic event through, and these handlers only consume captured state.
    script = window.canvas.tag_bind(tag, sequence)
    command = re.search(r"\[([^\s]+)", script).group(1)
    window.root.tk.call(command, "synthetic-event")


def test_redrawing_keeps_callbacks_and_canvas_items_bounded(window):
    window._draw(state())
    callbacks = len(window.canvas._tclCommands)
    commands = len(window.root.tk.call("info", "commands"))
    items = len(window.canvas.find_all())
    for _ in range(300):
        window._draw(state())
    assert len(window.canvas._tclCommands) == callbacks
    assert len(window.root.tk.call("info", "commands")) == commands
    assert len(window.canvas.find_all()) == items


def test_redrawn_buttons_use_current_paper_and_release_absent_controls(window):
    window._decide = Mock()
    window._open_output_dir = Mock()
    window._open_settings = Mock()
    window._draw(state())
    current = state(current="10.1000/second", run_id="second-run", output_dir="second-output")
    window._draw(current)
    invoke(window, "btn-skip_item")
    window._decide.assert_called_once_with("skip_item", current["current"], current)
    invoke(window, "outdir")
    window._open_output_dir.assert_called_once_with(current)
    window._draw(None)
    assert not window.canvas.tag_bind("btn-skip_item", "<Button-1>")
    assert not window.canvas.tag_bind("outdir", "<Button-1>")
    invoke(window, "settings")
    window._open_settings.assert_called_once()
