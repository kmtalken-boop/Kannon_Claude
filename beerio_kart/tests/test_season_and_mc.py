import random
import unittest

from beerio_kart.match import MatchConfig
from beerio_kart.monte_carlo import run_monte_carlo
from beerio_kart.roster import default_roster, load_roster
from beerio_kart.season import run_season


class TestSeason(unittest.TestCase):
    def test_full_season_runs_and_produces_a_champion(self):
        players, schedule = default_roster()
        config = MatchConfig()
        rng = random.Random(21)
        result = run_season(schedule, config, rng)
        all_players = {p.id for p in players}
        self.assertIn(result.playoffs.champion, all_players)
        self.assertEqual(len(result.league.season_points), 16)
        self.assertEqual(len(result.league.monthly_results), 3)

    def test_load_roster_from_config_file(self):
        players, schedule = load_roster("beerio_kart/config/players.yaml")
        self.assertEqual(len(players), 16)
        self.assertEqual(len(schedule), 3)
        for pods in schedule.values():
            self.assertEqual(len(pods), 4)
            for pod_players in pods.values():
                self.assertEqual(len(pod_players), 4)


class TestMonteCarlo(unittest.TestCase):
    def setUp(self):
        self.players, self.schedule = default_roster()
        self.config = MatchConfig()

    def test_playoff_appearances_sum_to_eight_per_sim(self):
        rng = random.Random(99)
        n_sims = 50
        stats = run_monte_carlo(self.players, self.schedule, self.config, n_sims, rng)
        total_playoff_appearances = sum(s.playoff_appearances for s in stats.values())
        self.assertEqual(total_playoff_appearances, 8 * n_sims)

    def test_exactly_one_champion_per_sim(self):
        rng = random.Random(100)
        n_sims = 50
        stats = run_monte_carlo(self.players, self.schedule, self.config, n_sims, rng)
        self.assertEqual(sum(s.championships for s in stats.values()), n_sims)

    def test_finalists_total_four_per_sim(self):
        rng = random.Random(101)
        n_sims = 50
        stats = run_monte_carlo(self.players, self.schedule, self.config, n_sims, rng)
        self.assertEqual(sum(s.finals_appearances for s in stats.values()), 4 * n_sims)


if __name__ == "__main__":
    unittest.main()
