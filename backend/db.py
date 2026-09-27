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


DEFAULT_ABSOLUTE_TOLERANCE = 10
DEFAULT_INVOICE_CURRENCY_SCOPE = ["AED"]
TOLERANCE_SCOPES = ("per_line", "per_invoice")
LEGACY_CATALOG_IMPORT_ID = "legacy"


def default_tolerance_policy(
    absolute_tolerance: float | int = DEFAULT_ABSOLUTE_TOLERANCE,
    *,
    effective_date: str | None = None,
) -> dict:
    """Version 1 of the tolerance policy: today's behaviour expressed as configuration.

    The absolute tolerance is applied per line in the invoice currency; the
    policy only applies to invoices whose currency is in ``invoice_currency_scope``
    (other invoices report ``unavailable_currency`` exactly as before).
    """

    return {
        "version": 1,
        "owner": "",
        "effective_date": effective_date or utc_now()[:10],
        "absolute_tolerance": absolute_tolerance,
        "percentage_tolerance": None,
        "scope": "per_line",
        "invoice_currency_scope": list(DEFAULT_INVOICE_CURRENCY_SCOPE),
    }


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
            rms_cost_currency TEXT,
            rms_unit_cost_converted TEXT,
            conversion_rate_id INTEGER,
            target_cost_comparison_reason TEXT,
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
            updated_at TEXT NOT NULL,
            cost_currency TEXT,
            import_id TEXT
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
            updated_at TEXT NOT NULL,
            tolerance_policy_json TEXT
        );

        CREATE TABLE IF NOT EXISTS policy_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_name TEXT NOT NULL,
            actor TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            settings_version INTEGER,
            before_json TEXT,
            after_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_policy_audit_name ON policy_audit(policy_name, id DESC);

        CREATE TABLE IF NOT EXISTS catalog_imports (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            imported_rows INTEGER NOT NULL DEFAULT 0,
            skipped_rows INTEGER NOT NULL DEFAULT 0,
            cost_currency TEXT,
            cost_currency_source TEXT,
            declared_by TEXT,
            declared_at TEXT,
            content_sha256 TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_imports_time ON catalog_imports(imported_at DESC);

        CREATE TABLE IF NOT EXISTS conversion_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_currency TEXT NOT NULL,
            to_currency TEXT NOT NULL,
            rate TEXT NOT NULL,
            source TEXT NOT NULL,
            entered_by TEXT NOT NULL,
            entered_at TEXT NOT NULL,
            effective_date TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_conversion_rates_pair
            ON conversion_rates(from_currency, to_currency, effective_date DESC, id DESC);
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
                "rms_cost_currency": "TEXT",
                "rms_unit_cost_converted": "TEXT",
                "conversion_rate_id": "INTEGER",
                "target_cost_comparison_reason": "TEXT",
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
            if "tolerance_policy_json" not in settings_columns:
                conn.execute("ALTER TABLE app_settings ADD COLUMN tolerance_policy_json TEXT")
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
                            "maximum_absolute_difference_aed": DEFAULT_ABSOLUTE_TOLERANCE,
                        }
                    ),
                    utc_now(),
                ),
            )
            self._migrate_tolerance_policy(conn)
            self._migrate_catalog_imports(conn)

    @staticmethod
    def _migrate_tolerance_policy(conn: sqlite3.Connection) -> None:
        """Express an existing bare tolerance as policy version 1, once.

        The absolute value is carried over unchanged, so a workspace behaves
        exactly as before until an operator edits the policy.  The migration
        itself is recorded in policy_audit with a system actor.
        """

        row = conn.execute(
            "SELECT version,updated_at,target_cost_policy_json,tolerance_policy_json "
            "FROM app_settings WHERE id = 1"
        ).fetchone()
        if row is None or row["tolerance_policy_json"]:
            return
        try:
            legacy = json.loads(row["target_cost_policy_json"] or "{}")
        except (TypeError, ValueError):
            legacy = {}
        absolute = legacy.get("maximum_absolute_difference_aed") if isinstance(legacy, dict) else None
        if not isinstance(absolute, (int, float)) or isinstance(absolute, bool) or absolute < 0:
            absolute = DEFAULT_ABSOLUTE_TOLERANCE
        policy = default_tolerance_policy(
            absolute, effective_date=str(row["updated_at"] or "")[:10] or None
        )
        now = utc_now()
        conn.execute(
            "UPDATE app_settings SET tolerance_policy_json = ? WHERE id = 1",
            (json_dumps(policy),),
        )
        conn.execute(
            """
            INSERT INTO policy_audit
                (policy_name,actor,changed_at,settings_version,before_json,after_json)
            VALUES ('tolerance_policy','system:migration',?,?,NULL,?)
            """,
            (now, row["version"], json_dumps(policy)),
        )

    @staticmethod
    def _migrate_catalog_imports(conn: sqlite3.Connection) -> None:
        """Attach catalog rows imported before cost currency was recorded to one
        'legacy' import record whose cost currency is undeclared (never guessed)."""

        catalog_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(catalog_items)").fetchall()
        }
        if "cost_currency" not in catalog_columns:
            conn.execute("ALTER TABLE catalog_items ADD COLUMN cost_currency TEXT")
        if "import_id" not in catalog_columns:
            conn.execute("ALTER TABLE catalog_items ADD COLUMN import_id TEXT")
        orphaned = conn.execute(
            "SELECT COUNT(*), MIN(created_at), MAX(source_name) FROM catalog_items "
            "WHERE import_id IS NULL"
        ).fetchone()
        if not orphaned or not orphaned[0]:
            return
        conn.execute(
            """
            INSERT OR IGNORE INTO catalog_imports
                (id,filename,imported_at,imported_rows,skipped_rows,cost_currency,
                 cost_currency_source,declared_by,declared_at,content_sha256)
            VALUES (?,?,?,?,0,NULL,NULL,NULL,NULL,NULL)
            """,
            (
                LEGACY_CATALOG_IMPORT_ID,
                orphaned[2] or "imported before cost currency was recorded",
                orphaned[1] or utc_now(),
                orphaned[0],
            ),
        )
        conn.execute(
            "UPDATE catalog_items SET import_id = ? WHERE import_id IS NULL",
            (LEGACY_CATALOG_IMPORT_ID,),
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_catalog_import ON catalog_items(import_id)"
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
