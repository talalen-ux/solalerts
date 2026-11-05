"""Walk-forward backtest: refit every week on data strictly before it, predict that week.

Answers the two questions that matter for parlays:
  1. Are single-selection probabilities calibrated? (a 70% leg should win ~70%)
  2. Do the agent's parlays hit as often as it says they will?
Without historical odds this cannot measure ROI; it measures whether the prices are honest.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from . import data, markets
from .model import DixonColes, DEFAULT_RIDGE, DEFAULT_XI
from .parlay import DEFAULT_CODES, MatchPrediction, build_parlays, candidate_legs


@dataclass
class Record:
    pred: MatchPrediction
    week: date

    def won(self, code: str) -> bool:
        m = self.pred.match
        s = markets.BY_CODE[code]
        return bool(s.mask[min(m.home_goals, markets.MAX_GOALS), min(m.away_goals, markets.MAX_GOALS)])


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def run(leagues: list[str], season: int, legs: int = 3, min_leg_prob: float = 0.55,
        max_leg_prob: float = 0.90, sgp: bool = False, min_odds: float = 1.0, xi: float = DEFAULT_XI,
        ridge: float = DEFAULT_RIDGE, seasons_history: int = 2, progress=None) -> dict:
    records: list[Record] = []
    baseline = {}
    for lg in leagues:
        ms = data.load_league(lg, season, seasons_history + 1)
        target = [m for m in ms if m.played and date(season, 7, 1) <= m.date < date(season + 1, 7, 1)]
        prior = [m for m in ms if m.played and m.date < date(season, 7, 1)]
        if not target or len(prior) < 30:
            continue
        n = len(prior)
        baseline[lg] = {
            "H": sum(m.home_goals > m.away_goals for m in prior) / n,
            "D": sum(m.home_goals == m.away_goals for m in prior) / n,
            "A": sum(m.home_goals < m.away_goals for m in prior) / n,
            "O2.5": sum(m.home_goals + m.away_goals > 2 for m in prior) / n,
            "BTTS_Y": sum(m.home_goals > 0 and m.away_goals > 0 for m in prior) / n,
        }
        weeks = sorted({_monday(m.date) for m in target})
        for w in weeks:
            model = DixonColes(xi=xi, ridge=ridge).fit(ms, w, lg)
            for m in target:
                if w <= m.date < w + timedelta(days=7):
                    records.append(Record(MatchPrediction(
                        m, model.score_matrix(m.home, m.away), model.expected_goals(m.home, m.away)), w))
        if progress:
            progress(lg, len(target))
    return summarise(records, baseline, legs, min_leg_prob, max_leg_prob, sgp, min_odds)


def _logloss(p: float) -> float:
    return -math.log(max(p, 1e-12))


def summarise(records, baseline, legs, min_leg_prob, max_leg_prob, sgp, min_odds=1.0) -> dict:
    out: dict = {"matches": len(records)}
    if not records:
        return out

    # 1X2 and binary markets: model vs. base-rate baseline
    metrics = {}
    for name, codes in (("1X2", ["H", "D", "A"]), ("Over 2.5", ["O2.5"]), ("BTTS", ["BTTS_Y"])):
        ll_m = ll_b = br_m = br_b = 0.0
        for r in records:
            base = baseline[r.pred.match.league]
            if len(codes) == 1:
                c = codes[0]
                y = r.won(c)
                pm, pb = r.pred.probs[c], base[c]
                ll_m += _logloss(pm if y else 1 - pm); ll_b += _logloss(pb if y else 1 - pb)
                br_m += (pm - y) ** 2; br_b += (pb - y) ** 2
            else:
                for c in codes:
                    y = r.won(c)
                    if y:
                        ll_m += _logloss(r.pred.probs[c]); ll_b += _logloss(base[c])
                    br_m += (r.pred.probs[c] - y) ** 2; br_b += (base[c] - y) ** 2
        n = len(records)
        metrics[name] = {"logloss": ll_m / n, "logloss_baseline": ll_b / n,
                         "brier": br_m / n, "brier_baseline": br_b / n}
    out["markets"] = metrics

    # calibration over every selection the parlay builder may use
    bins = defaultdict(lambda: [0, 0.0, 0])
    for r in records:
        for c in DEFAULT_CODES:
            p = r.pred.probs[c]
            if p < 0.5:
                continue
            b = min(int(p * 10), 9) / 10
            bins[b][0] += 1; bins[b][1] += p; bins[b][2] += r.won(c)
    out["calibration"] = [{"bin": f"{b:.0%}-{b + 0.1:.0%}", "n": n, "predicted": s / n, "actual": w / n}
                          for b, (n, s, w) in sorted(bins.items())]

    # parlay simulation: best safe parlay each week, pooled across leagues
    by_week = defaultdict(list)
    for r in records:
        by_week[r.week].append(r)
    sims = []
    for w, rs in sorted(by_week.items()):
        cands = candidate_legs([r.pred for r in rs], min_leg_prob=min_leg_prob,
                               max_leg_prob=max_leg_prob, sgp=sgp)
        best = build_parlays(cands, legs, mode="safe", top=1, min_fair_odds=min_odds)
        if not best:
            continue
        p = best[0]
        lookup = {id(r.pred): r for r in rs}
        leg_hits = [all(lookup[id(l.pred)].won(c) for c in l.codes) for l in p.legs]
        sims.append({"week": w.isoformat(), "prob": p.prob, "hit": all(leg_hits),
                     "legs_won": sum(leg_hits), "legs": [f"{l.pred.title}: {l.describe()}" for l in p.legs]})
    if sims:
        n = len(sims)
        out["parlays"] = {
            "n": n, "legs": legs,
            "predicted_hit_rate": sum(s["prob"] for s in sims) / n,
            "actual_hit_rate": sum(s["hit"] for s in sims) / n,
            "avg_fair_odds": sum(1 / s["prob"] for s in sims) / n,
            "leg_predicted": sum(s["prob"] ** (1 / legs) for s in sims) / n,
            "leg_actual": sum(s["legs_won"] for s in sims) / (n * legs),
            # flat 1-unit stakes at the model's own fair odds: ~0 if probabilities are honest
            "fair_odds_pnl": sum((1 / s["prob"] - 1) if s["hit"] else -1 for s in sims),
            "weeks": sims,
        }
    return out
