import random
import unittest

from beerio_kart.league import run_league_phase
from beerio_kart.match import MatchConfig
from beerio_kart.roster import default_roster


class TestLeaguePhase(unittest.TestCase):
    def setUp(self):
        self.players, self.schedule = default_roster()
        self.config = MatchConfig()

    def test_runs_one_match_per_pod_per_month(self):
        result = run_league_phase(self.schedule, self.config, random.Random(5))
        for month, pods in self.schedule.items():
            self.assertEqual(set(result.monthly_results[month]), set(pods))

    def test_season_points_within_the_possible_range(self):
        # Each race is a 12-racer field (4 humans + 8 CPUs), so a player's
        # points per match are bounded but don't sum to a fixed total --
        # CPUs absorb some of every race's point pool.
        result = run_league_phase(self.schedule, self.config, random.Random(5))
        matches_per_player = len(self.schedule)  # one per month
        max_possible = 15 * self.config.races_per_match * matches_per_player
        for pid, pts in result.season_points.items():
            self.assertGreaterEqual(pts, 0, pid)
            self.assertLessEqual(pts, max_possible, pid)

    def test_every_player_gets_a_season_total(self):
        result = run_league_phase(self.schedule, self.config, random.Random(5))
        self.assertEqual(sorted(result.season_points), sorted(p.id for p in self.players))

    def test_rejects_wrong_pod_size(self):
        bad_schedule = {"Month": {"Group 1": self.players[:3]}}
        with self.assertRaises(ValueError):
            run_league_phase(bad_schedule, self.config, random.Random(0))

    def test_no_player_faces_the_same_opponent_twice(self):
        from itertools import combinations

        seen = set()
        for pods in self.schedule.values():
            for players in pods.values():
                names = sorted(p.id for p in players)
                for a, b in combinations(names, 2):
                    self.assertNotIn((a, b), seen, f"{a} and {b} share a pod more than once")
                    seen.add((a, b))


if __name__ == "__main__":
    unittest.main()
