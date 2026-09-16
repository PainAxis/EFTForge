"""
Tests for the EvoErgo / EED / Arm Stamina calculation formulas.

These formulas are duplicated in frontend/modules/calculations.js (calcEED,
calcArmStamina) for instant client-side feedback; backend/stats.py::_calc_evo_ergo_delta
is the canonical copy. This file imports that real function rather than
reimplementing the formula a second time, and cross-checks it against
tests/data/stat_formula_golden.json - the same vectors frontend/tests/calculations.test.js
checks the JS copy against, so a drift between the two shows up as a test failure on
whichever side changed instead of silently shipping a client/server stat mismatch.

Run with:  cd backend && python -m pytest tests/
"""

import json
import math
import os
from pathlib import Path

os.environ.setdefault("IP_HASH_SECRET", "calculations-test-secret")
os.environ.setdefault("ADMIN_API_KEY", "calculations-test-admin")

from stats import KG_A, KG_B, KG_C, _calc_evo_ergo_delta

GOLDEN_PATH = Path(__file__).parent / "data" / "stat_formula_golden.json"
GOLDEN_CASES = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]


def _calc_eed(total_ergo: float, total_weight: float, equip_ergo_modifier: float = 0.0) -> float:
    eed, _overswing, _arm_stamina = _calc_evo_ergo_delta(total_ergo, total_weight, 10, equip_ergo_modifier)
    return eed


def _calc_arm_stamina(
    total_weight: float, total_ergo: float, strength_level: int = 10, equip_ergo_modifier: float = 0.0
) -> float:
    _eed, _overswing, arm_stamina = _calc_evo_ergo_delta(total_ergo, total_weight, strength_level, equip_ergo_modifier)
    return arm_stamina


# ---------------------------------------------------------------------------
# Golden-vector cross-check: same expected values frontend/tests/calculations.test.js
# checks calcEED/calcArmStamina against.
# ---------------------------------------------------------------------------


class TestGoldenVectors:
    def test_backend_matches_golden_vectors(self):
        for case in GOLDEN_CASES:
            eed, _overswing, arm_stamina = _calc_evo_ergo_delta(
                case["total_ergo"], case["total_weight"], case["strength_level"], case["equip_ergo_modifier"]
            )
            assert round(eed, 2) == case["expected_eed"], f"EED mismatch for {case}"
            assert round(arm_stamina, 2) == case["expected_arm_stamina"], f"arm_stamina mismatch for {case}"


# ---------------------------------------------------------------------------
# EED tests
# ---------------------------------------------------------------------------


class TestCalcEED:
    def test_zero_weight_zero_ergo(self):
        # With ergo=0, E=0, KG=2.9159 -> evo_weight = 0 - 2.9159 = -2.9159
        # EED = -15 * -2.9159 = 43.74
        eed = _calc_eed(0, 0)
        assert round(eed, 2) == 43.74

    def test_positive_eed_means_no_overswing(self):
        # A build well below threshold should have positive EED
        eed = _calc_eed(total_ergo=60, total_weight=3.0)
        assert eed > 0

    def test_negative_eed_means_overswing(self):
        # Very heavy build with low ergo
        eed = _calc_eed(total_ergo=10, total_weight=15.0)
        assert eed < 0

    def test_overswing_boundary(self):
        # At exactly KG = total_weight, EED should be 0
        total_ergo = 60.0
        b = 0.0
        E = total_ergo * (1 + b)
        kg = KG_A * (E**2) + KG_B * E + KG_C
        eed = _calc_eed(total_ergo, kg)  # total_weight == KG -> evo_weight = 0
        assert abs(eed) < 0.001

    def test_equip_ergo_modifier_reduces_effective_ergo(self):
        # A negative equip_ergo_modifier (equipment penalty) lowers effective ergo
        # and thus lowers the KG threshold, making EED smaller (worse)
        eed_no_penalty = _calc_eed(total_ergo=60, total_weight=5.0, equip_ergo_modifier=0.0)
        eed_with_penalty = _calc_eed(total_ergo=60, total_weight=5.0, equip_ergo_modifier=-0.20)
        assert eed_with_penalty < eed_no_penalty


# ---------------------------------------------------------------------------
# Arm stamina tests
# ---------------------------------------------------------------------------


class TestCalcArmStamina:
    def test_heavier_build_decreases_stamina(self):
        light = _calc_arm_stamina(3.0, 50)
        heavy = _calc_arm_stamina(7.0, 50)
        assert heavy < light

    def test_higher_ergo_increases_stamina(self):
        low_ergo = _calc_arm_stamina(4.0, 30)
        high_ergo = _calc_arm_stamina(4.0, 70)
        assert high_ergo > low_ergo

    def test_result_is_finite(self):
        stamina = _calc_arm_stamina(4.0, 50)
        assert math.isfinite(stamina)

    def test_higher_strength_increases_stamina(self):
        low_strength = _calc_arm_stamina(4.0, 50, strength_level=0)
        high_strength = _calc_arm_stamina(4.0, 50, strength_level=40)
        assert high_strength > low_strength


# ---------------------------------------------------------------------------
# Recoil modifier application
# ---------------------------------------------------------------------------


class TestRecoilModifier:
    def test_positive_modifier_increases_recoil(self):
        base_v = 100
        modifier = 0.10  # +10 %
        result = round(base_v * (1 + modifier))
        assert result == 110

    def test_negative_modifier_decreases_recoil(self):
        base_v = 100
        modifier = -0.15
        result = round(base_v * (1 + modifier))
        assert result == 85

    def test_zero_modifier_unchanged(self):
        base_v = 137
        result = round(base_v * (1 + 0.0))
        assert result == 137
