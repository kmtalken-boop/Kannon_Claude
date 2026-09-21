import unittest

from beerio_kart.data.history import ALL_RANKING_EVENTS
from beerio_kart.data.history_points import ALL_EVENTS_WITH_POINTS


class TestHistoryPointsConsistency(unittest.TestCase):
    def test_same_number_of_events(self):
        self.assertEqual(len(ALL_EVENTS_WITH_POINTS), len(ALL_RANKING_EVENTS))

    def test_player_order_matches_ranking_events(self):
        for (label, results), ranking in zip(ALL_EVENTS_WITH_POINTS, ALL_RANKING_EVENTS):
            self.assertEqual(
                [pid for pid, _points in results],
                ranking,
                msg=f"{label}: player order doesn't match history.py's ranking for this event",
            )

    def test_points_within_each_event_are_strictly_descending(self):
        for label, results in ALL_EVENTS_WITH_POINTS:
            points = [p for _pid, p in results]
            self.assertEqual(
                points, sorted(points, reverse=True), msg=f"{label}: points aren't in descending order"
            )


if __name__ == "__main__":
    unittest.main()
