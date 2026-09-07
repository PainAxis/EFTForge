"""Opt-in wire format for combo results; solver caches keep the legacy shape."""

import json
from typing import Literal

ComboResponseFormat = Literal["legacy", "items-v1"]


def format_combo_result(result: dict, response_format: ComboResponseFormat) -> dict:
    if response_format == "legacy":
        return result
    if response_format != "items-v1":
        raise ValueError(f"Unknown combo response format: {response_format}")

    items = {}
    combos = []
    for combo in result["combos"]:
        parent = combo["parent_item"]
        children = combo["child_items"]
        items[parent["id"]] = parent
        for child in children:
            items[child["id"]] = child
        # Preserve slot/owner arrays (including repeated IDs) and every stat.
        compact = {key: value for key, value in combo.items() if key not in ("parent_item", "child_items")}
        compact["parent_item_id"] = parent["id"]
        compact["child_item_ids"] = [child["id"] for child in children]
        combos.append(compact)
    return {**result, "response_format": "items-v1", "items": items, "combos": combos}


def combo_result_event(result: dict, response_format: ComboResponseFormat) -> str:
    event = {"type": "result", "data": format_combo_result(result, response_format)}
    separators = (",", ":") if response_format == "items-v1" else None
    return f"data: {json.dumps(event, separators=separators)}\n\n"
