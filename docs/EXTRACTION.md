# Invoice extraction and RMS matching

The backend uses bounded local parsers and CPU OCR. It does not require a supplier template, a hosted AI service, or a GPU. Generic extraction is deliberately conservative: source evidence is retained, missing values stay `null`, and uncertain line matches remain for review.

## Runtime dependencies

Python packages:

- `pypdf>=6` for embedded PDF text and encryption/page checks
- `pypdfium2>=4.30` for rendering scanned PDF pages
- `Pillow>=10` for raster images and TIFF frames
- `openpyxl>=3.1` for safe, data-only XLSX reads
- `rapidfuzz>=3.9` for candidate ranking
- `python-docx>=1.1` for DOCX text and tables

The host also needs the native `tesseract` executable and English language data. OCR is invoked directly with a subprocess and TSV output; `pytesseract` is not used. Embedded-text PDFs, CSV, XLSX, TXT, and DOCX still work if Tesseract is absent. A scanned PDF or raster image fails with an actionable error rather than pretending extraction succeeded.

## Public interface

```python
from backend.extraction import ExtractionLimits, extract_document

invoice = extract_document(
    "/safe/upload/path/43c...bin",
    filename="supplier-invoice.pdf",
    limits=ExtractionLimits(),
)
```

`filename` determines the parser because upload services commonly use extensionless storage paths. Supported extensions are:

```text
.pdf .png .jpg .jpeg .tif .tiff .bmp .webp .csv .xlsx .txt .docx
```

SVG, HTML, legacy XLS, email containers, and archives supplied directly by users are rejected. Exceptions are divided into `UnsupportedDocumentError`, `ExtractionLimitError`, and `DocumentExtractionError` so a job API can report a useful per-file failure.

The successful result contains:

```json
{
  "supplier_name": "Desert Beauty Trading LLC",
  "supplier_id": "SUP-1007",
  "supplier_site": "DUBAI-01",
  "invoice_number": "DB-2026-1042",
  "invoice_date": "2026-09-24",
  "po_number": "PO-880021",
  "currency": "AED",
  "subtotal": 65.0,
  "tax_total": 3.25,
  "total": 68.25,
  "field_confidence": {"invoice_number": 0.94},
  "document_confidence": 0.924,
  "raw_text": "source text retained here",
  "extraction_method": "pdf_text",
  "pages": 1,
  "page_texts": [
    {"page": 1, "raw_text": "page evidence", "method": "pdf_text", "ocr_confidence": null}
  ],
  "warnings": [],
  "lines": [
    {
      "id": "line-...",
      "description": "Hydrating Cleanser 50ml",
      "quantity": 2.0,
      "uom": "EA",
      "unit_price": 25.0,
      "line_total": 50.0,
      "tax_rate": 5.0,
      "confidence": 0.91
    }
  ]
}
```

Extra evidence fields are safe for callers to ignore. `raw_text` and `page_texts` make every heuristic field traceable to source. OCR confidence is the weighted mean of Tesseract word confidences. Field, line, and document confidence values are extraction indicators, not calibrated probabilities.

The parser does not derive a missing total from lines, a line total from quantity and price, or an invoice total from paid/settled text. A `$` symbol does not become USD without a code. A numeric date such as `01/02/2026` stays `null` because its day/month order is ambiguous. Recognized text with no credible rows returns `lines: []` and a manual-review warning.

## PDF and image flow

For each PDF page, embedded text is tried first. A page with fewer than 30 non-whitespace characters is rasterized at 144 DPI and sent to Tesseract. The result records which method supplied every page. If any required rasterizer or OCR dependency is unavailable, the entire file fails; pages are never silently skipped.

Raster PNG, JPEG, TIFF, BMP, and WEBP files go directly through OCR. Multi-frame TIFF is treated as a multi-page document. EXIF orientation is applied before OCR. OCR currently uses English language data, and every OCR result warns that non-English text may be incomplete.

Exact default bounds from `ExtractionLimits` are:

| Bound | Default | Setting |
| --- | ---: | --- |
| Upload size | 50 MiB | `INVOICE_MAX_FILE_BYTES` (the service default is 25 MiB) |
| Pages or image frames | 50 | `INVOICE_MAX_PAGES` |
| Pixels per rasterized page | 30,000,000 | `INVOICE_MAX_PIXELS_PER_PAGE` |
| Pixels across a document | 150,000,000 | `INVOICE_MAX_TOTAL_PIXELS` |
| OCR per page | 45 seconds | not exposed |
| OCR across a document | 180 seconds | not exposed |
| Spreadsheet rows | 20,000 | not exposed |
| Spreadsheet columns | 100 | not exposed |
| ZIP members inside DOCX/XLSX | 10,000 | not exposed |
| Expanded DOCX/XLSX bytes | 100 MiB | not exposed |
| Large-member compression ratio | 200:1 | not exposed |

