# Operator training: invoice to item master to consolidated Excel

Validation limit: these Windows instructions were authored and reviewed, but were not executed end to end on a clean Windows computer. Application and container checks ran on Linux. Treat the first Windows installation as a pilot and verify each checkpoint before importing real data.

This guide covers the local pilot workflow for one brand:

```text
isolated brand instance
        ↓
Brand setup: location + supplier/tax rules + current invoice-cost control
        ↓
approved full RMS master or normalized master
        ↓
supplier invoice upload
        ↓
local extraction and item suggestions
        ↓
human review and explicit item confirmation
        ↓
approval
        ↓
ONE consolidated XLSX: Header + Tax_Breakdown + Details
        ↓
controlled downstream validation and handoff
```

Complete [WINDOWS_SETUP.md](WINDOWS_SETUP.md) before using real data. Practice the full procedure with fictional documents first.

## 1. What the application does and does not do

Invoice Studio stores uploaded documents locally, extracts invoice fields, ranks possible RMS item matches, lets an operator correct and approve them, and creates one consolidated XLSX from selected approved invoices.

It does not:

- confirm a GRN;
- amend a purchase order;
- post an invoice to REIM or OmniFlow;
- release payment;
- prove that a downstream system accepted the workbook;
- decide that an uncertain item is correct;
- provide universal extraction or matching accuracy across supplier layouts.

The pilot has no application login or roles. The audit actor is not a verified individual identity. The Windows account, physical device controls, operator log, and handoff record must identify who did the work.

## 2. Roles for a controlled pilot

One person may cover more than one role during a small pilot, but the responsibilities remain distinct.

| Role | Responsibility |
| --- | --- |
| Brand operator | Uploads documents, compares extraction with the source, resolves item mappings, and records exceptions. |
| Brand reviewer | Confirms supplier, invoice identity, quantities, cost, tax, totals, and RMS item identity before approval. |
| Item-master owner | Supplies the current, approved brand RMS reference and resolves missing or ambiguous item identities. |
| Finance/downstream owner | Owns the exact workbook contract, validates the generated file, performs the controlled system upload, and records acceptance or rejection. |
| Pilot owner / IT | Owns releases, brand-instance register, backups, access to the Windows host, incident handling, and recovery tests. |

Do not make the same person silently invent missing master data and approve the resulting invoice. Escalate missing evidence.

## 3. Keep brands isolated

Each brand runs as a separate Compose project and Docker volume. It has its own port, item master, supplier aliases, invoices, exports, and backups. Never use a global catalog or one shared volume across brands.

At the start of a session, the operator must read the controlled brand-instance register and set the assigned values in PowerShell. Example:

```powershell
$BrandSlug = "ulta-ae"
$Port = "8000"
$ProjectName = "invoice-studio-$BrandSlug"
$env:INVOICE_HOST_PORT = $Port

docker compose --project-name $ProjectName up --detach --wait --wait-timeout 180
docker compose --project-name $ProjectName ps
Start-Process "http://localhost:$Port"
```

Before uploading anything, confirm all five items:

1. the expected brand slug and project name are in PowerShell;
2. the URL uses that brand's assigned port;
3. **Brand setup** shows the approved brand, location, supplier/tax rules, the current invoice-net application behavior, and AED 10 RMS comparison threshold;
4. the Item master page shows the expected brand catalog and refresh date/count recorded by the master owner;
5. the worklist contains only that brand's documents.

If any check fails, stop. Do not import, upload, correct, approve, or export until the pilot owner identifies the correct instance.

## 4. Configure Brand setup

Complete **Brand setup** before importing invoices. These settings populate required target fields and control the RMS cost-comparison alert; they are business configuration, not convenience labels.

1. Open **Brand setup**.
2. Under **Workspace and location**, enter the approved brand name, default target location, and location type. Keep codes as text, including leading zeroes.
3. Under **Supplier site and tax codes**, add one rule for each exact RMS supplier ID used in the pilot. Enter its approved supplier site and tax code. Do not infer a rule from a similar supplier name.
4. Under **Invoice cost and RMS comparison**, confirm that the read-only **Target unit cost** says **Invoice net unit cost after discount**. That is the current conservative application behavior: `Details.Unit Cost` comes from the reviewed invoice, while RMS cost is comparison evidence and does not replace it.
5. Enter `10` in **RMS variance review threshold (AED)**. An absolute RMS-versus-invoice difference above AED 10 triggers review without changing the current application output cost. Do not change the threshold unless Finance approves a new control.
6. Select **Save brand settings**, reopen the page, and confirm every value persisted.
7. Record the settings version, operator, reviewer, and approval reference in the controlled brand-instance register.

