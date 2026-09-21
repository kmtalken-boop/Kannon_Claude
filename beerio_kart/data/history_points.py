"""Raw point values behind the ranking events in ``history.py``.

``calibrate.fit_plackett_luce`` only needs finishing order, so
``history.py`` stores rankings, not points. The Excel dashboard wants to
show real point totals (season standings, a player's points trend), so
this module carries the same events with their actual scores attached.
Each event's player order here must match its counterpart in
``history.py`` -- ``tests/test_history_points.py`` checks that directly
rather than trusting the transcription twice.
"""
from __future__ import annotations

# Each event: (label, [(player, points), ...]) with players already
# ordered best (most points) to worst, mirroring history.py's ranking
# lists in the same order.
SEASON_1_WEEKLY_POINTS: list[tuple[str, list[tuple[str, int]]]] = [
    ("S1 Week 1 - Group 1", [("Kannon", 422), ("Jack", 359), ("Jake", 283), ("Sam", 195)]),
    ("S1 Week 1 - Group 2", [("Greg", 256), ("Isaiah", 230), ("Jackson", 217), ("Jorgen", 129)]),
    ("S1 Week 1 - Group 3", [("Will", 312), ("Stu", 310), ("Peter", 124), ("Max", 94)]),
    ("S1 Week 2 - Group 1", [("Jake", 370), ("Jackson", 203), ("Greg", 202), ("Max", 106)]),
    ("S1 Week 2 - Group 2", [("Jack", 387), ("Sam", 310), ("Stu", 283), ("Isaiah", 213)]),
    ("S1 Week 2 - Group 3", [("Kannon", 426), ("Will", 306), ("Jorgen", 170), ("Peter", 109)]),
    ("S1 Week 3 - Group 1", [("Will", 319), ("Stu", 283), ("Isaiah", 231), ("Zynny", 215)]),
    ("S1 Week 3 - Group 2", [("Kannon", 436), ("Jack", 313), ("Greg", 164), ("Max", 115)]),
    ("S1 Week 3 - Group 3", [("Jack (sub)", 415), ("Jake", 321), ("Sam", 288), ("Peter", 199)]),
]

SEASON_1_PLAYOFF_POINTS: list[tuple[str, list[tuple[str, int]]]] = [
    ("S1 Playoffs - Semi 1", [("Kannon", 384), ("Jack", 369), ("Isaiah", 240), ("Jackson", 181)]),
    ("S1 Playoffs - Semi 2", [("Jake", 356), ("Stu", 302), ("Will", 300), ("Sam", 212)]),
    ("S1 Playoffs - Final", [("Kannon", 368), ("Jack", 320), ("Stu", 302), ("Will", 281)]),
]

SEASON_2_WEEK_1_POINTS: list[tuple[str, list[tuple[str, int]]]] = [
    ("S2 Week 1 - Group A", [("Kannon", 421), ("Jack", 345), ("Christian", 238), ("Peter", 166)]),
    ("S2 Week 1 - Group B", [("Sam", 388), ("Jackson", 328), ("Max", 260), ("Jorgen", 168)]),
    ("S2 Week 1 - Group C", [("Isaiah", 350), ("Harrison", 237), ("Cailin", 116), ("Ivan", 39)]),
]

ALL_EVENTS_WITH_POINTS: list[tuple[str, list[tuple[str, int]]]] = (
    SEASON_1_WEEKLY_POINTS + SEASON_1_PLAYOFF_POINTS + SEASON_2_WEEK_1_POINTS
)
