"""ESPN public scoreboard feed: fixtures and results for every league the card covers.

One request per league per month (`?dates=YYYYMM`). Past months are cached for good, the
current and future months for six hours. Team colours and abbreviations come with the feed
and are used for the card's badges.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import requests

from .data import Match

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates={ym}"
CACHE = Path(os.environ.get("FOOTBALL_CACHE", Path(__file__).parent / ".cache")) / "espn"
TTL = 6 * 3600

# key: (ESPN code, display name, short label, region)
LEAGUES = {
    # Europe: top five
    "EPL": ("eng.1", "Premier League", "EPL", "Europe"),
    "LALIGA": ("esp.1", "La Liga", "LaLiga", "Europe"),
    "SERIEA": ("ita.1", "Serie A", "Serie A", "Europe"),
    "BUNDESLIGA": ("ger.1", "Bundesliga", "BuLi", "Europe"),
    "LIGUE1": ("fra.1", "Ligue 1", "Ligue 1", "Europe"),
    # Europe: next tier
    "EREDIVISIE": ("ned.1", "Eredivisie", "Eredivisie", "Europe"),
    "PRIMEIRA": ("por.1", "Primeira Liga", "Portugal", "Europe"),
    "BELGIUM": ("bel.1", "Belgian Pro League", "Belgium", "Europe"),
    "TURKEY": ("tur.1", "Süper Lig", "Turkey", "Europe"),
    "RUSSIA": ("rus.1", "Russian Premier League", "Russia", "Europe"),
    "SCOTLAND": ("sco.1", "Scottish Premiership", "Scotland", "Europe"),
    "GREECE": ("gre.1", "Greek Super League", "Greece", "Europe"),
    "AUSTRIA": ("aut.1", "Austrian Bundesliga", "Austria", "Europe"),
    "DENMARK": ("den.1", "Danish Superliga", "Denmark", "Europe"),
    # Europe: second divisions
    "CHAMPIONSHIP": ("eng.2", "Championship", "Champ", "Europe"),
    "BUNDESLIGA2": ("ger.2", "2. Bundesliga", "BuLi 2", "Europe"),
    "LALIGA2": ("esp.2", "LaLiga 2", "LaLiga 2", "Europe"),
    "SERIEB": ("ita.2", "Serie B", "Serie B", "Europe"),
    "LIGUE2": ("fra.2", "Ligue 2", "Ligue 2", "Europe"),
    # Rest of the world
    "SAUDI": ("ksa.1", "Saudi Pro League", "Saudi", "Asia"),
    "JAPAN": ("jpn.1", "J1 League", "Japan", "Asia"),
    "BRAZIL": ("bra.1", "Brasileirão", "Brazil", "Americas"),
    "ARGENTINA": ("arg.1", "Liga Profesional", "Argentina", "Americas"),
    "MLS": ("usa.1", "MLS", "MLS", "Americas"),
    "LIGAMX": ("mex.1", "Liga MX", "Liga MX", "Americas"),
    # added: more leagues with fixtures most weeks. (A-League Men was tested and dropped: the model
    # did worse than base rates there, -2.4% log loss, in the 2025-26 walk-forward.)
    "LEAGUEONE": ("eng.3", "League One", "L1 Eng", "Europe"),
    "LEAGUETWO": ("eng.4", "League Two", "L2 Eng", "Europe"),
    "NORWAY": ("nor.1", "Eliteserien", "Norway", "Europe"),
    "SWEDEN": ("swe.1", "Allsvenskan", "Sweden", "Europe"),
    "SOUTHAFRICA": ("rsa.1", "SA Premiership", "S. Africa", "Africa"),
    "CHILE": ("chi.1", "Chilean Primera", "Chile", "Americas"),
}

# Cross-league competitions, priced by the global model (globalmodel.py).
# key: (ESPN code, display name, short label, confederation)
CUPS = {
    "UCL": ("uefa.champions", "Champions League", "UCL", "EU"),
    "UEL": ("uefa.europa", "Europa League", "UEL", "EU"),
    "UECL": ("uefa.europa.conf", "Conference League", "UECL", "EU"),
    "ACLE": ("afc.champions", "AFC Champions League Elite", "ACL Elite", "AS"),
    "LIBERTADORES": ("conmebol.libertadores", "Copa Libertadores", "Libertadores", "SA"),
    "SUDAMERICANA": ("conmebol.sudamericana", "Copa Sudamericana", "Sudamericana", "SA"),
}

TEAM_META: dict[str, tuple[str, str, str]] = {}   # name -> (abbreviation, colour, alternate colour)


def _months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _fetch(code: str, ym: str, today: date) -> dict:
    path = CACHE / code / f"{ym}.json"
    past = ym < f"{today.year}{today.month:02d}"
    if path.exists() and (past or time.time() - path.stat().st_mtime < TTL):
        return json.loads(path.read_text())
    last = None
    for attempt in range(3):
        try:
            r = requests.get(URL.format(code=code, ym=ym), timeout=30)
            if r.status_code == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(r.text)
                return r.json()
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(1 + attempt)
    if path.exists():
        return json.loads(path.read_text())
    raise RuntimeError(f"ESPN {code} {ym}: {last}")


def _hex(c):
    return f"#{c.lower()}" if c and len(c) == 6 else None


def _parse(key: str, payload: dict) -> list[Match]:
    out = []
    for e in payload.get("events", []):
        comp = e["competitions"][0]
        side = {c["homeAway"]: c for c in comp["competitors"]}
        if "home" not in side or "away" not in side:
            continue
        st = e["status"]["type"]
        if st.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED"):
            continue
        h, a = side["home"], side["away"]
        for c in (h, a):
            t = c["team"]
            TEAM_META.setdefault(t["displayName"], (t.get("abbreviation", "")[:4], _hex(t.get("color")) or "#8e8e93",
                                                    _hex(t.get("alternateColor")) or "#ffffff"))
        when = datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ")
        done = st.get("completed", False)
        out.append(Match(key, when.date(), h["team"]["displayName"], a["team"]["displayName"],
                         int(h["score"]) if done else None, int(a["score"]) if done else None,
                         time=when.strftime("%H:%M") + " UTC", extra={"espn_id": e.get("id"),
                                                                     "neutral": comp.get("neutralSite", False)}))
    return out


def load_league(key: str, until: date, months_back: int = 36, today: date | None = None) -> list[Match]:
    today = today or date.today()
    code = (LEAGUES.get(key) or CUPS[key])[0]
    start = date(until.year - months_back // 12, until.month, 1)
    seen, out = set(), []
    for ym in _months(start, until):
        for m in _parse(key, _fetch(code, ym, today)):
            if key in CUPS:
                m.extra["confed"] = CUPS[key][3]
            k = m.extra.get("espn_id") or (m.date, m.home, m.away)
            if k not in seen:
                seen.add(k)
                out.append(m)
    return out


def load_many(keys, until: date, months_back: int = 36, workers: int = 6) -> dict[str, list[Match]]:
    with ThreadPoolExecutor(workers) as ex:
        res = dict(zip(keys, ex.map(lambda k: load_league(k, until, months_back), keys)))
    return res
