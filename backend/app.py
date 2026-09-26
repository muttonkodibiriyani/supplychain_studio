from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .service import (
    Conflict,
    DemoSeedRefused,
    InvoiceService,
    NotFound,
    Settings,
    UploadRejected,
    ValidationFailure,
)


class LineUpdate(BaseModel):
    id: str | None = None
    description: str | None = None
    quantity: float | int | str | None = None
    unit_price: float | int | str | None = None
    line_total: float | int | str | None = None
    tax_rate: float | int | str | None = None
    uom: str | None = None
    upc: str | None = None
    catalog_item_id: str | None = None
    rms_item_id: str | None = None
    match_status: str | None = None
    confidence: float | int | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class InvoiceUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    supplier_id: str | None = None
    supplier_name: str | None = None
    supplier_site: str | None = None
    invoice_number: str | None = None
    document_type: str | None = None
    document: str | None = None
    invoice_date: str | None = None
    po_number: str | None = None
    currency: str | None = None
    location: str | None = None
    location_type: str | None = None
    tax_code: str | None = None
    ref_no_1: str | None = None
    ref_no_2: str | None = None
    ref_no_3: str | None = None
    comment: str | None = None
    subtotal: float | int | str | None = None
    tax_total: float | int | str | None = None
    total: float | int | str | None = None
    lines: list[LineUpdate] | None = None


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class RematchRequest(VersionRequest):
    """``actor`` is recorded on the audit event as given: ``user`` (default,
    a person in the review screen) or ``system`` (an automated caller)."""

    actor: Literal["user", "system"] = "user"


class ApprovalRequest(VersionRequest):
    acknowledge_target_cost_variance: bool = False


class SupplierRule(BaseModel):
    supplier_id: str
    supplier_site: str
    tax_code: str


class TargetCostPolicy(BaseModel):
    mode: str = "invoice_only"
    maximum_absolute_difference_aed: float | int | str = 10


class BrandSettingsUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    brand_label: str = ""
    location: str = ""
    location_type: str = ""
    supplier_rules: list[SupplierRule] = Field(default_factory=list)
    include_upc_in_export: bool = False
    # Legacy shape: edits only the absolute tolerance of the versioned policy.
    target_cost_policy: TargetCostPolicy | None = None
    # Versioned policy (MAT-02 / POL-01). When present it takes precedence.
    tolerance_policy: dict[str, Any] | None = None
    changed_by: str = ""


class ConversionRateCreate(BaseModel):
    from_currency: str
    to_currency: str
    rate: float | int | str
    source: str
    entered_by: str
    effective_date: str | None = None


class CatalogImportCurrency(BaseModel):
    cost_currency: str
    declared_by: str


class ExportRequest(BaseModel):
    invoice_ids: list[str] = Field(min_length=1, max_length=5000)


