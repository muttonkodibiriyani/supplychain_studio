#!/usr/bin/env python3
"""Black-box volume and native-OCR verifier for Invoice Studio.

The verifier talks only to the HTTP API.  It creates deterministic, distinct
text-layer PDFs for the volume run and runtime-random raster invoices for the
OCR run.  OCR tokens exist only as pixels (never in filenames or file bytes),
so finding them in invoice detail is evidence that raster extraction ran.

Use a fresh service data directory.  Pass --restart-command to make the script
restart the service/container and prove that IDs and OCR evidence persist.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import os
import platform
import re
import secrets
import shlex
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urljoin

try:
    import requests
except ImportError as exc:  # pragma: no cover - exercised only on a broken host
    raise SystemExit("verify_volume.py requires requests") from exc

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - exercised only on a broken host
    raise SystemExit("verify_volume.py requires Pillow") from exc


PASS_STATUSES = {"needs_review", "ready", "exported"}
ACTIVE_STATUSES = {"queued", "processing"}
TERMINAL_STATUSES = PASS_STATUSES | {"failed"}
HTTP_ACCEPTED = {200, 201, 202}
HTTP_BACKPRESSURE = {429, 503}
HTTP_INVALID = {400, 409, 413, 415, 422}
VERSION = 2


class VerificationError(RuntimeError):
    """An acceptance invariant was not satisfied."""


@dataclass(frozen=True)
class Fixture:
    filename: str
    media_type: str
    data: bytes
    kind: str
    expected_token: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def compact(value: Any, limit: int = 2_000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = repr(value)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def normalize_token(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_text_pdf(index: int) -> Fixture:
    """Return a tiny valid one-page PDF with a unique embedded text invoice."""
    invoice_number = f"VOL-{index:06d}"
    supplier = f"Synthetic Supplier {index % 37:02d}"
    subtotal = 100 + (index % 997) / 10
    tax = round(subtotal * 0.05, 2)
    total = subtotal + tax
    lines = [
        "INVOICE",
        f"Supplier: {supplier}",
        f"Invoice Number: {invoice_number}",
        "Invoice Date: 2026-09-24",
        f"PO Number: PO-{index:06d}",
        "Currency: AED",
        "Description: Salon shampoo 500 ml",
        "Quantity: 2",
        f"Subtotal: {subtotal:.2f}",
        f"Tax: {tax:.2f}",
        f"Total: {total:.2f}",
    ]
    commands = ["BT", "/F1 13 Tf", "72 760 Td"]
    for line_number, line in enumerate(lines):
        if line_number:
            commands.append("0 -24 Td")
        commands.append(f"({pdf_escape(line)}) Tj")
    commands.append("ET")
    stream = ("\n".join(commands) + "\n").encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
    ]
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{object_number} 0 obj\n".encode("ascii"))
        result.extend(body)
        result.extend(b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return Fixture(
        filename=f"volume-invoice-{index:06d}.pdf",
        media_type="application/pdf",
        data=bytes(result),
        kind="text_pdf",
        expected_token=invoice_number,
    )


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _raster_invoice(token: str, supplier: str, total: str) -> Image.Image:
    image = Image.new("RGB", (1654, 2339), "white")
    draw = ImageDraw.Draw(image)
    title = _font(64)
    body = _font(38)
    small = _font(32)
    draw.rectangle((80, 70, 1574, 2200), outline="black", width=4)
    draw.text((130, 120), "INVOICE", fill="black", font=title)
    rows = [
        f"Supplier: {supplier}",
        f"Invoice Number: {token}",
        "Invoice Date: 24 September 2026",
        "PO Number: PO-OCR-4096",
        "Currency: AED",
    ]
    y = 310
    for row in rows:
        draw.text((130, y), row, fill="black", font=body)
        y += 72
    draw.line((130, y + 20, 1520, y + 20), fill="black", width=3)
    y += 80
    draw.text((130, y), "Description", fill="black", font=small)
    draw.text((980, y), "Qty", fill="black", font=small)
    draw.text((1220, y), "Amount", fill="black", font=small)
    y += 70
    draw.text((130, y), "Professional shampoo 500 ml", fill="black", font=small)
    draw.text((1000, y), "2", fill="black", font=small)
    draw.text((1220, y), "120.00", fill="black", font=small)
    y += 180
    draw.text((980, y), "Subtotal:", fill="black", font=body)
    draw.text((1330, y), "120.00", fill="black", font=body)
    y += 72
    draw.text((980, y), "Tax:", fill="black", font=body)
    draw.text((1365, y), "24.00", fill="black", font=body)
    y += 72
    draw.text((980, y), "Total:", fill="black", font=body)
    draw.text((1330, y), total, fill="black", font=body)
    return image


def make_ocr_fixtures() -> list[Fixture]:
    png_token = f"OCRPNG{secrets.randbelow(90_000_000) + 10_000_000}"
    scan_token = f"OCRSCAN{secrets.randbelow(90_000_000) + 10_000_000}"

    png_image = _raster_invoice(png_token, "Native Raster Supply Company", "144.00")
    png_output = io.BytesIO()
    png_image.save(png_output, format="PNG", compress_level=6)
    png_data = png_output.getvalue()

    scan_image = _raster_invoice(scan_token, "Scanned Paper Goods Company", "144.00")
    pdf_output = io.BytesIO()
    scan_image.save(pdf_output, format="PDF", resolution=150.0)
    scan_data = pdf_output.getvalue()

    for token, data, label in (
        (png_token, png_data, "PNG"),
        (scan_token, scan_data, "scanned PDF"),
    ):
        if token.encode("ascii") in data:
            raise VerificationError(f"{label} OCR token leaked into file bytes")

    return [
        Fixture("native-raster-invoice.png", "image/png", png_data, "raster_png", png_token),
        Fixture("scanned-raster-invoice.pdf", "application/pdf", scan_data, "scanned_pdf", scan_token),
    ]


def make_recovery_fixtures(count: int) -> list[Fixture]:
    """Create slow, pixel-only PDFs used to interrupt active OCR workers."""
    fixtures: list[Fixture] = []
    for index in range(count):
        token = f"OCRREC{secrets.randbelow(90_000_000) + 10_000_000}"
        image = _raster_invoice(token, f"Recovery Raster Supplier {index + 1}", "144.00")
        output = io.BytesIO()
        image.save(output, format="PDF", resolution=150.0)
        data = output.getvalue()
        if token.encode("ascii") in data:
            raise VerificationError("recovery OCR token leaked into PDF bytes")
        fixtures.append(
            Fixture(
                filename=f"crash-recovery-{index + 1:03d}.pdf",
                media_type="application/pdf",
                data=data,
                kind="crash_recovery_scanned_pdf",
                expected_token=token,
            )
        )
    return fixtures


def response_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw_text": response.text[:2_000]}


def invoice_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("invoices", "items", "results", "records", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("invoice", "item", "record"):
        value = payload.get(key)
        if isinstance(value, dict):
            return [value]
    if any(key in payload for key in ("id", "invoice_id", "filename", "status")):
        return [payload]
    return []


def upload_groups(payload: Any) -> dict[str, list[dict[str, Any]]] | None:
    """Normalize the upload endpoint's accepted/duplicates/rejected envelope."""
    if not isinstance(payload, dict):
        return None
    if not any(key in payload for key in ("accepted", "duplicates", "rejected")):
        return None
    return {
        key: [item for item in payload.get(key, []) if isinstance(item, dict)]
        if isinstance(payload.get(key, []), list)
        else []
        for key in ("accepted", "duplicates", "rejected")
    }


