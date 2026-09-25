from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from backend import matching as matching_module
from backend.matching import (
    CatalogValidationError,
    enrich_invoice,
    match_lines,
    normalize_description,
    suggest_matches,
)


FIXTURES = Path(__file__).parent / "fixtures"


class MatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = json.loads((FIXTURES / "sample_catalog.json").read_text(encoding="utf-8"))

    def test_unique_exact_normalized_description_is_auto(self) -> None:
        matched = match_lines(
            [{"description": "Hydrating Cleanser 50ml", "uom": "EA"}],
            self.catalog,
            supplier_id="SUP-1007",
        )[0]

        self.assertEqual(matched["match_status"], "auto")
        self.assertEqual(matched["rms_item_id"], "RMS-50100")
        self.assertEqual(matched["confidence"], 100.0)

    def test_spelling_and_abbreviation_variants_rank_correct_item(self) -> None:
        matched = match_lines(
            [{"description": "Hydratng Cleanser 50 millilitres", "uom": "each"}],
            self.catalog,
            supplier_id="SUP-1007",
        )[0]

        self.assertEqual(matched["candidates"][0]["rms_item_id"], "RMS-50100")
        self.assertIn(matched["match_status"], {"auto", "suggested"})
        self.assertNotEqual(matched["candidates"][0]["rms_item_id"], "RMS-50101")

    def test_size_conflict_cannot_suggest_or_auto_match(self) -> None:
        catalog = [
            {"rms_item_id": "RMS-100", "description": "Hydrating Cleanser 100 ml", "uom": "EA"}
        ]
        matched = match_lines(
            [{"description": "Hydrating Cleanser 50ml", "uom": "EA"}], catalog
        )[0]

        self.assertEqual(matched["match_status"], "unmatched")
        self.assertIsNone(matched["rms_item_id"])
        self.assertLessEqual(matched["candidates"][0]["score"], 45)
        self.assertIn("size conflict", matched["candidates"][0]["reason"])

    def test_pack_count_conflict_stays_unmatched(self) -> None:
        catalog = [
            {"rms_item_id": "PAD-1", "description": "Cotton Pads 100 count pack of 1", "uom": "PACK"}
        ]
        matched = match_lines(
            [{"description": "Cotton Pads 100 count pack of 2", "uom": "PACK"}], catalog
        )[0]

        self.assertEqual(matched["match_status"], "unmatched")
        self.assertIn("pack count conflict", matched["candidates"][0]["reason"])

    def test_unit_conflict_blocks_identical_name(self) -> None:
        catalog = [{"rms_item_id": "CASE-1", "description": "Display Stand", "uom": "CASE"}]
        matched = match_lines([{"description": "Display Stand", "uom": "EA"}], catalog)[0]

        self.assertEqual(matched["match_status"], "unmatched")
        self.assertIn("UOM conflict", matched["candidates"][0]["reason"])

    def test_shade_conflict_blocks_near_duplicate(self) -> None:
        catalog = [
            {"rms_item_id": "LIP-11", "description": "Velvet Lip Color Shade 11", "uom": "EA"}
        ]
        matched = match_lines(
            [{"description": "Velvet Lip Colour Shade 10", "uom": "EA"}], catalog
        )[0]

        self.assertEqual(matched["match_status"], "unmatched")
        self.assertIn("shade conflict", matched["candidates"][0]["reason"])

    def test_supplier_scoped_alias_only_applies_to_its_supplier(self) -> None:
        catalog = [
            {"rms_item_id": "RMS-50100", "description": "Hydrating Cleanser 50 ml", "uom": "EA"}
        ]
        aliases = [
            {
                "supplier_id": "SUP-A",
                "description": "HC Blue Small",
                "rms_item_id": "RMS-50100",
                "uom": "EA",
            }
        ]
        supplier_a = match_lines(
            [{"description": "HC Blue Small", "uom": "EA"}], catalog, aliases, "SUP-A"
        )[0]
        supplier_b = match_lines(
            [{"description": "HC Blue Small", "uom": "EA"}], catalog, aliases, "SUP-B"
        )[0]

        self.assertEqual(supplier_a["match_status"], "auto")
        self.assertEqual(supplier_a["rms_item_id"], "RMS-50100")
        self.assertNotEqual(supplier_b["match_status"], "auto")
        self.assertIsNone(supplier_b["rms_item_id"])

    def test_alias_uom_is_a_hard_scope(self) -> None:
        catalog = [{"rms_item_id": "RMS-1", "description": "Cotton Pad", "uom": "PACK"}]
        aliases = [
            {
                "supplier_id": "SUP-A",
                "description": "CP",
                "rms_item_id": "RMS-1",
                "uom": "PACK",
            }
        ]
        wrong_unit = match_lines(
            [{"description": "CP", "uom": "EA"}], catalog, aliases, "SUP-A"
        )[0]

        self.assertNotEqual(wrong_unit["match_status"], "auto")
        self.assertIsNone(wrong_unit["rms_item_id"])

        missing_unit = match_lines(
            [{"description": "CP"}], catalog, aliases, "SUP-A"
        )[0]
        self.assertNotEqual(missing_unit["match_status"], "auto")
        self.assertIsNone(missing_unit["rms_item_id"])

    def test_same_alias_description_can_have_distinct_uom_targets(self) -> None:
        catalog = [
            {"rms_item_id": "PAD-EA", "description": "Cotton Pad Single", "uom": "EA"},
            {"rms_item_id": "PAD-PK", "description": "Cotton Pad Retail Pack", "uom": "PACK"},
        ]
        aliases = [
            {"supplier_id": "SUP-A", "description": "CP", "rms_item_id": "PAD-EA", "uom": "EA"},
            {"supplier_id": "SUP-A", "description": "CP", "rms_item_id": "PAD-PK", "uom": "PACK"},
        ]

        each = match_lines([{"description": "CP", "uom": "EA"}], catalog, aliases, "SUP-A")[0]
        pack = match_lines([{"description": "CP", "uom": "PK"}], catalog, aliases, "SUP-A")[0]
        missing = match_lines([{"description": "CP"}], catalog, aliases, "SUP-A")[0]

        self.assertEqual(each["rms_item_id"], "PAD-EA")
        self.assertEqual(pack["rms_item_id"], "PAD-PK")
        self.assertEqual(each["match_status"], "auto")
        self.assertEqual(pack["match_status"], "auto")
        self.assertIsNone(missing["rms_item_id"])
        self.assertNotEqual(missing["match_status"], "auto")

    def test_unscoped_alias_record_is_rejected(self) -> None:
        with self.assertRaisesRegex(CatalogValidationError, "requires supplier_id"):
            match_lines(
                [{"description": "HC"}],
                self.catalog,
                [{"description": "HC", "rms_item_id": "RMS-50100"}],
                "SUP-1007",
            )

    def test_valid_supplied_id_is_confirmed(self) -> None:
        matched = match_lines(
            [{"description": "supplier wording", "rms_item_id": "RMS-50100"}],
            self.catalog,
            supplier_id="SUP-1007",
        )[0]

        self.assertEqual(matched["match_status"], "confirmed")
        self.assertEqual(matched["confidence"], 100.0)

    def test_invalid_supplied_id_is_removed_and_flagged(self) -> None:
        matched = match_lines(
            [{"description": "Hydrating Cleanser 50ml", "rms_item_id": "DOES-NOT-EXIST"}],
            self.catalog,
            supplier_id="SUP-1007",
        )[0]

        self.assertNotEqual(matched["match_status"], "confirmed")
        self.assertTrue(any("does not exist" in warning for warning in matched["match_warnings"]))

    def test_duplicate_exact_descriptions_require_review(self) -> None:
        catalog = [
            {"rms_item_id": "ONE", "description": "Generic Tissue Box", "uom": "BOX"},
            {"rms_item_id": "TWO", "description": "Generic Tissue Box", "uom": "BOX"},
        ]
        matched = match_lines(
            [{"description": "Generic Tissue Box", "uom": "BOX"}], catalog
        )[0]

        self.assertEqual(matched["match_status"], "suggested")
        self.assertIsNone(matched["rms_item_id"])
        self.assertEqual(len(matched["candidates"]), 2)

    def test_supplier_specific_catalog_does_not_leak(self) -> None:
        catalog = [
            {"rms_item_id": "A", "description": "House Serum", "supplier_id": "SUP-A"},
            {"rms_item_id": "B", "description": "House Serum", "supplier_id": "SUP-B"},
        ]
        result = match_lines([{"description": "House Serum"}], catalog, supplier_id="SUP-B")[0]

        self.assertEqual(result["rms_item_id"], "B")
        self.assertEqual([candidate["rms_item_id"] for candidate in result["candidates"]], ["B"])

    def test_unique_exact_supplier_upc_and_uom_auto_match_without_trimming_zeroes(self) -> None:
        catalog = [
            {
                "catalog_item_id": "cat-sup-a",
                "rms_item_id": "PARENT-A",
                "upc": "000123456789",
                "description": "Master wording unlike invoice text",
                "supplier_id": "SUP-A",
                "uom": "EA",
            },
            {
                "catalog_item_id": "cat-sup-b",
                "rms_item_id": "PARENT-B",
                "upc": "000123456789",
                "description": "Another supplier product",
                "supplier_id": "SUP-B",
                "uom": "EA",
            },
        ]
        matched = match_lines(
            [
                {
                    "description": "Factur-X supplier wording",
                    "upc": "000123456789",
                    "uom": "EA",
                }
            ],
            catalog,
            supplier_id="SUP-A",
        )[0]

        self.assertEqual(matched["match_status"], "auto")
        self.assertEqual(matched["catalog_item_id"], "cat-sup-a")
        self.assertEqual(matched["rms_item_id"], "PARENT-A")
        self.assertEqual(matched["rms_upc"], "000123456789")
        self.assertIn("Exact supplier-scoped UPC", matched["candidates"][0]["reason"])

        trimmed = match_lines(
            [
                {
                    "description": "Factur-X supplier wording",
                    "upc": "123456789",
                    "uom": "EA",
                }
            ],
            catalog,
            supplier_id="SUP-A",
        )[0]
        self.assertIsNone(trimmed["rms_item_id"])
        self.assertTrue(any("no exact row" in warning for warning in trimmed["match_warnings"]))

    def test_exact_upc_never_crosses_supplier_scope_or_coerces_numbers(self) -> None:
        catalog = [
            {
                "catalog_item_id": "cat-a",
                "rms_item_id": "ITEM-A",
                "upc": "001234567890",
                "description": "Supplier A exact barcode item",
                "supplier_id": "SUP-A",
                "uom": "EA",
            }
        ]
        wrong_supplier = match_lines(
            [{"description": "Unrelated", "upc": "001234567890", "uom": "EA"}],
            catalog,
            supplier_id="SUP-B",
        )[0]
        numeric_upc = match_lines(
            [{"description": "Supplier A exact barcode item", "upc": 1234567890, "uom": "EA"}],
            catalog,
            supplier_id="SUP-A",
        )[0]

        self.assertIsNone(wrong_supplier["rms_item_id"])
        self.assertIsNone(numeric_upc["rms_item_id"])
        self.assertTrue(any("no exact row" in warning for warning in wrong_supplier["match_warnings"]))
        self.assertTrue(any("no coercion" in warning for warning in numeric_upc["match_warnings"]))

    def test_exact_upc_requires_compatible_nonmissing_uom_and_pack_evidence(self) -> None:
        catalog = [
            {
                "catalog_item_id": "cat-pack",
                "rms_item_id": "PACK-6",
                "upc": "000000000006",
                "description": "Treatment pack of 6",
                "supplier_id": "SUP-A",
                "uom": "PACK",
            }
        ]
        wrong_uom = match_lines(
            [{"description": "Treatment pack of 6", "upc": "000000000006", "uom": "EA"}],
            catalog,
            supplier_id="SUP-A",
        )[0]
        missing_uom = match_lines(
            [{"description": "Treatment pack of 6", "upc": "000000000006"}],
            catalog,
            supplier_id="SUP-A",
        )[0]
        wrong_pack = match_lines(
            [{"description": "Treatment pack of 4", "upc": "000000000006", "uom": "PACK"}],
            catalog,
            supplier_id="SUP-A",
        )[0]

        for result in (wrong_uom, missing_uom, wrong_pack):
            self.assertIsNone(result["rms_item_id"])
            self.assertNotEqual(result["match_status"], "auto")
        self.assertTrue(any("UOM evidence" in warning for warning in wrong_uom["match_warnings"]))
        self.assertTrue(any("UOM evidence" in warning for warning in missing_uom["match_warnings"]))
        self.assertTrue(any("pack evidence" in warning for warning in wrong_pack["match_warnings"]))

    def test_duplicate_exact_supplier_upc_remains_reviewable(self) -> None:
        catalog = [
            {
                "catalog_item_id": "cat-one",
                "rms_item_id": "ITEM-ONE",
                "upc": "000777777777",
                "description": "Exact invoice wording",
                "supplier_id": "SUP-A",
                "uom": "EA",
            },
            {
                "catalog_item_id": "cat-two",
                "rms_item_id": "ITEM-TWO",
                "upc": "000777777777",
                "description": "Different master wording",
                "supplier_id": "SUP-A",
                "uom": "EA",
            },
        ]
        matched = match_lines(
            [{"description": "Exact invoice wording", "upc": "000777777777", "uom": "EA"}],
            catalog,
            supplier_id="SUP-A",
        )[0]

        self.assertIsNone(matched["rms_item_id"])
        self.assertNotEqual(matched["match_status"], "auto")
        self.assertTrue(any("multiple rows" in warning for warning in matched["match_warnings"]))

    def test_exact_upc_conflicting_with_saved_alias_remains_reviewable(self) -> None:
        catalog = [
            {
                "catalog_item_id": "cat-upc",
                "rms_item_id": "ITEM-UPC",
                "upc": "000888888888",
                "description": "UPC master wording",
                "supplier_id": "SUP-A",
                "uom": "EA",
            },
            {
                "catalog_item_id": "cat-alias",
                "rms_item_id": "ITEM-ALIAS",
                "upc": "000999999999",
                "description": "Saved alias target wording",
                "supplier_id": "SUP-A",
                "uom": "EA",
            },
        ]
        aliases = [
            {
                "supplier_id": "SUP-A",
                "description": "Invoice alias wording",
                "catalog_item_id": "cat-alias",
                "uom": "EA",
            }
        ]
        matched = match_lines(
            [{"description": "Invoice alias wording", "upc": "000888888888", "uom": "EA"}],
            catalog,
            aliases,
            supplier_id="SUP-A",
        )[0]

        self.assertIsNone(matched["rms_item_id"])
        self.assertNotEqual(matched["match_status"], "auto")
        self.assertTrue(
            any("UPC and saved alias" in warning for warning in matched["match_warnings"])
        )

    def test_candidate_helper_does_not_select_item(self) -> None:
        candidates = suggest_matches(
            "Hydrating Cleanser 50 ml", self.catalog, supplier_id="SUP-1007"
        )

        self.assertEqual(candidates[0]["rms_item_id"], "RMS-50100")
        self.assertEqual(set(candidates[0]), {"rms_item_id", "description", "score", "reason"})

    def test_enrich_invoice_is_non_mutating_and_ids_are_stable(self) -> None:
        invoice = {
            "supplier_id": "SUP-1007",
            "lines": [{"description": "Hydrating Cleanser 50ml", "uom": "EA", "confidence": 0.91}],
        }
        original = copy.deepcopy(invoice)
        first = enrich_invoice(invoice, self.catalog)
        second = enrich_invoice(invoice, self.catalog)

        self.assertEqual(invoice, original)
        self.assertEqual(first["lines"][0]["id"], second["lines"][0]["id"])
        self.assertEqual(first["lines"][0]["extraction_confidence"], 0.91)

    def test_normalization_preserves_size_and_pack_tokens(self) -> None:
        normalized = normalize_description("Cleanser 6 x 50ml PK")

        self.assertIn("6", normalized)
        self.assertIn("50", normalized)
        self.assertIn("ml", normalized)
        self.assertIn("pack", normalized)


