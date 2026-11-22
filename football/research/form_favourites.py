"""Do in-form favourites (3+ wins in last 5) win more often than the model says?"""
import sys
from collections import defaultdict
from datetime import date, timedelta
from football import data, markets
from football.model import DixonColes

stats = defaultdict(lambda: [0, 0.0, 0])  # group -> n, sum p, wins
for season in (2023, 2024, 2025):
    for lg in ["EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1"]:
        ms = data.load_league(lg, season, 3)
        played = sorted((m for m in ms if m.played), key=lambda m: m.date)
        tgt = [m for m in played if date(season, 7, 1) <= m.date < date(season + 1, 7, 1)]
        for w in sorted({m.date - timedelta(days=m.date.weekday()) for m in tgt}):
            try:
                mod = DixonColes().fit(ms, w, lg)
            except ValueError:
                continue
            hist = [m for m in played if m.date < w]
            def wins5(t):
                g = [m for m in hist if t in (m.home, m.away)][-5:]
                return len(g), sum((m.home_goals > m.away_goals) if m.home == t else (m.away_goals > m.home_goals) for m in g)
            for m in tgt:
                if not (w <= m.date < w + timedelta(7)):
                    continue
                p = markets.all_probs(mod.score_matrix(m.home, m.away))
                for team, code, won in ((m.home, "H", m.home_goals > m.away_goals), (m.away, "A", m.away_goals > m.home_goals)):
                    if p[code] < 0.5:
                        continue
                    n, wn = wins5(team)
                    if n < 5:
                        continue
                    grp = ("in-form (3+ W)" if wn >= 3 else "not in form") + (" | p>=0.65" if p[code] >= 0.65 else " | p 0.50-0.65")
                    s = stats[grp]; s[0] += 1; s[1] += p[code]; s[2] += won
for g, (n, sp, w) in sorted(stats.items()):
    se = ((sp / n) * (1 - sp / n) / n) ** 0.5
    print(f"{g:<32} n={n:<5} model {sp / n:.1%}  actual {w / n:.1%}  diff {(w - sp) / n * 100:+.1f}pts (±{1.96 * se * 100:.1f})")
