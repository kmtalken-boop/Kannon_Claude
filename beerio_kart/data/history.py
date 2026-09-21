"""Real historical league results, transcribed from the league's Google
Sheet (season standings + weekly group breakdowns).

This module only exists to feed real results into
``calibrate.fit_plackett_luce`` for skill estimation -- it is not read by
the season simulator itself (that runs off ``data/schedule.py`` and
``config/players_calibrated.yaml`` instead). Season 1's groups reshuffled
every week among 12 recurring drivers; season 2 (16 drivers) reshuffles
every month instead -- see ``data/schedule.py``.

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

Will, Stu, Maclane, and Luke complete the 16-player roster (see
``data/schedule.py``: ``SEASON_2_SCHEDULE``). Maclane and Luke never
appeared in a tracked race, so the Plackett-Luce fit alone has nothing to
estimate their skill from -- ``SEASON_2_EXPERT_RANKING`` (the league's own
full-roster ranking) is what gives them a real fitted skill instead of a
flat guess, the same as everyone else.
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

# The league's own full-field ranking of all 16 current players, given
# directly rather than pulled from a race. Fed into the same
# Plackett-Luce fit as an extra ranking event (best to worst) instead of
# being applied as separate hand-tuned overrides -- one full 16-player
# ranking is far more information-dense than any single 4-player race (15
# pairwise "stages" instead of 3), which is why a moderate weight on it
# goes a long way. This is also what lets Maclane and Luke -- no race
# history at all -- get a real fitted skill instead of a flat manual
# guess: they now appear in a ranking event like everyone else.
SEASON_2_EXPERT_RANKING: list[str] = [
    "Kannon", "Jack", "Sam", "Will", "Stu", "Isaiah", "Jackson", "Christian",
    "Max", "Harrison", "Peter", "Jorgen", "Cailin", "Maclane", "Luke", "Ivan",
]

# Every ranking event available, in chronological order -- what
# build_roster_from_history.py fits skills against by default.
ALL_RANKING_EVENTS: list[list[str]] = (
    SEASON_1_WEEKLY_RESULTS
    + SEASON_1_PLAYOFF_RESULTS
    + SEASON_2_WEEK_1_RESULTS
    + [SEASON_2_EXPERT_RANKING]
)

# Recency/confidence weight per event above (same order, same length) --
# how much each ranking counts in the Plackett-Luce fit. Season 1 results
# get the baseline weight; season 2 results and the league's own ranking
# both count 6x as much ("heavily weight this season versus last"), so
# recent play and the league's own read dominate the fit while real
# point margins still shape the exact skill gaps within that order. Tune
# these down over the course of the season as season 2 stops being
# "recent" and becomes most of the sample on its own.
SEASON_1_RECENCY_WEIGHT = 1.0
SEASON_2_RECENCY_WEIGHT = 6.0
EXPERT_RANKING_WEIGHT = 6.0
ALL_RANKING_WEIGHTS: list[float] = (
    [SEASON_1_RECENCY_WEIGHT] * len(SEASON_1_WEEKLY_RESULTS)
    + [SEASON_1_RECENCY_WEIGHT] * len(SEASON_1_PLAYOFF_RESULTS)
    + [SEASON_2_RECENCY_WEIGHT] * len(SEASON_2_WEEK_1_RESULTS)
    + [EXPERT_RANKING_WEIGHT]
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

# Skill overrides for drivers with no race history to fit from at all --
# left empty now that SEASON_2_EXPERT_RANKING covers every current
# player (Maclane and Luke included), which is a better source for this
# than a flat guess. Keep the mechanism for the next genuinely
# history-less player who joins before the league's ranking is updated.
MANUAL_SKILL_ESTIMATES: dict[str, float] = {}

# Multiplicative "current form" adjustments for drivers whose real skill
# has moved beyond what the weighted fit alone captures. Left empty now
# that SEASON_2_EXPERT_RANKING (which explicitly placed Max above
# Harrison, Peter, and Jorgen) supersedes the old one-off Max multiplier
# -- keep the mechanism for a future case the ranking doesn't cover.
FORM_ADJUSTMENTS: dict[str, float] = {}
