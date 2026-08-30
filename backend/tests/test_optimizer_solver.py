"""Tests for the MVP weapon build optimizer (optimizer/solver.py).

These run against the real, already-synced dev DB (backend/tarkov.db) rather
than a fixture DB - the solver's correctness depends on real slot/conflict/
offer data that isn't worth hand-modeling in a fixture, and every other build
feature in this repo (Combo Calculator, etc.) is only ever exercised against
real synced data too. Skipped automatically if that DB hasn't been synced yet
- CI never syncs one, and (deliberately) never sets IP_HASH_SECRET/
ADMIN_API_KEY either, so `database`/`config` must not be imported at module
level: config.py raises at import time when those are missing, which would
crash collection before pytest ever gets to evaluate the skip marker below.

Run with:  cd backend && python -m pytest tests/test_optimizer_solver.py
"""

import os

import pytest

M4A1_ID = "5447a9cd4bdc2dbd208b4567"
AK74N_ID = "5644bd2b4bdc2d3b4c8b4572"

_HAS_DB = os.path.exists(os.path.join(os.path.dirname(__file__), "..", "tarkov.db"))

pytestmark = pytest.mark.skipif(
    not _HAS_DB,
    reason="requires a synced tarkov.db - run sync_tarkov_dev.py first",
)

if _HAS_DB:
    from database import SessionLocal
    from stats import _compute_stats
    from optimizer.solver import optimize_weapon, OptimizeParams


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class TestUnconstrainedOptimize:
    def test_m4a1_solves_optimal(self, db):
        result = optimize_weapon(db, M4A1_ID, OptimizeParams())
        assert result["status"] == "optimal"
        assert isinstance(result["selected_items"], list)
        assert isinstance(result["slot_pairs"], list)
        # every slot pair is a well-formed [slot_id, item_id] pair referencing a selected item
        selected_set = set(result["selected_items"])
        for pair in result["slot_pairs"]:
            assert len(pair) == 2
            assert pair[1] in selected_set

    def test_ak74n_solves_optimal(self, db):
        result = optimize_weapon(db, AK74N_ID, OptimizeParams())
        assert result["status"] == "optimal"

    def test_final_stats_match_compute_stats_directly(self, db):
        """The solver must report exactly what stats._compute_stats() would say
        for the same attachment set - no second, divergent stat formula."""
        result = optimize_weapon(db, M4A1_ID, OptimizeParams())
        assert result["status"] == "optimal"

        from models_items import Item

        weapon = db.query(Item).filter(Item.id == M4A1_ID).first()
        mods = {m.id: m for m in db.query(Item).filter(Item.id.in_(result["selected_items"])).all()}
        expected = _compute_stats(weapon, result["selected_items"], mods)
        assert result["final_stats"] == expected


class TestEvoErgoMode:
    def test_solves_optimal(self, db):
        result = optimize_weapon(db, M4A1_ID, OptimizeParams(use_evo_ergo=True))
        assert result["status"] == "optimal"
        assert "evo_ergo_delta" in result["final_stats"]

    def test_beats_or_matches_plain_weighted_objective_on_eed(self, db):
        """EvoErgo mode explicitly searches for the best ergo/weight tradeoff
        (true EED), so it should never do worse on that specific metric than
        the plain weighted objective, which doesn't optimize for it at all."""
        plain = optimize_weapon(db, M4A1_ID, OptimizeParams())
        evo = optimize_weapon(db, M4A1_ID, OptimizeParams(use_evo_ergo=True))
        assert plain["status"] == "optimal"
        assert evo["status"] == "optimal"
        assert evo["final_stats"]["evo_ergo_delta"] >= plain["final_stats"]["evo_ergo_delta"]

    def test_explicit_k_override_matches_manual_stats_call(self, db):
        """A pinned evo_ergo_k should skip the sweep and solve once - just
        confirms the override path runs and still reports real, consistent stats."""
        result = optimize_weapon(db, M4A1_ID, OptimizeParams(use_evo_ergo=True, evo_ergo_k=0.15))
        assert result["status"] == "optimal"

        from models_items import Item

        weapon = db.query(Item).filter(Item.id == M4A1_ID).first()
        mods = {m.id: m for m in db.query(Item).filter(Item.id.in_(result["selected_items"])).all()}
        expected = _compute_stats(weapon, result["selected_items"], mods)
        assert result["final_stats"] == expected


class TestSlotPairOrdering:
    def test_pairs_are_parent_before_child(self, db):
        """frontend/modules/build-manager.js's loadBuildFromPayload installs
        slot_pairs with a single BFS pass and looks up each pair's parent by
        slot id - a child arriving before its parent gets silently dropped.
        This pins the ordering guarantee _order_pairs_parent_first provides."""
        from optimizer.compat_map import build_compatibility_map

        result = optimize_weapon(db, M4A1_ID, OptimizeParams())
        assert result["status"] == "optimal"
        assert result["slot_pairs"], "expected at least one attachment for this to be a meaningful check"

        compat_map = build_compatibility_map(db, M4A1_ID)
        seen_items = set()
        for slot_id, item_id in result["slot_pairs"]:
            owner = compat_map.slot_owner.get(slot_id)
            if owner != M4A1_ID:
                assert owner in seen_items, f"slot {slot_id}'s owner {owner} appears after its child {item_id}"
            seen_items.add(item_id)


class TestBudgetConstraint:
    def test_lower_budget_never_exceeds_it(self, db):
        unconstrained = optimize_weapon(db, M4A1_ID, OptimizeParams())
        assert unconstrained["status"] == "optimal"
        half_budget = unconstrained["total_price_rub"] // 2

        constrained = optimize_weapon(db, M4A1_ID, OptimizeParams(max_price=half_budget))
        assert constrained["status"] == "optimal"
        assert constrained["total_price_rub"] <= half_budget
        # a tighter budget can never do better than the unconstrained optimum
        assert constrained["total_price_rub"] <= unconstrained["total_price_rub"]


class TestInfeasibleConstraints:
    def test_impossible_min_ergonomics_is_infeasible(self, db):
        result = optimize_weapon(db, M4A1_ID, OptimizeParams(min_ergonomics=100_000))
        assert result["status"] == "infeasible"
        assert result["reason"]

    def test_impossible_mag_capacity_is_infeasible(self, db):
        result = optimize_weapon(db, M4A1_ID, OptimizeParams(min_mag_capacity=100_000))
        assert result["status"] == "infeasible"


class TestIncludeExcludeItems:
    def test_include_items_forces_selection(self, db):
        baseline = optimize_weapon(db, M4A1_ID, OptimizeParams())
        assert baseline["status"] == "optimal"
        assert baseline["selected_items"], "expected M4A1's unconstrained optimum to include at least one mod"
        forced_item = baseline["selected_items"][0]

        result = optimize_weapon(db, M4A1_ID, OptimizeParams(include_items=[forced_item]))
        assert result["status"] == "optimal"
        assert forced_item in result["selected_items"]

    def test_exclude_items_removes_it_from_candidates(self, db):
        baseline = optimize_weapon(db, M4A1_ID, OptimizeParams())
        assert baseline["status"] == "optimal"
        assert baseline["selected_items"]
        excluded_item = baseline["selected_items"][0]

        result = optimize_weapon(db, M4A1_ID, OptimizeParams(exclude_items=[excluded_item]))
        assert result["status"] == "optimal"
        assert excluded_item not in result["selected_items"]