Missing supplier rules do not become guessed defaults. They must be resolved during invoice review. When settings change, identify and re-review every affected unexported invoice; do not assume previously calculated target fields updated correctly without opening the record.

**Settings are applied once, at processing time.** When an upload is processed, the application copies the default location, location type, and the matching supplier rule's site and tax code onto that invoice record. They are not re-applied afterwards: **Rematch** re-reads only the cost-comparison policy, **Approve** validates the fields already stored on the invoice, and **Retry** touches only failed or queued uploads. So enter Brand setup and every supplier rule *before* uploading. Changing them later does not back-fill invoices that were already processed; those must be corrected by hand in the review screen or uploaded again after the change.

**Commercial-decision status:** invoice-net-only export is the application's current conservative behavior, adopted while the business wording is being confirmed. It is not represented here as an unequivocally user-approved pricing policy. Operators must follow the deployed behavior and must not substitute RMS cost by hand. Commercial signoff is still pending; if the business owner approves a different rule, the release owner must update and revalidate the application and this guide before operators use it.

## 5. Prepare the brand item master

The item master is the source of valid RMS identities, UPCs, supplier scope, UOM, and reference supplier cost. The RMS cost is used to flag a difference for review, never as the exported `Unit Cost`. Use only the approved, current brand package supplied through the internal secure channel. The raw RMS workbook/database and private conversion/mapping files must never be put in GitHub.

The normal UI import path is:

1. Open **Item master** or select **Import item master** from the invoice worklist.
2. Select either:
   - the approved original RMS XLSX, including the supported 179-column source layout; or
   - an approved normalized CSV/XLSX whose displayed base contract includes `rms_item_id` and `description`, with `supplier_id`, `uom`, and `unit_cost` where available.
3. Keep identifiers as text so leading zeroes survive. The native RMS path projects only the approved identity fields—parent item, UPC, description, supplier, UOM, and supplier unit cost—while retaining distinct supplier/item rows.
4. Read the import result and every warning. Rows missing required identity fields or containing invalid cost values are not acceptable evidence.
5. Compare the imported count with the controlled expected count recorded for that brand and master version. Another brand must have its own recorded expectation. Stop on an unexplained difference.
6. Search a controlled sample that covers item IDs, parent items, UPCs, descriptions, supplier scopes, units, and supplier costs, including leading-zero identifiers and duplicate item IDs across suppliers where applicable.
7. Record the source master name, date/version, hash, import time, imported count, warning count, brand, operator, reviewer, and spot-check result outside the target workbook.

A large original master may take several minutes to import. Keep the application open and wait for the imported count or an explicit error; do not repeatedly resubmit the same workbook while it is processing. The retained full-master acceptance run took about four minutes on the test host; this is not a Windows timing guarantee.

The catalog importer has a separate **128 MiB** file ceiling; invoice documents retain their separate 64 MiB ceiling. Support for the original 179-column RMS XLSX is part of the release contract, but it is not considered proven merely because it is documented. Before real invoice work, the pilot owner must retain the successful approved-build import test, and the operator must complete the count and spot checks above.

Re-import updates projected catalog records and adds new ones. It is not an instruction to ignore retirements, duplicates, or changed supplier relationships. The item-master owner must assess retired items, duplicate identities, supplier scope, pack/UOM, UPC, and cost changes before the operator processes new invoices.

The importer projects the large source rather than treating every one of its 179 columns as meaningful. Do not rename or reinterpret unrelated RMS fields. In particular, PO Box, `ORDERABLE_IND`, and `MIN_ORDER_QTY` are not purchase-order numbers.

### Optional import of previously confirmed mappings

A brand owner may provide a privately held, reviewed alias JSON file. Import it only into the matching brand instance, only after the current master is loaded, and only through the release's explicit **Import reviewed matches** control. The server validates every mapping against supplier and catalog scope through `/api/aliases/import`; the file is never bundled automatically.

Record its source hash, approval, imported count, and spot checks. If the approved release does not display the import control, stop and ask the release owner; do not copy the JSON into the source folder or improvise a manual API call. A successfully imported alias is still reviewed mapping reuse, not model training, and must be checked on later invoices.