def field(record: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in record:
            return record[name]
    source = record.get("source")
    if isinstance(source, dict):
        for name in names:
            if name in source:
                return source[name]
    return None


def invoice_id(record: Mapping[str, Any]) -> str | None:
    value = field(record, "id", "invoice_id", "invoiceId")
    return str(value) if value is not None else None


def invoice_filename(record: Mapping[str, Any]) -> str | None:
    value = field(record, "filename", "source_filename", "original_filename", "name")
    return str(value) if value is not None else None


def invoice_status(record: Mapping[str, Any]) -> str:
    value = field(record, "status", "state")
    return str(value).lower() if value is not None else "unknown"


def recursive_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from recursive_strings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from recursive_strings(child)


def recursive_numbers(value: Any, prefix: str = "") -> Iterable[tuple[str, float]]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield prefix.lower(), float(value)
    elif isinstance(value, Mapping):
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from recursive_numbers(child, next_prefix)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            yield from recursive_numbers(child, f"{prefix}.{index}")


class Api:
    def __init__(self, base_url: str, upload_field: str, timeout: float):
        self.base_url = base_url.rstrip("/") + "/"
        self.upload_field = upload_field
        self.timeout = timeout

    def url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        return requests.get(self.url(path), params=params, timeout=(5, self.timeout))

    def upload(self, fixtures: Sequence[Fixture]) -> requests.Response:
        files = [
            (self.upload_field, (fixture.filename, fixture.data, fixture.media_type))
            for fixture in fixtures
        ]
        return requests.post(
            self.url("/api/invoices/upload"), files=files, timeout=(5, self.timeout)
        )

    def health(self) -> Any:
        response = self.get("/api/health")
        if response.status_code != 200:
            raise VerificationError(
                f"health returned HTTP {response.status_code}: {response.text[:1000]}"
            )
        return response_json(response)

    def stats(self) -> Any:
        response = self.get("/api/stats")
        if response.status_code != 200:
            raise VerificationError(
                f"stats returned HTTP {response.status_code}: {response.text[:1000]}"
            )
        return response_json(response)

    def list_all(self, page_size: int = 200) -> tuple[list[dict[str, Any]], Any]:
        offset = 0
        records: list[dict[str, Any]] = []
        last_payload: Any = None
        seen: set[str] = set()
        for _ in range(100_000):
            response = self.get(
                "/api/invoices", params={"limit": page_size, "offset": offset}
            )
            if response.status_code != 200:
                raise VerificationError(
                    f"invoice list returned HTTP {response.status_code}: {response.text[:1000]}"
                )
            last_payload = response_json(response)
            page = invoice_items(last_payload)
            if not page:
                break
            added = 0
            for record in page:
                key = invoice_id(record) or f"row:{offset + added}:{compact(record, 200)}"
                if key not in seen:
                    records.append(record)
                    seen.add(key)
                    added += 1
            offset += len(page)
            total = None
            if isinstance(last_payload, dict):
                for key in ("total", "total_count", "count"):
                    candidate = last_payload.get(key)
                    if isinstance(candidate, int):
                        total = candidate
                        break
            if total is not None and offset >= total:
                break
            if len(page) < page_size:
                break
            if added == 0:
                raise VerificationError("pagination repeated a page; offset was not honored")
        else:  # pragma: no cover - defensive stop
            raise VerificationError("pagination exceeded safety limit")
        return records, last_payload

    def detail(self, identifier: str) -> Any:
        response = self.get(f"/api/invoices/{identifier}")
        if response.status_code != 200:
            raise VerificationError(
                f"invoice {identifier} returned HTTP {response.status_code}: {response.text[:1000]}"
            )
        return response_json(response)

    def audit(self, identifier: str) -> Any:
        response = self.get(f"/api/invoices/{identifier}/audit")
        if response.status_code != 200:
            raise VerificationError(
                f"invoice {identifier} audit returned HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )
        return response_json(response)


class QueueSampler:
    def __init__(self, api: Api, interval: float = 0.2):
        self.api = api
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="queue-sampler", daemon=True)
        self.samples = 0
        self.max_queued: float | None = None
        self.max_processing: float | None = None
        self.capacities: set[float] = set()
        self.errors: list[str] = []

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(2.0, self.interval * 4))

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                payloads = (self.api.health(), self.api.stats())
                self.samples += 1
                for payload in payloads:
                    for path, number in recursive_numbers(payload):
                        leaf = path.rsplit(".", 1)[-1]
                        if leaf in {"queue_depth", "queued", "pending"}:
                            self.max_queued = (
                                number if self.max_queued is None else max(self.max_queued, number)
                            )
                        elif leaf in {"processing", "active", "active_jobs"}:
                            self.max_processing = (
                                number
                                if self.max_processing is None
                                else max(self.max_processing, number)
                            )
                        elif leaf in {
                            "queue_capacity",
                            "max_queue_size",
                            "queue_maxsize",
                            "capacity",
                        }:
                            self.capacities.add(number)
            except Exception as exc:  # sampling must never interrupt the test
                if len(self.errors) < 5:
                    self.errors.append(f"{type(exc).__name__}: {exc}")

    def result(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "max_queued_observed": self.max_queued,
            "max_processing_observed": self.max_processing,
            "reported_capacities": sorted(self.capacities),
            "sample_errors": self.errors,
        }


