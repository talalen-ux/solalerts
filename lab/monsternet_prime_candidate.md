# MONSTERNET-PRIME candidate (alert-only premium tier of filter 3)

Source: user export backtest_query_3_2weeks.xlsx (filter 3, 9,972 rows,
Sep 22 - Oct 6) + engine bench on slot 2 (2-week, 2026-10-07).

## Condition = live filter 3 (MONSTERNET v3) + three legs
Append to the END of the filter-3 condition (top-level AND):

    AND bonding_progress >= 70 AND buyers <= 90 AND (dev_migrated IS NULL OR dev_migrated < 3)

(Filter-3 text is the get_filter(3) string of 2026-10-06, verbatim in alerts.yaml
MONSTERNET v3 block.) Rollback = remove the three legs.

## Evidence
Export (row-level), curve branch C (n=9,465): base 5x+ 11.76%.
  dm<3 & buyers<=90 & bonding>=70: n=1,581 (16.7%), 5x+ 14.04%, 2x+ 41.9%,
  10x+ 88, 20x+ 37, 50x+ 10; halves 14.1% / 14.0% (base 11.8 / 11.7).
Engine bench, 2 weeks (re-entry-safe; this is the number to trust):
  n=2,157 (~154/day), 2x+ 42.56%, 3x+ 29.39%, 5x+ 14.33% (309),
  10x+ 137 (6.35%), 20x+ 60 (2.78%), 50x+ 17 (0.79%), 100x+ 6, post-ATH 6.40%.
Filter 3 baseline (2 weeks, export): 2x+ 37.2%, 5x+ 11.9%, 10x+ 4.8%, 20x+ 2.0%,
  50x+ 0.67%, 100x+ 0.34%, post-ATH 6.5%.
Lift: 5x+ +20% relative, 10x+ +32%, 20x+ +39%, 50x+ +18%, 2x+ +14%.
It keeps ~26% of all 5x+ tokens: this is a SELECTIVE TIER, not a junk cutter.

## What did NOT work (do not retry)
- Out-of-sample GBM on 73 entry-time features: AUC 0.565 / 0.59 (near-random).
- Greedy multi-cut rules fit on one half: test-half lift -5% to +5%.
- 624 single-feature cuts: best lift +7.5% at the cost of 14% of the 5x+ tokens.
- Cutting row-level looks better than the engine shows (re-entry effect).
