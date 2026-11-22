"""Do trend, head-to-head, table position or clean sheets tell us more than the goal model?

Walk-forward over two seasons, 19 leagues. For every favourite (model >= 50% to win) the group it
falls in is compared on predicted v actual win rate. A stat adds information only if the gap
between predicted and actual differs between its groups."""
from collections import defaultdict
from datetime import date, timedelta
from football import espn, markets, teamstats
from football.model import DixonColes

START, END = date(2024, 11, 24), date(2026, 11, 23)
LEAGUES = [k for k in espn.LEAGUES if k not in ("LEAGUEONE", "LEAGUETWO", "LALIGA2", "SERIEB", "LIGUE2", "BUNDESLIGA2",
                                                "CHILE", "SOUTHAFRICA", "NORWAY", "SWEDEN", "DENMARK", "AUSTRIA")]
G = defaultdict(lambda: [0, 0.0, 0])
def add(k, p, won):
    g = G[k]; g[0] += 1; g[1] += p; g[2] += won
for key in LEAGUES:
    ms = espn.load_league(key, date(2026, 12, 31), 37)
    idx = teamstats.index_by_team(ms)
    tgt = [m for m in ms if m.played and START <= m.date < END]
    tables = {}
    for w in sorted({m.date - timedelta(days=m.date.weekday()) for m in tgt}):
        try: mod = DixonColes().fit(ms, w, key)
        except ValueError: continue
        for m in tgt:
            if not (w <= m.date < w + timedelta(7)): continue
            p = markets.all_probs(mod.score_matrix(m.home, m.away))
            code = "H" if p["H"] >= p["A"] else "A"
            if p[code] < 0.5: continue
            fav, dog = (m.home, m.away) if code == "H" else (m.away, m.home)
            won = (m.home_goals > m.away_goals) if code == "H" else (m.away_goals > m.home_goals)
            pr = p[code]
            f10, d10 = teamstats.last_n(idx[fav], fav, m.date), teamstats.last_n(idx[dog], dog, m.date)
            if f10 and "trend" in f10: add("trend: favourite " + f10["trend"], pr, won)
            if d10 and "trend" in d10: add("trend: underdog " + d10["trend"], pr, won)
            if f10 and f10["played"] == 10:
                add("clean sheets (fav, last 10): " + ("4+" if f10["cs"] >= 4 else "2-3" if f10["cs"] >= 2 else "0-1"), pr, won)
                add("goal diff (fav, last 10): " + ("+8 or better" if f10["gd"] >= 8 else "0 to +7" if f10["gd"] >= 0 else "negative"), pr, won)
            s = m.extra.get("season")
            h = teamstats.head_to_head(idx[fav], fav, dog, m.date, s)
            if h["n"]:
                add("head-to-head: favourite " + ("ahead" if h["home_w"] > h["away_w"] else "behind" if h["home_w"] < h["away_w"] else "level"), pr, won)
            else:
                add("head-to-head: no meetings", pr, won)
            tk = (s, w)
            if tk not in tables: tables[tk] = teamstats.table(ms, s, w)
            tb = tables[tk]
            if fav in tb and dog in tb and tb[fav]["played"] >= 8:
                gap = tb[dog]["pos"] - tb[fav]["pos"]
                add("table: favourite " + ("8+ places above" if gap >= 8 else "1-7 places above" if gap > 0 else "below underdog"), pr, won)
print(f"{'group':<44} {'n':>6}  predicted  won     gap")
for k in sorted(G):
    n, s, w = G[k]; se = ((s / n) * (1 - s / n) / n) ** .5
    print(f"{k:<44} {n:6}  {s / n:8.1%}  {w / n:6.1%}  {(w - s) / n * 100:+5.1f} (±{196 * se:.1f})")
