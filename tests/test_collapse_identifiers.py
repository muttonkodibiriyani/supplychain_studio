"""Duplicate-row collapse must not fold rows that disagree on an identifier.

All names, ids, barcodes and prices are fictional fixtures.  Each case runs in
both catalog row orders, because the defect was order-dependent: the surviving
row was whichever ranked first, so the exported UPC of an automatic line
changed when the catalog was re-imported in a different order.
"""

from __future__ import annotations

import unittest

from backend import matching
from backend.matching import match_lines

SUPPLIER = "900001"
LINE = [{"description": "Fictional Site Widget", "uom": "EA"}]


def rows(first: dict, second: dict) -> list[dict]:
    base = {
        "rms_item_id": "RMS-SITE",
        "description": "Fictional Site Widget",
        "supplier_id": SUPPLIER,
        "uom": "EA",
        "unit_cost": 4.0,
    }
    other = {
        "rms_item_id": "RMS-OTHER",
        "catalog_item_id": "o1",
        "description": "Fictional Other Gadget",
        "supplier_id": SUPPLIER,
        "uom": "EA",
        "unit_cost": 9.0,
    }
    return [{**base, "catalog_item_id": "s1", **first}, {**base, "catalog_item_id": "s2", **second}, other]


def both_orders(first: dict, second: dict) -> list[dict]:
    """The line matched against the pair in import order and in reversed order."""
    forward = rows(first, second)
    reverse = [forward[1], forward[0], forward[2]]
    return [match_lines(LINE, forward, [], SUPPLIER)[0], match_lines(LINE, reverse, [], SUPPLIER)[0]]


class IdentifierDisagreementRefusesTheCollapse(unittest.TestCase):
    def assert_refused_naming(self, line: dict, field: str, label: str, values: list[str]) -> None:
        self.assertEqual(line["match_status"], "suggested")
        self.assertIsNone(line["rms_item_id"])
        self.assertIsNone(line["rms_upc"])
        site_rows = [c for c in line["candidates"] if c["rms_item_id"] == "RMS-SITE"]
        self.assertEqual(len(site_rows), 2, line["candidates"])
        for candidate in site_rows:
            self.assertEqual(candidate["reason_code"], matching.COLLAPSE_DISAGREE_CODE)
            self.assertEqual(candidate["reason_owner"], matching.COLLAPSE_DISAGREE_OWNER)
            self.assertEqual(candidate["disagreeing_fields"], {field: values})
            self.assertIn(f"2 distinct {label}s ({', '.join(values)})", candidate["reason"])
            self.assertIn("not collapsed", candidate["reason"])
            self.assertIn(f"[{matching.COLLAPSE_DISAGREE_CODE}: {field}]", candidate["reason"])
        self.assertTrue(any(f"distinct {label}s" in w for w in line["match_warnings"]), line["match_warnings"])

    def test_1_two_rows_identical_except_upc_are_suggested_in_both_orders(self) -> None:
        for line in both_orders({"upc": "5000000000011"}, {"upc": "5000000000028"}):
            self.assert_refused_naming(line, "upc", "UPC", ["5000000000011", "5000000000028"])

    def test_two_rows_identical_except_parent_item_are_suggested_in_both_orders(self) -> None:
        for line in both_orders({"parent_item": "PARENT-A"}, {"parent_item": "PARENT-B"}):
            self.assert_refused_naming(line, "parent_item", "parent item", ["PARENT-A", "PARENT-B"])

    def test_two_rows_identical_except_master_po_are_suggested_in_both_orders(self) -> None:
        for line in both_orders({"master_po_number": "PO-1001"}, {"master_po_number": "PO-1002"}):
            self.assert_refused_naming(line, "master_po_number", "master PO", ["PO-1001", "PO-1002"])

    def test_disagreement_on_two_identifiers_names_both(self) -> None:
        line = both_orders(
            {"upc": "5000000000011", "master_po_number": "PO-1001"},
            {"upc": "5000000000028", "master_po_number": "PO-1002"},
        )[0]
        self.assertEqual(line["match_status"], "suggested")
        fields = line["candidates"][0]["disagreeing_fields"]
        self.assertEqual(set(fields), {"upc", "master_po_number"})
        self.assertIn(f"[{matching.COLLAPSE_DISAGREE_CODE}: upc, master_po_number]", line["candidates"][0]["reason"])


class AgreeingOrUndeclaredIdentifiersStillCollapse(unittest.TestCase):
    def test_2_identical_rows_including_upc_are_automatic_with_the_same_upc_in_both_orders(self) -> None:
        for line in both_orders({"upc": "5000000000011"}, {"upc": "5000000000011"}):
            self.assertEqual(line["match_status"], "auto")
            self.assertEqual(line["rms_item_id"], "RMS-SITE")
            self.assertEqual(line["rms_upc"], "5000000000011")
            self.assertEqual([c["rms_item_id"] for c in line["candidates"]].count("RMS-SITE"), 1)
            self.assertNotIn("reason_code", line["candidates"][0])
            self.assertIn("collapsed", line["candidates"][0]["reason"])

    def test_3_value_versus_empty_folds_and_the_survivor_carries_the_value_in_both_orders(self) -> None:
        # No instance in the replay corpus: every duplicate pair there either
        # agrees on the barcode or declares two different ones.  The rule is
        # specified anyway so that an undeclared sibling never blanks the value.
        for line in both_orders({"upc": "5000000000011"}, {"upc": None}) + both_orders(
            {"upc": ""}, {"upc": "5000000000011"}
        ):
            self.assertEqual(line["match_status"], "auto")
            self.assertEqual(line["rms_upc"], "5000000000011")
            self.assertEqual([c["rms_item_id"] for c in line["candidates"]].count("RMS-SITE"), 1)
        for line in both_orders({"master_po_number": "PO-1001"}, {"master_po_number": None}):
            self.assertEqual(line["match_status"], "auto")
            self.assertEqual(line["rms_po_number"], "PO-1001")
        for line in both_orders({"parent_item": "PARENT-A"}, {"parent_item": None}):
            self.assertEqual(line["match_status"], "auto")
            self.assertEqual(line["rms_parent_item"], "PARENT-A")

    def test_carried_value_is_named_in_the_survivor_reason(self) -> None:
        forward, reverse = both_orders({"upc": None}, {"upc": "5000000000011"})
        # Whichever row survives, the reason says when the value came from a sibling.
        carried = [l for l in (forward, reverse) if "UPC carried from a sibling row" in l["candidates"][0]["reason"]]
        self.assertTrue(carried, [forward["candidates"][0]["reason"], reverse["candidates"][0]["reason"]])

    def test_cost_and_uom_refusals_are_unchanged(self) -> None:
        line = both_orders({"unit_cost": 4.0, "upc": "5000000000011"}, {"unit_cost": 4.5, "upc": "5000000000011"})[0]
        self.assertEqual(line["match_status"], "suggested")
        self.assertIn("2 distinct unit costs", line["candidates"][0]["reason"])
        self.assertNotIn("reason_code", line["candidates"][0])


if __name__ == "__main__":
    unittest.main()
