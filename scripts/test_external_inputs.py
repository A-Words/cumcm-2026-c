"""Boundary, rejection and causal tests for the frozen external-data interface."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from external_inputs import load_future_data, build_causal_cache
from model import point_forecast, risk_forecast

ROOT = Path(__file__).resolve().parents[1]


class ExternalInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = dict(np.load(ROOT / "data/processed/data.npz"))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "future.npz"

    def future(self, count=2, start="2026-01-01"):
        return dict(dates=np.datetime64(start) + np.arange(count).astype("timedelta64[D]"),
                    load=np.full((count, 144), 5000.0),
                    pv=np.broadcast_to(np.arange(144, dtype=float), (count, 144)).copy(),
                    dynamic_price=np.full((count, 144), .5),
                    forecast_hourly=np.broadcast_to(np.arange(1, 25, dtype=float),
                                                    (count, 4, 24)).copy())

    def load(self, values, history=None):
        np.savez(self.path, **values)
        return load_future_data(self.history if history is None else history, self.path)

    def test_year_boundary_and_hourly_targets(self):
        values = self.future(1)
        merged, meta = self.load(values)
        self.assertEqual(merged["dates"].dtype, np.dtype("datetime64[D]"))
        self.assertEqual(meta["future_days"], 1)
        np.testing.assert_array_equal(merged["forecast"][365, :, 5::6], values["forecast_hourly"][0])
        np.testing.assert_array_equal(merged["forecast_anchor"][365],
            [self.history["pv"][-1, -1], 35, 71, 107])
        first = (5 * self.history["pv"][-1, -1] + values["forecast_hourly"][0, 0, 0]) / 6
        self.assertAlmostEqual(merged["forecast"][365, 0, 0], first)
        self.assertEqual(merged["load_trapezoid"][365, 0],
                         (self.history["load"][-1, -1] + 5000) / 2)

    def test_derived_arrays_cannot_be_injected(self):
        values = self.future()
        values.update(forecast=np.full((2, 4, 144), 1e20),
                      forecast_anchor=np.full((2, 4), 1e20), fixed_price=np.ones(144)*1e20)
        merged, meta = self.load(values)
        self.assertEqual(meta["ignored_fields"], ["fixed_price", "forecast", "forecast_anchor"])
        self.assertLess(merged["forecast_anchor"].max(), 1e20)
        np.testing.assert_array_equal(merged["fixed_price"], self.history["fixed_price"])
        before = self.history["pv"][0, 0]
        merged["pv"][0, 0] = -1
        self.assertEqual(self.history["pv"][0, 0], before)

    def test_leap_day_is_not_hardcoded_to_365_days(self):
        history = {key: value.copy() for key, value in self.history.items()}
        history["dates"] = np.datetime64("2027-02-28") + np.arange(365).astype("timedelta64[D]")
        self.assertEqual(str(history["dates"][-1]), "2028-02-27")
        merged, meta = self.load(self.future(3, "2028-02-28"), history)
        self.assertEqual(str(merged["dates"][-2]), "2028-02-29")
        self.assertEqual(meta["future_last_date"], "2028-03-01")

    def test_missing_required_field_rejected(self):
        values = self.future()
        del values["forecast_hourly"]
        with self.assertRaisesRegex(ValueError, "missing required"):
            self.load(values)

    def test_wrong_array_shapes_rejected(self):
        for key, shape in [("load", (2, 143)), ("forecast_hourly", (2, 4, 23))]:
            with self.subTest(key=key):
                values = self.future()
                values[key] = np.ones(shape)
                with self.assertRaisesRegex(ValueError, "expected shape"):
                    self.load(values)

    def test_nonfinite_and_negative_power_rejected(self):
        for key, invalid in [("load", np.nan), ("pv", -1), ("forecast_hourly", np.inf)]:
            with self.subTest(key=key):
                values = self.future()
                values[key].flat[0] = invalid
                with self.assertRaises(ValueError):
                    self.load(values)

    def test_nonpositive_price_rejected(self):
        for invalid in (0, -1):
            with self.subTest(price=invalid):
                values = self.future()
                values["dynamic_price"][0, 0] = invalid
                with self.assertRaisesRegex(ValueError, "positive"):
                    self.load(values)

    def test_date_gap_overlap_duplicate_and_subday_rejected(self):
        cases = [("2026-01-02", "2026-01-03"), ("2025-12-31", "2026-01-01"),
                 ("2026-01-01", "2026-01-01"), ("2026-01-01", "2026-01-03"),
                 ("2026-01-01T00:00", "2026-01-02T00:00")]
        for dates in cases:
            with self.subTest(dates=dates):
                values = self.future()
                values["dates"] = np.array(dates)
                with self.assertRaises(ValueError):
                    self.load(values)

    def test_empty_date_range_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonempty"):
            self.load(self.future(0))

    def test_cache_extends_past_365_and_excludes_later_data(self):
        values = self.future(3)
        merged, _ = self.load(values)
        cache = build_causal_cache(merged, .5, True)
        self.assertEqual(cache.net.shape, (368, 4, 144))
        expected = point_forecast(merged, 367, 2, True, dynamic=True, pv_weight=.5)
        np.testing.assert_array_equal(cache.net[367, 2, 72:], expected[0])
        changed = {key: value.copy() for key, value in values.items()}
        for key in ("load", "pv", "dynamic_price", "forecast_hourly"):
            changed[key][1:] += 100000
        alternate, _ = self.load(changed)
        alternate_cache = build_causal_cache(alternate, .5, True)
        for issue in range(4):
            np.testing.assert_array_equal(cache.net[365, issue], alternate_cache.net[365, issue])
            np.testing.assert_array_equal(cache.price[365, issue], alternate_cache.price[365, issue])
            np.testing.assert_array_equal(risk_forecast(cache, 365, issue, .65),
                                          risk_forecast(alternate_cache, 365, issue, .65))


if __name__ == "__main__":
    unittest.main()
