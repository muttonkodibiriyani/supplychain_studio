# Invoice Studio

Run a local invoice workspace for a brand: import its RMS item master, upload supplier invoices, review extracted lines and item matches, then export one consolidated Excel workbook. Reuse the application for another brand with a separate data volume and its own master and settings.

Source: [muttonkodibiriyani/supplychain_studio](https://github.com/muttonkodibiriyani/supplychain_studio). Sign in to an account with repository access, then choose **Code → Download ZIP**.

## Start on a new Windows computer

Follow [Windows setup from zero](docs/WINDOWS_SETUP.md) for Windows, WSL 2, Docker Desktop, download, first launch, backups and troubleshooting. You do not need to install Python, Node or an AI API key on Windows when using Docker.

After Docker Desktop is running and you have extracted the source, open PowerShell in the application folder:

```powershell
Copy-Item .env.example .env
docker compose --project-name invoice-studio up --build --detach
```

Open **http://localhost:8000**. Keep the same project name on later starts so you reconnect to the same stored invoices and mappings. The optional `Start-InvoiceStudio.ps1` helper checks Docker and starts this workflow.

## First brand and daily operation

The [operator training guide](docs/OPERATOR_TRAINING.md) walks through setup, review, corrections, exceptions and export.

1. Open **Brand setup**. Enter the brand name, location and location type, then the correct supplier-site and tax-code rules. Codes are text so leading zeroes survive. No customer codes are invented.
   Keep **Include UPC in target workbook** off unless your receiving system has verified populated UPCs; internal barcode matching is independent of this setting.

2. Import the brand's RMS XLSX extract or normalized CSV/XLSX item master. The original wide RMS format is supported; the catalog has a separate 128 MiB upload limit. Check the imported count and sample supplier/item/UPC rows.
3. Optionally import a private JSON file of reviewed supplier mappings in **Learned matches**. These mappings are not bundled with the source.
4. Upload invoice files or a folder. The browser limits concurrent uploads; accepted documents enter a durable queue. One invoice per file, with multiple pages supported.
5. Compare the source against captured header, quantities, net prices, tax and totals. Confirm document type, supplier, target codes and every item mapping. Missing or uncertain rows require correction; an invoice is not partially exported.
6. Use **Download exceptions** to save the excluded-document list and review reasons separately from the target workbook. Approve reviewed invoices, select them and download the consolidated workbook. Use **Select all approved matching search** for batches across pages (maximum 5,000 invoices per export). Check the receiving system's import result before treating the handoff as accepted.

If uploads sit in **Queued** with nothing in **Processing**, open `http://localhost:8000/api/health`. It reports `"status": "degraded"` with a `problems` list when fewer extraction workers than configured are alive or when the queue has had no worker activity for two minutes (`INVOICE_WORKER_STALL_SECONDS`). The `workers` block shows configured/alive counts, the last error and the last claim time. Dead workers are respawned automatically on the next health check; the log line `extraction worker error` names the cause.

The target contains **exactly `Header`, `Tax_Breakdown`, and `Details`**, joined by Transaction Number. It excludes unapproved invoices and documents classified as credit notes, purchase orders, delivery notes or unknown. The application generates the file; it does not submit it, confirm a GRN or release payment.

The current conservative pricing policy, pending commercial signoff, uses invoice net unit costs after discount for target detail prices. RMS costs are comparison evidence, not replacement prices. Differences above the configured AED threshold require review, and details must reconcile with the invoice's ex-tax total. No foreign-exchange rate is invented for cross-currency comparisons.

## What “learning” means here

Confirmed supplier/item mappings are reused within this brand's workspace. Extraction adapters support common text and table layouts and use local OCR for scans. This is application adaptation and remembered corrections, not model fine-tuning. A new brand or unfamiliar invoice layout still needs validation. No claim of universal layout support or 98% accuracy is made.

Current release checks are in [RELEASE_VALIDATION.md](docs/RELEASE_VALIDATION.md). The current real-corpus evaluation and limitations are documented in [REAL_CORPUS_EVALUATION.md](docs/REAL_CORPUS_EVALUATION.md); release acceptance is tracked in [IMPLEMENTATION_ACCEPTANCE.md](docs/IMPLEMENTATION_ACCEPTANCE.md). Historical synthetic volume results in [VOLUME_RESULTS.md](docs/VOLUME_RESULTS.md) measure queue durability, not real invoice accuracy.

## Inputs and limits

| Input | Capture method |
| --- | --- |
| PDF | Embedded text and tables; OCR for scanned pages |
| PNG, JPG/JPEG, TIFF, BMP, WebP | Local Tesseract OCR |
| CSV, XLSX | Structured invoice fields and lines |
| DOCX, TXT | Text/table extraction |

The supplied Compose configuration permits **64 MiB per invoice file**, with page/frame and decompression limits. The browser sends files individually, so a selection can exceed 1,000 files. Two processing workers are configured by default. Corrupt, encrypted, empty, unsupported and oversized files produce explicit errors. ZIP archives, HEIC, legacy XLS/DOC, HTML and SVG are not invoice inputs.

## Separate brands and persistent data

Use a fixed Compose project name and a different host port for each brand, as shown in the Windows guide. Each project gets its own database, originals, exports, settings and learned mappings. This is a local per-brand deployment, not a shared multi-tenant service.

```powershell
docker compose --project-name invoice-studio logs --tail 100 invoice-review
docker compose --project-name invoice-studio restart invoice-review
docker compose --project-name invoice-studio down
```

`down` preserves the named data volume; adding `--volumes` deletes it. Back up before updates. Run one API process per data directory. Accepted work survives browser closure, duplicate file bytes return the existing record, and interrupted jobs return to the queue after restart.

The service binds to loopback and has no application login or individual user roles. Shared production deployment requires access controls, retention and operational ownership. Local audit events are not verified user identities.

## Development

For a host development environment, install Python 3.12, Node 22.12+, Tesseract and its English language data:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
npm ci
npm run build
.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

For UI development run `npm run dev`; Vite proxies `/api`. API documentation is at `/docs`.

```bash
python3 -m pytest -q
npm run build
npx playwright install chromium
npm run test:ui
```

Set `LIVE_URL=http://localhost:8000` to run the browser workflow against a disposable server; it writes synthetic data. `scripts/verify_volume.py` checks HTTP ingestion and recovery. `scripts/evaluate_corpus.py` evaluates a private corpus without putting the source documents in the repository. Read each command's `--help` before running it.

The labelled static preview uses fictional browser-local data. Real OCR, persistent processing and XLSX exports require the full application. Server outages do not silently switch real records to samples.

## Source distribution

The source package and GitHub repository contain code, documentation and synthetic examples. Real invoices, item masters, learned mappings, local databases and credentials remain private. The package builder uses an explicit file selection rather than copying the working directory. Open-source component notes are in [OPEN_SOURCE.md](docs/OPEN_SOURCE.md).
