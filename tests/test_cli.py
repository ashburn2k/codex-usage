"""Tests for cli.py - Codex pricing fallback and formatting."""

import unittest
from cli import PRICING, calc_cost, fmt, fmt_cost, fmt_cost_for_model, get_pricing


class TestGetPricing(unittest.TestCase):
    def test_pricing_table_empty_by_default(self):
        self.assertEqual(PRICING, {})

    def test_codex_provider_returns_none(self):
        self.assertIsNone(get_pricing("codex/custom"))
        self.assertIsNone(get_pricing("codex/cborg"))

    def test_unknown_model_returns_none(self):
        self.assertIsNone(get_pricing("gpt-5"))
        self.assertIsNone(get_pricing("some-unknown-model"))

    def test_none_model_returns_none(self):
        self.assertIsNone(get_pricing(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(get_pricing(""))


class TestCalcCost(unittest.TestCase):
    def test_codex_costs_zero_without_public_pricing(self):
        cost = calc_cost("codex/custom", 1_000_000, 500_000, 100_000, 0)
        self.assertEqual(cost, 0.0)

    def test_unknown_model_costs_zero(self):
        cost = calc_cost("gpt-5", 1_000_000, 500_000, 100_000, 50_000)
        self.assertEqual(cost, 0.0)

    def test_zero_tokens(self):
        self.assertEqual(calc_cost("codex/custom", 0, 0, 0, 0), 0.0)


class TestFmt(unittest.TestCase):
    def test_millions(self):
        self.assertEqual(fmt(1_500_000), "1.50M")
        self.assertEqual(fmt(1_000_000), "1.00M")

    def test_thousands(self):
        self.assertEqual(fmt(1_500), "1.5K")
        self.assertEqual(fmt(1_000), "1.0K")

    def test_small_numbers(self):
        self.assertEqual(fmt(999), "999")
        self.assertEqual(fmt(0), "0")


class TestFmtCost(unittest.TestCase):
    def test_formatting(self):
        self.assertEqual(fmt_cost(3.0), "$3.0000")
        self.assertEqual(fmt_cost(0.0001), "$0.0001")
        self.assertEqual(fmt_cost(0), "$0.0000")

    def test_codex_cost_display_is_na(self):
        self.assertEqual(fmt_cost_for_model("codex/custom", 0), "n/a")


if __name__ == "__main__":
    unittest.main()
