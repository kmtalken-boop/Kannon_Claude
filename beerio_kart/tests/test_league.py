import random
import unittest

from beerio_kart.league import MONTHS_PER_SEASON, run_group, run_league_phase
from beerio_kart.match import MatchConfig
from beerio_kart.models import Player
from beerio_kart.race import POSITION_POINTS
from beerio_kart.roster import default_roster


class TestLeaguePhase(unittest.TestCase):
    def test_group_plays_three_matches(self):
        players = [Player(id=str(i), name=f"P{i}", skill=1000.0) for i in range(4)]
        config = MatchConfig()
        rng = random.Random(5)
        result = run_group("A", players, config, rng)
        self.assertEqual(len(result.match_results), MONTHS_PER_SEASON)

    def test_season_points_sum_across_matches(self):
        players = [Player(id=str(i), name=f"P{i}", skill=1000.0) for i in range(4)]
        config = MatchConfig()
        rng = random.Random(5)
        result = run_group("A", players, config, rng)
        per_match_total = sum(POSITION_POINTS.values()) * config.races_per_match
        self.assertEqual(sum(result.season_points.values()), per_match_total * MONTHS_PER_SEASON)

    def test_standings_include_all_players_once(self):
        players = [Player(id=str(i), name=f"P{i}", skill=1000.0) for i in range(4)]
        config = MatchConfig()
        rng = random.Random(5)
        result = run_group("A", players, config, rng)
        self.assertEqual(sorted(result.standings()), sorted(p.id for p in players))

    def test_rejects_wrong_group_size(self):
        players = [Player(id=str(i), name=f"P{i}") for i in range(3)]
        with self.assertRaises(ValueError):
            run_group("A", players, MatchConfig(), random.Random(0))

    def test_league_phase_runs_all_groups(self):
        groups = default_roster()
        rng = random.Random(11)
        results = run_league_phase(groups, MatchConfig(), rng)
        self.assertEqual(set(results.keys()), set(groups.keys()))
        for name, result in results.items():
            self.assertEqual(sorted(result.standings()), sorted(p.id for p in groups[name]))


if __name__ == "__main__":
    unittest.main()
