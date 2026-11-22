"""Weekly parlay card pipeline.

The public results feed (openfootball) stopped updating on 20 Sept 2026, so results after that
live in a ledger (football/ledger/<LEAGUE>.csv) that grows each week from researched scores.

    python3 -m football.weekly gaps   --outdir DIR             # fixtures with no result yet
    python3 -m football.weekly ingest DIR                      # add DIR/<LEAGUE>_new_results.csv to ledger
    python3 -m football.weekly card   --outdir football/cards  # build card.json + parlay-card.html

`card` defaults to the next Friday-to-Monday window. Team news (<LEAGUE>_news.json, see
adjust.py) is applied when --news DIR is given.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from . import data, weekend
from .leagues import season_start_year

ROOT = Path(__file__).parent
LEDGER = ROOT / "ledger"
TEMPLATE = ROOT / "templates" / "card.html"
LEAGUES = ["EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1"]
HEADER = ["date", "home", "away", "home_goals", "away_goals", "league"]


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def next_friday(today: date) -> date:
    return today + timedelta(days=(4 - today.weekday()) % 7)


def _season_matches(lg: str, until: date):
    ms = data.load_league(lg, season_start_year(until), 1)
    if (LEDGER / f"{lg}.csv").exists():
        data.merge_results_csv(ms, str(LEDGER / f"{lg}.csv"), lg)
    return ms


def gaps(outdir: Path, until: date) -> dict[str, int]:
    outdir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for lg in LEAGUES:
        ms = _season_matches(lg, until)
        miss = sorted((m for m in ms if not m.played and m.date < until), key=lambda m: m.date)
        with open(outdir / f"{lg}_gaps.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            for m in miss:
                w.writerow([m.date, m.home, m.away, "", "", lg])
        counts[lg] = len(miss)
    return counts


def ingest(src: Path) -> dict[str, int]:
    """Merge researched results into the ledger; a later row for the same pairing wins."""
    LEDGER.mkdir(exist_ok=True)
    added = {}
    for lg in LEAGUES:
        f = src / f"{lg}_new_results.csv"
        if not f.exists():
            continue
        path = LEDGER / f"{lg}.csv"
        rows = {}
        if path.exists():
            for r in csv.DictReader(open(path, encoding="utf-8-sig")):
                rows[(r["home"], r["away"], season_start_year(_d(r["date"])))] = r
        teams = {t for m in data.load_league(lg, season_start_year(date.today()), 1) for t in (m.home, m.away)}
        n = 0
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            if not (r.get("home_goals", "").strip().isdigit() and r.get("away_goals", "").strip().isdigit()):
                continue
            if r["home"] not in teams or r["away"] not in teams:
                print(f"  skip {lg}: unknown team in {r['home']} v {r['away']}")
                continue
            key = (r["home"], r["away"], season_start_year(_d(r["date"])))
            rows[key] = {**{k: r[k] for k in HEADER[:5]}, "league": lg}
            n += 1
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, HEADER)
            w.writeheader()
            for r in sorted(rows.values(), key=lambda r: (r["date"], r["home"])):
                w.writerow({k: r[k] for k in HEADER})
        added[lg] = n
    return added


def render(card: dict, out: Path) -> None:
    out.write_text(TEMPLATE.read_text().replace("__DATA__", json.dumps(card, ensure_ascii=False)))


def card(start: date, days: int, outdir: Path, news: Path | None, source: str = "espn",
         leagues: list[str] | None = None) -> Path:
    tmp = Path(tempfile.mkdtemp())
    for lg in LEAGUES:
        if (LEDGER / f"{lg}.csv").exists():
            shutil.copy(LEDGER / f"{lg}.csv", tmp / f"{lg}_results.csv")
        if news and (news / f"{lg}_news.json").exists():
            shutil.copy(news / f"{lg}_news.json", tmp / f"{lg}_news.json")
    outdir.mkdir(parents=True, exist_ok=True)
    js = outdir / "card.json"
    if leagues is None:
        from .espn import LEAGUES as ESPN_LEAGUES
        leagues = list(ESPN_LEAGUES) if source == "espn" else LEAGUES
    weekend.main(["--research", str(tmp), "--start", start.isoformat(), "--days", str(days), "--out", str(js),
                  "--source", source, "--leagues", ",".join(leagues)])
    html = outdir / "parlay-card.html"
    render(json.loads(js.read_text()), html)
    return html


def main(argv=None):
    ap = argparse.ArgumentParser(prog="football.weekly", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gaps")
    g.add_argument("--outdir", type=Path, required=True)
    g.add_argument("--until", type=_d, default=date.today())
    i = sub.add_parser("ingest")
    i.add_argument("src", type=Path)
    c = sub.add_parser("card")
    c.add_argument("--start", type=_d)
    c.add_argument("--days", type=int, default=4)
    c.add_argument("--outdir", type=Path, default=ROOT / "cards")
    c.add_argument("--news", type=Path)
    c.add_argument("--source", choices=["espn", "openfootball"], default="espn")
    c.add_argument("--leagues", help="comma list of league keys (default: all for the source)")
    a = ap.parse_args(argv)
    if a.cmd == "gaps":
        print(json.dumps(gaps(a.outdir, a.until)))
    elif a.cmd == "ingest":
        print(json.dumps(ingest(a.src)))
    else:
        start = a.start or next_friday(date.today())
        out = card(start, a.days, a.outdir / start.isoformat(), a.news, a.source,
                   a.leagues.split(",") if a.leagues else None)
        print(f"card -> {out}")


if __name__ == "__main__":
    main()
