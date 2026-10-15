from __future__ import annotations

import sys
from pathlib import Path
import ctypes

import win32com.client


def render(path: Path, out_dir: Path) -> None:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / (path.stem + ".pdf")
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    # Word COM on this machine intermittently misreads CJK paths through the
    # automation layer.  Use the filesystem's short path for opening only.
    buf = ctypes.create_unicode_buffer(4096)
    absolute = str(path.resolve())
    ctypes.windll.kernel32.GetShortPathNameW(absolute, buf, len(buf))
    open_path = buf.value or absolute
    doc = word.Documents.Open(open_path, ReadOnly=True, AddToRecentFiles=False)
    try:
        doc.ExportAsFixedFormat(str(pdf), 17, False, 0, 0, 1, 1, 0, True, False, 0, True, True, False)
    finally:
        doc.Close(False)
        word.Quit()
    print(pdf)


if __name__ == "__main__":
    render(Path(sys.argv[1]), Path(sys.argv[2]))

