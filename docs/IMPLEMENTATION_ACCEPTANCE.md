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
| A15 | The documented RMS master import actually works | **PASS — independently verified** | The guard failures I reported are fixed and the import is now confirmed by direct read-only inspection of the persisted store, not by receipt alone. Re-measured against current code, all five guards pass: compressed size vs 128 MiB; expanded size vs a raised 1 GiB; 179 columns vs a raised 256; the supplied row count vs a raised ceiling of 250,000; worst member ratio 7.9 vs 200. The persisted store carries `catalog_items` holding every supplied row as a distinct record with every key column populated, plus 5 aliases, in the application schema (`invoices`/`catalog_items`/`aliases`/`exports`) rather than the reference extract, timestamped during the reported run and naming the supplied master as its source. Remaining gap is durability, not capability: no regression exercises a wide many-row import, so the raised guards can silently regress. A synthetic generator for that test is available and needs no private data. |
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

Direct measurement of the imported master settles it in the opposite direction. Of 114,812 real
`unit_cost` values, **37.0% carry more than two decimal places** — 20.8% at three and 16.2% at four.
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
| Expanded archive size | 100 MB | **4.5× the limit** | Rejected |
| Header column count | 100 | 179 columns | Rejected |
| Data row count | 100,000 | above the limit | Rejected |

The column guard fires first, at the header, before a single data row is read.

The raised 128 MiB ceiling does not help and is actively misleading for XLSX input, because the
binding constraint is the **expanded** size rather than the uploaded size. A compressed workbook
comfortably inside 128 MiB still expands past the 100 MB guard; this one expands to roughly 4.5
times it. An operator following the documented sequence gets the file accepted on size and then
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
denial-of-service implications of a 476 MB expansion assessed, or the documentation should direct
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
records carry a currency marker, several currencies are present, and roughly seventy per cent of rows
are not AED-denominated. Identical items priced under suppliers of different currencies differ by an
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