def wait_for_health(api: Api, timeout: float) -> tuple[Any, float]:
    started = time.monotonic()
    last_error = "not attempted"
    while time.monotonic() - started < timeout:
        try:
            return api.health(), time.monotonic() - started
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5)
    raise VerificationError(f"service did not become healthy in {timeout:.1f}s: {last_error}")


def records_by_filename(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        name = invoice_filename(record)
        if name:
            result[name] = record
    return result


def wait_for_filenames(
    api: Api,
    filenames: set[str],
    timeout: float,
    *,
    require_terminal: bool,
) -> tuple[dict[str, dict[str, Any]], float]:
    started = time.monotonic()
    latest: dict[str, dict[str, Any]] = {}
    while time.monotonic() - started < timeout:
        records, _ = api.list_all()
        mapping = records_by_filename(records)
        latest = {name: mapping[name] for name in filenames if name in mapping}
        if len(latest) == len(filenames):
            statuses = {invoice_status(record) for record in latest.values()}
            if not require_terminal or not (statuses & ACTIVE_STATUSES):
                return latest, time.monotonic() - started
        time.sleep(0.5)
    missing = sorted(filenames - latest.keys())[:10]
    active = Counter(invoice_status(record) for record in latest.values())
    raise VerificationError(
        f"timed out after {timeout:.1f}s waiting for {len(filenames)} files; "
        f"seen={len(latest)}, missing_sample={missing}, statuses={dict(active)}"
    )


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def upload_volume(
    api: Api,
    fixtures: list[Fixture],
    batch_size: int,
    concurrency: int,
    retries: int,
) -> dict[str, Any]:
    batches = [fixtures[index : index + batch_size] for index in range(0, len(fixtures), batch_size)]
    lock = threading.Lock()
    active = 0
    max_active = 0
    backpressure = 0
    attempts = 0
    response_codes: Counter[int] = Counter()
    failures: list[dict[str, Any]] = []

    def send(batch_number: int, batch: list[Fixture]) -> dict[str, Any]:
        nonlocal active, max_active, backpressure, attempts
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            for attempt in range(retries + 1):
                with lock:
                    attempts += 1
                response = api.upload(batch)
                with lock:
                    response_codes[response.status_code] += 1
                if response.status_code in HTTP_BACKPRESSURE and attempt < retries:
                    with lock:
                        backpressure += 1
                    time.sleep(min(2.0, 0.05 * (2**attempt)))
                    continue
                payload = response_json(response)
                if response.status_code not in HTTP_ACCEPTED:
                    failure = {
                        "batch": batch_number,
                        "filenames": [item.filename for item in batch],
                        "status_code": response.status_code,
                        "response": compact(payload),
                    }
                    with lock:
                        failures.append(failure)
                    return failure
                groups = upload_groups(payload)
                if groups is not None and (
                    len(groups["accepted"]) != len(batch)
                    or groups["duplicates"]
                    or groups["rejected"]
                ):
                    failure = {
                        "batch": batch_number,
                        "filenames": [item.filename for item in batch],
                        "status_code": response.status_code,
                        "accepted": len(groups["accepted"]),
                        "duplicates": groups["duplicates"],
                        "rejected": groups["rejected"],
                        "response": compact(payload),
                    }
                    with lock:
                        failures.append(failure)
                    return failure
                return {"batch": batch_number, "status_code": response.status_code}
            raise AssertionError("unreachable")
        finally:
            with lock:
                active -= 1

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(send, number, batch) for number, batch in enumerate(batches)]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    elapsed = time.monotonic() - started
    ensure(not failures, f"{len(failures)} upload batches failed: {compact(failures[:3])}")
    ensure(max_active <= concurrency, f"client concurrency exceeded bound: {max_active}>{concurrency}")
    return {
        "documents": len(fixtures),
        "bytes": sum(len(item.data) for item in fixtures),
        "batches": len(batches),
        "batch_size": batch_size,
        "configured_concurrency": concurrency,
        "max_client_requests_observed": max_active,
        "http_attempts": attempts,
        "http_status_counts": {str(code): count for code, count in sorted(response_codes.items())},
        "backpressure_retries": backpressure,
        "elapsed_seconds": round(elapsed, 3),
        "documents_per_second": round(len(fixtures) / elapsed, 3) if elapsed else None,
    }


