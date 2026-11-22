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

5. **Report.** Give the form treble, the core treble, the number of matches and leagues, and
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

## Fallback

If ESPN becomes unavailable, `python3 -m football.weekly card --source openfootball` still covers
the big five leagues. Their results come from `football/ledger/`, which `gaps` and `ingest` keep
up to date from researched scores.
