"""Recognition that produces no text ends FAILED with reason ocr_empty.

A document whose recognised text has zero non-whitespace characters was not
"read and found empty"; it could not be read.  It must never be stored as
needs_review and later reported as ``lines:required``.  All documents here are
fictional fixtures generated in the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import extraction
from backend.service import (
    RECOGNITION_EMPTY_REASON,
    TEXT_RECOGNITION_METHODS,
    InvoiceService,
    Settings,
    ValidationFailure,
    recognised_text_is_empty,
)


def make_service(tmp_path: Path) -> InvoiceService:
    return InvoiceService(
        Settings(
            database_path=tmp_path / "service.db",
            source_dir=tmp_path / "sources",
            export_dir=tmp_path / "exports",
            workers=0,
        )
    )


def fake_extraction(method: str, raw_text: str, lines: list[dict] | None = None) -> dict:
    return {
        "supplier_name": "Fictional Supplier LLC",
        "supplier_id": None,
        "invoice_number": "FX-1",
        "invoice_date": "2026-09-24",
        "currency": "AED",
        "document_type": "invoice",
        "lines": lines or [],
        "subtotal": None,
        "tax_total": None,
        "total": None,
        "raw_text": raw_text,
        "extraction_method": method,
        "pages": 1,
        "page_texts": [],
        "warnings": [],
    }


def process(service: InvoiceService, monkeypatch: pytest.MonkeyPatch, extracted: dict, name: str = "doc.pdf") -> dict:
    monkeypatch.setattr(extraction, "extract_document", lambda *args, **kwargs: dict(extracted))
    item, _ = service.ingest_bytes(name, f"bytes for {name} {extracted['extraction_method']}".encode())
    assert service._claim_job() == item["id"]
    service._process_job(item["id"])
    return service.get_invoice(item["id"])


def failure_events(service: InvoiceService, invoice_id: str) -> list[dict]:
    return [e for e in service.audit(invoice_id)["items"] if e["event_type"] == "processing_failed"]


def test_empty_is_structural_not_a_character_threshold() -> None:
    assert recognised_text_is_empty({"extraction_method": "image_ocr", "raw_text": ""})
    assert recognised_text_is_empty({"extraction_method": "image_ocr", "raw_text": " \n\t\r\n "})
    assert recognised_text_is_empty({"extraction_method": "pdf_text", "raw_text": None})
    # One non-whitespace character is text: the parser, not this rule, judges it.
    assert not recognised_text_is_empty({"extraction_method": "image_ocr", "raw_text": " . "})
    # Structured sources are outside the rule: their lines come from data cells.
    assert not recognised_text_is_empty({"extraction_method": "pdf_facturx_xml", "raw_text": ""})
    assert TEXT_RECOGNITION_METHODS == {
        "image_ocr", "pdf_ocr", "pdf_text", "pdf_text+ocr", "text", "docx_text"
    }


@pytest.mark.parametrize("method", sorted(TEXT_RECOGNITION_METHODS))
def test_empty_recognised_text_fails_with_ocr_empty_per_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    service = make_service(tmp_path)
    invoice = process(service, monkeypatch, fake_extraction(method, "  \n\t"))
    assert invoice["status"] == "failed"
    assert invoice["error"].startswith(f"RecognitionEmpty: {RECOGNITION_EMPTY_REASON}: recognition produced no text")
    assert method in invoice["error"]
    assert invoice["lines"] == []
    events = failure_events(service, invoice["id"])
    assert len(events) == 1
    assert events[0]["details"]["reason"] == RECOGNITION_EMPTY_REASON
    assert events[0]["to_status"] == "failed"
    # Permanent: no automatic retry is scheduled for a deterministic empty read.
    assert events[0]["details"]["retry_at"] is None


def test_text_layer_pdf_with_empty_layer_is_treated_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service(tmp_path)
    invoice = process(service, monkeypatch, fake_extraction("pdf_text", ""))
    assert invoice["status"] == "failed"
    assert RECOGNITION_EMPTY_REASON in invoice["error"]
    assert "pdf_text" in invoice["error"]


def test_non_empty_text_with_zero_lines_stays_needs_review_lines_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two conditions stay distinct: text was read, no line rows detected."""

    service = make_service(tmp_path)
    invoice = process(
        service, monkeypatch, fake_extraction("image_ocr", "Fictional Supplier LLC\nThank you for your order")
    )
    assert invoice["status"] == "needs_review"
    assert invoice["error"] is None
    assert invoice["lines"] == []
    assert failure_events(service, invoice["id"]) == []
    with pytest.raises(ValidationFailure) as failure:
        service.approve(invoice["id"], invoice["version"])
    assert {"field": "lines", "code": "required"} in [
        {"field": e["field"], "code": e["code"]} for e in failure.value.errors
    ]


def test_structured_source_with_empty_rendered_text_is_not_ocr_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service(tmp_path)
    extracted = fake_extraction(
        "pdf_facturx_xml",
        "",
        [{"description": "Fictional Widget", "quantity": "1", "unit_price": "5.00", "line_total": "5.00"}],
    )
    invoice = process(service, monkeypatch, extracted)
    assert invoice["status"] == "needs_review"
    assert len(invoice["lines"]) == 1


def test_failed_ocr_empty_row_retries_like_any_failed_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service(tmp_path)
    invoice = process(service, monkeypatch, fake_extraction("image_ocr", ""))
    assert invoice["status"] == "failed"

    retried = service.retry(invoice["id"])
    assert retried["status"] == "queued"
    assert retried["error"] is None
    # A better recognition on retry (e.g. a replaced engine or language pack)
    # takes the ordinary path to needs_review.
    monkeypatch.setattr(
        extraction,
        "extract_document",
        lambda *args, **kwargs: fake_extraction(
            "image_ocr",
            "Fictional Widget 1 5.00 5.00",
            [{"description": "Fictional Widget", "quantity": "1", "unit_price": "5.00", "line_total": "5.00"}],
        ),
    )
    assert service._claim_job() == invoice["id"]
    service._process_job(invoice["id"])
    again = service.get_invoice(invoice["id"])
    assert again["status"] == "needs_review"
    assert again["error"] is None
    assert len(again["lines"]) == 1
    assert [e["event_type"] for e in service.audit(invoice["id"])["items"]].count("retry_requested") == 1
