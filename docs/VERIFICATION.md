# Verification record

> Historical pilot record (24 September 2026). For the current exact-target and real-corpus release, see [IMPLEMENTATION_ACCEPTANCE.md](IMPLEMENTATION_ACCEPTANCE.md), [REAL_CORPUS_EVALUATION.md](REAL_CORPUS_EVALUATION.md), and [OPERATOR_TRAINING.md](OPERATOR_TRAINING.md). Statements about the earlier internal-review schema describe that earlier build.


**Status:** bounded technical acceptance completed on 24 September 2026. This record distinguishes executed checks from planned or business acceptance work. A requirement or test procedure is not evidence that the behavior passed. Final archive/image publication occurs after this record is frozen and is reported in the delivery task receipt rather than retroactively counted here.

## Evidence rules

- Record the exact command, environment, fixture counts, elapsed time and observed result for every executed check.
- Preserve failure messages and limitations; do not convert a partial or mocked path into a pass.
- Treat OCR extraction, field parsing and RMS item matching as separate measurements.
- Do not claim the PRD's 98% auto-resolution target without a labelled, held-out supplier corpus. No such corpus has been supplied.
- Call generated header/tax/detail files the **internal review schema** until the REIM owner supplies and accepts the exact import contract.
- A static preview demonstrates interaction design only. Persistence, native OCR, restart recovery and bulk throughput require the running service and its retained data volume.

## Execution environment

The verifier fixture self-test ran on Linux 6.8.0-87-generic x86_64 with 4 logical CPUs, 8,131,816 KiB reported memory, Python 3.12.3, Requests 2.31.0 and Pillow 12.3.0. Container/runtime details will be recorded separately with the application checks.

## Executed checks

### Verifier fixture self-test — passed

```bash
python3 scripts/verify_volume.py --fixture-self-test --count 1000
```

Executed on 24 September 2026. The verifier generated 1,000 distinct valid text-layer PDF byte streams (1,000 distinct SHA-256 values, 935,000 bytes total) plus one PNG and one image-only PDF OCR fixture. Each random OCR token was absent from its file bytes. Fixture generation and checks completed in 0.300 seconds.

This result validates the test inputs only. It does **not** exercise upload, persistence, extraction, OCR, matching or export behavior and therefore does not mark an application acceptance row as passed.

### Local extraction and matching unit suite — passed with two dependency skips

```bash
python3 -m unittest discover -s tests -v
```

Executed on the same host. All 31 discovered tests completed in 0.391 seconds: 29 passed and 2 native-OCR tests were skipped because this host lacks the Tesseract executable and `pypdfium2`. Covered cases include embedded-PDF text, CSV/XLSX extraction, explicit corrupt/encrypted/oversized failures, ambiguity withholding, exact/fuzzy/ambiguous matching, supplier isolation, size/pack/shade/UOM conflicts, and UOM-scoped aliases. Native OCR remains unverified by this command and is tracked separately below.

`python3 -m pytest -q` was also attempted on the host but could not start because its system Python does not have pytest installed. The Docker runtime declares pytest; the container test receipt will be recorded independently rather than treating this environment issue as an application failure.

### Full suite in the application runtime — passed

```bash
docker run --rm --user 0:0 \
  -v WORKSPACE:/src:ro \
  -w /src invoice-studio-review:coordinator \
  python -m pytest -q -p no:cacheprovider
```

Executed on 24 September 2026 against the current source mounted read-only with the built Debian/Python 3.12 application image's dependencies, Tesseract 5.5 and `pypdfium2`. All **42 tests passed in 36.04 seconds**. One non-failing Starlette deprecation warning said its `TestClient` integration will move from `httpx` to `httpx2`. The run included two real native-OCR cases (PNG and multipage scanned PDF), not a mocked OCR result, as well as 1,000 distinct durable service jobs, interrupted-processing recovery at service start, duplicate pagination, approval/export gates, decimal reconciliation, formula-leading spreadsheet text, supplier/UOM alias isolation, and extraction/matching cases.

The first attempt found a test-harness error after 40 passes: the HTTP route-contract test read `.methods` from the frontend `Mount`, which does not expose that attribute. The test was corrected to use `getattr`; the 42-test result above is the clean rerun. This was a test defect, not an API failure.

### First black-box volume/recovery attempt — bulk passed; forced-crash OCR failed

The independent verifier's first application run accepted and reconciled all 1,000 distinct text-layer PDFs over the HTTP API: 50 successful batches, 935,000 bytes, 9.504 seconds to upload (105.214 documents/second in this synthetic test), 4.643 seconds to terminal state, all 1,000 in `needs_review`. Client concurrency peaked at the configured eight requests; server processing peaked at its configured two workers; the largest sampled queued count was 254. This is a synthetic local-host measurement, not a production throughput forecast or a demonstrated queue-capacity limit.

