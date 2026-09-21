# Beerio Kart League Predictor

A Monte Carlo simulator/predictor for a 16-player Mario Kart Wii drinking
league. Give it player skill ratings (or leave them equal) and it will
simulate the season thousands of times to estimate each player's odds of
making the playoffs, reaching the final, and winning it all.

## League structure implemented

- **16 players**, split into **4 groups of 4 that are redrawn every
  month** (`data/schedule.py`) — nobody faces the same opponent twice
  across the 3 monthly rounds, which is what "no player plays another more
  than once in league play" means here. A player's season score is the sum
  of their own points across those 3 (different-opponent) matches ("total
  points over your 3 placement matches").
- Each match is a full Mario Kart Wii GP session: **32 races** (8 cups × 4
  tracks). Every individual race is a full **12-racer field** — the 4
  human players plus **8 CPU racers** filling out the rest of the grid —
  scored on MKWii's real 12-place points table (**15/12/10/8/7/6/5/4/3/2/1/0**).
  A human can land anywhere from 1st to 12th depending on the other 3
  humans *and* the CPU field that race, which is what lets a weak
  player's match total drop into single/double digits while a strong
  player can approach (but rarely hit) the 15×32 = 480 max.
- **The beer rule**: each player drinks **8 beers across the 32 races** in
  every match, at their own self-chosen pace — not assigned by anything
  external. (The league's own "random selector" just shuffles which order
  the 32 races are played in; since races are otherwise symmetric here,
  that ordering has no effect on the simulation and isn't modeled
  separately.) There's no data on any individual's real pacing habits, and
  pace clearly varies person to person, so each player's beer timing is
  drawn independently at random — a stand-in for that unknown personal
  pacing. Each beer adds "impairment" that decays a bit every race
  (sobering up) but drags down that player's effective skill for the rest
  of the session while it's elevated.
- **Playoffs**: the **top 8 of all 16 players** by total season points
  qualify, seeded 1-8 directly by that total (there's no group-standings
  step — groups don't persist long enough to have their own). Seeds
  **{1, 2, 7, 8}** play one 4-player match; seeds **{3, 4, 5, 6}** play a
  second 4-player match (the "semifinal"). The **top 2 finishers from each
  of those two matches** (4 players total) advance to a single
  **winner-take-all final** match — highest score wins the league.
- Every match (league or playoff) is its own fresh 32-race session: beer
  count and impairment reset to zero each time.

These are the concrete choices made to turn the stated rules into code —
see "Assumptions worth double-checking" below if any of them don't match
how your league actually runs; they're all one-line changes.

## How races are simulated

Each race's finishing order is drawn from a **Plackett-Luce model**: every
player's effective (post-beer) skill implies a win probability
proportional to that skill, and the model samples a full 1st-4th ranking
consistent with those probabilities in one pass (the Gumbel-max trick).
A `chaos_scale` knob adds extra randomness on top of skill, standing in for
the game's own chaos (items, blue shells, bananas) — turn it up to make
skill matter less, down to make it matter more.

## Usage

```bash
# Monte Carlo prediction table over 10,000 simulated seasons, equal-skill default roster
python3 -m beerio_kart.cli

# Use your own roster (names + skill ratings), more simulations, reproducible seed
python3 -m beerio_kart.cli --config beerio_kart/config/players.yaml --sims 20000 --seed 42

# Print one full simulated season instead (league standings, seeding, bracket, champion)
python3 -m beerio_kart.cli --config beerio_kart/config/players.yaml --verbose --seed 1

# Tune the model
python3 -m beerio_kart.cli --beers-per-player 6 --impairment-coef 0.2 --chaos-scale 1.5
```

Edit `beerio_kart/config/players.yaml` with your real players' names and
skills (a flat 16-player list). `skill` is an arbitrary rating (like Elo) —
only the differences between players matter, 1000 is a reasonable
"average." If you don't have real skill priors yet, leave everyone equal:
the model then shows how much of the season is pure race/beer luck. An
optional `schedule:` section lets you specify the real monthly groups;
omit it and a generic (but still validated — nobody repeats an opponent)
3-month rotation is generated automatically.

Run the test suite:

```bash
python3 -m unittest discover -s beerio_kart/tests -p "test_*.py"
```

## Assumptions worth double-checking

The prompt left a few specifics unstated; these are the calls made, each
isolated to one file so they're easy to change:

- **Playoff seeding uses raw season point totals across all 16 players**
  (`playoffs.py: seed_playoffs`), even though players faced
  different-strength opposition each month.
- **Seeds {1,2,7,8} race as one 4-player free-for-all**, best 2 of the 4
  advance — same format as every other match in the league (confirmed;
  not two separate 1-on-1 races).
- **Beer scheduling is independent per player** — each of the 4 racers in
  a match gets their own random set of 8 "drink now" races out of 32,
  rather than one shared schedule for the table. (`beer.py`)
- **Impairment model** (`match.py`): a beer adds 1 unit of impairment,
  impairment decays 15% per race, and effective skill scales down by
  `exp(-0.12 * impairment)`. These constants (`impairment_coef`,
  `decay_rate`) are guesses at "how much does getting drunk actually hurt
  your Mario Kart", tune them with `--impairment-coef` or in `MatchConfig`.
- **`cpu_skill = 200`** (and `chaos_scale = 1.15`, up from an earlier
  default of `1.0`): fit by hand against two real recorded matches
  (Kannon/Jack/Christian/Peter and Isaiah/Harrison/Cailin/Ivan) so
  simulated totals land in the same range as those two actually did.
  It's one CPU skill level for every race regardless of who's driving —
  real MKWii CPU difficulty may itself vary — so treat this as a
  reasonable single-number stand-in, not a precise fit. Tune with
  `--cpu-skill` if simulated match totals start looking off (too many
  huge or tiny scores relative to what your league is actually seeing).

## Performance

10,000 simulated seasons (16 players × up to 6 matches of 32 races each,
plus playoffs) takes roughly 25-30s in pure Python on a single core. Use
`--sims` to trade off precision for speed.
