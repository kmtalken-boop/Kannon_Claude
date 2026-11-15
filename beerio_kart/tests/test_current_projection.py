import random
import unittest

from beerio_kart.current_projection import run_current_projection
from beerio_kart.data.current_standings import CURRENT_STANDINGS, REMAINING_FIXTURES
from beerio_kart.match import MatchConfig
from beerio_kart.roster import load_roster


class TestCurrentProjection(unittest.TestCase):
    def setUp(self):
        players, _schedule = load_roster("beerio_kart/config/players_calibrated.yaml")
        self.players_by_name = {p.name: p for p in players}
        self.config = MatchConfig()

    def test_every_remaining_fixture_player_is_on_the_roster(self):
        for label, names in REMAINING_FIXTURES:
            for name in names:
                self.assertIn(name, self.players_by_name, f"{label}: unknown player {name}")

    def test_remaining_fixture_count_matches_games_played_gap(self):
        # Each player's (3 - games_played) should equal exactly how many
        # of the remaining fixtures they appear in -- if not, either a
        # real match is missing from REMAINING_FIXTURES or one listed
        # there has actually already been played.
        remaining_count = {name: 0 for name in CURRENT_STANDINGS}
        for _label, names in REMAINING_FIXTURES:
            for name in names:
                remaining_count[name] += 1
        for name, (games_played, _points) in CURRENT_STANDINGS.items():
            self.assertEqual(
                remaining_count[name], 3 - games_played,
                f"{name}: played {games_played}/3 but appears in {remaining_count[name]} remaining fixtures",
            )

    def test_final_points_are_at_least_banked_points(self):
        rng = random.Random(1)
        stats = run_current_projection(self.players_by_name, self.config, 20, rng)
        for name, s in stats.items():
            row = s.as_row()
            self.assertGreaterEqual(row["avg_final_points"], CURRENT_STANDINGS[name][1])

    def test_players_with_no_remaining_fixtures_have_fixed_final_points(self):
        in_a_fixture = {n for _label, names in REMAINING_FIXTURES for n in names}
        done_players = [n for n in CURRENT_STANDINGS if n not in in_a_fixture]
        self.assertGreater(len(done_players), 0)
        rng = random.Random(2)
        stats = run_current_projection(self.players_by_name, self.config, 10, rng)
        for name in done_players:
            self.assertEqual(stats[name].as_row()["avg_final_points"], CURRENT_STANDINGS[name][1])

    def test_playoff_appearances_sum_to_eight_per_sim(self):
        rng = random.Random(3)
        n_sims = 30
        stats = run_current_projection(self.players_by_name, self.config, n_sims, rng)
        self.assertEqual(sum(s.playoff_appearances for s in stats.values()), 8 * n_sims)

    def test_exactly_one_champion_per_sim(self):
        rng = random.Random(4)
        n_sims = 30
        stats = run_current_projection(self.players_by_name, self.config, n_sims, rng)
        self.assertEqual(sum(s.championships for s in stats.values()), n_sims)


if __name__ == "__main__":
    unittest.main()
