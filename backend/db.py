from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


INVOICE_STATUSES = (
    "queued",
    "processing",
    "needs_review",
    "ready",
    "exported",
    "failed",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class Database:
    """Small SQLite wrapper with one connection per operation/thread."""

    def __init__(self, path: str | Path, *, busy_timeout_seconds: float = 30.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_seconds = max(0.05, float(busy_timeout_seconds))

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path, timeout=self.busy_timeout_seconds, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()

    def initialize(self) -> None:
        statuses = ",".join(f"'{status}'" for status in INVOICE_STATUSES)
        schema = f"""
        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            mime_type TEXT,
            source_size INTEGER NOT NULL DEFAULT 0,
            supplier_id TEXT,
            supplier_name TEXT,
            supplier_site TEXT,
            invoice_number TEXT,
            document_type TEXT NOT NULL DEFAULT 'unknown',
            document TEXT,
            invoice_date TEXT,
            po_number TEXT,
            currency TEXT,
            location TEXT,
            location_type TEXT,
            tax_code TEXT,
            ref_no_1 TEXT,
            ref_no_2 TEXT,
            ref_no_3 TEXT,
            comment TEXT,
            subtotal TEXT,
            tax_total TEXT,
            total TEXT,
            target_cost_reviewed INTEGER NOT NULL DEFAULT 0,
            target_cost_reviewed_at TEXT,
            status TEXT NOT NULL CHECK (status IN ({statuses})),
            extraction_method TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            version INTEGER NOT NULL DEFAULT 1,
            pages INTEGER NOT NULL DEFAULT 0,
            raw_text TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT,
            claimed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_invoices_status_queue
            ON invoices(status, next_attempt_at, created_at);
        CREATE INDEX IF NOT EXISTS idx_invoices_supplier_number
            ON invoices(supplier_id, invoice_number);
        CREATE INDEX IF NOT EXISTS idx_invoices_created ON invoices(created_at DESC);

        CREATE TABLE IF NOT EXISTS invoice_lines (
            invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            id TEXT NOT NULL,
            position INTEGER NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            quantity TEXT,
            unit_price TEXT,
            line_total TEXT,
            tax_rate TEXT,
            uom TEXT,
            upc TEXT,
            catalog_item_id TEXT,
            rms_item_id TEXT,
            rms_upc TEXT,
            rms_unit_cost TEXT,
            rms_po_number TEXT,
            target_unit_cost TEXT,
            target_cost_source TEXT,
            target_cost_variance TEXT,
            target_cost_comparison_status TEXT,
            target_cost_review_required INTEGER NOT NULL DEFAULT 0,
            match_status TEXT NOT NULL DEFAULT 'unmatched'
                CHECK (match_status IN ('unmatched','suggested','auto','confirmed')),
            confidence REAL NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 100),
            candidates_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (invoice_id, id)
        );
        CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice_position
            ON invoice_lines(invoice_id, position);

        CREATE TABLE IF NOT EXISTS catalog_items (
            catalog_item_id TEXT PRIMARY KEY,
            rms_item_id TEXT NOT NULL,
            parent_item TEXT NOT NULL,
            upc TEXT,
            description TEXT NOT NULL,
            normalized_description TEXT NOT NULL DEFAULT '',
            supplier_id TEXT,
            supplier_name TEXT,
            uom TEXT,
            unit_cost TEXT,
            master_po_number TEXT,
            source_row INTEGER,
            source_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_description ON catalog_items(description);
        CREATE INDEX IF NOT EXISTS idx_catalog_supplier ON catalog_items(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_catalog_rms_item ON catalog_items(rms_item_id);
        CREATE INDEX IF NOT EXISTS idx_catalog_supplier_item
            ON catalog_items(supplier_id, rms_item_id);
        CREATE INDEX IF NOT EXISTS idx_catalog_supplier_upc
            ON catalog_items(supplier_id, upc);
        CREATE INDEX IF NOT EXISTS idx_catalog_normalized
            ON catalog_items(normalized_description);

        CREATE TABLE IF NOT EXISTS aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_scope TEXT NOT NULL,
            normalized_description TEXT NOT NULL,
            uom_scope TEXT NOT NULL DEFAULT '',
            original_description TEXT NOT NULL,
            catalog_item_id TEXT NOT NULL REFERENCES catalog_items(catalog_item_id),
            rms_item_id TEXT NOT NULL,
            created_from_invoice_id TEXT REFERENCES invoices(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(supplier_scope, normalized_description, uom_scope)
        );
        CREATE INDEX IF NOT EXISTS idx_alias_lookup
            ON aliases(supplier_scope, normalized_description, uom_scope);

        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            created_at TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            version INTEGER NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{{}}'
        );
        CREATE INDEX IF NOT EXISTS idx_audit_invoice
            ON audit_events(invoice_id, id DESC);

        CREATE TABLE IF NOT EXISTS exports (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            invoice_count INTEGER NOT NULL,
            line_count INTEGER NOT NULL DEFAULT 0,
            invoice_ids_json TEXT NOT NULL,
            schema_name TEXT NOT NULL,
            sha256 TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_exports_created ON exports(created_at DESC);
        CREATE TABLE IF NOT EXISTS export_invoices (
            export_id TEXT NOT NULL REFERENCES exports(id) ON DELETE CASCADE,
            invoice_id TEXT NOT NULL REFERENCES invoices(id),
            invoice_version INTEGER NOT NULL,
            PRIMARY KEY (export_id, invoice_id)
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            brand_label TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            location_type TEXT NOT NULL DEFAULT '',
            supplier_rules_json TEXT NOT NULL DEFAULT '[]',
            include_upc_in_export INTEGER NOT NULL DEFAULT 0,
            target_cost_policy_json TEXT NOT NULL DEFAULT
                '{{"maximum_absolute_difference_aed":10,"mode":"invoice_only"}}',
            version INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        """
        with self.connection() as conn:
            catalog_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(catalog_items)").fetchall()
            }
            legacy_catalog = bool(catalog_columns and "catalog_item_id" not in catalog_columns)
            if legacy_catalog:
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("ALTER TABLE catalog_items RENAME TO catalog_items_legacy")
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='aliases'"
                ).fetchone():
                    conn.execute("ALTER TABLE aliases RENAME TO aliases_legacy")
            conn.executescript(schema)
            if legacy_catalog:
                conn.execute(
                    """
                    INSERT INTO catalog_items
                        (catalog_item_id,rms_item_id,parent_item,upc,description,
                         normalized_description,supplier_id,supplier_name,uom,unit_cost,
                         master_po_number,source_row,source_name,created_at,updated_at)
                    SELECT 'legacy:' || rms_item_id,rms_item_id,rms_item_id,NULL,description,
                           lower(trim(description)),supplier_id,NULL,uom,unit_cost,
                           NULL,NULL,'legacy migration',created_at,updated_at
                    FROM catalog_items_legacy
                    """
                )
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='aliases_legacy'"
                ).fetchone():
                    conn.execute(
                        """
                        INSERT INTO aliases
                            (id,supplier_scope,normalized_description,uom_scope,
                             original_description,catalog_item_id,rms_item_id,
                             created_from_invoice_id,created_at,updated_at)
                        SELECT id,supplier_scope,normalized_description,uom_scope,
                               original_description,'legacy:' || rms_item_id,rms_item_id,
                               created_from_invoice_id,created_at,updated_at
                        FROM aliases_legacy
                        """
                    )
                    conn.execute("DROP TABLE aliases_legacy")
                conn.execute("DROP TABLE catalog_items_legacy")
                conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_catalog_description
                    ON catalog_items(description);
                CREATE INDEX IF NOT EXISTS idx_catalog_supplier
                    ON catalog_items(supplier_id);
                CREATE INDEX IF NOT EXISTS idx_catalog_rms_item
                    ON catalog_items(rms_item_id);
                CREATE INDEX IF NOT EXISTS idx_catalog_supplier_item
                    ON catalog_items(supplier_id, rms_item_id);
                CREATE INDEX IF NOT EXISTS idx_catalog_supplier_upc
                    ON catalog_items(supplier_id, upc);
                CREATE INDEX IF NOT EXISTS idx_catalog_normalized
                    ON catalog_items(normalized_description);
                CREATE INDEX IF NOT EXISTS idx_alias_lookup
                    ON aliases(supplier_scope, normalized_description, uom_scope);
                """
            )

            invoice_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(invoices)").fetchall()
            }
            invoice_additions = {
                "document_type": "TEXT NOT NULL DEFAULT 'unknown'",
                "document": "TEXT",
                "location": "TEXT",
                "location_type": "TEXT",
                "tax_code": "TEXT",
                "ref_no_1": "TEXT",
                "ref_no_2": "TEXT",
                "ref_no_3": "TEXT",
                "comment": "TEXT",
                "target_cost_reviewed": "INTEGER NOT NULL DEFAULT 0",
                "target_cost_reviewed_at": "TEXT",
            }
            for name, definition in invoice_additions.items():
                if name not in invoice_columns:
                    conn.execute(f"ALTER TABLE invoices ADD COLUMN {name} {definition}")
            conn.execute("UPDATE invoices SET document = invoice_number WHERE document IS NULL")

            line_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(invoice_lines)").fetchall()
            }
            line_additions = {
                "upc": "TEXT",
                "catalog_item_id": "TEXT",
                "rms_upc": "TEXT",
                "rms_unit_cost": "TEXT",
                "rms_po_number": "TEXT",
                "target_unit_cost": "TEXT",
                "target_cost_source": "TEXT",
                "target_cost_variance": "TEXT",
                "target_cost_comparison_status": "TEXT",
                "target_cost_review_required": "INTEGER NOT NULL DEFAULT 0",
                "rms_unit_cost_min": "TEXT",
                "rms_unit_cost_max": "TEXT",
                "unit_status": "TEXT",
                "unit_reason": "TEXT",
            }
            for name, definition in line_additions.items():
                if name not in line_columns:
                    conn.execute(f"ALTER TABLE invoice_lines ADD COLUMN {name} {definition}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_invoice_lines_catalog "
                "ON invoice_lines(catalog_item_id)"
            )

            export_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(exports)").fetchall()
            }
            if "line_count" not in export_columns:
                conn.execute(
                    "ALTER TABLE exports ADD COLUMN line_count INTEGER NOT NULL DEFAULT 0"
                )
            settings_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(app_settings)").fetchall()
            }
            if "include_upc_in_export" not in settings_columns:
                conn.execute(
                    "ALTER TABLE app_settings ADD COLUMN "
                    "include_upc_in_export INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                """
                INSERT OR IGNORE INTO app_settings
                    (id,brand_label,location,location_type,supplier_rules_json,
                     include_upc_in_export,target_cost_policy_json,version,updated_at)
                VALUES (1,'','','','[]',0,?,1,?)
                """,
                (
                    json_dumps(
                        {
                            "mode": "invoice_only",
                            "maximum_absolute_difference_aed": 10,
                        }
                    ),
                    utc_now(),
                ),
            )

    def recover_interrupted_jobs(self) -> int:
        """Move jobs left in processing back to queued after a process restart."""
        now = utc_now()
        with self.transaction(immediate=True) as conn:
            rows = conn.execute(
                "SELECT id, version FROM invoices WHERE status = 'processing'"
            ).fetchall()
            for row in rows:
                new_version = row["version"] + 1
                conn.execute(
                    """
                    UPDATE invoices
                    SET status = 'queued', updated_at = ?, claimed_at = NULL,
                        next_attempt_at = NULL, version = ?
                    WHERE id = ?
                    """,
                    (now, new_version, row["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO audit_events
                        (invoice_id,event_type,actor,created_at,from_status,to_status,version,details_json)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["id"],
                        "processing_recovered",
                        "system",
                        now,
                        "processing",
                        "queued",
                        new_version,
                        json_dumps({"reason": "service restart"}),
                    ),
                )
            return len(rows)
