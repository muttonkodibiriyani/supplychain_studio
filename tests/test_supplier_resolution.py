"""Supplier resolution, the unresolved-supplier catalog gate and its guards.

All names, ids and prices here are fictional fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import matching
from backend.service import InvoiceService, Settings

CATALOG_CSV = b"""rms_item_id,description,supplier_id,supplier_name,uom,unit_cost
RMS-BLUE,Fictional Widget Blue,900001,FIC001RE4AED,EA,10
RMS-RED,Fictional Widget Red,900001,FIC001RE4AED,EA,11
RMS-GADGET,Fictional Gadget,900001,FIC001RE4AED,EA,5
RMS-GADGET,Fictional Gadget,900002,FIC001RE1AED,EA,5
RMS-OTHER,Other Fictional Thing,900003,OTH001RE4AED,EA,7
RMS-FREE,Fictional Widget Free,,,EA,0
"""


def make_service(tmp_path: Path) -> InvoiceService:
    service = InvoiceService(
        Settings(
            database_path=tmp_path / "service.db",
            source_dir=tmp_path / "sources",
            export_dir=tmp_path / "exports",
            workers=0,
        )
    )
    result = service.import_catalog("catalog.csv", CATALOG_CSV)
    assert result["skipped"] == 0
    return service


def real_shaped_invoice(seller: str) -> bytes:
    # Shape of a real PDF text layer: title, seller legal name, then Bill To.
    return (
        "INVOICE\n"
        f"{seller}\n"
        "Bill To\n"
        "Some Fictional Retailer LLC\n"
        "Invoice number: RS-INV-1\n"
        "Invoice date: 2026-09-24\n"
        "Currency: AED\n"
        "Description                     Qty Unit Price Line Total\n"
        "Fictional Widget Blue            2 10.00 20.00\n"
        "Subtotal AED 20.00\n"
        "VAT Total AED 1.00\n"
        "Grand Total AED 21.00\n"
    ).encode()


def process(service: InvoiceService, filename: str, content: bytes) -> dict:
    item, _ = service.ingest_bytes(filename, content)
    assert service._claim_job() == item["id"]
    service._process_job(item["id"])
    return service.get_invoice(item["id"])


def test_supplier_resolves_from_real_shaped_header_to_catalog_supplier(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    invoice = process(service, "seller.txt", real_shaped_invoice("Fictional Trading FZE"))

    assert invoice["supplier_name"] == "Fictional Trading FZE"
    # Two coded supplier sites share the FIC prefix; the invoice lines single
    # out the site whose rows carry the printed description.
    assert invoice["supplier_id"] == "900001"
    line = invoice["lines"][0]
    assert line["rms_item_id"] == "RMS-BLUE"
    assert line["match_status"] == "auto"
    assert any("resolved" in warning for warning in invoice["warnings"])
    assert not any(matching.SUPPLIER_UNRESOLVED_WARNING == w for w in invoice["warnings"])


def test_printed_supplier_id_known_to_catalog_wins(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    content = (
        b"Supplier name: Fictional Trading FZE\nSupplier ID: 900002\nInvoice number: RS-2\n"
        b"Invoice date: 2026-09-24\nCurrency: AED\n"
        b"Description                     Qty Unit Price Line Total\n"
        b"Fictional Gadget                 1 5.00 5.00\n"
        b"Grand Total AED 5.00\n"
    )
    invoice = process(service, "printed-id.txt", content)
    assert invoice["supplier_id"] == "900002"
    assert invoice["lines"][0]["rms_item_id"] == "RMS-GADGET"


def test_unresolved_supplier_falls_back_to_full_catalog_as_review_only(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    invoice = process(service, "unknown.txt", real_shaped_invoice("Unknown Vendor LLC"))

    assert invoice["supplier_id"] is None
    assert matching.SUPPLIER_UNRESOLVED_WARNING in invoice["warnings"]
    line = invoice["lines"][0]
    # The exact description exists in the catalog, but a full-catalog fallback
    # can never auto-select: it is surfaced as a suggestion for review.
    assert line["match_status"] == "suggested"
    assert line["rms_item_id"] is None
    assert {candidate["rms_item_id"] for candidate in line["candidates"]} >= {"RMS-BLUE", "RMS-RED"}
    assert all("Supplier unresolved" in candidate["reason"] for candidate in line["candidates"])
    assert line["target_cost_review_required"] is True
    assert line["target_cost_comparison_status"] == "unavailable_no_match"


def test_alias_persistence_is_off_by_default_and_confirmation_still_applies(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    assert service.settings.learn_aliases is False
    invoice = process(service, "unknown.txt", real_shaped_invoice("Unknown Vendor LLC"))
    line = dict(invoice["lines"][0])
    line.update({"rms_item_id": "RMS-RED", "match_status": "confirmed", "confidence": 100})

    corrected = service.update_invoice(invoice["id"], invoice["version"], {"lines": [line]})

    assert corrected["lines"][0]["rms_item_id"] == "RMS-RED"
    assert service.list_aliases()["total"] == 0
    audit = [entry for entry in service.audit(invoice["id"])["items"] if entry["event_type"] == "invoice_edited"]
    assert audit and audit[0]["details"]["learn_aliases_enabled"] is False
    assert audit[0]["details"]["aliases_learned"] == []


def test_operator_confirmation_with_unresolved_supplier_learns_row_scoped_alias(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.settings.learn_aliases = True  # explicit opt-in (INVOICE_LEARN_ALIASES=1)
    invoice = process(service, "unknown.txt", real_shaped_invoice("Unknown Vendor LLC"))
    line = dict(invoice["lines"][0])
    line.update({"rms_item_id": "RMS-RED", "match_status": "confirmed", "confidence": 100})

    corrected = service.update_invoice(invoice["id"], invoice["version"], {"lines": [line]})

    assert corrected["lines"][0]["rms_item_id"] == "RMS-RED"
    aliases = service.list_aliases()
    assert aliases["total"] == 1
    assert aliases["items"][0]["supplier_id"] == "900001"
    assert aliases["items"][0]["rms_item_id"] == "RMS-RED"


def test_unmatched_and_costless_lines_keep_the_cost_review_guard_on(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    lines = service._prepare_lines(
        [
            {"description": "Nothing matched", "unit_price": 3, "match_status": "unmatched"},
            {
                "description": "Fictional Widget Free",
                "unit_price": 3,
                "rms_item_id": "RMS-FREE",
                "rms_unit_cost": 0,
                "match_status": "auto",
            },
        ],
        currency="AED",
    )
    assert [line["target_cost_comparison_status"] for line in lines] == [
        "unavailable_no_match",
        "unavailable_rms_cost",
    ]
    assert all(line["target_cost_review_required"] for line in lines)


class TestMatchLinesFallback:
    catalog = [
        {"rms_item_id": "A-1", "description": "Fictional Widget Blue", "supplier_id": "SUP-A", "uom": "EA"},
        {"rms_item_id": "B-1", "description": "Fictional Widget Blue", "supplier_id": "SUP-B", "uom": "EA"},
        {"rms_item_id": "B-2", "description": "Fictional Gadget", "supplier_id": "SUP-B", "uom": "EA"},
    ]

    def test_unresolved_supplier_never_reaches_auto_and_is_flagged(self) -> None:
        result = matching.match_lines(
            [{"description": "Fictional Gadget", "uom": "EA"}], self.catalog, supplier_id=None
        )[0]
        assert result["match_status"] == "suggested"
        assert result["rms_item_id"] is None
        assert result["match_reason"] == "supplier_unresolved_full_catalog_fallback"
        assert matching.SUPPLIER_UNRESOLVED_WARNING in result["match_warnings"]
        assert result["candidates"][0]["rms_item_id"] == "B-2"

    def test_resolved_supplier_still_auto_matches_within_scope(self) -> None:
        result = matching.match_lines(
            [{"description": "Fictional Gadget", "uom": "EA"}], self.catalog, supplier_id="SUP-B"
        )[0]
        assert result["match_status"] == "auto"
        assert result["rms_item_id"] == "B-2"
        assert "match_reason" not in result

    def test_fallback_can_be_disabled_explicitly(self) -> None:
        result = matching.match_lines(
            [{"description": "Fictional Gadget", "uom": "EA"}],
            self.catalog,
            supplier_id=None,
            unresolved_supplier_fallback=False,
        )[0]
        assert result["match_status"] == "unmatched"
        assert result["candidates"] == []

    def test_enrich_invoice_surfaces_invoice_level_diagnostic(self) -> None:
        enriched = matching.enrich_invoice({"lines": [{"description": "Fictional Gadget"}]}, self.catalog)
        assert enriched["supplier_resolution"] == "unresolved"
        assert matching.SUPPLIER_UNRESOLVED_WARNING in enriched["warnings"]

    def test_large_catalog_prefilter_keeps_exact_and_near_matches(self) -> None:
        catalog = [
            {"rms_item_id": f"F-{index}", "description": f"Filler item number {index}", "supplier_id": "SUP-F"}
            for index in range(matching.PREFILTER_MIN_ROWS + 5)
        ]
        catalog.append({"rms_item_id": "T-1", "description": "Fictional Widget Blue", "supplier_id": "SUP-T"})
        catalog.append({"rms_item_id": "T-2", "description": "Fictional Widget Blue 50ml", "supplier_id": "SUP-T"})
        result = matching.match_lines([{"description": "Fictional Widget Blue"}], catalog, supplier_id="SUP-T")[0]
        assert result["match_status"] == "auto"
        assert result["rms_item_id"] == "T-1"
        assert {candidate["rms_item_id"] for candidate in result["candidates"]} == {"T-1", "T-2"}


def test_aliases_table_stays_empty_after_approving_a_resolved_invoice(tmp_path: Path) -> None:
    # Bar (f-2): supplier resolution ships with alias persistence disabled by an
    # explicit named switch (INVOICE_LEARN_ALIASES, default off).  Confirming
    # and approving a resolved invoice must not write a single alias row.
    service = make_service(tmp_path)
    assert service.settings.learn_aliases is False
    service.seed_demo()
    invoice = service.get_invoice("demo-invoice-002")
    assert invoice["supplier_id"]
    line = dict(invoice["lines"][0])
    line.update({"rms_item_id": "RMS-2001", "match_status": "confirmed", "confidence": 100})
    corrected = service.update_invoice(invoice["id"], invoice["version"], {"lines": [line]})
    assert service.list_aliases()["total"] == 0

    approved = service.approve(corrected["id"], corrected["version"])
    assert approved["status"] == "ready"
    assert service.list_aliases()["total"] == 0
    approval = [e for e in service.audit(approved["id"])["items"] if e["event_type"] == "invoice_approved"]
    assert approval and approval[0]["details"]["learn_aliases_enabled"] is False
    assert approval[0]["details"]["aliases_learned"] == []
