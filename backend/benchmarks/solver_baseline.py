"""Repeatable cold-cache baselines for the Combo Calculator and optimizer."""

import argparse
import asyncio
from collections import deque
import json
from pathlib import Path
import statistics
import sys
import time

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal  # noqa: E402
from main import _clear_solver_caches, combo_full  # noqa: E402
from optimizer.compat_map import build_compatibility_map  # noqa: E402
from optimizer.solver import OptimizeParams, optimize_weapon  # noqa: E402

CASES = (
    {
        "name": "m4a1_stress",
        "weapon_id": "5447a9cd4bdc2dbd208b4567",
        "combo_slot_id": "55d5a3074bdc2d61338b4574",  # Stock: branching children, but bounded runtime
        "min_reachable": 500,
    },
    {
        "name": "ppsh41_fast_path",
        "weapon_id": "5ea03f7400685063ec28bfa8",
        "combo_slot_id": "5ea03f7400685063ec28bfad",  # Magazine: shallow, low branching
        "max_reachable": 10,
    },
)


def _graph_metrics(cmap, weapon_id):
    placements = {}
    for slot_id, item_ids in cmap.slot_items.items():
        for item_id in item_ids:
            placements.setdefault(item_id, set()).add(slot_id)

    depths = {weapon_id: 0}
    queue = deque([weapon_id])
    while queue:
        owner_id = queue.popleft()
        for slot_id in cmap.item_to_slots.get(owner_id, []):
            for item_id in cmap.slot_items.get(slot_id, []):
                if item_id not in depths:
                    depths[item_id] = depths[owner_id] + 1
                    queue.append(item_id)

    return {
        "reachable_candidate_count": len(cmap.reachable_ids),
        "compatibility_edge_count": sum(len(items) for items in cmap.slot_items.values()),
        "multi_parent_slot_candidate_count": sum(len(slot_ids) > 1 for slot_ids in placements.values()),
        "max_depth": max(depths.values(), default=0),
    }


async def _consume_combo(response):
    buffer = ""
    async for chunk in response.body_iterator:
        buffer += chunk.decode() if isinstance(chunk, bytes) else chunk
    for part in buffer.split("\n\n"):
        if not part.startswith("data: "):
            continue
        event = json.loads(part[6:])
        if event.get("type") == "result":
            return event["data"]
    raise RuntimeError("combo-full stream ended without a result")


def _run_combo(case):
    _clear_solver_caches()
    db = SessionLocal()
    try:
        response = combo_full(
            case["weapon_id"],
            [],
            case["combo_slot_id"],
            "en",
            10,
            0.0,
            [],
            [],
            db,
        )
    finally:
        db.close()
    if isinstance(response, dict):
        return response
    return asyncio.run(_consume_combo(response))


def _run_optimizer(case):
    _clear_solver_caches()
    with SessionLocal() as db:
        return optimize_weapon(db, case["weapon_id"], OptimizeParams())


def _summarize(samples):
    timings = [sample["wall_ms"] for sample in samples]
    return {
        "wall_ms": {
            "min": round(min(timings), 3),
            "median": round(statistics.median(timings), 3),
            "max": round(max(timings), 3),
        },
        "last_result": samples[-1]["result"],
    }


def _sample(fn, case, runs):
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        result = fn(case)
        samples.append(
            {
                "wall_ms": (time.perf_counter() - started) * 1000,
                "result": {
                    "status": result.get("status"),
                    "truncated": result.get("truncated"),
                    "truncation_reasons": result.get("truncation_reasons"),
                    "metrics": result.get("metrics", {}),
                },
            }
        )
    return _summarize(samples)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3, help="Cold-cache samples per solver and case")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    report = {"runs": args.runs, "cases": {}}
    for case in CASES:
        with SessionLocal() as db:
            graph = _graph_metrics(build_compatibility_map(db, case["weapon_id"]), case["weapon_id"])
        if graph["reachable_candidate_count"] < case.get("min_reachable", 0):
            raise RuntimeError(f"{case['name']} no longer qualifies as the stress case: {graph}")
        if graph["reachable_candidate_count"] > case.get("max_reachable", float("inf")):
            raise RuntimeError(f"{case['name']} no longer qualifies as the fast-path case: {graph}")

        report["cases"][case["name"]] = {
            "weapon_id": case["weapon_id"],
            "combo_slot_id": case["combo_slot_id"],
            "graph": graph,
            "combo": _sample(_run_combo, case, args.runs),
            "optimizer": _sample(_run_optimizer, case, args.runs),
        }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
