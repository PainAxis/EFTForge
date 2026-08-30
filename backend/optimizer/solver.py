"""Top-level entry point for the weapon build optimizer.

This is the MVP pass agreed with the user: weapon + mods only. Deliberately
NOT yet handling, in order of how much they matter for a typical build:
  - presets as an alternative "base" competing with the naked receiver
  - Found-in-Raid fallback pricing for mods with no purchase offers
  - multi-slot placement variables (see milp.py's dependency-constraint
    comment for the narrow edge case this leaves)
  - EvoErgo tangent-sweep mode and Tchebycheff scalarization ("Sweet Spot")
  - category include/exclude filters
These are follow-up work, not something this module silently fakes.

Every stat number this module reports comes from stats._compute_stats() -
EFTForge's own, already-tested EED/overswing/arm-stamina/MOA formulas -
never a separately-derived formula, so the optimizer and the Combo
Calculator always agree on what a given attachment set's stats are.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict

from models_items import Item
from models_item_offers import ItemOffer
from stats import _compute_stats

from optimizer.compat_map import build_compatibility_map
from optimizer.pricing import get_best_price, offers_by_item
from optimizer.feasibility import check_feasibility
from optimizer.milp import build_and_solve


@dataclass
class OptimizeParams:
    max_price: Optional[float] = None
    min_ergonomics: Optional[float] = None
    max_recoil_v: Optional[float] = None
    max_weight: Optional[float] = None
    min_mag_capacity: Optional[int] = None
    min_sighting_range: Optional[float] = None
    include_items: Optional[List[str]] = None
    exclude_items: Optional[List[str]] = None
    ergo_weight: float = 1.0
    recoil_weight: float = 1.0
    price_weight: float = 0.0
    # EvoErgo mode replaces the weighted ergo/recoil/price objective above with
    # a tangent-sweep search for the build with the best true EED (see
    # optimizer/milp.py). evo_ergo_k lets a caller pin a specific tangent slope
    # instead of sweeping the default anchor set - mainly useful for tests.
    use_evo_ergo: bool = False
    evo_ergo_k: Optional[float] = None
    trader_levels: Optional[Dict[str, int]] = None
    flea_available: bool = True
    player_level: Optional[int] = None
    strength_level: int = 10
    equip_ergo_modifier: float = 0.0


def optimize_weapon(db, weapon_id: str, params: OptimizeParams) -> dict:
    weapon = db.query(Item).filter(Item.id == weapon_id, Item.is_weapon == True).first()  # noqa: E712
    if not weapon:
        return {"status": "error", "reason": f"Unknown weapon id: {weapon_id}", "selected_items": [], "slot_pairs": []}

    compat_map = build_compatibility_map(db, weapon_id)
    all_mod_ids = list(compat_map.reachable_ids)

    mods = {}
    if all_mod_ids:
        mods = {m.id: m for m in db.query(Item).filter(Item.id.in_(all_mod_ids)).all()}

    offers_map = {}
    if all_mod_ids:
        offer_rows = db.query(ItemOffer).filter(ItemOffer.item_id.in_(all_mod_ids)).all()
        offers_map = offers_by_item(offer_rows)

    exclude = set(params.exclude_items or [])
    candidate_ids = []
    prices = {}
    for item_id in all_mod_ids:
        if item_id in exclude or item_id not in mods:
            continue
        best = get_best_price(offers_map.get(item_id, []), params.trader_levels, params.flea_available, params.player_level)
        if best is None:
            continue  # unpurchasable under current filters - MVP excludes it outright, no FiR fallback yet
        candidate_ids.append(item_id)
        prices[item_id] = best

    reasons = check_feasibility(weapon, mods, candidate_ids, params)
    if reasons:
        return {"status": "infeasible", "reason": "; ".join(reasons), "selected_items": [], "slot_pairs": []}

    result = build_and_solve(weapon, mods, compat_map, candidate_ids, prices, params)

    if result["status"] == "optimal":
        final_stats = _compute_stats(
            weapon, result["selected_items"], mods, params.strength_level, params.equip_ergo_modifier
        )
        result["final_stats"] = final_stats
        result["gun_id"] = weapon_id

    return result
