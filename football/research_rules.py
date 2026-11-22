"""Rules taken from the parlay literature (see football/research/LITERATURE.md).

Whelan (2026), "The Parlay Puzzle": for a bettor WITH an edge on every leg, the leg count that
maximises expected utility depends almost only on the geometric-mean leg probability p, not on
risk aversion or edge size. N+1 legs beat N legs once p passes the root of
    (2N+1) p^(N+1) - (N+1)^2 p + N^2 = 0        (his eq. A.26)
which reproduces his Table 2 to within 0.003 (2 legs from p=1/3, 3 from 0.525, 5 from 0.70,
10 from 0.845). Without an edge no leg count is justified: expected return is (1-m)^N.
"""

from __future__ import annotations

import math
from functools import lru_cache


@lru_cache(maxsize=None)
def leg_threshold(n_legs: int) -> float:
    """Smallest geometric-mean leg probability at which n_legs beats n_legs - 1."""
    if n_legs <= 1:
        return 0.0
    n = n_legs - 1
    f = lambda p: (2 * n + 1) * p ** (n + 1) - (n + 1) ** 2 * p + n ** 2
    lo, hi = 0.0, 1 - 1e-6          # f(0) > 0; p = 1 is a trivial root, so stop just below it
    step = 1e-3
    a = lo
    while a + step < hi and f(a + step) > 0:
        a += step
    b = a + step
    for _ in range(50):
        m = (a + b) / 2
        a, b = (m, b) if f(m) > 0 else (a, m)
    return a


def max_legs(geo_mean_prob: float, cap: int = 40) -> int:
    """Longest parlay the rule supports for legs averaging geo_mean_prob (given an edge)."""
    n = 1
    while n < cap and geo_mean_prob >= leg_threshold(n + 1):
        n += 1
    return n


def near_miss_prob(leg_probs) -> float:
    """Chance that exactly one leg loses (Whelan: the "so close" result that keeps bettors coming back)."""
    total = math.prod(leg_probs)
    return sum(total / p * (1 - p) for p in leg_probs)


def check(leg_probs) -> dict:
    n = len(leg_probs)
    geo = math.prod(leg_probs) ** (1 / n)
    return {"geo_mean": round(geo, 4), "max_legs": max_legs(geo), "within_rule": n <= max_legs(geo),
            "near_miss": round(near_miss_prob(leg_probs), 4)}
