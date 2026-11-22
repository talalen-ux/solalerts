"""Weekend card: fit with filled-in results, apply team news, build parlay tiers, emit JSON.

    python3 -m football.weekend --research DIR --start 2026-11-06 --days 4 --out card.json
DIR holds <LEAGUE>_results.csv and <LEAGUE>_news.json files.
"""

from __future__ import annotations

import argparse
import math
import json
from datetime import date, datetime
from pathlib import Path

from . import badges, engine, markets
from .adjust import load_news
from .geo import distance_km
from .leagues import LEAGUES, season_start_year
from .parlay import Leg, build_parlays, candidate_legs

# Main-line markets only: the model beat base rates on results (1X2 / double chance) and
# these carry the lowest bookmaker margin. "Team scores 1+" and "no draw" legs are left out:
# they add little information and books load their margin onto them.
CARD_CODES = ["H", "A", "1X", "X2", "O1.5", "O2.5", "U2.5", "U3.5", "BTTS_Y", "BTTS_N",
              "HO1.5", "AO1.5", "H_WTN", "A_WTN"]

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


# Leagues where the model beat base rates by under 4% in the 2025-26 walk-forward
# (football/research/espn_backtest.py). Their 80%+ legs won 80.5% vs 84.1% predicted, so legs
# from them are capped at 80%, where calibration held (74.8% predicted, 74.2% won).
LOW_CONFIDENCE = {"CHAMPIONSHIP", "BUNDESLIGA2", "LALIGA2", "SERIEB", "LIGUE2", "AUSTRIA", "DENMARK",
                  "MLS", "LIGAMX", "ARGENTINA", "LEAGUEONE", "LEAGUETWO", "SWEDEN", "CHILE",
                  "LIBERTADORES"}  # last one from research/cup_backtest.py (+1.8%)
LOW_CONFIDENCE_CAP = 0.80


def capped(legs):
    return [l for l in legs if not (l.pred.match.league in LOW_CONFIDENCE and l.prob > LOW_CONFIDENCE_CAP)]


def league_label(key):
    from . import espn
    if key in espn.LEAGUES:
        _, name, short, region = espn.LEAGUES[key]
        return [name, short, region]
    if key in espn.CUPS:
        _, name, short, _ = espn.CUPS[key]
        return [name, short, "Cups"]
    return [LEAGUES[key]["name"], key, "Europe"]


def league_name(key):
    return league_label(key)[0]


FORM_MIN_WINS = 3        # "top performing": won at least 3 of the last 5 league games
FORM_MIN_PROB = 0.50     # and the model makes them favourite to win this one


def form_winners(preds, states):
    """In-form teams ranked by the model's probability that they win again, plus win-only accas.

    Form is the filter, the model is the ranking: on 2023-26 data a separate last-5 form term
    added nothing to the time-decayed ratings, so form does not boost the probabilities.
    """
    rows, legs = [], []
    for p in preds:
        m = p.match
        st = states[m.league]
        for side, code, opp in (("home", "H", m.away), ("away", "A", m.home)):
            team = getattr(m, side)
            f = form_string(st.matches, team, m.date)
            wins = sum(x["r"] == "W" for x in f)
            if len(f) < 5 or wins < FORM_MIN_WINS or p.probs[code] < FORM_MIN_PROB:
                continue
            if m.league in LOW_CONFIDENCE and p.probs[code] > LOW_CONFIDENCE_CAP:
                continue
            rows.append({"team": team, "opponent": opp, "home": side == "home", "league": m.league,
                         "date": m.date.isoformat(), "wins": wins, "form": "".join(x["r"] for x in f),
                         "prob": round(p.probs[code], 4), "fair": round(1 / p.probs[code], 2)})
            legs.append(Leg(p, (code,), p.probs[code], p.probs[code]))
    rows.sort(key=lambda r: -r["prob"])
    tiers = []
    for name, n, note in (("Form double", 2, "the two in-form teams most likely to win"),
                          ("Form treble", 3, "three in-form favourites, one per match"),
                          ("Form four-fold", 4, "four in-form favourites")):
        ps = build_parlays(legs, n, mode="safe", top=2)
        tiers.append({"name": name, "note": note, "legs_n": n, "target": 1.0, "form": True,
                      "options": [{"prob": round(x.prob, 4), "fair": round(x.fair_odds, 2),
                                   "legs": [leg_json(l) for l in x.legs]} for x in ps]})
    return rows, tiers


def team_notes(info):
    """Key absences, in-form players and manager change from a team's news entry, for display."""
    info = info or {}
    absn = [a for a in info.get("absences", []) if isinstance(a, dict) and a.get("importance") == "key"]
    mgr = info.get("manager_change")
    return {"abs": [f"{a.get('player')} ({a.get('pos')}{', doubtful' if a.get('status') == 'doubtful' else ''})"
                    for a in absn],
            "inform": [x for x in info.get("in_form", []) if isinstance(x, dict)][:3],
            "mgr": mgr if mgr not in (None, "", "unverified") else None}


WILDCARD_SIZES = (10, 15, 19)
WILDCARD_MAX_LEG = 0.92    # calibration held in the 90%+ bucket (92.2% predicted, 92.1% won)
BOOK_MARGIN = 0.05         # typical bookmaker margin per leg, used only for the warning figures


