import unittest

from beerio_kart.calibrate import fit_plackett_luce, strengths_to_skill


class TestFitPlackettLuce(unittest.TestCase):
    def test_empty_rankings_returns_empty(self):
        self.assertEqual(fit_plackett_luce([]), {})

    def test_strengths_normalize_to_mean_one(self):
        rankings = [["a", "b", "c", "d"], ["b", "a", "d", "c"], ["a", "c", "b", "d"]]
        w = fit_plackett_luce(rankings)
        self.assertAlmostEqual(sum(w.values()) / len(w), 1.0, places=6)

    def test_dominant_player_ends_up_strongest(self):
        # "a" wins every ranking it's in; should fit the highest strength.
        rankings = [
            ["a", "b", "c", "d"],
            ["a", "c", "d", "b"],
            ["a", "d", "b", "c"],
            ["b", "c", "d"],
        ]
        w = fit_plackett_luce(rankings)
        self.assertEqual(max(w, key=w.get), "a")

    def test_handles_partial_participation(self):
        # "d" only shows up once, in a losing spot -- should not crash and
        # should end up below the field average.
        rankings = [["a", "b", "c"], ["b", "c", "a"], ["c", "a", "b", "d"]]
        w = fit_plackett_luce(rankings)
        self.assertIn("d", w)
        self.assertLess(w["d"], 1.0)

    def test_strengths_to_skill_linear_rescale(self):
        w = {"a": 2.0, "b": 0.5}
        skill = strengths_to_skill(w, base_skill=1000.0)
        self.assertEqual(skill["a"], 2000.0)
        self.assertEqual(skill["b"], 500.0)

    def test_wrong_length_weights_raises(self):
        with self.assertRaises(ValueError):
            fit_plackett_luce([["a", "b"]], weights=[1.0, 2.0])

    def test_heavily_weighted_recent_result_dominates_fit(self):
        # "b" loses every early (low-weight) game but wins a single,
        # heavily-weighted recent one -- the recent result should be
        # enough to pull "b" above "a" despite the losing record.
        rankings = [["a", "b"], ["a", "b"], ["a", "b"], ["b", "a"]]
        weights = [1.0, 1.0, 1.0, 20.0]
        w = fit_plackett_luce(rankings, weights=weights)
        self.assertGreater(w["b"], w["a"])


if __name__ == "__main__":
    unittest.main()
