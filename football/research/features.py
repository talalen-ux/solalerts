"""Walk-forward feature table: base model rates + form residuals + travel distance."""
import sys, math, pickle
sys.path.insert(0, "/home/user/solalerts")
from datetime import date, timedelta
from collections import defaultdict
from football import data
from football.model import DixonColes
from football.geo import distance_km
rows = []
for season in (2023, 2024, 2025):
    for lg in ['EPL','LALIGA','SERIEA','BUNDESLIGA','LIGUE1']:
        ms = data.load_league(lg, season, 3)
        played = sorted([m for m in ms if m.played], key=lambda m: m.date)
        tgt = [m for m in played if date(season,7,1) <= m.date < date(season+1,7,1)]
        weeks = sorted({m.date - timedelta(days=m.date.weekday()) for m in tgt})
        for w in weeks:
            try: mod = DixonColes().fit(ms, w, lg)
            except ValueError: continue
            hist = [m for m in played if m.date < w]
            def form(team, n=5):
                gs = [m for m in hist if team in (m.home, m.away)][-n:]
                gf = ga = ef = ea = 0.0
                for m in gs:
                    l, u = mod.expected_goals(m.home, m.away)
                    if m.home == team: gf += m.home_goals; ga += m.away_goals; ef += l; ea += u
                    else: gf += m.away_goals; ga += m.home_goals; ef += u; ea += l
                k = max(len(gs), 1)
                return (gf-ef)/k, (ga-ea)/k, len(gs)
            for m in tgt:
                if not (w <= m.date < w + timedelta(7)): continue
                l, u = mod.expected_goals(m.home, m.away)
                fh, fa = form(m.home), form(m.away)
                d = distance_km(m.home, m.away)
                rows.append(dict(season=season, lg=lg, hg=m.home_goals, ag=m.away_goals, lam=l, mu=u,
                                 rho=mod.rho, h_att=fh[0], h_def=fh[1], a_att=fa[0], a_def=fa[1],
                                 n=min(fh[2], fa[2]), km=d))
pickle.dump(rows, open("rows.pkl","wb"))
print(len(rows), sum(r['km'] is None for r in rows))
