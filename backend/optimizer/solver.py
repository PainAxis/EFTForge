"""Top-level entry point for the weapon build optimizer.

What's deliberately not handled, and why:
  - presets as an alternative "base" competing with the base receiver - the
    one remaining piece of the reference optimizer's model this doesn't cover
  - multi-slot placement variables - attempted (a real gap: 418 of 579
    reachable M4A1 attachments have more than one valid parent slot), but the
    exact formulation blew up solve time badly enough in testing (full test
    suite went from single-digit seconds to 10+ minutes without finishing)
    that it's not viable without real solver-performance work first. Reverted;
    see milp.py's dependency-constraint comment for the narrow correctness
    gap this leaves.
  - Tchebycheff scalarization ("Sweet Spot" mode) - skipped as low value
    without a paired Explore/visualization feature
Found-in-Raid fallback pricing (below) and category include filters and
EvoErgo mode (optimizer/milp.py) are implemented.

Every stat number this module reports comes from stats._compute_stats() -
EFTForge's own, already-tested EED/overswing/arm-stamina/MOA formulas -
never a separately-derived formula, so the optimizer and the Combo
Calculator always agree on what a given attachment set's stats are.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict

from models_items import Item
from models_item_offers import ItemOffer
from stats import _compute_stats

from optimizer.compat_map import build_compatibility_map
from optimizer.pricing import get_best_price, offers_by_item
from optimizer.feasibility import check_feasibility
from optimizer.milp import build_and_solve, compute_stat_ranges as _milp_stat_ranges


@dataclass
class OptimizeParams:
    max_price: Optional[float] = None
    min_ergonomics: Optional[float] = None
    max_recoil_v: Optional[float] = None
    max_recoil_sum: Optional[float] = None  # vertical + horizontal combined - used by Gunsmith tasks
    max_weight: Optional[float] = None
    min_mag_capacity: Optional[int] = None
    min_sighting_range: Optional[float] = None
    include_items: Optional[List[str]] = None
    exclude_items: Optional[List[str]] = None
    # Each inner list is an OR-group of raw tarkov.dev category ids - at least
    # one selected item must match each group. Matches Item.category_ids
    # (comma-separated raw category ids, populated by sync_tarkov_dev.py).
    include_categories: Optional[List[List[str]]] = None
    # Flat list of raw category ids - no selected item may match any of them.
    exclude_categories: Optional[List[str]] = None
    ergo_weight: float = 1.0
    recoil_weight: float = 1.0
    price_weight: float = 0.0
    # EvoErgo mode replaces the weighted ergo/recoil/price objective above with
    # a tangent-sweep search for the build with the best true EED (see
    # optimizer/milp.py). evo_ergo_k lets a caller pin a specific tangent slope
    # instead of sweeping the default anchor set - mainly useful for tests.
    use_evo_ergo: bool = False
    evo_ergo_k: Optional[float] = None
    # Hard-constrains the build to stats._compute_stats()'s own "overswing"
    # definition (total_weight <= KG(effective_ergo)), approximated by tangent
    # cuts around milp.py's EVO_ERGO_ERGO_ANCHORS since a MILP can't encode the
    # true quadratic threshold directly.
    prevent_overswing: bool = False
    # Upper bound on stats.py's accuracy_moa (lower MOA = tighter grouping).
    max_moa: Optional[float] = None
    trader_levels: Optional[Dict[str, int]] = None
    flea_available: bool = True
    player_level: Optional[int] = None
    strength_level: int = 10
    equip_ergo_modifier: float = 0.0


def _load_candidates_and_prices(db, weapon_id: str, params: OptimizeParams):
    """Shared setup for optimize_weapon() and get_stat_ranges(): the weapon,
    its reachable mods, and which of those are actually selectable (and at
    what price) once exclude_items/exclude_categories and the current
    trader/flea/player-level access filters are applied.
    """
    weapon = db.query(Item).filter(Item.id == weapon_id, Item.is_weapon == True).first()  # noqa: E712
    if not weapon:
        return None, None, None, None

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
    exclude_categories = set(params.exclude_categories or [])
    candidate_ids = []
    prices = {}
    for item_id in all_mod_ids:
        if item_id in exclude or item_id not in mods:
            continue
        if exclude_categories and exclude_categories & set((mods[item_id].category_ids or "").split(",")):
            continue
        raw_offers = offers_map.get(item_id, [])
        best = get_best_price(raw_offers, params.trader_levels, params.flea_available, params.player_level)
        if best is None:
            if raw_offers:
                continue  # has offers, just none accessible under the current trader/flea filters
            # No trader or flea ever sells this at all - Found-in-Raid only.
            # A player might already own one, so it's freely selectable at
            # price 0 rather than excluded (matches the reference optimizer's
            # is_fir_mod handling in weapon_optimizer.py).
            best = {"price": 0, "currency": "RUB", "price_rub": 0, "vendor": None}
        candidate_ids.append(item_id)
        prices[item_id] = best

    return weapon, compat_map, mods, (candidate_ids, prices)


def optimize_weapon(db, weapon_id: str, params: OptimizeParams) -> dict:
    weapon, compat_map, mods, loaded = _load_candidates_and_prices(db, weapon_id, params)
    if weapon is None:
        return {"status": "error", "reason": f"Unknown weapon id: {weapon_id}", "selected_items": [], "slot_pairs": []}
    candidate_ids, prices = loaded

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


def get_stat_ranges(db, weapon_id: str, params: OptimizeParams) -> dict:
    """Theoretical [min, max] each hard-constraint stat can reach for this
    weapon under the current trader/flea/player-level access, so the
    optimizer UI can cap each constraint slider to what's actually
    achievable instead of an arbitrary fixed range.
    """
    weapon, compat_map, mods, loaded = _load_candidates_and_prices(db, weapon_id, params)
    if weapon is None:
        return {"status": "error", "reason": f"Unknown weapon id: {weapon_id}"}
    candidate_ids, prices = loaded
    return {"status": "ok", "ranges": _milp_stat_ranges(weapon, mods, compat_map, candidate_ids, prices)}


# Binary-search step count and convergence tolerance, ported from the
# reference optimizer's computeMOAFloor (solver.worker.ts) - it already had
# the right idea: reuse the existing max_moa constraint instead of a second,
# separately-derived "maximize accuracy" model.
_MOA_FLOOR_MAX_ITERS = 14
_MOA_FLOOR_EPS = 0.02


def get_moa_floor(db, weapon_id: str, params: OptimizeParams) -> dict:
    """Exact minimum achievable accuracy_moa for this weapon, found by
    binary-searching the max_moa constraint with real solves (each one an
    actual integer MILP, not the LP-relaxation approximation
    milp.compute_stat_ranges() uses for the fast/default slider bounds).
    Slower, but exact - only run when the user opts into it via the
    optimizer's "Exact slider floor" toggle.
    """
    weapon, compat_map, mods, loaded = _load_candidates_and_prices(db, weapon_id, params)
    if weapon is None:
        return {"status": "error", "reason": f"Unknown weapon id: {weapon_id}"}
    candidate_ids, prices = loaded

    base_params = OptimizeParams(
        trader_levels=params.trader_levels,
        flea_available=params.flea_available,
        player_level=params.player_level,
        ergo_weight=0.0,
        recoil_weight=0.0,
        price_weight=1.0,
    )

    seed = build_and_solve(weapon, mods, compat_map, candidate_ids, prices, base_params)
    if seed["status"] != "optimal":
        return {"status": "ok", "floor": 0.0}
    seed_stats = _compute_stats(weapon, seed["selected_items"], mods)
    hi = seed_stats["accuracy_moa"] or 0.0
    lo = 0.0

    for _ in range(_MOA_FLOOR_MAX_ITERS):
        if hi - lo <= _MOA_FLOOR_EPS:
            break
        mid = (lo + hi) / 2
        trial_params = OptimizeParams(
            trader_levels=params.trader_levels,
            flea_available=params.flea_available,
            player_level=params.player_level,
            ergo_weight=0.0,
            recoil_weight=0.0,
            price_weight=1.0,
            max_moa=mid,
        )
        result = build_and_solve(weapon, mods, compat_map, candidate_ids, prices, trial_params)
        if result["status"] == "optimal":
            stats = _compute_stats(weapon, result["selected_items"], mods)
            hi = min(hi, stats["accuracy_moa"] or hi)
        else:
            lo = mid

    return {"status": "ok", "floor": round(hi, 3)}