## 6. Upload invoices

1. Select **Upload invoices**.
2. Optionally enter the supplier ID and supplier name only when they are known from an authoritative source. Do not guess them from a logo or filename.
3. Choose files or a folder. Use one invoice per file; one invoice may contain multiple pages.
4. Check the selected list, then select **Start upload**.
5. Leave Docker Desktop and the application running while the queue processes. The browser sends at most three uploads concurrently; the default service processes with two workers.
6. Review accepted, duplicate, and failed results. Duplicate file bytes return the existing invoice instead of creating another record.

Supported inputs are PDF, PNG, JPG/JPEG, TIFF, BMP, WebP, CSV, XLSX, DOCX, and TXT. PDF text is read directly where possible; scanned pages and images use local Tesseract OCR. Current Docker defaults allow 64 MiB per file and 50 pages/frames. The service request ceiling is 1,000 files, but that ceiling is not a recommended operating batch size. Stage only as many documents as the assigned reviewer can inspect, resolve, and reconcile within the controlled pilot window.

Legacy XLS/DOC, HEIC, ZIP archives, HTML, SVG, encrypted, corrupt, empty, and limit-exceeding files are rejected. Do not remove pages, lower quality, or convert a source merely to bypass a limit. Preserve the original and use the exception process.

## 7. Work the queue

The worklist statuses mean:

| Status | Operator action |
| --- | --- |
| Queued / Processing | Wait. Keep the service running. Refresh the worklist if needed. |
| Needs review | Open the invoice and compare every value with the source. |
| Processing failed | Read the error and capture notes. Correct an operating issue if possible, then use **Retry processing**. Otherwise record an exception. |
| Ready to export | Review and approval completed; the invoice can be selected for consolidation. |
| Exported | The workbook was generated. This does not mean the downstream system accepted it. |

Interrupted queued/processing jobs are recovered when the single application service restarts. Do not run a second application process against the same brand volume.

## 8. Review every invoice against the original

Open a **Needs review** invoice. Use **Document** and **Extracted text** together; OCR text and confidence notes are aids, not evidence that the source was understood correctly.

Review the header:

- supplier name and RMS supplier ID;
- supplier site;
- invoice number and **Document type**; classify it as **Invoice** only after inspecting the source;
- **Target document**, which is the downstream document identifier;
- invoice date;
- explicit purchase-order/order number, if present;
- currency;
- target location, location type, and tax code populated from the approved Brand setup or corrected with authoritative evidence;
- subtotal / total cost excluding tax;
- tax amount;
- total.

Review every line:

- supplier description;
- quantity and UOM;
- unit price/cost and discounts needed to reach net unit cost;
- line total;
- tax evidence;
- RMS item ID, parent item, UPC, pack/size/shade, and supplier scope;
- the read-only **Target unit cost**, which must equal the reviewed invoice net unit cost after discount;
- the RMS reference cost and displayed absolute difference used for the AED 10 review rule.

The target-cost summary is read-only. The target total excluding tax must equal the sum of `Quantity × invoice net Unit Cost` and reconcile to the captured invoice subtotal / Header ex-tax total. The matched RMS cost may raise a comparison warning but must not change the target cost or total. Correct the source unit price/discount evidence, item mapping, or supplier scope, then save and review the calculation again.

Use the original document as the primary evidence. Do not rely on filename, OCR, the top suggestion, or a previously similar invoice when the current source disagrees.

The approval dialog checks required fields, positive quantities, mappings, arithmetic, duplicates, and totals. Passing a software validation means the record is internally consistent; it does not replace comparison with the invoice.

## 9. Resolve RMS item mappings

For an unresolved line, select **Resolve item**:

1. Read the complete supplier description and confirm size, pack, shade/variant, and UOM from the source.
2. Review ranked suggestions. A match score is a ranking signal, not a probability or accuracy percentage.
3. If needed, search by RMS item ID or description.
4. Confirm an item only when its identity and supplier scope agree with authoritative evidence.
5. If no candidate is proven, leave the line unresolved and raise it to the item-master owner. Never choose the closest-looking item merely to complete an export.
6. Select **Save changes** after corrections. Confirm that the worklist and line summary reflect the saved mapping.

An item associated with another supplier scope must not be reused. A global catalog item is eligible only when the master owner intentionally supplied it without a supplier restriction.

