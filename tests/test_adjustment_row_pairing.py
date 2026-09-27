"""Adjustment rows are recognised by structure, paired in runs, and never dropped.

Fixtures are generated, synthetic layouts under ``tests/fixtures/layouts``;
no corpus page is reproduced here.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from backend.extraction import (
    ADJUSTMENT_UNPAIRED_REASON,
    NON_PRODUCT_REASON,
    _is_contact_footer,
    _is_explicit_discount_adjustment,
    _pair_explicit_discount_rows,
    extract_document,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _row(description: str, quantity: float, unit_price: float, line_total: float, **extra):
    row = {
        "description": description,
        "quantity": quantity,
        "printed_unit_price": unit_price,
        "unit_price": unit_price,
        "line_total": line_total,
        "line_total_basis": "net",
        "gross_line_total": line_total,
        "tax_rate": None,
        "tax_amount": 0.0,
        "source_page": 1,
        "source_rows": [extra.pop("row", 1)] * 2,
        "confidence": 0.94,
    }
    row.update(extra)
    return row


class AdjustmentRecognitionTests(unittest.TestCase):
    def test_zero_or_negative_row_without_any_keyword_is_an_adjustment(self) -> None:
        self.assertTrue(_is_explicit_discount_adjustment(_row("Promotional Price_CODE.000001", 3, 0.0, 0.0)))
        self.assertTrue(_is_explicit_discount_adjustment(_row("Line 7 correction", 3, -1.0, -3.0)))

    def test_rows_that_sell_something_are_not_adjustments(self) -> None:
        self.assertFalse(_is_explicit_discount_adjustment(_row("Discounted Serum", 3, 10.0, 30.0)))
        self.assertFalse(_is_explicit_discount_adjustment(_row("Free sample", 3, 1.0, 0.0)))
        self.assertFalse(_is_explicit_discount_adjustment(_row("Subtotal", 1, 0.0, 0.0)))
        self.assertFalse(_is_explicit_discount_adjustment(_row("", 1, 0.0, 0.0)))
        self.assertFalse(_is_explicit_discount_adjustment(_row("Widget", 1, None, None)))


class AdjustmentPairingTests(unittest.TestCase):
    def test_a_run_of_adjustments_folds_into_the_preceding_product(self) -> None:
        rows = [
            _row("Serum", 3, 10.0, 30.0, row=1),
            _row("Code A", 3, 0.0, 0.0, row=2),
            _row("Code B", 3, -1.0, -3.0, row=3),
            _row("Mist", 2, 5.0, 10.0, row=4),
        ]
        paired, paired_count, unpaired_count = _pair_explicit_discount_rows(rows)

        self.assertEqual((paired_count, unpaired_count), (2, 0))
        self.assertEqual([line["description"] for line in paired], ["Serum", "Mist"])
        self.assertEqual(paired[0]["line_total"], 27.0)
        self.assertEqual(paired[0]["net_unit_price"], 9.0)
        self.assertEqual(paired[0]["paired_source_line_count"], 3)
        self.assertEqual([item["description"] for item in paired[0]["source_adjustments"]], ["Code A", "Code B"])
        self.assertEqual(paired[0]["source_rows"], [1, 3])
        self.assertEqual(paired[1]["line_total"], 10.0)
        self.assertNotIn("source_adjustments", paired[1])

    def test_adjustment_printed_before_its_product_pairs_forward(self) -> None:
        rows = [_row("Code A", 2, -1.0, -2.0, row=1), _row("Mist", 2, 5.0, 10.0, row=2)]
        paired, paired_count, unpaired_count = _pair_explicit_discount_rows(rows)

        self.assertEqual((paired_count, unpaired_count), (1, 0))
        self.assertEqual([line["description"] for line in paired], ["Mist"])
        self.assertEqual(paired[0]["line_total"], 8.0)

    def test_preceding_product_wins_when_both_neighbours_qualify(self) -> None:
        rows = [_row("Serum", 3, 10.0, 30.0), _row("Code A", 3, -1.0, -3.0), _row("Mist", 3, 5.0, 15.0)]
        paired, paired_count, unpaired_count = _pair_explicit_discount_rows(rows)

        self.assertEqual((paired_count, unpaired_count), (1, 0))
        self.assertEqual([line["line_total"] for line in paired], [27.0, 15.0])

    def test_unpairable_adjustment_is_kept_and_flagged_never_dropped(self) -> None:
        rows = [_row("Serum", 3, 10.0, 30.0), _row("Code A", 5, -1.0, -5.0), _row("Mist", 2, 5.0, 10.0)]
        paired, paired_count, unpaired_count = _pair_explicit_discount_rows(rows)

        self.assertEqual((paired_count, unpaired_count), (0, 1))
        self.assertEqual([line["description"] for line in paired], ["Serum", "Code A", "Mist"])
        kept = paired[1]
        self.assertTrue(kept["unpaired_adjustment"])
        self.assertEqual(kept["review_reasons"], [ADJUSTMENT_UNPAIRED_REASON])
        self.assertEqual(kept["line_total"], -5.0)
        self.assertEqual([line["line_total"] for line in paired], [30.0, -5.0, 10.0])

    def test_no_source_row_is_lost_in_any_arrangement(self) -> None:
        rows = [
            _row("Code A", 1, 0.0, 0.0, row=1),
            _row("Serum", 3, 10.0, 30.0, row=2),
            _row("Code B", 3, 0.0, 0.0, row=3),
            _row("Code C", 9, -1.0, -9.0, row=4),
            _row("Code D", 2, 0.0, 0.0, row=5),
            _row("Mist", 2, 5.0, 10.0, row=6),
        ]
        paired, paired_count, unpaired_count = _pair_explicit_discount_rows(rows)

        accounted = sum(line.get("paired_source_line_count", 1) for line in paired)
        self.assertEqual(accounted, len(rows))
        self.assertEqual((paired_count, unpaired_count), (2, 2))
        self.assertEqual(
            [line["description"] for line in paired if line.get("unpaired_adjustment")],
            ["Code A", "Code C"],
        )


class ContactFooterTests(unittest.TestCase):
    def test_contact_lines_are_recognised_by_structure(self) -> None:
        self.assertTrue(_is_contact_footer("TEL +000 0 000 0000 - FAX +000 0 000 0000   1/1"))
        self.assertTrue(_is_contact_footer("Tel: 04 000 0000  Fax: 04 000 0001"))
        self.assertTrue(_is_contact_footer("Phone No. 0000000"))
        self.assertTrue(_is_contact_footer("+00 00 000 0000 page 1 of 2"))

    def test_product_rows_and_codes_are_not_contact_lines(self) -> None:
        self.assertFalse(_is_contact_footer("Cordless telephone handset"))
        self.assertFalse(_is_contact_footer("Fax paper roll 210mm"))
        self.assertFalse(_is_contact_footer("Widget 0000000000000"))
        self.assertFalse(_is_contact_footer("Synthetic Renewal Serum 50ML"))


class AdjustmentRowRunsFixtureTests(unittest.TestCase):
    def test_runs_pair_unpairable_rows_stay_and_footers_carry_no_value(self) -> None:
        result = extract_document(FIXTURES / "layouts" / "adjustment_row_runs.txt")
        diagnostics = result["table_diagnostics"]
        lines = result["lines"]

        self.assertEqual(diagnostics["source_data_rows"], 7)
        self.assertEqual(diagnostics["paired_adjustment_rows"], 2)
        self.assertEqual(diagnostics["unpaired_adjustment_rows"], 1)
        self.assertEqual(diagnostics["non_product_rows"], 1)
        self.assertEqual(len(lines), 5)
        self.assertIn(
            "1 explicit adjustment row(s) could not be paired with a product row and require review.",
            result["warnings"],
        )

        serum, mist, unpaired, cream, footer = lines
        self.assertEqual(serum["description"], "Synthetic Renewal Serum 50ML")
        self.assertEqual(serum["quantity"], 3.0)
        self.assertEqual(serum["line_total"], 27.0)
        self.assertEqual(serum["net_unit_price"], 9.0)
        self.assertEqual(serum["gross_unit_price"], 10.0)
        self.assertEqual(serum["gross_line_total"], 28.35)
        self.assertEqual(serum["tax_amount"], 1.35)
        self.assertEqual(serum["paired_source_line_count"], 3)
        self.assertEqual(serum["line_total_basis"], "net_after_explicit_discount")
        self.assertEqual(serum["extraction_method"], "layout_header+paired_discount")
        self.assertEqual(serum["source_rows"], [8, 10])
        self.assertEqual(len(serum["source_adjustments"]), 2)

        self.assertEqual((mist["quantity"], mist["line_total"]), (2.0, 10.0))
        self.assertEqual(mist["extraction_method"], "layout_header")

        self.assertTrue(unpaired["unpaired_adjustment"])
        self.assertEqual(unpaired["review_reasons"], [ADJUSTMENT_UNPAIRED_REASON])
        self.assertEqual((unpaired["quantity"], unpaired["line_total"]), (5.0, -5.0))

        self.assertEqual((cream["quantity"], cream["line_total"]), (4.0, 8.0))

        self.assertTrue(footer["non_product"])
        self.assertEqual(footer["review_reasons"], [NON_PRODUCT_REASON])
        self.assertEqual(footer["extraction_method"], "layout_header+non_product")
        for field in ("quantity", "unit_price", "printed_unit_price", "line_total", "gross_line_total", "tax_amount"):
            self.assertIsNone(footer[field], field)

    def test_existing_adjacent_pairs_are_unchanged(self) -> None:
        result = extract_document(FIXTURES / "layouts" / "paired_discount_rows.txt")

        self.assertEqual(result["table_diagnostics"]["paired_adjustment_rows"], 2)
        self.assertEqual(result["table_diagnostics"]["unpaired_adjustment_rows"], 0)
        self.assertEqual(result["table_diagnostics"]["non_product_rows"], 0)
        self.assertEqual([line["line_total"] for line in result["lines"]], [24.0, 10.0])
        self.assertEqual([line["paired_source_line_count"] for line in result["lines"]], [2, 2])


if __name__ == "__main__":
    unittest.main()
