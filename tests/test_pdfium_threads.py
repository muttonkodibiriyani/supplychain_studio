"""Regression: pypdfium2 is not thread-safe, and extraction workers are threads
in one process.  Rasterising scanned PDFs concurrently without serialising the
PDFium calls raises "Could not rasterize scanned PDF pages: Failed to load
document (PDFium: Data format error)" or "Failed to load page." on files that
load cleanly single-threaded.

The gating test is structural: the pypdfium2 entry points the lock guards
(document load, page access, page size, render, bitmap copy, close) are
replaced by probes that record an entry/exit interval per thread and hold a
barrier open inside the call.  Serialised calls can never satisfy the barrier
and never overlap; with the lock replaced by a no-op every worker enters the
document load together, the barrier passes and the intervals overlap, so the
test fails on every run without depending on a race.

The race test that follows is a non-gating stress check.  Its limits: against
the unlocked code it passes 4 of 4 runs at the shipped settings (8 threads, 3
rounds of 1.5 s) and fails only 1 of 4 runs at 16 threads / 4 s (an independent
review run on c8b291b), so it cannot gate.  It runs only with PDFIUM_STRESS=1.
"""

from __future__ import annotations

import collections
import importlib.util
import os
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
class PdfiumSerialisationTests(unittest.TestCase):
    """Structural assertion that every guarded pypdfium2 call is serialised."""

    THREADS = 8  # the documented raise-to value (.env.example), above the shipped default of 4

    def test_guarded_pdfium_calls_never_overlap_across_threads(self) -> None:
        import pypdfium2

        real_document = pypdfium2.PdfDocument
        intervals: list[tuple[str, int, float, float]] = []
        state_lock = threading.Lock()
        inside = {"count": 0, "max": 0}
        # Passes only if THREADS workers are inside a probed call at once.
        barrier = threading.Barrier(self.THREADS, timeout=1.0)
        barrier_passed = {"count": 0}

        def probed(name, function):
            def call(*args, **kwargs):
                started = time.monotonic()
                with state_lock:
                    inside["count"] += 1
                    inside["max"] = max(inside["max"], inside["count"])
                try:
                    try:
                        barrier.wait()
                        with state_lock:
                            barrier_passed["count"] += 1
                    except threading.BrokenBarrierError:
                        pass
                    return function(*args, **kwargs)
                finally:
                    with state_lock:
                        inside["count"] -= 1
                        intervals.append((name, threading.get_ident(), started, time.monotonic()))

            return call

        class ProbeBitmap:
            def __init__(self, bitmap):
                self._bitmap = bitmap
                self.to_pil = probed("bitmap.to_pil", bitmap.to_pil)
                self.close = probed("bitmap.close", bitmap.close)

        class ProbePage:
            def __init__(self, page):
                self._page = page
                self.get_size = probed("page.get_size", page.get_size)
                self.close = probed("page.close", page.close)

            def render(self, *args, **kwargs):
                return ProbeBitmap(probed("page.render", self._page.render)(*args, **kwargs))

        class ProbeDocument:
            def __init__(self, *args, **kwargs):
                self._document = probed("PdfDocument", real_document)(*args, **kwargs)
                self.close = probed("document.close", self._document.close)

            def __len__(self):
                return len(self._document)

            def __getitem__(self, index):
                return ProbePage(probed("document[index]", self._document.__getitem__)(index))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.pdf"
            _make_scanned_pdf(path, pages=2)
            limits = ExtractionLimits()
            errors: list[str] = []

            def worker() -> None:
                try:
                    _ocr_pdf_pages(path, [0, 1], limits)
                except Exception as exc:  # noqa: BLE001 - asserted below
                    errors.append(f"{type(exc).__name__}: {exc}"[:120])

            with patch.object(pypdfium2, "PdfDocument", ProbeDocument), patch.object(
                extraction.shutil, "which", return_value="/usr/bin/tesseract"
            ), patch.object(extraction, "_run_tesseract", return_value=("stub", 90.0)):
                threads = [threading.Thread(target=worker) for _ in range(self.THREADS)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

        self.assertEqual(errors, [])
        probed_names = {name for name, _, _, _ in intervals}
        self.assertTrue(
            {"PdfDocument", "document[index]", "page.get_size", "page.render", "bitmap.to_pil", "document.close"}
            <= probed_names,
            probed_names,
        )
        self.assertGreaterEqual(len({thread for _, thread, _, _ in intervals}), self.THREADS)
        overlaps = [
            (first, second)
            for index, first in enumerate(intervals)
            for second in intervals[index + 1 :]
            if first[1] != second[1] and first[2] < second[3] and second[2] < first[3]
        ]
        self.assertEqual(
            len(overlaps),
            0,
            f"{len(overlaps)} overlapping guarded pypdfium2 intervals across threads, "
            f"first: {overlaps[0][0][0]} vs {overlaps[0][1][0]}" if overlaps else "",
        )
        self.assertEqual(inside["max"], 1, "more than one thread inside a guarded call at once")
        self.assertEqual(barrier_passed["count"], 0, "all workers entered a guarded call together")


@unittest.skipUnless(PDFIUM_AVAILABLE, "pypdfium2 is required")
@unittest.skipUnless(os.environ.get("PDFIUM_STRESS") == "1", "non-gating stress check; set PDFIUM_STRESS=1")
class ConcurrentRasterisationStressTests(unittest.TestCase):
    """Non-gating stress check.  See the module docstring for its limits: it
    does not fail reliably against the unlocked code and must not be read as
    proof of serialisation."""

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
    number that ran out is the document budget and the message must say so.

    A missed time budget is retryable, so the message also carries the retry
    hint.  What these tests pin is which budget gets named; the hint is
    asserted with it so neither change can silently drop the other."""

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
            self.assertEqual(
                message,
                "OCR exceeded the 180 second document limit; "
                "try again when the host is quieter.",
                remaining,
            )

    def test_full_page_budget_is_still_reported_per_page(self) -> None:
        limits = ExtractionLimits(ocr_timeout_seconds_per_page=45.0, ocr_timeout_seconds_total=180.0)
        self.assertEqual(
            self._timeout_message(45.0, limits),
            "OCR page exceeded its 45 second limit; try again when the host is quieter.",
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
        self.assertEqual(
            str(raised.exception),
            "OCR page exceeded its 5 second limit; try again when the host is quieter.",
        )
