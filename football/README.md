# Football parlay agent: top 7 leagues

Predicts match outcomes for the **Premier League, La Liga, Bundesliga, Serie A, Ligue 1,
Eredivisie and Primeira Liga**, then builds parlays from the predictions. It uses only
numpy, pandas and requests (pytest for the tests).

```bash
python3 -m football predict  --league ALL --days 4          # probabilities + fair odds
python3 -m football parlay   --legs 3 --min-odds 2.0        # safest 3-fold paying >= 2.0 fair
python3 -m football parlay   --legs 2 --sgp --min-odds 3    # allow same-game combo legs
python3 -m football parlay   --mode value --odds odds.csv --bankroll 200
python3 -m football backtest --season 2025                  # walk-forward validation
python3 -m football ratings  --league SERIEA
```

League codes: `EPL LALIGA BUNDESLIGA SERIEA LIGUE1 EREDIVISIE PRIMEIRA` (comma-separated) or `ALL`.

## How it works

1. **Data**: results and fixtures come from [openfootball](https://github.com/openfootball/football.json)
   for the last 3 seasons. Files are cached in `football/.cache/`: past seasons forever, the
   current season for 6 hours (`--refresh` forces a download).
2. **Model** (`model.py`): Dixon-Coles Poisson model, fitted separately for each league. Each team
   gets an attack and a defence rating, each league a home advantage, and the model includes the
   low-score correlation term (rho). Older matches count for less (exponential decay with
   xi = 0.0015/day). Ratings are shrunk toward a prior (ridge = 8 matches); newly promoted teams
   start below league average. xi and ridge were tuned by walk-forward on 2024-25 and 2025-26.
3. **Markets** (`markets.py`): each selection is a mask over the scoreline grid. Supported
   selections are 1X2, double chance, BTTS, totals 0.5 to 4.5, team totals, and win to nil.
   Because every selection is a mask, a **same-game parlay is priced exactly**:
   P(Home win AND Over 2.5) is the sum of the cells where both are true, not the product of the
   two probabilities.
4. **Parlays** (`parlay.py`): a beam search over legs, with at most one leg per match.
   - `safe` (no odds needed): finds the highest-probability parlay whose combined fair odds are
     at least `--min-odds`, spreading the price evenly across the legs. Legs above
     `--max-leg-prob` (default 90%) are skipped, because books leave no value in them.
   - `value` (needs `--odds`): removes the margin from the book's prices, blends them with the
     model (`--model-weight 0.6`), keeps legs with at least `--min-edge` edge, maximises parlay
     EV subject to `--min-parlay-prob`, and suggests a stake using quarter Kelly (`--kelly`).

## Backtest (walk-forward, refit weekly, 2025-26, 2,362 matches)

| Market   | log loss (model / base rate) | Brier (model / base) |
|----------|------------------------------|----------------------|
| 1X2      | 0.986 / 1.074                | 0.587 / 0.650        |
| Over 2.5 | 0.680 / 0.685                | 0.244 / 0.246        |
| BTTS     | 0.685 / 0.687                | 0.246 / 0.247        |

The model predicts 1X2 clearly better than the base rate. Its edge on goal totals and BTTS
over the base rate is small, which is normal for this kind of model.

Calibration of every leg the builder can use is within about 1.5 points in every bucket
(n ≈ 22k):
55% predicted → 56% won, 65 → 65, 75 → 75, 84 → 85, 93 → 94. Same-game pair probabilities
(n ≈ 180k over two seasons) are also calibrated to about 1 point per bucket.

The "best parlay each week" simulation has only 38 samples per season. Its hit rate moves
±10 points between seasons and settings, so treat it as noise. The leg calibration above is
the reliable evidence.

## Inputs you can add

**Odds** (`--odds file.csv`), see `odds_example.csv`:

```
home,away,selection,odds
Arsenal,Leeds,H,1.40
Arsenal,Leeds,O2.5,1.65
Arsenal,Leeds,H+O2.5,2.05      # same-game combo price from your book
```

Selection codes: `H D A 1X X2 12 BTTS_Y BTTS_N O0.5..O4.5 U0.5..U4.5 HO/HU/AO/AU0.5..2.5 H_WTN A_WTN`.
Team names are matched loosely ("Man Utd", "Spurs", "PSG" and "Sporting CP" all resolve).

**Missing results** (`--results file.csv`): `date,home,away,home_goals,away_goals,league`.
CSVs from football-data.co.uk (`Date,HomeTeam,AwayTeam,FTHG,FTAG`) are also accepted, with
`league` set per row. The public feed often lags by weeks; the CLI warns when it does.

## Honest limits

- With no odds, `safe` mode finds parlays the model rates as likely and gives their *fair*
  price. It does not find value: only bet when your book pays more than the fair odds shown.
  Books charge 5-10% margin on each leg, and the margin compounds across a parlay. Real edge
  needs `value` mode with live odds.
- Probabilities across different matches are multiplied, i.e. treated as independent.
- The model knows nothing about injuries, lineups, rotation, cup schedules or transfers.
  It sees only scorelines.
- Parlays carry high variance even with an edge. Stake small: the Kelly suggestion is
  already a quarter of full Kelly.
