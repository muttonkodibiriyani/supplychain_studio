# Implementation acceptance record

Independent acceptance for the invoice-to-target-Excel delivery, written solely by the programme's
independent acceptance owner. Every other file in this repository belongs to another owner; nothing
here was produced by editing their work.

This document is published with the source. It deliberately carries no invoice number, supplier
site, store code, commercial amount or private file path. The two known-good workbooks it refers to
are called **Golden A** and **Golden B** throughout; the detailed evidence that identifies them, and
the private-material signature patterns used to scan for leaks, are held privately by the acceptance
owner and are not published.

**Frozen: 25 September 2026 UTC. Overall verdict: NOT ACCEPTED — 12 of 15 criteria pass.**

**FROZEN — 25 September 2026.** This record is now fixed against a specific build and is not
provisional. It is bound to the delivery image `sha256:a749afa3…8020` and the frozen extractor
`150871eb…e3f9`. I verified that binding rather than accepting it: I re-hashed all six backend runtime
modules in the workspace, then hashed the same six files *inside the image itself*, and all six match
byte for byte. The code described below is the code that ships. Any change to those modules invalidates
this record and requires a re-run.

**Verdict: NOT ACCEPTED for general production use. 12 of 15 criteria pass.** The application is, on
this evidence, suitable for a supervised pilot on a controlled host with an operator reviewing every
document. It is not suitable for unattended bulk conversion, and nothing here should be quoted as an
accuracy figure.

**Read the post-freeze findings section before relying on this verdict.** Five gates discovered
after the freeze sit between a scanned invoice and an accepted workbook; three are defects, and one
materially undermines the reasoning behind A6.

**The four limits that remain, stated plainly:**

1. **Pricing is not commercially signed off.** Every `Details.Unit Cost` carries the invoice net unit
   cost after discount, and RMS cost is comparison evidence that never substitutes. That behaviour is
   implemented, tested and enforced, but it remains the application's conservative reading rather than a
   rule the user has confirmed. It must not be described as a user-approved business rule until that
   confirmation arrives.
2. **The Windows procedure has never been executed on Windows.** No clean Windows host was available;
   every check behind the installation and training material ran on Linux. The instructions are
   internally consistent and were reviewed against verified behaviour, but the first real run should be
   treated as part of the pilot. Both operator documents now state this limit explicitly at the top,
   which is why A11 passes — but the limit itself is real and does not go away by being documented.
3. **No generated workbook has ever been accepted by the downstream system.** The exported file matches
   the contract and matches the supplied reviewed examples, including the blank UPC convention. That is
   the best available evidence and it is not the same as an import succeeding. Nobody should treat a
   conformant workbook as proof of acceptance.
4. **Corpus coverage is incomplete and corpus-wide mapping is unverified.** Of 179 documents, 81 yield
   candidate rows and 13 reconcile financially, while zero pass the full source-to-target gate. That
   gate requires UPC and UOM to be present in the source, so failing it shows those fields were not read
   from the document — it does not show the catalog and target mapping could never be completed, which
   is precisely what the operator workflow exists to supply. Read this as no automatic corpus-wide
   conversion and no verified mapping at corpus scale, not as impossibility. Likewise the 151
   `subtotal_unavailable` rejections mean the extractor did not capture a subtotal, not that the sources
   lack one; no manual source audit has been done.

**What is established, and was checked rather than reported:** the workbook contract is exact and
mechanically enforced; the exporter emits it; a regression defends it; conversion rules come from
per-brand settings; excluded documents leave through a separate report that is exhaustive by
construction; identifiers survive as text; the documented master import genuinely works at full scale;
and the published source carries no private data.

The GitHub commit hash is deliberately not recorded here. It belongs in the parent delivery receipt,
since this document is itself part of what gets committed.

**Scope this is judged against:** a local Windows pilot, one brand per isolated Compose project and
data volume, bound to loopback, with the application source published to GitHub. Shared, networked
or multi-tenant production deployment is explicitly not claimed and is not judged here.
The application cannot currently emit the user's file at all, and no consolidated target workbook
exists for the real corpus. What follows is the evidence for that statement, criterion by
criterion, so the gap is actionable rather than merely asserted.

