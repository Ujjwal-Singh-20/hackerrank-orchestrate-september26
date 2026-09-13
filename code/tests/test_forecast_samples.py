"""Unit tests for the forecast module, calibrated against the 25 solved
samples. These assertions record the engine's measured status (they are test
expectations, not model constants — nothing in config.py is fitted)."""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from ingest import cached_dataset
from perception import DeterministicPerception, resolve_blank_amounts
from schemas import Request
from forecast import run


def _compute_all():
    """Sample requests are NOT in requests.csv (that is the eval set), so we
    build Request objects from sample_requests.csv directly."""
    ds = cached_dataset()
    provider = DeterministicPerception()
    image_amounts = resolve_blank_amounts(ds, provider)
    results = {}
    for rid, row in SAMPLES.items():
        req = Request(
            request_id=rid, user_id=row["user_id"],
            request_date=date.fromisoformat(row["request_date"]),
            request_type=row["request_type"],
            requested_amount=float(row["requested_amount"]),
            desired_completion_date=date.fromisoformat(row["desired_completion_date"]),
            allows_partial_payment=row["allows_partial_payment"].strip().lower() == "true",
            request_text=row["request_text"])
        profile = ds.profiles[req.user_id]
        events = ds.events_for_user(req.user_id)
        amendments = provider.extract_amendments(ds, req.user_id)
        results[rid] = (req, run(profile, events, req, amendments,
                                 image_amounts, ds.rates))
    return results


def _samples():
    import csv
    path = Path(__file__).resolve().parent.parent.parent / "dataset" / "sample_requests.csv"
    with open(path, newline="", encoding="utf-8") as f:
        return {r["request_id"]: r for r in csv.DictReader(f)}


SAMPLE_IDS = set(_samples().keys())
SAMPLES = _samples()


class TestForecastOnSamples(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.results = _compute_all()

    def test_all_25_samples_forecastable(self):
        self.assertEqual(len(self.results), 25)

    def test_edfp_exact_matches_at_least_20(self):
        n = 0
        for rid, (req, fr) in self.results.items():
            expected = SAMPLES[rid]["earliest_date_for_full_payment"] or None
            got = fr.earliest_full_payment.isoformat() if fr.earliest_full_payment else None
            if got == expected:
                n += 1
        self.assertGreaterEqual(n, 20, f"edfp exact matches fell to {n}/25")

    def test_safe_within_bounds(self):
        for rid, (req, fr) in self.results.items():
            self.assertGreaterEqual(fr.amount_safe_to_pay, 0.0)
            self.assertLessEqual(fr.amount_safe_to_pay, req.requested_amount + 1e-9)

    def test_safe_capped_cases_exact(self):
        # samples where expected safe == requested must compute >= requested
        for rid, (req, fr) in self.results.items():
            expected = float(SAMPLES[rid]["amount_safe_to_pay"])
            if expected >= req.requested_amount - 1e-9:
                self.assertGreaterEqual(fr.amount_safe_to_pay, req.requested_amount - 0.005,
                                        f"{rid}: capped case not affordable")

    def test_safe_median_relative_error_under_10pct(self):
        rels = []
        for rid, (req, fr) in self.results.items():
            expected = float(SAMPLES[rid]["amount_safe_to_pay"])
            if expected < req.requested_amount - 1e-9 and expected > 0:
                rels.append(abs(fr.amount_safe_to_pay - expected) / expected)
        rels.sort()
        median = rels[len(rels) // 2]
        self.assertLess(median, 0.10, f"median relative error {median:.2%}")

    def test_base_path_never_below_min_balance(self):
        for rid, (req, fr) in self.results.items():
            profile = cached_dataset().profiles[req.user_id]
            self.assertGreaterEqual(fr.base_path_min_balance,
                                     profile.min_balance - 1e-6,
                                     f"{rid}: base path breaches minimum")


if __name__ == "__main__":
    unittest.main()