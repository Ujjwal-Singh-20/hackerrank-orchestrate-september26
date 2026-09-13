"""Unit tests for ingest: shape and join integrity of the loaded dataset."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest import cached_dataset
from errors import DatasetError

class TestIngest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = cached_dataset()

    def test_shapes(self):
        self.assertEqual(len(self.ds.requests), 250)
        self.assertGreater(len(self.ds.profiles), 250)
        self.assertGreater(len(self.ds.events), 25000)

    def test_all_requests_have_profiles(self):
        for r in self.ds.requests.values():
            self.assertIn(r.user_id, self.ds.profiles)

    def test_options_cover_two_to_four_per_eval_request(self):
        # every EVAL request (requests.csv) has 2-4 options; the file also
        # carries options for the 25 sample requests, which are not in
        # requests.csv and therefore out of scope here
        for rid in self.ds.requests:
            opts = self.ds.options.get(rid, [])
            self.assertTrue(2 <= len(opts) <= 4, f"{rid}: {len(opts)} options")

    def test_blank_amount_events_have_images(self):
        blanks = [e for e in self.ds.events.values() if e.amount is None]
        img_events = {i.related_event_id for i in self.ds.images}
        for e in blanks:
            self.assertIn(e.event_id, img_events,
                          f"{e.event_id} blank without an image link")

if __name__ == "__main__":
    unittest.main()
