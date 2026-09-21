import unittest

from beerio_kart.data.history import ALL_RANKING_EVENTS
from beerio_kart.data.history_points import ALL_EVENTS_WITH_POINTS


class TestHistoryPointsConsistency(unittest.TestCase):
    """ALL_RANKING_EVENTS (used for the Plackett-Luce fit) can hold events
    with no real points behind them, like the league's own full-roster
    ranking -- those are appended after the real, point-scored races, so
    this only checks the leading real-race prefix the two lists share.
    """

    def test_ranking_events_cover_at_least_the_real_races(self):
        self.assertGreaterEqual(len(ALL_RANKING_EVENTS), len(ALL_EVENTS_WITH_POINTS))

    def test_player_order_matches_ranking_events(self):
        real_race_rankings = ALL_RANKING_EVENTS[: len(ALL_EVENTS_WITH_POINTS)]
        for (label, results), ranking in zip(ALL_EVENTS_WITH_POINTS, real_race_rankings):
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
