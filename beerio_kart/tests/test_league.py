import random
import unittest

from beerio_kart.league import run_league_phase
from beerio_kart.match import MatchConfig
from beerio_kart.race import POSITION_POINTS
from beerio_kart.roster import default_roster


class TestLeaguePhase(unittest.TestCase):
    def setUp(self):
        self.players, self.schedule = default_roster()
        self.config = MatchConfig()

    def test_runs_one_match_per_pod_per_month(self):
        result = run_league_phase(self.schedule, self.config, random.Random(5))
        for month, pods in self.schedule.items():
            self.assertEqual(set(result.monthly_results[month]), set(pods))

    def test_season_points_sum_across_all_pods(self):
        result = run_league_phase(self.schedule, self.config, random.Random(5))
        per_match_total = sum(POSITION_POINTS.values()) * self.config.races_per_match
        n_matches = sum(len(pods) for pods in self.schedule.values())
        self.assertEqual(sum(result.season_points.values()), per_match_total * n_matches)

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
