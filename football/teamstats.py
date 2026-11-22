"""Descriptive team stats for the card: league table, last-10 record and trend, clean sheets,
head-to-head this season and last.

These are shown for context. research/context_stats.py tests whether each one says anything the
goal model does not already know.
"""

from __future__ import annotations

from collections import defaultdict

TREND_STEP = 0.6   # change in goal difference per game (last 5 v previous 5) that counts as a trend


def index_by_team(matches):
    idx = defaultdict(list)
    for m in matches:
        if m.played:
            idx[m.home].append(m)
            idx[m.away].append(m)
    for ms in idx.values():
        ms.sort(key=lambda m: m.date)
    return idx


def table(league_matches, season, before) -> dict:
    """{team: {pos, played, pts, gd, gf, ga}} for one league season, from matches before a date."""
    t = defaultdict(lambda: {"played": 0, "pts": 0, "gf": 0, "ga": 0})
    for m in league_matches:
        if not m.played or m.date >= before or m.extra.get("season") != season:
            continue
        for team, gf, ga in ((m.home, m.home_goals, m.away_goals), (m.away, m.away_goals, m.home_goals)):
            r = t[team]
            r["played"] += 1; r["gf"] += gf; r["ga"] += ga
            r["pts"] += 3 if gf > ga else 1 if gf == ga else 0
    order = sorted(t, key=lambda k: (-t[k]["pts"], -(t[k]["gf"] - t[k]["ga"]), -t[k]["gf"], k))
    return {k: {**t[k], "gd": t[k]["gf"] - t[k]["ga"], "pos": i + 1, "of": len(order)} for i, k in enumerate(order)}


def _line(team, m):
    return (m.home_goals, m.away_goals) if m.home == team else (m.away_goals, m.home_goals)


def last_n(team_matches, team, before, n: int = 10) -> dict | None:
    ms = [m for m in team_matches if m.date < before][-n:]
    if len(ms) < 4:
        return None
    rows = [_line(team, m) for m in ms]
    gf, ga = sum(r[0] for r in rows), sum(r[1] for r in rows)
    out = {"played": len(rows), "gf": gf, "ga": ga, "gd": gf - ga,
           "w": sum(a > b for a, b in rows), "d": sum(a == b for a, b in rows), "l": sum(a < b for a, b in rows),
           "cs": sum(b == 0 for _, b in rows), "failed_to_score": sum(a == 0 for a, _ in rows)}
    if len(rows) >= 8:
        half = len(rows) // 2
        old, new = rows[:half], rows[half:]
        per = lambda rs: sum(a - b for a, b in rs) / len(rs)
        delta = per(new) - per(old)
        out["trend_delta"] = round(delta, 2)
        out["trend"] = "improving" if delta >= TREND_STEP else "declining" if delta <= -TREND_STEP else "steady"
        out["gf_recent"], out["ga_recent"] = sum(a for a, _ in new), sum(b for _, b in new)
        out["gf_before"], out["ga_before"] = sum(a for a, _ in old), sum(b for _, b in old)
    return out


def head_to_head(team_matches, home, away, before, season) -> dict:
    """Meetings between the two sides this season and last (any competition on the card)."""
    meets = [m for m in team_matches if m.date < before and away in (m.home, m.away)]
    this, last = [], []
    for m in meets:
        s = m.extra.get("season")
        row = {"date": m.date.isoformat(), "home": m.home, "away": m.away, "score": f"{m.home_goals}-{m.away_goals}",
               "league": m.league}
        if season is not None and s == season:
            this.append(row)
        elif season is not None and s == season - 1:
            last.append(row)
        elif season is None and (before - m.date).days <= 800:
            last.append(row)
    w = d = l = 0
    for m in meets:
        if season is not None and m.extra.get("season") not in (season, season - 1):
            continue
        a, b = _line(home, m)
        w += a > b; d += a == b; l += a < b
    return {"this_season": this, "last_season": last, "home_w": w, "draws": d, "away_w": l, "n": w + d + l}


def shape(last10: dict | None) -> str | None:
    """Recent shape of a team from its last 10. For favourites over 2024-26 (research/context_stats.py):
    solid ones won 3.7 points more often than the model predicted, shaky ones 3.2 points less."""
    if not last10 or last10["played"] < 10:
        return None
    if last10["cs"] >= 4 and last10["gd"] >= 0:
        return "solid"
    if last10["cs"] <= 1 or last10["gd"] < 0:
        return "shaky"
    return None
