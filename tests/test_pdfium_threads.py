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


class OcrBudgetMessageTests(unittest.TestCase):
    """The per-page OCR timeout is ``min(per-page limit, remaining document
    budget)``.  When the document budget clips it, a Tesseract timeout used to
    read "OCR page exceeded its 0 second limit" (or "1 second limit"); the
    number that ran out is the document budget and the message must say so."""

    def _timeout_message(self, timeout: float, limits: ExtractionLimits) -> str:
        from PIL import Image
        import subprocess

        image = Image.new("RGB", (40, 30), "white")
        try:
            with patch.object(
                extraction.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="tesseract", timeout=timeout),
            ):
                with self.assertRaises(extraction.ExtractionLimitError) as raised:
                    extraction._run_tesseract(
                        image,
                        timeout,
                        limits.max_pixels_per_page,
                        timeout_message=extraction._ocr_budget_message(timeout, limits),
                    )
        finally:
            image.close()
        return str(raised.exception)

    def test_document_budget_clipping_the_page_is_reported_as_the_document_limit(self) -> None:
        limits = ExtractionLimits(ocr_timeout_seconds_per_page=45.0, ocr_timeout_seconds_total=180.0)
        for remaining in (0.2, 1.0, 44.9):
            message = self._timeout_message(min(45.0, remaining), limits)
            self.assertEqual(message, "OCR exceeded the 180 second document limit.", remaining)

    def test_full_page_budget_is_still_reported_per_page(self) -> None:
        limits = ExtractionLimits(ocr_timeout_seconds_per_page=45.0, ocr_timeout_seconds_total=180.0)
        self.assertEqual(
            self._timeout_message(45.0, limits), "OCR page exceeded its 45 second limit."
        )

    def test_default_message_without_a_budget_label_is_unchanged(self) -> None:
        from PIL import Image
        import subprocess

        image = Image.new("RGB", (40, 30), "white")
        try:
            with patch.object(
                extraction.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="tesseract", timeout=5),
            ):
                with self.assertRaises(extraction.ExtractionLimitError) as raised:
                    extraction._run_tesseract(image, 5, 2_000_000)
        finally:
            image.close()
        self.assertEqual(str(raised.exception), "OCR page exceeded its 5 second limit.")
