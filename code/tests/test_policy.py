"""Unit tests for policy: ranking order and eligibility are pure and exact."""
import sys, unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schemas import PaymentMethod, PlanCandidate
from policy import rank, _option_months
from schemas import PaymentOption

def cand(kind, total, start, n_pays=1, changes=0, deadline=True, oid=None):
    from datetime import timedelta
    pays = tuple((start + timedelta(days=30 * i), total / max(n_pays, 1))
                for i in range(n_pays))
    from schemas import SpendingChange
    ch = tuple(SpendingChange(f"event_{i}", "stop", None)
               for i in range(changes))
    return PlanCandidate(kind=PaymentMethod(kind), payments=pays, total_paid=total,
                        spending_changes=ch, completes_by_deadline=deadline,
                        eligible=True, ineligible_reason="", option_id=oid,
                        start_date=start)

class TestRanking(unittest.TestCase):
    def test_deadline_beats_everything(self):
        a = cand("full_payment", 100, date(2026,1,1), deadline=False)
        b = cand("installments", 999999, date(2026,1,1), deadline=True)
        self.assertEqual(rank([a, b])[0], b)

    def test_no_changes_beats_cheaper_with_changes(self):
        # criterion 2 (no spending changes) precedes criterion 3 (total paid)
        a = cand("installments", 100, date(2026,1,1), changes=1)
        b = cand("full_payment", 500, date(2026,1,1), changes=0)
        self.assertEqual(rank([a, b])[0], b)

    def test_total_paid_beats_earlier_start(self):
        a = cand("installments", 200, date(2026,1,1))
        b = cand("full_payment", 100, date(2026,2,1))
        self.assertEqual(rank([a, b])[0], b)

    def test_fewer_payments_beats_option_id(self):
        a = cand("installments", 100, date(2026,1,1), n_pays=5, oid="payment_option_01")
        b = cand("installments", 100, date(2026,1,1), n_pays=2, oid="payment_option_09")
        self.assertEqual(rank([a, b])[0], b)

    def test_option_id_final_tiebreak(self):
        a = cand("installments", 100, date(2026,1,1), oid="payment_option_07")
        b = cand("installments", 100, date(2026,1,1), oid="payment_option_03")
        self.assertEqual(rank([a, b])[0], b)

class TestOptionMonths(unittest.TestCase):
    def test_single_payment_is_one_month(self):
        o = PaymentOption("o1","r","full_payment",100.0,1,date(2026,1,1),None,0.0,100.0)
        self.assertEqual(_option_months(o), 1)
    def test_monthly_frequency(self):
        o = PaymentOption("o1","r","installments",100.0,3,date(2026,1,1),30,25.0,325.0)
        self.assertEqual(_option_months(o), 3)
    def test_31day_frequency_overage(self):
        o = PaymentOption("o1","r","installments",100.0,18,date(2026,1,1),31,25.0,1825.0)
        self.assertGreater(_option_months(o), 18)

if __name__ == "__main__":
    unittest.main()
