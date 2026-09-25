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


def test_worker_pool_survives_database_lock_longer_than_busy_timeout(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.start()
    try:
        first, _ = service.ingest_bytes("before-lock.txt", b"queued before the lock")
        assert wait_until(lambda: terminal(service, first["id"]))

        # Hold the write lock for far longer than the 0.2 s busy timeout so
        # every worker claim raises "database is locked".
        blocker = sqlite3.connect(service.settings.database_path, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        time.sleep(1.0)
        status = service.worker_status()
        blocker.execute("ROLLBACK")
        blocker.close()

        assert status["error_count"] > 0, "expected claim attempts to hit the lock"
        assert "locked" in (status["last_error"] or "")
        assert status["alive"] == 2
        assert status["thread_exits"] == 0, "worker threads must not exit on a lock error"

        second, _ = service.ingest_bytes("after-lock.txt", b"queued after the lock is released")
        assert wait_until(lambda: terminal(service, second["id"])), (
            "queue did not drain after the lock was released: " + str(service.worker_status())
        )
        assert service.worker_status()["thread_exits"] == 0
    finally:
        service.stop()


def test_large_catalog_import_then_queue_still_drains(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.start()
    try:
        warm, _ = service.ingest_bytes("warm.txt", b"warm up the pool")
        assert wait_until(lambda: terminal(service, warm["id"]))

        started = time.monotonic()
        result = service.import_catalog("master.csv", synthetic_catalog(60_000))
        elapsed = time.monotonic() - started
        assert result["imported"] == 60_000
        assert elapsed > 0.2, "import must outlast the busy timeout for this test to prove anything"

        after, _ = service.ingest_bytes("after-import.txt", b"queued after a large catalog import")
        assert wait_until(lambda: terminal(service, after["id"]), timeout=30), (
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
