"""Regression tests for MILP termination reporting.

These tests use small fake HiGHS results, so they run without tarkov.db and
pin the distinction between infeasible, timed out, and feasible-at-time-limit.
"""

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from optimizer.milp import ConstraintBuilder, _solve_once


def _result(status, x=None, success=False):
    return SimpleNamespace(
        status=status,
        success=success,
        x=x,
        message={0: "Optimal", 1: "Time limit reached", 2: "Infeasible"}.get(status, "Solver error"),
        mip_node_count=3,
        mip_dual_bound=1.25,
        mip_gap=0.1,
    )


def _run(fake_result):
    with patch("optimizer.milp.milp", return_value=fake_result):
        return _solve_once(
            np.array([1.0]),
            ConstraintBuilder(1),
            1,
            ["mod"],
            "weapon",
            {"mod": [("slot", "weapon")]},
            {"mod": {"price_rub": 100}},
        )


def test_infeasible_is_reported_separately():
    result = _run(_result(2))

    assert result["status"] == "infeasible"
    assert result["selected_items"] == []
    assert result["termination"]["solver_status_code"] == 2


def test_timeout_without_incumbent_is_not_infeasible():
    result = _run(_result(1))

    assert result["status"] == "timeout"
    assert result["selected_items"] == []
    assert "time limit" in result["reason"].lower()


def test_timeout_with_fractional_vector_is_not_treated_as_an_incumbent():
    result = _run(_result(1, x=np.array([0.5])))

    assert result["status"] == "timeout"
    assert result["selected_items"] == []


def test_timeout_with_incumbent_preserves_feasible_build():
    result = _run(_result(1, x=np.array([1.0])))

    assert result["status"] == "feasible"
    assert result["selected_items"] == ["mod"]
    assert result["slot_pairs"] == [["slot", "mod"]]
    assert result["total_price_rub"] == 100


def test_optimal_result_remains_optimal():
    result = _run(_result(0, x=np.array([1.0]), success=True))

    assert result["status"] == "optimal"
    assert result["reason"] is None
