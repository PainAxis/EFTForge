"""MILP formulation: weapon + mods (no presets-as-base yet - see
optimizer/solver.py's module docstring for what's still deferred and why).

Solved with scipy.optimize.milp (HiGHS backend) - the same solver engine the
original optimizer's WASM frontend already uses.
"""

from collections import deque

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds

from stats import _compute_stats

TIEBREAK = 0.01

# Hard cap on a single HiGHS solve. A normal solve finishes in well under a
# second; this only ever matters for a pathological case (an earlier attempt
# at multi-slot placement variables produced a MILP that ran for 30+ minutes
# without finishing). Without a cap, that kind of case would hang a backend
# worker indefinitely instead of degrading gracefully.
SOLVE_TIME_LIMIT_SECONDS = 120

# Reference scales so the 0-1 priority sliders behave consistently regardless
# of a weapon's absolute ergo/recoil/price magnitudes.
ERGO_SCALE = 100.0
PRICE_SCALE_FALLBACK = 300_000.0

# EvoErgo tangent sweep: anchor total-ergo values to linearize EFTForge's own
# quadratic KG(E) curve (stats.py's _compute_stats) around. A MILP can only
# optimize a linear objective, so true EED (a quadratic function of ergo) has
# to be approximated by a handful of tangent lines, each solved separately -
# the tangent whose resulting build has the best *true* EED wins. This mirrors
# the reference optimizer's k-sweep approach (CHANGELOG "EED tangent k-sweep
# solver"), just re-derived against EFTForge's own KG(E) coefficients instead
# of the reference's separate formula, per the "always use EFTForge's own
# formula" decision.
EVO_ERGO_ERGO_ANCHORS = [30, 55, 80, 105, 130, 155]


class _Infeasible(Exception):
    def __init__(self, reason):
        self.reason = reason


class ConstraintBuilder:
    """Accumulates (coeffs, lb, ub) rows, then assembles one LinearConstraint."""

    def __init__(self, n):
        self.n = n
        self.rows = []

    def le(self, coeffs: dict, rhs):
        self.rows.append((coeffs, -np.inf, rhs))

    def ge(self, coeffs: dict, rhs):
        self.rows.append((coeffs, rhs, np.inf))

    def eq(self, coeffs: dict, rhs):
        self.rows.append((coeffs, rhs, rhs))

    def build(self):
        if not self.rows:
            return None
        A = np.zeros((len(self.rows), self.n))
        lb = np.zeros(len(self.rows))
        ub = np.zeros(len(self.rows))
        for row_i, (coeffs, l, u) in enumerate(self.rows):
            for col_i, val in coeffs.items():
                A[row_i, col_i] += val
            lb[row_i] = l
            ub[row_i] = u
        return LinearConstraint(A, lb, ub)


def _order_pairs_parent_first(selected_ids, item_to_valid_slots, weapon_id, selected_set):
    """EFTForge's build importer (build-manager.js loadBuildFromPayload) installs
    slot_pairs with a single BFS pass and looks up each pair's parent node by
    slot id - so a child pair arriving before its parent silently gets dropped.
    I pick one concrete slot per selected item (same "first owner that's
    actually in the build" rule the plain selected-order version used), then
    emit pairs in a real BFS from the weapon outward so every parent is
    guaranteed to precede its children.
    """
    chosen = {}
    for item_id in selected_ids:
        for slot_id, owner in sorted(item_to_valid_slots.get(item_id, [])):
            if owner == weapon_id or owner in selected_set:
                chosen[item_id] = (slot_id, owner)
                break

    children_of = {}
    for item_id, (_, owner) in chosen.items():
        children_of.setdefault(owner, []).append(item_id)

    pairs = []
    queue = deque(children_of.get(weapon_id, []))
    while queue:
        item_id = queue.popleft()
        slot_id, _ = chosen[item_id]
        pairs.append([slot_id, item_id])
        queue.extend(children_of.get(item_id, []))

    return pairs


def _item_to_valid_slots(compat_map, candidate_set):
    """item_id -> [(slot_id, owner_id), ...] restricted to candidate items."""
    out = {}
    for slot_id, items in compat_map.slot_items.items():
        owner = compat_map.slot_owner[slot_id]
        for item_id in items:
            if item_id in candidate_set:
                out.setdefault(item_id, []).append((slot_id, owner))
    return out


