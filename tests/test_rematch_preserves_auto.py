"""Rematch keeps machine selections machine.

A stored ``auto`` line sent back through rematch comes back ``auto`` with its
score byte for byte; ``confirmed`` is reserved for a decision the audit trail
records as a human line edit; the ``invoice_rematched`` event carries the actor
who asked.  Every fixture here is fictional and generated in the test.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import matching
from backend.app import create_app
from backend.service import (
    InvoiceService,
    Settings,
    ValidationFailure,
)

CATALOG = [
    {
        "catalog_item_id": "c-1",
        "rms_item_id": "RMS-900",
        "description": "Fictional Widget Blue",
        "supplier_id": "900001",
        "uom": "EA",
        "unit_cost": 4.5,
    }
]
CATALOG_CSV = (
    b"rms_item_id,description,supplier_id,uom,unit_cost\n"
    b"RMS-900,Fictional Widget Blue,900001,EA,4.50\n"
)
INVOICE_TXT = (
    b"Supplier name: Fictional Trading FZE\nSupplier ID: 900001\nInvoice number: AUTO-1\n"
    b"Invoice date: 2026-09-24\nCurrency: AED\n"
    b"Description                     Qty Unit Price Line Total\n"
    b"Fictional Widget Blue            2 10.00 20.00\n"
    b"Grand Total AED 20.00\n"
)


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "service.db",
        source_dir=tmp_path / "sources",
        export_dir=tmp_path / "exports",
        workers=0,
    )


def make_service(tmp_path: Path) -> InvoiceService:
    return InvoiceService(settings_for(tmp_path))


def bytes_of(value: object) -> bytes:
    return struct.pack("<d", float(value))  # type: ignore[arg-type]


def ingest_auto_invoice(service: InvoiceService) -> dict:
    service.import_catalog("catalog.csv", CATALOG_CSV)
    item, duplicate = service.ingest_bytes("auto.txt", INVOICE_TXT)
    assert not duplicate
    assert service._claim_job() == item["id"]
    service._process_job(item["id"])
    invoice = service.get_invoice(item["id"])
    assert invoice["status"] == "needs_review"
    assert [line["match_status"] for line in invoice["lines"]] == ["auto"]
    return invoice


def rematch_events(service: InvoiceService, invoice_id: str) -> list[dict]:
    """Rematch events oldest first (the audit endpoint lists newest first)."""
    return sorted(
        (
            event
            for event in service.audit(invoice_id)["items"]
            if event["event_type"] == "invoice_rematched"
        ),
        key=lambda event: event["version"],
    )


# --- matcher level -----------------------------------------------------------


def test_stored_auto_line_revalidates_as_auto_with_score_byte_equal() -> None:
    [first] = matching.match_lines(
        [{"description": "Fictional Widget Blue", "quantity": "2", "unit_price": "10.00"}],
        CATALOG,
        supplier_id="900001",
    )
    assert first["match_status"] == "auto"
    assert first["catalog_item_id"] == "c-1"

    [again] = matching.match_lines([dict(first)], CATALOG, supplier_id="900001")

    assert again["match_status"] == "auto"
    assert bytes_of(again["confidence"]) == bytes_of(first["confidence"])
    assert again["rms_item_id"] == "RMS-900"
    assert [c["rms_item_id"] for c in again["candidates"]] == [
        c["rms_item_id"] for c in first["candidates"]
    ]


def test_stored_auto_score_is_preserved_not_recomputed() -> None:
    line = {
        "description": "Fictional Widget Blue",
        "catalog_item_id": "c-1",
        "match_status": "auto",
        "confidence": 87.3,
    }

    [again] = matching.match_lines([line], CATALOG, supplier_id="900001")

    assert again["match_status"] == "auto"
    assert bytes_of(again["confidence"]) == bytes_of(87.3)
    assert again["candidates"][0]["rms_item_id"] == "RMS-900"
    assert again["candidates"][0]["score"] == 87.3
    assert again["unit_status"]  # unit and cost facts are still recomputed


def test_human_confirmed_line_and_bare_identifier_are_confirmed() -> None:
    human = {
        "description": "Fictional Widget Blue",
        "catalog_item_id": "c-1",
        "match_status": "confirmed",
        "confidence": 100.0,
    }
    bare = {"description": "supplier wording", "rms_item_id": "RMS-900"}
    for line in (human, bare):
        [again] = matching.match_lines([line], CATALOG, supplier_id="900001")
        assert (again["match_status"], again["confidence"]) == ("confirmed", 100.0)


# --- service level -----------------------------------------------------------


def test_rematch_over_stored_auto_yields_auto_with_score_byte_equal(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    invoice = ingest_auto_invoice(service)
    stored = invoice["lines"][0]

    result = service.rematch(invoice["id"], invoice["version"], actor="system")

    line = result["lines"][0]
    assert line["match_status"] == "auto"
    assert bytes_of(line["confidence"]) == bytes_of(stored["confidence"])
    assert line["rms_item_id"] == stored["rms_item_id"] == "RMS-900"
    persisted = service.get_invoice(invoice["id"])["lines"][0]
    assert persisted["match_status"] == "auto"
    assert bytes_of(persisted["confidence"]) == bytes_of(stored["confidence"])

    # A second rematch, this time by a person, still does not promote it.
    result = service.rematch(invoice["id"], result["version"], actor="user")
    assert result["lines"][0]["match_status"] == "auto"
    assert bytes_of(result["lines"][0]["confidence"]) == bytes_of(stored["confidence"])

    events = rematch_events(service, invoice["id"])
    assert [event["actor"] for event in events] == ["system", "user"]
    assert events[0]["details"] == {
        "line_count": 1,
        "auto_lines_preserved": 1,
        "unrecorded_confirmations_demoted": 0,
    }


def test_rematch_actor_defaults_to_user_and_rejects_others(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    invoice = ingest_auto_invoice(service)

    result = service.rematch(invoice["id"], invoice["version"])
    assert [event["actor"] for event in rematch_events(service, invoice["id"])] == ["user"]

    with pytest.raises(ValidationFailure) as failure:
        service.rematch(invoice["id"], result["version"], actor="robot")
    assert failure.value.errors[0]["field"] == "actor"
    assert failure.value.errors[0]["code"] == "invalid_choice"
    assert len(rematch_events(service, invoice["id"])) == 1


def test_human_line_edit_confirms_and_survives_rematch(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    invoice = ingest_auto_invoice(service)
    edited_line = {**invoice["lines"][0], "match_status": "confirmed", "confidence": 100}

    edited = service.update_invoice(invoice["id"], invoice["version"], {"lines": [edited_line]})
    assert edited["lines"][0]["match_status"] == "confirmed"
    edits = [e for e in service.audit(invoice["id"])["items"] if e["event_type"] == "invoice_edited"]
    assert edits and edits[0]["actor"] == "user"
    assert "lines" in edits[0]["details"]["changed_fields"]

    result = service.rematch(invoice["id"], edited["version"], actor="system")

    assert (result["lines"][0]["match_status"], result["lines"][0]["confidence"]) == (
        "confirmed",
        100.0,
    )
    assert rematch_events(service, invoice["id"])[0]["details"]["auto_lines_preserved"] == 0


def test_confirmed_without_recorded_human_decision_is_treated_as_machine(tmp_path: Path) -> None:
    """A line stored as confirmed with no human line edit in the trail is what
    the old promotion produced.  It is taken back to auto with its stored score."""

    service = make_service(tmp_path)
    invoice = ingest_auto_invoice(service)
    stored = invoice["lines"][0]
    with service.db.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE invoice_lines SET match_status='confirmed' WHERE invoice_id=?",
            (invoice["id"],),
        )
    assert service.get_invoice(invoice["id"])["lines"][0]["match_status"] == "confirmed"

    result = service.rematch(invoice["id"], invoice["version"], actor="system")

    line = result["lines"][0]
    assert line["match_status"] == "auto"
    assert bytes_of(line["confidence"]) == bytes_of(stored["confidence"])
    assert line["rms_item_id"] == "RMS-900"
    assert rematch_events(service, invoice["id"])[0]["details"] == {
        "line_count": 1,
        "auto_lines_preserved": 0,
        "unrecorded_confirmations_demoted": 1,
    }


# --- route level -------------------------------------------------------------


def test_rematch_route_records_the_requested_actor(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path))
    reader = make_service(tmp_path)
    with TestClient(app) as client:
        service = app.state.service if hasattr(app.state, "service") else reader
        invoice = ingest_auto_invoice(service)
        url = f"/api/invoices/{invoice['id']}/rematch"

        as_system = client.post(url, json={"expected_version": invoice["version"], "actor": "system"})
        assert as_system.status_code == 200, as_system.text
        assert as_system.json()["lines"][0]["match_status"] == "auto"

        by_default = client.post(url, json={"expected_version": as_system.json()["version"]})
        assert by_default.status_code == 200, by_default.text

        rejected = client.post(
            url, json={"expected_version": by_default.json()["version"], "actor": "robot"}
        )
        assert rejected.status_code == 422

    assert [event["actor"] for event in rematch_events(reader, invoice["id"])] == [
        "system",
        "user",
    ]
    line = reader.get_invoice(invoice["id"])["lines"][0]
    assert line["match_status"] == "auto"
    assert bytes_of(line["confidence"]) == bytes_of(invoice["lines"][0]["confidence"])
