"""Command line: predict, parlay, backtest, ratings.

    python3 -m football predict --league ALL --days 7
    python3 -m football parlay  --league EPL,SERIEA --legs 3
    python3 -m football parlay  --odds my_odds.csv --mode value --bankroll 200
    python3 -m football backtest --league ALL --season 2025
    python3 -m football ratings --league BUNDESLIGA
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta

from . import backtest, engine, markets
from .leagues import LEAGUES
from .parlay import build_parlays, candidate_legs


def _date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _pct(p: float) -> str:
    return f"{p * 100:5.1f}%"


def _warn_stale(states, start: date) -> None:
    gaps = []
    for lg, st in states.items():
        missing = sum(1 for m in st.matches if not m.played and m.date < start)
        if missing:
            gaps.append(f"{lg} {missing} (last {st.last_result})")
    if gaps:
        print("! Fixtures before the window with no score in the feed: " + ", ".join(gaps) +
              ".\n  Ratings skip them; pass --results file.csv to fill them in.", file=sys.stderr)


def _load(args):
    leagues = engine.resolve_leagues(args.league)
    start = args.start or date.today()
    states = engine.load_and_fit(leagues, start, refresh=args.refresh, results_csv=args.results,
                                 xi=args.xi, ridge=args.ridge)
    _warn_stale(states, start)
    preds = []
    for st in states.values():
        preds += engine.predict(st, engine.upcoming(st, start, args.days))
    preds.sort(key=lambda p: (p.match.date, p.match.time, p.match.league))
    if getattr(args, "odds", None):
        used, problems = engine.attach_odds(preds, args.odds)
        print(f"Odds: {used} prices attached.", file=sys.stderr)
        for p in problems[:15]:
            print(f"  ! {p}", file=sys.stderr)
    return states, preds, start


def cmd_predict(args) -> None:
    states, preds, start = _load(args)
    if not preds:
        print(f"No fixtures between {start} and {start + timedelta(days=args.days)}.")
        return
    if args.json:
        print(json.dumps([{
            "league": p.match.league, "date": p.match.date.isoformat(), "time": p.match.time,
            "home": p.match.home, "away": p.match.away, "xg": [round(x, 2) for x in p.xg],
            "probs": {k: round(v, 4) for k, v in p.probs.items()},
        } for p in preds], indent=2))
        return
    current = None
    for p in preds:
        if p.match.league != current:
            current = p.match.league
            print(f"\n=== {LEAGUES[current]['name']} ===")
        pr = p.probs
        top = ", ".join(f"{h}-{a} {_pct(q).strip()}" for h, a, q in markets.most_likely_scores(p.matrix, 3))
        print(f"{p.match.date} {p.match.time:>5}  {p.match.home} v {p.match.away}")
        print(f"    xG {p.xg[0]:.2f}-{p.xg[1]:.2f} | 1 {_pct(pr['H'])} X {_pct(pr['D'])} 2 {_pct(pr['A'])}"
              f" | fair {1 / pr['H']:.2f}/{1 / pr['D']:.2f}/{1 / pr['A']:.2f}")
        print(f"    O2.5 {_pct(pr['O2.5'])}  BTTS {_pct(pr['BTTS_Y'])}  O1.5 {_pct(pr['O1.5'])}"
              f"  U3.5 {_pct(pr['U3.5'])} | likely: {top}")


def cmd_parlay(args) -> None:
    states, preds, start = _load(args)
    if args.mode == "value" and not args.odds:
        sys.exit("--mode value needs --odds file.csv (columns: home,away,selection,odds)")
    codes = args.markets.split(",") if args.markets else None
    legs = candidate_legs(preds, codes=codes, min_leg_prob=args.min_leg_prob,
                          max_leg_prob=args.max_leg_prob, sgp=args.sgp,
                          model_weight=args.model_weight, require_odds=args.mode == "value",
                          min_edge=args.min_edge)
    parlays = build_parlays(legs, args.legs, mode=args.mode, top=args.top,
                            min_parlay_prob=args.min_parlay_prob, min_fair_odds=args.min_odds)
    print(f"{len(preds)} fixtures, {len(legs)} candidate legs, {start} to "
          f"{start + timedelta(days=args.days)}  (mode: {args.mode}{', same-game combos' if args.sgp else ''})")
    if not parlays:
        print("No parlay meets the constraints. Try fewer legs, a wider --days window, "
              "a lower --min-leg-prob, or (value mode) a lower --min-parlay-prob.")
        return
    for i, p in enumerate(parlays, 1):
        line = f"\n#{i}  {len(p.legs)}-fold  hit chance {_pct(p.prob).strip()}  fair odds {p.fair_odds:.2f}"
        if p.odds:
            line += f"  book odds {p.odds:.2f}  EV {p.ev * 100:+.1f}%"
            k = p.kelly(args.kelly)
            if k:
                line += f"  stake {k * 100:.2f}% bankroll"
                if args.bankroll:
                    line += f" = {k * args.bankroll:.2f}"
        print(line)
        for l in p.legs:
            m = l.pred.match
            extra = f"  book {l.odds:.2f} edge {l.edge * 100:+.1f}%" if l.odds else ""
            print(f"    {m.date} {LEAGUES[m.league]['name'][:14]:<14} {l.pred.title}: {l.describe()}"
                  f"  [{l.code}] {_pct(l.prob).strip()} (fair {l.fair_odds:.2f}){extra}")
    if args.mode == "safe":
        print("\nFair odds are break-even prices. Only bet a parlay where your book pays MORE "
              "than the fair odds shown; books add 5-10% margin per leg, so the gap compounds.")


def cmd_backtest(args) -> None:
    leagues = engine.resolve_leagues(args.league)
    res = backtest.run(leagues, args.season, legs=args.legs, min_leg_prob=args.min_leg_prob,
                       max_leg_prob=args.max_leg_prob, sgp=args.sgp, min_odds=args.min_odds,
                       xi=args.xi, ridge=args.ridge, progress=lambda lg, n: print(f"  {LEAGUES[lg]['name']}: {n} matches", file=sys.stderr))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(res, fh, indent=2, default=str)
        print(f"Wrote {args.json}", file=sys.stderr)
    print(f"\nWalk-forward backtest, season {args.season}-{str(args.season + 1)[-2:]}: {res['matches']} matches")
    if not res["matches"]:
        return
    print("\nMarket          logloss (base)     brier (base)")
    for k, v in res["markets"].items():
        print(f"  {k:<12} {v['logloss']:.4f} ({v['logloss_baseline']:.4f})   "
              f"{v['brier']:.4f} ({v['brier_baseline']:.4f})")
    print("\nCalibration of legs the parlay builder uses (p >= 50%):")
    for c in res["calibration"]:
        print(f"  {c['bin']:<9} n={c['n']:<5} predicted {_pct(c['predicted'])}  actual {_pct(c['actual'])}")
    if "parlays" in res:
        p = res["parlays"]
        print(f"\nWeekly best safe {p['legs']}-fold, {p['n']} weeks:")
        print(f"  predicted hit rate {_pct(p['predicted_hit_rate'])}  actual {_pct(p['actual_hit_rate'])}"
              f"  (avg fair odds {p['avg_fair_odds']:.2f})")
        print(f"  per-leg predicted {_pct(p['leg_predicted'])}  actual {_pct(p['leg_actual'])}")
        print(f"  P&L at the model's own fair odds, 1u flat: {p['fair_odds_pnl']:+.1f}u "
              f"(near 0 = honest prices; real books pay less than fair)")


def cmd_ratings(args) -> None:
    states = engine.load_and_fit(engine.resolve_leagues(args.league), args.start or date.today(),
                                 refresh=args.refresh, results_csv=args.results, xi=args.xi, ridge=args.ridge)
    for lg, st in states.items():
        m = st.model
        print(f"\n=== {LEAGUES[lg]['name']} (results to {st.last_result}; home adv "
              f"x{2.718281828 ** m.home_adv:.2f}, rho {m.rho:+.3f}) ===")
        current = {t for x in st.matches if x.date >= date(st.last_result.year if st.last_result.month >= 7
                                                              else st.last_result.year - 1, 7, 1)
                   for t in (x.home, x.away)}
        rows = [r for r in m.table() if r[0] in current]
        for i, (t, a, d, s) in enumerate(rows, 1):
            print(f"  {i:>2}. {t:<32} attack {a:+.2f}  defence {d:+.2f}  overall {s:+.2f}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="football", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, window=True):
        p.add_argument("--league", default="ALL", help=f"ALL or comma list of {','.join(LEAGUES)}")
        p.add_argument("--start", type=_date, help="first day of the window / ratings date (default today)")
        p.add_argument("--results", help="CSV of extra results: date,home,away,home_goals,away_goals,league")
        p.add_argument("--refresh", action="store_true", help="re-download the current season")
        p.add_argument("--xi", type=float, default=engine.DEFAULT_XI, help="time decay per day")
        p.add_argument("--ridge", type=float, default=engine.DEFAULT_RIDGE, help="rating shrinkage")
        if window:
            p.add_argument("--days", type=int, default=7, help="window length in days")

    p = sub.add_parser("predict", help="probabilities for upcoming fixtures")
    common(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("parlay", help="build parlays from upcoming fixtures")
    common(p)
    p.add_argument("--legs", type=int, default=3)
    p.add_argument("--mode", choices=["safe", "value"], default="safe")
    p.add_argument("--odds", help="CSV: home,away,selection,odds (selection codes: "
                                   + ",".join(s.code for s in markets.SELECTIONS) + "; combos like H+O1.5)")
    p.add_argument("--markets", help="comma list of selection codes to allow")
    p.add_argument("--sgp", action="store_true", help="allow 2-selection same-game legs")
    p.add_argument("--min-leg-prob", type=float, default=0.55)
    p.add_argument("--max-leg-prob", type=float, default=0.90,
                   help="skip near-certain legs that books price with no value")
    p.add_argument("--min-odds", type=float, default=2.0, help="minimum combined fair odds")
    p.add_argument("--min-parlay-prob", type=float, default=0.10, help="value mode: minimum hit chance")
    p.add_argument("--min-edge", type=float, default=0.02, help="value mode: minimum edge per leg")
    p.add_argument("--model-weight", type=float, default=0.6,
                   help="value mode: weight on model vs de-margined market probability")
    p.add_argument("--kelly", type=float, default=0.25, help="Kelly fraction for stakes")
    p.add_argument("--bankroll", type=float)
    p.add_argument("--top", type=int, default=5)
    p.set_defaults(func=cmd_parlay)

    p = sub.add_parser("backtest", help="walk-forward check of calibration and parlay hit rates")
    p.add_argument("--league", default="ALL")
    p.add_argument("--season", type=int, default=2025, help="season start year, e.g. 2025 for 2025-26")
    p.add_argument("--legs", type=int, default=3)
    p.add_argument("--min-leg-prob", type=float, default=0.55)
    p.add_argument("--max-leg-prob", type=float, default=0.90)
    p.add_argument("--sgp", action="store_true")
    p.add_argument("--min-odds", type=float, default=2.0, help="minimum combined fair odds")
    p.add_argument("--xi", type=float, default=engine.DEFAULT_XI)
    p.add_argument("--ridge", type=float, default=engine.DEFAULT_RIDGE)
    p.add_argument("--json", help="write full results to this file")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("ratings", help="team attack/defence ratings")
    common(p, window=False)
    p.set_defaults(func=cmd_ratings)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