if __name__ == "__main__":
    unittest.main()



class CriticalUnknownCapInvariantTests(unittest.TestCase):
    def test_critical_unknown_cap_stays_below_auto_fuzzy_threshold(self) -> None:
        # Item (6): the min(score, CRITICAL_UNKNOWN_SCORE_CAP) cap in
        # _rank_candidates and AUTO_FUZZY_THRESHOLD are partners.  Lines with a
        # one-sided size / pack / shade sit at exactly the cap; the gap to the
        # threshold is the only thing that holds them out of the auto tier on
        # the fuzzy path.  Lowering the threshold to the cap (or raising the
        # cap to the threshold) would let them through with no other test
        # failing.
        cap = matching_module.CRITICAL_UNKNOWN_SCORE_CAP
        threshold = matching_module.AUTO_FUZZY_THRESHOLD
        self.assertLess(
            cap,
            threshold,
            f"CRITICAL_UNKNOWN_SCORE_CAP ({cap}) must stay strictly below "
            f"AUTO_FUZZY_THRESHOLD ({threshold}): a candidate with a one-sided "
            "size / pack / shade is capped at the former and must never clear "
            "the latter on the fuzzy path",
        )
        catalog = [
            {
                "rms_item_id": "RMS-1",
                "description": "Fictional Hydrating Face Serum Night Repair Formula 30ml",
                "uom": "EA",
            }
        ]
        held = match_lines(
            [{"description": "Fictional Hydrating Face Serum Night Repair Formula", "uom": "EA"}],
            catalog,
        )[0]
        self.assertNotEqual(held["match_status"], "auto")
        self.assertEqual(held["candidates"][0]["score"], cap)


