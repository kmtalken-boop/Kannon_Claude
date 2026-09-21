import random
import unittest

from beerio_kart.match import MatchConfig, simulate_match
from beerio_kart.models import Player
from beerio_kart.race import POSITION_POINTS


class TestSimulateMatch(unittest.TestCase):
    def setUp(self):
        self.players = [Player(id=str(i), name=f"P{i}", skill=1000.0) for i in range(4)]
        self.config = MatchConfig()
        self.rng = random.Random(3)

    def test_points_total_matches_expected(self):
        result = simulate_match(self.players, self.config, self.rng)
        per_race_total = sum(POSITION_POINTS.values())
        expected_total = per_race_total * self.config.races_per_match
        self.assertEqual(sum(result.points.values()), expected_total)

    def test_race_wins_sum_to_races_per_match(self):
        result = simulate_match(self.players, self.config, self.rng)
        self.assertEqual(sum(result.race_wins.values()), self.config.races_per_match)

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
        totals = []
        rng = random.Random(9)
        for _ in range(200):
            result = simulate_match(players, self.config, rng)
            totals.append(result.points["strong"])
        avg_strong = sum(totals) / len(totals)
        self.assertGreater(avg_strong, 45 * 32 / 4)  # better than a flat average share


if __name__ == "__main__":
    unittest.main()
