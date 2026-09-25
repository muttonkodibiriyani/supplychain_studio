#!/usr/bin/env python3
"""Independent read-only conformance checker for the exact consolidated target workbook.

Validates a candidate .xlsx against the three-sheet upload contract.
Reports shapes, counts and arithmetic without printing invoice identifiers or amounts.

Usage: python3 target_conformance.py <workbook.xlsx> [more.xlsx ...]
Exit 0 = every workbook conformant. Exit 1 = at least one FAIL.
"""
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import openpyxl

SHEETS = ["Header", "Tax_Breakdown", "Details"]
COLUMNS = {
    "Header": [
        "Transaction Number", "Document", "Supplier Site", "Order No", "Location",
        "Location Type", "Document Date", "Total Cost Ex Tax", "Tax Amount",
        "Ref No. 1", "Ref No. 2", "Ref No. 3", "Comment",
    ],
    "Tax_Breakdown": ["Transaction Number", "Tax Code", "Tax Basis"],
    "Details": ["Transaction Number", "Item", "UPC", "Unit Cost", "Quantity", "Unit Tax Code"],
}
# Leading characters Excel treats as the start of a formula.
INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
# Current application policy retains invoice net costs. Commercial signoff is separate.
ARITHMETIC_TOLERANCE = Decimal("0.01")


