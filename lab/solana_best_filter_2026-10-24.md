# Best Solana filter search — 2026-10-24

Method: 44-agent research workflow (7 readers mined all 3,926 lines of alerts.yaml
+ lab/, 1 knowledge-base synthesis, 5 designers x 2 candidates, 3 adversarial
critics per candidate, 1 ranker) -> 10 live DRBT backtests (Free tier = 10/day),
each arm = the exact live T20-PRIME string + ONE leg, benched on slot 2,
SHIELD restored byte-identical afterwards. Profit modelled with agent/score.py
(RH-calibrated costs: 10% entry + 8% exit friction, 40% stop, fill haircuts).

## Results (same windows, Oct 2026)
| arm | 1w n | 1w 2x+ | 1m n | 1m 2x+ | 5x+ | 10x+ | 20/50/100 | pATH | ev / ev_lcb (1m) |
|---|---|---|---|---|---|---|---|---|---|
| T20-PRIME (live slot 1) | 53 | 39.6% | 404 | 55.5% | 21.3% | 35 | 10/3/2 | 0.74% | +0.021 / -0.030 |
| + top_source>=10 | 42 | 42.9% | 355 | 56.1% | 21.7% | 29 | 6/1/1 | 0.56% | +0.028 / -0.026 |
| + top_source>=5 | 46 | 41.3% | - | - | - | - | - | - | - |
| + top_source>=10 OR buyers<20 | 49 | 40.8% | - | - | - | - | - | - | - |
| + age cap (<1h) | 52 | 40.4% | - | - | - | - | - | - | inert |
| **+ sol_price_24h > 0** | **21** | **47.6%** | **179** | **59.2%** | **25.7%** | **17 (9.5%)** | 4/1/1 | 1.68% | **+0.068 / -0.008** |
| SHIELD (slot 2) | - | - | 172 | 50.6% | 15.7% | 9 | 3/1/0 | 1.16% | -0.039 / -0.117 |

Removed by the SOL-green gate (red-SOL-day alerts): 1m n=225, 2x+ 52.4%, 5x+ 17.8%,
10x+ 8.0%, ev -0.016; in the cold last week n=32, 2x+ 34.4%.
Time halves: older 3 weeks gate 60.8% vs 57.8% (+3.0pp, ev_lcb +0.006 vs -0.004);
last week 47.6% vs 39.6% (+8.0pp, still negative EV for both in the cold week).

## Verdicts
- top_source>=10: the Sept +6.5pp did NOT replicate (+0.6pp on the month) and it cut
  4/10 twenties, 2/3 fifties, 1/2 hundreds (U-shape). KILLED.
- age cap: inert (T20-PRIME entries are already <1h). KILLED.
- WINNER: T20-PRIME + (sol_price_24h IS NULL OR sol_price_24h > 0). Lifts 2x+/5x+/10x+
  rate in both halves, removes 225 tokens (>100 bar), tripled point EV. Costs: half the
  volume, and the deep tail in this window was split (4/10 twenties kept, 50x+ 1/3).
- Laws confirmed: #37 (T20-PRIME zone is distilled: no entry-time token leg separates),
  #32 (regime dominates) - and the regime lever IS expressible as a leg.
## Caveats
- Day-clustered effect: ~30 independent days, not 404 independent tokens.
- sol_price_24h is market regime, not a token property; threshold 0 is natural, not fitted.
- Under the conservative cost model nothing on Solana clears ev_lcb > 0 on the full month
  (the gate gets closest). Not deployed: filter 1 inactive, Free tier, user decision.
- top_source leak not fully verified (snapshot-stored per row; token_history gave no rows).

## UPDATE 2026-10-25 — response curve (protocol #2)
T20-PRIME + sol_price_24h > -2, 1 month (window shifted 1 day): n=294, 2x+ 55.8%,
5x+ 21.8%, 10x+ 8.5%, 20/50/100 = 8/3/2. Curve: none 55.5% -> >-2 55.8% -> >0 59.2%.
Implied bands: <-2% ~54.5%, -2..0% ~50.4%, >0% 59.2% — NON-MONOTONE.
Verdict DOWNGRADED: the green-day lift may be day-cluster noise (~30 days). Do not
deploy as a leg yet; treat as a sizing hint and re-test after two more weeks.
