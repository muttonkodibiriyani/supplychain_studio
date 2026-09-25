# Open-source assessment

Reviewed against the supplied upstream repositories on 24 September 2026. These are upstream capabilities, not claims that all four engines are installed in this application. Pin versions and review their bundled models and dependencies before deployment.

| Project | Relevant capability and runtime | License at reviewed source | Decision for this delivery |
| --- | --- | --- | --- |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Text recognition plus document layout/table parsing through PP-Structure and document models. Python/native inference dependencies and model downloads; CPU and accelerator options depend on the selected pipeline. | [Apache-2.0](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE) for repository code. | Preferred next extraction candidate for complex invoice layouts. Evaluate as an isolated worker against real supplier documents; do not present upstream benchmark accuracy as invoice accuracy. |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Native OCR engine/CLI for images, with text and positional output. Requires language data and Leptonica. PDF input needs a separate renderer; it does not itself supply an invoice schema or item matcher. | [Apache-2.0](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE) for engine code; dependencies have their own terms. | Practical local CPU baseline for the MVP. Keep extraction evidence visible and route uncertain fields/lines to review. A bounded worker pool controls resource use. |
| [MinerU](https://github.com/opendatalab/MinerU) | Structured document conversion with OCR, layout/table handling, broad document-format support, and local/API options. Current local tiers use ONNX/Torch and optional VLM runtimes; model downloads and memory requirements vary. | [MinerU license](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md): Apache-based **with additional conditions**, including commercial-license thresholds and service attribution. | Candidate for difficult layouts and additional formats. Not an installed dependency in this delivery. Confirm terms for the adopting organisation and chosen version before integration. |
| [TaxHacker](https://github.com/vas3k/TaxHacker) | Existing receipt/invoice review and accounting app with extraction, bulk operations and exports. Uses Next.js, Prisma, PostgreSQL and PDF-processing tools; extraction can use hosted or local model endpoints. | [MIT](https://github.com/vas3k/TaxHacker/blob/main/LICENSE) for application code. | Useful workflow reference. It does not remove the need to implement this business's RMS name matching, supplier aliases, review gates and agreed REIM export contract. No TaxHacker code is represented as integrated here. |

## Implementation decision

Use React for upload/review, FastAPI for document APIs, SQLite plus retained source files for a single-instance durable worklist, and a bounded native extraction worker. Extract existing PDF text first; use rasterisation and Tesseract for scanned documents. Parse structured input directly when its supported format is known. Match descriptions against an imported item master, keep ranked candidates for uncertain names, and persist reviewed supplier aliases.

This recommendation is an engineering judgment for a runnable first delivery. Neither an OCR engine nor a general accounting app supplies the complete C5 workflow. The extraction boundary should allow a later PaddleOCR or MinerU worker to return the same invoice/header/tax/line evidence model without rewriting upload, review and export.

### What this repository actually integrates

The supplied Docker runtime installs the native Tesseract engine and English language data. Application code calls its CLI directly and uses `pypdf` for embedded PDF text, `pypdfium2` for scanned-page rendering, Pillow for raster images, `openpyxl` for XLSX/review workbooks, `python-docx` for DOCX text/tables, and RapidFuzz for candidate ranking. These supporting packages have their own licences and must be included in the deployment's dependency/SBOM review.

PaddleOCR, MinerU and TaxHacker are **not** dependencies, copied code, network services or runtime fallbacks in this release. They remain evaluated alternatives/reference material only. The application does not silently send supplier documents to any hosted model endpoint.

### Release dependency controls

The source handoff includes `package-lock.json` for the frontend and `requirements.lock.txt` for the Python runtime, and the Docker build installs the latter. Browser redistribution notices are supplied in `public/THIRD_PARTY_NOTICES.txt`. These locks and notices make the reviewed handoff more reproducible, but they are not a complete software bill of materials, legal review or vulnerability attestation. The Python base image and Debian Tesseract packages are currently selected by repository tag/package name rather than immutable image and package digests. Before controlled deployment, generate an SBOM for the built image, scan that exact image, retain all dependency notices, and adopt a reviewed update cadence.

The container also installs Debian's `tesseract-ocr-eng` language data. Additional languages require separately selected data packages and a new extraction evaluation; the presence of an OCR language model does not establish invoice-field or item-match accuracy.

## License detail that affects the choice

The reviewed MinerU license says a separate commercial license is required when the adopting entity and its affiliates, consolidated, exceed 100 million monthly active users **or USD 20 million total monthly revenue**. It also requires attribution for third-party online services based on MinerU. This is a version-specific source observation; adopting it for a large group needs a review against the actual deployment and pinned source. See the [license text](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md).

## Evaluation before changing the engine

Compare engines on the same held-out supplier documents. Measure header/line-field exactness, table row preservation, review rate, correctly auto-resolved item IDs, latency, CPU/GPU memory, and processing failures. Include poor scans, rotated pages, multipage tables, decimal/grouping separators, multiple languages, credit notes and near-identical product sizes. Keep the full pipeline's results separate from upstream OCR benchmarks.