class HasBlockingUnknownPredicateTests(unittest.TestCase):
    """The one kind-keyed predicate shared by the auto boundary and the RMS
    cost comparison reads the structured unknown KINDS, never the reason
    labels, so rewording a label can neither enable nor disable the rule."""

    @staticmethod
    def compat(left_desc, left_uom, right_desc, right_uom):
        return matching_module._compatibility(
            matching_module._attributes(left_desc, left_uom),
            matching_module._attributes(right_desc, right_uom),
        )

    def test_uom_only_unknown_does_not_block(self) -> None:
        compat = self.compat("Fictional Sun Cream", None, "Fictional Sun Cream", "EA")
        self.assertEqual(compat["unknown_kinds"], [matching_module.KIND_UOM])
        self.assertFalse(matching_module.has_blocking_unknown(compat))

    def test_size_pack_or_shade_unknown_blocks(self) -> None:
        for left, right, kind in (
            ("Fictional Lotion", "Fictional Lotion 200ml", matching_module.KIND_SIZE),
            ("Fictional Juice", "Fictional Juice 12x250ml", matching_module.KIND_PACK),
            ("Fictional Lipstick", "Fictional Lipstick shade 12", matching_module.KIND_SHADE),
        ):
            compat = self.compat(left, None, right, "EA")
            self.assertIn(kind, compat["unknown_kinds"], (left, right))
            self.assertTrue(matching_module.has_blocking_unknown(compat), (left, right))

    def test_a_real_uom_conflict_still_blocks(self) -> None:
        compat = self.compat("Fictional Sun Cream", "CS", "Fictional Sun Cream", "EA")
        self.assertEqual(compat["conflict_kinds"], [matching_module.KIND_UOM])
        self.assertEqual(compat["unknown_kinds"], [])
        self.assertTrue(matching_module.has_blocking_unknown(compat))

    def test_predicate_ignores_the_label_text(self) -> None:
        # Reword every label: the verdict must not move, because the rule is
        # keyed on the kinds list, not on the words.
        blocking = self.compat("Fictional Lotion", None, "Fictional Lotion 200ml", "EA")
        blocking["unknowns"] = ["UOM something reworded"] * len(blocking["unknowns"])
        self.assertTrue(matching_module.has_blocking_unknown(blocking))
        harmless = self.compat("Fictional Sun Cream", None, "Fictional Sun Cream", "EA")
        harmless["unknowns"] = ["size reworded to look critical"]
        self.assertFalse(matching_module.has_blocking_unknown(harmless))


