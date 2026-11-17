"""National-team model: Dixon-Coles on international results (martj42/international_results).

Differences from the club model:
  * one model for all national teams, fitted on every international since `years` ago;
  * neutral venues get no home advantage;
  * friendlies count half (rotated squads, low intensity);
  * no promoted-team prior.

    python3 -m football.international predict --date 2026-11-17 --fixtures fx.csv [--results extra.csv]
    python3 -m football.international backtest
fixtures CSV: home,away[,neutral]   extra results CSV: date,home,away,home_goals,away_goals[,neutral,tournament]
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import requests

from . import markets
from .data import Match
from .model import DixonColes
from .parlay import MatchPrediction, build_parlays, candidate_legs

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
CACHE = Path(os.environ.get("FOOTBALL_CACHE", Path(__file__).parent / ".cache")) / "international_results.csv"
FRIENDLY_WEIGHT = 0.5
XI = 0.0005      # per day: a match ~3.8 years old counts half (tuned 2024-26, see backtest)
RIDGE = 1.0


class InternationalModel(DixonColes):
    def _priors(self, played, names, as_of):
        return np.zeros(len(names))


def _d(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def load(refresh: bool = False, since: date | None = None) -> list[Match]:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if refresh or not CACHE.exists() or time.time() - CACHE.stat().st_mtime > 12 * 3600:
        try:
            r = requests.get(URL, timeout=30)
            r.raise_for_status()
            CACHE.write_text(r.text)
        except requests.RequestException:
            if not CACHE.exists():
                raise
    out = []
    for row in csv.DictReader(io.StringIO(CACHE.read_text())):
        d = _d(row["date"])
        if since and d < since:
            continue
        try:
            hg, ag = int(row["home_score"]), int(row["away_score"])
        except ValueError:
            hg = ag = None
        out.append(_match(d, row["home_team"], row["away_team"], hg, ag, row["neutral"] == "TRUE",
                          row["tournament"]))
    return out


def _match(d, home, away, hg, ag, neutral, tournament):
    return Match("INTL", d, home, away, hg, ag, extra={
        "neutral": neutral, "tournament": tournament,
        "weight": FRIENDLY_WEIGHT if tournament == "Friendly" else 1.0})


def add_results(matches: list[Match], path: str) -> int:
    seen = {(m.date, m.home, m.away) for m in matches}
    n = 0
    for row in csv.DictReader(open(path, encoding="utf-8-sig")):
        d = _d(row["date"])
        if (d, row["home"], row["away"]) in seen:
            continue
        matches.append(_match(d, row["home"], row["away"], int(row["home_goals"]), int(row["away_goals"]),
                              row.get("neutral", "").upper() == "TRUE", row.get("tournament") or "UEFA Nations League"))
        n += 1
    return n


def fit(matches, as_of: date, years: int = 6, xi: float = XI, ridge: float = RIDGE) -> InternationalModel:
    start = as_of - timedelta(days=365 * years)
    ms = [m for m in matches if m.played and start <= m.date < as_of]
    return InternationalModel(xi=xi, ridge=ridge).fit(ms, as_of)


def predict(model, fixtures) -> list[MatchPrediction]:
    out = []
    for f in fixtures:
        neutral = f.extra.get("neutral", False)
        for t in (f.home, f.away):
            if t not in model.teams:
                raise SystemExit(f"Unknown team {t!r}: use the dataset's spelling")
        lam, mu = model.expected_goals(f.home, f.away, neutral)
        out.append(MatchPrediction(f, model.matrix_from_rates(lam, mu), (lam, mu)))
    return out


def backtest(matches, start=date(2024, 3, 1), end=date(2026, 11, 1), xi=XI, ridge=RIDGE,
             tournaments=("UEFA Nations League", "UEFA Euro qualification", "UEFA Euro",
                          "FIFA World Cup qualification")) -> dict:
    """Walk-forward over UEFA-team competitive matches, refitting at each international window."""
    tgt = [m for m in matches if m.played and start <= m.date < end and m.extra["tournament"] in tournaments]
    windows = sorted({m.date - timedelta(days=m.date.weekday()) for m in tgt})
    ll = llb = 0.0
    n = 0
    bins = {}
    base = None
    for w in windows:
        model = fit(matches, w, xi=xi, ridge=ridge)
        if base is None:
            prior = [m for m in matches if m.played and w - timedelta(days=730) <= m.date < w
                     and m.extra["tournament"] in tournaments]
            base = {o: sum(f(m) for m in prior) / len(prior) for o, f in
                    (("H", lambda m: m.home_goals > m.away_goals), ("D", lambda m: m.home_goals == m.away_goals),
                     ("A", lambda m: m.home_goals < m.away_goals))}
        for m in tgt:
            if not (w <= m.date < w + timedelta(days=7)):
                continue
            if m.home not in model.teams or m.away not in model.teams:
                continue
            M = model.matrix_from_rates(*model.expected_goals(m.home, m.away, m.extra["neutral"]))
            p = markets.all_probs(M)
            o = "H" if m.home_goals > m.away_goals else "D" if m.home_goals == m.away_goals else "A"
            ll += -math.log(p[o]); llb += -math.log(base[o]); n += 1
            hg, ag = min(m.home_goals, 10), min(m.away_goals, 10)
            for c in ("H", "A", "1X", "X2", "O1.5", "O2.5", "U2.5", "U3.5", "BTTS_Y", "BTTS_N", "H_WTN", "A_WTN"):
                q = p[c]
                if q < 0.5:
                    continue
                b = min(int(q * 10), 9) / 10
                s = bins.setdefault(b, [0, 0.0, 0])
                s[0] += 1; s[1] += q; s[2] += bool(markets.BY_CODE[c].mask[hg, ag])
    return {"n": n, "logloss": ll / n, "logloss_base": llb / n,
            "calibration": {f"{k:.0%}": (v[0], round(v[1] / v[0], 3), round(v[2] / v[0], 3))
                            for k, v in sorted(bins.items())}}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="football.international")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("predict")
    p.add_argument("--date", type=_d, default=date.today())
    p.add_argument("--fixtures", required=True)
    p.add_argument("--results")
    p.add_argument("--legs", type=int, default=3)
    p.add_argument("--min-odds", type=float, default=2.0)
    p.add_argument("--sgp", action="store_true")
    sub.add_parser("backtest")
    a = ap.parse_args(argv)
    ms = load(since=date(2014, 1, 1))
    if a.cmd == "backtest":
        for xi in (0.0005, 0.0008, 0.0012):
            for ridge in (2.0, 4.0, 8.0):
                r = backtest(ms, xi=xi, ridge=ridge)
                print(f"xi {xi} ridge {ridge}: n={r['n']} logloss {r['logloss']:.4f} (base {r['logloss_base']:.4f})")
        print(backtest(ms)["calibration"])
        return
    if a.results:
        print(f"added {add_results(ms, a.results)} results")
    model = fit(ms, a.date)
    fx = [_match(a.date, r["home"], r["away"], None, None, r.get("neutral", "").upper() == "TRUE", "UEFA Nations League")
          for r in csv.DictReader(open(a.fixtures, encoding="utf-8-sig"))]
    preds = predict(model, fx)
    for p in preds:
        pr = p.probs
        print(f"{p.title:<36} xG {p.xg[0]:.2f}-{p.xg[1]:.2f}  1 {pr['H']:.0%} X {pr['D']:.0%} 2 {pr['A']:.0%}"
              f"  O2.5 {pr['O2.5']:.0%} BTTS {pr['BTTS_Y']:.0%}")
    legs = candidate_legs(preds, codes=["H", "A", "1X", "X2", "O1.5", "O2.5", "U2.5", "U3.5", "BTTS_Y",
                                        "BTTS_N", "HO1.5", "AO1.5", "H_WTN", "A_WTN"],
                          min_leg_prob=0.55, max_leg_prob=0.90, sgp=a.sgp)
    for par in build_parlays(legs, a.legs, mode="safe", top=3, min_fair_odds=a.min_odds):
        print(f"\n{len(par.legs)}-fold  {par.prob:.1%}  fair {par.fair_odds:.2f}")
        for l in par.legs:
            print(f"   {l.pred.title}: {l.describe()}  {l.prob:.0%} (fair {l.fair_odds:.2f})")


if __name__ == "__main__":
    main()
