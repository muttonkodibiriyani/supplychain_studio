# Real corpus extraction evaluation

Evaluation date: 25 September 2026

This report measures the local extractor against a private intake of 179 files. It publishes aggregate evidence only. The invoices, filenames, supplier and customer identities, document identifiers, product text, prices, and commercial totals are excluded from this repository.

The result is not an accuracy score. Candidate rows are unreviewed parser output. A document counted by the strict-core gate has financially reconciled source rows, but still needs supplier, catalog, target-setting, and operator approval checks before export.

## Corpus and runtime

| Input | Count |
| --- | ---: |
| PDF | 168 |
| JPEG | 6 |
| XLSX | 5 |
| **Total** | **179** |

The final run used the release container with networking disabled, two workers, a 6 GiB memory limit, and the extractor's page, pixel, file, archive, XML, and OCR-time bounds. Forty-four PDFs were flagged for OCR. Of those, 43 completed and one stopped with `ExtractionLimitError`; all six JPEGs completed through local OCR. The same single failure occurred before and after this change.

The implementation uses fixed-position PDF text from [pypdf's documented layout mode](https://pypdf.readthedocs.io/en/6.18.1/user/extract-text.html). Scans use local Tesseract TSV output, which is one of the formats in the [official Tesseract command-line documentation](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html). Factur-X attachments are treated as structured invoice evidence because the [official Factur-X description](https://fnfe-mpe.org/factur-x/factur-x_en/) defines the format as a readable PDF with structured XML invoice data.

## Measured result

| Measure | Result |
| --- | ---: |
| Selected documents | 179 |
| Completed | 178 |
| Explicit failures | 1 |
| Documents with candidate rows | 102 |
| Candidate rows | 1,230 |
| Candidate rows with description, quantity, unit price, and line total | 1,036 |
| Strict-core financially reconciled documents | 13 |
| Strict-core emitted product lines | 70 |
| Maximal source-field gate documents | 0 |
| Prior audit documents with heuristic rows | 10 |
| Prior audit heuristic rows | 77 |

The 13 strict-core documents are all audit-labelled invoice candidates with embedded PDF text. Their 70 emitted product lines retain evidence for 140 physical source rows because each product consumed one adjacent, explicit discount adjustment. All 13 have a recognized table, no empty table section, no possible unparsed numeric row, no unpaired adjustment, no legacy fallback, complete core line fields, and a line-total sum that matches the ex-tax subtotal.

The maximal source-field gate additionally requires every line to carry source UOM, net unit price, line total, and UPC. No document in this intake supplied all of those fields on every line. A missing source UPC or UOM is not filled from the catalog by the extractor.

A separate provenance replay of all 102 candidate-row documents found nine printed or structured subtotals, 32 subtotals derived from grand total and a printed tax total, 15 derived from grand total and tax summed from explicit line-tax cells, and 46 unavailable subtotals. All 13 documents passing the existing strict-core gate are in the line-summed-tax class. They demonstrate internally reconciled source fields, while the replay reports them separately from printed-tax and explicit-zero evidence because the subtotal check is less independent. No corpus document used the new absent-tax-as-zero rule. The reviewed carbon-copy example below is the positive zero-tax case.

Four documents contained 170 line extensions with a non-zero third decimal. None was among the 13 strict-core documents. This measures exposure to older two-decimal line handling; it does not establish that those four documents are otherwise export-ready.

The 118 audit-labelled invoice candidates account for 74 documents with rows, 1,079 candidate rows, 977 core-complete rows, and the same 13 strict-core documents. The larger candidate count compared with the prior 77-row heuristic is evidence of broader table capture, not evidence that all 1,230 candidates are correct.

## OCR result

| OCR path | Completed documents | Documents with rows | Candidate rows | Strict core |
| --- | ---: | ---: | ---: | ---: |
| Scanned PDF | 43 | 14 | 111 | 0 |
| JPEG | 6 | 1 | 6 | 0 |
| **Combined** | **49** | **15** | **117** | **0** |

OCR used the installed English language data. Low confidence, non-English text, missed table boundaries, and missing totals keep OCR output in review. The one failed scanned PDF exceeded a configured extraction limit and did not produce partial output.

## Why documents remain in review

Gate reasons overlap; one document can contribute to several rows.

| Strict-core rejection reason | All completed documents | Audit invoice candidates |
| --- | ---: | ---: |
| Subtotal unavailable | 142 | 87 |
| No rows | 76 | 44 |
| No recognized table | 75 | 43 |
| Possible unparsed numeric rows | 54 | 36 |
| Missing core line fields | 40 | 20 |
| Classified outside invoice workflow | 29 | 9 |
| Recognized table section without accepted rows | 5 | 4 |
| Subtotal mismatch | 22 | 17 |
| Unpaired explicit adjustment rows | 13 | 13 |

The dominant recovered layout appeared in 26 documents. It contained 895 physical source rows. The parser paired 331 explicit non-positive discount rows while retaining each adjustment and its source-row range, and emitted 564 reviewable product or unpaired-adjustment rows. Thirteen documents reconciled strictly. The other 13 remain in review; they include 96 unpaired adjustments, possible partial rows in eight documents, and no usable subtotal reconciliation.

A second recurring layout appeared in 14 documents and supplied item code, description, UOM, quantity, price, and discount amount, but no unambiguous line-total column. Its 82 candidates are retained for review rather than inventing extensions. Seven more documents exposed UPC, description, quantity, price, tax, and a generic amount, but their captured line sums did not reconcile in the documents where a subtotal was available.

## Separate reviewed-source check

Two reviewed reference invoices supplied outside the 179-file drive intake were evaluated separately against their reviewed workbooks. One used embedded Factur-X XML and produced seven source lines. The other used 26 physical product and discount rows, paired to 13 product lines with every adjustment retained in provenance.

Both references passed the strict-core gate. Across 20 lines, document number, date, explicitly labelled purchase-order token, ex-tax subtotal, tax total, line count, every quantity, every net unit price, and the sum of line totals matched the reviewed workbooks. One reference also passed the maximal source-field gate; the other source did not print UPC or UOM, so those fields remain absent. These reviewed references demonstrate two supported layouts and are not counted among the 179 drive documents.

Private comparison and per-document receipts remain under `.runtime/real-reference-sources/`. They must not be copied into a source package or public repository.

## Extraction behavior added from the evidence

- PDF table extraction uses fixed-position headings, column boundaries, repeated table sections, and multiline descriptions. Centered headings with overflowing descriptions use a bounded right-tail tokenizer. Explicit `N/A` tax cells remain null and cannot shift product-code digits into numeric columns.
- Tesseract word boxes are converted to a fixed-position grid before the same table parser runs.
- Scanned PDFs first retain the former 144 DPI PSM 6 pass. Documents of up to 12 OCR pages may also use grayscale autocontrast PSM 4 for column layout and PSM 11 for sparse header evidence; a generic evidence score chooses the layout. Longer scanned packets remain single-pass so optional work cannot consume the document-wide timeout before every page is processed.
- Factur-X and ZUGFeRD attachments are limited to 10 MiB and 100,000 elements. XML with a DTD or entity declaration is rejected. Type codes distinguish invoice and credit note, and the full buyer-order reference is preserved while only an explicitly labelled PO token enters `po_number`.
- Adjacent discount pairing requires explicit discount wording, a non-positive net adjustment, equal quantity, compatible tax evidence, and explicit ex-tax line amounts. The original printed unit price, adjustment values, physical row range, and derived-field provenance remain on the product line.
- Net unit prices derived from net line amount divided by quantity retain eight decimal places and are accepted only when multiplying them back by quantity rounds `HALF_UP` to the exact source extension. Printed prices are not rounded to two decimals by the parser.
- A subtotal can be derived from total minus tax total with explicit provenance. A missing tax total can be summed from every explicit line-tax amount only when the recognized table is complete and has no partial rows, empty sections, unpaired adjustments, or legacy fallback.
- Explicit absence of tax can be treated as zero only for a complete Gross/Net/discount table with no tax token or line tax, where every line has explicit gross and net evidence and the independently captured extensions reconcile the printed total. The subtotal still derives from the printed total minus that zero tax; it is never derived from the line sum.
- Credit notes, delivery notes, purchase-order support, and unknown documents remain separately classified for review.

The baseline-to-final comparison preserved all 13 strict-core documents and introduced no new extraction failure. Documents with candidate rows increased from 81 to 102. Among the 151 documents whose baseline subtotal was unavailable, one became reconciled, ten exposed a mismatch and stayed rejected, and 140 remained unavailable. Eight documents changed from unknown to invoice; no credit note changed to invoice. Four OCR documents changed from invoice to unknown and remain explicitly reviewable rather than eligible for approval.

A separate reviewed carbon-copy invoice, outside this 179-file intake, measured the OCR change at field level. All 13 quantities, net unit costs, and line totals matched the reviewed capture, and the extensions reconciled the printed total. Four of 13 barcodes and six normalized descriptions were exact; description similarity averaged 0.9736. Its ambiguous numeric date stayed withheld. The `CREDIT INVOICE` title classified as invoice at 0.90 confidence, while synthetic `CREDIT NOTE`, `TAX CREDIT NOTE`, and `CREDIT MEMO` regressions remained credit notes. This one reviewed example is not an accuracy estimate for other layouts.

## Reproduce the private evaluation

Run from the repository root. The status CSV paths must be relative to the private corpus root.

```bash
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --cpus 2 --memory 6g --pids-limit 512 \
  -e OMP_THREAD_LIMIT=1 \
  -v "$PWD:/work" \
  -v "${PRIVATE_CORPUS_ROOT}:/corpus:ro" \
  -v "${PRIVATE_STATUS_CSV}:/status.csv:ro" \
  -w /work invoice-studio:release \
  python scripts/evaluate_corpus.py \
    --input-root /corpus \
    --status-csv /status.csv \
    --output /work/.runtime/carbon-copy-ocr/corpus-improved-preserved.json \
    --selection all --workers 2 --progress-every 20
```

The receipt stores opaque content-derived document IDs, methods, counts, diagnostics, and failure categories. It excludes filenames, source paths, raw text, extracted identifiers, product descriptions, and monetary values. Its per-document gate-reason arrays provide the private failure list requested for follow-up.

For this run:

- receipt SHA-256: `292cc2b868a0334749ec4c7e0c674c2efcace523f0fccfd00f3aa6929530890b`
- extractor SHA-256: `37e052819d24504097a4eec79e0c9d41d266b522aa3739d458d5343097f1f76d`
- evaluator SHA-256: `fa7669cbb4816bb56a14ac3eae5a0b2ea032e43e8c84638ecdc45a94cc19e228`

## Limits of the evidence

There is no reviewed ground-truth annotation for all 179 documents, so precision, recall, and an overall accuracy percentage cannot be calculated honestly. Arithmetic equality can also fail legitimately when a source represents discounts, free goods, tax, or rounding elsewhere. The strict gate detects recognized empty sections and partial numeric rows but cannot prove that a PDF text layer or OCR engine omitted no source line.

Strict-core reconciliation is financial extraction evidence. It does not establish supplier-site correctness, catalog matching, target tax codes, store settings, approval, receiving acceptance, or payment readiness. Operators must compare the rendered source, resolve every exception, and approve the invoice before export.

“Learning” in this application means improved parsers and reuse of operator-reviewed mappings. No model was fine-tuned, and these results do not support a claim of universal invoice-layout accuracy.
