# Invoice Studio volume verification

> Historical pilot record (24 September 2026). For the current exact-target and real-corpus release, see [IMPLEMENTATION_ACCEPTANCE.md](IMPLEMENTATION_ACCEPTANCE.md), [REAL_CORPUS_EVALUATION.md](REAL_CORPUS_EVALUATION.md), and [OPERATOR_TRAINING.md](OPERATOR_TRAINING.md). Statements about the earlier internal-review schema describe that earlier build.


This document records executed black-box HTTP evidence for bulk ingestion and
native raster OCR. Planned checks are not results, and no matching-accuracy or
REIM-compatibility claim is made here.

## Verifier

`scripts/verify_volume.py` creates at least 1,000 distinct, valid text-layer PDF
invoices, sends them through `POST /api/invoices/upload` with bounded client
concurrency, reconciles them through paginated `GET /api/invoices`, waits for
terminal extraction states, checks duplicate idempotency and invalid-file
handling, and queries `GET /api/stats`.

It also generates a PNG invoice and an image-only scanned PDF. A random token is
rendered only into each raster's pixels; the verifier asserts the token is absent
from the uploaded bytes and present in the eventual invoice-detail API response.
This is the native-OCR acceptance signal—fixture filenames and metadata do not
contain the token.

For a clean run, start the service against a temporary data directory. To test
persistence, pass an explicit restart command; after it returns, the verifier
waits for health, re-lists every invoice ID, and rechecks both OCR tokens.
Supplying paired crash commands adds a stronger check: several image-only PDFs
enter native OCR, the service is killed while jobs are visibly processing, and
the verifier requires `processing_recovered` audit events and successful
post-restart OCR tokens.

```bash
python3 scripts/verify_volume.py \
  --base-url http://127.0.0.1:8000 \
  --count 1000 \
  --batch-size 20 \
  --concurrency 8 \
  --expected-workers 2 \
  --crash-stop-command 'docker kill --signal KILL invoice-studio-volume' \
  --crash-start-command 'docker start invoice-studio-volume' \
  --restart-command 'docker restart invoice-studio-volume' \
  --tested-container invoice-studio-volume \
  --result-json /tmp/invoice-studio-volume-result.json
```

Fixture generation can be checked without a running server:

```bash
python3 scripts/verify_volume.py --fixture-self-test --count 1000
```

The verifier refuses to use a non-empty service by default, so demo data is not
silently mixed with the measurement. `--allow-existing` is available only for a
deliberate non-clean run, and counts are still reconciled against the baseline.
Client concurrency is measured against its configured bound. When
`--expected-workers` is supplied, the observed `processing` count from
`GET /api/stats` must stay within that worker bound. A server-side backlog
capacity is reported only if the API exposes one; worker-bounded execution must
not be mislabelled as proof of a capped persistent backlog.

## Executed result

**Result: passed on 2026-09-24.** The final isolated run used the replacement
RGB-OCR image and completed in 27.709 seconds. The machine-readable receipt is
`/tmp/invoice-studio-volume-result-rgb.json` (14,589 bytes, SHA-256
`56da7c7c40c7e98aaf63e851dd42e089ecc5ceac5bc03b87bc1a06d6079e87be`).

### Tested runtime

- Image: `invoice-review:test`, immutable ID
  `sha256:5f02028a5a385dcc7e16b68bff96551f0fdfa9626eee540d3e7ea904d9ba8e33`,
  created `2026-09-24T12:29:27.815716421Z`, Linux/amd64, 125,213,722 bytes.
- Container: `invoice-studio-volume-verify`, ID
  `bf94559a5b0ace30c12768fff90b9b77b9ee768da93ddfcd92388cc8ffe440ff`,
  non-root user `invoice`, read-only root filesystem, temporary host directory
  mounted at `/app/data`.
- Server: Python 3.12.14, Tesseract 5.5.0, `INVOICE_WORKERS=2`,
  `OMP_THREAD_LIMIT=1`, 1,000-file request cap, 25 MiB per-file cap, and 50-page
  document cap.