class ResolvedScopeDuplicateRowCollapseTests(unittest.TestCase):
    """Mechanism 1: several rows of ONE rms_item_id in a resolved supplier scope.

    All names, ids and prices are fictional fixtures.
    """

    def two_site_rows(self, second_cost: float, second_uom: str = "EA") -> list[dict]:
        return [
            {"rms_item_id": "RMS-SITE", "catalog_item_id": "s1", "description": "Fictional Site Widget", "supplier_id": "900001", "uom": "EA", "unit_cost": 4.0},
            {"rms_item_id": "RMS-SITE", "catalog_item_id": "s2", "description": "Fictional Site Widget", "supplier_id": "900001", "uom": second_uom, "unit_cost": second_cost},
            {"rms_item_id": "RMS-OTHER", "catalog_item_id": "o1", "description": "Fictional Other Gadget", "supplier_id": "900001", "uom": "EA", "unit_cost": 9.0},
        ]

    def test_same_cost_rows_collapse_and_the_exact_item_is_auto(self) -> None:
        line = match_lines(
            [{"description": "Fictional Site Widget", "uom": "EA"}], self.two_site_rows(4.0), [], "900001"
        )[0]
        self.assertEqual(line["match_status"], "auto")
        self.assertEqual(line["rms_item_id"], "RMS-SITE")
        self.assertEqual(line["rms_unit_cost"], 4.0)
        ids = [candidate["rms_item_id"] for candidate in line["candidates"]]
        self.assertEqual(ids.count("RMS-SITE"), 1, ids)
        self.assertIn("2 eligible catalog rows for this RMS item collapsed", line["candidates"][0]["reason"])

    def test_divergent_costs_are_refused_and_the_tie_surfaces_as_suggested(self) -> None:
        line = match_lines(
            [{"description": "Fictional Site Widget", "uom": "EA"}], self.two_site_rows(4.5), [], "900001"
        )[0]
        self.assertEqual(line["match_status"], "suggested")
        self.assertIsNone(line["rms_item_id"])
        ids = [candidate["rms_item_id"] for candidate in line["candidates"]]
        self.assertEqual(ids.count("RMS-SITE"), 2, ids)
        self.assertIn("2 distinct unit costs", line["candidates"][0]["reason"])
        self.assertIn("not collapsed", line["candidates"][0]["reason"])
        self.assertTrue(any("2 distinct unit costs" in warning for warning in line["match_warnings"]))

    def test_divergent_uoms_are_refused_even_with_one_cost(self) -> None:
        # The line states no unit, so neither row is excluded by evidence and
        # the refused group is a real tie.  (A line that states EA settles it:
        # the CS row then conflicts and the EA row is the one exact candidate.)
        line = match_lines(
            [{"description": "Fictional Site Widget", "uom": None}], self.two_site_rows(4.0, "CS"), [], "900001"
        )[0]
        self.assertEqual(line["match_status"], "suggested")
        self.assertIsNone(line["rms_item_id"])
        self.assertEqual([c["rms_item_id"] for c in line["candidates"]].count("RMS-SITE"), 2)
        self.assertIn("2 distinct UOMs", line["candidates"][0]["reason"])
        stated = match_lines(
            [{"description": "Fictional Site Widget", "uom": "EA"}], self.two_site_rows(4.0, "CS"), [], "900001"
        )[0]
        self.assertEqual(stated["match_status"], "auto")
        self.assertEqual(stated["catalog_item_id"], "s1")

    def test_no_collapse_in_the_unresolved_supplier_fallback(self) -> None:
        catalog = [
            {"rms_item_id": "RMS-SITE", "catalog_item_id": "s1", "description": "Fictional Site Widget", "supplier_id": "900001", "uom": "EA", "unit_cost": 4.0},
            {"rms_item_id": "RMS-SITE", "catalog_item_id": "s2", "description": "Fictional Site Widget", "supplier_id": "900002", "uom": "EA", "unit_cost": 4.0},
        ]
        line = match_lines([{"description": "Fictional Site Widget", "uom": "EA"}], catalog, [], None)[0]
        self.assertEqual(line["match_status"], "suggested")
        self.assertIsNone(line["rms_item_id"])
        ids = [candidate["rms_item_id"] for candidate in line["candidates"]]
        self.assertEqual(ids.count("RMS-SITE"), 2, ids)
        self.assertNotIn("collapsed", line["candidates"][0]["reason"])

    def test_no_collapse_without_a_resolved_supplier_even_on_a_global_catalog(self) -> None:
        catalog = [
            {"rms_item_id": "RMS-SITE", "catalog_item_id": "s1", "description": "Fictional Site Widget", "uom": "EA", "unit_cost": 4.0},
            {"rms_item_id": "RMS-SITE", "catalog_item_id": "s2", "description": "Fictional Site Widget", "uom": "EA", "unit_cost": 4.0},
        ]
        line = match_lines([{"description": "Fictional Site Widget", "uom": "EA"}], catalog, [], None)[0]
        self.assertEqual(line["match_status"], "suggested")
        self.assertEqual(len(line["candidates"]), 2)

    def test_suggest_matches_collapses_in_a_resolved_scope_only(self) -> None:
        scoped = suggest_matches("Fictional Site Widget", self.two_site_rows(4.0), [], "900001")
        self.assertEqual([c["rms_item_id"] for c in scoped].count("RMS-SITE"), 1)
        global_rows = [dict(row, supplier_id=None) for row in self.two_site_rows(4.0)]
        unscoped = suggest_matches("Fictional Site Widget", global_rows, [], None)
        self.assertEqual([c["rms_item_id"] for c in unscoped].count("RMS-SITE"), 2)


