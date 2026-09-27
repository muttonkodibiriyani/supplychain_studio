"""POST /api/demo is a training aid, not a data path.

It writes fictional catalog rows and invoices whose lines are stored as matched
without running the matcher, so it must be off unless explicitly enabled and
must never seed next to real rows.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.service import DemoSeedRefused, InvoiceService, Settings

CATALOG_CSV = (
    b"rms_item_id,description,supplier_id,uom,unit_cost\n"
    b"RMS-REAL-1,Fictional Real Row 100ml,SUP-REAL,EA,12.00\n"
)


def make_settings(tmp_path: Path, *, enable_demo_seed: bool) -> Settings:
    return Settings(
        database_path=tmp_path / "demo-seed.db",
        source_dir=tmp_path / "sources",
        export_dir=tmp_path / "exports",
        workers=0,
        enable_demo_seed=enable_demo_seed,
    )


def row_counts(service: InvoiceService) -> dict[str, int]:
    with service.db.connection() as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("catalog_items", "invoices", "invoice_lines")
        }


def test_flag_defaults_off_and_reads_the_environment(tmp_path: Path) -> None:
    assert Settings(database_path=tmp_path, source_dir=tmp_path, export_dir=tmp_path).enable_demo_seed is False
    with mock.patch.dict(os.environ, {"INVOICE_DATA_DIR": str(tmp_path)}, clear=False):
        os.environ.pop("INVOICE_ENABLE_DEMO_SEED", None)
        assert Settings.from_env().enable_demo_seed is False
        for value in ("1", "true", "YES", " on "):
            os.environ["INVOICE_ENABLE_DEMO_SEED"] = value
            assert Settings.from_env().enable_demo_seed is True, value
        for value in ("0", "false", "", "off"):
            os.environ["INVOICE_ENABLE_DEMO_SEED"] = value
            assert Settings.from_env().enable_demo_seed is False, value


def test_endpoint_is_refused_and_writes_nothing_when_the_flag_is_off(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, enable_demo_seed=False))
    with TestClient(app) as client:
        response = client.post("/api/demo")
        assert response.status_code == 403
        assert "INVOICE_ENABLE_DEMO_SEED" in response.json()["detail"]
        service = app.state.invoice_service
        assert row_counts(service) == {"catalog_items": 0, "invoices": 0, "invoice_lines": 0}
        assert not any(service.settings.source_dir.glob("*"))


def test_endpoint_seeds_once_and_reseeding_is_idempotent_when_the_flag_is_on(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, enable_demo_seed=True))
    with TestClient(app) as client:
        first = client.post("/api/demo")
        assert first.status_code == 200
        service = app.state.invoice_service
        counts = row_counts(service)
        assert first.json()["catalog_items_upserted"] == counts["catalog_items"] > 0
        assert first.json()["invoices_created"] == counts["invoices"] > 0
        assert counts["invoice_lines"] > 0
        with service.db.connection() as conn:
            ids = [row[0] for row in conn.execute("SELECT catalog_item_id FROM catalog_items")]
            invoice_ids = [row[0] for row in conn.execute("SELECT id FROM invoices")]
        assert ids and all(item.startswith("demo:") for item in ids)
        assert invoice_ids and all(item.startswith("demo-") for item in invoice_ids)

        second = client.post("/api/demo")
        assert second.status_code == 200
        # Catalog rows are upserted on their fixed ids, invoices are skipped when present.
        assert second.json()["catalog_items_upserted"] == counts["catalog_items"]
        assert second.json()["invoices_created"] == 0
        assert row_counts(service) == counts


def test_seed_is_refused_over_a_non_demo_catalog_row(tmp_path: Path) -> None:
    service = InvoiceService(make_settings(tmp_path, enable_demo_seed=True))
    assert service.import_catalog("catalog.csv", CATALOG_CSV)["imported"] == 1
    before = row_counts(service)
    with pytest.raises(DemoSeedRefused) as refused:
        service.seed_demo()
    assert refused.value.non_demo_catalog_rows == 1
    assert refused.value.non_demo_invoices == 0
    assert row_counts(service) == before


def test_seed_is_refused_over_a_non_demo_invoice_and_names_the_counts(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, enable_demo_seed=True))
    with TestClient(app) as client:
        service = app.state.invoice_service
        service.ingest_bytes("real-upload.txt", b"Supplier name: Fictional Upload\nTotal 1.00\n")
        before = row_counts(service)
        assert before["invoices"] == 1
        response = client.post("/api/demo")
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["non_demo_catalog_rows"] == 0
        assert detail["non_demo_invoices"] == 1
        assert "1 non-demo invoices" in detail["message"]
        assert row_counts(service) == before


def test_stats_flag_demo_rows_so_a_seeded_database_is_not_read_as_a_measurement(tmp_path: Path) -> None:
    service = InvoiceService(make_settings(tmp_path, enable_demo_seed=True))
    clean = service.stats()
    assert clean["contains_demo_data"] is False
    assert (clean["demo_catalog_items"], clean["demo_invoices"], clean["demo_lines"]) == (0, 0, 0)

    service.seed_demo()
    seeded = service.stats()
    assert seeded["contains_demo_data"] is True
    assert seeded["demo_catalog_items"] == seeded["catalog_items"] > 0
    assert seeded["demo_invoices"] == seeded["total"] > 0
    assert seeded["demo_lines"] == seeded["total_lines"] > 0
    # The seeded literals are exactly what inflates the rate; the flag is what
    # tells a reader that matched_lines here measured nothing.
    assert seeded["matched_lines"] > 0


def _load_evaluate_corpus_module():
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_corpus.py"
    spec = importlib.util.spec_from_file_location("evaluate_corpus_under_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_corpus_evaluator_refuses_an_input_root_holding_demo_sources(tmp_path: Path) -> None:
    from backend.service import DEMO_SOURCE_PREFIX

    evaluate_corpus = _load_evaluate_corpus_module()
    assert evaluate_corpus.DEMO_SOURCE_PREFIX == DEMO_SOURCE_PREFIX
    root = tmp_path / "sources"
    root.mkdir()
    (root / "real-invoice.txt").write_bytes(b"Supplier name: Fictional Real\nTotal 1.00\n")
    assert len(evaluate_corpus._load_records(root, None)) == 1

    (root / f"{DEMO_SOURCE_PREFIX}001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(SystemExit) as refused:
        evaluate_corpus._load_records(root, None)
    assert "demo" in str(refused.value)
    assert refused.value.code not in (None, 0)