def dec(value):
    """Coerce a cell to Decimal, or None when it is not a usable number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
        return number if number.is_finite() else None
    except (InvalidOperation, AttributeError):
        return None


def rows_of(sheet, width):
    """Data rows below the header, trimmed to the contract width."""
    out = []
    for row in sheet.iter_rows(min_row=2, max_col=width, values_only=True):
        if all(cell is None or str(cell).strip() == "" for cell in row):
            continue
        out.append(row)
    return out


def check(path):
    fails, warns, notes = [], [], []
    book = openpyxl.load_workbook(path, data_only=False)

    # --- structure: exact sheets, exact order, nothing extra -------------------
    if book.sheetnames != SHEETS:
        fails.append("Sheet names/order do not match Header, Tax_Breakdown, Details")
        missing = [s for s in SHEETS if s not in book.sheetnames]
        if missing:
            book.close()
            return fails, warns, notes  # cannot validate content without the sheets

    # --- headers: exact text, exact order, no extra columns -------------------
    for name in SHEETS:
        sheet = book[name]
        want = COLUMNS[name]
        got = [c.value for c in sheet[1]]
        if got[: len(want)] != want:
            fails.append(f"{name}: header row does not match the required columns")
        if sheet.max_column > len(want):
            extra = [c for c in got[len(want):] if c is not None]
            fails.append(
                f"{name}: {sheet.max_column} columns present, contract allows {len(want)}"
                + ("; extra headers" if extra else "; trailing blank columns")
            )

    header = book["Header"]
    tax = book["Tax_Breakdown"]
    details = book["Details"]
    h_rows = rows_of(header, len(COLUMNS["Header"]))
    t_rows = rows_of(tax, len(COLUMNS["Tax_Breakdown"]))
    d_rows = rows_of(details, len(COLUMNS["Details"]))

    # --- blank artifact rows ---------------------------------------------------
    for name, sheet, kept in (("Header", header, h_rows), ("Tax_Breakdown", tax, t_rows),
                              ("Details", details, d_rows)):
        declared = max(sheet.max_row - 1, 0)
        if declared != len(kept):
            fails.append(
                f"{name}: {declared} rows below the header but {len(kept)} carry data; "
                f"{declared - len(kept)} blank artifact row(s)"
            )

    # --- Transaction Number keys ----------------------------------------------
    def key(row):
        return None if row[0] is None else str(row[0]).strip()

    h_keys = [key(r) for r in h_rows]
    blank_keys = sum(1 for k in h_keys if not k)
    if blank_keys:
        fails.append(f"Header: {blank_keys} row(s) with a blank Transaction Number")
    seen, dupes = set(), set()
    for k in h_keys:
        if k in seen:
            dupes.add(k)
        seen.add(k)
    if dupes:
        fails.append(f"Header: Transaction Number must be one row per invoice; {len(dupes)} duplicated")

    for name, rows in (("Tax_Breakdown", t_rows), ("Details", d_rows)):
        orphans = {key(r) for r in rows if key(r) not in seen}
        if orphans:
            fails.append(f"{name}: {len(orphans)} Transaction Number(s) with no matching Header row")

    covered = {key(r) for r in d_rows}
    uncovered = seen - covered
    if uncovered:
        # An invoice whose Details do not reconcile to its stated total cannot be in the target at
        # all; a header with no lines can never reconcile, so this is a failure, not a warning.
        fails.append(f"Header: {len(uncovered)} invoice(s) carry no Details line at all")

    # --- formula injection -----------------------------------------------------
    injected = 0
    for name in SHEETS:
        for row in book[name].iter_rows(values_only=True):
            for cell in row:
                if isinstance(cell, str) and cell.strip().startswith(INJECTION_PREFIXES):
                    injected += 1
    if injected:
        fails.append(f"{injected} text cell(s) begin with a formula-injection character")

    # --- identifier typing: leading zeros must survive ------------------------
    # An identifier stored as a number has already lost any leading zeros, and the loss is not
    # recoverable from the workbook. Flag numeric identifiers so the exporter is checked at source.
    IDENTIFIERS = {
        "Header": [("Transaction Number", 0), ("Document", 1), ("Supplier Site", 2), ("Order No", 3), ("Location", 4), ("Location Type", 5)],
        "Tax_Breakdown": [("Transaction Number", 0), ("Tax Code", 1)],
        "Details": [("Transaction Number", 0), ("Item", 1), ("UPC", 2), ("Unit Tax Code", 5)],
    }
    for name, columns in IDENTIFIERS.items():
        rows = {"Header": h_rows, "Tax_Breakdown": t_rows, "Details": d_rows}[name]
        for label, idx in columns:
            numeric = sum(1 for r in rows if isinstance(r[idx], (int, float)) and not isinstance(r[idx], bool))
            if numeric:
                fails.append(
                    f"{name}.{label}: {numeric} value(s) stored as a number, not text; "
                    f"any leading zero is already lost"
                )

    # --- per-invoice arithmetic: sum(Details) vs Header Total Cost Ex Tax ------
    extended = {}
    lines_for = {}
    unusable = 0
    for row in d_rows:
        unit, qty = dec(row[3]), dec(row[4])
        if unit is None or qty is None or unit < 0 or qty <= 0:
            unusable += 1
            continue
        extended[key(row)] = extended.get(key(row), Decimal("0")) + (unit * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if unusable:
        fails.append(f"Details: {unusable} line(s) have a non-numeric or invalid Unit Cost or Quantity")

    mismatched = []
    for row in h_rows:
        stated = dec(row[7])
        if stated is None:
            fails.append(f"Header: Total Cost Ex Tax is not numeric for one invoice")
            continue
        computed = extended.get(key(row))
        if computed is None:
            continue
        gap = abs(computed - stated)
        if gap > ARITHMETIC_TOLERANCE:
            mismatched.append((key(row), stated, computed.quantize(Decimal("0.01")), gap))
        lines_for.setdefault(key(row), 0)
    for k, stated, computed, gap in mismatched:
        fails.append(
            "Header: Total Cost Ex Tax does not equal sum of Details"
        )

    tax_basis = {}
    for row in t_rows:
        basis = dec(row[2])
        if basis is None:
            fails.append("Tax_Breakdown: non-numeric Tax Basis")
        else:
            tax_basis[key(row)] = tax_basis.get(key(row), Decimal("0")) + basis
    for row in h_rows:
        stated = dec(row[7])
        if key(row) not in tax_basis:
            fails.append("Header: invoice has no Tax_Breakdown row")
        elif stated is not None and abs(tax_basis[key(row)] - stated) > ARITHMETIC_TOLERANCE:
            fails.append("Tax_Breakdown: Tax Basis does not reconcile to Header")
    book.close()
    notes.append(
        f"{len(h_rows)} invoice(s), {len(t_rows)} tax row(s), {len(d_rows)} detail line(s); "
        f"{len(h_rows) - len(mismatched)} invoice(s) reconcile within {ARITHMETIC_TOLERANCE}"
    )
    return fails, warns, notes


def main(paths):
    worst = 0
    for index, path in enumerate(paths, start=1):
        print(f"\n=== Workbook {index}")
        try:
            fails, warns, notes = check(path)
        except Exception as exc:  # a workbook we cannot open is a failure, not a crash
            print(f"  FAIL  cannot validate: {exc.__class__.__name__}")
            worst = 1
            continue
        for note in notes:
            print(f"  note  {note}")
        for warn in warns:
            print(f"  WARN  {warn}")
        for fail in fails:
            print(f"  FAIL  {fail}")
        print(f"  ==> {'CONFORMANT' if not fails else 'NON-CONFORMANT'}")
        worst = max(worst, 1 if fails else 0)
    return worst


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
