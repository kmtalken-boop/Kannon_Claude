# Beerio Kart League Predictor

A Monte Carlo simulator/predictor for a 16-player Mario Kart Wii drinking
league. Give it player skill ratings (or leave them equal) and it will
simulate the season thousands of times to estimate each player's odds of
making the playoffs, reaching the final, and winning it all.

## League structure implemented

- **16 players** split into **4 fixed groups of 4** (A-D).
- **League phase**: each group plays a match once a month for **3 months**,
  always the same 4 group-mates. Since groups never change, no player ever
  races anyone outside their own group — that's what "no player plays
  another more than once in league play" means here. A player's season
  score is the sum of their points across those 3 matches ("total points
  over your 3 placement matches").
- Each match is a full Mario Kart Wii GP session: **32 races** (8 cups × 4
  tracks), scored with MKWii's own points table for a 4-driver field: **1st
  = 15, 2nd = 12, 3rd = 10, 4th = 8**.
- **The beer rule**: each player must drink **8 beers across the 32
  races** in every match. *Which* races trigger each of their 8 beers is
  chosen by a random selector, independently per player. Each beer adds
  "impairment" that decays a bit every race (sobering up) but drags down
  that player's effective skill for the rest of the session while it's
  elevated — so bad luck on the selector (beers bunched up early/late) can
  genuinely tank a session.
- **Playoffs**: top 2 from each group (8 players) qualify and are seeded
  1-8 by total league points, compared directly across groups. Seeds
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
groups. `skill` is an arbitrary rating (like Elo) — only the differences
between players matter, 1000 is a reasonable "average." If you don't have
real skill priors yet, leave everyone equal: the model then shows how much
of the season is pure race/beer luck.

Run the test suite:

```bash
python3 -m unittest discover -s beerio_kart/tests -p "test_*.py"
```

## Assumptions worth double-checking

The prompt left a few specifics unstated; these are the calls made, each
isolated to one file so they're easy to change:

- **Groups are fixed for the whole season** (`roster.py`) rather than
  reshuffled between the 3 monthly matches. This is what makes "no player
  plays another more than once" automatically true.
- **Cross-group playoff seeding uses raw point totals** (`playoffs.py:
  seed_playoffs`), even though groups could face different-strength
  opposition. An alternative would be seeding 1-4 by group winners and 5-8
  by runners-up instead of pure points.
- **"1 and 2 seeds play 7 and 8" is read as one 4-player match** with seeds
  {1,2,7,8} together (not two separate 1-on-1 races), to stay consistent
  with every other match in the league being a 4-driver field.
- **Beer scheduling is independent per player** — each of the 4 racers in
  a match gets their own random set of 8 "drink now" races out of 32,
  rather than one shared schedule for the table. (`beer.py`)
- **Impairment model** (`match.py`): a beer adds 1 unit of impairment,
  impairment decays 15% per race, and effective skill scales down by
  `exp(-0.12 * impairment)`. These constants (`impairment_coef`,
  `decay_rate`) are guesses at "how much does getting drunk actually hurt
  your Mario Kart", tune them with `--impairment-coef` or in `MatchConfig`.

## Performance

10,000 simulated seasons (16 players × up to 6 matches of 32 races each,
plus playoffs) takes roughly 25-30s in pure Python on a single core. Use
`--sims` to trade off precision for speed.
