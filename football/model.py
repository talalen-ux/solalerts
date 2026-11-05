"""Dixon-Coles goal model with time decay, fitted per league.

log(home goals rate) = mu + home_adv + attack[home] - defence[away]
log(away goals rate) = mu            + attack[away] - defence[home]

Fitted by penalised Newton-Raphson (weighted Poisson likelihood, ridge pull toward a
prior), then the Dixon-Coles low-score correlation rho is chosen by 1-D search.
The ridge prior is 0 for established teams and negative for newly promoted ones, so a
promoted side starts below league average and the data moves it from there.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from .data import Match

MAX_GOALS = 10
DEFAULT_XI = 0.0015        # per-day decay: a match 15 months old counts ~half (tuned on 2024-26)
DEFAULT_RIDGE = 8.0        # prior strength in (decayed) matches (tuned on 2024-26 walk-forward)
PROMOTED_PRIOR = -0.20     # attack and defence prior for teams new to the league


def _poisson_pmf(lam: float, k: np.ndarray) -> np.ndarray:
    return np.exp(k * math.log(lam) - lam - np.array([math.lgamma(x + 1) for x in k]))


def _tau(hg, ag, lam, mu, rho):
    """Dixon-Coles adjustment for the four low-scoring cells (vectorised)."""
    t = np.ones_like(lam)
    t = np.where((hg == 0) & (ag == 0), 1 - lam * mu * rho, t)
    t = np.where((hg == 0) & (ag == 1), 1 + lam * rho, t)
    t = np.where((hg == 1) & (ag == 0), 1 + mu * rho, t)
    t = np.where((hg == 1) & (ag == 1), 1 - rho, t)
    return t


@dataclass
class TeamRating:
    attack: float
    defence: float
    weight: float  # decayed number of matches the rating rests on


class DixonColes:
    def __init__(self, xi: float = DEFAULT_XI, ridge: float = DEFAULT_RIDGE):
        self.xi = xi
        self.ridge = ridge
        self.teams: dict[str, TeamRating] = {}
        self.mu = 0.3
        self.home_adv = 0.25
        self.rho = 0.0
        self.as_of: date | None = None
        self.league: str | None = None

    # ------------------------------------------------------------- fitting
    def fit(self, matches: list[Match], as_of: date, league: str | None = None) -> "DixonColes":
        """Fit on played matches strictly before `as_of`, for teams in `league` if given."""
        self.as_of, self.league = as_of, league
        played = [m for m in matches if m.played and m.date < as_of
                  and (league is None or m.league == league)]
        if len(played) < 30:
            raise ValueError(f"Not enough matches to fit {league or ''} before {as_of}: {len(played)}")

        names = sorted({m.home for m in played} | {m.away for m in played})
        idx = {t: i for i, t in enumerate(names)}
        n = len(names)

        hi = np.array([idx[m.home] for m in played])
        ai = np.array([idx[m.away] for m in played])
        hg = np.array([m.home_goals for m in played], float)
        ag = np.array([m.away_goals for m in played], float)
        age = np.array([(as_of - m.date).days for m in played], float)
        w = np.exp(-self.xi * age)

        prior = self._priors(played, names, as_of)
        # theta = [mu, home, att(n), def(n)]
        theta = np.zeros(2 + 2 * n)
        theta[0] = math.log(max(np.average(np.r_[hg, ag], weights=np.r_[w, w]), 0.1))
        theta[1] = 0.2
        theta[2:2 + n] = prior
        theta[2 + n:] = prior

        # design: rows for home-goal and away-goal observations
        m = len(played)
        X = np.zeros((2 * m, 2 + 2 * n))
        r = np.arange(m)
        X[r, 0] = 1; X[r, 1] = 1; X[r, 2 + hi] = 1; X[r, 2 + n + ai] = -1
        X[m + r, 0] = 1; X[m + r, 2 + ai] = 1; X[m + r, 2 + n + hi] = -1
        y = np.r_[hg, ag]
        ww = np.r_[w, w]
        P = np.zeros(2 + 2 * n); P[2:] = self.ridge
        pr = np.r_[0, 0, prior, prior]
        P[:2] = 1e-6

        for _ in range(50):
            lam = np.exp(np.clip(X @ theta, -10, 5))
            grad = X.T @ (ww * (y - lam)) - P * (theta - pr)
            H = (X * (ww * lam)[:, None]).T @ X + np.diag(P)
            step = np.linalg.solve(H, grad)
            theta += step
            if np.max(np.abs(step)) < 1e-8:
                break

        self.mu, self.home_adv = float(theta[0]), float(theta[1])
        wt = np.bincount(hi, w, n) + np.bincount(ai, w, n)
        self.teams = {t: TeamRating(float(theta[2 + i]), float(theta[2 + n + i]), float(wt[i]))
                      for t, i in idx.items()}

        lam_h = np.exp(theta[0] + theta[1] + theta[2 + hi] - theta[2 + n + ai])
        lam_a = np.exp(theta[0] + theta[2 + ai] - theta[2 + n + hi])
        self.rho = self._fit_rho(hg, ag, lam_h, lam_a, w)
        return self

    def _priors(self, played, names, as_of) -> np.ndarray:
        """Negative prior for teams absent from the league's previous season (promoted)."""
        season_start = date(as_of.year if as_of.month >= 7 else as_of.year - 1, 7, 1)
        prev_start = date(season_start.year - 1, 7, 1)
        prev = {t for m in played if prev_start <= m.date < season_start for t in (m.home, m.away)}
        if not prev:
            return np.zeros(len(names))
        return np.array([0.0 if t in prev else PROMOTED_PRIOR for t in names])

    @staticmethod
    def _fit_rho(hg, ag, lam, mu, w) -> float:
        low = (hg <= 1) & (ag <= 1)
        best, best_ll = 0.0, -np.inf
        for rho in np.linspace(-0.25, 0.25, 101):
            t = _tau(hg[low], ag[low], lam[low], mu[low], rho)
            if np.any(t <= 0):
                continue
            ll = float(np.sum(w[low] * np.log(t)))
            if ll > best_ll:
                best, best_ll = float(rho), ll
        return best

    # ------------------------------------------------------------- predicting
    def rating(self, team: str) -> TeamRating:
        if team in self.teams:
            return self.teams[team]
        return TeamRating(PROMOTED_PRIOR, PROMOTED_PRIOR, 0.0)  # never seen: assume promoted

    def expected_goals(self, home: str, away: str) -> tuple[float, float]:
        h, a = self.rating(home), self.rating(away)
        lam = math.exp(self.mu + self.home_adv + h.attack - a.defence)
        mu = math.exp(self.mu + a.attack - h.defence)
        return lam, mu

    def score_matrix(self, home: str, away: str) -> np.ndarray:
        """P[i, j] = probability the match finishes home i - away j (0..MAX_GOALS)."""
        lam, mu = self.expected_goals(home, away)
        k = np.arange(MAX_GOALS + 1)
        M = np.outer(_poisson_pmf(lam, k), _poisson_pmf(mu, k))
        M[0, 0] *= 1 - lam * mu * self.rho
        M[0, 1] *= 1 + lam * self.rho
        M[1, 0] *= 1 + mu * self.rho
        M[1, 1] *= 1 - self.rho
        M = np.clip(M, 0, None)
        return M / M.sum()

    def table(self) -> list[tuple[str, float, float, float]]:
        """Teams by overall strength (attack + defence)."""
        rows = [(t, r.attack, r.defence, r.attack + r.defence) for t, r in self.teams.items()]
        return sorted(rows, key=lambda x: -x[3])