The pixel bounds decide how many scanned pages a document may hold, so the page bound is an upper limit, not a promise. A PDF page rasterises at 2 pixels per point (144 dpi against the page box), so an A4 page box (595 x 842 pt) costs 1190 x 1684 = 2,003,960 pixels and 50 such pages fit the document bound. Some scanners write the scan's pixel size as the page box (1 pt per pixel): a 300 dpi A4 scan stored that way is 2480 x 3508 pt, rasterises at 4960 x 7016 = 34,799,360 pixels and exceeds the per-page bound; its 200 dpi equivalent (1654 x 2339 pt, 15,474,824 pixels) passes, and nine such pages fit the document bound. An image upload counts its own pixels: A4 at 300 dpi (2480 x 3508 = 8,699,840) allows 17 pages within the document bound, at 400 dpi (3307 x 4677 = 15,466,839) 9 pages, at 500 dpi (4134 x 5846 = 24,167,364) 6 pages, and at 600 dpi (4961 x 7016 = 34,806,376) a single page fails. Raise `INVOICE_MAX_PIXELS_PER_PAGE` and `INVOICE_MAX_TOTAL_PIXELS` together with the memory available to the OCR workers: the rendered RGB page alone is 3 bytes per pixel, and OCR holds a grayscale copy beside it.

Crossing a bound rejects the file. There is no partial-page or partial-row success. DOCX and XLSX ZIP containers are checked before their parsers run. XLSX formulas are never executed (`data_only=True`, external links disabled). Encrypted and corrupt PDFs return explicit errors.

Two kinds of bound fail a document. A content bound (upload size, pages, pixels, rows, columns, archive members) describes the document itself, so the failure is final: the job records it as `ExtractionLimitError` and does not retry it. The OCR time budgets bound the host's work, not the document: the same scan can clear them on a quiet machine and miss them on a busy one. A missed time budget therefore fails as `ExtractionTimeBudgetError`, whose message ends "try again when the host is quieter", and the job treats it like any transient error: it is re-queued automatically with back-off up to `INVOICE_MAX_ATTEMPTS` (default 3), and after that an operator can re-queue it with `POST /api/invoices/{id}/retry`. Neither budget moves; only the classification does.

For thousands of uploads, the job service should store files first, queue one job per file, and run a bounded worker pool. Tesseract and PDF rendering are CPU and memory intensive, so worker concurrency should be sized from measured page latency and resident memory rather than the HTTP request count. The extractor itself has no shared mutable state and can run in separate worker processes.

## Structured files

CSV and XLSX accept common columns including:

```text
invoice_number invoice_date supplier_name supplier_id supplier_site po_number currency
description quantity uom unit_price line_total tax_rate subtotal tax_total total
```

Common spelling variants such as `invoice_no`, `vendor_name`, `qty`, `unit_cost`, and `vat_total` are normalized. One invoice per file is mandatory. Conflicting invoice number, supplier identity, or invoice date values reject the file instead of merging records. An XLSX workbook with multiple non-empty sheets is likewise rejected so sheet boundaries cannot silently combine invoices.

## RMS matching

```python
from backend.matching import enrich_invoice, match_lines, suggest_matches

matched_invoice = enrich_invoice(invoice, catalog, aliases, supplier_id="SUP-1007")
```

Catalog records use `rms_item_id`, `description`, optional `supplier_id`, `uom`, and optional `unit_cost`. Supplier-specific catalog entries are visible only to that supplier; entries without a supplier are global. A line that already carries an RMS ID is `confirmed` only after that ID is found in the eligible catalog.

Alias records use `supplier_id`, `description`, `rms_item_id`, and optional `uom`. Supplier scope is mandatory. UOM-scoped aliases require the invoice line to contain the same normalized UOM. The same supplier wording may map to different RMS items for `EA` and `PACK`; a missing or different line UOM does not activate either alias.

Each enriched line has `match_status` (`unmatched`, `suggested`, `auto`, or `confirmed`), a 0–100 `confidence`, nullable `rms_item_id`, and up to five candidates. Candidate scores are ranking scores, not probabilities.

Automatic matches are limited to:

- a supplied RMS ID validated against the supplier-eligible catalog;
- a supplier-scoped approved alias with compatible UOM and product attributes;
- one unique exact normalized description with no explicit attribute conflict;
- a fuzzy score of at least 96, at least an 8-point lead over the next candidate, and no missing or conflicting size, pack, shade, or UOM evidence.

Normalization handles case, punctuation, accents, common abbreviations, and spelling variants such as `colour`/`color` and `moisturiser`/`moisturizer`. Size, pack, shade, and unit tokens are retained as control evidence. Explicit conflicts such as 50 ml versus 100 ml, pack-of-1 versus pack-of-2, shade 10 versus shade 11, or EA versus CASE cap the candidate score and prevent both suggestion and automatic selection.

## Known limits

Generic text heuristics work best when labels and table columns survive extraction. Complex merged cells, handwritten invoices, curved or low-resolution photos, multilingual invoices, and rows whose numeric columns are separated from their descriptions can yield missing fields or `lines: []`. The extractor does not use supplier-specific geometry or learn new aliases by itself. Human confirmation should be persisted as a supplier-scoped alias only after the reviewer verifies item identity and UOM.

Test/demo sources are in `tests/fixtures/`. The suite also creates an embedded-text PDF, a real PNG OCR source, a real two-page scanned PDF, encrypted/corrupt PDFs, CSV/XLSX examples, and ambiguity cases at runtime.
