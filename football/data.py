"""Match data: openfootball JSON (results + fixtures) with a local cache, plus CSV loaders.

Two optional CSV inputs extend what openfootball has:
  * results CSV  (date,home,away,home_goals,away_goals[,league]) to fill in results the
    public feed has not caught up with yet;
  * football-data.co.uk style CSVs (Date,HomeTeam,AwayTeam,FTHG,FTAG,...) for deeper history.
"""

from __future__ import annotations

import csv
import difflib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import requests

from .leagues import LEAGUES, season_label

BASE_URL = "https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{file}.json"
CACHE_DIR = Path(os.environ.get("FOOTBALL_CACHE", Path(__file__).parent / ".cache"))
CACHE_TTL_SECONDS = 6 * 3600


@dataclass
class Match:
    league: str
    date: date
    home: str
    away: str
    home_goals: int | None = None
    away_goals: int | None = None
    time: str = ""
    round: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def played(self) -> bool:
        return self.home_goals is not None and self.away_goals is not None

    @property
    def key(self) -> tuple:
        return (self.league, self.date, self.home, self.away)


# ---------------------------------------------------------------- team names

_STRIP = re.compile(
    r"\b(fc|afc|cf|sc|ac|as|ssc|ss|us|ud|cd|rc|rcd|sd|sv|vfb|vfl|tsg|bv|bsc|fk|sk|"
    r"club|calcio|de|futbol|football|1\.|04|05|1899|1900|1846|1907|1909|1910|1913)\b"
)


def norm_name(name: str) -> str:
    s = name.lower()
    for a, b in (("ü", "u"), ("ö", "o"), ("ä", "a"), ("é", "e"), ("á", "a"), ("í", "i"),
                 ("ó", "o"), ("ç", "c"), ("ã", "a"), ("ñ", "n"), ("&", " and ")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9. ]", " ", s)
    s = _STRIP.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


ALIASES = {  # common short forms -> normalised openfootball forms
    "man united": "manchester united", "man utd": "manchester united",
    "man city": "manchester city", "spurs": "tottenham hotspur", "tottenham": "tottenham hotspur",
    "wolves": "wolverhampton wanderers", "newcastle": "newcastle united",
    "nottm forest": "nottingham forest", "nott m forest": "nottingham forest",
    "west ham": "west ham united", "brighton": "brighton and hove albion",
    "leeds": "leeds united", "inter": "internazionale", "inter milan": "internazionale",
    "milan": "milan", "bayern": "bayern munchen", "bayern munich": "bayern munchen",
    "dortmund": "borussia dortmund", "leverkusen": "bayer leverkusen",
    "m gladbach": "borussia monchengladbach", "gladbach": "borussia monchengladbach",
    "psg": "paris saint germain", "paris sg": "paris saint germain",
    "ath madrid": "atletico madrid", "atletico": "atletico madrid",
    "ath bilbao": "athletic bilbao", "betis": "real betis", "sociedad": "real sociedad",
    "sp lisbon": "sporting clube portugal", "sporting": "sporting clube portugal",
    "sporting cp": "sporting clube portugal", "benfica": "sport lisboa e benfica",
    "porto": "porto", "sp braga": "sporting braga", "braga": "sporting braga",
    "psv": "psv", "ajax": "ajax", "feyenoord": "feyenoord",
}


class TeamResolver:
    """Maps free-form team names onto the canonical names present in the match data."""

    def __init__(self, names):
        self.canon = sorted(set(names))
        self.by_norm = {norm_name(n): n for n in self.canon}

    def resolve(self, name: str) -> str | None:
        if name in self.canon:
            return name
        n = norm_name(name)
        n = ALIASES.get(n, n)
        if n in self.by_norm:
            return self.by_norm[n]
        for k, v in self.by_norm.items():  # containment: "Bournemouth" in "afc bournemouth"
            if n and (n in k.split() or (len(n) > 4 and n in k) or (len(k) > 4 and k in n)):
                return v
        hit = difflib.get_close_matches(n, list(self.by_norm), n=1, cutoff=0.72)
        return self.by_norm[hit[0]] if hit else None


# ---------------------------------------------------------------- openfootball

def _fetch_json(season: str, file: str, current: bool, refresh: bool = False) -> dict | None:
    """Past seasons are cached forever; the current one for CACHE_TTL_SECONDS."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{season}_{file}.json"
    fresh = path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS
    if path.exists() and not refresh and (fresh or not current):
        return json.loads(path.read_text())
    try:
        r = requests.get(BASE_URL.format(season=season, file=file), timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        path.write_text(r.text)
        return r.json()
    except requests.RequestException:
        if path.exists():
            return json.loads(path.read_text())
        raise


def _parse_score(score):
    if not score:
        return None, None
    ft = score.get("ft") if isinstance(score, dict) else score
    if isinstance(ft, list) and len(ft) == 2 and all(isinstance(x, int) for x in ft):
        return ft[0], ft[1]
    return None, None


def load_league_season(league: str, start_year: int, current: bool = False,
                       refresh: bool = False) -> list[Match]:
    data = _fetch_json(season_label(start_year), LEAGUES[league]["file"], current, refresh)
    if not data:
        return []
    out = []
    for m in data.get("matches", []):
        hg, ag = _parse_score(m.get("score"))
        out.append(Match(league, datetime.strptime(m["date"], "%Y-%m-%d").date(),
                         m["team1"], m["team2"], hg, ag, m.get("time", ""), m.get("round", "")))
    return out


def load_league(league: str, current_start_year: int, seasons: int = 3,
                refresh: bool = False) -> list[Match]:
    matches = []
    for y in range(current_start_year - seasons + 1, current_start_year + 1):
        cur = y == current_start_year
        matches += load_league_season(league, y, current=cur, refresh=refresh and cur)
    return matches


# ---------------------------------------------------------------- CSV inputs

def _parse_date(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date {s!r}")


def merge_results_csv(matches: list[Match], path: str, league: str | None = None) -> int:
    """Apply results from a CSV to existing fixtures (or add them). Returns rows applied.

    Columns: date,home,away,home_goals,away_goals[,league]. football-data.co.uk columns
    (Date,HomeTeam,AwayTeam,FTHG,FTAG) are accepted too.
    """
    resolvers: dict[str, TeamResolver] = {}
    by_key = {}
    for m in matches:
        by_key.setdefault((m.league, m.home, m.away), []).append(m)
    applied = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            lg = (row.get("league") or league or "").upper()
            if lg not in LEAGUES:
                continue
            if lg not in resolvers:
                resolvers[lg] = TeamResolver(m.home for m in matches if m.league == lg)
            res = resolvers[lg]
            home = res.resolve(row.get("home") or row.get("HomeTeam", ""))
            away = res.resolve(row.get("away") or row.get("AwayTeam", ""))
            hg = row.get("home_goals", row.get("FTHG"))
            ag = row.get("away_goals", row.get("FTAG"))
            if not (home and away) or hg in (None, "") or ag in (None, ""):
                continue
            d = _parse_date(row.get("date") or row["Date"])
            cands = by_key.get((lg, home, away), [])
            target = min(cands, key=lambda m: abs((m.date - d).days), default=None)
            if target is not None and abs((target.date - d).days) <= 10:
                target.home_goals, target.away_goals = int(hg), int(ag)
            else:
                matches.append(Match(lg, d, home, away, int(hg), int(ag)))
            applied += 1
    return applied


def latest_result_date(matches: list[Match]) -> date | None:
    played = [m.date for m in matches if m.played]
    return max(played) if played else None