The same run then deliberately sent `SIGKILL` while two of six raster-PDF jobs were processing and four were queued. After restart, two reached `needs_review` and four ended `failed` with the exact error `ExtractionLimitError: OCR page exceeded its 45 second limit.` The verifier correctly exited non-zero after 119.897 seconds. Receipt: `/tmp/invoice-studio-volume-result-final.json` (failed run; receipt SHA-256 `114ddfbaf6494ed444a0433be561dd56b9a1d3b1653e85a1469eea15951e664d`; tested image `sha256:82c0be7f1796889dbce780a67c2e00a86f8e0be551d50d12b58683566a60ced4`).

Investigation reproduced the cause in the delivered Tesseract 5.5 environment: grayscale mode-L staging PNGs took roughly 30–45 seconds, while an equivalent RGB-encoded staging PNG completed in about 1.5 seconds. The extraction path now writes RGB staging images, has a regression test, and the container bounds OpenMP threads. A clean-image black-box rerun was therefore required; its passing result follows. The failed receipt remains part of the record.

### Fixed-image native OCR smoke — passed

The corrected Debian/Tesseract 5.5 image passed all 17 extraction tests. A two-worker HTTP smoke then processed a PNG invoice in 1.228 seconds as `image_ocr` and a scanned PDF in 1.436 seconds as `pdf_ocr`. Both finished in `needs_review`, each extracted one line, matched that line to the supplied RMS item and returned the expected AED 21 total; neither failed. This small controlled smoke demonstrates the corrected code path, not general OCR accuracy.

### Fixed-image black-box volume, crash recovery and persistence — passed

```bash
/usr/bin/python3 -B \
  WORKSPACE/scripts/verify_volume.py \
  --base-url http://127.0.0.1:8765 \
  --count 1000 --batch-size 20 --concurrency 8 --expected-workers 2 \
  --processing-timeout 600 --health-timeout 120 \
  --crash-stop-command 'docker kill --signal KILL invoice-studio-volume-verify' \
  --crash-start-command 'docker start invoice-studio-volume-verify' \
  --recovery-count 6 \
  --restart-command 'docker restart invoice-studio-volume-verify' \
  --tested-container invoice-studio-volume-verify \
  --result-json /tmp/invoice-studio-volume-result-rgb.json
```

Executed on 24 September 2026 on the four-CPU, 8,131,816-KiB Linux host described above. The tested container ran as user `invoice` with a read-only root filesystem, a fresh temporary data bind and two workers on `linux/amd64`. Immutable image ID: `sha256:5f02028a5a385dcc7e16b68bff96551f0fdfa9626eee540d3e7ea904d9ba8e33`; image size: 125,213,722 bytes; image created: `2026-09-24T12:29:27.815716421Z`.

The verifier passed without recorded failures in **27.709 seconds**:

- Generated and uploaded 1,000 distinct valid text-layer PDFs (935,000 bytes) in 50 successful HTTP 200 batches. Upload took 8.054 seconds (124.166 documents/second on this local synthetic workload); terminal reconciliation took 3.041 seconds; all 1,000 unique IDs and filenames ended in `needs_review`.
- Observed at most eight client requests, exactly the configured bound, and at most two processing jobs, exactly the worker bound. The largest sampled queued count was 191. No server backlog capacity was exposed, so 191 is an observation rather than proof of a configured queue limit.
- Uploaded six pixel-only scanned PDFs, observed two `processing` and four `queued`, sent `SIGKILL`, restarted the same container, and saw all six finish in `needs_review` in 3.520 seconds. The two interrupted IDs each had a `processing_recovered` audit event. Every per-file random token was absent from source bytes and present in API detail after recovery.
- Verified independent pixel-only PNG and scanned-PDF OCR in 1.383 seconds. Both random tokens were absent from the source bytes and present in API detail, with reported methods `image_ocr` and `pdf_ocr`.
- Re-uploaded identical bytes under the same and a different filename. Both HTTP responses explicitly returned the original ID under `duplicates`; the count stayed 1,006.
- Empty PDF and unsupported EXE inputs were synchronously rejected in the HTTP 200 per-file envelope with explicit reasons and no records. A corrupt supported PDF became one durable `failed` record with `DocumentExtractionError: The PDF is corrupt or unreadable: startxref not found`; other work remained successful.
- Restarted the healthy service after terminal processing, retained all 1,009 distinct record IDs, re-downloaded both OCR sources with identical SHA-256 values, and retained both OCR tokens. Final state was 1,008 `needs_review`, one deliberately corrupt `failed`, and no queued or processing records.

Machine receipt: `/tmp/invoice-studio-volume-result-rgb.json`, SHA-256 `56da7c7c40c7e98aaf63e851dd42e089ecc5ceac5bc03b87bc1a06d6079e87be`. These timings cover generated local fixtures on one machine and do not establish production throughput, arbitrary-layout accuracy or a safe maximum backlog.

### Frontend build and browser workflow — passed

```bash
npm run build
```

The production TypeScript/Vite build exited successfully after the bundled-font and live-audit corrections. Its principal generated assets were 303.72 KB of JavaScript and 47.49 KB of CSS.

```bash
docker run --rm --network host --ipc=host \
  -v WORKSPACE:/workspace \
  -w /workspace \
  -e BROWSER_EXECUTABLE=/ms-playwright/chromium-1208/chrome-linux64/chrome \
  -e BROWSER_SINGLE_PROCESS=1 \
  -e LIVE_URL=http://127.0.0.1:5173 \
  mcr.microsoft.com/playwright:v1.58.2-noble \
  npm run test:ui -- --fully-parallel --workers=3
```