def upload_one(api: Api, fixture: Fixture) -> tuple[requests.Response, Any]:
    response = api.upload([fixture])
    return response, response_json(response)


def find_returned_ids(payload: Any) -> set[str]:
    records = invoice_items(payload)
    groups = upload_groups(payload)
    if groups is not None:
        records = [*groups["accepted"], *groups["duplicates"]]
    return {identifier for item in records if (identifier := invoice_id(item))}


def check_duplicates(
    api: Api, fixture: Fixture, original_record: dict[str, Any]
) -> dict[str, Any]:
    original_id = invoice_id(original_record)
    ensure(original_id is not None, "original volume invoice has no id")
    before, _ = api.list_all()
    evidence: list[dict[str, Any]] = []
    variants = [
        fixture,
        Fixture(
            filename="same-bytes-different-name.pdf",
            media_type=fixture.media_type,
            data=fixture.data,
            kind="duplicate_alias",
        ),
    ]
    for variant in variants:
        response, payload = upload_one(api, variant)
        ensure(
            response.status_code in HTTP_ACCEPTED | {409},
            f"duplicate upload returned HTTP {response.status_code}: {compact(payload)}",
        )
        returned_ids = find_returned_ids(payload)
        groups = upload_groups(payload)
        explicit = (
            response.status_code == 409
            or "duplicate" in compact(payload).lower()
            or original_id in returned_ids
            or (groups is not None and bool(groups["duplicates"]))
        )
        ensure(explicit, f"duplicate handling was not explicit: {compact(payload)}")
        after, _ = api.list_all()
        ensure(
            len(after) == len(before),
            f"duplicate {variant.filename} changed invoice count {len(before)}->{len(after)}",
        )
        evidence.append(
            {
                "filename": variant.filename,
                "http_status": response.status_code,
                "returned_ids": sorted(returned_ids),
                "response": compact(payload, 800),
                "count_after": len(after),
            }
        )
    return {"original_id": original_id, "attempts": evidence, "count_unchanged": len(before)}


