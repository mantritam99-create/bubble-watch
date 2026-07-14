import json
import tempfile
import unittest
from pathlib import Path

from fetch_risk import load_overrides
from risk_model import model_config, score_all


class CoverageAwareScoringTests(unittest.TestCase):
    def test_missing_fuel_cannot_issue_directional_verdict(self):
        result = score_all({})

        self.assertIsNone(result["fuel"])
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")
        self.assertEqual(result["coverage"]["fuel"]["live"], 0)
        self.assertEqual(result["coverage"]["fuel"]["baseline"], 1)

    def test_baselines_do_not_change_observed_score(self):
        result = score_all({"curve": 36}, sources={"curve": "live"})

        self.assertEqual(result["fuel"], 43)
        self.assertEqual(result["coverage"]["fuel"]["live"], 0.125)
        self.assertEqual(result["coverage"]["fuel"]["baseline"], 0.875)
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")

    def test_manual_values_are_not_live_coverage(self):
        values = {"cape": 45, "fwd_pe": 24, "pb": 5.5, "margin_yoy": 45, "curve": 36}
        sources = {key: "manual" for key in values}
        sources["curve"] = "live"

        result = score_all(values, sources=sources)

        self.assertEqual(result["coverage"]["fuel"]["live"], 0.125)
        self.assertEqual(result["coverage"]["fuel"]["manual"], 0.5625)
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")

    def test_sufficient_live_coverage_can_issue_high_risk(self):
        values = {"cape": 45, "fwd_pe": 24, "pb": 5.5, "margin_yoy": 45}
        sources = {key: "live" for key in values}

        result = score_all(values, sources=sources)

        self.assertEqual(result["coverage"]["fuel"]["live"], 0.5625)
        self.assertEqual(result["fuel"], 100)
        self.assertEqual(result["verdict"], "HIGH_RISK")

    def test_exported_config_is_json_serializable(self):
        self.assertIn('"min_live_fuel_coverage": 0.5', json.dumps(model_config()))
        html = Path("index.html").read_text(encoding="utf-8")
        self.assertNotIn("const SIGNALS", html)
        self.assertIn("MODEL.signals", html)

    def test_manual_overrides_require_an_asof_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "overrides.json")
            path.write_text(json.dumps({"cape": 40}), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_overrides(path)


if __name__ == "__main__":
    unittest.main()
