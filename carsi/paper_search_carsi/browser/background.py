"""The owned Camoufox's bundled background helper; no native input or global hooks.

The helper is an internal Firefox experiment because window activation belongs
in browser chrome, outside web pages. It has no network/content permissions and
is not installed in a user's normal browser. Camoufox's version is pinned.
"""
from __future__ import annotations

import json
import hashlib
import io
import time
import zipfile
from pathlib import Path
from typing import Any

ADDON_ID = "background@papersearch.local"
ADDON_DIR = Path(__file__).resolve().parents[1] / "assets" / "quiet-browser"


def install_startup_helper(profile: Path) -> None:
    """Load before Windows creates its first window, inside the owned profile only."""
    files = {p.name: p.read_bytes() for p in sorted(ADDON_DIR.iterdir()) if p.is_file()}
    version = int.from_bytes(hashlib.sha256(b"".join(files.values())).digest()[:3], "big")
    manifest = json.loads(files["manifest.json"])
    manifest["version"] = f"1.0.{version}"
    files["manifest.json"] = json.dumps(manifest).encode()
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(zipfile.ZipInfo(name), content)
    target = profile / "extensions" / (ADDON_ID + ".xpi")
    content = data.getvalue()
    if target.is_file() and target.read_bytes() == content:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(content)
    temporary.replace(target)


def options(opts: dict[str, Any]) -> None:
    """Configure only this launch; the shared installed browser is never patched."""
    addons = list(opts.get("addons") or [])
    if str(ADDON_DIR) not in addons:
        addons.append(str(ADDON_DIR))
    opts["addons"] = addons
    prefs = opts["firefox_user_prefs"]
    prefs.update({"extensions.experiments.enabled": True,
                  "layout.throttled_frame_rate": 60})


def ready(profile: Path, session: str) -> None:
    """Verify before visiting any site; never claim quiet mode if the helper failed."""
    path = profile / "papersearch-background.json"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if path.stat().st_size <= 4096:
                result = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(result, dict) and result.get("session") == session:
                    if result.get("ready") is True:
                        return
                    raise RuntimeError("Camoufox background helper initialization failed")
        except (OSError, ValueError):
            pass  # not written yet, or the atomic write is still being replaced
        time.sleep(.05)
    raise RuntimeError("Camoufox background helper did not initialize within 10 seconds")
