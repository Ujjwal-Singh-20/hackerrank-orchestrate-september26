"""Contract test: every row of output.csv satisfies the output schema
invariants from problem_statement.md (via validate.validate_row)."""

import csv
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from ingest import cached_dataset
from validate import validate_row
from schemas import Request

ROOT = Path(__file__).resolve().parent.parent.parent


class TestOutputContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ds = cached_dataset()
        if not (ROOT / "output.csv").exists():
            raise unittest.SkipTest(
                "output.csv not generated yet - run: python3 code/main.py")
        with open(ROOT / "output.csv", newline="", encoding="utf-8") as f:
            cls.rows = list(csv.DictReader(f))

    def test_row_per_request(self):
        self.assertEqual(len(self.rows), len(self.ds.requests))
        got_ids = {r["request_id"] for r in self.rows}
        self.assertEqual(got_ids, set(self.ds.requests))

    def test_header_order(self):
        expected = ("request_id,amount_safe_to_pay,affordability_status,"
                    "recommended_payment_method,payment_plan,"
                    "earliest_date_for_full_payment,spending_changes_needed,"
                    "decision_explanation")
        with open(ROOT / "output.csv", encoding="utf-8") as f:
            self.assertEqual(f.readline().strip(), expected)

    def test_every_row_valid(self):
        for r in self.rows:
            req = self.ds.requests[r["request_id"]]
            from schemas import OutputRow
            row = OutputRow(
                request_id=r["request_id"],
                amount_safe_to_pay=float(r["amount_safe_to_pay"]),
                affordability_status=r["affordability_status"],
                recommended_payment_method=r["recommended_payment_method"],
                payment_plan=r["payment_plan"],
                earliest_date_for_full_payment=r["earliest_date_for_full_payment"],
                spending_changes_needed=r["spending_changes_needed"],
                decision_explanation=r["decision_explanation"])
            validate_row(row, req)  # raises OutputContractError on violation

    def test_installment_plans_match_supplied_options(self):
        for r in self.rows:
            if r["recommended_payment_method"] != "installments":
                continue
            opts = self.ds.options.get(r["request_id"], [])
            pays = r["payment_plan"].split("|")
            first_amt = float(pays[0].split(":")[1])
            n = len(pays)
            matched = any(
                abs(o.payment_amount - first_amt) < 0.005
                and o.number_of_payments == n
                for o in opts)
            self.assertTrue(matched,
                            f"{r['request_id']}: installment plan does not "
                            f"match any supplied payment option")


if __name__ == "__main__":
    unittest.main()