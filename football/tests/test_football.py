"""Offline tests: synthetic leagues, no network."""

import math
import random
from datetime import date, timedelta

import numpy as np
import pytest

from football import markets
from football.data import Match, TeamResolver, norm_name
from football.model import DixonColes
from football.parlay import MatchPrediction, build_parlays, candidate_legs


def synthetic_league(seed=0, seasons=2, strengths=None):
    rng = np.random.default_rng(seed)
    teams = [f"Team {c}" for c in "ABCDEFGHIJ"]
    strengths = strengths or {t: s for t, s in zip(teams, np.linspace(0.5, -0.5, len(teams)))}
    out, d = [], date(2024, 8, 10)
    for _ in range(seasons):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                lam = math.exp(0.15 + 0.25 + strengths[h] - strengths[a] * 0.5)
                mu = math.exp(0.15 + strengths[a] - strengths[h] * 0.5)
                out.append(Match("EPL", d, h, a, int(rng.poisson(lam)), int(rng.poisson(mu))))
                d += timedelta(days=1)
    return out, teams


def test_score_matrix_is_a_distribution():
    ms, teams = synthetic_league()
    m = DixonColes().fit(ms, date(2027, 1, 1))
    M = m.score_matrix(teams[0], teams[-1])
    assert M.shape == (11, 11)
    assert abs(M.sum() - 1) < 1e-9 and (M >= 0).all()


def test_model_recovers_team_order():
    ms, teams = synthetic_league(seasons=4)
    m = DixonColes(ridge=1.0).fit(ms, date(2030, 1, 1))
    order = [t for t, *_ in m.table()]
    assert order[0] in teams[:2] and order[-1] in teams[-2:]
    assert m.home_adv > 0.1
    p = markets.all_probs(m.score_matrix(teams[0], teams[-1]))
    assert p["H"] > 0.6 and p["A"] < 0.15


def test_fit_ignores_future_matches():
    ms, teams = synthetic_league()
    cutoff = ms[50].date
    a = DixonColes().fit(ms, cutoff)
    b = DixonColes().fit(ms[:50], cutoff)
    assert a.mu == pytest.approx(b.mu)


def test_market_identities():
    ms, teams = synthetic_league()
    M = DixonColes().fit(ms, date(2027, 1, 1)).score_matrix(teams[2], teams[5])
    p = markets.all_probs(M)
    assert p["H"] + p["D"] + p["A"] == pytest.approx(1)
    assert p["1X"] == pytest.approx(p["H"] + p["D"])
    assert p["O2.5"] + p["U2.5"] == pytest.approx(1)
    assert p["BTTS_Y"] + p["BTTS_N"] == pytest.approx(1)
    # same-game pricing: contradictory selections are impossible, nested ones collapse
    assert markets.prob(M, "H", "A") == 0
    assert markets.prob(M, "H_WTN", "H") == pytest.approx(p["H_WTN"])
    assert markets.prob(M, "H", "O2.5") <= min(p["H"], p["O2.5"])


def test_implied_probs_remove_margin():
    ip = markets.implied_probs({"H": 2.0, "D": 3.4, "A": 3.6})
    assert sum(ip[c] for c in "HDA") == pytest.approx(1)


def _preds():
    ms, teams = synthetic_league()
    model = DixonColes().fit(ms, date(2027, 1, 1))
    fixtures = [Match("EPL", date(2027, 1, 2), teams[i], teams[-1 - i]) for i in range(5)]
    return [MatchPrediction(f, model.score_matrix(f.home, f.away), model.expected_goals(f.home, f.away))
            for f in fixtures]


def test_safe_parlay_one_leg_per_match_and_price_floor():
    preds = _preds()
    legs = candidate_legs(preds, min_leg_prob=0.55, max_leg_prob=0.9)
    parlays = build_parlays(legs, 3, mode="safe", top=3, min_fair_odds=2.0)
    assert parlays
    for p in parlays:
        assert len({id(l.pred) for l in p.legs}) == 3
        assert p.fair_odds >= 2.0
        assert all(0.55 <= l.prob <= 0.9 for l in p.legs)
    assert parlays[0].prob >= parlays[-1].prob - 1e-12


def test_sgp_legs_priced_jointly():
    preds = _preds()
    legs = [l for l in candidate_legs(preds, sgp=True, min_leg_prob=0.3, max_leg_prob=0.95)
            if len(l.codes) == 2]
    assert legs
    for l in legs:
        assert l.model_prob == pytest.approx(markets.prob(l.pred.matrix, *l.codes))


def test_value_mode_requires_positive_ev():
    preds = _preds()
    for p in preds:  # generous prices on home win / double chance
        p.odds = {"H": 1.25 / p.probs["H"], "1X": 1.2 / p.probs["1X"], "O1.5": 0.9 / p.probs["O1.5"]}
    legs = candidate_legs(preds, require_odds=True, min_edge=0.02, min_leg_prob=0.3, max_leg_prob=0.99)
    assert legs and all(l.edge >= 0.02 and "O1.5" not in l.codes for l in legs)
    parlays = build_parlays(legs, 2, mode="value", min_parlay_prob=0.05)
    assert parlays and all(p.ev > 0 and p.kelly() > 0 for p in parlays)


def test_team_resolver():
    r = TeamResolver(["Manchester United FC", "Manchester City FC", "Tottenham Hotspur FC",
                      "Borussia Mönchengladbach", "Paris Saint-Germain FC"])
    assert r.resolve("Man United") == "Manchester United FC"
    assert r.resolve("Man City") == "Manchester City FC"
    assert r.resolve("Spurs") == "Tottenham Hotspur FC"
    assert r.resolve("M'gladbach") == "Borussia Mönchengladbach"
    assert r.resolve("PSG") == "Paris Saint-Germain FC"
    assert norm_name("AFC Bournemouth") == "bournemouth"
