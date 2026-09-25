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

The run used the release container with networking disabled, two workers, a 4 GiB memory limit, and the extractor's page, pixel, file, archive, XML, and OCR-time bounds. Forty-four PDFs were flagged for OCR. Of those, 43 completed and one stopped with `ExtractionLimitError`; all six JPEGs completed through local OCR.

The implementation uses fixed-position PDF text from [pypdf's documented layout mode](https://pypdf.readthedocs.io/en/6.18.1/user/extract-text.html). Scans use local Tesseract TSV output, which is one of the formats in the [official Tesseract command-line documentation](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html). Factur-X attachments are treated as structured invoice evidence because the [official Factur-X description](https://fnfe-mpe.org/factur-x/factur-x_en/) defines the format as a readable PDF with structured XML invoice data.

## Measured result

| Measure | Result |
| --- | ---: |
| Selected documents | 179 |
| Completed | 178 |
| Explicit failures | 1 |
| Documents with candidate rows | 81 |
| Candidate rows | 1,007 |
| Candidate rows with description, quantity, unit price, and line total | 690 |
| Strict-core financially reconciled documents | 13 |
| Strict-core emitted product lines | 70 |
| Maximal source-field gate documents | 0 |
| Prior audit documents with heuristic rows | 10 |
| Prior audit heuristic rows | 77 |

The 13 strict-core documents are all audit-labelled invoice candidates with embedded PDF text. Their 70 emitted product lines retain evidence for 140 physical source rows because each product consumed one adjacent, explicit discount adjustment. All 13 have a recognized table, no empty table section, no possible unparsed numeric row, no unpaired adjustment, no legacy fallback, complete core line fields, and a line-total sum that matches the ex-tax subtotal.

The maximal source-field gate additionally requires every line to carry source UOM, net unit price, line total, and UPC. No document in this intake supplied all of those fields on every line. A missing source UPC or UOM is not filled from the catalog by the extractor.

The 118 audit-labelled invoice candidates account for 63 documents with rows, 954 candidate rows, 667 core-complete rows, and the same 13 strict-core documents. The larger candidate count compared with the prior 77-row heuristic is evidence of broader table capture, not evidence that all 1,007 candidates are correct.

## OCR result

| OCR path | Completed documents | Documents with rows | Candidate rows | Strict core |
| --- | ---: | ---: | ---: | ---: |
| Scanned PDF | 43 | 3 | 11 | 0 |
| JPEG | 6 | 2 | 7 | 0 |
| **Combined** | **49** | **5** | **18** | **0** |

OCR used the installed English language data. Low confidence, non-English text, missed table boundaries, and missing totals keep OCR output in review. The one failed scanned PDF exceeded a configured extraction limit and did not produce partial output.

## Why documents remain in review

Gate reasons overlap; one document can contribute to several rows.

| Strict-core rejection reason | All completed documents | Audit invoice candidates |
| --- | ---: | ---: |
| Subtotal unavailable | 151 | 96 |
| No rows | 97 | 55 |
| No recognized table | 84 | 43 |
| Possible unparsed numeric rows | 61 | 50 |
| Missing core line fields | 34 | 23 |
| Classified outside invoice workflow | 33 | 10 |
| Recognized table section without accepted rows | 19 | 16 |
| Subtotal mismatch | 14 | 9 |
| Unpaired explicit adjustment rows | 13 | 13 |
| Legacy fallback used | 3 | 2 |

The dominant recovered layout appeared in 26 documents. It contained 895 physical source rows. The parser paired 331 explicit non-positive discount rows while retaining each adjustment and its source-row range, and emitted 564 reviewable product or unpaired-adjustment rows. Thirteen documents reconciled strictly. The other 13 remain in review; they include 96 unpaired adjustments, possible partial rows in eight documents, and no usable subtotal reconciliation.

A second recurring layout appeared in 14 documents and supplied item code, description, UOM, quantity, price, and discount amount, but no unambiguous line-total column. Its 82 candidates are retained for review rather than inventing extensions. Seven more documents exposed UPC, description, quantity, price, tax, and a generic amount, but their captured line sums did not reconcile in the documents where a subtotal was available.

## Separate reviewed-source check

Two reviewed reference invoices supplied outside the 179-file drive intake were evaluated separately against their reviewed workbooks. One used embedded Factur-X XML and produced seven source lines. The other used 26 physical product and discount rows, paired to 13 product lines with every adjustment retained in provenance.

Both references passed the strict-core gate. Across 20 lines, document number, date, explicitly labelled purchase-order token, ex-tax subtotal, tax total, line count, every quantity, every net unit price, and the sum of line totals matched the reviewed workbooks. One reference also passed the maximal source-field gate; the other source did not print UPC or UOM, so those fields remain absent. These reviewed references demonstrate two supported layouts and are not counted among the 179 drive documents.

Private comparison and per-document receipts remain under `.runtime/real-reference-sources/`. They must not be copied into a source package or public repository.

## Extraction behavior added from the evidence

- PDF table extraction uses fixed-position headings, column boundaries, repeated table sections, and multiline descriptions. Centered headings with overflowing descriptions use a bounded right-tail tokenizer. Explicit `N/A` tax cells remain null and cannot shift product-code digits into numeric columns.
- Tesseract word boxes are converted to a fixed-position grid before the same table parser runs.
- Factur-X and ZUGFeRD attachments are limited to 10 MiB and 100,000 elements. XML with a DTD or entity declaration is rejected. Type codes distinguish invoice and credit note, and the full buyer-order reference is preserved while only an explicitly labelled PO token enters `po_number`.
- Adjacent discount pairing requires explicit discount wording, a non-positive net adjustment, equal quantity, compatible tax evidence, and explicit ex-tax line amounts. The original printed unit price, adjustment values, physical row range, and derived-field provenance remain on the product line.
- Net unit prices derived from net line amount divided by quantity retain eight decimal places and are accepted only when multiplying them back by quantity rounds `HALF_UP` to the exact source extension. Printed prices are not rounded to two decimals by the parser.
- A subtotal can be derived from total minus tax total with explicit provenance. A missing tax total can be summed from every explicit line-tax amount only when the recognized table is complete and has no partial rows, empty sections, unpaired adjustments, or legacy fallback.
- Credit notes, delivery notes, purchase-order support, and unknown documents remain separately classified for review.

## Reproduce the private evaluation

Run from the repository root. The status CSV paths must be relative to the private corpus root.

```bash
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --cpus 2 --memory 4g --pids-limit 256 \
  -e OMP_THREAD_LIMIT=1 \
  -v "$PWD:/work" \
  -v "${PRIVATE_CORPUS_ROOT}:/corpus:ro" \
  -v "${PRIVATE_STATUS_CSV}:/status.csv:ro" \
  -w /work invoice-studio:release \
  python scripts/evaluate_corpus.py \
    --input-root /corpus \
    --status-csv /status.csv \
    --output /work/.runtime/real-corpus-evaluation-final.json \
    --selection all --workers 2 --progress-every 20
```

The receipt stores opaque content-derived document IDs, methods, counts, diagnostics, and failure categories. It excludes filenames, source paths, raw text, extracted identifiers, product descriptions, and monetary values. Its per-document gate-reason arrays provide the private failure list requested for follow-up.

For this run:

- receipt SHA-256: `ec87d68e574fd74d0ec67710c8baa56cdef687c5b1a1a6ad99a133f27371ecd5`
- extractor SHA-256: `150871ebb0cf3b5423677fbc65a20c24e0801ce3e085b840c215d77de4b8e3f9`
- evaluator SHA-256: `8aec17f6387afe89ea79fd1da541d3a3235d25d9909ed9eb5b4bcf875cd8aae0`

## Limits of the evidence

There is no reviewed ground-truth annotation for all 179 documents, so precision, recall, and an overall accuracy percentage cannot be calculated honestly. Arithmetic equality can also fail legitimately when a source represents discounts, free goods, tax, or rounding elsewhere. The strict gate detects recognized empty sections and partial numeric rows but cannot prove that a PDF text layer or OCR engine omitted no source line.

Strict-core reconciliation is financial extraction evidence. It does not establish supplier-site correctness, catalog matching, target tax codes, store settings, approval, receiving acceptance, or payment readiness. Operators must compare the rendered source, resolve every exception, and approve the invoice before export.

“Learning” in this application means improved parsers and reuse of operator-reviewed mappings. No model was fine-tuned, and these results do not support a claim of universal invoice-layout accuracy.
