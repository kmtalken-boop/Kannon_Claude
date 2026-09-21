import random
import unittest

from beerio_kart.match import MatchConfig
from beerio_kart.monte_carlo import run_monte_carlo
from beerio_kart.roster import default_roster, load_roster
from beerio_kart.season import run_season


class TestSeason(unittest.TestCase):
    def test_full_season_runs_and_produces_a_champion(self):
        groups = default_roster()
        config = MatchConfig()
        rng = random.Random(21)
        result = run_season(groups, config, rng)
        all_players = {p.id for plist in groups.values() for p in plist}
        self.assertIn(result.playoffs.champion, all_players)
        self.assertEqual(len(result.groups), 4)

    def test_load_roster_from_config_file(self):
        groups = load_roster("beerio_kart/config/players.yaml")
        self.assertEqual(len(groups), 4)
        for players in groups.values():
            self.assertEqual(len(players), 4)


class TestMonteCarlo(unittest.TestCase):
    def test_playoff_appearances_sum_to_eight_per_sim(self):
        groups = default_roster()
        config = MatchConfig()
        rng = random.Random(99)
        n_sims = 50
        stats = run_monte_carlo(groups, config, n_sims, rng)
        total_playoff_appearances = sum(s.playoff_appearances for s in stats.values())
        self.assertEqual(total_playoff_appearances, 8 * n_sims)

    def test_exactly_one_champion_per_sim(self):
        groups = default_roster()
        config = MatchConfig()
        rng = random.Random(100)
        n_sims = 50
        stats = run_monte_carlo(groups, config, n_sims, rng)
        self.assertEqual(sum(s.championships for s in stats.values()), n_sims)

    def test_finalists_total_four_per_sim(self):
        groups = default_roster()
        config = MatchConfig()
        rng = random.Random(101)
        n_sims = 50
        stats = run_monte_carlo(groups, config, n_sims, rng)
        self.assertEqual(sum(s.finals_appearances for s in stats.values()), 4 * n_sims)


if __name__ == "__main__":
    unittest.main()
