from __future__ import annotations

import unittest

from nba_sim.franchise.cba import (
    CBA_2026_27,
    CapBand,
    TransactionAction,
    cap_position,
    evaluate_transaction,
)


class CBAEngineTests(unittest.TestCase):
    def test_2026_27_official_system_levels_are_versioned(self) -> None:
        self.assertEqual(CBA_2026_27.salary_cap, 164_961_000)
        self.assertEqual(CBA_2026_27.tax_level, 200_428_000)
        self.assertEqual(CBA_2026_27.first_apron, 209_015_000)
        self.assertEqual(CBA_2026_27.second_apron, 221_686_000)
        self.assertEqual(CBA_2026_27.non_taxpayer_mle, 15_044_000)
        self.assertEqual(CBA_2026_27.taxpayer_mle, 6_064_000)

    def test_cap_position_uses_threshold_boundaries(self) -> None:
        self.assertEqual(cap_position(160_000_000).band, CapBand.BELOW_CAP)
        self.assertEqual(
            cap_position(CBA_2026_27.salary_cap).band,
            CapBand.OVER_CAP,
        )
        self.assertEqual(
            cap_position(CBA_2026_27.first_apron).band,
            CapBand.TAX,
        )
        self.assertEqual(
            cap_position(CBA_2026_27.second_apron + 1).band,
            CapBand.SECOND_APRON,
        )

    def test_non_taxpayer_mle_hard_caps_team_at_first_apron(self) -> None:
        legal = evaluate_transaction(
            team_salary=190_000_000,
            outgoing_salary=0,
            incoming_salary=15_000_000,
            action=TransactionAction.NON_TAXPAYER_MLE,
        )
        self.assertTrue(legal.legal)
        self.assertEqual(legal.hard_cap_triggered, "first_apron")

        illegal = evaluate_transaction(
            team_salary=200_000_000,
            outgoing_salary=0,
            incoming_salary=10_000_000,
            action=TransactionAction.NON_TAXPAYER_MLE,
        )
        self.assertFalse(illegal.legal)
        self.assertTrue(any("hard-caps" in blocker for blocker in illegal.blockers))

    def test_taxpayer_mle_requires_first_apron_and_stays_below_second(self) -> None:
        legal = evaluate_transaction(
            team_salary=205_000_000,
            outgoing_salary=0,
            incoming_salary=6_000_000,
            action=TransactionAction.TAXPAYER_MLE,
        )
        self.assertTrue(legal.legal)
        self.assertEqual(legal.after.band, CapBand.FIRST_APRON)

        below_first = evaluate_transaction(
            team_salary=195_000_000,
            outgoing_salary=0,
            incoming_salary=6_000_000,
            action=TransactionAction.TAXPAYER_MLE,
        )
        self.assertFalse(below_first.legal)
        self.assertTrue(
            any("only when" in blocker for blocker in below_first.blockers)
        )

    def test_second_apron_blocks_aggregation_and_cash(self) -> None:
        aggregate = evaluate_transaction(
            team_salary=220_000_000,
            outgoing_salary=10_000_000,
            incoming_salary=12_000_000,
            action=TransactionAction.AGGREGATED_TRADE,
        )
        self.assertFalse(aggregate.legal)
        self.assertEqual(aggregate.applicable_apron, "second_apron")

        cash = evaluate_transaction(
            team_salary=222_000_000,
            outgoing_salary=0,
            incoming_salary=0,
            action=TransactionAction.SEND_CASH,
        )
        self.assertFalse(cash.legal)

    def test_standard_trade_loses_allowance_above_first_apron(self) -> None:
        result = evaluate_transaction(
            team_salary=210_000_000,
            outgoing_salary=10_000_000,
            incoming_salary=10_000_001,
            action=TransactionAction.STANDARD_TRADE,
        )
        self.assertFalse(result.legal)
        self.assertEqual(result.maximum_incoming_salary, 10_000_000)


if __name__ == "__main__":
    unittest.main()