def error_text(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("error", "detail", "message", "reason"):
            value = payload.get(key)
            if value:
                return compact(value, 800)
    return compact(payload, 800)


def check_invalid(api: Api, timeout: float) -> dict[str, Any]:
    invalid = [
        Fixture("empty-invoice.pdf", "application/pdf", b"", "invalid_empty"),
        Fixture(
            "corrupt-invoice.pdf",
            "application/pdf",
            b"%PDF-1.7\nthis is deliberately corrupt and has no objects\n%%EOF\n",
            "invalid_corrupt",
        ),
        Fixture(
            "unsupported-invoice.exe",
            "application/octet-stream",
            b"MZ\x00deliberately unsupported invoice payload",
            "invalid_unsupported",
        ),
    ]
    before, _ = api.list_all()
    current_count = len(before)
    outcomes: list[dict[str, Any]] = []
    for fixture in invalid:
        response, payload = upload_one(api, fixture)
        groups = upload_groups(payload)
        outcome: dict[str, Any] = {
            "filename": fixture.filename,
            "http_status": response.status_code,
            "response": error_text(payload),
        }
        envelope_rejection = groups is not None and bool(groups["rejected"])
        if response.status_code in HTTP_INVALID or envelope_rejection:
            ensure(bool(error_text(payload).strip()), f"{fixture.filename} rejection had no reason")
            after, _ = api.list_all()
            ensure(
                len(after) == current_count,
                f"rejected invalid file changed count {current_count}->{len(after)}",
            )
            outcome["handling"] = (
                "synchronous_envelope_rejection"
                if envelope_rejection
                else "synchronous_http_rejection"
            )
        elif response.status_code in HTTP_ACCEPTED:
            found, wait = wait_for_filenames(
                api, {fixture.filename}, timeout, require_terminal=True
            )
            record = found[fixture.filename]
            identifier = invoice_id(record)
            detail = api.detail(identifier) if identifier else record
            status = invoice_status(record)
            detail_text = compact(detail).lower()
            ensure(status == "failed", f"accepted invalid {fixture.filename} ended in {status}")
            ensure(
                any(word in detail_text for word in ("error", "invalid", "unsupported", "empty", "failed", "corrupt")),
                f"accepted invalid {fixture.filename} has no actionable failure reason: {compact(detail)}",
            )
            after, _ = api.list_all()
            ensure(
                len(after) == current_count + 1,
                f"durable invalid record count mismatch {current_count}->{len(after)}",
            )
            current_count = len(after)
            outcome.update(
                {
                    "handling": "durable_failed_record",
                    "invoice_id": identifier,
                    "terminal_status": status,
                    "wait_seconds": round(wait, 3),
                    "detail": compact(detail, 1_200),
                }
            )
        else:
            raise VerificationError(
                f"invalid file {fixture.filename} caused HTTP {response.status_code}: {compact(payload)}"
            )
        outcomes.append(outcome)
    return {
        "count_before": len(before),
        "count_after": current_count,
        "durable_failed_records": current_count - len(before),
        "outcomes": outcomes,
    }


def check_ocr(api: Api, fixtures: list[Fixture], timeout: float) -> dict[str, Any]:
    response = api.upload(fixtures)
    payload = response_json(response)
    ensure(
        response.status_code in HTTP_ACCEPTED,
        f"OCR upload returned HTTP {response.status_code}: {compact(payload)}",
    )
    groups = upload_groups(payload)
    if groups is not None:
        ensure(
            len(groups["accepted"]) == len(fixtures)
            and not groups["duplicates"]
            and not groups["rejected"],
            f"OCR upload envelope did not accept both new fixtures: {compact(payload)}",
        )
    names = {fixture.filename for fixture in fixtures}
    records, wait = wait_for_filenames(api, names, timeout, require_terminal=True)
    evidence: list[dict[str, Any]] = []
    for fixture in fixtures:
        record = records[fixture.filename]
        identifier = invoice_id(record)
        ensure(identifier is not None, f"OCR record {fixture.filename} has no id")
        detail = api.detail(identifier)
        status = invoice_status(record)
        ensure(status in PASS_STATUSES, f"OCR record {fixture.filename} ended in {status}")
        haystack = normalize_token("\n".join(recursive_strings(detail)))
        needle = normalize_token(fixture.expected_token)
        ensure(
            needle in haystack,
            f"pixel-only token {fixture.expected_token} absent from {fixture.filename} detail: {compact(detail)}",
        )
        method_values: list[str] = []
        if isinstance(detail, Mapping):
            for key in ("extraction_method", "extractionMethod", "method"):
                value = detail.get(key)
                if isinstance(value, str):
                    method_values.append(value)
            invoice_value = detail.get("invoice")
            if isinstance(invoice_value, Mapping):
                for key in ("extraction_method", "extractionMethod", "method"):
                    value = invoice_value.get(key)
                    if isinstance(value, str):
                        method_values.append(value)
        evidence.append(
            {
                "kind": fixture.kind,
                "filename": fixture.filename,
                "invoice_id": identifier,
                "sha256": fixture.sha256,
                "bytes": len(fixture.data),
                "token": fixture.expected_token,
                "token_absent_from_file_bytes": fixture.expected_token.encode("ascii")
                not in fixture.data,
                "token_found_in_api_detail": True,
                "status": status,
                "reported_extraction_methods": method_values,
            }
        )
    return {
        "upload_http_status": response.status_code,
        "terminal_wait_seconds": round(wait, 3),
        "files": evidence,
    }


def run_command(command: str, timeout: float, label: str) -> dict[str, Any]:
    argv = shlex.split(command)
    ensure(bool(argv), f"{label} command parsed to no arguments")
    started = time.monotonic()
    completed = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    ensure(
        completed.returncode == 0,
        f"{label} command exited {completed.returncode}: "
        f"stdout={completed.stdout[-1000:]!r} stderr={completed.stderr[-1000:]!r}",
    )
    return {
        "argv": argv,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout": completed.stdout[-1_000:],
        "stderr": completed.stderr[-1_000:],
    }


def check_crash_recovery(
    api: Api,
    fixtures: list[Fixture],
    stop_command: str,
    start_command: str,
    timeout: float,
    health_timeout: float,
) -> dict[str, Any]:
    """Kill the service during native OCR and prove durable job recovery."""
    response = api.upload(fixtures)
    payload = response_json(response)
    ensure(
        response.status_code in HTTP_ACCEPTED,
        f"crash-recovery upload returned HTTP {response.status_code}: {compact(payload)}",
    )
    groups = upload_groups(payload)
    if groups is not None:
        ensure(
            len(groups["accepted"]) == len(fixtures)
            and not groups["duplicates"]
            and not groups["rejected"],
            f"crash-recovery fixtures were not all accepted: {compact(payload)}",
        )

    names = {fixture.filename for fixture in fixtures}
    observed_records: dict[str, dict[str, Any]] = {}
    stats_before: Any = None
    observation_started = time.monotonic()
    while time.monotonic() - observation_started < min(timeout, 30.0):
        records, _ = api.list_all()
        mapping = records_by_filename(records)
        observed_records = {name: mapping[name] for name in names if name in mapping}
        stats_before = api.stats()
        statuses = Counter(invoice_status(record) for record in observed_records.values())
        if len(observed_records) == len(fixtures) and statuses["processing"] > 0:
            break
        time.sleep(0.05)
    statuses_before = Counter(invoice_status(record) for record in observed_records.values())
    ensure(
        len(observed_records) == len(fixtures),
        f"only {len(observed_records)}/{len(fixtures)} recovery fixtures appeared before crash",
    )
    ensure(
        statuses_before["processing"] > 0,
        f"could not catch an active processing job before crash: {dict(statuses_before)}",
    )
    processing_before = {
        identifier
        for record in observed_records.values()
        if invoice_status(record) == "processing"
        if (identifier := invoice_id(record)) is not None
    }

    stop_result = run_command(stop_command, health_timeout, "crash-stop")
    start_result = run_command(start_command, health_timeout, "crash-start")
    health, health_wait = wait_for_health(api, health_timeout)
    settled, settle_wait = wait_for_filenames(api, names, timeout, require_terminal=True)
    statuses_after = Counter(invoice_status(record) for record in settled.values())
    ensure(
        all(invoice_status(record) in PASS_STATUSES for record in settled.values()),
        f"recovered jobs did not all succeed: {dict(statuses_after)}",
    )

    recovery_audits: list[dict[str, Any]] = []
    for identifier in sorted(processing_before):
        audit = api.audit(identifier)
        event_types = [
            str(item.get("event_type"))
            for item in invoice_items(audit)
            if isinstance(item, dict)
        ]
        ensure(
            "processing_recovered" in event_types,
            f"processing job {identifier} has no processing_recovered audit: {compact(audit)}",
        )
        recovery_audits.append(
            {"invoice_id": identifier, "processing_recovered_event": True}
        )

    file_evidence: list[dict[str, Any]] = []
    for fixture in fixtures:
        record = settled[fixture.filename]
        identifier = invoice_id(record)
        ensure(identifier is not None, f"recovered fixture {fixture.filename} has no id")
        detail = api.detail(identifier)
        ensure(
            normalize_token(fixture.expected_token)
            in normalize_token("\n".join(recursive_strings(detail))),
            f"recovered OCR token missing for {fixture.filename}",
        )
        file_evidence.append(
            {
                "filename": fixture.filename,
                "invoice_id": identifier,
                "sha256": fixture.sha256,
                "token": fixture.expected_token,
                "token_absent_from_file_bytes": fixture.expected_token.encode("ascii")
                not in fixture.data,
                "token_found_after_recovery": True,
                "status": invoice_status(record),
            }
        )
    return {
        "tested": True,
        "fixtures": len(fixtures),
        "statuses_immediately_before_crash": dict(sorted(statuses_before.items())),
        "processing_ids_before_crash": sorted(processing_before),
        "stats_immediately_before_crash": stats_before,
        "stop": stop_result,
        "start": start_result,
        "health_wait_seconds": round(health_wait, 3),
        "terminal_wait_seconds": round(settle_wait, 3),
        "statuses_after_recovery": dict(sorted(statuses_after.items())),
        "recovery_audits": recovery_audits,
        "files": file_evidence,
        "health_after": health,
    }


def run_restart_check(
    api: Api,
    command: str,
    health_timeout: float,
    expected_ids: set[str],
    source_expectations: dict[str, Fixture],
) -> dict[str, Any]:
    ensure(bool(command.strip()), "restart command is empty")
    started = time.monotonic()
    command_result = run_command(command, health_timeout, "restart")
    health, health_wait = wait_for_health(api, health_timeout)
    records, _ = api.list_all()
    after_ids = {identifier for item in records if (identifier := invoice_id(item))}
    missing = sorted(expected_ids - after_ids)
    ensure(not missing, f"restart lost {len(missing)} invoice IDs; sample={missing[:10]}")
    sources_after: list[dict[str, Any]] = []
    mapping = records_by_filename(records)
    for filename, fixture in source_expectations.items():
        ensure(filename in mapping, f"restart lost OCR fixture {filename}")
        identifier = invoice_id(mapping[filename])
        ensure(identifier is not None, f"restart OCR fixture {filename} has no id")
        detail = api.detail(identifier)
        ensure(
            normalize_token(fixture.expected_token)
            in normalize_token("\n".join(recursive_strings(detail))),
            f"restart lost OCR evidence for {filename}",
        )
        source_response = api.get(f"/api/invoices/{identifier}/source")
        ensure(
            source_response.status_code == 200,
            f"restart source download for {filename} returned HTTP {source_response.status_code}",
        )
        downloaded_sha256 = hashlib.sha256(source_response.content).hexdigest()
        ensure(
            downloaded_sha256 == fixture.sha256,
            f"restart source digest mismatch for {filename}: "
            f"{downloaded_sha256}!={fixture.sha256}",
        )
        sources_after.append(
            {
                "filename": filename,
                "invoice_id": identifier,
                "token_retained": True,
                "source_sha256_retained": True,
                "sha256": downloaded_sha256,
                "bytes": len(source_response.content),
            }
        )
    return {
        "tested": True,
        "command_argv": command_result["argv"],
        "command_stdout": command_result["stdout"],
        "command_stderr": command_result["stderr"],
        "health_wait_seconds": round(health_wait, 3),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "expected_ids": len(expected_ids),
        "retained_ids": len(expected_ids & after_ids),
        "record_count_after": len(records),
        "source_and_ocr_evidence": sources_after,
        "health_after": health,
    }


def machine_info() -> dict[str, Any]:
    memory_kib = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                memory_kib = int(line.split()[1])
                break
    except (OSError, ValueError):
        pass
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "memory_total_kib": memory_kib,
        "requests": getattr(requests, "__version__", "unknown"),
        "pillow": getattr(Image, "__version__", "unknown"),
    }


