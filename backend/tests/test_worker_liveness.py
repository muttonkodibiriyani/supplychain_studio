"""Regression tests for the extraction worker pool dying silently.

Observed in production: after a multi-minute item-master import the queue
showed queued=20 processing=0 forever with no log line. Cause: the import held
``BEGIN IMMEDIATE`` for the whole parse, every worker's job claim outlived the
SQLite busy timeout, ``sqlite3.OperationalError: database is locked`` escaped
``_worker_loop`` and the daemon threads exited. These tests pin the fix.
"""

from __future__ import annotations

import io
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.service import InvoiceService, Settings


def make_service(tmp_path: Path, *, workers: int = 2, **overrides) -> InvoiceService:
    settings = Settings(
        database_path=tmp_path / "invoices.sqlite3",
        source_dir=tmp_path / "sources",
        export_dir=tmp_path / "exports",
        workers=workers,
        poll_seconds=0.05,
        db_busy_timeout_seconds=0.2,
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return InvoiceService(settings)


def wait_until(predicate, timeout: float = 15.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def terminal(service: InvoiceService, invoice_id: str) -> bool:
    return service.get_invoice(invoice_id)["status"] not in {"queued", "processing"}


def synthetic_catalog(rows: int) -> bytes:
    buffer = io.StringIO()
    buffer.write("rms_item_id,description,supplier_id,uom,unit_cost\n")
    for index in range(rows):
        buffer.write(f"SYN-{index},Synthetic catalog item {index} 500g,SUP-{index % 40},EA,{index % 97}.25\n")
    return buffer.getvalue().encode("utf-8")


def test_worker_pool_survives_database_lock_longer_than_busy_timeout(tmp_path: Path, monkeypatch) -> None:
    """A job is mid-extraction when another writer takes the lock for longer
    than the busy timeout. Recording the result fails with 'database is
    locked'; the worker must survive, requeue the job and finish it later."""

    from backend import extraction

    service = make_service(tmp_path)
    gate = threading.Event()
    original = extraction.extract_document

    def slow_extract(*args, **kwargs):
        gate.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(extraction, "extract_document", slow_extract)
    service.start()
    try:
        job, _ = service.ingest_bytes("held.txt", b"extracted while the lock is held")
        assert wait_until(lambda: service.get_invoice(job["id"])["status"] == "processing")

        blocker = sqlite3.connect(service.settings.database_path, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        gate.set()  # extraction finishes; every write the worker tries now hits the lock
        time.sleep(1.5)
        status = service.worker_status()
        blocker.execute("ROLLBACK")
        blocker.close()

        assert status["error_count"] > 0, "expected the worker's writes to hit the lock"
        assert "locked" in (status["last_error"] or ""), status
        assert all(thread.is_alive() for thread in service._threads)
        assert status["thread_exits"] == 0, "worker threads must not exit on a lock error"

        assert wait_until(lambda: terminal(service, job["id"])), (
            "job left in limbo after the lock was released: " + str(service.worker_status())
        )
        second, _ = service.ingest_bytes("after-lock.txt", b"queued after the lock is released")
        assert wait_until(lambda: terminal(service, second["id"]))
        assert service.worker_status()["thread_exits"] == 0
    finally:
        service.stop()


def test_uploads_during_large_catalog_import_drain_without_restart(tmp_path: Path) -> None:
    """The production failure: a catalog import longer than the busy timeout,
    uploads arriving while it runs, then queued>0 processing=0 forever."""

    # 2 s busy timeout: a 1000-row commit chunk stays far below it even on a
    # loaded shared host, while parsing 80k rows takes well over 2 s.
    service = make_service(tmp_path, db_busy_timeout_seconds=2.0)
    service.start()
    try:
        warm, _ = service.ingest_bytes("warm.txt", b"warm up the pool")
        assert wait_until(lambda: terminal(service, warm["id"]))

        catalog = synthetic_catalog(80_000)
        outcome: dict[str, object] = {}

        def run_import() -> None:
            started = time.monotonic()
            try:
                outcome["result"] = service.import_catalog("master.csv", catalog)
            except BaseException as error:  # pragma: no cover - reported below
                outcome["error"] = error
            outcome["elapsed"] = time.monotonic() - started

        importer = threading.Thread(target=run_import)
        importer.start()
        ids: list[str] = []
        while importer.is_alive():
            time.sleep(0.15)
            job, _ = service.ingest_bytes(f"during-{len(ids)}.txt", f"queued during import {len(ids)}".encode())
            ids.append(job["id"])
        importer.join()
        assert "error" not in outcome, outcome
        assert outcome["result"]["imported"] == 80_000  # type: ignore[index]
        assert outcome["elapsed"] > service.settings.db_busy_timeout_seconds, outcome  # type: ignore[operator]
        assert len(ids) >= 3, "import finished before enough uploads arrived; enlarge the catalog"

        assert all(thread.is_alive() for thread in service._threads), "worker threads died during the import"
        assert wait_until(lambda: all(terminal(service, job_id) for job_id in ids), timeout=120), (
            "queue stalled after the catalog import: " + str(service.worker_status())
        )
        status = service.worker_status()
        assert status["alive"] == 2
        assert status["thread_exits"] == 0
        assert status["queued"] == 0 and status["processing"] == 0
    finally:
        service.stop()


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_dead_worker_thread_is_respawned_and_counted(tmp_path: Path, monkeypatch) -> None:
    service = make_service(tmp_path)
    original = service._claim_job
    fired = threading.Event()

    def claim_then_die():
        if not fired.is_set():
            fired.set()
            raise KeyboardInterrupt("simulated non-Exception escape")
        return original()

    monkeypatch.setattr(service, "_claim_job", claim_then_die)
    service.start()
    try:
        # thread_exits is counted just before the thread finishes, so wait for
        # the respawn itself (ensure_workers runs inside worker_status).
        assert wait_until(lambda: service.worker_status()["respawns"] >= 1)
        status = service.worker_status()
        assert status["thread_exits"] >= 1
        assert status["alive"] == 2
        # Self-healing must stay visible: the respawn is flagged as a problem.
        assert any("respawn" in problem for problem in status["problems"]), status
        job, _ = service.ingest_bytes("after-respawn.txt", b"processed by the respawned pool")
        assert wait_until(lambda: terminal(service, job["id"]))
    finally:
        service.stop()


def test_health_reports_degraded_when_queue_is_stalled(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "invoices.sqlite3",
        source_dir=tmp_path / "sources",
        export_dir=tmp_path / "exports",
        workers=0,
        worker_stall_seconds=0.1,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        response = client.post(
            "/api/invoices/upload",
            files=[("files", ("stalled.txt", b"nobody will process me", "text/plain"))],
        )
        assert response.status_code in (200, 201, 207), response.text
        time.sleep(0.3)
        health = client.get("/api/health").json()
        assert health["status"] == "degraded", health
        assert health["workers"]["queued"] == 1
        assert health["workers"]["stalled"] is True
        assert any("queued" in problem for problem in health["problems"])


def test_catalog_import_does_not_freeze_health_endpoint(tmp_path: Path, monkeypatch) -> None:
    """A slow import must not block the event loop: health keeps answering."""

    settings = Settings(
        database_path=tmp_path / "invoices.sqlite3",
        source_dir=tmp_path / "sources",
        export_dir=tmp_path / "exports",
        workers=0,
    )
    app = create_app(settings)
    import backend.service as service_module

    original = service_module.InvoiceService.import_catalog

    def slow_import(self, filename, content):
        time.sleep(1.5)
        return original(self, filename, content)

    monkeypatch.setattr(service_module.InvoiceService, "import_catalog", slow_import)
    with TestClient(app) as client:
        health_latencies: list[float] = []
        stop = threading.Event()

        def probe():
            while not stop.is_set():
                started = time.monotonic()
                assert client.get("/api/health").status_code == 200
                health_latencies.append(time.monotonic() - started)
                time.sleep(0.1)

        prober = threading.Thread(target=probe)
        prober.start()
        response = client.post(
            "/api/catalog/import",
            files=[("file", ("catalog.csv", synthetic_catalog(10), "text/csv"))],
        )
        stop.set()
        prober.join()
        assert response.status_code == 200, response.text
        assert response.json()["imported"] == 10
        assert len(health_latencies) >= 5, "health probes were blocked during the import"
        assert max(health_latencies) < 1.0, health_latencies


def test_worker_count_is_bounded_by_cores(monkeypatch) -> None:
    import os

    from backend.service import _bounded_workers

    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert _bounded_workers("4") == 4
    assert _bounded_workers("16") == 16
    assert _bounded_workers("64") == 16
    assert _bounded_workers("0") == 0
