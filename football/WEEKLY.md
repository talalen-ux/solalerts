# Weekly parlay card runbook

Runs every Thursday morning (UK). It produces the card for the coming Friday-to-Monday across 25
leagues and republishes it to the same page: https://claude.ai/artifact/4j98Go6HigD8VvHx9qbFWP

Work on branch `claude/solana-token-alerts-mYL5N` of `talalen-ux/solalerts`. Another job also
pushes to this branch, so always `git pull --rebase` before pushing.

The session must run in the **solalerts** cloud environment, which allows `site.api.espn.com`.
That host is the data source for fixtures, results and team colours.

## Steps

1. **Build the card.** This fetches ESPN results and fixtures, fits each league and builds the slips.
   ```
   python3 -m football.weekly card            # next Friday + 4 days -> football/cards/<date>/
   ```
   Check that it reports at least 150 matches and that the form-winners list is not empty. If
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

## Leagues

Europe: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie, Primeira Liga,
Belgium, Turkey, Russia, Scotland, Greece, Austria, Denmark, Championship, 2. Bundesliga,
LaLiga 2, Serie B, Ligue 2. Asia: Saudi Pro League, J1 League. Americas: Brasileirão,
Argentina, MLS, Liga MX. The list is in `football/espn.py`; add a league there with its ESPN code.

**Even leagues.** In 10 leagues the model beat base rates by under 4%: the second divisions,
Austria, Denmark, MLS, Liga MX and Argentina. Their legs are capped at 80% on the slips, because
legs above that won 80.5% against 84.1% predicted (`football/research/espn_backtest.py`).

## Fallback

If ESPN becomes unavailable, `python3 -m football.weekly card --source openfootball` still covers
the big five leagues. Their results come from `football/ledger/`, which `gaps` and `ingest` keep
up to date from researched scores.