def docker_runtime_info(container_name: str) -> dict[str, Any]:
    """Capture immutable image/container identity for a reproducible receipt."""
    inspected = subprocess.run(
        ["docker", "inspect", container_name],
        text=True,
        capture_output=True,
        timeout=30,
    )
    ensure(
        inspected.returncode == 0,
        f"could not inspect tested container {container_name}: {inspected.stderr[-1000:]}",
    )
    containers = json.loads(inspected.stdout)
    ensure(isinstance(containers, list) and containers, "docker inspect returned no container")
    container = containers[0]
    image_id = str(container.get("Image") or "")
    image_run = subprocess.run(
        ["docker", "image", "inspect", image_id],
        text=True,
        capture_output=True,
        timeout=30,
    )
    ensure(
        image_run.returncode == 0,
        f"could not inspect tested image {image_id}: {image_run.stderr[-1000:]}",
    )
    images = json.loads(image_run.stdout)
    image = images[0] if isinstance(images, list) and images else {}
    config = container.get("Config") or {}
    host_config = container.get("HostConfig") or {}
    state = container.get("State") or {}
    invoice_env = sorted(
        value
        for value in config.get("Env") or []
        if isinstance(value, str) and value.startswith("INVOICE_")
    )
    return {
        "container_name": str(container.get("Name") or "").lstrip("/"),
        "container_id": str(container.get("Id") or ""),
        "configured_image": config.get("Image"),
        "immutable_image_id": image_id,
        "image_created": image.get("Created"),
        "image_size_bytes": image.get("Size"),
        "platform": f"{image.get('Os', 'unknown')}/{image.get('Architecture', 'unknown')}",
        "container_started_at": state.get("StartedAt"),
        "container_user": config.get("User"),
        "read_only_rootfs": host_config.get("ReadonlyRootfs"),
        "invoice_environment": invoice_env,
        "mounts": [
            {
                "type": mount.get("Type"),
                "source": mount.get("Source"),
                "destination": mount.get("Destination"),
                "rw": mount.get("RW"),
            }
            for mount in container.get("Mounts") or []
        ],
    }