### What “learned matches” means

The application does **not** train a machine-learning model from operator work.

When an operator explicitly confirms an RMS item and saves the invoice, the application stores a deterministic alias with this scope:

```text
brand instance + supplier ID + normalized supplier description + UOM → RMS item ID
```

On a later invoice in the same brand instance, supplier scope, description, and UOM, that reviewed alias can be reused. A mapping from another supplier, UOM, or brand is not transferred. Merely viewing a suggestion, importing a master, or approving a different line does not “train” a model.

This is reviewed mapping reuse, not statistical learning. It creates no universal accuracy claim and does not prove that a future invoice is correct. Packaging, descriptions, supplier assortments, and master data change; the operator must still compare the reused mapping with the current source.

Use **Learned matches** to inspect saved mappings. If a stored alias is wrong, stop processing affected invoices, document its supplier/description/UOM and the correct RMS evidence, then re-confirm and save the correct mapping under the controlled correction procedure. Check already reviewed invoices that may have reused the wrong alias.

## 10. Apply the approved conversion rules

These rules govern the exact target conversion. They do not authorize the operator to invent missing data.

### Invoice cost and RMS comparison

The steps below describe the current conservative application behavior pending commercial signoff. They are the operating rule for this release, not a claim that the business owner has finally approved invoice-net-only pricing.

1. Calculate each invoice net unit cost after discount from the source evidence. It must reconcile with the net line amount and quantity.
2. Use that invoice net unit cost for `Details.Unit Cost` **every time**. RMS cost never substitutes for it, whether the RMS value is higher, lower, or within tolerance.
3. Compare the eligible supplier-scoped RMS cost with the invoice net unit cost. Do not compare a parent-item cost, another supplier's cost, or a visually similar item's cost.
4. When the absolute difference is greater than the tolerance in the current tolerance policy (10 in the invoice currency unless an operator has changed it), keep the invoice net unit cost as the target and raise the line for explicit review. Recheck the item mapping, supplier scope, RMS currency/unit, invoice discount, quantity, and UOM.
5. Preserve the available invoice net unit-cost precision; do not round unit prices to two decimals. Multiply each quantity by its net unit cost, round each line extension to cents using half-up rounding, then sum those rounded extensions. That sum must reconcile with `Header.Total Cost Ex Tax` and the reviewed invoice ex-tax total. For example, `3.3333333333 × 300` rounds to `1000.00`. A mismatch is an error, not an allowed pricing choice.
6. If the greater-than-AED-10 RMS comparison is explained after those checks, the reviewer explicitly acknowledges the warning in the approval dialog. The acknowledgement records review; it does not authorize an RMS substitution or an unreconciled Header total.

### Tolerance policy and master cost currency

The tolerance is versioned configuration, not a constant. **Brand setup** shows the policy with its version, owner, effective date, absolute tolerance, optional percentage tolerance, scope (per line or per invoice), and the invoice currencies it applies to. Every saved change appends a row to the policy audit (who, when, before, after); the version increases by one per change. A new workspace starts at version 1 with the absolute tolerance of 10 and no percentage; an existing workspace migrates its previous absolute value to version 1 with no change in behaviour until an operator edits the policy. A percentage tolerance only adds a second, stricter check; it never widens the absolute band.

The cost currency of the item master is recorded per import and is never guessed. A file with a `cost_currency` column uses that column; otherwise state the currency on the import form. Rows imported without a currency show **Not declared** in the item master list and in the imports table, where the currency can be declared later. Undeclared rows keep the previous behaviour (direct comparison, labelled `master_cost_currency_undeclared`).

Conversion rates are entered by an operator in **Brand setup** with a source, the person entering it, and an effective date. Nothing is fetched or assumed. When a master cost currency differs from the invoice currency:

- with no applicable rate (none entered, or none effective on or before the invoice date), the line is classed `currency_basis_mismatch` and requires review; it is not reported as above tolerance;
- with a rate, the master cost is converted, compared under the policy, and the rate row id is recorded on the line.

Same-currency lines compare exactly as before.

### Order number

Use the first available authoritative value in this order:

1. an explicit invoice PO/order number;
2. an explicit approved master PO field;
3. blank.

Never substitute a PO Box, `ORDERABLE_IND`, `MIN_ORDER_QTY`, filename fragment, or guessed number.

### Location, supplier site, tax, UPC, and references

