"""One goal model across every league, for cross-league matches (Champions League, Europa League,
Conference League, AFC Champions League, Libertadores...).

log(rate) = mu + home*(not neutral) + LeagueAttack[L(team)] + attack[team]
                                     - LeagueDefence[L(opponent)] - defence[opponent]

Team ratings are shrunk toward their own league's level, not toward a global mean, so a mid-table
Belgian side is not dragged up to the Premier League average. League levels are pinned down by the
continental cup matches that link the leagues. Fitted by sparse Newton steps (each match touches
at most six parameters), with time decay and a Dixon-Coles low-score correction.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, timedelta

import numpy as np

from .data import Match
from .model import MAX_GOALS, DixonColes

XI = 0.0015
TEAM_RIDGE = 8.0      # team offsets toward their league level, in decayed matches
LEAGUE_RIDGE = 2.0    # league levels toward the global level
FALLBACK = {"EU": "UEFA_OTHER", "AS": "AFC_OTHER", "SA": "CONMEBOL_OTHER"}


class GlobalModel:
    def __init__(self, xi: float = XI, team_ridge: float = TEAM_RIDGE, league_ridge: float = LEAGUE_RIDGE):
        self.xi, self.team_ridge, self.league_ridge = xi, team_ridge, league_ridge
        self._dc = DixonColes()  # reuse its score-matrix code

    @staticmethod
    def assign_leagues(domestic: dict[str, list[Match]], cup_matches: list[Match], as_of: date) -> dict[str, str]:
        """Each team's league: where it played most league games in the year before as_of."""
        cnt = defaultdict(Counter)
        for lg, ms in domestic.items():
            for m in ms:
                if m.played and as_of - timedelta(days=400) <= m.date < as_of:
                    cnt[m.home][lg] += 1
                    cnt[m.away][lg] += 1
        out = {t: c.most_common(1)[0][0] for t, c in cnt.items()}
        for m in cup_matches:  # teams from leagues the card does not cover
            for t in (m.home, m.away):
                out.setdefault(t, FALLBACK.get(m.extra.get("confed", "EU"), "UEFA_OTHER"))
        return out

    def fit(self, matches: list[Match], team_league: dict[str, str], as_of: date) -> "GlobalModel":
        ms = [m for m in matches if m.played and m.date < as_of and m.home in team_league and m.away in team_league]
        teams = sorted({t for m in ms for t in (m.home, m.away)})
        leagues = sorted({team_league[t] for t in teams})
        ti = {t: i for i, t in enumerate(teams)}
        li = {l: i for i, l in enumerate(leagues)}
        nT, nL = len(teams), len(leagues)
        # parameter layout: 0 mu, 1 home, [2, 2+nL) LA, [.., +nL) LD, then team a, team d
        LA, LD, A, D = 2, 2 + nL, 2 + 2 * nL, 2 + 2 * nL + nT
        P = 2 + 2 * nL + 2 * nT

        rows = []  # (y, weight, [(param, sign)...])
        for m in ms:
            w = math.exp(-self.xi * (as_of - m.date).days) * m.extra.get("weight", 1.0)
            h, a = ti[m.home], ti[m.away]
            lh, la = li[team_league[m.home]], li[team_league[m.away]]
            home = 0.0 if m.extra.get("neutral") else 1.0
            rows.append((m.home_goals, w, [(0, 1.0), (1, home), (LA + lh, 1.0), (A + h, 1.0), (LD + la, -1.0), (D + a, -1.0)]))
            rows.append((m.away_goals, w, [(0, 1.0), (LA + la, 1.0), (A + a, 1.0), (LD + lh, -1.0), (D + h, -1.0)]))
        n = len(rows)
        K = 6
        idx = np.zeros((n, K), dtype=np.int64)
        val = np.zeros((n, K))
        for r, (_, _, terms) in enumerate(rows):
            for k, (p, s) in enumerate(terms):
                idx[r, k], val[r, k] = p, s
        y = np.array([r[0] for r in rows], float)
        wt = np.array([r[1] for r in rows])

        ridge = np.zeros(P)
        ridge[LA:LD + nL] = self.league_ridge
        ridge[A:] = self.team_ridge
        ridge[:2] = 1e-6
        theta = np.zeros(P)
        theta[0] = math.log(max(np.average(y, weights=wt), 0.1))
        theta[1] = 0.25
        for _ in range(40):
            eta = (theta[idx] * val).sum(1)
            lam = np.exp(np.clip(eta, -10, 5))
            resid = wt * (y - lam)
            grad = np.zeros(P)
            np.add.at(grad, idx.ravel(), (val * resid[:, None]).ravel())
            grad -= ridge * theta
            H = np.zeros((P, P))
            c = wt * lam
            for j in range(K):
                for k in range(K):
                    np.add.at(H, (idx[:, j], idx[:, k]), c * val[:, j] * val[:, k])
            H[np.diag_indices(P)] += ridge
            step = np.linalg.solve(H, grad)
            theta += step
            if np.max(np.abs(step)) < 1e-7:
                break

        self.mu, self.home_adv = theta[0], theta[1]
        self.league_att = {l: theta[LA + i] for l, i in li.items()}
        self.league_def = {l: theta[LD + i] for l, i in li.items()}
        self.att = {t: theta[A + i] for t, i in ti.items()}
        self.dfn = {t: theta[D + i] for t, i in ti.items()}
        self.team_league = team_league
        # Dixon-Coles rho on the fitted rates
        eta = (theta[idx] * val).sum(1)
        lam = np.exp(eta)
        hg, ag = y[0::2], y[1::2]
        self.rho = DixonColes._fit_rho(hg, ag, lam[0::2], lam[1::2], wt[0::2])
        self._dc.rho = self.rho
        return self

    def strength(self, team: str) -> tuple[float, float]:
        lg = self.team_league.get(team)
        return (self.league_att.get(lg, 0.0) + self.att.get(team, 0.0),
                self.league_def.get(lg, 0.0) + self.dfn.get(team, 0.0))

    def expected_goals(self, home: str, away: str, neutral: bool = False) -> tuple[float, float]:
        ha, hd = self.strength(home)
        aa, ad = self.strength(away)
        base = self.mu
        lam = math.exp(base + (0.0 if neutral else self.home_adv) + ha - ad)
        mu = math.exp(base + aa - hd)
        return lam, mu

    def matrix_from_rates(self, lam: float, mu: float) -> np.ndarray:
        return self._dc.matrix_from_rates(lam, mu)

    def score_matrix(self, home: str, away: str, neutral: bool = False) -> np.ndarray:
        return self.matrix_from_rates(*self.expected_goals(home, away, neutral))

    def league_table(self) -> list[tuple[str, float]]:
        return sorted(((l, self.league_att[l] + self.league_def[l]) for l in self.league_att), key=lambda x: -x[1])