class UninformativeUomUnknownTests(unittest.TestCase):
    """Mechanism 2: a UOM column single-valued across the scope carries no information."""

    def rows(self, second_uom: str) -> list[dict]:
        return [
            {"rms_item_id": "RMS-A", "description": "Fictional Hydrating Face Serum Night Repair Formula", "supplier_id": "900001", "uom": "EA", "unit_cost": 5.0},
            {"rms_item_id": "RMS-B", "description": "Fictional Unrelated Mop Bucket", "supplier_id": "900001", "uom": second_uom, "unit_cost": 6.0},
        ]

    # One character off the catalog string: fuzzy path, above the auto threshold.
    line = {"description": "Fictional Hydrating Face Serum Night Repair Formulas", "uom": None}

    def test_single_valued_uom_does_not_cap_a_line_that_states_no_unit(self) -> None:
        matched = match_lines([self.line], self.rows("EA"), [], "900001")[0]
        self.assertEqual(matched["match_status"], "auto")
        self.assertEqual(matched["rms_item_id"], "RMS-A")
        self.assertGreaterEqual(matched["candidates"][0]["score"], matching_module.AUTO_FUZZY_THRESHOLD)
        self.assertEqual(matched["unit_status"], "assumed")
        self.assertIn("not held against the match", matched["candidates"][0]["reason"])

    def test_a_uom_column_that_varies_keeps_the_cap(self) -> None:
        matched = match_lines([self.line], self.rows("CS"), [], "900001")[0]
        self.assertEqual(matched["match_status"], "suggested")
        self.assertIsNone(matched["rms_item_id"])
        self.assertEqual(matched["candidates"][0]["score"], matching_module.CRITICAL_UNKNOWN_SCORE_CAP)
        self.assertIn("UOM appears on only one side", matched["candidates"][0]["reason"])

    def test_a_one_sided_size_is_still_capped_when_the_uom_column_is_single_valued(self) -> None:
        catalog = [
            {"rms_item_id": "RMS-A", "description": "Fictional Hydrating Face Serum Night Repair Formula 30ml", "supplier_id": "900001", "uom": "EA"},
            {"rms_item_id": "RMS-B", "description": "Fictional Unrelated Mop Bucket", "supplier_id": "900001", "uom": "EA"},
        ]
        matched = match_lines(
            [{"description": "Fictional Hydrating Face Serum Night Repair Formula", "uom": "EA"}], catalog, [], "900001"
        )[0]
        self.assertNotEqual(matched["match_status"], "auto")
        self.assertEqual(matched["candidates"][0]["score"], matching_module.CRITICAL_UNKNOWN_SCORE_CAP)

    def test_kinds_helper_reads_the_uom_column_only(self) -> None:
        prepared = matching_module._prepare_catalog(self.rows("EA"), "900001")
        self.assertEqual(matching_module._uninformative_kinds(prepared), frozenset({matching_module.KIND_UOM}))
        varied = matching_module._prepare_catalog(self.rows("CS"), "900001")
        self.assertEqual(matching_module._uninformative_kinds(varied), frozenset())


class UncappedOrderingTests(unittest.TestCase):
    """Mechanism 3: ranking by the uncapped score; the cap decides auto, not order."""

    catalog = [
        {"rms_item_id": "RMS-NEAR", "description": "Fictional Hydrating Face Serum Night Repair Formula 30ml", "supplier_id": "900001", "uom": "EA"},
        {"rms_item_id": "RMS-FAR", "description": "Fictional Hydrating Face Serum Night Formula", "supplier_id": "900001", "uom": "EA"},
    ]

    def test_the_first_candidate_is_the_best_guess_not_the_best_capped_score(self) -> None:
        matched = match_lines(
            [{"description": "Fictional Hydrating Face Serum Night Repair Formula", "uom": "EA"}], self.catalog, [], "900001"
        )[0]
        self.assertNotEqual(matched["match_status"], "auto")
        first, second = matched["candidates"][0], matched["candidates"][1]
        self.assertEqual(first["rms_item_id"], "RMS-NEAR")
        self.assertEqual(first["score"], matching_module.CRITICAL_UNKNOWN_SCORE_CAP)
        self.assertGreater(second["score"], first["score"])