def _build_constraints(weapon, mods: dict, compat_map, candidate_ids: list, prices: dict, params):
    """Builds every item_id/idx/constraint/item_to_valid_slots the solve needs,
    independent of the objective - so the EvoErgo sweep can re-solve the same
    model with different objectives without rebuilding constraints each time.
    Raises _Infeasible for anything that can be ruled out before ever calling
    the solver (an empty candidate set, an unmeetable mag/sighting/include
    requirement).
    """
    item_ids = list(candidate_ids)
    idx = {item_id: i for i, item_id in enumerate(item_ids)}
    n = len(item_ids)
    weapon_id = weapon.id

    if n == 0:
        raise _Infeasible("No attachments are available under the current filters.")

    candidate_set = set(item_ids)
    item_to_valid_slots = _item_to_valid_slots(compat_map, candidate_set)

    cb = ConstraintBuilder(n)

    # 1. Slot mutex - at most one item per slot.
    for slot_id, items in compat_map.slot_items.items():
        in_play = [i for i in items if i in idx]
        if len(in_play) >= 2:
            cb.le({idx[i]: 1 for i in in_play}, 1)

    # 2. Dependency - an item needs at least one of its owning slots' owners
    # selected (or to sit directly on the weapon). Items reachable through more
    # than one parent are treated as "usable via any of them" (an OR over
    # owners) rather than tracked with per-slot placement variables. Tried a
    # full placement-variable model (see git history) - it's the structurally
    # correct fix (checked on the M4A1: 418 of 579 reachable attachments have
    # more than one valid parent, so this is common, not a rare edge case),
    # but it blew up solve time badly enough in testing (full suite went from
    # single-digit seconds to 10+ minutes without finishing) that it's not
    # viable without real solver-performance work (tighter symmetry-breaking,
    # a solve time limit, or restricting placement vars to only the items that
    # actually matter for a required-slot conflict). Reverted; the narrow
    # correctness gap this leaves - a multi-parent item double-counting toward
    # two different required-slot constraints at once - stays open.
    for item_id in item_ids:
        owners = {owner for _, owner in item_to_valid_slots.get(item_id, [])}
        if weapon_id in owners:
            continue  # always reachable straight off the weapon
        owner_vars = [idx[o] for o in owners if o in idx]
        if owner_vars:
            coeffs = {idx[item_id]: 1}
            for ov in owner_vars:
                coeffs[ov] = coeffs.get(ov, 0) - 1
            cb.le(coeffs, 0)
        else:
            cb.eq({idx[item_id]: 1}, 0)  # no reachable owner - can't be placed

    # 3. Conflicts - item<->item and item<->slot, both directions.
    conflict_pairs = set()

    def _add_conflicts_for(item_id, item_row):
        if item_row.conflicting_item_ids:
            for other_id in item_row.conflicting_item_ids.split(","):
                if other_id in idx:
                    conflict_pairs.add(tuple(sorted((item_id, other_id))))
        if item_row.conflicting_slot_ids:
            for slot_id in item_row.conflicting_slot_ids.split(","):
                for other_id in compat_map.slot_items.get(slot_id, []):
                    if other_id in idx and other_id != item_id:
                        conflict_pairs.add(tuple(sorted((item_id, other_id))))

    for item_id in item_ids:
        _add_conflicts_for(item_id, mods[item_id])
    # The weapon itself may also declare conflicts (e.g. a receiver that
    # blocks a specific handguard) - those forbid the mod outright.
    forced_zero = set()
    if weapon.conflicting_item_ids:
        for other_id in weapon.conflicting_item_ids.split(","):
            if other_id in idx:
                forced_zero.add(other_id)
    if weapon.conflicting_slot_ids:
        for slot_id in weapon.conflicting_slot_ids.split(","):
            for other_id in compat_map.slot_items.get(slot_id, []):
                if other_id in idx:
                    forced_zero.add(other_id)
    for item_id in forced_zero:
        cb.eq({idx[item_id]: 1}, 0)

    for a, b in conflict_pairs:
        cb.le({idx[a]: 1, idx[b]: 1}, 1)

    # 4. Required slots.
    for slot_id, items in compat_map.slot_items.items():
        slot = compat_map.slots_by_id.get(slot_id)
        if not slot or not slot.required:
            continue
        in_play = [i for i in items if i in idx]
        if not in_play:
            continue
        owner = compat_map.slot_owner[slot_id]
        coeffs = {idx[i]: -1 for i in in_play}
        if owner == weapon_id:
            cb.le(coeffs, -1)  # sum(x_i) >= 1
        elif owner in idx:
            coeffs[idx[owner]] = coeffs.get(idx[owner], 0) + 1
            cb.le(coeffs, 0)  # sum(x_i) >= x_owner

    # 5. Hard-stat / budget constraints. Recoil and weight are affine in x
    # given a fixed receiver base, since EFTForge's own stat formula is
    # base * (1 + sum(x_i * modifier_i)) for recoil and base + sum(x_i *
    # weight_i) for weight - both linear once the base is a known constant.
    base_ergo = weapon.base_ergonomics or 0
    base_weight = weapon.weight or 0
    base_recoil_v = weapon.recoil_vertical
    base_recoil_h = weapon.recoil_horizontal

    if params.max_price is not None:
        cb.le({idx[i]: prices[i]["price_rub"] for i in item_ids}, params.max_price)

    if params.min_ergonomics is not None:
        cb.ge({idx[i]: (mods[i].ergonomics_modifier or 0) for i in item_ids}, params.min_ergonomics - base_ergo)

    if params.max_recoil_v is not None and base_recoil_v is not None:
        cb.le(
            {idx[i]: base_recoil_v * (mods[i].recoil_modifier or 0) for i in item_ids},
            params.max_recoil_v - base_recoil_v,
        )

    # Vertical + horizontal combined - both scale by the same recoil_modifier
    # sum per _compute_stats, so this is still affine in x given fixed bases.
    if params.max_recoil_sum is not None and base_recoil_v is not None and base_recoil_h is not None:
        base_sum = base_recoil_v + base_recoil_h
        cb.le(
            {idx[i]: base_sum * (mods[i].recoil_modifier or 0) for i in item_ids},
            params.max_recoil_sum - base_sum,
        )

    if params.include_categories:
        for group in params.include_categories:
            group_set = set(group)
            matching = [i for i in item_ids if group_set & set((mods[i].category_ids or "").split(","))]
            if not matching:
                raise _Infeasible(f"No available item matches required category group: {sorted(group_set)}.")
            cb.ge({idx[i]: 1 for i in matching}, 1)

    if params.max_weight is not None:
        cb.le({idx[i]: (mods[i].weight or 0) for i in item_ids}, params.max_weight - base_weight)

    if params.min_mag_capacity:
        mags = [i for i in item_ids if (mods[i].magazine_capacity or 0) >= params.min_mag_capacity]
        if not mags:
            raise _Infeasible(f"No available magazine with capacity >= {params.min_mag_capacity} rounds.")
        cb.ge({idx[i]: 1 for i in mags}, 1)

    if params.min_sighting_range:
        base_sight = weapon.sighting_range or 0
        if base_sight < params.min_sighting_range:
            sights = [i for i in item_ids if (mods[i].sighting_range or 0) >= params.min_sighting_range]
            if not sights:
                raise _Infeasible(f"No available sight with sighting range >= {params.min_sighting_range}m.")
            cb.ge({idx[i]: 1 for i in sights}, 1)

    if params.include_items:
        for req_id in params.include_items:
            if req_id not in idx:
                raise _Infeasible(f"Required item {req_id} is not available under the current filters.")
            cb.eq({idx[req_id]: 1}, 1)

    return item_ids, idx, cb, item_to_valid_slots, base_ergo, base_weight, base_recoil_v


