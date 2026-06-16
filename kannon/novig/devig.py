"""
Devigging engine: removes bookmaker margin from sharp-book odds to get
true probabilities, then computes EV for make bets.

Primary method: Power devigging (Šin / power method).
  - Finds exponent c > 1 such that sum(p_i ^ c) = 1, where p_i are the raw
    implied probabilities from the book.
  - Handles favourite-longshot bias correctly; the industry standard for
    devigging sharp books like Pinnacle.
  - Implemented via bisection — no external dependencies.

Secondary method: Multiplicative (proportional) devigging.
  - Scales each implied prob by 1/total. Simpler but slightly biased
    toward favourites.
"""
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Odds conversions ─────────────────────────────────────────────────────────

def american_to_implied(american: int | float) -> float:
    """Convert American odds to raw implied probability."""
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def american_to_decimal(american: int | float) -> float:
    if american > 0:
        return american / 100.0 + 1.0
    return 100.0 / abs(american) + 1.0


def implied_to_american(prob: float) -> int:
    """Convert true probability to American odds (rounded to nearest integer)."""
    if not (0.0 < prob < 1.0):
        raise ValueError(f"Probability must be in (0, 1), got {prob:.6f}")
    if prob >= 0.5:
        return int(round(-(prob / (1.0 - prob)) * 100.0))
    return int(round(((1.0 - prob) / prob) * 100.0))


# ── Devigging ─────────────────────────────────────────────────────────────────

def devig_power(odds_by_outcome: dict[str, int | float]) -> dict[str, float]:
    """
    Power-method devigging.

    Finds exponent c > 1 such that sum(p_i ^ c) = 1, then returns
    {outcome: p_i ^ c / sum(p_j ^ c)} as fair probabilities.

    Args:
        odds_by_outcome: {outcome_name: american_odds}

    Returns:
        {outcome_name: true_probability}
    """
    if not odds_by_outcome:
        return {}

    outcomes = list(odds_by_outcome.keys())
    implied = [american_to_implied(odds_by_outcome[o]) for o in outcomes]
    total = sum(implied)

    if abs(total - 1.0) < 1e-8:
        return dict(zip(outcomes, implied))

    if total < 1.0:
        logger.warning(
            "Implied probs sum to %.4f < 1 (negative-vig book). "
            "Falling back to multiplicative method.", total
        )
        return devig_multiplicative(odds_by_outcome)

    # f(c) = sum(p_i ^ c) - 1 = 0  (f is monotone decreasing for p_i in (0,1))
    # f(1) = total - 1 > 0, so we need c > 1.
    def f(c: float) -> float:
        return sum(p ** c for p in implied) - 1.0

    lo, hi = 1.0, 2.0
    for _ in range(60):          # expand upper bound if needed
        if f(hi) < 0:
            break
        hi = min(hi * 2.0, 1_000.0)

    for _ in range(120):         # bisect to 1e-12 precision
        mid = (lo + hi) / 2.0
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break

    c = (lo + hi) / 2.0
    fair = [p ** c for p in implied]
    s = sum(fair)
    return dict(zip(outcomes, [p / s for p in fair]))


def devig_multiplicative(odds_by_outcome: dict[str, int | float]) -> dict[str, float]:
    """
    Multiplicative (proportional) devigging.
    Scales all implied probs uniformly so they sum to 1.
    """
    if not odds_by_outcome:
        return {}
    outcomes = list(odds_by_outcome.keys())
    implied = [american_to_implied(odds_by_outcome[o]) for o in outcomes]
    total = sum(implied)
    return dict(zip(outcomes, [p / total for p in implied]))


def blend_fair_values(
    fair_values: list[dict[str, float]],
    weights: list[float],
) -> dict[str, float]:
    """
    Weighted blend of fair-value dicts from multiple books.

    Outcomes absent from a particular book are excluded from that book's
    contribution but still appear in the result (weighted by books that
    do have them).
    """
    if not fair_values:
        return {}
    total_w = sum(weights)
    norm_w = [w / total_w for w in weights]

    all_outcomes: set[str] = set()
    for fv in fair_values:
        all_outcomes.update(fv)

    blended: dict[str, float] = {}
    for outcome in all_outcomes:
        wsum, wt = 0.0, 0.0
        for fv, w in zip(fair_values, norm_w):
            if outcome in fv:
                wsum += fv[outcome] * w
                wt += w
        if wt > 0:
            blended[outcome] = wsum / wt

    return blended


# ── EV calculation ────────────────────────────────────────────────────────────

def calc_ev(true_prob: float, american_odds: int | float, fee_rate: float = 0.0) -> float:
    """
    Expected value of a bet as a decimal (0.05 = 5% EV).

    EV = true_prob × decimal_odds × (1 - fee_rate) - 1

    Args:
        true_prob:     Devvigged probability of winning (0–1).
        american_odds: Odds we will receive if the bet is accepted.
        fee_rate:      Platform commission on winnings (e.g. 0.02 for 2%).

    Returns:
        EV as a fraction of the stake (positive = +EV).
    """
    decimal = american_to_decimal(american_odds)
    net_decimal = 1.0 + (decimal - 1.0) * (1.0 - fee_rate)
    return true_prob * net_decimal - 1.0


def min_odds_for_ev(
    true_prob: float,
    target_ev: float = 0.05,
    fee_rate: float = 0.0,
) -> int:
    """
    Minimum American odds needed so that EV >= target_ev.

    Used to determine the lowest acceptable line to post as a maker.
    """
    # EV = p × (1 + (d-1)×(1-f)) - 1 ≥ target_ev
    # (d-1) ≥ (1 + target_ev - p) / (p × (1-f))
    # d ≥ 1 + (1 + target_ev - p) / (p × (1-f))
    if true_prob <= 0:
        raise ValueError("true_prob must be > 0")
    net_factor = 1.0 - fee_rate
    if net_factor <= 0:
        raise ValueError("fee_rate must be < 1")
    min_decimal = 1.0 + (1.0 + target_ev - true_prob) / (true_prob * net_factor)
    return implied_to_american(1.0 / min_decimal)


def better_odds(base: int, step: int = 5) -> int:
    """
    Return odds slightly better than `base` for the bettor.
    For positive odds: add step. For negative: reduce absolute value by step.
    """
    if base > 0:
        return base + step
    return min(base + step, -101)   # keep at least -101
