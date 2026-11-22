# Weekly parlay card runbook

Runs every Thursday morning (UK). It produces the card for the next 7 days (Thursday to Wednesday:
league rounds plus the midweek cup nights) across 31 leagues and 6 continental cups, and
republishes it to the same page: https://claude.ai/artifact/4j98Go6HigD8VvHx9qbFWP

Work on branch `claude/solana-token-alerts-mYL5N` of `talalen-ux/solalerts`. Another job also
pushes to this branch, so always `git pull --rebase` before pushing.

The session must run in the **solalerts** cloud environment, which allows `site.api.espn.com`.
That host is the data source for fixtures, results and team colours.

## Steps

1. **Build the card.** This fetches ESPN results and fixtures, fits each league and builds the slips.
   ```
   python3 -m football.weekly card            # today + 7 days -> football/cards/<date>/
   ```
   Check that it reports at least 200 matches and that the form-winners list is not empty. If
   ESPN is unreachable, the fetch fails with an HTTP error: report that and stop.

2. **Team news (optional).** For the biggest matches, write `<LEAGUE>_news.json` using the team
   names exactly as they appear in `card.json` (format in `football/adjust.py`), then rebuild with
   `--news <dir>`. Apply only absences you can source.

3. **Publish** `football/cards/<date>/parlay-card.html` with the Artifact tool, passing
   `url: https://claude.ai/artifact/4j98Go6HigD8VvHx9qbFWP` (read the artifact first, as the
   tool requires) so the link stays the same.

4. **Commit and push** the card folder and any news files:
   `git pull --rebase origin claude/solana-token-alerts-mYL5N && git push`.

5. **Report.** Give the World five-fold, the form treble, the core treble, the number of matches and leagues, and
   anything that failed.

## Coverage

Leagues (per-league models): Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie,
Primeira Liga, Belgium, Turkey, Russia, Scotland, Greece, Austria, Denmark, Norway, Sweden,
Championship, League One, League Two, 2. Bundesliga, LaLiga 2, Serie B, Ligue 2, Saudi Pro League,
J1 League, South Africa, Brasileirão, Argentina, Chile, MLS, Liga MX.

Cups (one cross-league model, `football/globalmodel.py`): Champions League, Europa League,
Conference League, AFC Champions League Elite, Copa Libertadores, Copa Sudamericana. Team ratings
sit on top of league levels that the cup results link together. In the 2025-26 walk-forward it
beat base rates by 7.7% on 973 cup matches (`football/research/cup_backtest.py`).

Dropped after testing: A-League Men, where the model did worse than base rates.

**Even competitions.** Legs are capped at 80% in the second divisions, League One and Two,
Austria, Denmark, Sweden, Chile, MLS, Liga MX, Argentina and the Libertadores. In these the model
gains less than 4% over base rates, and its 80%+ legs came in about 3 points short.

## Wildcards

Each card also carries 10-, 15- and 19-leg accumulators: the most likely result (up to 92%, or
80% in the even competitions) from that many different matches. Each one states a typical
bookmaker price and the average return at a 5% margin per leg: about 61p, 48p and 40p per £1.

## Build tab

The card opens on a pick list for building your own slip: every straight win at 70% or better
(up to 30, strongest first) and the 30 strongest "win or draw" picks between 70% and 92%. Tapping
a pick adds it; the slip shows the combined chance, fair odds, the leg-count check and a copy
button, and is remembered on the device for that week. One pick per match.

## Players

Each run reads the line-ups of every team's last 8 matches from ESPN match summaries (about 2,500
requests, 80 seconds) and grades players: star, regular, rotation, fringe, plus hot, cold and
"missed last game" (`football/players.py`). Grades are shown per fixture and on the Winners tab.
They do not move probabilities on their own: over a year in 12 leagues, a top star not starting
cost 4% of expected goals and added 4% conceded, and "missed the previous squad" predicted little
(`football/research/star_absence.py`). Confirmed absences still go through `--news`.

## Winners by league

The first tab ranks straight match-winner picks: the best win in every competition, the biggest
mismatches overall, and winner-only slips that take one pick per competition (World treble,
five-fold and eight-fold, Big five, League tour, European nights). Form and model slips also take
at most one leg per competition, and wildcards at most two.

## Double-headers

A team may appear twice on a slip when it plays two matches in the window (for example a
Champions League night, then the league). The card also lists the top "team ×2" doubles. The legs
are multiplied as independent: short rest and a previous win made no measurable difference over
2024-26 (`football/research/short_rest.py`).

## Fallback

If ESPN becomes unavailable, `python3 -m football.weekly card --source openfootball` still covers
the big five leagues. Their results come from `football/ledger/`, which `gaps` and `ingest` keep
up to date from researched scores.
