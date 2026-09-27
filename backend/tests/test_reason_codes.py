"""Governed reason codes, duplicate suspicion, exception queue and KPIs.

Requirements EXC-01, MAT-03, INV-07, CTL-02.  Everything here runs on synthetic
text invoices and the fictional demo seed; no private corpus is involved.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import reason_codes as rc
from backend.app import create_app
from backend.service import (
    EXCEPTION_REPORT_COLUMNS,
    InvoiceService,
    Settings,
    ValidationFailure,
)

REPO = Path(__file__).resolve().parents[2]
GOVERNED = {
    "extraction_failed",
    "extraction_limit",
    "document_type_not_invoice",
    "supplier_unresolved",
    "line_unmapped",
    "line_low_confidence",
    "unit_unconfirmed",
    "price_above_tolerance",
    "adjustment_unpaired",
    "currency_basis_mismatch",
    "total_reconciliation_failed",
    "duplicate_suspected",
    "header_field_missing",
}


def make_service(tmp_path: Path, **overrides) -> InvoiceService:
    return InvoiceService(
        Settings(
            database_path=tmp_path / "invoices.sqlite3",
            source_dir=tmp_path / "sources",
            export_dir=tmp_path / "exports",
            workers=0,
            **overrides,
        )
    )


def text_invoice(
    ref: str,
    *,
    number: str = "TXT-INV-9",
    total: str = "21.00",
    date: str = "2026-09-24",
    supplier_id: str | None = "SUP-TXT",
    supplier_name: str = "Fictional Text Supplier",
) -> bytes:
    """A fictional plain-text tax invoice; ``ref`` keeps each upload's bytes distinct."""
    supplier_line = f"Supplier ID: {supplier_id}\n" if supplier_id else ""
    return (
        "TAX INVOICE\n"
        f"Supplier name: {supplier_name}\n"
        f"{supplier_line}"
        f"Invoice number: {number}\n"
        f"Invoice date: {date}\n"
        "Currency: AED\n"
        f"Reference: {ref}\n\n"
        "Item Description Qty UOM Unit Price Amount\n"
        "Fictional Widget 250ml 2 EA 10.00 20.00\n\n"
        "Subtotal 20.00\n"
        "Tax 1.00\n"
        f"Total {total}\n"
    ).encode()


def process(service: InvoiceService, filename: str, content: bytes) -> str:
    uploaded, duplicate = service.ingest_bytes(filename, content)
    assert not duplicate, "each fixture upload must have distinct bytes"
    assert service._claim_job() == uploaded["id"]
    service._process_job(uploaded["id"])
    return uploaded["id"]


# --- registry -------------------------------------------------------------


def test_registry_is_the_governed_list_with_an_owner_role_per_code() -> None:
    codes = [entry.code for entry in rc.REASON_CODES]
    assert set(codes) == GOVERNED
    assert len(codes) == len(set(codes)) == len(GOVERNED)
    for entry in rc.REASON_CODES:
        assert entry.owner in rc.OWNER_ROLES, entry.code
        assert entry.message.strip(), entry.code
        assert entry.level in {"invoice", "line"}, entry.code
    assert rc.sort_codes(reversed(codes)) == codes
    with pytest.raises(rc.UnknownReasonCode):
        rc.sort_codes(["not_a_code"])
    with pytest.raises(rc.UnknownReasonCode):
        rc.reason_code_for_error({"field": "total", "code": "made_up"})


