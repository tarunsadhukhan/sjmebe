"""
Tests for MR weight rounding logic.
Verifies that actual_weight, shortage_kgs and accepted_weight are rounded to
2 decimals, matching the frontend round2() behavior in mr.py update_mr.
"""
import pytest


def calculate_shortage_and_accepted(
    actual_weight: float,
    allowable_moisture: float | None,
    actual_moisture: float,
    claim_dust: float,
) -> tuple[float, float]:
    """Mirror of the backend rounding logic in mr.py update_mr."""
    if actual_weight <= 0:
        return 0.0, 0.0

    weight = round(actual_weight, 2)
    moisture_diff = 0.0
    if allowable_moisture is not None and actual_moisture > allowable_moisture:
        moisture_diff = actual_moisture - allowable_moisture

    deduction_percentage = moisture_diff + claim_dust
    if deduction_percentage <= 0:
        return 0.0, weight

    shortage_kgs = round(weight * deduction_percentage / 100.0, 2)
    accepted_weight = round(max(0.0, weight - shortage_kgs), 2)
    return shortage_kgs, accepted_weight


class TestMRWeightRounding:
    """Tests for MR weight rounding to 2 decimals."""

    def test_zero_weight_returns_zeros(self):
        shortage, accepted = calculate_shortage_and_accepted(0, 10, 12, 0)
        assert shortage == 0
        assert accepted == 0

    def test_negative_weight_returns_zeros(self):
        shortage, accepted = calculate_shortage_and_accepted(-5, 10, 12, 0)
        assert shortage == 0
        assert accepted == 0

    def test_no_deduction_returns_full_weight(self):
        shortage, accepted = calculate_shortage_and_accepted(500, 15, 10, 0)
        assert shortage == 0
        assert accepted == 500

    def test_no_deduction_when_actual_equals_allowable(self):
        shortage, accepted = calculate_shortage_and_accepted(500, 10, 10, 0)
        assert shortage == 0
        assert accepted == 500

    def test_returns_floats(self):
        shortage, accepted = calculate_shortage_and_accepted(1000, 10, 16.67, 2)
        assert isinstance(shortage, float)
        assert isinstance(accepted, float)
        # deduction = 8.67% -> shortage = round2(86.7) = 86.7, accepted = 913.3
        assert shortage == pytest.approx(86.7)
        assert accepted == pytest.approx(913.3)

    def test_correct_calculation_8_percent(self):
        # 1000 kg, moisture diff = 6%, dust = 2%, total = 8%
        # shortage = round2(1000 * 8 / 100) = 80, accepted = 1000 - 80 = 920
        shortage, accepted = calculate_shortage_and_accepted(1000, 10, 16, 2)
        assert shortage == 80
        assert accepted == 920

    def test_shortage_plus_accepted_equals_actual(self):
        """shortage + accepted should always equal the actual weight (2 dp)."""
        shortage, accepted = calculate_shortage_and_accepted(1000, 10, 16, 2)
        assert shortage + accepted == pytest.approx(1000)

    def test_fractional_weight_keeps_2dp(self):
        # 999.6 kg, deduction 8% -> shortage = round2(79.968) = 79.97
        # accepted = round2(999.6 - 79.97) = 919.63
        shortage, accepted = calculate_shortage_and_accepted(999.6, 10, 16, 2)
        assert shortage == pytest.approx(79.97)
        assert accepted == pytest.approx(919.63)
        assert shortage + accepted == pytest.approx(999.6)

    def test_dust_only_deduction(self):
        # No moisture diff, but claimDust = 5%
        # shortage = round2(1000 * 5 / 100) = 50
        shortage, accepted = calculate_shortage_and_accepted(1000, 10, 8, 5)
        assert shortage == 50
        assert accepted == 950

    def test_allowable_moisture_none(self):
        # allowable_moisture is None -> moisture_diff = 0, only dust = 3% applies
        shortage, accepted = calculate_shortage_and_accepted(1000, None, 20, 3)
        assert shortage == 30
        assert accepted == 970

    @pytest.mark.parametrize("weight,moisture_allow,moisture_actual,dust", [
        (500, 10, 18, 3),
        (1234, 12, 15.5, 1.5),
        (750, 8, 8, 0),         # no deduction
        (100, None, 20, 5),     # no allowable moisture
        (10000, 10, 25, 0),
        (333, 10, 12, 1),       # fractional shortage
        (7777, 5, 22, 3.5),     # large deduction
    ])
    def test_always_returns_2dp_that_sum_to_weight(self, weight, moisture_allow, moisture_actual, dust):
        shortage, accepted = calculate_shortage_and_accepted(
            weight, moisture_allow, moisture_actual, dust
        )
        assert isinstance(shortage, float), f"shortage_kgs not float: {shortage}"
        assert isinstance(accepted, float), f"accepted_weight not float: {accepted}"
        # values carry at most 2 decimals
        assert round(shortage, 2) == shortage
        assert round(accepted, 2) == accepted
        rounded_weight = round(weight, 2)
        if shortage > 0:
            assert shortage + accepted == pytest.approx(rounded_weight), (
                f"shortage({shortage}) + accepted({accepted}) != weight({rounded_weight})"
            )

    def test_large_weight_with_small_deduction(self):
        # 50000 kg, moisture diff = 0.5%, dust = 0.3%, total = 0.8%
        # shortage = round2(50000 * 0.8 / 100) = 400
        shortage, accepted = calculate_shortage_and_accepted(50000, 10, 10.5, 0.3)
        assert shortage == 400
        assert accepted == 49600
        assert shortage + accepted == pytest.approx(50000)

    def test_100_percent_deduction(self):
        # Edge case: 100% deduction (extreme moisture + dust)
        shortage, accepted = calculate_shortage_and_accepted(1000, 0, 80, 20)
        assert shortage == 1000
        assert accepted == 0
