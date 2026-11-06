"""Build the bundled notification helper for Apple Silicon and Intel Macs.

Maintainer-only: end users run the bundled executable, without Xcode or a compiler.
"""
from pathlib import Path
import subprocess
import sys

if sys.platform != "darwin":
    raise SystemExit("Build this helper on macOS with Apple's command line tools")
root = Path(__file__).resolve().parents[1]
subprocess.run([
    "xcrun", "clang", "-fobjc-arc", "-O2", "-arch", "arm64", "-arch", "x86_64",
    "-mmacosx-version-min=11.0", "-Wno-deprecated-declarations",
    "-framework", "AppKit", "-framework", "CoreServices",
    str(root / "tools/macos-notifier.m"), "-o",
    str(root / "paper_search_carsi/assets/papersearch-notifier"),
], check=True)
