"""Walk-forward check of the goal model on every ESPN league: refit weekly, predict that week."""
import math
from collections import defaultdict
from datetime import date, timedelta
from football import espn, markets
from football.model import DixonColes

START, END = date(2025, 11, 24), date(2026, 11, 23)
CODES = ["H", "A", "1X", "X2", "O1.5", "O2.5", "U2.5", "U3.5", "BTTS_Y", "BTTS_N"]
cal = defaultdict(lambda: [0, 0.0, 0])
print(f"{'league':<13} {'n':>5}  logloss  base    gain")
tot = [0, 0.0, 0.0]
for key in espn.LEAGUES:
    ms = espn.load_league(key, date(2026, 12, 31), 37)
    played = [m for m in ms if m.played]
    tgt = [m for m in played if START <= m.date < END]
    prior = [m for m in played if START - timedelta(days=730) <= m.date < START]
    if not tgt or len(prior) < 100:
        continue
    base = {o: max(sum(f(m) for m in prior) / len(prior), 1e-3) for o, f in
            (("H", lambda m: m.home_goals > m.away_goals), ("D", lambda m: m.home_goals == m.away_goals),
             ("A", lambda m: m.home_goals < m.away_goals))}
    ll = llb = 0.0; n = 0
    for w in sorted({m.date - timedelta(days=m.date.weekday()) for m in tgt}):
        try:
            mod = DixonColes().fit(ms, w, key)
        except ValueError:
            continue
        for m in tgt:
            if not (w <= m.date < w + timedelta(7)):
                continue
            p = markets.all_probs(mod.score_matrix(m.home, m.away))
            o = "H" if m.home_goals > m.away_goals else "D" if m.home_goals == m.away_goals else "A"
            ll -= math.log(p[o]); llb -= math.log(base[o]); n += 1
            hg, ag = min(m.home_goals, 10), min(m.away_goals, 10)
            for c in CODES:
                if p[c] >= 0.5:
                    b = cal[min(int(p[c] * 10), 9)]
                    b[0] += 1; b[1] += p[c]; b[2] += bool(markets.BY_CODE[c].mask[hg, ag])
    if n:
        tot[0] += n; tot[1] += ll; tot[2] += llb
        print(f"{key:<13} {n:5}  {ll / n:.4f}  {llb / n:.4f}  {100 * (1 - ll / llb):+.1f}%")
print(f"{'ALL':<13} {tot[0]:5}  {tot[1] / tot[0]:.4f}  {tot[2] / tot[0]:.4f}  {100 * (1 - tot[1] / tot[2]):+.1f}%")
print("calibration (legs >= 50%):")
for k, (n, s, w) in sorted(cal.items()):
    print(f"  {k * 10}-{k * 10 + 10}%  n={n:<6} predicted {s / n:.1%}  won {w / n:.1%}")