In **Brand setup**, **Include UPC in target workbook** is off by default. This keeps the target UPC column blank to match the reviewed examples, while barcode matching continues internally. Enable it only after the receiving-system owner confirms populated catalog UPCs are accepted. The export audit records the setting used.

Use the evidence and approved brand mapping for the current invoice. A location, site, tax code, UPC, or reference used in a prior example is not blanket evidence for a new supplier or document. Leave the record unresolved and outside the target workbook until its owner supplies authoritative mapping.

Credit notes, RTVs, PODs, purchase-order/support files, non-invoice documents, and unresolved invoices remain outside the consolidated target. Track them in the separate controlled exception/status record.

## 11. Approve an invoice

Select **Approve invoice**, then complete the confirmation only when:

- **Document type** is explicitly set to **Invoice** and the source is a genuine eligible invoice for the active brand;
- supplier and site are proven;
- invoice number/date, target document, and explicit order number rule are correct;
- target location, location type, and tax code agree with the approved brand/supplier rule or documented invoice-specific evidence;
- every product line is present once and mapped to the correct RMS item;
- quantities, UOM, UPC, invoice-net target cost, discount treatment, tax, subtotal, target total, and invoice total reconcile;
- duplicate supplier/invoice-number warnings are resolved;
- every displayed validation issue is cleared;
- all unresolved assumptions are in the exception process rather than hidden in a field.

If an RMS reference cost differs from the invoice net unit cost by more than AED 10, the approval dialog requires the reviewer to acknowledge the cost-comparison warning. Recheck the mapping, supplier, unit, invoice discount, and both values before ticking it. `Details.Unit Cost` remains the invoice net value. A target total that does not reconcile to the reviewed invoice ex-tax total must be corrected and cannot be waived by this acknowledgement.

Approval changes the invoice to **Ready to export**. It enables consolidation only. It does not post, receive, release, or pay anything.

## 12. Generate one consolidated workbook

1. Filter the worklist to **Ready to export**.
2. Select only the approved invoices for the same controlled batch and brand. Page-level selection keeps your selections from other pages. After selecting an invoice, **Select all approved matching search** selects approved matches across pages (up to 5,000); narrow the search for larger batches. This selects previously approved invoices and never approves documents for you.
3. Select **Export selected**.
4. Read the confirmation, then download the workbook once.
5. Save it in the approved private output location outside the GitHub source folder.
6. Record the batch, included invoice IDs/source hashes, operator, reviewer, generated filename, time, and file SHA-256 in the external handoff record.

The batch output is **one XLSX with exactly three sheets in this order**:

| Sheet | Exact columns, in order | Row rule |
| --- | --- | --- |
| `Header` | `Transaction Number`; `Document`; `Supplier Site`; `Order No`; `Location`; `Location Type`; `Document Date`; `Total Cost Ex Tax`; `Tax Amount`; `Ref No. 1`; `Ref No. 2`; `Ref No. 3`; `Comment` | One row per eligible approved invoice. |
| `Tax_Breakdown` | `Transaction Number`; `Tax Code`; `Tax Basis` | Applicable tax rows for included invoices. |
| `Details` | `Transaction Number`; `Item`; `UPC`; `Unit Cost`; `Quantity`; `Unit Tax Code` | Every eligible product line from included invoices. |

`Transaction Number` is the link across all three sheets. Every transaction in `Tax_Breakdown` or `Details` must exist once in `Header`. The workbook must have no extra sheet, extra column, changed header, reordered header, or blank artifact row.

For every Details row, `Unit Cost` is the reviewed **invoice net unit cost after discount**. RMS cost is not exported in its place. For each transaction, the sum of `Details.Unit Cost × Details.Quantity` must equal `Header.Total Cost Ex Tax` and the reviewed invoice ex-tax total.

The earlier internal-review workbook shape with README, Tax, Detail, or Audit sheets is not the target. If a release generates those names, stop and report a release defect; do not rename tabs by hand and call it complete.

## 13. Validate the workbook before handoff

Open the downloaded file in desktop Excel or the approved corporate XLSX viewer. Do not enable macros or external links; the target is an `.xlsx` data workbook.

Complete these checks:

