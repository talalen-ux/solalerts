"""Does short rest hurt? League matches, walk-forward: actual vs model by days since last match
(any competition). Also: does a favourite that won 2-4 days earlier win again as often as predicted?"""
import bisect
from collections import defaultdict
from datetime import date, timedelta
from football import espn, markets
from football.model import DixonColes

START, END = date(2024, 11, 24), date(2026, 11, 23)
data = espn.load_many(list(espn.LEAGUES) + list(espn.CUPS), date(2026, 12, 31), 37)
games = defaultdict(list)   # team -> sorted [(date, won)]
for ms in data.values():
    for m in ms:
        if m.played:
            games[m.home].append((m.date, m.home_goals > m.away_goals))
            games[m.away].append((m.date, m.away_goals > m.home_goals))
for t in games: games[t].sort()
def prev(team, d):
    g = games[team]; i = bisect.bisect_left(g, (d, False)) - 1
    return ((d - g[i][0]).days, g[i][1]) if i >= 0 else (99, False)
goal = defaultdict(lambda: [0, 0.0, 0.0]); fav = defaultdict(lambda: [0, 0.0, 0])
for key in espn.LEAGUES:
    ms = data[key]; tgt = [m for m in ms if m.played and START <= m.date < END]
    for w in sorted({m.date - timedelta(days=m.date.weekday()) for m in tgt}):
        try: mod = DixonColes().fit(ms, w, key)
        except ValueError: continue
        for m in tgt:
            if not (w <= m.date < w + timedelta(7)): continue
            lam, mu = mod.expected_goals(m.home, m.away)
            p = markets.all_probs(mod.matrix_from_rates(lam, mu))
            (rh, wh), (ra, wa) = prev(m.home, m.date), prev(m.away, m.date)
            for rest, opp, gf, xg in ((rh, ra, m.home_goals, lam), (ra, rh, m.away_goals, mu)):
                b = "short (<=4d) v rested (6d+)" if rest <= 4 and opp >= 6 else "rested v short" if rest >= 6 and opp <= 4 else "both short" if rest <= 4 and opp <= 4 else "normal"
                g = goal[b]; g[0] += 1; g[1] += xg; g[2] += gf
            for rest, won_prev, code, won in ((rh, wh, "H", m.home_goals > m.away_goals), (ra, wa, "A", m.away_goals > m.home_goals)):
                if p[code] < 0.5: continue
                b = ("2-4 days after a win" if won_prev else "2-4 days after a non-win") if 2 <= rest <= 4 else "5+ days rest"
                f = fav[b]; f[0] += 1; f[1] += p[code]; f[2] += won
print("goals scored vs model expectation:")
for b, (n, x, g) in sorted(goal.items()): print(f"  {b:<28} n={n:<6} expected {x / n:.3f}  actual {g / n:.3f}  ratio {g / x:.3f}")
print("favourites (model >= 50%) winning:")
for b, (n, s, w) in sorted(fav.items()):
    se = ((s / n) * (1 - s / n) / n) ** .5
    print(f"  {b:<28} n={n:<6} predicted {s / n:.1%}  won {w / n:.1%}  diff {(w - s) / n * 100:+.1f} (±{196 * se:.1f})")
