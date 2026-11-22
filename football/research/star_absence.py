"""Does it matter when a team's star does not start? Walk-forward, 12 leagues, Nov 2025 - Nov 2026.

For each league match: grade each team's players from its previous 8 line-ups (league matches),
then compare goals scored and conceded with the model's expectation, split by whether the stars
started this match, and by whether a star was missing from the PREVIOUS matchday squad (the only
thing known before line-ups come out)."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from football import espn, players
from football.model import DixonColes

LEAGUES = ["EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "EREDIVISIE", "PRIMEIRA", "BELGIUM", "TURKEY",
           "SAUDI", "CHAMPIONSHIP", "BRAZIL"]
START, END = date(2025, 11, 24), date(2026, 11, 23)
G = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])   # n, xg for, goals for, xg against, goals against
for key in LEAGUES:
    ms = espn.load_league(key, date(2026, 12, 31), 37)
    played = sorted((m for m in ms if m.played and m.extra.get("espn_id")), key=lambda m: m.date)
    need = [m for m in played if START - timedelta(days=120) <= m.date < END]
    with ThreadPoolExecutor(12) as ex:
        sums = dict(zip((m.extra["espn_id"] for m in need), ex.map(lambda m: players.summary(key, m.extra["espn_id"]), need)))
    hist = defaultdict(list)                          # team -> [(match, rows)]
    tgt = [m for m in need if m.date >= START]
    models = {}
    for m in need:
        s = sums.get(m.extra["espn_id"]) or {}
        if m.date >= START and m.home in s and m.away in s:
            w = m.date - timedelta(days=m.date.weekday())
            if w not in models:
                try: models[w] = DixonColes().fit(ms, w, key)
                except ValueError: models[w] = None
            mod = models[w]
            if mod:
                lam, mu = mod.expected_goals(m.home, m.away)
                for team, xf, gf, xa, ga in ((m.home, lam, m.home_goals, mu, m.away_goals), (m.away, mu, m.away_goals, lam, m.home_goals)):
                    logs = hist[team][-8:]
                    if len(logs) >= 6:
                        prof = players.profile(logs)
                        stars = prof["stars"]
                        if stars:
                            starters = {r["id"] for r in s[team] if r["start"]}
                            out = sum(x["id"] not in starters for x in stars)
                            a = "A star not starting" if out else "All stars start"
                            b = "A star missed previous squad" if any(not x["in_last_squad"] for x in stars) else "Stars in previous squad"
                            top = stars[0]
                            c = "Top star not starting" if top["id"] not in starters else "Top star starts"
                            for k in (a, b, c):
                                g = G[k]; g[0] += 1; g[1] += xf; g[2] += gf; g[3] += xa; g[4] += ga
                        reg = [x for x in prof["players"] if x["tier"] in ("star", "regular")]
                        if len(reg) >= 6:
                            starters = {r["id"] for r in s[team] if r["start"]}
                            miss = sum(x["id"] not in starters for x in reg)
                            k = "0-1 regulars rested" if miss <= 1 else "2-3 regulars rested" if miss <= 3 else "4+ regulars rested"
                            g = G[k]; g[0] += 1; g[1] += xf; g[2] += gf; g[3] += xa; g[4] += ga
        for team in (m.home, m.away):
            if team in s and s[team]:
                hist[team].append((m, s[team]))
print(f"{'group':<30} {'n':>6}  goals for vs model   goals against vs model")
for k in ["All stars start", "A star not starting", "Top star starts", "Top star not starting", "Stars in previous squad",
          "A star missed previous squad", "0-1 regulars rested", "2-3 regulars rested", "4+ regulars rested"]:
    n, xf, gf, xa, ga = G[k]
    if n:
        se = (1 / max(gf, 1)) ** .5
        print(f"{k:<30} {n:6}  {gf / xf:.3f} (±{1.96 * se:.3f})       {ga / xa:.3f}")
