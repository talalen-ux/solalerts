# DRBT Filter Parameters (official)

Source: `filter_parameters_4.xlsx` exported from DRBT (2026-08-18). 74 parameters.
Cross-column arithmetic is allowed in conditions (e.g. `mc > mc_1h * 2`).
Nullable booleans: use `IS NOT TRUE` instead of `= false` to include NULLs.

## Market Cap

| Parameter | Type | Description | Example |
|---|---|---|---|
| `mc` | int | Current market cap in USD | `mc > 50000` |
| `ath_mc` | int | All-time high market cap | `ath_mc > 100000` |
| `launch_mc` | int | Market cap at launch | `launch_mc < 10000` |
| `mc_1h` | int | Market cap 1 hour ago | `mc > mc_1h * 2` |
| `mc_d1` | int | Market cap 1 day ago | `mc > mc_d1` |
| `prev_slot_mc` | int | Market cap in previous slot | `mc > prev_slot_mc` |
| `sol_price` | float | SOL price in USD at snapshot time | `sol_price > 100` |
| `sol_price_24h` | float | SOL 24h price change percentage | `sol_price_24h < -5` |

## Liquidity

| Parameter | Type | Description | Example |
|---|---|---|---|
| `lp_sol` | float | Liquidity pool SOL amount | `lp_sol > 5` |
| `lp_sol_launch` | float | LP SOL at launch | `lp_sol_launch > 10` |
| `lp_ratio` | float | LP ratio | `lp_ratio > 0.1` |

## Volume

| Parameter | Type | Description | Example |
|---|---|---|---|
| `buy_volume` | int | Total buy volume | `buy_volume > 10000` |
| `sell_volume` | int | Total sell volume | `sell_volume < buy_volume` |
| `buy_volume_1m` | int | Buy volume in last 1 minute | `buy_volume_1m > 1000` |
| `buy_volume_1h` | int | Buy volume in last 1 hour | `buy_volume_1h > 5000` |
| `max_bundle_sol` | float | Maximum SOL spent in a single slot buy bundle | `max_bundle_sol > 10` |

## Activity

| Parameter | Type | Description | Example |
|---|---|---|---|
| `buys` | int | Number of buy transactions | `buys > 10` |
| `sells` | int | Number of sell transactions | `sells < buys` |
| `buyers` | int | Number of unique buyers | `buyers > 5` |
| `sellers` | int | Number of unique sellers | `sellers < buyers` |
| `cnt_distinct_makers` | int | Count of distinct maker positions | `cnt_distinct_makers > 10` |
| `med_makers` | float | Median maker count (median number of positions held by buyers) | `med_makers > 5` |

## KOL

| Parameter | Type | Description | Example |
|---|---|---|---|
| `kol()` | function | Check if token was bought by specific KOL(s). Multiple IDs = any match. Use AND for requiring all: kol(5) AND kol(12) | `kol(55) or kol(55, 4, 60)` |
| `kol_buyers` | int | Number of KOL buyers | `kol_buyers >= 1` |
| `kol_holders` | int | Number of KOL holders | `kol_holders >= 2` |
| `avg_kol_median_xs` | float | Average KOL median multiplier | `avg_kol_median_xs > 5` |
| `ca_score` | int | Call Analyser score | `ca_score >= 5` |
| `ca()` | function | Check if token was called by specific caller(s). Multiple IDs = any match. Use AND for requiring all: ca(5) AND ca(12) | `ca(55) or ca(55, 4, 60)` |

## Wallets

| Parameter | Type | Description | Example |
|---|---|---|---|
| `tracked_count` | int | Your tracked wallets holding this token | `tracked_count > 0` |
| `blacklist_count` | int | Number of your blacklisted wallets that bought/hold this token | `blacklist_count = 0` |
| `cnt_new` | int | Number of fresh wallets | `cnt_new > 5` |
| `fresh_holding_pct` | float | Percentage of tokens held by fresh wallets (0-100) | `fresh_holding_pct < 50` |
| `launch_bundle_pct` | float | Percentage of supply held by wallets that bought in the first slot (0-100) | `launch_bundle_pct < 30` |
| `max_launch_bundle_pct` | float | Historical maximum percentage of supply held by wallets that bought in the first slot (never decreases) | `max_launch_bundle_pct > 20` |

## Token

