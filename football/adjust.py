"""Team-news adjustments: absences and midweek European football.

These cannot be backtested from scorelines alone, so they are deliberately small priors
applied to the expected-goal rates before the score matrix is built:

  absence (status out; doubtful counts half)      own attack   opponent attack (= we concede)
    key forward                                      -6%            -
    key midfielder                                   -3%           +2%
    key defender                                      -            +4%
    key goalkeeper                                    -            +6%
    rotation player                                  quarter of the key value
  played in Europe within 3 days of kick-off         -3%           +2%

Totals are capped at -15% attack / +15% conceded per team.

Tested and NOT applied: last-5 form and travel distance. On 2023-26 walk-forward data
(5,235 matches) neither improved out-of-sample log loss once the time-decayed ratings were
in place, so they are reported as context only.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

KEY_EFFECT = {"FW": (-0.06, 0.0), "MF": (-0.03, 0.02), "DF": (0.0, 0.04), "GK": (0.0, 0.06)}
ROTATION_SHARE = 0.25
EUROPE = (-0.03, 0.02)
CAP = 0.15


def load_news(paths) -> dict[str, dict]:
    """Merge *_news.json files into {team: info}."""
    teams = {}
    for p in paths:
        p = Path(p)
        files = sorted(p.glob("*_news.json")) if p.is_dir() else [p]
        for f in files:
            teams.update(json.loads(f.read_text()).get("teams", {}))
    return teams


def team_factors(info: dict | None, kickoff: date) -> tuple[float, float, list[str]]:
    """Returns (attack multiplier, conceded multiplier, reasons)."""
    if not info:
        return 1.0, 1.0, []
    att = conc = 0.0
    why = []
    for a in info.get("absences", []):
        pos = (a.get("pos") or "").upper()[:2]
        if pos not in KEY_EFFECT:
            continue
        w = 1.0 if a.get("status", "out") == "out" else 0.5
        if a.get("importance") != "key":
            w *= ROTATION_SHARE
        da, dc = KEY_EFFECT[pos]
        att += da * w
        conc += dc * w
        if a.get("importance") == "key":
            why.append(f"{a.get('player')} ({pos}, {a.get('status', 'out')})")
    eu = info.get("europe_midweek")
    if eu:
        try:
            d = datetime.strptime(eu[:10], "%Y-%m-%d").date()
            if 0 < (kickoff - d).days <= 3:
                att += EUROPE[0]; conc += EUROPE[1]
                why.append(f"Europe {eu}")
        except ValueError:
            pass
    att, conc = max(att, -CAP), min(conc, CAP)
    return 1 + att, 1 + conc, why


def adjusted_rates(lam: float, mu: float, home_info, away_info, kickoff: date):
    ha, hc, hw = team_factors(home_info, kickoff)
    aa, ac, aw = team_factors(away_info, kickoff)
    return lam * ha * ac, mu * aa * hc, hw, aw