1. There is exactly one workbook for the batch and exactly three tabs: `Header`, `Tax_Breakdown`, `Details`.
2. Tab names, order, headers, and column order exactly match section 12.
3. `Header` contains one row for each selected eligible invoice, with no duplicate transaction number.
4. Every transaction number in `Tax_Breakdown` and `Details` exists in `Header`; no row points to a missing transaction.
5. Every source product line appears once in `Details`; non-product, credit-note, RTV, POD, and unresolved rows do not appear.
6. Item, UPC, invoice net unit cost after discount, quantity, and tax code agree with the reviewed record and approved mappings. No Details unit cost was substituted from RMS.
7. For each invoice, the sum of `Details.Unit Cost × Details.Quantity` equals `Header.Total Cost Ex Tax` and the reviewed source ex-tax total; tax basis and tax amount also reconcile under the approved rules.
8. Every RMS-versus-invoice unit-cost difference above AED 10 was investigated and explicitly acknowledged without changing the invoice-net output cost.
9. Dates, leading zeros, identifiers, negative/credit behavior, text encoding, and decimal precision survive correctly.
10. There are no formulas or values beginning as executable spreadsheet formulas in supplier-controlled text fields.
11. The workbook file hash and row counts are recorded in the external handoff record.

Do not insert a cover sheet, notes, totals, formulas, comments, or exception rows into the target workbook. Put operational evidence and exceptions in the separate controlled record.

## 14. Downstream handoff

1. Transfer the validated workbook through the approved internal finance channel. Do not use personal email, consumer file sharing, GitHub, or a public ticket.
2. The authorized downstream owner performs the receiving-system validation/upload.
3. Record accepted/rejected status, time, operator, receiving system reference, and any rejected row/message outside the target workbook.
4. If rejected, keep the original export and error evidence. Correct the source review or mapping in Invoice Studio, reapprove as required, and generate a new traceable export. Do not silently edit the downloaded workbook.
5. Mark the business step complete only after the downstream owner confirms acceptance. The Invoice Studio **Exported** status alone means only that a file was generated.

## 15. Exceptions and escalation

On the invoice worklist, choose **Download exceptions** to save a separate CSV of documents that are not currently eligible for target export and their review reasons. This covers the whole brand workspace, independent of the current worklist search. It is a snapshot: regenerate it after corrections. Files rejected before intake have no stored invoice record; retain their upload error separately.

The **Exceptions** page (the exception workbench) shows the same held invoices grouped by governed reason code. Each code names the role that owns the next action (brand operator, brand reviewer, item-master owner, finance/downstream owner, or pilot owner) and shows how long the oldest invoice in the group has waited; open any row to review it. The same codes appear on each invoice and in the two right-hand columns of the exceptions CSV, so the offline record below can use them verbatim. A `duplicate_suspected` code means another invoice in this workspace shares the supplier and invoice number (and, when strong, the total and date); the other invoice ID is shown, nothing is deleted or merged automatically, and approval stays blocked until the business event is confirmed. Discount, credit, rebate and other adjustment rows that have no RMS item carry `adjustment_unpaired` (brand reviewer) rather than `line_unmapped`, so they do not sit in the item-master owner's queue; they are kept and flagged, never dropped, and the reviewer pairs them with the product lines they adjust. `price_above_tolerance` is assigned only where an RMS cost comparison was made and exceeded tolerance; a line whose comparison could not be made because it has no RMS item yet, or its unit is in disagreement, is shown as a state on the review page, not as an exception anyone owns, because it resolves when the line is matched. A line that is matched (automatically or by hand) to an RMS item that has no master cost to compare against carries `rms_cost_missing` (item-master owner): approval is blocked, ticking the cost-review acknowledgement does not clear it, and it resolves when the item master supplies the cost and the invoice is rematched. The panel above the groups shows the three control KPIs as counts with their denominators; read them as "x of N" for this workspace, never as a general accuracy claim. K1 (touchless) and K3 (cycle time) show "Not evaluable" with the reason until at least one invoice has reached ready or exported, because a zero there would not distinguish "nothing touchless" from "nothing approved yet". K2 (first-time match) is fixed at extraction time for invoices processed by this release; for older records it falls back to the current line states and may undercount after a rematch until the matcher stops promoting automatic matches to confirmed (a separate matcher defect, tracked outside this guide). For that reason the K2 shown here has not been reconciled with the programme's recorded Metric 2: that reconciliation is BLOCKED-ON-DEFECT, and both figures will be re-measured on the same tree and the same database copy once the fix lands.