def _weighted_objective(item_ids, idx, mods, prices, params, base_recoil_v):
    ergo_w = max(params.ergo_weight, TIEBREAK)
    recoil_w = max(params.recoil_weight, TIEBREAK)
    price_w = max(params.price_weight, TIEBREAK)
    price_scale = params.max_price or PRICE_SCALE_FALLBACK
    recoil_scale = abs(base_recoil_v) if base_recoil_v else 1.0

    c = np.zeros(len(item_ids))
    for item_id in item_ids:
        i = idx[item_id]
        ergo_term = -(ergo_w / ERGO_SCALE) * (mods[item_id].ergonomics_modifier or 0)
        recoil_term = (recoil_w / recoil_scale) * (base_recoil_v or 0) * (mods[item_id].recoil_modifier or 0)
        price_term = (price_w / price_scale) * prices[item_id]["price_rub"]
        c[i] = ergo_term + recoil_term + price_term
    return c


def _evo_ergo_objective(k, item_ids, idx, mods, prices, params, base_recoil_v):
    """Same blended objective as _weighted_objective, but the ergo term is
    replaced with a tangent-linearized EvoErgo term (ergo adjusted for its
    weight cost at slope k, the first-order approximation of EFTForge's true
    quadratic EED around the ergo value k was derived from) instead of raw
    ergo. recoil_weight and price_weight still apply exactly as in the plain
    mode - checked against the reference optimizer's lpBuilder.ts, where
    useEvoErgo only adds a weight-penalty term on top of the usual blended
    ergo/recoil/price objective, it doesn't replace it.
    """
    ergo_w = max(params.ergo_weight, TIEBREAK)
    recoil_w = max(params.recoil_weight, TIEBREAK)
    price_w = max(params.price_weight, TIEBREAK)
    price_scale = params.max_price or PRICE_SCALE_FALLBACK
    recoil_scale = abs(base_recoil_v) if base_recoil_v else 1.0

    c = np.zeros(len(item_ids))
    for item_id in item_ids:
        i = idx[item_id]
        evo_ergo_term = (ergo_w / ERGO_SCALE) * (
            -k * (mods[item_id].ergonomics_modifier or 0) + 15 * (mods[item_id].weight or 0)
        )
        recoil_term = (recoil_w / recoil_scale) * (base_recoil_v or 0) * (mods[item_id].recoil_modifier or 0)
        price_term = (price_w / price_scale) * prices[item_id]["price_rub"]
        c[i] = evo_ergo_term + recoil_term + price_term
    return c