def wildcard_accas(preds, sizes=WILDCARD_SIZES, alternatives=2):
    """Long accumulators: the most likely leg from each of the N best matches.

    With one leg per match and independent matches, the highest joint probability for N legs is
    simply the N strongest per-match legs, so this is greedy. Alternatives swap the weakest legs
    for the next-best matches.
    """
    legs = capped(candidate_legs(preds, codes=CARD_CODES, min_leg_prob=0.60, max_leg_prob=WILDCARD_MAX_LEG))
    best = {}
    for l in legs:
        k = id(l.pred)
        if k not in best or l.prob > best[k].prob:
            best[k] = l
    ranked = sorted(best.values(), key=lambda l: -l.prob)
    out = []
    for n in sizes:
        if len(ranked) < n:
            continue
        opts = []
        for shift in range(alternatives + 1):
            chosen = ranked[:n - shift] + ranked[n:n + shift] if shift else ranked[:n]
            if len(chosen) < n:
                break
            chosen = sorted(chosen, key=lambda l: (l.pred.match.date, l.pred.match.time))
            prob = math.prod(l.prob for l in chosen)
            opts.append({"prob": round(prob, 5), "fair": round(1 / prob, 2),
                         "legs": [leg_json(l) for l in chosen]})
        book_factor = (1 + BOOK_MARGIN) ** -n
        out.append({"name": f"{n}-leg wildcard", "note": f"the {n} most likely results this week, one per match",
                    "legs_n": n, "target": 1.0, "wildcard": True,
                    "typical_book_odds": round(opts[0]["fair"] * book_factor, 1),
                    "expected_return": round(book_factor - 1, 3), "options": opts})
    return out


def leg_json(l):
    m = l.pred.match
    return {"league": m.league, "date": m.date.isoformat(), "match": l.pred.title,
            "home": m.home, "away": m.away,
            "pick": l.describe(), "code": l.code, "prob": round(l.prob, 4), "fair": round(l.fair_odds, 2)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--research", required=True)
    ap.add_argument("--leagues", default="EPL,LALIGA,SERIEA,BUNDESLIGA,LIGUE1")
    ap.add_argument("--source", choices=["openfootball", "espn"], default="openfootball")
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
    states = engine.load_and_fit(leagues, a.start, results_csv=None if a.source == "espn" else str(merged),
                                 source=a.source)
    preds = []
    for st in states.values():
        preds += engine.predict(st, engine.upcoming(st, a.start, a.days), news)

    matches = []
    for p in preds:
        m = p.match
        st = states[m.league]
        km = distance_km(m.home, m.away)
        matches.append({
            "league": m.league, "league_name": league_name(m.league), "date": m.date.isoformat(),
            "time": m.time, "home": m.home, "away": m.away,
            "xg": [round(x, 2) for x in p.xg],
            "base_xg": [round(x, 2) for x in p.notes.get("base_xg", p.xg)],
            "probs": {k: round(v, 4) for k, v in p.probs.items()},
            "scores": [[h, a_, round(q, 4)] for h, a_, q in markets.most_likely_scores(p.matrix, 3)],
            "home_form": form_string(st.matches, m.home, m.date),
            "away_form": form_string(st.matches, m.away, m.date),
            "home_news": p.notes.get("home_news", []), "away_news": p.notes.get("away_news", []),
            **{f"{side}_{k}": v for side in ("home", "away")
               for k, v in team_notes(news.get(getattr(m, side))).items()},
            "km": round(km) if km is not None else None,
        })

    season_start = date(season_start_year(a.start), 7, 1)
    tiers = []
    for name, n, odds, sgp, note in TIERS:
        legs = capped(candidate_legs(preds, codes=CARD_CODES, min_leg_prob=0.55, max_leg_prob=0.90, sgp=sgp))
        ps = build_parlays(legs, n, mode="safe", top=3, min_fair_odds=odds)
        tiers.append({"name": name, "note": note, "legs_n": n, "target": odds,
                      "options": [{"prob": round(p.prob, 4), "fair": round(p.fair_odds, 2),
                                   "legs": [leg_json(l) for l in p.legs]} for p in ps]})

    form_teams, form_tiers = form_winners(preds, states)
    wildcards = wildcard_accas(preds)

    singles = sorted(capped(candidate_legs(preds, codes=CARD_CODES, min_leg_prob=0.60, max_leg_prob=0.92)),
                     key=lambda l: -l.prob)
    card = {"generated": date.today().isoformat(), "window": [a.start.isoformat(), a.days],
            "results_added": n_results, "teams_with_news": len(news),
            "last_result": {lg: str(st.last_result) for lg, st in states.items()},
            "missing_before_window": {lg: sum(1 for m in st.matches if not m.played
                                              and season_start <= m.date < a.start)
                                      for lg, st in states.items()},
            "matches": matches, "tiers": tiers, "form_teams": form_teams, "form_tiers": form_tiers,
            "wildcards": wildcards,
            "badges": badges.for_teams({(t, m["league"]) for m in matches for t in (m["home"], m["away"])}),
            "league_marks": badges.league_marks({m["league"] for m in matches}),
            "league_names": {k: league_label(k) for k in {m["league"] for m in matches}},
            "low_confidence": sorted(LOW_CONFIDENCE & {m["league"] for m in matches}),
            "top_singles": [leg_json(l) for l in singles[:15]]}
    Path(a.out).write_text(json.dumps(card, indent=1, ensure_ascii=False))
    print(f"{len(matches)} matches, {n_results} results merged, news for {len(news)} teams -> {a.out}")
    print("\nIn-form teams most likely to win again:")
    for f in form_teams[:10]:
        print(f"   {f['team']} ({f['wins']}W in last 5) v {f['opponent']}: {f['prob'] * 100:.0f}%")
    for t in form_tiers + tiers + wildcards:
        if t["options"]:
            o = t["options"][0]
            print(f"\n{t['name']}: {o['prob'] * 100:.1f}% @ fair {o['fair']}")
            for l in o["legs"]:
                print(f"   {l['match']}: {l['pick']} ({l['prob'] * 100:.0f}%)")


if __name__ == "__main__":
    main()
