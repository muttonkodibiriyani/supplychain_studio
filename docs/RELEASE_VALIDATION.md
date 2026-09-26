# Release validation: v1.0.0-rc1

26 September 2026

Validated tree: `main` at `4bd33cc` plus the source-package fix in commit `3fda219` (`scripts/package_source.py` now ships `start.sh` and `Start-InvoiceStudio.command`; no application code changed). The packaged release is built from that tree by `python scripts/package_source.py`. This record is not shipped inside the package; it describes the package.

The downloadable application supports brand-specific master import, invoice capture, assisted item review, approval, a separate exception CSV, and consolidated Excel output. This record covers what was run on this tree with the public fixtures in `tests/fixtures`; it is not a universal accuracy claim and no real-corpus figure was produced in this run.

Host for every check below: Linux x86_64, 8 CPUs, Docker Engine 29.7.2 with BuildKit 0.32.2 and binfmt for `linux/arm64`. The host was shared with other running containers; 1-minute load average was between 40 and 63 during the runs, so the durations are upper bounds, not throughput figures.

## 1. Source package

```
$ python scripts/package_source.py
Packaged 75 files: invoice-studio-source.zip (269,014 bytes)
$ sha256sum invoice-studio-source.zip
60c153aafe89f58f33555611d4dc1f74ac8139e9f54fc4543341cb6e8eaf4a8f  invoice-studio-source.zip
```

Checked in the archive listing: `start.sh` and `Start-InvoiceStudio.command` present with mode `-rwxr-xr-x`; `Start-InvoiceStudio.ps1` present; no entry matching `.sqlite`, `.db`, `.venv`, `/data/`, `.pdf`, `.xlsx`, `.runtime` or `task-context` (count 0); docs limited to the six shipped guides. The packager's identifier/capability scan passed on every packaged file.

Before the fix, the same cold start failed from the unzipped folder:

```
$ ./start.sh --project-name invoice-launch-check --port 8061 --no-browser
/bin/bash: line 1: ./start.sh: No such file or directory
exit=127
```

## 2. Cold start from the zip (amd64, fresh Compose project)

```
$ sha256sum -c SHA256SUMS
invoice-studio-source.zip: OK
$ unzip -q invoice-studio-source.zip && cd invoice-studio
$ ./start.sh --project-name invoice-launch-check --port 8061 --no-browser
...
 Container invoice-launch-check-invoice-review-1 Healthy
Workspace: invoice-launch-check
Open http://localhost:8061
NAME                                    ... STATUS                   PORTS
invoice-launch-check-invoice-review-1   ... Up 6 seconds (healthy)   127.0.0.1:8061->8000/tcp
real 0m19.466s
exit=0
```

The 19-second wall time is with Docker's layer cache warm from earlier builds of the same Dockerfile on this host (11 cached steps); a first build on a new machine downloads base images and packages and takes several minutes, as the start script says.

API walkthrough against `http://127.0.0.1:8061`, all inputs public fixtures:

| Step | Command | Result |
| --- | --- | --- |
| Health | `GET /api/health` | `status: ok`, `ocr_available: true`, `workers.configured: 4`, `workers.alive: 4` |
| Brand settings | `PUT /api/settings` (location `0001`, type `S`, supplier rules for the two fixture suppliers with tax code `VAT5`) | HTTP 200, version 2 |
| Item master | `POST /api/catalog/import` with `tests/fixtures/sample_catalog.json` transcribed to the CSV import columns | `imported: 3, skipped: 0, warnings: []` |
| Upload | `POST /api/invoices/upload` with all 11 files under `tests/fixtures` (`sample_invoice.csv`, `sample_invoice.txt`, 9 files in `layouts/`) | 11 accepted, 0 duplicates, 0 rejected |
| Drain | poll `GET /api/invoices` | queue empty after 2.1 s; 11 of 11 in `needs_review`; health after drain `status: ok`, `error_count: 0`, `respawns: 0` |
| Approve (first pass) | `POST /api/invoices/{id}/approve` on all 11 | 11 × HTTP 422 with validation codes. The 9 layout fixtures report missing required fields, unmapped lines or a non-invoice document type, which is their purpose as extraction fixtures. The two sample invoices reject each other with `duplicate_supplier_invoice`: they are the same fictional invoice in CSV and text form. |
| Duplicate resolution | `PUT /api/invoices/{txt id}` suffixing the invoice number with `-DUPLICATE-COPY` and a comment | HTTP 200 |
| Approve | `POST /api/invoices/{csv id}/approve` | HTTP 200, `status: ready`; both lines auto-matched (`match_status: auto`, `target_cost_comparison_status: within_tolerance`) |
| Export | `POST /api/exports` with the approved id | HTTP 200, 6,322-byte workbook, sha256 `96561fa8a0cd24ca5baaf6f09c100ae69d2a75fe0770273d1339ad27581878bf` |
| Exceptions | `GET /api/reports/exceptions.csv` | HTTP 200, 11 data lines (one per unapproved or duplicate-marked upload) |
| Stats | `GET /api/stats` | `total: 11, needs_review: 10, exported: 1, failed: 0, matched_lines: 4, total_lines: 17, catalog_items: 3` |

