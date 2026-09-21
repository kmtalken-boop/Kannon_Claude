import random
import unittest

from beerio_kart.league import run_league_phase
from beerio_kart.match import MatchConfig
from beerio_kart.playoffs import run_playoffs, seed_playoffs
from beerio_kart.roster import default_roster


class TestPlayoffs(unittest.TestCase):
    def setUp(self):
        self.players, self.schedule = default_roster()
        self.players_by_id = {p.id: p for p in self.players}
        self.config = MatchConfig()
        self.rng = random.Random(13)
        self.league_result = run_league_phase(self.schedule, self.config, self.rng)

    def test_seeding_produces_eight_of_the_top_scorers(self):
        seeds = seed_playoffs(self.league_result.season_points, self.rng)
        self.assertEqual(len(seeds), 8)
        self.assertEqual(len(set(seeds)), 8)
        ranked = sorted(self.league_result.season_points, key=lambda pid: -self.league_result.season_points[pid])
        self.assertEqual(set(seeds), set(ranked[:8]))

    def test_bracket_assignment_matches_seed_rule(self):
        result = run_playoffs(self.league_result.season_points, self.players_by_id, self.config, self.rng)
        seeds = result.seeds
        top_expected = {seeds[0], seeds[1], seeds[6], seeds[7]}
        bottom_expected = {seeds[2], seeds[3], seeds[4], seeds[5]}
        self.assertEqual(set(result.bracket_top.points), top_expected)
        self.assertEqual(set(result.bracket_bottom.points), bottom_expected)

    def test_finalists_are_two_from_each_bracket(self):
        result = run_playoffs(self.league_result.season_points, self.players_by_id, self.config, self.rng)
        self.assertEqual(len(result.finalists), 4)
        top_expected = {result.seeds[0], result.seeds[1], result.seeds[6], result.seeds[7]}
        bottom_expected = {result.seeds[2], result.seeds[3], result.seeds[4], result.seeds[5]}
        finalists_from_top = [pid for pid in result.finalists if pid in top_expected]
        finalists_from_bottom = [pid for pid in result.finalists if pid in bottom_expected]
        self.assertEqual(len(finalists_from_top), 2)
        self.assertEqual(len(finalists_from_bottom), 2)

    def test_champion_is_one_of_the_finalists(self):
        result = run_playoffs(self.league_result.season_points, self.players_by_id, self.config, self.rng)
        self.assertIn(result.champion, result.finalists)


if __name__ == "__main__":
    unittest.main()
