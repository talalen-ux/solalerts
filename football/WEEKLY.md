# Weekly parlay card runbook

Runs every Thursday morning (UK). Produces the card for the coming Friday-to-Monday and
republishes it to the same page: https://claude.ai/artifact/4j98Go6HigD8VvHx9qbFWP

Work on branch `claude/solana-token-alerts-mYL5N` of `talalen-ux/solalerts`. Another job also
pushes to this branch, so always `git pull --rebase` before pushing.

## Steps

1. **Find missing results.** The public feed stopped on 20 Sept 2026; results live in
   `football/ledger/`.
   ```
   python3 -m football.weekly gaps --outdir <scratch>/gaps
   ```
   This writes `<LEAGUE>_gaps.csv` for EPL, LALIGA, SERIEA, BUNDESLIGA and LIGUE1.

2. **Research the scores.** One research agent per league with missing results, run in
   parallel. Each gets about 20 web searches and works from round summaries. Each writes
   `<scratch>/gaps/<LEAGUE>_new_results.csv` with the same columns and the exact team names
   from the gaps file. Only verified final scores go in: never guess.

3. **Add them to the ledger.**
   ```
   python3 -m football.weekly ingest <scratch>/gaps
   ```

4. **Team news (optional, if search budget is left).** For big matches, write
   `<LEAGUE>_news.json` (format in `football/adjust.py`) and pass `--news <dir>` to the next step.
   Apply only absences you can source.

5. **Build the card.**
   ```
   python3 -m football.weekly card            # next Friday + 4 days -> football/cards/<date>/
   ```
   Check that it reports about 45-50 fixtures and that the form-winners list is not empty.

6. **Publish** `football/cards/<date>/parlay-card.html` with the Artifact tool, passing
   `url: https://claude.ai/artifact/4j98Go6HigD8VvHx9qbFWP` (read the artifact first, as the
   tool requires) so the page keeps its link.

7. **Commit and push** the ledger, the card folder and any news files:
   `git pull --rebase origin claude/solana-token-alerts-mYL5N && git push`.

8. **Report.** Give the top form-winners slip and the core treble, the number of results
   added, the number of gaps left, and anything that failed.

## What the card contains

- **Form winners:** teams with 3+ wins in their last 5 league games who are favourites again,
  ranked by model win probability, plus win-only doubles, trebles and four-folds.
  Over 2023-26, in-form favourites won at least as often as the model predicted, so form is
  used as a filter and does not raise the probabilities
  (`football/research/form_favourites.py`).
- **Model slips:** a banker double, a treble at about 2.0, a four-fold at about 3.0, a
  same-game builder and a long shot, all at fair odds.
- **Every fixture:** form, travel distance, team news and probabilities.
