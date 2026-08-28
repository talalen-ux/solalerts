# SHIELD LAB — the self-improving filter loop

The finding that created this system (2026-08-28): **there is no universal
sub-2x cutter.** The best single leg works in 3 of 12 universes; each
filter's junk is shaped by the filter itself. Mature filters (MOONNET,
v9) are fully distilled — nothing passes the bars in their universes.
Fresh universes (Q1-WIDE) still hold removable chunks. Therefore junk
removal is a PER-FILTER PROCEDURE that must re-run every time a filter
changes or new data arrives. That procedure is this loop.

## The loop (run monthly, or after any filter change)

1. **Export** — in DRBT Telegram, run a 1-month backtest for each live
   filter and download the row-level Excel export (one file per filter).
2. **Search** — `python3 lab/shield_search.py <dir with the .xlsx files>`
   It emits, per universe, the legs that pass ALL bars, plus paste-ready
   SQL and the projected improvement.
3. **Gate check** — every emitted leg must be NULL-guarded
   (`col IS NULL OR ...`) before pasting into DRBT.
4. **Backtest** — backtest the candidate query in DRBT (main-condition
   legs only; the backtester ignores confirmation conditions — proven
   2026-08-28). Accept only if the histogram matches the projection.
5. **Deploy** — update the live filter. Log query + prediction in
   alerts.yaml. The next month's export of THIS filter becomes the new
   universe — the loop tightens itself on its own output.

## The bars (do not relax silently)

- honest-xs only: `xs_h = xs if current_ath_slot > entry_slot else 1.0`
- junk cut >= 3% of sub-2x rows; winner cost <= 1/3 of junk cut
- 2x+ rate must improve (or hold within 0.5pp) in EVERY week with n>=80
- zero removals from `lab/veto_mints.txt` (confirmed live monsters)
- <= 5% of the universe's 10x+ tail removed per leg
- universe purity: legs derive only from the target filter's own export
- deployment only after a matching DRBT backtest (live engine)

## First output of the loop (2026-08-28): Q1-WIDE SHIELD

Universe: fb4350e4 confirmed export, n=1,012. Legs (all bundle/flow
anchored, all week-stable):
  max_bundle_sol < 90, sells <= 48, cnt_from_cex >= 1  [+ optional
  lp_sol > 85 and buy_volume_1m < 9300 for the MAX variant]
Result (SHIELD-A): volume -18%, 2x+ 64.9% -> 70.2%, EV 1.34 -> 1.46,
keeps 89/97 tens, 30/32 twenties, 13/13 fifties; improves every week.
MAX variant: 2x+ 72.2%, EV 1.48, keeps 82/97 tens.
Transfer to Q1-SNIPER: harmless no-op (0.8% cut) — safe as safety legs.
MOONNET/v9/PREMIUM: NOTHING passes — confirmed distilled; do not force.