| Parameter | Type | Description | Example |
|---|---|---|---|
| `symbol` | text | Token symbol | `symbol LIKE '%PEPE%'` |
| `name` | text | Token name | `name IS NOT NULL` |
| `decimals` | int | Token decimals | `decimals = 6` |
| `total_supply` | bigint | Total token supply | `total_supply < 1000000000` |
| `uri_count` | int | Number of tokens sharing the same metadata URI (detects reused metadata) | `uri_count = 1` |
| `image_hash_count` | int | Number of tokens sharing the same image hash (detects reused images) | `image_hash_count = 1` |

## Platform

| Parameter | Type | Description | Example |
|---|---|---|---|
| `pumpfun` | bool | Is original pump.fun token | `pumpfun = true (nullable — use IS NOT TRUE instead of = false)` |
| `dexscreener` | bool | Is on DexScreener | `dexscreener = true (nullable — use IS NOT TRUE instead of = false)` |
| `bonding_progress` | float | Bonding curve progress (0-100) | `bonding_progress > 0.5` |
| `dex_is_cto` | bool | Is DexScreener CTO (Community Takeover) | `dex_is_cto = true (nullable — use IS NOT TRUE instead of = false)` |
| `dex_ads` | int | DexScreener ads count | `dex_ads > 0` |
| `dex_boost` | int | DexScreener boost amount | `dex_boost > 100` |
| `program_ids_max` | float | Maximum program interaction count in a single transaction | `program_ids_max < 20` |
| `program_ids_stddev` | float | Standard deviation of program interaction counts across transactions | `program_ids_stddev < 5` |
| `top_source` | int | Max number of makers with same origin of funds | `top_source = 1` |

## Risk

| Parameter | Type | Description | Example |
|---|---|---|---|
| `rugcheck_score` | int | Rugcheck safety score (lower = safer) | `rugcheck_score < 500` |
| `program_ids_count` | int | Number of program IDs | `program_ids_count < 5` |
| `dev_sold` | bool | Developer has sold tokens | `dev_sold IS NOT TRUE (use IS NOT TRUE instead of = false to include NULLs)` |
| `mayhem` | bool | Token launched in pump.fun Mayhem mode | `mayhem IS NOT TRUE (use IS NOT TRUE instead of = false to include NULLs)` |

## Timing

| Parameter | Type | Description | Example |
|---|---|---|---|
| `created_slot` | int | Slot when token was created | `created_slot > 300000000` |
| `launched_slot` | int | Slot when token launched | `launched_slot IS NOT NULL` |
| `updated_slot` | int | Last update slot | `updated_slot > created_slot + 1000` |
| `migration_slot` | int | Slot when token migrated | `migration_slot IS NOT NULL` |
| `ath_slot` | int | Slot when ATH was reached | `ath_slot > launched_slot` |

## Fees

| Parameter | Type | Description | Example |
|---|---|---|---|
| `max_tip` | float | Maximum Jito tip | `max_tip < 0.1` |
| `med_tip` | float | Median Jito tip | `med_tip < 0.05` |
| `max_prio` | float | Maximum priority fee | `max_prio < 1000000` |
| `med_prio` | float | Median priority fee | `med_prio < 500000` |
| `network_fees` | float | Network fees paid in SOL | `network_fees > 0.01` |

## CEX

| Parameter | Type | Description | Example |
|---|---|---|---|
| `cnt_from_cex` | int | Transactions from CEX wallets | `cnt_from_cex > 0` |

## Owner/Origin

| Parameter | Type | Description | Example |
|---|---|---|---|
| `owner_age` | int | Owner wallet age in seconds since first tx | `owner_age > 86400` |
| `owner_tx` | int | Owner wallet transaction count | `owner_tx > 100` |
| `owner_balance` | float | Owner wallet SOL balance | `owner_balance > 1` |
| `origin` | string | Origin wallet address (first funder) | `origin IS NOT NULL` |
| `origin_tx` | int | Origin wallet transaction count | `origin_tx > 50` |
| `origin_balance` | float | Origin wallet SOL balance | `origin_balance > 10` |
| `origin_cex` | bool | True if origin is a CEX address | `origin_cex = true (nullable — use IS NOT TRUE instead of = false)` |
| `origin_cex_name` | string | CEX name if origin is from exchange | `origin_cex_name = 'Binance'` |
| `dev_deploys` | int | Count of previous tokens by same owner | `dev_deploys >= 3` |
| `dev_migrated` | int | Count of owner tokens that migrated | `dev_migrated >= 1` |