The browser suite exited zero with **3/3 tests passed in 10.6 seconds**. Host Vite on port 5173 proxied `/api` to an isolated Docker test service on port 8000. The tests covered the fictional preview correction/alias/approval/export path; a 390 × 844 mobile worklist, search and honest preview-upload message with no page overflow; and a live RMS-master import → CSV invoice upload → processing → named audit events → approval → XLSX download. Screenshots `test-results/worklist-desktop.png`, `review-desktop.png` and `worklist-mobile.png` were visually inspected. Chromium's single-process setting was a host test accommodation, not application behavior.

The downloaded live workbook was independently opened with:

```python
from openpyxl import load_workbook
w = load_workbook("test-results/live-export.xlsx", read_only=True, data_only=False)
print(w.sheetnames)
for s in w:
    print(s.title, s.max_row, s.max_column)
    print(list(s.values)[:3])
```

It contained README, Header, Tax, Detail and Audit sheets: one Header data row, one Tax row, two Detail rows and one Audit row. Subtotal 1,420 plus tax 71 equalled total 1,491; line arithmetic was 10 × 78 = 780 and 10 × 64 = 640. The exported invoice recorded version 4 and approved state `ready`. This validates the internal-review workbook for one controlled fixture only; no REIM import schema or downstream acceptance was available.

The integration owner regenerates the source archive from these frozen documents, builds the archive-inclusive image and publishes the static companion as the post-record delivery step. Its archive hash, health and download checks belong in the final delivery receipt; they are not pre-claimed here.

## Acceptance ledger

| Area | Evidence required | Current result |
| --- | --- | --- |
| Build and startup | Reproducible frontend/backend or container build plus health response. | **Passed for tested components:** production frontend build and fixed read-only/non-root runtime health passed. Archive-inclusive publication is the integration owner's post-record delivery step. |
| Durable bulk intake | At least 1,000 distinct supported fixtures; reconciled accepted, queued, completed, review and failed counts; pagination and elapsed time. | **Passed:** 1,000/1,000 distinct synthetic text PDFs over HTTP on the fixed image, all `needs_review`; exact counts and timings above. |
| Native extraction | Real image, embedded-text PDF, scanned PDF and supported multipage fixture, with source-derived text/evidence and no silent truncation. | **Passed for supplied fixtures:** real PNG, scanned PDF, multipage scanned PDF and embedded-PDF paths produced source-derived evidence. This is not a layout-accuracy result. |
| Restart recovery | Queued/running work survives a service restart or becomes explicitly retryable without duplicate results. | **Passed after defect correction:** all 6/6 forced-crash OCR jobs recovered; both interrupted IDs had recovery audit events. The failed pre-fix run remains recorded above. |
| Failure isolation and retry | Corrupt/unsupported input fails with an actionable reason while other jobs proceed; retry leaves one coherent record and audit trail. | **Partial:** empty/unsupported rejection and isolated durable corrupt-PDF failure passed. The user-triggered retry endpoint was not exercised in the final HTTP run. |
| Duplicate handling | Identical bytes under the same and a different name cannot silently create duplicate export candidates. | **Passed:** same and renamed identical bytes explicitly returned the original ID without increasing the count. |
| RMS matching | Exact/alias/fuzzy/ambiguous cases, ranked suggestions, and no confident silent guess below policy. | Passed the matching suite; scores remain ranking signals, not calibrated probabilities. No real-corpus accuracy result. |
| Supplier alias isolation | A reviewed alias is reusable for the same supplier and does not leak to another supplier or incompatible unit/pack. | Passed supplier, UOM, size and pack isolation tests. |
| Explicit review gate | Unresolved or unapproved invoices cannot enter an export. | **Passed:** server-side gate/invariant tests and live edit → approve → export workflow passed. |
| Header/tax/detail consistency | All offered export representations select the same reviewed versions; decimal totals and formula-leading text remain safe. | **Passed for the internal XLSX path:** set/version, decimal, formula-safety and one downloaded workbook inspection passed. No alternate production export or REIM schema exists to compare. |
| Audit trace | Source name/description, selected RMS ID, human correction, status transitions and exported version are traceable. | **Passed for local actors:** backend version/recovery checks and the live browser assertion for named `uploaded` and `extraction_completed` events passed. Actors are not authenticated identities. |

## Business acceptance that cannot be completed from the supplied material

- The 98% auto-resolution target requires representative, labelled invoices spanning the supplier population and a current RMS item master. Report coverage and precision separately on held-out data.
- “Any supplier layout,” same-day indexing, and under-five-minute handling require a production-like invoice mix and operating trial, not a synthetic smoke test.
- REIM compatibility and successful downstream ingestion require the exact header/tax/detail specification, accepted sample files and acknowledgement/error behavior from the integration owner.
- Email/shared-folder capture and downstream settled/payment status require authenticated connector contracts and credentials that are not part of this delivery.
