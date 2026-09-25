#!/usr/bin/env python3
"""Evaluate local invoice extraction without retaining private document text.

The receipt contains content-derived opaque IDs, aggregate counts, extraction
methods and completeness/reconciliation signals.  It deliberately excludes
filenames, relative paths, supplier names, invoice identifiers, product text
and monetary values.  Run this inside the release container with networking
disabled for a reproducible assessment of private corpora.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.extraction import (  # noqa: E402
    SUPPORTED_EXTENSIONS,
    ExtractionLimits,
    extract_document,
)


SCHEMA_VERSION = "invoice-corpus-evaluation.v1"
# Source files written by POST /api/demo (backend.service.DEMO_SOURCE_PREFIX).
# Seeded demo data is fictional and its lines are stored as matched without
# running the matcher, so a corpus holding it is refused as a measurement
# source rather than silently counted.
DEMO_SOURCE_PREFIX = "FICTIONAL-demo-invoice-"
CORE_LINE_FIELDS = ("description", "quantity", "unit_price", "line_total")
SOURCE_TARGET_FIELDS = (
    "description",
    "quantity",
    "uom",
    "net_unit_price",
    "line_total",
    "upc",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bool(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _safe_resolve(root: Path, relative: str) -> tuple[Path, str]:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Inventory contains an absolute or parent-traversing path.")
    resolved = (root / relative_path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Inventory path resolves outside the input root.")
    return resolved, relative_path.as_posix()


def _load_records(input_root: Path, status_csv: Path | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if status_csv:
        with status_csv.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"path", "classification", "needs_ocr"}
            if not required.issubset(reader.fieldnames or []):
                missing = ", ".join(sorted(required - set(reader.fieldnames or [])))
                raise ValueError(f"Status CSV is missing required columns: {missing}.")
            inventory_rows = list(reader)
        for row in inventory_rows:
            path, relative = _safe_resolve(input_root, row["path"])
            if not path.is_file():
                records.append(
                    {
                        "relative": relative,
                        "path": str(path),
                        "extension": path.suffix.lower(),
                        "audit_classification": row.get("classification") or "unclassified",
                        "audit_needs_ocr": _bool(row.get("needs_ocr")),
                        "audit_heuristic_lines": int(row.get("heuristic_lines") or 0),
                        "inventory_error": "missing_file",
                    }
                )
                continue
            records.append(
                {
                    "relative": relative,
                    "path": str(path),
                    "extension": path.suffix.lower(),
                    "audit_classification": row.get("classification") or "unclassified",
                    "audit_needs_ocr": _bool(row.get("needs_ocr")),
                    "audit_heuristic_lines": int(row.get("heuristic_lines") or 0),
                }
            )
    else:
        for path in sorted(input_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                records.append(
                    {
                        "relative": path.relative_to(input_root).as_posix(),
                        "path": str(path),
                        "extension": path.suffix.lower(),
                        "audit_classification": "unclassified",
                        "audit_needs_ocr": path.suffix.lower() in {
                            ".png",
                            ".jpg",
                            ".jpeg",
                            ".tif",
                            ".tiff",
                            ".bmp",
                            ".webp",
                        },
                        "audit_heuristic_lines": 0,
                    }
                )

    demo_records = [
        record for record in records if Path(record["relative"]).name.startswith(DEMO_SOURCE_PREFIX)
    ]
    if demo_records:
        raise SystemExit(
            f"Refusing to evaluate: {len(demo_records)} demo-seeded source file(s) "
            f"(prefix {DEMO_SOURCE_PREFIX!r}) are inside the input root. Seeded demo "
            "data is fictional and must not enter a measurement."
        )

    for record in records:
        path = Path(record["path"])
        if record.get("inventory_error"):
            content_hash = "missing"
            size = 0
        else:
            content_hash = _sha256_file(path)
            size = path.stat().st_size
        identity = hashlib.sha256(
            f"{record['relative']}\0{content_hash}".encode("utf-8")
        ).hexdigest()
        record["document_id"] = identity[:24]
        record["content_sha256"] = content_hash
        record["source_bytes"] = size
    return records


def _select_records(
    records: Sequence[dict[str, Any]],
    selection: str,
    sample_size: int,
    sample_per_stratum: int,
) -> list[dict[str, Any]]:
    if selection == "embedded":
        selected = [
            record
            for record in records
            if record["extension"] == ".pdf" and not record["audit_needs_ocr"]
        ]
    elif selection == "ocr":
        selected = [record for record in records if record["audit_needs_ocr"]]
    elif selection == "sample":
        strata: dict[tuple[str, bool, str, str], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            parent_key = hashlib.sha256(
                str(Path(record["relative"]).parent).encode("utf-8")
            ).hexdigest()[:8]
            key = (
                record["audit_classification"],
                record["audit_needs_ocr"],
                record["extension"],
                parent_key,
            )
            strata[key].append(record)
        selected = []
        for key in sorted(strata, key=str):
            ordered = sorted(strata[key], key=lambda item: item["document_id"])
            selected.extend(ordered[:sample_per_stratum])
        if len(selected) < sample_size:
            chosen = {record["document_id"] for record in selected}
            remainder = sorted(
                (record for record in records if record["document_id"] not in chosen),
                key=lambda item: item["document_id"],
            )
            selected.extend(remainder[: sample_size - len(selected)])
        selected = sorted(selected, key=lambda item: item["document_id"])[:sample_size]
    else:
        selected = list(records)

    # Embedded-text documents go first so a long OCR tail never hides the
    # cheaper, independently useful result.  No path or name is printed.
    return sorted(
        selected,
        key=lambda item: (item["audit_needs_ocr"], item["extension"] != ".pdf", item["document_id"]),
    )


def _present(line: Mapping[str, Any], field: str) -> bool:
    value = line.get(field)
    return value is not None and value != ""


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(0.02, abs(right) * 0.001)


def _warning_categories(warnings: Iterable[str]) -> list[str]:
    categories: set[str] = set()
    for warning in warnings:
        lowered = warning.casefold()
        if "no credible invoice line" in lowered:
            categories.add("no_rows")
        elif "document type" in lowered or "outside the invoice workflow" in lowered:
            categories.add("document_type_review")
        elif "ocr confidence" in lowered:
            categories.add("low_ocr_confidence")
        elif "ocr used english" in lowered:
            categories.add("ocr_language_limit")
        elif "table" in lowered and ("no source rows" in lowered or "no row" in lowered):
            categories.add("unparsed_table_section")
        elif "ambiguous" in lowered or "withheld" in lowered:
            categories.add("withheld_ambiguous_field")
        else:
            categories.add("other")
    return sorted(categories)


def _core_gate_reasons(record: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if record.get("status") != "completed":
        return ["extraction_failed"]
    if record.get("document_type") != "invoice":
        reasons.append("not_classified_invoice")
    line_count = int(record.get("line_count") or 0)
    diagnostics = record.get("table_diagnostics") or {}
    if line_count == 0:
        reasons.append("no_rows")
    if int(diagnostics.get("recognized_table_sections") or 0) == 0:
        reasons.append("no_recognized_table")
    if int(diagnostics.get("sections_without_rows") or 0) > 0:
        reasons.append("empty_table_section")
    if int(diagnostics.get("possible_unparsed_rows") or 0) > 0:
        reasons.append("possible_unparsed_rows")
    if int(diagnostics.get("unpaired_adjustment_rows") or 0) > 0:
        reasons.append("unpaired_adjustment_rows")
    if bool(diagnostics.get("legacy_fallback")):
        reasons.append("legacy_fallback")
    if line_count and int(record.get("core_complete_lines") or 0) < line_count:
        reasons.append("missing_core_line_fields")
    if record.get("subtotal_reconciled") is None:
        reasons.append("subtotal_unavailable")
    elif record.get("subtotal_reconciled") is False:
        reasons.append("subtotal_mismatch")
    return reasons


def _source_target_gate_reasons(record: Mapping[str, Any]) -> list[str]:
    reasons = _core_gate_reasons(record)
    line_count = int(record.get("line_count") or 0)
    if line_count and int(record.get("source_target_complete_lines") or 0) < line_count:
        reasons.append("missing_source_target_fields")
    return reasons


def _evaluate_one(record: Mapping[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    base: dict[str, Any] = {
        "document_id": record["document_id"],
        "content_sha256": record["content_sha256"],
        "extension": record["extension"],
        "source_bytes": record["source_bytes"],
        "audit_classification": record["audit_classification"],
        "audit_needs_ocr": record["audit_needs_ocr"],
        "audit_heuristic_lines": record.get("audit_heuristic_lines", 0),
    }
    if record.get("inventory_error"):
        return {
            **base,
            "status": "failed",
            "failure_type": record["inventory_error"],
            "seconds": 0.0,
        }
    try:
        result = extract_document(
            record["path"],
            filename=Path(record["path"]).name,
            limits=ExtractionLimits(),
        )
    except Exception as exc:
        return {
            **base,
            "status": "failed",
            "failure_type": type(exc).__name__,
            "seconds": round(time.monotonic() - started, 3),
        }

    lines = list(result.get("lines") or [])
    field_counts = {
        field: sum(_present(line, field) for line in lines)
        for field in (
            "description",
            "quantity",
            "uom",
            "unit_price",
            "net_unit_price",
            "gross_unit_price",
            "printed_unit_price",
            "line_total",
            "gross_line_total",
            "discount_line_total",
            "upc",
            "item_code",
            "tax_rate",
            "tax_amount",
            "discount_rate",
            "discount_amount",
        )
    }
    core_complete_lines = sum(
        all(_present(line, field) for field in CORE_LINE_FIELDS) for line in lines
    )
    source_target_complete_lines = sum(
        all(_present(line, field) for field in SOURCE_TARGET_FIELDS) for line in lines
    )

    arithmetic_comparable = 0
    arithmetic_equal = 0
    arithmetic_without_explicit_discount = 0
    arithmetic_without_explicit_discount_equal = 0
    for line in lines:
        quantity = line.get("quantity")
        unit_price = line.get("unit_price")
        line_total = line.get("line_total")
        if None in (quantity, unit_price, line_total):
            continue
        arithmetic_comparable += 1
        equal = _close(float(quantity) * float(unit_price), float(line_total))
        arithmetic_equal += int(equal)
        if line.get("discount_rate") is None and line.get("discount_amount") is None:
            arithmetic_without_explicit_discount += 1
            arithmetic_without_explicit_discount_equal += int(equal)

    subtotal_reconciliation: bool | None = None
    if (
        result.get("subtotal") is not None
        and lines
        and all(line.get("line_total") is not None for line in lines)
    ):
        subtotal_reconciliation = _close(
            sum(float(line["line_total"]) for line in lines),
            float(result["subtotal"]),
        )

    diagnostics = dict(result.get("table_diagnostics") or {})
    field_provenance = dict(result.get("field_provenance") or {})
    diagnostic_gate = (
        int(diagnostics.get("recognized_table_sections") or 0) > 0
        and int(diagnostics.get("sections_without_rows") or 0) == 0
        and int(diagnostics.get("possible_unparsed_rows") or 0) == 0
        and int(diagnostics.get("unpaired_adjustment_rows") or 0) == 0
        and not bool(diagnostics.get("legacy_fallback"))
    )
    invoice_gate = result.get("document_type") == "invoice" and bool(lines)
    strict_core_reconciled = bool(
        invoice_gate
        and diagnostic_gate
        and core_complete_lines == len(lines)
        and subtotal_reconciliation is True
    )
    strict_source_target_reconciled = bool(
        strict_core_reconciled and source_target_complete_lines == len(lines)
    )

    evaluated = {
        **base,
        "status": "completed",
        "seconds": round(time.monotonic() - started, 3),
        "pages": result.get("pages"),
        "extraction_method": result.get("extraction_method") or "unknown",
        "document_type": result.get("document_type") or "unknown",
        "document_type_confidence": result.get("document_type_confidence") or 0.0,
        "table_extraction_method": result.get("table_extraction_method") or "none",
        "table_diagnostics": {
            "recognized_table_sections": int(diagnostics.get("recognized_table_sections") or 0),
            "sections_without_rows": int(diagnostics.get("sections_without_rows") or 0),
            "possible_unparsed_rows": int(diagnostics.get("possible_unparsed_rows") or 0),
            "emitted_rows": int(diagnostics.get("emitted_rows") or len(lines)),
            "joined_continuation_lines": int(diagnostics.get("joined_continuation_lines") or 0),
            "legacy_fallback": bool(diagnostics.get("legacy_fallback")),
            "header_schemas": list(diagnostics.get("header_schemas") or []),
            "paired_adjustment_rows": int(diagnostics.get("paired_adjustment_rows") or 0),
            "unpaired_adjustment_rows": int(diagnostics.get("unpaired_adjustment_rows") or 0),
            "source_data_rows": int(diagnostics.get("source_data_rows") or len(lines)),
        },
        "line_count": len(lines),
        "line_field_counts": field_counts,
        "core_complete_lines": core_complete_lines,
        "source_target_complete_lines": source_target_complete_lines,
        "quantity_x_unit_price": {
            "comparable": arithmetic_comparable,
            "equal_to_line_total": arithmetic_equal,
            "without_explicit_discount": arithmetic_without_explicit_discount,
            "without_explicit_discount_equal": arithmetic_without_explicit_discount_equal,
        },
        "subtotal_reconciled": subtotal_reconciliation,
        "subtotal_provenance": field_provenance.get("subtotal"),
        "tax_total_provenance": field_provenance.get("tax_total"),
        "strict_core_reconciled_review_gate": strict_core_reconciled,
        "strict_source_target_reconciled_review_gate": strict_source_target_reconciled,
        "warning_count": len(result.get("warnings") or []),
        "warning_categories": _warning_categories(result.get("warnings") or []),
    }
    evaluated["strict_core_gate_reasons"] = _core_gate_reasons(evaluated)
    evaluated["strict_source_target_gate_reasons"] = _source_target_gate_reasons(evaluated)
    return evaluated


def _counter(records: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get(field, "unknown")) for record in records).items()))


def _summarize(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    completed = [record for record in results if record.get("status") == "completed"]
    failed = [record for record in results if record.get("status") == "failed"]
    line_count = sum(int(record.get("line_count") or 0) for record in completed)
    invoice_candidates = [
        record for record in completed if record.get("audit_classification") == "invoice_candidate"
    ]
    field_totals: Counter[str] = Counter()
    warning_categories: Counter[str] = Counter()
    header_schemas: Counter[str] = Counter()
    missing_field_documents: Counter[str] = Counter()
    for record in completed:
        field_totals.update(record.get("line_field_counts") or {})
        warning_categories.update(record.get("warning_categories") or [])
        for schema in set((record.get("table_diagnostics") or {}).get("header_schemas") or []):
            header_schemas[str(schema)] += 1
        document_lines = int(record.get("line_count") or 0)
        if document_lines:
            for field in SOURCE_TARGET_FIELDS:
                if int((record.get("line_field_counts") or {}).get(field) or 0) < document_lines:
                    missing_field_documents[field] += 1
    arithmetic_comparable = sum(
        int((record.get("quantity_x_unit_price") or {}).get("comparable") or 0)
        for record in completed
    )
    arithmetic_equal = sum(
        int((record.get("quantity_x_unit_price") or {}).get("equal_to_line_total") or 0)
        for record in completed
    )
    subtotal_values = Counter(str(record.get("subtotal_reconciled")) for record in completed)
    core_gate_reasons = Counter(
        reason for record in completed for reason in _core_gate_reasons(record)
    )
    invoice_candidate_core_gate_reasons = Counter(
        reason for record in invoice_candidates for reason in _core_gate_reasons(record)
    )
    source_target_gate_reasons = Counter(
        reason for record in completed for reason in _source_target_gate_reasons(record)
    )
    return {
        "selected": len(results),
        "completed": len(completed),
        "failed": len(failed),
        "prior_heuristic_documents_with_rows": sum(
            int(record.get("audit_heuristic_lines") or 0) > 0 for record in results
        ),
        "prior_heuristic_rows": sum(
            int(record.get("audit_heuristic_lines") or 0) for record in results
        ),
        "documents_with_candidate_rows": sum(int(record.get("line_count") or 0) > 0 for record in completed),
        "candidate_rows": line_count,
        "core_complete_candidate_rows": sum(int(record.get("core_complete_lines") or 0) for record in completed),
        "source_target_complete_candidate_rows": sum(
            int(record.get("source_target_complete_lines") or 0) for record in completed
        ),
        "line_field_counts": dict(sorted(field_totals.items())),
        "document_types": _counter(completed, "document_type"),
        "extraction_methods": _counter(completed, "extraction_method"),
        "table_extraction_methods": _counter(completed, "table_extraction_method"),
        "recognized_header_schemas_by_document": dict(header_schemas.most_common()),
        "documents_missing_line_fields": dict(sorted(missing_field_documents.items())),
        "audit_classifications": _counter(completed, "audit_classification"),
        "invoice_candidate_document_types": _counter(invoice_candidates, "document_type"),
        "quantity_x_unit_price_comparable": arithmetic_comparable,
        "quantity_x_unit_price_equals_line_total": arithmetic_equal,
        "subtotal_reconciliation": dict(sorted(subtotal_values.items())),
        "strict_core_reconciled_review_gate_documents": sum(
            bool(record.get("strict_core_reconciled_review_gate")) for record in completed
        ),
        "strict_source_target_reconciled_review_gate_documents": sum(
            bool(record.get("strict_source_target_reconciled_review_gate")) for record in completed
        ),
        "strict_core_gate_rejection_reasons": dict(sorted(core_gate_reasons.items())),
        "invoice_candidate_core_gate_rejection_reasons": dict(
            sorted(invoice_candidate_core_gate_reasons.items())
        ),
        "strict_source_target_gate_rejection_reasons": dict(
            sorted(source_target_gate_reasons.items())
        ),
        "documents_with_possible_unparsed_rows": sum(
            int((record.get("table_diagnostics") or {}).get("possible_unparsed_rows") or 0) > 0
            for record in completed
        ),
        "documents_with_empty_table_sections": sum(
            int((record.get("table_diagnostics") or {}).get("sections_without_rows") or 0) > 0
            for record in completed
        ),
        "documents_with_paired_adjustments": sum(
            int((record.get("table_diagnostics") or {}).get("paired_adjustment_rows") or 0) > 0
            for record in completed
        ),
        "paired_adjustment_rows": sum(
            int((record.get("table_diagnostics") or {}).get("paired_adjustment_rows") or 0)
            for record in completed
        ),
        "documents_with_unpaired_adjustments": sum(
            int((record.get("table_diagnostics") or {}).get("unpaired_adjustment_rows") or 0) > 0
            for record in completed
        ),
        "warning_categories": dict(sorted(warning_categories.items())),
        "failures_by_type": _counter(failed, "failure_type"),
        "failures_by_extension": _counter(failed, "extension"),
        "total_processing_seconds": round(sum(float(record.get("seconds") or 0) for record in results), 3),
    }


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _receipt(
    *,
    selection: str,
    manifest_sha256: str,
    extractor_sha256: str,
    results: Sequence[Mapping[str, Any]],
    started_at: str,
    elapsed: float,
    workers: int,
) -> dict[str, Any]:
    normalized_results: list[dict[str, Any]] = []
    for record in results:
        normalized = dict(record)
        normalized["strict_core_gate_reasons"] = _core_gate_reasons(normalized)
        normalized["strict_source_target_gate_reasons"] = _source_target_gate_reasons(normalized)
        normalized_results.append(normalized)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started_at,
        "elapsed_wall_seconds": round(elapsed, 3),
        "selection": selection,
        "workers": workers,
        "network_requirement": "none",
        "privacy": {
            "contains_filenames_or_paths": False,
            "contains_raw_text": False,
            "contains_extracted_field_values": False,
        },
        "manifest_sha256": manifest_sha256,
        "extractor_sha256": extractor_sha256,
        "summary": _summarize(normalized_results),
        "limitations": [
            "Candidate-row counts are parser outputs, not reviewed ground truth or an accuracy score.",
            "Arithmetic equality can legitimately fail when source discounts, free goods, tax or rounding are represented elsewhere.",
            "The strict review gates reject recognized empty sections and partial numeric rows, but cannot prove that PDF/OCR omitted no source line.",
            "Document classification is lexical workflow routing evidence and remains reviewable.",
            "Adjacent discount pairing requires explicit non-positive discount text, equal quantity and tax rate, and net/ex-tax amounts; every consumed source row remains in line provenance.",
        ],
        "documents": sorted(normalized_results, key=lambda record: str(record["document_id"])),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--status-csv", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--selection",
        choices=("all", "embedded", "ocr", "sample"),
        default="all",
    )
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--sample-size", type=int, default=24)
    parser.add_argument("--sample-per-stratum", type=int, default=2)
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    input_root = args.input_root.resolve()
    if not input_root.is_dir():
        raise SystemExit("Input root does not exist or is not a directory.")
    status_csv = args.status_csv.resolve() if args.status_csv else None
    if status_csv and not status_csv.is_file():
        raise SystemExit("Status CSV does not exist or is not a file.")
    if args.sample_size < 1 or args.sample_per_stratum < 1 or args.progress_every < 1:
        raise SystemExit("Sample and progress values must be positive integers.")

    all_records = _load_records(input_root, status_csv)
    selected = _select_records(
        all_records,
        args.selection,
        args.sample_size,
        args.sample_per_stratum,
    )
    manifest_sha256 = hashlib.sha256(
        "\n".join(record["document_id"] for record in selected).encode("ascii")
    ).hexdigest()
    extractor_sha256 = _sha256_file(PROJECT_ROOT / "backend" / "extraction.py")
    completed_by_id: dict[str, Mapping[str, Any]] = {}
    if args.resume and args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        if (
            previous.get("schema_version") != SCHEMA_VERSION
            or previous.get("manifest_sha256") != manifest_sha256
            or previous.get("extractor_sha256") != extractor_sha256
        ):
            raise SystemExit("Resume receipt does not match this manifest and extractor version.")
        completed_by_id = {
            str(record["document_id"]): record
            for record in previous.get("documents", [])
        }

    pending = [record for record in selected if record["document_id"] not in completed_by_id]
    started = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    print(
        json.dumps(
            {
                "selected": len(selected),
                "already_completed": len(selected) - len(pending),
                "pending": len(pending),
                "workers": args.workers,
                "selection": args.selection,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    def save() -> None:
        results = list(completed_by_id.values())
        payload = _receipt(
            selection=args.selection,
            manifest_sha256=manifest_sha256,
            extractor_sha256=extractor_sha256,
            results=results,
            started_at=started_at,
            elapsed=time.monotonic() - started,
            workers=args.workers,
        )
        _atomic_write(args.output, payload)

    if pending:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_evaluate_one, record): record["document_id"] for record in pending}
            processed = 0
            for future in as_completed(futures):
                document_id = futures[future]
                try:
                    result = future.result()
                except BaseException as exc:  # preserve a receipt even if a worker exits unexpectedly
                    source = next(record for record in pending if record["document_id"] == document_id)
                    result = {
                        "document_id": document_id,
                        "content_sha256": source["content_sha256"],
                        "extension": source["extension"],
                        "source_bytes": source["source_bytes"],
                        "audit_classification": source["audit_classification"],
                        "audit_needs_ocr": source["audit_needs_ocr"],
                        "audit_heuristic_lines": source.get("audit_heuristic_lines", 0),
                        "status": "failed",
                        "failure_type": type(exc).__name__,
                        "seconds": 0.0,
                    }
                completed_by_id[document_id] = result
                processed += 1
                save()
                if processed % args.progress_every == 0 or processed == len(pending):
                    current = _summarize(list(completed_by_id.values()))
                    print(
                        json.dumps(
                            {
                                "processed_this_run": processed,
                                "remaining": len(pending) - processed,
                                "completed": current["completed"],
                                "failed": current["failed"],
                                "documents_with_candidate_rows": current[
                                    "documents_with_candidate_rows"
                                ],
                                "strict_core_reconciled_review_gate_documents": current[
                                    "strict_core_reconciled_review_gate_documents"
                                ],
                                "elapsed_wall_seconds": round(time.monotonic() - started, 1),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
    else:
        save()

    summary = _summarize(list(completed_by_id.values()))
    print(json.dumps({"output": str(args.output), "summary": summary}, sort_keys=True), flush=True)
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
