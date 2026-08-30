"""Cheap pre-checks that catch the most common infeasible requests with a
human-readable reason before ever building the MILP. Not exhaustive - the
solver's own infeasibility result is still the authority for anything not
checked here (e.g. a required-slot chain that can't be satisfied within
budget), this just gives better error messages for the common cases.
"""


def check_feasibility(weapon, mods: dict, candidate_ids: list, params) -> list | None:
    reasons = []
    available = set(candidate_ids)

    if params.include_items:
        for req_id in params.include_items:
            if req_id not in available:
                reasons.append(f"Required item {req_id} is not available under the current filters")

    if params.min_mag_capacity:
        if not any((mods[i].magazine_capacity or 0) >= params.min_mag_capacity for i in available):
            reasons.append(f"No available magazine with capacity >= {params.min_mag_capacity} rounds")

    if params.min_sighting_range:
        base_sight = weapon.sighting_range or 0
        if base_sight < params.min_sighting_range:
            if not any((mods[i].sighting_range or 0) >= params.min_sighting_range for i in available):
                reasons.append(f"No available sight with sighting range >= {params.min_sighting_range}m")

    if params.max_weight is not None:
        base_weight = weapon.weight or 0
        if base_weight > params.max_weight:
            reasons.append(
                f"Weapon's base weight ({base_weight:.2f}kg) already exceeds the limit ({params.max_weight}kg)"
            )

    return reasons or None
