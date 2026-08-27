# Parameter Exploration Ledger

Status of every DRBT filter parameter and mechanism across the project.
Full evidence for each entry lives in alerts.yaml commit history.

## Deployed as filter legs
mc (zone bands) | buy_volume_1m (floors+ceilings, moderate-burst law) |
buy_volume_1h (quiet caps) | lp_sol (floors, whale>90, HB2T 60-100) |
lp_ratio (THE decoupling law, 4-universe) | buyers (early-crowd bands) |
sellers (+whale exemption) | sellers/buyers (scarcity) | buys>sells |
buys/buyers churn cap | rugcheck_score (NULL-safe) | fresh_holding_pct |
launch_bundle_pct (caps; 3-10 skin window; dust tell) |
max_launch_bundle_pct | max_tip + sell/buy volume (organic-flow OR) |
max_bundle_sol | top_source | owner_age | med_makers (>88 crowd, <17 HB2T
inversion) | mc_d1 (fresh guard) | updated_slot-created_slot (freshness) |
mayhem | prev_slot_mc & ath_mc (IGNITION CONFIRMATION - post-entry) |
kol() toxic exclusion (22659, 8318, 82, 1788 - zero-cost)

## Sizing / manual signals (validated, not legs)
owner_balance>5 (rate streams) | elite-KOL set {30240,32843,10233,196,
1818,83,69,4912,13399,14071,92} | whale-branch flag | bundle 3-10 size-up |
name case (lowercase > ALL-CAPS, ~9pp) | meta-alignment (cat season) |
dexscreener, origin_cex (mild)

## Tested and rejected (reasons in alerts.yaml)
dev_sold | origin_balance>1 (as universal) | med_makers>=1600 |
ath-breakout entry leg | kol_buyers>=1 hard | dev_migrated/dev_deploys
caps | buyers<120 | uri_count/image_hash_count | total_supply |
bonding_progress hard | network_fees | cnt_from_cex | cnt_new |
name word-blocklist | emoji | program_ids_count global | tweet_* |
launch_mc/lp_sol_launch global (archetype-inverted) | dist_prio
(unofficial param)

## Unexplored / blocked / queued
ca()/ca_score (99% NULL) | tracked_count (QUEUED: find_apes pipeline on
8 confirmed monsters) | blacklist_count | sol_price regime (sizing-layer)
| decimals | tip/prio medians | symbol LIKE | time-of-day (inexpressible)
| set_buy_formula (tier sizing) | sell system (exits - THE open item) |
set_filter_wallet_subset | set_mooners_query
