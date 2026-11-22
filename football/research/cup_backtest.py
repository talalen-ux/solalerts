"""Walk-forward check of the global (cross-league) model on continental cup matches."""
import math, time
from collections import defaultdict
from datetime import date, timedelta
from football import espn, markets
from football.globalmodel import GlobalModel

START, END = date(2025, 11, 24), date(2026, 11, 23)
data = espn.load_many(list(espn.LEAGUES) + list(espn.CUPS), date(2026, 12, 31), 37)
dom = {k: v for k, v in data.items() if k in espn.LEAGUES}
cups = [m for k, v in data.items() if k in espn.CUPS for m in v]
allm = [m for v in data.values() for m in v]
tgt = [m for m in cups if m.played and START <= m.date < END]
prior = [m for m in cups if m.played and START - timedelta(days=730) <= m.date < START and not m.extra.get("neutral")]
base = {o: sum(f(m) for m in prior) / len(prior) for o, f in
        (("H", lambda m: m.home_goals > m.away_goals), ("D", lambda m: m.home_goals == m.away_goals),
         ("A", lambda m: m.home_goals < m.away_goals))}
CODES = ["H", "A", "1X", "X2", "O1.5", "O2.5", "U2.5", "U3.5", "BTTS_Y", "BTTS_N"]
cal = defaultdict(lambda: [0, 0.0, 0]); per = defaultdict(lambda: [0, 0.0, 0.0])
t0 = time.time()
for w in sorted({m.date - timedelta(days=m.date.weekday()) for m in tgt}):
    tl = GlobalModel.assign_leagues(dom, cups, w)
    g = GlobalModel().fit(allm, tl, w)
    for m in tgt:
        if not (w <= m.date < w + timedelta(7)):
            continue
        p = markets.all_probs(g.score_matrix(m.home, m.away, m.extra.get("neutral", False)))
        o = "H" if m.home_goals > m.away_goals else "D" if m.home_goals == m.away_goals else "A"
        comp = m.league
        per[comp][0] += 1; per[comp][1] -= math.log(p[o]); per[comp][2] -= math.log(base[o])
        hg, ag = min(m.home_goals, 10), min(m.away_goals, 10)
        for c in CODES:
            if p[c] >= 0.5:
                b = cal[min(int(p[c] * 10), 9)]; b[0] += 1; b[1] += p[c]; b[2] += bool(markets.BY_CODE[c].mask[hg, ag])
n = sum(v[0] for v in per.values())
print(f"fits done in {time.time() - t0:.0f}s")
for k, (c, ll, lb) in sorted(per.items()):
    print(f"{k:<13} n={c:<4} logloss {ll / c:.4f} base {lb / c:.4f} gain {100 * (1 - ll / lb):+.1f}%")
print(f"ALL cups      n={n:<4} logloss {sum(v[1] for v in per.values()) / n:.4f} base {sum(v[2] for v in per.values()) / n:.4f} "
      f"gain {100 * (1 - sum(v[1] for v in per.values()) / sum(v[2] for v in per.values())):+.1f}%")
for k, (c, s, w_) in sorted(cal.items()):
    print(f"  {k * 10}-{k * 10 + 10}%  n={c:<5} predicted {s / c:.1%}  won {w_ / c:.1%}")
print("league levels (attack+defence), top 12:", [(l, round(v, 2)) for l, v in g.league_table()[:12]])
print("bottom 6:", [(l, round(v, 2)) for l, v in g.league_table()[-6:]])
