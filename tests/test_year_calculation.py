# clockapp/tests/test_year_calculation.py
"""
Tests for year derivation logic. The server receives `year` as a path parameter int.
These tests verify the numeric contract (HH:MM → year) that JS and Python must agree on.
"""


def derive_year_python(hh: int, mm: int) -> int:
    """Python reference implementation matching JS: parseInt(pad(HH) + pad(MM))."""
    return int(f"{hh:02d}{mm:02d}")


class TestDeriveYear:

    def test_midnight_zero_zero_returns_zero(self):
        assert derive_year_python(0, 0) == 0

    def test_hh_15_mm_50_returns_1550(self):
        assert derive_year_python(15, 50) == 1550

    def test_hh_23_mm_59_returns_2359(self):
        assert derive_year_python(23, 59) == 2359

    def test_hh_9_mm_7_returns_907_with_padding(self):
        # '09' + '07' = '0907' → int = 907
        assert derive_year_python(9, 7) == 907

    def test_hh_0_mm_1_returns_1_not_10(self):
        # '00' + '01' = '0001' → int = 1 (not 10)
        assert derive_year_python(0, 1) == 1