This record is read-only acceptance. It does not restate the program audit
(root's private program security and conversion audit, held outside the published tree), which remains the baseline; where a number
comes from that audit it is labelled as baseline, and where it comes from this session's own
re-execution it is labelled as verified here.

## How to reproduce this record

Two read-only instruments were written for this acceptance. They live outside this repository, in
the acceptance owner's private working area, and are identified here by hash so a reviewer can
confirm which version produced a given result:

| Instrument | sha256 (first 24) | What it decides |
|---|---|---|
| `target_conformance.py` | `304c321dcec6594c0eeb9342` | Whether a candidate workbook satisfies the exact target contract |
| `publication_sim.py` | `b8a263a6071722f597cb60d2` | What a publication would actually contain, and whether it carries private material |

Neither writes to this workspace. `target_conformance.py` takes workbook paths and exits non-zero
on any failure, so it can be wired into CI once the exporter produces a candidate.

## The contract being accepted against

One consolidated `.xlsx`, exactly three sheets in this order, no others:

- **Header** (13 columns): Transaction Number; Document; Supplier Site; Order No; Location;
  Location Type; Document Date; Total Cost Ex Tax; Tax Amount; Ref No. 1; Ref No. 2; Ref No. 3;
  Comment. One row per genuine eligible invoice.
- **Tax_Breakdown** (3 columns): Transaction Number; Tax Code; Tax Basis.
- **Details** (6 columns): Transaction Number; Item; UPC; Unit Cost; Quantity; Unit Tax Code.
  Every eligible product line.

Transaction Number links all three tabs. No README, Audit or metadata tab; no extra columns; no
blank artifact rows. Credit notes, RTVs, PODs and unresolved matches are excluded from the target
and belong in a separate exception report.

Unit cost and Order No follow the private conversion-rules file. Aliases are the five in the
private confirmed-aliases file and only those.

## Criteria and verdicts

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| A1 | The exact three-tab contract is precisely specified and mechanically checkable | **PASS** | `target_conformance.py` encodes sheets, order, headers, widths, key integrity, blank-row detection, formula-injection and per-invoice arithmetic. Calibrated against known-good files, below. |
| A2 | Known-good target workbooks satisfy the contract | **PASS, with a typing warning** | All four known-good workbooks held privately under `data/outputs` return CONFORMANT, exit 0. Their hashes match the programme audit's durable receipts. Identifier typing is a separate concern — see A14. |
| A3 | The application exporter emits the exact contract | **PASS for the exporter, verified independently** | The five-sheet output (README/Header/Tax/Detail/Audit) is gone. The exporter now produces a consolidated workbook with exactly `Header`/`Tax_Breakdown`/`Details`, and I verified the artefact myself rather than accepting the run report: the file's SHA-256 matches the one supplied byte for byte, and my own conformance checker — written before and independently of the implementation — returns CONFORMANT with 2 invoices, 2 tax rows, 20 detail lines, both invoices reconciling within one cent. Correctly scoped by its owner as a reference round-trip over two already-reviewed invoices: it is evidence the exporter emits the contract, not evidence of corpus conversion (A7) or of downstream acceptance.  **Open watch item — the UPC column now diverges from every known-good example.** In the first actual-source export all 20 Details rows carry a populated 13-character UPC, stored correctly as text with an `@` format. Every one of the five reviewed reference workbooks leaves that column blank, in all 13 and all 7 of their rows. I had previously examined those blanks and recorded them as intended rather than a defect, so the observed-good behaviour is blank and the new behaviour is populated. This is not an exporter regression: `backend/exporter.py` emits the matched UPC unconditionally and has not been modified since before the matcher work, so the change comes from master rows now being selected upstream where previously none were. The risk is unchanged by that explanation. The only evidence anyone holds about what the downstream system accepts is those five workbooks, and this output differs from all five in a column the consumer may key on. **Resolution agreed, implementation outstanding.** Root accepted the finding and delegated a backend change: blank UPC by default, matching the supplied reviewed targets, with an explicit per-brand `include_upc_in_export` opt-in available only after downstream verification. That is the right shape — it restores the only behaviour known to be accepted, and puts the deviation behind a deliberate, brand-scoped decision instead of compiled-in code, which is what A5 expects of a conversion rule. The enriched workbook above is therefore superseded integration evidence, not a deliverable. **Closed — verified in both directions, 25 September.** Three exports were produced with the setting off, on, then off again. I checked each file's SHA-256 against its receipt, and ran the contract checker on all three: CONFORMANT at exit 0, 2 Header / 2 Tax_Breakdown / 20 Details every time, so the switch cannot break the contract in either position. Default gives 20 blank UPC cells; opt-in gives 20 populated 13-character UPCs stored as text with an `@` format, so A14 still holds when the column is in use. Two properties make this stronger than a simple before-and-after. First, I diffed the off and on workbooks cell by cell across all three sheets: exactly 20 cells differ, every one of them in the Details UPC column, with the column header itself preserved — the setting changes what it claims to change and nothing else. Second, the third export is byte-identical to the first, so toggling on and back off leaves no residue and the setting is not sticky. The default also matches the five reviewed reference workbooks in substance: blank with a null cell type, exactly as they are. One residual difference, recorded for precision rather than as a defect: those references carry `General` on that column while our default carries `@`. On an empty cell this has no value or display consequence, and `@` is the safer choice for an identifier column, but the default is therefore equivalent to the references rather than byte-identical to them. |
| A4 | The exact contract is defended by an automated test | **PASS — verified on a clone-equivalent snapshot** | `tests/test_target_export.py` defends the contract, and I ran it the way a cloner would: an allowlisted snapshot containing no private data at all, in a network-isolated container. 10 passed, 1 skipped, the skip being the private-gated import. The contract test is stricter than my own checker — it asserts leading zeros survive on real examples (`000INV-1`, `000077`, `000000456789`) and requires both `data_type == "s"` and `number_format == "@"`, where I had only checked the stored type. It also covers transaction linkage across all three sheets. |
| A5 | Conversion rules are executed from per-brand configuration, not hard-coded | **PASS** | Verified semantically, as restated: no bundled private file is involved. Settings are versioned with optimistic concurrency (a stale version raises `Conflict`), brand-scoped, and default to `invoice_only` with the review threshold as configured data. The suite also proves the rule is enforced rather than merely stored: setting `target_cost_policy.mode` to `rms_within_tolerance` is rejected with a field-level validation error, so the superseded substitute-RMS behaviour cannot be configured back in. Aliases arrive through an operator import path. The rounding convention is defended too, retaining full net-unit precision and rounding each extension. |
| A6 | Cost reconciliation is defined | **PROVISIONAL — conservative rule adopted, user confirmation outstanding** | The quoted user turn establishes a *fallback*, not an unconditional rule. The conservative reading (invoice cost always) is implemented because it is the only one internally consistent with exact reconciliation, and it never restates a supplier price. An explicit user confirmation has been requested and is pending. See below. |
| A7 | One consolidated workbook exists for the real corpus | **FAIL** | Baseline: zero verified consolidated target outputs. Every known-good file is a single-invoice review artefact, not a consolidated batch target.  **Bottleneck update — the blocker has moved from extraction to matching.** Root fed both verified originals through an isolated InvoiceService with a copied real master: 20 of 20 quantities, prices and subtotals were preserved end to end, but the baseline matcher resolved only 9 of 20 lines. Under the all-or-nothing rule 11 unresolved lines route both invoices to exceptions whole, so these two documents still produce no consolidated output despite extracting perfectly. That reframes A7: extraction is no longer the limiting factor on these layouts, item resolution is. A bounded matcher improvement is delegated on explicit source UPC evidence; `backend/matching.py` was being edited as I checked, so treat 9 of 20 as a baseline snapshot rather than a current figure.  **First actual-source consolidated workbook produced — verified, but assisted rather than autonomous.** Both reviewed reference PDFs were ingested through InvoiceService against a copied full master and exported to a single workbook: 2 Header rows, 2 Tax_Breakdown rows, 20 Details rows. I confirmed it independently — the receipt's declared SHA-256 matches the file, and root's own checker returns CONFORMANT at exit 0 on my run, with both invoices reconciling and every Details and Tax_Breakdown row linking to a Header transaction number. That is the first time the contract has been satisfied end to end from original PDFs rather than from fixtures. It is **not** A7. Only 12 of the 20 lines resolved automatically (7 of 7 on the Factur-X source, 5 of 13 on the discount-paired source); the remaining 8 replayed previously reviewed mapping decisions supported by explicit supplier, UOM and size evidence. **Scope of this criterion, stated precisely.** A7 asks for one consolidated workbook covering the real 179-file corpus. What is unmet is coverage, and only coverage. Assisted mapping review is an intended product workflow, not a defect: an operator confirming an ambiguous item match is the system working as designed, so the presence of reviewed decisions in this run is not itself evidence against the exporter or the matcher. I had earlier implied otherwise and that was too strong. The two-original reviewed consolidation is verified and stands on its own; 179-file coverage is a separate, still-unresolved requirement, and the rerun has since completed. A7 stays FAIL on coverage alone, and the completed corpus run now settles this with a measurement rather than an expectation: of 179 documents, the number passing the full source-to-target gate is **zero**, with 81 rejected for missing source-target fields. **The limits of that number matter.** The maximal gate requires UPC and UOM to be present in the source document, so a failure there means those fields were not read from the source — not that supplier, catalog and target mapping could never be completed. Those are exactly the things the intended operator workflow supplies, as the two-document reviewed replay demonstrated. So what is established is incomplete coverage and unverified catalog and target mapping across the corpus, not impossibility: nothing here shows the 13 financially reconciled documents could not be exported after operator mapping. No automatic corpus-wide conversion exists today, and that is what A7 asks for. One non-defect planning note for the user rather than for acceptance: the ratio of automatic to reviewed lines drives operator workload, so 8 reviewed lines in 20 is comfortable at two documents and worth watching as a time cost at corpus scale. |
| A8 | Real invoice layouts yield product lines | **PARTIAL — exact on the reviewed reference sources; corpus now measured and materially improved** | This moves off FAIL. Baseline: of 124 embedded-text PDFs, 114 returned zero product lines, including 106 of 114 invoice candidates. Two real originals have now been parsed and checked field by field against independently reviewed workbooks, and matched exactly: the Factur-X source at 7 of 7 lines, and the discount-paired source at 13 products recovered from 26 source rows (13 paired adjustment rows correctly collapsed). Document number, date, PO, subtotal, tax total, every quantity and every net unit price matched, with line totals reconciling to the stated subtotal and an empty mismatch list. I verified this is a genuine parser-on-original run rather than a re-read of the reviewed targets: the receipt's two `source_path` values are byte-identical (SHA-256) to the original source PDFs whose provenance the corpus coordinator supplied to me separately, and its `extractor_sha256` equals the `backend/extraction.py` currently on disk, so the receipt describes live code and not a stale build. **Denominators are separate and must stay separate.** These two reviewed reference PDFs are not members of the 179-file drive collection, so this is 2 of 2 on the reference set and says nothing quantitative about the corpus. **Corpus now measured, 25 September, against a frozen extractor.** The tokenizer defect was corrected and the full run completed: 178 of 179 documents processed, 1 rejected with an explicit resource-limit error rather than a silent failure. 81 documents produced 1,007 candidate rows, and 690 of those rows carry every core field. Against a baseline where 114 of 124 embedded-text PDFs returned nothing at all, that is a large and real improvement, and it is measured rather than asserted — I verified the receipt's SHA-256 and confirmed its `extractor_sha256` matches the frozen extractor on disk. It is still not PASS, and the reason is quality rather than volume: only 13 documents covering 70 product lines pass the strict financial reconciliation gate. The dominant rejection reason is worth naming: `subtotal_unavailable` accounts for 151 of them. **Read that precisely.** It means the extractor did not capture or derive a subtotal for those documents. It does not mean the source documents fail to print one — no complete manual audit of the sources exists, so the split between source limitation and extractor limitation is unknown and I should not have implied otherwise in an earlier draft. Candidate rows are unreviewed parser output and neither these counts nor any ratio drawn from them is an accuracy score. A8 stays PARTIAL. |
| A9 | Exceptions are separated from the target | **PASS — verified, and exhaustive by construction** | Both halves now hold. Exclusion was already enforced: any unresolved line or non-invoice document blocks the whole invoice. The missing half — an artefact the operator can work from — now exists as a read-only `GET /api/reports/exceptions.csv`, downloadable from the UI, with five columns and an explicit machine-readable reason per row. The design detail that makes this trustworthy is that the report is the **complement** of the export-eligible set (`eligible = status in {ready, exported} and not reasons`; everything else is reported) rather than an enumerated list of known exception types, so it cannot silently omit a category as new ones appear. Credit notes, RTVs and PODs reach it via the `not_invoice` code and unresolved matches via `unmapped`, both confirmed present in the validation path. CSV text is formula-injection safe — the guard strips nulls and checks for `=`, `+`, `-`, `@` *after* stripping leading whitespace and a BOM, so the obvious prefix bypass does not work. Output is UTF-8 with BOM so Excel opens it correctly. Critically, the target export is untouched: the same workbook re-checks CONFORMANT with exactly three sheets. Worth stating plainly for planning: while the corpus sits at zero strict reconciliations (A7), this report is where essentially every document lands, so it is the operator's primary workspace today rather than an edge case. |
| A10 | Publication carries no private data | **PASS, conditional — re-verified 25 September against the tightened allowlist** | Re-simulated after the allowlist began admitting four named data fixtures: 65 files, 716,087 bytes, and the packager's own negative assertions (`task-context`, `/data/`, `/.runtime/`) match nothing. The four fixtures were checked for being *synthetic in fact*, not merely in name: no fixture supplier ID, item ID, invoice number or PO appears in the real item master or the confirmed-alias file. Three apparent hits on product wording were coincidental substring matches against generic cosmetics vocabulary, not fixture products. No assigned literal secret exists anywhere in the allowlist; every credential-pattern hit is the word "token" used for text processing or OCR. The earlier `git add -A` hazard is separately closed by a root-level `/*.json` ignore with explicit exceptions, which covers the event dumps and every receipt variant I had enumerated. That simulation was run against the allowlist as it then stood, while the tree was still changing. At freeze the code is fixed at the named image and root reports the final publication scan passing; I am recording that as root's result, not as a second independent run of my own. |
| A11 | Windows from-zero install and operator training exist | **PASS** | Both documents are present and were checked independently: code fences balanced, no TODO or placeholder text, no stale RMS-preferred language, the fixed pricing rule stated explicitly in both, and the Compose configuration validates against the supplied example environment. Not walked through on a clean Windows host — none was available — so the installation claim itself stays unverified, and see A15 for a documented step that cannot currently succeed.  **Read-only consistency review completed 25 September; content is accurate, one omission keeps this PARTIAL.** I checked both documents against what I had independently verified and found the substantive claims correct: the UPC default is described as off, blank to match the reviewed examples, and enabled only after the receiving system confirms acceptance; the repository named is the one actually created; the expected master row count stated there matches the store I inspected; the stated import time of about four minutes matches the measured run and is explicitly not offered as a Windows guarantee; and the exception section describes the download, its whole-workspace scope and its snapshot nature exactly as the implementation behaves. The escalation table is consistent with the enforced gates, including the AED 10 acknowledgement and the rule that RMS cost never substitutes. Both documents avoid accuracy and machine-learning claims, and one states plainly that learned matching is reviewed mapping reuse rather than statistical learning. **The gap is that neither document says the Windows procedure itself has never been run.** No clean Windows host was available, so every check behind these instructions was performed on Linux. The install guide opens by stating it installs and runs the application, and its boundaries section lists many honest limits without listing this one, so a reader would reasonably assume the steps were executed as written. The single oblique hint is a timing caveat in the other document. I routed it to root as the owner's to fix. **It is fixed and I verified it.** Both documents now carry a prominent validation limit near the top stating that the Windows instructions were authored and reviewed but not executed end to end on a clean Windows computer, that the checks ran on Linux, and that the first installation should be treated as a pilot. That was the only thing standing between this criterion and a pass, so A11 passes. |
| A13 | No private reference data is required at runtime or shipped in the release | **PASS — reconfirmed after handoff** | Restated after root's correction of 25 September. `data/reference/` is excluded from the published snapshot and no code path loads it; that exclusion is the desired state, not a gap. The superseded `target_conversion_rules.json` is retained as a *historical* artefact only, pending the outstanding user pricing clarification. Reconfirmed after handoff by building a clone-equivalent snapshot: 65 files, no `data/reference` content of any kind, and the full target-export suite passes inside it, so the shipped tree genuinely starts empty and needs no brand data to be correct. |
| A14 | Identifiers are stored as text so leading zeros survive | **PASS for exporter output — now better than the reference files** | Every identifier column in the exporter's output is stored as text: `Document`, `Supplier Site`, `Order No`, `Location`, `Details.Item` and `Tax Code` all carry `str`, with no numeric cells. This is a genuine improvement over the known-good workbooks, which store some identifiers numerically and would already have lost any leading zero. The criterion stays open only in the sense that no corpus-scale output has been checked yet. |
| A15 | The documented RMS master import actually works | **PASS — independently verified** | The guard failures I reported are fixed and the import is now confirmed by direct read-only inspection of the persisted store, not by receipt alone. Re-measured against current code, all five guards pass: compressed size vs 128 MiB; expanded size vs a raised 1 GiB; the supplied column count vs a raised 256; the supplied row count vs a raised ceiling of 250,000; worst member ratio well under 200. The persisted store carries `catalog_items` holding every supplied row as a distinct record with every key column populated, plus the supplied aliases, in the application schema (`invoices`/`catalog_items`/`aliases`/`exports`) rather than the reference extract, timestamped during the reported run and naming the supplied master as its source. Remaining gap is durability, not capability: no regression exercises a wide many-row import, so the raised guards can silently regress. A synthetic generator for that test is available and needs no private data. |
| A12 | The absence of authentication is a stated, enforced boundary | **PASS as a boundary — blocking only for shared deployment** | The delivered scope is a local single-operator pilot on loopback, which never claimed multi-user access control. The boundary is documented where an operator will actually meet it: `WINDOWS_SETUP.md` line 7 states the application has no login or user roles and must run on one access-controlled computer with one authorized operator, and must not be published to the office network or internet; line 146 makes confirming the `127.0.0.1` binding a stop-check; line 429 repeats it for the port-conflict path. Compose binds loopback. Baseline anonymous access findings stand and remain blocking for any shared, networked or multi-user deployment. |

## A6 in detail: provisional, on a conservative reading of an ambiguous instruction

**Status: implemented conservatively, user confirmation outstanding. Not closed.**

The rule being implemented is:

- `Details.Unit Cost` is the invoice net unit cost after discount.
- RMS supplier cost is **matching and validation evidence only**. A difference beyond AED 10.00 is
  reviewable and flagged, but RMS cost is **not substituted into the target**.
- `Header.Total Cost Ex Tax` carries the **invoice's stated ex-tax total**, and the included
  `Details` reconcile **exactly** to it.
- `Order No` stays blank when there is no explicit invoice PO and no explicit RMS PO/order field.

**Why this is provisional and not settled.** The underlying user instruction was a direct chat turn
with no graph-addressable identifier; the coordinator who relayed it checked and declined to invent
one, which was the right call. The quoted instruction directs that invoice cost be used *when the
two do not match*. That establishes a **fallback**. It does not, on its own wording, establish that
invoice cost is used unconditionally.

The two readings agree everywhere except one band: where RMS and invoice cost differ by more than
zero but no more than AED 10.00. The superseded configuration would substitute RMS cost there; the
conservative reading would not. That band is the common case, so the difference is material rather
than academic.

**Why the conservative reading was nevertheless adopted.** It is the only reading internally
consistent with the rest of the contract. If RMS cost were substituted anywhere, the Details would
no longer sum to the invoice's stated ex-tax total, and `Header.Total Cost Ex Tax` — which carries
that stated total — could not reconcile exactly. The stricter reading also never restates a
supplier's price, which the programme audit prohibits outright. It is the safe direction to be
wrong in.

An explicit user confirmation has been requested. **Until it arrives this criterion stays
provisional, and no receipt should describe the pricing rule as a direct user assertion.** All four
known-good workbooks satisfy the conservative rule at one-cent tolerance, so adopting it costs
nothing against existing evidence.

### Rounding convention and the reconciliation tolerance will collide unless tied together

The rounding convention is now an implementation decision (banker's-free `ROUND_HALF_UP`, material
discrepancies rejected) rather than an open business question, which is the right call. It does,
however, interact with the reconciliation check in a way that is not yet reconciled, and the
existing evidence hides the problem rather than testing it.

Measured across all known-good workbooks: every `Details.Unit Cost` is exact at two decimal places
and per-invoice drift between `sum(unit x qty)` and `Header.Total Cost Ex Tax` is exactly `0.00`.
So the goldens do not exercise rounding at all — they are silent on it, not evidence for it.

The collision appears as soon as a line discount produces a unit cost that is not exact at two
decimals, which is the ordinary case for a percentage discount. Storing the unit cost rounded to
two decimals and then reconstructing `unit x qty` admits an error of up to `0.005 x quantity` on a
single line. Observed maximum quantity in the known-good set is 21, which alone yields up to
`0.105` — more than ten times the one-cent workbook tolerance the checker applies. Several such
lines compound.

**Convention adopted (25 September):** retain full invoice net-unit precision in `Details.Unit Cost`,
round each line extension to cents HALF_UP, then sum the rounded extensions. The checker mirrors it.
This keeps the strict tolerance meaningful instead of widening it.

I initially read a two-decimal constraint into this, because all 53 `Details.Unit Cost` values in the
known-good workbooks carry one or two decimal places and none exceeds two. That inference was wrong:
examples that happen to be short do not establish that the consumer forbids more precision, and root
was right to reject it as an invented contract.

Direct measurement of the imported master settles it in the opposite direction: a substantial
minority of its real `unit_cost` values carry three or four decimal places rather than one or two.
The exact rates, and the master's row count, are commercial figures about the user's data rather than
observations of this software's behaviour, so they are recorded in the project's internal channel and
deliberately not reproduced here.
The commercial data this system consumes is already routinely more precise than two decimals, so
retaining captured source precision is the behaviour consistent with the source, not a deviation from
it. What remains genuinely unknown is whether the downstream *import* accepts that precision, and
that is an integration-validation limit to be settled by an actual import result, not a coding
blocker and not a question to put to the user speculatively.

A related limit, correctly raised by root: arithmetic equality alone cannot prove that no RMS cost was
substituted, because offsetting differences across lines can cancel. The reconciliation check is a
necessary condition, not a sufficient one; proving source-cost fidelity needs backend contract tests
that assert the unit cost equals the invoice source value line by line.

The tolerance and the convention still have to be defined against each other, and there were three
coherent ways to do that:

- have the exporter derive `Unit Cost` so that `unit x qty` reproduces the line total exactly, which
  keeps the flat one-cent tolerance honest;
- carry more precision in `Unit Cost` than two decimals; or
- make the acceptance tolerance quantity-aware rather than flat.

The first is preferable if the target consumer tolerates it, because it keeps the workbook-level
check strict, and strictness here is load-bearing: the one-cent tolerance is what detects a wrongly
substituted RMS cost. Loosening it to absorb rounding drift would disable that detection. Whichever
is chosen, this needs a regression with a non-terminating discounted unit cost and a large quantity;
no such case exists in the current evidence.

One consequence constrains the exporter: because included Details must reconcile exactly to the
invoice's stated total, **an invoice cannot be admitted to the target with lines missing**. An
invoice carrying any unresolved line goes to the exception report whole. `target_conformance.py`
treats a Header row with no Details lines as a failure on that basis.

### A13: the superseded reference file is historical, and must stay out of the release

`data/reference/target_conversion_rules.json` encodes a *prefer RMS cost, substitute it whenever it
is within AED 10* rule. The behaviour the application currently implements never substitutes RMS
cost. These diverge on exactly the lines where the two costs disagree by under AED 10 — the common
case.

My earlier reading of this was wrong in its remedy, and root corrected it. I had recorded the fix as
*correct the file, then wire the exporter to load it*. That would have been the wrong architecture
for what is being delivered: a brand-neutral application that anyone can download and point at their
own invoices must not depend on a reference file derived from one brand's commercial data, and that
file is excluded from publication in any case. Correcting a private file the code must never read
would have been effort spent making a hazard tidier instead of removing it.

The right shape, and the one that was built:

- Runtime rules are **explicit persisted Brand setup settings**, entered per brand. The AED review
  threshold is a configured number, not a constant read from a bundled file.
- Aliases are **imported by the operator** through the API/UI, as brand-owned data, and never
  ship in the repository.
- `data/reference/` stays outside the published allowlist, so a cloner starts with an empty system.

That leaves the old file as a historical record of what the rule used to say. It should not be
corrected to state the current behaviour either, because the pricing question is still open pending
the user's clarification (A6) — editing it now would manufacture the appearance of a settled
decision. It stays as-is, unread and unpublished, until that clarification lands.

The acceptance consequence: the thing to test is no longer *does the app load the right file* but
*does a brand configured through setup, with an operator-imported alias set, produce an export that
honours both* — and, negatively, does a freshly cloned tree contain no brand data at all.

## A10 in detail: what publication would actually contain

Two publication paths were simulated. They give opposite results, which is why A10 passes only
conditionally.

**The allowlisted snapshot — clean.** Reimplementing the selection rules of
`scripts/package_source.py` without running it selects 56 files totalling 542,936 bytes. A
signature scan over that set found no credential, no invoice number, no supplier or location
reference and no commercial amount. The credential-pattern hits are all false positives on the
word "token": OCR and matching tokenisation in `backend/matching.py`, `backend/extraction.py` and
`scripts/verify_volume.py`, where `secrets.randbelow` generates synthetic OCR probe tokens. The
two hits in `docs/WINDOWS_SETUP.md` are the instructions telling operators *not* to publish
credentials and `data/reference`, which is correct content. **No private material is in the
allowlisted set today.**

**A plain `git add -A` — not clean, and must never be used.** Simulated with an isolated git
directory so this workspace was never touched. It stages 68 files, including material the current
`.gitignore` does not reach:

| Would be committed | Size | Why `.gitignore` misses it |
|---|---:|---|
| `events-next.json`, `events-last.json`, `events-after-orientation.json`, `events-latest.json` | up to 344 KB | Raw tm8 event dumps; no rule matches them |
| `task-actions-final.json` | 42 KB | The rule is the exact name `task-actions.json`; the `-final` variant slips past it |
| `artifact-publication.json`, `coordinator-review-ready.json`, `docs-final-request.json`, `volume-accepted.json`, `volume-final-go.json` | small | Rules cover `*-receipt.json`, `*-reply.json`, `*-update.json` but not `-request`, `-ready`, `-accepted`, `-go`, `-publication` |
| `public/source-package.json` | 195 KB | Base64 of the entire source archive. `*.zip` excludes the archive itself; base64 inside a `.json` defeats every suffix rule |

Measured honestly, the exposure in those files is **internal coordination metadata, not customer
commercial data**: 1,243 / 782 / 174 tm8 entity identifiers in the three largest, and zero
occurrences of the known invoice numbers, supplier site, location or amounts. The risk is
forward-looking rather than historical — those dumps predate the arrival of the private reference
material on 24 September, and any dump taken from here on would carry the private discussion.

**Two structural weaknesses remain even in the allowlisted path**, and they matter because
`docs/` and `tests/` are being written right now by other owners:

1. `package_source.py` selects whole directories by `rglob` and filters only `.pyc` and `.zip`.
   It does **not** exclude `.xlsx`, `.pdf`, `.sqlite`, `.db`, `.csv` or images, although
   `.gitignore` blocks all of them. A real-invoice fixture dropped into `tests/fixtures/`, or a
   corpus-evaluation document carrying real invoice numbers placed in `docs/`, would be packaged
   silently. Today only three small synthetic CSVs match, which is benign.
2. The packager's own negative assertion checks only for `task-context`, `/data/` and
   `/.runtime/` in entry names. It cannot catch either case above.

Both are cheap to close: extend the suffix denylist to the data-bearing extensions, and extend the
assertion to scan selected file *content* for the private-material signatures rather than only
their paths.

## A14 in detail: the known-good files carry the defect their own criterion names

The design's acceptance criterion for the exact workbook explicitly lists **leading zeros** as a
case that must be handled. The known-good workbooks do not handle it. Every `Details.Item` value in
both known-good files is stored as a number rather than text, as are `Header.Supplier Site` in both,
`Header.Document` in one and `Header.Order No` in the other.

This is reported as a warning rather than a failure because the loss is not provable from the
workbook: once an identifier has been coerced to a number, a leading zero is simply gone and
nothing downstream can tell whether one was ever there. Nothing in these two files is demonstrably
corrupted — one file's invoice number is long enough to be at risk yet still within the range integers
represent exactly, and the other's contains punctuation and so stayed text as it had to.

It matters because these files are the reference the exporter is expected to reproduce. **An
exporter that faithfully reproduces them inherits the defect**, and it will surface as soon as a
supplier site, store code or RMS item ID with a leading zero enters the batch. The fix belongs at
the exporter: write every identifier column as text, and cover it with the leading-zero regression
the design already asks for. Owner: backend.

## A15 in detail: why the documented master import could not succeed, and how it was fixed

The operator documentation presents the raw 179-column RMS master import as a supported release
contract, raises the catalog file ceiling to 128 MiB to accommodate it, and tells the operator to
expect the full supplied row count. The code rejects the supplied master three separate ways. All three
were measured against the actual file, not inferred from the documentation.

| Guard in `backend/service.py` | Limit | Supplied master | Result |
|---|---|---|---|
| Expanded archive size | 100 MB | above the limit | Rejected |
| Header column count | 100 | 179 columns | Rejected |
| Data row count | 100,000 | above the limit | Rejected |

The column guard fires first, at the header, before a single data row is read.

The raised 128 MiB ceiling does not help and is actively misleading for XLSX input, because the
binding constraint is the **expanded** size rather than the uploaded size. A compressed workbook
comfortably inside 128 MiB still expands past the 100 MB guard, and the supplied one does. An operator following the documented sequence gets the file accepted on size and then
rejected on structure.

To be fair to the documentation, it does not claim the import is proven — it says the contract
"must pass the approved-build release test" and that "documentation alone is not a test result".
That caution is well placed. But the gap was larger than unproven: against the build as it stood when
I wrote this, the documented step was **impossible**, and it sat at step three of an eight-step
operator sequence, so everything after it was unreachable.

> **Superseded — resolved 25 September.** The guards were subsequently raised and the full master
> import was confirmed working by direct inspection of the persisted store, which is why A15 passes
> above. This paragraph is retained as the record of why the change was needed; do not read it as the
> current state of the build. Either the three guards are raised deliberately, with the memory and
denial-of-service implications of an in-memory expansion many times the original guard assessed, or the documentation should direct
operators to the normalized projection instead and stop presenting the raw import as available.
Owner: root, with the backend worker.

## A8 in detail: the first real movement, and what the numbers do and do not say

The extraction owner has reported the first measured improvement on the programme's largest gap.
On a 19-document private layout sample, documents yielding any rows rose from 2 to 11, and
candidate rows from 9 to 83. Twenty extraction tests pass on the production image. The reported
mechanism is fixed-position table parsing driven by explicit headers, joins for wrapped
descriptions, source-only UPC / item code / UOM / net-unit fields, and a conservative document
classification that admits an `unknown` outcome rather than guessing.

This is genuine progress and it is claimed correctly: the owner explicitly declines to call it
accuracy. Two things should be held alongside it so the improvement is not over-read.

**The reconciling fraction depends on which denominator is used.** Of the 83 candidate rows, 28 are
fully populated, and 13 of those 28 reconcile quantity × source unit price to the source line
total. Measured against fully populated rows that is roughly half; measured against all candidate
rows it is 13 of 83, closer to one in six. Neither figure is an accuracy rate, because the number
of true source lines in the sample is not established — an extractor that misses a line entirely
is not penalised by either ratio.

**The sample is not the corpus.** These 19 documents are a layout sample. The 179-file corpus and
the 44 OCR-flagged PDFs are still in evaluation at a maximum of two workers. Until that completes,
the baseline of 106 of 114 invoice candidates yielding zero lines remains the corpus-level figure
of record, and this criterion stays failed.

The right next measurement is a per-document comparison against known source line counts, so that
missed lines are visible rather than silently absent from the denominator.

## Residual limits of this record

Stated plainly, because an acceptance record that hides its own boundaries is worthless.

- **Early in this engagement no test run was performed by me**, because backend and extraction work
  was in flight on a shared, bounded host and rerunning suites was declined at the root session's
  instruction. That limit was lifted later: I independently ran the contract checker on every
  delivered workbook, executed a suite inside a clone-equivalent snapshot, read the persisted catalog
  store directly, and hashed the six runtime modules inside the delivery image itself.
- **No OCR, no page rendering and no corpus extraction were run by this session.** The extraction
  owner held that budget exclusively throughout. The corpus figures in this record come from that
  owner's final run against the frozen extractor; I verified the receipt's hash and confirmed its
  declared extractor matches the shipped code, but I did not reproduce the run.
- **A2 proves the contract is satisfiable, not that the application satisfies it.** Four hand-built
  workbooks passing is evidence about those four files only.
- **A11 was assessed by inspection, not by installing on a clean Windows machine.** No Windows host
  was available. Until someone completes a from-zero install by following only the document, the
  installation claim is unverified. A11 passes because both guides now disclose this limit prominently,
  which is the most an inspection-based review can honestly certify — it does not mean the procedure
  has been shown to work.
- **No accuracy figure is asserted anywhere in this record.** Item-name match accuracy against the
  real corpus is not measured. The historical 1,000-file synthetic intake demonstrated queue
  durability, not accuracy. Nothing in this delivery is machine learning training or fine-tuning,
  and it should never be described as such.
- **Security findings are carried from the audit, not re-tested.** The 181 Debian advisory matches
  remain package-level candidates, not proven exploitable vulnerabilities.

### The contract also holds through the live operator workflow

Separately from the exporter round-trip, a live browser run now exercises the whole operator path —
brand settings, master import, upload and extraction, classification, review, approval, and an actual
XLSX download — and I verified the downloaded file rather than the run report.

It is conformant on my own checker: exactly `Header` / `Tax_Breakdown` / `Details` in that order, one
invoice, one tax row, two detail lines, arithmetic reconciled. Identifier typing holds through the
full round trip, which is the part worth noting: `Location` arrives as the string `0001` with number
format `@`, so a leading zero survives extraction, storage, export, HTTP download and reopening. That
is the failure mode A14 exists to catch, and it is the hardest place to catch it, because every layer
in that chain has its own opportunity to coerce an identifier to a number.

This is synthetic-data evidence about the *plumbing*. It says the workflow an operator will follow
produces a contract-conformant workbook end to end. It says nothing about extraction accuracy on real
invoices, which remains A7 and A8.

### What the reference round-trip does and does not prove

Worth stating precisely, because the round-trip is easy to over-read. It was run against the two
already-reviewed target workbooks, not against the original invoice PDFs. It therefore demonstrates
that the exporter emits the exact contract and reproduces reviewed values cell for cell. It does not
demonstrate that the parser, given the source document, arrives at those values — no claim about
source parsing can be made from reviewed targets alone.

The source documents for both reviewed targets have since been identified and confirmed present, so
the parser-versus-reviewed-target regression that *would* close that gap is now constructible. It
belongs to the extraction owner, and is deliberately not run here while that work is active. That
owner is currently prioritising Factur-X embedded XML and a discount-paired source regression ahead
of the full corpus rerun, which is the right order: a discount-paired case is the one that exercises
the rounding convention against a real document rather than a constructed one.

### A question the round-trip surfaced, since settled: `Details.UPC` is empty

Every `Details.UPC` cell in the exporter's output is blank. That is **not** a defect: all five
reviewed reference workbooks also carry UPC blank (0 of 13 and 0 of 7 lines), so the exporter is
faithfully reproducing what the references do, which is exactly what a round-trip should show.

It is worth recording only because the data to populate it now demonstrably exists. The imported
catalog holds a UPC for these items — the first sampled `Details.Item` resolves to a real 13-digit
UPC in `catalog_items`. So leaving the column blank is a choice inherited from the references rather
than a limitation, and if the downstream consumer ever wants UPC populated, nothing needs to be
collected to do it. Not an acceptance blocker, and not something to change without the consumer
asking.

> **Settled — 25 September.** That last sentence turned out to matter. A later build did begin
> populating the column, because matched catalog rows made the values available; the output then
> differed from all five reviewed references in a column the consumer may key on. The behaviour is
> now a per-brand `include_upc_in_export` setting, off by default so the column stays blank, to be
> enabled only once the receiving system confirms it accepts populated UPCs. I verified both
> positions and confirmed that toggling on and back off returns a byte-identical workbook.

## Post-freeze findings: five gates between a scanned invoice and an accepted workbook

**Added after the freeze, 25 September 2026.** These were found while investigating a single real
three-decimal-currency invoice from a supplier whose master rows are not AED-denominated. They do not
revise any verdict above — no criterion was re-run — but three of them are defects rather than
limitations, and one materially undermines the reasoning behind **A6**. Recording them here is the
honest alternative to leaving a frozen record that reads cleaner than the system behaves.

The investigation asked one question: with a perfect extractor, would this document reach an accepted
workbook? The answer is no, and extraction is only the first of five independent gates.

**Gate 1 — document classification rejects a common invoice heading.** The classifier's invoice title
and phrase rules admit a closed set of qualifiers. A heading widely used in Gulf trade to denote an
invoice issued on credit terms is not among them, and the title pattern is anchored, so it matches
nothing. The only rule that scores is the invoice-number field rule, which lands one point below the
threshold that separates a classified document from `unknown`. Approval requires the type to be
exactly `invoice`, so every document carrying that heading is unapprovable. It is invisible in the
corpus figures because these documents fail as `unknown` rather than as extraction errors. Adding the
qualifier to both rules was verified against a regression matrix: genuine credit notes and memos
continue to classify as credit notes and do not match the widened invoice pattern, and no heading
matches both. Routed to the extraction owner. *(Affects A8's denominator, not its method.)*

**Gate 2 — the subtotal derivation has a zero-tax blind spot.** The dominant corpus rejection reason
is an unavailable subtotal. The sole derivation path requires both a grand total and a tax total to be
present, and derives the subtotal by subtraction. An invoice that prints no tax at all yields a tax
total of `None` rather than zero, so the derivation is skipped and the document is rejected even when
it carries a clean printed total and a complete line table. Non-VAT and zero-rated jurisdictions fail
this systematically. Treating explicit absence of tax as a zero, under its own provenance value,
restores the derivation while leaving the reconciliation check fully intact — the line extensions are
still independently compared against the printed total. Deriving the subtotal from the line extensions
instead would make that check circular and must not be accepted. Routed to the extraction owner.

**Gate 2, resolved 25 September — the circularity I warned about above is now measured, and it is
present on every document the gate currently passes.** The extraction owner added subtotal and tax
provenance to the evaluator and replayed the corpus. I verified the replay artifact myself rather
than accepting the summary: its recorded extractor hash is unchanged from the frozen extractor, so
this run added measurement and changed no extraction behaviour; its completion invariant holds
exactly (selected equals the document count equals completed plus failed, with no failures); and I
recomputed every provenance class count from the per-document rows rather than reading the
pre-aggregated totals. All recomputed counts reproduced the recorded ones exactly.

The result. Of the documents that the corpus records as having reconciled their subtotal, all but one
derive that subtotal as printed total minus a tax total that was itself summed from the line items.
That is the circular case: the line extensions are being checked against a figure computed from the
line extensions, so the check cannot fail and proves nothing. The single non-circular one derives its
subtotal against a *printed* tax label, and it is not among the strict passes.

**The sharper finding, which I derived and the summaries I received did not state.** I joined the
strict-core pass set to the provenance classes by document identity. Every strict pass is circular,
and no strict pass is anything else — the pass set and the circular reconciled set are the same set.
There is therefore no document anywhere in the corpus that both clears the strict core gate and rests
on an independently evidenced subtotal. The count of such documents is zero.

**What this does and does not mean.** It does not mean those extractions are wrong. The reviewed
carbon-copy comparison shows a document of this class matching its source exactly on every quantity,
net cost and line total, with extensions reconciling independently. It means the *reconciliation
check* is not evidence. Gate 2 has been self-satisfying on the entire strict pass set, and the strict
count I have cited in every report as preserved by identity must from here be reported as preserved
but circular. My C1 finding stands as a factual identity-preservation result and is not withdrawn;
the significance I attached to it is reduced, and that reduction is mine to state, not root's.

Two further points from the same artifact. The safe provenance class — explicit absence of tax
recorded as zero under its own provenance value, which is the remedy I proposed above — occurs on no
document in this corpus at all; it is currently exercised only by a private reviewed document. And a
small number of documents carry line extensions with non-zero third decimals, which is a rounding
exposure against a two-decimal target and is worth its own check before export.

Criterion C5 was pre-registered as unverifiable for want of this evidence. It is now verifiable, and
it **fails**. I pre-registered three readings before the artifact existed: a falling reconciled count
would mean the gate had been over-crediting itself. The clean count fell from fourteen to one, and
the clean-and-strict count fell to zero, so that is the reading that applies. Routed to the
extraction owner; not a blocker on extraction correctness, and a blocker on any claim that the
zero-tax subtotal gate has been satisfied.

**Gate 3 — OCR runs at roughly half the usable resolution.** Scanned pages are rasterised at a fixed
scale equivalent to about 144 DPI, against a documented working floor near 300 DPI for clean print;
degraded dot-matrix and carbon-copy originals need more, not less. A guard intended to upscale small
inputs is keyed to an absolute pixel width that a full page marginally exceeds, so for exactly the
documents that need it the upscaler never fires. Grayscale conversion is the only preprocessing: no
binarisation, no deskew. Page segmentation assumes a single uniform text block on documents that are a
multi-column header above a line-item table. Raising the render scale multiplies pixel counts
quadratically and will collide with the existing per-page and total-pixel ceilings, so the ceilings
must be raised deliberately for the OCR path — otherwise a quality defect becomes an availability
defect. Routed to the extraction owner.

**Gate 4 — the supplier cannot be resolved from the document.** Supplier identity is required for
approval and is supplied by the operator at upload; it is not extracted. The supplied master does not
store supplier trading names, it stores coded identifiers, so searching it for the name printed on an
invoice returns nothing. Nothing in the application bridges the two, and the gap repeats across every
supplier in the master. The same physical goods also appear under more than one supplier record in
different markets, so a mis-selection is both easy and consequential. The application already holds
every barcode in the master and receives documents whose lines carry barcodes, so proposing the
supplier from barcode evidence — and surfacing the ambiguity when candidates overlap — would convert
an unanswerable lookup into a confirmation. That is new scope and a user decision, not a patch.

**Gate 5 — the cost comparison assumes a single-currency master, and the master is multi-currency.**
This is the most consequential finding and it reopens reasoning that had been filed as settled policy.
The comparison is enabled on the basis of the *invoice's* currency alone, which is sound only if
recorded costs are always denominated in one currency. In the supplied master they are not: supplier
records carry a currency marker, several currencies are present, and most rows are not
AED-denominated (the share is withheld here because it describes the master's content). Identical items priced under suppliers of different currencies differ by an
order of magnitude consistent with exchange rates rather than by any plausible margin, and aggregate
cost magnitudes per currency agree with that reading. Two consequences follow, in opposite directions.
The comparison is *refused* where it is valid — same-currency invoice and master rows are directly
comparable, and against the correct supplier the observed relationship is a small constant ratio
consistent with a stable commercial margin, exactly what the check exists to confirm — and each such
line is instead forced to manual acknowledgement, permanently, across the majority of suppliers. That
is not conservatism; it discards a working check and bills the operator for it, and the reviewer is
asked to acknowledge the absence of evidence rather than to examine any. Conversely the comparison is
*performed* where it is invalid: the currency of the master rows being compared against is never
tested, so an AED invoice matched onto non-AED rows is compared against incommensurable figures, where
a large real discrepancy can fall inside an absolute per-unit tolerance and be approved silently.
Ambient exposure is small — only a negligible fraction of rows are unscoped by supplier — but operator
mis-selection is the realistic path, and Gate 4 makes that likely. Gates 4 and 5 compound.

The minimal correct fix requires no exchange rate and weakens nothing: record the currency of catalogue
costs at import and require invoice and master currency to be equal before comparing. Inferring the
currency from a naming convention is too fragile to ship. Pending the owning business confirming that
supplier currency is authoritative, the existing gate must stay as it is and no claim of automatic
same-currency comparison should be made.

**A separate policy question, raised and not answered.** The tolerance is absolute and applied per
unit. On low-value, high-volume goods a systematic proportional discrepancy stays well inside it while
accumulating materially across a line's quantity. Whether the threshold should be relative, or applied
to the line extension, is a commercial decision rather than a defect.

**What these five do not change.** The three-tab contract, the exporter's conformance to it, identifier
typing, and the all-or-nothing inclusion rule are unaffected; the reviewed invoice's own arithmetic was
verified independently and is internally consistent, its units agree with the master, and its extensions
reconcile to its printed total under both the shipped and the proposed rounding conventions. The gates
sit between extraction and approval, not in the workbook construction that A1 to A4 accept.

### Later evidence on Gates 4 and 5, from the catalogue itself

Appended after the section above, and after read-only inspection of the supplied catalogue rather than
of the code alone. No criterion was re-run and no verdict moves. Figures are deliberately omitted: the
findings below are stated as mechanisms because the measurements behind them are commercial.

**The currency question is no longer open.** The section above recorded that costs appear to be
denominated per supplier, and held that inferring currency from a naming convention was too fragile to
ship and that the owning business should confirm the reading before anything changed. The reading is
now confirmed from the data, by evidence independent of the naming convention. A separate territory
field carried on each row agrees with the convention, and for the smaller currencies agrees with it
almost exactly, without having been used to derive it. More decisively, a large population of items is
stocked under suppliers of two different currencies at once; across the genuinely priced members of
that population the two costs stand in a ratio matching the exchange rate between those currencies,
and only a negligible share stand near unity. A single-denomination catalogue would produce the
opposite distribution. The conclusion is therefore established rather than inferred: catalogue costs
are denominated in the supplier's own currency, and the comparison gate's single-currency assumption
is wrong for this deployment.

What does not change is the recommended fix. That the convention is *reliable* does not make it a
sound thing to depend on: it remains a naming convention, and a supplier created tomorrow without the
suffix would silently acquire a default denomination. Record the currency of catalogue costs at import
and require invoice and master currency to be equal before comparing. The convention is now good
evidence about what the data means; it is still not a good key to compute on.

**A second defect, not previously recorded: placeholder costs are treated as prices.** A material
minority of catalogue rows carry a token near-zero unit cost that is plainly a placeholder for "not
priced" rather than a price. Nothing in the comparison distinguishes these from real costs. Two
failure modes follow, and they mirror the pair already described for currency. A placeholder compared
against a real invoice cost yields a variance equal to the whole invoice cost and trips the tolerance,
so the operator is shown a cost alarm generated entirely by absent data; at volume this is the fastest
route to the review step being dismissed by habit. Conversely, on a low-value line the placeholder
falls *inside* an absolute per-unit tolerance and is reported as agreement, which records a cost
confirmation where no cost was ever held. The second is the more serious, because it is silent.

These two compound in a specific and unfortunate way. Placeholder costs are not evenly spread across
currencies; they are concentrated in the one currency for which the comparison is enabled at all. The
single path on which the check runs is therefore the path whose underlying data is least trustworthy,
and the paths with the better cost data are the ones on which the check is refused.

**Context for how this arose.** The catalogue's selling currency is uniform across every row, and it is
not the currency the comparison is gated on. The gate was in all likelihood inherited from a different
deployment rather than chosen for this one. That is not a criticism of the implementation so much as a
reason to stop treating the single-currency assumption as a conservative default: in this deployment it
disables the check for the home market and enables it where the data is weakest.

**A question raised during the engagement, now closed.** It was asked whether the tax code required for
approval might already be carried in the item master, which would remove it from the operator's setup
burden. It is not. The catalogue schema was read in full, across both of its item tables, and contains
no tax field under that or any other name. The per-supplier rule remains the only source, and the
setup burden described for Gate 4 stands as stated.

### Later evidence still: two structural gaps in the supplied master, and the first independent check of supplier resolution

Appended after the sections above, from read-only inspection of the supplied master and of the
documents' own stored text. No criterion was re-run and no verdict moves. As before, findings are
stated as mechanisms because the measurements behind them are commercial.

**The master's unit-of-measure column carries no information.** Every row in the supplied item master
holds the same single unit value. This is not an importer default — the import path was searched for a
fallback write and contains none; the column arrives that way from the source file. The consequence is
not cosmetic. The matcher raises an "attribute appears on only one side" flag when a unit is present on
one side and absent on the other, and because the invoice side never carries a unit at all, that flag
fires on every line in the system. It reads like a discriminating signal and is a constant.

Two separate safety rules were drafted during this engagement keyed on that flag. Had either shipped,
one would have disabled the automatic-match tier outright and the other would have suppressed the
cost-variance figure on every line — in both cases to guard against an ambiguity affecting a handful of
lines. Both were caught before merge, and neither was caught by reading the rule: they were caught by
asking what proportion of rows the predicate actually fires on. That question should be a standing
requirement for any rule keyed on this column. The deeper consequence is that this deployment cannot
check a pack-versus-single question against its master at all, because the master does not record the
answer. Rules written against the column are therefore either dead code or off switches, and the
distinction between the two is worth stating explicitly wherever one is retained for future data.

**The master carries no human-readable supplier name.** Supplier rows hold a coded name only. There is
no field on which an invoice's printed supplier name can be joined to a master supplier directly. That
is why the resolver matches on an alphabetic prefix of the coded name, and why the check described next
had to be performed the same way.

**Supplier resolution has now been checked against the documents themselves, for the first time.**
Until this check, the evidence that the resolver chose the right supplier was circular: the supplier is
chosen partly by which supplier's catalogue rows best match the invoice's line descriptions, and the
quality of the outcome was then reported in terms of how many lines matched. The check breaks that
loop — the supplier name printed in each document's own stored text was read and compared against the
supplier the resolver selected, without reference to any matching result.

On every invoice where the resolver made a choice, the choice agrees with the name printed on the
document, at the level of the supplier family. On the invoices where it declined to choose, it declined
rather than guessing. The resolver is, to its credit, honest about itself: it emits a warning naming
the heuristic on every path it takes, and it refuses to resolve when its evidence does not single out
one candidate strictly. The circularity was in how its output was reported upward, not in the function.

Three qualifications, each of which matters more than the result:

- **The agreement reaches the supplier family, not the supplier site.** The master holds several sibling
  suppliers sharing the coded prefix that the printed name reduces to, and the document does not name
  which one. That finer choice is still made by the circular step and remains unverified in principle.
  It is inert on this corpus because the siblings are near-empty stubs set against one substantial price
  list, and because the few items they share carry no cost divergence — both checked, not assumed.
- **The check exercised one supplier family, and that family was uncontested.** Every invoice in the
  examined corpus resolves to the same family, so this is one success replicated, not many independent
  ones. The master contains a substantial number of prefix groups in which the same mechanism faces a
  genuine contest between two or more well-populated suppliers, and across suppliers sharing a prefix
  there is a large population of shared items whose recorded costs diverge materially. That shape was
  subsequently tested by construction — see immediately below — with a result that is reassuring about
  the dangerous failure mode and unflattering about throughput.
- **The prefix comparison is a "starts with" test** against a name key from which legal suffixes have
  been stripped. A printed trading name that merely begins with another supplier's prefix would pull in
  that supplier's siblings on a false premise. The master side of this is bounded; the printed side is
  not.

**The contested case was then tested by construction, and the resolver refuses rather than errs.** A
synthetic invoice was built for each well-populated sibling in every contested prefix group, with the
printed supplier name set to the shared prefix so that the resolver took the same path the real
invoices took, and with the line descriptions drawn from that sibling's own catalogue rows so that the
correct answer is known by construction. Each sibling was tried twice: once with lines sampled from all
of its rows, and once — the case designed specifically to defeat the tie-break — with lines sampled
only from rows it *shares* with its siblings. Across every trial, the resolver never once selected a
sibling other than the correct one. Where it could not distinguish, it returned no supplier.

The reason is in the code rather than in the sample. The tie-break requires the leading candidate's
evidence to be strictly greater than the runner-up's. A description stocked by several siblings
contributes evidence to all of them, so on a deliberately confusable invoice the counts tie and the
condition fails. Only rows exclusive to one sibling can open a margin, and when they do they point at
that sibling by definition. The mechanism is therefore not "choose the best-matching supplier" — which
is how its own docstring reads — but "choose the only supplier with distinguishing evidence, otherwise
refuse". The implementation is stricter than its documentation, which is the right direction for the
discrepancy to run, and the docstring should be corrected to match rather than the other way round.

**The cost of that strictness is throughput, and it is not small.** On contested groups roughly half of
the typical synthetic invoices resolved to no supplier at all, against none of the real invoices from
the uncontested family. Unresolved documents fall back to whole-catalogue matching, which a change on
the pending branch correctly prevents from ever reaching automatic acceptance. The practical
consequence is that for suppliers in a contested group, the automatic tier largely disappears and the
operator confirms more lines by hand. Any improvement figure quoted from the examined corpus is
measured on the uncontested case and should not be presented as representative of the contested one.

**What this test does and does not establish, stated as strictly as the test itself.** The ground truth
used is which sibling's catalogue the descriptions were drawn from — the same *kind* of evidence the
resolver consumes. What is therefore proven is that the tie-break is self-consistent and safe: given
lines genuinely belonging to one sibling it returns that sibling or nothing, never a different one.
That is a real and non-trivial property, since the mechanism could easily have drifted toward whichever
sibling holds more rows, and it rules out the failure mode that would silently corrupt data. What is
*not* proven is that the resolver identifies the real-world issuing entity on a contested group; that
would require a genuine invoice from such a supplier with the printed name checked against the page,
and no such document exists in either corpus. The status moved from "untested" to "tested for the
failure mode that would corrupt data, which does not occur; untested for real-world entity identity on
a contested group". Both halves travel together or neither should be quoted.

The defensible statement is that supplier resolution was independently checked against the documents
for the first time and passed on the cases available. It is evidence that the approach works. It is not
evidence that it is reliable, and it must not be described as verified.

**A related defect the check hardened.** Where a document prints a supplier identifier that the master
does not contain, the application warns and then proceeds to scope matching to that absent supplier,
yielding a near-empty candidate set and, predictably, no matches. This was previously treated as a
malformed-input edge case. The check showed the identifier concerned is genuinely printed on the
document — so this is the normal path for any supplier the master has not been updated for, including a
new supplier or one whose identifier changed at the most recent periodic re-import. Those are precisely
the documents an operator most needs help with, and the system answers them with a silent, nearly empty
catalogue rather than with a declared failure.

**Character corruption in the master originates upstream of this application.** A minority of master
rows carry mis-decoded accented characters, in a signature consistent with text encoded once and then
decoded as a different single-byte encoding. The corruption is present in the source file as received:
it was confirmed by reading raw cells of the supplied workbook independently, from two separate copies,
rather than inferred from the imported rows. **The import is faithful.** The distinction matters for
what the deployment is told about its own data, and it determines the fix: a conservative repair at
import together with a warning naming the upstream export, not a correction of this application's
reading of the file.

**An undocumented coupling between two constants is the only thing holding a group of lines out of
automatic acceptance.** The matcher caps the score of a candidate whose attributes are incompletely
known, with the stated intent of keeping such a line reviewable, and separately requires a score above a
fixed threshold before accepting a fuzzy match automatically. The cap sits a few points below the
threshold, and that gap alone prevents a group of incompletely-known lines from being accepted without
review. Neither constant references the other, and no test asserts the relationship. A routine tuning
change to either would widen automatic acceptance silently, with nothing failing. The two are being
tied together by an invariant test rather than by a comment, on the reasoning that a comment informs a
careful reader while a test stops a careless one.

**The contradiction underneath all of this, recorded because it is the clearest instance of the pattern
this record keeps finding.** On the path where a line matches exactly one catalogue candidate, the
application accepts the match automatically and reports full confidence — including for lines whose
scores it has just capped precisely because it judged their attributes incompletely known. The comment
at the cap states the intent to keep those lines reviewable; the decision taken a few lines later
overrides that intent and reports certainty instead. The system is not failing to detect these cases.
It detects them, records the doubt, and then discards it. That is the shape of nearly every defect in
this record: each layer degrades toward silent acceptance rather than toward review, and the reported
confidence is highest exactly where the evidence for it was deliberately limited.

### The first defect in this record to be closed under mutation, and two corrections to how it was measured

The three defects named in the section above — the unknown-attribute check that keyed on a reason
string, the unverified supplier id that reached a silently near-empty catalogue, and the cost
comparison that printed a figure where the unit was unsettled — have been fixed on a branch and
reviewed independently. This entry records the outcome and, more importantly, what the evidence for
it is worth. It revises no verdict above.

**What makes this different from every other fix in this record.** The reviewer who found the
original defects re-derived the work rather than reading it: their own checkout, their own
environment, mutants applied to the full combined suite rather than to the two files the
implementer had used, and a replay against their own corpus that neither the implementer nor the
coordinating session could reach. Five separate mutations were introduced, each disabling one
limb of the new behaviour, and every one of them caused at least one named test to fail. The
review that opened this thread found most of its mutants surviving in silence — a guard that was
correct but unprotected, so that the next refactor would remove it without a signal. This is the
first occasion on this project where that could not be done. The distinction matters because a
fix that no test defends is indistinguishable, six months on, from a fix that was never made.

**The first correction: a guard was measured where it could not fire.** The replay reported that
no line lost its cost comparison under the new rule. That was true and it was measured over the
lines the system had already matched automatically — the one population in which the new rule's
trigger is unreachable, because the far larger set of merely suggested lines carries no mapping
for the rule to examine. Re-measured over the path the product actually requires, in which an
operator confirms every suggested line before anything can be exported, the rule engages on
eleven of the two hundred and seventy-one lines, spread across seven of the twenty documents.
Those lines lose their printed cost comparison and are flagged for review; approval is not
blocked. That is a rule with a modest reach, which is the intended result — but "nothing was
affected" and "eleven lines are affected on the path we ship" are different statements, and only
the second one describes the delivered system.

**The second correction, which needed correcting twice.** The reviewer concluded that the new
attribute guard does nothing against the supplied master and becomes meaningful only against some
future one. That was wrong, and the first attempt to correct it was also wrong, in the same
direction and for the same reason. The guard has a second limb, evaluated before the attribute
comparison, which demotes a line when the invoice states no unit and the matched master row
describes a multi-unit pack. Counting how many rows of the master carry pack wording appears to
give that limb a rate, and it was reported as one. It does not. The demotion applies only where
the invoice line and the master row share an identical normalised description, and pack wording
is derived from that same normalised description, so on that path the two pack sets are always
equal — verified over every exactly-matching candidate pair in the corpus, with no exceptions.
A pack-bearing master row is therefore reachable on this path only by a pack-bearing invoice line,
and the master's own rate never enters the calculation.

The guard's real trigger is narrower and much easier to reason about: **the invoice line itself
names a pack size, states no unit, and matches a master row exactly.** No line in either corpus
names a pack size. The absence of demotions is not a low rate rounding to nothing; it is a
structural property of these particular documents. Two consequences follow, and the second is the
useful one. The guard does not scale with the number of invoices processed, as a per-row rate
would imply — it scales with how often a supplier prints pack sizes in line descriptions, which
is none of the time for the family examined here and is common practice for wholesalers and
distributors. And it is therefore well aimed rather than rare and arbitrary: it engages exactly
on multipack lines, which is precisely where per-pack and per-unit pricing are ambiguous and
where an assumed unit would be expensive to get wrong.

That this correction had to be made twice, by two people who had each spent the day insisting
that others state the population a number was measured over, is the most useful thing in this
section. A count can be accurate, reproducible and still answer a different question than the one
being asked of it.

**Why the verdict does not move.** Both corrections were found by asking what share of the
population a new rule's trigger actually fires on, and comparing that to the sample it was
measured in. That question is the same one that, earlier in this record, exposed a proposed safety
rule keyed on a column holding a single value throughout the master — a rule that would have read
as a careful safeguard while functioning as an off switch. A guard that fires on everything and a
guard that fires on nothing fail in opposite directions and look identical in a replay that cannot
distinguish them. Three closed defects, a completed independent review and a suite that now
resists mutation are real improvements to the code's trustworthiness. None of them changes what
the system does for an operator: no document in the corpus reaches an export without manual work,
and the number that do reach it after an operator has confirmed every suggested line is unchanged.
The verdict in this record stands.

## Post-freeze findings, second round: why the numbers in this record were unreliable, and the constraint that actually holds Metric 1 at zero

Three findings below are about the code. The first is about this record itself, and it
should be read first, because it is the reason the other two took as long as they did.

### This program has no continuous integration, and that is a root cause rather than a missing nicety

There is no `.github/workflows` directory on `main`. A pull request merged during this
round with an entirely empty status-check rollup: there was no gate that could have been
red. Every test figure this record has ever quoted is therefore whatever a human chose
to run locally, on whichever tree they happened to have.

That is the structural explanation for a specific failure of this record, not a general
complaint. Two test figures taken by two reviewers disagreed for hours with nothing
noticing, because nothing was positioned to notice. A failing test can sit on `main`
unremarked for the same reason, and one does: the end-to-end text-extraction and
matching flow test fails on `main`, before and after the supplier-resolution fix, because
the frozen extraction line parser reads a pack size of `250ml` as a quantity of 250 with
unit `ML`. It has a follow-up of its own. The point for this record is that its redness
was discovered by a reviewer reading output, not by the project.

Consequence for how this record should be read: every measurement in it needs its commit
and its corpus stated in the same sentence as the number. Where earlier sections state a
figure without them, treat the figure as unverified rather than as wrong.

### A measurement was attributed to the wrong commit, and the correction is the general rule

A root cause for the zero auto-match rate was diagnosed, stated, and withdrawn within the
same evening. The mechanism described was real on the tree it was measured on. It was
already fixed on the branch waiting to merge. The figures were all correct; the frame was
stale.

No measurement in this record now stands without its commit and its corpus. This is not
a courtesy to future readers. A number that is arithmetically right and frame-less can
describe software nobody is running, and it reads exactly like a current finding.

A second instance of the same class, recorded because it recurred three times in one
session between two independent reviewers: a count that is true of an entire supplied
table was carried into a question about one narrow slice of it. In each case the count was
right and the population was wrong. Any table-wide count used to answer a scoped question
is now re-taken inside the scope before it is quoted.

### The privacy control cannot see the thing it is supposed to protect

The handoff package selects documentation files, runs a secret scan over them, zips them,
and base64-encodes the zip into a JSON asset that the preview build requires. The secret
scan's pattern list covers private keys, hosting tokens, and cloud access key ids. It does
not cover capabilities or identifiers — a document share link, an account id, an absolute
path under a home directory — and it does not cover the commercial figures this record is
already careful to exclude.

The failure is not the missing patterns. It is that every privacy check performed in this
program greps the source tree, and the artifact is base64. A tree grep returns clean
whether or not the artifact is clean, so the check cannot distinguish a safe artifact from
an unsafe one. That is the same shape as the other defects found this round: a control
that returns a benign, normal-looking value instead of doing its job.

Verified rather than reasoned about: every package ever published was decoded and searched.
The published one — 52 files, zip `sha256 9b4cc2e7…` — contains no share link, no account
id and no supplied-table figure. A later, never-published local build does contain one
such figure. So this is a near-miss, and it stays one only until the next build. The
guard belongs in the packaging script's pattern list, where it becomes a build failure
rather than a convention, and the check itself has to run against the decoded package.

### The constraint that holds Metric 1 at zero is three gates that compound

With supplier resolution fixed, most real invoices now resolve a supplier and the binding
constraint moved. Three gates in the matcher now hold the automatic match rate at zero,
and each one alone accounts for almost none of it:

1. A score cap applied whenever any attribute is unknown sits below the threshold an
   automatic match must clear. A capped line can never clear the bar.
2. The unknown-attribute gate consults no score at all. It was true of 312 of the 333
   top candidates on the resolved-supplier corpus, and of 205 of 208 on a second corpus
   measured independently by the other reviewer. So the fuzzy automatic path is closed on
   the overwhelming majority of real lines and no threshold change reaches them — but it
   is *not* closed on all of them, and the earlier wording in this record which said
   "every single top candidate" was an overstatement that has been corrected here.
3. The margin rule requires a gap to the runner-up. Of 333 lines from resolved-supplier
   invoices, 139 have a top-two tie on score, and 133 of those ties are between two rows
   that carry the *same* item id. The export consumes the item id. The matcher is refusing
   to match automatically because it found the right item twice.

Gates 1 and 2 do not key on one named attribute. Both test whether the set of unknown
attributes is non-empty, whatever is in it. One attribute dominates that set, and its
column in the supplied table holds a single value on every row: a predicate keyed on a
constant is an off switch, not a rule, because it fires on every line that does not state
that attribute, and most suppliers in this corpus do not print it.

The distinction matters for anyone acting on this section, because the dominant attribute
is not the whole of it. Composition of the unknown set on the top candidate, measured over
the 333 resolved-supplier lines: 300 carry that one attribute alone, and 12 carry it
together with a size unknown. Repairing the constant column therefore clears gates 1 and 2
for 300 lines and leaves **12 still gated for a different and genuinely separate reason**.
An independent measurement on a second corpus found the same shape at a larger share — 18
of 205 gated lines carrying a non-dominant unknown, 2 of them with no instance of the
dominant one at all.

This is exactly the misread this section exists to prevent. Someone who repairs the
constant column, expects gates 1 and 2 to be gone, and finds a residual still capped will
reach for the warning below and conclude the fix failed — when it succeeded on the large
majority and hit a second, smaller cause. The residual is a separate item of work, not
evidence against the first fix.

**Measured, and it is the important number here: removing the cap alone, with nothing else
varied, changes zero line statuses.** Deduplicating candidates by item id before the margin
is computed makes up to 102 of those 333 lines margin-eligible. Any partial fix in this
area will move scores without moving Metric 1, and will therefore look like the fix did
not work.

Two bounds on that uplift, stated because the figure invites over-reading. Every invoice
that resolves a supplier in this corpus resolves the *same* supplier, so 102 of 333 is one
supplier's behaviour and not a property of the software; it is re-checked the first time a
second supplier resolves. And the deduplication cannot be unconditional — with the supplier
unresolved the candidate set spans suppliers, the duplicate groups disagree on cost, and
collapsing them would put an arbitrary cost in front of an operator on the money path. It
is conditioned on a resolved supplier, or on cost agreement within the group.

Recorded as retracted so it is not re-raised: it was proposed that the cap manufactures the
ties the margin rule reads. The mechanism is genuine — the cap is not order-preserving and
no uncapped score is retained — but the predicted effect was measured twice, independently,
and is nil. What survives is smaller: because candidates are ranked on the capped score with
the item id as tie-break, lifting the cap changes which candidate is *selected* on a small
but non-zero fraction of lines, so an operator can be shown a row that is not the system's
own best guess, with nothing in the display to say so.

### Throughput is not limited by the number of extraction workers

Two runs of 1,000 uploads, identical in every respect except worker count — 4 against 8,
same image, same 129 distinct source documents repeated, all text-layer — finished 0.6%
apart in wall time (1,141.1 s against 1,134.5 s). Container CPU was 0.95 and 0.96 cores in
the two runs; the load guard passed in both. Per-document text parsing got *slower* as
workers doubled, from a median of 1.37 s to 2.42 s and a mean of 4.31 s to 7.91 s.

The pre-registered verdict rule returns **not worker-bound**. Doubling the pool bought
nothing because the pool was never the constraint.

The leading explanation is that the text-parsing stage is pure Python and holds the
interpreter lock, so any number of threads shares roughly one core. A named confound
remains — the host carried more runnable threads than it had cores available to this work
during both runs — and it is not yet settled. The discriminating experiment is processes
against threads at equal total worker count, pre-registered with its bands and with the
rule that a saturated host can only *confirm* the lock reading and never refute it, since
saturation removes the cores the process arm would need. Until that returns, the
explanation is a hypothesis and is recorded as one.

### The volume target is met for text-layer invoices, and it buys nothing

Both runs put 1,000 text-layer documents through the system in **under twenty minutes** of
wall time — 1,141.1 s and 1,134.5 s, which is 19 min 01 s and 18 min 55 s — with no failed
document, no backpressure rejection, no container restart, and every health check passing.
The stated target was 20 to 30 minutes, so both runs come in below its lower bound at
either worker count. They beat the window rather than landing inside it.

It is worth being exact about what that does and does not establish, because the number
invites a promise this record cannot make.

- It is one class. Text-layer PDFs and spreadsheets only. Scanned invoices go through
  optical recognition, take far longer per document, and are the class where a batch
  limit is a real operational question. That measurement is separate and is not complete.
- It is not a throughput rate for the user. The corpus was 129 distinct documents repeated
  to reach 1,000, on a shared host under other load, so it does not predict a rate on a
  thousand genuinely distinct invoices on the operator's own machine.
- **Every one of the 1,000 landed in `needs_review`. Nothing was exportable without an
  operator touching it.** The run finished inside the window and produced no accepted
  workbook.

So the binding constraint on this program is not the batch size and not the worker count.
Both runs show the pipeline moving documents fast enough; what neither shows is documents
coming out the other end decided. That is the matcher, and it is the section above.

A consequence for how the volume limit should be set: there is no batch size that raises
accuracy, because accuracy is a per-document property and batch size is a throughput one.
The measurements bracket this directly — twenty real invoices produce zero exportable
without operator action, and a thousand produce zero. Shrinking the batch would change how
long a run takes and how deep the queue gets. It would not change what comes out.

## Proposed next steps, in dependency order

> **Historical — retained as the plan of record, not as outstanding work.** Most of this list was
> completed during the engagement: the exporter was rewritten to the contract (2), a contract test
> landed (3), extraction was substantially rebuilt and measured (4), the packager was hardened (5),
> identifiers are written as text (6), and the rounding convention was settled (7, first half). What
> genuinely remains open at freeze is item 1, item 7's currency policy, item 8, and item 9's trigger
> condition. The four limits in the frozen verdict at the top of this document are the authoritative
> statement of what is outstanding; read this list for the reasoning behind each item.


1. **Keep `data/reference/` unread and unpublished, and leave the superseded file uncorrected
   (A13).** It is a historical artefact; editing it while the pricing question is open would imply
   a decision that has not been made. Confirm at handoff that no code path reads it and that `data/`
   stays outside the allowlist. *(Owner: root.)*
2. **Rewrite the exporter to the exact three-tab contract**, taking the review threshold and Order No
   precedence from persisted Brand setup settings and aliases from an operator-performed import,
   with no bundled brand data. Price every line at invoice net unit cost after discount; use RMS
   cost only to raise a review flag beyond the configured threshold. *(Owner: backend.)*
3. **Land a contract test** that builds a workbook through the real exporter path and asserts it
   conformant, so A4 stops being a documentation promise. `target_conformance.py` can be adopted
   wholesale for this. *(Owner: backend.)*
4. **Attack A8, the zero-line problem, ahead of everything cosmetic.** 106 of 114 text invoice
   candidates yielding nothing is the difference between a demonstration and a product. Characterise
   the failing layouts before choosing an engine, and measure on real files. *(Owner: extraction.)*
5. **Harden the packager** per the two structural weaknesses in A10, and record the prohibition on
   `git add -A` from this workspace somewhere a future maintainer will actually read.
   *(Owner: root.)*
6. **Write identifier columns as text (A14)** so leading zeros survive, and cover it with the
   regression the design already requires. *(Owner: backend.)*
7. **Settle two policies the design flags but does not fix**: the decimal/rounding convention that
   "reconcile exactly" is measured against, and the currency/rate/date policy for non-AED invoices
   before the AED-denominated review threshold is applied to them. *(Owner: root, to business.)*
8. **Produce one consolidated workbook over the reviewed eligible set** and run it through the
   contract checker. *(Done for the two reviewed reference sources: a single workbook carrying both
   invoices, 2 Header / 2 Tax_Breakdown / 20 Details, checked CONFORMANT at exit 0 on my own run, with
   12 of its 20 line mappings automatic and the remainder confirmed by reviewed operator decisions.
   What remains open is not this step but corpus coverage — see limit 4 in the frozen verdict. A7
   fails on coverage, not on the exporter's ability to produce a conformant consolidated workbook,
   which is now demonstrated from original source documents.)*
9. **Keep authentication tied to the shared-deployment decision, not to this delivery.** Loopback
   binding plus a documented single-operator boundary is adequate for the local pilot as scoped.
   Identity and roles become prerequisites the moment anyone proposes a shared host, a networked
   port or a second concurrent operator. *(Owner: backend/root, on that trigger.)*

This record is frozen against the build named at the top. Its verdicts are not revised; the
post-freeze findings section above was appended after the freeze and records defects discovered
later, without re-running any criterion. Nothing in it should be read as approval to describe the delivery as complete, or as an
accuracy claim about invoices beyond those actually examined.

## Post-freeze findings, third round: Metric 1 becomes two numbers, and the remaining zero is not in the matcher

Everything in this section is measured at a named commit on a named corpus. Where a figure
describes the system's behaviour on our own sample it appears here; where it would describe the
size, shape or cost structure of the supplied master it stays out of this file by the rule recorded
in the round above.

### Metric 1 was one number doing three jobs

Metric 1 has read zero all through this program, stated as "invoices exportable after automatic
approval with no operator action". That single number was absorbing three unrelated refusals: a line
with no candidate at all inside the resolved supplier's scope, a header field the frozen extraction
parser never produced, and a cost comparison the export gate refuses. Those have three different
owners and three different fixes, and collapsing them into one figure means every genuine fix looks
like it did nothing.

From here the record carries two numbers, each always stated with its corpus, its denominator and
its commit:

- **Metric 1a** — exportable with **zero** operator action.
- **Metric 1b** — exportable after **one invoice-level acknowledgement** and **no per-line edit**.

Metric 1b is not a lowered bar substituted for a failing one. The delivery was asked to solve every
invoice and to *flag the ones with missing information for recheck*; an acknowledgement is that
recheck, so 1b measures the thing the delivery was actually asked for. Metric 1a stays on the board
because the wall-time promise at a thousand documents depends on operator action being zero, and
because a metric that has read zero all night is not retired by renaming it.

**Metric 1a has a ceiling of 6 of the 20 real uploads under any ranking or tie-breaking change.**
That figure is derived, not measured here: it comes from a distribution of unmatched lines per
invoice produced by the unit that wrote the matcher change, relayed to me, and the arithmetic over it
is mine. An earlier version of this paragraph called the ceiling *hard* and said it held under *any
matcher change*. Both words were wrong and they are corrected here, because the correction matters
more than the number.

It is not *hard*. What is hard is the floor of refusals underneath it; the ceiling itself is an upper
bound that two further conditions can only push down. The header fields the frozen parser did not
produce are one, and the cost comparison three subsections below is the other — it refuses two
invoices whose every line is already matched automatically, so a reader treating 6 as reachable would
be wrong for a reason this same document supplies a few paragraphs later.

It does not hold under *any matcher change*, and the justification originally offered — that no
ranking or tie-breaking change can reach those lines — is narrower than the claim it was supporting.
Widening the eligible scope is a matcher change and it manufactures candidates for exactly those
lines; the unresolved-supplier fallback already in this codebase is that change.

The premise itself also needed correcting, and this part I measured myself at `72c4c04` on the same
database copy rather than taking it relayed. The claim had been that those lines have *no candidate
at all* in the resolved supplier's scope. They do. Across 357 lines, 333 of them under a resolved
supplier, there is **not one line for which the matcher returns an empty candidate list**. The 85
lines in question come back as `unmatched`, which is a different thing: they have candidates and the
best one falls below the suggestion floor of 70. Where it falls is the finding —

| best candidate score on an unmatched line | lines |
| --- | --- |
| 60 to 70 | 50 |
| 50 to 60 | 34 |
| 30 to 40 | 1 |

**84 of the 85 sit within twenty points of the floor.** These are not lines beyond the reach of
matching work. They are lines just under a threshold, and the intervention most likely to lift them
is better description normalisation — which means the size-token handling in the frozen extraction
parser, the same component the cost comparison below independently points at. Two separate lines of
evidence now converge on one frozen file. The routes previously named for these lines, an operator
mapping each one so an alias is learned or fresh master coverage, are real but they are no longer the
only ones.

### What the matcher work moves, and what it does not

Measured by replaying the stored lines of the same twenty uploads, baseline `b765f36`, arms produced
by disabling one mechanism at a time:

| arm | auto | suggested | unmatched |
| --- | --- | --- | --- |
| baseline | 21 | 250 | 86 |
| critical-unknown cap lifted alone | 42 | 229 | 86 |
| duplicate-row collapse alone | 136 | 135 | 86 |
| both | 162 | 109 | 86 |

The unmatched column does not move in any arm: the same lines that sit below the suggestion floor,
seen from the other direction. The transition is entirely `suggested` to `auto`: 141 lines, with
nothing moving the other way. This confirms the prediction registered before the experiment —
lifting the score cap alone changes almost nothing, and the mover is the collapse of several eligible
catalog rows of one RMS item that were tying at the top and zeroing the margin. It also confirms the
prediction's corollary, which matters more: **the matcher's share of the refusal moves and the export
count does not.** Metric 1a is 0 of 20 on the baseline and 0 of 20 with both mechanisms in.

**The cap-lifted row and the earlier finding above are not in conflict, and the account this record
gave of why was wrong.** The round above reports, in bold, that removing the cap alone changed zero
line statuses; the row here moves twenty-one. This record previously explained that by rank
restoration: lifting the cap returns an exactly-named candidate to the top, where it satisfies the
*exact* automatic condition, which consults no threshold. A single field discriminated that account,
it was named in advance, and it came back against it. **The path recorded on all twenty-one is
`fuzzy`. None is `exact`.** The reason clause on every one of them is strong name similarity, and the
stored scores run from 96.6 to 99.0 — above the fuzzy threshold of 96.0, not around the exact
condition. The rank-restoration account is therefore withdrawn. It was a structurally sound reading of
the baseline code and it described something the baseline code can do; it is not what produced these
twenty-one.

**The real reconciliation is that the two measurements are not the same intervention, and the row's
label said they were.** The zero was obtained by patching the score-cap *constant* and nothing else,
which leaves the critical-unknown flag computed exactly as before. The automatic fuzzy path requires
that flag to be clear, so a constant-only lift is structurally incapable of admitting a fuzzy
automatic match — the zero was guaranteed before it was measured, which is why it is a weak result
rather than a surprising one. The twenty-one come from a different arm entirely: it does not patch the
baseline at all. It runs the candidate change's own tree with the row collapse disabled, and on that
tree the mechanism removes a single-valued unit-of-measure from the predicate that feeds **both** the
cap and the flag. Two terms clear at once. So the arm labelled as a cap lift measures the candidate
mechanism with one component switched off, and the phrase describes an experiment nobody ran. The row
is relabelled accordingly wherever it appears: *the uninformative-unit mechanism, cap and gate cleared
together for a unit-only unknown on a single-valued column, row collapse disabled.* Both numbers were
correct throughout; the label and the explanation were not. Two independent verification passes
reached the relabelling conclusion separately, one of them from its own replay rather than from the
supplied data.

**A gate property that follows from the same evidence, and that is not a defect in the change.** On
the twenty-one, the selected item has exactly one eligible row in scope. The margin test compares the
best candidate against the strongest runner-up, so with one eligible row the runner-up score is zero
and the eight-point margin clears automatically. The margin therefore contributes no discrimination on
those lines, and the automatic decision rests on the similarity score alone clearing 96.0 — in the
closest case by 0.6. This is a property of the gate rather than a regression: it is equally true at the
baseline, where the automatic set also contains single-candidate lines, and no change under review
introduced it. What the change does is **enlarge the population that leans on it**, which is the
reason the automatic decisions outside the independently checked subset were verified one by one by two
parties rather than accepted on the arm counts. Recorded here so that a later reader does not count
three conditions on the automatic gate where, on a single-candidate line, there is effectively one.

A change of this shape moves 141 lines from operator-reviewed to machine-decided, which is the
population where a ranking error stops being a suggestion somebody rejects and becomes an export
nobody looked at. Trading a measured refusal for an unmeasured acceptance is not progress even when
the arrow points the right way, so the automatic decisions falling outside the independently checked
subset are verified item by item before that work merges, and any one of them wrong is a blocker
rather than a caveat.

### The remaining refusal is a cost comparison whose cause is not yet attributed

With every matcher mechanism enabled, the export gate still refuses all twenty. Two invoices now
have every line automatically matched and are refused for a different reason: the gate also requires
each line's price to sit within an absolute per-unit tolerance of the master's cost for the matched
item, and those lines do not. Across the corpus the comparison puts 59 of 357 lines outside that
tolerance and 103 inside it.

The item identities are not in doubt for the lines concerned — they are exact-name matches that were
independently checked — so the discrepancy is between the master's cost column and the invoice's
price basis, and the tolerance value is not the question until the cause is known. Three candidate
mechanisms were registered in advance, and their signatures are stated here rather than merely
claimed, because a pre-registration nobody wrote down is not a pre-registration — it is an assertion
of having had one, and it leaves no way to check afterwards that the signature was not chosen to fit
the answer. The signatures describe our software, not anyone's commercial values, so they belong in
this record:

- **A pack or case basis.** The discrepancy tracks a pack or case count: it lands on small whole
  numbers, and for a given item it is the same number on every invoice that carries it.
- **A quantity or column misread by the frozen extraction parser.** The discrepancy tracks the row's
  *own* parsed quantity, varies line to line with no relation to anything in the master, and
  disappears when the line total is compared instead of the unit price. This is the same component,
  and very nearly the same fault, as the extraction test that fails on `main`.
- **A scale or currency factor.** The discrepancy is one constant, the same on every affected line
  regardless of item or invoice.

**One of the three is our own defect**, and it is the one the evidence already favours: the extraction
test that fails on `main` fails precisely because the frozen parser reads a size token in a
description as a quantity. The discriminating measurement is being run before any
question about the master's cost basis is put to anyone, for the general reason that a question you
can answer yourself in minutes should not be escalated at all, and certainly not when one of its
possible answers is that the defect is ours.

No tolerance value fixes any of the three mechanisms. Retuning the threshold would only stop the
gate reporting them.

### Two controls landed

The publication path is now guarded at `9eed4a7`. Documentation is packaged from an explicit
allowlist rather than a directory walk, so a document is excluded until it is named; measurement
records of customer data and of our own process no longer ship at all; and the content check covers
identifier and capability forms — sharing links, account and user identifiers, absolute home
directory paths on all three platforms — alongside the credential patterns it already carried. The
check runs inside the build over exactly the file list the archive is written from, so it is
build-time and fail-closed rather than a test that only runs when someone remembers to run it; the
archive is additionally decoded and re-scanned, because the archive is base64-encoded inside its
manifest and a scan of the source tree returns clean whether or not the published artifact is clean.
That last point is the general lesson: every privacy check in this program had been reading the tree,
and the published thing is not the tree.

Verified independently by building the package from the tree that still contained the offending link,
decoding the manifest, confirming the receipt digest against the decoded bytes, and finding no
pattern hit inside the archive. Two narrow gaps in the new patterns are recorded as hardening rather
than holes: a placeholder exemption terminated by a word boundary also exempts a real name that
merely begins with the placeholder, and UNC paths are not covered.

The demo-seed endpoint is gated at `72c4c04`. It wrote fictional catalog rows and invoices whose
lines were stored as matched, with full confidence, without the matcher running — from an
unauthenticated endpoint that nothing in the application or the documentation ever called. It is now
off unless explicitly enabled, refuses inside the same transaction as its own write when the database
already holds non-demo rows, flags its rows in the statistics endpoint so a seeded database cannot be
read as a measurement, and the corpus evaluator refuses an input set containing seeded sources
outright. One gap remains filed: the statistics endpoint reports the flag and the interface does not
yet read it.

## Post-freeze findings, fourth round: the ceiling was a claim about the wrong metric

Three claims from the round above are revised here. Two are withdrawn and one is confirmed by
measurement after being challenged. All figures in this section are recomputed at the release-candidate
baseline commit against the twenty real uploads, with the catalog scope and the alias set stated.

**The threshold that the sub-floor lines are short of is the suggestion floor, not the automatic bar,
and that makes the finding about a different metric than the ceiling it was offered as a replacement
for.** A line lifted from the 60s to just above 70.0 becomes a *suggestion*. A suggestion is an
operator touch. Metric 1a counts invoices exportable with **zero** operator action, so lifting every
one of the eighty-four lines within twenty points of the floor moves Metric 1b and Metric 2 and leaves
Metric 1a exactly where it is. The ceiling in the round above was a statement about 1a; the distribution
offered in its place is a statement about 1b and 2. The premise of the original ceiling was false — that
correction stands — but its conclusion was never reachable by the evidence that replaced it, in either
direction. The only route from a sub-floor score to an automatic decision is the exact condition, which
requires the normalised strings to be *identical* rather than merely closer; the fuzzy route needs 96.0
with a clear unknown flag, which is not reachable from the 60s by any normalisation of this kind.

**The distribution itself was challenged as an artefact and it survives, verified.** The challenge was
that the published bands were the stored confidence column read back rather than a measurement, that
the column was written by older code, and that the stored values exceeded a recomputation by a median of
more than twenty points in one direction. Recomputed at the baseline commit over the eighty-five
sub-floor lines in the resolved-supplier scope: the highest-scoring candidate is the first element on
eighty-five of eighty-five, so the figure is not an ordering artefact; and **the stored column equals
the recomputation exactly on all eighty-five** — median, minimum and maximum difference all zero, with
the stored value higher on none of them. The bands are 50 in 60–70, 34 in 50–60, and 1 in 30–40; eighty-
four of eighty-five sit within twenty points of the floor. The column is live, and it agrees with the
recomputation because the code that wrote it is the code that recomputes it. The alias table carries no
rows at all, so the empty alias list used in every recomputation is the system's actual state rather
than a simplification, and cannot account for a discrepancy in either direction. One recomputation of
the baseline disagrees with the stored state on six lines; two independent recomputations, one of them
inside a container built from the delivery image, reproduce it exactly. The disagreement is being
located as a harness difference and no figure in this record rests on it.

**The size-token hypothesis is withdrawn, and it was this document's own suggestion.** The round above
named asymmetric size tokens between invoice descriptions and catalog descriptions as the intervention
most likely to lift the sub-floor block. Three measurements, designed independently and pointing the
same way, refuse it. First, the touched population on the invoice side is empty: none of the sub-floor
lines carries a size token at all, against an instrument verified to fire on the suggestion population,
on the automatic population and on the catalog side before the zero was accepted. Second, on the catalog
side the population is one line by the direct reading — the single line in the lowest band — and
seventeen under the most generous reading that counts any currently-stored near-candidate. Third, an
independent test that strips size and pack tokens from *both* sides of every sub-floor line and its
strongest fifty candidates produces no string identity, nothing reaching the fuzzy threshold, and
nothing reaching even the suggestion floor. That test deletes tokens rather than parsing them, which is
a crude proxy, but the crudeness runs one way only: had these descriptions differed mainly by a size
token, deleting it on both sides would have produced high similarity, and it produced none. **What
separates these descriptions from the master's is therefore not a size token, and naming it is open work
rather than a finding.** No claim is made here about what would lift them.

**One metric has moved on real uploads, for the first time in this programme.** Metric 1b is 0 of 20 at
the baseline and 2 of 20 with the candidate matching change in, measured by rematching the same twenty
uploads through the service. Metric 1a is 0 of 20 in both. The two invoices that move are single-line
invoices whose one line becomes automatic. They do **not** pass the cost tolerance — they fail it, and
failing it is precisely why they land in 1b rather than 1a: an above-tolerance cost is an
invoice-level flag an operator can acknowledge without editing a line, which is what 1b measures.
The flag they require is itself an artefact of the currency defect recorded below, so the movement in
the matcher is real and the acknowledgement it still costs the operator is spurious. This is recorded with both
numbers in one sentence deliberately: a change that moves 1b from zero to two while leaving 1a at zero
is a real improvement to the matcher's share of the work and **not** a step toward the acceptance
criterion, and the two readings must not be separated in later quotation. The refusal classes behind the
remaining eighteen, counted per invoice and overlapping, are a sub-floor line, a suggested line, a
missing subtotal or tax total, an above-tolerance cost line, and an unresolved supplier. The programme
verdict is unchanged: **not accepted.**

## Post-freeze findings, fifth round: two defects change owner, and one of them is not a matching defect

**The cost-comparison block is a master-data defect, and this record's extraction parser is cleared of
it.** Three signatures were pre-registered before the discriminator ran: a pack-or-case basis, a
quantity-or-column misread by our own frozen parser, and a scale-or-currency factor. The ratio of
invoice unit price to master unit cost was then computed on every above-tolerance line. It is a single
constant, the *same* constant on all of them, and constant per item across different lines and different
invoices. That decides it: a repeated constant is a basis difference, not a scatter of errors. The
pack-basis signature fits the arithmetic but the master refuses it — the pack fields are unit-valued on
every row of every item involved, with one unit cost per item. The parser-misread signature is measured
at **zero**: line total equals quantity times invoice price on every one of these lines, and the size
token survived into the description on every line that carries one, so the known frozen-parser defect
did not fire here. The scale-or-currency signature as originally worded, a factor near one hundred,
is also zero. The mechanism is the fourth possibility, which this record's own Gate 5 already names:
**the master holds cost in more than one currency, the comparison assumes one, and the constant is a
rate.** The fix is the standing Gate 5 design — record currency at import and require equality before
comparing — and the absolute cost tolerance is not well-posed until that lands. **The convergence
argument of the third round is withdrawn in full.** It rested on two lines of evidence pointing at the
frozen extraction parser; one was the size-token hypothesis, refuted above, and the other was this cost
block, which belongs to master data. Neither leg survives.

**Sixty-eight of the eighty-five sub-floor lines are not product lines at all, and that is the real
finding in this block.** A token-class characterisation of what actually differs on them returns two
dominant classes that are not products: footer and contact text carrying a page marker, and
pricing-adjustment label rows carrying a currency code and an internal identifier. The extractor emitted
both as **line items with a quantity attached**. Their best candidates score in the 50s and 60s on a
single shared word — coincidences, not near misses. Three consequences, and the third is the serious one:
1. No matcher change can ever resolve these lines, because there is nothing to resolve them to. This is
   why the unmatched count is the one number that does not move in any arm of any experiment — a figure
   constant across every arm is usually a figure the experiment is not touching.
2. The remaining seventeen are genuine product lines whose gap is alphabetic wording, with **no** numeric
   and **no** size component in the symmetric difference. Within them, one sub-population of thirteen
   differs by a trademark artefact in the master's stored text, and that is the only sub-population where
   a normalisation-only change in the matcher could plausibly cross the suggestion floor. Ceiling
   thirteen of eighty-five, untested, and stated as a ceiling rather than a forecast.
3. **These phantom rows carry a quantity and would be exported.** A label row leaving the system as an
   invoice line is a correctness defect in the deliverable itself, not a missed match, and it is more
   serious than anything else in this block. It also contaminates every per-line denominator in this
   record: per-line rates computed over the full line count are computed over a population that includes
   non-product rows, so they understate per-product performance and must not be quoted as either.
The owner is the extraction stage, which is frozen, so the routes are a parser-side filter under an
exemption or a matcher-side refusal of lines carrying no product tokens. Both are open; neither is a
decision this document can take.

**A privacy defect in this document, found by someone else, and the check that would have caught it does
not exist.** This file has been published with the repository since the first snapshot and carried four
master-derived figures: a count of priced rows with their decimal-place distribution, a size multiple in
the import-guard discussion, and a share-of-rows proportion. They are being replaced with the
qualitative conclusion and an explicit statement that the figure is withheld. The lesson is structural
rather than clerical. Every automated privacy pattern in this repository matches an **identifier shape**
— a key, a token, a URL, a home path. A master-derived *quantity* has no shape to match: it is an
ordinary numeral in an ordinary sentence, and it passes every pattern cleanly, which is exactly what
happened on each of the sweeps this document records as clean. The only instrument that finds this class
is a human numeral-by-numeral read against the stated test — does the number describe the software's
behaviour on a sample, or the size, shape, content or cost structure of the master — and an extended grep
found one of the three. **Those sweeps were clean and they were also uninformative about this class, and
this record should not be read as having checked for it before this round.**

## Volume: the thread-safety fix is proven, and the batch-size question has an answer

**Scope.** One thousand uploads of the OCR document class through eight workers, on a shared host
carrying four other containers at a load average between 23 and 28, against a build consisting of the
release baseline plus a single serialising lock around the PDF rasteriser. The run was reconstructed
from the container's own database after the driver process was lost; the container was never restarted.
Peak memory and the queue-depth series for the final half hour were not captured and are not
recoverable — that is a gap in the measurement and is recorded as one, not as an absence of a problem.

**The fix is proven on the class it targets.** Zero of one thousand uploads hit the data-format-error
class, against 133 of one thousand on the unpatched build with the same corpus and the same worker
count. Predicted zero, observed zero. No retries anywhere, no worker exits, no respawns, no stall, and
the queue drained to empty.

**The batch-size question is answered, and the premise behind it was wrong.** The delivery was asked
whether one thousand documents in a single run is viable, and if not, what smaller batch works without
losing conversion accuracy. One thousand in a single run destabilised nothing: every row was processed
on its first attempt, the worker pool was intact at the end, and nothing queued behind a stall. **The
limiting factor is not batch size.** It is wall time and per-document limits, and a smaller batch
improves neither. No batch-size ceiling is recommended, because none was found.

**Failures, with both denominators, because they say different things.** By upload, 25 of 1,000 failed.
Every one of them terminated with an explicit, specific reason and a terminal failed state: none was
dropped, none produced a silent partial conversion. That is the behaviour the delivery was asked for —
solve what can be solved and flag the rest for recheck — and it is the second strongest result in this
run. By **source document**, which is the denominator that carries meaning, 48 of 50 document types
reached a terminal extraction-and-matching state on every copy; one failed on every copy against a
deterministic page-size limit, being a scan
whose raster exceeds the configured per-page ceiling; and one failed on five of its twenty copies
against a time limit. **The upload figure is a count of copies, not a failure rate.** A rate on a
genuinely distinct population is not estimable from fifty source documents and none is offered here.
Of the 25, twenty are deterministic and five are not: a time limit is a property of the document *and*
the machine it ran on, and those five were measured on a loaded shared host. The page-size ceiling is a
configuration constant, and raising it trades memory for coverage — a change that must report peak
memory at the raised limit before it is argued for, since a large scan admitted and then exhausting
container memory under eight workers is a worse outcome than a clean rejection.

**Throughput, and the two targets in play disagree with each other.** One thousand OCR-class documents
reached a terminal state in 58 minutes 55 seconds, of which the intake phase was under two minutes —
so essentially all of it is processing and none of it is an intake problem. Sustained, that is roughly
24,400 documents per day. The programme design document sets a throughput requirement of 10,000
invoices per day with no queue backlog older than fifteen minutes, so **this run is about 2.4 times
ahead of the written requirement**, on the hardest document class, on a loaded shared host. The
separately stated verbal target of one thousand invoices in twenty to thirty minutes is about 5.8 times
that written requirement and about 2.4 times what was measured. Both readings are true simultaneously
and neither is quoted without the other. Which target governs the launch is a decision for the
programme owner, not one this document takes. No projection is made to a dedicated machine: that
requires a run on such a machine, and none has been performed.

## The volume requirement was reduced by the requester, and the gate changes with it

The delivery was originally asked for one thousand invoices converted in twenty to thirty minutes, and
the programme design document separately sets ten thousand per day. **Neither is now the operating
requirement.** The requester has since specified a batch of fifty to two hundred documents, with fifty
acceptable, and no time figure. Both earlier numbers stay recorded as stated targets; neither is the
launch gate. This section records the change so that a later reader does not measure the delivery
against a requirement its owner withdrew, and does not read the withdrawal as the delivery lowering
its own bar.

**At the requested size the throughput question is effectively closed.** Prefix timings from the
thousand-document run on the locked build give fifty documents in 4 minutes 22 seconds, one hundred in
9 minutes 27 seconds, and two hundred in 16 minutes 18 seconds. Every one of those is an **upper
bound** rather than a measurement, because those documents were processed while the remainder of the
thousand was still arriving and competing for the same workers; a standalone batch can only be faster.
They are OCR-class, on a shared host, and the text class is unmeasured at these sizes.

**The launch gate is fifty distinct documents, and distinctness is the point.** The corpus holds fifty
distinct source documents and the requester's minimum batch is fifty, so the two coincide exactly. A
two-hundred-document batch assembled from the same fifty sources at four copies each measures
throughput and adds nothing about conversion, so any such figure is labelled as copies rather than as
invoices. The gate is:
1. every document reaches a terminal state, and each is **either** exported into the consolidated
   workbook **or** flagged with a reason code naming what is missing — nothing silently dropped,
   silently partial, or exported wrong;
2. the workbook satisfies the three-sheet contract, every detail and tax row links to a header
   transaction, and line totals reconcile to the stated subtotal on every exported invoice — producing
   a workbook is not the criterion, producing a reconciling one is;
3. no failure carries a class outside those already characterised — a novel reason is a stop, not a
   pass, notwithstanding that it is explicit;
4. wall time is reported with its full scope and is **not** gated, because no time figure was given.

**Two expected failures at this batch size, stated in advance.** One source fails deterministically on
the page-size ceiling and one intermittently on the OCR time budget, so a fifty-document batch
containing them shows about two failures. That is characterised behaviour, not a regression, and it is
written here before the run so the first launch result is not misread by whoever sees it first.

**The flagged share is reported and not gated, and that is the specification rather than a
concession.** The delivery was asked to solve what it can and flag the rest for recheck. On present
measurements the flagged share will be large: the touchless count is zero of twenty real uploads, and
the corpus evaluation put thirteen of one hundred and seventy-nine documents through the strict
financial gate. A large flagged share with correct reasons is the system behaving as asked; a single
wrongly exported invoice is not. The gate above is written to separate those two outcomes, which a gate
resting on terminal states alone cannot do.

## Post-freeze findings, sixth round: the word "converted" was wrong, and the block on automatic matching was the master repeating itself
> **WITHDRAWN.** The duplicate-master-row diagnosis below is refuted by a second instrument and is no
> longer this document's position. See "Two withdrawals" at the end.


Three findings and one withdrawal, all measured at `af4a6d8` unless stated. Two of them reduce what
this programme may claim; one of them is the largest positive movement recorded so far; and the last is
a negative result that closes off a fix several people expected to be decisive.

**Withdrawal: no run in this programme has converted anything.** Every volume run to date, the
thousand-upload OCR-lock run included, started from a fresh database with empty operator settings. The
approval validator therefore blocked every invoice on the four required setting codes and export was
never attempted. That is the product behaving as specified — brand and location setup is the documented
first operator step — but it means the sentence corrected above originally read "48 of 50 document types
converted on every copy", and that was not measured. What was measured is that extraction and matching
reached a terminal state with an explicit reason. Conversion, which is the thing actually asked for — a
target workbook out the other end — has never been exercised at volume. The error is the one this
record has repeatedly charged against others: measure the stage that ran, then name it with the word
for the stage that did not. The launch gate of record configures settings from the repository's own
fictional placeholders before upload, so it will be the first run in this programme to exercise export
at all, and its result certifies structure and reconciliation under placeholder coding, never the
requester's own codes.

**The dominant block on automatic matching was a duplicate master row, not conservatism.** Re-matching
the stored extracted lines of the twenty-invoice corpus holds extraction fixed so that only matching
varies. The harness was validated before it was believed: at the baseline commit it reproduces the
stored decision on 315 of 357 lines, with the 21 stored automatic lines reproducing as confirmed. 21
stored-suggested lines recompute as unmatched and are not yet accounted for, most plausibly a small
difference in catalog scope, so every count in this section carries that 21-line uncertainty.

At the baseline, 109 real product lines match a master row on an exact normalised description and still
do not reach automatic. Every one of them has exactly two exact candidates, and the blocker is the
condition requiring a single exact candidate. The split is the whole finding: **107 of the 109 are two
master rows carrying the identical normalised description and the same item id** — the same item listed
twice, a bookkeeping duplicate. Only 2 of 109 are two genuinely different item ids, and those two carry
two different master unit costs, so holding them for review is correct behaviour rather than a defect.
The system's silence was not caution and it was not ambiguity in the goods; it was the master repeating
itself while the gate read a repeat as a tie. Collapsing those duplicates in a resolved scope moves
line-level automatic decisions from none to **141 of 357** on the same stored lines.

**The negative result: fixing the phantom adjustment rows unlocks no invoice.** Invoice-level on
matching status alone, 2 of 20 invoices now have every line automatic. The count of invoices blocked
*only* by phantom rows is **zero** — every invoice carrying them also carries at least one suggested or
unmatched real product line. The phantom-row defect remains worth fixing on its own correctness merits,
and the earlier figure for it stands as what it always was, a count on the unmatched axis. It is not a
route to touchless and must not be planned as one.

Neither 2 of 20 nor 141 of 357 is a touchless figure. Touchless additionally requires no cost-variance
review flag and an actual export, and export has never run. **Metric 1a therefore stays 0 of 20 as
recorded.** The defensible statement is narrower and more useful: matching has stopped being the
binding constraint on two of the twenty, and what constrains those two instead is unmeasured, because
the stage that would reveal it has never executed.

**A deterministic reproduction of a column-shift defect in the plain-text path.** The application
snapshot arrived with a failing test, carried through this programme as pre-existing; it fails
identically at the pre-programme commit, so that label is accurate. Its content is not background
noise. On a synthetic invoice whose description matches the catalog exactly, whose supplier, unit of
measure and unit cost all agree, the extractor reads the size token out of the product name as the
quantity and shifts every later column left: a line of two units at ten becomes a line of two hundred
and fifty of a volume unit at twenty, and the matcher then correctly reports a unit-of-measure conflict
on corrupted input. The failure is in extraction and is being read as a matching failure. Its blast
radius is bounded: on the real corpus every line carries no unit of measure at all and the
quantity-times-price identity holds on all 289 real lines, so the real documents do not take this path.
A fixture exercising a branch real data never reaches is worth exactly what it measures, and the
converse — that this defect would silently multiply a delivered quantity if a real document ever did
take the path — is why it is recorded rather than closed.

## Two stages have never executed, and a cross-check that validates the duplicate-row finding
> **PARTLY WITHDRAWN.** The cross-check below does not validate the duplicate-row finding; it
> corroborated a number produced by a three-part change. See "Two withdrawals" at the end.


**An independent reconciliation.** The duplicate-row finding above rests on one instrument, which is a
reason to distrust it. It reconciles exactly with a figure derived by a different worker on a different
harness: 141 automatic lines measured here, plus the 21 lines the matcher had already decided,
is 162, and 162 is the automatic-decision count recorded from the duplicate-collapse branch's own
evidence. The phrase first written here was "the 21 lines the corpus already carried as confirmed",
and it was wrong in a way worth preserving rather than quietly overwriting: the stored corpus holds
**zero** confirmed lines, all 21 are stored as automatic, and the confirmed label appears only when the
matcher is re-run. No human has touched any line in this corpus. "Already confirmed" imported a
reviewer who does not exist, and a later reader would have turned it into "21 lines were
human-reviewed" — which is precisely the kind of claim this document is supposed to stop. Two harnesses, one number, neither built from the other. That does not make the classification
correct, but it removes the most likely way for it to be wrong.

**Cost comparison is starved, not inert.** 336 of 357 lines carry an unavailable-comparison status with
no master unit cost, and the same 336 carry the review-required flag. The cause is not a defect in the
cost machinery: no match means no master cost means nothing to compare. So the cost path is downstream
of the matching failure, and when the duplicate collapse lands its automatic lines, cost comparison
executes on real documents for the first time. A reason code resting entirely on this condition is a
constant rather than a rule, and has been split for that reason.

**Consequence for the launch gate, correcting a rule set out earlier in this record.** Two stages have
never executed on a real document in this programme: export, because operator settings were never
configured, and cost comparison, because almost nothing matched. The gate criterion forbidding a novel
failure reason would therefore halt on the first reason either stage emits, which is not a defect but a
certainty. The criterion is amended: a first-encounter reason originating in export or in cost
comparison is expected and is reported rather than treated as a stop, while a novel reason from
extraction, matching or the terminal-state machinery still stops the gate, those being the stages with a
measured history to be novel against. A gate that fires on its own first execution tests nothing.

**The whole-tree privacy guard closes the file hole and not the path hole.** Running the pattern set over
every tracked and untracked-not-ignored text file, failing closed before the archive is written and
naming the file rather than the value, is correct and it would have caught the historic leak's content.
It runs when the packager runs. Publication to the forge happens on push, which does not invoke the
packager, and the historic leak travelled by push. The remedy is a check on the publication path itself,
with its limits stated rather than implied: a local hook prevents but is bypassable, and a
publish-triggered check detects after the fact rather than preventing. Neither makes exposure
impossible, and the record should not say otherwise.

## The launch gate was pointed at the wrong class, and a reason code that has never once meant what it says

**A premise error in the gate defined earlier in this record, and it is mine.** That gate required fifty
distinct documents on the stated ground that fifty distinct coincided with the corpus breadth and with
the requester's stated minimum. The coincidence does not exist. Fifty is the OCR-class subset of the
corpus — scans without a text layer, plus photographs — and the corpus holds 179 distinct documents
across two extraction classes, the other 129 being text-class. The requester's own invoices are mostly
text-class. So the gate was aimed at the minority class, and measurement has now shown that class cannot
reach the gate's hardest criterion at all: supplier resolution succeeds on 0 of 50 OCR-class documents
against 18 of 20 on the text-class replay corpus, and an unresolved supplier blocks approval, so export
can never be attempted there. The gate would have passed its first three criteria honestly and left the
fourth unevaluated — the self-satisfying shape this record rules against, reached through a premise
rather than through a criterion.

**Amended gate.** Two fifty-distinct batches, reported separately and never summed. The text-class batch,
with settings and supplier rules configured from the repository's fictional placeholders, is the gate of
record, because it is the requester's actual population and the only class where export runs. The
OCR-class batch is a characterisation run establishing that class's baseline, and is not to be described
as the launch gate. An evaluability floor applies to both: if export is 0 of 50 on both classes, or if
workbook reconciliation goes unevaluated for any reason, the verdict is **not evaluable**, never passed.

**A new criterion, because a document can be scored as converted while being empty.** In the
stress-window observation, 48 OCR-class documents reached a review state and produced 100 product lines
between them — 2.08 per document, against a text-class mean of 14.4 real product lines per document,
median 10, with no text-class document yielding zero. Different documents explain part of a sevenfold
gap; they do not explain a mean of two lines on commercial invoices, and none of the 100 lines is
automatic. The reading to rule out is that OCR-class extraction is losing most line items while the
documents still terminate as successes. So product lines per document are reported as a distribution
rather than a total, the count of documents yielding **zero** product lines is stated explicitly, and a
document yielding no product lines is flagged with a reason rather than counted as terminal success. It
has not been read, whatever state its row carries.

**A reason code that has never fired for its stated meaning.** An independent check established by set
equality, not by comparing counts, that the 336 lines flagged as priced above tolerance are exactly the
union of the low-confidence and unmapped sets, and that the flag fires on no automatic line. Zero lines
are above tolerance. The code is a re-encoding of "not automatic" wearing the name of a pricing
exception, and it would tell a reviewer that every invoice has a price problem when none does. Splitting
it is necessary and not sufficient: the unavailable arm must also stop being presented as an exception
owned by a named role, because a reason code has to name a condition its owner can act on, and no
item-master owner can act on an unmatched line by examining a price. Relatedly, four of the fourteen
invoices in that owner's queue have nothing unmapped except discount rows, so the phantom-row defect has
reached a real person's workload; those counts are not a workload figure until non-product rows carry
their own code.

**A metric pinned to one value is not a measurement.** The touchless numerator considers only invoices
already ready or exported, and export has never executed. Its zero therefore cannot distinguish "nothing
is touchless" from "nothing has been approved yet". Until the gate of record runs, it is reported as not
evaluable with that reason, or against a denominator restricted to invoices that reached approval, and
the same test applies to the cycle-time metric at n=0.

## The OCR class reads no line items from most documents it accepts

The yield criterion was added on suspicion and answered on its first use. On the OCR class, on the
locked lineage, at eight workers: of 50 distinct documents, 36 yield **zero product lines** — 34 of the
48 that reach a review state, plus the 2 that fail. The 100 product lines come from 14 documents, and one
document supplies 34 of them. The per-document distribution is min 0, median 0, mean 2.08, max 34.

Every zero-yield document carries a lines-required reason, so none is silent and none is dropped, which
is the flag-for-recheck behaviour the requester specified. But flagged is not converted. Under the
criteria as first written, 34 documents from which nothing was read would have counted as converted,
because they reached a terminal state with an explicit reason and the criteria asked for nothing more.
This is the same defect class as everything else in this record — a mechanism that cannot do its job
returning a normal-looking result — arriving this time in the acceptance criteria themselves rather than
in the code.

**What is not yet known, and it decides both the owner and the difficulty.** Two readings fit the
evidence and they have opposite consequences, so both are registered before the measurement rather than
argued after it. If the OCR text is substantial and header fields are present, then optical recognition
works and the line-table parser cannot read OCR-class layout: a bounded extraction defect, and the
highest-value fix available. If the OCR text is near-empty, then recognition itself produces nothing, and
a document that could not be read is being reported as a document that was read and found empty — a
second defect, in the reporting, on top of the first. Those are different statements to the person
holding the invoice. Supplier names being recovered on 2 of 50 documents makes the second reading the
one to expect.

**A timing figure that must not travel alone.** Fifty documents reached terminal state 354 seconds after
the first upload, at a mean load well above the rule. That is not fifty invoices converted in six
minutes. Two thirds of those documents produced no line items, so the run largely performed the cheap
part of the work and skipped the expensive part; the figure is a **lower** bound on a real conversion of
fifty documents, not an estimate of one. Wall time is reported beside yield in this record, never alone.

**Consequence for what may be claimed.** Conversion is class-dependent and no blended figure across the
two classes is admissible, because averaging a working path with a non-working one describes neither. For
text-layer PDFs the system extracts and matches line items. For scans and photographs it currently reads
no line items from most documents and flags them for manual entry. Any per-document success rate in this
programme carries its class or it carries nothing.

### Which reading held: recognition works, the line parser does not

The discriminator registered above was measured on the 34 zero-yield documents and the first reading
holds on 32 of them, with the second holding on 2. Recognised text is present in volume — median 41,250
characters, with 32 of 34 above two thousand — and header fields are recovered from 20 of the 34. On 2
documents recognition produced nothing; those reached a review state carrying a lines-required reason
instead of failing with a recognition reason, which is the mislabelling defect registered above,
small in count and real in kind.

**The evidence inverts the intuitive explanation, which is why it is worth recording in detail.** On
every available proxy for document quality the zero-yield group is equal to or better than the group that
did yield lines: characters 41,250 against 26,978, numeric-candidate lines 107 against 62, invoice total
recovered on 20 of 34 against 4 of 14, and vocabulary, alphabetic and whitespace ratios indistinguishable
between the groups. The documents the parser reads nothing from are the longer, denser, more numeric ones.
Failure correlates positively with content density. Degraded recognition, short text and missing headers
are all excluded, and what remains is a structural limit in the line-table parser's row model as column
structure grows richer. Characterisation starts from the densest zero-yield document rather than the
smallest, and three strata are kept separate: the 32 the parser cannot read, the 2 near-empty, and the 6
within the 32 that carry long text yet not one header field.

**A condition that outranks the fix.** Character accuracy against ground truth is unmeasured. That text
is present, and of the same profile as text the parser does read, is a claim about volume and shape and
not about correctness. Teaching the parser to read these layouts while recognition silently mis-reads
digits would not produce a non-conversion; it would produce a wrong quantity and a wrong price carried
into a downstream system with a terminal state and no flag — this record's recurring defect class in its
most damaging available form, and strictly worse than reading nothing. A digit-level accuracy check on a
hand-transcribed sample of quantities and prices is therefore required *before* any parser change is
planned as a fix. If digit accuracy on those fields is not high, the class is not fixable by parsing and
the honest product statement is that scanned and photographed invoices must be keyed by hand.

**The mislabelling fix is not held by the extraction freeze.** The lines-required error is raised in the
service validator with the invoice record in hand, and the recognised text is a stored column, so a
near-empty recognition result can be given its own reason and a failed terminal state without touching
the frozen extraction module. It is two documents in fifty and still worth doing promptly, because the
defect — reporting a document that could not be read as one that was read and found empty — is one the
requester will meet on their own scans and will have no way to diagnose.

## A label that manufactures human review, and the cost stage's first real numbers
> **PARTLY WITHDRAWN.** The above-tolerance count below is an artefact of an undeclared currency basis
> and is not a price variance. See "Two withdrawals" at the end.


**A machine decision is relabelled as a reviewed one.** The matcher revalidates any line that already
carries a persisted catalog selection and, on revalidation, stamps it confirmed at a confidence of
100.0 without asking where the selection came from. The proof is set equality rather than a count: the
lines that come back confirmed are *exactly* the lines that were stored as automatic — not a set of the
same size, the same set — and every one of them carries 100.0 afterwards. Three consequences, in
increasing order of seriousness:

1. The first-time-match metric documents a confirmed line as one a human touched. That documentation is
   false for every line in this corpus, so the metric's own definition misdescribes its data.
2. The metric's numerator counts automatic lines only, so re-running the matcher *lowers* the reported
   first-time-match rate with no human action anywhere. The number moves because of a relabelling.
3. The original score is overwritten with 100.0. The evidence for the decision is destroyed by the act
   of re-checking it, which means an audit that re-runs the matcher to see what it decided has already
   erased what it wanted to look at.

The third is the one that outlives this corpus. The first two are wrong numbers; the third is a lost
record, and a lost record cannot be recomputed later.

The reach is one route, a re-match endpoint, reached today only by an API client because no user
interface offers the action. That bounds the present blast radius and does not reduce the defect: the
first re-match button added to the interface makes it routine. The same call also records the actor as
a person, so a single re-match depresses both headline metrics at once, and a test encodes that
mislabelling as expected behaviour — so the test is to be corrected, not deleted.

**Confirmed lines in this record from here on mean a machine decision unless a human decision is named.**

**A prediction in the previous section executed, and produced a number nobody had seen.** That section
argued the cost stage was starved rather than inert, and that it would execute on real documents for the
first time once automatic matching produced master costs to compare against. It has now been run on the
real corpus. The comparison statuses move from one status on almost every line to three: the
unavailable-no-master-cost group falls sharply, a within-tolerance group appears at 103 lines, and an
above-tolerance group appears at **59** lines where before there were none. 59 plus 103 is 162, the
machine-decided line count exactly, which is the arithmetic that says the cost stage now sees every
line matching made available to it and no others.

Three things follow, and the third is the one that matters for launch:

- The starvation reading was correct. The cost machinery was never broken; it had nothing to compare.
- The reason code that flagged lines as priced above tolerance was, as recorded earlier, firing on
  lines that had no comparison at all. After re-matching it still conflates: the flag covers both the
  genuine above-tolerance lines and the still-unavailable ones, and at invoice level it fires on every
  invoice. Splitting it remains necessary and remains insufficient.
- **Touchless processing has a second ceiling, and it is not a defect.** Fixing duplicate master rows
  and phantom rows cannot deliver a touchless invoice if that invoice also carries a genuine cost
  variance, because a cost-variance flag requires review by design. Before this run, every
  above-tolerance count was zero and the variance question was invisible. It is now visible and
  non-zero. Any forecast of the touchless rate that counts only matching fixes is therefore an
  overestimate, including forecasts made earlier in this document.

No variance magnitude, tolerance value, item, supplier or price appears above. The counts recorded are
flag outcomes — what the software did to a sample — on the same footing as the review-required count
already in this record. What the prices actually are stays out.

## Launch blocker: the extraction module is frozen and the authority that froze it has gone

The module that reads documents was placed under a rule that nothing touching it merges until the
implementation owner ruled on three queued changes. That owner's session has ended without ruling on
any of them. The rule as written therefore became a condition that can never be satisfied — the
unsatisfiable twin of the self-satisfying gate this document has objected to repeatedly, and just as
capable of producing a wrong outcome through nobody doing anything.

**This is recorded as a launch blocker in its own right, independent of whether the queued changes are
good.** A module nobody is authorised to change is not a maintainable module, and an operator who is
handed this system needs to know that its document reader has no owner.

Two decisions were taken rather than left to expire, and both are recorded here as the coordinator's,
not the absent owner's, so that a later reader can see who decided and on what basis:

- A change measured neutral on the real corpus may proceed. Neutral means demonstrated: no line's
  status, candidate, score, quantity, price or total differs across the whole corpus, with the named
  failing test passing and the test file provably untouched.
- A change that alters any extracted **value** waits for the person whose invoices these are. That
  boundary is not procedural caution. A neutral change cannot silently corrupt data; a value-changing
  one is exactly the class where a wrong call ships a wrong quantity or a wrong price with a terminal
  state and no flag, and the decision belongs to the data's owner.

One measurement was added to the first queued change that had not been asked for: it serialises the
document-reading hot path across parallel workers to fix a thread-safety fault. The correctness case is
accepted. The throughput cost had been nobody's question, which is the same omission this document has
charged elsewhere — a correctness fix whose cost is unmeasured becomes an unexplained slowdown later.
It is being measured with and without the lock on the same tree at comparable load, and the cost will be
stated in the release record whichever way it falls. The fix lands either way; thread safety outranks
speed on a data-corruption fault.

## Three instruments, one split, and a residual that resolved against this document

The re-matching figures in this record were produced on three independent harnesses. Two agree on every
count. The one that disagreed is the one used here, and it disagreed by exactly 21 lines in the boundary
between suggested and unmatched. The other two reproduce the stored unmatched count exactly; this one
does not. **The two agreeing harnesses are the record; the split reported here earlier was wrong and is
corrected.** The automatic count, which is the figure every conclusion in this document rests on, is
identical on all three.

Publishing an uncertainty band obliges publishing its resolution even when it resolves against the
publisher, and this one did. The structural finding built on the same harness survives for a reason
that is worth stating rather than assuming: it rests on two master rows sharing one item identifier,
and no narrowing of a catalog scope can invent a duplicate row. A scope error can hide candidates; it
cannot manufacture the ones that are there. An independent re-run of that classification is still
outstanding and is the arbiter.

**A challenged measurement discipline, applied to this document's own discriminator.** The test used to
separate "recognition failed" from "recognition worked and the line parser could not read it" counts
characters of recognised text, and the objection raised against it was precise: that count discriminates
only if it is measured on the same text the line parser was handed, not on whatever an earlier stage
produced. The objection is correct in principle and does not apply here, and the reason is checkable in
four lines of the module. The stored text column is assigned from the extraction result; the extraction
result assigns it from the same value that is passed as the parser's first argument; no transformation
sits between them. For scanned pages the stored text is a concatenation that *contains* the layout text,
and the layout text is additionally handed to the parser as a second source. So the parser never
receives less than the count measures. The discriminator holds — byte-identical input, not merely
consistent input — and the objection has been converted into a stated property of the pipeline rather
than an assumption.

### The guard's fail-open mode, and which platforms it is verified on

The push-path guard is delivered as a repository hook, and the launchers are being changed to point git
at the committed hook directory, which is the correct answer because git cannot install a hook on its
own and a launcher is something an operator genuinely runs. Two conditions sit under that, and only one
of them is dangerous:

- **Fail-open, and therefore the gate.** If the hook is committed without the executable mode bit, git
  skips it silently. The push succeeds, nothing is printed, the hook path configuration still reads back
  correctly, and any test asserting the launcher mentions that configuration still passes. The bit must
  be read off the git index rather than off a working tree, because the index is what a clone receives
  and a developer's own checkout can have the bit where the index does not.
- **Fail-closed, and therefore acceptable.** If the hook's interpreter is absent it exits non-zero and
  the push is refused. That is noisy and safe. The only requirement is that the message name what to
  install instead of surfacing a bare exit code.

A test asserting that a launcher *contains* the configuration line is a tripwire, not evidence. A line
can sit inside a branch the operator's path never takes, after an early return, or below a failing exit.
The evidence is a fresh clone, the real launcher run, the configuration read back, and a planted marker's
push refused.

**Platform reach is stated, not assumed.** This system is required on two operating systems and ships two
launchers. A guard configured by only one of them leaves every operator on the other platform with no
protection on the publication path, which is half a guard delivered as a whole one. Both launchers set
it. Where the refused-push check cannot be executed on a platform from this environment, this record and
the operator documentation name the platform the guard was **verified** on and say plainly that the other
is configured but unexercised. Verified and assumed are different words, and the reader is entitled to
the first one.

### A regression test that guards a machine nobody runs

The thread-safety fix arrived with a test that passes when the lock is replaced by a no-op at the shipped
worker count, and only distinguishes the two at roughly twice that count. The correctness of the fix is
not in question. The test is: it does not discriminate in the configuration that ships, so it would not
notice a future refactor removing the lock. The high-thread-count result is kept as evidence that the
race is real — which is worth having and was not previously demonstrated — but it is not the gate.

The gate is a structural assertion that no two calls into the document-reading library overlap,
deterministic and independent of thread count, required to fail with the lock removed and pass with it at
shipped settings. A race test asks whether the fault happened to lose a coin toss on this run; a
structural probe asks whether the fault is possible. Only the second answers the question, and only the
second keeps answering it a year from now.

### A correct fix can remove a flag from lines that still need review

Splitting the cost reason code was necessary: it had been firing on lines that had no comparison at all.
After the split it fires only where a comparison was actually made and exceeded tolerance. That is right,
and it raises a question the split does not answer, because the lines that lose the flag do not stop
needing review — they were never above tolerance, but they have no master cost either, and something
must still hold them.

In this corpus they are held, and the arithmetic says why rather than an assumption: the
no-comparison-available group is exactly the set of lines the matcher did not decide automatically, and
those lines already block approval through the matching reason. Remove the cost flag and the matching
flag still stands. No review coverage is lost here.

**That is a property of this corpus, not of the code, and the difference is the defect.** The
no-comparison-available state has no code path and no owner. It is reachable by a line that the matcher
decides automatically *and* for which no master cost exists — a master row carrying no unit cost, or a
zero one. Such a line would carry no matching flag, because it matched, and no cost flag, because the
split correctly removed the one that used to fire. It would be approved silently with no cost check ever
performed. The coincidence that makes this corpus safe is that every automatically decided line here
happens to have a master cost; nothing in the code requires it.

Two requirements follow. First, count the master rows carrying no unit cost or a zero one: if that count
is greater than zero the unowned state is reachable today and this is a live defect, not a latent one.
Second, the unowned state gets an owner — a reason code of its own that blocks approval when a decided
line has nothing to compare against — and a test that asserts an automatically matched line with no
master cost does not reach an approvable state. Without that test, the correct fix above is one master
row away from becoming a silent approval.

This is the fourth occurrence in this programme of the same shape: a control that loses its capability
and returns a normal-looking result. It is the first where the capability is removed by a change that is
itself correct, which is why it is recorded beside that change rather than against it.

## Two withdrawals, and the first real export

Two findings recorded earlier in this document are withdrawn. Both were mine, both were published before
a second instrument existed, and both are withdrawn now rather than held pending a third opinion, because
a wrong diagnosis in an acceptance record is planned on top of by other people while it waits.

### Withdrawn: the block on automatic matching is not the master repeating itself

The claim was that of the lines matching a master row on an exact normalised description and not being
decided automatically, all but two were the same item listed twice under one identifier, so a
duplicate-collapse rule was the route to automatic matching. A second instrument, using **the matcher's
own normalisation function** rather than a reimplementation of it, finds that those lines have **zero**
exact normalised rows in scope and zero in the entire master, and that the matcher's own top-candidate
reasons on them are fuzzy-similarity reasons, not exact ties. The two genuine cases stand, and the
collapse rule correctly refuses to fold them because they are two different items at two different costs.

**Why my defence of this finding failed, which matters more than the finding.** When the classification
was challenged I argued it survived a catalog-scope error, because narrowing a scope can hide candidates
but cannot invent a duplicate row. That argument is correct and it was answering the wrong threat. The
refutation did not come through scope. It came through **normalisation**: I compared descriptions with my
own equality rule instead of the one the matcher uses, and a looser equality manufactures an exact tie
where the matcher sees none. I defended the instrument against the attack I had thought of.

**What replaces it, honestly.** The ceiling on automatic matching is not duplicate rows. It is that for
most of these lines **no master row's description matches the invoice's description under the matcher's
own normalisation at all** — the master and the suppliers' documents use different words for the same
goods. That is a vocabulary gap, and it is a harder problem than a bookkeeping duplicate: a collapse rule
is a day's work with a clear test, and closing a vocabulary gap means alias learning, operator
confirmation that accumulates, or both. **No forecast of the automatic-match rate in this document
survives this withdrawal, and nothing here should be read as saying we know what closes the gap.**

### Withdrawn: the above-tolerance lines are not a price variance

The claim was that the cost stage's first execution revealed genuine price variance, giving touchless
processing a second ceiling that no matching fix could lift. The mechanism was not checked, only the
number, which is the failure this document has charged repeatedly at others.

The master's cost column is declared in a currency that is **not** the invoices' currency, and the
comparison on the current mainline treats the two as the same currency without saying so. Every
above-tolerance and within-tolerance count produced so far therefore compares quantities on two
different scales. With a currency basis required and no rate supplied, every compared line refuses with
a basis-mismatch reason on almost every invoice — which is the correct fail-closed behaviour and did not
exist before. With an arbitrary round rate supplied by the measuring operator and labelled as such, the
two groups **swap**: the lines that were above tolerance fall within it and the lines that were within it
go above, and the two groups are disjoint item families sitting in different identifier bands.

Two groups that exchange places under a single scale factor, separated cleanly by item family, do not
indicate price drift. They indicate **units** — and here that the master's cost basis is mixed across
item families, so no single rate is correct for the whole master. This is the second time tonight a gap
between two groups has named a mechanism rather than a trend.

Consequences, and the third is a ruling:

- The cost-comparison axis is **NOT EVALUABLE**, not "flagged on N lines". A count published with a
  careful caveat still travels as a count, and the caveat does not travel with it. The axis reports its
  reason, not its numerator, until the basis is declared.
- Touchless processing has no demonstrated second ceiling. The earlier claim that every touchless
  forecast was an overestimate was itself unfounded; what is true is that the cost axis cannot yet
  contribute a number in either direction.
- **Which basis is authoritative — the master's declared currency column or the values in it — is not a
  question this programme may answer by choosing.** The software must refuse rather than default, which
  is what the pending change does. The question goes to the item master's owner, and it must not be put
  as "what currency are your costs in", because the measurement says the answer is not one currency. It
  is put as: are all costs on one basis, or do some item families use another.

### Not withdrawn: export has run end to end on real documents

The first genuinely positive delivery fact in this record. On a copy of real data, with suggested lines
confirmed to their top candidate as a human reviewer would, invoices approved and an export created: a
workbook is produced with its header, tax-breakdown and detail sheets populated, for **5 of 20**
invoices, identically on the mainline and on both arms of the currency change. No aliases were learned in
the process, before or after.

The 15 refusals are named and are not mysteries: a required subtotal or tax total absent, unmapped lines,
required supplier fields absent, and a supplier/item mismatch. Those are the work queue.

Two labels this figure must carry wherever it is quoted. It is **harness-assisted**: a harness stood in
for the human who confirms suggested lines, so it measures what the system delivers *with* a reviewer,
not touchless throughput. And for that reason it is **not comparable** with the machine-only first-time
match metric — the two differ by definition and not by defect, which is a separate fact from the
relabelling defect recorded earlier and must not be folded into it.

### The worst part of the second withdrawal: this document already contained the refutation

An earlier section of this same document, written by the same author, records that the currency of the
master rows being compared against is never tested, that an invoice in the operating currency matched
onto rows denominated otherwise is compared against **incommensurable figures**, and that a large real
discrepancy can therefore fall inside an absolute per-unit tolerance and be approved silently.

That is the refutation of the variance claim, in full, several hundred lines above the claim. It was
written before the claim was made. When the above-tolerance count arrived from a measurement run, it was
recorded as a finding about prices without anyone — least of all me — going back to the section that said
those two quantities are not comparable. The number was new, so it was treated as evidence, and the
existing conclusion that would have disqualified it was not re-read.

This is a harder failure than missing something. A missed fact is a gap in knowledge; **this was a fact
already established, written down, and owned, that was not consulted when the very measurement it
governed came in.** It is the reason the earlier prediction "the cost stage will execute for the first
time when matching lands" felt like a confirmation when it arrived: the prediction was about the stage
running, and the stage running was mistaken for the stage producing a meaningful number.

Two standing rules follow, and they apply to this document first:

- When a stage produces a number for the first time, re-read what this record already says about that
  stage's inputs **before** recording the number. First execution is the moment a latent input defect
  becomes visible, not the moment it stops mattering.
- A finding is not retired by being superseded in attention. The incommensurability note had not been
  withdrawn, contradicted or resolved. It was simply older than the excitement.
