"""Weekend card: fit with filled-in results, apply team news, build parlay tiers, emit JSON.

    python3 -m football.weekend --research DIR --start 2026-11-06 --days 4 --out card.json
DIR holds <LEAGUE>_results.csv and <LEAGUE>_news.json files.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from . import engine, markets
from .adjust import load_news
from .geo import distance_km
from .leagues import LEAGUES
from .parlay import build_parlays, candidate_legs

TIERS = [  # name, legs, min fair odds, sgp, note
    ("Banker double", 2, 1.6, False, "two strongest legs on the card"),
    ("Core treble", 3, 2.0, False, "about even money, one leg per match"),
    ("Four-fold", 4, 3.0, False, "about 3/1"),
    ("Same-game builder treble", 3, 4.0, True, "legs may pair two selections on one match, priced jointly"),
    ("Long shot", 5, 7.0, True, "about 6/1, for small stakes"),
]


def form_string(matches, team, before, n=5):
    gs = sorted((m for m in matches if m.played and m.date < before and team in (m.home, m.away)),
                key=lambda m: m.date)[-n:]
    out = []
    for m in gs:
        gf, ga = (m.home_goals, m.away_goals) if m.home == team else (m.away_goals, m.home_goals)
        out.append({"r": "W" if gf > ga else "D" if gf == ga else "L", "score": f"{gf}-{ga}",
                    "opp": m.away if m.home == team else m.home, "home": m.home == team})
    return out


def leg_json(l):
    m = l.pred.match
    return {"league": m.league, "date": m.date.isoformat(), "match": l.pred.title,
            "pick": l.describe(), "code": l.code, "prob": round(l.prob, 4), "fair": round(l.fair_odds, 2)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--research", required=True)
    ap.add_argument("--leagues", default="EPL,LALIGA,SERIEA,BUNDESLIGA,LIGUE1")
    ap.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), default=date.today())
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    research = Path(a.research)
    leagues = a.leagues.split(",")

    import tempfile, csv
    merged = Path(tempfile.mkdtemp()) / "results.csv"
    n_results = 0
    with merged.open("w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["date", "home", "away", "home_goals", "away_goals", "league"])
        for lg in leagues:
            f = research / f"{lg}_results.csv"
            if f.exists():
                for row in csv.DictReader(f.open(encoding="utf-8-sig")):
                    if row.get("home_goals", "").strip() != "" and row.get("away_goals", "").strip() != "":
                        w.writerow([row["date"], row["home"], row["away"], row["home_goals"],
                                    row["away_goals"], lg])
                        n_results += 1

    news = load_news([research])
    states = engine.load_and_fit(leagues, a.start, results_csv=str(merged))
    preds = []
    for st in states.values():
        preds += engine.predict(st, engine.upcoming(st, a.start, a.days), news)

    matches = []
    for p in preds:
        m = p.match
        st = states[m.league]
        km = distance_km(m.home, m.away)
        matches.append({
            "league": m.league, "league_name": LEAGUES[m.league]["name"], "date": m.date.isoformat(),
            "time": m.time, "home": m.home, "away": m.away,
            "xg": [round(x, 2) for x in p.xg],
            "base_xg": [round(x, 2) for x in p.notes.get("base_xg", p.xg)],
            "probs": {k: round(v, 4) for k, v in p.probs.items()},
            "scores": [[h, a_, round(q, 4)] for h, a_, q in markets.most_likely_scores(p.matrix, 3)],
            "home_form": form_string(st.matches, m.home, m.date),
            "away_form": form_string(st.matches, m.away, m.date),
            "home_news": p.notes.get("home_news", []), "away_news": p.notes.get("away_news", []),
            "km": round(km) if km is not None else None,
        })

    tiers = []
    used_first = set()
    for name, n, odds, sgp, note in TIERS:
        legs = candidate_legs(preds, min_leg_prob=0.55, max_leg_prob=0.90, sgp=sgp)
        ps = build_parlays(legs, n, mode="safe", top=3, min_fair_odds=odds)
        tiers.append({"name": name, "note": note, "legs_n": n, "target": odds,
                      "options": [{"prob": round(p.prob, 4), "fair": round(p.fair_odds, 2),
                                   "legs": [leg_json(l) for l in p.legs]} for p in ps]})

    singles = sorted(candidate_legs(preds, min_leg_prob=0.60, max_leg_prob=0.92),
                     key=lambda l: -l.prob)
    card = {"generated": date.today().isoformat(), "window": [a.start.isoformat(), a.days],
            "results_added": n_results, "teams_with_news": len(news),
            "last_result": {lg: str(st.last_result) for lg, st in states.items()},
            "missing_before_window": {lg: sum(1 for m in st.matches if not m.played and m.date < a.start)
                                      for lg, st in states.items()},
            "matches": matches, "tiers": tiers,
            "top_singles": [leg_json(l) for l in singles[:15]]}
    Path(a.out).write_text(json.dumps(card, indent=1, ensure_ascii=False))
    print(f"{len(matches)} matches, {n_results} results merged, news for {len(news)} teams -> {a.out}")
    for t in tiers:
        if t["options"]:
            o = t["options"][0]
            print(f"\n{t['name']}: {o['prob'] * 100:.1f}% @ fair {o['fair']}")
            for l in o["legs"]:
                print(f"   {l['match']}: {l['pick']} ({l['prob'] * 100:.0f}%)")


if __name__ == "__main__":
    main()
