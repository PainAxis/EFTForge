"""Gunsmith mode: solves for a build that satisfies a specific Gunsmith
questline task's requirements, reusing the same MILP solver as Optimize mode
with the task's constraints/required items/categories injected - no separate
solver logic needed.

Task data (backend/data/gunsmith_tasks.json) is vendored as-is from the
reference project's own hand-curated file (frontend/public/tasks.json at
https://github.com/AhaiMk01/tarkov-weapon-optimizer). It's static Tarkov quest
content, not something to sync live - diff it against that file by hand
whenever a wipe changes the Gunsmith questline.

Known gap: a required item that has no direct slot on the weapon and needs an
intermediate mount to be reachable (the reference project's
requiredItemDeps.ts expands these) isn't handled here - that task will solve
as infeasible with a "not available under the current filters" reason instead
of silently finding the mount for you. Not implemented, not faked.
"""

import json
import os

from models_items import Item
from optimizer.solver import optimize_weapon, OptimizeParams

_TASKS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "gunsmith_tasks.json")

_cache = None


def _load_raw_tasks():
    global _cache
    if _cache is None:
        with open(_TASKS_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def get_gunsmith_tasks(db, lang="en"):
    """Vendored task list joined against live item data (names, weapon image)
    so the frontend never needs a second data source for display. Tasks whose
    weapon_id no longer resolves (a wipe changed the Gunsmith questline)
    are silently skipped rather than erroring the whole list.
    """
    raw_tasks = _load_raw_tasks()
    weapon_ids = {t["weapon_id"] for t in raw_tasks}
    weapons = {w.id: w for w in db.query(Item).filter(Item.id.in_(weapon_ids)).all()} if weapon_ids else {}

    all_item_ids = set()
    for t in raw_tasks:
        all_item_ids.update(t.get("required_item_ids") or [])
    required_items = {i.id: i for i in db.query(Item).filter(Item.id.in_(all_item_ids)).all()} if all_item_ids else {}

    name_field = "name_zh" if lang == "zh" else "name"
    out = []
    for t in raw_tasks:
        weapon = weapons.get(t["weapon_id"])
        if not weapon:
            continue
        required_names = []
        for iid in t.get("required_item_ids") or []:
            item = required_items.get(iid)
            if item:
                required_names.append(getattr(item, name_field, None) or item.name)
        out.append(
            {
                "task_name": t["task_name"],
                "weapon_id": t["weapon_id"],
                "weapon_name": getattr(weapon, name_field, None) or weapon.name,
                "weapon_image": weapon.image_512_link or weapon.icon_link,
                "constraints": t.get("constraints") or {},
                "required_item_ids": t.get("required_item_ids") or [],
                "required_item_names": required_names,
                "required_category_group_ids": t.get("required_category_group_ids") or [],
            }
        )
    return out


def solve_gunsmith_task(
    db,
    task_name,
    trader_levels=None,
    flea_available=True,
    player_level=None,
    strength_level=10,
    equip_ergo_modifier=0.0,
):
    raw_tasks = _load_raw_tasks()
    task = next((t for t in raw_tasks if t["task_name"] == task_name), None)
    if not task:
        return {
            "status": "error",
            "reason": f"Unknown Gunsmith task: {task_name}",
            "selected_items": [],
            "slot_pairs": [],
        }

    constraints = task.get("constraints") or {}
    params = OptimizeParams(
        min_ergonomics=constraints.get("min_ergonomics"),
        max_recoil_sum=constraints.get("max_recoil_sum"),
        min_mag_capacity=constraints.get("min_mag_capacity"),
        min_sighting_range=constraints.get("min_sighting_range"),
        max_weight=constraints.get("max_weight"),
        include_items=task.get("required_item_ids") or None,
        include_categories=task.get("required_category_group_ids") or None,
        trader_levels=trader_levels,
        flea_available=flea_available,
        player_level=player_level,
        strength_level=strength_level,
        equip_ergo_modifier=equip_ergo_modifier,
        # A Gunsmith task is about satisfying its requirements, not chasing a
        # preference - a mild default lean just resolves ties toward a more
        # generally useful build instead of an arbitrary feasible one.
        ergo_weight=1.0,
        recoil_weight=1.0,
        price_weight=0.3,
    )
    result = optimize_weapon(db, task["weapon_id"], params)
    result["task_name"] = task_name
    return result
