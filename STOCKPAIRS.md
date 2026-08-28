# EQUITY PAIRS — Ethena collateral on Hyperliquid infra

Sister book to the Solana alert system. Same lab discipline, inverted risk
shape: `alerts.yaml` hunts a convex long tail (2x+ rates, 100x trophies) and
survives a low hit rate; this book wins small and often and dies from one fat
left tail. Every design choice below follows from that asymmetry.

## The one number that matters

A dollar-neutral pair earns nothing from direction by construction. Its entire
P&L is:

```
spread convergence  +  sUSDe yield  −  funding  −  fees  −  slippage
```

Three of five terms are carry. Collateralising in sUSDe rather than USDC flips
the sign of the idle-margin term — a book that breaks even on spread still
earns staking yield on posted margin, so the hurdle rate is *negative*.

But:

> **Yield accrues on EQUITY. Funding accrues on NOTIONAL.**

Carry per unit of notional therefore *falls* as leverage rises. At a 7%
annualised funding differential against the book, net carry crosses zero at
roughly **1.6x gross**:

| gross lev | net carry | breakeven spread move (3d hold) |
|-----------|-----------|--------------------------------|
| 1.0x | +0.52 bps/d | +26.9 bps |
| 1.5x | +0.04 bps/d | +29.8 bps ← crossover |
| 2.0x | −0.44 bps/d | +31.3 bps |
| 4.0x | −2.36 bps/d | +33.5 bps |

```
python3 lab/pairs_run.py carry --apy 0.09 --long-funding 11 --short-funding 4 --funding-is-apr
```

This is why `gross_leverage` is 2.0 with a 3.0 ceiling, not the 5–10x the
venue permits. Above ~2x the strategy stops being a carry book and becomes a
leveraged bet on convergence alone — the same trade minus the reason to prefer
it. **Run this table before changing leverage, not after.**

## Layout

| file | role |
|------|------|
| `pairs.yaml` | strategy spec, parameters, and the reasoning for each |
| `lab/hl.py` | Hyperliquid infra: HIP-3 dex discovery, asset indexing, candles, funding, account state, gated executor |
| `lab/ethena.py` | sUSDe/USDe collateral, yield curve, net-carry math |
| `lab/pairs.py` | pair stats, screen, signal state machine, sizing, risk |
| `lab/pairs_backtest.py` | walk-forward backtest netting all five P&L terms |
| `lab/pairs_run.py` | CLI: `markets` `scan` `backtest` `signal` `carry` `trade` |
| `lab/test_pairs.py` | 63-check offline self-test, no network, no deps |

Pure stdlib + `requests`. No pandas, no numpy, no scipy — the whole book runs
on a bare Python 3.9+.

## The HIP-3 trap

Builder-deployed perps do **not** continue the core perp asset index space:

```
core perps    0 .. n
spot          10000 + index
builder perps 110000 + i*10000 + index      # i enumerates perpDexs()[1:]
```

An order built on the naive assumption points at an entirely different market
**and still fills**. `lab/hl.py` resolves this from `perpDexs()`, and the
self-test pins the arithmetic. Bare market names that exist on more than one
loaded dex raise rather than resolve to a coin flip — qualify them as
`dex:NAME`.

Two more encoded there: perp prices must satisfy **both** the 5-significant-
figure rule and the `(6 − szDecimals)` decimal rule (integers are exempt from
the first), and `clearinghouseState` / `allMids` / `meta` are all per-dex —
margin does not automatically pool across HIP-3 dexs.

## Doctrine (do not relax silently)

Ported from `SYSTEM.md`, because the failure modes are the same ones:

- **No lookahead, ever.** The hedge ratio and z-score for bar *t* are refit on
  the trailing window ending at *t*. In-sample beta is the stat-arb equivalent
  of fitting a filter to its own backtest: a beautiful curve and no money.
- **Stability over headline fit.** A pair must stay mean-reverting in *every*
  sub-window (`min_stability: 0.75`), the direct analogue of the SHIELD bar
  that a leg must improve in every week with n≥80. Full-window-only
  cointegration is one regime, not a relationship — and it breaks exactly when
  leverage makes it expensive.
- **Cost-aware entry.** Round trip is 4× the per-leg cost (2 legs × in+out),
  ~30bps at defaults. `min_sigma_bps: 40` exists because a spread whose entire
  standard deviation is 40bps cannot pay 30bps and still be worth the margin.