def _evo_ergo_k_for_anchor(ergo_anchor, equip_ergo_modifier):
    b = equip_ergo_modifier
    E0 = ergo_anchor * (1 + b)
    kg_prime = 0.0015112 * E0 + 0.02736  # d/dE of stats.py's KG(E) = 0.0007556*E^2 + 0.02736*E + 2.9159
    return 15 * kg_prime * (1 + b)  # chain rule through E = ergo*(1+b)


def _solve_once(c, cb, n, item_ids, weapon_id, item_to_valid_slots, prices):
    constraints = cb.build()
    bounds = Bounds(0, 1)
    integrality = np.ones(n)

    res = milp(
        c,
        constraints=constraints,
        bounds=bounds,
        integrality=integrality,
        options={"time_limit": SOLVE_TIME_LIMIT_SECONDS},
    )
    if not res.success:
        return None

    selected_ids = [item_ids[i] for i in range(n) if res.x[i] > 0.5]
    selected_set = set(selected_ids)
    slot_pairs = _order_pairs_parent_first(selected_ids, item_to_valid_slots, weapon_id, selected_set)

    return {
        "status": "optimal",
        "selected_items": selected_ids,
        "slot_pairs": slot_pairs,
        "total_price_rub": sum(prices[i]["price_rub"] for i in selected_ids),
    }


def build_and_solve(weapon, mods: dict, compat_map, candidate_ids: list, prices: dict, params):
    try:
        item_ids, idx, cb, item_to_valid_slots, base_ergo, base_weight, base_recoil_v = _build_constraints(
            weapon, mods, compat_map, candidate_ids, prices, params
        )
    except _Infeasible as exc:
        return {"status": "infeasible", "reason": exc.reason, "selected_items": [], "slot_pairs": []}

    n = len(item_ids)

    if not params.use_evo_ergo:
        c = _weighted_objective(item_ids, idx, mods, prices, params, base_recoil_v)
        result = _solve_once(c, cb, n, item_ids, weapon.id, item_to_valid_slots, prices)
        if result is None:
            return {
                "status": "infeasible",
                "reason": "No feasible build satisfies these constraints.",
                "selected_items": [],
                "slot_pairs": [],
            }
        return result

    # EvoErgo mode: sweep tangent anchors, keep whichever candidate has the
    # best *true* (quadratic) EED - the tangent-line objectives are only an
    # approximation used to generate candidates the MILP can actually solve.
    anchors = (
        [params.evo_ergo_k]
        if params.evo_ergo_k is not None
        else [_evo_ergo_k_for_anchor(a, params.equip_ergo_modifier) for a in EVO_ERGO_ERGO_ANCHORS]
    )

    best = None
    best_eed = None
    for k in anchors:
        c = _evo_ergo_objective(k, item_ids, idx, mods, prices, params, base_recoil_v)
        candidate = _solve_once(c, cb, n, item_ids, weapon.id, item_to_valid_slots, prices)
        if candidate is None:
            continue
        eed = _compute_stats(
            weapon, candidate["selected_items"], mods, params.strength_level, params.equip_ergo_modifier
        )["evo_ergo_delta"]
        if best_eed is None or eed > best_eed:
            best, best_eed = candidate, eed

    if best is None:
        return {
            "status": "infeasible",
            "reason": "No feasible build satisfies these constraints.",
            "selected_items": [],
            "slot_pairs": [],
        }
    return best
