import random
import unittest

from beerio_kart.cli import run_matchup
from beerio_kart.match import MatchConfig
from beerio_kart.roster import default_roster


class TestRunMatchup(unittest.TestCase):
    def setUp(self):
        self.groups = default_roster()
        self.config = MatchConfig()
        self.rng = random.Random(0)

    def test_duplicate_names_raise(self):
        with self.assertRaises(SystemExit):
            run_matchup(["Player 1", "Player 1", "Player 2", "Player 3"], self.groups, self.config, 10, self.rng)

    def test_unknown_name_raises(self):
        with self.assertRaises(SystemExit):
            run_matchup(["Player 1", "Player 2", "Player 3", "Nobody"], self.groups, self.config, 10, self.rng)

    def test_valid_matchup_runs_without_error(self):
        run_matchup(["Player 1", "Player 2", "Player 3", "Player 4"], self.groups, self.config, 10, self.rng)


if __name__ == "__main__":
    unittest.main()
