"""A captured PDF reaches the download folder on another drive (Windows, 2026-11-11)."""
import errno
import os
from pathlib import Path

from paper_search_school.engine import bridge


def test_a_pdf_moves_across_drives_when_a_rename_cannot(tmp_path, monkeypatch):
    run_dir = tmp_path / "C" / "runs" / "diagnostics" / "work-x" / "run" / "pdfs"
    run_dir.mkdir(parents=True)
    src = run_dir / "10.1016_j.stem.pdf"
    src.write_bytes(b"%PDF-1.7 captured")
    output = tmp_path / "D" / "Downloads" / "topic" / "Cell Stem Cell_2026_A study.pdf"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"%PDF-1.7 an older copy")

    def cross_drive(a, b):  # what Windows answers from C: to D: (WinError 17)
        raise OSError(errno.EXDEV, "The system cannot move the file to a different disk drive")

    monkeypatch.setattr(os, "rename", cross_drive)
    bridge._move_into_place(src, output)
    assert output.read_bytes() == b"%PDF-1.7 captured"
    assert not src.exists()


def test_a_missing_download_folder_is_made(tmp_path):
    src = tmp_path / "pdfs" / "a.pdf"
    src.parent.mkdir()
    src.write_bytes(b"%PDF-1.7")
    output = tmp_path / "new" / "folder" / "a.pdf"
    bridge._move_into_place(src, output)
    assert output.exists() and not src.exists()
