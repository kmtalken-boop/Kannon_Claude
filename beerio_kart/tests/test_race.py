import random
import unittest
from collections import Counter

from beerio_kart.race import simulate_race


class TestSimulateRace(unittest.TestCase):
    def test_returns_full_permutation(self):
        rng = random.Random(0)
        skills = {"a": 1000.0, "b": 1000.0, "c": 1000.0, "d": 1000.0}
        order = simulate_race(skills, chaos_scale=1.0, rng=rng)
        self.assertEqual(sorted(order), sorted(skills))
        self.assertEqual(len(order), 4)

    def test_higher_skill_wins_more_often(self):
        # Plackett-Luce win probability = skill / sum(skills) = 2000/3500 ~= 0.571.
        rng = random.Random(42)
        skills = {"strong": 2000.0, "weak1": 500.0, "weak2": 500.0, "weak3": 500.0}
        wins = Counter()
        n = 4000
        for _ in range(n):
            order = simulate_race(skills, chaos_scale=1.0, rng=rng)
            wins[order[0]] += 1
        self.assertAlmostEqual(wins["strong"] / n, 2000 / 3500, delta=0.05)

    def test_equal_skill_wins_are_roughly_uniform(self):
        rng = random.Random(7)
        skills = {"a": 1000.0, "b": 1000.0, "c": 1000.0, "d": 1000.0}
        wins = Counter()
        n = 4000
        for _ in range(n):
            wins[simulate_race(skills, chaos_scale=1.0, rng=rng)[0]] += 1
        for pid in skills:
            self.assertAlmostEqual(wins[pid] / n, 0.25, delta=0.05)


if __name__ == "__main__":
    unittest.main()