Document classes in this run: text and CSV only (no PDF, no image, so no OCR path exercised). Upload count 11 equals distinct-document count 11 (two of them are the same invoice in two formats). Workers: 4 configured, 4 alive. Terminal state: 10 `needs_review`, 1 `exported`, 0 `failed`.

Workbook contract check:

```
$ python scripts/check_target_workbook.py target.xlsx
=== Workbook 1
  note  1 invoice(s), 1 tax row(s), 2 detail line(s); 1 invoice(s) reconcile within 0.01
  ==> CONFORMANT
exit=0
```

Teardown:

```
$ docker compose --project-name invoice-launch-check down -v
 Container invoice-launch-check-invoice-review-1 Removed
 Volume invoice-launch-check_invoice-data Removed
 Network invoice-launch-check_default Removed
exit=0
```

## 3. Python suite inside the built image

The image copies `backend/` only; `tests/` and `scripts/` are not in it, so `docker run --rm <image> python -m pytest backend/tests tests` exits 4 with `file or directory not found: tests`. The suite was therefore run on the image's interpreter and dependencies against a copy of the unzipped source:

```
$ docker run --rm -v $PWD:/src:ro invoice-launch-check-invoice-review \
    sh -c 'cp -r /src /tmp/src && cd /tmp/src && python -m pytest -p no:cacheprovider backend/tests tests'
FAILED backend/tests/test_backend.py::test_real_text_extraction_and_catalog_matching_flow_to_review
1 failed, 156 passed, 1 skipped, 1 warning in 52.73s
exit=1

$ docker run --rm -v $PWD:/src:ro invoice-launch-check-invoice-review \
    sh -c 'cp -r /src /tmp/src && cd /tmp/src && python -m pytest -p no:cacheprovider tests'
140 passed, 1 skipped, 1 warning in 27.41s
exit=0
```

The second command does not collect `backend/tests`, which is why it is green; the first command is the release check. The skipped test requires a private master and is skipped by design. The warning is the upstream Starlette test-client deprecation.

**Known open defect (not fixed in this release):** `backend/tests/test_backend.py::test_real_text_extraction_and_catalog_matching_flow_to_review` is red on every tree including `main`; the failing assertion is `assert invoice["lines"][0]["rms_item_id"] == "RMS-TXT-1"`. Ticket wording: line parser reads a size token as quantity. The test stays in the suite unchanged.

## 4. arm64 image build under emulation

```
$ docker buildx build --platform linux/arm64 -t invoice-studio:arm64-check .
#22 naming to docker.io/library/invoice-studio:arm64-check done
real 6m10.974s
exit=0
$ docker image inspect invoice-studio:arm64-check --format '{{.Architecture}} {{.Os}}'
arm64 linux
$ docker run --rm --platform linux/arm64 invoice-studio:arm64-check python -c "import platform; print(platform.machine())"
aarch64
```

This is a build check under QEMU emulation on an x86_64 host. It shows the Dockerfile and locked dependencies resolve for `linux/arm64`; it does not show the application running on a Mac.

## 5. Windows helper parse check

```
$ docker run --rm -v $PWD/Start-InvoiceStudio.ps1:/s/Start-InvoiceStudio.ps1:ro mcr.microsoft.com/powershell \
    pwsh -NoProfile -Command '[System.Management.Automation.Language.Parser]::ParseFile(...)'
7.4.2
parse errors: 0
tokens: 297; param block present: True; parameters: ProjectName, Port, NoBuild, NoBrowser
PSScriptAnalyzer: not available in the image; skipped (no network installs)
exit=0
```

Installation and the helper's behaviour on a clean Windows computer remain unverified here; `docs/WINDOWS_SETUP.md` keeps the direct Compose commands as the canonical procedure.

## Silent capability loss: standing check

Three times in this programme a benign-looking artefact shipped with a capability missing, and nothing red said so:

