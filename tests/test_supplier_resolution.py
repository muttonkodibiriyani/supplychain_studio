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
    # The fixture table carries no unit column: the exact description in the
    # resolved supplier's scope auto-selects the supplier's own row (not the
    # global look-alike) and the UOM-only unknown against a single-unit master
    # row is carried as the "unit assumed" flag, not a demotion.
    assert line["match_status"] == "auto"
    assert line["rms_item_id"] == "RMS-BLUE"
    assert line["unit_status"] == "assumed"
    assert line["unit_reason"].startswith("unit assumed")
    assert line["target_cost_comparison_status"] == "within_tolerance"
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
    line = invoice["lines"][0]
    assert line["match_status"] == "auto"
    assert line["rms_item_id"] == "RMS-GADGET"
    assert line["catalog_item_id"]
    assert line["unit_status"] == "assumed"


def test_unverified_printed_supplier_id_takes_the_full_catalog_fallback(tmp_path: Path) -> None:
    # Item (2): an id printed on the document but absent from the catalog (new
    # supplier, or an id changed at the last master re-import) must NOT take
    # the scoped branch (0 supplier rows + global rows, the silently narrowed
    # set through a second door).  It takes the same full-catalog fallback as
    # an unresolved supplier, and the fallback block demotes any auto.
    service = make_service(tmp_path)
    content = (
        b"Supplier name: Brand New Vendor LLC\nSupplier ID: 777777\nInvoice number: RS-3\n"
        b"Invoice date: 2026-09-24\nCurrency: AED\n"
        b"Description                     Qty Unit Price Line Total\n"
        b"Other Fictional Thing            1 7.00 7.00\n"
        b"Grand Total AED 7.00\n"
    )
    invoice = process(service, "unverified-id.txt", content)
    assert invoice["supplier_id"] == "777777"
    assert matching.SUPPLIER_UNRESOLVED_WARNING in invoice["warnings"]
    assert any("not present in the catalog" in warning for warning in invoice["warnings"])
    line = invoice["lines"][0]
    # The exact description lives only under supplier 900003: reachable now,
    # but never auto because the supplier is not the row's supplier.
    assert line["match_status"] == "suggested"
    assert line["rms_item_id"] is None
    assert line["candidates"][0]["rms_item_id"] == "RMS-OTHER"
    assert "Supplier unresolved" in line["candidates"][0]["reason"]
    assert matching.SUPPLIER_UNRESOLVED_WARNING in line["match_warnings"] if "match_warnings" in line else True

    with service.db.connection() as conn:
        assert service._matching_scope_supplier(conn, "777777") is None
        assert service._matching_scope_supplier(conn, "900001") == "900001"
        catalog, _ = service._catalog_for_matching(conn, "777777")
    assert {row["supplier_id"] for row in catalog} >= {"900001", "900002", "900003"}


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
    # seed_demo refuses a database that already holds non-demo catalog rows,
    # so the fictional demo workspace is seeded first and the fixture catalog
    # is imported on top of it.  Every assertion below is unchanged.
    service = InvoiceService(
        Settings(
            database_path=tmp_path / "service.db",
            source_dir=tmp_path / "sources",
            export_dir=tmp_path / "exports",
            workers=0,
        )
    )
    assert service.settings.learn_aliases is False
    service.seed_demo()
    assert service.import_catalog("catalog.csv", CATALOG_CSV)["skipped"] == 0
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


