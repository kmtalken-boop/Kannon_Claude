"""Real historical league results, transcribed from the league's Google
Sheet (season standings + weekly group breakdowns).

That sheet's actual structure differs from the placeholder 16-player / 4
fixed-group setup in ``roster.py``: it has 12 recurring drivers split into
3 groups of 4 that get *reshuffled every week*, rather than 4 groups that
stay fixed all season. This module only exists to feed real results into
``calibrate.fit_plackett_luce`` for skill estimation -- it is not read by
the season simulator itself.

A few rows needed a judgment call while transcribing:

- Jorgen has "DNP" (did not play) in week 3 -- he's simply absent from
  that week's groups below, which Plackett-Luce handles natively (a
  ranking is only over the players who actually raced that day).
- Week 3, group 1's 4th-place score of 215 is credited in the sheet's
  season-totals row to "Budzy", but the weekly group table names the
  actual participant "Zynny" -- a likely one-off substitute. Recorded
  here under a distinct id ``Zynny`` (not merged into Budzy) so Budzy's
  rating isn't credited with a game he didn't play.
- Week 3, group 3 lists "Jack (sub)" scoring 415 -- since the real Jack
  already has his own (different, lower) result in group 2 that week,
  this is someone else subbing under Jack's name. Recorded under a
  distinct id ``Jack (sub)`` so it doesn't get merged into Jack's rating.

Both one-off substitute ids are kept in the ranking events (they still
carry information about how the *other* three racers in their group did
that day) but are excluded from the final calibrated roster -- see
``build_roster_from_history.py``.
"""
from __future__ import annotations

# Each entry: one race group's results for one week, ordered best (most
# points) to worst. This is exactly the "ranking" format
# calibrate.fit_plackett_luce expects.
WEEKLY_GROUP_RESULTS: list[list[str]] = [
    # Week 1
    ["Kannon", "Jack", "Jake", "Sam"],
    ["Greg", "Isaiah", "Budzy", "Jorgen"],
    ["Will", "Stu", "Peter", "Max"],
    # Week 2
    ["Jake", "Budzy", "Greg", "Max"],
    ["Jack", "Sam", "Stu", "Isaiah"],
    ["Kannon", "Will", "Jorgen", "Peter"],
    # Week 3
    ["Will", "Stu", "Isaiah", "Zynny"],
    ["Kannon", "Jack", "Greg", "Max"],
    ["Jack (sub)", "Jake", "Sam", "Peter"],
]

# Ids that showed up in the weekly groups above but aren't recurring
# league members (one-off substitutes) -- excluded from the calibrated
# roster even though their ranking events are kept for the fit.
SUBSTITUTE_IDS = {"Zynny", "Jack (sub)"}

# Season point totals through week 3, for cross-checking the calibration
# against the sheet's own running standings.
SEASON_TOTALS_THROUGH_WEEK_3: dict[str, int] = {
    "Kannon": 1284,
    "Jack": 1059,
    "Jake": 974,
    "Will": 937,
    "Stu": 876,
    "Sam": 793,
    "Isaiah": 674,
    "Budzy": 635,
    "Greg": 622,
    "Peter": 432,
    "Max": 315,
    "Jorgen": 299,
}
