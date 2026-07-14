import unittest

import pandas as pd

from backtest import forward, stats


class BacktestOutcomeTests(unittest.TestCase):
    def test_rebound_does_not_erase_forward_maximum_drawdown(self):
        prices = [100, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 145, 150]
        panel = forward(pd.DataFrame({"spx": prices}))

        result = stats(panel, "synthetic")

        self.assertEqual(result["outcomes"]["1m"]["n"], 12)
        self.assertEqual(result["outcomes"]["12m"]["mean_pct"], 50.0)
        self.assertEqual(result["worst_max_drawdown_12m_pct"], -50.0)


if __name__ == "__main__":
    unittest.main()
