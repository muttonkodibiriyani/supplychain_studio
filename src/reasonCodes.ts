// Client copy of the governed reason-code registry (backend/reason_codes.py is
// the source of truth; backend/tests/test_reason_codes.py checks the two agree).
// The live workbench renders the registry the server returns; this copy serves
// the interactive preview, which has no server.
export type ReasonCodeEntry={code:string;owner:string;message:string;level:'invoice'|'line'};
export const OWNER_LABELS:Record<string,string>={brand_operator:'Brand operator',brand_reviewer:'Brand reviewer',item_master_owner:'Item-master owner',finance_owner:'Finance / downstream owner',pilot_owner:'Pilot owner / IT'};
export const REASON_CODES:ReasonCodeEntry[]=[
 {code:'extraction_failed',owner:'pilot_owner',message:'document processing failed; read the error, then retry or record an exception',level:'invoice'},
 {code:'extraction_limit',owner:'pilot_owner',message:'document exceeds a processing limit (size, pages or format); it will not be retried',level:'invoice'},
 {code:'document_type_not_invoice',owner:'brand_operator',message:'document is not classified as an invoice; confirm the type from the source',level:'invoice'},
 {code:'supplier_unresolved',owner:'brand_operator',message:'supplier could not be resolved to a supplier ID; confirm the supplier',level:'invoice'},
 {code:'line_unmapped',owner:'item_master_owner',message:'a line has no RMS item; resolve it against the item master',level:'line'},
 {code:'line_low_confidence',owner:'brand_reviewer',message:'a line has a suggested RMS item that needs confirmation against the source',level:'line'},
 {code:'unit_unconfirmed',owner:'brand_reviewer',message:'unit of measure disagrees with the RMS item or could not be established',level:'line'},
 {code:'price_above_tolerance',owner:'brand_reviewer',message:'invoice cost differs from the RMS reference beyond tolerance',level:'line'},
 {code:'price_comparison_unavailable',owner:'item_master_owner',message:'no RMS cost comparison could be made for a line (no RMS item, unit disagreement, missing RMS cost, currency or missing invoice cost); fix the reference data or acknowledge at review',level:'line'},
 {code:'currency_basis_mismatch',owner:'finance_owner',message:'invoice currency basis differs from the comparison basis (reserved for the currency unit)',level:'invoice'},
 {code:'total_reconciliation_failed',owner:'brand_reviewer',message:'line, subtotal, tax or total arithmetic does not reconcile',level:'invoice'},
 {code:'duplicate_suspected',owner:'finance_owner',message:'another invoice in this workspace shares the supplier and invoice number; confirm before approval',level:'invoice'},
 {code:'header_field_missing',owner:'brand_operator',message:'a required header field is missing or invalid',level:'invoice'},
];
export const REGISTRY:Record<string,ReasonCodeEntry>=Object.fromEntries(REASON_CODES.map(e=>[e.code,e]));
