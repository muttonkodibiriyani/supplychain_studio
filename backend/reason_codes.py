"""Governed exception reason codes (EXC-01, MAT-03).

One list, one place.  Every reason an invoice can be held out of the target
export maps onto exactly one code here, each code names the role that owns
the next action, and anything that does not map is a defect rather than a
silent pass-through: ``reason_code_for_error`` raises ``UnknownReasonCode``
and the registry test greps the service for every code literal it emits.

Codes are ordered by how early in the flow they arise; ``sort_codes`` keeps
that order so the CSV, the API and the workbench agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


OWNER_ROLES = (
    "brand_operator",
    "brand_reviewer",
    "item_master_owner",
    "finance_owner",
    "pilot_owner",
)


@dataclass(frozen=True)
class ReasonCode:
    code: str
    owner: str
    message: str
    level: str  # "invoice" or "line": where the evidence lives


REASON_CODES: tuple[ReasonCode, ...] = (
    ReasonCode(
        "extraction_failed",
        "pilot_owner",
        "document processing failed; read the error, then retry or record an exception",
        "invoice",
    ),
    ReasonCode(
        "extraction_limit",
        "pilot_owner",
        "document exceeds a processing limit (size, pages or format); it will not be retried",
        "invoice",
    ),
    ReasonCode(
        "document_type_not_invoice",
        "brand_operator",
        "document is not classified as an invoice; confirm the type from the source",
        "invoice",
    ),
    ReasonCode(
        "supplier_unresolved",
        "brand_operator",
        "supplier could not be resolved to a supplier ID; confirm the supplier",
        "invoice",
    ),
    ReasonCode(
        "line_unmapped",
        "item_master_owner",
        "a line has no RMS item; resolve it against the item master",
        "line",
    ),
    ReasonCode(
        "line_low_confidence",
        "brand_reviewer",
        "a line has a suggested RMS item that needs confirmation against the source",
        "line",
    ),
    ReasonCode(
        "unit_unconfirmed",
        "brand_reviewer",
        "unit of measure disagrees with the RMS item or could not be established",
        "line",
    ),
    ReasonCode(
        "price_above_tolerance",
        "brand_reviewer",
        "invoice cost differs from the RMS reference beyond tolerance, or the comparison is unavailable",
        "line",
    ),
    ReasonCode(
        "currency_basis_mismatch",
        "finance_owner",
        "invoice currency basis differs from the comparison basis (reserved for the currency unit)",
        "invoice",
    ),
    ReasonCode(
        "total_reconciliation_failed",
        "brand_reviewer",
        "line, subtotal, tax or total arithmetic does not reconcile",
        "invoice",
    ),
    ReasonCode(
        "duplicate_suspected",
        "finance_owner",
        "another invoice in this workspace shares the supplier and invoice number; confirm before approval",
        "invoice",
    ),
    ReasonCode(
        "header_field_missing",
        "brand_operator",
        "a required header field is missing or invalid",
        "invoice",
    ),
)

REGISTRY: dict[str, ReasonCode] = {entry.code: entry for entry in REASON_CODES}
_ORDER = {entry.code: index for index, entry in enumerate(REASON_CODES)}


class UnknownReasonCode(KeyError):
    """A validation error code or failure class with no governed reason code."""


# Validation error codes emitted by InvoiceService._validation_errors, keyed by
# the ``code`` field.  Codes whose meaning depends on the field they sit on are
# resolved in ``reason_code_for_error`` before this table is consulted.
VALIDATION_CODE_MAP: dict[str, str] = {
    "invalid_date": "header_field_missing",
    "invalid_currency": "header_field_missing",
    "invalid_order_number": "header_field_missing",
    "not_invoice": "document_type_not_invoice",
    "invalid_number": "total_reconciliation_failed",
    "negative_money": "total_reconciliation_failed",
    "nonpositive_quantity": "total_reconciliation_failed",
    "line_calculation_mismatch": "total_reconciliation_failed",
    "sum_mismatch": "total_reconciliation_failed",
    "target_cost_mismatch": "total_reconciliation_failed",
    "unmapped": "line_unmapped",
    "unknown_rms_item": "line_unmapped",
    "catalog_item_mismatch": "line_unmapped",
    "supplier_item_mismatch": "line_unmapped",
    "unit_unconfirmed": "unit_unconfirmed",
    "target_cost_review_required": "price_above_tolerance",
    "duplicate_supplier_invoice": "duplicate_suspected",
    "duplicate_suspected": "duplicate_suspected",
}

# ``required`` depends on which field is missing.
_REQUIRED_BY_FIELD: dict[str, str] = {
    "supplier_id": "supplier_unresolved",
    "supplier_name": "supplier_unresolved",
    "invoice_number": "header_field_missing",
    "invoice_date": "header_field_missing",
    "currency": "header_field_missing",
    "document": "header_field_missing",
    "supplier_site": "header_field_missing",
    "location": "header_field_missing",
    "location_type": "header_field_missing",
    "tax_code": "header_field_missing",
    "subtotal": "header_field_missing",
    "tax_total": "header_field_missing",
    "total": "header_field_missing",
    # No lines at all after extraction: the capture is unusable, not unmapped.
    "lines": "extraction_failed",
}
_REQUIRED_LINE_FIELD: dict[str, str] = {
    "description": "line_unmapped",
    "quantity": "total_reconciliation_failed",
    "unit_price": "total_reconciliation_failed",
    "line_total": "total_reconciliation_failed",
}

# Exception class names recorded in ``invoices.error`` by _fail_processing.
FAILURE_CLASS_MAP: dict[str, str] = {
    "ExtractionLimitError": "extraction_limit",
    "UnsupportedDocumentError": "extraction_failed",
    "DocumentExtractionError": "extraction_failed",
}
_DEFAULT_FAILURE_CODE = "extraction_failed"


def line_index_of(field: str) -> int | None:
    """``lines.3.rms_item_id`` -> 3; anything else -> None."""
    parts = field.split(".")
    if len(parts) >= 3 and parts[0] == "lines" and parts[1].isdigit():
        return int(parts[1])
    return None


def reason_code_for_error(
    error: Mapping[str, Any], lines: Sequence[Mapping[str, Any]] | None = None
) -> str:
    """Map one validation error onto its governed reason code.

    Raises ``UnknownReasonCode`` for a code or field that is not governed.
    """
    code = str(error.get("code") or "")
    field = str(error.get("field") or "")
    index = line_index_of(field)
    if code == "required":
        if index is not None:
            leaf = field.split(".")[-1]
            if leaf in _REQUIRED_LINE_FIELD:
                return _REQUIRED_LINE_FIELD[leaf]
            raise UnknownReasonCode(f"{field}.{code}")
        if field in _REQUIRED_BY_FIELD:
            return _REQUIRED_BY_FIELD[field]
        raise UnknownReasonCode(f"{field}.{code}")
    if code == "unmapped" and index is not None and lines is not None and index < len(lines):
        # A suggestion the matcher offered but nobody confirmed is a different
        # queue (reviewer) from a line with nothing to confirm (item master).
        if str(lines[index].get("match_status") or "") == "suggested":
            return "line_low_confidence"
    if code in VALIDATION_CODE_MAP:
        return VALIDATION_CODE_MAP[code]
    raise UnknownReasonCode(f"{field}.{code}")


def reason_code_for_failure(error_text: str | None) -> str:
    """Map the stored ``invoices.error`` text (``Class: message``) onto a code."""
    class_name = str(error_text or "").split(":", 1)[0].strip()
    return FAILURE_CLASS_MAP.get(class_name, _DEFAULT_FAILURE_CODE)


def sort_codes(codes: Iterable[str]) -> list[str]:
    unique = set(codes)
    unknown = unique - REGISTRY.keys()
    if unknown:
        raise UnknownReasonCode(", ".join(sorted(unknown)))
    return sorted(unique, key=_ORDER.__getitem__)


def assign_reason_codes(
    *,
    status: str,
    error_text: str | None,
    validation_errors: Sequence[Mapping[str, Any]],
    lines: Sequence[Mapping[str, Any]] | None,
    duplicate_level: str | None,
) -> list[str]:
    """Invoice-level governed reason codes for one invoice, in registry order.

    Queued and processing records carry no code: they are in flight, not
    exceptions.  A failed record carries exactly its failure class.  Anything
    reviewable carries one code per distinct approval/export gate it fails,
    plus ``duplicate_suspected`` when another record collides on identity.
    """
    if status in {"queued", "processing"}:
        return []
    if status == "failed":
        return [reason_code_for_failure(error_text)]
    codes = {reason_code_for_error(error, lines) for error in validation_errors}
    if duplicate_level in {"strong", "weak"}:
        codes.add("duplicate_suspected")
    return sort_codes(codes)


def line_reason_codes(
    index: int,
    line: Mapping[str, Any],
    validation_errors: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Line-level codes: the line's own validation errors plus the price gate
    the per-line comparison already recorded (it surfaces at invoice level
    only once the operator has not acknowledged it)."""
    codes: set[str] = set()
    for error in validation_errors:
        if line_index_of(str(error.get("field") or "")) == index:
            codes.add(reason_code_for_error(error, _padded(line, index)))
    if line.get("target_cost_review_required"):
        codes.add("price_above_tolerance")
    return sort_codes(codes)


def _padded(line: Mapping[str, Any], index: int) -> list[Mapping[str, Any]]:
    """Place ``line`` at ``index`` so field-indexed lookups resolve to it."""
    padded: list[Mapping[str, Any]] = [{}] * index
    padded.append(line)
    return padded


def registry_rows() -> list[dict[str, str]]:
    return [
        {"code": entry.code, "owner": entry.owner, "message": entry.message, "level": entry.level}
        for entry in REASON_CODES
    ]


def owners_for(codes: Iterable[str]) -> list[str]:
    """Distinct owner roles for a set of codes, in registry order."""
    seen: list[str] = []
    for code in sort_codes(codes):
        owner = REGISTRY[code].owner
        if owner not in seen:
            seen.append(owner)
    return seen


__all__ = [
    "OWNER_ROLES",
    "REASON_CODES",
    "REGISTRY",
    "ReasonCode",
    "UnknownReasonCode",
    "VALIDATION_CODE_MAP",
    "FAILURE_CLASS_MAP",
    "assign_reason_codes",
    "line_reason_codes",
    "owners_for",
    "reason_code_for_error",
    "reason_code_for_failure",
    "registry_rows",
    "sort_codes",
]
