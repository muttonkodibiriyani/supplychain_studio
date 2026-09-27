"""Conservative supplier invoice-line matching against an RMS catalog.

Similarity scores rank candidates; they are not probabilities.  Automatic
selection is restricted to validated IDs, unique exact supplier-scoped UPCs
with compatible unit/pack evidence, supplier-scoped approved aliases, unique
exact descriptions, or very high-margin fuzzy matches with compatible size,
pack, shade, and unit evidence.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence


class CatalogValidationError(ValueError):
    """Catalog or alias configuration is invalid."""


AUTO_FUZZY_THRESHOLD = 96.0
AUTO_FUZZY_MARGIN = 8.0
# Score ceiling for candidates with a one-sided critical attribute; must stay
# strictly below AUTO_FUZZY_THRESHOLD (see _rank_candidates).
CRITICAL_UNKNOWN_SCORE_CAP = 92.0
SUGGEST_THRESHOLD = 70.0
# Unit kinds for the auto-boundary unit check (see unit_check).  Values are the
# canonical forms produced by _normalize_uom.
SINGLE_UNIT_UOMS = frozenset({"EACH"})
MULTI_UNIT_UOMS = frozenset({"PACK", "BOX", "CASE", "CARTON", "DOZEN"})
UNIT_UNCONFIRMED = "unit unconfirmed"
# Attribute kinds as produced by _compatibility.  Rules keyed on "which
# attribute is unknown" read these, never the reason labels.
KIND_SIZE = "size"
KIND_PACK = "pack"
KIND_SHADE = "shade"
KIND_UOM = "uom"
ATTRIBUTE_KINDS = (
    ("sizes", KIND_SIZE, "size"),
    ("packs", KIND_PACK, "pack count"),
    ("shades", KIND_SHADE, "shade"),
)
DEFAULT_CANDIDATE_LIMIT = 5
# Above this many eligible rows a token prefilter narrows the fuzzy scan so an
# unresolved-supplier fallback over a large full catalog stays bounded.
PREFILTER_MIN_ROWS = 2000
PREFILTER_POOL_SIZE = 250
SUPPLIER_UNRESOLVED_WARNING = (
    "Supplier unresolved: no catalog supplier could be matched to this invoice, so "
    "candidates were drawn from the full catalog across all suppliers. Matches are "
    "low-confidence suggestions only and require review."
)

_ABBREVIATIONS = {
    "btl": "bottle",
    "btls": "bottle",
    "clr": "color",
    "colour": "color",
    "ea": "each",
    "each": "each",
    "pc": "piece",
    "pcs": "piece",
    "pkg": "pack",
    "pk": "pack",
    "pks": "pack",
    "milliliter": "ml",
    "milliliters": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "gram": "g",
    "grams": "g",
    "kilogram": "kg",
    "kilograms": "kg",
    "moisturiser": "moisturizer",
}

_UOM_ALIASES = {
    "EA": "EACH",
    "EACH": "EACH",
    "PC": "EACH",
    "PCS": "EACH",
    "PIECE": "EACH",
    "PIECES": "EACH",
    "UNIT": "EACH",
    "UNITS": "EACH",
    "PK": "PACK",
    "PKG": "PACK",
    "PACK": "PACK",
    "PACKS": "PACK",
    "BX": "BOX",
    "BOX": "BOX",
    "CASE": "CASE",
    "CS": "CASE",
    "CTN": "CARTON",
    "CARTON": "CARTON",
    "DOZ": "DOZEN",
    "DZ": "DOZEN",
    "DOZEN": "DOZEN",
    "BTL": "BOTTLE",
    "BOTTLE": "BOTTLE",
    "ML": "ML",
    "L": "L",
    "G": "G",
    "KG": "KG",
}


def normalize_description(value: str) -> str:
    """Normalize typography and common abbreviations while preserving attributes."""

    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.casefold().replace("&", " and ").replace("×", " x ")
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    tokens = re.findall(r"[a-z0-9]+", text)
    return " ".join(_ABBREVIATIONS.get(token, token) for token in tokens)


def suggest_matches(
    line: Mapping[str, Any] | str,
    catalog: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]] | Mapping[str, str] | None = None,
    supplier_id: str | None = None,
    *,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    """Return ranked candidates for one line without selecting an RMS item."""

    if limit < 1:
        return []
    line_mapping: Mapping[str, Any] = {"description": line} if isinstance(line, str) else line
    description = str(line_mapping.get("description") or "").strip()
    if not description:
        return []
    prepared_catalog = _prepare_catalog(catalog, supplier_id)
    alias_map = _prepare_aliases(aliases, supplier_id, prepared_catalog)
    ranked = _rank_candidates(
        line_mapping, prepared_catalog, uninformative_kinds=_uninformative_kinds(prepared_catalog)
    )

    upc_state, upc_item, _ = _resolve_exact_upc(
        line_mapping, prepared_catalog, supplier_id
    )
    if upc_state == "matched" and upc_item is not None:
        for candidate in ranked:
            if candidate["_catalog_key"] == upc_item["_catalog_key"]:
                candidate["score"] = candidate["_raw_score"] = 100.0
                candidate["reason"] = (
                    "Exact supplier-scoped UPC with compatible UOM/pack evidence; "
                    + candidate["reason"]
                )
                break

    alias_record = _find_alias(alias_map, description, line_mapping)
    alias_id = alias_record["catalog_key"] if alias_record else None
    if alias_id:
        for candidate in ranked:
            if str(candidate["_catalog_key"]) == alias_id and candidate["_compatible"]:
                candidate["score"] = candidate["_raw_score"] = 100.0
                candidate["reason"] = "Approved supplier alias; " + candidate["reason"]
                candidate["_alias"] = True
                break
    ranked.sort(key=_ranking_key)
    if _supplier_key(supplier_id) is not None:
        ranked = _collapse_duplicate_rows(ranked)
    return [_public_candidate(candidate) for candidate in ranked[:limit]]


def match_lines(
    lines: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]] | Mapping[str, str] | None = None,
    supplier_id: str | None = None,
    *,
    unresolved_supplier_fallback: bool = True,
) -> list[dict[str, Any]]:
    """Enrich lines with a conservative match decision and ranked candidates.

    With a resolved ``supplier_id`` only that supplier's rows and global rows
    are eligible.  Without one, the catalog is NOT silently narrowed to global
    rows: when ``unresolved_supplier_fallback`` is enabled every supplier's rows
    stay eligible, every line carries an explicit "supplier unresolved" warning
    and no line can reach ``auto`` (at best ``suggested``).
    """

    fallback_active = bool(
        unresolved_supplier_fallback
        and _supplier_key(supplier_id) is None
        and supplier_scoping_needed(catalog)
    )
    if not lines:
        # Nothing to match: do not pay for preparing a (possibly very large)
        # catalog.  Catalog validation still runs whenever a line is matched.
        return []
    prepared_catalog, candidate_index, uninformative_kinds = _prepared_catalog_and_index(
        catalog, supplier_id, include_all_suppliers=fallback_active
    )
    # Duplicate rows of one RMS item are folded only inside a resolved
    # supplier's scope (see _collapse_duplicate_rows); never in the
    # unresolved-supplier fallback, where rows from different suppliers with
    # one rms_item_id are not the same thing.
    collapse_duplicates = _supplier_key(supplier_id) is not None and not fallback_active
    # Latent, no instance observed: this lookup is keyed on the catalog row
    # key, so if two prepared rows ever shared one key (a row id reused
    # across imports, say) only the later row would be reachable by a
    # persisted selection.  _prepare_catalog refuses duplicate keys within one
    # catalog, which is what keeps it latent; it is recorded here so the
    # assumption is visible next to the code that relies on it.
    catalog_by_key = {str(item["_catalog_key"]): item for item in prepared_catalog}
    catalog_by_rms: dict[str, list[dict[str, Any]]] = {}
    for item in prepared_catalog:
        catalog_by_rms.setdefault(str(item["rms_item_id"]), []).append(item)
    all_catalog_ids = {
        str(item.get("rms_item_id"))
        for item in catalog
        if item.get("rms_item_id") not in (None, "")
    }
    alias_map = _prepare_aliases(aliases, supplier_id, prepared_catalog)
    output: list[dict[str, Any]] = []

    for index, original in enumerate(lines):
        line = dict(original)
        if not line.get("id"):
            line["id"] = _stable_line_id(index, line)
        if "confidence" in line and "extraction_confidence" not in line:
            line["extraction_confidence"] = line["confidence"]
        line["match_warnings"] = list(line.get("match_warnings") or [])
        if fallback_active:
            line["match_warnings"].append(SUPPLIER_UNRESOLVED_WARNING)
            line["match_reason"] = "supplier_unresolved_full_catalog_fallback"
        supplied_catalog_key = line.get("catalog_item_id")
        supplied_id = line.get("rms_item_id")
        selected = None
        if supplied_catalog_key not in (None, ""):
            selected = catalog_by_key.get(str(supplied_catalog_key))
        elif supplied_id not in (None, ""):
            eligible = catalog_by_rms.get(str(supplied_id), [])
            if len(eligible) == 1:
                selected = eligible[0]
        if supplied_catalog_key not in (None, "") or supplied_id not in (None, ""):
            supplied_key = str(supplied_id or supplied_catalog_key)
            if selected is not None:
                unit = unit_check(
                    line.get("description"), line.get("uom"), selected["description"], selected.get("uom")
                )
                cost = _cost_facts(selected, catalog_by_rms.get(str(selected["rms_item_id"]), []))
                line.update(
                    {
                        "catalog_item_id": selected.get("catalog_item_id"),
                        "rms_item_id": selected["rms_item_id"],
                        "rms_parent_item": selected.get("parent_item")
                        or selected["rms_item_id"],
                        "rms_upc": selected.get("upc"),
                        "rms_cost_currency": _cost_currency_of(selected),
                        "rms_unit_cost": cost["rms_unit_cost"],
                        "rms_unit_cost_min": cost["rms_unit_cost_min"],
                        "rms_unit_cost_max": cost["rms_unit_cost_max"],
                        "rms_po_number": selected.get("master_po_number"),
                        "unit_status": unit["status"],
                        "unit_reason": unit["reason"],
                        **_revalidation_decision(line, selected),
                    }
                )
                output.append(line)
                continue
            if supplied_id not in (None, "") and supplied_key in all_catalog_ids:
                line["match_warnings"].append(
                    f"Supplied RMS item ID '{supplied_key}' is ambiguous or not eligible for supplier '{supplier_id or 'unspecified'}'."
                )
            else:
                line["match_warnings"].append(
                    f"Supplied catalog selection '{supplied_key}' does not exist in the eligible catalog."
                )
            line["catalog_item_id"] = None
            line["rms_item_id"] = None

        description = str(line.get("description") or "").strip()
        upc_state, upc_item, upc_warning = _resolve_exact_upc(
            line, prepared_catalog, supplier_id
        )
        if upc_warning:
            line["match_warnings"].append(upc_warning)
        if not description and upc_state != "matched":
            line.update(
                {
                    "rms_item_id": None,
                    "match_status": "unmatched",
                    "confidence": 0.0,
                    "candidates": [],
                }
            )
            line["match_warnings"].append("Line has no description to match.")
            output.append(line)
            continue

        ranked = _rank_candidates(
            line, prepared_catalog, index=candidate_index, uninformative_kinds=uninformative_kinds
        )
        upc_candidate: dict[str, Any] | None = None
        if upc_state == "matched" and upc_item is not None:
            upc_candidate = next(
                (
                    candidate
                    for candidate in ranked
                    if candidate["_catalog_key"] == upc_item["_catalog_key"]
                ),
                None,
            )
            if upc_candidate is not None:
                upc_candidate["score"] = upc_candidate["_raw_score"] = 100.0
                upc_candidate["reason"] = (
                    "Exact supplier-scoped UPC with compatible UOM/pack evidence; "
                    + upc_candidate["reason"]
                )
        alias_record = _find_alias(alias_map, description, line)
        alias_id = alias_record["catalog_key"] if alias_record else None
        alias_candidate: dict[str, Any] | None = None
        if alias_id:
            alias_candidate = next(
                (candidate for candidate in ranked if str(candidate["_catalog_key"]) == alias_id), None
            )
            if alias_candidate and alias_candidate["_compatible"]:
                alias_candidate["score"] = alias_candidate["_raw_score"] = 100.0
                alias_candidate["reason"] = "Approved supplier alias; " + alias_candidate["reason"]
                alias_candidate["_alias"] = True
        upc_alias_conflict = bool(
            upc_candidate is not None
            and alias_candidate is not None
            and upc_candidate["_catalog_key"] != alias_candidate["_catalog_key"]
        )
        if upc_alias_conflict:
            line["match_warnings"].append(
                "Exact supplier-scoped UPC and saved alias resolve to different catalog rows; manual review is required."
            )
        ranked.sort(key=_ranking_key)
        if collapse_duplicates:
            ranked = _collapse_duplicate_rows(ranked)
            if ranked and ranked[0].get("_collapse_refused"):
                line["match_warnings"].append(ranked[0]["_collapse_refused"])
        if fallback_active:
            for candidate in ranked[:DEFAULT_CANDIDATE_LIMIT]:
                candidate["reason"] = (
                    f"Supplier unresolved; full-catalog fallback row from supplier "
                    f"'{candidate.get('supplier_id') or 'global'}'; " + candidate["reason"]
                )
        public_candidates = [_public_candidate(candidate) for candidate in ranked[:DEFAULT_CANDIDATE_LIMIT]]

        selected: dict[str, Any] | None = None
        status = "unmatched"
        confidence = ranked[0]["score"] if ranked else 0.0
        upc_blocks_automatic_selection = (
            upc_state not in {"absent", "matched"} or upc_alias_conflict
        )
        path = None
        if upc_candidate is not None and not upc_alias_conflict:
            selected, status, confidence, path = upc_candidate, "auto", 100.0, "upc"
        elif not upc_blocks_automatic_selection and alias_candidate and alias_candidate["_compatible"]:
            selected, status, confidence, path = alias_candidate, "auto", 100.0, "alias"
        elif ranked:
            top = ranked[0]
            exact_candidates = [
                candidate
                for candidate in ranked
                if candidate["_exact"] and candidate["_compatible"]
            ]
            if (
                not upc_blocks_automatic_selection
                and len(exact_candidates) == 1
                and top is exact_candidates[0]
            ):
                # Exact means identical normalised strings, so size / pack /
                # shade cannot be unknown here; a UOM-only unknown is settled
                # by the unit check at the auto boundary below.
                selected, status, confidence, path = top, "auto", 100.0, "exact"
            else:
                # Ranking is by uncapped score (_ranking_key); the margin is
                # measured on capped scores against the strongest runner-up,
                # wherever it sits, so the ordering change cannot admit a
                # line the capped ordering would have held.
                second_score = max((candidate["score"] for candidate in ranked[1:]), default=0.0)
                margin = top["score"] - second_score
                if (
                    not upc_blocks_automatic_selection
                    and top["score"] >= AUTO_FUZZY_THRESHOLD
                    and margin >= AUTO_FUZZY_MARGIN
                    and top["_compatible"]
                    and not top["_critical_unknown"]
                ):
                    selected, status, confidence, path = top, "auto", top["score"], "fuzzy"
                elif top["score"] >= SUGGEST_THRESHOLD and top["_compatible"]:
                    status = "suggested"

        # Auto boundary: the RMS item id is the unit carrier in the export
        # (the Details sheet has no UOM column), so the unit question is
        # settled here.  Every auto selection carries the unit flag; the
        # kind-keyed demotion (has_blocking_unknown via unit_check) applies
        # to the EXACT path only, and that boundary is proven, not chosen:
        # size, pack count and shade are derived from the normalised
        # description, and an exact candidate has the identical normalised
        # string, so those kinds can never be "on only one side" here; the
        # only unknown reachable on this path is UOM, and a UOM conflict is
        # already excluded by _compatible.  The fuzzy path keeps its own
        # `not _critical_unknown` gate (every unknown kind, UOM included),
        # so nothing with an unknown reaches auto through it.  The UPC and
        # alias paths keep their own evidence checks (_resolve_exact_upc,
        # _find_alias) and are not demoted here; the alias path is
        # unreachable while alias learning is off.
        unit = None
        if selected is not None and status == "auto":
            item = catalog_by_key[str(selected["_catalog_key"])]
            unit = unit_check(description, line.get("uom"), item["description"], item.get("uom"))
            if unit["demote"] and path == "exact":
                line["match_warnings"].append(unit["reason"])
                selected = None
                status = "suggested"
                confidence = ranked[0]["score"] if ranked else 0.0

        if fallback_active and status == "auto":
            # A full-catalog fallback cannot select a row automatically:
            # description-only matches across suppliers collide.
            selected = None
            status = "suggested"
            confidence = ranked[0]["score"] if ranked else 0.0

        cost = _cost_facts(
            selected, catalog_by_rms.get(str(selected["rms_item_id"]), []) if selected else []
        )
        line.update(
            {
                "catalog_item_id": selected.get("catalog_item_id") if selected else None,
                "rms_item_id": selected["rms_item_id"] if selected else None,
                "rms_parent_item": (
                    selected.get("parent_item") or selected["rms_item_id"]
                    if selected
                    else None
                ),
                "rms_upc": selected.get("upc") if selected else None,
                "rms_cost_currency": _cost_currency_of(selected) if selected else None,
                "rms_unit_cost": cost["rms_unit_cost"],
                "rms_unit_cost_min": cost["rms_unit_cost_min"],
                "rms_unit_cost_max": cost["rms_unit_cost_max"],
                "rms_po_number": selected.get("master_po_number") if selected else None,
                "unit_status": unit["status"] if unit else None,
                "unit_reason": unit["reason"] if unit else None,
                "match_status": status,
                "confidence": round(float(confidence), 1),
                "candidates": public_candidates,
            }
        )
        output.append(line)
    return output


# Unit statuses for which the RMS cost comparison must refuse to show a number
# (InvoiceService._prepare_lines); produced only by unit_check below.
BLOCKING_UNIT_STATUSES = frozenset({"unverified", "unconfirmed"})


def has_blocking_unknown(compatibility: Mapping[str, Sequence[str]]) -> bool:
    """The ONE kind-keyed rule shared by the auto boundary and the cost site.

    True for any stated disagreement (conflicts of every kind, including a
    real UOM conflict, still block), and for a SIZE, PACK COUNT or SHADE
    known on only one side.  False for a UOM-only unknown: the master's UOM
    column is a constant single unit compared against a line that states
    none, which carries no information (it would fire on every line).

    Reads ``unknown_kinds`` (the structured kinds), not the reason labels, so
    rewording a label cannot re-enable or disable the rule.
    """

    if compatibility["conflicts"]:
        return True
    return any(kind != KIND_UOM for kind in compatibility["unknown_kinds"])


def unit_check(
    line_description: Any,
    line_uom: Any,
    item_description: Any,
    item_uom: Any,
) -> dict[str, Any]:
    """Decide whether a selected catalog row's unit is settled for a line.

    Keyed on the KIND of the unknown, not on the master UOM alone:

    * a stated disagreement of any kind (UOM, size, pack count, shade) ->
      ``unconfirmed``: demote and block approval, reason "unit unconfirmed";
    * the master row is a multi-unit row (case / box / carton / pack / dozen
      UOM, or an NxSIZE pack in its description) and the line is silent on
      the unit -> ``unconfirmed``, same reason.  Dead against the current
      master (its UOM column is a constant single unit) but it is the gate
      for a master that carries case rows;
    * size, pack count or shade known on only one side -> ``unverified``:
      demote to suggested (the words agree but the item cannot be told apart
      from its sibling), approval is not blocked once an operator confirms;
    * UOM known on only one side, master single-unit or unstated ->
      ``assumed``: permitted, the line carries the flag "unit assumed";
    * both sides agree -> ``confirmed``.
    """

    line_attributes = _attributes(str(line_description or ""), line_uom)
    item_attributes = _attributes(str(item_description or ""), item_uom)
    compatibility = _compatibility(line_attributes, item_attributes)
    line_unit, item_unit = line_attributes["uom"], item_attributes["uom"]
    master_multi = item_unit in MULTI_UNIT_UOMS or bool(item_attributes["packs"])
    if compatibility["conflicts"]:
        reason = f"{UNIT_UNCONFIRMED}: " + "; ".join(compatibility["conflicts"])
        return {"status": "unconfirmed", "reason": reason, "demote": True, "block": True}
    blocking_unknowns = [
        label
        for kind, label in zip(compatibility["unknown_kinds"], compatibility["unknowns"])
        if kind != KIND_UOM
    ]
    if line_unit is None and master_multi:
        reason = (
            f"{UNIT_UNCONFIRMED}: invoice line states no unit and the RMS item is a "
            f"multi-unit row ({item_unit if item_unit in MULTI_UNIT_UOMS else 'pack of ' + _format_attribute(item_attributes['packs'])})"
        )
        return {"status": "unconfirmed", "reason": reason, "demote": True, "block": True}
    if has_blocking_unknown(compatibility):
        reason = "item attribute unverified: " + "; ".join(blocking_unknowns)
        return {"status": "unverified", "reason": reason, "demote": True, "block": False}
    if line_unit and item_unit:
        return {
            "status": "confirmed",
            "reason": f"unit confirmed ({line_unit})",
            "demote": False,
            "block": False,
        }
    if line_unit is None and item_unit is not None and item_unit not in SINGLE_UNIT_UOMS:
        # A master unit that is neither single nor multi (e.g. a size unit in
        # the UOM column) cannot be assumed for a line that states none.
        reason = f"{UNIT_UNCONFIRMED}: invoice line states no unit and the RMS item unit is {item_unit}"
        return {"status": "unconfirmed", "reason": reason, "demote": True, "block": True}
    stated = item_unit or line_unit
    reason = (
        f"unit assumed: {'invoice line' if line_unit is None else 'RMS item'} states no unit"
        + (f"; {stated} taken from the {'RMS item' if line_unit is None else 'invoice line'}" if stated else "")
    )
    return {"status": "assumed", "reason": reason, "demote": False, "block": False}


def _cost_facts(
    selected: Mapping[str, Any] | None, tied_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Cost facts for a selected RMS item over every eligible row of that id.

    A master can hold several rows (sites) for one RMS item with different
    unit costs.  The first ranked row's cost must not be picked silently, so
    with more than one distinct cost the line carries the [min, max] range
    and no single ``rms_unit_cost``; the service turns the range into a
    comparison (see InvoiceService._prepare_lines).
    """

    if selected is None:
        return {"rms_unit_cost": None, "rms_unit_cost_min": None, "rms_unit_cost_max": None}
    costs: set[float] = set()
    for row in tied_rows or [selected]:
        value = row.get("unit_cost")
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0.01:
            costs.add(number)
    if len(costs) > 1:
        return {
            "rms_unit_cost": None,
            "rms_unit_cost_min": min(costs),
            "rms_unit_cost_max": max(costs),
        }
    return {
        "rms_unit_cost": selected.get("unit_cost"),
        "rms_unit_cost_min": None,
        "rms_unit_cost_max": None,
    }