Keep an exception/status record outside the three-sheet workbook. Record at least the brand, source filename/hash, invoice/document number if known, classification, current stage, reason, owner, action, and decision timestamp.

| Exception | Required response |
| --- | --- |
| Wrong brand instance | Stop immediately; do not approve/export. Notify the pilot owner and assess recovery from the clean backup. |
| Brand setup missing or wrong | Stop invoice work; correct and independently verify brand, location, supplier/tax rules, invoice-net cost basis, and AED 10 RMS comparison threshold, then re-review affected records. |
| Full RMS import count/warnings differ from the approved expectation | Do not begin invoice matching. Retain the import result and escalate to the item-master owner/release owner. |
| Credit note, RTV, POD, or support document | Classify and route separately; do not include in the invoice target. |
| Encrypted/corrupt/unsupported/oversize document | Preserve the original and request an approved source or exception process. Do not drop pages or provenance. |
| OCR unreadable or fields missing | Manually review the original; correct only evidenced values. Escalate if evidence is unclear. |
| No proven RMS item / ambiguous size or pack | Leave unresolved and send to the item-master owner. |
| Supplier/site/location/tax/UPC not evidenced | Leave unresolved; request authoritative mapping. |
| Duplicate supplier invoice number | Investigate the existing record and business event before approval. |
| RMS-versus-invoice cost difference above AED 10 is unexplained | Do not tick the acknowledgement. Stop approval; Finance/item-master owner resolves the source, mapping, unit, or master value. |
| Export target cost differs from invoice net cost, or Header does not reconcile to Details | Stop approval/export and report a defect. RMS cost must never substitute, and the ex-tax totals must agree. |
| Cost or tax otherwise does not reconcile | Stop approval; Finance/item-master owner resolves it. |
| Wrong learned alias | Stop affected work, correct under review, and inspect prior invoices that may have reused it. |
| Workbook contract differs | Do not rename/edit it into shape. Record a release defect and retain evidence. |
| Downstream rejection | Retain the original file/error, correct in the application, and issue a new traceable export. |

## 16. End-of-session procedure

1. Confirm no invoice was left with unsaved edits.
2. Record queued, processing, needs-review, ready, failed, exported, and exception counts for the brand.
3. Confirm downloaded workbooks and exception records are in approved private storage, outside the source folder.
4. Back up the brand after an important reviewed batch using `WINDOWS_SETUP.md`.
5. Stop the brand service:

   ```powershell
   docker compose --project-name $ProjectName stop
   ```

6. Lock the Windows computer and follow the approved retention schedule for originals, exports, and backups.

Never use `docker compose down -v`, `docker compose down --volumes`, or `docker volume prune` on the pilot computer.

## 17. Training completion check

Before receiving access to real invoices, an operator should demonstrate with fictional data that they can:

- identify and start the correct isolated brand project and port;
- verify health and open the real local application rather than preview mode;
- configure and re-open fictional Brand setup values, including supplier/tax, invoice-net cost basis, and the AED 10 RMS comparison threshold;
- import and spot-check an approved fictional normalized master;
- explain the 128 MiB full-RMS contract, expected-count check, and why an approved-build test is required before using the real 179-column master;
- upload a multipage invoice and interpret queue/failure states;
- correct extracted header, classification, target fields, and line values from the original;
- reject an ambiguous suggestion, search the master, and confirm a proven item;
- explain why a learned mapping is supplier/UOM scoped and is not ML model training;
- prove each read-only target cost is the invoice net unit cost after discount and that Header reconciles to Details;
- investigate an RMS difference above AED 10 and use the acknowledgement only after the comparison is explained, without substituting RMS cost;
- approve only a classified and reconciled invoice;
- create and validate the exact three-sheet consolidated workbook;
- route an exception without inventing data;
- create and verify a brand backup;
- explain why **Exported** is different from downstream acceptance.

The reviewer records training completion and any restrictions in the controlled operator register.

## 18. Measure the pilot without overstating accuracy

Report results separately by brand, supplier layout, file type, and scan quality. Useful measures include reviewed invoices, reviewed lines, fields corrected, mappings corrected, unresolved lines, exceptions, handling time, and downstream rejection reasons.

Do not label suggestion scores as probabilities. Do not calculate “accuracy” from unreviewed output, a few successful examples, or saved aliases alone. A defensible item-match rate needs a reviewed ground-truth set and a stated denominator. Until that exists, report observed counts and limitations rather than a universal percentage.