- the source packager omitted `start.sh` and `Start-InvoiceStudio.command`, so the unmodified zip died at exit 127 on the documented first command (section 1);
- the privacy guard checked only the paths written into the archive, so a document excluded from the zip by the allowlist was never scanned by anything, while git published it (closed by the whole-tree guard in `scripts/package_source.py`, `validate_repository`);
- a margin check that could pass vacuously, with nothing under it that could fail.
- a pre-push hook committed into the repository, which git never installs on clone, so it looked like a guard and fired for nobody; and, once installed, a hook that scanned the working tree while a push carries a commit range, so a marker committed and then deleted in a later commit passed it (closed by the launchers setting `core.hooksPath` and by `scripts/package_source.py --pre-push`, which scans every file version the pushed commits introduce).

Standing check for every release validation from now on: execute the shipped artefact from an unmodified copy of what is published (not from the working tree); run the privacy guard over the whole repository tree, not only the packaged paths; and assert each gate on a value that can actually fail, showing the command and its output.

### Push guard gate arms (fresh clone, real launcher)

Measured at branch `fix/whole-tree-privacy-guard` commit `aa8818b` (the tree under test; this section is the only later change). Push target: a bare mirror of that branch cloned from GitHub, so no marker leaves the machine; each arm is a fresh clone of that mirror. Marker: a synthetic home-directory path matching the eighth listed pattern, assembled at run time. Log kept outside the repository.

| Arm | Steps | Result |
| --- | --- | --- |
| C | `git ls-files -s .githooks/pre-push` in a fresh clone | `100755` in the index |
| A | fresh clone; `core.hooksPath` unset; `./start.sh --project-name hook-arm --port 8071 --no-browser` (real launcher, image built, project up); `core.hooksPath` reads `.githooks`; commit the marker; push | refused: message names `notes.txt` and the commit, never the value; mirror head unchanged |
| A2 | fresh clone; launcher once; commit the marker; commit its deletion on top; working tree clean and `--check-only` passes; push both | refused on the buried commit; mirror head unchanged |
| B | fresh clone; nothing run; `core.hooksPath` unset; commit the marker; push | not refused; README states this limit |

Re-run at `101e11f` (rebased on `main` `b3b2b7d`; refusal wording and the `--check-only` range scan changed since `aa8818b`), same setup, 2026-09-26T06:59Z to 07:00Z: arms C, A, A2 and B gave the same outcomes. Two additions: on the A2 tree `python3 scripts/package_source.py --check-only` now refuses with the identical message the push prints (tree guard line, then "commit <sha> introduces notes.txt … remove it from that commit … deleting the file in a later commit does not remove it from the push; do not bypass the hook"), so a clean pre-flight is a true pre-flight; and a fresh clone pushing its whole history to an empty remote is refused with "the history of this repository carries previously removed content at <commit> (<file>): the repository owner must rewrite history before this push; do not bypass the hook", the remote left with no refs.

Mutation pair at the same commit, differing only in the hook's last line: with `--check-only` (tree-only) in place of `--pre-push`, the test for arm A still passes and the test for arm A2 fails; restored, both pass. Verified on the Unix launcher; the Windows launcher sets the same configuration but has not been exercised here. Corroboration: one instrument (this run) plus the same arms as unit tests against a local bare origin in `tests/test_source_package.py`; Reviewer B's independent run was in flight when this was written.

## Scope limits

The separate [179-file corpus evaluation](REAL_CORPUS_EVALUATION.md) completed 178 documents with one explicit extraction-limit failure. It produced candidate rows in 81 documents; 13 invoice candidates passed strict financial extraction checks. Those checks do not establish catalog matching or export readiness. OCR coverage remains limited (`INVOICE_MAX_PAGES` is 50 in `compose.yaml`), and unfamiliar layouts still need source comparison and correction. Nothing in this run measures accuracy on real supplier documents.

The current invoice-only pricing policy is conservative application behavior pending commercial signoff. RMS costs are comparison evidence and never silently replace invoice prices. No downstream import has been performed. The Windows instructions were reviewed and the container was tested on Linux; installation on a clean Windows computer remains unverified. Shared network deployment requires controls beyond the current loopback, single-operator pilot.

See [implementation acceptance](IMPLEMENTATION_ACCEPTANCE.md) for the independent, bounded verdict, [Mac setup](MAC_SETUP.md) and [Windows setup](WINDOWS_SETUP.md) for installation, and [operator training](OPERATOR_TRAINING.md) for daily use. The release tag and distribution checksum are published on the GitHub release page rather than embedded in the source they identify.
