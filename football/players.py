"""Player-level analysis from ESPN match summaries (line-ups and per-player match stats).

For each team, the last N matches (league and cups) are read and every player is graded:

  star      one of the team's top three for goals+assists, with at least 3 and a quarter of
            the team's goals (the top contributor needs only the 3)
  regular   started at least 60% of the matches
  rotation  started 25-60%
  fringe    started under 25%

"Hot" = goal or assist in 3 of the last 5 appearances. "Cold" = forward with 8+ shots and no
goal. "Missed last game" = a star or regular who was not in the previous matchday squad, the
feed's only hint that a player may be unavailable (it has no injury list).
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import espn

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/summary?event={eid}"
CACHE = Path(os.environ.get("FOOTBALL_CACHE", Path(__file__).parent / ".cache")) / "espn_players"
WINDOW = 8
KEEP = ("totalGoals", "goalAssists", "totalShots", "shotsOnTarget", "yellowCards", "redCards", "ownGoals")


def _code(league_key: str) -> str:
    return (espn.LEAGUES.get(league_key) or espn.CUPS[league_key])[0]


def _compact(payload: dict) -> dict:
    out = {}
    for side in payload.get("rosters", []):
        team = side.get("team", {}).get("displayName")
        rows = []
        for p in side.get("roster", []) or []:
            st = {s["name"]: s.get("value", 0) for s in p.get("stats", [])}
            played = bool(p.get("starter")) or bool(p.get("subbedIn"))
            rows.append({"id": p["athlete"]["id"], "name": p["athlete"]["displayName"],
                         "pos": (p.get("position") or {}).get("abbreviation", ""),
                         "start": bool(p.get("starter")), "played": played,
                         **{k: int(st.get(k, 0) or 0) for k in KEEP}})
        if team:
            out[team] = rows
    return out


def summary(league_key: str, event_id: str) -> dict | None:
    """Compact line-ups for one match, cached for good (only the fields above are kept)."""
    path = CACHE / _code(league_key) / f"{event_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    for attempt in range(3):
        try:
            r = requests.get(URL.format(code=_code(league_key), eid=event_id), timeout=40)
            if r.status_code == 200:
                data = _compact(r.json())
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data, ensure_ascii=False))
                return data
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1 + attempt)
    return None


def recent_matches(all_matches, team: str, before, n: int = WINDOW):
    ms = [m for m in all_matches if m.played and m.date < before and team in (m.home, m.away)
          and m.extra.get("espn_id")]
    return sorted(ms, key=lambda m: m.date)[-n:]


def fetch_for(teams, all_matches, before, n: int = WINDOW, workers: int = 12) -> dict:
    """{team: [(match, line-up rows)] oldest first} for every team, fetching what is not cached."""
    by_team = {}
    for m in all_matches:
        if m.played and m.date < before and m.extra.get("espn_id"):
            by_team.setdefault(m.home, []).append(m)
            by_team.setdefault(m.away, []).append(m)
    need, plan = {}, {}
    for t in teams:
        ms = sorted(by_team.get(t, []), key=lambda m: m.date)[-n:]
        plan[t] = ms
        for m in ms:
            need[(m.league, m.extra["espn_id"])] = None
    keys = list(need)
    with ThreadPoolExecutor(workers) as ex:
        for k, res in zip(keys, ex.map(lambda k: summary(*k), keys)):
            need[k] = res
    out = {}
    for t, ms in plan.items():
        logs = []
        for m in ms:
            s = need.get((m.league, m.extra["espn_id"])) or {}
            if t in s and s[t]:
                logs.append((m, s[t]))
        out[t] = logs
    return out


def is_forward(pos: str) -> bool:
    return pos.startswith(("F", "CF", "ST", "LW", "RW", "AM", "W")) or pos in ("LF", "RF", "SS")


def profile(logs) -> dict:
    """Grade a team's players from its recent line-ups."""
    n = len(logs)
    if n < 3:
        return {"matches": n, "players": [], "stars": [], "hot": [], "cold": [], "missed_last": []}
    agg = {}
    for i, (m, rows) in enumerate(logs):
        for r in rows:
            a = agg.setdefault(r["id"], {"name": r["name"], "pos": r["pos"], "starts": 0, "apps": 0, "squads": [],
                                         "g": 0, "a": 0, "sh": 0, "sot": 0, "inv": []})
            a["squads"].append(i)
            if r["pos"]:
                a["pos"] = r["pos"]
            if r["played"]:
                a["apps"] += 1
                a["starts"] += r["start"]
                a["g"] += r["totalGoals"]; a["a"] += r["goalAssists"]
                a["sh"] += r["totalShots"]; a["sot"] += r["shotsOnTarget"]
                a["inv"].append(r["totalGoals"] + r["goalAssists"] > 0)
    team_goals = sum(p["g"] for p in agg.values()) or 1
    top_inv = max((p["g"] + p["a"] for p in agg.values()), default=0)
    ranked = sorted(agg, key=lambda k: (-(agg[k]["g"] + agg[k]["a"]), -agg[k]["g"], -agg[k]["starts"]))
    top3 = set(ranked[:3])
    players = []
    for pid, p in agg.items():
        ga = p["g"] + p["a"]
        share = p["starts"] / n
        if pid in top3 and ga >= 3 and (ga / team_goals >= 0.25 or pid == ranked[0]):
            tier = "star"
        elif share >= 0.60:
            tier = "regular"
        elif share >= 0.25:
            tier = "rotation"
        else:
            tier = "fringe"
        last5 = p["inv"][-5:]
        players.append({"id": pid, "name": p["name"], "pos": p["pos"], "tier": tier, "starts": p["starts"],
                        "apps": p["apps"], "g": p["g"], "a": p["a"], "shots": p["sh"], "sot": p["sot"],
                        "hot": len(last5) >= 3 and sum(last5) >= 3,
                        "cold": is_forward(p["pos"]) and p["sh"] >= 8 and p["g"] == 0,
                        "in_last_squad": (n - 1) in p["squads"],
                        "played_last": bool(p["inv"]) and (n - 1) in p["squads"]})
    players.sort(key=lambda x: (-(x["g"] + x["a"]), -x["starts"]))
    order = {"star": 0, "regular": 1, "rotation": 2, "fringe": 3}
    strong = [x for x in players if x["tier"] in ("star", "regular")]
    return {
        "matches": n, "players": players,
        "stars": [x for x in players if x["tier"] == "star"][:3],
        "hot": [x for x in players if x["hot"]][:3],
        "cold": [x for x in players if x["cold"]][:2],
        "missed_last": [x for x in sorted(strong, key=lambda x: order[x["tier"]]) if not x["in_last_squad"]][:4],
        "counts": {t: sum(x["tier"] == t for x in players) for t in order},
        "star_goal_share": round(sum(x["g"] for x in players if x["tier"] == "star") / team_goals, 3),
    }


def brief(p: dict) -> dict:
    """What the card shows for one team."""
    line = lambda x: {"name": x["name"], "pos": x["pos"], "g": x["g"], "a": x["a"], "starts": x["starts"],
                      "tier": x["tier"]}
    return {"matches": p["matches"], "stars": [line(x) for x in p["stars"]], "hot": [line(x) for x in p["hot"]],
            "cold": [{**line(x), "shots": x["shots"]} for x in p["cold"]],
            "missed_last": [line(x) for x in p["missed_last"]],
            "counts": p.get("counts", {}), "star_goal_share": p.get("star_goal_share", 0)}
