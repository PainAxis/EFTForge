"""Tests for Gunsmith mode (optimizer/gunsmith.py) - reuses the same MILP
solver as Optimize mode with a task's constraints/required items/categories
injected. Runs against the real synced dev DB, same as test_optimizer_solver.py.
Skipped automatically if that DB hasn't been synced yet - CI never syncs one,
and (deliberately) never sets IP_HASH_SECRET/ADMIN_API_KEY either, so
`database` must not be imported at module level: config.py raises at import
time when those are missing, which would crash collection before pytest ever
gets to evaluate the skip marker below.

Run with:  cd backend && python -m pytest tests/test_gunsmith.py
"""

import os

import pytest

_HAS_DB = os.path.exists(os.path.join(os.path.dirname(__file__), "..", "tarkov.db"))

pytestmark = pytest.mark.skipif(
    not _HAS_DB,
    reason="requires a synced tarkov.db - run sync_tarkov_dev.py first",
)

if _HAS_DB:
    from database import SessionLocal
    from optimizer.gunsmith import get_gunsmith_tasks, solve_gunsmith_task


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class TestGetGunsmithTasks:
    def test_returns_tasks_with_resolved_names(self, db):
        tasks = get_gunsmith_tasks(db)
        assert len(tasks) > 20  # the vendored file has ~29 entries; a wipe could drop a couple
        for t in tasks:
            assert t["weapon_name"], f"{t['task_name']} has no resolved weapon name"
            assert isinstance(t["constraints"], dict)


class TestSolveGunsmithTask:
    def test_every_task_solves_or_reports_a_specific_reason(self, db):
        """Every vendored task must resolve to a real weapon and either solve
        or fail with an actual reason - never the generic "error" status,
        which would mean something is broken rather than genuinely infeasible
        (an unpriced required item, an unmeetable constraint combination)."""
        tasks = get_gunsmith_tasks(db)
        for t in tasks:
            result = solve_gunsmith_task(db, t["task_name"])
            assert result["status"] in (
                "optimal",
                "infeasible",
            ), f"{t['task_name']} returned status={result['status']}: {result.get('reason')}"
            if result["status"] == "infeasible":
                assert result.get("reason")

    def test_first_task_includes_its_required_item(self, db):
        tasks = get_gunsmith_tasks(db)
        task = tasks[0]
        result = solve_gunsmith_task(db, task["task_name"])
        assert result["status"] == "optimal"
        for req_id in task["required_item_ids"]:
            assert req_id in result["selected_items"]

    def test_category_group_requirement_is_enforced(self, db):
        """Find a task using required_category_group_ids and confirm the
        solved build actually contains an item from at least one such group -
        not just that the solve succeeded."""
        from models_items import Item

        tasks = get_gunsmith_tasks(db)
        task = next((t for t in tasks if t["required_category_group_ids"]), None)
        assert task is not None, "expected at least one vendored task to use category groups"

        result = solve_gunsmith_task(db, task["task_name"])
        assert result["status"] == "optimal"

        selected = db.query(Item).filter(Item.id.in_(result["selected_items"])).all()
        for group in task["required_category_group_ids"]:
            group_set = set(group)
            matched = any(group_set & set((i.category_ids or "").split(",")) for i in selected)
            assert matched, f"{task['task_name']}: no selected item matches category group {group}"

    def test_unknown_task_returns_error(self, db):
        result = solve_gunsmith_task(db, "not a real task")
        assert result["status"] == "error"
