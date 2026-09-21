import random
import unittest

from beerio_kart.beer import draw_beer_schedule


class TestBeerSchedule(unittest.TestCase):
    def test_schedule_has_correct_size_and_range(self):
        rng = random.Random(1)
        schedule = draw_beer_schedule(rng, races_per_match=32, beers_per_player=8)
        self.assertEqual(len(schedule), 8)
        self.assertTrue(all(1 <= n <= 32 for n in schedule))

    def test_too_many_beers_raises(self):
        rng = random.Random(1)
        with self.assertRaises(ValueError):
            draw_beer_schedule(rng, races_per_match=32, beers_per_player=33)

    def test_schedules_vary(self):
        rng = random.Random(2)
        schedules = [draw_beer_schedule(rng, 32, 8) for _ in range(10)]
        self.assertGreater(len({frozenset(s) for s in schedules}), 1)


if __name__ == "__main__":
    unittest.main()
