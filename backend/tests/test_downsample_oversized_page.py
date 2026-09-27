"""Pages above the rendered-pixel cap are downsampled with a warning, not refused.

The cap is a rendering cap, not a content bound: the per-page and per-document
pixel bounds still apply to the reduced page, and a page that fits the cap
renders exactly as before.
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend import extraction
from backend.extraction import (
    ExtractionLimitError,
    ExtractionLimits,
    _fit_render_scale,
    _ocr_pdf_pages,
)

CAP = ExtractionLimits().max_render_pixels_per_page
# A page box that rasterises above the cap at the standard 2 px/pt.
OVERSIZED_PT = (2480.0, 3507.0)
A4_PT = (595.0, 842.0)


class _FakeBitmap:
    def __init__(self, size: tuple[int, int]) -> None:
        self._size = size

    def to_pil(self) -> Image.Image:
        return Image.new("L", self._size, 255)

    def close(self) -> None:
        pass


class _FakePage:
    def __init__(self, size_pt: tuple[float, float]) -> None:
        self._size_pt = size_pt
        self.render_scales: list[float] = []

    def get_size(self) -> tuple[float, float]:
        return self._size_pt

    def render(self, scale: float) -> _FakeBitmap:
        self.render_scales.append(scale)
        width, height = self._size_pt
        return _FakeBitmap((int(width * scale), int(height * scale)))

    def close(self) -> None:
        pass


class _FakeDocument:
    pages: list[_FakePage] = []

    def __init__(self, _path: str) -> None:
        pass

    def __getitem__(self, index: int) -> _FakePage:
        return self.pages[index]

    def close(self) -> None:
        pass


def _fake_pdfium(*sizes_pt: tuple[float, float]) -> tuple[types.ModuleType, list[_FakePage]]:
    pages = [_FakePage(size) for size in sizes_pt]
    _FakeDocument.pages = pages
    module = types.ModuleType("pypdfium2")
    module.PdfDocument = _FakeDocument  # type: ignore[attr-defined]
    return module, pages


class _OcrCapture:
    def __init__(self) -> None:
        self.sizes: list[tuple[int, int]] = []
        self.dpis: list[int | None] = []

    # Mirrors ``extraction._run_tesseract`` exactly, keyword-only tail included,
    # so a signature change there fails these tests instead of passing silently.
    def __call__(
        self,
        image,
        timeout,
        max_pixels,
        *,
        psm=6,
        autocontrast=False,
        dpi=None,
        timeout_message=None,
    ):
        self.sizes.append(image.size)
        self.dpis.append(dpi)
        return "Invoice 1\nTotal 5.00\n", 90.0


def _run_pdf(sizes_pt, limits: ExtractionLimits):
    module, pages = _fake_pdfium(*sizes_pt)
    capture = _OcrCapture()
    warnings: list[str] = []
    with (
        patch.dict(sys.modules, {"pypdfium2": module}),
        patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"),
        patch.object(extraction, "_run_tesseract", capture),
    ):
        results = _ocr_pdf_pages(Path("unused.pdf"), range(len(sizes_pt)), limits, warnings=warnings)
    return results, pages, capture, warnings


class FitRenderScaleTests(unittest.TestCase):
    def test_page_under_cap_keeps_its_scale_exactly(self) -> None:
        self.assertEqual(_fit_render_scale(*A4_PT, 2.0, CAP), 2.0)

    def test_page_over_cap_gets_largest_fitting_scale(self) -> None:
        width, height = OVERSIZED_PT
        self.assertGreater(int(width * 2.0) * int(height * 2.0), CAP)
        scale = _fit_render_scale(width, height, 2.0, CAP)
        self.assertLess(scale, 2.0)
        self.assertLessEqual(int(width * scale) * int(height * scale), CAP)
        # Largest fitting: one step up no longer fits.
        step = scale + 0.01
        self.assertGreater(int(width * step) * int(height * step), CAP)


class PdfDownsampleTests(unittest.TestCase):
    def test_oversized_page_is_rendered_smaller_with_warning(self) -> None:
        results, pages, capture, warnings = _run_pdf([OVERSIZED_PT], ExtractionLimits())
        self.assertEqual(list(results), [0])
        (scale,) = pages[0].render_scales[:1]
        self.assertLess(scale, 2.0)
        width, height = capture.sizes[0]
        self.assertLessEqual(width * height, CAP)
        self.assertEqual(capture.dpis[0], round(72 * scale))
        self.assertEqual(len(warnings), 1)
        self.assertIn("Page 1 was rendered at", warnings[0])
        self.assertIn(str(CAP), warnings[0])

    def test_page_under_cap_renders_at_two_px_per_pt_without_warning(self) -> None:
        results, pages, capture, warnings = _run_pdf([A4_PT], ExtractionLimits())
        self.assertEqual(pages[0].render_scales[0], 2.0)
        self.assertEqual(capture.sizes[0], (int(A4_PT[0] * 2.0), int(A4_PT[1] * 2.0)))
        self.assertEqual(warnings, [])

    def test_reduced_pixels_are_what_the_document_total_counts(self) -> None:
        # The unreduced page (about 34.8M pixels) would cross this total; the
        # reduced page must not.
        limits = ExtractionLimits(max_total_pixels=CAP + 1)
        results, _, capture, _ = _run_pdf([OVERSIZED_PT], limits)
        self.assertEqual(list(results), [0])

    def test_per_page_pixel_bound_still_applies_to_the_reduced_page(self) -> None:
        limits = ExtractionLimits(max_pixels_per_page=1_000)
        with self.assertRaises(ExtractionLimitError) as ctx:
            _run_pdf([OVERSIZED_PT], limits)
        self.assertIn("per-page limit is 1000", str(ctx.exception))

    def test_cap_can_be_raised_above_the_page_so_nothing_is_reduced(self) -> None:
        # Both the cap and the content bound sit above the page; the bound is
        # untouched by the cap and would otherwise refuse the unreduced page.
        limits = ExtractionLimits(max_render_pixels_per_page=40_000_000, max_pixels_per_page=40_000_000)
        _, pages, _, warnings = _run_pdf([OVERSIZED_PT], limits)
        self.assertEqual(pages[0].render_scales[0], 2.0)
        self.assertEqual(warnings, [])


class ImageDownsampleTests(unittest.TestCase):
    def _extract(self, size: tuple[int, int], limits: ExtractionLimits | None = None):
        capture = _OcrCapture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.png"
            Image.new("L", size, 255).save(path, compress_level=1)
            with (
                patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"),
                patch.object(extraction, "_run_tesseract", capture),
            ):
                result = extraction._extract_image(path, limits or ExtractionLimits())
        return result, capture

    def test_oversized_frame_is_resized_with_warning(self) -> None:
        size = (5000, 4000)
        self.assertGreater(size[0] * size[1], CAP)
        result, capture = self._extract(size)
        width, height = capture.sizes[0]
        self.assertLessEqual(width * height, CAP)
        self.assertLess(width, size[0])
        downsample = [w for w in result["warnings"] if "downsampled" in w]
        self.assertEqual(len(downsample), 1)
        self.assertIn("Page 1 was downsampled from 5000x4000", downsample[0])
        self.assertIn(str(CAP), downsample[0])

    def test_frame_under_cap_is_passed_through_unchanged(self) -> None:
        size = (2400, 3200)
        result, capture = self._extract(size)
        self.assertEqual(capture.sizes[0], size)
        self.assertFalse([w for w in result["warnings"] if "downsampled" in w])

    def test_per_page_pixel_bound_still_applies_to_the_reduced_frame(self) -> None:
        with self.assertRaises(ExtractionLimitError):
            self._extract((5000, 4000), ExtractionLimits(max_pixels_per_page=1_000))


if __name__ == "__main__":
    unittest.main()