def enrich_invoice(
    invoice: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]] | Mapping[str, str] | None = None,
    supplier_id: str | None = None,
    *,
    scope_resolved: bool = False,
) -> dict[str, Any]:
    """Return a copy of an extracted invoice with its lines matched.

    With ``scope_resolved`` the caller has already decided the matching scope:
    ``supplier_id`` is authoritative and ``None`` means unresolved, so the id
    printed on the invoice is NOT used as a scope.  A printed id the catalog
    does not know would otherwise scope matching to 0 supplier rows plus the
    global rows, the silently narrowed set through a second door.
    """

    enriched = dict(invoice)
    if scope_resolved:
        effective_supplier = supplier_id
    else:
        effective_supplier = supplier_id or _optional_string(invoice.get("supplier_id"))
    enriched["lines"] = match_lines(
        invoice.get("lines") or [],
        catalog,
        aliases,
        effective_supplier,
    )
    warnings = list(invoice.get("warnings") or [])
    if _supplier_key(effective_supplier) is None and supplier_scoping_needed(catalog):
        enriched["supplier_resolution"] = "unresolved"
        enriched["match_reason"] = "supplier_unresolved_full_catalog_fallback"
        if SUPPLIER_UNRESOLVED_WARNING not in warnings:
            warnings.append(SUPPLIER_UNRESOLVED_WARNING)
    else:
        enriched["supplier_resolution"] = "resolved" if effective_supplier else "not_required"
    enriched["warnings"] = warnings
    return enriched


