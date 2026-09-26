"""Tolerance policy as versioned configuration and currency-basis-aware comparison.

Currencies in these tests are fictional choices for a demo brand; they say
nothing about any real master.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend import matching
from backend.service import InvoiceService, NotFound, Settings, UploadRejected, ValidationFailure


def make_service(tmp_path: Path) -> InvoiceService:
    return InvoiceService(
        Settings(
            database_path=tmp_path / "invoice.sqlite3",
            source_dir=tmp_path / "sources",
            export_dir=tmp_path / "exports",
            workers=0,
        )
    )


def legacy_settings_service(tmp_path: Path, tolerance: str = "10") -> InvoiceService:
    """A workspace created before the versioned policy existed."""

    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            f"""
            CREATE TABLE app_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                brand_label TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                location_type TEXT NOT NULL DEFAULT '',
                supplier_rules_json TEXT NOT NULL DEFAULT '[]',
                target_cost_policy_json TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            INSERT INTO app_settings
                (id,brand_label,location,location_type,supplier_rules_json,
                 target_cost_policy_json,version,updated_at)
            VALUES
                (1,'Legacy brand','','','[]',
                 '{{"mode":"invoice_only","maximum_absolute_difference_aed":{tolerance}}}',
                 7,'2026-09-25T00:00:00.000Z');
            """
        )
    return InvoiceService(
        Settings(
            database_path=database_path,
            source_dir=tmp_path / "sources",
            export_dir=tmp_path / "exports",
            workers=0,
        )
    )


def audit_rows(service: InvoiceService, policy_name: str = "tolerance_policy") -> list[dict]:
    return [
        row
        for row in service.list_policy_audit()["items"]
        if row["policy_name"] == policy_name
    ]


# --- defaults and migration -------------------------------------------------


def test_defaults_are_unchanged_by_the_policy_object() -> None:
    assert matching.AUTO_FUZZY_THRESHOLD == 96.0
    assert matching.AUTO_FUZZY_MARGIN == 8.0
    assert matching.SUGGEST_THRESHOLD == 70.0
    assert matching.CRITICAL_UNKNOWN_SCORE_CAP == 92.0


def test_fresh_workspace_has_policy_version_one_with_ten_absolute(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    settings = service.get_settings()
    assert settings["target_cost_policy"] == {
        "mode": "invoice_only",
        "maximum_absolute_difference_aed": 10,
    }
    policy = settings["tolerance_policy"]
    assert policy["version"] == 1
    assert policy["absolute_tolerance"] == 10
    assert policy["percentage_tolerance"] is None
    assert policy["scope"] == "per_line"
    assert policy["invoice_currency_scope"] == ["AED"]
    migration = audit_rows(service)
    assert len(migration) == 1
    assert migration[0]["actor"] == "system:migration"
    assert migration[0]["before"] is None
    assert migration[0]["after"]["absolute_tolerance"] == 10


def test_legacy_settings_migrate_to_version_one_with_same_absolute_value(
    tmp_path: Path,
) -> None:
    service = legacy_settings_service(tmp_path, tolerance="12.5")
    settings = service.get_settings()
    assert settings["version"] == 7
    assert settings["brand_label"] == "Legacy brand"
    assert settings["target_cost_policy"]["maximum_absolute_difference_aed"] == 12.5
    policy = settings["tolerance_policy"]
    assert policy["version"] == 1
    assert policy["absolute_tolerance"] == 12.5
    assert policy["effective_date"] == "2026-09-25"
    assert policy["scope"] == "per_line"
    rows = audit_rows(service)
    assert len(rows) == 1 and rows[0]["actor"] == "system:migration"
    # Re-opening the same database does not migrate twice.
    again = InvoiceService(service.settings)
    assert again.get_settings()["tolerance_policy"]["version"] == 1
    assert len(audit_rows(again)) == 1


def test_legacy_client_update_edits_only_the_absolute_tolerance(tmp_path: Path) -> None:
    service = legacy_settings_service(tmp_path)
    settings = service.get_settings()
    updated = service.update_settings(
        settings["version"],
        {
            "brand_label": "Legacy brand",
            "target_cost_policy": {
                "mode": "invoice_only",
                "maximum_absolute_difference_aed": 25,
            },
        },
    )
    assert updated["target_cost_policy"]["maximum_absolute_difference_aed"] == 25
    assert updated["tolerance_policy"]["version"] == 2
    assert updated["tolerance_policy"]["absolute_tolerance"] == 25
    assert updated["tolerance_policy"]["scope"] == "per_line"
    rows = audit_rows(service)
    assert len(rows) == 2
    change = rows[0]
    assert change["actor"] == "operator"
    assert change["settings_version"] == updated["version"]
    assert change["before"]["absolute_tolerance"] == 10
    assert change["after"]["absolute_tolerance"] == 25


def test_saving_settings_without_a_policy_change_appends_no_audit_row(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    settings = service.get_settings()
    updated = service.update_settings(
        settings["version"],
        {"brand_label": "Renamed", "target_cost_policy": settings["target_cost_policy"]},
    )
    assert updated["brand_label"] == "Renamed"
    assert updated["tolerance_policy"]["version"] == 1
    assert len(audit_rows(service)) == 1


# --- versioned policy edits and audit --------------------------------------


def test_policy_edit_bumps_version_and_records_before_and_after(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    settings = service.get_settings()
    updated = service.update_settings(
        settings["version"],
        {
            "changed_by": "finance-lead",
            "tolerance_policy": {
                "owner": "Finance",
                "effective_date": "2026-10-01",
                "absolute_tolerance": 15,
                "percentage_tolerance": 5,
                "scope": "per_invoice",
                "invoice_currency_scope": ["AED", "USD"],
            },
        },
    )
    policy = updated["tolerance_policy"]
    assert policy["version"] == 2
    assert policy["owner"] == "Finance"
    assert policy["effective_date"] == "2026-10-01"
    assert policy["absolute_tolerance"] == 15
    assert policy["percentage_tolerance"] == 5
    assert policy["scope"] == "per_invoice"
    assert policy["invoice_currency_scope"] == ["AED", "USD"]
    # The compatibility projection follows the absolute tolerance.
    assert updated["target_cost_policy"] == {
        "mode": "invoice_only",
        "maximum_absolute_difference_aed": 15,
    }
    rows = audit_rows(service)
    assert [row["actor"] for row in rows] == ["finance-lead", "system:migration"]
    assert rows[0]["before"]["version"] == 1
    assert rows[0]["after"]["version"] == 2
    assert rows[0]["after"]["scope"] == "per_invoice"
    assert rows[0]["settings_version"] == updated["version"]
    # A second, identical save changes nothing and is not audited.
    same = service.update_settings(updated["version"], {"tolerance_policy": policy})
    assert same["tolerance_policy"]["version"] == 2
    assert len(audit_rows(service)) == 2


def test_policy_validation_rejects_bad_values(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    version = service.get_settings()["version"]
    with pytest.raises(ValidationFailure) as failure:
        service.update_settings(
            version,
            {
                "tolerance_policy": {
                    "absolute_tolerance": -1,
                    "percentage_tolerance": 150,
                    "scope": "per_planet",
                    "effective_date": "yesterday",
                    "invoice_currency_scope": ["A1"],
                }
            },
        )
    fields = {error["field"] for error in failure.value.errors}
    assert {
        "tolerance_policy.absolute_tolerance",
        "tolerance_policy.percentage_tolerance",
        "tolerance_policy.scope",
        "tolerance_policy.effective_date",
        "tolerance_policy.invoice_currency_scope",
    } <= fields
    assert service.get_settings()["tolerance_policy"]["version"] == 1
    assert len(audit_rows(service)) == 1


# --- catalog import currency -------------------------------------------------


CATALOG_HEADER = b"rms_item_id,upc,description,supplier_id,uom,unit_cost\n"


def test_import_without_currency_leaves_rows_undeclared_and_keeps_count_shape(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    counts = service.import_catalog(
        "counts.csv",
        CATALOG_HEADER + b"ITEM-0,,Fictional item zero,SUP-1,EA,10\n",
    )
    assert counts == {"imported": 1, "skipped": 0, "warnings": []}
    result = service.import_catalog_detailed(
        "catalog.csv",
        CATALOG_HEADER + b"ITEM-1,,Fictional item one,SUP-1,EA,10\n",
    )
    assert result["imported"] == 1
    assert result["cost_currency"] is None
    assert result["cost_currency_source"] is None
    assert result["undeclared_currency_rows"] == 1
    imports = service.list_catalog_imports()["items"]
    assert [row["id"] for row in imports][0] == result["import_id"]
    assert len(imports) == 2
    assert imports[0]["cost_currency"] is None
    assert imports[0]["undeclared_currency_rows"] == 1
    item = service.list_catalog(search="ITEM-1", limit=5)["items"][0]
    assert item["cost_currency"] is None


def test_import_records_operator_declared_currency(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    result = service.import_catalog_detailed(
        "catalog.csv",
        CATALOG_HEADER + b"ITEM-1,,Fictional item one,SUP-1,EA,10\n",
        cost_currency="usd",
        declared_by="ops-1",
    )
    assert result["cost_currency"] == "USD"
    assert result["cost_currency_source"] == "operator"
    assert result["undeclared_currency_rows"] == 0
    record = service.list_catalog_imports()["items"][0]
    assert record["cost_currency"] == "USD"
    assert record["cost_currency_source"] == "operator"
    assert record["declared_by"] == "ops-1"
    assert record["declared_at"]
    assert service.list_catalog(search="ITEM-1", limit=5)["items"][0]["cost_currency"] == "USD"


def test_import_prefers_a_cost_currency_column_over_the_declaration(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    result = service.import_catalog_detailed(
        "catalog.csv",
        b"rms_item_id,description,supplier_id,uom,unit_cost,cost_currency\n"
        b"ITEM-1,Fictional item one,SUP-1,EA,10,EUR\n"
        b"ITEM-2,Fictional item two,SUP-1,EA,10,\n",
        cost_currency="USD",
        declared_by="ops-1",
    )
    assert result["cost_currency_source"] == "column"
    assert result["column_currency_rows"] == 1
    items = {
        row["rms_item_id"]: row["cost_currency"]
        for row in service.list_catalog(search="Fictional", limit=5)["items"]
    }
    assert items == {"ITEM-1": "EUR", "ITEM-2": "USD"}


def test_selling_retail_currency_column_is_not_taken_as_the_cost_currency(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    result = service.import_catalog_detailed(
        "catalog.csv",
        b"rms_item_id,description,supplier_id,uom,unit_cost,selling_retail_currency\n"
        b"ITEM-1,Fictional item one,SUP-1,EA,10,GBP\n",
    )
    assert result["cost_currency_source"] is None
    assert service.list_catalog(search="ITEM-1", limit=5)["items"][0]["cost_currency"] is None


def test_import_rejects_invalid_currency_or_missing_declarer(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    rows = CATALOG_HEADER + b"ITEM-1,,Fictional item one,SUP-1,EA,10\n"
    with pytest.raises(UploadRejected):
        service.import_catalog("catalog.csv", rows, cost_currency="dollars", declared_by="x")
    with pytest.raises(UploadRejected):
        service.import_catalog("catalog.csv", rows, cost_currency="USD")


def test_declaring_currency_later_updates_undeclared_rows_and_is_audited(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    result = service.import_catalog_detailed(
        "catalog.csv",
        CATALOG_HEADER + b"ITEM-1,,Fictional item one,SUP-1,EA,10\n",
    )
    with pytest.raises(ValidationFailure):
        service.declare_catalog_import_currency(result["import_id"], "US", "ops-2")
    with pytest.raises(NotFound):
        service.declare_catalog_import_currency("import:missing", "USD", "ops-2")
    declared = service.declare_catalog_import_currency(result["import_id"], "usd", "ops-2")
    assert declared["cost_currency"] == "USD"
    assert declared["cost_currency_source"] == "operator"
    assert declared["rows_declared"] == 1
    assert service.list_catalog(search="ITEM-1", limit=5)["items"][0]["cost_currency"] == "USD"
    record = service.list_catalog_imports()["items"][0]
    assert record["undeclared_currency_rows"] == 0
    audit = audit_rows(service, f"catalog_import_currency:{result['import_id']}")
    assert len(audit) == 1
    assert audit[0]["actor"] == "ops-2"
    assert audit[0]["before"]["cost_currency"] is None
    assert audit[0]["after"]["cost_currency"] == "USD"


def test_catalog_rows_from_before_the_feature_attach_to_a_legacy_import(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.import_catalog(
        "old.csv", CATALOG_HEADER + b"ITEM-1,,Fictional item one,SUP-1,EA,10\n"
    )
    # Simulate a database written before catalog imports were tracked.
    with sqlite3.connect(service.settings.database_path) as connection:
        connection.execute("UPDATE catalog_items SET import_id = NULL, cost_currency = NULL")
        connection.execute("DELETE FROM catalog_imports")
    reopened = InvoiceService(service.settings)
    imports = reopened.list_catalog_imports()["items"]
    assert [row["id"] for row in imports] == ["legacy"]
    assert imports[0]["cost_currency"] is None
    assert imports[0]["imported_rows"] == 1
    assert imports[0]["undeclared_currency_rows"] == 1


# --- conversion rates -------------------------------------------------------


def test_rate_table_starts_empty_and_only_holds_operator_entries(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    assert service.list_conversion_rates()["items"] == []
    with pytest.raises(ValidationFailure) as failure:
        service.add_conversion_rate(
            {"from_currency": "USD", "to_currency": "USD", "rate": "0", "source": ""}
        )
    fields = {error["field"] for error in failure.value.errors}
    assert {"to_currency", "rate", "source", "entered_by"} <= fields
    row = service.add_conversion_rate(
        {
            "from_currency": "usd",
            "to_currency": "aed",
            "rate": "3.6725",
            "source": "treasury sheet",
            "entered_by": "ops-3",
            "effective_date": "2026-09-01",
        }
    )
    assert row["from_currency"] == "USD"
    assert row["to_currency"] == "AED"
    assert row["rate"] == 3.6725
    assert row["source"] == "treasury sheet"
    assert row["entered_by"] == "ops-3"
    assert row["effective_date"] == "2026-09-01"
    assert row["entered_at"]
    assert service.list_conversion_rates()["items"][0]["id"] == row["id"]
    assert audit_rows(service, "conversion_rate")[0]["actor"] == "ops-3"


# --- comparison --------------------------------------------------------------


def demo_with_foreign_master(tmp_path: Path, currency: str = "USD") -> tuple[InvoiceService, dict, dict]:
    """Demo invoice (AED) with a catalog item whose cost is declared in another currency."""

    service = make_service(tmp_path)
    service.seed_demo()
    service.import_catalog(
        "foreign.csv",
        CATALOG_HEADER + b"FOREIGN-1,,Fictional Hydrating Cleanser 250ml,DEMO-SUPPLIER,EA,12.25\n",
        cost_currency=currency,
        declared_by="ops-4",
    )
    selected = service.list_catalog(search="FOREIGN-1", supplier_id="DEMO-SUPPLIER", limit=5)[
        "items"
    ][0]
    invoice = service.get_invoice("demo-invoice-001")
    lines = invoice["lines"]
    lines[0].update(
        quantity="10",
        unit_price="45",
        line_total="450.00",
        catalog_item_id=selected["catalog_item_id"],
        rms_item_id=selected["rms_item_id"],
        match_status="confirmed",
    )
    edited = service.update_invoice(invoice["id"], invoice["version"], {"lines": lines})
    return service, edited, selected


def test_same_currency_comparison_is_unchanged(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.seed_demo()
    invoice = service.get_invoice("demo-invoice-001")
    line = invoice["lines"][0]
    assert line["rms_cost_currency"] == "AED"
    assert line["target_cost_comparison_status"] in {"within_tolerance", "above_tolerance"}
    assert line["target_cost_comparison_reason"] == "same_currency"
    assert line["conversion_rate_id"] is None
    assert line["rms_unit_cost_converted"] is None


def test_foreign_master_currency_without_rate_is_currency_basis_mismatch(
    tmp_path: Path,
) -> None:
    service, edited, _ = demo_with_foreign_master(tmp_path)
    line = edited["lines"][0]
    assert line["rms_cost_currency"] == "USD"
    assert line["rms_unit_cost"] == 12.25
    assert line["target_unit_cost"] == 45
    assert line["target_cost_variance"] is None
    assert line["target_cost_comparison_status"] == "currency_basis_mismatch"
    assert line["target_cost_comparison_reason"] == "no_conversion_rate:USD->AED"
    assert line["target_cost_review_required"]
    assert line["conversion_rate_id"] is None
    assert edited["target_cost_review_required"]
    # Persisted, not only computed.
    stored = service.get_invoice(edited["id"])["lines"][0]
    assert stored["target_cost_comparison_status"] == "currency_basis_mismatch"


def test_auto_matched_line_carries_the_master_currency_into_the_comparison(
    tmp_path: Path,
) -> None:
    """The auto path selects from the public candidate projection, which renames
    ``cost_currency`` to ``rms_cost_currency``; the line must still carry it."""

    catalog = [
        {
            "catalog_item_id": "c-1",
            "rms_item_id": "RMS-GBP-1",
            "description": "Fictional Widget Blue",
            "supplier_id": "900001",
            "uom": "EA",
            "unit_cost": 4.5,
            "cost_currency": "GBP",
        }
    ]
    [line] = matching.match_lines(
        [{"description": "Fictional Widget Blue", "quantity": "2", "unit_price": "10.00"}],
        catalog,
        supplier_id="900001",
    )
    assert line["match_status"] == "auto"
    assert line["rms_cost_currency"] == "GBP"
    assert line["candidates"][0]["rms_cost_currency"] == "GBP"

    # End to end: an invoice whose only line auto-matches a GBP master row.
    service = make_service(tmp_path)
    service.import_catalog(
        "gbp.csv",
        CATALOG_HEADER + b"RMS-GBP-1,,Fictional Widget Blue,900001,EA,4.50\n",
        cost_currency="GBP",
        declared_by="ops-9",
    )
    content = (
        b"Supplier name: Fictional Trading FZE\nSupplier ID: 900001\nInvoice number: GBP-1\n"
        b"Invoice date: 2026-09-24\nCurrency: AED\n"
        b"Description                     Qty Unit Price Line Total\n"
        b"Fictional Widget Blue            2 10.00 20.00\n"
        b"Grand Total AED 20.00\n"
    )
    item, _ = service.ingest_bytes("gbp.txt", content)
    assert service._claim_job() == item["id"]
    service._process_job(item["id"])
    invoice = service.get_invoice(item["id"])
    line = invoice["lines"][0]
    assert line["match_status"] == "auto"
    assert line["rms_item_id"] == "RMS-GBP-1"
    assert line["rms_cost_currency"] == "GBP"
    assert line["target_cost_comparison_status"] == "currency_basis_mismatch"
    assert line["target_cost_comparison_reason"] == "no_conversion_rate:GBP->AED"


def test_foreign_master_currency_with_operator_rate_is_converted_and_compared(
    tmp_path: Path,
) -> None:
    service, edited, _ = demo_with_foreign_master(tmp_path)
    rate = service.add_conversion_rate(
        {
            "from_currency": "USD",
            "to_currency": "AED",
            "rate": "3.6725",
            "source": "treasury sheet",
            "entered_by": "ops-3",
            "effective_date": "2020-01-01",
        }
    )
    rematched = service.rematch(edited["id"], edited["version"])
    line = rematched["lines"][0]
    assert line["conversion_rate_id"] == rate["id"]
    assert line["rms_unit_cost"] == 12.25
    assert line["rms_unit_cost_converted"] == pytest.approx(44.988125)
    assert line["target_cost_variance"] == pytest.approx(-0.011875)
    assert line["target_cost_comparison_status"] == "within_tolerance"
    assert line["target_cost_comparison_reason"] == f"converted_with_operator_rate:{rate['id']}"
    assert not line["target_cost_review_required"]
    # A rate in the other direction, or for another pair, does not apply.
    service.add_conversion_rate(
        {
            "from_currency": "EUR",
            "to_currency": "AED",
            "rate": "4",
            "source": "treasury sheet",
            "entered_by": "ops-3",
        }
    )
    again = service.rematch(rematched["id"], rematched["version"])
    assert again["lines"][0]["conversion_rate_id"] == rate["id"]


def test_operator_rate_after_the_invoice_date_does_not_apply(tmp_path: Path) -> None:
    service, edited, _ = demo_with_foreign_master(tmp_path)
    service.add_conversion_rate(
        {
            "from_currency": "USD",
            "to_currency": "AED",
            "rate": "3.6725",
            "source": "treasury sheet",
            "entered_by": "ops-3",
            "effective_date": "2099-01-01",
        }
    )
    rematched = service.rematch(edited["id"], edited["version"])
    assert rematched["lines"][0]["target_cost_comparison_status"] == "currency_basis_mismatch"


def test_converted_comparison_can_still_be_above_tolerance(tmp_path: Path) -> None:
    service, edited, _ = demo_with_foreign_master(tmp_path)
    service.add_conversion_rate(
        {
            "from_currency": "USD",
            "to_currency": "AED",
            "rate": "2",
            "source": "treasury sheet",
            "entered_by": "ops-3",
            "effective_date": "2020-01-01",
        }
    )
    line = service.rematch(edited["id"], edited["version"])["lines"][0]
    assert line["rms_unit_cost_converted"] == 24.5
    assert line["target_cost_variance"] == -20.5
    assert line["target_cost_comparison_status"] == "above_tolerance"
    assert line["target_cost_review_required"]


def test_undeclared_master_currency_compares_as_before_with_a_reason(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.seed_demo()
    service.import_catalog(
        "undeclared.csv",
        CATALOG_HEADER + b"UNDECLARED-1,,Fictional Hydrating Cleanser 250ml,DEMO-SUPPLIER,EA,44\n",
    )
    selected = service.list_catalog(search="UNDECLARED-1", supplier_id="DEMO-SUPPLIER", limit=5)[
        "items"
    ][0]
    invoice = service.get_invoice("demo-invoice-001")
    lines = invoice["lines"]
    lines[0].update(
        quantity="10",
        unit_price="45",
        line_total="450.00",
        catalog_item_id=selected["catalog_item_id"],
        rms_item_id=selected["rms_item_id"],
        match_status="confirmed",
    )
    line = service.update_invoice(invoice["id"], invoice["version"], {"lines": lines})["lines"][0]
    assert line["rms_cost_currency"] is None
    assert line["target_cost_variance"] == -1
    assert line["target_cost_comparison_status"] == "within_tolerance"
    assert line["target_cost_comparison_reason"] == "master_cost_currency_undeclared"


def test_percentage_tolerance_makes_review_stricter_not_looser(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.seed_demo()
    invoice = service.get_invoice("demo-invoice-001")
    lines = invoice["lines"]
    lines[0].update(quantity="2", unit_price="44.00", line_total="88.00")
    invoice = service.update_invoice(invoice["id"], invoice["version"], {"lines": lines})
    line = invoice["lines"][0]
    assert line["target_cost_comparison_status"] == "within_tolerance"
    assert line["target_cost_variance"] == 1
    settings = service.get_settings()
    service.update_settings(
        settings["version"],
        {
            "tolerance_policy": {
                **settings["tolerance_policy"],
                "percentage_tolerance": 1,
            }
        },
    )
    rematched = service.rematch(invoice["id"], invoice["version"])
    assert rematched["lines"][0]["target_cost_variance"] == 1
    assert rematched["lines"][0]["target_cost_comparison_status"] == "above_tolerance"
    assert rematched["lines"][0]["target_cost_review_required"]


def test_per_invoice_scope_applies_the_tolerance_to_the_invoice_total_variance(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.seed_demo()
    invoice = service.get_invoice("demo-invoice-001")
    per_line = [line["target_cost_comparison_status"] for line in invoice["lines"]]
    assert "within_tolerance" in per_line
    settings = service.get_settings()
    service.update_settings(
        settings["version"],
        {"tolerance_policy": {**settings["tolerance_policy"], "scope": "per_invoice"}},
    )
    rematched = service.rematch(invoice["id"], invoice["version"])
    comparable = [
        line
        for line in rematched["lines"]
        if line["target_cost_comparison_status"] in {"within_tolerance", "above_tolerance"}
    ]
    assert comparable
    total_variance = sum(
        abs(float(line["target_cost_variance"])) * float(line["quantity"]) for line in comparable
    )
    expected = "above_tolerance" if total_variance > 10 else "within_tolerance"
    assert {line["target_cost_comparison_status"] for line in comparable} == {expected}
    assert all("scope=per_invoice" in line["target_cost_comparison_reason"] for line in comparable)


# --- API surface -------------------------------------------------------------


def test_api_exposes_policy_rates_and_import_currency(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from backend.app import create_app

    settings = Settings(
        database_path=tmp_path / "api.sqlite3",
        source_dir=tmp_path / "sources",
        export_dir=tmp_path / "exports",
        workers=0,
    )
    with TestClient(create_app(settings)) as client:
        current = client.get("/api/settings").json()
        assert current["tolerance_policy"]["version"] == 1
        assert current["target_cost_policy"]["maximum_absolute_difference_aed"] == 10

        # Legacy client payload (target_cost_policy only) still works.
        legacy = client.put(
            "/api/settings",
            json={
                "expected_version": current["version"],
                "target_cost_policy": {"mode": "invoice_only", "maximum_absolute_difference_aed": 11},
            },
        )
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["tolerance_policy"]["absolute_tolerance"] == 11
        assert legacy.json()["tolerance_policy"]["version"] == 2

        # Versioned client payload.
        versioned = client.put(
            "/api/settings",
            json={
                "expected_version": legacy.json()["version"],
                "changed_by": "api-user",
                "tolerance_policy": {**legacy.json()["tolerance_policy"], "percentage_tolerance": 2},
            },
        )
        assert versioned.status_code == 200, versioned.text
        assert versioned.json()["tolerance_policy"]["percentage_tolerance"] == 2
        assert versioned.json()["tolerance_policy"]["version"] == 3
        audit = client.get("/api/settings/audit").json()["items"]
        assert [row["actor"] for row in audit][:2] == ["api-user", "operator"]

        assert client.get("/api/rates").json() == {"items": []}
        rate = client.post(
            "/api/rates",
            json={
                "from_currency": "USD",
                "to_currency": "AED",
                "rate": "3.6725",
                "source": "treasury sheet",
                "entered_by": "api-user",
            },
        )
        assert rate.status_code == 200, rate.text
        assert client.get("/api/rates").json()["items"][0]["id"] == rate.json()["id"]

        imported = client.post(
            "/api/catalog/import",
            files={"file": ("catalog.csv", CATALOG_HEADER + b"ITEM-1,,Fictional item one,SUP-1,EA,10\n")},
            data={"cost_currency": "usd", "declared_by": "api-user"},
        )
        assert imported.status_code == 200, imported.text
        body = imported.json()
        assert body["imported"] == 1
        assert body["import"]["cost_currency"] == "USD"
        assert body["import"]["cost_currency_source"] == "operator"
        imports = client.get("/api/catalog/imports").json()["items"]
        assert imports[0]["id"] == body["import"]["id"]

        undeclared = client.post(
            "/api/catalog/import",
            files={"file": ("second.csv", CATALOG_HEADER + b"ITEM-2,,Fictional item two,SUP-1,EA,10\n")},
        )
        assert undeclared.json()["import"]["cost_currency"] is None
        declared = client.put(
            f"/api/catalog/imports/{undeclared.json()['import']['id']}",
            json={"cost_currency": "EUR", "declared_by": "api-user"},
        )
        assert declared.status_code == 200, declared.text
        assert declared.json()["cost_currency"] == "EUR"
        assert declared.json()["rows_declared"] == 1