def test_every_validation_code_literal_in_the_service_is_governed() -> None:
    source = (REPO / "backend" / "service.py").read_text()
    start = source.index("def _validation_errors(")
    end = source.index("\n    def ", start + 1)
    body = source[start:end]
    literals = set(re.findall(r'\berror\(\s*[^,]+,\s*"([a-z_]+)"', body))
    assert len(literals) >= 12, literals  # the regex must actually see the calls
    unknown = {code for code in literals if code != "required" and code not in rc.VALIDATION_CODE_MAP}
    assert not unknown, f"validation codes without a governed reason code: {sorted(unknown)}"
    for code, target in rc.VALIDATION_CODE_MAP.items():
        assert target in rc.REGISTRY, code
    for target in list(rc.FAILURE_CLASS_MAP.values()) + [rc.reason_code_for_failure("Whatever: x")]:
        assert target in rc.REGISTRY
    assert rc.reason_code_for_failure("ExtractionLimitError: too many pages") == "extraction_limit"
    assert rc.reason_code_for_failure("UnsupportedDocumentError: x") == "extraction_failed"
    assert rc.reason_code_for_failure(None) == "extraction_failed"


def test_every_required_field_error_the_service_emits_maps(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with service.db.connection() as conn:
        empty = service._validation_errors(conn, {"id": "probe", "lines": []})
        empty_line = service._validation_errors(conn, {"id": "probe", "lines": [{}]})
    assert {error["code"] for error in empty} >= {"required", "not_invoice"}
    mapped = {rc.reason_code_for_error(error) for error in empty + empty_line}
    assert mapped >= {
        "supplier_unresolved",
        "header_field_missing",
        "document_type_not_invoice",
        "extraction_failed",
        "line_unmapped",
        "total_reconciliation_failed",
    }
    assert mapped <= GOVERNED


def test_suggested_line_is_low_confidence_and_bare_line_is_unmapped() -> None:
    error = {"field": "lines.1.rms_item_id", "code": "unmapped"}
    assert rc.reason_code_for_error(error, [{}, {"match_status": "suggested"}]) == "line_low_confidence"
    assert rc.reason_code_for_error(error, [{}, {"match_status": "unmatched"}]) == "line_unmapped"
    assert rc.line_reason_codes(1, {"match_status": "suggested"}, [error]) == ["line_low_confidence"]
    # A flagged line with no comparison made is a state, not an exception.
    assert rc.line_reason_codes(0, {"target_cost_review_required": True}, [error]) == []
    assert rc.comparison_state({"target_cost_review_required": True}) == "unavailable"
    assert rc.assign_reason_codes(
        status="queued", error_text=None, validation_errors=[error], lines=[], duplicate_level="strong"
    ) == []
    assert rc.assign_reason_codes(
        status="failed", error_text="ExtractionLimitError: x", validation_errors=[], lines=[], duplicate_level=None
    ) == ["extraction_limit"]
    assert rc.owners_for(["header_field_missing", "line_unmapped", "supplier_unresolved"]) == [
        "brand_operator",
        "item_master_owner",
    ]


def test_frontend_registry_copy_matches_the_backend() -> None:
    source = (REPO / "src" / "reasonCodes.ts").read_text()
    client = re.findall(r"\{code:'([a-z_]+)',owner:'([a-z_]+)',message:'([^']*)',level:'(invoice|line)'\}", source)
    assert client == [(e.code, e.owner, e.message, e.level) for e in rc.REASON_CODES]


# --- API, CSV -------------------------------------------------------------


def test_invoices_expose_reason_codes_and_the_csv_gains_code_and_owner_columns(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "invoices.sqlite3",
        source_dir=tmp_path / "sources",
        export_dir=tmp_path / "exports",
        workers=0,
        enable_demo_seed=True,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post("/api/demo").status_code == 200
        registry = client.get("/api/reason-codes").json()["reason_codes"]
        assert [row["code"] for row in registry] == [e.code for e in rc.REASON_CODES]

        listed = client.get("/api/invoices").json()["items"]
        assert listed and all(isinstance(item["reason_codes"], list) for item in listed)
        by_id = {item["id"]: item for item in listed}
        assert "line_low_confidence" in by_id["demo-invoice-002"]["reason_codes"]
        assert "brand_reviewer" in by_id["demo-invoice-002"]["reason_owners"]
        assert by_id["demo-invoice-002"]["duplicate_suspicion"] == {"level": None, "matches": []}

        detail = client.get("/api/invoices/demo-invoice-002").json()
        assert detail["lines"][0]["reason_codes"] == ["line_low_confidence"]
        assert detail["price_comparison"]["lines"] == len(detail["lines"])
        assert detail["price_comparison"]["unavailable"] >= 1
        assert "price_above_tolerance" not in detail["reason_codes"]

        queue = client.get("/api/exceptions").json()
        assert queue["invoices_total"] == len(listed)
        codes = {group["code"]: group for group in queue["groups"]}
        assert codes["line_low_confidence"]["count"] == 1
        assert codes["line_low_confidence"]["owner"] == "brand_reviewer"
        assert codes["line_low_confidence"]["oldest_invoice_id"] == "demo-invoice-002"
        assert codes["line_low_confidence"]["invoices"][0]["id"] == "demo-invoice-002"
        assert codes["line_low_confidence"]["oldest_age_seconds"] >= 0
        assert [row["code"] for row in queue["registry"]] == [e.code for e in rc.REASON_CODES]

        kpis = client.get("/api/kpis").json()
        assert kpis["contains_demo_data"] is True
        assert kpis["k1_touchless"]["denominator"] == len(listed)
        assert kpis["k3_cycle_time"] == {
            "median_seconds": None,
            "n": 0,
            "evaluable": False,
            "not_evaluable_reason": kpis["k3_cycle_time"]["not_evaluable_reason"],
            "definition": kpis["k3_cycle_time"]["definition"],
        }
        assert kpis["k3_cycle_time"]["not_evaluable_reason"]

        report = client.get("/api/reports/exceptions.csv")
        assert report.status_code == 200
        rows = list(csv.DictReader(io.StringIO(report.content.decode("utf-8-sig"))))
        assert list(rows[0]) == list(EXCEPTION_REPORT_COLUMNS)
        assert list(EXCEPTION_REPORT_COLUMNS[:5]) == [
            "Invoice ID",
            "Filename",
            "Document Type",
            "Status",
            "Reasons",
        ]
        csv_by_id = {row["Invoice ID"]: row for row in rows}
        assert csv_by_id["demo-invoice-002"]["Reason Codes"].split(" | ") == by_id["demo-invoice-002"]["reason_codes"]
        assert csv_by_id["demo-invoice-002"]["Owner Roles"].split(" | ") == by_id["demo-invoice-002"]["reason_owners"]
        for row in rows:
            for code in filter(None, row["Reason Codes"].split(" | ")):
                assert code in rc.REGISTRY, row


# --- duplicate suspicion --------------------------------------------------


@pytest.mark.parametrize(
    ("second", "expected"),
    [
        pytest.param({}, "strong", id="same supplier, number, total, date"),
        pytest.param({"total": "31.50"}, "weak", id="same supplier and number, different total"),
        pytest.param({"date": "2026-09-25"}, "weak", id="same supplier and number, different date"),
        pytest.param({"total": "31.50", "date": "2026-09-25"}, "weak", id="different total and date"),
        pytest.param({"number": "TXT-INV-10"}, None, id="different invoice number"),
        pytest.param({"supplier_id": "SUP-OTHER"}, None, id="different supplier id"),
        pytest.param(
            {"supplier_id": None, "supplier_name": "FICTIONAL TEXT SUPPLIER L.L.C."},
            "strong",
            id="no id on one side: normalised supplier names decide",
        ),
        pytest.param(
            {"supplier_id": None, "supplier_name": "Another Fictional Vendor"},
            None,
            id="no id on one side and different names",
        ),
    ],
)
def test_duplicate_matrix(tmp_path: Path, second: dict, expected: str | None) -> None:
    service = make_service(tmp_path)
    first = process(service, "first.txt", text_invoice("one"))
    other = process(service, "second.txt", text_invoice("two", **second))

    invoice = service.get_invoice(other)
    assert invoice["duplicate_suspicion"]["level"] == expected
    assert ("duplicate_suspected" in invoice["reason_codes"]) is (expected is not None)
    events = [event["event_type"] for event in service.audit(other)["items"]]
    assert ("duplicate_suspected" in events) is (expected is not None)
    if expected:
        assert invoice["duplicate_suspicion"]["matches"][0]["invoice_id"] == first
        assert any(first in warning for warning in invoice["warnings"])
        assert "finance_owner" in invoice["reason_owners"]
        # symmetric on read: the earlier invoice now sees the later one
        assert service.get_invoice(first)["duplicate_suspicion"]["matches"][0]["invoice_id"] == other
        with pytest.raises(ValidationFailure) as blocked:
            service.approve(other, invoice["version"])
        assert any(error["code"] == "duplicate_supplier_invoice" for error in blocked.value.errors)
    else:
        assert service.get_invoice(first)["duplicate_suspicion"]["level"] is None
    # never auto-deleted
    listing = service.list_invoices(status=None, search=None, offset=0, limit=10)
    assert {item["id"] for item in listing["items"]} == {first, other}


def test_duplicate_by_normalised_supplier_name_when_neither_side_has_an_id(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    first = process(service, "a.txt", text_invoice("a", supplier_id=None))
    second = process(
        service, "b.txt", text_invoice("b", supplier_id=None, supplier_name="FICTIONAL TEXT SUPPLIER L.L.C.")
    )
    assert service.get_invoice(first)["supplier_id"] in (None, "")
    invoice = service.get_invoice(second)
    assert invoice["duplicate_suspicion"]["level"] == "strong"
    assert invoice["duplicate_suspicion"]["matches"][0]["invoice_id"] == first
    unrelated = process(service, "c.txt", text_invoice("c", supplier_id=None, supplier_name="Another Fictional Vendor"))
    assert service.get_invoice(unrelated)["duplicate_suspicion"]["level"] is None


def test_failed_records_are_not_duplicate_identities(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    first = process(service, "a.txt", text_invoice("a"))
    second = process(service, "b.txt", text_invoice("b"))
    assert service.get_invoice(second)["duplicate_suspicion"]["level"] == "strong"
    with service.db.transaction(immediate=True) as conn:
        conn.execute("UPDATE invoices SET status='failed', error='DocumentExtractionError: x' WHERE id=?", (first,))
    assert service.get_invoice(second)["duplicate_suspicion"]["level"] is None
    assert service.get_invoice(first)["reason_codes"] == ["extraction_failed"]
    assert service.get_invoice(first)["reason_owners"] == ["pilot_owner"]


# --- KPIs -----------------------------------------------------------------


def test_kpi_arithmetic_on_a_seeded_workspace(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    ids = [process(service, f"{n}.txt", text_invoice(str(n), number=f"TXT-{n}")) for n in range(5)]
    queued, _ = service.ingest_bytes("queued.txt", text_invoice("q", number="TXT-Q"))
    a, b, c, d, f = ids
    base = "2026-09-20T08:00:00Z"

    def at(seconds: int) -> str:
        minutes, secs = divmod(seconds, 60)
        return f"2026-09-20T08:{minutes:02d}:{secs:02d}Z"

    plan = {
        # id: (status, extraction detail, human events, ready-at seconds)
        a: ("ready", {"line_count": 1, "auto_matched_lines": 1}, [], 100),
        b: ("ready", {"line_count": 1, "auto_matched_lines": 0}, ["invoice_edited"], 300),
        c: ("exported", {"line_count": 2, "auto_matched_lines": 2}, ["invoice_exported"], 50),
        d: ("needs_review", {"line_count": 1, "auto_matched_lines": 1}, ["invoice_rematched"], None),
        f: ("needs_review", {"line_count": 1}, [], None),  # legacy detail: falls back to lines
    }
    with service.db.transaction(immediate=True) as conn:
        conn.execute("DELETE FROM audit_events")
        for invoice_id, (status, detail, human, ready_at) in plan.items():
            conn.execute(
                "UPDATE invoices SET status=?, created_at=? WHERE id=?", (status, base, invoice_id)
            )
            service._audit(conn, invoice_id, "uploaded", actor="user", version=1, created_at=base)
            service._audit(
                conn, invoice_id, "extraction_completed", actor="system", version=2,
                from_status="processing", to_status="needs_review", details=detail, created_at=at(5),
            )
            for event in human:
                service._audit(conn, invoice_id, event, actor="user", version=3, created_at=at(20))
            if ready_at is not None:
                service._audit(
                    conn, invoice_id, "invoice_approved", actor="user", version=4,
                    from_status="needs_review", to_status="ready", created_at=at(ready_at),
                )
        conn.execute(
            "UPDATE invoice_lines SET match_status='auto', rms_item_id='RMS-F' WHERE invoice_id=?", (f,)
        )
        conn.execute("UPDATE invoices SET created_at=? WHERE id=?", (base, queued["id"]))

    kpis = service.kpis()
    assert kpis["contains_demo_data"] is False
    assert (kpis["k1_touchless"]["numerator"], kpis["k1_touchless"]["denominator"]) == (2, 6)
    assert kpis["k1_touchless"]["evaluable"] is True
    assert kpis["k1_touchless"]["approval_stage"] == 3
    assert kpis["k1_touchless"]["not_evaluable_reason"] is None
    assert kpis["k3_cycle_time"]["evaluable"] is True
    assert (kpis["k2_first_time_match"]["numerator"], kpis["k2_first_time_match"]["denominator"]) == (4, 5)
    assert kpis["k3_cycle_time"]["n"] == 3
    assert kpis["k3_cycle_time"]["median_seconds"] == 100.0
    for key in ("k1_touchless", "k2_first_time_match", "k3_cycle_time"):
        assert kpis[key]["definition"]

    # even count -> mean of the middle pair
    with service.db.transaction(immediate=True) as conn:
        conn.execute("UPDATE invoices SET status='ready' WHERE id=?", (d,))
        service._audit(
            conn, d, "invoice_approved", actor="user", version=5,
            from_status="needs_review", to_status="ready", created_at=at(200),
        )
    kpis = service.kpis()
    assert kpis["k3_cycle_time"]["n"] == 4
    assert kpis["k3_cycle_time"]["median_seconds"] == 150.0
    assert kpis["k1_touchless"]["numerator"] == 2  # d was rematched by a person

    queue = service.exception_queue()
    assert queue["invoices_total"] == 6
    groups = {group["code"]: group for group in queue["groups"]}
    assert groups["header_field_missing"]["count"] >= 2
    assert groups["header_field_missing"]["owner"] == "brand_operator"
    assert all(group["oldest_age_seconds"] is not None for group in queue["groups"])
    assert queue["groups"] == sorted(queue["groups"], key=lambda g: (-g["count"], g["code"]))


def test_price_gate_codes_only_a_comparison_that_was_made_and_failed() -> None:
    above = {"target_cost_comparison_status": "above_tolerance", "target_cost_review_required": True}
    within = {"target_cost_comparison_status": "within_tolerance", "target_cost_review_required": False}
    unavailable = {
        "target_cost_comparison_status": "unavailable_no_match",
        "target_cost_review_required": True,
    }
    legacy = {"target_cost_comparison_status": None, "target_cost_review_required": True}
    assert rc.comparison_state(above) == "above_tolerance"
    assert rc.comparison_state(within) == "within_tolerance"
    assert rc.comparison_state(unavailable) == "unavailable"
    assert rc.comparison_state(legacy) == "unavailable"
    assert rc.comparison_state({}) is None
    assert rc.line_price_code(above) == "price_above_tolerance"
    assert rc.line_price_code(unavailable) is None
    assert rc.line_reason_codes(0, above, []) == ["price_above_tolerance"]
    assert rc.line_reason_codes(0, unavailable, []) == []
    assert rc.comparison_summary([above, within, unavailable, legacy, {}]) == {
        "above_tolerance": 1,
        "within_tolerance": 1,
        "unavailable": 2,
        "lines": 5,
    }

    gate = {"field": "target_cost_reviewed", "code": "target_cost_review_required"}

    def assign(lines, variance=False):
        return rc.assign_reason_codes(
            status="needs_review",
            error_text=None,
            validation_errors=[gate],
            lines=lines,
            duplicate_level=None,
            target_variance_flagged=variance,
        )

    assert assign([within, unavailable]) == []
    assert assign([above, within]) == ["price_above_tolerance"]
    assert assign([above, unavailable]) == ["price_above_tolerance"]
    # The invoice-level target variance is a reconciliation failure, coded as one.
    assert assign([within], variance=True) == ["total_reconciliation_failed"]
    assert assign([above, unavailable], variance=True) == [
        "price_above_tolerance",
        "total_reconciliation_failed",
    ]
    assert "price_comparison_unavailable" not in rc.REGISTRY
    assert rc.REGISTRY["price_above_tolerance"].owner == "brand_reviewer"


def test_adjustment_rows_leave_the_item_master_queue_but_are_never_dropped() -> None:
    error = {"field": "lines.0.rms_item_id", "code": "unmapped"}
    discount = {"description": "Promotional discount", "match_status": "unmatched"}
    credit = {"description": "CREDIT for returned goods", "match_status": "unmatched"}
    product = {"description": "Fictional Widget 250ml", "match_status": "unmatched"}
    suggested_discount = {"description": "Discount", "match_status": "suggested"}
    assert rc.is_adjustment_line(discount) and rc.is_adjustment_line(credit)
    assert not rc.is_adjustment_line(product)
    assert rc.reason_code_for_error(error, [discount]) == "adjustment_unpaired"
    assert rc.reason_code_for_error(error, [credit]) == "adjustment_unpaired"
    assert rc.reason_code_for_error(error, [product]) == "line_unmapped"
    assert rc.reason_code_for_error(error, [suggested_discount]) == "line_low_confidence"
    assert rc.REGISTRY["adjustment_unpaired"].owner == "brand_reviewer"
    assert rc.owners_for(["adjustment_unpaired"]) == ["brand_reviewer"]
    # Generic vocabulary only: the keyword list carries no supplier spelling.
    assert all(word.islower() and word.isalpha() for word in rc.ADJUSTMENT_KEYWORDS)
    # The row still fails the approval gate (it is kept and flagged, not dropped).
    assert rc.assign_reason_codes(
        status="needs_review",
        error_text=None,
        validation_errors=[error],
        lines=[discount],
        duplicate_level=None,
    ) == ["adjustment_unpaired"]


def test_k1_and_k3_are_not_evaluable_before_any_approval(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    process(service, "k1-a.txt", text_invoice("k1-a"))
    process(service, "k1-b.txt", text_invoice("k1-b", number="TXT-INV-10"))
    kpis = service.kpis()
    assert kpis["k1_touchless"]["denominator"] == 2
    assert kpis["k1_touchless"]["numerator"] == 0
    assert kpis["k1_touchless"]["approval_stage"] == 0
    assert kpis["k1_touchless"]["evaluable"] is False
    assert "ready" in kpis["k1_touchless"]["not_evaluable_reason"]
    assert kpis["k3_cycle_time"]["n"] == 0
    assert kpis["k3_cycle_time"]["evaluable"] is False
    assert kpis["k3_cycle_time"]["not_evaluable_reason"]
    # K2 is evaluable as soon as extraction has completed; it needs no approval.
    assert kpis["k2_first_time_match"]["denominator"] == 2
