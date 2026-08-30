"""MVP MILP formulation: weapon + mods only (no presets-as-base, no
Found-in-Raid fallback pricing, no multi-slot placement variables yet - see
optimizer/solver.py's module docstring for what's deferred and why).

Solved with scipy.optimize.milp (HiGHS backend) - the same solver engine the
original optimizer's WASM frontend already uses.
"""

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds

TIEBREAK = 0.01

# Reference scales so the 0-1 priority sliders behave consistently regardless
# of a weapon's absolute ergo/recoil/price magnitudes.
ERGO_SCALE = 100.0
PRICE_SCALE_FALLBACK = 300_000.0


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
    from collections import deque

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


def build_and_solve(weapon, mods: dict, compat_map, candidate_ids: list, prices: dict, params):
    item_ids = list(candidate_ids)
    idx = {item_id: i for i, item_id in enumerate(item_ids)}
    n = len(item_ids)
    weapon_id = weapon.id

    if n == 0:
        return {"status": "infeasible", "reason": "No attachments are available under the current filters.",
                "selected_items": [], "slot_pairs": []}

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
    # owners) rather than tracked with per-slot placement variables - this is
    # the MVP's one known modeling gap: a multi-parent item can, in rare
    # cases, get counted toward two different required-slot constraints at
    # once even though it can only physically occupy one. Most attachments
    # only have a single valid parent, so this doesn't affect the common case.
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

    if params.max_price is not None:
        cb.le({idx[i]: prices[i]["price_rub"] for i in item_ids}, params.max_price)

    if params.min_ergonomics is not None:
        cb.ge({idx[i]: (mods[i].ergonomics_modifier or 0) for i in item_ids}, params.min_ergonomics - base_ergo)

    if params.max_recoil_v is not None and base_recoil_v is not None:
        cb.le(
            {idx[i]: base_recoil_v * (mods[i].recoil_modifier or 0) for i in item_ids},
            params.max_recoil_v - base_recoil_v,
        )

    if params.max_weight is not None:
        cb.le({idx[i]: (mods[i].weight or 0) for i in item_ids}, params.max_weight - base_weight)

    if params.min_mag_capacity:
        mags = [i for i in item_ids if (mods[i].magazine_capacity or 0) >= params.min_mag_capacity]
        if not mags:
            return {"status": "infeasible",
                    "reason": f"No available magazine with capacity >= {params.min_mag_capacity} rounds.",
                    "selected_items": [], "slot_pairs": []}
        cb.ge({idx[i]: 1 for i in mags}, 1)

    if params.min_sighting_range:
        base_sight = weapon.sighting_range or 0
        if base_sight < params.min_sighting_range:
            sights = [i for i in item_ids if (mods[i].sighting_range or 0) >= params.min_sighting_range]
            if not sights:
                return {"status": "infeasible",
                        "reason": f"No available sight with sighting range >= {params.min_sighting_range}m.",
                        "selected_items": [], "slot_pairs": []}
            cb.ge({idx[i]: 1 for i in sights}, 1)

    if params.include_items:
        for req_id in params.include_items:
            if req_id not in idx:
                return {"status": "infeasible",
                        "reason": f"Required item {req_id} is not available under the current filters.",
                        "selected_items": [], "slot_pairs": []}
            cb.eq({idx[req_id]: 1}, 1)

    # 6. Objective - minimize a weighted blend of -ergo, +recoil, +price.
    ergo_w = max(params.ergo_weight, TIEBREAK)
    recoil_w = max(params.recoil_weight, TIEBREAK)
    price_w = max(params.price_weight, TIEBREAK)
    price_scale = params.max_price or PRICE_SCALE_FALLBACK
    recoil_scale = abs(base_recoil_v) if base_recoil_v else 1.0

    c = np.zeros(n)
    for item_id in item_ids:
        i = idx[item_id]
        ergo_term = -(ergo_w / ERGO_SCALE) * (mods[item_id].ergonomics_modifier or 0)
        recoil_term = (recoil_w / recoil_scale) * (base_recoil_v or 0) * (mods[item_id].recoil_modifier or 0)
        price_term = (price_w / price_scale) * prices[item_id]["price_rub"]
        c[i] = ergo_term + recoil_term + price_term

    constraints = cb.build()
    bounds = Bounds(0, 1)
    integrality = np.ones(n)

    res = milp(c, constraints=constraints, bounds=bounds, integrality=integrality)

    if not res.success:
        return {"status": "infeasible", "reason": "No feasible build satisfies these constraints.",
                "selected_items": [], "slot_pairs": []}

    selected_ids = [item_ids[i] for i in range(n) if res.x[i] > 0.5]
    selected_set = set(selected_ids)
    slot_pairs = _order_pairs_parent_first(selected_ids, item_to_valid_slots, weapon_id, selected_set)

    return {
        "status": "optimal",
        "selected_items": selected_ids,
        "slot_pairs": slot_pairs,
        "total_price_rub": sum(prices[i]["price_rub"] for i in selected_ids),
    }
