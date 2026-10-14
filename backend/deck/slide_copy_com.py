"""High-fidelity slide structural surgery via PowerPoint COM automation.

python-pptx cannot reliably copy a slide (with its native charts, embedded
workbooks, and images) from one presentation into another, or reorder slides,
without fragile hand-written XML surgery. PowerPoint itself does this
perfectly via its own object model, so we drive a real (minimized) PowerPoint
instance through win32com for all structural changes (delete / duplicate /
insert-from-file), then hand back to python-pptx for text edits.

Only used on Windows with PowerPoint installed.
"""
from __future__ import annotations

from pathlib import Path

PP_WINDOW_MINIMIZED = 2


class DeckSurgeon:
    """One COM session driving structural slide surgery on a single
    destination deck, pulling slides from arbitrary source decks.

    Usage:
        with DeckSurgeon() as surgeon:
            surgeon.open_dest(output_path)
            surgeon.delete_slide(16)
            ...
            surgeon.save()
    """

    def __init__(self):
        self.app = None
        self.dest = None
        self._dest_path: str = ""

    def __enter__(self) -> "DeckSurgeon":
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        self.app = win32com.client.DispatchEx("PowerPoint.Application")
        try:
            self.app.Visible = True
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import pythoncom
        if self.dest is not None:
            try:
                self.dest.Close()
            except Exception:
                pass
        if self.app is not None:
            try:
                self.app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    def open_dest(self, path: str) -> None:
        self._dest_path = str(Path(path).resolve())
        self.dest = self.app.Presentations.Open(
            self._dest_path, ReadOnly=False, Untitled=False, WithWindow=True
        )
        try:
            self.dest.Windows(1).WindowState = PP_WINDOW_MINIMIZED
        except Exception:
            pass

    def delete_slide(self, index: int) -> None:
        """1-based index."""
        self.dest.Slides(index).Delete()

    def duplicate_slide(self, index: int) -> int:
        """Duplicates slide at 1-based index; the copy lands at index+1.
        Returns the new slide's 1-based index."""
        dup = self.dest.Slides(index).Duplicate()
        return dup(1).SlideIndex

    def paste_slide(self, source_deck: str, source_slide_no: int, dest_index: int) -> int:
        """Inserts slide source_slide_no (1-based) from source_deck into the
        destination deck at dest_index (1-based). Uses InsertFromFile which
        reads directly from disk — no clipboard needed. Returns the resulting
        1-based index."""
        source_path = str(Path(source_deck).resolve())
        self.dest.Slides.InsertFromFile(source_path, dest_index - 1, source_slide_no, source_slide_no)
        return dest_index

    def slide_count(self) -> int:
        return self.dest.Slides.Count

    def save(self) -> None:
        self.dest.Save()