- Load client/host: Linux x86_64, 4 logical CPUs, 8,131,816 KiB RAM, Python
  3.12.3, Requests 2.31.0, Pillow 12.3.0.
- The service started with an empty `/app/data`; no demo data was read or
  modified. No other OCR batch was run concurrently.

The exact startup and verification commands were:

```bash
docker run -d \
  --name invoice-studio-volume-verify \
  --read-only \
  --tmpfs /tmp:size=256m,mode=1777 \
  --security-opt no-new-privileges:true \
  -p 127.0.0.1:8765:8000 \
  -e INVOICE_DATA_DIR=/app/data \
  -e INVOICE_WORKERS=2 \
  -e INVOICE_MAX_FILE_BYTES=26214400 \
  -e INVOICE_MAX_UPLOAD_FILES=1000 \
  -e INVOICE_MAX_PAGES=50 \
  -e OMP_THREAD_LIMIT=1 \
  -v /tmp/invoice-studio-volume.3CeYtRpU:/app/data \
  invoice-review:test

python3 -B scripts/verify_volume.py \
  --base-url http://127.0.0.1:8765 \
  --count 1000 \
  --batch-size 20 \
  --concurrency 8 \
  --expected-workers 2 \
  --processing-timeout 600 \
  --health-timeout 120 \
  --crash-stop-command 'docker kill --signal KILL invoice-studio-volume-verify' \
  --crash-start-command 'docker start invoice-studio-volume-verify' \
  --recovery-count 6 \
  --restart-command 'docker restart invoice-studio-volume-verify' \
  --tested-container invoice-studio-volume-verify \
  --result-json /tmp/invoice-studio-volume-result-rgb.json
```

### Measured results

| Check | Executed observation |
| --- | --- |
| Fixture integrity | 1,000 distinct valid PDFs, 1,000 distinct SHA-256 hashes, 935,000 total bytes. A separate fixture-only self-test also passed; its receipt is `/tmp/invoice-studio-volume-fixture-self-test.json` (SHA-256 `c388f4e49dc6872f6a1c7661264a973b7d71f2286d8604e5342075656684e36e`). |
| HTTP ingestion | 1,000/1,000 accepted in 50 multipart requests; no rejected entries, 50 HTTP 200 responses, zero retries. Upload time 8.054 s (124.166 documents/s). |
| Extraction/reconciliation | All 1,000 filenames and 1,000 distinct IDs were found through paginated `GET /api/invoices`; all reached `needs_review`. Terminal wait after upload was 3.041 s. |
| Concurrency/queue | Client requests never exceeded the configured 8. Server `processing` never exceeded 2 workers; maximum observed was 2. Maximum observed persistent `queued` count was 191 across 15 samples. |
| Abrupt recovery | Six image-only PDFs entered OCR; immediately before `SIGKILL`, exactly 2 were `processing` and 4 were `queued`. Health returned in 2.035 s; all 6 reached `needs_review` in 3.520 s, all pixel-only tokens were recovered, and both interrupted IDs had a `processing_recovered` audit event. |
| Native OCR | Pixel-only PNG reported `image_ocr`; scanned image-only PDF reported `pdf_ocr`. Both random tokens were absent from the uploaded file bytes and present in API detail. Both ended `needs_review`; joint terminal wait was 1.383 s. |
| Duplicate idempotency | Re-uploading identical bytes under both the original filename and a different filename returned the original ID in `duplicates`; count stayed 1,006. |
| Invalid files | Empty PDF and unsupported `.exe` were synchronously returned in the HTTP 200 `rejected` array and created no rows. A corrupt PDF created one durable `failed` row with `DocumentExtractionError: The PDF is corrupt or unreadable: startxref not found`. |
| Graceful restart/persistence | After `docker restart`, all 1,009 IDs remained. The two native-OCR tokens and byte-for-byte source SHA-256 hashes remained. |
| Final reconciliation | 1,009 distinct rows: 1,008 `needs_review`, one expected `failed` corrupt-PDF row, zero `queued`, zero `processing`. Health reported `ocr_available: true`. |

