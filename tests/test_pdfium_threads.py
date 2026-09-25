"""Regression: pypdfium2 is not thread-safe, and extraction workers are threads
in one process.  Rasterising scanned PDFs concurrently without serialising the
PDFium calls raises "Could not rasterize scanned PDF pages: Failed to load
document (PDFium: Data format error)" or "Failed to load page." on files that
load cleanly single-threaded.  The fixtures are small image-only PDFs generated
here; OCR is stubbed so only the rasterisation path runs, and small pages keep
document loads (where the race lives) dense.  The test is a gate on the
aggregate of several rounds so that it is red against the unlocked code every
run, not most runs."""

from __future__ import annotations

import collections
import importlib.util
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import extraction
from backend.extraction import ExtractionLimits, _ocr_pdf_pages

PDFIUM_AVAILABLE = importlib.util.find_spec("pypdfium2") is not None


def _make_scanned_pdf(path: Path, pages: int) -> None:
    from PIL import Image, ImageDraw

    images = []
    for index in range(pages):
        image = Image.new("RGB", (300, 200), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 290, 190), outline="black", width=3)
        draw.text((20, 20), f"SYNTHETIC SCANNED PAGE {index + 1}", fill="black")
        images.append(image)
    images[0].save(path, "PDF", save_all=True, append_images=images[1:], resolution=72)
    for image in images:
        image.close()


@unittest.skipUnless(PDFIUM_AVAILABLE, "pypdfium2 is required")
class ConcurrentRasterisationTests(unittest.TestCase):
    ROUNDS = 3
    THREADS = 8
    SECONDS_PER_ROUND = 1.5

    def test_concurrent_rasterisation_never_fails_to_load_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index in range(6):
                path = Path(directory) / f"scan-{index}.pdf"
                _make_scanned_pdf(path, pages=2)
                paths.append(path)
            limits = ExtractionLimits()
            errors: collections.Counter[str] = collections.Counter()
            completed: list[int] = []

            def worker(offset: int, deadline: float) -> None:
                cursor = offset
                while time.monotonic() < deadline:
                    path = paths[cursor % len(paths)]
                    cursor += self.THREADS
                    try:
                        completed.append(len(_ocr_pdf_pages(path, [0, 1], limits)))
                    except Exception as exc:  # noqa: BLE001 - counted, then asserted below
                        errors[f"{type(exc).__name__}: {exc}"[:120]] += 1

            with patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"), patch.object(
                extraction, "_run_tesseract", return_value=("stub", 90.0)
            ):
                # Single-threaded baseline: every fixture rasterises on its own.
                for path in paths:
                    self.assertEqual(len(_ocr_pdf_pages(path, [0, 1], limits)), 2)
                for _ in range(self.ROUNDS):
                    deadline = time.monotonic() + self.SECONDS_PER_ROUND
                    threads = [
                        threading.Thread(target=worker, args=(index, deadline))
                        for index in range(self.THREADS)
                    ]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()

        # Structure first: the workers really rasterised documents concurrently.
        self.assertGreaterEqual(len(completed), 8 * self.ROUNDS, completed)
        self.assertTrue(all(count == 2 for count in completed), completed)
        self.assertEqual(dict(errors), {}, "concurrent PDFium use failed")
