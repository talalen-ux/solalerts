"""Parlay construction.

Two modes:
  * safe  - no odds needed. Picks the N legs (one per match) with the highest joint win
            probability, skipping near-certain legs that books price below any value
            (max_leg_prob). Shows the FAIR price: only take the parlay if your book pays more.
  * value - needs bookmaker odds. Blends the model with the de-margined market, keeps legs
            with positive edge, and maximises parlay EV subject to a minimum hit chance.
            Stakes by fractional Kelly.

Cross-match legs are treated as independent. Legs on the same match (same-game parlays,
--sgp) are priced jointly from the score matrix, so "Home win + Over 2.5" is the true
probability of both, not the product.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from . import markets
from .data import Match

DEFAULT_CODES = ["H", "A", "D", "1X", "X2", "12", "BTTS_Y", "BTTS_N", "O1.5", "O2.5", "U2.5",
                 "U3.5", "O3.5", "HO0.5", "AO0.5", "HO1.5", "AO1.5", "H_WTN", "A_WTN"]


@dataclass
class MatchPrediction:
    match: Match
    matrix: np.ndarray
    xg: tuple[float, float]
    probs: dict[str, float] = field(default_factory=dict)
    odds: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if not self.probs:
            self.probs = markets.all_probs(self.matrix)

    @property
    def title(self) -> str:
        return f"{self.match.home} v {self.match.away}"


@dataclass
class Leg:
    pred: MatchPrediction
    codes: tuple[str, ...]
    model_prob: float
    prob: float                  # probability used for decisions (blended when odds exist)
    odds: float | None = None    # bookmaker decimal odds, if known

    @property
    def code(self) -> str:
        return "+".join(self.codes)

    @property
    def fair_odds(self) -> float:
        return 1 / self.prob

    @property
    def edge(self) -> float | None:
        return None if self.odds is None else self.prob * self.odds - 1

    def describe(self) -> str:
        m = self.pred.match
        return " & ".join(markets.BY_CODE[c].describe(m.home, m.away) for c in self.codes)


@dataclass
class Parlay:
    legs: list[Leg]

    @property
    def prob(self) -> float:
        return math.prod(l.prob for l in self.legs)

    @property
    def model_prob(self) -> float:
        return math.prod(l.model_prob for l in self.legs)

    @property
    def fair_odds(self) -> float:
        return 1 / self.prob

    @property
    def odds(self) -> float | None:
        if any(l.odds is None for l in self.legs):
            return None
        return math.prod(l.odds for l in self.legs)

    @property
    def ev(self) -> float | None:
        o = self.odds
        return None if o is None else self.prob * o - 1

    def kelly(self, fraction: float = 0.25) -> float | None:
        o, ev = self.odds, self.ev
        if o is None or ev is None or ev <= 0:
            return None
        return fraction * ev / (o - 1)


def _blend(model_p: float, market_p: float | None, weight: float) -> float:
    if market_p is None:
        return model_p
    return weight * model_p + (1 - weight) * market_p


def candidate_legs(preds: list[MatchPrediction], codes=None, min_leg_prob=0.55,
                   max_leg_prob=0.90, sgp=False, model_weight=0.6, require_odds=False,
                   min_edge=0.0, per_match=None) -> list[Leg]:
    codes = codes or DEFAULT_CODES
    out = []
    for p in preds:
        implied = markets.implied_probs(p.odds) if p.odds else {}
        legs = []
        combos = [(c,) for c in codes]
        if sgp:
            for a, b in itertools.combinations(codes, 2):
                pa, pb, pab = p.probs[a], p.probs[b], markets.prob(p.matrix, a, b)
                # skip redundant pairs (one implies the other) and impossible ones
                if pab > 0.02 and pab < min(pa, pb) - 0.03:
                    combos.append((a, b))
        for combo in combos:
            mp = markets.prob(p.matrix, *combo)
            key = "+".join(combo)
            o = p.odds.get(key)
            if require_odds and o is None:
                continue
            prob = _blend(mp, implied.get(key) if len(combo) == 1 else None, model_weight)
            if not (min_leg_prob <= prob <= max_leg_prob):
                continue
            leg = Leg(p, combo, mp, prob, o)
            if require_odds and leg.edge < min_edge:
                continue
            legs.append(leg)
        score = (lambda l: math.log(l.prob * l.odds)) if require_odds else (lambda l: math.log(l.prob))
        legs.sort(key=score, reverse=True)
        out += legs[:per_match] if per_match else legs
    return out


def build_parlays(legs: list[Leg], n_legs: int, mode: str = "safe", top: int = 5,
                  min_parlay_prob: float = 0.10, min_fair_odds: float = 1.0,
                  beam: int = 300) -> list[Parlay]:
    """Beam search over one-leg-per-match combinations."""
    if mode == "value":
        score = lambda l: math.log(l.prob * l.odds)  # noqa: E731  log EV growth
    else:
        score = lambda l: math.log(l.prob)  # noqa: E731
    legs = sorted(legs, key=score, reverse=True)
    target_p = 1 / min_fair_odds
    floor_leg = min((l.prob for l in legs), default=1.0)
    # state: (score, chosen legs, index of last leg) - ordered so each set appears once
    states: list[tuple[float, list[Leg], int]] = [(0.0, [], -1)]
    for step in range(n_legs):
        nxt = []
        for s, chosen, last in states:
            used = {id(l.pred) for l in chosen}
            p_so_far = math.prod(x.prob for x in chosen)
            for i in range(last + 1, len(legs)):
                l = legs[i]
                if id(l.pred) in used:
                    continue
                p_new = p_so_far * l.prob
                if mode == "value" and p_new < min_parlay_prob:
                    continue
                # keep only states that can still get down to the price floor
                if p_new * floor_leg ** (n_legs - step - 1) > target_p:
                    continue
                nxt.append((s + score(l), chosen + [l], i))
        if step == n_legs - 1:  # apply the price floor before truncating the final beam
            nxt = [x for x in nxt if 1 / math.prod(l.prob for l in x[1]) >= min_fair_odds]
        if mode == "safe" and min_fair_odds > 1 and step < n_legs - 1:
            # steer toward an even split of the price across legs so the last legs are not
            # forced to be long shots: each leg aims for target_p ** (1/n)
            goal = (step + 1) * math.log(target_p) / n_legs
            nxt.sort(key=lambda x: abs(math.log(math.prod(l.prob for l in x[1])) - goal))
        else:
            nxt.sort(key=lambda x: x[0], reverse=True)
        states = nxt[:beam]
        if not states:
            return []
    results = [Parlay(c) for _, c, _ in states]
    if mode == "value":
        results = [r for r in results if r.ev is not None and r.ev > 0]

    picked: list[Parlay] = []  # diversify: each new parlay shares at most n-1 matches
    for r in results:
        ids = {id(l.pred) for l in r.legs}
        if all(len(ids & {id(l.pred) for l in q.legs}) < max(1, n_legs - 1) or n_legs == 1
               for q in picked):
            picked.append(r)
        if len(picked) >= top:
            break
    return picked