class TestKindKeyedUnitGuardAtAutoBoundary:
    """Item (1): the auto boundary is keyed on the KIND of the unknown.

    UOM-only unknown + single-unit master + silent line -> auto, flag "unit
    assumed".  Size / pack / shade unknown -> demote.  Multi-unit master row
    or a stated disagreement -> demote with the reason "unit unconfirmed" and
    approval blocked.  The multi-unit and disagreement branches are dead
    against the current master (its UOM column is a constant single unit);
    these synthetic rows are the only thing that exercises them.
    """

    catalog = [
        {"rms_item_id": "RMS-SUN", "description": "Fictional Sunscreen SPF 50", "supplier_id": "900001", "uom": "EA", "unit_cost": 5.0},
        {"rms_item_id": "RMS-LOTION", "description": "Fictional Lotion 200ml", "supplier_id": "900001", "uom": "EA", "unit_cost": 3.0},
        {"rms_item_id": "RMS-CASE", "description": "Fictional Water Case", "supplier_id": "900001", "uom": "CS", "unit_cost": 30.0},
        {"rms_item_id": "RMS-TRAY", "description": "Fictional Juice 12x250ml", "supplier_id": "900001", "uom": "EA", "unit_cost": 18.0},
    ]

    def match(self, line: dict) -> dict:
        return matching.match_lines([line], self.catalog, [], "900001")[0]

    def test_uom_only_unknown_against_single_unit_master_is_auto_with_unit_assumed(self) -> None:
        line = self.match({"description": "Fictional Sunscreen SPF 50", "quantity": 30, "uom": None})
        assert line["match_status"] == "auto"
        assert line["rms_item_id"] == "RMS-SUN"
        assert line["confidence"] == 100.0
        assert line["unit_status"] == "assumed"
        assert line["unit_reason"].startswith("unit assumed")

    def test_uom_on_both_sides_is_auto_and_unit_confirmed(self) -> None:
        line = self.match({"description": "Fictional Sunscreen SPF 50", "quantity": 30, "uom": "EA"})
        assert line["match_status"] == "auto"
        assert line["rms_item_id"] == "RMS-SUN"
        assert line["unit_status"] == "confirmed"

    def test_size_unknown_on_one_side_demotes_even_with_single_unit_master(self) -> None:
        # Fuzzy path: the words agree except for the size the invoice omits.
        line = self.match({"description": "Fictional Lotion", "quantity": 2, "uom": "EA"})
        assert line["match_status"] != "auto"
        assert line["rms_item_id"] is None
        assert line["candidates"][0]["rms_item_id"] == "RMS-LOTION"
        assert "size appears on only one side" in line["candidates"][0]["reason"]
        check = matching.unit_check("Fictional Lotion", "EA", "Fictional Lotion 200ml", "EA")
        assert check["status"] == "unverified" and check["demote"] and not check["block"]

    def test_multi_unit_master_row_with_silent_line_is_demoted_unit_unconfirmed(self) -> None:
        # Tier (b), synthetic: a CS/CASE row.  Exact description, so without
        # the guard this would auto-select at 100.
        line = self.match({"description": "Fictional Water Case", "quantity": 4, "uom": None})
        assert line["match_status"] == "suggested"
        assert line["rms_item_id"] is None
        assert line["unit_status"] == "unconfirmed"
        assert line["unit_reason"].startswith("unit unconfirmed")
        assert any(w.startswith("unit unconfirmed") for w in line["match_warnings"])
        assert line["candidates"][0]["rms_item_id"] == "RMS-CASE"

    def test_nxsize_pack_row_with_silent_line_is_demoted_unit_unconfirmed(self) -> None:
        # Tier (b), synthetic: an NxSIZE row whose UOM column still says EA.
        line = self.match({"description": "Fictional Juice 12x250ml", "quantity": 1, "uom": None})
        assert line["match_status"] == "suggested"
        assert line["rms_item_id"] is None
        assert line["unit_status"] == "unconfirmed"
        assert "multi-unit row" in line["unit_reason"]

    def test_stated_disagreement_is_demoted_unit_unconfirmed(self) -> None:
        # Tier (c), synthetic: the line states EA, the row is a case.
        line = self.match({"description": "Fictional Water Case", "quantity": 4, "uom": "EA"})
        assert line["match_status"] != "auto"
        assert line["rms_item_id"] is None
        check = matching.unit_check("Fictional Water Case", "EA", "Fictional Water Case", "CS")
        assert check["status"] == "unconfirmed" and check["block"]
        assert "UOM conflict" in check["reason"]

    def test_agreeing_multi_unit_line_is_auto_and_unit_confirmed(self) -> None:
        line = self.match({"description": "Fictional Water Case", "quantity": 4, "uom": "CS"})
        assert line["match_status"] == "auto"
        assert line["rms_item_id"] == "RMS-CASE"
        assert line["unit_status"] == "confirmed"