def create_app(settings: Settings | None = None) -> FastAPI:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    service = InvoiceService(settings or Settings.from_env())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.start()
        try:
            yield
        finally:
            service.stop()

    app = FastAPI(
        title="Invoice Flow 5 Review API",
        version="1.0.0",
        description="Durable invoice capture, RMS matching review, approval, and controlled export.",
        lifespan=lifespan,
    )
    app.state.invoice_service = service

    @app.exception_handler(NotFound)
    async def not_found_handler(_: Request, error: NotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(Conflict)
    async def conflict_handler(_: Request, error: Conflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {"message": str(error), "current_version": error.current_version}
            },
        )

    @app.exception_handler(ValidationFailure)
    async def validation_handler(_: Request, error: ValidationFailure) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": {"errors": error.errors}})

    @app.exception_handler(UploadRejected)
    async def upload_handler(_: Request, error: UploadRejected) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(DemoSeedRefused)
    async def demo_seed_refused_handler(_: Request, error: DemoSeedRefused) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "message": str(error),
                    "non_demo_catalog_rows": error.non_demo_catalog_rows,
                    "non_demo_invoices": error.non_demo_invoices,
                }
            },
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        workers = service.worker_status()
        return {
            "status": "degraded" if workers["problems"] else "ok",
            "problems": workers["problems"],
            "ocr_available": service.ocr_available(),
            "supported_formats": service.supported_formats,
            "workers": workers,
        }

    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        return service.stats()

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return service.get_settings()

    @app.put("/api/settings")
    def put_settings(update: BrandSettingsUpdate) -> dict[str, Any]:
        payload = update.model_dump()
        expected_version = payload.pop("expected_version")
        return service.update_settings(expected_version, payload)

    @app.get("/api/settings/audit")
    def settings_audit(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
        return service.list_policy_audit(limit=limit)

    @app.get("/api/rates")
    def rates() -> dict[str, Any]:
        return service.list_conversion_rates()

    @app.post("/api/rates")
    def add_rate(rate: ConversionRateCreate) -> dict[str, Any]:
        return service.add_conversion_rate(rate.model_dump())

    @app.get("/api/invoices")
    def invoices(
        status: str | None = None,
        search: str | None = None,
        limit: int = Query(default=25, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return service.list_invoices(status=status, search=search, limit=limit, offset=offset)

    @app.post("/api/invoices/upload")
    async def upload_invoices(
        files: list[UploadFile] = File(...),
        supplier_id: str | None = Form(default=None),
        supplier_name: str | None = Form(default=None),
    ) -> dict[str, list[dict[str, Any]]]:
        if len(files) > service.settings.max_upload_files:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"maximum {service.settings.max_upload_files} files per request"
                },
            )
        result: dict[str, list[dict[str, Any]]] = {
            "accepted": [],
            "duplicates": [],
            "rejected": [],
        }
        for upload in files:
            try:
                item, duplicate = await service.ingest_upload(
                    upload,
                    supplier_id=(supplier_id or "").strip() or None,
                    supplier_name=(supplier_name or "").strip() or None,
                )
                if duplicate:
                    item.pop("status", None)
                result["duplicates" if duplicate else "accepted"].append(item)
            except UploadRejected as error:
                result["rejected"].append(
                    {"filename": upload.filename or "upload", "error": str(error)}
                )
            finally:
                await upload.close()
        return result

    @app.get("/api/invoices/{invoice_id}")
    def invoice(invoice_id: str) -> dict[str, Any]:
        return service.get_invoice(invoice_id)

    @app.get("/api/invoices/{invoice_id}/source")
    def invoice_source(invoice_id: str) -> FileResponse:
        path, filename, media_type = service.source_for(invoice_id)
        return FileResponse(
            path,
            filename=filename,
            media_type=media_type or "application/octet-stream",
            content_disposition_type="inline",
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox; default-src 'none'",
            },
        )

    @app.put("/api/invoices/{invoice_id}")
    def update_invoice(invoice_id: str, update: InvoiceUpdate) -> dict[str, Any]:
        payload = update.model_dump(exclude_unset=True)
        expected_version = payload.pop("expected_version")
        if payload.get("lines") is not None:
            payload["lines"] = [line.model_dump(exclude_unset=True) for line in update.lines or []]
        return service.update_invoice(invoice_id, expected_version, payload)

    @app.post("/api/invoices/{invoice_id}/approve")
    def approve_invoice(invoice_id: str, request: ApprovalRequest) -> dict[str, Any]:
        return service.approve(
            invoice_id,
            request.expected_version,
            acknowledge_target_cost_variance=request.acknowledge_target_cost_variance,
        )

    @app.post("/api/invoices/{invoice_id}/rematch")
    def rematch_invoice(invoice_id: str, request: RematchRequest) -> dict[str, Any]:
        return service.rematch(invoice_id, request.expected_version, actor=request.actor)

    @app.post("/api/invoices/{invoice_id}/retry")
    def retry_invoice(invoice_id: str) -> dict[str, Any]:
        return service.retry(invoice_id)

    @app.get("/api/invoices/{invoice_id}/audit")
    def invoice_audit(invoice_id: str) -> dict[str, Any]:
        return service.audit(invoice_id)

    @app.get("/api/catalog")
    def catalog(
        search: str | None = None,
        supplier_id: str | None = None,
        limit: int = Query(default=20, ge=1, le=200),
    ) -> dict[str, Any]:
        return service.list_catalog(search=search, supplier_id=supplier_id, limit=limit)

    @app.post("/api/catalog/import")
    async def import_catalog(
        file: UploadFile = File(...),
        cost_currency: str | None = Form(default=None),
        declared_by: str | None = Form(default=None),
    ) -> dict[str, Any]:
        content = await file.read(service.settings.max_catalog_file_bytes + 1)
        await file.close()
        # A large master takes minutes to parse. Running it on the event loop
        # freezes every other request (health, stats, uploads) for that long.
        declaration: dict[str, str] = {}
        if cost_currency:
            declaration["cost_currency"] = cost_currency
        if declared_by:
            declaration["declared_by"] = declared_by
        counts = await run_in_threadpool(
            lambda: service.import_catalog(file.filename or "catalog", content, **declaration)
        )
        return {**counts, "import": service.latest_catalog_import()}

    @app.get("/api/catalog/imports")
    def catalog_imports() -> dict[str, Any]:
        return service.list_catalog_imports()

    @app.put("/api/catalog/imports/{import_id}")
    def declare_catalog_import_currency(
        import_id: str, body: CatalogImportCurrency
    ) -> dict[str, Any]:
        return service.declare_catalog_import_currency(
            import_id, body.cost_currency, body.declared_by
        )

    @app.get("/api/aliases")
    def aliases() -> dict[str, Any]:
        return service.list_aliases()

    @app.post("/api/aliases/import")
    async def import_aliases(file: UploadFile = File(...)) -> dict[str, Any]:
        content = await file.read(5 * 1024 * 1024 + 1)
        await file.close()
        return await run_in_threadpool(
            service.import_aliases, file.filename or "aliases.json", content
        )

    @app.post("/api/exports")
    def export_invoices(request: ExportRequest) -> FileResponse:
        result = service.create_export(request.invoice_ids)
        return FileResponse(
            result["path"],
            filename=result["filename"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "X-Export-Id": result["id"],
                "X-Export-Schema": result["schema_name"],
                "X-Content-SHA256": result["sha256"],
            },
        )

    @app.get("/api/exports")
    def exports() -> dict[str, Any]:
        return service.list_exports()

    @app.get("/api/reports/exceptions.csv")
    def exception_report() -> Response:
        report = service.create_exception_report()
        return Response(
            content=report["content"],
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{report["filename"]}"',
                "X-Exception-Count": str(report["count"]),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/api/demo")
    def demo() -> Any:
        if not service.settings.enable_demo_seed:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "demo seeding is disabled; set INVOICE_ENABLE_DEMO_SEED=true "
                    "on a demo-only workspace to enable POST /api/demo"
                },
            )
        return service.seed_demo()

    project_root = Path(__file__).resolve().parents[1]
    frontend_dist = next(
        (candidate for candidate in (project_root / "frontend" / "dist", project_root / "dist") if candidate.is_dir()),
        None,
    )
    if frontend_dist is not None:
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()
