# C5 delivery and acceptance

> Historical pilot record (24 September 2026). For the current exact-target and real-corpus release, see [IMPLEMENTATION_ACCEPTANCE.md](IMPLEMENTATION_ACCEPTANCE.md), [REAL_CORPUS_EVALUATION.md](REAL_CORPUS_EVALUATION.md), and [OPERATOR_TRAINING.md](OPERATOR_TRAINING.md). Statements about the earlier internal-review schema describe that earlier build.


The user's immediate priority is **C5: invoice capture and item-name matching**, with uploads of thousands of images, PDFs and other common document formats. The PRD's P5 is the separate receiving-value problem, covered by C4; this delivery must not imply that an invoice worklist prevents a GRN from being confirmed.

This build is a self-hosted first release: a React worklist with a FastAPI service, durable single-instance document jobs, local extraction, RMS item-master import, reviewable name matching, supplier-specific correction memory, and generated exports. The tm8 static artifact is a companion preview; persistent bulk processing requires the running service and its data volume.

## Delivered surfaces

- **Full service:** the repository root contains the React UI, FastAPI API, SQLite worklist, retained source/export storage, bounded worker pool, local parsers and native Tesseract OCR. `compose.yaml` mounts a named data volume and binds the application to `127.0.0.1:8000` by default.
- **Static companion preview:** fictional browser-local data demonstrates the worklist and review interaction. It cannot upload, OCR, persist server jobs or establish throughput. The preview is visibly labelled and its sample export is not a REIM file.
- **Accepted invoice files:** PDF; PNG, JPG/JPEG, TIFF, BMP and WebP; CSV and XLSX; TXT and DOCX. A PDF uses embedded text where available and OCR for image-only pages. OCR currently uses English Tesseract data. Unsupported, corrupt, encrypted or limit-exceeding files surface an explicit failure instead of partial silent success.
- **Output:** one XLSX internal-review workbook with Header, Tax, Detail and Audit sheets. It is deliberately marked as an internal schema because no accepted REIM/OmniFlow import specification was supplied.

## Run the full service

From the extracted source directory:

```bash
docker compose up --build -d
curl --fail http://127.0.0.1:8000/api/health
```

Open `http://127.0.0.1:8000`. Import a current RMS item-master CSV/XLSX before relying on match suggestions, then upload one invoice per file. The UI sends at most three file requests concurrently and leaves accepted jobs in the durable worklist if the browser closes.

Useful operating commands:

```bash
docker compose logs -f invoice-review
docker compose down
```

`docker compose down` retains the named `invoice-data` volume. Do not add `-v` unless permanent deletion of stored sources, decisions, audit history and exports is intentional. Back up the volume before upgrades; this first release does not automate backup or migration orchestration.

The supplied defaults use one API process, two extraction threads, SQLite WAL, a 25 MiB per-file limit, a 50-page/frame limit and up to 1,000 multipart files per request. Native OCR is bounded to 45 seconds per page and 180 seconds per document; a timeout becomes an explicit failed record that can be retried. Browser uploads use one file per request. Size the worker count and container memory from measured invoice pages rather than HTTP concurrency. The Compose bind is local-only and the application has no user authentication; place it behind the organisation's authenticated gateway and retention controls before any shared or real-supplier deployment.

## Scope against the PRD

| Requirement | Credible delivery boundary | Still required for full business acceptance |
| --- | --- | --- |
| FR-5.1 Capture | User-selected bulk files/folders enter a visible processing worklist. | Authenticated email/shared-folder connectors and ownership rules. |
| FR-5.2 Extract | Supported formats have real extraction paths; failures and uncertain data remain visible for review. | Representative validation across approximately 200 supplier layouts; extraction from arbitrary files is not guaranteed. |
| FR-5.3 Match | Resolve exact/known names and offer ranked candidates for uncertainty using an imported master. | Labelled, held-out supplier corpus establishing the 98% target and false-match limits. |
| FR-5.4 Learn | Persist approved supplier aliases for reuse, with safeguards against cross-supplier leakage. | Governed alias review, item-master lifecycle and measured reduction in corrections. |
| FR-5.5 Export | Generate a consistent internal header/tax/detail representation and downloadable files after review. | The actual RMS/REIM import specification, sample accepted files and downstream validation. |
| FR-5.6 Index | Persist extracted invoice number and header metadata with source evidence. | Same-day handling measured on live workload, including exceptions. |
| FR-5.7 Status | Show local queued, processing, review, ready and error states. | REIM/payment connectors before claiming received, matched, paid or settled downstream. |

## Verification matrix

This matrix defines the acceptance checks and pass conditions; it is not itself evidence. Executed results and limitations are recorded in the receipt below and in the linked verification records.