The 1,009 durable rows are 1,000 volume PDFs, six crash-recovery scanned PDFs,
two native-OCR fixtures, and one deliberately corrupt PDF. Empty, unsupported,
and duplicate submissions did not add rows.

The queue observation proves bounded execution at the configured two-worker
limit and bounded client pressure at eight concurrent requests. The API did not
report a persistent-backlog capacity, so this run does **not** claim that the
stored `queued` backlog itself has a fixed maximum.

### PO number to location master — added 2026-09-25

The user-supplied PO/GRN report workbook was downloaded read-only from the
user's shared drive and checked without converting or modifying the source
file. Its name, location, size, checksum and contents are private and are
deliberately not reproduced here.

The exact standalone verifier command was:

```bash
python3 -B scripts/verify_volume.py \
  --po-location-master <local copy of the workbook> \
  --po-location-master-only \
  --result-json /tmp/invoice-studio-po-location-master-result.json
```

The receipt passed in under a minute and was kept privately with its checksum.
It selected the line-level PO extract sheet and checked:

| Master check | Observed result |
| --- | --- |
| Rows and locations | Every row carrying an RMS PO had a location code. |
| Canonical RMS mapping | No `RMS_ORDER_NO` value mapped to more than one location. `RMS_ORDER_NO → LOCATION` is therefore the safe primary mapping in this snapshot. |
| Missing RMS PO | A small number of rows had no `RMS_ORDER_NO` and were excluded from the mapping. |
| External order mapping | Most `EXT_ORDER_NO` values resolved to one location; a small minority spanned several locations, and some rows had no external order number. |
| Namespace collision | A handful of tokens occurred in both the RMS and external-order columns; at least one resolved to different locations across those namespaces. |

The row, location, order-number and collision counts behind these rows are
figures about the workbook itself, not about the software, and are held in the
private acceptance channel.

Resolution rule: use `RMS_ORDER_NO` as the canonical PO key. Use
`EXT_ORDER_NO` only when it resolves to exactly one location and is not
location-ambiguous across the RMS/external namespaces. Any missing, conflicting,
or multiply mapped value requires human review; the verifier never guesses.

This was a **master-data integrity check, not an end-to-end application pass**.
The tested application currently supplies `invoice.location` from the Brand
Settings default; it has no PO/location-master import or lookup API. The item
catalog route is not a substitute: it requires an RMS item plus description,
limits input to 250,000 rows, and does not treat `RMS_ORDER_NO` as its PO alias.
Therefore the supplied workbook cannot activate PO-based location
validation in the current build. Backend/UI integration and a subsequent HTTP
acceptance test are required before the product may claim this check.

### Superseded failure evidence

The earlier official image
`sha256:82c0be7f1796889dbce780a67c2e00a86f8e0be551d50d12b58683566a60ced4`
is not the final tested image. It accepted and reconciled 1,000/1,000 PDFs, but
after the same abrupt-recovery setup only two of six raster jobs succeeded; four
failed with `ExtractionLimitError: OCR page exceeded its 45 second limit`.
That verifier run correctly exited nonzero after 119.897 seconds. Its preserved
receipt is `/tmp/invoice-studio-volume-result-final.json` (3,288 bytes, SHA-256
`114ddfbaf6494ed444a0433be561dd56b9a1d3b1653e85a1469eea15951e664d`).

The backend team reproduced the issue as Tesseract 5.5 processing mode-L PNG
staging images in tens of seconds; converting OCR staging to RGB reduced the
same class of work to under two seconds. The replacement image above includes
that fix, and the final independent run passed the previously failing crash
recovery path. These synthetic fixtures establish ingestion, recovery, and
native-OCR execution; they do not establish a production-corpus accuracy rate
or REIM compatibility.
