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
  here under a distinct id ``Zynny`` (not merged into Budzy/Jackson) so
  that game isn't credited to a driver who didn't play it.
- Week 3, group 3 lists "Jack (sub)" scoring 415 -- since the real Jack
  already has his own (different, lower) result in group 2 that week,
  this is someone else subbing under Jack's name. Recorded under a
  distinct id ``Jack (sub)`` so it doesn't get merged into Jack's rating.
- "Budzy" (season 1) and "Jackson" (season 1 playoffs, season 2) are
  confirmed to be the same person. All of "Budzy"'s season-1 results
  below are recorded under the id ``Jackson`` -- the name he's known by
  in the current season's groups -- so his full history counts as one
  driver instead of splitting his sample between two ids.

Both one-off substitute ids are kept in the ranking events (they still
carry information about how the *other* three racers in their group did
that day) but are excluded from the final calibrated roster -- see
``build_roster_from_history.py``.

Two more batches were added after the initial transcription, both
provided directly by the user rather than pulled from the sheet:

- ``SEASON_1_PLAYOFF_RESULTS``: last season's playoffs. This is a strong
  real-world confirmation of the bracket structure the simulator models
  (``playoffs.py``): an 8-player field splits into two 4-player semis,
  and the top 2 from *each* semi (not just the semis' outright winners)
  advance to a single 4-player final. In the final, Will raced in Jake's
  slot ("Will (subbing for Jake)") -- recorded under Will's own id since
  it's genuinely his result, not Jake's.
- ``SEASON_2_WEEK_1_RESULTS``: the first week of the new season, with 4
  new drivers (Christian, Harrison, Cailin, Ivan) added to the returning
  core.

Group D (Will, Stu, Maclane, Luke) completes the 16-player/4-group
target structure. Maclane and Luke have no race history -- they've never
appeared in a tracked group -- so the Plackett-Luce fit has nothing to
estimate their skill from. Per the league's own read on them ("probably
somewhere between Ivan and Cailin"), ``MANUAL_SKILL_ESTIMATES`` overrides
their skill directly rather than leaving them out or defaulting them to
the field average; ``build_roster_from_history.py`` applies it after the
fit. Replace it with a real rating as soon as they've actually raced.
"""
from __future__ import annotations

# Each entry: one race group's results for one week, ordered best (most
# points) to worst. This is exactly the "ranking" format
# calibrate.fit_plackett_luce expects.
SEASON_1_WEEKLY_RESULTS: list[list[str]] = [
    # Week 1
    ["Kannon", "Jack", "Jake", "Sam"],
    ["Greg", "Isaiah", "Jackson", "Jorgen"],  # "Budzy" in the sheet -- see note above
    ["Will", "Stu", "Peter", "Max"],
    # Week 2
    ["Jake", "Jackson", "Greg", "Max"],  # "Budzy" in the sheet -- see note above
    ["Jack", "Sam", "Stu", "Isaiah"],
    ["Kannon", "Will", "Jorgen", "Peter"],
    # Week 3
    ["Will", "Stu", "Isaiah", "Zynny"],
    ["Kannon", "Jack", "Greg", "Max"],
    ["Jack (sub)", "Jake", "Sam", "Peter"],
]

SEASON_1_PLAYOFF_RESULTS: list[list[str]] = [
    ["Kannon", "Jack", "Isaiah", "Jackson"],  # semi 1 (seeds 1,2,7,8)
    ["Jake", "Stu", "Will", "Sam"],  # semi 2 (seeds 3-6)
    ["Kannon", "Jack", "Stu", "Will"],  # final -- Will subbed for Jake
]

SEASON_2_WEEK_1_RESULTS: list[list[str]] = [
    ["Kannon", "Jack", "Christian", "Peter"],
    ["Sam", "Jackson", "Max", "Jorgen"],
    ["Isaiah", "Harrison", "Cailin", "Ivan"],
]

# Every ranking event available, in chronological order -- what
# build_roster_from_history.py fits skills against by default.
ALL_RANKING_EVENTS: list[list[str]] = (
    SEASON_1_WEEKLY_RESULTS + SEASON_1_PLAYOFF_RESULTS + SEASON_2_WEEK_1_RESULTS
)

# Ids that showed up in the results above but aren't recurring league
# members (one-off substitutes) -- excluded from the calibrated roster
# even though their ranking events are kept for the fit.
SUBSTITUTE_IDS = {"Zynny", "Jack (sub)"}

# Season point totals through week 3 of season 1, for cross-checking the
# calibration against the sheet's own running standings.
SEASON_TOTALS_THROUGH_WEEK_3: dict[str, int] = {
    "Kannon": 1284,
    "Jack": 1059,
    "Jake": 974,
    "Will": 937,
    "Stu": 876,
    "Sam": 793,
    "Isaiah": 674,
    "Jackson": 635,  # "Budzy" in the sheet -- see note above
    "Greg": 622,
    "Peter": 432,
    "Max": 315,
    "Jorgen": 299,
}

# This season's groups, now complete at 4 groups of 4.
SEASON_2_GROUPS: dict[str, list[str]] = {
    "A": ["Kannon", "Jack", "Christian", "Peter"],
    "B": ["Sam", "Jackson", "Max", "Jorgen"],
    "C": ["Isaiah", "Harrison", "Cailin", "Ivan"],
    "D": ["Will", "Stu", "Maclane", "Luke"],
}

# Skill overrides for drivers with no race history to fit from -- see the
# module docstring. Applied on top of the Plackett-Luce fit, not blended
# with it.
MANUAL_SKILL_ESTIMATES: dict[str, float] = {
    "Maclane": 826.0,  # midpoint of fitted Ivan/Cailin skill
    "Luke": 826.0,  # midpoint of fitted Ivan/Cailin skill
}
