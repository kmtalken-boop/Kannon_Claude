"""Calibrates player skill ratings from historical results.

Fits a Plackett-Luce model to real ranking data via the standard MM
algorithm (Hunter, 2004, "MM algorithms for generalized Bradley-Terry
models"). This is the *same* ranking model ``race.simulate_race`` uses to
turn skill into a finishing order, so the strengths this produces plug
directly into the simulator's ``skill`` field with no unit conversion --
a fitted strength of 1.4x the field average behaves exactly like a
hand-entered skill of ``1.4 * BASE_SKILL`` would.
"""
from __future__ import annotations


def fit_plackett_luce(
    rankings: list[list[str]], iterations: int = 300, ridge: float = 3.0
) -> dict[str, float]:
    """Fit multiplicative Plackett-Luce strengths from historical rankings.

    ``rankings``: each entry is a list of player ids for one race/match,
    ordered best to worst. Rankings don't need to cover the same players
    or the same number of players -- partial participation (someone
    sitting a week out, a group of 3 instead of 4) is handled natively.

    Returns a strength > 0 per player that appeared at least once,
    normalized so the mean strength across all players is 1.0. A strength
    of 2.0 means "twice as likely to beat a strength-1.0 field member,
    head to head, as a coin flip would predict."

    ``ridge`` is a Bayesian pseudo-count added to every player's
    win/exposure tally so that a player with very few results doesn't
    drift to 0 or infinity -- it pulls thin-sample players back toward
    the field average until more data arrives. The default of 3.0 is
    deliberately on the same order as a handful of weeks of real results:
    with only 2-3 games per player, an early undefeated record shouldn't
    be read as near-certain dominance, so the prior is strong enough to
    meaningfully soften it. It should shrink automatically as more
    history accumulates -- if you tune it, tune it down as the season's
    real sample size grows.
    """
    players = sorted({p for ranking in rankings for p in ranking})
    if not players:
        return {}

    w = {p: 1.0 for p in players}

    for _ in range(iterations):
        wins = {p: ridge for p in players}
        denom = {p: ridge for p in players}

        for ranking in rankings:
            remaining = list(ranking)
            # Plackett-Luce factors a full ranking into a sequence of
            # "who's best among those still remaining" contests: 1st
            # place wins against the whole field, 2nd wins against
            # everyone but 1st, and so on. The last-place finisher never
            # wins a contest, so it contributes no win but still adds to
            # the denominator of every contest it's present for.
            while len(remaining) > 1:
                total_strength = sum(w[p] for p in remaining)
                wins[remaining[0]] += 1.0
                for p in remaining:
                    denom[p] += 1.0 / total_strength
                remaining = remaining[1:]

        w = {p: wins[p] / denom[p] for p in players}
        mean_w = sum(w.values()) / len(w)
        w = {p: v / mean_w for p, v in w.items()}

    return w


def strengths_to_skill(strengths: dict[str, float], base_skill: float = 1000.0) -> dict[str, float]:
    """Rescale fitted strengths (mean 1.0) onto the simulator's skill scale.

    This is a direct linear rescale, not a log transform: fitted
    strengths already are the multiplicative Plackett-Luce parameter that
    ``race.simulate_race`` expects as ``skill``, so `skill_i = base_skill
    * strength_i` reproduces the exact same head-to-head win
    probabilities the fit was estimated from.
    """
    return {p: base_skill * s for p, s in strengths.items()}