def supplier_scoping_needed(catalog: Sequence[Mapping[str, Any]]) -> bool:
    """True when the catalog holds supplier-specific rows (scoping matters)."""

    return any(_supplier_key(item.get("supplier_id")) for item in catalog)


class _CandidateIndex:
    """Token prefilter so a large (full-master) scan stays bounded per line.

    Rows sharing rare normalized tokens with the line are scored by inverse
    document frequency; the top pool plus every exact normalized match is then
    ranked by the regular similarity scoring.  Deterministic and dependency-free.
    """

    def __init__(self, catalog: Sequence[Mapping[str, Any]], pool_size: int = PREFILTER_POOL_SIZE) -> None:
        self.catalog = catalog
        self.pool_size = pool_size
        self.by_normalized: dict[str, list[int]] = {}
        self.postings: dict[str, list[int]] = {}
        for position, item in enumerate(catalog):
            normalized = item["_normalized"]
            self.by_normalized.setdefault(normalized, []).append(position)
            for token in set(normalized.split()):
                self.postings.setdefault(token, []).append(position)
        total = max(1, len(catalog))
        self.common_limit = max(50, total // 5)
        self.weights = {
            token: math.log(total / len(rows)) for token, rows in self.postings.items()
        }

    def pool(self, normalized: str) -> list[Mapping[str, Any]]:
        scores: dict[int, float] = {}
        for token in set(normalized.split()):
            rows = self.postings.get(token)
            if not rows or len(rows) > self.common_limit:
                continue
            weight = self.weights[token]
            for position in rows:
                scores[position] = scores.get(position, 0.0) + weight
        chosen = set(sorted(scores, key=lambda position: (-scores[position], position))[: self.pool_size])
        chosen.update(self.by_normalized.get(normalized, ()))
        return [self.catalog[position] for position in sorted(chosen)]


def _prepare_catalog(
    catalog: Sequence[Mapping[str, Any]],
    supplier_id: str | None,
    *,
    include_all_suppliers: bool = False,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    wanted_supplier = _supplier_key(supplier_id)
    for index, source in enumerate(catalog):
        item_id = source.get("rms_item_id")
        description = str(source.get("description") or "").strip()
        if item_id in (None, "") or not description:
            raise CatalogValidationError(
                f"Catalog record {index} requires non-empty rms_item_id and description."
            )
        catalog_id = source.get("catalog_item_id")
        item_key = str(catalog_id or item_id)
        if item_key in seen:
            raise CatalogValidationError(f"Duplicate catalog row ID '{item_key}' in catalog.")
        seen.add(item_key)
        item_supplier = _supplier_key(source.get("supplier_id"))
        # Supplier-specific catalog rows cannot leak across suppliers.  Global
        # rows (supplier_id absent) remain eligible for every supplier.  With an
        # unresolved supplier the caller opts into the explicit full-catalog
        # fallback instead of silently narrowing to global rows.
        if item_supplier and item_supplier != wanted_supplier and not include_all_suppliers:
            continue
        prepared.append(
            {
                **dict(source),
                "rms_item_id": item_id,
                "parent_item": source.get("parent_item") or item_id,
                "_catalog_key": item_key,
                "description": description,
                "_normalized": normalize_description(description),
                "_attributes": _attributes(description, source.get("uom")),
            }
        )
    return prepared


# Preparing a full catalog (normalising and tokenising every row) costs
# seconds per call, and the unresolved-supplier fallback would otherwise pay it
# for every invoice.  The service hands the same catalog list object to every
# job while the catalog is unchanged, so one prepared copy (plus its prefilter
# index) is memoised per catalog object.  Prepared rows are never mutated by
# the matcher, which makes sharing them across calls safe.
_PREPARED_CACHE_LOCK = threading.Lock()
_PREPARED_CACHE: dict[
    tuple[int, int, str | None, bool],
    tuple[Any, list[dict[str, Any]], Any, frozenset[str]],
] = {}


def _prepared_catalog_and_index(
    catalog: Sequence[Mapping[str, Any]],
    supplier_id: str | None,
    *,
    include_all_suppliers: bool,
) -> tuple[list[dict[str, Any]], "_CandidateIndex | None", frozenset[str]]:
    cacheable = len(catalog) >= PREFILTER_MIN_ROWS
    key = (id(catalog), len(catalog), _supplier_key(supplier_id), include_all_suppliers)
    if cacheable:
        with _PREPARED_CACHE_LOCK:
            entry = _PREPARED_CACHE.get(key)
        # The cached entry keeps the catalog object alive, so an identity match
        # guarantees the id() was not recycled for a different list.
        if entry is not None and entry[0] is catalog:
            return entry[1], entry[2], entry[3]
    prepared = _prepare_catalog(catalog, supplier_id, include_all_suppliers=include_all_suppliers)
    index = _CandidateIndex(prepared) if len(prepared) > PREFILTER_MIN_ROWS else None
    uninformative = _uninformative_kinds(prepared)
    if cacheable:
        with _PREPARED_CACHE_LOCK:
            _PREPARED_CACHE.clear()
            _PREPARED_CACHE[key] = (catalog, prepared, index, uninformative)
    return prepared, index, uninformative


def _uninformative_kinds(prepared: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    """Attribute kinds that carry no information in this eligible catalog.

    An attribute single-valued across the supplier-scoped catalog cannot tell
    one row from another, so a line that omits it has not lost anything by
    omitting it.  Today this is decided for the UOM column only: when every
    eligible row states the same unit (the current master's UOM column is a
    constant single unit) a "UOM appears on only one side" unknown must not
    cap the score or set ``_critical_unknown`` in ``_rank_candidates``.  The
    unit itself is still settled at the auto boundary by ``unit_check``
    (``assumed`` against a SINGLE_UNIT_UOMS row, ``unconfirmed`` otherwise).

    Size, pack count and shade are NOT lifted here even when single-valued:
    ``unit_check`` treats a one-sided size / pack / shade as blocking on the
    exact path, so lifting their cap on the fuzzy path would make the fuzzy
    path looser than the exact one
    (tests/test_matching.py::test_critical_unknown_cap_stays_below_auto_fuzzy_threshold).
    """

    if not prepared:
        return frozenset()
    units = {item["_attributes"]["uom"] for item in prepared}
    return frozenset({KIND_UOM}) if len(units) == 1 else frozenset()


def _prepare_aliases(
    aliases: Sequence[Mapping[str, Any]] | Mapping[str, str] | None,
    supplier_id: str | None,
    catalog: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, str | None]]]:
    if not aliases:
        return {}
    wanted_supplier = _supplier_key(supplier_id)
    catalog_keys = {str(item["_catalog_key"]) for item in catalog}
    rms_to_keys: dict[str, list[str]] = {}
    for item in catalog:
        rms_to_keys.setdefault(str(item["rms_item_id"]), []).append(str(item["_catalog_key"]))
    records: Iterable[Mapping[str, Any]]
    if isinstance(aliases, Mapping):
        # Legacy compact mappings are still supplier scoped by the explicit
        # function argument.  Without a supplier they are deliberately inactive.
        if not wanted_supplier:
            return {}
        records = (
            {"supplier_id": supplier_id, "description": description, "rms_item_id": rms_item_id}
            for description, rms_item_id in aliases.items()
        )
    else:
        records = aliases

    prepared: dict[str, list[dict[str, str | None]]] = {}
    for index, record in enumerate(records):
        alias_supplier = _supplier_key(record.get("supplier_id"))
        if not alias_supplier:
            raise CatalogValidationError(f"Alias record {index} requires supplier_id.")
        if alias_supplier != wanted_supplier:
            continue
        description = str(record.get("description") or record.get("alias") or "").strip()
        requested_catalog_key = str(record.get("catalog_item_id") or "").strip()
        requested_rms_id = str(record.get("rms_item_id") or "").strip()
        if not description or not (requested_catalog_key or requested_rms_id):
            raise CatalogValidationError(
                f"Alias record {index} requires description and a catalog target."
            )
        if requested_catalog_key:
            target = requested_catalog_key if requested_catalog_key in catalog_keys else None
        else:
            targets = rms_to_keys.get(requested_rms_id, [])
            target = targets[0] if len(targets) == 1 else None
        if target is None:
            raise CatalogValidationError(
                f"Alias '{description}' has an ambiguous or ineligible catalog target for supplier '{supplier_id}'."
            )
        normalized = normalize_description(description)
        alias_uom = _normalize_uom(record.get("uom"))
        scoped_records = prepared.setdefault(normalized, [])
        previous = next((item for item in scoped_records if item.get("uom") == alias_uom), None)
        if previous and previous["catalog_key"] != target:
            scope = alias_uom or "any UOM"
            raise CatalogValidationError(
                f"Supplier alias '{description}' has conflicting RMS targets for {scope}."
            )
        if not previous:
            scoped_records.append({"catalog_key": target, "uom": alias_uom})
    return prepared


def _find_alias(
    aliases: Mapping[str, Sequence[Mapping[str, Any]]],
    description: str,
    line: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    """Resolve an alias only when its saved UOM scope is satisfied.

    Different targets may validly share supplier wording when their UOM scopes
    differ.  A scoped alias never applies when the invoice line omits its UOM.
    """

    records = list(aliases.get(normalize_description(description), ()))
    if not records:
        return None
    line_uom = _normalize_uom(line.get("uom"))
    if line_uom:
        exact = [record for record in records if record.get("uom") == line_uom]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None
    unscoped = [record for record in records if not record.get("uom")]
    return unscoped[0] if len(unscoped) == 1 else None


def _rank_candidates(
    line: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    index: _CandidateIndex | None = None,
    uninformative_kinds: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    description = str(line.get("description") or "").strip()
    normalized = normalize_description(description)
    line_attributes = _attributes(description, line.get("uom"))
    candidates: list[dict[str, Any]] = []
    pool = index.pool(normalized) if index is not None else catalog
    for item in pool:
        compatibility = _compatibility(line_attributes, item["_attributes"])
        exact = normalized == item["_normalized"]
        score = 100.0 if exact else _similarity(normalized, item["_normalized"])
        reason_parts = [_score_reason(score, exact)]
        if compatibility["matches"]:
            reason_parts.extend(compatibility["matches"])
        # An unknown on a kind that is single-valued across the eligible
        # catalog (see _uninformative_kinds) is reported but not held against
        # the candidate: it cannot cap the score or block the auto decision.
        informative_unknowns: list[str] = []
        for kind, label in zip(compatibility["unknown_kinds"], compatibility["unknowns"]):
            if kind in uninformative_kinds:
                reason_parts.append(f"{label} (single-valued across the eligible catalog; not held against the match)")
            else:
                reason_parts.append(label)
                informative_unknowns.append(label)
        if compatibility["conflicts"]:
            score = min(score, 45.0)
            reason_parts.extend(compatibility["conflicts"])
        # The score before the critical-unknown cap.  Ordering and tie-breaking
        # use it so the first candidate is the system's own best guess; the
        # capped ``score`` is what the auto decision reads.
        raw_score = round(max(0.0, min(100.0, score)), 1)
        if not compatibility["conflicts"] and informative_unknowns:
            # Missing critical attributes should remain reviewable even when the
            # words happen to be very similar.
            # Partner constant: AUTO_FUZZY_THRESHOLD (top of this module).  This
            # cap must stay strictly below it; the gap is the only thing that
            # keeps a near-identical line with a one-sided size / pack / shade
            # out of the auto tier on the fuzzy path
            # (tests/test_matching.py::test_critical_unknown_cap_stays_below_auto_fuzzy_threshold).
            score = min(score, CRITICAL_UNKNOWN_SCORE_CAP)
        candidates.append(
            {
                "catalog_item_id": item.get("catalog_item_id"),
                "_catalog_key": item["_catalog_key"],
                "rms_item_id": item["rms_item_id"],
                "parent_item": item.get("parent_item") or item["rms_item_id"],
                "upc": item.get("upc"),
                "unit_cost": item.get("unit_cost"),
                "cost_currency": item.get("cost_currency"),
                "uom": item.get("uom"),
                "master_po_number": item.get("master_po_number"),
                "description": item["description"],
                "supplier_id": item.get("supplier_id"),
                "score": round(max(0.0, min(100.0, score)), 1),
                "_raw_score": raw_score,
                "reason": "; ".join(reason_parts),
                "_compatible": not compatibility["conflicts"],
                "_critical_unknown": bool(informative_unknowns),
                "_exact": exact,
                "_alias": False,
            }
        )
    candidates.sort(key=_ranking_key)
    return candidates


def _ranking_key(candidate: Mapping[str, Any]) -> tuple[float, float, str, str]:
    """Order by the uncapped score first so the shown row is the best guess.

    The critical-unknown cap (CRITICAL_UNKNOWN_SCORE_CAP) applies to the auto
    decision, not to ranking: with capped-score ordering two near-identical
    rows could be shown in rms_item_id order rather than by how well they
    match.  The margin in match_lines is still measured on capped scores
    against the strongest runner-up, so this ordering never loosens the gate.
    """

    return (
        -float(candidate.get("_raw_score", candidate["score"])),
        -float(candidate["score"]),
        str(candidate["rms_item_id"]),
        str(candidate.get("_catalog_key") or ""),
    )


# Identifiers the duplicate-row collapse must agree on before folding rows of
# one RMS item.  The cost and UOM checks below refuse blank-vs-real correctly
# (None is a set member); these identifiers were absent from the guard
# entirely, so two rows disagreeing on the barcode folded into whichever row
# ranked first, and the exported UPC of an automatic line depended on catalog
# row order.  Value-vs-empty is not a disagreement: the survivor carries the
# one declared value regardless of which row ranked first.
COLLAPSE_IDENTIFIER_FIELDS: tuple[tuple[str, str], ...] = (
    ("upc", "UPC"),
    ("parent_item", "parent item"),
    ("master_po_number", "master PO"),
)
# Reason code named on a line whose duplicate rows disagree on an identifier,
# and the role that owns it.  (Registered here until the governed reason-code
# registry lands on main; it maps 1:1 onto a registry entry then.)
COLLAPSE_DISAGREE_CODE = "duplicate_rows_disagree"
COLLAPSE_DISAGREE_OWNER = "brand_reviewer"


def _identifier_value(member: Mapping[str, Any], field: str) -> str | None:
    """A declared identifier, or None when the row leaves it empty.

    ``_prepare_catalog`` fills an empty parent item with the row's own
    rms_item_id, so a parent equal to the item is "undeclared" here.
    """
    value = member.get(field)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if field == "parent_item" and text == str(member.get("rms_item_id")):
        return None
    return text


def _collapse_duplicate_rows(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold several eligible rows of ONE RMS item into their best row.

    A master holds one row per site for an item, so a resolved supplier's
    scope can present the same rms_item_id several times.  Left alone those
    rows tie at the top, the margin is zero and an exactly named item is
    never selected.  Reviewer A's conditions, applied verbatim: collapse
    ONLY within a resolved supplier scope, or refuse to collapse any group
    whose unit_cost values differ.  The caller enforces the first (this is
    never called in unresolved_supplier_fallback mode); this function
    enforces the second and additionally refuses a group whose UOM differs,
    because the selected row's unit is what unit_check reads.  A refused
    group keeps every row, so the tie stands and the line surfaces as
    ``suggested`` with a reason naming the divergence.

    The same refusal covers the row identifiers in COLLAPSE_IDENTIFIER_FIELDS:
    two or more DISTINCT declared values for the UPC, the parent item or the
    master PO are a disagreement the software cannot settle, so the group is
    kept and the line carries COLLAPSE_DISAGREE_CODE naming the field(s) and
    the values that would have been discarded.  One declared value against
    empties folds, and the surviving row carries that value whichever row
    ranked first.
    """

    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in ranked:
        groups.setdefault(str(candidate["rms_item_id"]), []).append(candidate)
    if len(groups) == len(ranked):
        return ranked
    kept: list[dict[str, Any]] = []
    noted: set[str] = set()
    for candidate in ranked:
        rms_item_id = str(candidate["rms_item_id"])
        group = groups[rms_item_id]
        if len(group) == 1:
            kept.append(candidate)
            continue
        costs = {_cost_value(member.get("unit_cost")) for member in group}
        units = {_normalize_uom(member.get("uom")) for member in group}
        divergence = []
        if len(costs) > 1:
            divergence.append(f"{len(costs)} distinct unit costs")
        if len(units) > 1:
            divergence.append(f"{len(units)} distinct UOMs")
        # Identifier disagreement: DISTINCT declared values only; empties do
        # not count, so value-vs-empty is not a divergence.
        disagreements: dict[str, list[str]] = {}
        carried: dict[str, str] = {}
        for field, label in COLLAPSE_IDENTIFIER_FIELDS:
            declared = sorted({v for v in (_identifier_value(m, field) for m in group) if v is not None})
            if len(declared) > 1:
                disagreements[field] = declared
                divergence.append(f"{len(declared)} distinct {label}s ({', '.join(declared)})")
            elif len(declared) == 1:
                carried[field] = declared[0]
        if divergence:
            if rms_item_id not in noted:
                noted.add(rms_item_id)
                note = (
                    f"{len(group)} eligible catalog rows for this RMS item carry "
                    + " and ".join(divergence)
                    + "; not collapsed, the row must be chosen by an operator"
                )
                if disagreements:
                    note += f" [{COLLAPSE_DISAGREE_CODE}: " + ", ".join(disagreements) + "]"
                for member in group:
                    member["reason"] = member["reason"] + "; " + note
                    member["_collapse_refused"] = note
                    if disagreements:
                        member["_collapse_disagreement"] = {
                            "code": COLLAPSE_DISAGREE_CODE,
                            "owner": COLLAPSE_DISAGREE_OWNER,
                            "fields": dict(disagreements),
                        }
            kept.append(candidate)
            continue
        if candidate is group[0]:
            filled = []
            for field, label in COLLAPSE_IDENTIFIER_FIELDS:
                value = carried.get(field)
                if value is not None and _identifier_value(candidate, field) != value:
                    candidate[field] = value
                    filled.append(label)
            candidate["reason"] = (
                candidate["reason"]
                + f"; {len(group)} eligible catalog rows for this RMS item collapsed "
                "(same unit cost, UOM, UPC, parent item and master PO where declared"
                + (f"; {', '.join(filled)} carried from a sibling row" if filled else "")
                + ")"
            )
            candidate["_collapsed_rows"] = len(group)
            kept.append(candidate)
    return kept


def _cost_value(value: Any) -> float | None:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _resolve_exact_upc(
    line: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    supplier_id: str | None,
) -> tuple[str, Mapping[str, Any] | None, str | None]:
    """Resolve only exact text UPCs with unique supplier and unit evidence.

    UPCs deliberately receive no normalization or numeric coercion here.  In
    particular, leading zeroes are identity-bearing.  A captured UPC that is
    ambiguous or conflicts with UOM/pack evidence blocks weaker automatic
    matching so the line remains reviewable.
    """

    raw_upc = line.get("upc")
    if raw_upc in (None, ""):
        return "absent", None, None
    if not isinstance(raw_upc, str):
        return (
            "invalid",
            None,
            "Captured UPC is not text; no coercion was applied and manual review is required.",
        )
    wanted_supplier = _supplier_key(supplier_id)
    if not wanted_supplier:
        return (
            "missing_supplier",
            None,
            f"Captured UPC '{raw_upc}' cannot be resolved without an exact supplier scope.",
        )

    matches = [
        item
        for item in catalog
        if _supplier_key(item.get("supplier_id")) == wanted_supplier
        and isinstance(item.get("upc"), str)
        and item.get("upc") == raw_upc
    ]
    if not matches:
        return (
            "not_found",
            None,
            f"Captured UPC '{raw_upc}' has no exact row in supplier '{supplier_id}'.",
        )
    if len(matches) != 1:
        return (
            "ambiguous",
            None,
            f"Captured UPC '{raw_upc}' has multiple rows in supplier '{supplier_id}'; manual review is required.",
        )

    selected = matches[0]
    line_attributes = _attributes(str(line.get("description") or ""), line.get("uom"))
    item_attributes = selected["_attributes"]
    line_uom = line_attributes.get("uom")
    item_uom = item_attributes.get("uom")
    if not line_uom or not item_uom or line_uom != item_uom:
        return (
            "incompatible_evidence",
            None,
            f"Captured UPC '{raw_upc}' lacks compatible non-missing UOM evidence; manual review is required.",
        )

    line_packs = set(line_attributes.get("packs") or ())
    item_packs = set(item_attributes.get("packs") or ())
    if (line_packs or item_packs) and (
        not line_packs or not item_packs or line_packs != item_packs
    ):
        return (
            "incompatible_evidence",
            None,
            f"Captured UPC '{raw_upc}' lacks compatible non-missing pack evidence; manual review is required.",
        )
    return "matched", selected, None


def _attributes(description: str, uom: Any) -> dict[str, Any]:
    normalized = normalize_description(description)
    sizes: set[tuple[str, int]] = set()
    size_pattern = re.compile(
        r"\b(\d+(?:[.,]\d+)?)\s*(fl\s*oz|ml|milliliter|l|liter|cl|kg|kilogram|g|gram|oz)\b",
        re.I,
    )
    for match in size_pattern.finditer(normalized):
        value = float(match.group(1).replace(",", "."))
        unit = re.sub(r"\s+", "", match.group(2).lower())
        if unit in {"ml", "milliliter"}:
            sizes.add(("volume_ml", round(value * 1000)))
        elif unit in {"l", "liter"}:
            sizes.add(("volume_ml", round(value * 1_000_000)))
        elif unit == "cl":
            sizes.add(("volume_ml", round(value * 10_000)))
        elif unit in {"g", "gram"}:
            sizes.add(("weight_g", round(value * 1000)))
        elif unit in {"kg", "kilogram"}:
            sizes.add(("weight_g", round(value * 1_000_000)))
        elif unit == "floz":
            sizes.add(("fluid_oz", round(value * 1000)))
        else:
            sizes.add(("weight_oz", round(value * 1000)))

    packs: set[int] = set()
    pack_patterns = (
        r"\b(?:pack|pk|box|case)\s*(?:of\s*)?(\d+)\b",
        r"\b(\d+)\s*(?:pack|pk)\b",
        r"\b(\d+)\s*x\s*\d+(?:[.,]\d+)?\s*(?:ml|l|cl|g|kg|oz)\b",
    )
    for pattern in pack_patterns:
        packs.update(int(match) for match in re.findall(pattern, normalized, re.I))

    shades = {
        f"shade:{match.casefold()}"
        for match in re.findall(r"\bshade\s*(?:no\s*)?([a-z0-9]+)\b", normalized, re.I)
    }
    shades.update(
        f"color:{match.casefold()}"
        for match in re.findall(
            r"\bcolor\s+(?!shade\b)(?:no\s*)?([a-z0-9]+)\b", normalized, re.I
        )
    )
    return {
        "sizes": sizes,
        "packs": packs,
        "shades": shades,
        "uom": _normalize_uom(uom),
    }


def _compatibility(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, list[str]]:
    """Compare two attribute sets.

    ``conflicts`` / ``unknowns`` / ``matches`` are human-readable labels for
    reasons.  ``conflict_kinds`` and ``unknown_kinds`` are the parallel lists
    of attribute KINDS (``KIND_SIZE`` ... ``KIND_UOM``); rules that depend on
    which attribute is unknown must read the kinds, never the label text.
    """

    conflicts: list[str] = []
    conflict_kinds: list[str] = []
    unknowns: list[str] = []
    unknown_kinds: list[str] = []
    matches: list[str] = []
    for key, kind, label in ATTRIBUTE_KINDS:
        left_values = set(left[key])
        right_values = set(right[key])
        if left_values and right_values:
            if left_values == right_values:
                matches.append(f"{label} matches")
            else:
                conflicts.append(
                    f"{label} conflict ({_format_attribute(left_values)} vs {_format_attribute(right_values)})"
                )
                conflict_kinds.append(kind)
        elif left_values or right_values:
            unknowns.append(f"{label} appears on only one side")
            unknown_kinds.append(kind)
    left_uom, right_uom = left.get("uom"), right.get("uom")
    if left_uom and right_uom:
        if left_uom == right_uom:
            matches.append("UOM matches")
        else:
            conflicts.append(f"UOM conflict ({left_uom} vs {right_uom})")
            conflict_kinds.append(KIND_UOM)
    elif left_uom or right_uom:
        unknowns.append("UOM appears on only one side")
        unknown_kinds.append(KIND_UOM)
    return {
        "conflicts": conflicts,
        "conflict_kinds": conflict_kinds,
        "unknowns": unknowns,
        "unknown_kinds": unknown_kinds,
        "matches": matches,
    }


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    try:
        from rapidfuzz import fuzz

        weighted = float(fuzz.WRatio(left, right))
        token_sort = float(fuzz.token_sort_ratio(left, right))
        direct = float(fuzz.ratio(left, right))
    except ImportError:  # deterministic lightweight fallback for constrained environments
        weighted = SequenceMatcher(None, left, right).ratio() * 100
        token_sort = SequenceMatcher(None, " ".join(sorted(left.split())), " ".join(sorted(right.split()))).ratio() * 100
        direct = weighted
    return round(0.5 * weighted + 0.3 * token_sort + 0.2 * direct, 1)


def _score_reason(score: float, exact: bool) -> str:
    if exact:
        return "Exact normalized description"
    if score >= 94:
        return "Very strong name similarity"
    if score >= 82:
        return "Strong name similarity"
    if score >= 70:
        return "Moderate name similarity"
    return "Weak name similarity"



def _cost_currency_of(row: Mapping[str, Any] | None) -> str | None:
    """Master cost currency of a catalog row or of its public-candidate projection.

    Raw catalog rows carry ``cost_currency``; ``_public_candidate`` renames it to
    ``rms_cost_currency``.  Both shapes reach the line-update paths, so read
    whichever key is present and never fall back to a default currency.
    """
    if not row:
        return None
    value = row.get("cost_currency")
    if value in (None, ""):
        value = row.get("rms_cost_currency")
    return value if value not in (None, "") else None


def _revalidation_decision(line: Mapping[str, Any], selected: Mapping[str, Any]) -> dict[str, Any]:
    """Decide the status of a line whose supplied catalog row was found again.

    Revalidating a row is not a decision about who chose it.  A line that
    arrives as ``auto`` is a machine selection (for example a stored auto line
    sent back through ``rematch``): it stays ``auto`` and keeps its original
    ``confidence`` byte for byte, with its stored candidates when it has any.
    Only a line that arrives as a human decision (``confirmed``, written by an
    edit the audit trail records) or as a bare supplied identifier with no
    status (an integration asserting the row) is confirmed at 100.0.
    """

    if str(line.get("match_status") or "") == "auto":
        preserved = line.get("confidence")
        stored = line.get("candidates")
        if isinstance(stored, list) and stored:
            candidates = [dict(candidate) for candidate in stored]
        else:
            candidates = [
                _public_candidate(
                    {
                        **selected,
                        "score": preserved,
                        "reason": "Machine selection revalidated against the eligible "
                        "supplier catalog; original score preserved.",
                    }
                )
            ]
        return {"match_status": "auto", "confidence": preserved, "candidates": candidates}
    return {
        "match_status": "confirmed",
        "confidence": 100.0,
        "candidates": [
            _public_candidate(
                {
                    **selected,
                    "score": 100.0,
                    "reason": "Supplied catalog row validated against the eligible supplier catalog.",
                }
            )
        ],
    }


def _public_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "rms_item_id": candidate["rms_item_id"],
        "description": candidate["description"],
        "score": candidate["score"],
        "reason": candidate["reason"],
    }
    disagreement = candidate.get("_collapse_disagreement")
    if disagreement:
        result["reason_code"] = disagreement["code"]
        result["reason_owner"] = disagreement["owner"]
        result["disagreeing_fields"] = dict(disagreement["fields"])
    if candidate.get("catalog_item_id") is not None:
        result["catalog_item_id"] = candidate["catalog_item_id"]
        for field in ("uom", "master_po_number"):
            if candidate.get(field) is not None:
                result[field] = candidate[field]
        if candidate.get("parent_item") is not None:
            result["rms_parent_item"] = candidate["parent_item"]
        if candidate.get("upc") is not None:
            result["rms_upc"] = candidate["upc"]
        if candidate.get("unit_cost") is not None:
            result["rms_unit_cost"] = candidate["unit_cost"]
        if candidate.get("cost_currency") is not None:
            result["rms_cost_currency"] = candidate["cost_currency"]
    return result


def _normalize_uom(value: Any) -> str | None:
    if value in (None, ""):
        return None
    compact = re.sub(r"[^A-Za-z]", "", str(value)).upper()
    return _UOM_ALIASES.get(compact, compact or None)


def _format_attribute(values: set[Any]) -> str:
    formatted = []
    for value in sorted(values, key=str):
        if isinstance(value, tuple) and len(value) == 2:
            kind, scaled = value
            if kind == "volume_ml":
                formatted.append(f"{scaled / 1000:g}ml")
            elif kind == "weight_g":
                formatted.append(f"{scaled / 1000:g}g")
            else:
                formatted.append(f"{scaled / 1000:g} {kind}")
        else:
            formatted.append(str(value))
    return ", ".join(formatted)


def _supplier_key(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def _optional_string(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _stable_line_id(index: int, line: Mapping[str, Any]) -> str:
    evidence = "|".join(
        str(line.get(field, ""))
        for field in ("description", "quantity", "uom", "unit_price", "line_total", "tax_rate")
    )
    digest = hashlib.sha256(f"{index}|{evidence}".encode("utf-8")).hexdigest()[:16]
    return f"line-{digest}"


__all__ = [
    "AUTO_FUZZY_MARGIN",
    "AUTO_FUZZY_THRESHOLD",
    "CatalogValidationError",
    "SUGGEST_THRESHOLD",
    "enrich_invoice",
    "match_lines",
    "normalize_description",
    "suggest_matches",
]
