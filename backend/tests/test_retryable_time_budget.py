"""A missed OCR time budget is a bound of the host, not of the document, so it
carries its own explicitly retryable failure class; content bounds stay final.

The service already has two retry paths: a non-permanent failure is re-queued
automatically (``_fail_processing``, up to ``Settings.max_attempts``), and an
operator can re-queue any failed invoice (``InvoiceService.retry``, exposed at
``POST /api/invoices/{id}/retry``).  Before this change the time budget was
classified as permanent, so neither path ever ran for it unless the operator
guessed.  These tests pin the classification on both sides."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from backend import extraction
from backend.extraction import (
    DocumentExtractionError,
    ExtractionLimitError,
    ExtractionLimits,
    ExtractionTimeBudgetError,
)
from backend.service import InvoiceService, Settings


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        database_path=tmp_path / "invoices.sqlite3",
        source_dir=tmp_path / "sources",
        export_dir=tmp_path / "exports",
        workers=0,
        **overrides,
    )


def _png(width: int = 40, height: int = 40) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _tiff(frames: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    pages = [Image.new("RGB", (40, 40), "white") for _ in range(frames)]
    pages[0].save(buffer, format="TIFF", save_all=True, append_images=pages[1:])
    return buffer.getvalue()


def _timeout_run(*args: object, **kwargs: object) -> None:
    raise subprocess.TimeoutExpired(cmd="tesseract", timeout=float(kwargs.get("timeout", 0)))


def _events(service: InvoiceService, invoice_id: str) -> list[str]:
    with service.db.connection() as conn:
        rows = conn.execute(
            "SELECT event_type FROM audit_events WHERE invoice_id = ? ORDER BY id", (invoice_id,)
        ).fetchall()
    return [row[0] for row in rows]


# --- the extractor names the class ---------------------------------------------


def test_time_budget_class_is_a_retryable_limit_error() -> None:
    assert issubclass(ExtractionTimeBudgetError, ExtractionLimitError)
    assert ExtractionTimeBudgetError.retryable is True
    assert ExtractionLimitError.retryable is False
    assert DocumentExtractionError.retryable is False


def test_page_timeout_raises_the_retryable_class() -> None:
    from PIL import Image

    with patch.object(extraction.subprocess, "run", _timeout_run):
        with pytest.raises(ExtractionTimeBudgetError) as caught:
            extraction._run_tesseract(Image.new("RGB", (40, 40), "white"), 7.0, 30_000_000)
    assert caught.value.retryable is True
    assert "7 second limit" in str(caught.value)
    assert "try again when the host is quieter" in str(caught.value)


def test_exhausted_document_budget_raises_the_retryable_class(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(_png())
    # A zero document budget is exhausted the moment the first page is reached;
    # Tesseract is never invoked, so the stub below would fail the test if it were.
    with patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"), patch.object(
        extraction, "_run_tesseract", side_effect=AssertionError("must not run")
    ):
        with pytest.raises(ExtractionTimeBudgetError) as caught:
            extraction.extract_document(source, limits=ExtractionLimits(ocr_timeout_seconds_total=0.0))
    assert "document limit" in str(caught.value)
    assert "try again when the host is quieter" in str(caught.value)


def test_content_bounds_are_not_retryable(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(_png(50, 50))
    with patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"):
        with pytest.raises(ExtractionLimitError) as caught:
            extraction.extract_document(source, limits=ExtractionLimits(max_pixels_per_page=1_000))
    assert not isinstance(caught.value, ExtractionTimeBudgetError)
    assert caught.value.retryable is False


# --- the service acts on the class -----------------------------------------------


def test_time_budget_failure_is_requeued_automatically(tmp_path: Path) -> None:
    service = InvoiceService(_settings(tmp_path, max_attempts=3))
    accepted, _ = service.ingest_bytes("scan.png", _png())
    assert service._claim_job() == accepted["id"]
    with patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"), patch.object(
        extraction.subprocess, "run", _timeout_run
    ):
        service._process_job(accepted["id"])
    invoice = service.get_invoice(accepted["id"])
    assert invoice["status"] == "queued"
    assert invoice["error"].startswith("ExtractionTimeBudgetError: ")
    assert "try again when the host is quieter" in invoice["error"]
    assert _events(service, accepted["id"])[-1] == "processing_retry_scheduled"


def test_content_failure_is_final(tmp_path: Path) -> None:
    # The page bound is a content bound the job (not the upload) enforces.
    service = InvoiceService(_settings(tmp_path, max_attempts=3, max_pages=1))
    accepted, _ = service.ingest_bytes("scan.tiff", _tiff(frames=2))
    assert service._claim_job() == accepted["id"]
    with patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"), patch.object(
        extraction, "_run_tesseract", side_effect=AssertionError("must not run")
    ):
        service._process_job(accepted["id"])
    invoice = service.get_invoice(accepted["id"])
    assert invoice["status"] == "failed"
    assert invoice["error"].startswith("ExtractionLimitError: ")
    assert "try again" not in invoice["error"]
    assert _events(service, accepted["id"])[-1] == "processing_failed"


def test_operator_retry_reprocesses_after_the_budget_attempts_run_out(tmp_path: Path) -> None:
    service = InvoiceService(_settings(tmp_path, max_attempts=1))
    accepted, _ = service.ingest_bytes("scan.png", _png())
    assert service._claim_job() == accepted["id"]
    with patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"), patch.object(
        extraction.subprocess, "run", _timeout_run
    ):
        service._process_job(accepted["id"])
    failed = service.get_invoice(accepted["id"])
    assert failed["status"] == "failed", "the single permitted attempt is used up"
    assert failed["error"].startswith("ExtractionTimeBudgetError: ")

    requeued = service.retry(accepted["id"])
    assert requeued["status"] == "queued"
    assert requeued["error"] is None
    assert service._claim_job() == accepted["id"]
    with patch.object(extraction.shutil, "which", return_value="/usr/bin/tesseract"), patch.object(
        extraction, "_run_tesseract", return_value=("Invoice 1\nTotal 5.00\n", 90.0)
    ):
        service._process_job(accepted["id"])
    reprocessed = service.get_invoice(accepted["id"])
    assert reprocessed["status"] == "needs_review"
    assert reprocessed["error"] is None
    events = _events(service, accepted["id"])
    assert events[-1] == "extraction_completed"
    assert events.index("processing_failed") < events.index("retry_requested") < len(events) - 1
