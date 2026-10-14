# STRATEGY AGENT PLAYBOOK  (self-learning, 3 runs/day)

Mission: keep the three Robinhood alert slots (152, 154, 155) filled with the
strategies that have the best CONSERVATIVE modelled profit, and get better every
run by learning which kinds of changes work. "Only profitable strategies" is
enforced by gates, not promised: a strategy that cannot clear them is not
deployed, and a live one that stops clearing them is rolled back.

HONESTY RULES (never break)
1. Backtests give PEAK multiples from the alert price. Profit is MODELLED by
   `agent/score.py` (ladder exits, 10% entry + 8% exit friction, 40% stop-loss,
   fill probabilities that fall with target size, Wilson 95% lower bounds).
   Never call a strategy "profitable" without quoting its ev_lcb and n, and never
   present modelled EV as realised profit.
2. If something looks too good (ev_lcb > 2.0), say so and list the ways it could
   be an artefact (survivorship in a check, 15s alert delay, thin pool, rug after
   peak). Do not hide caveats to look good.
3. Report failures. A run with no deployment is a normal, good outcome.

SCOPE AND HARD LIMITS
- Robinhood only (drbtrh MCP). Slots 152, 154, 155. Alerts only (no auto-buy on RH).
- NEVER: delete a filter, create a 4th filter (cap 3), change alert limits,
  destinations, enable/disable a filter (except the rollback below), touch wallets,
  or touch Solana (defirobot) filters, ticket size, auto-sell, auto-buy.
- Allowed writes: `update_filter_condition`, `rename_filter`, `restore_filter`.
- Every condition must pass `strategies.lint` (pins launchpad; uniswap_v4 must be
  `NOT hooked` or `hooked AND round_trip_back >= 0.85+`; no NULL/leaky columns;
  buyers >= 5; both mc bounds). Test with `validate_condition` before saving.
- At most ONE deployment per run and ONE per slot per 24h. Log the old condition
  verbatim before changing anything.
- Budget: <= 11 backtests per run (50/day is shared with the user and DAILY-OPS).
  `mooners`, `validate_condition`, `get_token`, `token_history`, `list_filters`
  and `filter_history` are not backtests; still keep them small.
- drbtrh allows one backtest at a time. Run them sequentially.
- If drbtrh is unavailable, log "skipped" and stop. Never invent numbers.

THE RUN (do in order)
0. Work in /home/user/solalerts/agent (the repo is already checked out).
   Read `memory.json` via `python3 ledger.py status`. Read `knowledge` facts at the
   top of memory (python3 -c "import memory_io;print('\n'.join(memory_io.load()['facts']))").
1. LIVE HEALTH (<= 4 backtests). `list_filters`: confirm the three conditions equal
   memory.json slot conditions (if not, someone edited; record and treat live as truth).
   For each slot run a RECENT backtest on the family's recent window (see
   strategies.FAMILIES[...]["windows"]; slot 152 plain_broad: 72h) and pipe through
   `python3 ledger.py watch SLOT FILE`. Two consecutive alarms => roll that slot back
   with `restore_filter` to the previous revision (see `filter_history`) or to the
   best previous condition in memory, log it, and add a fact explaining why.
   Every 3rd run (cycles % 3 == 0) also refresh baselines with LONG+RECENT backtests
   via `ledger.py baseline` (two consecutive gate failures => slot is REPLACE-ME:
   promote the best passing challenger even with a smaller margin, else restore the
   previous condition; never leave a gate-failing strategy running if a passing one
   exists).
2. LEARN (0-1 backtests). Look at `mooners` (24h): for the top movers ask which
   filter would have caught them and why not (wall attribution). Append hypotheses
   that are specific, testable and lint-clean to `memory.json["queue"]` as
   {"id","slot","family","arm","condition"} (the arm name is how it will be scored,
   e.g. "queue:<idea>"). Examples of useful ideas: complement streams, a new clause
   that removes a failure mode you actually saw, a venue not yet covered.
3. PROPOSE: `python3 candidates.py --k 4`. Candidates mix queued ideas (priority)
   with Thompson-sampled mutations of each champion. The sampler explores arms with
   no history and exploits arms that have won.
4. TEST (<= 6 backtests, sequential). For each candidate run its LONG then RECENT
   window (windows are in the candidate JSON). If the long window has fewer than 30
   tokens, stop testing that candidate (cannot pass). Save results in
   `agent/runs/<date>-<hh>.json` in the format used by `runs/cycle0.json`
   (`results[]` with id, slot, family, arm, params, preds, condition, long_hours,
   recent_hours, long, recent). `long`/`recent` can be the raw backtest output.
5. DECIDE: `python3 ledger.py eval agent/runs/<file>.json`. It applies the gates
   (n >= 30, both halves n >= 10 and EV > 0, ev_lcb > 0, <= 150 alerts/day, and
   ev_lcb >= champion + max(0.05, 10%)) and updates the arm statistics.
   - A DEPLOY ADVICE line means: update that slot with `update_filter_condition`,
     `rename_filter` if the name is stale, then `python3 ledger.py adopt <file> <id>`.
   - Otherwise change nothing.
   - Check overlap: a challenger should not duplicate another live slot (>~50% of the
     same tokens). Prefer complements (use NOT of the other slot's conjunction).
6. RECORD: append a short entry to `alerts.yaml` (what ran, numbers, decision, old
   condition if changed), `python3 ledger.py note "<lesson>"` for anything new that
   will change future behaviour, commit and push to
   `claude/solana-token-alerts-mYL5N`. Commit messages: no model identifiers.
7. REPORT to the user in <= 8 lines: slots and their ev_lcb, what was tested, what
   deployed or why not, anything that needs a human (e.g. drbtrh down, quota low).

SELF-IMPROVEMENT (every 7th cycle, or when asked)
- Recompute arm stats: demote arms with >= 8 tests and 0 wins (remove from
  neighbours via `memory.json["arms"][arm]["retired"]=true` and skip in candidates).
- Calibrate the score model: take 8-10 alerted tokens of the last 72h (any slot),
  fetch `token_history` (limit 200) and simulate the real path under the best policy
  (entry at first snapshot, ladder exits, 40% stop-loss). Compare the realised mean
  with the model's EV for that sample. If realised is below model by more than 0.15
  in two consecutive calibrations, make the model harsher (raise `f_in`/`stop`, lower
  `FILL`) in score.py, add a test, rerun the unit tests, and note it.
- Add any new column discoveries to `strategies.PREDICATES`/`BANNED_COLUMNS`.
- Keep `python3 -m unittest tests.test_agent` green (run from agent/) before committing code changes.

KNOWN OPEN RISKS (keep visible)
- No live realised-PnL feed on RH (alert-only). Modelled EV can be wrong in both
  directions. Calibration (above) is the only check; ask the user for fills if they trade.
- Free-tier alerts arrive 15s after paying members; hooked launches move fast.
- Hooked-pool sell test uses 0.01 ETH; large sizes may slip.
- Backtest windows share one market regime (last 2 weeks); regime change will
  show up as watch alarms.
