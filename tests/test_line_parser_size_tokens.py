"""A pack or size token printed inside a description ("250ml", "6x330ml") is
part of the product, never the quantity.  Rows typed as space-separated text
under a heading are not column aligned, and slicing them at the heading
offsets cut "250ml" into a quantity of 250 with unit ML.  A bare number
followed by a unit word ("8 KG") is still a quantity with a UOM."""

from __future__ import annotations

import unittest

from backend.extraction import _extract_lines, _parse_quantity_cell

HEADER = "Item Description Qty UOM Unit Price Amount"


def _one_row(header: str, row: str) -> tuple[str, dict]:
    lines, method, _warnings, _stats = _extract_lines(f"{header}\n{row}\n")
    assert len(lines) == 1, (method, lines)
    return method, lines[0]


class QuantityCellTests(unittest.TestCase):
    def test_attached_size_tokens_are_not_quantities(self) -> None:
        for token in ("250ml", "500g", "1kg", "2l", "33cl", "1.5L", "6x330ml", "6 x 330ml", "12x1kg", "6x330"):
            with self.subTest(token=token):
                self.assertEqual(_parse_quantity_cell(token), (None, None))

    def test_bare_quantity_followed_by_a_unit_word_is_a_quantity(self) -> None:
        self.assertEqual(_parse_quantity_cell("2 EA"), (2.0, "EA"))
        self.assertEqual(_parse_quantity_cell("8 KG"), (8.0, "KG"))
        self.assertEqual(_parse_quantity_cell("1.5 L"), (1.5, "L"))
        self.assertEqual(_parse_quantity_cell("2EA"), (2.0, "EA"))
        self.assertEqual(_parse_quantity_cell("12"), (12.0, None))


class SizeTokenRowTests(unittest.TestCase):
    CASES = (
        ("Fictional Widget 250ml 2 EA 10.00 20.00", "Fictional Widget 250ml", 2.0, "EA", 10.0, 20.0),
        ("Fictional Sugar 500g 7 EA 0.50 3.50", "Fictional Sugar 500g", 7.0, "EA", 0.5, 3.5),
        ("Fictional Flour 1kg 4 PK 2.50 10.00", "Fictional Flour 1kg", 4.0, "PK", 2.5, 10.0),
        ("Fictional Oil 2l 5 BTL 3.00 15.00", "Fictional Oil 2l", 5.0, "BTL", 3.0, 15.0),
        ("Fictional Juice 33cl 6 PCS 1.00 6.00", "Fictional Juice 33cl", 6.0, "PCS", 1.0, 6.0),
        ("Fictional Soda 6x330ml 3 CASE 12.00 36.00", "Fictional Soda 6x330ml", 3.0, "CASE", 12.0, 36.0),
        ("Fictional Water 6 x 330 ml 4 PCS 1.00 4.00", "Fictional Water 6 x 330 ml", 4.0, "PCS", 1.0, 4.0),
    )

    def test_size_token_stays_in_the_description_and_never_becomes_the_quantity(self) -> None:
        for row, description, quantity, uom, unit_price, line_total in self.CASES:
            with self.subTest(row=row):
                method, line = _one_row(HEADER, row)
                self.assertEqual(method, "layout_header")
                self.assertEqual(line["description"], description)
                self.assertEqual(line["quantity"], quantity)
                self.assertEqual(line["uom"], uom)
                self.assertEqual(line["unit_price"], unit_price)
                self.assertEqual(line["line_total"], line_total)

    def test_bare_quantity_followed_by_unit_word_in_a_row(self) -> None:
        method, line = _one_row(HEADER, "Fictional Rice 8 KG 1.25 10.00")
        self.assertEqual(method, "layout_header")
        self.assertEqual(line["description"], "Fictional Rice")
        self.assertEqual((line["quantity"], line["uom"]), (8.0, "KG"))
        self.assertEqual((line["unit_price"], line["line_total"]), (1.25, 10.0))

    def test_size_token_row_without_a_uom_column(self) -> None:
        method, line = _one_row(
            "Description Qty Unit Price Amount", "Fictional Widget 250ml 2 10.00 20.00"
        )
        self.assertEqual(method, "layout_header")
        self.assertEqual(line["description"], "Fictional Widget 250ml")
        self.assertEqual((line["quantity"], line["uom"]), (2.0, None))
        self.assertEqual((line["unit_price"], line["line_total"]), (10.0, 20.0))

    def test_column_aligned_table_with_uom_column_is_unchanged(self) -> None:
        header = "Item Description        Qty   UOM   Unit Price      Amount"
        row = "Fictional Widget 250ml  2     EA         10.00       20.00"
        method, line = _one_row(header, row)
        self.assertEqual(method, "layout_header")
        self.assertEqual(line["description"], "Fictional Widget 250ml")
        self.assertEqual((line["quantity"], line["uom"]), (2.0, "EA"))
        self.assertEqual((line["unit_price"], line["line_total"]), (10.0, 20.0))

    def test_mixed_rows_in_one_table_all_come_from_the_layout_parser(self) -> None:
        text = (
            f"{HEADER}\n"
            "Fictional Widget 250ml 2 EA 10.00 20.00\n"
            "Fictional Rice 8 KG 1.25 10.00\n"
            "Fictional Soda 6x330ml 3 CASE 12.00 36.00\n"
        )
        lines, method, _warnings, _stats = _extract_lines(text)
        self.assertEqual(method, "layout_header")
        self.assertEqual(
            [(line["description"], line["quantity"], line["uom"]) for line in lines],
            [
                ("Fictional Widget 250ml", 2.0, "EA"),
                ("Fictional Rice", 8.0, "KG"),
                ("Fictional Soda 6x330ml", 3.0, "CASE"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
