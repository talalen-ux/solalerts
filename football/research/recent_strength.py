"""Can last-10 goal difference / clean sheets improve the goal model out of sample?

rate_home = lam * exp(b * (gd_home - gd_away) + c * (cs_home - cs_away))   (per-game values)
rate_away = mu  * exp(-b * (...)             - c * (...))
b, c fitted on one season, scored on the other (both directions), 19 leagues."""
import math, pickle, sys
from datetime import date, timedelta
import numpy as np
from football import espn, markets, teamstats
from football.model import DixonColes

LEAGUES = [k for k in espn.LEAGUES if k not in ("LEAGUEONE", "LEAGUETWO", "LALIGA2", "SERIEB", "LIGUE2", "BUNDESLIGA2",
                                                "CHILE", "SOUTHAFRICA", "NORWAY", "SWEDEN", "DENMARK", "AUSTRIA")]
if len(sys.argv) > 1 and sys.argv[1] == "all":
    LEAGUES = list(espn.LEAGUES)
START, MID, END = date(2024, 11, 24), date(2025, 11, 24), date(2026, 11, 23)
rows = []
for key in LEAGUES:
    ms = espn.load_league(key, date(2026, 12, 31), 37)
    idx = teamstats.index_by_team(ms)
    tgt = [m for m in ms if m.played and START <= m.date < END]
    for w in sorted({m.date - timedelta(days=m.date.weekday()) for m in tgt}):
        try: mod = DixonColes().fit(ms, w, key)
        except ValueError: continue
        for m in tgt:
            if not (w <= m.date < w + timedelta(7)): continue
            h, a = teamstats.last_n(idx[m.home], m.home, m.date), teamstats.last_n(idx[m.away], m.away, m.date)
            if not h or not a or h["played"] < 10 or a["played"] < 10: continue
            lam, mu = mod.expected_goals(m.home, m.away)
            rows.append((m.date >= MID, lam, mu, m.home_goals, m.away_goals, (h["gd"] - a["gd"]) / 10, (h["cs"] - a["cs"]) / 10, mod.rho))
R = np.array(rows, float); print(len(R), "matches")
def fit(X, use_c=True):
    b = np.zeros(2)
    for _ in range(40):
        f = np.c_[X[:, 5], X[:, 6] if use_c else 0 * X[:, 6]]
        e = f @ b
        lh, la = X[:, 1] * np.exp(e), X[:, 2] * np.exp(-e)
        g = f.T @ ((X[:, 3] - lh) - (X[:, 4] - la))
        H = (f * (lh + la)[:, None]).T @ f + np.eye(2) * 1e-6
        b += np.linalg.solve(H, g)
    return b
dc = DixonColes()
def score(X, b):
    ll = 0.0; brier_fav = 0.0
    for r in X:
        e = b[0] * r[5] + b[1] * r[6]; dc.rho = r[7]
        p = markets.all_probs(dc.matrix_from_rates(r[1] * math.exp(e), r[2] * math.exp(-e)))
        o = "H" if r[3] > r[4] else "D" if r[3] == r[4] else "A"
        ll -= math.log(p[o])
    return ll / len(X)
A, B = R[R[:, 0] == 0], R[R[:, 0] == 1]
for name, tr, te in (("fit 2024-25, test 2025-26", A, B), ("fit 2025-26, test 2024-25", B, A)):
    base = score(te, np.zeros(2))
    for label, use_c in (("goal diff only", False), ("goal diff + clean sheets", True)):
        b = fit(tr, use_c)
        print(f"{name}: {label:<26} b={b[0]:+.3f} c={b[1]:+.3f}  test logloss {score(te, b):.4f} vs base {base:.4f} ({score(te, b) - base:+.4f})")
print("both seasons:", fit(R, False), fit(R, True))
pickle.dump(R, open("/tmp/claude-0/-home-user-solalerts/41a047d0-8af8-5ca5-a4d9-22504ba594f0/scratchpad/recent_rows.pkl", "wb"))
