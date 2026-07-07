# Custom parameter schema — Solana token alerts

Original parameters designed for one job: predicting market-cap growth
*before* it happens, on Solana. Organized by category. Each entry:
`name` | type | description | example filter.

Conventions:
- All percentages are 0–100.
- All SOL amounts are floats, USD amounts are floats.
- `*_z` suffix = z-score vs the token's own trailing baseline (how unusual is
  this right now, normalized). Z-scores make thresholds portable across
  mcap sizes — `vol_1m_z > 4` works for a $50k token and a $5M token.
- Nullable booleans: filter with `IS NOT TRUE` to fail-open on unknowns.

---

## 1. Holder quality (who owns this, and are they any good?)

| name | type | description | example |
|---|---|---|---|
| `pnl_wallets_pct` | float | % of current supply held by wallets that are historically profitable (lifetime realized PnL > 0 across all tokens) | `pnl_wallets_pct > 30` |
| `diamond_score` | float | Median hold-duration percentile of current holders vs their own history — do these wallets usually hold or flip? | `diamond_score > 60` |
| `winner_density` | float | % of holders whose median past trade returned > 2x | `winner_density > 15` |
| `bagholder_pct` | float | % of supply held by wallets whose historical win rate < 20% (exit-liquidity crowd) | `bagholder_pct < 40` |
| `holder_retention_1h` | float | % of wallets holding 1h ago that still hold now | `holder_retention_1h > 80` |
| `avg_entry_mc` | float | Supply-weighted average market cap at which current holders bought | `mc < avg_entry_mc * 3` |
| `underwater_pct` | float | % of supply currently held at a loss (unrealized). High = overhead resistance from break-even sellers | `underwater_pct < 30` |
| `gini` | float | Gini coefficient of holder distribution (0 = perfectly even, 1 = one wallet owns all) | `gini < 0.85` |
| `top10_pct` | float | % of supply held by top 10 non-LP, non-CEX wallets | `top10_pct < 25` |
| `median_position_usd` | float | Median holder position size in USD — distinguishes real holders from dust airdrops | `median_position_usd > 50` |

## 2. Wallet graph forensics (is this one actor pretending to be many?)

| name | type | description | example |
|---|---|---|---|
| `sybil_cluster_pct` | float | % of supply held by wallets linked into funding clusters (shared origin ≤ 2 hops) | `sybil_cluster_pct < 20` |
| `largest_cluster_wallets` | int | Wallet count of the single largest funding cluster among holders | `largest_cluster_wallets < 10` |
| `wash_score` | float | 0–100 estimate of volume that is circular (A→B→A within short windows, same-cluster self-trades) | `wash_score < 20` |
| `organic_volume_1h` | float | 1h volume in USD after subtracting wash-flagged trades — the number `h1Buy` pretends to be | `organic_volume_1h > 10000` |
| `funding_entropy` | float | Shannon entropy of buyer funding sources. Low = everyone funded from one place (bundle); high = genuinely diverse crowd | `funding_entropy > 2.5` |
| `relay_wallet_pct` | float | % of buyers that are pass-through wallets (funded < 10 min before buying, no other history) | `relay_wallet_pct < 30` |
| `dev_linked_pct` | float | % of supply held by wallets within 2 funding hops of the deployer | `dev_linked_pct < 10` |

## 3. Smart-money flow (what are proven winners doing *right now*?)

