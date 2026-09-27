"""The rasterisation bounds reach the extractor from settings, like the file
and page bounds do, and their defaults equal the extractor's own constants."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from backend import extraction
from backend.extraction import ExtractionLimits
from backend.service import InvoiceService, Settings, extraction_limits


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        database_path=tmp_path / "invoices.sqlite3",
        source_dir=tmp_path / "sources",
        export_dir=tmp_path / "exports",
        workers=0,
        **overrides,
    )


def test_default_settings_equal_the_extractor_constants(tmp_path: Path) -> None:
    defaults = ExtractionLimits()
    settings = _settings(tmp_path)
    assert settings.max_pixels_per_page == defaults.max_pixels_per_page == 30_000_000
    assert settings.max_total_pixels == defaults.max_total_pixels == 150_000_000
    # With settings at their defaults the extractor receives exactly the limits
    # it received before the bounds were exposed.
    assert extraction_limits(settings) == ExtractionLimits(
        max_file_bytes=settings.max_file_bytes, max_pages=settings.max_pages
    )


def test_environment_reaches_the_pixel_bounds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("INVOICE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INVOICE_MAX_PIXELS_PER_PAGE", "4000000")
    monkeypatch.setenv("INVOICE_MAX_TOTAL_PIXELS", "9000000")
    settings = Settings.from_env()
    assert settings.max_pixels_per_page == 4_000_000
    assert settings.max_total_pixels == 9_000_000
    limits = extraction_limits(settings)
    assert limits.max_pixels_per_page == 4_000_000
    assert limits.max_total_pixels == 9_000_000
    assert limits.max_pages == settings.max_pages
    assert limits.max_file_bytes == settings.max_file_bytes


def test_environment_defaults_equal_the_extractor_constants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INVOICE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("INVOICE_MAX_PIXELS_PER_PAGE", raising=False)
    monkeypatch.delenv("INVOICE_MAX_TOTAL_PIXELS", raising=False)
    settings = Settings.from_env()
    assert settings.max_pixels_per_page == ExtractionLimits().max_pixels_per_page
    assert settings.max_total_pixels == ExtractionLimits().max_total_pixels


def _png(width: int, height: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_configured_per_page_bound_is_honoured_by_the_job(tmp_path: Path) -> None:
    service = InvoiceService(_settings(tmp_path, max_pixels_per_page=1_000))
    accepted, duplicate = service.ingest_bytes("scan.png", _png(50, 50))
    assert not duplicate
    assert service._claim_job() == accepted["id"]
    with patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"), patch.object(
        extraction, "_run_tesseract", return_value=("", None)
    ):
        service._process_job(accepted["id"])
    invoice = service.get_invoice(accepted["id"])
    assert invoice["status"] == "failed"
    assert "2500 pixels; the per-page limit is 1000" in (invoice["error"] or "")


def test_configured_total_bound_is_honoured_by_the_job(tmp_path: Path) -> None:
    from PIL import Image

    frames = [Image.new("L", (60, 60), 255) for _ in range(3)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="TIFF", save_all=True, append_images=frames[1:])
    service = InvoiceService(_settings(tmp_path, max_total_pixels=8_000))
    accepted, duplicate = service.ingest_bytes("scan.tiff", buffer.getvalue())
    assert not duplicate
    assert service._claim_job() == accepted["id"]
    with patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"), patch.object(
        extraction, "_run_tesseract", return_value=("", None)
    ):
        service._process_job(accepted["id"])
    invoice = service.get_invoice(accepted["id"])
    assert invoice["status"] == "failed"
    assert "8000 total pixel limit" in (invoice["error"] or "")


def test_default_bound_still_fails_the_same_page(tmp_path: Path) -> None:
    # The previous behaviour at defaults, stated as a number: a page of
    # 30,000,001 pixels fails and one of 30,000,000 does not.
    limits = extraction_limits(_settings(tmp_path))
    extraction._check_page_pixels(30_000_000, 1, limits)
    with pytest.raises(extraction.ExtractionLimitError, match="per-page limit is 30000000"):
        extraction._check_page_pixels(30_000_001, 1, limits)
