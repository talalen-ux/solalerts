"""Glue: load leagues, fit one model per league, predict a fixture window, attach odds."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta

from . import data
from .leagues import LEAGUES, season_start_year
from .markets import BY_CODE
from .model import DixonColes, DEFAULT_RIDGE, DEFAULT_XI
from .parlay import MatchPrediction


@dataclass
class LeagueState:
    league: str
    matches: list[data.Match]
    model: DixonColes
    last_result: date | None


def load_and_fit(leagues: list[str], as_of: date, seasons: int = 3, refresh: bool = False,
                 results_csv: str | None = None, xi: float = DEFAULT_XI,
                 ridge: float = DEFAULT_RIDGE) -> dict[str, LeagueState]:
    states = {}
    start = season_start_year(as_of)
    all_matches = {lg: data.load_league(lg, start, seasons, refresh) for lg in leagues}
    if results_csv:
        for lg in leagues:
            data.merge_results_csv(all_matches[lg], results_csv)
    for lg in leagues:
        ms = all_matches[lg]
        model = DixonColes(xi=xi, ridge=ridge).fit(ms, as_of, lg)
        states[lg] = LeagueState(lg, ms, model, data.latest_result_date(
            [m for m in ms if m.date < as_of]))
    return states


def upcoming(state: LeagueState, start: date, days: int) -> list[data.Match]:
    end = start + timedelta(days=days)
    return sorted((m for m in state.matches if not m.played and start <= m.date < end),
                  key=lambda m: (m.date, m.time))


def predict(state: LeagueState, fixtures: list[data.Match]) -> list[MatchPrediction]:
    out = []
    for m in fixtures:
        out.append(MatchPrediction(m, state.model.score_matrix(m.home, m.away),
                                   state.model.expected_goals(m.home, m.away)))
    return out


def attach_odds(preds: list[MatchPrediction], path: str) -> tuple[int, list[str]]:
    """Read odds CSV: home,away,selection,odds[,league,date]. Returns (rows used, problems).

    `selection` is a code from markets.BY_CODE (H, D, A, O2.5, BTTS_Y, ...) or a same-game
    combo joined with '+', e.g. 'H+O1.5'.
    """
    resolver = data.TeamResolver({t for p in preds for t in (p.match.home, p.match.away)})
    by_teams = {(p.match.home, p.match.away): p for p in preds}
    used, problems = 0, []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            home, away = resolver.resolve(row["home"]), resolver.resolve(row["away"])
            p = by_teams.get((home, away))
            sel = row["selection"].strip().upper().replace("BTTS_YES", "BTTS_Y").replace("BTTS_NO", "BTTS_N")
            sel = "+".join(c.strip() for c in sel.split("+"))
            if p is None:
                problems.append(f"line {i}: no fixture in window for {row['home']} v {row['away']}")
                continue
            if not all(c in BY_CODE for c in sel.split("+")):
                problems.append(f"line {i}: unknown selection {row['selection']!r}")
                continue
            try:
                odds = float(row["odds"])
            except ValueError:
                problems.append(f"line {i}: bad odds {row['odds']!r}")
                continue
            if odds <= 1:
                problems.append(f"line {i}: odds must be decimal > 1")
                continue
            p.odds[sel] = odds
            used += 1
    return used, problems


def resolve_leagues(arg: str) -> list[str]:
    if arg.upper() == "ALL":
        return list(LEAGUES)
    from .leagues import resolve
    return [resolve(x) for x in arg.split(",")]