- **`|z| ≥ stop_z` at entry is a refusal, not an opportunity.** A spread that
  far out is more often a corporate action, an index rebalance, or a broken
  relationship than a rich spread. This is the fat-left-tail guard.
- **A halt blocks new risk only.** Closing an open pair is always permitted. A
  kill switch that also blocks the exit is not a kill switch.
- **Both legs in one batch.** Legging in one order at a time leaves the book
  outright directional between fills — the one exposure this strategy exists
  to avoid. Correctness requirement, not an optimisation.
- **Backtest all five terms or none.** A spread-only backtest measures a
  quarter of the strategy, and always the flattering quarter.

## Status: CANDIDATE — nothing here is live-validated

The engine, the math, and the safety gates are tested. **The parameters are
not.** Every number in `pairs.yaml` is a prior, never fitted to real HIP-3
equity data — that data was not reachable from the environment this was built
in (`api.hyperliquid.xyz` is egress-blocked there).

`lab/test_pairs.py` verifies the machinery against synthetic worlds with known
answers: OLS recovers a planted slope, half-life recovers a planted AR(1)
target (19.8 vs 20.0), P&L attribution reconciles to the equity change to the
cent, and — the check that actually matters — **the screen rejects two
independent random walks and the backtester takes zero trades on them.** Any
pairs engine makes money on a cointegrated pair; in a real universe most pairs
are random walks, and the screen is the only thing between you and trading
them.

## Promotion ladder

Same shape as the Solana loop. Do not skip a rung.

1. **Discover** — `pairs_run.py markets --dex <name>` to find the equity dex
   and confirm asset indices resolve.
2. **Screen** — `pairs_run.py scan --dex <name> --days 90`. If nothing passes,
   that is a result. Do not relax the bars to manufacture candidates.
3. **Backtest** — `pairs_run.py backtest --pair A,B --days 90 --trades` on
   real data. Read the *attribution line*, not the headline return: a book
   whose profit is all yield is a savings account with liquidation risk, and
   one whose profit is all spread does not need Ethena at all.
4. **Carry check** — re-run `carry` with the pair's *actual* funding rates.
   If net carry is negative at your chosen leverage, either lower leverage or
   drop the pair.
5. **Paper** — `pairs_run.py trade --pair A,B` (dry-run) on a live schedule.
   Confirm the emitted sizes, prices, and asset indices are what you expect
   before any capital moves.
6. **Size** — `--live` plus `HL_ALLOW_LIVE=1`, starting at a fraction of
   target. Log the deployed config and its prediction here, the way
   `alerts.yaml` logs filter deployments.

## Known gaps, stated plainly

- **Session-awareness is the largest modelling gap.** Equity perps trade ~24/7
  but the underlying only prices during the cash session; overnight bars are
  stale-underlying and the spread mean-reverts differently across the session
  boundary. The Sharpe annualiser uses 6552 rather than 8760 to acknowledge
  this, but a session-aware bar filter is **not implemented**.
- **Corporate actions** put step changes in the spread that look identical to
  a rich entry. `stop_z` refusal is a blunt proxy; a real feed is the fix.
- **HIP-3 oracle risk is deployer risk** — mark price depends on a
  deployer-delegated oracle and the deployer can halt trading. Per-dex
  position limits are not yet enforced in code.
- **Funding** is the trailing hourly rate snapped to each bar; predicted
  funding is unused.
- **`YieldCurve` accepts a time series** of sUSDe APY so a backtest can pay
  the yield that actually existed. Nobody has fed it one yet — it currently
  runs constant, and it says so (`[CONSTANT ASSUMPTION]`).

## Quick start

```bash
python3 lab/test_pairs.py                      # 63 checks, offline, no deps
python3 lab/pairs_run.py carry --apy 0.09      # leverage/carry tradeoff
python3 lab/pairs_run.py markets --dex <equity-dex>
python3 lab/pairs_run.py scan    --dex <equity-dex> --days 90
python3 lab/pairs_run.py backtest --pair AAPL,MSFT --dex <equity-dex> --trades
python3 lab/pairs_run.py trade   --pair AAPL,MSFT --dex <equity-dex>   # dry-run
```

Live trading requires **both** `--live` and `HL_ALLOW_LIVE=1`, plus
`HL_SECRET_KEY` (API wallet) and `pip install hyperliquid-python-sdk`.