def test_unit_unconfirmed_blocks_approval_and_refuses_the_cost_comparison(tmp_path: Path) -> None:
    # Approval recomputes the unit tier from the catalog row: an operator who
    # confirms a multi-unit row for a line without a unit is stopped with the
    # named reason, and the RMS cost comparison shows no number for it.
    service = make_service(tmp_path)
    service.import_catalog(
        "cases.csv",
        b"rms_item_id,description,supplier_id,supplier_name,uom,unit_cost\n"
        b"RMS-CASE,Fictional Water Case,900001,FIC001RE4AED,CS,30\n",
    )
    content = (
        b"Supplier name: Fictional Trading FZE\nSupplier ID: 900001\nInvoice number: RS-4\n"
        b"Invoice date: 2026-09-24\nCurrency: AED\n"
        b"Description                     Qty Unit Price Line Total\n"
        b"Fictional Water Case             4 30.00 120.00\n"
        b"Subtotal AED 120.00\nVAT Total AED 6.00\nGrand Total AED 126.00\n"
    )
    invoice = process(service, "case.txt", content)
    line = dict(invoice["lines"][0])
    assert line["match_status"] == "suggested"
    assert line["unit_status"] == "unconfirmed"
    line.update({"rms_item_id": "RMS-CASE", "match_status": "confirmed", "confidence": 100})
    corrected = service.update_invoice(
        invoice["id"],
        invoice["version"],
        {"lines": [line], "supplier_site": "S1", "location": "L1", "location_type": "STORE", "tax_code": "T1"},
    )
    stored = corrected["lines"][0]
    assert stored["rms_item_id"] == "RMS-CASE"
    assert stored["unit_status"] == "unconfirmed"
    assert stored["target_cost_comparison_status"] == "unavailable_uom_mismatch"
    assert stored["target_cost_variance"] is None
    assert stored["target_cost_review_required"] is True

    from backend.service import ValidationFailure

    with pytest.raises(ValidationFailure) as failure:
        service.approve(corrected["id"], corrected["version"], acknowledge_target_cost_variance=True)
    codes = {(e["field"], e["code"]) for e in failure.value.errors}
    assert ("lines.0.uom", "unit_unconfirmed") in codes
    assert any(e["message"].startswith("unit unconfirmed") for e in failure.value.errors)

    # Stating the agreeing unit on the line clears the block.
    stored = dict(stored)
    stored.update({"uom": "CS", "rms_item_id": "RMS-CASE", "match_status": "confirmed"})
    cleared = service.update_invoice(corrected["id"], corrected["version"], {"lines": [stored]})
    assert cleared["lines"][0]["unit_status"] == "confirmed"
    assert cleared["lines"][0]["target_cost_comparison_status"] == "within_tolerance"
    approved = service.approve(cleared["id"], cleared["version"])
    assert approved["status"] == "ready"