| name | type | description | example |
|---|---|---|---|
| `smart_net_flow_5m` | float | Net USD flow (buys − sells) from top-decile-PnL wallets, last 5 min | `smart_net_flow_5m > 1000` |
| `smart_net_flow_1h` | float | Same, 1 hour window | `smart_net_flow_1h > 0` |
| `smart_first_pct` | float | % of the first 100 buyers that are top-decile-PnL wallets — smart money early is the tell | `smart_first_pct > 5` |
| `smart_avg_entry_mc` | float | Average mcap at which smart wallets entered — are you buying near their basis or 10x above it? | `mc < smart_avg_entry_mc * 2` |
| `smart_exit_pct` | float | % of smart-money positions already fully closed. High = the trade is over | `smart_exit_pct < 30` |
| `copytrade_lag_score` | float | 0–100: how much current buying is copy-bots trailing smart wallets (high = move already crowded) | `copytrade_lag_score < 60` |
| `whale_bid_depth` | float | USD of resting intent from wallets > $100k wealth: repeat-buy patterns + DCA behavior detected on this token | `whale_bid_depth > 5000` |

## 4. Flow acceleration (momentum, but normalized)

| name | type | description | example |
|---|---|---|---|
| `vol_1m_z` | float | 1-minute volume z-score vs token's trailing 1h baseline | `vol_1m_z > 4` |
| `buyer_accel` | float | Unique-buyer growth rate: (buyers last 5m) / (buyers per 5m avg over last 1h) | `buyer_accel > 3` |
| `net_flow_slope_15m` | float | Linear-regression slope of cumulative net flow (USD/min) over 15 min — sustained pressure, not one candle | `net_flow_slope_15m > 0` |
| `buy_size_median_1m` | float | Median buy size (USD) last minute. Rising median = conviction sizing up, not dust spam | `buy_size_median_1m > 100` |
| `new_holder_rate_5m` | int | Net new holders in 5 min (joins − full exits) | `new_holder_rate_5m > 20` |
| `reentry_count_1h` | int | Wallets that previously sold this token and are buying back in, last hour — strongest reversal signal there is | `reentry_count_1h > 5` |
| `sell_absorption` | float | Ratio of price impact per $1k sold now vs 1h ago. < 1 means the book got thicker: sells are being absorbed | `sell_absorption < 0.7` |

## 5. Liquidity & microstructure

| name | type | description | example |
|---|---|---|---|
| `depth_2pct_usd` | float | USD needed to move price 2% (buy side) | `depth_2pct_usd > 3000` |
| `lp_net_change_1h` | float | Net LP change last hour in SOL (adds − removes). Negative while price pumps = distribution setup | `lp_net_change_1h >= 0` |
| `lp_burned_or_locked` | bool | LP tokens verifiably burned or locked (nullable) | `lp_burned_or_locked = true` |
| `mcap_liq_ratio` | float | Market cap / pool liquidity USD. Very high = thin exit; very low = dead | `mcap_liq_ratio < 40` |
| `pool_count` | int | Number of active pools (Raydium/Orca/Meteora). > 1 = third parties committing capital | `pool_count >= 1` |
| `price_impact_asym` | float | Sell-side impact / buy-side impact for equal size. > 1.5 = one-way-door pool geometry | `price_impact_asym < 1.5` |
| `route_health` | float | 0–100: is the token routable via Jupiter aggregator with sane slippage at $1k size? | `route_health > 80` |

## 6. Deployer & provenance

| name | type | description | example |
|---|---|---|---|
| `dev_track_xs` | float | Median ATH multiple across this deployer's previous tokens | `dev_track_xs > 2` |
| `dev_rug_count` | int | Deployer's prior tokens that hit rug criteria (LP pull, dev dump > 50%, mint abuse) | `dev_rug_count = 0` |
| `dev_hold_pct` | float | % of supply the deployer cluster currently holds | `dev_hold_pct < 5` |
| `dev_sold_pct` | float | % of the dev's original allocation already sold (graded, not just boolean) | `dev_sold_pct < 20` |
| `authority_clean` | bool | Mint authority AND freeze authority both revoked | `authority_clean = true` |
| `metadata_mutable` | bool | Token metadata still mutable (rug-adjacent) | `metadata_mutable IS NOT TRUE` |
| `deployer_age_days` | float | Age of deployer wallet in days | `deployer_age_days > 7` |
| `launch_stealth_score` | float | 0–100: launch had no pre-mine, no insider slot-0 bundle, organic first 50 buys | `launch_stealth_score > 70` |

