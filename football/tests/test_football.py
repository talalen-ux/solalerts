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


def test_team_news_adjustments():
    from football import adjust
    k = date(2026, 11, 8)
    info = {"absences": [{"player": "X", "pos": "FW", "status": "out", "importance": "key"},
                         {"player": "Y", "pos": "GK", "status": "doubtful", "importance": "key"},
                         {"player": "Z", "pos": "DF", "status": "out", "importance": "rotation"}],
            "europe_midweek": "2026-11-05 UEL"}
    att, conc, why = adjust.team_factors(info, k)
    assert att == pytest.approx(1 - 0.06 - 0.03)
    assert conc == pytest.approx(1 + 0.03 + 0.01 + 0.02)
    assert len(why) == 3
    many = {"absences": [{"pos": "FW", "status": "out", "importance": "key"}] * 10}
    assert adjust.team_factors(many, k)[0] == pytest.approx(0.85)
    lam, mu, _, _ = adjust.adjusted_rates(1.5, 1.0, info, None, k)
    assert lam == pytest.approx(1.5 * att) and mu == pytest.approx(1.0 * conc)


def test_form_winners_filters_and_ranks(monkeypatch):
    from football import weekend
    preds = _preds()
    ms, _ = synthetic_league()

    class St:  # minimal league state: weekend.form_winners only reads .matches
        matches = ms
    # every fixture's home team gets a WWWWW history by construction below
    fake_form = lambda matches, team, before, n=5: [{"r": "W", "score": "1-0", "opp": "X", "home": True}] * 5
    monkeypatch.setattr(weekend, "form_string", fake_form)
    rows, tiers = weekend.form_winners(preds, {"EPL": St})
    assert rows and all(r["prob"] >= weekend.FORM_MIN_PROB for r in rows)
    assert [r["prob"] for r in rows] == sorted((r["prob"] for r in rows), reverse=True)
    dbl = tiers[0]["options"][0]
    assert dbl["prob"] == pytest.approx(rows[0]["prob"] * rows[1]["prob"], rel=1e-3)
    assert all(l["code"] in ("H", "A") for t in tiers for o in t["options"] for l in o["legs"])


def test_weekly_ingest_dedupes(tmp_path, monkeypatch):
    from football import weekly, data as d
    monkeypatch.setattr(weekly, "LEDGER", tmp_path / "ledger")
    monkeypatch.setattr(d, "load_league", lambda lg, y, s=3, refresh=False: [
        Match(lg, date(2026, 9, 1), "A FC", "B FC"), Match(lg, date(2026, 9, 8), "B FC", "A FC")])
    src = tmp_path / "src"; src.mkdir()
    (src / "EPL_new_results.csv").write_text(
        "date,home,away,home_goals,away_goals,league\n2026-11-07,A FC,B FC,1,0,EPL\n"
        "2026-11-07,A FC,Nope FC,2,0,EPL\n2026-11-08,B FC,A FC,,,EPL\n")
    assert weekly.ingest(src) == {"EPL": 1}
    (src / "EPL_new_results.csv").write_text(
        "date,home,away,home_goals,away_goals,league\n2026-11-07,A FC,B FC,2,0,EPL\n")
    weekly.ingest(src)
    rows = (tmp_path / "ledger" / "EPL.csv").read_text().strip().splitlines()
    assert rows[1:] == ["2026-11-07,A FC,B FC,2,0,EPL"]


def test_next_friday():
    from football.weekly import next_friday
    assert next_friday(date(2026, 11, 22)) == date(2026, 11, 27)
    assert next_friday(date(2026, 11, 27)) == date(2026, 11, 27)


def test_espn_parse_results_fixtures_and_colours():
    from football import espn
    def ev(i, d, done, hs, as_, status="STATUS_FULL_TIME"):
        return {"id": str(i), "date": d, "status": {"type": {"name": status, "completed": done}},
                "competitions": [{"neutralSite": False, "competitors": [
                    {"homeAway": "home", "score": hs, "team": {"displayName": "Al Nassr", "abbreviation": "NSR",
                                                               "color": "f7f316", "alternateColor": "1c31ce"}},
                    {"homeAway": "away", "score": as_, "team": {"displayName": "Al Hilal", "abbreviation": "HIL"}}]}]}
    ms = espn._parse("SAUDI", {"events": [ev(1, "2026-11-20T17:00Z", True, "2", "1"),
                                          ev(2, "2026-11-28T17:00Z", False, "0", "0", "STATUS_SCHEDULED"),
                                          ev(3, "2026-11-29T17:00Z", False, "0", "0", "STATUS_POSTPONED")]})
    assert len(ms) == 2
    assert ms[0].played and (ms[0].home_goals, ms[0].away_goals) == (2, 1)
    assert not ms[1].played and ms[1].date == date(2026, 11, 28)
    assert espn.TEAM_META["Al Nassr"] == ("NSR", "#f7f316", "#1c31ce")
    assert espn.TEAM_META["Al Hilal"][1] == "#8e8e93"   # no colour in feed -> neutral


def test_badge_clashes_within_league_get_initials():
    from football import badges, espn
    espn.TEAM_META.update({"Dundee": ("DUN", "#000040", "#ffffff"), "Dundee United": ("DUN", "#ff621a", "#009f00")})
    b = badges.for_teams({("Dundee", "SCOTLAND"), ("Dundee United", "SCOTLAND")})
    assert b["Dundee"][0] != b["Dundee United"][0]