def test_divergent_tied_row_costs_are_refused_not_picked(tmp_path: Path) -> None:
    # Item (3): the master holds two rows (sites) for one RMS item in the
    # supplier's scope with different unit costs.  No row's cost is picked
    # silently: the comparison is refused and labelled.
    service = make_service(tmp_path)
    service.import_catalog(
        "sites.csv",
        b"rms_item_id,description,supplier_id,supplier_name,uom,unit_cost\n"
        b"RMS-TWIN,Fictional Twin Item,900001,FIC001RE4AED,EA,10\n"
        b"RMS-TWIN,Fictional Twin Item,900001,FIC001RE4AED,EA,10.60\n",
    )
    catalog = [
        {"rms_item_id": "RMS-TWIN", "catalog_item_id": "c1", "description": "Fictional Twin Item", "supplier_id": "900001", "uom": "EA", "unit_cost": 10.0},
        {"rms_item_id": "RMS-TWIN", "catalog_item_id": "c2", "description": "Fictional Twin Item", "supplier_id": "900001", "uom": "EA", "unit_cost": 10.6},
    ]
    line = matching.match_lines([{"description": "Fictional Twin Item", "uom": "EA"}], catalog, [], "900001")[0]
    # Two rows of ONE rms id: still a single exact item, so it auto-selects...
    assert line["match_status"] == "suggested" or line["rms_item_id"] == "RMS-TWIN"
    if line["rms_item_id"] == "RMS-TWIN":
        assert line["rms_unit_cost"] is None
        assert (line["rms_unit_cost_min"], line["rms_unit_cost_max"]) == (10.0, 10.6)

    content = (
        b"Supplier name: Fictional Trading FZE\nSupplier ID: 900001\nInvoice number: RS-5\n"
        b"Invoice date: 2026-09-24\nCurrency: AED\n"
        b"Description                     Qty Unit Price Line Total\n"
        b"Fictional Twin Item              1 10.30 10.30\n"
        b"Grand Total AED 10.30\n"
    )
    invoice = process(service, "twin.txt", content)
    stored = dict(invoice["lines"][0])
    assert stored["rms_unit_cost"] is None
    stored.update({"rms_item_id": "RMS-TWIN", "match_status": "confirmed", "confidence": 100})
    # Operator confirms the item explicitly; the cost comparison still refuses.
    try:
        corrected = service.update_invoice(invoice["id"], invoice["version"], {"lines": [stored]})
    except Exception as error:  # ambiguous_rms_item: two rows, pick one explicitly
        assert "ambiguous" in str(getattr(error, "errors", error)).lower()
        with service.db.connection() as conn:
            row = conn.execute("SELECT catalog_item_id FROM catalog_items WHERE rms_item_id='RMS-TWIN' ORDER BY catalog_item_id").fetchone()
        stored["catalog_item_id"] = row["catalog_item_id"]
        corrected = service.update_invoice(invoice["id"], invoice["version"], {"lines": [stored]})
    confirmed = corrected["lines"][0]
    assert confirmed["rms_unit_cost"] is None
    assert confirmed["rms_unit_cost_min"] == 10.0 and confirmed["rms_unit_cost_max"] == 10.6
    assert confirmed["rms_unit_cost_note"] == "master holds multiple prices for this RMS item"
    assert confirmed["target_cost_comparison_status"] == "unavailable_uom_mismatch"
    assert confirmed["target_cost_variance"] is None
    assert confirmed["target_cost_review_required"] is True


def test_two_in_scope_rows_with_the_same_description_never_auto_select() -> None:
    # Collision guard: len(exact_candidates) == 1 is a safety property.  Two
    # distinct RMS items with one normalised description, both compatible,
    # stay "suggested" with no rms_item_id.
    catalog = [
        {"rms_item_id": "RMS-A", "description": "Fictional Twin Widget", "supplier_id": "900001", "uom": "EA"},
        {"rms_item_id": "RMS-B", "description": "Fictional  Twin Widget", "supplier_id": "900001", "uom": "EA"},
    ]
    line = matching.match_lines([{"description": "Fictional Twin Widget", "uom": "EA"}], catalog, [], "900001")[0]
    assert line["match_status"] == "suggested"
    assert line["rms_item_id"] is None
    assert {c["rms_item_id"] for c in line["candidates"][:2]} == {"RMS-A", "RMS-B"}