## 7. Attention & social (measured on-chain-adjacent, decay-weighted)

| name | type | description | example |
|---|---|---|---|
| `mention_velocity_z` | float | Z-score of social mention rate (X/Telegram) vs token's trailing baseline | `mention_velocity_z > 3` |
| `kol_reach_wtd` | float | Follower-weighted sum of KOLs who bought AND still hold (holdings decay the weight to zero on exit) | `kol_reach_wtd > 100000` |
| `kol_conviction` | float | Median % of their typical position size that KOL buyers deployed here — a KOL max-sizing beats ten KOLs lotto-sizing | `kol_conviction > 50` |
| `caller_hit_rate` | float | Historical win rate (>2x within 24h) of the specific channels calling this token now | `caller_hit_rate > 30` |
| `attention_flow_gap` | float | Mention velocity percentile − volume percentile. Positive gap = attention arriving faster than buys (front-run the flow) | `attention_flow_gap > 20` |
| `narrative_match` | bool | Token maps to a currently-hot cluster (semantic match vs top movers' metadata last 48h) | `narrative_match = true` |

## 8. Lifecycle & regime context

| name | type | description | example |
|---|---|---|---|
| `age_minutes` | int | Minutes since first pool | `age_minutes > 30` |
| `drawdown_pct` | float | % below ATH mcap | `drawdown_pct < 70` |
| `ath_headroom` | float | mc / ath_mc. < 1.1 avoids blow-off wicks (same idea as alpha_ignition) | `ath_headroom < 1.1` |
| `base_duration_min` | int | Minutes price has consolidated within ±15% band — length of the base before breakout | `base_duration_min > 20` |
| `higher_lows_count` | int | Consecutive higher lows on 5m candles | `higher_lows_count >= 3` |
| `survival_score` | float | 0–100: P(token alive in 24h) from a survival model over age, liquidity, holder retention | `survival_score > 60` |
| `sol_regime` | float | Market-wide risk appetite: net SOL flowing into memecoin pools last 4h, z-scored. Alerts fire looser in risk-on | `sol_regime > 0` |
| `cohort_perf_24h` | float | Median 24h return of tokens launched the same hour — is this cohort catching bids at all? | `cohort_perf_24h > 0` |

---

## Composite scores (derived, 0–100 each)

- `SAFETY = f(dev_rug_count, authority_clean, sybil_cluster_pct, wash_score, lp_burned_or_locked, dev_hold_pct, price_impact_asym)`
- `SMART = f(smart_net_flow_5m, smart_first_pct, smart_exit_pct, pnl_wallets_pct, winner_density)`
- `MOMENTUM = f(vol_1m_z, buyer_accel, net_flow_slope_15m, new_holder_rate_5m, sell_absorption)`
- `ATTENTION = f(mention_velocity_z, kol_reach_wtd, kol_conviction, caller_hit_rate, attention_flow_gap)`

### Flagship filter using this schema

```
SAFETY > 70
  AND authority_clean = true
  AND dev_rug_count = 0
  AND wash_score < 20
  AND sybil_cluster_pct < 20
  AND smart_net_flow_5m > 1000
  AND smart_exit_pct < 30
  AND vol_1m_z > 4
  AND buyer_accel > 3
  AND holder_retention_1h > 80
  AND reentry_count_1h > 3
  AND underwater_pct < 30
  AND ath_headroom < 1.1
  AND attention_flow_gap > 0
  AND sol_regime > 0
```

Reading: safe structure, smart money net-buying and not yet exiting, volume
and buyer count abnormally high *for this token*, existing holders staying
put, sellers who left are coming back, few trapped bagholders overhead,
not a blow-off wick, attention still outrunning price, and the whole memecoin
market is catching bids. Every leg is independent — that's what makes the
conjunction rare and high-precision.
