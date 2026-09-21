import random
import unittest

from beerio_kart.match import MatchConfig
from beerio_kart.matchup import estimate_matchup
from beerio_kart.models import Player


class TestEstimateMatchup(unittest.TestCase):
    def setUp(self):
        self.config = MatchConfig()
        self.rng = random.Random(5)

    def test_requires_four_players(self):
        players = [Player(id=str(i), name=f"P{i}") for i in range(3)]
        with self.assertRaises(ValueError):
            estimate_matchup(players, self.config, self.rng)

    def test_avg_points_cover_all_players_and_are_plausible(self):
        # Every race is a 12-racer field (4 humans + 8 CPUs at equal
        # skill), so with all 4 humans also at equal skill each should
        # average roughly a 1/12 share of the race's point pool, not a
        # 1/4 share -- there's no fixed total to check against any more.
        players = [Player(id=str(i), name=f"P{i}", skill=1000.0) for i in range(4)]
        estimate = estimate_matchup(players, self.config, self.rng, trials=50)
        self.assertEqual(set(estimate.avg_points), {p.id for p in players})
        max_possible = 15 * self.config.races_per_match
        for pid, avg in estimate.avg_points.items():
            self.assertGreater(avg, 0, pid)
            self.assertLess(avg, max_possible, pid)

    def test_stronger_player_scores_and_wins_more(self):
        players = [
            Player(id="strong", name="Strong", skill=2000.0),
            Player(id="w1", name="W1", skill=700.0),
            Player(id="w2", name="W2", skill=700.0),
            Player(id="w3", name="W3", skill=700.0),
        ]
        estimate = estimate_matchup(players, self.config, self.rng, trials=150)
        self.assertGreater(estimate.avg_points["strong"], estimate.avg_points["w1"])
        self.assertGreater(estimate.win_pct["strong"], estimate.win_pct["w1"])

    def test_win_pct_sums_to_100(self):
        players = [Player(id=str(i), name=f"P{i}", skill=1000.0) for i in range(4)]
        estimate = estimate_matchup(players, self.config, self.rng, trials=40)
        self.assertAlmostEqual(sum(estimate.win_pct.values()), 100.0, places=6)


if __name__ == "__main__":
    unittest.main()