| Check | Procedure | Pass condition |
| --- | --- | --- |
| Thousands of documents | Ingest at least 1,000 distinct synthetic supported files using bounded client concurrency. Mix a few deliberate malformed/unsupported files into a separate run. | Every accepted file has one durable record; totals reconcile; worklist remains usable through pagination; each rejected/failed file has an actionable reason. Report file types, bytes, machine, workers and elapsed time. |
| Real image/PDF extraction | Upload an image invoice, a PDF with embedded text, a scanned PDF and supported multipage input. | Text comes from the document; header/line evidence is reviewable; no fabricated fallback data or silent page truncation. |
| Persistence and recovery | Restart the service with queued/running jobs and reload the browser after completed/reviewed jobs. | Retained originals, statuses and decisions survive; interrupted work resumes or exposes a retryable state without duplicate results. |
| Failure and retry | Submit corrupt content and force an extraction failure; retry a job after correcting the condition. | Other files continue; failed job has a reason; retry is bounded and leaves one coherent current record with an audit entry. |
| Duplicate prevention | Upload identical bytes again under the same and a different filename. | Duplicate handling is explicit and cannot silently double the export/payment candidate set. |
| Ambiguous names | Use equal/near-equal candidates and conflicting sizes, quantities or units. | Ambiguity remains in review with ranked suggestions; a similarity score is not labelled a calibrated probability. |
| Supplier alias isolation | Approve a mapping for supplier A; ingest the same description for A and supplier B. | A can reuse the approved mapping; B does not inherit it. A changed pack size/unit cannot silently reuse an incompatible alias. |
| Export consistency | Compare JSON/CSV or other offered outputs after review; include unresolved and failed documents. | All formats use the same eligible documents/lines; unresolved rows are blocked or clearly excluded; totals and exact decimal values agree. Include formula-leading text in spreadsheet-export tests. |
| Source/audit trace | Inspect a corrected line and an exported record. | Retain original description/source, selected RMS ID and human correction evidence; exported values can be traced to the reviewed record. |
| Format honesty | Compare UI format labels and configured limits with actual parser paths. | Every advertised format succeeds on a real fixture or gives a precise conversion/unsupported message; large/page-limited files are not silently truncated. |

## Interpreting the 98% target

The PRD calls 98% automatic item resolution an accuracy target. Track both coverage (auto-resolved lines / all eligible lines) and precision (correct auto-resolved lines / audited auto-resolved lines). A confident wrong mapping is not success. Split evaluation by supplier and document quality, separate learned aliases from novel descriptions, and use held-out invoices so a previously corrected fixture cannot masquerade as generalisation. Report manual review time independently from machine processing time. No 98% result is claimed for this delivery.

## Production gaps and next decisions

- Obtain representative invoice samples, a current RMS item master with supplier/item relationships, and the exact header/tax/detail import contract. Neither live RMS credentials nor an accepted REIM schema has been supplied.
- Add authenticated users/roles, access control, secret management, a reviewed retention policy, backup/restore and audit identity before shared production use. The PRD explicitly requires controlled access and traceable decisions.
- Move from a single host to object storage and a transactional multi-worker queue/database when operational scale or availability requires it. Benchmark the actual invoice mix before claiming a pages/hour capacity.
- Validate and tune the supplied file, page, pixel/decompression and OCR-time limits against the real workload; add operational alerts and a governed retry policy. Continue to advertise only formats with a real extraction adapter.
- Connect email/folders and ERP acknowledgement/status APIs as separate integrations. A local export is not proof that REIM accepted an invoice or that a supplier was paid.
- Keep C4 pre-GRN receiving checks as a separate business track. C5 does not amend a frozen PO or close the receiving control gap.

## Verification receipt

Independent acceptance on 24 September 2026 produced the following bounded result:

- The production frontend build passed, and 3/3 browser workflows passed in 10.6 seconds, covering fictional preview correction/approval/export, mobile search and upload honesty, plus a live RMS-master → CSV invoice → audit → approval → XLSX workflow.
- The complete Python runtime suite passed 42/42 in 36.04 seconds with native Tesseract and `pypdfium2`, including real PNG and multipage scanned-PDF OCR, conservative matching, supplier/UOM alias isolation, durable jobs, review gates, decimal checks and formula-safe export.
- The fixed-image black-box run accepted and reconciled 1,000/1,000 distinct synthetic PDFs, recovered 6/6 pixel-only OCR jobs after `SIGKILL` (including audit events for both jobs interrupted while processing), verified independent PNG/scanned-PDF OCR, handled duplicates and invalid files explicitly, and retained all 1,009 resulting IDs plus the checked OCR source bytes across restart. The run passed in 27.709 seconds on a four-CPU local host; this is synthetic functional evidence, not a production throughput forecast.
- The first forced-crash attempt is retained as failed evidence: its grayscale OCR staging caused four timeouts. The RGB staging correction was reproduced, regression-tested and passed in the final fixed-image rerun; the failure has not been erased from the record.

Exact commands, immutable image IDs, counts, timings, receipt hashes and limitations are in [`VERIFICATION.md`](VERIFICATION.md) and [`VOLUME_RESULTS.md`](VOLUME_RESULTS.md). The integration owner regenerates the downloadable archive from these frozen documents and records its final hash, image health and static-download checks in the delivery task receipt. This evidence does **not** establish the 98% business target, arbitrary supplier-layout accuracy, production readiness or REIM compatibility.
