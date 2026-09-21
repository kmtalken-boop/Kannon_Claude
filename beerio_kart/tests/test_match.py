import random
import unittest

from beerio_kart.match import MatchConfig, simulate_match
from beerio_kart.models import Player


class TestSimulateMatch(unittest.TestCase):
    def setUp(self):
        self.players = [Player(id=str(i), name=f"P{i}", skill=1000.0) for i in range(4)]
        self.config = MatchConfig()
        self.rng = random.Random(3)

    def test_points_are_within_the_possible_range(self):
        # Every race is a 12-racer field (4 humans + 8 CPUs, race.py), so a
        # human's per-match total is bounded by "always last of 12" (0) and
        # "always 1st" (15 * races_per_match) -- CPUs absorb some points,
        # so there's no fixed total to sum to any more.
        result = simulate_match(self.players, self.config, self.rng)
        max_possible = 15 * self.config.races_per_match
        for pid, pts in result.points.items():
            self.assertGreaterEqual(pts, 0, pid)
            self.assertLessEqual(pts, max_possible, pid)

    def test_race_wins_bounded_by_races_per_match(self):
        # A CPU can win a race too, so the 4 humans' race wins don't have
        # to sum to races_per_match any more -- just can't exceed it.
        result = simulate_match(self.players, self.config, self.rng)
        self.assertLessEqual(sum(result.race_wins.values()), self.config.races_per_match)

    def test_requires_exactly_four_players(self):
        with self.assertRaises(ValueError):
            simulate_match(self.players[:3], self.config, self.rng)

    def test_higher_skill_scores_more_on_average(self):
        players = [
            Player(id="strong", name="Strong", skill=1500.0),
            Player(id="w1", name="W1", skill=800.0),
            Player(id="w2", name="W2", skill=800.0),
            Player(id="w3", name="W3", skill=800.0),
        ]
        rng = random.Random(9)
        totals = {"strong": [], "w1": []}
        for _ in range(200):
            result = simulate_match(players, self.config, rng)
            totals["strong"].append(result.points["strong"])
            totals["w1"].append(result.points["w1"])
        avg_strong = sum(totals["strong"]) / len(totals["strong"])
        avg_w1 = sum(totals["w1"]) / len(totals["w1"])
        self.assertGreater(avg_strong, avg_w1)


if __name__ == "__main__":
    unittest.main()
