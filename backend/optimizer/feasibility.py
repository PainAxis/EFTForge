"""Cheap pre-checks that catch the most common infeasible requests with a
human-readable reason before ever building the MILP. Not exhaustive - the
solver's own infeasibility result is still the authority for anything not
checked here (e.g. a required-slot chain that can't be satisfied within
budget), this just gives better error messages for the common cases.
"""


def check_feasibility(weapon, mods: dict, candidate_ids: list, params) -> list | None:
    """Each entry is {"text": <english, for logs>, "key": <i18n key>, "params":
    <values to interpolate into that key's translation>}, so the frontend can
    translate every reason instead of showing this function's English text.
    """
    reasons = []
    available = set(candidate_ids)

    if params.include_items:
        for req_id in params.include_items:
            if req_id not in available:
                reasons.append(
                    {
                        "text": f"Required item {req_id} is not available under the current filters",
                        "key": "optimizer.reason.requiredItemUnavailable",
                        "params": {"itemId": req_id},
                    }
                )

    if params.min_mag_capacity:
        if not any((mods[i].magazine_capacity or 0) >= params.min_mag_capacity for i in available):
            reasons.append(
                {
                    "text": f"No available magazine with capacity >= {params.min_mag_capacity} rounds",
                    "key": "optimizer.reason.minMagCapacityUnavailable",
                    "params": {"capacity": params.min_mag_capacity},
                }
            )

    if params.min_sighting_range:
        base_sight = weapon.sighting_range or 0
        if base_sight < params.min_sighting_range:
            if not any((mods[i].sighting_range or 0) >= params.min_sighting_range for i in available):
                reasons.append(
                    {
                        "text": f"No available sight with sighting range >= {params.min_sighting_range}m",
                        "key": "optimizer.reason.minSightingRangeUnavailable",
                        "params": {"range": params.min_sighting_range},
                    }
                )

    if params.max_weight is not None:
        base_weight = weapon.weight or 0
        if base_weight > params.max_weight:
            reasons.append(
                {
                    "text": (
                        f"Weapon's base weight ({base_weight:.2f}kg) already exceeds "
                        f"the limit ({params.max_weight}kg)"
                    ),
                    "key": "optimizer.reason.baseWeightExceedsLimit",
                    "params": {"baseWeight": f"{base_weight:.2f}", "maxWeight": params.max_weight},
                }
            )

    return reasons or None
