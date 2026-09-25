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
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence


class CatalogValidationError(ValueError):
    """Catalog or alias configuration is invalid."""


AUTO_FUZZY_THRESHOLD = 96.0
AUTO_FUZZY_MARGIN = 8.0
SUGGEST_THRESHOLD = 70.0
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
    ranked = _rank_candidates(line_mapping, prepared_catalog)

    upc_state, upc_item, _ = _resolve_exact_upc(
        line_mapping, prepared_catalog, supplier_id
    )
    if upc_state == "matched" and upc_item is not None:
        for candidate in ranked:
            if candidate["_catalog_key"] == upc_item["_catalog_key"]:
                candidate["score"] = 100.0
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
                candidate["score"] = 100.0
                candidate["reason"] = "Approved supplier alias; " + candidate["reason"]
                candidate["_alias"] = True
                break
    ranked.sort(key=lambda item: (-item["score"], str(item["rms_item_id"])))
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
    prepared_catalog = _prepare_catalog(
        catalog, supplier_id, include_all_suppliers=fallback_active
    )
    candidate_index = (
        _CandidateIndex(prepared_catalog)
        if len(prepared_catalog) > PREFILTER_MIN_ROWS
        else None
    )
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
                line.update(
                    {
                        "catalog_item_id": selected.get("catalog_item_id"),
                        "rms_item_id": selected["rms_item_id"],
                        "rms_parent_item": selected.get("parent_item")
                        or selected["rms_item_id"],
                        "rms_upc": selected.get("upc"),
                        "rms_unit_cost": selected.get("unit_cost"),
                        "rms_po_number": selected.get("master_po_number"),
                        "match_status": "confirmed",
                        "confidence": 100.0,
                        "candidates": [_public_candidate({
                            **selected,
                            "score": 100.0,
                            "reason": "Supplied catalog row validated against the eligible supplier catalog.",
                        })],
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

        ranked = _rank_candidates(line, prepared_catalog, index=candidate_index)
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
                upc_candidate["score"] = 100.0
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
                alias_candidate["score"] = 100.0
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
        ranked.sort(key=lambda item: (-item["score"], str(item["rms_item_id"])))
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
        if upc_candidate is not None and not upc_alias_conflict:
            selected, status, confidence = upc_candidate, "auto", 100.0
        elif not upc_blocks_automatic_selection and alias_candidate and alias_candidate["_compatible"]:
            selected, status, confidence = alias_candidate, "auto", 100.0
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
                selected, status, confidence = top, "auto", 100.0
            else:
                second_score = ranked[1]["score"] if len(ranked) > 1 else 0.0
                margin = top["score"] - second_score
                if (
                    not upc_blocks_automatic_selection
                    and top["score"] >= AUTO_FUZZY_THRESHOLD
                    and margin >= AUTO_FUZZY_MARGIN
                    and top["_compatible"]
                    and not top["_critical_unknown"]
                ):
                    selected, status, confidence = top, "auto", top["score"]
                elif top["score"] >= SUGGEST_THRESHOLD and top["_compatible"]:
                    status = "suggested"

        if fallback_active and status == "auto":
            # A full-catalog fallback cannot select a row automatically:
            # description-only matches across suppliers collide.
            selected = None
            status = "suggested"
            confidence = ranked[0]["score"] if ranked else 0.0

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
                "rms_unit_cost": selected.get("unit_cost") if selected else None,
                "rms_po_number": selected.get("master_po_number") if selected else None,
                "match_status": status,
                "confidence": round(float(confidence), 1),
                "candidates": public_candidates,
            }
        )
        output.append(line)
    return output


def enrich_invoice(
    invoice: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]] | Mapping[str, str] | None = None,
    supplier_id: str | None = None,
) -> dict[str, Any]:
    """Return a copy of an extracted invoice with its lines matched."""

    enriched = dict(invoice)
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
        if compatibility["unknowns"]:
            reason_parts.extend(compatibility["unknowns"])
        if compatibility["conflicts"]:
            score = min(score, 45.0)
            reason_parts.extend(compatibility["conflicts"])
        elif compatibility["unknowns"]:
            # Missing critical attributes should remain reviewable even when the
            # words happen to be very similar.
            score = min(score, 92.0)
        candidates.append(
            {
                "catalog_item_id": item.get("catalog_item_id"),
                "_catalog_key": item["_catalog_key"],
                "rms_item_id": item["rms_item_id"],
                "parent_item": item.get("parent_item") or item["rms_item_id"],
                "upc": item.get("upc"),
                "unit_cost": item.get("unit_cost"),
                "master_po_number": item.get("master_po_number"),
                "description": item["description"],
                "supplier_id": item.get("supplier_id"),
                "score": round(max(0.0, min(100.0, score)), 1),
                "reason": "; ".join(reason_parts),
                "_compatible": not compatibility["conflicts"],
                "_critical_unknown": bool(compatibility["unknowns"]),
                "_exact": exact,
                "_alias": False,
            }
        )
    candidates.sort(key=lambda item: (-item["score"], str(item["rms_item_id"])))
    return candidates


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
    conflicts: list[str] = []
    unknowns: list[str] = []
    matches: list[str] = []
    for key, label in (("sizes", "size"), ("packs", "pack count"), ("shades", "shade")):
        left_values = set(left[key])
        right_values = set(right[key])
        if left_values and right_values:
            if left_values == right_values:
                matches.append(f"{label} matches")
            else:
                conflicts.append(
                    f"{label} conflict ({_format_attribute(left_values)} vs {_format_attribute(right_values)})"
                )
        elif left_values or right_values:
            unknowns.append(f"{label} appears on only one side")
    left_uom, right_uom = left.get("uom"), right.get("uom")
    if left_uom and right_uom:
        if left_uom == right_uom:
            matches.append("UOM matches")
        else:
            conflicts.append(f"UOM conflict ({left_uom} vs {right_uom})")
    elif left_uom or right_uom:
        unknowns.append("UOM appears on only one side")
    return {"conflicts": conflicts, "unknowns": unknowns, "matches": matches}


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


def _public_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "rms_item_id": candidate["rms_item_id"],
        "description": candidate["description"],
        "score": candidate["score"],
        "reason": candidate["reason"],
    }
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