def write_receipt(path: str | None, receipt: dict[str, Any]) -> None:
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def fixture_self_test(args: argparse.Namespace, receipt: dict[str, Any]) -> None:
    started = time.monotonic()
    volume = [make_text_pdf(index) for index in range(args.count)]
    ocr = make_ocr_fixtures()
    hashes = {fixture.sha256 for fixture in volume}
    ensure(len(volume) == args.count, "volume fixture count mismatch")
    ensure(len(hashes) == args.count, "volume fixture bytes are not distinct")
    ensure(all(item.data.startswith(b"%PDF-1.4") for item in volume), "PDF header mismatch")
    ensure(all(item.data.endswith(b"%%EOF\n") for item in volume), "PDF EOF mismatch")
    receipt["checks"]["fixture_self_test"] = {
        "volume_documents": len(volume),
        "distinct_sha256": len(hashes),
        "volume_bytes": sum(len(item.data) for item in volume),
        "first_sha256": volume[0].sha256 if volume else None,
        "last_sha256": volume[-1].sha256 if volume else None,
        "ocr_files": [
            {
                "filename": item.filename,
                "kind": item.kind,
                "bytes": len(item.data),
                "sha256": item.sha256,
                "token_absent_from_bytes": item.expected_token.encode("ascii") not in item.data,
            }
            for item in ocr
        ],
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def run_http(args: argparse.Namespace, receipt: dict[str, Any]) -> None:
    api = Api(args.base_url, args.upload_field, args.request_timeout)
    health, health_wait = wait_for_health(api, args.health_timeout)
    before, initial_page = api.list_all(args.page_size)
    ensure(
        args.allow_existing or not before,
        f"refusing to run destructive volume verification against {len(before)} existing records; "
        "use a temporary data directory or --allow-existing",
    )
    baseline_ids = {identifier for item in before if (identifier := invoice_id(item))}
    receipt["checks"]["preflight"] = {
        "health_wait_seconds": round(health_wait, 3),
        "health": health,
        "initial_invoice_count": len(before),
        "initial_page_shape": type(initial_page).__name__,
    }

    build_started = time.monotonic()
    volume = [make_text_pdf(index) for index in range(args.count)]
    ensure(len({fixture.sha256 for fixture in volume}) == args.count, "volume PDFs are not distinct")
    receipt["checks"]["fixture_generation"] = {
        "documents": len(volume),
        "distinct_sha256": len({fixture.sha256 for fixture in volume}),
        "bytes": sum(len(fixture.data) for fixture in volume),
        "elapsed_seconds": round(time.monotonic() - build_started, 3),
    }

    sampler = QueueSampler(api, args.sample_interval)
    sampler.start()
    try:
        receipt["checks"]["volume_upload"] = upload_volume(
            api, volume, args.batch_size, args.concurrency, args.retries
        )
        expected_names = {fixture.filename for fixture in volume}
        settled, settle_wait = wait_for_filenames(
            api, expected_names, args.processing_timeout, require_terminal=True
        )
    finally:
        sampler.stop()
    queue_result = sampler.result()
    receipt["checks"]["queue_observation"] = queue_result
    if queue_result["reported_capacities"] and queue_result["max_queued_observed"] is not None:
        ensure(
            queue_result["max_queued_observed"] <= max(queue_result["reported_capacities"]),
            "observed queue depth exceeded reported capacity",
        )
    if args.expected_workers is not None:
        ensure(queue_result["samples"] > 0, "queue sampler captured no server samples")
        ensure(
            queue_result["max_processing_observed"] is not None,
            "stats did not expose processing count for worker-bound verification",
        )
        ensure(
            queue_result["max_processing_observed"] <= args.expected_workers,
            f"observed processing count {queue_result['max_processing_observed']} exceeded "
            f"configured worker bound {args.expected_workers}",
        )
        queue_result["expected_worker_bound"] = args.expected_workers
        queue_result["worker_bound_satisfied"] = True

    statuses = Counter(invoice_status(record) for record in settled.values())
    failed_names = sorted(
        name for name, record in settled.items() if invoice_status(record) not in PASS_STATUSES
    )
    ensure(
        not failed_names,
        f"{len(failed_names)} volume documents did not extract successfully; sample={failed_names[:10]}, "
        f"statuses={dict(statuses)}",
    )
    after_volume, _ = api.list_all(args.page_size)
    ensure(
        len(after_volume) == len(before) + args.count,
        f"volume count mismatch: baseline={len(before)}, expected={len(before)+args.count}, "
        f"actual={len(after_volume)}",
    )
    volume_ids = {
        identifier
        for record in settled.values()
        if (identifier := invoice_id(record)) is not None
    }
    ensure(len(volume_ids) == args.count, f"expected {args.count} distinct IDs, got {len(volume_ids)}")
    receipt["checks"]["volume_reconciliation"] = {
        "expected_filenames": args.count,
        "found_filenames": len(settled),
        "distinct_invoice_ids": len(volume_ids),
        "status_counts": dict(sorted(statuses.items())),
        "terminal_wait_seconds": round(settle_wait, 3),
        "api_count_after": len(after_volume),
    }

    if args.crash_stop_command and args.crash_start_command:
        recovery_fixtures = make_recovery_fixtures(args.recovery_count)
        receipt["checks"]["interrupted_job_recovery"] = check_crash_recovery(
            api,
            recovery_fixtures,
            args.crash_stop_command,
            args.crash_start_command,
            args.processing_timeout,
            args.health_timeout,
        )
    else:
        receipt["checks"]["interrupted_job_recovery"] = {
            "tested": False,
            "reason": "--crash-stop-command and --crash-start-command were not both supplied",
        }

    original = settled[volume[0].filename]
    receipt["checks"]["duplicate_idempotency"] = check_duplicates(api, volume[0], original)

    ocr_fixtures = make_ocr_fixtures()
    receipt["checks"]["native_ocr"] = check_ocr(api, ocr_fixtures, args.processing_timeout)

    receipt["checks"]["invalid_files"] = check_invalid(api, args.processing_timeout)

    final_records, _ = api.list_all(args.page_size)
    final_ids = {identifier for item in final_records if (identifier := invoice_id(item))}
    ensure(baseline_ids <= final_ids, "pre-existing invoice IDs disappeared during verification")
    stats = api.stats()
    receipt["checks"]["final_reconciliation"] = {
        "invoice_count": len(final_records),
        "distinct_ids": len(final_ids),
        "status_counts": dict(
            sorted(Counter(invoice_status(record) for record in final_records).items())
        ),
        "stats": stats,
    }

    if args.restart_command:
        receipt["checks"]["persistence_restart"] = run_restart_check(
            api,
            args.restart_command,
            args.health_timeout,
            final_ids,
            {fixture.filename: fixture for fixture in ocr_fixtures},
        )
    else:
        receipt["checks"]["persistence_restart"] = {
            "tested": False,
            "reason": "--restart-command was not supplied",
        }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--upload-field", default="files")
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--health-timeout", type=float, default=90.0)
    parser.add_argument("--processing-timeout", type=float, default=600.0)
    parser.add_argument("--sample-interval", type=float, default=0.2)
    parser.add_argument(
        "--expected-workers",
        type=int,
        help="Assert that GET /api/stats processing never exceeds this worker bound",
    )
    parser.add_argument(
        "--restart-command",
        help="Command run without a shell after all checks, e.g. 'docker restart invoice-volume'",
    )
    parser.add_argument(
        "--crash-stop-command",
        help="Abrupt stop command used while OCR jobs are processing",
    )
    parser.add_argument(
        "--crash-start-command",
        help="Start command paired with --crash-stop-command",
    )
    parser.add_argument("--recovery-count", type=int, default=6)
    parser.add_argument("--allow-existing", action="store_true")
    parser.add_argument(
        "--allow-small-run",
        action="store_true",
        help="Permit count below 1000 for verifier development only",
    )
    parser.add_argument(
        "--fixture-self-test",
        action="store_true",
        help="Build and validate fixtures without making HTTP requests",
    )
    parser.add_argument("--result-json", help="Optional path for the machine-readable receipt")
    parser.add_argument(
        "--tested-container",
        help="Docker container name to inspect and record in the result receipt",
    )
    args = parser.parse_args(argv)
    if args.count < 1000 and not args.allow_small_run:
        parser.error("--count must be at least 1000 (or pass --allow-small-run for development)")
    for name in ("count", "batch_size", "concurrency", "page_size"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.retries < 0:
        parser.error("--retries cannot be negative")
    if args.expected_workers is not None and args.expected_workers <= 0:
        parser.error("--expected-workers must be positive")
    if bool(args.crash_stop_command) != bool(args.crash_start_command):
        parser.error("--crash-stop-command and --crash-start-command must be supplied together")
    if args.recovery_count < 3:
        parser.error("--recovery-count must be at least 3 to leave work queued behind two workers")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    started = time.monotonic()
    environment = machine_info()
    if args.tested_container:
        environment["tested_docker_runtime"] = docker_runtime_info(args.tested_container)
    receipt: dict[str, Any] = {
        "schema": "invoice-studio-volume-verification.v1",
        "verifier_version": VERSION,
        "started_at": utc_now(),
        "status": "running",
        "command": [sys.executable, *sys.argv],
        "environment": environment,
        "configuration": {
            "base_url": args.base_url,
            "count": args.count,
            "batch_size": args.batch_size,
            "concurrency": args.concurrency,
            "page_size": args.page_size,
            "upload_field": args.upload_field,
            "expected_workers": args.expected_workers,
            "restart_command_supplied": bool(args.restart_command),
            "crash_recovery_commands_supplied": bool(args.crash_stop_command),
            "recovery_count": args.recovery_count,
            "tested_container": args.tested_container,
            "fixture_self_test": args.fixture_self_test,
        },
        "checks": {},
        "failures": [],
    }
    exit_code = 0
    try:
        if args.fixture_self_test:
            fixture_self_test(args, receipt)
        else:
            run_http(args, receipt)
        receipt["status"] = "passed"
    except Exception as exc:
        exit_code = 1
        receipt["status"] = "failed"
        receipt["failures"].append(
            {"type": type(exc).__name__, "message": str(exc), "observed_at": utc_now()}
        )
    receipt["finished_at"] = utc_now()
    receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
    write_receipt(args.result_json, receipt)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
