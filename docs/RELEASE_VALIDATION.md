# Local pilot release validation

25 September 2026

The downloadable application supports brand-specific master import, invoice capture, assisted item review, approval, a separate exception CSV, and consolidated Excel output. This record covers the tested local pilot, not universal invoice automation or receiving-system acceptance.

## Verified release checks

- A clean source-only snapshot built successfully with the supplied Dockerfile. The image's six runtime modules matched the workspace files used for acceptance.
- The Python suite ran inside that image against the clean snapshot: **84 passed, 1 skipped in 33.21 seconds**. The skipped test requires private master data; native OCR tests ran. One upstream Starlette deprecation warning remains.
- Browser workflows passed **3 of 3 in 7.4 seconds**, including the live brand setup, master import, invoice upload, exception download, manual approval and XLSX download, plus sample and mobile workflows.
- The downloaded live XLSX passed the exact three-sheet contract checker.
- A separate private acceptance imported the supplied master with zero skips or warnings and validated reviewed aliases. Public tests cover a sparse 185-column workbook and 100,005-row catalog without private inputs.
- Two original reference PDFs produced 20 lines with quantities and invoice net costs matching reviewed references. Twelve item mappings resolved automatically; eight replayed previously reviewed decisions. The assisted consolidated output contains 2 Header, 2 Tax_Breakdown and 20 Details rows.
- UPC export defaults to blank. A false/true/false policy check changed exactly the 20 UPC cells, preserved the other workbook values, and restored the original bytes after disabling it again. Enabled UPC values are Excel text.

## Scope limits

The separate [179-file corpus evaluation](REAL_CORPUS_EVALUATION.md) completed 178 documents with one explicit extraction-limit failure. It produced candidate rows in 81 documents; 13 invoice candidates passed strict financial extraction checks. Those checks do not establish catalog matching or export readiness. OCR coverage remains limited, and unfamiliar layouts still need source comparison and correction.

The current invoice-only pricing policy is conservative application behavior pending commercial signoff. RMS costs are comparison evidence and never silently replace invoice prices. No downstream import has been performed. The Windows instructions were reviewed and the container was tested on Linux; installation on a clean Windows computer remains unverified. Shared network deployment requires controls beyond the current loopback, single-operator pilot.

See [implementation acceptance](IMPLEMENTATION_ACCEPTANCE.md) for the independent, bounded verdict, [Windows setup](WINDOWS_SETUP.md) for installation, and [operator training](OPERATOR_TRAINING.md) for daily use. Final repository commit and distribution hashes are recorded in the delivery receipt rather than embedded in the source they identify.
